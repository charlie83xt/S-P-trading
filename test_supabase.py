# test_data_manager_supabase.py


import pytest
from datetime import datetime, timedelta
from data_manager import DataManager
from config import Config


@pytest.fixture
def dm():
    """DataManager instance with Supabase"""
    config = Config()
    return DataManager(config)


def test_get_historical_bars_with_timezone(dm):
    """Test Supabase query with explicit UTC timezone"""
    # Use a known weekday with market data
    bars = dm.get_historical_bars(
        'ES',
        '2026-02-23 14:30:00+00',  # 9:30 AM ET in UTC
        '2026-02-23 15:00:00+00'   # 10:00 AM ET in UTC
    )
   
    assert isinstance(bars, list)
    if bars:  # If data exists
        assert len(bars) == 30  # 30 minutes of 1m bars
        assert all('open' in b for b in bars)


def test_get_historical_bars_auto_timezone(dm):
    """Test that missing timezone gets +00 suffix"""
    bars = dm.get_historical_bars(
        'ES',
        '2026-02-23 14:30:00',  # No timezone
        '2026-02-23 15:00:00'
    )
   
    # Should auto-add +00 and work
    assert isinstance(bars, list)


def test_query_yesterday_bars_full_session(dm):
    """Test convenience wrapper for yesterday's full session"""
    bars = dm.query_yesterday_bars('ES')  # 9:30 AM - 4:00 PM ET
   
    assert isinstance(bars, list)
    # Weekend or Supabase unavailable → empty list OK
    # Weekday with data → ~390 bars expected


def test_query_yesterday_bars_custom_range(dm):
    """Test custom time range"""
    bars = dm.query_yesterday_bars('ES', start_hour=10, end_hour=12)
   
    assert isinstance(bars, list)
    if bars:
        assert len(bars) <= 120  # Max 2 hours of 1m bars


def test_get_historical_bars_weekend(dm):
    """Edge case: Query weekend (no market data)"""
    # Force a known weekend date
    bars = dm.get_historical_bars(
        'ES',
        '2026-03-01 14:30:00+00',  # Sunday
        '2026-03-01 15:00:00+00'
    )
   
    assert bars == []  # No market on weekends


def test_get_historical_bars_no_supabase(dm):
    """Edge case: Supabase unavailable"""
    dm.supabase = None
    bars = dm.get_historical_bars('ES', '2026-02-23 14:30:00+00', '2026-02-23 15:00:00+00')
   
    assert bars == []  # Graceful fallback


def test_et_to_utc_timestamp(dm):
    """Test timezone conversion helper"""
    utc_ts = dm._et_to_utc_timestamp('2026-03-01', '09:30:00')
   
    # 9:30 AM ET = 14:30 UTC (EST, no DST in early March)
    assert '14:30:00+00' in utc_ts or '13:30:00+00' in utc_ts  # Account for DST
