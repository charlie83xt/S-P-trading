"""
NinjaTrader API Implementation

This module provides a concrete implementation of the TradingAPIInterface
for NinjaTrader futures trading platform.

Note: This implementation assumes the use of NinjaTrader's REST API or
a third-party wrapper like CrossTrade API for remote access.
"""

import logging
import requests
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from api_interface import (
    TradingAPIInterface, MarketData, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)

class NinjaTraderAPI(TradingAPIInterface):
    """NinjaTrader API implementation."""
    
    def __init__(self, api_url: str = "http://localhost:8080", 
                 api_key: Optional[str] = None, simulation: bool = True):
        """
        Initialize NinjaTrader API client.
        
        Args:
            api_url: Base URL for NinjaTrader API (local or remote)
            api_key: API key if using remote access
            simulation: Whether to use simulation mode (default: True)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.simulation = simulation
        self._connected = False
        self.session = requests.Session()
        
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
    
    def connect(self) -> bool:
        """Establish connection to NinjaTrader."""
        try:
            # Test connection by getting account info
            response = self.session.get(f"{self.api_url}/accounts")
            
            if response.status_code == 200:
                self._connected = True
                logger.info(f"Connected to NinjaTrader (simulation: {self.simulation})")
                return True
            else:
                logger.error(f"Failed to connect to NinjaTrader: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to NinjaTrader: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from NinjaTrader."""
        self._connected = False
        logger.info("Disconnected from NinjaTrader")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to NinjaTrader."""
        return self._connected
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to NinjaTrader API."""
        try:
            if not self.is_connected():
                return None
            
            url = f"{self.api_url}{endpoint}"
            
            if method.upper() == "GET":
                response = self.session.get(url, params=data)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            elif method.upper() == "PUT":
                response = self.session.put(url, json=data)
            elif method.upper() == "DELETE":
                response = self.session.delete(url)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return None
            
            if response.status_code in [200, 201]:
                return response.json() if response.content else {}
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error making request to {endpoint}: {e}")
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            result = self._make_request("GET", f"/marketdata/{symbol}/last")
            if result:
                return float(result.get("price", 0))
            return None
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    def get_market_data(self, symbol: str, timeframe: str = '1m', 
                       limit: int = 100) -> List[MarketData]:
        """Get historical market data."""
        try:
            params = {
                "instrument": symbol,
                "interval": timeframe,
                "count": limit
            }
            
            result = self._make_request("GET", "/marketdata/bars", params)
            if not result or "bars" not in result:
                return []
            
            market_data = []
            for bar in result["bars"]:
                data = MarketData(
                    symbol=symbol,
                    timestamp=datetime.fromisoformat(bar["time"]),
                    open_price=float(bar["open"]),
                    high_price=float(bar["high"]),
                    low_price=float(bar["low"]),
                    close_price=float(bar["close"]),
                    volume=float(bar["volume"])
                )
                market_data.append(data)
            
            return market_data
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return []
    
    def get_price_range(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """Get min and max prices from N hours back."""
        try:
            # Get minute bars for the specified period
            market_data = self.get_market_data(symbol, "1m", hours_back * 60)
            
            if not market_data:
                return 0.0, 0.0
            
            prices = []
            for data in market_data:
                prices.extend([data.high_price, data.low_price])
            
            return min(prices), max(prices)
        except Exception as e:
            logger.error(f"Error getting price range for {symbol}: {e}")
            return 0.0, 0.0
    
    def get_yesterday_range(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """Get yesterday's day and night price ranges."""
        try:
            # Get yesterday's data (1440 minutes = 24 hours)
            yesterday_data = self.get_market_data(symbol, "1m", 1440)
            
            if not yesterday_data:
                return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
            
            day_prices = []
            night_prices = []
            
            for data in yesterday_data:
                hour = data.timestamp.hour
                
                if 9 <= hour < 16:  # Day session (9:30 AM - 4:00 PM EST, simplified)
                    day_prices.extend([data.high_price, data.low_price])
                else:  # Night session
                    night_prices.extend([data.high_price, data.low_price])
            
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
            
            order_data = {
                "instrument": symbol,
                "action": "BUY" if side == OrderSide.BUY else "SELL",
                "quantity": int(quantity),
                "orderType": self._convert_to_nt_order_type(order_type)
            }
            
            if order_type == OrderType.LIMIT and price:
                order_data["limitPrice"] = price
            elif order_type == OrderType.STOP and stop_price:
                order_data["stopPrice"] = stop_price
            elif order_type == OrderType.STOP_LIMIT and price and stop_price:
                order_data["limitPrice"] = price
                order_data["stopPrice"] = stop_price
            
            result = self._make_request("POST", "/orders", order_data)
            if result and "orderId" in result:
                order = Order(
                    order_id=str(result["orderId"]),
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    status=OrderStatus.PENDING,
                    timestamp=datetime.now()
                )
                return order
            else:
                logger.error(f"Order placement failed: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        try:
            if not self.is_connected():
                return False
            
            result = self._make_request("DELETE", f"/orders/{order_id}")
            return result is not None
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get status of a specific order."""
        try:
            if not self.is_connected():
                return None
            
            result = self._make_request("GET", f"/orders/{order_id}")
            if result:
                return self._convert_to_order(result)
            return None
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {e}")
            return None
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders."""
        try:
            if not self.is_connected():
                return []
            
            params = {"instrument": symbol} if symbol else {}
            result = self._make_request("GET", "/orders", params)
            
            if not result or "orders" not in result:
                return []
            
            orders = []
            for order_data in result["orders"]:
                if order_data.get("orderState") in ["Working", "Accepted", "PendingSubmit"]:
                    order = self._convert_to_order(order_data)
                    if order:
                        orders.append(order)
            
            return orders
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []
    
    def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information."""
        try:
            if not self.is_connected():
                return None
            
            result = self._make_request("GET", "/accounts")
            if not result or "accounts" not in result:
                return None
            
            # Assume first account
            account_data = result["accounts"][0]
            positions = self.get_positions()
            
            account_info = AccountInfo(
                account_id=str(account_data.get("account", "default")),
                balance=float(account_data.get("cashValue", 0)),
                available_margin=float(account_data.get("buyingPower", 0)),
                used_margin=float(account_data.get("initialMargin", 0)),
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
            
            params = {"instrument": symbol} if symbol else {}
            result = self._make_request("GET", "/positions", params)
            
            if not result or "positions" not in result:
                return []
            
            positions = []
            for pos_data in result["positions"]:
                if pos_data.get("quantity", 0) != 0:  # Only non-zero positions
                    position = Position(
                        symbol=pos_data.get("instrument", ""),
                        quantity=float(pos_data.get("quantity", 0)),
                        average_price=float(pos_data.get("averagePrice", 0)),
                        unrealized_pnl=float(pos_data.get("unrealizedPnL", 0)),
                        realized_pnl=float(pos_data.get("realizedPnL", 0)),
                        timestamp=datetime.now()
                    )
                    positions.append(position)
            
            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols."""
        try:
            if not self.is_connected():
                return []
            
            result = self._make_request("GET", "/instruments")
            if result and "instruments" in result:
                return [instr.get("name", "") for instr in result["instruments"]]
            return []
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
        return "NinjaTrader"
    
    def _convert_to_order(self, order_data: Dict) -> Optional[Order]:
        """Convert NinjaTrader order data to standardized Order object."""
        try:
            order = Order(
                order_id=str(order_data.get("orderId", "")),
                symbol=order_data.get("instrument", ""),
                side=OrderSide.BUY if order_data.get("action") == "BUY" else OrderSide.SELL,
                order_type=self._convert_from_nt_order_type(order_data.get("orderType", "")),
                quantity=float(order_data.get("quantity", 0)),
                price=float(order_data.get("limitPrice", 0)) if order_data.get("limitPrice") else None,
                status=self._convert_order_status(order_data.get("orderState", "")),
                timestamp=datetime.now(),  # Would need proper timestamp parsing
                filled_quantity=float(order_data.get("filled", 0))
            )
            return order
        except Exception as e:
            logger.error(f"Error converting order data: {e}")
            return None
    
    def _convert_order_status(self, nt_status: str) -> OrderStatus:
        """Convert NinjaTrader order status to standardized status."""
        status_map = {
            "Working": OrderStatus.PENDING,
            "Accepted": OrderStatus.PENDING,
            "PendingSubmit": OrderStatus.PENDING,
            "Filled": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "Rejected": OrderStatus.REJECTED,
            "PartFilled": OrderStatus.PARTIALLY_FILLED
        }
        return status_map.get(nt_status, OrderStatus.PENDING)
    
    def _convert_to_nt_order_type(self, order_type: OrderType) -> str:
        """Convert standardized order type to NinjaTrader type."""
        type_map = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP: "STOP_MARKET",
            OrderType.STOP_LIMIT: "STOP_LIMIT"
        }
        return type_map.get(order_type, "MARKET")
    
    def _convert_from_nt_order_type(self, nt_type: str) -> OrderType:
        """Convert NinjaTrader order type to standardized type."""
        type_map = {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP_MARKET": OrderType.STOP,
            "STOP_LIMIT": OrderType.STOP_LIMIT
        }
        return type_map.get(nt_type, OrderType.MARKET)

