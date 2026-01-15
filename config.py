"""
Configuration module for the futures trading bot.
Supports multiple trading platforms: Binance, Tradovate, and NinjaTrader.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class for the trading bot."""
    
    # Trading platform selection
    TRADING_PLATFORM = os.getenv('TRADING_PLATFORM', 'binance').lower()
    
    # Supported platforms
    SUPPORTED_PLATFORMS = ['binance', 'tradovate', 'ninjatrader', 'tradovate_ui']
    
    # Default trading symbol
    DEFAULT_SYMBOL = os.getenv('DEFAULT_SYMBOL', 'BTCUSDT')
    
    # Risk management settings
    MAX_POSITION_SIZE = float(os.getenv('MAX_POSITION_SIZE', '0.1'))
    STOP_LOSS_PERCENTAGE = float(os.getenv('STOP_LOSS_PERCENTAGE', '2.0'))
    TAKE_PROFIT_PERCENTAGE = float(os.getenv('TAKE_PROFIT_PERCENTAGE', '4.0'))
    
    # Opening range strategy settings
    OPENING_RANGE_MINUTES = int(os.getenv('OPENING_RANGE_MINUTES', '30'))
    BREAKOUT_THRESHOLD = float(os.getenv('BREAKOUT_THRESHOLD', '0.1'))
    
    # Bot control settings
    COOLDOWN_PERIOD = int(os.getenv('COOLDOWN_PERIOD', '300'))  # 5 minutes
    MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', '10'))
    
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
    
    # NinjaTrader configuration
    NINJATRADER_API_URL = os.getenv('NINJATRADER_API_URL', 'http://localhost:8080')
    NINJATRADER_API_KEY = os.getenv('NINJATRADER_API_KEY')
    NINJATRADER_SIMULATION = os.getenv('NINJATRADER_SIMULATION', 'true').lower() == 'true'
    
    # Database settings
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///trading_bot.db')
    
    # Logging settings
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'trading_bot.log')

    # contract multipliers
    CONTRACT_MULTIPLIERS = {"ES": 50.0}

    INSTANT_CLOSE_TRADES = "hold"
    RM_EMIT_CLOSED_ON_HOLD = False

    DRY_RUN = "false" # bot in simulation
    DRY_RUN_UI = "true" # CLICK the UI (browser driver)
    DRY_RUN_ACCOUNTING = False # still write to RM.trade_history
    INSTANT_CLOSE_TRADES = "hold" # keep positions, don't force close
    # fallback siimulation account balance
    SIM_BALANCE = 50000
    
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

