"""Overnight hold for MES (Simulation forward test).

Rule tested in research/overnight.py (SPY 1993-2026 and MES 2024-2026):
    at ~15:55 ET, if the price is above its 200-day average of daily closes -> BUY 1
    at 09:30 ET the next trading day                                        -> SELL (flatten)

Runs inside the trading thread (it drives Playwright), called from the web_app heartbeat about
once a second. It does nothing unless OVERNIGHT_ENABLED=1. Settings (.env):
    OVERNIGHT_ENABLED=1
    OVERNIGHT_DRY_RUN=1          log + Telegram what it WOULD do, place no orders (start with this)
    OVERNIGHT_ENTRY_ET=15:55     entry window: this time until 16:00 ET
    OVERNIGHT_EXIT_ET=09:30      exit at/after this time
    OVERNIGHT_ALERT_ET=09:35     urgent alert if still holding at this time
    OVERNIGHT_SMA_DAYS=200
Daily closes live in data/overnight_closes.csv (seeded from history; the bot adds one row per day
at entry time). State survives restarts in data/overnight_state.json.
"""
import csv
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MAX_EXIT_ATTEMPTS = 3
RETRY_SECONDS = 30


def _flag(name):
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


class OvernightHold:
    def __init__(self, bot, notify, logger,
                 closes_path=os.path.join("data", "overnight_closes.csv"),
                 state_path=os.path.join("data", "overnight_state.json")):
        self.bot, self.notify, self.log = bot, notify, logger
        self.enabled = _flag("OVERNIGHT_ENABLED")
        self.dry_run = _flag("OVERNIGHT_DRY_RUN")
        self.entry_at = os.getenv("OVERNIGHT_ENTRY_ET", "15:55").strip()
        self.exit_at = os.getenv("OVERNIGHT_EXIT_ET", "09:30").strip()
        self.alert_at = os.getenv("OVERNIGHT_ALERT_ET", "09:35").strip()
        self.sma_days = int(os.getenv("OVERNIGHT_SMA_DAYS", "200"))
        self.expected_account = os.getenv("EXPECTED_ACCOUNT", "").strip()
        self.closes_path, self.state_path = closes_path, state_path
        self.state = {"entry_date": None, "exit_date": None, "holding": False, "entry_px": None,
                      "exit_attempts": 0, "next_try": 0.0, "notified": {}}
        self._load_state()
        if self.enabled:
            self.log.warning("OVERNIGHT: enabled (dry_run=%s) entry %s ET, exit %s ET, SMA %d",
                             self.dry_run, self.entry_at, self.exit_at, self.sma_days)

    # ------------------------------------------------------------------ persistence
    def _load_state(self):
        try:
            with open(self.state_path) as fh:
                self.state.update(json.load(fh))
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log.warning("OVERNIGHT: could not read state (%s) - starting fresh", e)

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w") as fh:
            json.dump(self.state, fh, indent=2, default=str)

    def closes(self):
        try:
            with open(self.closes_path) as fh:
                return [(r["date"], float(r["close"])) for r in csv.DictReader(fh)]
        except FileNotFoundError:
            return []

    def _record_close(self, date_str, px):
        rows = [r for r in self.closes() if r[0] != date_str] + [(date_str, float(px))]
        rows.sort()
        os.makedirs(os.path.dirname(self.closes_path) or ".", exist_ok=True)
        with open(self.closes_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "close"])
            w.writerows(rows)

    def sma(self):
        c = [px for _, px in self.closes()]
        return sum(c[-self.sma_days:]) / self.sma_days if len(c) >= self.sma_days else None

    # ------------------------------------------------------------------ helpers
    def _once(self, key, text):
        """Telegram + log a message at most once per key per day."""
        today = datetime.now(ET).date().isoformat()
        if self.state["notified"].get(key) == today:
            return
        self.state["notified"][key] = today
        self.log.warning("OVERNIGHT: %s", text)
        self.notify(text)
        self._save_state()

    def _symbol(self):
        return (getattr(self.bot, "symbol", None) or "MES").upper()

    def _broker_qty(self, api):
        """Net quantity from Tradovate's positions table; None if it cannot be read."""
        rows = api.get_positions(root_symbol=self._symbol())
        if rows is None:
            return None
        return sum(int(r.get("qty") or 0) for r in rows)

    def status(self):
        c = self.closes()
        return {"enabled": self.enabled, "dry_run": self.dry_run, "entry_at": self.entry_at,
                "exit_at": self.exit_at, "sma_days": self.sma_days, "closes_on_file": len(c),
                "last_close": c[-1] if c else None,
                "sma": round(self.sma(), 2) if self.sma() else None, **self.state}

    # ------------------------------------------------------------------ main hook
    def tick(self, api, connected, flatten):
        if not self.enabled:
            return
        now = datetime.now(ET)
        if now.weekday() >= 5:
            return
        hhmm, today = now.strftime("%H:%M"), now.date().isoformat()
        if self.exit_at <= hhmm < self.entry_at and self.state.get("exit_date") != today:
            self._exit(api, connected, flatten, today, hhmm)
        if self.entry_at <= hhmm < "16:00" and self.state.get("entry_date") != today:
            self._enter(api, connected, today)

    # ------------------------------------------------------------------ exit (09:30)
    def _exit(self, api, connected, flatten, today, hhmm):
        if not connected or api is None:
            if hhmm >= self.alert_at:
                self._once("exit_disconnected", "🚨 Overnight EXIT: bot not connected to Tradovate - "
                                                "log in and check the position NOW.")
            return
        if self.state.get("exit_try_date") != today:          # new day (e.g. after a holiday): fresh attempts
            self.state.update(exit_try_date=today, exit_attempts=0, next_try=0.0)
        if time.time() < self.state.get("next_try", 0.0):
            return
        qty = self._broker_qty(api)
        if qty is None:
            self.state["next_try"] = time.time() + RETRY_SECONDS
            if hhmm >= self.alert_at:
                self._once("exit_unknown", "🚨 Overnight EXIT: cannot read Tradovate positions - check NOW.")
            return
        if qty == 0:
            if self.state.get("holding"):
                self._once("exit_already_flat", "Overnight EXIT: already flat at the open (closed elsewhere?).")
            self.state.update(exit_date=today, holding=False, exit_attempts=0)
            self._save_state()
            return
        if self.dry_run:
            self._once("exit_dry", f"DRY RUN: would SELL {qty} {self._symbol()} at the open.")
            self.state.update(exit_date=today)
            self._save_state()
            return
        if self.state.get("exit_attempts", 0) >= MAX_EXIT_ATTEMPTS:
            self._once("exit_gave_up", f"🚨 Overnight EXIT FAILED {MAX_EXIT_ATTEMPTS} times - still holding "
                                       f"{qty}. Close it in Tradovate NOW.")
            return
        self.state["exit_attempts"] = self.state.get("exit_attempts", 0) + 1
        px_before = api.get_current_price(self._symbol())
        res = flatten("overnight_exit")
        if res.get("success"):
            pts = (px_before - self.state["entry_px"]) if (px_before and self.state.get("entry_px")) else None
            self.state.update(exit_date=today, holding=False, exit_attempts=0)
            self._save_state()
            self._once("exit_done", "✅ Overnight EXIT done, flat." +
                       (f" Approx {pts:+.2f} pts (${pts * 5 - 3.74:+.2f} after costs)." if pts is not None else ""))
        else:
            self.state["next_try"] = time.time() + RETRY_SECONDS
            self._save_state()
            self.log.error("OVERNIGHT: exit attempt %d not confirmed (%s)", self.state["exit_attempts"],
                           res.get("message"))
            if hhmm >= self.alert_at:
                self._once("exit_late", f"🚨 Still holding after {self.alert_at} ET - exit not confirmed. Check Tradovate.")

    # ------------------------------------------------------------------ entry (15:55)
    def _enter(self, api, connected, today):
        sym = self._symbol()

        def skip(reason, alert=False):
            self.state["entry_date"] = today
            self._save_state()
            self._once("entry_skip", ("⚠️ " if alert else "") + f"Overnight: no position tonight - {reason}")

        if not connected or api is None:
            self._once("entry_disconnected", "⚠️ Overnight ENTRY: bot not connected to Tradovate (will keep trying until 16:00 ET).")
            return
        if self.bot.entries_blocked():
            return skip("entries are blocked (bot paused, or FLATTEN_AT_ET is set - leave it empty in overnight mode)", True)
        if self.expected_account:
            label = api.get_account_label()
            if label != self.expected_account:
                return skip(f"wrong Tradovate account selected ({label or 'unknown'}, expected {self.expected_account})", True)
        px = api.get_current_price(sym)
        if not px:
            return                                           # retry next second until 16:00
        self._record_close(today, px)
        avg = self.sma()
        if avg is None:
            return skip(f"fewer than {self.sma_days} daily closes on file", True)
        if px <= avg:
            return skip(f"price {px:.2f} is below its {self.sma_days}-day average {avg:.2f}")
        qty = self._broker_qty(api)
        if qty is None:
            return skip("cannot read Tradovate positions", True)
        if qty != 0:
            return skip(f"a position is already open ({qty})", True)
        if self.dry_run:
            self.state.update(entry_date=today)
            self._save_state()
            return self._once("entry_dry", f"DRY RUN: would BUY 1 {sym} at {px:.2f} (200-day avg {avg:.2f}).")

        for prep in ("ensure_symbol_loaded", "ensure_trading_panels_ready"):
            try:
                fn = getattr(api, prep, None)
                if fn:
                    fn(sym) if prep == "ensure_symbol_loaded" else fn(timeout_ms=12000)
            except Exception as e:
                self.log.warning("OVERNIGHT: %s failed (non-fatal): %s", prep, e)

        signal = {"type": "BUY", "symbol": sym, "reason": "overnight_entry", "strategy_name": "OvernightHold",
                  "_signal_id": f"overnight_{today}"}
        self.state["entry_date"] = today                    # one attempt per day: never double up
        self._save_state()
        ok = self.bot._execute_trade(signal, 1, px)
        time.sleep(3.0)
        held = self._broker_qty(api)
        if held and held > 0:
            self.bot._entry_strategy[sym] = "OvernightHold"
            self.state.update(holding=True, entry_px=float(px), exit_attempts=0, next_try=0.0)
            self._save_state()
            self._once("entry_done", f"🌙 Overnight ENTRY: bought 1 {sym} ~{px:.2f} (200-day avg {avg:.2f}). "
                                     f"Exit at {self.exit_at} ET.")
        else:
            self._once("entry_failed", f"⚠️ Overnight ENTRY not confirmed (order result={ok}, broker qty={held}). "
                                       "Check Tradovate.")
