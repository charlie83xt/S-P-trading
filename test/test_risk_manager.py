# tests/test_risk_manager.py
import math
import time
from datetime import datetime, timedelta
from risk_manager import RiskManager


EPS = 1e-6
def almost(a, b, eps=EPS): return abs(a - b) < eps


def test_long_round_trip_realized_and_unrealized():
    rm = RiskManager()
    rm.contract_multipliers = {"ES": 50.0}


    # Buy 1 @ 100
    t1 = rm.paper_fill(symbol="ES", side="BUY", qty=1, price=100.0, dry_run=True)
    assert rm.positions["ES"]["qty"] == 1
    assert almost(rm.positions["ES"]["avg_price"], 100.0)
    assert almost(rm.realized_pnl, 0.0)


    # Mark @ 101 => +50 unrealized
    rm.mark_to_market(symbol="ES", last_price=101.0)
    assert almost(rm.positions["ES"]["unrealized"], 50.0)
    assert almost(rm.daily_pnl, 50.0)


    # Sell 1 @ 102 => +100 realized, flat
    t2 = rm.paper_fill(symbol="ES", side="SELL", qty=1, price=102.0, dry_run=True)
    assert rm.positions["ES"]["qty"] == 0
    assert almost(rm.realized_pnl, 100.0)
    rm.mark_to_market(symbol="ES", last_price=102.0)
    assert almost(rm.daily_pnl, 100.0)


    # Records appended and normalized
    assert isinstance(rm.trade_history, list) and len(rm.trade_history) >= 2
    for rec in rm.trade_history:
        assert "symbol" in rec and "side" in rec and "qty" in rec
        assert "price" in rec and "realized_total" in rec and "position_qty" in rec


def test_short_round_trip():
    rm = RiskManager()
    rm.contract_multipliers = {"ES": 50.0}


    # Sell short 2 @ 100
    rm.paper_fill("ES", "SELL", 2, 100.0, dry_run=True)
    assert rm.positions["ES"]["qty"] == -2
    assert almost(rm.positions["ES"]["avg_price"], 100.0)


    # Cover 1 @ 98 => +100 realized (2 points * 50 * 1)
    rm.paper_fill("ES", "BUY", 1, 98.0, dry_run=True)
    assert rm.positions["ES"]["qty"] == -1
    assert almost(rm.realized_pnl, (100.0 - 98.0) * 50.0 * 1)


    # Cover 1 @ 103 => -150 realized more, total now -50
    rm.paper_fill("ES", "BUY", 1, 103.0, dry_run=True)
    assert rm.positions["ES"]["qty"] == 0
    total = (100.0 - 98.0) * 50.0 + (100.0 - 103.0) * 50.0
    assert almost(rm.realized_pnl, total)


def test_contract_multiplier_map():
    rm = RiskManager()
    rm.contract_multipliers = {"ES": 50.0, "NQ": 20.0}
    rm.paper_fill("NQ", "BUY", 1, 100.0, dry_run=True)
    rm.mark_to_market("NQ", 101.0)
    assert almost(rm.positions["NQ"]["unrealized"], 20.0)


def test_daily_reset_logic():
    rm = RiskManager()
    # simulate a prior date
    rm._last_reset_date = (datetime.utcnow() - timedelta(days=1)).date()
    # trigger any call that checks the date
    rm.reset_if_new_day()
    assert rm.daily_trades == 0
    assert almost(rm.daily_pnl, 0.0)




