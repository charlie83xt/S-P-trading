"""
Data Manager module for handling market data ingestion, storage, and retrieval.
Supports both real-time and historical data management across multiple platforms.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import sqlite3
import json
from config import get_config
from api_factory import APIFactory
from api_interface import TradingAPIInterface, MarketData

logger = logging.getLogger(__name__)

class DataManager:
    """Manages market data ingestion, storage, and retrieval across platforms."""
    
    def __init__(self):
        self.config = get_config()
        self.api: Optional[TradingAPIInterface] = None
        self.db_connection = None
        self._initialize_api()
        self._initialize_database()
    
    def _initialize_api(self):
        """Initialize trading API based on configuration."""
        try:
            self.api = APIFactory.create_api()
            if self.api and self.api.connect():
                logger.info(f"Data manager connected to {self.api.get_platform_name()}")
            else:
                logger.error("Failed to initialize trading API")
                raise Exception("API initialization failed")
        except Exception as e:
            logger.error(f"Failed to initialize API: {e}")
            raise
    
    def _initialize_database(self):
        """Initialize database connection and create tables."""
        try:
            self.db_connection = sqlite3.connect('trading_data.db', check_same_thread=False)
            self._create_tables()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _create_tables(self):
        """Create necessary database tables."""
        cursor = self.db_connection.cursor()
        
        # OHLCV data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ohlcv_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                close_price REAL NOT NULL,
                volume REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, timestamp)
            )
        ''')
        
        # Price data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                price REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Opening range data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS opening_ranges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                range_start INTEGER NOT NULL,
                range_end INTEGER NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                range_size REAL NOT NULL,
                volume REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, date)
            )
        ''')
        
        self.db_connection.commit()
        logger.info("Database tables created successfully")
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current market price for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current price or None if unavailable
        """
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return None
            
            price = self.api.get_current_price(symbol)
            if price:
                self._store_price_data(symbol, price)
            
            return price
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    def get_historical_data(self, symbol: str, timeframe: str = '1m', 
                          limit: int = 100) -> pd.DataFrame:
        """
        Retrieve historical OHLCV data for a symbol.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1m', '5m', '1h', '1d')
            limit: Maximum number of records to retrieve
            
        Returns:
            DataFrame with OHLCV data
        """
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return pd.DataFrame()
            
            # Get data from API
            market_data = self.api.get_market_data(symbol, timeframe, limit)
            
            if not market_data:
                return pd.DataFrame()
            
            # Convert to DataFrame
            data_list = []
            for data in market_data:
                data_list.append({
                    'timestamp': data.timestamp,
                    'open_price': data.open_price,
                    'high_price': data.high_price,
                    'low_price': data.low_price,
                    'close_price': data.close_price,
                    'volume': data.volume
                })
            
            df = pd.DataFrame(data_list)
            if not df.empty:
                df.set_index('timestamp', inplace=True)
                # Store in database
                self._store_ohlcv_data(df, symbol, timeframe)
            
            return df
            
        except Exception as e:
            logger.error(f"Error retrieving historical data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_min_max_prices_hours_back(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """
        Get minimum and maximum prices from N hours back.
        
        Args:
            symbol: Trading symbol
            hours_back: Number of hours to look back
            
        Returns:
            Tuple of (min_price, max_price)
        """
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return 0.0, 0.0
            
            return self.api.get_price_range(symbol, hours_back)
            
        except Exception as e:
            logger.error(f"Error getting price range for {symbol}: {e}")
            return 0.0, 0.0
    
    def get_yesterday_day_night_ranges(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """
        Get yesterday's day and night price ranges.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict with 'day' and 'night' keys, each containing (min, max) tuples
        """
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
            
            return self.api.get_yesterday_range(symbol)
            
        except Exception as e:
            logger.error(f"Error getting yesterday's ranges for {symbol}: {e}")
            return {'day': (0.0, 0.0), 'night': (0.0, 0.0)}
    
    def calculate_opening_range(self, symbol: str, range_minutes: int = 30) -> Optional[Dict]:
        """
        Calculate opening range for a symbol.
        
        Args:
            symbol: Trading symbol
            range_minutes: Number of minutes for opening range
            
        Returns:
            Dict with opening range data or None
        """
        try:
            # Get minute data for the opening range period
            market_data = self.get_historical_data(symbol, '1m', range_minutes)
            
            if market_data.empty:
                return None
            
            # Calculate opening range
            high_price = market_data['high_price'].max()
            low_price = market_data['low_price'].min()
            range_size = high_price - low_price
            total_volume = market_data['volume'].sum()
            
            opening_range = {
                'symbol': symbol,
                'high': high_price,
                'low': low_price,
                'range_size': range_size,
                'volume': total_volume,
                'start_time': market_data.index[0],
                'end_time': market_data.index[-1]
            }
            
            # Store opening range data
            self._store_opening_range(opening_range)
            
            return opening_range
            
        except Exception as e:
            logger.error(f"Error calculating opening range for {symbol}: {e}")
            return None
    
    def _store_price_data(self, symbol: str, price: float):
        """Store current price data in database."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                INSERT INTO price_data (symbol, timestamp, price)
                VALUES (?, ?, ?)
            ''', (symbol, int(datetime.now().timestamp() * 1000), price))
            self.db_connection.commit()
        except Exception as e:
            logger.error(f"Error storing price data: {e}")
    
    def _store_ohlcv_data(self, df: pd.DataFrame, symbol: str, timeframe: str):
        """Store OHLCV data in database."""
        try:
            cursor = self.db_connection.cursor()
            for timestamp, row in df.iterrows():
                cursor.execute('''
                    INSERT OR REPLACE INTO ohlcv_data 
                    (symbol, timeframe, timestamp, open_price, high_price, low_price, close_price, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    symbol, timeframe, int(timestamp.timestamp() * 1000),
                    row['open_price'], row['high_price'], row['low_price'],
                    row['close_price'], row['volume']
                ))
            self.db_connection.commit()
        except Exception as e:
            logger.error(f"Error storing OHLCV data: {e}")
    
    def _store_opening_range(self, opening_range: Dict):
        """Store opening range data in database."""
        try:
            cursor = self.db_connection.cursor()
            date_str = opening_range['start_time'].strftime('%Y-%m-%d')
            
            cursor.execute('''
                INSERT OR REPLACE INTO opening_ranges
                (symbol, date, range_start, range_end, high_price, low_price, range_size, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                opening_range['symbol'], date_str,
                int(opening_range['start_time'].timestamp() * 1000),
                int(opening_range['end_time'].timestamp() * 1000),
                opening_range['high'], opening_range['low'],
                opening_range['range_size'], opening_range['volume']
            ))
            self.db_connection.commit()
        except Exception as e:
            logger.error(f"Error storing opening range data: {e}")
    
    def get_available_symbols(self) -> List[str]:
        """Get list of available trading symbols."""
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return []
            
            return self.api.get_available_symbols()
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate if a symbol is available for trading."""
        try:
            if not self.api or not self.api.is_connected():
                logger.error("API not connected")
                return False
            
            return self.api.validate_symbol(symbol)
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from API and close database connection."""
        try:
            if self.api:
                self.api.disconnect()
            if self.db_connection:
                self.db_connection.close()
            logger.info("Data manager disconnected")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    def __del__(self):
        """Cleanup on object destruction."""
        self.disconnect()

