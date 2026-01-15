"""
Tradovate API Implementation

This module provides a concrete implementation of the TradingAPIInterface
for Tradovate futures trading platform.
"""

import logging
import requests
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import websocket
import threading

from api_interface import (
    TradingAPIInterface, MarketData, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)

class TradovateAPI(TradingAPIInterface):
    """Tradovate API implementation."""
    
    def __init__(self, username: str, password: str, app_id: str, 
                 app_version: str, cid: str, sec: str, demo: bool = True):
        """
        Initialize Tradovate API client.
        
        Args:
            username: Tradovate username
            password: Tradovate password
            app_id: Application ID
            app_version: Application version
            cid: Client ID
            sec: Secret
            demo: Whether to use demo environment (default: True)
        """
        self.username = username
        self.password = password
        self.app_id = app_id
        self.app_version = app_version
        self.cid = cid
        self.sec = sec
        self.demo = demo
        
        self.base_url = "https://demo.tradovateapi.com/v1" if demo else "https://live.tradovateapi.com/v1"
        self.ws_url = "wss://demo.tradovateapi.com/v1/websocket" if demo else "wss://live.tradovateapi.com/v1/websocket"
        
        self.access_token = None
        self.md_access_token = None
        self._connected = False
        self.ws = None
        self.account_id = None
    
    def connect(self) -> bool:
        """Establish connection to Tradovate."""
        try:
            # Get access token
            auth_data = {
                "name": self.username,
                "password": self.password,
                "appId": self.app_id,
                "appVersion": self.app_version,
                "cid": self.cid,
                "sec": self.sec
            }
            
            response = requests.post(
                f"{self.base_url}/auth/accesstokenrequest",
                json=auth_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get("accessToken")
                self.md_access_token = result.get("mdAccessToken")
                
                # Get account information
                self._get_account_info_on_connect()
                
                self._connected = True
                logger.info(f"Connected to Tradovate (demo: {self.demo})")
                return True
            else:
                logger.error(f"Failed to authenticate with Tradovate: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Tradovate: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from Tradovate."""
        if self.ws:
            self.ws.close()
        self.access_token = None
        self.md_access_token = None
        self._connected = False
        logger.info("Disconnected from Tradovate")
        return True
    
    def is_connected(self) -> bool:
        """Check if connected to Tradovate."""
        return self._connected and self.access_token is not None
    
    def _get_account_info_on_connect(self):
        """Get account ID on connection."""
        try:
            response = requests.get(
                f"{self.base_url}/account/list",
                headers={"Authorization": f"Bearer {self.access_token}"}
            )
            
            if response.status_code == 200:
                accounts = response.json()
                if accounts:
                    self.account_id = accounts[0].get("id")
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make authenticated request to Tradovate API."""
        try:
            if not self.is_connected():
                return None
            
            headers = {"Authorization": f"Bearer {self.access_token}"}
            if data:
                headers["Content-Type"] = "application/json"
            
            url = f"{self.base_url}{endpoint}"
            
            if method.upper() == "GET":
                response = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return None
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error making request to {endpoint}: {e}")
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            # First, get contract ID for symbol
            contract_data = self._make_request("GET", f"/contract/find?name={symbol}")
            if not contract_data:
                return None
            
            contract_id = contract_data.get("id")
            if not contract_id:
                return None
            
            # Get current quote
            quote_data = self._make_request("GET", f"/md/getquote?contractId={contract_id}")
            if quote_data:
                # Return mid price or last price
                bid = quote_data.get("bid")
                ask = quote_data.get("ask")
                if bid and ask:
                    return (float(bid) + float(ask)) / 2
                return quote_data.get("last")
            
            return None
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    def get_market_data(self, symbol: str, timeframe: str = '1m', 
                       limit: int = 100) -> List[MarketData]:
        """Get historical market data."""
        try:
            # This is a simplified implementation
            # In practice, you'd need to use Tradovate's chart data endpoints
            logger.warning("Historical market data not fully implemented for Tradovate")
            return []
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return []
    
    def get_price_range(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """Get min and max prices from N hours back."""
        try:
            # This would require historical data implementation
            logger.warning("Price range calculation not fully implemented for Tradovate")
            return 0.0, 0.0
        except Exception as e:
            logger.error(f"Error getting price range for {symbol}: {e}")
            return 0.0, 0.0
    
    def get_yesterday_range(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """Get yesterday's day and night price ranges."""
        try:
            # This would require historical data implementation
            logger.warning("Yesterday's range calculation not fully implemented for Tradovate")
            return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
        except Exception as e:
            logger.error(f"Error getting yesterday's range for {symbol}: {e}")
            return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
    
    def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                   quantity: float, price: Optional[float] = None,
                   stop_price: Optional[float] = None) -> Optional[Order]:
        """Place a trading order."""
        try:
            if not self.is_connected() or not self.account_id:
                return None
            
            # Get contract ID for symbol
            contract_data = self._make_request("GET", f"/contract/find?name={symbol}")
            if not contract_data:
                return None
            
            contract_id = contract_data.get("id")
            if not contract_id:
                return None
            
            # Prepare order data
            order_data = {
                "accountSpec": self.username,
                "accountId": self.account_id,
                "action": "Buy" if side == OrderSide.BUY else "Sell",
                "symbol": symbol,
                "orderQty": int(quantity),
                "isAutomated": True
            }
            
            if order_type == OrderType.MARKET:
                order_data["orderType"] = "Market"
            elif order_type == OrderType.LIMIT:
                order_data["orderType"] = "Limit"
                order_data["price"] = price
            else:
                logger.error(f"Order type {order_type} not implemented for Tradovate")
                return None
            
            # Place order
            result = self._make_request("POST", "/order/placeorder", order_data)
            if result and not result.get("errorText"):
                # Convert to standardized Order object
                order = Order(
                    order_id=str(result.get("orderId", "")),
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
                logger.error(f"Order placement failed: {result.get('errorText', 'Unknown error')}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        try:
            if not self.is_connected():
                return False
            
            cancel_data = {"orderId": int(order_id)}
            result = self._make_request("POST", "/order/cancelorder", cancel_data)
            
            return result is not None and not result.get("errorText")
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get status of a specific order."""
        try:
            if not self.is_connected():
                return None
            
            result = self._make_request("GET", f"/order/item?id={order_id}")
            if result:
                return self._convert_to_order(result)
            return None
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {e}")
            return None
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders."""
        try:
            if not self.is_connected() or not self.account_id:
                return []
            
            result = self._make_request("GET", f"/order/deps?masterid={self.account_id}")
            if not result:
                return []
            
            orders = []
            for order_data in result:
                if order_data.get("ordStatus") in ["Working", "Pending"]:
                    order = self._convert_to_order(order_data)
                    if order and (not symbol or order.symbol == symbol):
                        orders.append(order)
            
            return orders
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []
    
    def get_account_info(self) -> Optional[AccountInfo]:
        """Get account information."""
        try:
            if not self.is_connected() or not self.account_id:
                return None
            
            account_data = self._make_request("GET", f"/account/item?id={self.account_id}")
            if not account_data:
                return None
            
            positions = self.get_positions()
            
            account_info = AccountInfo(
                account_id=str(self.account_id),
                balance=float(account_data.get("balance", 0)),
                available_margin=float(account_data.get("availableBalance", 0)),
                used_margin=float(account_data.get("marginUsed", 0)),
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
            if not self.is_connected() or not self.account_id:
                return []
            
            result = self._make_request("GET", f"/position/deps?masterid={self.account_id}")
            if not result:
                return []
            
            positions = []
            for pos_data in result:
                if pos_data.get("netPos", 0) != 0:  # Only non-zero positions
                    position = Position(
                        symbol=pos_data.get("contractName", ""),
                        quantity=float(pos_data.get("netPos", 0)),
                        average_price=float(pos_data.get("avgPrice", 0)),
                        unrealized_pnl=float(pos_data.get("unrealizedPnL", 0)),
                        realized_pnl=float(pos_data.get("realizedPnL", 0)),
                        timestamp=datetime.now()
                    )
                    
                    if not symbol or position.symbol == symbol:
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
            
            # Get all products (simplified - in practice you'd want to filter)
            result = self._make_request("GET", "/product/list")
            if result:
                return [product.get("name", "") for product in result if product.get("name")]
            return []
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate if a symbol is available for trading."""
        try:
            contract_data = self._make_request("GET", f"/contract/find?name={symbol}")
            return contract_data is not None and contract_data.get("id") is not None
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    def get_platform_name(self) -> str:
        """Get the name of the trading platform."""
        return "Tradovate"
    
    def _convert_to_order(self, order_data: Dict) -> Optional[Order]:
        """Convert Tradovate order data to standardized Order object."""
        try:
            order = Order(
                order_id=str(order_data.get("id", "")),
                symbol=order_data.get("contractName", ""),
                side=OrderSide.BUY if order_data.get("action") == "Buy" else OrderSide.SELL,
                order_type=self._convert_order_type(order_data.get("orderType", "")),
                quantity=float(order_data.get("orderQty", 0)),
                price=float(order_data.get("price", 0)) if order_data.get("price") else None,
                status=self._convert_order_status(order_data.get("ordStatus", "")),
                timestamp=datetime.now(),  # Tradovate timestamps would need parsing
                filled_quantity=float(order_data.get("filledQty", 0))
            )
            return order
        except Exception as e:
            logger.error(f"Error converting order data: {e}")
            return None
    
    def _convert_order_status(self, tradovate_status: str) -> OrderStatus:
        """Convert Tradovate order status to standardized status."""
        status_map = {
            "Working": OrderStatus.PENDING,
            "Pending": OrderStatus.PENDING,
            "Filled": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "Rejected": OrderStatus.REJECTED,
            "PartFilled": OrderStatus.PARTIALLY_FILLED
        }
        return status_map.get(tradovate_status, OrderStatus.PENDING)
    
    def _convert_order_type(self, tradovate_type: str) -> OrderType:
        """Convert Tradovate order type to standardized type."""
        type_map = {
            "Market": OrderType.MARKET,
            "Limit": OrderType.LIMIT,
            "Stop": OrderType.STOP,
            "StopLimit": OrderType.STOP_LIMIT
        }
        return type_map.get(tradovate_type, OrderType.MARKET)

