"""
Binance Futures API implementation.
"""

import requests
import hmac
import hashlib
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from api_interface import TradingAPIInterface

class BinanceAPI(TradingAPIInterface):
    """Binance Futures API implementation."""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """
        Initialize Binance API.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            testnet: Whether to use testnet
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.base_url = 'https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
        self.connected = False
        self.logger = logging.getLogger(__name__)
        
    def _generate_signature(self, query_string: str) -> str:
        """Generate signature for authenticated requests."""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False) -> Dict:
        """Make HTTP request to Binance API."""
        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key} if self.api_key else {}
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            params['signature'] = self._generate_signature(query_string)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(url, params=params, headers=headers, timeout=10)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, params=params, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Binance API request failed: {e}")
            return {'error': str(e)}
    
    def connect(self) -> bool:
        """Establish connection to Binance."""
        try:
            # Test connection by getting server time
            response = self._make_request('GET', '/fapi/v1/time')
            if 'serverTime' in response:
                self.connected = True
                self.logger.info("Connected to Binance Futures API")
                return True
            else:
                self.logger.error("Failed to connect to Binance")
                return False
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from Binance."""
        self.connected = False
        self.logger.info("Disconnected from Binance")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to Binance."""
        return self.connected
    
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        if not self.api_key or not self.api_secret:
            return {'error': 'API credentials not provided'}
        
        return self._make_request('GET', '/fapi/v2/account', signed=True)
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        response = self._make_request('GET', '/fapi/v1/ticker/price', {'symbol': symbol})
        if 'price' in response:
            return float(response['price'])
        else:
            self.logger.error(f"Failed to get price for {symbol}: {response}")
            return 0.0
    
    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> List[Dict]:
        """Get historical kline data."""
        params = {
            'symbol': symbol,
            'interval': timeframe,
            'limit': limit
        }
        
        response = self._make_request('GET', '/fapi/v1/klines', params)
        
        if isinstance(response, list):
            # Convert Binance kline format to standard format
            data = []
            for kline in response:
                data.append({
                    'timestamp': kline[0],
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            return data
        else:
            self.logger.error(f"Failed to get historical data: {response}")
            return []
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        """Place a market order."""
        if not self.api_key or not self.api_secret:
            return {'error': 'API credentials not provided'}
        
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': quantity
        }
        
        return self._make_request('POST', '/fapi/v1/order', params, signed=True)
    
    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        """Place a limit order."""
        if not self.api_key or not self.api_secret:
            return {'error': 'API credentials not provided'}
        
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'LIMIT',
            'quantity': quantity,
            'price': price,
            'timeInForce': 'GTC'
        }
        
        return self._make_request('POST', '/fapi/v1/order', params, signed=True)
    
    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        """Place a stop market order."""
        if not self.api_key or not self.api_secret:
            return {'error': 'API credentials not provided'}
        
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': 'STOP_MARKET',
            'quantity': quantity,
            'stopPrice': stop_price
        }
        
        return self._make_request('POST', '/fapi/v1/order', params, signed=True)
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        if not self.api_key or not self.api_secret:
            return False
        
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        
        response = self._make_request('DELETE', '/fapi/v1/order', params, signed=True)
        return 'orderId' in response
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        if not self.api_key or not self.api_secret:
            return []
        
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        response = self._make_request('GET', '/fapi/v1/openOrders', params, signed=True)
        return response if isinstance(response, list) else []
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current positions."""
        if not self.api_key or not self.api_secret:
            return []
        
        response = self._make_request('GET', '/fapi/v2/positionRisk', signed=True)
        
        if isinstance(response, list):
            positions = []
            for pos in response:
                if float(pos['positionAmt']) != 0:  # Only return non-zero positions
                    if symbol is None or pos['symbol'] == symbol:
                        positions.append(pos)
            return positions
        return []
    
    def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get order history."""
        if not self.api_key or not self.api_secret:
            return []
        
        params = {'limit': limit}
        if symbol:
            params['symbol'] = symbol
        
        response = self._make_request('GET', '/fapi/v1/allOrders', params, signed=True)
        return response if isinstance(response, list) else []
    
    def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        account_info = self.get_account_info()
        
        if 'assets' in account_info:
            balance = {}
            for asset in account_info['assets']:
                if float(asset['walletBalance']) > 0:
                    balance[asset['asset']] = {
                        'free': float(asset['availableBalance']),
                        'locked': float(asset['walletBalance']) - float(asset['availableBalance']),
                        'total': float(asset['walletBalance'])
                    }
            return balance
        return {}
    
    def get_platform_name(self) -> str:
        """Get the platform name."""
        return "Binance Futures"

