"""
Data Manager for handling market data across different trading platforms.
"""

import pandas as pd
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Deque, Any
import logging
import os
import math
from collections import defaultdict, deque
from dataclasses import dataclass

from api_factory import APIFactory
from api_interface import TradingAPIInterface
from config import Config
import time

@dataclass
class Bar:
    ts_open: float # epoch at bar open
    open: float
    high: float
    low: float
    close: float

class LiveBarStore:
    """
    Keeps rolling 1m bars per symbol from streaming Last prices
    """
    def __init__(self, keep: int = 480):
        self.keep = int(keep)
        # self._bars: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.keep))
        # self._working: Dict[str, Dict[str, Any]] = {}
        # self._per_symbol: Dict[str, Deque[Bar]] = {}
        # deque of Bar(ts_open, open, high, low, close) per symbol
        self._per_symbol: Dict[str, Deque[Bar]] = defaultdict(lambda: deque(maxlen=self.keep))
    
    
    def _bucket_start(self, t: float) -> float:
        # minute-aligned timestamp
        return math.floor(t / 60.0) * 60.0

    def ingest_tick(self, symbol: str, ts: float, price: Optional[float]) -> None:
        if price is None or not isinstance(price, (int, float)) or price != price:
            return
        dq = self._per_symbol[symbol] #.setdefault(symbol, deque(maxlen=self.keep))
        bstart = self._bucket_start(ts)

        if not dq or dq[-1].ts_open < bstart:
            # start a new bar
            dq.append(Bar(bstart, price, price, price, price))
        else:
            # update current bar
            b = dq[-1]
            b.close = float(price)
            if price > b.high:
                b.high = float(price)
            if price < b.low:
                b.low = float(price)
            # b.close = price

    def get_last_n(self, symbol: str, n: int = 60) -> List[Bar]:
        dq = self._per_symbol.get(symbol)
        if not dq:
            return []
        return list(dq)[-n:]

    def get_bars(self, symbol: str, n: int = 60) -> List[Any]:
        # include working bar as a provisional last bar
        # self._ensure_tick_buf()
        # ticks = list(self._tick_buf.get(symbol, []))[-n:]
        # if not ticks:
        #     return []
        return self.get_last_n(symbol, n)

        # simple OHLC "bars" from ticks: 1 tick -> flat bar
        # class Bar: pass
        # Bar = type("Bar", (), {})
        # bars = list(self._bars[symbol])
        ###########
        # bars = []
        # for ts, px in ticks:
        #     b = Bar()
        #     b.time = ts
        #     b.open = px
        #     b.high = px
        #     b.low = px
        #     b.close = px
        #     bars.append(b)
        ################
        # if symbol in self._working:
        #     bars = bars + [self._working[symbol]]
        # return bars


    def get_opening_range(self, symbol: str, minutes: int, session_anchor_ts: float) -> Optional[Tuple[float, float]]:
        """
        Compute (low, high) of first `minutes` minutes since session_anchor_ts.
        """
        dq = self._per_symbol.get(symbol)
        if not dq:
            return None
        end_cut = session_anchor_ts + minutes * 60.0
        lows, highs = [], []
        for b in dq:
            if b.ts_open >= session_anchor_ts and b.ts_open < end_cut:
                lows.append(b.low)
                highs.append(b.high)
        if not lows or not highs:
            return None
        return (min(lows), max(highs))


