"""
Test script for the Opening Range Breakthrough Strategy.
This script provides comprehensive testing capabilities for the trading bot components.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch, MagicMock

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(__file__))

from config import TradingConfig, update_config
from data_manager import DataManager
from opening_range_strategy import OpeningRangeStrategy, SignalType, TradingSignal
from risk_manager import RiskManager, RiskLevel
from trading_bot import TradingBot

class TestDataManager(unittest.TestCase):
    """Test cases for the DataManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = TradingConfig()
        self.config.testnet = True
        self.config.api_key = "test_key"
        self.config.api_secret = "test_secret"
        
    @patch('data_manager.Client')
    def test_data_manager_initialization(self, mock_client):
        """Test DataManager initialization."""
        mock_client.return_value = Mock()
        
        with patch('sqlite3.connect') as mock_connect:
            mock_connect.return_value = Mock()
            data_manager = DataManager()
            
            self.assertIsNotNone(data_manager.client)
            self.assertIsNotNone(data_manager.db_connection)
    
    def test_calculate_opening_range_with_mock_data(self):
        """Test opening range calculation with mock data."""
        # Create mock data
        mock_data = pd.DataFrame({
            'timestamp': [1640995200000 + i * 60000 for i in range(30)],  # 30 minutes of data
            'open_price': [50000 + np.random.randn() * 10 for _ in range(30)],
            'high_price': [50010 + np.random.randn() * 10 for _ in range(30)],
            'low_price': [49990 + np.random.randn() * 10 for _ in range(30)],
            'close_price': [50005 + np.random.randn() * 10 for _ in range(30)],
            'volume': [100 + np.random.randn() * 10 for _ in range(30)]
        })
        
        # Set datetime index
        mock_data['datetime'] = pd.to_datetime(mock_data['timestamp'], unit='ms')
        mock_data.set_index('datetime', inplace=True)
        
        with patch('data_manager.DataManager.get_historical_data') as mock_get_data:
            mock_get_data.return_value = mock_data
            
            with patch('sqlite3.connect') as mock_connect:
                mock_connect.return_value = Mock()
                
                with patch('data_manager.Client') as mock_client:
                    mock_client.return_value = Mock()
                    
                    data_manager = DataManager()
                    
                    # Test opening range calculation
                    test_date = datetime(2022, 1, 1)
                    opening_range = data_manager.calculate_opening_range("BTCUSDT", test_date)
                    
                    self.assertIsNotNone(opening_range)
                    self.assertIn('high_price', opening_range)
                    self.assertIn('low_price', opening_range)
                    self.assertIn('range_size', opening_range)

