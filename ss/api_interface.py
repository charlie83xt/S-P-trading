"""
Abstract API Interface for Platform-Agnostic Trading Bot

This module defines the abstract base class and interfaces that all trading platform
implementations must follow. This ensures consistency across different API providers
and allows seamless switching between platforms.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

class OrderType(Enum):
    """Standard order types across all platforms."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderSide(Enum):
    """Order side (buy/sell) standardized across platforms."""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """Order status standardized across platforms."""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class MarketData:
    """Standardized market data structure."""
    symbol: str
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None

@dataclass
class Order:
    """Standardized order structure."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float]
    status: OrderStatus
    timestamp: datetime
    filled_quantity: float = 0.0
    average_price: Optional[float] = None

@dataclass
class Position:
    """Standardized position structure."""
    symbol: str
    quantity: float
    average_price: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: datetime

@dataclass
class AccountInfo:
    """Standardized account information structure."""
    account_id: str
    balance: float
    available_margin: float
    used_margin: float
    positions: List[Position]
    timestamp: datetime

class TradingAPIInterface(ABC):
    """
    Abstract base class defining the interface that all trading platform
    implementations must follow.
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the trading platform.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from the trading platform.
        
        Returns:
            bool: True if disconnection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if currently connected to the trading platform.
        
        Returns:
            bool: True if connected, False otherwise
        """
        pass
    
    # Market Data Methods
    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current market price for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., 'ES', 'NQ')
            
        Returns:
            Current price or None if unavailable
        """
        pass
    
    @abstractmethod
    def get_market_data(self, symbol: str, timeframe: str = '1m', 
                       limit: int = 100) -> List[MarketData]:
        """
        Get historical market data.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (1m, 5m, 1h, 1d, etc.)
            limit: Number of data points to retrieve
            
        Returns:
            List of MarketData objects
        """
        pass
    
    @abstractmethod
    def get_price_range(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """
        Get min and max prices from N hours back.
        
        Args:
            symbol: Trading symbol
            hours_back: Number of hours to look back
            
        Returns:
            Tuple of (min_price, max_price)
        """
        pass
    
    @abstractmethod
    def get_yesterday_range(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """
        Get yesterday's day and night price ranges.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict with 'day' and 'night' keys, each containing (min, max) tuples
        """
        pass
    
    # Trading Methods
    @abstractmethod
    def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                   quantity: float, price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> Optional[Order]:
        """
        Place a trading order.
        
        Args:
            symbol: Trading symbol
            side: Buy or sell
            order_type: Type of order
            quantity: Order quantity
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)
            
        Returns:
            Order object if successful, None otherwise
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.
        
        Args:
            order_id: ID of the order to cancel
            
        Returns:
            True if cancellation successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """
        Get status of a specific order.
        
        Args:
            order_id: ID of the order
            
        Returns:
            Order object with current status, None if not found
        """
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        Get all open orders.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of open Order objects
        """
        pass
    
    # Account Methods
    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfo]:
        """
        Get account information including balance and positions.
        
        Returns:
            AccountInfo object or None if unavailable
        """
        pass
    
    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        Get current positions.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of Position objects
        """
        pass
    
    # Utility Methods
    @abstractmethod
    def get_available_symbols(self) -> List[str]:
        """
        Get list of available trading symbols.
        
        Returns:
            List of symbol strings
        """
        pass
    
    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """
        Validate if a symbol is available for trading.
        
        Args:
            symbol: Symbol to validate
            
        Returns:
            True if symbol is valid, False otherwise
        """
        pass
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """
        Get the name of the trading platform.
        
        Returns:
            Platform name string
        """
        pass

