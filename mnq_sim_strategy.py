"""
Live paper/dry adapter for the mnq_sim package.

Reuses the SAME VwapEngine / SetupClassifier / Gate that run_mnq_backtest.py
validated — no logic fork: what you backtested is what runs here.

DRY MODE (default): check_signal() ALWAYS returns None, so the bot never places
an MNQ order. Every gate-passed signal for an enabled setup is simulated
internally bar-by-bar (same bracket model as the backtest) and written to
data/mnq_paper/paper_trades.csv for forward walk-forward evidence.

LIVE MODE (dry=False): the internal sim is disabled; gate-passed signals are
returned to the bot for real execution and record_trade_result() feeds PnL back
into the session risk state.

Start with enabled_setups={"D"} — prove one setup at a time (Part 15).
"""

from __future__ import annotations

import os
import csv
import time
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from mnq_sim.types import Bar, Side, SessionLevels, POINT_VALUE
from mnq_sim.vwap import VwapEngine
from mnq_sim.classifier import SetupClassifier
from mnq_sim.gate import Gate, SessionRiskState, _structural_stop
from mnq_sim.profile import compute_profile

ET = ZoneInfo("America/New_York")
HARD_FLAT = (11, 30)
PAPER_CSV = "data/mnq_paper/paper_trades.csv"


