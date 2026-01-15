"""
API Factory for Platform-Agnostic Trading Bot

This module provides a factory pattern implementation for creating
trading API instances based on configuration settings.
"""

import logging
from typing import Optional
from config import get_config
from api_interface import TradingAPIInterface
# from platforms import BinanceAPI, TradovateAPI, NinjaTraderAPI
from binance_api import BinanceAPI
from tradovate_api import TradovateAPI
from ninjatrader_api import NinjaTraderAPI

logger = logging.getLogger(__name__)

class APIFactory:
    """Factory class for creating trading API instances."""
    
    SUPPORTED_PLATFORMS = {
        'binance': BinanceAPI,
        'tradovate': TradovateAPI,
        'ninjatrader': NinjaTraderAPI
    }
    
    @classmethod
    def create_api(cls, platform: Optional[str] = None) -> Optional[TradingAPIInterface]:
        """
        Create a trading API instance based on platform configuration.
        
        Args:
            platform: Platform name (optional, uses config if not provided)
            
        Returns:
            TradingAPIInterface instance or None if creation fails
        """
        try:
            config = get_config()
            
            # Use provided platform or get from config
            platform_name = platform or config.platform
            platform_name = platform_name.lower()
            
            if platform_name not in cls.SUPPORTED_PLATFORMS:
                logger.error(f"Unsupported platform: {platform_name}")
                logger.info(f"Supported platforms: {list(cls.SUPPORTED_PLATFORMS.keys())}")
                return None
            
            # Create platform-specific API instance
            if platform_name == 'binance':
                return cls._create_binance_api(config)
            elif platform_name == 'tradovate':
                return cls._create_tradovate_api(config)
            elif platform_name == 'ninjatrader':
                return cls._create_ninjatrader_api(config)
            else:
                logger.error(f"Platform {platform_name} not implemented")
                return None
                
        except Exception as e:
            logger.error(f"Error creating API instance: {e}")
            return None
    
    @classmethod
    def _create_binance_api(cls, config) -> Optional[BinanceAPI]:
        """Create Binance API instance."""
        try:
            if not config.binance_api_key or not config.binance_api_secret:
                logger.error("Binance API credentials not found in configuration")
                return None
            
            api = BinanceAPI(
                api_key=config.binance_api_key,
                api_secret=config.binance_api_secret,
                testnet=config.binance_testnet
            )
            
            logger.info("Created Binance API instance")
            return api
            
        except Exception as e:
            logger.error(f"Error creating Binance API: {e}")
            return None
    
    @classmethod
    def _create_tradovate_api(cls, config) -> Optional[TradovateAPI]:
        """Create Tradovate API instance."""
        try:
            required_fields = [
                config.tradovate_username,
                config.tradovate_password,
                config.tradovate_app_id,
                config.tradovate_app_version,
                config.tradovate_cid,
                config.tradovate_sec
            ]
            
            if not all(required_fields):
                logger.error("Tradovate API credentials not found in configuration")
                return None
            
            api = TradovateAPI(
                username=config.tradovate_username,
                password=config.tradovate_password,
                app_id=config.tradovate_app_id,
                app_version=config.tradovate_app_version,
                cid=config.tradovate_cid,
                sec=config.tradovate_sec,
                demo=config.tradovate_demo
            )
            
            logger.info("Created Tradovate API instance")
            return api
            
        except Exception as e:
            logger.error(f"Error creating Tradovate API: {e}")
            return None
    
    @classmethod
    def _create_ninjatrader_api(cls, config) -> Optional[NinjaTraderAPI]:
        """Create NinjaTrader API instance."""
        try:
            if not config.ninjatrader_api_url:
                logger.error("NinjaTrader API URL not found in configuration")
                return None
            
            api = NinjaTraderAPI(
                api_url=config.ninjatrader_api_url,
                api_key=config.ninjatrader_api_key,
                simulation=config.ninjatrader_simulation
            )
            
            logger.info("Created NinjaTrader API instance")
            return api
            
        except Exception as e:
            logger.error(f"Error creating NinjaTrader API: {e}")
            return None
    
    @classmethod
    def get_supported_platforms(cls) -> list:
        """Get list of supported platform names."""
        return list(cls.SUPPORTED_PLATFORMS.keys())
    
    @classmethod
    def validate_platform(cls, platform: str) -> bool:
        """Validate if a platform is supported."""
        return platform.lower() in cls.SUPPORTED_PLATFORMS

