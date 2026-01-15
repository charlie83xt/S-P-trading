"""
Configuration module for the futures trading bot.
Handles environment variables and configuration settings for multiple platforms.
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class Config:
    """Configuration class for trading bot settings."""
    
    # Platform Selection
    platform: str = "binance"  # binance, tradovate, ninjatrader
    
    # Binance Configuration
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True
    
    # Tradovate Configuration
    tradovate_username: str = ""
    tradovate_password: str = ""
    tradovate_app_id: str = ""
    tradovate_app_version: str = ""
    tradovate_cid: str = ""
    tradovate_sec: str = ""
    tradovate_demo: bool = True
    
    # NinjaTrader Configuration
    ninjatrader_api_url: str = "http://localhost:8080"
    ninjatrader_api_key: Optional[str] = None
    ninjatrader_simulation: bool = True
    
    # Trading Configuration
    default_symbol: str = "ES"  # Changed to futures symbol
    default_quantity: float = 1.0  # Changed to futures quantity
    max_position_size: float = 5.0
    
    # Risk Management
    max_daily_loss: float = 500.0
    max_drawdown_percent: float = 5.0
    stop_loss_percent: float = 2.0
    take_profit_percent: float = 4.0
    
    # Opening Range Strategy Configuration
    opening_range_minutes: int = 30
    breakout_threshold_percent: float = 0.1
    min_range_size: float = 0.001
    volume_confirmation: bool = True
    profit_target_multiplier: float = 2.0
    stop_loss_multiplier: float = 1.0
    
    # Bot Control
    trading_enabled: bool = True
    cooldown_minutes: int = 5
    max_open_positions: int = 3
    
    # Database
    database_url: str = "sqlite:///trading_bot.db"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "trading_bot.log"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'platform': self.platform,
            'binance_api_key': self.binance_api_key[:8] + '...' if self.binance_api_key else '',
            'binance_testnet': self.binance_testnet,
            'tradovate_username': self.tradovate_username,
            'tradovate_demo': self.tradovate_demo,
            'ninjatrader_api_url': self.ninjatrader_api_url,
            'ninjatrader_simulation': self.ninjatrader_simulation,
            'default_symbol': self.default_symbol,
            'default_quantity': self.default_quantity,
            'max_position_size': self.max_position_size,
            'max_daily_loss': self.max_daily_loss,
            'max_drawdown_percent': self.max_drawdown_percent,
            'opening_range_minutes': self.opening_range_minutes,
            'breakout_threshold_percent': self.breakout_threshold_percent,
            'trading_enabled': self.trading_enabled,
            'cooldown_minutes': self.cooldown_minutes,
            'max_open_positions': self.max_open_positions,
            'log_level': self.log_level
        }

def get_config() -> Config:
    """Get configuration from environment variables."""
    return Config(
        # Platform Selection
        platform=os.getenv("TRADING_PLATFORM", "binance").lower(),
        
        # Binance Configuration
        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
        binance_testnet=os.getenv("BINANCE_TESTNET", "true").lower() == "true",
        
        # Tradovate Configuration
        tradovate_username=os.getenv("TRADOVATE_USERNAME", ""),
        tradovate_password=os.getenv("TRADOVATE_PASSWORD", ""),
        tradovate_app_id=os.getenv("TRADOVATE_APP_ID", ""),
        tradovate_app_version=os.getenv("TRADOVATE_APP_VERSION", ""),
        tradovate_cid=os.getenv("TRADOVATE_CID", ""),
        tradovate_sec=os.getenv("TRADOVATE_SEC", ""),
        tradovate_demo=os.getenv("TRADOVATE_DEMO", "true").lower() == "true",
        
        # NinjaTrader Configuration
        ninjatrader_api_url=os.getenv("NINJATRADER_API_URL", "http://localhost:8080"),
        ninjatrader_api_key=os.getenv("NINJATRADER_API_KEY"),
        ninjatrader_simulation=os.getenv("NINJATRADER_SIMULATION", "true").lower() == "true",
        
        # Trading Configuration
        default_symbol=os.getenv("DEFAULT_SYMBOL", "ES"),
        default_quantity=float(os.getenv("DEFAULT_QUANTITY", "1.0")),
        max_position_size=float(os.getenv("MAX_POSITION_SIZE", "5.0")),
        
        # Risk Management
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "500.0")),
        max_drawdown_percent=float(os.getenv("MAX_DRAWDOWN_PERCENT", "5.0")),
        stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", "2.0")),
        take_profit_percent=float(os.getenv("TAKE_PROFIT_PERCENT", "4.0")),
        
        # Opening Range Strategy Configuration
        opening_range_minutes=int(os.getenv("OPENING_RANGE_MINUTES", "30")),
        breakout_threshold_percent=float(os.getenv("BREAKOUT_THRESHOLD_PERCENT", "0.1")),
        min_range_size=float(os.getenv("MIN_RANGE_SIZE", "0.001")),
        volume_confirmation=os.getenv("VOLUME_CONFIRMATION", "true").lower() == "true",
        profit_target_multiplier=float(os.getenv("PROFIT_TARGET_MULTIPLIER", "2.0")),
        stop_loss_multiplier=float(os.getenv("STOP_LOSS_MULTIPLIER", "1.0")),
        
        # Bot Control
        trading_enabled=os.getenv("TRADING_ENABLED", "true").lower() == "true",
        cooldown_minutes=int(os.getenv("COOLDOWN_MINUTES", "5")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
        
        # Database
        database_url=os.getenv("DATABASE_URL", "sqlite:///trading_bot.db"),
        
        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE", "trading_bot.log")
    )

# Global configuration instance
config = get_config()

def update_config(**kwargs):
    """Update configuration parameters."""
    global config
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            raise ValueError(f"Unknown configuration parameter: {key}")

