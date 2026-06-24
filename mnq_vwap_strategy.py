"""
MNQ/NQ VWAP + Volume Profile Strategy wrapper (Option A).

Uses MNQStrategySuite for entry signal generation only.
Stop / trailing / exit execution stays in the bot's existing risk_manager.
"""

import time
import logging
from datetime import datetime, date
from datetime import timezone as _tz
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from mnq_strategy_core import (
    MNQStrategySuite,
    ProfileSnapshot,
    Direction,
    ENTRY_START,
    LAST_ENTRY,
    MAX_DAILY_LOSS,
    PROFIT_LOCK_ANY,
    MAX_LOSSES,
)

ET_TZ = ZoneInfo("America/New_York")


def _compute_profile_snapshot(bars: List[dict], open_price: float) -> ProfileSnapshot:
    """Build a ProfileSnapshot from a list of {"o","h","l","c","v"} dicts."""
    if not bars:
        return ProfileSnapshot(
            vah=open_price + 500.0,
            poc=open_price,
            val=open_price - 500.0,
            pdh=open_price + 500.0,
            pdl=open_price - 500.0,
            lvns=[],
            open_price=open_price,
        )

    pdh = max(b["h"] for b in bars)
    pdl = min(b["l"] for b in bars)

    # Volume profile: 1-point buckets
    price_vol: Dict[int, float] = {}
    for b in bars:
        typ = (b["h"] + b["l"] + b["c"]) / 3.0
        bucket = int(round(typ))
        price_vol[bucket] = price_vol.get(bucket, 0.0) + float(b.get("v", 1))

    poc = float(max(price_vol, key=price_vol.get)) if price_vol else (pdh + pdl) / 2.0

    # 70 % value area by expanding from POC
    total_vol = sum(price_vol.values())
    target_vol = total_vol * 0.70
    buckets = sorted(price_vol.keys())
    va_lo = va_hi = int(round(poc))
    va_vol = price_vol.get(va_lo, 0.0)

    while va_vol < target_vol:
        above = va_hi + 1
        below = va_lo - 1
        av = price_vol.get(above, 0.0) if above <= buckets[-1] else -1
        bv = price_vol.get(below, 0.0) if below >= buckets[0] else -1
        if av < 0 and bv < 0:
            break
        if av >= bv:
            va_hi = above
            va_vol += av
        else:
            va_lo = below
            va_vol += bv

    return ProfileSnapshot(
        vah=float(va_hi),
        poc=poc,
        val=float(va_lo),
        pdh=pdh,
        pdl=pdl,
        lvns=[],
        open_price=open_price,
    )


