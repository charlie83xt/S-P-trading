"""
Abstract API interface for trading platforms.
This module defines the common interface that all trading platform APIs must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime

class TradingAPIInterface(ABC):
    """Abstract base class for trading platform APIs."""
    
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
        Check if connected to the trading platform.
        
        Returns:
            bool: True if connected, False otherwise
        """
        pass
    
    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Dict containing account information
        """
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """
        Get current price for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT', 'ES')
            
        Returns:
            Current price as float
        """
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> List[Dict]:
        """
        Get historical price data.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1m', '5m', '1h', '1d')
            limit: Number of data points to retrieve
            
        Returns:
            List of dictionaries containing OHLCV data
        """
        pass
    
    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        """
        Place a market order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order quantity
            
        Returns:
            Order information dictionary
        """
        pass
    
    @abstractmethod
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        """
        Place a limit order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order quantity
            price: Limit price
            
        Returns:
            Order information dictionary
        """
        pass
    
    @abstractmethod
    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        """
        Place a stop order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order quantity
            stop_price: Stop price
            
        Returns:
            Order information dictionary
        """
        pass
    
    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            symbol: Trading symbol
            order_id: Order ID to cancel
            
        Returns:
            True if cancellation successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get open orders.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of open orders
        """
        pass
    
    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get current positions.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of current positions
        """
        pass
    
    @abstractmethod
    def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get order history.
        
        Args:
            symbol: Optional symbol filter
            limit: Number of orders to retrieve
            
        Returns:
            List of historical orders
        """
        pass
    
    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """
        Get account balance.
        
        Returns:
            Dictionary containing balance information
        """
        pass
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """
        Get the platform name.
        
        Returns:
            Platform name as string
        """
        pass

