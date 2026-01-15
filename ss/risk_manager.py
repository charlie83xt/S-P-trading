"""
Risk Management module for the futures trading bot.
Implements comprehensive risk controls and monitoring.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from config import get_config
from opening_range_strategy import TradingSignal, SignalType

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    """Risk level enumeration."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

@dataclass
class RiskMetrics:
    """Data class for risk metrics."""
    total_exposure: float
    daily_pnl: float
    max_drawdown: float
    position_count: int
    largest_position: float
    risk_level: RiskLevel
    violations: List[str]

class RiskManager:
    """
    Comprehensive risk management system for the trading bot.
    
    Implements multiple layers of risk control including:
    - Position size limits
    - Maximum drawdown protection
    - Daily loss limits
    - Exposure concentration limits
    - Emergency stop mechanisms
    """
    
    def __init__(self):
        self.config = get_config()
        self.daily_pnl: float = 0.0
        self.max_drawdown: float = 0.0
        self.peak_equity: float = 10000.0  # Starting equity
        self.current_equity: float = 10000.0
        self.positions: Dict[str, Dict] = {}
        self.daily_trades: int = 0
        self.risk_violations: List[str] = []
        self.emergency_stop: bool = False
        self.last_reset_date: str = datetime.now().strftime('%Y-%m-%d')
        
        logger.info("Risk Manager initialized")
    
    def validate_signal(self, signal: TradingSignal) -> Tuple[bool, str]:
        """
        Validate a trading signal against risk parameters.
        
        Args:
            signal: Trading signal to validate
            
        Returns:
            Tuple of (is_valid, reason)
        """
        if not self.config.enable_risk_management:
            return True, "Risk management disabled"
        
        if self.emergency_stop:
            return False, "Emergency stop activated"
        
        try:
            # Check daily loss limit
            if self.daily_pnl <= -self.config.max_daily_loss:
                return False, f"Daily loss limit exceeded: {self.daily_pnl:.2f}"
            
            # Check maximum drawdown
            if self.max_drawdown >= self.config.max_drawdown:
                return False, f"Maximum drawdown exceeded: {self.max_drawdown:.2%}"
            
            # For opening signals, check additional constraints
            if signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                # Check maximum open positions
                if len(self.positions) >= self.config.max_open_positions:
                    return False, f"Maximum open positions limit reached: {len(self.positions)}"
                
                # Check if position already exists for this symbol
                if signal.symbol in self.positions:
                    return False, f"Position already exists for {signal.symbol}"
                
                # Check position size limits
                if signal.position_size and signal.position_size > self.config.max_position_size:
                    return False, f"Position size exceeds limit: {signal.position_size} > {self.config.max_position_size}"
                
                # Check if we have sufficient equity for the trade
                required_margin = self._calculate_required_margin(signal)
                if required_margin > self.current_equity * 0.8:  # Use max 80% of equity
                    return False, f"Insufficient equity for trade: required {required_margin:.2f}"
            
            return True, "Signal validated"
            
        except Exception as e:
            logger.error(f"Error validating signal: {e}")
            return False, f"Validation error: {str(e)}"
    
    def _calculate_required_margin(self, signal: TradingSignal) -> float:
        """
        Calculate required margin for a trading signal.
        
        Args:
            signal: Trading signal
            
        Returns:
            Required margin amount
        """
        try:
            if not signal.position_size:
                return 0.0
            
            # For futures, margin is typically a percentage of notional value
            notional_value = signal.price * signal.position_size
            margin_rate = 0.1  # 10% margin requirement (typical for crypto futures)
            
            return notional_value * margin_rate
            
        except Exception as e:
            logger.error(f"Error calculating required margin: {e}")
            return float('inf')  # Return high value to prevent trade
    
    def update_position(self, symbol: str, signal: TradingSignal):
        """
        Update position tracking and risk metrics.
        
        Args:
            symbol: Trading symbol
            signal: Executed trading signal
        """
        try:
            current_date = datetime.now().strftime('%Y-%m-%d')
            
            # Reset daily stats if new day
            if current_date != self.last_reset_date:
                self._reset_daily_stats()
                self.last_reset_date = current_date
            
            if signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                # Open new position
                self.positions[symbol] = {
                    'direction': 'long' if signal.signal_type == SignalType.LONG else 'short',
                    'entry_price': signal.price,
                    'entry_time': signal.timestamp,
                    'position_size': signal.position_size,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'unrealized_pnl': 0.0
                }
                
                self.daily_trades += 1
                logger.info(f"Risk Manager: Position opened for {symbol}")
                
            elif signal.signal_type in [SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT]:
                # Close existing position
                if symbol in self.positions:
                    position = self.positions[symbol]
                    
                    # Calculate realized P&L
                    if position['direction'] == 'long':
                        pnl = (signal.price - position['entry_price']) * position['position_size']
                    else:
                        pnl = (position['entry_price'] - signal.price) * position['position_size']
                    
                    # Update equity and daily P&L
                    self.current_equity += pnl
                    self.daily_pnl += pnl
                    
                    # Update peak equity and drawdown
                    if self.current_equity > self.peak_equity:
                        self.peak_equity = self.current_equity
                    
                    current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
                    self.max_drawdown = max(self.max_drawdown, current_drawdown)
                    
                    logger.info(f"Risk Manager: Position closed for {symbol}, P&L: {pnl:.2f}, Equity: {self.current_equity:.2f}")
                    
                    # Remove position
                    del self.positions[symbol]
                    
                    # Check for risk violations after trade
                    self._check_risk_violations()
            
        except Exception as e:
            logger.error(f"Error updating position in risk manager: {e}")
    
    def update_unrealized_pnl(self, symbol: str, current_price: float):
        """
        Update unrealized P&L for open positions.
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
        """
        try:
            if symbol in self.positions:
                position = self.positions[symbol]
                
                if position['direction'] == 'long':
                    unrealized_pnl = (current_price - position['entry_price']) * position['position_size']
                else:
                    unrealized_pnl = (position['entry_price'] - current_price) * position['position_size']
                
                position['unrealized_pnl'] = unrealized_pnl
                
        except Exception as e:
            logger.error(f"Error updating unrealized P&L for {symbol}: {e}")
    
    def _check_risk_violations(self):
        """Check for risk violations and take appropriate action."""
        try:
            violations = []
            
            # Check daily loss limit
            if self.daily_pnl <= -self.config.max_daily_loss:
                violations.append(f"Daily loss limit exceeded: {self.daily_pnl:.2f}")
            
            # Check maximum drawdown
            if self.max_drawdown >= self.config.max_drawdown:
                violations.append(f"Maximum drawdown exceeded: {self.max_drawdown:.2%}")
            
            # Check equity level
            if self.current_equity <= self.peak_equity * (1 - self.config.max_drawdown):
                violations.append(f"Equity below maximum drawdown threshold")
            
            # Update violations list
            self.risk_violations = violations
            
            # Trigger emergency stop if critical violations
            if len(violations) > 0:
                logger.warning(f"Risk violations detected: {violations}")
                
                # Activate emergency stop for severe violations
                if (self.daily_pnl <= -self.config.max_daily_loss * 1.5 or 
                    self.max_drawdown >= self.config.max_drawdown * 1.2):
                    self.emergency_stop = True
                    logger.critical("EMERGENCY STOP ACTIVATED due to severe risk violations")
            
        except Exception as e:
            logger.error(f"Error checking risk violations: {e}")
    
    def get_risk_metrics(self) -> RiskMetrics:
        """
        Get current risk metrics.
        
        Returns:
            RiskMetrics object with current risk information
        """
        try:
            # Calculate total exposure
            total_exposure = sum(
                abs(pos['position_size'] * pos['entry_price']) 
                for pos in self.positions.values()
            )
            
            # Find largest position
            largest_position = max(
                (abs(pos['position_size'] * pos['entry_price']) for pos in self.positions.values()),
                default=0.0
            )
            
            # Determine risk level
            risk_level = self._calculate_risk_level()
            
            return RiskMetrics(
                total_exposure=total_exposure,
                daily_pnl=self.daily_pnl,
                max_drawdown=self.max_drawdown,
                position_count=len(self.positions),
                largest_position=largest_position,
                risk_level=risk_level,
                violations=self.risk_violations.copy()
            )
            
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return RiskMetrics(
                total_exposure=0.0,
                daily_pnl=0.0,
                max_drawdown=0.0,
                position_count=0,
                largest_position=0.0,
                risk_level=RiskLevel.CRITICAL,
                violations=[f"Error calculating metrics: {str(e)}"]
            )
    
    def _calculate_risk_level(self) -> RiskLevel:
        """
        Calculate current risk level based on various factors.
        
        Returns:
            RiskLevel enum value
        """
        try:
            risk_score = 0
            
            # Daily P&L factor
            if self.daily_pnl < -self.config.max_daily_loss * 0.5:
                risk_score += 2
            elif self.daily_pnl < -self.config.max_daily_loss * 0.25:
                risk_score += 1
            
            # Drawdown factor
            if self.max_drawdown > self.config.max_drawdown * 0.8:
                risk_score += 3
            elif self.max_drawdown > self.config.max_drawdown * 0.5:
                risk_score += 2
            elif self.max_drawdown > self.config.max_drawdown * 0.25:
                risk_score += 1
            
            # Position count factor
            if len(self.positions) >= self.config.max_open_positions:
                risk_score += 2
            elif len(self.positions) >= self.config.max_open_positions * 0.8:
                risk_score += 1
            
            # Emergency stop factor
            if self.emergency_stop:
                risk_score += 5
            
            # Determine risk level
            if risk_score >= 5:
                return RiskLevel.CRITICAL
            elif risk_score >= 3:
                return RiskLevel.HIGH
            elif risk_score >= 1:
                return RiskLevel.MEDIUM
            else:
                return RiskLevel.LOW
                
        except Exception as e:
            logger.error(f"Error calculating risk level: {e}")
            return RiskLevel.CRITICAL
    
    def _reset_daily_stats(self):
        """Reset daily statistics for a new trading day."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.risk_violations.clear()
        
        # Don't reset emergency stop automatically - requires manual intervention
        logger.info("Daily risk statistics reset")
    
    def reset_emergency_stop(self) -> bool:
        """
        Reset emergency stop (manual intervention required).
        
        Returns:
            True if reset successful, False otherwise
        """
        try:
            # Check if conditions are safe to reset
            current_metrics = self.get_risk_metrics()
            
            if (current_metrics.daily_pnl > -self.config.max_daily_loss * 0.5 and
                current_metrics.max_drawdown < self.config.max_drawdown * 0.8):
                
                self.emergency_stop = False
                self.risk_violations.clear()
                logger.info("Emergency stop reset successfully")
                return True
            else:
                logger.warning("Cannot reset emergency stop - risk conditions still unsafe")
                return False
                
        except Exception as e:
            logger.error(f"Error resetting emergency stop: {e}")
            return False
    
    def get_position_summary(self) -> Dict:
        """
        Get summary of current positions.
        
        Returns:
            Dictionary with position summary
        """
        try:
            total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in self.positions.values())
            
            return {
                'position_count': len(self.positions),
                'total_unrealized_pnl': total_unrealized_pnl,
                'current_equity': self.current_equity,
                'daily_pnl': self.daily_pnl,
                'max_drawdown': self.max_drawdown,
                'daily_trades': self.daily_trades,
                'emergency_stop': self.emergency_stop,
                'positions': {
                    symbol: {
                        'direction': pos['direction'],
                        'entry_price': pos['entry_price'],
                        'position_size': pos['position_size'],
                        'unrealized_pnl': pos['unrealized_pnl']
                    }
                    for symbol, pos in self.positions.items()
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting position summary: {e}")
            return {'error': str(e)}

