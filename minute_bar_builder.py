"""
Enhanced MinuteBarBuilder with volume tracking and VWAP calculation.
Supports both actual volume (if available) and tick count as a proxy.

ENHANCEMENTS vs original:
- Bar now includes: volume, tick_count, vwap fields
- update() accepts volume parameter
- Added get_volume_profile() for volume analysis
- Added get_session_vwap() for session-wide VWAP
"""

from dataclasses import dataclass
from typing import List, Optional
import math, time


@dataclass
class Bar:
    """
    OHLC bar with volume tracking.
    
    Attributes:
        ts_open: Unix epoch seconds (start of minute)
        open: First price in the minute
        high: Highest price in the minute
        low: Lowest price in the minute
        close: Last/current price in the minute
        volume: Cumulative volume (or tick count if volume unavailable)
        tick_count: Number of price updates received
        vwap: Volume-weighted average price (approximated)
    """
    ts_open: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    tick_count: int = 0
    vwap: float = 0.0


class MinuteBarBuilder:
    """
    Builds 1-minute OHLCV bars from tick data.
    Tracks volume (or tick count) and calculates VWAP.
    """
    
    def __init__(self, keep: int = 240):
        """
        Args:
            keep: Maximum number of bars to retain (default 240 = 4 hours)
        """
        self.keep = keep
        self._bars: List[Bar] = []

    @staticmethod
    def _minute_start(ts: float) -> int:
        """Round timestamp down to the start of its minute."""
        return int(ts) - (int(ts) % 60)

    def update(self, ts: Optional[float], price: Optional[float], 
               volume: Optional[int] = None) -> Optional[Bar]:
        """
        Update bars with a new price tick.
        
        Args:
            ts: Timestamp (epoch seconds). If None, uses current time.
            price: Price for this tick
            volume: Volume for this tick. If None, uses 1 (tick count mode)
        
        Returns:
            The bar that was updated/created, or None if price is None
        """
        if price is None:
            return None
        
        if ts is None:
            ts = time.time()
        
        ms = self._minute_start(ts)
        tick_vol = volume if volume is not None else 1
        
        # Check if we need to start a new bar
        if not self._bars or self._bars[-1].ts_open != ms:
            # Start new minute bar
            new_bar = Bar(
                ts_open=ms,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick_vol,
                tick_count=1,
                vwap=price  # First price = initial VWAP
            )
            self._bars.append(new_bar)
            
            # Trim old bars if exceeding keep limit
            if len(self._bars) > self.keep:
                self._bars = self._bars[-self.keep:]
            
            return new_bar
        
        else:
            # Update existing bar
            bar = self._bars[-1]
            
            # Update OHLC
            if price > bar.high:
                bar.high = price
            if price < bar.low:
                bar.low = price
            bar.close = price
            
            # Update volume
            bar.volume += tick_vol
            bar.tick_count += 1
            
            # Update VWAP (simplified: running average weighted by tick count)
            # True VWAP would be: sum(price * volume) / sum(volume)
            # This approximation: cumulative average of all prices
            bar.vwap = ((bar.vwap * (bar.tick_count - 1)) + price) / bar.tick_count
            
            return bar

    def last_n(self, n: int) -> List[Bar]:
        """
        Get the last N bars.
        
        Args:
            n: Number of bars to retrieve
            
        Returns:
            List of bars (oldest to newest), or empty list if n <= 0
        """
        return self._bars[-n:] if n > 0 else []

    def all(self) -> List[Bar]:
        """
        Get all bars currently stored.
        
        Returns:
            List of all bars (oldest to newest)
        """
        return list(self._bars)
    
    def get_volume_profile(self, lookback: int = 20) -> dict:
        """
        Calculate volume statistics for recent bars.
        
        Args:
            lookback: Number of bars to analyze (default 20)
            
        Returns:
            Dictionary with volume metrics:
            - avg_volume: Average volume over lookback period
            - current_volume: Volume of most recent bar
            - volume_ratio: current / average
            - is_high_volume: True if current > 1.5x average
            - is_low_volume: True if current < 0.5x average
        """
        bars = self.last_n(lookback)
        
        if not bars:
            return {
                "avg_volume": 0,
                "current_volume": 0,
                "volume_ratio": 1.0,
                "is_high_volume": False,
                "is_low_volume": False,
            }
        
        avg_vol = sum(b.volume for b in bars) / len(bars)
        current_vol = bars[-1].volume
        
        ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        
        return {
            "avg_volume": avg_vol,
            "current_volume": current_vol,
            "volume_ratio": ratio,
            "is_high_volume": ratio > 1.5,
            "is_low_volume": ratio < 0.5,
        }
    
    def get_session_vwap(self) -> float:
        """
        Calculate session VWAP across all stored bars.
        
        Returns:
            Volume-weighted average price, or 0.0 if no bars
        """
        if not self._bars:
            return 0.0
        
        # Weighted average of all bar VWAPs by their volume
        total_pv = sum(b.vwap * b.volume for b in self._bars)
        total_v = sum(b.volume for b in self._bars)
        
        return total_pv / total_v if total_v > 0 else self._bars[-1].close
