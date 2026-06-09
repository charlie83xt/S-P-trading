"""
Configuration module for the futures trading bot.
Supports multiple trading platforms: Binance, Tradovate, and NinjaTrader.
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env from APPDATA location first (packaged app / user machine)
# Falls back to project root .env (development)
_appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
_user_env = Path(_appdata) / "S-P-Trading" / ".env"
_dev_env  = Path(__file__).parent / ".env"

# Load environment variables from .env file
if _user_env.exists():
    load_dotenv(_user_env)
elif _dev_env.exists():
    load_dotenv(_dev_env)


# load_dotenv()

class Config:
    """Configuration class for the trading bot."""
    # -------------------------------------------------------------------
    # ORB BREAK + RETEST STRATEGY (Cousin's Recommendation)
    # -------------------------------------------------------------------
    ORB_RETEST_OR_MINUTES = int(os.getenv("ORB_RETEST_OR_MINUTES", "30"))
    ORB_RETEST_BREAKOUT_POINTS = float(os.getenv("ORB_RETEST_BREAKOUT_PTS", "2.0"))
    ORB_RETEST_BREAKOUT_PCT = float(os.getenv("ORB_RETEST_BREAKOUT_PCT", "0.0"))
    ORB_RETEST_TOLERANCE = float(os.getenv("ORB_RETEST_TOLERANCE", "1.0"))
    ORB_RETEST_MAX_STOP = float(os.getenv("ORB_RETEST_MAX_STOP", "10.0"))
    ORB_RETEST_MIN_GAP_SEC = float(os.getenv("ORB_RETEST_MIN_GAP_SEC", "30.0"))
    ORB_RETEST_MAX_TRADES = int(os.getenv("ORB_RETEST_MAX_TRADES", "2"))
    ORB_RETEST_ONE_SIDE_ONLY = bool(os.getenv("ORB_RETEST_ONE_SIDE", "true").lower() == "true")

    # Previous Day High/Low Reversal Strategy 
    PREV_DAY_SHADOW_RATIO = float(os.getenv("PREV_DAY_SHADOW_RATIO", "2.0")) 
    PREV_DAY_MAX_OTHER_SHADOW = float(os.getenv("PREV_DAY_MAX_OTHER_SHADOW", "0.3")) 
    PREV_DAY_MIN_BODY_PCT = float(os.getenv("PREV_DAY_MIN_BODY_PCT", "0.05")) 
    PREV_DAY_TOLERANCE_PCT = float(os.getenv("PREV_DAY_TOLERANCE_PCT", "0.002")) 
    PREV_DAY_MAX_TRADES = int(os.getenv("PREV_DAY_MAX_TRADES", "4"))

    # Parse trade window times (format: "9,45" -> (9, 45))
    _start_str = os.getenv("ORB_RETEST_START", "9,45")
    _end_str = os.getenv("ORB_RETEST_END", "10,30")
    ORB_RETEST_TRADE_START = tuple(map(int, _start_str.split(",")))
    ORB_RETEST_TRADE_END = tuple(map(int, _end_str.split(",")))

    ORB_RETEST_USE_SMA = bool(os.getenv("ORB_RETEST_USE_SMA", "true").lower() == "true")
    ORB_RETEST_SMA_TIMEFRAME = os.getenv("ORB_RETEST_SMA_TF", "5m")
        
    # Trading platform selection
    TRADING_PLATFORM = os.getenv('TRADING_PLATFORM', 'tradovate_ui').lower()
    
    # Supported platforms
    SUPPORTED_PLATFORMS = ['binance', 'tradovate', 'ninjatrader', 'tradovate_ui']
    
    # Default trading symbol
    DEFAULT_SYMBOL = os.getenv('DEFAULT_SYMBOL', 'MES')
    
    # Risk management settings
    MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', '0.1'))
    STOP_LOSS_PERCENTAGE = float(os.getenv('STOP_LOSS_PERCENTAGE', '2.0'))
    TAKE_PROFIT_PERCENTAGE = float(os.getenv('TAKE_PROFIT_PERCENTAGE', '4.0'))

    
    # Opening range strategy settings
    OPENING_RANGE_MINUTES = int(os.getenv('OPENING_RANGE_MINUTES', '30'))
    BREAKOUT_THRESHOLD_PERCENT = float(os.getenv('BREAKOUT_THRESHOLD_PERCENT', '0.05'))
    BREAKOUT_POINTS = float(os.getenv('BREAKOUT_POINTS', '2.0'))
    MIN_MOVE_FROM_OR = float(os.getenv('MIN_MOVE_FROM_OR', '1.5')) # Minimum move in points
    
    # Bot control settings
    COOLDOWN_PERIOD = int(os.getenv('COOLDOWN_PERIOD', '300'))  # 5 minutes
    MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', '10'))

    SUPABASE_URL="https://ndqtzugtnnqyhnqjxeta.supabase.co"
    SUPABASE_KEY="sb_publishable__aPkSACT6LNsLmoLSopOFQ_VPQ3iJ0U"
    
    # Binance configuration
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    BINANCE_TESTNET = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
    BINANCE_BASE_URL = 'https://testnet.binancefuture.com' if BINANCE_TESTNET else 'https://fapi.binance.com'
    
    # Tradovate configuration
    TRADOVATE_USERNAME = os.getenv('TRADOVATE_USERNAME', '')
    TRADOVATE_PASSWORD = os.getenv('TRADOVATE_PASSWORD', '')
    TRADOVATE_DEMO = os.getenv('TRADOVATE_DEMO', 'true').lower() == 'true'
    TRADOVATE_BASE_URL = 'https://demo.tradovateapi.com/v1' if TRADOVATE_DEMO else 'https://live.tradovateapi.com/v1'
    TRADOVATE_APP_ID = os.getenv('TRADOVATE_APP_ID', '')
    TRADOVATE_APP_VERSION = os.getenv('TRADOVATE_APP_VERSION', '') # tradovate_app_version
    TRADOVATE_CID = os.getenv('TRADOVATE_CID', '')# tradovate_cid,
    TRADOVATE_SEC = os.getenv('TRADOVATE_SEC', '') # tradovate_sec,
    
    # NinjaTrader configuration
    NINJATRADER_API_URL = os.getenv('NINJATRADER_API_URL', 'http://localhost:8080')
    NINJATRADER_API_KEY = os.getenv('NINJATRADER_API_KEY')
    NINJATRADER_SIMULATION = os.getenv('NINJATRADER_SIMULATION', 'true').lower() == 'true'
    
    # Database settings
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///trading_bot.db')
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/db/market_data.db')
    
    # Logging settings
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'trading_bot.log')

    # contract multipliers
    CONTRACT_MULTIPLIERS = {
        "ES": 50.0, # E-mini S&P 500: S&P: $50 per point
        "MES": 5.0, # Micro E-mini S&P 500: $5 per point
        "NQ": 20.0, # E-mini Nasdaq: $20 per point
        "MNQ": 2.0, # Micro E-mini Nasdaq: $2 per point
        "YM": 5.0,  # E-mini Dow: $5 per point
        "MYM": 0.5  # Micro E-mini Dow: $0.50 per point
    }

    INSTANT_CLOSE_TRADES = "hold"
    RM_EMIT_CLOSED_ON_HOLD = False

    DRY_RUN = "false" # bot in simulation
    DRY_RUN_UI = "true" # CLICK the UI (browser driver)
    DRY_RUN_ACCOUNTING = False # still write to RM.trade_history
    INSTANT_CLOSE_TRADES = "hold" # keep positions, don't force close
    # fallback simulation account balance
    SIM_BALANCE = 50000
    # Exit points. 1 point = $50 per contract (classic ES)
    # 1 tick = 0.25 points = $12.50
    STOP_LOSS_POINTS = float(os.getenv("STOP_LOSS_POINTS", "4.0"))
    TAKE_PROFIT_POINTS = float(os.getenv("TAKE_PROFIT_POINTS", "6.0"))
    # Base configuration — sniper-tuned: smaller base = tighter exits on quiet days
    STOP_LOSS_BASE_POINTS = float(os.getenv("STOP_LOSS_BASE_POINTS", "4.0"))
    TAKE_PROFIT_BASE_POINTS = float(os.getenv("TAKE_PROFIT_BASE_POINTS", "6.0"))

    # Adaptive multipliers
    VOLATILITY_STOP_MULTIPLIER = 2.5    # Stop = 2.5x recent volatility
    VOLATILITY_TAKE_MULTIPLIER = 4.0    # Target = 4.0x recent volatility

    # Safety bounds (prevent crazy outliers)
    MAX_STOP_LOSS_POINTS = float(os.getenv("MAX_STOP_LOSS_POINTS", "12.0"))
    MIN_STOP_LOSS_POINTS = float(os.getenv("MIN_STOP_LOSS_POINTS", "3.0"))
    MAX_TAKE_PROFIT_POINTS = float(os.getenv("MAX_TAKE_PROFIT_POINTS", "20.0"))
    MIN_TAKE_PROFIT_POINTS = float(os.getenv("MIN_TAKE_PROFIT_POINTS", "4.0"))

    # -------------------------------------------------------------------
    # SNIPER EXIT SYSTEM
    # After BREAKEVEN_TRIGGER_POINTS profit, SL moves to entry + buffer
    # so a winner can never turn into a meaningful loser.
    # MAX_TRADE_DURATION_MINUTES forces a flat exit if price hasn't
    # committed in either direction within the time window.
    # -------------------------------------------------------------------
    BREAKEVEN_TRIGGER_POINTS = float(os.getenv("BREAKEVEN_TRIGGER_POINTS", "2.0"))
    BREAKEVEN_BUFFER_POINTS  = float(os.getenv("BREAKEVEN_BUFFER_POINTS",  "0.5"))
    MAX_TRADE_DURATION_MINUTES = int(os.getenv("MAX_TRADE_DURATION_MINUTES", "20"))

    # -------------------------------------------------------------------
    # VOLUME TRACKING (NEW)
    # -------------------------------------------------------------------
    VOLUME_LOOKBACK_BARS = int(os.getenv("VOLUME_LOOKBACK_BARS", "20"))
    HIGH_VOLUME_THRESHOLD = float(os.getenv("HIGH_VOLUME_THRESHOLD", "1.5"))
    LOW_VOLUME_THRESHOLD = float(os.getenv("LOW_VOLUME_THRESHOLD", "0.5"))

    # -------------------------------------------------------------------
    # DATA MANAGEMENT (NEW)
    # -------------------------------------------------------------------
    KEEP_BARS = int(os.getenv("KEEP_BARS", "480"))  # 8 hours of 1m bars
    DATA_REFRESH_INTERVAL = float(os.getenv("DATA_REFRESH_INTERVAL", "1.0"))

    # Mean Reversion Strategy (Afternoon Session)
    ENTRY_MIN_MOMENTUM    = float(os.getenv("ENTRY_MIN_MOMENTUM",    "0.20"))
    ENTRY_MIN_VOLUME_RATIO= float(os.getenv("ENTRY_MIN_VOLUME_RATIO","1.10"))
    ENTRY_MIN_ORDER_FLOW  = float(os.getenv("ENTRY_MIN_ORDER_FLOW",  "0.10"))

    MEAN_REVERSION_LOOKBACK = int(os.getenv("MEAN_REVERSION_LOOKBACK", "20"))
    MEAN_REVERSION_STD_DEV = float(os.getenv("MEAN_REVERSION_STD_DEV", "2.0"))
    MEAN_REVERSION_MAX_TRADES = int(os.getenv("MEAN_REVERSION_MAX_TRADES", "4"))
    MEAN_REVERSION_MIN_BANDWIDTH = float(os.getenv("MEAN_REVERSION_MIN_BANDWIDTH", "0.0010"))
    MEAN_REVERSION_COOLDOWN_BARS = int(os.getenv("MEAN_REVERSION_COOLDOWN_BARS", "3"))
    MEAN_REVERSION_REQUIRE_CONFIRMATION = os.getenv("MEAN_REVERSION_REQUIRE_CONFIRMATION", "true").lower() == 'true'


    @classmethod
    def validate_platform(cls):
        """Validate that the selected platform is supported."""
        if cls.TRADING_PLATFORM not in cls.SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: {cls.TRADING_PLATFORM}. "
                           f"Supported platforms: {', '.join(cls.SUPPORTED_PLATFORMS)}")
    
    @classmethod
    def get_platform_config(cls, platform=None):
        """Get configuration for the selected platform."""
        if platform is None:
            platform = cls.TRADING_PLATFORM
        
        # Temporarily set the platform for validation
        original_platform = cls.TRADING_PLATFORM
        cls.TRADING_PLATFORM = platform
        cls.validate_platform()
        cls.TRADING_PLATFORM = original_platform
        
        if platform == 'binance':
            return {
                'api_key': cls.BINANCE_API_KEY,
                'api_secret': cls.BINANCE_API_SECRET,
                'testnet': cls.BINANCE_TESTNET,
                'base_url': cls.BINANCE_BASE_URL
            }
        elif platform == 'tradovate':
            return {
                'username': cls.TRADOVATE_USERNAME,
                'password': cls.TRADOVATE_PASSWORD,
                'demo': cls.TRADOVATE_DEMO,
                'base_url': cls.TRADOVATE_BASE_URL
            }
        elif platform == 'ninjatrader':
            return {
                'api_url': cls.NINJATRADER_API_URL,
                'api_key': cls.NINJATRADER_API_KEY,
                'simulation': cls.NINJATRADER_SIMULATION
            }
        elif platform == "tradovate_ui":
            return {
                'username': cls.TRADOVATE_USERNAME,
                'password': cls.TRADOVATE_PASSWORD,
                'demo': cls.TRADOVATE_DEMO,
                'base_url': cls.TRADOVATE_BASE_URL
            }
        else:
            raise ValueError(f"Unknown platform: {platform}")

# Create a global config instance
config = Config()
