#!/usr/bin/env python3
"""Integration tests for multi-strategy system"""


import pytest
from strategy_factory import create, list_strategies
from strategy_manager import StrategyManager
from unittest.mock import Mock


def test_list_strategies():
    """Test strategy registry returns all enabled strategies"""
    strategies = list_strategies()
   
    names = [s['name'] for s in strategies if s['enabled']]
   
    # Should have these enabled
    assert 'ORBRetest' in names
    assert 'MeanReversion' in names
   
    # Should NOT have these (disabled)
    enabled_only = [s['name'] for s in strategies if s.get('enabled', True)]
    assert 'OpeningRange' not in enabled_only or not any(
        s['name'] == 'OpeningRange' and s['enabled'] for s in strategies
    )


def test_create_mean_reversion():
    """Test factory can create MeanReversionStrategy"""
    dm = Mock()
   
    strategy = create(
        'MeanReversion',
        data_manager=dm,
        lookback=20,
        std_dev=2.0
    )
   
    assert strategy is not None
    assert hasattr(strategy, 'check_signal')
    assert hasattr(strategy, 'check_breakout')


def test_strategy_manager_initialization():
    """Test StrategyManager loads all strategies"""
    dm = Mock()
    config = Mock()
    config.ORB_RETEST_OR_MINUTES = 15
    config.ORB_RETEST_BREAKOUT_POINTS = 2.0
    config.MEAN_REVERSION_LOOKBACK = 20
    config.MEAN_REVERSION_STD_DEV = 2.0
    config.MEAN_REVERSION_MAX_TRADES = 4
   
    analytics = Mock()
   
    manager = StrategyManager(dm, config, analytics)
   
    # Should have all 3 strategies
    assert 'ORBRetest' in manager.strategies
    assert 'MeanReversion' in manager.strategies
    assert 'OpeningRange' in manager.strategies


def test_strategy_manager_time_based_switching():
    """Test StrategyManager selects correct strategy by time"""
    dm = Mock()
    config = Mock()
    config.ORB_RETEST_OR_MINUTES = 15
    config.ORB_RETEST_BREAKOUT_POINTS = 2.0
    config.MEAN_REVERSION_LOOKBACK = 20
    config.MEAN_REVERSION_STD_DEV = 2.0
    config.MEAN_REVERSION_MAX_TRADES = 4
   
    analytics = Mock()
    analytics.get_strategy_performance = Mock(return_value={})
   
    manager = StrategyManager(dm, config, analytics)
   
    # Morning (10:00 AM ET) - should use ORBRetest
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
   
    morning_10am = datetime(2026, 3, 3, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    strategy = manager.get_active_strategy(ts=morning_10am.timestamp())
    assert manager.current_strategy_name == 'ORBRetest'
   
    # Afternoon (2:00 PM ET) - should use MeanReversion
    afternoon_2pm = datetime(2026, 3, 3, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    strategy = manager.get_active_strategy(ts=afternoon_2pm.timestamp())
    assert manager.current_strategy_name == 'MeanReversion'
   
    # Early morning (8:30 AM ET) - should use OpeningRange
    early_830am = datetime(2026, 3, 3, 8, 30, tzinfo=ZoneInfo("America/New_York"))
    strategy = manager.get_active_strategy(ts=early_830am.timestamp())
    assert manager.current_strategy_name == 'OpeningRange'



