"""
ORB Break + Retest Strategy (MES-friendly, discipline-first).

This is the strategy your cousin recommended - it's much more sophisticated than
the simple Opening Range strategy. Key improvements:

1. Waits for CLOSED 5m candle beyond OR (not just a wick touch)
2. Requires RETEST of the OR level (filters false breakouts)
3. Needs PATTERN confirmation (engulfing/hammer/breaks)
4. SMA trend filter (only trades with the trend)
5. Built-in risk guardrails (max stop points)
6. Time discipline (9:45 AM - 12:00 PM ET window)

Expected: 2-6 trades per day (vs 0-2 with simple OR)
Quality: Higher win rate due to confirmation requirements

DataManager requirements:
- get_candles(symbol, timeframe, start_ts, end_ts)
- get_last_closed_candles(symbol, timeframe, n)
- get_sma(symbol, length, timeframe, offset) [optional but recommended]
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any, Dict, Optional, List, Tuple

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _TZ = ZoneInfo("America/New_York")
except ImportError:
    try:
        import pytz
        _TZ = ZoneInfo("America/New_York")
    except ImportError:
        _TZ = None  # Fallback for older Python



@dataclass
class ORBState:
    """Tracks the state machine for ORB Break+Retest strategy."""
    session_date: Optional[str] = None
    
    # Opening Range
    or_low: Optional[float] = None
    or_high: Optional[float] = None
    or_ready: bool = False
    or_computed: bool = False
    
    # State machine: WAIT_OR -> WAIT_BREAK -> WAIT_RETEST -> WAIT_TRIGGER -> DONE
    phase: str = "WAIT_OR"
    
    # Breakout tracking
    breakout_side: Optional[str] = None  # "UP" or "DOWN"
    breakout_level: Optional[float] = None
    breakout_ts: Optional[float] = None
    
    # Retest tracking
    retest_seen: bool = False
    last_processed_5m_close_ts: Optional[float] = None
    
    # Trade limiting
    trades_today: int = 0
    last_signal_ts: Optional[float] = None


class ORBRetestStrategy:
    """
    ORB Break + Retest Strategy with pattern confirmation.
    
    Phase 1 (WAIT_OR): Wait for opening range to complete (9:30-9:45 ET)
    Phase 2 (WAIT_BREAK): Wait for 5m CLOSE beyond OR high/low + breakout_points
    Phase 3 (WAIT_RETEST): Wait for price to pull back and touch OR level
    Phase 4 (WAIT_TRIGGER): Wait for confirmation pattern (engulfing/hammer/break)
    Phase 5 (DONE): Max trades reached or one-side-per-day limit hit
    """
    
    def __init__(
        self,
        data_manager,
        opening_range_minutes: int = 15,  # 9:30-9:45 ET (15 min)
        breakout_points: float = 2.0,  # Points beyond OR to confirm breakout
        breakout_threshold_pct: float = 0.00,  # Optional % beyond OR (0 = disabled)
        retest_tolerance_points: float = 1.0,  # How close retest must get
        max_stop_points: float = 10.0,  # Max risk per trade (10pts MES = $50)
        min_signal_gap_sec: float = 30.0,  # Cooldown between signals
        max_trades_per_day: int = 2,  # Max trades per session
        allow_only_one_side_per_day: bool = True,  # Prevents whipsaw
        trade_start_time_et: Tuple[int, int] = (9, 45),  # Earliest trade (h, m)
        trade_end_time_et: Tuple[int, int] = (12, 0),  # Latest trade (h, m)
        use_sma_filter: bool = True,  # SMA20/200 trend filter
        sma_timeframe: str = "5m",
    ):
        self.dm = data_manager
        self.opening_range_minutes = int(opening_range_minutes)
        
        self.breakout_points = float(breakout_points)
        self.breakout_threshold_pct = float(breakout_threshold_pct)
        
        self.retest_tolerance_points = float(retest_tolerance_points)
        self.max_stop_points = float(max_stop_points)
        
        self.min_signal_gap_sec = float(min_signal_gap_sec)
        self.max_trades_per_day = int(max_trades_per_day)
        self.allow_only_one_side_per_day = bool(allow_only_one_side_per_day)
        
        self.trade_start_time_et = trade_start_time_et
        self.trade_end_time_et = trade_end_time_et
        
        self.use_sma_filter = bool(use_sma_filter)
        self.sma_timeframe = sma_timeframe
        
        self.state = ORBState()
        self.logger = logging.getLogger(__name__)

    # ============================================================================
    # TIME HELPERS
    # ============================================================================

    def _now(self) -> float:
        """Current timestamp (epoch seconds)."""
        return time.time()

    def get_et_time(self, ts: float):
        """Convert any timestamp to ET time - works from anywhere!"""
        return datetime.fromtimestamp(ts, tz=ET_TZ)


    def _et_now(self, ts: Optional[float] = None) -> datetime:
        """Convert timestamp to ET timezone-aware datetime."""
        ts = ts if ts is not None else self._now()
        if _TZ is None:
            return datetime.fromtimestamp(ts)
        return datetime.fromtimestamp(ts, tz=_TZ)

    def _session_key(self, ts: float) -> str:
        """Session identifier (YYYY-MM-DD)."""
        return self._et_now(ts).date().isoformat()

    def _session_open_close_ts(self, ts: float) -> Tuple[float, float]:
        """
        Returns (session_open_ts, session_close_ts) for US market.
        Session open = 9:30 AM ET
        Session close = 4:00 PM ET
        """
        now = self._et_now(ts)
        day = now.date()
        
        if _TZ is None:
            open_dt = datetime.combine(day, dtime(9, 30))
            close_dt = datetime.combine(day, dtime(16, 0))
        else:
            open_dt = datetime.combine(day, dtime(9, 30), tzinfo=_TZ)
            close_dt = datetime.combine(day, dtime(16, 0), tzinfo=_TZ)
        
        return open_dt.timestamp(), close_dt.timestamp()

    def _within_trade_window(self, ts: float) -> bool:
        """Check if current time is within allowed trading window."""
        now = self._et_now(ts)
        h, m = now.hour, now.minute
        
        sh, sm = self.trade_start_time_et
        eh, em = self.trade_end_time_et
        
        start_ok = (h > sh) or (h == sh and m >= sm)
        end_ok = (h < eh) or (h == eh and m <= em)
        
        return start_ok and end_ok

    def _in_trading_window(self, ts: float) -> bool:
        """
        Check if current time is within trading window.
        
        TIMEZONE-AWARE: Works from London, Spain, NY, anywhere!
        Trading window is ALWAYS 9:45 AM - 12:00 PM Eastern Time.
        
        Args:
            ts: Unix timestamp
        
        Returns:
            True if within trading window, False otherwise
        """
        if _TZ is None:
            # No timezone library available - allow all trades
            self.logger.warning("No timezone library - trading window disabled")
            return True
        
        # Convert timestamp to Eastern Time
        current_et = datetime.fromtimestamp(ts, tz=_TZ)
        hour = current_et.hour
        minute = current_et.minute
        
        # Get window from config
        start_hour, start_min = self.trade_window_start  # (9, 45)
        end_hour, end_min = self.trade_window_end        # (12, 0)
        
        # Check if before window start
        if hour < start_hour or (hour == start_hour and minute < start_min):
            return False
        
        # Check if after window end
        if hour > end_hour or (hour == end_hour and minute >= end_min):
            return False
        
        # Within window!
        return True


    # ============================================================================
    # RESET & ORB COMPUTATION
    # ============================================================================

    def reset_strategy(self) -> None:
        """Reset strategy state (for new session or manual reset)."""
        self.state = ORBState()
        self.logger.info("ORB strategy reset")

    def _reset_if_new_session(self, ts: float) -> None:
        """Automatically reset state on new trading day."""
        key = self._session_key(ts)
        if self.state.session_date != key:
            self.state = ORBState(session_date=key)
            self.logger.info("New session detected: %s", key)

    def _compute_orb_if_ready(self, symbol: str, ts: float) -> None:
        """
        TIMEZONE-SAFE: Use rolling window from current time.
        Computes OR from the last N minutes of collected bars.
        """
        self._reset_if_new_session(ts)
        
        # Already computed for this session
        if self.state.or_computed:
            return
        
        # Need at least opening_range_minutes worth of data
        bars_available = self.dm.live.get_last_n(symbol, n=self.opening_range_minutes + 5)
        
        self.logger.info(f"📊 COMPUTE_OR: have {len(bars_available)} bars, need {self.opening_range_minutes}")
        
        # ADD THESE LINES:
        if bars_available:
            first_bar_time = datetime.fromtimestamp(bars_available[0].ts_open)
            last_bar_time = datetime.fromtimestamp(bars_available[-1].ts_open)
            self.logger.info(f"   First bar: {first_bar_time} (ts={bars_available[0].ts_open})")
            self.logger.info(f"   Last bar:  {last_bar_time} (ts={bars_available[-1].ts_open})")
        
        if len(bars_available) < self.opening_range_minutes:
            self.state.phase = "WAIT_OR"
            self.logger.debug(f"Collecting bars: {len(bars_available)}/{self.opening_range_minutes}")
            return
        
        # FIX: Use first N bars for OR calculation
        or_bars = bars_available[:self.opening_range_minutes]  # First 30 bars
        
        # Calculate time range from actual bars used
        or_start = or_bars[0].ts_open
        or_end = or_bars[-1].ts_open + 60  # End of last bar
        
        # ADD DIAGNOSTIC LOGGING:
        or_start_time = datetime.fromtimestamp(or_start)
        or_end_time = datetime.fromtimestamp(or_end)
        self.logger.info(f"📊 OR Time Range: {or_start_time} to {or_end_time}")
        self.logger.info(f"   Unix: {or_start} to {or_end}")
        
        # Get candles from the OR period
        candles = []
        for tf in ("1m", "2m", "5m"):
            try:
                candles = self.dm.get_candles(symbol, timeframe=tf, start_ts=or_start, end_ts=or_end) or []
            except Exception as e:
                self.logger.debug(f"Failed to get {tf} candles: {e}")
                candles = []
            if candles:
                self.logger.info(f"📊 Using {tf} timeframe for OR calculation")
                break
        
        self.logger.info(f"📊 COMPUTE_OR: got {len(candles)} candles from get_candles()")
        
        if not candles:
            self.logger.warning("No candles available for OR calculation")
            return
        
        # Calculate OR boundaries
        lo = min(float(c["low"]) for c in candles)
        hi = max(float(c["high"]) for c in candles)
        
        self.state.or_low = lo
        self.state.or_high = hi
        self.state.or_ready = True
        self.state.or_computed = True
        self.state.phase = "WAIT_BREAK"
        
        # CRITICAL: Show breakout thresholds
        threshold_up = hi + self.breakout_points
        threshold_down = lo - self.breakout_points
        
        self.logger.info(f"✅ ORB COMPUTED for {symbol}:")
        self.logger.info(f"   OR Low:  {lo:.2f}")
        self.logger.info(f"   OR High: {hi:.2f}")
        self.logger.info(f"   Range:   {hi - lo:.2f} points")
        self.logger.info(f"   🔺 BREAKOUT UP if price > {threshold_up:.2f}")
        self.logger.info(f"   🔻 BREAKOUT DOWN if price < {threshold_down:.2f}")


    # ============================================================================
    # FILTERS
    # ============================================================================

    def _cooldown_ok(self, ts: float) -> bool:
        """Check if enough time has passed since last signal."""
        if self.state.last_signal_ts is None:
            return True
        return (ts - self.state.last_signal_ts) >= self.min_signal_gap_sec

    def _sma_permission(self, symbol: str, side: str) -> bool:
        """
        SMA-based trend filter:
        - LONG: price > SMA200 AND SMA20 rising
        - SHORT: price < SMA200 AND SMA20 falling
        
        Returns True if filter allows trade, or if filter disabled/unavailable.
        """
        if not self.use_sma_filter:
            return True
        
        try:
            sma20 = float(self.dm.get_sma(symbol, 20, timeframe=self.sma_timeframe))
            sma200 = float(self.dm.get_sma(symbol, 200, timeframe=self.sma_timeframe))
        except Exception as e:
            self.logger.debug(f"SMA filter unavailable: {e}")
            return True  # Fail-open (no filter)
        
        # Detect SMA20 slope (rising/falling)
        slope_up = True
        slope_dn = True
        try:
            sma20_prev = float(self.dm.get_sma(symbol, 20, timeframe=self.sma_timeframe, offset=1))
            slope_up = sma20 >= sma20_prev
            slope_dn = sma20 <= sma20_prev
        except Exception:
            # No offset support - assume neutral slope
            pass
        
        # Get current price (last close)
        try:
            last_candles = self.dm.get_last_closed_candles(symbol, timeframe=self.sma_timeframe, n=1)
            last_close = float(last_candles[-1]["close"]) if last_candles else None
        except Exception:
            last_close = None
        
        if last_close is None:
            return True
        
        # Apply filter logic
        if side == "UP":
            return (last_close > sma200) and slope_up
        else:  # side == "DOWN"
            return (last_close < sma200) and slope_dn

    # ============================================================================
    # CANDLE PATTERN DETECTION (5m bars)
    # ============================================================================

    @staticmethod
    def _is_bullish_engulfing(prev: Dict[str, Any], cur: Dict[str, Any]) -> bool:
        """Bullish engulfing: green candle completely engulfs prior red candle."""
        return (
            float(prev["close"]) < float(prev["open"]) and
            float(cur["close"]) > float(cur["open"]) and
            float(cur["open"]) <= float(prev["close"]) and
            float(cur["close"]) >= float(prev["open"])
        )

    @staticmethod
    def _is_bearish_engulfing(prev: Dict[str, Any], cur: Dict[str, Any]) -> bool:
        """Bearish engulfing: red candle completely engulfs prior green candle."""
        return (
            float(prev["close"]) > float(prev["open"]) and
            float(cur["close"]) < float(cur["open"]) and
            float(cur["open"]) >= float(prev["close"]) and
            float(cur["close"]) <= float(prev["open"])
        )

    @staticmethod
    def _is_hammer(cur: Dict[str, Any]) -> bool:
        """Hammer: long lower wick (2x body), small upper wick, bullish close."""
        o = float(cur["open"])
        c = float(cur["close"])
        h = float(cur["high"])
        l = float(cur["low"])
        
        body = abs(c - o)
        if body == 0:
            body = 1e-9
        
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        return (lower_wick >= 2.0 * body) and (upper_wick <= 1.0 * body) and (c > o)

    @staticmethod
    def _is_shooting_star(cur: Dict[str, Any]) -> bool:
        """Shooting star: long upper wick (2x body), small lower wick, bearish close."""
        o = float(cur["open"])
        c = float(cur["close"])
        h = float(cur["high"])
        l = float(cur["low"])
        
        body = abs(c - o)
        if body == 0:
            body = 1e-9
        
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        return (upper_wick >= 2.0 * body) and (lower_wick <= 1.0 * body) and (c < o)

    @staticmethod
    def _higher_low_break(prev: Dict[str, Any], cur: Dict[str, Any]) -> bool:
        """Higher-low break: current low > previous low AND close > previous high."""
        return (
            float(cur["low"]) > float(prev["low"]) and
            float(cur["close"]) > float(prev["high"])
        )

    @staticmethod
    def _lower_high_break(prev: Dict[str, Any], cur: Dict[str, Any]) -> bool:
        """Lower-high break: current high < previous high AND close < previous low."""
        return (
            float(cur["high"]) < float(prev["high"]) and
            float(cur["close"]) < float(prev["low"])
        )

    # ============================================================================
    # MAIN SIGNAL LOGIC
    # ============================================================================

    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Main entry point - checks for trade signals based on current market state.
        
        Returns signal dict if conditions met, None otherwise.
        Signal dict format:
        {
            "type": "BUY" or "SELL",
            "symbol": symbol,
            "price": entry_price,
            "qty": 1,
            "reason": description,
            "context": {...}  # Extra info for logging/debugging
        }
        """
        # ADD THESE LINES:
        try:
            bars = self.dm.live.get_last_n(symbol, n=5)
            bar_count = len(bars)
        except Exception as e:
            self.logger.error(f"❌ Failed to get bars: {e}")
            bar_count = -1
        
        # self.logger.info(
        #     f"🔍 CHECK_SIGNAL: phase={self.state.phase} "
        #     f"or_ready={self.state.or_ready} "
        #     f"or_computed={self.state.or_computed} "
        #     f"bars_count={bar_count}"
        # )

        self.logger.debug(
            "🔍 CHECK_SIGNAL: phase=%s or_ready=%s or_computed=%s bars_count=%d", 
            self.state.phase, self.state.or_ready, self.state.or_computed, 
            len(self.dm.live.get_last_n(symbol, n=50))
        )
        ts = self._now()
        
        # Step 1: Compute OR if ready
        self._compute_orb_if_ready(symbol, ts)
        if not self.state.or_ready:
            return None
        
        # Step 2: Check trade window
        # if not self._within_trade_window(ts):
        #     return None
        
        # Step 3: Check daily trade limits
        if self.state.trades_today >= self.max_trades_per_day:
            self.state.phase = "DONE"
            return None
        
        # Step 4: Check cooldown
        if not self._cooldown_ok(ts):
            return None
        
        # Step 5: Get last 2 closed 5m candles
        try:
            bars = self.dm.get_last_closed_candles(symbol, timeframe="5m", n=2) or []
        except Exception as e:
            self.logger.warning(f"Failed to get closed candles: {e}")
            return None
        
        if len(bars) < 2:
            return None
        
        prev, cur = bars[-2], bars[-1]
        close_ts = float(cur.get("close_ts") or cur.get("ts") or 0.0)
        
        # Step 6: Process each 5m close only once
        if self.state.last_processed_5m_close_ts == close_ts:
            return None
        self.state.last_processed_5m_close_ts = close_ts
        
        # Extract OR and current candle data
        or_low = float(self.state.or_low)
        or_high = float(self.state.or_high)
        
        cur_close = float(cur["close"])
        cur_low = float(cur["low"])
        cur_high = float(cur["high"])
        
        # Calculate breakout triggers
        up_pct = or_high * (1.0 + (self.breakout_threshold_pct / 100.0))
        dn_pct = or_low * (1.0 - (self.breakout_threshold_pct / 100.0))
        up_trigger = max(or_high + self.breakout_points, up_pct)
        dn_trigger = min(or_low - self.breakout_points, dn_pct)
        
        # One-side-per-day lock
        if self.allow_only_one_side_per_day and self.state.breakout_side and self.state.phase == "DONE":
            return None
        
        # ========================================================================
        # PHASE: WAIT_BREAK
        # ========================================================================
        if self.state.phase == "WAIT_BREAK":
            # Breakout UP
            # ===== DIAGNOSTIC LOGGING (CRITICAL!) =====
            or_high = self.state.or_high
            or_low = self.state.or_low
            threshold_up = or_high + self.breakout_points
            threshold_down = or_low - self.breakout_points
            
            # Only log every 10th check to avoid spam
            self._break_check_count = getattr(self, '_break_check_count', 0) + 1
            
            if self._break_check_count % 10 == 1:  # Log on 1st, 11th, 21st, etc.
                current_price = self.dm.get_current_price(symbol)
                self.logger.info(f"")  # Blank line for readability
                self.logger.info(f"📊 WAIT_BREAK STATUS:")
                self.logger.info(f"   OR Range: {or_low:.2f} to {or_high:.2f}")
                self.logger.info(f"   Current Price: {current_price:.2f}")
                self.logger.info(f"   Need CLOSE > {threshold_up:.2f} OR < {threshold_down:.2f}")
            # ===== END DIAGNOSTIC LOGGING =====
            
            # Get last 3 closed 5m candles
            candles_5m = self.dm.get_last_closed_candles(symbol, "5m", n=3)
            
            # ===== DIAGNOSTIC: Show what we got =====
            if self._break_check_count % 10 == 1:
                self.logger.info(f"   Retrieved {len(candles_5m)} closed 5m candles")
                
                if candles_5m:
                    for i, c in enumerate(candles_5m[-3:]):  # Last 3 candles
                        candle_time = datetime.fromtimestamp(c['ts'])
                        self.logger.info(
                            f"   5m[{i}] {candle_time.strftime('%H:%M')}: "
                            f"O={c['open']:.2f} H={c['high']:.2f} "
                            f"L={c['low']:.2f} C={c['close']:.2f}"
                        )
            # ===== END DIAGNOSTIC =====
            
            if not candles_5m or len(candles_5m) < 2:
                if self._break_check_count % 10 == 1:
                    self.logger.warning(
                        f"❌ Not enough 5m candles! Got {len(candles_5m)}, need 2+"
                    )
                return None
            
            # Check most recent closed 5m candle
            last_5m = candles_5m[-1]
            close = last_5m["close"]
            high = last_5m["high"]
            low = last_5m["low"]
            
            # ===== BREAKOUT DETECTION =====
            
            # Breakout upward?
            if close > threshold_up:
                self.logger.info(f"")
                self.logger.info(f"🚀 ═══ UPWARD BREAKOUT DETECTED! ═══")
                self.logger.info(f"   5m Close: {close:.2f}")
                self.logger.info(f"   Threshold: {threshold_up:.2f}")
                self.logger.info(f"   Broke above by: {close - threshold_up:.2f} points")
                self.logger.info(f"   Phase: WAIT_BREAK → WAIT_RETEST")
                self.logger.info(f"")
                
                self.state.breakout_side = "UP"
                self.state.breakout_level = or_high
                self.state.breakout_ts = last_5m["close_ts"]
                self.state.phase = "WAIT_RETEST"
                return None
            
            # Breakout downward?
            elif close < threshold_down:
                self.logger.info(f"")
                self.logger.info(f"🔻 ═══ DOWNWARD BREAKOUT DETECTED! ═══")
                self.logger.info(f"   5m Close: {close:.2f}")
                self.logger.info(f"   Threshold: {threshold_down:.2f}")
                self.logger.info(f"   Broke below by: {threshold_down - close:.2f} points")
                self.logger.info(f"   Phase: WAIT_BREAK → WAIT_RETEST")
                self.logger.info(f"")
                
                self.state.breakout_side = "DOWN"
                self.state.breakout_level = or_low
                self.state.breakout_ts = last_5m["close_ts"]
                self.state.phase = "WAIT_RETEST"
                return None
            
            else:
                # Still within range
                if self._break_check_count % 10 == 1:
                    distance_to_up = threshold_up - close
                    distance_to_down = close - threshold_down
                    self.logger.info(
                        f"   ⏳ No breakout yet. "
                        f"Need +{distance_to_up:.2f}pts up OR -{distance_to_down:.2f}pts down"
                    )
            
            return None
        
        # ========================================================================
        # PHASE: WAIT_RETEST
        # ========================================================================
        if self.state.phase == "WAIT_RETEST":
            level = float(self.state.breakout_level)
            tol = self.retest_tolerance_points
            
            # Check if candle range touched the OR level
            touched = (cur_low <= (level + tol)) and (cur_high >= (level - tol))
            
            if touched:
                self.state.retest_seen = True
                self.state.phase = "WAIT_TRIGGER"
                self.logger.info(f"Retest detected @ level={level:.2f}")
            
            return None
        
        # ========================================================================
        # PHASE: WAIT_TRIGGER
        # ========================================================================
        if self.state.phase == "WAIT_TRIGGER":

            # Log every 20th check to avoid spam
            self._trigger_check_count = getattr(self, '_trigger_check_count', 0) + 1
        
            if self._trigger_check_count % 20 == 1:
                current_price = self.dm.get_current_price(symbol)
            
                self.logger.info(f"")
                self.logger.info(f"🎯 WAIT_TRIGGER STATUS:")
                self.logger.info(f"   Breakout Side: {self.state.breakout_side}")
                self.logger.info(f"   OR Level: {self.state.breakout_level:.2f}")
                self.logger.info(f"   Current Price: {current_price:.2f}")
                self.logger.info(f"   Trades Today: {self.state.trades_today}/{self.max_trades_per_day}")
                self.logger.info(f"   One-side limit: {self.allow_only_one_side_per_day}")
            
                if self.allow_only_one_side_per_day:
                    self.logger.info(f"   ⚠️  Already traded {self.state.breakout_side} today")
                    self.logger.info(f"   Will only look for opposite direction until tomorrow")

            side = self.state.breakout_side or ""
            level = float(self.state.breakout_level)
            tol = self.retest_tolerance_points
            
            # Must still be near the retest area (don't chase)
            near_level = (cur_low <= (level + tol)) and (cur_high >= (level - tol))
            if not near_level:
                return None
            
            # --- LONG TRIGGER ---
            if side == "UP":
                trigger_ok = (
                    self._is_bullish_engulfing(prev, cur) or
                    self._is_hammer(cur) or
                    self._higher_low_break(prev, cur)
                )
                
                if not trigger_ok:
                    return None
                
                # Risk box check
                stop_pts = cur_close - cur_low
                if stop_pts > self.max_stop_points:
                    self.logger.info(f"BUY rejected: stop={stop_pts:.2f} > max={self.max_stop_points}")
                    return None
                
                # Generate BUY signal
                self.state.trades_today += 1
                self.state.last_signal_ts = ts
                self.state.phase = "WAIT_BREAK" if not self.allow_only_one_side_per_day else "DONE"
                
                return {
                    "type": "BUY",
                    "symbol": symbol,
                    "price": cur_close,
                    "qty": 1,
                    "reason": "ORB break+retest (5m trigger)",
                    "context": {
                        "or_low": or_low,
                        "or_high": or_high,
                        "breakout_level": level,
                        "trigger": "engulf/hammer/HL-break",
                        "stop_est_points": stop_pts,
                    },
                }
            
            # --- SHORT TRIGGER ---
            if side == "DOWN":
                trigger_ok = (
                    self._is_bearish_engulfing(prev, cur) or
                    self._is_shooting_star(cur) or
                    self._lower_high_break(prev, cur)
                )
                
                if not trigger_ok:
                    return None
                
                # Risk box check
                stop_pts = cur_high - cur_close
                if stop_pts > self.max_stop_points:
                    self.logger.info(f"SELL rejected: stop={stop_pts:.2f} > max={self.max_stop_points}")
                    return None
                
                # Generate SELL signal
                self.state.trades_today += 1
                self.state.last_signal_ts = ts
                self.state.phase = "WAIT_BREAK" if not self.allow_only_one_side_per_day else "DONE"
                
                return {
                    "type": "SELL",
                    "symbol": symbol,
                    "price": cur_close,
                    "qty": 1,
                    "reason": "ORB break+retest (5m trigger)",
                    "context": {
                        "or_low": or_low,
                        "or_high": or_high,
                        "breakout_level": level,
                        "trigger": "engulf/star/LH-break",
                        "stop_est_points": stop_pts,
                    },
                }
        
        # Unknown phase or DONE
        return None

    # ============================================================================
    # UI / DASHBOARD SUPPORT
    # ============================================================================

    def analyze_market_context(self, symbol: str) -> Dict[str, Any]:
        """
        Returns current strategy state for dashboard display.
        """
        ts = self._now()
        self._compute_orb_if_ready(symbol, ts)
        
        return {
            "opening_range": (self.state.or_low, self.state.or_high) if self.state.or_ready else None,
            "phase": self.state.phase,
            "breakout_side": self.state.breakout_side,
            "trades_today": self.state.trades_today,
        }

    def _get_yesterday_context(self) -> dict:
        """
        Query yesterday's data from Supabase for context.
        This is OPTIONAL and doesn't affect core trading logic.

        Returns dict with yesterday's stats or empty dict if unavailable.
        """
        if not hasattr(self.dm, 'supabase') or not self.dm.supabase:
            return {}

        try:
            if hasattr(self.dm, "query_yesterday_bars"):
                # New method available - use it!
                bars = self.dm.query_yesterday_bars (
                    self.symbol,
                    start_hour=9, start_min=30,
                    end_hour=16, end_min=0
                )
            else:
                # Get yesterday's date
                yesterday = (datetime.now(ET_TZ) - timedelta(days=1)).strftime('%Y-%M-%d')

                # Query Supabase for yesterday's data
                bars = self.dm.get_historical_bars(
                    self.symbol,
                    f'{yesterday} 14:30:00+00',
                    f'{yesterday} 21:00:00+00'
                )

            if not bars:
                self.logger.debug('No yesterday bars available from Supabase')
                return {}

            # Calculate yesterday's stats
            highs = [float(b['high']) for b in bars]
            lows = [float(b['low']) for b in bars]

            stats = {
                'yesterday_high': max(highs),
                'yesterday_low': min(lows),
                'yesterday_range': max(highs) - min(lows),
                'yesterday_bars': len(bars)
            }

            self.logger.info(
                f"📊 Yesterday context: Range={stats['yesterday_range']:.2f} pts,"
                f"Bars={len(bars)}"
            )

            return stats

        except Exception as e:
            self.logger.warning(f"Could not get yesterday context: {e}")
            return {}

    # ============================================================================
    # COMPATIBILITY METHODS FOR trading_bot.py
    # ============================================================================
    
    def check_breakout(self, symbol: str, current_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Compatibility wrapper for trading_bot.py which calls check_breakout().
        
        ORB Retest doesn't use live current_price - it gets closed 5m candles itself.
        This method simply delegates to check_signal().
        
        Args:
            symbol: Trading symbol
            current_price: Ignored (kept for compatibility)
            
        Returns:
            Signal dict or None (same as check_signal)
        """
        return self.check_signal(symbol)
    
    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        """
        Compatibility method for trading_bot.py tick ingestion.
        
        ORB Retest doesn't use live ticks - it analyzes closed 5m candles.
        This is a no-op method provided for compatibility with trading_bot.py
        which calls ingest_tick() for all strategies.
        
        Args:
            symbol: Trading symbol
            ts_epoch: Timestamp
            price: Price (ignored)
        """
        pass  # No-op - ORB Retest uses closed candles, not live ticks