class MNQVwapStrategy:
    """
    VWAP Fade + Volume Profile strategy for NQ / MNQ.

    Public interface matches the bot's standard strategy contract:
      - check_signal(symbol)        → signal dict or None
      - check_breakout(symbol, px)  → alias
      - ingest_tick(symbol, ts, px) → feed price/bar data
      - record_trade_result(pnl)    → notify strategy of closed-trade PnL
      - analyze_market_context(sym) → dashboard data dict
      - reset_strategy()            → force session reset next tick
    """

    VALID_SYMBOLS = {"NQ", "MNQ"}

    def __init__(self, data_manager, symbol: str = "MNQ", qty: int = 1):
        sym = symbol.upper()
        if sym not in self.VALID_SYMBOLS:
            raise ValueError(
                f"MNQVwapStrategy only supports {self.VALID_SYMBOLS}, got {sym!r}"
            )

        self.dm = data_manager
        self.symbol = sym
        self.qty = qty
        self.logger = logging.getLogger(__name__)

        self._session_date: Optional[date] = None
        self._suite: Optional[MNQStrategySuite] = None
        self._pending_signal = None      # Signal object awaiting check_signal pickup
        self._last_bar_ts: Optional[float] = None
        self._open_price: float = 0.0

        self._last_5m_window: Optional[int] = None 

    # ------------------------------------------------------------------ #
    # Session management                                                    #
    # ------------------------------------------------------------------ #

    def _reset_if_new_session(self) -> None:
        today = datetime.now(ET_TZ).date()
        if self._session_date == today:
            return

        self._session_date = today
        self._pending_signal = None
        self._last_bar_ts = None

        self._last_5m_window = None

        try:
            self._open_price = float(self.dm.get_current_price(self.symbol) or 0)
        except Exception:
            self._open_price = 0.0

        prev_bars = self._get_prev_day_bars()
        snapshot = _compute_profile_snapshot(prev_bars, self._open_price or 30000.0)

        self._suite = MNQStrategySuite(
            profile_snapshot=snapshot,
            news_times=[],       # no news feed; governor skips news blocks
        )

        self._seed_today_vwap()

        self.logger.info(
            "MNQVwap session reset | date=%s | POC=%.2f VAH=%.2f VAL=%.2f PDH=%.2f PDL=%.2f",
            today,
            snapshot.poc, snapshot.vah, snapshot.val,
            snapshot.pdh, snapshot.pdl,
        )

    def _get_prev_day_bars(self) -> List[dict]:
        """Return bars for the most recent trading day (skips weekends and holidays)."""
        try:
            if not (hasattr(self.dm, "get_historical_bars") and
                    hasattr(self.dm, "_et_to_utc_timestamp")):
                return []

            from datetime import date, timedelta

            # Walk back up to 5 calendar days to find the last day with bars
            for days_back in range(1, 6):
                target = (date.today() - timedelta(days=days_back)).strftime('%Y-%m-%d')
                start_ts = self.dm._et_to_utc_timestamp(target, "09:30:00")
                end_ts   = self.dm._et_to_utc_timestamp(target, "16:00:00")
                raw = self.dm.get_historical_bars(self.symbol, start_ts, end_ts) or []
                if raw:
                    break
            else:
                return []  # nothing found in 5 days

            normalized = []
            for b in raw:
                normalized.append({
                    "o": float(b.get("open")   or b.get("o", 0)),
                    "h": float(b.get("high")   or b.get("h", 0)),
                    "l": float(b.get("low")    or b.get("l", 0)),
                    "c": float(b.get("close")  or b.get("c", 0)),
                    "v": float(b.get("volume") or b.get("v", 1)),
                })
            return normalized

        except Exception as exc:
            self.logger.warning("Could not fetch previous day bars: %s", exc)
            return []


    # ------------------------------------------------------------------ #
    # Bar feeding                                                        #
    # ------------------------------------------------------------------ #

    def _seed_today_vwap(self) -> None:
        """
        Fetch today's 1-min Supabase bars from 9:00 AM ET onward, aggregate into
        5-min bars, and seed the VWAP filter. Runs once at session init so the
        strategy has VWAP direction before the first possible trade at 9:45 ET.
        """
        try:
            if not (hasattr(self.dm, "get_historical_bars") and
                    hasattr(self.dm, "_et_to_utc_timestamp")):
                return

            from datetime import timedelta, datetime as _dt

            now_et    = datetime.now(ET_TZ)
            today_str = now_et.date().strftime('%Y-%m-%d')

            start_ts = self.dm._et_to_utc_timestamp(today_str, "09:00:00")

            # End: 5 minutes before now so we never feed the in-progress bar
            seed_end_utc  = (now_et - timedelta(minutes=5)).astimezone(_tc.utc)
            end_ts = seed_end_utc.strftime('%Y-%m-%d %H:%M:%S')

            raw = self.dm.get_historical_bars(self.symbol, start_ts, end_ts) or []
            if not raw:
                self.logger.info(
                    "MNQVwap: no today bars in Supabase (symbol=%s) — VWAP will build from live",
                    self.symbol,
                )
                return

            # Parse Supabase rows — format is "2026-06-22 02:48:00+00" (note +00, not +00:00)
            tagged = []
            for b in raw:
                ts_raw = str(b.get("ts") or "")
                try:
                    ts_clean = ts_raw.replace(" ", "T")
                    # Python fromisoformat needs +HH:MM, not just +HH
                    if len(ts_clean) > 3 and ts_clean[-3] == "+" and ":" not in ts_clean[-3:]:
                        ts_clean += ":00"
                    epoch = _dt.fromisoformat(ts_clean).timestamp()
                except Exception:
                    continue

                tagged.append({
                    "ts":   epoch,
                    "win5": int(epoch // 300) * 300,
                    "o": float(b.get("open")   or 0),
                    "h": float(b.get("high")   or 0),
                    "l": float(b.get("low")    or 0),
                    "c": float(b.get("close")  or 0),
                    "v": float(b.get("volume") or 1),
                })

            if not tagged:
                return

            current_win = int(now_et.timestamp() // 300) * 300
            wins = sorted(w for w in set(b["win5"] for b in tagged) if w < current_win)
            fed = 0

            for win in wins:
                wb = [b for b in tagged if b["win5"] == win]
                agg = {
                    "o": wb[0]["o"],
                    "h": max(b["h"] for b in wb),
                    "l": min(b["l"] for b in wb),
                    "c": wb[-1]["c"],
                    "v": sum(b["v"] for b in wb),
                    "ts": win,
                }
                # Signal return is discarded — only VWAP history matters here
                self._suite.on_new_5m_bar(agg, next_bar_open=agg["c"])
                self._last_5m_window = win
                fed += 1

            self.logger.info(
                "MNQVwap: seeded VWAP with %d 5-min bars from Supabase (09:00 ET → now)", fed
            )

        except Exception as exc:
            self.logger.warning("MNQVwap VWAP seeding failed: %s", exc)


    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        """Called by trading_bot on every price tick. Aggregates 1-min bars into 5-min bars."""
        if price is None:
            return
        self._reset_if_new_session()
        if not self._suite:
            return

        try:
            raw_bars = self.dm.live.get_last_n(symbol, n=7)
            if not raw_bars:
                return

            # Tag each 1-min bar with its 5-minute window floor
            tagged = []
            for b in raw_bars:
                ts = float(getattr(b, "ts_open", 0))
                tagged.append({
                    "ts": ts,
                    "win5": int(ts // 300) * 300,   # e.g. 09:45 → 09:45, 09:46–09:49 → 09:45
                    "o": float(b.open),
                    "h": float(b.high),
                    "l": float(b.low),
                    "c": float(b.close),
                    "v": float(getattr(b, "volume", 1)),
                })

            # Current (in-progress) window — never feed until it closes
            current_win = tagged[-1]["win5"]

            # Completed windows not yet fed to the suite
            unseen = sorted(
                win for win in set(b["win5"] for b in tagged)
                if win < current_win
                and (self._last_5m_window is None or win > self._last_5m_window)
            )

            for win in unseen:
                wb = [b for b in tagged if b["win5"] == win]
                agg = {
                    "o": wb[0]["o"],
                    "h": max(b["h"] for b in wb),
                    "l": min(b["l"] for b in wb),
                    "c": wb[-1]["c"],
                    "v": sum(b["v"] for b in wb),
                    "ts": win,
                }
                self._last_5m_window = win

                # next_bar_open: first bar of the following window, else current tick
                next_open = price
                for b in tagged:
                    if b["win5"] > win:
                        next_open = b["o"]
                        break

                sig = self._suite.on_new_5m_bar(agg, next_bar_open=next_open)
                if sig is not None and self._pending_signal is None:
                    self._pending_signal = sig

        except Exception as exc:
            self.logger.debug("ingest_tick 5m aggregation failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Signal check                                                          #
    # ------------------------------------------------------------------ #

    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._reset_if_new_session()

        if not self._suite:
            return None

        # Guard: session risk governor locked
        if self._suite.governor.state.locked:
            return None

        # Guard: outside entry window (re-check here for visibility)
        now_et = datetime.now(ET_TZ)
        h, m = now_et.hour, now_et.minute
        entry_h, entry_m = ENTRY_START
        last_h, last_m = LAST_ENTRY
        before_start = (h, m) < (entry_h, entry_m)
        after_last = (h, m) >= (last_h, last_m)
        if before_start or after_last:
            return None

        if self._pending_signal is None:
            return None

        sig = self._pending_signal
        self._pending_signal = None

        # Mark suite as in-trade so it won't generate another signal
        self._suite.open_trade(sig)

        direction = "BUY" if sig.direction == Direction.LONG else "SELL"
        stop_pts = abs(sig.entry - sig.stop)
        suite_profile = self._suite.profile.snapshot

        return {
            "type": direction,
            "symbol": symbol,
            "price": sig.entry,
            "qty": self.qty * sig.size,
            "reason": f"MNQVwap-{sig.setup.value}",
            "context": {
                "setup": sig.setup.value,
                "vwap": self._suite.vwap_filter.vwap,
                "vwap_color": self._suite.vwap_filter.color().value,
                "poc": suite_profile.poc,
                "vah": suite_profile.vah,
                "val": suite_profile.val,
                "pdh": suite_profile.pdh,
                "pdl": suite_profile.pdl,
                "stop_price": sig.stop,
                "stop_est_points": stop_pts,
                "counter_vwap": sig.counter_vwap,
                "target_1": sig.profile_target_1,
            },
        }

    def check_breakout(self, symbol: str, current_price=None) -> Optional[Dict[str, Any]]:
        return self.check_signal(symbol)

    # ------------------------------------------------------------------ #
    # Trade result (called from trading_bot after a fill closes)           #
    # ------------------------------------------------------------------ #

    def record_trade_result(self, pnl_usd: float) -> None:
        """
        Reset the suite's in-trade state and record PnL in the risk governor.
        Called from trading_bot._record_fill() when 'closed' key is present.
        """
        if not self._suite:
            return
        # Reset trade state so suite can generate the next signal
        self._suite.trade.reset()
        # Record PnL in the risk governor (tracks losses, locks, daily limit)
        self._suite.governor.record_trade_result(pnl_usd, time.time())

        state = self._suite.governor.state
        if state.locked:
            self.logger.warning(
                "MNQVwap LOCKED: daily_pnl=%.2f losses=%d",
                state.daily_pnl, state.losses,
            )

    # ------------------------------------------------------------------ #
    # Dashboard                                                             #
    # ------------------------------------------------------------------ #

    def reset_strategy(self) -> None:
        self._session_date = None

    def analyze_market_context(self, symbol: str = None) -> Dict[str, Any]:
        self._reset_if_new_session()

        now_et = datetime.now(ET_TZ)
        h, m = now_et.hour, now_et.minute
        entry_h, entry_m = ENTRY_START
        last_h, last_m = LAST_ENTRY
        in_session = (entry_h, entry_m) <= (h, m) < (last_h, last_m)

        if not self._suite:
            return {
                "strategy": "MNQVwap",
                "symbol": symbol or self.symbol,
                "vwap": 0.0,
                "vwap_color": "white",
                "poc": 0.0, "vah": 0.0, "val": 0.0,
                "pdh": 0.0, "pdl": 0.0,
                "daily_pnl": 0.0,
                "bot_paused": False,
                "profit_locked": False,
                "in_session": in_session,
            }

        state = self._suite.governor.state
        snap = self._suite.profile.snapshot

        return {
            "strategy": "MNQVwap",
            "symbol": symbol or self.symbol,
            "vwap": self._suite.vwap_filter.vwap,
            "vwap_color": self._suite.vwap_filter.color().value,
            "poc": snap.poc,
            "vah": snap.vah,
            "val": snap.val,
            "pdh": snap.pdh,
            "pdl": snap.pdl,
            "daily_pnl": state.daily_pnl,
            "bot_paused": state.locked,
            "profit_locked": state.locked,
            "in_session": in_session,
        }