class DataManager:
    """Manages market data retrieval and storage across different platforms."""
    
    # def __init__(self, platform: Optional[str] = None):
    def __init__(self, config: Config):
        """
        Initialize DataManager.
        
        Args:
            platform: Trading platform to use. If None, uses config default.
        """
        self.config = config
        # self.api: TradingAPIInterface = APIFactory.create_api(platform)
        self.api: TradingAPIInterface = APIFactory.create_api(config=self.config)
        self.logger = logging.getLogger(__name__)
        self.db_path = 'market_data.db'
        self._init_database()
        self._tick_buf = None

        self.live = LiveBarStore(keep=480)

    
    def _ensure_tick_buf(self):
        if self._tick_buf is None:
            self._tick_buf = defaultdict(lambda: deque(maxlen=3000))


    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        """
        Feed one price tick into the in-memory 1m bar builder
        """
        try:
            self.live.ingest_tick(symbol, ts_epoch, price)
        except Exception:
            # keep ingestion robust; never break the caller
            pass


    def get_bars(self, symbol: str, n: int = 60):
        """
        Return last n 1-minute bars (Bar dataclass) from the live store.
        """
        try:
            get_last_n = getattr(self.live, "get_last_n", None)
            if callable(get_last_n):
                return get_last_n(symbol, n)
            # fallback if your store uses a different name:
            get_bars = getattr(self.live, "get_bars", None)
            if callable(get_bars):
                return get_bars(symbol, n)
            return []
        except Exception:
            return []



    def _is_ui_platform(self) -> bool:
        """True when we're using the Tradovate UI driver (no historical candles)."""
        try:
            name = self.api.get_platform_name().lower()
        except Exception:
            name = ""
        return ("tradovate" in name and "ui" in name) or ("web" in name and "ui" in name)

        
    def _init_database(self):
        """Initialize SQLite database for storing market data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create table for storing OHLCV data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                platform TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timestamp, platform, timeframe)
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def connect(self) -> bool:
        """Connect to the trading platform."""
        return self.api.connect()
    
    def disconnect(self) -> bool:
        """Disconnect from the trading platform."""
        return self.api.disconnect()
    
    def is_connected(self) -> bool:
        """Check if connected to the trading platform."""
        return self.api.is_connected()
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current price
        """
        price = self.api.get_current_price(symbol)
        try:
            if price is None:
                self._null_reads = getattr(self, "_null_reads", 0) + 1
                if self._null_reads % 10 == 0:
                    self.logger.debug("Adapter returned None price x%d", self._null_reads)
                else:
                    self._null_reads = 0
                return None


            p = float(price)
            if p <= 0 or p != p:  # <=0 or NaN
                return price


            # keep a compact tick buffer for ad-hoc analytics
            self._ensure_tick_buf()
            self._tick_buf[symbol].append((datetime.now(timezone.utc), p))


            # feed the live bar builder
            now_ts = time.time()


            # prefer ingest_tick(symbol, t, price) if available
            now_ts = time.time()
            # if hasattr(self.live, "ingest_tick"):
            #     self.live.ingest_tick(symbol, now_ts, p)
            # elif hasattr(self.live, "update"):
            #     self.live.update(symbol, now_ts, p)
            ingest = getattr(self.live, "ingest_tick", None)
            if callable(ingest):
                ingest(symbol, now_ts, p)
            else:
                # fallback to update(symbol, ts_epoch, price) if that's what you have
                upd = getattr(self.live, "update", None)
                if callable(upd):
                    upd(symbol, now_ts, p)


            # occasional debug
            if len(self._tick_buf[symbol]) % 60 == 0:
                self.logger.debug("TickBuf[%s]: %d", symbol, len(self._tick_buf[symbol]))
        except Exception:
            # never break price reads
            pass

        return price

    
    def get_historical_data(self, symbol: str, timeframe: str = '1m', limit: int = 100, 
                          use_cache: bool = True) -> pd.DataFrame:
        """
        Get historical price data.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '1m', '5m', '1h', '1d')
            limit: Number of data points to retrieve
            use_cache: Whether to use cached data
            
        Returns:
            DataFrame with OHLCV data
        """
        # Try to get data from cache first
        if use_cache:
            cached_data = self._get_cached_data(symbol, timeframe, limit)
            if not cached_data.empty:
                self.logger.info(f"Using cached data for {symbol} {timeframe}")
                return cached_data
        
        # Fetch fresh data from API
        data = self.api.get_historical_data(symbol, timeframe, limit)
        
        if data:
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Cache the data
            self._cache_data(symbol, timeframe, df)
            
            return df
        else:
            # For UI-driven platforms this is expected; reduce log level
            if self._is_ui_platform():
                self.logger.debug(f"No historical data (UI platform) for {symbol}")
            else:
                self.logger.warning(f"No data received for {symbol} {timeframe}")
            return pd.DataFrame()
    
    def _get_cached_data(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Get cached data from database."""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = ? AND timeframe = ? AND platform = ?
            ORDER BY timestamp DESC
            LIMIT ?
        '''
        
        try:
            df = pd.read_sql_query(
                query, 
                conn, 
                params=(symbol, timeframe, self.api.get_platform_name(), limit)
            )
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                df = df.sort_index()  # Sort by timestamp ascending
            
            return df
        except Exception as e:
            self.logger.error(f"Error retrieving cached data: {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    
    def _cache_data(self, symbol: str, timeframe: str, df: pd.DataFrame):
        """Cache data to database."""
        if df.empty:
            return
        
        conn = sqlite3.connect(self.db_path)
        
        try:
            for timestamp, row in df.iterrows():
                timestamp_ms = int(timestamp.timestamp() * 1000)
                
                conn.execute('''
                    INSERT OR REPLACE INTO market_data 
                    (symbol, timestamp, open, high, low, close, volume, platform, timeframe)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    symbol, timestamp_ms, row['open'], row['high'], 
                    row['low'], row['close'], row['volume'],
                    self.api.get_platform_name(), timeframe
                ))
            
            conn.commit()
            self.logger.info(f"Cached {len(df)} data points for {symbol} {timeframe}")
            
        except Exception as e:
            self.logger.error(f"Error caching data: {e}")
        finally:
            conn.close()
    
    def get_price_range(self, symbol: str, hours_back: int) -> Tuple[float, float]:
        """
        Get min and max prices from N hours back.
        
        Args:
            symbol: Trading symbol
            hours_back: Number of hours to look back
            
        Returns:
            Tuple of (min_price, max_price)
        """
        # Calculate how many 1-minute candles we need
        limit = hours_back * 60
        
        df = self.get_historical_data(symbol, '1m', limit)
        
        if df.empty:
            current_price = self.get_current_price(symbol)
            return current_price, current_price
        
        return df['low'].min(), df['high'].max()
    
    def get_yesterday_range(self, symbol: str) -> Dict[str, Tuple[float, float]]:
        """
        Get yesterday's price ranges for day and night sessions.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dictionary with 'day' and 'night' ranges
        """
        # Get 2 days of data to ensure we have yesterday's complete data
        df = self.get_historical_data(symbol, '1h', 48)
        
        if df.empty:
            current_price = self.get_current_price(symbol)
            return {
                'day': (current_price, current_price),
                'night': (current_price, current_price)
            }
        
        # Get yesterday's date
        yesterday = datetime.now().date() - timedelta(days=1)
        
        # Filter for yesterday's data
        yesterday_data = df[df.index.date == yesterday]
        
        if yesterday_data.empty:
            current_price = self.get_current_price(symbol)
            return {
                'day': (current_price, current_price),
                'night': (current_price, current_price)
            }
        
        # Split into day (9:30 AM - 4:00 PM) and night sessions
        day_data = yesterday_data.between_time('09:30', '16:00')
        night_data = yesterday_data[~yesterday_data.index.isin(day_data.index)]
        
        day_range = (day_data['low'].min(), day_data['high'].max()) if not day_data.empty else (0, 0)
        night_range = (night_data['low'].min(), night_data['high'].max()) if not night_data.empty else (0, 0)
        
        return {
            'day': day_range,
            'night': night_range
        }
    
    def get_opening_range(self, symbol: str, minutes: int = 30, session_anchor_ts: Optional[float] = None) -> Tuple[float, float]:
        """
        Get opening range (high and low) for the specified number of minutes.
        
        Args:
            symbol: Trading symbol
            minutes: Number of minutes from market open
            
        Returns:
            Tuple of (range_low, range_high)
        """
        minutes = int(minutes)

        # 1) try historical candles first (Binance, NinjaTrader API, etc)
        if not self._is_ui_platform():
            df = self.get_historical_data(symbol, '1m', minutes)
            if not df.empty:
                opening_data = df.tail(minutes)
                return float(opening_data['low'].min()), float(opening_data['high'].max())
            # fall through to a safe fallback if empty
            cp = self.get_current_price(symbol)
            return (cp, cp)
        
        # 2) UI platform: use live 1m bars
        # If strategy passed a session anchor, great; otherwise, derive from earliest bar we have
        # The liveBarStore has a helper we can call directly if anchor is provided.
        try:
            if session_anchor_ts is not None:
                rng = self.live.get_opening_range(symbol, minutes, session_anchor_ts)
                if rng:
                    return (float(rng[0]), float(rng[1]))

            # No anchor provided or not enough bars yet: fallback heuristic
            bars = self.live.get_last_n(symbol, keep := minutes)
            if not bars:
                cp = self.get_current_price(symbol)
                return (cp, cp)
            lows = [b.low for b in bars]
            highs = [b.high for b in bars]
            return (float(min(lows)), float(max(highs)))
        except Exception:
            cp = self.get_current_price(symbol)
            return (cp, cp)


        # self._ensure_tick_buf()
        # ticks = list(self._tick_buf[symbol])
        # if not ticks:
        #     # No ticks yet; fall back to current price
        #     cp = self.get_current_price(symbol)
        #     return (cp, cp)

        # # Session open heuristic:
        # # - If we have ticks from "today", use the earliest tick as the "session open"
        # # - Otherwise, use the first tick we have
        # ticks_sorted = sorted(ticks, key=lambda x: x[0])
        # first_ts = ticks_sorted[0][0]
        # start_ts = first_ts
        # end_ts = start_ts + timedelta(minutes=minutes)

        # now = datetime.now(timezone.utc)
        # if now < end_ts:
        #     # we're still within the opening window -> use ticks from start -> now
        #     window = [p for (ts, p) in ticks_sorted if start_ts <= ts <= now]
        # else:
        #     # we started mid-session - use the first `minutes` worth of ticks we have
        #     window = [p for (ts, p) in ticks_sorted if ts <= end_ts]

        # # if very few ticks are available, keep sampling until we have enough.
        # if len(window) < max(5, minutes): # heuristic: at least 5 samples
        #     # fall back to "all we have" to avoid blocking strategy
        #     window =  [p for (_, p) in ticks_sorted]

        # low = min(window) if window else self.get_current_price(symbol)
        # high = max(window) if window else low
        
        # return low, high

    
    def get_platform_name(self) -> str:
        """Get the name of the current trading platform."""
        return self.api.get_platform_name()
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """
        Clean up old cached data.
        
        Args:
            days_to_keep: Number of days of data to keep
        """
        cutoff_timestamp = int((datetime.now() - timedelta(days=days_to_keep)).timestamp() * 1000)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM market_data WHERE timestamp < ?', (cutoff_timestamp,))
        deleted_rows = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        self.logger.info(f"Cleaned up {deleted_rows} old data records")
    
    def get_available_symbols(self) -> List[str]:
        """
        Get list of available symbols from cached data.
        
        Returns:
            List of available symbols
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT symbol FROM market_data ORDER BY symbol')
        symbols = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return symbols

