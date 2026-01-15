"""
Main Trading Bot module that orchestrates all trading operations.
Supports multiple trading platforms through a unified interface.
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import schedule

from config import get_config
from api_factory import APIFactory
from api_interface import TradingAPIInterface, OrderSide, OrderType, OrderStatus
from data_manager import DataManager
from opening_range_strategy import OpeningRangeStrategy, SignalType
from risk_manager import RiskManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class TradingBot:
    """Main trading bot class that coordinates all trading operations."""
    
    def __init__(self):
        self.config = get_config()
        self.api: Optional[TradingAPIInterface] = None
        self.data_manager = DataManager()
        self.risk_manager = RiskManager()
        self.opening_range_strategy = OpeningRangeStrategy()
        
        # Bot state
        self.is_running = False
        self.is_paused = False
        self.last_trade_time = None
        self.daily_pnl = 0.0
        self.active_orders = {}
        self.positions = {}
        self.cooldown_until = None
        
        # Threading
        self.main_thread = None
        self.stop_event = threading.Event()
        
        self._initialize_api()
        self._setup_logging()
    
    def _initialize_api(self):
        """Initialize trading API based on configuration."""
        try:
            self.api = APIFactory.create_api()
            if self.api and self.api.connect():
                logger.info(f"Trading bot connected to {self.api.get_platform_name()}")
            else:
                logger.error("Failed to initialize trading API")
                raise Exception("API initialization failed")
        except Exception as e:
            logger.error(f"Failed to initialize API: {e}")
            raise
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config.log_level.upper())
        logging.getLogger().setLevel(log_level)
        logger.info(f"Logging configured at {self.config.log_level} level")
    
    def start(self):
        """Start the trading bot."""
        try:
            if self.is_running:
                logger.warning("Bot is already running")
                return False
            
            if not self.config.trading_enabled:
                logger.warning("Trading is disabled in configuration")
                return False
            
            # Verify API connection
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return False
            
            # Reset state
            self.stop_event.clear()
            self.is_running = True
            self.is_paused = False
            
            # Start main trading thread
            self.main_thread = threading.Thread(target=self._trading_loop, daemon=True)
            self.main_thread.start()
            
            logger.info(f"Trading bot started on {self.api.get_platform_name()}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """Stop the trading bot."""
        try:
            if not self.is_running:
                logger.warning("Bot is not running")
                return False
            
            logger.info("Stopping trading bot...")
            self.is_running = False
            self.stop_event.set()
            
            # Cancel all open orders
            self._cancel_all_orders()
            
            # Wait for main thread to finish
            if self.main_thread and self.main_thread.is_alive():
                self.main_thread.join(timeout=10)
            
            logger.info("Trading bot stopped")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
            return False
    
    def pause(self, minutes: int = 0):
        """Pause the trading bot for a specified duration."""
        try:
            self.is_paused = True
            if minutes > 0:
                self.cooldown_until = datetime.now() + timedelta(minutes=minutes)
                logger.info(f"Bot paused for {minutes} minutes")
            else:
                self.cooldown_until = None
                logger.info("Bot paused indefinitely")
            return True
        except Exception as e:
            logger.error(f"Error pausing bot: {e}")
            return False
    
    def resume(self):
        """Resume the trading bot."""
        try:
            self.is_paused = False
            self.cooldown_until = None
            logger.info("Bot resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming bot: {e}")
            return False
    
    def _trading_loop(self):
        """Main trading loop."""
        logger.info("Trading loop started")
        
        while self.is_running and not self.stop_event.is_set():
            try:
                # Check if paused or in cooldown
                if self._is_in_cooldown():
                    time.sleep(10)  # Check every 10 seconds
                    continue
                
                # Update positions and orders
                self._update_positions()
                self._update_orders()
                
                # Check risk limits
                if not self.risk_manager.check_daily_loss_limit(self.daily_pnl):
                    logger.warning("Daily loss limit reached, pausing bot")
                    self.pause()
                    continue
                
                # Generate trading signals
                symbol = self.config.default_symbol
                signal = self.opening_range_strategy.generate_signal(symbol)
                
                if signal and signal.signal_type != SignalType.HOLD:
                    # Check if we can trade
                    if self._can_place_order(symbol, signal):
                        self._execute_signal(signal)
                
                # Sleep before next iteration
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(10)  # Wait longer on error
        
        logger.info("Trading loop ended")
    
    def _is_in_cooldown(self) -> bool:
        """Check if bot is in cooldown period."""
        if self.is_paused:
            if self.cooldown_until and datetime.now() >= self.cooldown_until:
                self.resume()
                return False
            return True
        return False
    
    def _update_positions(self):
        """Update current positions."""
        try:
            if not self.api or not self.api.is_connected():
                return
            
            positions = self.api.get_positions()
            self.positions = {pos.symbol: pos for pos in positions}
            
            # Update daily P&L
            total_pnl = sum(pos.unrealized_pnl + pos.realized_pnl for pos in positions)
            self.daily_pnl = total_pnl
            
        except Exception as e:
            logger.error(f"Error updating positions: {e}")
    
    def _update_orders(self):
        """Update active orders."""
        try:
            if not self.api or not self.api.is_connected():
                return
            
            open_orders = self.api.get_open_orders()
            self.active_orders = {order.order_id: order for order in open_orders}
            
        except Exception as e:
            logger.error(f"Error updating orders: {e}")
    
    def _can_place_order(self, symbol: str, signal) -> bool:
        """Check if we can place an order."""
        try:
            # Check if we already have a position
            if symbol in self.positions and self.positions[symbol].quantity != 0:
                return False
            
            # Check if we have pending orders
            symbol_orders = [order for order in self.active_orders.values() 
                           if order.symbol == symbol]
            if symbol_orders:
                return False
            
            # Check position limits
            if len(self.positions) >= self.config.max_open_positions:
                return False
            
            # Check risk limits
            if not self.risk_manager.can_open_position(
                symbol, signal.quantity, signal.entry_price
            ):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking if can place order: {e}")
            return False
    
    def _execute_signal(self, signal):
        """Execute a trading signal."""
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return
            
            # Determine order side
            side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
            
            # Place market order
            order = self.api.place_order(
                symbol=signal.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=signal.quantity
            )
            
            if order:
                logger.info(f"Order placed: {order.order_id} - {side.value} {signal.quantity} {signal.symbol}")
                self.last_trade_time = datetime.now()
                
                # Set cooldown
                if self.config.cooldown_minutes > 0:
                    self.pause(self.config.cooldown_minutes)
            else:
                logger.error("Failed to place order")
                
        except Exception as e:
            logger.error(f"Error executing signal: {e}")
    
    def _cancel_all_orders(self):
        """Cancel all open orders."""
        try:
            if not self.api or not self.api.is_connected():
                return
            
            for order_id in list(self.active_orders.keys()):
                success = self.api.cancel_order(order_id)
                if success:
                    logger.info(f"Cancelled order: {order_id}")
                else:
                    logger.warning(f"Failed to cancel order: {order_id}")
                    
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bot status."""
        try:
            account_info = self.api.get_account_info() if self.api else None
            
            status = {
                'is_running': self.is_running,
                'is_paused': self.is_paused,
                'platform': self.api.get_platform_name() if self.api else 'Unknown',
                'is_connected': self.api.is_connected() if self.api else False,
                'daily_pnl': self.daily_pnl,
                'active_orders_count': len(self.active_orders),
                'positions_count': len(self.positions),
                'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None,
                'cooldown_until': self.cooldown_until.isoformat() if self.cooldown_until else None,
                'account_balance': account_info.balance if account_info else 0.0,
                'available_margin': account_info.available_margin if account_info else 0.0
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {'error': str(e)}
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        try:
            positions_data = []
            for position in self.positions.values():
                positions_data.append({
                    'symbol': position.symbol,
                    'quantity': position.quantity,
                    'average_price': position.average_price,
                    'unrealized_pnl': position.unrealized_pnl,
                    'realized_pnl': position.realized_pnl,
                    'timestamp': position.timestamp.isoformat()
                })
            return positions_data
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """Get active orders."""
        try:
            orders_data = []
            for order in self.active_orders.values():
                orders_data.append({
                    'order_id': order.order_id,
                    'symbol': order.symbol,
                    'side': order.side.value,
                    'order_type': order.order_type.value,
                    'quantity': order.quantity,
                    'price': order.price,
                    'status': order.status.value,
                    'filled_quantity': order.filled_quantity,
                    'timestamp': order.timestamp.isoformat()
                })
            return orders_data
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []
    
    def disconnect(self):
        """Disconnect from API and cleanup."""
        try:
            if self.is_running:
                self.stop()
            
            if self.api:
                self.api.disconnect()
            
            if self.data_manager:
                self.data_manager.disconnect()
                
            logger.info("Trading bot disconnected")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    def __del__(self):
        """Cleanup on object destruction."""
        self.disconnect()

