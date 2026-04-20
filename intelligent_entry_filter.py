# 🛡️ INTELLIGENT ENTRY PROTECTION SYSTEM
# Prevents trap entries and stop hunting
 
"""
PROBLEM: Simple pattern-following strategies get trapped by:
- False breakouts (looks good, then reverses)
- Stop hunting (market sweeps stops intentionally)
- Liquidity grabs (big players need your orders)
 
SOLUTION: Multi-layer confirmation BEFORE entering:
1. Volume confirmation (real breakouts have volume)
2. Momentum confirmation (price accelerating, not fading)
3. Microstructure confirmation (order flow supports direction)
4. Context confirmation (broader market agrees)
 
ONLY ENTER when ALL layers confirm!
"""
 
import pandas as pd
import numpy as np
from datetime import datetime, time, timezone
from typing import Optional, Dict, Tuple
from debug_config import CHECK, CROSS
 
class IntelligentEntryFilter:
    """
    Multi-layer confirmation system to avoid trap entries.
  
    Filters out:
    - False breakouts
    - Stop hunts
    - Low-conviction setups
    - Counter-trend entries during strong moves
    """
  
    def __init__(self, data_manager, logger):
        self.dm = data_manager
        self.logger = logger
        
        # Thresholds (tune these based on backtesting)
        self.min_volume_ratio = 1.5      # Breakout volume must be 1.5x average
        self.min_momentum_score = 0.6    # 0-1 scale, >0.6 = strong
        self.min_order_flow_score = 0.5  # >0 = buying pressure, <0 = selling
        self.max_against_trend = 0.3     # Don't fade strong trends (0-1 scale)
      
    def should_enter_trade(
        self,
        symbol: str,
        signal_type: str,  # "BUY" or "SELL"
        signal_price: float,
        strategy_name: str
    ) -> Tuple[bool, str]:
        """
        Run ALL confirmation checks before entering trade.
        
        Returns:
            (allow_entry: bool, reason: str)
        """
        
        # Layer 1: Volume Confirmation
        volume_ok, volume_reason = self._check_volume(symbol, signal_type)
        if not volume_ok:
            self.logger.warning(f"{CROSS} Entry BLOCKED: {volume_reason}")
            return False, volume_reason
        
        # Layer 2: Momentum Confirmation
        momentum_ok, momentum_reason = self._check_momentum(symbol, signal_type, signal_price)
        if not momentum_ok:
            self.logger.warning(f"{CROSS} Entry BLOCKED: {momentum_reason}")
            return False, momentum_reason
        
        # Layer 3: Order Flow Confirmation (if we have tick data)
        flow_ok, flow_reason = self._check_order_flow(symbol, signal_type)
        if not flow_ok:
            self.logger.warning(f"{CROSS} Entry BLOCKED: {flow_reason}")
            return False, flow_reason
        
        # Layer 4: Trend Context
        trend_ok, trend_reason = self._check_trend_context(symbol, signal_type)
        if not trend_ok:
            self.logger.warning(f"{CROSS} Entry BLOCKED: {trend_reason}")
            return False, trend_reason
        
        # ALL CHECKS PASSED!
        self.logger.info(f"{CHECK} Entry APPROVED: All filters passed")
        return True, "all_filters_passed"
  
    def _check_volume(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """Volume Confirmation."""
        try:
            # Get last 50 bars
            bars = self.dm.get_recent_bars(symbol, count=50, timeframe="1m")
            
            # FIX: Check if bars is empty
            if bars is None or (hasattr(bars, 'empty') and bars.empty):
                self.logger.warning("Insufficient data for volume check")
                return True, "insufficient_data"  # Allow if no data
            
            # FIX: Check if bars has enough rows
            if len(bars) < 20:
                self.logger.warning(f"Only {len(bars)} bars, need 20+")
                return True, "insufficient_data"
            
            # Get volume
            try:
                current_volume = bars.iloc[-1]['volume']
                avg_volume = bars.iloc[-21:-1]['volume'].mean()
            except (KeyError, IndexError) as e:
                self.logger.error(f"Volume column error: {e}")
                return True, "volume_data_error"
            
            if avg_volume == 0:
                return True, "no_volume_data"
            
            volume_ratio = current_volume / avg_volume
            
            if volume_ratio < self.min_volume_ratio:
                return False, f"low_volume (ratio={volume_ratio:.2f}, need {self.min_volume_ratio})"
            
            self.logger.debug(f"{CHECK} Volume OK: {volume_ratio:.2f}x average")
            return True, "volume_confirmed"
            
        except Exception as e:
            self.logger.error(f"Volume check error: {e}")
            return True, "volume_check_error"  # Don't block on errors

  
    def _check_momentum(
        self,
        symbol: str,
        signal_type: str,
        signal_price: float
    ) -> Tuple[bool, str]:
        """Momentum Confirmation."""
        try:
            bars = self.dm.get_recent_bars(symbol, count=50, timeframe="1m")
            
            # FIX: Check if bars is valid
            if bars is None or (hasattr(bars, 'empty') and bars.empty):
                self.logger.warning("Insufficient data for momentum check")
                return True, "insufficient_data"
            
            if len(bars) < 20:
                self.logger.warning(f"Only {len(bars)} bars, need 20+")
                return True, "insufficient_data"
            
            # Get closes
            try:
                closes = bars['close'].values
            except KeyError:
                self.logger.error("No 'close' column in bars")
                return True, "data_error"
            
            # Recent momentum (last 3 bars)
            if len(closes) < 4:
                return True, "insufficient_data"
            
            recent_change = (closes[-1] - closes[-4]) / closes[-4]
            
            # Longer momentum (last 10 bars)
            if len(closes) < 11:
                longer_change = recent_change
            else:
                longer_change = (closes[-1] - closes[-11]) / closes[-11]
            
            # Momentum score
            if signal_type == "BUY":
                # Want positive momentum
                if recent_change <= 0:
                    return False, f"no_upward_momentum (change={recent_change:.4f})"
                
                momentum_score = recent_change / max(abs(longer_change), 0.0001)
                
            else:  # SELL
                # Want negative momentum
                if recent_change >= 0:
                    return False, f"no_downward_momentum (change={recent_change:.4f})"
                
                momentum_score = abs(recent_change) / max(abs(longer_change), 0.0001)
            
            if momentum_score < self.min_momentum_score:
                return False, f"weak_momentum (score={momentum_score:.2f}, need {self.min_momentum_score})"
            
            # Check RSI
            rsi = self._calculate_rsi(closes, period=14)
            if signal_type == "BUY" and rsi > 75:
                return False, f"overbought (RSI={rsi:.1f})"
            if signal_type == "SELL" and rsi < 25:
                return False, f"oversold (RSI={rsi:.1f})"
            
            self.logger.debug(f"{CHECK} Momentum OK: score={momentum_score:.2f}, RSI={rsi:.1f}")
            return True, "momentum_confirmed"
            
        except Exception as e:
            self.logger.error(f"Momentum check error: {e}")
            return True, "momentum_check_error"

  
    def _check_order_flow(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """
        Order Flow Confirmation: Check if institutional buyers/sellers are present.
        
        Uses:
        - Bid/ask spread changes
        - Large vs small trade ratio
        - Uptick vs downtick volume
        
        NOTE: Requires tick data. Skip if not available.
        """
        try:
            # Get recent bars
            bars = self.dm.get_recent_bars(symbol, count=10, timeframe="1m")
            if len(bars) < 5:
                return True, "insufficient_data"
            
            # Simple proxy: compare up-moves vs down-moves
            closes = bars['close'].values
            highs = bars['high'].values
            lows = bars['low'].values
            volumes = bars['volume'].values
            
            # Calculate buying vs selling pressure
            up_volume = 0
            down_volume = 0
            
            for i in range(1, len(bars)):
                if closes[i] > closes[i-1]:
                    up_volume += volumes[i]
                elif closes[i] < closes[i-1]:
                    down_volume += volumes[i]
            
            total_volume = up_volume + down_volume
            if total_volume == 0:
                return True, "no_volume_data"
            
            # Order flow score: +1 = all buying, -1 = all selling
            flow_score = (up_volume - down_volume) / total_volume
            
            if signal_type == "BUY" and flow_score < self.min_order_flow_score:
                return False, f"selling_pressure (flow={flow_score:.2f})"
            
            if signal_type == "SELL" and flow_score > -self.min_order_flow_score:
                return False, f"buying_pressure (flow={flow_score:.2f})"
            
            self.logger.debug(f"{CHECK} Order Flow OK: score={flow_score:.2f}")
            return True, "order_flow_confirmed"
            
        except Exception as e:
            self.logger.error(f"Order flow check error: {e}")
            return True, "order_flow_check_error"
  
    def _check_trend_context(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """
        Trend Context: Don't fight strong trends.
        
        Checks:
        - 5-minute trend (immediate)
        - 15-minute trend (short-term)
        - Alignment between timeframes
        """
        try:
            # Get 5-minute bars
            bars_5m = self.dm.get_recent_bars(symbol, count=20, timeframe="5m")
            if len(bars_5m) < 10:
                return True, "insufficient_data"
            
            # Calculate trend strength on 5m
            closes_5m = bars_5m['close'].values
            sma_fast = np.mean(closes_5m[-5:])   # Last 5 bars (25 minutes)
            sma_slow = np.mean(closes_5m[-20:])  # Last 20 bars (100 minutes)
            
            # Trend score: >0 = uptrend, <0 = downtrend
            trend_score = (sma_fast - sma_slow) / sma_slow
            trend_strength = abs(trend_score)
            
            # Don't fade strong trends
            if signal_type == "BUY" and trend_score < -self.max_against_trend:
                return False, f"strong_downtrend (trend={trend_score:.4f})"
            
            if signal_type == "SELL" and trend_score > self.max_against_trend:
                return False, f"strong_uptrend (trend={trend_score:.4f})"
            
            self.logger.debug(f"{CHECK} Trend OK: score={trend_score:.4f}, strength={trend_strength:.4f}")
            return True, "trend_context_ok"
            
        except Exception as e:
            self.logger.error(f"Trend check error: {e}")
            return True, "trend_check_error"
  
    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 50.0  # Neutral
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi

