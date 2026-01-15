"""
Test script for the Opening Range Strategy.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import logging

from data_manager import DataManager
from opening_range_strategy import OpeningRangeStrategy
from risk_manager import RiskManager
from config import config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_mock_data(symbol: str, days: int = 5) -> pd.DataFrame:
    """
    Generate mock price data for testing.
    
    Args:
        symbol: Trading symbol
        days: Number of days of data to generate
        
    Returns:
        DataFrame with mock OHLCV data
    """
    # Generate timestamps for the last N days
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    
    # Generate minute-by-minute timestamps
    timestamps = pd.date_range(start=start_time, end=end_time, freq='1min')
    
    # Generate realistic price data
    base_price = 4500.0  # S&P 500 base price
    price_data = []
    
    current_price = base_price
    
    for i, timestamp in enumerate(timestamps):
        # Add some randomness and trends
        daily_trend = np.sin(i / (24 * 60) * 2 * np.pi) * 10  # Daily cycle
        noise = np.random.normal(0, 2)  # Random noise
        
        # Calculate price change
        price_change = daily_trend + noise
        current_price += price_change * 0.1  # Scale the change
        
        # Generate OHLC for this minute
        high = current_price + abs(np.random.normal(0, 1))
        low = current_price - abs(np.random.normal(0, 1))
        open_price = current_price + np.random.normal(0, 0.5)
        close_price = current_price + np.random.normal(0, 0.5)
        volume = np.random.randint(1000, 10000)
        
        price_data.append({
            'timestamp': timestamp,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close_price,
            'volume': volume
        })
    
    df = pd.DataFrame(price_data)
    df.set_index('timestamp', inplace=True)
    
    return df

def test_opening_range_strategy():
    """Test the opening range strategy with mock data."""
    print("🧪 Testing Opening Range Strategy")
    print("=" * 50)
    
    # Create data manager (will use mock data)
    data_manager = DataManager()
    
    # Create strategy
    strategy = OpeningRangeStrategy(data_manager, opening_range_minutes=30, breakout_threshold=0.1)
    
    # Create risk manager
    risk_manager = RiskManager()
    
    # Generate mock data
    symbol = "ES"  # S&P 500 E-mini futures
    mock_data = generate_mock_data(symbol, days=2)
    
    print(f"Generated {len(mock_data)} data points for {symbol}")
    print(f"Price range: {mock_data['low'].min():.2f} - {mock_data['high'].max():.2f}")
    
    # Test opening range calculation
    print("\n📊 Testing Opening Range Calculation")
    
    # Use the first 30 minutes of data as opening range
    opening_data = mock_data.head(30)
    range_low = opening_data['low'].min()
    range_high = opening_data['high'].max()
    
    print(f"Opening Range: {range_low:.2f} - {range_high:.2f}")
    print(f"Range Size: {range_high - range_low:.2f}")
    
    # Manually set the opening range in strategy
    strategy.opening_range_low = range_low
    strategy.opening_range_high = range_high
    strategy.range_established = True
    
    # Test signal generation
    print("\n🎯 Testing Signal Generation")
    signals = []
    
    # Test with prices that should generate signals
    test_prices = [
        range_high + 5,   # Should generate BUY signal
        range_low - 5,    # Should generate SELL signal
        (range_high + range_low) / 2,  # Should not generate signal
        range_high + 10,  # Should generate another BUY signal
    ]
    
    for i, price in enumerate(test_prices):
        signal = strategy.check_breakout(symbol, price)
        if signal:
            signals.append(signal)
            print(f"✅ Signal {i+1}: {signal['type']} at {price:.2f}")
        else:
            print(f"❌ No signal at {price:.2f}")
    
    # Test risk management
    print("\n🛡️ Testing Risk Management")
    
    account_balance = 100000.0  # $100k account
    
    for signal in signals:
        is_valid, reason, quantity = risk_manager.validate_trade(
            signal, account_balance, signal['price']
        )
        
        print(f"Signal: {signal['type']} at {signal['price']:.2f}")
        print(f"  Valid: {is_valid}")
        print(f"  Reason: {reason}")
        print(f"  Quantity: {quantity:.4f}")
        
        if is_valid:
            # Simulate trade execution
            risk_manager.record_trade_entry(
                symbol, signal['type'].lower(), quantity, signal['price']
            )
            
            # Simulate exit after some profit/loss
            exit_price = signal['price'] * (1.02 if signal['type'] == 'BUY' else 0.98)
            risk_manager.record_trade_exit(symbol, exit_price, "test_exit")
    
    # Show risk metrics
    print("\n📈 Risk Metrics")
    metrics = risk_manager.get_risk_metrics()
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    
    # Test market analysis
    print("\n🔍 Testing Market Analysis")
    
    # Mock the data manager methods for testing
    class MockDataManager:
        def get_current_price(self, symbol):
            return mock_data['close'].iloc[-1]
        
        def get_yesterday_range(self, symbol):
            yesterday_data = mock_data.iloc[-1440:-720]  # Yesterday's data
            return {
                'day': (yesterday_data['low'].min(), yesterday_data['high'].max()),
                'night': (yesterday_data['low'].min(), yesterday_data['high'].max())
            }
        
        def get_price_range(self, symbol, hours_back):
            recent_data = mock_data.tail(hours_back * 60)
            return recent_data['low'].min(), recent_data['high'].max()
    
    # Replace data manager temporarily
    original_dm = strategy.data_manager
    strategy.data_manager = MockDataManager()
    
    analysis = strategy.analyze_market_context(symbol)
    
    print("Market Analysis:")
    for key, value in analysis.items():
        print(f"  {key}: {value}")
    
    # Restore original data manager
    strategy.data_manager = original_dm
    
    print("\n✅ Strategy testing completed!")

def test_platform_switching():
    """Test platform switching functionality."""
    print("\n🔄 Testing Platform Switching")
    print("=" * 50)
    
    from api_factory import APIFactory
    
    # Test supported platforms
    platforms = APIFactory.get_supported_platforms()
    print(f"Supported platforms: {platforms}")
    
    for platform in platforms:
        try:
            print(f"\n🔌 Testing {platform.upper()} API creation...")
            
            # This will fail due to missing credentials, but should create the API object
            api = APIFactory.create_api(platform)
            print(f"✅ {api.get_platform_name()} API created successfully")
            
            # Test connection (will likely fail due to missing credentials)
            connected = api.connect()
            if connected:
                print(f"✅ Connected to {platform}")
                api.disconnect()
            else:
                print(f"❌ Failed to connect to {platform} (expected - no credentials)")
                
        except Exception as e:
            print(f"❌ Error with {platform}: {e}")

def test_data_caching():
    """Test data caching functionality."""
    print("\n💾 Testing Data Caching")
    print("=" * 50)
    
    data_manager = DataManager()
    symbol = "BTCUSDT"
    
    # Test cache initialization
    print("Testing database initialization...")
    data_manager._init_database()
    print("✅ Database initialized")
    
    # Generate and cache some mock data
    mock_data = generate_mock_data(symbol, days=1)
    
    print(f"Caching {len(mock_data)} data points...")
    data_manager._cache_data(symbol, '1m', mock_data)
    print("✅ Data cached")
    
    # Test cache retrieval
    print("Testing cache retrieval...")
    cached_data = data_manager._get_cached_data(symbol, '1m', 100)
    print(f"✅ Retrieved {len(cached_data)} cached data points")
    
    # Test cleanup
    print("Testing cache cleanup...")
    data_manager.cleanup_old_data(days_to_keep=0)  # Remove all data
    print("✅ Cache cleaned up")

def main():
    """Main test function."""
    print("🚀 FUTURES TRADING BOT - STRATEGY TESTING")
    print("=" * 60)
    
    try:
        # Run all tests
        test_opening_range_strategy()
        test_platform_switching()
        test_data_caching()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

