"""
MARKET REGIME DETECTOR
======================

PURPOSE:
    Sits BETWEEN strategy signals and entry filters to provide market context.
    
    Instead of blocking trades blindly, we UNDERSTAND the market state and
    adapt our approach:
    
    - Accumulation phase? Weak momentum is NORMAL → Lower thresholds
    - Stop hunt detected? Wait for reversal → Strict thresholds
    - Strong trend? Need confirmation → Higher thresholds
    - Ranging market? Mean reversion works → Medium thresholds

ARCHITECTURE:
    
    Strategy Signal → [REGIME DETECTOR] → Adaptive Filter → Trade
                            ↓
                      Detects market state
                      Recommends thresholds
                      Provides confidence

REGIMES DETECTED:
    1. ACCUMULATION: Smart money quietly buying (weak momentum + increasing volume)
    2. DISTRIBUTION: Smart money selling (weak momentum + price at resistance)
    3. TRENDING: Strong directional move (high momentum + aligned MAs)
    4. RANGING: Choppy, no clear direction (low volatility + mean-reverting)
    5. BREAKOUT_PENDING: Range compression before expansion
    6. STOP_HUNT: Liquidity grab (spike + immediate reversal)

USAGE:
    detector = MarketRegimeDetector(data_manager, logger)
    regime_info = detector.detect_regime(symbol, signal_type, signal_context)
    
    # Use regime to adapt filter thresholds
    adapted_thresholds = regime_info['recommended_thresholds']
"""

import numpy as np
from typing import Dict, Tuple, Optional
from datetime import datetime
from debug_config import CHECK, CROSS, CHART


