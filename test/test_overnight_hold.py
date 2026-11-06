"""Offline tests for overnight_hold.py: fake clock, fake bot, fake Tradovate API. No browser.

    python test/test_overnight_hold.py -v      (from the repo root)
"""
import datetime as _dt
import os
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import overnight_hold as oh  # noqa: E402

ET = ZoneInfo("America/New_York")


class Clock:
    now = _dt.datetime(2026, 10, 19, 15, 55, 5, tzinfo=ET)       # a Monday


class FakeDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return Clock.now.astimezone(tz) if tz else Clock.now.replace(tzinfo=None)


class FakeTime:
    t = 1_000_000.0

    @classmethod
    def time(cls):
        return cls.t

    @staticmethod
    def sleep(_):
        pass


oh.datetime = FakeDT
oh.time = FakeTime


class FakeAPI:
    def __init__(self, price=7900.0, qty=0, account="DEMO5181998"):
        self.price, self.qty, self.account = price, qty, account

    def get_current_price(self, sym):
        return self.price

    def get_positions(self, root_symbol=None):
        return [] if self.qty == 0 else [{"symbol": "MESZ6", "qty": self.qty}]

    def get_account_label(self):
        return self.account


class FakeBot:
    symbol = "MES"

    def __init__(self, api, blocked=False):
        self.api, self.blocked, self.orders, self._entry_strategy = api, blocked, [], {}

    def entries_blocked(self):
        return self.blocked

    def _execute_trade(self, signal, qty, px):
        self.orders.append((signal["type"], qty, px))
        self.api.qty += qty if signal["type"] == "BUY" else -qty
        return True


class OvernightTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        env = {"OVERNIGHT_ENABLED": "1", "OVERNIGHT_DRY_RUN": "0", "EXPECTED_ACCOUNT": "DEMO5181998"}
        self._old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.closes = os.path.join(self.dir, "closes.csv")
        with open(self.closes, "w") as fh:                        # 200 closes averaging 7500
            fh.write("date,close\n")
            day = _dt.date(2025, 1, 1)
            for i in range(200):
                fh.write(f"{day + _dt.timedelta(days=i)},7500\n")
        self.msgs = []
        Clock.now = _dt.datetime(2026, 10, 19, 15, 55, 5, tzinfo=ET)

    def tearDown(self):
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def make(self, api, **bot_kw):
        self.api, self.bot = api, FakeBot(api, **bot_kw)
        log = type("L", (), {"warning": lambda *a: None, "error": lambda *a: None})()
        return oh.OvernightHold(self.bot, self.msgs.append, log, closes_path=self.closes,
                                state_path=os.path.join(self.dir, "state.json"))

    def flatten_ok(self, reason):
        self.api.qty = 0
        return {"success": True}

    def test_enters_once_when_above_average(self):
        h = self.make(FakeAPI(price=7900))
        for _ in range(5):
            h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [("BUY", 1, 7900)])
        self.assertTrue(h.state["holding"])
        self.assertEqual(self.bot._entry_strategy["MES"], "OvernightHold")

    def test_no_entry_below_average(self):
        h = self.make(FakeAPI(price=7000))
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])
        self.assertIn("below its 200-day average", self.msgs[-1])

    def test_no_entry_when_already_holding(self):
        h = self.make(FakeAPI(price=7900, qty=1))
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])

    def test_no_entry_when_blocked(self):
        h = self.make(FakeAPI(), blocked=True)
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])
        self.assertIn("entries are blocked", self.msgs[-1])

    def test_no_entry_on_wrong_account(self):
        h = self.make(FakeAPI(account="1510541"))
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])
        self.assertIn("wrong Tradovate account", self.msgs[-1])

    def test_dry_run_places_no_orders(self):
        os.environ["OVERNIGHT_DRY_RUN"] = "1"
        h = self.make(FakeAPI(price=7900))
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])
        self.assertIn("DRY RUN: would BUY", self.msgs[-1])

    def test_exit_next_morning(self):
        h = self.make(FakeAPI(price=7900))
        h.tick(self.api, True, self.flatten_ok)                  # Monday 15:55 entry
        Clock.now = _dt.datetime(2026, 10, 20, 9, 30, 2, tzinfo=ET)
        self.api.price = 7920
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.api.qty, 0)
        self.assertFalse(h.state["holding"])
        self.assertIn("+20.00 pts", self.msgs[-1])

    def test_exit_retries_then_alerts_and_resets_next_day(self):
        h = self.make(FakeAPI(qty=1))
        Clock.now = _dt.datetime(2026, 10, 20, 9, 30, 0, tzinfo=ET)
        fail = lambda reason: {"success": False, "message": "rejected"}
        for i in range(6):                                       # 30 s apart
            FakeTime.t += 31
            Clock.now += _dt.timedelta(seconds=31)
            h.tick(self.api, True, fail)
        self.assertTrue(any("EXIT FAILED" in m or "Still holding" in m for m in self.msgs))
        Clock.now = _dt.datetime(2026, 10, 21, 9, 30, 0, tzinfo=ET)      # next day: tries again
        FakeTime.t += 31
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.api.qty, 0)

    def test_weekend_does_nothing(self):
        h = self.make(FakeAPI(price=7900))
        Clock.now = _dt.datetime(2026, 10, 24, 15, 56, tzinfo=ET)        # Saturday
        h.tick(self.api, True, self.flatten_ok)
        self.assertEqual(self.bot.orders, [])


if __name__ == "__main__":
    unittest.main()