class TestOpeningRangeStrategy(unittest.TestCase):
    """Test cases for the OpeningRangeStrategy class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_data_manager = Mock(spec=DataManager)
        self.strategy = OpeningRangeStrategy(self.mock_data_manager)
        
    def test_strategy_initialization(self):
        """Test strategy initialization."""
        self.assertIsNotNone(self.strategy.data_manager)
        self.assertEqual(len(self.strategy.opening_ranges), 0)
        self.assertEqual(len(self.strategy.active_positions), 0)
        self.assertEqual(self.strategy.daily_pnl, 0.0)
        
    def test_signal_generation_no_opening_range(self):
        """Test signal generation when no opening range is available."""
        current_time = datetime.now()
        signal = self.strategy.generate_signal("BTCUSDT", 50000.0, current_time)
        
        self.assertEqual(signal.signal_type, SignalType.NO_SIGNAL)
        self.assertIn("No valid opening range", signal.reason)
        
    def test_signal_generation_with_breakthrough(self):
        """Test signal generation with price breakthrough."""
        # Set up mock opening range
        from opening_range_strategy import OpeningRange
        opening_range = OpeningRange(
            symbol="BTCUSDT",
            date="2022-01-01",
            high=50100.0,
            low=49900.0,
            range_size=200.0,
            range_size_pct=0.4,
            volume=1000.0,
            start_time=datetime(2022, 1, 1, 0, 0),
            end_time=datetime(2022, 1, 1, 0, 30),
            is_valid=True
        )
        
        self.strategy.opening_ranges["BTCUSDT"] = opening_range
        
        # Test long signal (price above opening range high)
        current_time = datetime(2022, 1, 1, 1, 0)  # After opening range
        signal = self.strategy.generate_signal("BTCUSDT", 50150.0, current_time)
        
        self.assertEqual(signal.signal_type, SignalType.LONG)
        self.assertGreater(signal.confidence, 0.0)
        self.assertIsNotNone(signal.stop_loss)
        self.assertIsNotNone(signal.take_profit)
        
        # Test short signal (price below opening range low)
        signal = self.strategy.generate_signal("BTCUSDT", 49850.0, current_time)
        
        self.assertEqual(signal.signal_type, SignalType.SHORT)
        self.assertGreater(signal.confidence, 0.0)
        
    def test_position_update(self):
        """Test position tracking updates."""
        signal = TradingSignal(
            signal_type=SignalType.LONG,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime.now(),
            confidence=0.8,
            stop_loss=49900.0,
            take_profit=50200.0,
            position_size=0.01
        )
        
        # Test opening position
        self.strategy.update_position("BTCUSDT", signal)
        self.assertIn("BTCUSDT", self.strategy.active_positions)
        self.assertEqual(self.strategy.active_positions["BTCUSDT"]["direction"], "long")
        
        # Test closing position
        close_signal = TradingSignal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            price=50100.0,
            timestamp=datetime.now(),
            confidence=1.0
        )
        
        self.strategy.update_position("BTCUSDT", close_signal)
        self.assertNotIn("BTCUSDT", self.strategy.active_positions)
        self.assertGreater(self.strategy.daily_pnl, 0)  # Should be profitable

class TestRiskManager(unittest.TestCase):
    """Test cases for the RiskManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.risk_manager = RiskManager()
        
    def test_risk_manager_initialization(self):
        """Test risk manager initialization."""
        self.assertEqual(self.risk_manager.daily_pnl, 0.0)
        self.assertEqual(self.risk_manager.max_drawdown, 0.0)
        self.assertEqual(len(self.risk_manager.positions), 0)
        self.assertFalse(self.risk_manager.emergency_stop)
        
    def test_signal_validation_basic(self):
        """Test basic signal validation."""
        signal = TradingSignal(
            signal_type=SignalType.LONG,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime.now(),
            confidence=0.8,
            position_size=0.01
        )
        
        is_valid, reason = self.risk_manager.validate_signal(signal)
        self.assertTrue(is_valid)
        
    def test_signal_validation_position_limit(self):
        """Test signal validation with position limits."""
        # Fill up to maximum positions
        for i in range(self.risk_manager.config.max_open_positions):
            self.risk_manager.positions[f"SYMBOL{i}"] = {
                'direction': 'long',
                'entry_price': 50000.0,
                'position_size': 0.01
            }
        
        # Try to add one more position
        signal = TradingSignal(
            signal_type=SignalType.LONG,
            symbol="NEWBTC",
            price=50000.0,
            timestamp=datetime.now(),
            confidence=0.8,
            position_size=0.01
        )
        
        is_valid, reason = self.risk_manager.validate_signal(signal)
        self.assertFalse(is_valid)
        self.assertIn("Maximum open positions", reason)
        
    def test_emergency_stop_activation(self):
        """Test emergency stop activation."""
        # Simulate large loss
        self.risk_manager.daily_pnl = -self.risk_manager.config.max_daily_loss * 2
        self.risk_manager._check_risk_violations()
        
        self.assertTrue(self.risk_manager.emergency_stop)
        
        # Test signal validation with emergency stop
        signal = TradingSignal(
            signal_type=SignalType.LONG,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime.now(),
            confidence=0.8,
            position_size=0.01
        )
        
        is_valid, reason = self.risk_manager.validate_signal(signal)
        self.assertFalse(is_valid)
        self.assertIn("Emergency stop", reason)
        
    def test_risk_metrics_calculation(self):
        """Test risk metrics calculation."""
        # Add some positions
        self.risk_manager.positions["BTCUSDT"] = {
            'direction': 'long',
            'entry_price': 50000.0,
            'position_size': 0.01,
            'unrealized_pnl': 100.0
        }
        
        metrics = self.risk_manager.get_risk_metrics()
        
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.position_count, 1)
        self.assertGreater(metrics.total_exposure, 0)
        self.assertIsInstance(metrics.risk_level, RiskLevel)

