# tests/test_api.py
import json
from types import SimpleNamespace
from web_app import app, bot as app_bot
from trading_bot import TradingBot


class DM:
    def __init__(self, price): self.price = price
    def get_current_price(self, symbol): return self.price


class Strat:
    def __init__(self, dm): self.dm = dm
    def ingest_tick(self, *a, **k): pass
    def check_breakout(self, s, p): return None
    def analyze_market_context(self, s): return {"current_price": self.dm.get_current_price(s), "range_position": "middle"}


def test_market_and_trades_endpoints(monkeypatch):
    cfg = SimpleNamespace(DEFAULT_SYMBOL="ES", DRY_RUN="true")
    dm = DM(price=123.45)
    bot = TradingBot(cfg, dm)
    bot.set_strategy(Strat(dm))
    # inject the bot used by Flask
    monkeypatch.setenv("FLASK_ENV", "testing")
    import web_app
    web_app.bot = bot


    client = app.test_client()
    r = client.get("/api/market_analysis")
    payload = r.get_json()
    assert payload["success"] is True
    assert isinstance(payload["analysis"], dict)


    # empty trades initially
    r = client.get("/api/trades")
    payload = r.get_json()
    assert payload["success"] is True
    assert isinstance(payload["trades"], list)






