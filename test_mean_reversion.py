#!/usr/bin/env python3
"""Unit tests for MeanReversionStrategy"""


import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime
from mean_reversion_strategy import MeanReversionStrategy


@pytest.fixture
def dm():
    """Mock DataManager"""
    dm = Mock()
    dm.get_current_price = Mock(return_value=6850.0)
    dm.live = Mock()
    return dm


@pytest.fixture
def strategy(dm):
    """MeanReversionStrategy instance"""
    return MeanReversionStrategy(
        data_manager=dm,
        lookback=20,
        std_dev=2.0,
        max_trades_per_day=4
    )


def test_strategy_initialization(strategy):
    """Test strategy initializes correctly"""
    assert strategy.lookback == 20
    assert strategy.std_dev == 2.0
    assert strategy.max_trades_per_day == 4
    assert strategy.trades_today == 0


def test_insufficient_bars(strategy, dm):
    """Test returns None when not enough bars"""
    dm.live.get_last_n = Mock(return_value=[])
   
    signal = strategy.check_signal('ES')
    assert signal is None


def test_buy_signal_lower_band(strategy, dm):
    """Test BUY signal when price touches lower band"""
    # Create mock bars with decreasing prices
    bars = []
    for i in range(20):
        bar = Mock()
        bar.close = 6900.0 - (i * 5)  # Declining prices
        bars.append(bar)
   
    dm.live.get_last_n = Mock(return_value=bars)
    dm.get_current_price = Mock(return_value=6780.0)  # Below lower band
   
    signal = strategy.check_signal('ES')
   
    assert signal is not None
    assert signal['type'] == 'BUY'
    assert signal['symbol'] == 'ES'
    assert signal['reason'] == 'Oversold (BB lower)'


def test_sell_signal_upper_band(strategy, dm):
    """Test SELL signal when price touches upper band"""
    # Create mock bars with increasing prices
    bars = []
    for i in range(20):
        bar = Mock()
        bar.close = 6800.0 + (i * 5)  # Rising prices
        bars.append(bar)
   
    dm.live.get_last_n = Mock(return_value=bars)
    dm.get_current_price = Mock(return_value=6920.0)  # Above upper band
   
    signal = strategy.check_signal('ES')
   
    assert signal is not None
    assert signal['type'] == 'SELL'
    assert signal['symbol'] == 'ES'
    assert signal['reason'] == 'Overbought (BB upper)'


def test_max_trades_limit(strategy, dm):
    """Test respects max trades per day"""
    bars = [Mock(close=6850.0) for _ in range(20)]
    dm.live.get_last_n = Mock(return_value=bars)
    dm.get_current_price = Mock(return_value=6780.0)
   
    # Hit max trades
    strategy.session_date = datetime.now().date().isoformat()
    strategy.trades_today = 4
   
    signal = strategy.check_signal('ES')
    assert signal is None  # Should not generate signal


def test_daily_reset(strategy, dm):
    """Test daily counter resets on new day"""
    strategy.trades_today = 3
    strategy.session_date = "2026-03-01"
   
    bars = [Mock(close=6850.0) for _ in range(20)]
    dm.live.get_last_n = Mock(return_value=bars)
    dm.get_current_price = Mock(return_value=6780.0)
   
    # New day - should reset
    signal = strategy.check_signal('ES')
    assert strategy.trades_today == 1  # Reset and counted this signal


def test_check_breakout_compatibility(strategy, dm):
    """Test compatibility wrapper"""
    bars = [Mock(close=6850.0) for _ in range(20)]
    dm.live.get_last_n = Mock(return_value=bars)
    dm.get_current_price = Mock(return_value=6850.0)
    
    signal = strategy.check_breakout('ES', 6850.0)
    # Should delegate to check_signal
    assert signal is None or isinstance(signal, dict)


def test_analyze_market_context(strategy, dm):
    """Test market context analysis"""
    bars = [Mock(close=6850.0 + i) for i in range(20)]
    dm.live.get_last_n = Mock(return_value=bars)
   
    context = strategy.analyze_market_context('ES')
   
    assert 'sma' in context
    assert 'trades_today' in context
    assert 'max_trades' in context



