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
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    create_client = None
    Client = None


import sys
import traceback
from debug_config import debug_print, production_print

_TRACE = False

def trace_call(func):
    """Decorator to trace function calls"""
    def wrapper(*args, **kwargs):
        if _TRACE:
            print(f"{'='*80}")
            print(f"🔍 TRACE: {func.__name__} called")
            print(f"   args: {args[:2]}")  # First 2 args only
            print(f"   Stack: {traceback.format_stack()[-3:-1]}")
            print(f"{'='*80}")
        return func(*args, **kwargs)
    return wrapper

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
        self.logger = logging.getLogger(__name__)
    
    
    def _bucket_start(self, t: float) -> float:
        # minute-aligned timestamp
        return math.floor(t / 60.0) * 60.0


    def ingest_tick(self, symbol: str, ts: float, price: Optional[float]) -> None:
        # self.logger.info(f"LiveBarStore.ingest_tick called: symbol={symbol} ts={ts} price={price}")

        if price is None or not isinstance(price, (int, float)) or price != price:
            return
        dq = self._per_symbol[symbol] #.setdefault(symbol, deque(maxlen=self.keep))
        bstart = self._bucket_start(ts)

        if not dq or dq[-1].ts_open < bstart:
            # start a new bar
            # self.logger.info(f"Creating new bar for: {symbol} at {bstart}")
            dq.append(Bar(bstart, price, price, price, price))
        else:
            # update current bar
            # self.logger.info(f"Updating existing bar for {symbol}")
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
        return self.get_last_n(symbol, n)


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
    @trace_call
    def __init__(self, config: Config):
        """
        Initialize DataManager.
        
        Args:
            platform: Trading platform to use. If None, uses config default.
        """
        self.config = config
        # self.api: TradingAPIInterface = APIFactory.create_api(platform)
        self.logger = logging.getLogger(__name__)
        self.api: TradingAPIInterface = APIFactory.create_api(config=self.config)
        
        if self.api is None:
            raise RuntimeError(
                f"Failed to create API for platform: {config.TRADING_PLATFORM}. "
                f"Check your configuration and credentials."
            )
        self.logger.info(f"✅ API created successfully: {self.api.get_platform_name()}")

        # self.db_path = 'market_data.db'
        self.db_path = getattr(self.config, 'DATABASE_PATH', 'data/db/market_data.db')
        self._init_database()
        self._tick_buf = None

        self.live = LiveBarStore(keep=480)
        self.logger.info(f"DataManager initialised: self.live type={type(self.live)}")
        self.supabase = self._init_supabase()

    def _init_supabase(self):
        try:
            url = os.getenv('SUPABASE_URL')
            key = os.getenv('SUPABASE_KEY')

            if not url or not key:
                self.logger.info("Supabase not configured (Optional)")
                return None

            client = create_client(url, key)
            self.logger.info("✅ Supabase connected for historical data")
            return client

        except Exception as e:
            self.logger.warning(f"Supabase not available (non-critical): {e}")
            return None

    
    def get_historical_bars(self, symbol: str, start_time: str, end_time: str) -> List[dict]:
        """
        Get bars from supabase for backtesting or analysis

        ⚠️ IMPORTANT: Only use for COMPLETED historical data, never for current trading!

        Use cases:
        - Backtesting
        - ML training
        - Analytics
        - Yesterday's data for context

        DO NOT use for:
        - Current opening range calculation
        - Live trading decisions
        """
        if not self.supabase:
            self.logger.debug("Supabase not available, retturning empty")
            return [] # Fallback to local/live data

        try:
            start_utc = start_time if '+' in start_time else f'{start_time}+00'
            end_utc = end_time if '+' in end_time else f'{end_time}+00'

            # Convert to Supabase symbol format
            supabase_symbol = f'{symbol}_CONTFUT'

            # Query Supabase
            response = self.supabase.table('market_bars_1m') \
                .select('*') \
                .eq('symbol', supabase_symbol) \
                .gte('ts', start_utc) \
                .lte('ts', end_utc) \
                .order('ts', desc=False) \
                .execute()

            self.logger.info(
                f"Supabase query {supabase_symbol} {start_utc} to {end_utc} "
                f"-> {len(response.data)} bars"
            )
            return response.data

        except Exception as e:
            self.logger.error(f"Supabase query failed: {e}")
            return []

    def get_daily_bars(self, symbol: str, days: int = 5) -> List:
        """
        Get daily OHLCV bars by aggregating 1-minute bars from Supabase.
        
        Args:
            symbol: Trading symbol (e.g., 'MES', 'ES')
            days: Number of days to retrieve (default: 5)
        
        Returns:
            List of daily bar objects with .open, .high, .low, .close, .volume
            Returns empty list if Supabase unavailable or query fails
        
        Usage:
            daily_bars = dm.get_daily_bars('MES', days=5)
            yesterday = daily_bars[-2]  # Second to last (last is today partial)
            prev_high = yesterday.high
            prev_low = yesterday.low
        """
        if not SUPABASE_AVAILABLE:
            self.logger.warning("Supabase not available - cannot get daily bars")
            return []
        
        try:
            # Calculate date range
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days + 1)  # Extra day for safety
            
            # Format timestamps for Supabase
            start_ts = start_date.isoformat()
            end_ts = end_date.isoformat()
            
            self.logger.info(
                f"Fetching daily bars for {symbol}: {start_date.date()} to {end_date.date()}"
            )
            
            # Use existing get_historical_bars method
            minute_bars = self.get_historical_bars(symbol, start_ts, end_ts)
            
            if not minute_bars:
                self.logger.warning(f"No Supabase data for {symbol}")
                return []
            
            self.logger.debug(f"Retrieved {len(minute_bars)} 1-minute bars from Supabase")
            
            # Group bars by date
            daily_data = defaultdict(list)
            
            for bar in minute_bars:
                # Parse timestamp
                ts_str = bar['ts']
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                date_key = ts.date()
                
                daily_data[date_key].append(bar)
            
            # Create daily bar objects
            class DailyBar:
                """Simple daily bar object compatible with strategy expectations"""
                def __init__(self, date, o, h, l, c, v):
                    self.timestamp = date
                    self.open = float(o)
                    self.high = float(h)
                    self.low = float(l)
                    self.close = float(c)
                    self.volume = float(v)
            
            daily_bars = []
            
            for date in sorted(daily_data.keys()):
                bars = daily_data[date]
                
                # Aggregate OHLCV for this day
                open_price = bars[0]['open']           # First bar's open
                high_price = max(b['high'] for b in bars)
                low_price = min(b['low'] for b in bars)
                close_price = bars[-1]['close']       # Last bar's close
                total_volume = sum(b.get('volume', 0) for b in bars)
                
                daily_bar = DailyBar(
                    date=date,
                    o=open_price,
                    h=high_price,
                    l=low_price,
                    c=close_price,
                    v=total_volume
                )
                
                daily_bars.append(daily_bar)
            
            self.logger.debug(f"Aggregated into {len(daily_bars)} daily bars")
            
            # Log the bars for verification
            if daily_bars:
                self.logger.info("Daily bars:")
                for bar in daily_bars[-3:]:  # Last 3 days
                    self.logger.info(
                        f"  {bar.timestamp}: O={bar.open:.2f} H={bar.high:.2f} "
                        f"L={bar.low:.2f} C={bar.close:.2f}"
                    )
            
            return daily_bars
            
        except Exception as e:
            self.logger.error(f"Error getting daily bars from Supabase: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []


    def _et_to_utc_timestamp(self, date_str: str, time_str: str) -> str:
        """
        Convert ET time to UTC timestamp for Supabase queries.
        
        Args:
            date_str: Date in 'YYYY-MM-DD' format
            time_str: Time in 'HH:MM:SS' format (ET)
        
        Returns:
            UTC timestamp string with timezone suffix
        
        Example:
            >>> _et_to_utc_timestamp('2026-03-01', '09:30:00')
            '2026-03-01 14:30:00+00'
        """
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            ET_TZ = ZoneInfo("America/New_York")
        except ImportError:
            import pytz
            ET_TZ = pytz.timezone("America/New_York")
        
        dt_et = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M:%S')
        dt_et = dt_et.replace(tzinfo=ET_TZ)
        dt_utc = dt_et.astimezone(timezone.utc)
        
        return dt_utc.strftime('%Y-%m-%d %H:%M:%S+00')


    def query_yesterday_bars(self, symbol: str, start_hour: int = 9, start_min: int = 30, end_hour: int = 16, end_min: int = 0) -> List[dict]:
        """
        Thin wrapper: Query yesterday's bars from Supabase.
        
        Args:
            symbol: Trading symbol
           start_hour: Start hour in ET (default 9)
            start_min: Start minute in ET (default 30)
            end_hour: End hour in ET (default 16)
            end_min: End minute in ET (default 0)
        
        Returns:
            List of yesterday's bars from Supabase
        
        Edge cases:
            - Returns [] if yesterday was weekend/holiday
            - Returns [] if Supabase unavailable
            - Handles DST transitions automatically
        
        Example:
            >>> bars = dm.query_yesterday_bars('ES')
            >>> len(bars)  # ~390 bars for full session
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        start_ts = self._et_to_utc_timestamp(
            yesterday,
            f'{start_hour:02d}:{start_min:02d}:00'
        )
        end_ts = self._et_to_utc_timestamp(
            yesterday,
            f'{end_hour:02d}:{end_min:02d}:00'
        )
        
        return self.get_historical_bars(symbol, start_ts, end_ts)

    
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
            self.logger.exception(f"Tick ingestion failed: {e}") # LOG IT!


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

    # def get_current_price(self, symbol: str) -> Optional[float]:
    #     """Get current price and feed to LiveBarStore"""
    #     try:
    #         price = self.api.get_current_price(symbol)
            
    #         if price is None:
    #             return None
            
    #         # Feed to LiveBarStore IMMEDIATELY
    #         now_ts = time.time()
    #         self.live.ingest_tick(symbol, now_ts, float(price))

    #         # DEBUG: Log every 10 calls 
    #         self._price_call_count = getattr(self, '_price_call_count', 0) + 1 
    #         if self._price_call_count % 10 == 0: 
    #             bars = self.live.get_last_n(symbol, n=5) 
    #             self.logger.info(f"📊 PRICE CALLS: {self._price_call_count} | BARS: {len(bars)}")

            
    #         return price
            
    #     except Exception as e:
    #         self.logger.error(f"get_current_price failed: {e}")
    #         return None

    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current price
        """
        price = self.api.get_current_price(symbol)
        # ADD THIS AS FIRST LINE: 
        self.logger.info(f"🟢 get_current_price() got price={price} from API")

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

            # ADD THIS LINE BEFORE TICK INGESTION:
            self.logger.info(f"🔥 About to ingest tick: symbol={symbol} price={p} live={self.live}")


            # self.live.ingest_tick(symbol, time.time(), p)
            
            # keep a compact tick buffer for ad-hoc analytics
            self._ensure_tick_buf()
            self._tick_buf[symbol].append((datetime.now(timezone.utc), p))

            # prefer ingest_tick(symbol, t, price) if available
            now_ts = time.time()
            ingest = getattr(self.live, "ingest_tick", None)

            self.logger.info(f"🔵 ingest callable check: {callable(ingest)}")

            if callable(ingest):
                self.logger.info(f"🔵 Calling ingest_tick: symbol={symbol} ts={now_ts} price={p}") # ADD THIS
                ingest(symbol, now_ts, p)

                # VERIFY IT WORKED
                bars = self.live.get_last_n(symbol, n=5)
                self.logger.info(f"📊After Ingest: BAR COUNT: {len(bars)}")
            else:
                self.logger.error(f"X ingest_tick is not callable!")
                # fallback to update(symbol, ts_epoch, price) if that's what you have
                upd = getattr(self.live, "update", None)
                if callable(upd):
                    self.logger.info(f"🟡 Falling back to update()")
                    upd(symbol, now_ts, p)


            # occasional debug
            if len(self._tick_buf[symbol]) % 60 == 0:
                self.logger.debug("TickBuf[%s]: %d", symbol, len(self._tick_buf[symbol]))
        except Exception as e:
            # never break price reads
            self.logger.exception("X EXCEPTION in get_current_price: {e}")
            # pass

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

    def get_last_closed_candles(self, symbol: str, timeframe: str = "5m", 
                                n: int = 2) -> List[Dict[str, Any]]:
        """
        Returns last N CLOSED candles for pattern detection.
        
        Required by ORB Retest strategy for:
        - Engulfing pattern detection (needs 2 candles)
        - Hammer/shooting star detection
        - Higher-low break / Lower-high break patterns
        
        Args:
            symbol: Trading symbol
            timeframe: "1m", "5m", etc.
            n: Number of candles to return
            
        Returns:
            List of dicts with keys: open, high, low, close, ts, close_ts, volume
            Ordered oldest -> newest
            Excludes the current (incomplete) bar
        """
        if not hasattr(self, 'live') or self.live is None:
            return []
        
        if timeframe == "5m":
            # Get last 5*n + 5 minutes of 1m bars (buffer for aggregation)
            bars_1m = self.live.get_last_n(symbol, n=5 * n + 10)
            
            if len(bars_1m) < 5:
                return []
            
            # Exclude the last incomplete bar (current minute)
            # Then aggregate into 5-minute candles
            complete_bars = bars_1m[:-1] if bars_1m else []
            
            candles_5m = []
            for i in range(0, len(complete_bars), 5):
                chunk = complete_bars[i:i+5]
                if len(chunk) == 5:  # Only use complete 5m periods
                    candles_5m.append({
                        "ts": chunk[0].ts_open,
                        "open": chunk[0].open,
                        "high": max(b.high for b in chunk),
                        "low": min(b.low for b in chunk),
                        "close": chunk[-1].close,
                        "close_ts": chunk[-1].ts_open + 60,
                        "volume": sum(getattr(b, 'volume', 0) for b in chunk),
                    })
            
            # Return last n complete 5m candles
            return candles_5m[-n:] if candles_5m else []
        
        elif timeframe == "1m":
            bars = self.live.get_last_n(symbol, n=n + 1)
            
            if len(bars) < 2:
                return []
            
            # Return all but the last bar (which is still building)
            complete_bars = bars[:-1]
            
            return [
                {
                    "ts": b.ts_open,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "close_ts": b.ts_open + 60,
                    "volume": getattr(b, 'volume', 0),
                }
                for b in complete_bars
            ][-n:]
        
        else:
            # Unsupported timeframe
            self.logger.warning(f"Unsupported timeframe: {timeframe}")
            return []

    def get_sma(self, symbol: str, length: int, timeframe: str = "5m", 
                offset: int = 0) -> float:
        """
        Simple Moving Average over the last `length` closed candles.
        
        Required by ORB Retest for trend filtering:
        - SMA20 for short-term bias
        - SMA200 for major trend
        - Offset for slope calculation (SMA now vs SMA 1 bar ago)
        
        Args:
            symbol: Trading symbol
            length: Number of periods (e.g., 20, 200)
            timeframe: "1m", "5m", etc.
            offset: 0 = current, 1 = 1 bar ago (for slope detection)
            
        Returns:
            SMA value, or 0.0 if insufficient data
        """
        candles = self.get_last_closed_candles(
            symbol, 
            timeframe, 
            n=length + offset
        )
        
        if len(candles) < (length + offset):
            return 0.0
        
        # Select the range for SMA calculation
        if offset > 0:
            # Get bars from -(length+offset) to -offset
            relevant_candles = candles[-(length + offset):-offset]
        else:
            # Get last `length` bars
            relevant_candles = candles[-length:]
        
        if len(relevant_candles) < length:
            return 0.0
        
        closes = [c["close"] for c in relevant_candles]
        return sum(closes) / len(closes)

    # def get_candles(self, symbol: str, timeframe: str, start_ts: float, 
    #                 end_ts: float) -> List[Dict[str, Any]]:
    #     """
    #     Returns historical candles for a specific time range.
        
    #     Required by ORB Retest for computing the opening range
    #     (e.g., 9:30-9:45 AM ET = 15 minute window).
        
    #     Args:
    #         symbol: Trading symbol
    #         timeframe: "1m", "2m", "5m"
    #         start_ts: Start timestamp (epoch seconds)
    #         end_ts: End timestamp (epoch seconds)
            
    #     Returns:
    #         List of dicts with keys: ts, open, high, low, close, volume
    #         Ordered oldest -> newest
    #     """
    #     if not hasattr(self, 'bar_store') or self.bar_store is None:
    #         return []
        
    #     # Get all available 1m bars
    #     all_bars = self.bar_store.get_last_n(symbol, n=10000)  # Get as many as we have
        
    #     if timeframe == "1m":
    #         # Filter bars within time range
    #         result = [
    #             {
    #                 "ts": b.ts_open,
    #                 "open": b.open,
    #                 "high": b.high,
    #                 "low": b.low,
    #                 "close": b.close,
    #                 "volume": getattr(b, 'volume', 0),
    #             }
    #             for b in all_bars
    #             if start_ts <= b.ts_open < end_ts
    #         ]
    #         return result
        
    #     elif timeframe in ("2m", "5m"):
    #         # First, filter 1m bars to the time range
    #         bars_in_range = [
    #             b for b in all_bars
    #             if start_ts <= b.ts_open < end_ts
    #         ]
            
    #         if not bars_in_range:
    #             return []
            
    #         # Aggregate into requested timeframe
    #         period_minutes = int(timeframe.replace("m", ""))
    #         candles = []
            
    #         for i in range(0, len(bars_in_range), period_minutes):
    #             chunk = bars_in_range[i:i+period_minutes]
    #             if chunk:  # Accept partial chunks at the end
    #                 candles.append({
    #                     "ts": chunk[0].ts_open,
    #                     "open": chunk[0].open,
    #                     "high": max(b.high for b in chunk),
    #                     "low": min(b.low for b in chunk),
    #                     "close": chunk[-1].close,
    #                     "volume": sum(getattr(b, 'volume', 0) for b in chunk),
    #                 })
            
    #         return candles
        
    #     else:
    #         self.logger.warning(f"Unsupported timeframe: {timeframe}")
    #         return []


    def get_candles(self, symbol: str, timeframe: str, start_ts: float, end_ts: float):
        """Debug version with extensive logging"""
        
        # Check 1: Does live exist?
        if not hasattr(self, 'live'):
            self.logger.error("❌ live attribute doesn't exist!")
            return []
        
        # Check 2: Is live None?
        if self.live is None:
            self.logger.error("❌ live is None!")
            return []
        
        # Check 3: Can we get bars?
        try:
            all_bars = self.live.get_last_n(symbol, n=100)
            self.logger.info(f"✓ Got {len(all_bars)} bars from live for {symbol}")
        except Exception as e:
            self.logger.error(f"❌ Failed to get bars: {e}")
            return []
        
        # Check 4: Filter to time range
        filtered = [b for b in all_bars if start_ts <= b.ts_open < end_ts]
        self.logger.info(f"✓ Filtered to {len(filtered)} bars in range {start_ts}-{end_ts}")
        
        if not filtered:
            self.logger.warning(f"⚠️  No bars in time range! Got {len(all_bars)} total bars")
            if all_bars:
                self.logger.info(f"   First bar: {all_bars[0].ts_open}, Last bar: {all_bars[-1].ts_open}")
                self.logger.info(f"   Requested: {start_ts} to {end_ts}")
        
        # Return formatted
        result = [
            {
                "ts": b.ts_open,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": getattr(b, 'volume', 0),
            }
            for b in filtered
        ]
        
        return result



    def get_volume_profile(self, symbol: str, lookback_bars: int = 20) -> Dict[str, Any]:
        """
        Calculate volume statistics for volume-based filtering.
        
        Used to confirm breakouts:
        - High volume breakout = strong conviction
        - Low volume breakout = false signal
        
        Args:
            symbol: Trading symbol
            lookback_bars: Number of bars to analyze (default 20)
            
        Returns:
            Dictionary with:
            - avg_volume: Average volume over lookback
            - current_volume: Volume of most recent bar
            - volume_ratio: current / average
            - is_high_volume: True if ratio > 1.5
            - is_low_volume: True if ratio < 0.5
        """
        if not hasattr(self, 'live') or self.live is None:
            return {
                "avg_volume": 0,
                "current_volume": 0,
                "volume_ratio": 1.0,
                "is_high_volume": False,
                "is_low_volume": False,
            }
        
        bars = self.live.get_last_n(symbol, n=lookback_bars)
        
        if not bars:
            return {
                "avg_volume": 0,
                "current_volume": 0,
                "volume_ratio": 1.0,
                "is_high_volume": False,
                "is_low_volume": False,
            }
        
        volumes = [getattr(b, 'volume', 1) for b in bars]
        avg_vol = sum(volumes) / len(volumes)
        current_vol = volumes[-1] if volumes else 0
        
        ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        
        return {
            "avg_volume": avg_vol,
            "current_volume": current_vol,
            "volume_ratio": ratio,
            "is_high_volume": ratio > 1.5,
            "is_low_volume": ratio < 0.5,
        }

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get the most recent price for a symbol.
        
        This method should already exist in your DataManager.
        If not, here's an implementation:
        """
        if hasattr(self, 'api') and self.api:
            try:
                return self.api.get_current_price(symbol)
            except Exception as e:
                self.logger.error(f"Failed to get current price: {e}")
        
        # Fallback: get from bar store
        if hasattr(self, 'live') and self.live:
            bars = self.live.get_last_n(symbol, n=1)
            if bars:
                return bars[-1].close
        
        return None

