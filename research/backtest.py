"""Event-driven, cost-aware backtester. Strategies only ever see bars up to the current minute.

A strategy is a class with:
    name: str
    params: dict                    (recorded in the registry)
    def reset(self, day_info): ...  called at the start of each day (day_info has pdh, pdl, pclose, date)
    def on_bar(self, i, bars): ...  bars = BarsView of the day up to and including bar i;
                                    return None or an Entry
One position at a time; on_bar is not called while a position is open.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

POINT_VALUE = 5.0            # MES: $5 per point
COMMISSION = 1.24            # $ per round trip (2 x $0.62)
SLIPPAGE_TICKS = 1           # per side
TICK = 0.25
COST_PER_TRADE = COMMISSION + 2 * SLIPPAGE_TICKS * TICK * POINT_VALUE   # $3.74


@dataclass
class Entry:
    side: int                        # +1 long, -1 short
    stop_pts: float                  # distance from entry, > 0
    target_pts: Optional[float] = None
    exit_at_m: int = 389             # force exit at the open of this minute (389 = 15:59 ET)
    breakeven_at: Optional[float] = None   # move stop to entry + lock once this many pts in profit
    breakeven_lock: float = 1.0


class BarsView:
    """Read-only window on today's bars [0..i]. Arrays are numpy views (no copies)."""
    def __init__(self, day, i):
        s = slice(0, i + 1)
        self.m, self.open, self.high = day.m[s], day.open[s], day.high[s]
        self.low, self.close, self.volume = day.low[s], day.close[s], day.volume[s]


@dataclass
class DayInfo:
    date: object
    pdh: float
    pdl: float
    pclose: float


def _simulate(day, i, e: Entry):
    """Enter at the close of bar i. Stops are checked before targets inside a bar (conservative)."""
    price = day.close[i]
    stop = price - e.side * e.stop_pts
    best = 0.0
    for k in range(i + 1, len(day.m)):
        if day.m[k] >= e.exit_at_m:
            return k, (day.open[k] - price) * e.side, "time"
        adverse = day.low[k] if e.side > 0 else day.high[k]
        favour = day.high[k] if e.side > 0 else day.low[k]
        if (adverse - stop) * e.side <= 0:
            return k, (stop - price) * e.side, "stop"
        if e.target_pts and (favour - price) * e.side >= e.target_pts:
            return k, e.target_pts, "target"
        best = max(best, (favour - price) * e.side)
        if e.breakeven_at and best >= e.breakeven_at:
            be = price + e.side * e.breakeven_lock
            if (be - stop) * e.side > 0:
                stop = be
    k = len(day.m) - 1
    return k, (day.close[k] - price) * e.side, "close"


def run(strategy, days):
    """Returns a DataFrame of trades with P&L after costs."""
    rows = []
    for day in days:
        strategy.reset(DayInfo(day.date, day.pdh, day.pdl, day.pclose))
        i = 0
        while i < len(day.m):
            e = strategy.on_bar(i, BarsView(day, i))
            if e is None:
                i += 1
                continue
            if e.side not in (1, -1) or e.stop_pts <= 0:
                raise ValueError(f"{strategy.name}: invalid entry {e}")
            k, pts, how = _simulate(day, i, e)
            rows.append(dict(date=day.date, contract=day.contract, entry_m=int(day.m[i]), exit_m=int(day.m[k]),
                             side=e.side, entry=day.close[i], pts=pts, how=how,
                             usd=pts * POINT_VALUE - COST_PER_TRADE))
            i = k + 1
    return pd.DataFrame(rows, columns=["date", "contract", "entry_m", "exit_m", "side", "entry",
                                       "pts", "how", "usd"])