class MNQSimStrategy:
    """mnq_sim classifier+gate wired to the bot's standard strategy interface."""

    VALID_SYMBOLS = {"NQ", "MNQ"}

    def __init__(self, data_manager, symbol: str = "MNQ", qty: int = 1,
                 enabled_setups=None, dry: bool = False):
        sym = symbol.upper()
        if sym not in self.VALID_SYMBOLS:
            raise ValueError(f"MNQSimStrategy supports {self.VALID_SYMBOLS}, got {sym!r}")

        self.dm = data_manager
        self.symbol = sym
        self.qty = qty
        self.dry = dry
        self.enabled_setups = set(enabled_setups or {"D"})
        self.logger = logging.getLogger("mnq_sim_live")

        self._session_date: Optional[date] = None
        self._levels: Optional[SessionLevels] = None
        self._vwap: Optional[VwapEngine] = None
        self._clf: Optional[SetupClassifier] = None
        self._gate: Optional[Gate] = None
        self._risk: Optional[SessionRiskState] = None

        self._bars5m: List[Bar] = []
        self._last_win: Optional[int] = None

        # internal paper-sim position state
        self._await_entry: Optional[dict] = None
        self._open_pos: Optional[dict] = None
        self._paper_count = 0

        # live (non-dry) handoff
        self._pending_live: Optional[Dict[str, Any]] = None
        self._last_live_level: Optional[float] = None

    # ================================================================== #
    # Session setup                                                        #
    # ================================================================== #

    def _reset_if_new_session(self) -> None:
        today = datetime.now(ET).date()
        if self._session_date == today:
            return
        self._session_date = today
        self._bars5m = []
        self._last_win = None
        self._await_entry = None
        self._open_pos = None
        self._pending_live = None

        levels = self._build_levels(today)
        if levels is None:
            self._clf = None
            self.logger.warning("MNQSim: no prior-day levels for %s — inactive today", today)
            return

        now_et = datetime.now(ET)
        # today_bars = self._fetch_5m(today, (9, 30), (now_et.hour, now_et.minute))
        # NEW: before 09:30 there is nothing to seed; live bars build state from the open.
        if (now_et.hour, now_et.minute) >= (9, 30):
            today_bars = self._fetch_5m(today, (9, 30), (now_et.hour, now_et.minute))
        else:
            today_bars = []

        rth_open = today_bars[0].open if today_bars else float(
            self.dm.get_current_price(self.symbol) or levels.poc)

        levels.open_location = None
        self._levels = levels
        self._vwap = VwapEngine()
        self._clf = SetupClassifier(levels, rth_open)
        self._gate = Gate()
        self._risk = SessionRiskState()

        # replay today's completed bars to rebuild vwap+classifier state (no signals)
        cur_win = int(now_et.timestamp() // 300) * 300
        for b in today_bars:
            w = int(b.ts.timestamp() // 300) * 300
            if w >= cur_win:
                continue
            self._process_bar(b, live=False)
            self._last_win = w

        self.logger.info(
            "MNQSim reset | %s | mode=%s setups=%s | open=%s POC=%.0f VAH=%.0f VAL=%.0f "
            "PDH=%.0f PDL=%.0f | seeded %d bars",
            today, "DRY" if self.dry else "LIVE", sorted(self.enabled_setups),
            levels.open_location.value if levels.open_location else "?",
            levels.poc, levels.vah, levels.val, levels.pdh, levels.pdl, len(self._bars5m),
        )

    def _build_levels(self, session_date: date) -> Optional[SessionLevels]:
        for back in range(1, 6):
            pday = session_date - timedelta(days=back)
            pbars = self._fetch_5m(pday, (9, 30), (16, 0))
            if pbars:
                pdh = max(b.high for b in pbars)
                pdl = min(b.low for b in pbars)
                try:
                    return compute_profile(pbars, session_date, pdh, pdl, bin_size=1.0)
                except ValueError:
                    return None
        return None

    def _fetch_5m(self, d: date, start_hm, end_hm) -> List[Bar]:
        # Nohing to fetch if the window is empty/inverted (e.g. connected pre-09:30)
        if (start_hm[0], start_hm[1]) >= (end_hm[0], end_hm[1]):
            return []
        try:
            start = self.dm._et_to_utc_timestamp(
                d.strftime("%Y-%m-%d"), f"{start_hm[0]:02d}:{start_hm[1]:02d}:00")
            end = self.dm._et_to_utc_timestamp(
                d.strftime("%Y-%m-%d"), f"{end_hm[0]:02d}:{end_hm[1]:02d}:00")
            rows = self.dm.get_historical_bars(self.symbol, start, end) or []
        except Exception as exc:
            self.logger.debug("MNQSim _fetch_5m failed: %s", exc)
            return []
        return self._agg5(rows)

    def _agg5(self, rows: List[dict]) -> List[Bar]:
        buckets: dict[int, list] = {}
        for r in rows:
            ts_raw = str(r.get("ts") or "")
            try:
                s = ts_raw.replace(" ", "T")
                if s.endswith("+00"):
                    s = s[:-3] + "+00:00"
                dt_et = datetime.fromisoformat(s).astimezone(ET)
            except Exception:
                continue
            key = int(dt_et.timestamp() // 300)
            buckets.setdefault(key, []).append((dt_et, r))
        out = []
        for key in sorted(buckets):
            items = sorted(buckets[key], key=lambda x: x[0])
            ts0 = datetime.fromtimestamp(key * 300, tz=ET)
            out.append(Bar(
                ts=ts0,
                open=float(items[0][1]["open"]),
                high=max(float(x[1]["high"]) for x in items),
                low=min(float(x[1]["low"]) for x in items),
                close=float(items[-1][1]["close"]),
                volume=max(sum(float(x[1].get("volume") or 0) for x in items), 1.0),
            ))
        return out

    def _bar_from_live(self, win: int, members: list) -> Bar:
        members = sorted(members, key=lambda b: getattr(b, "ts_open", 0))
        return Bar(
            ts=datetime.fromtimestamp(win, tz=ET),
            open=float(members[0].open),
            high=max(float(b.high) for b in members),
            low=min(float(b.low) for b in members),
            close=float(members[-1].close),
            volume=float(sum(getattr(b, "volume", 1) or 1 for b in members)),
        )

    # ================================================================== #
    # Tick feed                                                            #
    # ================================================================== #

    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        if price is None:
            return
        self._reset_if_new_session()
        if self._clf is None:
            return
        try:
            raw = self.dm.live.get_last_n(symbol, n=12)
            if not raw:
                return
            tagged = [(int(float(getattr(b, "ts_open", 0)) // 300) * 300, b) for b in raw]
            cur_win = int(time.time() // 300) * 300
            wins = sorted({w for w, _ in tagged
                           if w < cur_win and (self._last_win is None or w > self._last_win)})
            for w in wins:
                members = [b for ww, b in tagged if ww == w]
                self._process_bar(self._bar_from_live(w, members), live=True)
                self._last_win = w
        except Exception as exc:
            self.logger.debug("MNQSim ingest_tick failed: %s", exc)

    # ================================================================== #
    # Core: one completed 5-min bar                                        #
    # ================================================================== #

    def _atr(self, period: int = 14) -> float:
        bars = self._bars5m
        if len(bars) < 2:
            return bars[-1].rng if bars else 1.0
        trs = []
        for j in range(max(1, len(bars) - period), len(bars)):
            pc = bars[j - 1].close
            b = bars[j]
            trs.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
        return sum(trs) / len(trs) if trs else bars[-1].rng

    def _process_bar(self, b: Bar, live: bool) -> None:
        # 1) VWAP + classifier state (every bar, in order)
        self._vwap.update(b)
        v = self._vwap.value
        color = self._vwap.color()
        dets = self._clf.on_bar(b, v, color)
        self._bars5m.append(b)
        if not live:
            return
        atr = self._atr()

        # 2) fill a pending paper entry at this bar's open (dry only)
        if self.dry and self._await_entry and self._open_pos is None:
            self._fill_entry(b)

        # 3) manage an open paper position on this bar (dry only)
        if self.dry and self._open_pos is not None:
            self._manage_exit(b)

        # 4) if flat, look for a new gate-passed enabled signal
        flat = self._open_pos is None and self._await_entry is None
        if not flat:
            return
        for d in dets:
            if not d.fired or d.side is None or d.tag not in self.enabled_setups:
                continue
            gd = self._gate.evaluate(d, b, b.ts, atr, self._risk)
            if not gd.allow:
                self.logger.info("MNQSim %s FIRED but GATED @ %.2f: %s | (%s)",
                                 d.tag, b.close, gd.reason, d.reason)
                continue
            stop, pts = _structural_stop(d, b, atr)
            self.logger.info("MNQSim SIGNAL %s %s entry_ref=%.2f stop=%.2f (%.1fpt) size=%d | %s",
                             d.tag, d.side.value, d.entry_ref or b.close, stop, pts, gd.size, d.reason)
            if self.dry:
                self._await_entry = dict(side=d.side, stop=stop, target=d.target,
                                         level=d.level, tag=d.tag, size=gd.size)
            else:
                self._pending_live = self._to_signal(d, gd, stop, pts)
                self._last_live_level = d.level
            break


    # ---- paper-sim bracket (dry) -------------------------------------- #

    def _fill_entry(self, b: Bar) -> None:
        ae = self._await_entry
        entry = b.open
        stop = ae["stop"]
        target = ae["target"]
        if target is None:
            risk = abs(entry - stop)
            target = entry + 1.5 * risk if ae["side"] == Side.LONG else entry - 1.5 * risk
        long = ae["side"] == Side.LONG
        if not ((long and stop < entry < target) or (not long and target < entry < stop)):
            self.logger.info("MNQSim paper entry skipped (bad geometry) %s", ae["tag"])
            self._await_entry = None
            return
        self._open_pos = dict(side=ae["side"], entry=entry, stop=stop, target=target,
                              level=ae["level"], tag=ae["tag"], size=ae["size"], entry_ts=b.ts)
        self._await_entry = None

    def _manage_exit(self, b: Bar) -> None:
        p = self._open_pos
        long = p["side"] == Side.LONG
        if (b.ts.hour, b.ts.minute) >= HARD_FLAT:
            self._close(b, b.open, "flat_1130")
            return
        hit_stop = b.low <= p["stop"] if long else b.high >= p["stop"]
        hit_tgt = b.high >= p["target"] if long else b.low <= p["target"]
        if hit_stop:                       # pessimistic: stop wins ties
            self._close(b, p["stop"], "stop")
        elif hit_tgt:
            self._close(b, p["target"], "target")

    def _close(self, b: Bar, exit_px: float, reason: str) -> None:
        p = self._open_pos
        long = p["side"] == Side.LONG
        pts = (exit_px - p["entry"]) if long else (p["entry"] - exit_px)
        pnl = pts * POINT_VALUE * p["size"]
        self._risk.register_fill(b.ts, pnl, p["level"])
        self._paper_count += 1
        self.logger.info("MNQSim PAPER %s %s entry=%.2f exit=%.2f pts=%.2f pnl=$%.2f [%s] daily=$%.2f",
                         p["tag"], p["side"].value, p["entry"], exit_px, pts, pnl, reason,
                         self._risk.realized_pnl)
        self._write_csv(p, b, exit_px, pts, pnl, reason)
        self._open_pos = None

    def _write_csv(self, p, b, exit_px, pts, pnl, reason) -> None:
        try:
            os.makedirs(os.path.dirname(PAPER_CSV), exist_ok=True)
            new = not os.path.exists(PAPER_CSV)
            with open(PAPER_CSV, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["entry_ts", "exit_ts", "symbol", "tag", "side", "entry",
                                "stop", "target", "exit", "points", "pnl_usd", "win", "reason"])
                w.writerow([p["entry_ts"].isoformat(), b.ts.isoformat(), self.symbol, p["tag"],
                            p["side"].value, f"{p['entry']:.2f}", f"{p['stop']:.2f}",
                            f"{p['target']:.2f}", f"{exit_px:.2f}", f"{pts:.2f}",
                            f"{pnl:.2f}", int(pts > 0), reason])
        except Exception as exc:
            self.logger.debug("MNQSim CSV write failed: %s", exc)

    # ================================================================== #
    # Bot interface                                                        #
    # ================================================================== #

    def _to_signal(self, d, gd, stop, pts) -> Dict[str, Any]:
        return {
            "type": "BUY" if d.side == Side.LONG else "SELL",
            "symbol": self.symbol,
            "price": d.entry_ref,
            "qty": self.qty * gd.size,
            "reason": f"MNQSim-{d.tag}",
            "context": {"setup": d.tag, "stop_price": stop, "stop_est_points": pts,
                        "target": d.target, "vwap": d.vwap,
                        "vwap_color": d.vwap_color.value if d.vwap_color else "white",
                        "level": d.level},
        }

    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._reset_if_new_session()
        if self.dry:
            return None                    # paper: never hand a trade to the bot
        sig, self._pending_live = self._pending_live, None
        return sig

    def check_breakout(self, symbol: str, current_price=None) -> Optional[Dict[str, Any]]:
        return self.check_signal(symbol)

    def record_trade_result(self, pnl_usd: float) -> None:
        if self.dry or self._risk is None:
            return
        self._risk.register_fill(datetime.now(ET), pnl_usd, self._last_live_level)

    def reset_strategy(self) -> None:
        self._session_date = None

    def analyze_market_context(self, symbol: str = None) -> Dict[str, Any]:
        self._reset_if_new_session()
        now = datetime.now(ET)
        in_session = (9, 45) <= (now.hour, now.minute) < (11, 0)
        if self._clf is None or self._vwap is None:
            return {"strategy": "MNQSim", "symbol": symbol or self.symbol,
                    "mode": "dry" if self.dry else "live", "active": False,
                    "in_session": in_session}
        L = self._levels
        return {
            "strategy": "MNQSim", "symbol": symbol or self.symbol,
            "mode": "dry" if self.dry else "live",
            "enabled_setups": sorted(self.enabled_setups),
            "vwap": self._vwap.value or 0.0,
            "vwap_color": self._vwap.color().value,
            "poc": L.poc, "vah": L.vah, "val": L.val, "pdh": L.pdh, "pdl": L.pdl,
            "open_location": L.open_location.value if L.open_location else "?",
            "daily_pnl": self._risk.realized_pnl if self._risk else 0.0,
            "paper_trades": self._paper_count,
            "bot_paused": self._risk.locked if self._risk else False,
            "in_session": in_session,
        }

