"""
Previous Day High/Low Reversal Strategy
Adapted for the trading bot architecture
"""

import logging
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from debug_config import PRINT_STRATEGY_STATE, should_log_throttled


@dataclass
class Candle:
    """OHLCV candle data"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    
    @property
    def body(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def body_top(self) -> float:
        return max(self.open, self.close)
    
    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)
    
    @property
    def upper_shadow(self) -> float:
        return self.high - self.body_top
    
    @property
    def lower_shadow(self) -> float:
        return self.body_bottom - self.low
    
    @property
    def total_range(self) -> float:
        return self.high - self.low



class PreviousDayHighLowStrategy:
    """
    Previous Day High/Low Reversal Strategy
    
    Logic:
    1. Calculate previous day's high and low at session start
    2. Wait for price to touch previous day's high or low
    3. Look for reversal candle pattern:
       - Shooting Star at previous high → SHORT signal
       - Hanging Man at previous low → LONG signal
    4. Enter trade targeting opposite level
    
    Pattern Definitions:
    - Shooting Star: Small body at bottom, long upper shadow (≥2x body), little/no lower shadow
    - Hanging Man: Small body at top, long lower shadow (≥2x body), little/no upper shadow
    """
    
    def __init__(
        self,
        data_manager,
        shadow_ratio: float = 2.0,          # Shadow must be ≥2x body
        max_other_shadow: float = 0.3,      # Opposite shadow ≤30% of body
        min_body_pct: float = 0.05,         # Body ≥5% of total range (avoid doji)
        tolerance_pct: float = 0.002,       # Within 0.2% counts as level touch
        max_trades_per_day: int = 4,
        qty: int = 1,
        session_timezone: str = "America/New_York",
        session_start: time = time(9, 30),   # Market open
        session_end: time = time(16, 0),     # Market close
        use_session_filter: bool = True,
    ):
        self.dm = data_manager
        self.shadow_ratio = shadow_ratio
        self.max_other_shadow = max_other_shadow
        self.min_body_pct = min_body_pct
        self.tolerance_pct = tolerance_pct
        self.max_trades_per_day = max_trades_per_day
        self.qty = qty
        
        self.session_timezone = ZoneInfo(session_timezone)
        self.session_start = session_start
        self.session_end = session_end
        self.use_session_filter = use_session_filter
        
        # State tracking
        self.trades_today = 0
        self.session_date: Optional[str] = None
        self.prev_day_high: Optional[float] = None
        self.prev_day_low: Optional[float] = None
        self.prev_day_date: Optional[str] = None
        
        # Tracking which levels have been touched today
        self.high_touched = False
        self.low_touched = False
        
        self.logger = logging.getLogger(__name__)
    
    # -------------------------------------------------------------------------
    # Time / Session Helpers
    # -------------------------------------------------------------------------
    
    def _now_local(self) -> datetime:
        """Get current time in session timezone"""
        return datetime.now(self.session_timezone)
    
    def _today_str(self) -> str:
        """Get today's date as string"""
        return self._now_local().date().isoformat()
    
    def _in_session(self) -> bool:
        """Check if currently in trading session"""
        if not self.use_session_filter:
            return True
        now_t = self._now_local().time()
        return self.session_start <= now_t <= self.session_end
    
    def _reset_if_new_day(self) -> None:
        """Reset daily counters on new day"""
        today = self._today_str()
        if self.session_date != today:
            self.session_date = today
            self.trades_today = 0
            self.high_touched = False
            self.low_touched = False
            self.logger.info(f"PrevDayHL: New session {today}, trades_today={self.trades_today}")
    
    # -------------------------------------------------------------------------
    # Previous Day Level Calculation
    # -------------------------------------------------------------------------
    
    def _calculate_prev_day_levels(self, symbol: str) -> bool:
        """
        Calculate previous day's high/low from Supabase daily bars.
        Returns True if successful, False otherwise.
        """
        try:
            # Get daily bars from Supabase (last 5 days)
            daily_bars = self.dm.get_daily_bars(symbol, days=5)
            
            if len(daily_bars) < 2:
                self.logger.warning(
                    f"PrevDayHL: Insufficient daily bars from Supabase ({len(daily_bars)}). "
                    f"Need at least 2 days (yesterday + today partial)."
                )
                return False
            
            # Get yesterday's bar (second to last)
            # Last bar is today (partial/incomplete), second-to-last is yesterday (complete)
            yesterday_bar = daily_bars[-2]
            
            self.prev_day_high = yesterday_bar.high
            self.prev_day_low = yesterday_bar.low
            self.prev_day_date = self._today_str()
            
            self.logger.info(
                f"PrevDayHL: ✅ Levels from Supabase - "
                f"Date={yesterday_bar.timestamp}, "
                f"High={self.prev_day_high:.2f}, "
                f"Low={self.prev_day_low:.2f}, "
                f"Range={self.prev_day_high - self.prev_day_low:.2f} pts"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"PrevDayHL: Error calculating levels from Supabase: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    # -------------------------------------------------------------------------
    # Pattern Detection
    # -------------------------------------------------------------------------
    
    def _valid_body(self, candle: Candle) -> bool:
        """Check if candle has valid body size (not a doji)"""
        if candle.total_range == 0:
            return False
        return (candle.body / candle.total_range) >= self.min_body_pct
    
    def _is_shooting_star(self, candle: Candle) -> bool:
        """
        Bearish reversal at resistance.
        - Long upper shadow (≥ shadow_ratio * body)
        - Small or no lower shadow
        - Small real body
        """
        if not self._valid_body(candle):
            return False
        if candle.body == 0:
            return False
        
        long_upper = candle.upper_shadow >= self.shadow_ratio * candle.body
        small_lower = candle.lower_shadow <= self.max_other_shadow * candle.body
        
        return long_upper and small_lower
    
    def _is_hanging_man(self, candle: Candle) -> bool:
        """
        Reversal candle at support.
        - Long lower shadow (≥ shadow_ratio * body)
        - Small or no upper shadow
        - Small real body
        """
        if not self._valid_body(candle):
            return False
        if candle.body == 0:
            return False
        
        long_lower = candle.lower_shadow >= self.shadow_ratio * candle.body
        small_upper = candle.upper_shadow <= self.max_other_shadow * candle.body
        
        return long_lower and small_upper
    
    # -------------------------------------------------------------------------
    # Level Touch Detection
    # -------------------------------------------------------------------------
    
    def _touches_prev_high(self, candle: Candle) -> bool:
        """Check if candle touched previous day's high"""
        if self.prev_day_high is None:
            return False
        
        tolerance = self.prev_day_high * self.tolerance_pct
        return candle.high >= (self.prev_day_high - tolerance)
    
    def _touches_prev_low(self, candle: Candle) -> bool:
        """Check if candle touched previous day's low"""
        if self.prev_day_low is None:
            return False
        
        tolerance = self.prev_day_low * self.tolerance_pct
        return candle.low <= (self.prev_day_low + tolerance)
    
    # -------------------------------------------------------------------------
    # Signal Generation
    # -------------------------------------------------------------------------
    
    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Main signal generation method.
        Called by the bot's main loop.
        """
        # Reset on new day
        self._reset_if_new_day()
        
        # Log strategy status every minute
        current_time = datetime.now(self.session_timezone)
        if not hasattr(self, '_last_status_log'):
            self._last_status_log = current_time

        # Log status once per minute
        if (current_time - self._last_status_log).total_seconds() >= 60:
            self._last_status_log = current_time
            
            status_parts = []
            
            if self.trades_today >= self.max_trades_per_day:
                status_parts.append(f"MAX TRADES REACHED ({self.trades_today}/{self.max_trades_per_day})")
            
            if not self._in_session():
                status_parts.append("OUT OF SESSION")
            
            if self.prev_day_high and self.prev_day_low:
                current_price = float(self.dm.get_current_price(symbol) or 0)
                dist_to_high = abs(current_price - self.prev_day_high)
                dist_to_low = abs(current_price - self.prev_day_low)
                
                status_parts.append(
                    f"Levels: H={self.prev_day_high:.2f} ({dist_to_high:.2f}pts away) "
                    f"L={self.prev_day_low:.2f} ({dist_to_low:.2f}pts away)"
                )
                
                if self.high_touched:
                    status_parts.append("HIGH TOUCHED")
                if self.low_touched:
                    status_parts.append("LOW TOUCHED")
            else:
                status_parts.append("NO LEVELS YET")
            
            self.logger.info(f"📊 PrevDayHL Status: {' | '.join(status_parts)}")

        # Check trade limit
        if self.trades_today >= self.max_trades_per_day:
            return None
        
        # Check session time
        if not self._in_session():
            self.logger.warning("PrevDayHL: Outside session hours")
            return None
        
        # Ensure we have previous day levels
        if (self.prev_day_high is None or 
            self.prev_day_low is None or 
            self.prev_day_date != self._today_str()):
            
            if not self._calculate_prev_day_levels(symbol):
                self.logger.warning("PrevDayHL: Could not calculate levels")
                return None

        if self.prev_day_high:
            if PRINT_STRATEGY_STATE or should_log_throttled('strategy_state', 300):
                self.logger.info(
                    f"📊 PrevDayHL Active: High={self.prev_day_high:.2f}, "
                    f"Low={self.prev_day_low:.2f}, "
                    f"Trades={self.trades_today}/{self.max_trades_per_day}"
                )
                # Only log this once per minute, not every tick
        
        # Get current price
        current_price = self.dm.get_current_price(symbol)
        if not current_price:
            return None
        
        current_price = float(current_price)

        distance_to_high = abs(current_price - self.prev_day_high)
        distance_to_low = abs(current_price - self.prev_day_low)

        if distance_to_high < 5.0:  # Within 5 points of high
            self.logger.info(f"🔥 Approaching prev high: {distance_to_high:.2f} pts away")


        if distance_to_low < 5.0:  # Within 5 points of low
            self.logger.info(f"❄️  Approaching prev low: {distance_to_low:.2f} pts away")
        
        # Get recent bars to build current candle
        try:
            bars = self.dm.live.get_last_n(symbol, n=2)
        except Exception as e:
            self.logger.debug(f"PrevDayHL: Error getting bars: {e}")
            return None
        
        if len(bars) < 1:
            return None
        
        # Use most recent completed bar
        recent_bar = bars[-1]
        
        # Convert to Candle object
        current_candle = Candle(
            timestamp=datetime.now(self.session_timezone),
            open=recent_bar.open,
            high=recent_bar.high,
            low=recent_bar.low,
            close=recent_bar.close,
            volume=getattr(recent_bar, 'volume', 0.0)
        )

        # ✅ ADD: Log when approaching levels
        dist_to_high = abs(current_candle.high - self.prev_day_high)
        dist_to_low = abs(current_candle.low - self.prev_day_low)
        
        if dist_to_high < 5.0 and not self.high_touched:
            self.logger.info(f"🔥 Approaching prev high: {dist_to_high:.2f}pts away")
        
        if dist_to_low < 5.0 and not self.low_touched:
            self.logger.info(f"❄️  Approaching prev low: {dist_to_low:.2f}pts away")

        # Check for SHORT signal: Touch prev high + Shooting Star
        if self._touches_prev_high(current_candle) and not self.high_touched:
            self.high_touched = True
            
            if self._is_shooting_star(current_candle):
                self.trades_today += 1
                
                self.logger.info(
                    f"PrevDayHL SHORT: Shooting Star at prev high {self.prev_day_high:.2f}, "
                    f"price={current_price:.2f}"
                )
                
                return {
                    "type": "SELL",
                    "symbol": symbol,
                    "price": current_price,
                    "qty": self.qty,
                    "reason": "Shooting Star at prev day high",
                    "context": {
                        "prev_high": self.prev_day_high,
                        "prev_low": self.prev_day_low,
                        "pattern": "ShootingStar",
                        "target": self.prev_day_low,
                        "candle_high": current_candle.high,
                        "candle_low": current_candle.low,
                    }
                }
        
        # Check for LONG signal: Touch prev low + Hanging Man
        if self._touches_prev_low(current_candle) and not self.low_touched:
            self.low_touched = True
            
            if self._is_hanging_man(current_candle):
                self.trades_today += 1
                
                self.logger.info(
                    f"PrevDayHL LONG: Hanging Man at prev low {self.prev_day_low:.2f}, "
                    f"price={current_price:.2f}"
                )
                
                return {
                    "type": "BUY",
                    "symbol": symbol,
                    "price": current_price,
                    "qty": self.qty,
                    "reason": "Hanging Man at prev day low",
                    "context": {
                        "prev_high": self.prev_day_high,
                        "prev_low": self.prev_day_low,
                        "pattern": "HangingMan",
                        "target": self.prev_day_high,
                        "candle_high": current_candle.high,
                        "candle_low": current_candle.low,
                    }
                }
        
        return None
    
    # -------------------------------------------------------------------------
    # Compatibility Methods (for bot integration)
    # -------------------------------------------------------------------------
    
    def check_breakout(self, symbol: str, current_price=None):
        """Compatibility method - delegates to check_signal"""
        return self.check_signal(symbol)
    
    def ingest_tick(self, symbol: str, ts_epoch: float, price):
        """Compatibility method - not needed for this strategy"""
        pass
    
    def reset_strategy(self):
        """Reset strategy state"""
        self.trades_today = 0
        self.high_touched = False
        self.low_touched = False
        self.prev_day_high = None
        self.prev_day_low = None
        self.prev_day_date = None
    
    def analyze_market_context(self, symbol: str) -> dict:
        """Return strategy state for dashboard"""
        return {
            "prev_day_high": self.prev_day_high,
            "prev_day_low": self.prev_day_low,
            "high_touched": self.high_touched,
            "low_touched": self.low_touched,
            "trades_today": self.trades_today,
            "max_trades": self.max_trades_per_day,
            "in_session": self._in_session(),
        }



