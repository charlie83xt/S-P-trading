"""
NinjaTrader API implementation.
"""

import requests
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from api_interface import TradingAPIInterface

class NinjaTraderAPI(TradingAPIInterface):
    """NinjaTrader API implementation."""
    
    def __init__(self, api_key: str, api_url: str = 'http://localhost:8080', simulation: bool = True):
        """
        Initialize NinjaTrader API.
        
        Args:
            api_url: NinjaTrader API URL
            simulation: Whether to use simulation mode
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.simulation = simulation
        self.connected = False
        self.logger = logging.getLogger(__name__)
        
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make HTTP request to NinjaTrader API."""
        url = f"{self.api_url}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
            }
        
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
            self.logger.error(f"NinjaTrader API request failed: {e}")
            return {'error': str(e)}
    
    def connect(self) -> bool:
        """Establish connection to NinjaTrader."""
        try:
            # Test connection by getting account info
            response = self._make_request('GET', '/accounts')
            if isinstance(response, list) or 'accounts' in response:
                self.connected = True
                self.logger.info("Connected to NinjaTrader API")
                return True
            else:
                self.logger.error("Failed to connect to NinjaTrader")
                return False
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from NinjaTrader."""
        self.connected = False
        self.logger.info("Disconnected from NinjaTrader")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to NinjaTrader."""
        return self.connected
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        if not self.is_connected():
            return {'error': 'Not connected to NinjaTrader'}
        
        return self._make_request('GET', '/accounts')
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        if not self.is_connected():
            self.logger.error("Not connected to NinjaTrader")
            return 0.0
        
        # Get last price from market data
        response = self._make_request('GET', f'/marketdata/{symbol}/last')
        
        if 'last' in response:
            return float(response['last'])
        else:
            self.logger.error(f"Failed to get price for {symbol}: {response}")
            return 0.0
    
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> List[Dict]:
        """Get historical price data."""
        if not self.is_connected():
            return []
        
        # Map timeframe to NinjaTrader format
        timeframe_map = {
            '1m': 'Minute',
            '5m': '5 Minute',
            '15m': '15 Minute',
            '1h': 'Hour',
            '1d': 'Day'
        }
        
        nt_timeframe = timeframe_map.get(timeframe, 'Minute')
        
        params = {
            'instrument': symbol,
            'barType': nt_timeframe,
            'barsBack': limit
        }
        
        response = self._make_request('GET', '/marketdata/bars', params)
        
        if isinstance(response, list):
            # Convert NinjaTrader format to standard format
            data = []
            for bar in response:
                data.append({
                    'timestamp': bar.get('time', 0),
                    'open': float(bar.get('open', 0)),
                    'high': float(bar.get('high', 0)),
                    'low': float(bar.get('low', 0)),
                    'close': float(bar.get('close', 0)),
                    'volume': float(bar.get('volume', 0))
                })
            return data
        else:
            self.logger.error(f"Failed to get historical data: {response}")
            return []
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        """Place a market order."""
        if not self.is_connected():
            return {'error': 'Not connected to NinjaTrader'}
        
        order_data = {
            'instrument': symbol,
            'action': side.upper(),
            'quantity': quantity,
            'orderType': 'MARKET',
            'timeInForce': 'DAY'
        }
        
        if self.simulation:
            order_data['account'] = 'Sim101'  # Default simulation account
        
        return self._make_request('POST', '/orders', order_data)
    
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        """Place a limit order."""
        if not self.is_connected():
            return {'error': 'Not connected to NinjaTrader'}
        
        order_data = {
            'instrument': symbol,
            'action': side.upper(),
            'quantity': quantity,
            'orderType': 'LIMIT',
            'limitPrice': price,
            'timeInForce': 'GTC'
        }
        
        if self.simulation:
            order_data['account'] = 'Sim101'
        
        return self._make_request('POST', '/orders', order_data)
    
    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        """Place a stop order."""
        if not self.is_connected():
            return {'error': 'Not connected to NinjaTrader'}
        
        order_data = {
            'instrument': symbol,
            'action': side.upper(),
            'quantity': quantity,
            'orderType': 'STOP_MARKET',
            'stopPrice': stop_price,
            'timeInForce': 'GTC'
        }
        
        if self.simulation:
            order_data['account'] = 'Sim101'
        
        return self._make_request('POST', '/orders', order_data)
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        if not self.is_connected():
            return False
        
        response = self._make_request('DELETE', f'/orders/{order_id}')
        return 'error' not in response
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/orders')
        
        if isinstance(response, list):
            orders = []
            for order in response:
                if order.get('orderState') in ['Working', 'Accepted']:
                    if symbol is None or order.get('instrument') == symbol:
                        orders.append(order)
            return orders
        return []
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current positions."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/positions')
        
        if isinstance(response, list):
            positions = []
            for pos in response:
                if pos.get('quantity', 0) != 0:  # Only return non-zero positions
                    if symbol is None or pos.get('instrument') == symbol:
                        positions.append(pos)
            return positions
        return []
    
    def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get order history."""
        if not self.is_connected():
            return []
        
        response = self._make_request('GET', '/orders/history')
        
        if isinstance(response, list):
            history = []
            for order in response:
                if symbol is None or order.get('instrument') == symbol:
                    history.append(order)
            return history[:limit]
        return []
    
    def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        if not self.is_connected():
            return {}
        
        account_info = self.get_account_info()
        
        if isinstance(account_info, list) and len(account_info) > 0:
            account = account_info[0]
            return {
                'USD': {
                    'free': account.get('buyingPower', 0.0),
                    'locked': 0.0,  # Would need to calculate from open positions
                    'total': account.get('netLiquidation', 0.0)
                }
            }
        return {}
    
    def get_platform_name(self) -> str:
        """Get the platform name."""
        return "NinjaTrader"

