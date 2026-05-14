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
 
THRESHOLD TUNING GUIDE:
  min_volume_ratio:      1.0 (permissive) → 2.0 (strict)
  min_momentum_score:    0.1 (permissive) → 0.8 (strict)
  min_order_flow_score:  0.1 (permissive) → 0.7 (strict)
  max_against_trend:     0.005 (permissive) → 0.0005 (strict)  ← NOTE: in % terms!
"""
 
import pandas as pd
import numpy as np
from datetime import datetime, time, timezone
from typing import Optional, Dict, Tuple
from debug_config import CHECK, CROSS
from market_regime_detector import MarketRegimeDetector
from config import Config
 
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
        cfg = getattr(self.dm, 'config', None) or Config()
        
        # Regime Detector
        self.regime_detector = MarketRegimeDetector(data_manager, logger)
        # ── THRESHOLDS ─────────────────────────────────────────────────────────
        # Tune these based on backtesting. See tuning guide in module docstring.
        #
        # VOLUME: current bar volume vs 20-bar average
        #   1.5 was too strict — most non-breakout bars are 0.8–1.2x average.
        #   1.1 catches genuine volume upticks without demanding a spike.
        # self.min_volume_ratio = 1.1
        self.min_volume_ratio    = float(getattr(cfg, "ENTRY_MIN_VOLUME_RATIO", 1.10))

        # MOMENTUM: ratio of (3-bar change) / (10-bar change)
        #   This is a *ratio*, not a percentage. When recent move aligns with
        #   the longer move it tends to sit between 0.5–3.0. Requiring 0.6
        #   was fine in theory but the direction check (recent_change <= 0)
        #   already blocks counter-moves — the ratio check adds little and
        #   often misfires when longer_change is tiny. Set low; raise if needed.
        # self.min_momentum_score = 0.2
        self.min_momentum_score  = float(getattr(cfg, "ENTRY_MIN_MOMENTUM",    0.20))

        # ORDER FLOW: (up_volume - down_volume) / total_volume  → range [-1, +1]
        #   0.5 meant 75% of bars had to close up — almost never true in chop.
        #   0.1 means just a slight net-buying bias, which is realistic.
        # self.min_order_flow_score = 0.1
        self.min_order_flow_score= float(getattr(cfg, "ENTRY_MIN_ORDER_FLOW",   0.10))

        # TREND: (sma_fast - sma_slow) / sma_slow  → expressed as a fraction
        #   e.g. 0.001 = price is 0.1% above the slow MA (a real trend signal).
        #   0.3 was in the wrong unit — it would require a 30% MA gap, never hit.
        #   0.002 blocks entries only when strongly trending against the signal.
        self.max_against_trend = 0.002

        # STRONG PATTERN OVERRIDE: bypass weak-momentum block for high-quality
        #   reversal patterns. Set to None to disable.
        self.strong_pattern_triggers = {
            'engulf/hammer/HL-break',
            'engulf/star/LH-break',
        }
        # ───────────────────────────────────────────────────────────────────────
      
    def should_enter_trade(
        self,
        symbol: str,
        signal_type: str,
        signal_price: float,
        strategy_name: str,
        signal_context: Optional[Dict] = None
    ) -> Tuple[bool, str]:
        """
        Run ALL confirmation checks with REGIME-ADAPTIVE thresholds.
        """
        
        # ⭐ NEW: Detect market regime FIRST
        regime_info = self.regime_detector.detect_regime(
            symbol, 
            signal_type, 
            signal_context
        )
        
        # Log regime detection
        self.logger.info(
            f"📊 REGIME: {regime_info['regime']} "
            f"(confidence={regime_info['confidence']:.2f}) - "
            f"{regime_info['explanation']}"
        )
        
        # ⭐ ADAPT THRESHOLDS based on regime
        original_thresholds = self._save_current_thresholds()
        self._apply_regime_thresholds(regime_info['recommended_thresholds'])
        
        try:
            # Run existing filter checks (now with adapted thresholds!)
            
            # Layer 1: Volume
            volume_ok, volume_reason = self._check_volume(symbol, signal_type)
            if not volume_ok:
                self.logger.warning(f"{CROSS} Entry BLOCKED: {volume_reason}")
                return False, volume_reason
            
            # Layer 2: Momentum
            momentum_ok, momentum_reason = self._check_momentum(
                symbol, signal_type, signal_price, signal_context
            )
            if not momentum_ok:
                self.logger.warning(f"{CROSS} Entry BLOCKED: {momentum_reason}")
                return False, momentum_reason
            
            # Layer 3: Order Flow
            flow_ok, flow_reason = self._check_order_flow(symbol, signal_type)
            if not flow_ok:
                self.logger.warning(f"{CROSS} Entry BLOCKED: {flow_reason}")
                return False, flow_reason
            
            # Layer 4: Trend
            trend_ok, trend_reason = self._check_trend_context(symbol, signal_type)
            if not trend_ok:
                self.logger.warning(f"{CROSS} Entry BLOCKED: {trend_reason}")
                return False, trend_reason
            
            # ALL CHECKS PASSED!
            self.logger.info(
                f"{CHECK} Entry APPROVED: All filters passed "
                f"(regime={regime_info['regime']})"
            )
            return True, f"approved_in_{regime_info['regime'].lower()}_regime"
        
        finally:
            # ⭐ Restore original thresholds for next signal
            self._restore_thresholds(original_thresholds)


    def _save_current_thresholds(self) -> Dict:
        """Save current thresholds before modifying."""
        return {
            'min_volume_ratio': self.min_volume_ratio,
            'min_momentum_score': self.min_momentum_score,
            'min_order_flow_score': self.min_order_flow_score,
            'max_against_trend': self.max_against_trend
        }


    def _apply_regime_thresholds(self, regime_thresholds: Dict):
        """Apply regime-specific thresholds."""
        self.min_volume_ratio = regime_thresholds.get('min_volume_ratio', self.min_volume_ratio)
        self.min_momentum_score = regime_thresholds.get('min_momentum_score', self.min_momentum_score)
        self.min_order_flow_score = regime_thresholds.get('min_order_flow_score', self.min_order_flow_score)
        self.max_against_trend = regime_thresholds.get('max_against_trend', self.max_against_trend)
        
        self.logger.debug(
            f"Applied regime thresholds: "
            f"momentum={self.min_momentum_score:.2f}, "
            f"volume={self.min_volume_ratio:.2f}, "
            f"flow={self.min_order_flow_score:.2f}"
        )


    def _restore_thresholds(self, saved_thresholds: Dict):
        """Restore original thresholds."""
        self.min_volume_ratio = saved_thresholds['min_volume_ratio']
        self.min_momentum_score = saved_thresholds['min_momentum_score']
        self.min_order_flow_score = saved_thresholds['min_order_flow_score']
        self.max_against_trend = saved_thresholds['max_against_trend']

  
    def _check_volume(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """Volume Confirmation."""
        try:
            bars = self.dm.get_recent_bars(symbol, count=50, timeframe="1m")
            
            if bars is None or (hasattr(bars, 'empty') and bars.empty):
                self.logger.warning("Insufficient data for volume check")
                return True, "insufficient_data"
            
            if len(bars) < 20:
                self.logger.warning(f"Only {len(bars)} bars, need 20+")
                return True, "insufficient_data"
            
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
            return True, "volume_check_error"

  
    def _check_momentum(
        self,
        symbol: str,
        signal_type: str,
        signal_price: float,
        signal_context: Optional[Dict] = None,
    ) -> Tuple[bool, str]:
        """
        Momentum Confirmation - FIXED VERSION.
        
        ✅ Strong-pattern override now works PROPERLY
        ✅ Doesn't block on tiny opposite-direction moves
        """
        try:
            bars = self.dm.get_recent_bars(symbol, count=50, timeframe="1m")
            
            if bars is None or (hasattr(bars, 'empty') and bars.empty):
                self.logger.warning("Insufficient data for momentum check")
                return True, "insufficient_data"
            
            if len(bars) < 20:
                self.logger.warning(f"Only {len(bars)} bars, need 20+")
                return True, "insufficient_data"
            
            try:
                closes = bars['close'].values
            except KeyError:
                self.logger.error("No 'close' column in bars")
                return True, "data_error"
            
            if len(closes) < 4:
                return True, "insufficient_data"
            
            recent_change = (closes[-1] - closes[-4]) / closes[-4]
            
            longer_change = (
                (closes[-1] - closes[-11]) / closes[-11]
                if len(closes) >= 11
                else recent_change
            )
            
            # ✅ FIX: Check for strong pattern FIRST
            trigger = (signal_context or {}).get('trigger', '')
            has_strong_pattern = trigger in self.strong_pattern_triggers
            
            if signal_type == "BUY":
                # ✅ FIX: Allow SMALL negative moves for strong patterns
                if recent_change < -0.001:  # Only block if moving DOWN significantly
                    if has_strong_pattern:
                        self.logger.info(
                            f"{CHECK} Momentum override: strong pattern '{trigger}' "
                            f"(small opposite move {recent_change:.4f} ignored)"
                        )
                        return True, "strong_pattern_override"
                    
                    return False, f"no_upward_momentum (change={recent_change:.4f})"
                
                # Calculate momentum score
                if abs(longer_change) < 0.0001:
                    momentum_score = 0.0
                else:
                    momentum_score = recent_change / abs(longer_change)
                    
            else:  # SELL
                # ✅ FIX: Allow SMALL positive moves for strong patterns
                if recent_change > 0.001:  # Only block if moving UP significantly
                    if has_strong_pattern:
                        self.logger.info(
                            f"{CHECK} Momentum override: strong pattern '{trigger}' "
                            f"(small opposite move {recent_change:.4f} ignored)"
                        )
                        return True, "strong_pattern_override"
                    
                    return False, f"no_downward_momentum (change={recent_change:.4f})"
                
                # Calculate momentum score
                if abs(longer_change) < 0.0001:
                    momentum_score = 0.0
                else:
                    momentum_score = abs(recent_change) / abs(longer_change)
            
            # Check momentum score threshold
            if momentum_score < self.min_momentum_score:
                # ✅ Strong-pattern override for weak momentum
                if has_strong_pattern:
                    self.logger.info(
                        f"{CHECK} Momentum override: strong pattern '{trigger}' "
                        f"(score={momentum_score:.2f}, threshold={self.min_momentum_score})"
                    )
                    return True, "strong_pattern_override"
                
                return False, f"weak_momentum (score={momentum_score:.2f}, need {self.min_momentum_score})"
            
            # RSI extremes - widened ranges
            rsi = self._calculate_rsi(closes, period=14)
            
            # ✅ FIX: Don't block on RSI for strong patterns either!
            if signal_type == "BUY" and rsi > 80:
                if has_strong_pattern:
                    self.logger.info(
                        f"{CHECK} RSI override: strong pattern '{trigger}' (RSI={rsi:.1f})"
                    )
                    return True, "strong_pattern_override"
                return False, f"overbought (RSI={rsi:.1f})"
            
            if signal_type == "SELL" and rsi < 20:
                if has_strong_pattern:
                    self.logger.info(
                        f"{CHECK} RSI override: strong pattern '{trigger}' (RSI={rsi:.1f})"
                    )
                    return True, "strong_pattern_override"
                return False, f"oversold (RSI={rsi:.1f})"
            
            self.logger.debug(f"{CHECK} Momentum OK: score={momentum_score:.2f}, RSI={rsi:.1f}")
            return True, "momentum_confirmed"
            
        except Exception as e:
            self.logger.error(f"Momentum check error: {e}", exc_info=True)
            return True, "momentum_check_error"

  
    def _check_order_flow(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """
        Order Flow Confirmation: Check if institutional buyers/sellers are present.
        
        Score range: +1 (all buying) → -1 (all selling).
        Flat/choppy markets sit near 0; we only need slight directional bias.
        """
        try:
            bars = self.dm.get_recent_bars(symbol, count=10, timeframe="1m")
            if len(bars) < 5:
                return True, "insufficient_data"
            
            closes = bars['close'].values
            volumes = bars['volume'].values
            
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
            
            flow_score = (up_volume - down_volume) / total_volume
            
            if signal_type == "BUY" and flow_score < -self.min_order_flow_score:
                # Only block on *clear* selling pressure, not neutral flow
                return False, f"strong_selling_pressure (flow={flow_score:.2f})"
            
            if signal_type == "SELL" and flow_score > self.min_order_flow_score:
                return False, f"strong_buying_pressure (flow={flow_score:.2f})"
            
            self.logger.debug(f"{CHECK} Order Flow OK: score={flow_score:.2f}")
            return True, "order_flow_confirmed"
            
        except Exception as e:
            self.logger.error(f"Order flow check error: {e}")
            return True, "order_flow_check_error"
  
    def _check_trend_context(self, symbol: str, signal_type: str) -> Tuple[bool, str]:
        """
        Trend Context: Don't fight strong trends.

        trend_score = (sma_fast - sma_slow) / sma_slow

        This is a fractional deviation (e.g. 0.002 = 0.2% gap between MAs).
        max_against_trend must be set in the same units — NOT as a percentage
        integer. 0.002 is a sensible default for 1–5 min intraday charts.
        """
        try:
            bars_5m = self.dm.get_recent_bars(symbol, count=20, timeframe="5m")
            if len(bars_5m) < 10:
                return True, "insufficient_data"
            
            closes_5m = bars_5m['close'].values
            sma_fast = np.mean(closes_5m[-5:])
            sma_slow = np.mean(closes_5m[-20:])
            
            trend_score = (sma_fast - sma_slow) / sma_slow
            
            if signal_type == "BUY" and trend_score < -self.max_against_trend:
                return False, f"strong_downtrend (trend={trend_score:.4f})"
            
            if signal_type == "SELL" and trend_score > self.max_against_trend:
                return False, f"strong_uptrend (trend={trend_score:.4f})"
            
            self.logger.debug(
                f"{CHECK} Trend OK: score={trend_score:.4f} "
                f"(threshold=±{self.max_against_trend})"
            )
            return True, "trend_context_ok"
            
        except Exception as e:
            self.logger.error(f"Trend check error: {e}")
            return True, "trend_check_error"
  
    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate RSI indicator."""
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