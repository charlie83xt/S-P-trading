# File: mean_reversion_strategy.py
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from debug_config import PRINT_STRATEGY_STATE, should_log_throttled

class MeanReversionStrategyOld:
    """
    Simple mean reversion strategy using Bollinger Bands.
   
    Rules:
    - Buy when price touches lower band (oversold)
    - Sell when price touches upper band (overbought)
    - Works best in choppy, range-bound markets
    - Good for US afternoon session (12-4 PM ET)
    """
   
    def __init__(
        self,
        data_manager,
        lookback: int = 20,  # SMA period
        std_dev: float = 2.0,  # BB standard deviations
        max_trades_per_day: int = 4
    ):
        self.dm = data_manager
        self.lookback = lookback
        self.std_dev = std_dev
        self.max_trades_per_day = max_trades_per_day
       
        self.trades_today = 0
        self.session_date = None
       
        self.logger = logging.getLogger(__name__)
   
    def reset_strategy(self):
        """Reset daily counters"""
        self.trades_today = 0
   
    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Check for mean reversion signals.
       
        Returns signal dict or None
        """
        # Reset on new day
        today = datetime.now().date().isoformat()
        if self.session_date != today:
            self.session_date = today
            self.trades_today = 0
       
        # Check trade limit
        if self.trades_today >= self.max_trades_per_day:
            return None
       
        # Get current price
        price = self.dm.get_current_price(symbol)
        if not price:
            return None
       
        price = float(price)
       
        # Get last N bars for BB calculation
        try:
            bars = self.dm.live.get_last_n(symbol, n=self.lookback + 1)
        except:
            return None
       
        if len(bars) < self.lookback:
            return None
       
        # Calculate Bollinger Bands
        closes = [b.close for b in bars[-self.lookback:]]
       
        sma = sum(closes) / len(closes)
        variance = sum((c - sma) ** 2 for c in closes) / len(closes)
        std = variance ** 0.5
       
        upper_band = sma + (self.std_dev * std)
        lower_band = sma - (self.std_dev * std)
       
        # Generate signals
        # Buy when price below lower band (oversold)
        if price <= lower_band:
            self.trades_today += 1
            if PRINT_STRATEGY_STATE or should_log_throttled('strategy_state', 300):
                self.logger.info(
                    f"Mean Reversion BUY: price={price:.2f} <= lower_band={lower_band:.2f}"
                )
           
            return {
                "type": "BUY",
                "symbol": symbol,
                "price": price,
                "qty": 1,
                "reason": f"Oversold (BB lower)",
                "context": {
                    "sma": sma,
                    "upper_band": upper_band,
                    "lower_band": lower_band
                }
            }
       
        # Sell when price above upper band (overbought)
        elif price >= upper_band:
            self.trades_today += 1
            if PRINT_STRATEGY_STATE or should_log_throttled('strategy_state', 300):
                self.logger.info(
                    f"Mean Reversion SELL: price={price:.2f} >= upper_band={upper_band:.2f}"
                )
           
            return {
                "type": "SELL",
                "symbol": symbol,
                "price": price,
                "qty": 1,
                "reason": f"Overbought (BB upper)",
                "context": {
                    "sma": sma,
                    "upper_band": upper_band,
                    "lower_band": lower_band
                }
            }
       
        return None
   
    # Compatibility methods
    def check_breakout(self, symbol: str, current_price=None):
        return self.check_signal(symbol)
   
    def ingest_tick(self, symbol: str, ts_epoch: float, price):
        pass
   
    def analyze_market_context(self, symbol: str) -> dict:
        """Return strategy state for dashboard"""
        bars = self.dm.live.get_last_n(symbol, n=self.lookback)
       
        if len(bars) < self.lookback:
            return {"status": "insufficient_data"}
       
        closes = [b.close for b in bars]
        sma = sum(closes) / len(closes)
       
        return {
            "sma": sma,
            "trades_today": self.trades_today,
            "max_trades": self.max_trades_per_day
        }


