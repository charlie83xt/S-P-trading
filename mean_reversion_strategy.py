import logging
from datetime import datetime, time
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from dataclasses import field


class MeanReversionStrategy:
    """
    Mean reversion strategy using Bollinger Bands with confirmation.

    Logic:
    - Track when price pierces outside a Bollinger Band.
    - Only trigger a trade when price re-enters the band:
        BUY  -> after piercing below lower band, then reclaiming above it
        SELL -> after piercing above upper band, then falling back below it

    Why this is better:
    - Avoids blindly buying weakness / selling strength on first touch
    - Reduces repeated signals while price stays extended
    - Enforces daily trade limits and session rules
    - Adds cooldown between trades
    - Adds bandwidth filter to avoid dead markets

    Assumptions:
    - data_manager.get_current_price(symbol) -> current float-compatible price
    - data_manager.live.get_last_n(symbol, n=...) -> list of bar objects with .close
    """

    def __init__(
        self,
        data_manager,
        lookback: int = 20,
        std_dev: float = 2.0,
        max_trades_per_day: int = 4,
        qty: int = 1,
        session_timezone: str = "America/New_York",
        session_start: time = time(12, 0),
        session_end: time = time(16, 0),
        use_session_filter: bool = True,
        min_bandwidth_pct: float = 0.0025,
        cooldown_bars: int = 3,
        require_reentry_confirmation: bool = True,
    ):
        if lookback < 5:
            raise ValueError("lookback must be at least 5")
        if std_dev <= 0:
            raise ValueError("std_dev must be > 0")
        if max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if qty < 1:
            raise ValueError("qty must be >= 1")
        if cooldown_bars < 0:
            raise ValueError("cooldown_bars must be >= 0")

        self.dm = data_manager
        self.lookback = lookback
        self.std_dev = std_dev
        self.max_trades_per_day = max_trades_per_day
        self.qty = qty

        self.session_timezone = ZoneInfo(session_timezone)
        self.session_start = session_start
        self.session_end = session_end
        self.use_session_filter = use_session_filter

        self.min_bandwidth_pct = min_bandwidth_pct
        self.cooldown_bars = cooldown_bars
        self.require_reentry_confirmation = require_reentry_confirmation

        self.trades_today = 0
        self.session_date: Optional[str] = None

        # State tracking
        self.last_signal_side: Optional[str] = None   # "BUY", "SELL", or None
        self.awaiting_buy_reentry = False
        self.awaiting_sell_reentry = False
        self.bars_since_last_trade = 10_000

        self.logger = logging.getLogger(__name__)

    # -----------------------------
    # Time / session helpers
    # -----------------------------
    def _now_local(self) -> datetime:
        return datetime.now(self.session_timezone)

    def _today_str(self) -> str:
        return self._now_local().date().isoformat()

    def _in_session(self) -> bool:
        if not self.use_session_filter:
            return True
        now_t = self._now_local().time()
        return self.session_start <= now_t <= self.session_end

    def _reset_if_new_day(self) -> None:
        today = self._today_str()
        if self.session_date != today:
            self.session_date = today
            self.trades_today = 0
            self.last_signal_side = None
            self.awaiting_buy_reentry = False
            self.awaiting_sell_reentry = False
            self.bars_since_last_trade = 10_000
            self.logger.info("New session detected. Strategy state reset.")

    def reset_strategy(self) -> None:
        """Manual reset of strategy state."""
        self.trades_today = 0
        self.last_signal_side = None
        self.awaiting_buy_reentry = False
        self.awaiting_sell_reentry = False
        self.bars_since_last_trade = 10_000

    # -----------------------------
    # Data / math helpers
    # -----------------------------
    def _get_bars(self, symbol: str, n: int):
        bars = self.dm.live.get_last_n(symbol, n=n)
        if not bars or len(bars) < n:
            return None
        return bars

    def _extract_closes(self, bars) -> List[float]:
        return [float(b.close) for b in bars]

    def _calculate_bands(self, closes: List[float]) -> Dict[str, float]:
        sma = sum(closes) / len(closes)
        variance = sum((c - sma) ** 2 for c in closes) / len(closes)
        std = variance ** 0.5

        upper_band = sma + (self.std_dev * std)
        lower_band = sma - (self.std_dev * std)
        bandwidth = upper_band - lower_band
        bandwidth_pct = (bandwidth / sma) if sma else 0.0

        latest_close = closes[-1]
        zscore = ((latest_close - sma) / std) if std > 0 else 0.0

        return {
            "sma": sma,
            "std": std,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "bandwidth": bandwidth,
            "bandwidth_pct": bandwidth_pct,
            "zscore": zscore,
        }

    def _build_signal(
        self,
        signal_type: str,
        symbol: str,
        price: float,
        reason: str,
        stats: Dict[str, float],
    ) -> Dict[str, Any]:
        return {
            "type": signal_type,
            "symbol": symbol,
            "price": price,
            "qty": self.qty,
            "reason": reason,
            "context": {
                "sma": stats["sma"],
                "std": stats["std"],
                "upper_band": stats["upper_band"],
                "lower_band": stats["lower_band"],
                "bandwidth_pct": stats["bandwidth_pct"],
                "zscore": stats["zscore"],
                "trades_today": self.trades_today,
                "max_trades_per_day": self.max_trades_per_day,
                "awaiting_buy_reentry": self.awaiting_buy_reentry,
                "awaiting_sell_reentry": self.awaiting_sell_reentry,
                "bars_since_last_trade": self.bars_since_last_trade,
            },
        }

    # -----------------------------
    # Main signal logic
    # -----------------------------
    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Check for mean reversion trade signal.

        Returns:
            signal dict or None
        """
        self._reset_if_new_day()

        if not self._in_session():
            return None

        if self.trades_today >= self.max_trades_per_day:
            return None

        try:
            price_raw = self.dm.get_current_price(symbol)
            if price_raw is None:
                return None
            price = float(price_raw)
        except (TypeError, ValueError) as e:
            self.logger.warning("Invalid current price for %s: %r (%s)", symbol, price_raw, e)
            return None
        except Exception as e:
            self.logger.exception("Unexpected error reading price for %s: %s", symbol, e)
            return None

        try:
            # Need one extra bar so we can compare previous close and current close behavior
            bars = self._get_bars(symbol, self.lookback + 1)
            if not bars:
                return None

            closes = self._extract_closes(bars)
        except Exception as e:
            self.logger.exception("Failed to fetch/parse bars for %s: %s", symbol, e)
            return None

        # Use prior lookback window for stable BB calculation
        calculation_window = closes[-self.lookback:]
        stats = self._calculate_bands(calculation_window)

        upper_band = stats["upper_band"]
        lower_band = stats["lower_band"]
        bandwidth_pct = stats["bandwidth_pct"]

        prev_close = closes[-2]
        latest_close = closes[-1]

        # Count bars forward each time we evaluate
        self.bars_since_last_trade += 1

        # Skip dead markets
        if bandwidth_pct < self.min_bandwidth_pct:
            self.awaiting_buy_reentry = False
            self.awaiting_sell_reentry = False
            return None

        # Cooldown after a trade
        if self.bars_since_last_trade < self.cooldown_bars:
            return None

        # -----------------------------------
        # State setup: detect band pierce
        # -----------------------------------
        if latest_close < lower_band:
            self.awaiting_buy_reentry = True

        if latest_close > upper_band:
            self.awaiting_sell_reentry = True

        # If not requiring reentry confirmation, allow immediate signal on pierce
        if not self.require_reentry_confirmation:
            if latest_close <= lower_band and self.last_signal_side != "BUY":
                self.trades_today += 1
                self.last_signal_side = "BUY"
                self.awaiting_buy_reentry = False
                self.awaiting_sell_reentry = False
                self.bars_since_last_trade = 0

                self.logger.info(
                    "BUY %s | price=%.2f lower=%.2f sma=%.2f z=%.2f",
                    symbol, price, lower_band, stats["sma"], stats["zscore"]
                )
                return self._build_signal(
                    "BUY",
                    symbol,
                    price,
                    "Oversold below lower Bollinger Band",
                    stats,
                )

            if latest_close >= upper_band and self.last_signal_side != "SELL":
                self.trades_today += 1
                self.last_signal_side = "SELL"
                self.awaiting_buy_reentry = False
                self.awaiting_sell_reentry = False
                self.bars_since_last_trade = 0

                self.logger.info(
                    "SELL %s | price=%.2f upper=%.2f sma=%.2f z=%.2f",
                    symbol, price, upper_band, stats["sma"], stats["zscore"]
                )
                return self._build_signal(
                    "SELL",
                    symbol,
                    price,
                    "Overbought above upper Bollinger Band",
                    stats,
                )

            return None

        # -----------------------------------
        # Confirmation logic: re-enter band
        # -----------------------------------
        # BUY when market was below lower band and now reclaims inside
        buy_confirmed = (
            self.awaiting_buy_reentry
            and prev_close < lower_band
            and latest_close >= lower_band
            and self.last_signal_side != "BUY"
        )

        if buy_confirmed:
            self.trades_today += 1
            self.last_signal_side = "BUY"
            self.awaiting_buy_reentry = False
            self.awaiting_sell_reentry = False
            self.bars_since_last_trade = 0

            self.logger.info(
                "CONFIRMED BUY %s | price=%.2f lower=%.2f sma=%.2f z=%.2f trades=%d/%d",
                symbol,
                price,
                lower_band,
                stats["sma"],
                stats["zscore"],
                self.trades_today,
                self.max_trades_per_day,
            )

            return self._build_signal(
                "BUY",
                symbol,
                price,
                "Reclaimed inside lower Bollinger Band after oversold pierce",
                stats,
            )

        # SELL when market was above upper band and now falls back inside
        sell_confirmed = (
            self.awaiting_sell_reentry
            and prev_close > upper_band
            and latest_close <= upper_band
            and self.last_signal_side != "SELL"
        )

        if sell_confirmed:
            self.trades_today += 1
            self.last_signal_side = "SELL"
            self.awaiting_buy_reentry = False
            self.awaiting_sell_reentry = False
            self.bars_since_last_trade = 0

            self.logger.info(
                "CONFIRMED SELL %s | price=%.2f upper=%.2f sma=%.2f z=%.2f trades=%d/%d",
                symbol,
                price,
                upper_band,
                stats["sma"],
                stats["zscore"],
                self.trades_today,
                self.max_trades_per_day,
            )

            return self._build_signal(
                "SELL",
                symbol,
                price,
                "Fell back inside upper Bollinger Band after overbought pierce",
                stats,
            )

        # Clear stale state if price has normalized toward the middle
        if lower_band < latest_close < upper_band:
            # Keep same-side lock until opposite condition or next day,
            # but remove "awaiting" flags once market is back inside.
            self.awaiting_buy_reentry = False
            self.awaiting_sell_reentry = False

        return None

    # -----------------------------
    # Compatibility hooks
    # -----------------------------
    def check_breakout(self, symbol: str, current_price=None):
        return self.check_signal(symbol)

    def ingest_tick(self, symbol: str, ts_epoch: float, price):
        """
        Placeholder for future tick-based logic.
        Right now strategy is bar-driven.
        """
        return None

    # -----------------------------
    # Dashboard / monitoring
    # -----------------------------
    def analyze_market_context(self, symbol: str) -> Dict[str, Any]:
        """Return strategy state for dashboard / monitoring."""
        try:
            bars = self._get_bars(symbol, self.lookback + 1)
            if not bars:
                return {"status": "insufficient_data"}

            closes = self._extract_closes(bars)
            stats = self._calculate_bands(closes[-self.lookback:])

            current_price_raw = self.dm.get_current_price(symbol)
            current_price = float(current_price_raw) if current_price_raw is not None else None

            signal_zone = "inside_bands"
            if current_price is not None:
                if current_price < stats["lower_band"]:
                    signal_zone = "below_lower_band"
                elif current_price > stats["upper_band"]:
                    signal_zone = "above_upper_band"

            return {
                "status": "ok",
                "symbol": symbol,
                "current_price": current_price,
                "sma": stats["sma"],
                "std": stats["std"],
                "upper_band": stats["upper_band"],
                "lower_band": stats["lower_band"],
                "bandwidth_pct": stats["bandwidth_pct"],
                "zscore": stats["zscore"],
                "signal_zone": signal_zone,
                "trades_today": self.trades_today,
                "max_trades": self.max_trades_per_day,
                "bars_since_last_trade": self.bars_since_last_trade,
                "awaiting_buy_reentry": self.awaiting_buy_reentry,
                "awaiting_sell_reentry": self.awaiting_sell_reentry,
                "last_signal_side": self.last_signal_side,
                "in_session": self._in_session(),
                "session_date": self.session_date,
            }

        except Exception as e:
            self.logger.exception("Failed to analyze market context for %s: %s", symbol, e)
            return {
                "status": "error",
                "symbol": symbol,
                "message": str(e),
            }