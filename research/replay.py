"""Replay adapter: run the bot's LIVE strategy classes, unchanged, on historical bars.

The live strategies read the wall clock (time.time / datetime.now) and a DataManager fed by the
browser. Here both are replaced:
  - a simulated clock that advances one minute per bar (patched into the strategy's module)
  - ReplayDataManager, which serves the same methods from historical 1-minute bars
    (method bodies follow data_manager.py so the strategies see the same shapes)

The bot calls ingest_tick() and check_breakout() about once a second; the replay calls them once
per 1-minute bar, at the bar's close. Exits are not part of these strategies (the live bot's risk
manager handles them), so the replay applies live-like exits that you can change in `exits`.
"""
import datetime as _dt
import logging
import sys
import time as _time
import types
from zoneinfo import ZoneInfo

from .backtest import Entry

ET = ZoneInfo("America/New_York")
SYMBOL = "MES"

# The live strategies log a lot; keep research output readable.
logging.disable(logging.CRITICAL)

# opening_range_strategy.py imports `from data_manager import DataManager` (type hint only).
# The real data_manager pulls in the whole trading stack, so research gets a stub module.
if "data_manager" not in sys.modules:
    _stub = types.ModuleType("data_manager")
    _stub.DataManager = object
    sys.modules["data_manager"] = _stub


# --------------------------------------------------------------------------- clock

class Clock:
    def __init__(self):
        self.now = 0.0


class _TimeShim:
    """Stands in for the `time` module inside a strategy module."""
    def __init__(self, clock):
        self._clock = clock

    def time(self):
        return self._clock.now

    def __getattr__(self, name):
        return getattr(_time, name)


def _datetime_for(clock):
    class ReplayDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            t = _dt.datetime.fromtimestamp(clock.now, tz or ET)
            return t if tz else t.replace(tzinfo=None)      # naive = New York wall time
    return ReplayDateTime


def patch_clock(module, clock):
    """Point a strategy module's `time` and `datetime` names at the simulated clock."""
    if getattr(module, "time", None) is _time:
        module.time = _TimeShim(clock)
    if getattr(module, "datetime", None) is _dt.datetime:
        module.datetime = _datetime_for(clock)


# --------------------------------------------------------------------------- data

class Bar:
    __slots__ = ("ts_open", "open", "high", "low", "close", "volume")

    def __init__(self, ts_open, o, h, l, c, v):
        self.ts_open, self.open, self.high, self.low, self.close, self.volume = ts_open, o, h, l, c, v

    @property
    def timestamp(self):            # used by DataManager.get_prev_day_levels_local
        return self.ts_open


class DailyBar:
    def __init__(self, date, o, h, l, c, v=0.0):
        self.timestamp, self.open, self.high, self.low, self.close, self.volume = date, o, h, l, c, v


class LiveStore:
    """Same interface as data_manager.LiveBarStore. The last bar is treated as the current one."""
    def __init__(self):
        self.bars = []

    def get_last_n(self, symbol, n=60):
        return self.bars[-n:]

    get_bars = get_last_n

    def get_opening_range(self, symbol, minutes, session_anchor_ts):
        end_cut = session_anchor_ts + minutes * 60.0
        sel = [b for b in self.bars if session_anchor_ts <= b.ts_open < end_cut]
        if not sel:
            return None
        return (min(b.low for b in sel), max(b.high for b in sel))


class ReplayDataManager:
    supabase = None                                   # strategies skip their Supabase extras

    def __init__(self, clock):
        self.clock = clock
        self.live = LiveStore()
        self.daily_history = []                       # previous days as DailyBar, oldest first
        self.logger = logging.getLogger("replay_dm")

    def get_current_price(self, symbol):
        return self.live.bars[-1].close if self.live.bars else None

    def get_opening_range(self, symbol, minutes=30, session_anchor_ts=None):
        minutes = int(minutes)
        if session_anchor_ts is not None:
            rng = self.live.get_opening_range(symbol, minutes, session_anchor_ts)
            if rng:
                return (float(rng[0]), float(rng[1]))
        bars = self.live.get_last_n(symbol, minutes)
        if not bars:
            cp = self.get_current_price(symbol)
            return (cp, cp)
        return (float(min(b.low for b in bars)), float(max(b.high for b in bars)))

    def get_last_closed_candles(self, symbol, timeframe="5m", n=2):
        if timeframe == "5m":
            bars_1m = self.live.get_last_n(symbol, n=5 * n + 10)
            if len(bars_1m) < 5:
                return []
            complete = bars_1m[:-1]
            out = []
            for i in range(0, len(complete), 5):
                ch = complete[i:i + 5]
                if len(ch) == 5:
                    out.append({"ts": ch[0].ts_open, "open": ch[0].open, "high": max(b.high for b in ch),
                                "low": min(b.low for b in ch), "close": ch[-1].close,
                                "close_ts": ch[-1].ts_open + 60, "volume": sum(b.volume for b in ch)})
            return out[-n:]
        if timeframe == "1m":
            bars = self.live.get_last_n(symbol, n=n + 1)
            if len(bars) < 2:
                return []
            return [{"ts": b.ts_open, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                     "close_ts": b.ts_open + 60, "volume": b.volume} for b in bars[:-1]][-n:]
        return []

    def get_sma(self, symbol, length, timeframe="5m", offset=0):
        c = self.get_last_closed_candles(symbol, timeframe, n=length + offset)
        if len(c) < length + offset:
            return 0.0
        rel = c[-(length + offset):-offset] if offset > 0 else c[-length:]
        return sum(x["close"] for x in rel) / len(rel) if len(rel) >= length else 0.0

    def get_candles(self, symbol, timeframe, start_ts, end_ts):
        return [{"ts": b.ts_open, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                 "volume": b.volume}
                for b in self.live.get_last_n(symbol, n=100) if start_ts <= b.ts_open < end_ts]

    def get_daily_bars(self, symbol, days=5):
        out = list(self.daily_history[-days:])
        if self.live.bars:                            # today's partial bar comes last, like live
            b = self.live.bars
            out.append(DailyBar(_dt.datetime.fromtimestamp(b[0].ts_open, ET).date(), b[0].open,
                                max(x.high for x in b), min(x.low for x in b), b[-1].close))
        return out

    def get_prev_day_levels_local(self, symbol):
        return None        # live store only holds today's bars, as in the live bot after a restart

    def get_historical_bars(self, *a, **k):
        return []

    def query_yesterday_bars(self, *a, **k):
        return []


