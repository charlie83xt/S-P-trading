"""
MNQ/NQ VWAP + Volume Profile Strategy wrapper (Option A).

Uses MNQStrategySuite for entry signal generation only.
Stop / trailing / exit execution stays in the bot's existing risk_manager.
"""

import time
import logging
from datetime import datetime, date
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

        self.logger.info(
            "MNQVwap session reset | date=%s | POC=%.2f VAH=%.2f VAL=%.2f PDH=%.2f PDL=%.2f",
            today,
            snapshot.poc, snapshot.vah, snapshot.val,
            snapshot.pdh, snapshot.pdl,
        )

    def _get_prev_day_bars(self) -> List[dict]:
        try:
            if hasattr(self.dm, "get_previous_day_bars"):
                raw = self.dm.get_previous_day_bars(self.symbol) or []
            elif hasattr(self.dm, "query_yesterday_bars"):
                raw = self.dm.query_yesterday_bars(
                    self.symbol,
                    start_hour=9, start_min=30,
                    end_hour=16, end_min=0,
                ) or []
            else:
                return []

            normalized = []
            for b in raw:
                normalized.append({
                    "o": float(b.get("open")  or b.get("o", 0)),
                    "h": float(b.get("high")  or b.get("h", 0)),
                    "l": float(b.get("low")   or b.get("l", 0)),
                    "c": float(b.get("close") or b.get("c", 0)),
                    "v": float(b.get("volume") or b.get("v", 1)),
                })
            return normalized
        except Exception as exc:
            self.logger.warning("Could not fetch previous day bars: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Bar feeding                                                           #
    # ------------------------------------------------------------------ #

    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        """Called by trading_bot on every price tick."""
        if price is None or not self._suite:
            return
        self._reset_if_new_session()
        if not self._suite:
            return

        try:
            bars = self.dm.live.get_last_n(symbol, n=2)
            if not bars:
                return
            latest = bars[-1]
            ts = float(getattr(latest, "ts_open", ts_epoch))
            if ts == self._last_bar_ts:
                return
            self._last_bar_ts = ts

            bar_dict = {
                "o": float(latest.open),
                "h": float(latest.high),
                "l": float(latest.low),
                "c": float(latest.close),
                "v": float(getattr(latest, "volume", 1)),
                "ts": ts,
            }

            # Feed bar to suite — may return a Signal
            sig = self._suite.on_new_5m_bar(bar_dict, next_bar_open=price)
            if sig is not None and self._pending_signal is None:
                self._pending_signal = sig

        except Exception as exc:
            self.logger.debug("ingest_tick bar update failed: %s", exc)

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



