from risk_manager import RiskManager
from datetime import datetime


def almost(a, b, eps=1e-9):
    return abs(a - b) < eps


def run():
    rm = RiskManager()
    rm.contract_multipliers = {"ES": 50.0}


    # Buy 1 @ 100
    t1 = rm.paper_fill(symbol="ES", side="BUY", qty=1, price=100.0)
    assert rm.positions["ES"]["qty"] == 1
    assert almost(rm.positions["ES"]["avg_price"], 100.0)
    assert almost(rm.realized_pnl, 0.0)


    # Mark @ 101 => +50 unrealized
    rm.mark_to_market(symbol="ES", last_price=101.0)
    assert almost(rm.positions["ES"]["unrealized"], 50.0)
    assert almost(rm.daily_pnl, 50.0)


    # Sell 1 @ 102 => +100 realized, no position
    t2 = rm.paper_fill(symbol="ES", side="SELL", qty=1, price=102.0)
    assert rm.positions["ES"]["qty"] == 0
    assert almost(rm.realized_pnl, 100.0)
    rm.mark_to_market(symbol="ES", last_price=102.0)
    # no unrealized now, daily = realized
    assert almost(rm.daily_pnl, 100.0)


    print("OK: paper engine math is sane.")
    print("Trades:", rm.trade_history if hasattr(rm, "trade_history") else [t1, t2])


if __name__ == "__main__":
    run()