# --------------------------------------------------------------------------- harness wrapper

DEFAULT_EXITS = {"default_stop": 6.0, "min_stop": 2.0, "max_stop": 12.0, "target": 10.0,
                 "breakeven_at": 4.0, "breakeven_lock": 1.0, "exit_at_m": 123}


class LiveStrategyReplay:
    """Base class for research/strategies/live_*.py wrappers.

    Subclasses set: name, modules (the strategy's module objects), build(dm) -> strategy instance,
    and optionally entry_window=(first_m, last_m) and exits={...}.
    A fresh strategy instance is built every day, as when the bot is restarted each morning.
    """
    name = "live_strategy"
    modules = ()
    entry_window = (15, 120)          # 09:45 - 11:30 ET
    exits = DEFAULT_EXITS

    def __init__(self):
        self.clock = Clock()
        for mod in self.modules:
            patch_clock(mod, self.clock)
        self.params = {"entry_window": list(self.entry_window), **self.exits}
        self._history = []
        self._last = None

    def build(self, dm):
        raise NotImplementedError

    def reset(self, day):
        if self._last is not None:                       # remember yesterday for get_daily_bars
            self._history.append(self._last)
            self._history = self._history[-10:]
        self.t0 = _dt.datetime.combine(day.date, _dt.time(9, 30), ET).timestamp()
        self.clock.now = self.t0
        self.dm = ReplayDataManager(self.clock)
        self.dm.daily_history = list(self._history)
        self.strategy = self.build(self.dm)
        self._fed = 0
        self._last = None
        self._date = day.date
        self._hi, self._lo = float("-inf"), float("inf")

    def _feed(self, i, bars):
        while self._fed <= i:                            # catch up on bars skipped while in a trade
            k = self._fed
            self.dm.live.bars.append(Bar(self.t0 + int(bars.m[k]) * 60, float(bars.open[k]),
                                         float(bars.high[k]), float(bars.low[k]),
                                         float(bars.close[k]), float(bars.volume[k])))
            self._hi, self._lo = max(self._hi, float(bars.high[k])), min(self._lo, float(bars.low[k]))
            self._fed += 1
        b = self.dm.live.bars
        self._last = DailyBar(self._date, b[0].open, self._hi, self._lo, b[-1].close)

    def on_bar(self, i, bars):
        self._feed(i, bars)
        m = int(bars.m[i])
        self.clock.now = self.t0 + m * 60 + 59.9        # end of this minute
        price = float(bars.close[i])
        s = self.strategy
        if hasattr(s, "ingest_tick"):
            s.ingest_tick(SYMBOL, self.clock.now, price)
        sig = s.check_breakout(SYMBOL, price)
        if not sig or str(sig.get("type", "")).upper() not in ("BUY", "SELL"):
            return None
        if not (self.entry_window[0] <= m < self.entry_window[1]):
            return None
        if hasattr(s, "on_trade_executed"):
            s.on_trade_executed()
        ctx = sig.get("context") or {}
        est = ctx.get("stop_est_points") or sig.get("stop_est_points")
        x = self.exits
        stop = min(x["max_stop"], max(x["min_stop"], float(est) if est else x["default_stop"]))
        return Entry(side=1 if sig["type"].upper() == "BUY" else -1, stop_pts=stop,
                     target_pts=x["target"], breakeven_at=x["breakeven_at"],
                     breakeven_lock=x["breakeven_lock"], exit_at_m=x["exit_at_m"])
