"""
Binance Futures API Implementation

This module provides a concrete implementation of the TradingAPIInterface
for Binance Futures trading.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException

from api_interface import (
    TradingAPIInterface, MarketData, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)

class BinanceAPI(TradingAPIInterface):
    """Binance Futures API implementation."""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """
        Initialize Binance API client.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            testnet: Whether to use testnet (default: True)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client = None
        self._connected = False
    
    def connect(self) -> bool:
        """Establish connection to Binance."""
        try:
            self.client = Client(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet
            )
            # Test connection
            self.client.get_account()
            self._connected = True
            logger.info(f"Connected to Binance (testnet: {self.testnet})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Binance: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from Binance."""
        self.client = None
        self._connected = False
        logger.info("Disconnected from Binance")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to Binance."""
        return self._connected and self.client is not None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            if not self.is_connected():
                return None
            
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    def get_market_data(self, symbol: str, timeframe: str = '1m', 
                       limit: int = 100) -> List[MarketData]:
        """Get historical market data."""
        try:
            if not self.is_connected():
                return []
            
            klines = self.client.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=limit
            )
            
            market_data = []
            for kline in klines:
                data = MarketData(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(kline[0] / 1000),
                    open_price=float(kline[1]),
                    high_price=float(kline[2]),
                    low_price=float(kline[3]),
                    close_price=float(kline[4]),
                    volume=float(kline[5])
                )
                market_data.append(data)
            
            return market_data
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return []
    
    def get_price_range(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """Get min and max prices from N hours back."""
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            klines = self.client.get_historical_klines(
                symbol=symbol,
                interval='1m',
                start_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                end_str=end_time.strftime('%Y-%m-%d %H:%M:%S')
            )
            
            if not klines:
                return 0.0, 0.0
            
            prices = [float(kline[2]) for kline in klines]  # High prices
            prices.extend([float(kline[3]) for kline in klines])  # Low prices
            
            return min(prices), max(prices)
        except Exception as e:
            logger.error(f"Error getting price range for {symbol}: {e}")
            return 0.0, 0.0
    
    def get_yesterday_range(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """Get yesterday's day and night price ranges."""
        try:
            yesterday = datetime.now() - timedelta(days=1)
            start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_yesterday = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            klines = self.client.get_historical_klines(
                symbol=symbol,
                interval='1m',
                start_str=start_of_yesterday.strftime('%Y-%m-%d %H:%M:%S'),
                end_str=end_of_yesterday.strftime('%Y-%m-%d %H:%M:%S')
            )
            
            if not klines:
                return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
            
            # Split into day (9:30 AM - 4:00 PM) and night sessions
            day_prices = []
            night_prices = []
            
            for kline in klines:
                timestamp = datetime.fromtimestamp(kline[0] / 1000)
                hour = timestamp.hour
                
                high_price = float(kline[2])
                low_price = float(kline[3])
                
                if 9 <= hour < 16:  # Day session (simplified)
                    day_prices.extend([high_price, low_price])
                else:  # Night session
                    night_prices.extend([high_price, low_price])
            
            day_range = (min(day_prices), max(day_prices)) if day_prices else (0.0, 0.0)
            night_range = (min(night_prices), max(night_prices)) if night_prices else (0.0, 0.0)
            
            return {'day': day_range, 'night': night_range}
        except Exception as e:
            logger.error(f"Error getting yesterday's range for {symbol}: {e}")
            return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
    
    def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                   quantity: float, price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> Optional[Order]:
        """Place a trading order."""
        try:
            if not self.is_connected():
                return None
            
            # Convert to Binance format
            binance_side = 'BUY' if side == OrderSide.BUY else 'SELL'
            
            order_params = {
                'symbol': symbol,
                'side': binance_side,
                'quantity': quantity
            }
            
            if order_type == OrderType.MARKET:
                order_params['type'] = 'MARKET'
                result = self.client.futures_create_order(**order_params)
            elif order_type == OrderType.LIMIT:
                order_params.update({
                    'type': 'LIMIT',
                    'price': price,
                    'timeInForce': 'GTC'
                })
                result = self.client.futures_create_order(**order_params)
            else:
                logger.error(f"Order type {order_type} not implemented for Binance")
                return None
            
            # Convert result to standardized Order object
            order = Order(
                order_id=str(result['orderId']),
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=float(result['origQty']),
                price=float(result['price']) if result['price'] != '0' else None,
                status=self._convert_order_status(result['status']),
                timestamp=datetime.fromtimestamp(result['updateTime'] / 1000),
                filled_quantity=float(result['executedQty'])
            )
            
            return order
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        try:
            if not self.is_connected():
                return False
            
            # Note: Binance requires symbol for cancellation, 
            # this is a limitation of the current implementation
            # In practice, you'd need to store order details or get them first
            logger.warning("Binance order cancellation requires symbol - not implemented")
            return False
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get status of a specific order."""
        try:
            if not self.is_connected():
                return None
            
            # Similar limitation as cancel_order
            logger.warning("Binance order status check requires symbol - not implemented")
            return None
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {e}")
            return None
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders."""
        try:
            if not self.is_connected():
                return []
            
            if symbol:
                orders = self.client.futures_get_open_orders(symbol=symbol)
            else:
                orders = self.client.futures_get_open_orders()
            
            result = []
            for order in orders:
                order_obj = Order(
                    order_id=str(order['orderId']),
                    symbol=order['symbol'],
                    side=OrderSide.BUY if order['side'] == 'BUY' else OrderSide.SELL,
                    order_type=self._convert_order_type(order['type']),
                    quantity=float(order['origQty']),
                    price=float(order['price']) if order['price'] != '0' else None,
                    status=self._convert_order_status(order['status']),
                    timestamp=datetime.fromtimestamp(order['updateTime'] / 1000),
                    filled_quantity=float(order['executedQty'])
                )
                result.append(order_obj)
            
            return result
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []
    
    def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information."""
        try:
            if not self.is_connected():
                return None
            
            account = self.client.futures_account()
            positions = self.get_positions()
            
            account_info = AccountInfo(
                account_id=str(account.get('accountAlias', 'default')),
                balance=float(account['totalWalletBalance']),
                available_margin=float(account['availableBalance']),
                used_margin=float(account['totalInitialMargin']),
                positions=positions,
                timestamp=datetime.now()
            )
            
            return account_info
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return None
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get current positions."""
        try:
            if not self.is_connected():
                return []
            
            positions = self.client.futures_position_information()
            
            result = []
            for pos in positions:
                if symbol and pos['symbol'] != symbol:
                    continue
                
                if float(pos['positionAmt']) != 0:  # Only non-zero positions
                    position = Position(
                        symbol=pos['symbol'],
                        quantity=float(pos['positionAmt']),
                        average_price=float(pos['entryPrice']),
                        unrealized_pnl=float(pos['unRealizedProfit']),
                        realized_pnl=0.0,  # Binance doesn't provide this directly
                        timestamp=datetime.now()
                    )
                    result.append(position)
            
            return result
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols."""
        try:
            if not self.is_connected():
                return []
            
            exchange_info = self.client.futures_exchange_info()
            symbols = [s['symbol'] for s in exchange_info['symbols'] if s['status'] == 'TRADING']
            return symbols
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate if a symbol is available for trading."""
        try:
            available_symbols = self.get_available_symbols()
            return symbol in available_symbols
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    def get_platform_name(self) -> str:
        """Get the name of the trading platform."""
        return "Binance Futures"
    
    def _convert_order_status(self, binance_status: str) -> OrderStatus:
        """Convert Binance order status to standardized status."""
        status_map = {
            'NEW': OrderStatus.PENDING,
            'PARTIALLY_FILLED': OrderStatus.PARTIALLY_FILLED,
            'FILLED': OrderStatus.FILLED,
            'CANCELED': OrderStatus.CANCELLED,
            'REJECTED': OrderStatus.REJECTED,
            'EXPIRED': OrderStatus.CANCELLED
        }
        return status_map.get(binance_status, OrderStatus.PENDING)
    
    def _convert_order_type(self, binance_type: str) -> OrderType:
        """Convert Binance order type to standardized type."""
        type_map = {
            'MARKET': OrderType.MARKET,
            'LIMIT': OrderType.LIMIT,
            'STOP': OrderType.STOP,
            'STOP_MARKET': OrderType.STOP,
            'TAKE_PROFIT': OrderType.LIMIT,
            'TAKE_PROFIT_MARKET': OrderType.MARKET
        }
        return type_map.get(binance_type, OrderType.MARKET)

