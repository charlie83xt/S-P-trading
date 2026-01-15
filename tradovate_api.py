"""
Tradovate API implementation.
"""

import requests
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from api_interface import TradingAPIInterface

class TradovateAPI(TradingAPIInterface):
    """Tradovate API implementation."""
    
    def __init__(self, username: str, password: str, demo: bool = True):
        """
        Initialize Tradovate API.
        
        Args:
            username: Tradovate username
            password: Tradovate password
            demo: Whether to use demo environment
        """
        self.username = username
        self.password = password
        self.demo = demo
        self.base_url = 'https://demo.tradovateapi.com/v1' if demo else 'https://live.tradovateapi.com/v1'
        self.access_token = None
        self.connected = False
        self.logger = logging.getLogger(__name__)
        
    def _make_request(self, method: str, endpoint: str, data: Dict = None, authenticated: bool = False) -> Dict:
        """Make HTTP request to Tradovate API."""
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if authenticated and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method.upper() == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=10)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Tradovate API request failed: {e}")
            return {'error': str(e)}
    
    def _authenticate(self) -> bool:
        """Authenticate with Tradovate API."""
        auth_data = {
            'name': self.username,
            'password': self.password,
            'appId': 'TradingBot',
            'appVersion': '1.0'
        }
        
        response = self._make_request('POST', '/auth/accesstokenrequest', auth_data)
        
        if 'accessToken' in response:
            self.access_token = response['accessToken']
            self.logger.info("Successfully authenticated with Tradovate")
            return True
        else:
            self.logger.error(f"Authentication failed: {response}")
            return False
    
    def connect(self) -> bool:
        """Establish connection to Tradovate."""
        try:
            if self._authenticate():
                self.connected = True
                self.logger.info("Connected to Tradovate API")
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from Tradovate."""
        if self.access_token:
            # Invalidate the access token
            self._make_request('POST', '/auth/logout', authenticated=True)
            self.access_token = None
        
        self.connected = False
        self.logger.info("Disconnected from Tradovate")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to Tradovate."""
        return self.connected and self.access_token is not None
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        if not self.is_connected():
            return {'error': 'Not connected to Tradovate'}
        
        return self._make_request('GET', '/account/list', authenticated=True)
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        # Note: This is a simplified implementation
        # In practice, you would need to subscribe to market data feeds
        if not self.is_connected():
            self.logger.error("Not connected to Tradovate")
            return 0.0
        
        # For demo purposes, return a mock price
        # In real implementation, use WebSocket for real-time data
        self.logger.warning(f"Mock price returned for {symbol}")
        return 4500.0  # Mock S&P 500 price
    
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> List[Dict]:
        """Get historical price data."""
        if not self.is_connected():
            return []
        
        # Note: This would require contract ID lookup and proper timeframe mapping
        # This is a simplified implementation
        self.logger.warning("Historical data not fully implemented for Tradovate")
        return []
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        """Place a market order."""
        if not self.is_connected():
            return {'error': 'Not connected to Tradovate'}
        
        order_data = {
            'accountSpec': self.username,
            'accountId': 1,  # This would need to be retrieved from account info
            'action': 'Buy' if side.lower() == 'buy' else 'Sell',
            'symbol': symbol,
            'orderQty': quantity,
            'orderType': 'Market'
        }
        
        return self._make_request('POST', '/order/placeorder', order_data, authenticated=True)
    
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        """Place a limit order."""
        if not self.is_connected():
            return {'error': 'Not connected to Tradovate'}
        
        order_data = {
            'accountSpec': self.username,
            'accountId': 1,
            'action': 'Buy' if side.lower() == 'buy' else 'Sell',
            'symbol': symbol,
            'orderQty': quantity,
            'orderType': 'Limit',
            'price': price
        }
        
        return self._make_request('POST', '/order/placeorder', order_data, authenticated=True)
    
    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        """Place a stop order."""
        if not self.is_connected():
            return {'error': 'Not connected to Tradovate'}
        
        order_data = {
            'accountSpec': self.username,
            'accountId': 1,
            'action': 'Buy' if side.lower() == 'buy' else 'Sell',
            'symbol': symbol,
            'orderQty': quantity,
            'orderType': 'Stop',
            'stopPrice': stop_price
        }
        
        return self._make_request('POST', '/order/placeorder', order_data, authenticated=True)
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        if not self.is_connected():
            return False
        
        cancel_data = {
            'orderId': order_id
        }
        
        response = self._make_request('POST', '/order/cancelorder', cancel_data, authenticated=True)
        return 'orderId' in response
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/order/list', authenticated=True)
        
        if isinstance(response, list):
            orders = []
            for order in response:
                if order.get('orderStatus') == 'Working':
                    if symbol is None or order.get('symbol') == symbol:
                        orders.append(order)
            return orders
        return []
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current positions."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/position/list', authenticated=True)
        
        if isinstance(response, list):
            positions = []
            for pos in response:
                if pos.get('netPos', 0) != 0:  # Only return non-zero positions
                    if symbol is None or pos.get('symbol') == symbol:
                        positions.append(pos)
            return positions
        return []
    
    def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get order history."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/order/list', authenticated=True)
        
        if isinstance(response, list):
            # Filter for completed orders
            history = []
            for order in response:
                if order.get('orderStatus') in ['Filled', 'Cancelled']:
                    if symbol is None or order.get('symbol') == symbol:
                        history.append(order)
            return history[:limit]
        return []
    
    def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        account_info = self.get_account_info()
        
        if isinstance(account_info, list) and len(account_info) > 0:
            account = account_info[0]
            return {
                'USD': {
                    'free': account.get('cashBalance', 0.0),
                    'locked': 0.0,  # Would need to calculate from open positions
                    'total': account.get('cashBalance', 0.0)
                }
            }
        return {}
    
    def get_platform_name(self) -> str:
        """Get the platform name."""
        return "Tradovate"

