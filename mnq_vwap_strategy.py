"""
MNQ/NQ VWAP Fade Strategy wrapper.
Adapts the SignalEngine + TradeManager core to the bot's standard interface.
Exclusive to NQ / MNQ — uses Volume Profile + VWAP color + PDH/PDL levels.
"""

import logging
import time
from datetime import datetime, date
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

from mnq_strategy_core import (
    SignalEngine, TradeManager, Vwap, ProfileLevels,
    calculate_levels, BarBuilder,
    LAST_ENTRY_HOUR, LAST_ENTRY_MIN, DAILY_LOSS_LIMIT, PROFIT_LOCK,
)

ET_TZ = ZoneInfo("America/New_York")


class MNQVwapStrategy:
    """
    VWAP Fade strategy for NQ / MNQ.
    Wraps SignalEngine with the standard bot interface.

    Requires DataManager to provide:
    - get_current_price(symbol)
    - live.get_last_n(symbol, n)         ← bar objects with .open/.high/.low/.close/.volume
    - get_previous_day_bars(symbol)      ← list of {o, h, l, c, v} dicts (yesterday's session)
    """

    VALID_SYMBOLS = {"NQ", "MNQ"}

    def __init__(self, data_manager, symbol: str = "MNQ", qty: int = 1):
        sym = symbol.upper()
        if sym not in self.VALID_SYMBOLS:
            raise ValueError(f"MNQVwapStrategy only supports {self.VALID_SYMBOLS}, got {sym}")

        self.dm = data_manager
        self.symbol = sym
        self.qty = qty
        self.logger = logging.getLogger(__name__)

        self._session_date: Optional[date] = None
        self._vwap = Vwap()
        self._levels = ProfileLevels()
        self._engine: Optional[SignalEngine] = None
        self._trade_manager: Optional[TradeManager] = None
        self._daily_pnl: float = 0.0
        self._loss_count: int = 0
        self._profit_locked: bool = False
        self._bot_paused: bool = False
        self._last_bar_ts: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Session reset                                                         #
    # ------------------------------------------------------------------ #

    def _reset_if_new_session(self) -> None:
        today = datetime.now(ET_TZ).date()
        if self._session_date == today:
            return

        self._session_date = today
        self._vwap = Vwap()
        self._daily_pnl = 0.0
        self._loss_count = 0
        self._profit_locked = False
        self._bot_paused = False
        self._last_bar_ts = None

        # Load previous day bars for volume profile / PDH / PDL
        prev_bars = self._get_prev_day_bars()
        self._levels = calculate_levels(prev_bars) if prev_bars else ProfileLevels()

        self._engine = SignalEngine(self._levels, self._vwap)
        self._trade_manager = TradeManager(self._levels)

        # Set open location once market data is available
        try:
            open_price = float(self.dm.get_current_price(self.symbol) or 0)
            if open_price:
                self._engine.set_open_location(open_price)
        except Exception:
            pass

        self.logger.info(
            "MNQVwap session reset | date=%s | POC=%.2f VAH=%.2f VAL=%.2f PDH=%.2f PDL=%.2f",
            today, self._levels.poc, self._levels.vah,
            self._levels.val, self._levels.pdh, self._levels.pdl,
        )

    def _get_prev_day_bars(self) -> list:
        """
        Fetch yesterday's OHLCV bars from DataManager.
        Returns list of {"o","h","l","c","v"} dicts.
        Falls back gracefully to empty list.
        """
        try:
            # Prefer a dedicated method if data_manager supports it
            if hasattr(self.dm, 'get_previous_day_bars'):
                raw = self.dm.get_previous_day_bars(self.symbol) or []
            elif hasattr(self.dm, 'query_yesterday_bars'):
                raw = self.dm.query_yesterday_bars(
                    self.symbol,
                    start_hour=9, start_min=30,
                    end_hour=16, end_min=0,
                ) or []
            else:
                return []

            # Normalize to {"o","h","l","c","v"} format
            normalized = []
            for b in raw:
                normalized.append({
                    "o": float(b.get("open") or b.get("o", 0)),
                    "h": float(b.get("high") or b.get("h", 0)),
                    "l": float(b.get("low")  or b.get("l", 0)),
                    "c": float(b.get("close") or b.get("c", 0)),
                    "v": float(b.get("volume") or b.get("v", 1)),
                })
            return normalized
        except Exception as e:
            self.logger.warning("Could not fetch previous day bars: %s", e)
            return []

    # ------------------------------------------------------------------ #
    # Ingest tick → feed bar builders → update VWAP                       #
    # ------------------------------------------------------------------ #

    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        """Called by trading_bot on every price tick."""
        if price is None:
            return
        self._reset_if_new_session()

        # Feed current bars to VWAP and engine
        # Use live bars from data_manager — no separate bar builder needed
        # because data_manager already maintains live bar history
        try:
            bars = self.dm.live.get_last_n(symbol, n=2)
            if bars:
                latest = bars[-1]
                ts = float(getattr(latest, 'ts_open', ts_epoch))
                if ts != self._last_bar_ts:
                    self._last_bar_ts = ts
                    bar_dict = {
                        "o": float(latest.open),
                        "h": float(latest.high),
                        "l": float(latest.low),
                        "c": float(latest.close),
                        "v": float(getattr(latest, 'volume', 1)),
                        "ts": ts,
                    }
                    vwap_val = self._vwap.update(bar_dict)
                    if self._engine:
                        self._engine.add_5m(bar_dict)
                        # Also add to 15m window every 3 bars (approximate)
                        if len(self._engine.bars_5m) % 3 == 0:
                            self._engine.add_15m(bar_dict)
        except Exception as e:
            self.logger.debug("ingest_tick bar update failed: %s", e)

    # ------------------------------------------------------------------ #
    # Main signal check                                                    #
    # ------------------------------------------------------------------ #

    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._reset_if_new_session()

        if self._bot_paused or self._profit_locked:
            return None

        # Last entry time cutoff (11:30 ET by default)
        now_et = datetime.now(ET_TZ)
        if now_et.hour > LAST_ENTRY_HOUR or \
           (now_et.hour == LAST_ENTRY_HOUR and now_et.minute >= LAST_ENTRY_MIN):
            return None

        if not self._engine:
            return None

        sig = self._engine.evaluate()
        if sig is None:
            return None

        # Map cousin's Signal → bot's standard signal dict
        direction = "BUY" if sig.direction.value == "long" else "SELL"
        stop_pts = abs(sig.entry - sig.stop)

        return {
            "type": direction,
            "symbol": symbol,
            "price": sig.entry,
            "qty": self.qty * sig.size,
            "reason": f"MNQVwap-{sig.setup.value}",
            "context": {
                "setup": sig.setup.value,
                "vwap": self._vwap.value,
                "vwap_color": self._vwap.color().value,
                "poc": self._levels.poc,
                "vah": self._levels.vah,
                "val": self._levels.val,
                "pdh": self._levels.pdh,
                "pdl": self._levels.pdl,
                "stop_price": sig.stop,
                "stop_est_points": stop_pts,
                "counter_vwap": sig.counter_vwap,
            },
        }

    def check_breakout(self, symbol: str, current_price=None) -> Optional[Dict[str, Any]]:
        return self.check_signal(symbol)

    def record_trade_result(self, pnl_usd: float) -> None:
        """Call this when a trade closes to update daily risk tracking."""
        self._daily_pnl += pnl_usd
        if pnl_usd < 0:
            self._loss_count += 1
            if self._loss_count >= 2:
                self._bot_paused = True
                self.logger.warning("MNQVwap PAUSED: 2 consecutive losses")
        if self._daily_pnl <= -DAILY_LOSS_LIMIT:
            self._bot_paused = True
            self.logger.warning("MNQVwap PAUSED: daily loss limit $%.0f hit", DAILY_LOSS_LIMIT)
        if self._daily_pnl >= PROFIT_LOCK:
            self._profit_locked = True
            self.logger.info("MNQVwap PROFIT LOCK: $%.0f target hit", PROFIT_LOCK)

    def reset_strategy(self) -> None:
        self._session_date = None

    def analyze_market_context(self, symbol: str) -> Dict[str, Any]:
        self._reset_if_new_session()
        return {
            "strategy": "MNQVwap",
            "symbol": symbol,
            "vwap": self._vwap.value,
            "vwap_color": self._vwap.color().value if self._engine else "white",
            "poc": self._levels.poc,
            "vah": self._levels.vah,
            "val": self._levels.val,
            "pdh": self._levels.pdh,
            "pdl": self._levels.pdl,
            "daily_pnl": self._daily_pnl,
            "bot_paused": self._bot_paused,
            "profit_locked": self._profit_locked,
            "in_session": (
                datetime.now(ET_TZ).hour < LAST_ENTRY_HOUR or
                (datetime.now(ET_TZ).hour == LAST_ENTRY_HOUR and
                 datetime.now(ET_TZ).minute < LAST_ENTRY_MIN)
            ),
        }