class MarketRegimeDetector:
   """
   Detects current market regime to adapt trading behavior.
  
   FIXED: Safe division, better handling of missing data.
   """
  
   def __init__(self, data_manager, logger):
       self.dm = data_manager
       self.logger = logger
      
       # Regime detection thresholds
       self.config = {
           'accumulation': {
               'max_momentum': 0.40,
               'min_volume_increase': 1.05,  # Lowered from 1.1
               'min_higher_lows': 2,
           },
           'distribution': {
               'max_momentum': 0.40,
               'min_volume_spike': 1.3,  # Lowered from 1.5
               'min_lower_highs': 2,
           },
           'trending': {
               'min_momentum': 0.50,
               'min_trend_score': 0.003,
           },
           'ranging': {
               'max_volatility': 0.015,
               'max_trend_score': 0.001,
           },
           'stop_hunt': {
               'min_spike_size': 0.005,
               'max_reversal_time': 3,
           }
       }
  
   def detect_regime(
       self,
       symbol: str,
       signal_type: str,
       signal_context: Optional[Dict] = None
   ) -> Dict:
       """
       Detect current market regime and return adaptive recommendations.
       """
      
       try:
           # Get market data
           bars_1m = self.dm.get_recent_bars(symbol, count=50, timeframe="1m")
           bars_5m = self.dm.get_recent_bars(symbol, count=20, timeframe="5m")
          
           if bars_1m is None or len(bars_1m) < 20:
               return self._default_regime()
          
           # Calculate regime indicators
           momentum = self._calculate_momentum(bars_1m)
           volume_profile = self._analyze_volume(bars_1m)
           structure = self._analyze_structure(bars_1m)
           trend = self._analyze_trend(bars_5m) if bars_5m is not None else 0.0
           volatility = self._calculate_volatility(bars_1m)
          
           # Check for strong pattern override first
           trigger = (signal_context or {}).get('trigger', '')
           has_strong_pattern = trigger in [
               'engulf/hammer/HL-break',
               'engulf/star/LH-break'
           ]
          
           # Detect regimes (priority order matters!)
          
           # 1. Stop Hunt (highest priority)
           stop_hunt_detected, stop_hunt_conf = self._is_stop_hunt(bars_1m)
           if stop_hunt_detected:
               return self._build_regime_info(
                   'STOP_HUNT',
                   stop_hunt_conf,
                   {'momentum': momentum, 'spike_detected': True},
                   'fade_initial_move',
                   'Liquidity grab detected - wait for reversal confirmation',
                   {
                       'min_momentum_score': 0.50,
                       'min_volume_ratio': 1.5,
                       'min_order_flow_score': 0.3,
                       'max_against_trend': 0.001
                   }
               )
          
           # 2. Accumulation (RELAXED for strong patterns!)
           accumulation_detected, accum_conf = self._is_accumulation(
               momentum, volume_profile, structure, signal_type
           )
           if accumulation_detected:
               # ✅ FIX: Lower threshold if strong pattern
               momentum_threshold = 0.20 if has_strong_pattern else 0.25
              
               return self._build_regime_info(
                   'ACCUMULATION',
                   accum_conf,
                   {
                       'momentum': momentum,
                       'volume_trend': volume_profile.get('trend', 'unknown'),
                       'structure': 'higher_lows' if structure > 0 else 'consolidating',
                       'strong_pattern': has_strong_pattern
                   },
                   'look_for_longs' if signal_type == 'BUY' else 'wait',
                   f'Smart money accumulating - weak momentum is expected{"  + STRONG PATTERN" if has_strong_pattern else ""}',
                   {
                       'min_momentum_score': momentum_threshold,
                       'min_volume_ratio': 0.9,  # Very relaxed
                       'min_order_flow_score': 0.0,  # Don't check
                       'max_against_trend': 0.004
                   }
               )
          
           # 3. Distribution
           distribution_detected, dist_conf = self._is_distribution(
               momentum, volume_profile, structure, signal_type
           )
           if distribution_detected:
               momentum_threshold = 0.20 if has_strong_pattern else 0.25
              
               return self._build_regime_info(
                   'DISTRIBUTION',
                   dist_conf,
                   {
                       'momentum': momentum,
                       'volume_trend': volume_profile.get('trend', 'unknown'),
                       'structure': 'lower_highs' if structure < 0 else 'topping',
                       'strong_pattern': has_strong_pattern
                   },
                   'look_for_shorts' if signal_type == 'SELL' else 'wait',
                   f'Smart money distributing{"  + STRONG PATTERN" if has_strong_pattern else ""}',
                   {
                       'min_momentum_score': momentum_threshold if signal_type == 'SELL' else 0.60,
                       'min_volume_ratio': 0.9,
                       'min_order_flow_score': -0.10 if signal_type == 'SELL' else 0.30,
                       'max_against_trend': 0.004
                   }
               )
          
           # 4. Strong Trending
           if abs(trend) > self.config['trending']['min_trend_score']:
               if momentum > self.config['trending']['min_momentum']:
                   trend_direction = 'UP' if trend > 0 else 'DOWN'
                   with_trend = (
                       (signal_type == 'BUY' and trend > 0) or
                       (signal_type == 'SELL' and trend < 0)
                   )
                  
                   return self._build_regime_info(
                       f'TRENDING_{trend_direction}',
                       0.80,
                       {
                           'momentum': momentum,
                           'trend_score': trend,
                           'with_trend': with_trend
                       },
                       'follow_trend' if with_trend else 'wait_for_pullback',
                       f'Strong {trend_direction} trend - {"trade with it" if with_trend else "wait for pullback"}',
                       {
                           'min_momentum_score': 0.35 if with_trend else 0.50,
                           'min_volume_ratio': 1.1,
                           'min_order_flow_score': 0.10,
                           'max_against_trend': 0.002 if with_trend else 0.0005
                       }
                   )
          
           # 5. Ranging Market - ✅ FIX: More lenient!
           if volatility < self.config['ranging']['max_volatility']:
               if abs(trend) < self.config['ranging']['max_trend_score']:
                   # ✅ FIX: Lower threshold if strong pattern
                   momentum_threshold = 0.20 if has_strong_pattern else 0.25
                  
                   return self._build_regime_info(
                       'RANGING',
                       0.75,
                       {
                           'momentum': momentum,
                           'volatility': volatility,
                           'trend_score': trend,
                           'strong_pattern': has_strong_pattern
                       },
                       'mean_reversion',
                       f'Choppy ranging market{"  + STRONG PATTERN" if has_strong_pattern else ""}',
                       {
                           'min_momentum_score': momentum_threshold,
                           'min_volume_ratio': 0.9,  # Lowered
                           'min_order_flow_score': 0.0,  # Don't check
                           'max_against_trend': 0.003
                       }
                   )
          
           # 6. Default (uncertain) - ✅ FIX: Still allow strong patterns!
           return self._build_regime_info(
               'NEUTRAL',
               0.50,
               {
                   'momentum': momentum,
                   'volatility': volatility,
                   'trend_score': trend,
                   'strong_pattern': has_strong_pattern
               },
               'standard_filters',
               f'No clear regime{"  + STRONG PATTERN" if has_strong_pattern else ""}',
               {
                   'min_momentum_score': 0.20 if has_strong_pattern else 0.30,
                   'min_volume_ratio': 1.0,
                   'min_order_flow_score': 0.05,
                   'max_against_trend': 0.003
               }
           )
          
       except Exception as e:
           self.logger.error(f"Regime detection error: {e}", exc_info=True)
           return self._default_regime()
  
   def _is_accumulation(
       self,
       momentum: float,
       volume_profile: Dict,
       structure: float,
       signal_type: str
   ) -> Tuple[bool, float]:
       """Detect accumulation phase."""
      
       if signal_type != 'BUY':
           return False, 0.0
      
       confidence = 0.0
      
       # Weak momentum (expected during accumulation)
       if momentum < self.config['accumulation']['max_momentum']:
           confidence += 0.35
      
       # Volume increasing (safe check)
       vol_trend = volume_profile.get('trend', 'unknown')
       if vol_trend == 'increasing':
           confidence += 0.35
       elif vol_trend == 'stable':
           confidence += 0.15  # Partial credit
      
       # Higher lows structure
       if structure > 0:
           confidence += 0.30
      
       detected = confidence > 0.60  # Lowered from 0.65
      
       if detected:
           self.logger.info(
               f"{CHART} REGIME: Accumulation detected "
               f"(momentum={momentum:.3f}, vol_trend={vol_trend}, "
               f"structure={structure:.3f}, confidence={confidence:.2f})"
           )
      
       return detected, confidence
  
   def _is_distribution(
       self,
       momentum: float,
       volume_profile: Dict,
       structure: float,
       signal_type: str
   ) -> Tuple[bool, float]:
       """Detect distribution phase."""
      
       if signal_type != 'SELL':
           return False, 0.0
      
       confidence = 0.0
      
       if momentum < self.config['distribution']['max_momentum']:
           confidence += 0.35
      
       spike_ratio = volume_profile.get('spike_ratio', 1.0)
       if spike_ratio > self.config['distribution']['min_volume_spike']:
           confidence += 0.35
      
       if structure < 0:
           confidence += 0.30
      
       detected = confidence > 0.60  # Lowered from 0.65
      
       if detected:
           self.logger.info(
               f"{CHART} REGIME: Distribution detected "
               f"(momentum={momentum:.3f}, vol_spike={spike_ratio:.2f}, "
               f"structure={structure:.3f}, confidence={confidence:.2f})"
           )
      
       return detected, confidence
  
   def _is_stop_hunt(self, bars) -> Tuple[bool, float]:
       """Detect stop hunt / liquidity grab."""
      
       if len(bars) < 5:
           return False, 0.0
      
       closes = bars['close'].values
       highs = bars['high'].values
       lows = bars['low'].values
      
       recent_range = np.max(highs[-10:-3]) - np.min(lows[-10:-3])
       if recent_range == 0:
           return False, 0.0
      
       spike_up = (highs[-3] - np.max(highs[-10:-3])) / recent_range
       spike_down = (np.min(lows[-10:-3]) - lows[-3]) / recent_range
      
       if spike_up > self.config['stop_hunt']['min_spike_size']:
           if closes[-1] < closes[-3]:
               self.logger.info(
                   f"{CHART} REGIME: Stop hunt detected (spike up + reversal down)"
               )
               return True, 0.85
      
       if spike_down > self.config['stop_hunt']['min_spike_size']:
           if closes[-1] > closes[-3]:
               self.logger.info(
                   f"{CHART} REGIME: Stop hunt detected (spike down + reversal up)"
               )
               return True, 0.85
      
       return False, 0.0
  
   def _calculate_momentum(self, bars) -> float:
       """Calculate momentum score."""
       if len(bars) < 11:
           return 0.0
      
       closes = bars['close'].values
       recent_change = (closes[-1] - closes[-4]) / closes[-4]
       longer_change = (closes[-1] - closes[-11]) / closes[-11]
      
       if abs(longer_change) < 0.0001:
           return 0.0
      
       return abs(recent_change) / abs(longer_change)
  
   def _analyze_volume(self, bars) -> Dict:
       """
       Analyze volume profile - ✅ FIXED: Safe division!
       """
       if len(bars) < 20:
           return {'trend': 'unknown', 'spike_ratio': 1.0}
      
       volumes = bars['volume'].values
       current_vol = volumes[-1]
      
       # ✅ FIX: Safe average calculation
       avg_vol = np.mean(volumes[-20:-1])
       if avg_vol == 0:
           spike_ratio = 1.0
       else:
           spike_ratio = current_vol / avg_vol
      
       # ✅ FIX: Safe trend calculation
       recent_avg = np.mean(volumes[-5:])
       older_avg = np.mean(volumes[-20:-15])
      
       if older_avg == 0 or np.isnan(older_avg):
           recent_trend = 1.0
       else:
           recent_trend = recent_avg / older_avg
      
       return {
           'trend': 'increasing' if recent_trend > 1.1 else 'decreasing' if recent_trend < 0.9 else 'stable',
           'spike_ratio': spike_ratio,
           'current_vs_avg': spike_ratio
       }
  
   def _analyze_structure(self, bars) -> float:
       """Analyze price structure."""
       if len(bars) < 10:
           return 0.0
      
       lows = bars['low'].values[-10:]
       highs = bars['high'].values[-10:]
      
       higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
       lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])
      
       return (higher_lows - lower_highs) / len(lows)
  
   def _analyze_trend(self, bars_5m) -> float:
       """Calculate trend score."""
       if bars_5m is None or len(bars_5m) < 20:
           return 0.0
      
       closes = bars_5m['close'].values
       sma_fast = np.mean(closes[-5:])
       sma_slow = np.mean(closes[-20:])
      
       if sma_slow == 0:
           return 0.0
      
       return (sma_fast - sma_slow) / sma_slow
  
   def _calculate_volatility(self, bars) -> float:
       """Calculate recent volatility."""
       if len(bars) < 20:
           return 0.0
      
       closes = bars['close'].values
       returns = np.diff(closes) / closes[:-1]
      
       return np.std(returns[-20:])
  
   def _build_regime_info(
       self,
       regime: str,
       confidence: float,
       characteristics: Dict,
       action: str,
       explanation: str,
       thresholds: Dict
   ) -> Dict:
       """Build regime info dictionary."""
       return {
           'regime': regime,
           'confidence': confidence,
           'characteristics': characteristics,
           'recommended_action': action,
           'explanation': explanation,
           'recommended_thresholds': thresholds
       }
  
   def _default_regime(self) -> Dict:
       """Return default regime when detection fails."""
       return self._build_regime_info(
           'NEUTRAL',
           0.50,
           {},
           'standard_filters',
           'Insufficient data for regime detection',
           {
               'min_momentum_score': 0.25,  # Lowered from 0.30
               'min_volume_ratio': 1.0,
               'min_order_flow_score': 0.0,
               'max_against_trend': 0.003
           }
       )

