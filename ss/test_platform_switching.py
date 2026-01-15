#!/usr/bin/env python3
"""
Test script for platform switching functionality.
Tests the ability to switch between different trading platforms.
"""

import os
import sys
import time
import logging
from typing import Dict, Any

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import get_config, update_config
from api_factory import APIFactory
from data_manager import DataManager
from trading_bot import TradingBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlatformSwitchingTest:
    """Test class for platform switching functionality."""
    
    def __init__(self):
        self.test_results = {}
        self.original_platform = None
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all platform switching tests."""
        logger.info("Starting platform switching tests...")
        
        # Store original platform
        config = get_config()
        self.original_platform = config.platform
        
        try:
            # Test 1: API Factory Platform Creation
            self.test_api_factory_creation()
            
            # Test 2: Configuration Updates
            self.test_configuration_updates()
            
            # Test 3: Data Manager Platform Switching
            self.test_data_manager_switching()
            
            # Test 4: Trading Bot Platform Switching
            self.test_trading_bot_switching()
            
            # Test 5: Platform Validation
            self.test_platform_validation()
            
        except Exception as e:
            logger.error(f"Test suite failed: {e}")
            self.test_results['suite_error'] = str(e)
        
        finally:
            # Restore original platform
            if self.original_platform:
                self._set_platform(self.original_platform)
        
        return self.test_results
    
    def test_api_factory_creation(self):
        """Test API factory platform creation."""
        logger.info("Testing API factory platform creation...")
        
        test_name = "api_factory_creation"
        self.test_results[test_name] = {}
        
        platforms = ['binance', 'tradovate', 'ninjatrader']
        
        for platform in platforms:
            try:
                logger.info(f"Testing {platform} API creation...")
                
                # Set platform
                self._set_platform(platform)
                
                # Create API instance
                api = APIFactory.create_api()
                
                if api is None:
                    self.test_results[test_name][platform] = {
                        'success': False,
                        'error': 'API creation returned None'
                    }
                    continue
                
                # Check platform name
                platform_name = api.get_platform_name()
                expected_names = {
                    'binance': 'Binance Futures',
                    'tradovate': 'Tradovate',
                    'ninjatrader': 'NinjaTrader'
                }
                
                success = platform_name == expected_names.get(platform)
                
                self.test_results[test_name][platform] = {
                    'success': success,
                    'platform_name': platform_name,
                    'expected_name': expected_names.get(platform),
                    'api_type': type(api).__name__
                }
                
                logger.info(f"{platform} API creation: {'PASS' if success else 'FAIL'}")
                
            except Exception as e:
                self.test_results[test_name][platform] = {
                    'success': False,
                    'error': str(e)
                }
                logger.error(f"{platform} API creation failed: {e}")
    
    def test_configuration_updates(self):
        """Test configuration updates for platform switching."""
        logger.info("Testing configuration updates...")
        
        test_name = "configuration_updates"
        self.test_results[test_name] = {}
        
        platforms = ['binance', 'tradovate', 'ninjatrader']
        
        for platform in platforms:
            try:
                logger.info(f"Testing {platform} configuration...")
                
                # Set platform
                self._set_platform(platform)
                
                # Get updated config
                config = get_config()
                
                success = config.platform == platform
                
                self.test_results[test_name][platform] = {
                    'success': success,
                    'config_platform': config.platform,
                    'expected_platform': platform
                }
                
                logger.info(f"{platform} configuration: {'PASS' if success else 'FAIL'}")
                
            except Exception as e:
                self.test_results[test_name][platform] = {
                    'success': False,
                    'error': str(e)
                }
                logger.error(f"{platform} configuration failed: {e}")
    
    def test_data_manager_switching(self):
        """Test data manager platform switching."""
        logger.info("Testing data manager platform switching...")
        
        test_name = "data_manager_switching"
        self.test_results[test_name] = {}
        
        platforms = ['binance']  # Only test platforms with working credentials
        
        for platform in platforms:
            try:
                logger.info(f"Testing {platform} data manager...")
                
                # Set platform
                self._set_platform(platform)
                
                # Create data manager (this will use the new platform)
                data_manager = DataManager()
                
                # Check if API is initialized correctly
                api_platform = data_manager.api.get_platform_name() if data_manager.api else None
                
                expected_names = {
                    'binance': 'Binance Futures',
                    'tradovate': 'Tradovate',
                    'ninjatrader': 'NinjaTrader'
                }
                
                success = api_platform == expected_names.get(platform)
                
                self.test_results[test_name][platform] = {
                    'success': success,
                    'api_platform': api_platform,
                    'expected_platform': expected_names.get(platform),
                    'api_connected': data_manager.api.is_connected() if data_manager.api else False
                }
                
                # Cleanup
                data_manager.disconnect()
                
                logger.info(f"{platform} data manager: {'PASS' if success else 'FAIL'}")
                
            except Exception as e:
                self.test_results[test_name][platform] = {
                    'success': False,
                    'error': str(e)
                }
                logger.error(f"{platform} data manager failed: {e}")
    
    def test_trading_bot_switching(self):
        """Test trading bot platform switching."""
        logger.info("Testing trading bot platform switching...")
        
        test_name = "trading_bot_switching"
        self.test_results[test_name] = {}
        
        platforms = ['binance']  # Only test platforms with working credentials
        
        for platform in platforms:
            try:
                logger.info(f"Testing {platform} trading bot...")
                
                # Set platform
                self._set_platform(platform)
                
                # Create trading bot (this will use the new platform)
                bot = TradingBot()
                
                # Get status to check platform
                status = bot.get_status()
                
                expected_names = {
                    'binance': 'Binance Futures',
                    'tradovate': 'Tradovate',
                    'ninjatrader': 'NinjaTrader'
                }
                
                success = status.get('platform') == expected_names.get(platform)
                
                self.test_results[test_name][platform] = {
                    'success': success,
                    'bot_platform': status.get('platform'),
                    'expected_platform': expected_names.get(platform),
                    'is_connected': status.get('is_connected', False)
                }
                
                # Cleanup
                bot.disconnect()
                
                logger.info(f"{platform} trading bot: {'PASS' if success else 'FAIL'}")
                
            except Exception as e:
                self.test_results[test_name][platform] = {
                    'success': False,
                    'error': str(e)
                }
                logger.error(f"{platform} trading bot failed: {e}")
    
    def test_platform_validation(self):
        """Test platform validation functionality."""
        logger.info("Testing platform validation...")
        
        test_name = "platform_validation"
        self.test_results[test_name] = {}
        
        # Test valid platforms
        valid_platforms = ['binance', 'tradovate', 'ninjatrader']
        invalid_platforms = ['invalid', 'test', 'unknown']
        
        try:
            # Test valid platforms
            for platform in valid_platforms:
                is_valid = APIFactory.validate_platform(platform)
                self.test_results[test_name][f"valid_{platform}"] = {
                    'success': is_valid,
                    'platform': platform,
                    'is_valid': is_valid
                }
            
            # Test invalid platforms
            for platform in invalid_platforms:
                is_valid = APIFactory.validate_platform(platform)
                self.test_results[test_name][f"invalid_{platform}"] = {
                    'success': not is_valid,  # Should be False for invalid platforms
                    'platform': platform,
                    'is_valid': is_valid
                }
            
            # Test supported platforms list
            supported = APIFactory.get_supported_platforms()
            expected_supported = ['binance', 'tradovate', 'ninjatrader']
            
            self.test_results[test_name]['supported_platforms'] = {
                'success': set(supported) == set(expected_supported),
                'supported': supported,
                'expected': expected_supported
            }
            
            logger.info("Platform validation: PASS")
            
        except Exception as e:
            self.test_results[test_name]['error'] = str(e)
            logger.error(f"Platform validation failed: {e}")
    
    def _set_platform(self, platform: str):
        """Set the platform in environment and update config."""
        os.environ['TRADING_PLATFORM'] = platform
        # Force config reload by creating new instance
        global config
        from config import get_config
        config = get_config()
    
    def print_results(self):
        """Print test results in a readable format."""
        print("\n" + "="*60)
        print("PLATFORM SWITCHING TEST RESULTS")
        print("="*60)
        
        for test_name, test_data in self.test_results.items():
            print(f"\n{test_name.upper().replace('_', ' ')}:")
            print("-" * 40)
            
            if isinstance(test_data, dict):
                for platform, result in test_data.items():
                    if isinstance(result, dict):
                        status = "PASS" if result.get('success', False) else "FAIL"
                        print(f"  {platform}: {status}")
                        
                        if not result.get('success', False) and 'error' in result:
                            print(f"    Error: {result['error']}")
                    else:
                        print(f"  {platform}: {result}")
            else:
                print(f"  {test_data}")
        
        print("\n" + "="*60)

def main():
    """Main test function."""
    print("Platform-Agnostic Futures Trading Bot")
    print("Platform Switching Test Suite")
    print("="*60)
    
    # Run tests
    test_suite = PlatformSwitchingTest()
    results = test_suite.run_all_tests()
    
    # Print results
    test_suite.print_results()
    
    # Summary
    total_tests = 0
    passed_tests = 0
    
    for test_name, test_data in results.items():
        if isinstance(test_data, dict):
            for platform, result in test_data.items():
                if isinstance(result, dict) and 'success' in result:
                    total_tests += 1
                    if result['success']:
                        passed_tests += 1
    
    print(f"\nSUMMARY: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("✅ All tests passed! Platform switching is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Check the results above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

