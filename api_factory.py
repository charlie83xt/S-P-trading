"""
API Factory for Platform-Agnostic Trading Bot

This module provides a factory pattern implementation for creating
trading API instances based on configuration settings.
"""

import logging
import os
from typing import Optional
from config import Config
from api_interface import TradingAPIInterface
# from platforms import BinanceAPI, TradovateAPI, NinjaTraderAPI
from binance_api import BinanceAPI
from tradovate_api import TradovateAPI
# try:
from tradovate_web_ui_api import TradovateWebUIAPI
# except Exception as e:
#     import logging; logging.getLogger(__name__).exception("Import TradovateWebUIAPI failed: %s", e)
#     TradovateWebUIAPI = None

from ninjatrader_api import NinjaTraderAPI

logger = logging.getLogger(__name__)
logger.info("api_factory loaded from %s", __file__)

class APIFactory:
    """Factory class for creating trading API instances."""
    
    SUPPORTED_PLATFORMS = {
        'binance': BinanceAPI,
        'tradovate': TradovateAPI,
        'ninjatrader': NinjaTraderAPI,
        'tradovate_ui': TradovateWebUIAPI
    }
    
    @classmethod
    # def create_api(cls, platform: Optional[str] = None) -> Optional[TradingAPIInterface]:
    def create_api(cls, config: Config) -> Optional[TradingAPIInterface]:
        """
        Create a trading API instance based on platform configuration.
        
        Args:
            platform: Platform name (optional, uses config if not provided)
            
        Returns:
            TradingAPIInterface instance or None if creation fails
        """
        try:
            # Use provided platform or get from config
            platform = config.TRADING_PLATFORM
            platform_name = platform.lower()
            
            if platform_name not in cls.SUPPORTED_PLATFORMS:
                logger.error(f"Unsupported platform: {platform_name}")
                logger.info(f"Supported platforms: {list(cls.SUPPORTED_PLATFORMS.keys())}")
                return None

            logger.info("APIFactory using platform=%s", platform_name)

            # Create platform-specific API instance
            if platform_name == 'binance':
                return cls._create_binance_api(config)
            elif platform_name == 'tradovate':
                return cls._create_tradovate_api(config)
            elif platform_name == 'ninjatrader':
                return cls._create_ninjatrader_api(config)
            elif platform_name == 'tradovate_ui':
                print("[APIFactory] Using TradovateWebUIAPI (UI automation) - dry_run=", os.getenv("DRY_RUN", "true"))
                return cls._create_tradovate_ui_api(config)
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
            if not config.BINANCE_API_KEY or not config.BINANCE_API_SECRET:
                logger.error("Binance API credentials not found in configuration")
                return None
            
            api = BinanceAPI(
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                testnet=config.BINANCE_TESTNET
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
                config.TRADOVATE_USERNAME,
                config.TRADOVATE_PASSWORD,
                config.TRADOVATE_APP_ID,
                config.TRADOVATE_APP_VERSION,
                config.TRADOVATE_CID,
                config.TRADOVATE_SEC
            ]
            
            if not all(required_fields):
                logger.error("Tradovate API credentials not found in configuration")
                return None
            
            api = TradovateAPI(
                username=config.TRADOVATE_USERNAME,
                password=config.TRADOVATE_PASSWORD,
                app_id=config.TRADOVATE_APP_ID,
                app_version=config.TRADOVATE_APP_VERSION,
                cid=config.TRADOVATE_CID,
                sec=config.TRADOVATE_SEC,
                demo=config.TRADOVATE_DEMO
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
            # if not config.ninjatrader_api_url:
            if not config.NINJATRADER_API_URL:
                logger.error("NinjaTrader API URL not found in configuration")
                return None
            if not config.NINJATRADER_API_KEY:
                logger.error("NinjaTrader API Key not found in configuration")
                return None
            
            api = NinjaTraderAPI(
                # api_url=config.ninjatrader_api_url,
                api_url=config.NINJATRADER_API_URL,
                # api_key=config.ninjatrader_api_key,
                api_key=config.NINJATRADER_API_KEY,
                # simulation=config.ninjatrader_simulation
                simulation=config.NINJATRADER_SIMULATION
            )
            
            logger.info("Created NinjaTrader API instance")
            return api
            
        except Exception as e:
            logger.error(f"Error creating NinjaTrader API: {e}")
            return None

    
    @classmethod
    def _create_tradovate_ui_api(cls, config) -> Optional[TradovateWebUIAPI]:
        """Create UI-driven Tradovate adapter (no REST keys)."""
        try:
            # dry_run = str(getattr(config, "DRY_RUN", "true")).lower() == "true"
            acct_mode = str(getattr(config, "DRY_RUN", "true")).lower()
            # dry_run = acct_mode != "false"  # True = sim, False = live
            normalized = str(getattr(config, "DRY_RUN", "true")).strip().lower()
            dry_run = normalized in ("true", "1", "yes", "on")

            # separate flag: should we actually click UI confirm buttons?
            ui_confirm = str(getattr(config, "DRY_RUN_UI", "false")).lower() == "true"

            logger.info(
                "APIFactory: Creating TradovateWebUIAPI(dry_run=%s, ui_confirm=%s)",
                dry_run,
                ui_confirm,
            )

            # pull from env the knobs we used in the adapter
            api = TradovateWebUIAPI(
                base_url=os.getenv("TRADOVATE_BASE_URL", "https://trader.tradovate.com"),
                username=os.getenv("TRADOVATE_USER") or os.getenv("TRADOVATE_USERNAME", ""),
                password=os.getenv("TRADOVATE_PASS") or os.getenv("TRADOVATE_PASSWORD", ""),
                headless=bool(int(os.getenv("HEADLESS", "0"))),
                storage_dir=os.getenv("BROWSER_STATE_DIR", ".browser_state"),
                timeout_ms=int(os.getenv("BROWSER_TIMEOUT_MS", "15000")),
                # now this matches the main sim flag,
                dry_run=dry_run,
                # fixture_html_path=os.getenv("FIXTURE") or None,
                ui_confirm=ui_confirm,
                # Optional quality-of-life flags in your adapter:
                manual_login=getattr(config, "TRADOVATE_MANUAL_LOGIN", True)
            )

            logger.info("Created Tradovate Web UI adapter")
            return api
        except Exception as e:
            logger.error(f"Error creating Tradovate Web UI adapter: {e}")
            return None
    
    @classmethod
    def get_supported_platforms(cls) -> list:
        """Get list of supported platform names."""
        return list(cls.SUPPORTED_PLATFORMS.keys())
    
    @classmethod
    def validate_platform(cls, platform: str) -> bool:
        """Validate if a platform is supported."""
        return platform.lower() in cls.SUPPORTED_PLATFORMS

