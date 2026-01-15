"""
Opening Range Breakout Strategy (clean, production-safe).
- Computes the opening range over the last `opening_range_minutes`
- Emits BUY when price breaks above OR high by `breakout_threshold` %
- Emits SELL when price breaks below OR low  by `breakout_threshold` %
- Provides lightweight context for the dashboard
"""


from __future__ import annotations


import time
import logging
from typing import Any, Dict, Optional, Tuple, List


from data_manager import DataManager

class OpeningRangeStrategy:
    def __init__(
        self,
        data_manager: DataManager,
        opening_range_minutes: int = 30,
        breakout_threshold: float = 0.05,     # percent, e.g. 0.05 = 0.05%
        stop_loss_percent: float = 2.0,
        take_profit_percent: float = 4.0,
    ):
        self.data_manager = data_manager


        # === external params (match the UI/POST /api/start) ===
        self.opening_range_minutes = int(opening_range_minutes)
        self.breakout_threshold = float(breakout_threshold)  # percent
        self.stop_loss_percent = float(stop_loss_percent)
        self.take_profit_percent = float(take_profit_percent)


        # === internal state ===
        self.logger = logging.getLogger(__name__)
        self._or_bounds: Optional[Tuple[float, float]] = None   # (low, high)
        self._or_computed_at: float = 0.0
        self._or_ttl_sec: float = 5.0                            # recompute at most every 5s


        self.last_price: Optional[float] = None
        self.last_signal_ts: Optional[float] = None
        self._min_signal_gap_sec: float = 10.0                   # cooldown between signals


    # ---------- helpers ----------


    def _now(self) -> float:
        return time.time()


    def _maybe_compute_opening_range(self, symbol: str) -> None:
        """
        Compute opening range if missing/stale, using DM fast path with graceful
        fallback to recent ticks. Never raises.
        """
        now = self._now()
        if self._or_bounds is not None and (now - self._or_computed_at) < self._or_ttl_sec:
            return


        end = now
        start = end - self.opening_range_minutes * 60.0
        lo_hi: Optional[Tuple[float, float]] = None


        # Preferred API: DataManager.get_opening_range
        try:
            # Be tolerant to either (sym, minutes, start_ts) or (sym, minutes)
            dm_method = getattr(self.data_manager, "get_opening_range", None)
            if callable(dm_method):
                try:
                    # try 3-arg form first
                    rng = dm_method(symbol, self.opening_range_minutes, start)
                except TypeError:
                    rng = dm_method(symbol, self.opening_range_minutes)


                if rng and len(rng) >= 2:
                    lo_hi = (float(rng[0]), float(rng[1]))
        except Exception:
            lo_hi = None


        # Fallback: compute from recent prices or tick series
        if lo_hi is None:
            try:
                prices: List[float] = []
                if hasattr(self.data_manager, "get_recent_prices"):
                    series = self.data_manager.get_recent_prices(symbol, int(self.opening_range_minutes * 60))
                    prices = [p[1] if isinstance(p, (tuple, list)) else p for p in (series or [])]
                elif hasattr(self.data_manager, "get_tick_series"):
                    series = self.data_manager.get_tick_series(symbol, start_ts=start, end_ts=end)
                    prices = [p for (_, p) in (series or [])]


                if prices:
                    lo_hi = (float(min(prices)), float(max(prices)))
            except Exception:
                lo_hi = None


        # Commit/cached result
        if lo_hi:
            self._or_bounds = lo_hi
            self._or_computed_at = now
            self.logger.info("Opening range ready for %s: low=%.2f high=%.2f", symbol, lo_hi[0], lo_hi[1])
        else:
            # keep previous bounds if we had them; otherwise stay None
            if self._or_bounds is None:
                self.logger.debug("Opening range not available yet for %s", symbol)


    # ---------- dashboard context ----------


    def analyze_market_context(self, symbol: str) -> Dict[str, Any]:
        """
        Returns a compact snapshot for the UI.
        """
        self._maybe_compute_opening_range(symbol)


        price = None
        try:
            price = self.data_manager.get_current_price(symbol)
        except Exception:
            price = None


        if price is not None:
            self.last_price = float(price)


        or_bounds = tuple(self._or_bounds) if self._or_bounds else None
        or_low, or_high = (or_bounds if or_bounds else (None, None))


        range_position = "unknown"
        if price is not None and or_low is not None and or_high is not None:
            if price > or_high:
                range_position = "above"
            elif price < or_low:
                range_position = "below"
            else:
                range_position = "inside"


        return {
            "current_price": float(price) if price is not None else None,
            "opening_range": or_bounds,
            "yesterday_day_range": None,
            "range_position": range_position,
        }


    # ---------- signal generation ----------


    def _cooldown_ok(self) -> bool:
        if self.last_signal_ts is None:
            return True
        return (self._now() - self.last_signal_ts) >= self._min_signal_gap_sec


    def check_breakout(self, symbol: str, current_price: Optional[float]) -> Optional[Dict[str, Any]]:
        """
        Called once per bot loop with the latest tick price.
        Returns a signal dict or None.
        """
        if current_price is None:
            return None


        self._maybe_compute_opening_range(symbol)
        if not self._or_bounds:
            # OR not ready yet (insufficient data)
            return None


        or_low, or_high = self._or_bounds
        thr = self.breakout_threshold / 100.0  # convert percent → fraction


        buy_trigger = or_high * (1.0 + thr)
        sell_trigger = or_low * (1.0 - thr)


        # Long breakout
        if current_price >= buy_trigger and self._cooldown_ok():
            self.last_signal_ts = self._now()
            self.logger.info(
                "OpeningRange BUY %s @ %.2f (OR high=%.2f thr=%.5f%%)",
                symbol, float(current_price), or_high, self.breakout_threshold
            )
            return {
                "type": "BUY",
                "symbol": symbol,
                "price": float(current_price),
                "qty": 1,
                "reason": "OR breakout up",
            }


        # Short breakdown
        if current_price <= sell_trigger and self._cooldown_ok():
            self.last_signal_ts = self._now()
            self.logger.info(
                "OpeningRange SELL %s @ %.2f (OR low=%.2f thr=%.5f%%)",
                symbol, float(current_price), or_low, self.breakout_threshold
            )
            return {
                "type": "SELL",
                "symbol": symbol,
                "price": float(current_price),
                "qty": 1,
                "reason": "OR breakdown down",
            }


        return None


    # ---------- optional hook used by TradingBot ----------


    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        if price is not None:
            self.last_price = float(price)


    def reset_strategy(self) -> None:
        self._or_bounds = None
        self._or_computed_at = 0.0
        self.last_price = None
        self.last_signal_ts = None
        self.logger.info("OpeningRangeStrategy reset for new session")






