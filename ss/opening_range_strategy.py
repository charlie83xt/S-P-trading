"""
Opening Range Breakthrough Strategy Implementation.
This strategy identifies the opening range and generates signals when price breaks above or below this range.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
from enum import Enum

from data_manager import DataManager
from config import get_config

logger = logging.getLogger(__name__)

class SignalType(Enum):
    """Enumeration for signal types."""
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    NO_SIGNAL = "NO_SIGNAL"

@dataclass
class TradingSignal:
    """Data class for trading signals."""
    signal_type: SignalType
    symbol: str
    price: float
    timestamp: datetime
    confidence: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: Optional[float] = None
    reason: str = ""

@dataclass
class OpeningRange:
    """Data class for opening range information."""
    symbol: str
    date: str
    high: float
    low: float
    range_size: float
    range_size_pct: float
    volume: float
    start_time: datetime
    end_time: datetime
    is_valid: bool = True

class OpeningRangeStrategy:
    """
    Opening Range Breakthrough Strategy.
    
    This strategy:
    1. Identifies the opening range (high/low) during the first N minutes of trading
    2. Generates long signals when price breaks above the opening range high
    3. Generates short signals when price breaks below the opening range low
    4. Implements profit targets and stop losses based on range size
    """
    
    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager
        self.config = get_config()
        self.opening_ranges: Dict[str, OpeningRange] = {}
        self.active_positions: Dict[str, Dict] = {}
        self.daily_pnl: float = 0.0
        self.trade_count: int = 0
        
        logger.info("Opening Range Strategy initialized")
    
    def calculate_opening_range(self, symbol: str, date: datetime) -> Optional[OpeningRange]:
        """
        Calculate the opening range for a given symbol and date.
        
        Args:
            symbol: Trading symbol
            date: Date to calculate opening range for
            
        Returns:
            OpeningRange object or None if calculation fails
        """
        try:
            # Calculate opening range using data manager
            range_data = self.data_manager.calculate_opening_range(
                symbol=symbol,
                date=date,
                range_minutes=self.config.opening_range_minutes
            )
            
            if not range_data:
                return None
            
            # Create OpeningRange object
            opening_range = OpeningRange(
                symbol=symbol,
                date=range_data['date'],
                high=range_data['high_price'],
                low=range_data['low_price'],
                range_size=range_data['range_size'],
                range_size_pct=range_data['range_size_pct'],
                volume=range_data['volume'],
                start_time=datetime.fromtimestamp(range_data['range_start'] / 1000),
                end_time=datetime.fromtimestamp(range_data['range_end'] / 1000)
            )
            
            # Validate opening range
            opening_range.is_valid = self._validate_opening_range(opening_range)
            
            if opening_range.is_valid:
                self.opening_ranges[symbol] = opening_range
                logger.info(f"Opening range calculated for {symbol}: {opening_range.low:.4f} - {opening_range.high:.4f}")
            else:
                logger.warning(f"Invalid opening range for {symbol}: range too small or insufficient volume")
            
            return opening_range
            
        except Exception as e:
            logger.error(f"Error calculating opening range for {symbol}: {e}")
            return None
    
    def _validate_opening_range(self, opening_range: OpeningRange) -> bool:
        """
        Validate if the opening range meets minimum criteria.
        
        Args:
            opening_range: OpeningRange to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Check minimum range size
        if opening_range.range_size_pct < self.config.min_range_size * 100:
            return False
        
        # Check for sufficient volume if volume confirmation is enabled
        if self.config.volume_confirmation and opening_range.volume <= 0:
            return False
        
        # Check that high and low are different
        if opening_range.high <= opening_range.low:
            return False
        
        return True
    
    def generate_signal(self, symbol: str, current_price: float, 
                       current_time: datetime) -> TradingSignal:
        """
        Generate trading signal based on current market conditions.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_time: Current timestamp
            
        Returns:
            TradingSignal object
        """
        try:
            # Check if we have a valid opening range for today
            today = current_time.strftime('%Y-%m-%d')
            
            if symbol not in self.opening_ranges:
                # Try to calculate opening range for today
                self.calculate_opening_range(symbol, current_time)
            
            if symbol not in self.opening_ranges or not self.opening_ranges[symbol].is_valid:
                return TradingSignal(
                    signal_type=SignalType.NO_SIGNAL,
                    symbol=symbol,
                    price=current_price,
                    timestamp=current_time,
                    confidence=0.0,
                    reason="No valid opening range available"
                )
            
            opening_range = self.opening_ranges[symbol]
            
            # Check if we're still in the opening range period
            if current_time <= opening_range.end_time:
                return TradingSignal(
                    signal_type=SignalType.NO_SIGNAL,
                    symbol=symbol,
                    price=current_price,
                    timestamp=current_time,
                    confidence=0.0,
                    reason="Still in opening range period"
                )
            
            # Check for existing position
            if symbol in self.active_positions:
                return self._check_exit_conditions(symbol, current_price, current_time)
            
            # Check for breakthrough signals
            return self._check_breakthrough_signals(symbol, current_price, current_time, opening_range)
            
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=0.0,
                reason=f"Error: {str(e)}"
            )
    
    def _check_breakthrough_signals(self, symbol: str, current_price: float,
                                  current_time: datetime, opening_range: OpeningRange) -> TradingSignal:
        """
        Check for breakthrough signals above or below the opening range.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_time: Current timestamp
            opening_range: Opening range data
            
        Returns:
            TradingSignal object
        """
        # Long signal: price breaks above opening range high
        if current_price > opening_range.high:
            confidence = self._calculate_signal_confidence(
                current_price, opening_range.high, opening_range, "long"
            )
            
            if confidence >= 0.6:  # Minimum confidence threshold
                stop_loss = opening_range.low
                take_profit = opening_range.high + (opening_range.range_size * self.config.profit_target_multiplier)
                
                return TradingSignal(
                    signal_type=SignalType.LONG,
                    symbol=symbol,
                    price=current_price,
                    timestamp=current_time,
                    confidence=confidence,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_size=self._calculate_position_size(symbol, current_price, stop_loss),
                    reason=f"Breakthrough above opening range high ({opening_range.high:.4f})"
                )
        
        # Short signal: price breaks below opening range low
        elif current_price < opening_range.low:
            confidence = self._calculate_signal_confidence(
                current_price, opening_range.low, opening_range, "short"
            )
            
            if confidence >= 0.6:  # Minimum confidence threshold
                stop_loss = opening_range.high
                take_profit = opening_range.low - (opening_range.range_size * self.config.profit_target_multiplier)
                
                return TradingSignal(
                    signal_type=SignalType.SHORT,
                    symbol=symbol,
                    price=current_price,
                    timestamp=current_time,
                    confidence=confidence,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_size=self._calculate_position_size(symbol, current_price, stop_loss),
                    reason=f"Breakthrough below opening range low ({opening_range.low:.4f})"
                )
        
        return TradingSignal(
            signal_type=SignalType.NO_SIGNAL,
            symbol=symbol,
            price=current_price,
            timestamp=current_time,
            confidence=0.0,
            reason="Price within opening range"
        )
    
    def _calculate_signal_confidence(self, current_price: float, breakthrough_level: float,
                                   opening_range: OpeningRange, direction: str) -> float:
        """
        Calculate confidence score for a breakthrough signal.
        
        Args:
            current_price: Current market price
            breakthrough_level: Price level that was broken
            opening_range: Opening range data
            direction: "long" or "short"
            
        Returns:
            Confidence score between 0 and 1
        """
        try:
            # Base confidence from breakthrough distance
            breakthrough_distance = abs(current_price - breakthrough_level)
            distance_score = min(breakthrough_distance / opening_range.range_size, 1.0)
            
            # Range size score (larger ranges are more reliable)
            range_score = min(opening_range.range_size_pct / 2.0, 1.0)  # Normalize to 2% max
            
            # Volume score (if volume confirmation is enabled)
            volume_score = 1.0
            if self.config.volume_confirmation:
                # This would require additional volume analysis
                # For now, use a default score
                volume_score = 0.8
            
            # Time score (earlier in the day is better)
            current_hour = datetime.now().hour
            if current_hour < 12:
                time_score = 1.0
            elif current_hour < 16:
                time_score = 0.8
            else:
                time_score = 0.6
            
            # Combine scores
            confidence = (distance_score * 0.4 + range_score * 0.3 + 
                         volume_score * 0.2 + time_score * 0.1)
            
            return min(confidence, 1.0)
            
        except Exception as e:
            logger.error(f"Error calculating signal confidence: {e}")
            return 0.0
    
    def _calculate_position_size(self, symbol: str, entry_price: float, stop_loss: float) -> float:
        """
        Calculate position size based on risk management rules.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price for the position
            stop_loss: Stop loss price
            
        Returns:
            Position size
        """
        try:
            # Calculate risk per share
            risk_per_share = abs(entry_price - stop_loss)
            
            # Use default position size for now
            # In a real implementation, this would consider account balance and risk limits
            position_size = self.config.default_position_size
            
            # Ensure position size doesn't exceed maximum
            position_size = min(position_size, self.config.max_position_size)
            
            return position_size
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return self.config.default_position_size
    
    def _check_exit_conditions(self, symbol: str, current_price: float,
                             current_time: datetime) -> TradingSignal:
        """
        Check if existing position should be closed.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_time: Current timestamp
            
        Returns:
            TradingSignal object
        """
        if symbol not in self.active_positions:
            return TradingSignal(
                signal_type=SignalType.NO_SIGNAL,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=0.0,
                reason="No active position"
            )
        
        position = self.active_positions[symbol]
        
        # Check stop loss
        if position['direction'] == 'long' and current_price <= position['stop_loss']:
            return TradingSignal(
                signal_type=SignalType.CLOSE_LONG,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=1.0,
                reason="Stop loss hit"
            )
        elif position['direction'] == 'short' and current_price >= position['stop_loss']:
            return TradingSignal(
                signal_type=SignalType.CLOSE_SHORT,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=1.0,
                reason="Stop loss hit"
            )
        
        # Check take profit
        if position['direction'] == 'long' and current_price >= position['take_profit']:
            return TradingSignal(
                signal_type=SignalType.CLOSE_LONG,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=1.0,
                reason="Take profit hit"
            )
        elif position['direction'] == 'short' and current_price <= position['take_profit']:
            return TradingSignal(
                signal_type=SignalType.CLOSE_SHORT,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=1.0,
                reason="Take profit hit"
            )
        
        # Check time-based exit (end of day)
        if current_time.hour >= 23:  # Close positions before market close
            signal_type = SignalType.CLOSE_LONG if position['direction'] == 'long' else SignalType.CLOSE_SHORT
            return TradingSignal(
                signal_type=signal_type,
                symbol=symbol,
                price=current_price,
                timestamp=current_time,
                confidence=1.0,
                reason="End of day exit"
            )
        
        return TradingSignal(
            signal_type=SignalType.NO_SIGNAL,
            symbol=symbol,
            price=current_price,
            timestamp=current_time,
            confidence=0.0,
            reason="Position maintained"
        )
    
    def update_position(self, symbol: str, signal: TradingSignal):
        """
        Update position tracking based on executed signal.
        
        Args:
            symbol: Trading symbol
            signal: Executed trading signal
        """
        try:
            if signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                # Open new position
                self.active_positions[symbol] = {
                    'direction': 'long' if signal.signal_type == SignalType.LONG else 'short',
                    'entry_price': signal.price,
                    'entry_time': signal.timestamp,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'position_size': signal.position_size
                }
                logger.info(f"Opened {signal.signal_type.value} position for {symbol} at {signal.price}")
                
            elif signal.signal_type in [SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT]:
                # Close existing position
                if symbol in self.active_positions:
                    position = self.active_positions[symbol]
                    
                    # Calculate P&L
                    if position['direction'] == 'long':
                        pnl = (signal.price - position['entry_price']) * position['position_size']
                    else:
                        pnl = (position['entry_price'] - signal.price) * position['position_size']
                    
                    self.daily_pnl += pnl
                    self.trade_count += 1
                    
                    logger.info(f"Closed {position['direction']} position for {symbol} at {signal.price}, P&L: {pnl:.2f}")
                    
                    # Remove position
                    del self.active_positions[symbol]
                    
        except Exception as e:
            logger.error(f"Error updating position for {symbol}: {e}")
    
    def get_strategy_status(self) -> Dict:
        """
        Get current strategy status and performance metrics.
        
        Returns:
            Dictionary with strategy status information
        """
        return {
            'active_positions': len(self.active_positions),
            'daily_pnl': self.daily_pnl,
            'trade_count': self.trade_count,
            'opening_ranges': {symbol: {
                'high': range_data.high,
                'low': range_data.low,
                'range_size': range_data.range_size,
                'range_size_pct': range_data.range_size_pct
            } for symbol, range_data in self.opening_ranges.items()},
            'positions': self.active_positions
        }
    
    def reset_daily_stats(self):
        """Reset daily statistics for a new trading day."""
        self.daily_pnl = 0.0
        self.trade_count = 0
        self.opening_ranges.clear()
        logger.info("Daily statistics reset")