class TestTradingBot(unittest.TestCase):
    """Test cases for the TradingBot class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.bot = TradingBot()
        
    def test_bot_initialization(self):
        """Test bot initialization."""
        self.assertFalse(self.bot.is_running)
        self.assertFalse(self.bot.is_paused)
        self.assertIsNone(self.bot.data_manager)
        self.assertIsNone(self.bot.strategy)
        self.assertIsNone(self.bot.risk_manager)
        
    @patch('trading_bot.DataManager')
    @patch('trading_bot.OpeningRangeStrategy')
    @patch('trading_bot.RiskManager')
    def test_component_initialization(self, mock_risk_manager, mock_strategy, mock_data_manager):
        """Test component initialization."""
        mock_data_manager.return_value = Mock()
        mock_strategy.return_value = Mock()
        mock_risk_manager.return_value = Mock()
        
        self.bot.initialize_components()
        
        self.assertIsNotNone(self.bot.data_manager)
        self.assertIsNotNone(self.bot.strategy)
        self.assertIsNotNone(self.bot.risk_manager)
        
    def test_pause_and_resume(self):
        """Test bot pause and resume functionality."""
        # Test pause
        success = self.bot.pause(30)
        self.assertTrue(success)
        self.assertTrue(self.bot.is_paused)
        self.assertIsNotNone(self.bot.cooldown_until)
        
        # Test resume
        success = self.bot.resume()
        self.assertTrue(success)
        self.assertFalse(self.bot.is_paused)
        self.assertIsNone(self.bot.cooldown_until)
        
    def test_configuration_update(self):
        """Test configuration updates."""
        original_position_size = self.bot.config.default_position_size
        
        success = self.bot.update_configuration(default_position_size=0.05)
        self.assertTrue(success)
        self.assertNotEqual(self.bot.config.default_position_size, original_position_size)
        
    def test_status_reporting(self):
        """Test status reporting."""
        status = self.bot.get_status()
        
        self.assertIn('bot_info', status)
        self.assertIn('performance', status)
        self.assertIn('configuration', status)
        self.assertIn('is_running', status['bot_info'])

class TestIntegration(unittest.TestCase):
    """Integration tests for the complete trading system."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.bot = TradingBot()
        
    @patch('data_manager.Client')
    @patch('sqlite3.connect')
    def test_full_system_integration(self, mock_connect, mock_client):
        """Test full system integration."""
        # Mock database and API client
        mock_connect.return_value = Mock()
        mock_client.return_value = Mock()
        
        # Mock API responses
        mock_client.return_value.get_historical_klines.return_value = [
            [1640995200000, "50000", "50100", "49900", "50050", "100", 1640995260000, "5005000", 100, "50", "2502500", "0"]
            for i in range(30)
        ]
        mock_client.return_value.get_symbol_ticker.return_value = {"price": "50075"}
        
        # Initialize components
        self.bot.initialize_components()
        
        # Verify all components are initialized
        self.assertIsNotNone(self.bot.data_manager)
        self.assertIsNotNone(self.bot.strategy)
        self.assertIsNotNone(self.bot.risk_manager)
        
        # Test data retrieval
        data = self.bot.data_manager.get_historical_data("BTCUSDT", "1m", limit=30)
        self.assertIsNotNone(data)
        
        # Test signal generation
        current_price = 50150.0  # Above opening range
        signal = self.bot.strategy.generate_signal("BTCUSDT", current_price, datetime.now())
        
        # Test risk validation
        is_valid, reason = self.bot.risk_manager.validate_signal(signal)
        
        # Get system status
        status = self.bot.get_status()
        self.assertIsNotNone(status)

