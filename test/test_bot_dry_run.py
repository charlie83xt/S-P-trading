# tests/test_bot_dry_run.py
import time
from types import SimpleNamespace
from trading_bot import TradingBot


class StubDM:
    def __init__(self, prices):
        self.prices = list(prices)
        self.i = 0
    def get_current_price(self, symbol):
        if self.i < len(self.prices):
            p = self.prices[self.i]
            self.i += 1
            return p
        return self.prices[-1]


class StubStrategy:
    def __init__(self, dm):
        self.dm = dm
        self.last_signal_ts = None
    def ingest_tick(self, symbol, ts, price):
        pass
    def check_breakout(self, symbol, price):
        # fire exactly once
        if self.last_signal_ts is None and price is not None:
            self.last_signal_ts = time.time()
            return {"type": "BUY", "symbol": symbol, "qty": 1, "reason": "unit_test"}
        return None
    def analyze_market_context(self, symbol):
        return {"current_price": self.dm.get_current_price(symbol), "range_position": "unknown"}


def test_dry_run_creates_trade_record(monkeypatch):
    cfg = SimpleNamespace(DEFAULT_SYMBOL="ES", DRY_RUN="true")
    dm = StubDM(prices=[100.0, 100.25, 100.5])
    bot = TradingBot(config=cfg, data_manager=dm)
    bot.set_strategy(StubStrategy(dm))


    # run a tiny slice of the loop manually
    price = dm.get_current_price("ES")
    sig = bot.strategy.check_breakout("ES", price)
    assert sig is not None
    bot._process_signal(sig, price)


    # risk manager should have one record
    rm = bot.risk_manager
    assert hasattr(rm, "trade_history")
    assert len(rm.trade_history) >= 1
    r = rm.trade_history[-1]
    assert r["symbol"] == "ES" and r["side"] in ("BUY", "SELL") and "realized_total" in r