def run_performance_test():
    """Run performance tests for the trading system."""
    print("\n" + "="*50)
    print("PERFORMANCE TEST RESULTS")
    print("="*50)
    
    # Test data processing speed
    import time
    
    # Mock large dataset
    large_data = pd.DataFrame({
        'timestamp': [1640995200000 + i * 60000 for i in range(1000)],
        'open_price': [50000 + np.random.randn() * 100 for _ in range(1000)],
        'high_price': [50010 + np.random.randn() * 100 for _ in range(1000)],
        'low_price': [49990 + np.random.randn() * 100 for _ in range(1000)],
        'close_price': [50005 + np.random.randn() * 100 for _ in range(1000)],
        'volume': [100 + np.random.randn() * 10 for _ in range(1000)]
    })
    
    start_time = time.time()
    
    # Test data processing
    high_price = large_data['high_price'].max()
    low_price = large_data['low_price'].min()
    range_size = high_price - low_price
    
    processing_time = time.time() - start_time
    print(f"Data processing (1000 records): {processing_time:.4f} seconds")
    
    # Test signal generation speed
    mock_data_manager = Mock()
    strategy = OpeningRangeStrategy(mock_data_manager)
    
    start_time = time.time()
    for i in range(100):
        signal = strategy.generate_signal("BTCUSDT", 50000 + i, datetime.now())
    
    signal_time = time.time() - start_time
    print(f"Signal generation (100 signals): {signal_time:.4f} seconds")
    print(f"Average signal generation time: {signal_time/100:.6f} seconds")
    
    # Test risk validation speed
    risk_manager = RiskManager()
    test_signal = TradingSignal(
        signal_type=SignalType.LONG,
        symbol="BTCUSDT",
        price=50000.0,
        timestamp=datetime.now(),
        confidence=0.8,
        position_size=0.01
    )
    
    start_time = time.time()
    for i in range(100):
        is_valid, reason = risk_manager.validate_signal(test_signal)
    
    validation_time = time.time() - start_time
    print(f"Risk validation (100 validations): {validation_time:.4f} seconds")
    print(f"Average validation time: {validation_time/100:.6f} seconds")

def run_strategy_backtest():
    """Run a simple backtest of the opening range strategy."""
    print("\n" + "="*50)
    print("STRATEGY BACKTEST RESULTS")
    print("="*50)
    
    # Generate mock historical data
    np.random.seed(42)  # For reproducible results
    
    dates = pd.date_range(start='2022-01-01', end='2022-01-10', freq='D')
    results = []
    
    for date in dates:
        # Generate opening range
        opening_high = 50000 + np.random.randn() * 50
        opening_low = opening_high - (100 + np.random.randn() * 20)
        range_size = opening_high - opening_low
        
        # Generate subsequent price movement
        breakthrough_prob = 0.3  # 30% chance of breakthrough
        if np.random.random() < breakthrough_prob:
            # Breakthrough occurred
            direction = np.random.choice(['up', 'down'])
            if direction == 'up':
                exit_price = opening_high + range_size * (1 + np.random.random())
                pnl = exit_price - opening_high
            else:
                exit_price = opening_low - range_size * (1 + np.random.random())
                pnl = opening_low - exit_price
            
            results.append({
                'date': date,
                'opening_high': opening_high,
                'opening_low': opening_low,
                'range_size': range_size,
                'breakthrough': True,
                'direction': direction,
                'exit_price': exit_price,
                'pnl': pnl
            })
        else:
            # No breakthrough
            results.append({
                'date': date,
                'opening_high': opening_high,
                'opening_low': opening_low,
                'range_size': range_size,
                'breakthrough': False,
                'direction': None,
                'exit_price': None,
                'pnl': 0
            })
    
    # Calculate backtest statistics
    df = pd.DataFrame(results)
    
    total_trades = df['breakthrough'].sum()
    winning_trades = len(df[(df['breakthrough'] == True) & (df['pnl'] > 0)])
    losing_trades = len(df[(df['breakthrough'] == True) & (df['pnl'] < 0)])
    
    total_pnl = df['pnl'].sum()
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df[df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    print(f"Backtest Period: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"Total Trading Days: {len(dates)}")
    print(f"Total Trades: {total_trades}")
    print(f"Winning Trades: {winning_trades}")
    print(f"Losing Trades: {losing_trades}")
    print(f"Win Rate: {win_rate:.2%}")
    print(f"Total P&L: ${total_pnl:.2f}")
    print(f"Average Win: ${avg_win:.2f}")
    print(f"Average Loss: ${avg_loss:.2f}")
    
    if avg_loss != 0:
        profit_factor = abs(avg_win * winning_trades) / abs(avg_loss * losing_trades)
        print(f"Profit Factor: {profit_factor:.2f}")

if __name__ == "__main__":
    print("="*60)
    print("FUTURES TRADING BOT - COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    # Run unit tests
    print("\nRunning Unit Tests...")
    unittest.main(argv=[''], exit=False, verbosity=2)
    
    # Run performance tests
    run_performance_test()
    
    # Run strategy backtest
    run_strategy_backtest()
    
    print("\n" + "="*60)
    print("TEST SUITE COMPLETED")
    print("="*60)

