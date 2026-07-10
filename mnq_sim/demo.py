"""
Runnable smoke test / demo.

    python -m mnq_sim.demo

It (1) verifies the Task-1 VWAP seeding window is correctly ordered, then
(2) generates synthetic sessions and runs the full detector -> gate -> backtest
pipeline so you can see the per-tag report render.

The synthetic numbers are MEANINGLESS as a strategy result -- this only proves
the code runs end to end. Real conclusions need your real historical bars.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo

from .types import Bar, SessionLevels
from .vwap import seed_window_utc
from .backtest import run_backtest, format_report

ET = ZoneInfo("America/New_York")


def check_seeding_fix() -> None:
    now_et = datetime(2026, 6, 26, 10, 15, tzinfo=ET)
    start_ts, end_ts = seed_window_utc(now_et, lookback_minutes=5)
    assert start_ts < end_ts, (start_ts, end_ts)
    print("Task 1 seed window check:")
    print(f"  start_ts = {start_ts}")
    print(f"  end_ts   = {end_ts}")
    print(f"  ordered  = {start_ts < end_ts}  (start before end -> query returns bars)")
    print()


def _gen_session(d: date, base: float, rng: random.Random) -> list[Bar]:
    """Random-walk 5-min bars from 09:30 to 11:30 ET around a base price."""
    bars = []
    t = datetime.combine(d, time(9, 30), tzinfo=ET)
    end = datetime.combine(d, time(11, 30), tzinfo=ET)
    price = base + rng.uniform(-15, 15)   # open somewhere near value
    drift = rng.uniform(-0.6, 0.6)        # gives some sessions a trend
    while t <= end:
        o = price
        step = rng.gauss(drift, 4.0)
        c = o + step
        hi = max(o, c) + abs(rng.gauss(0, 2.0))
        lo = min(o, c) - abs(rng.gauss(0, 2.0))
        vol = max(1.0, rng.gauss(800, 200))
        bars.append(Bar(ts=t, open=round(o, 2), high=round(hi, 2),
                        low=round(lo, 2), close=round(c, 2), volume=vol))
        price = c
        t += timedelta(minutes=5)
    return bars


def main() -> None:
    check_seeding_fix()

    rng = random.Random(7)
    base = 18000.0
    all_bars: list[Bar] = []
    levels_map: dict[date, SessionLevels] = {}

    start = date(2026, 5, 4)  # a Monday
    sessions = 0
    d = start
    while sessions < 40:
        if d.weekday() < 5:  # weekdays only
            sb = _gen_session(d, base, rng)
            all_bars.extend(sb)
            # synthetic FRVP levels around the base
            poc = base + rng.uniform(-5, 5)
            levels_map[d] = SessionLevels(
                session_date=d, vah=poc + 12, poc=poc, val=poc - 12,
                pdh=poc + 22, pdl=poc - 22)
            base += rng.uniform(-20, 20)  # walk the base across days
            sessions += 1
        d += timedelta(days=1)

    res = run_backtest(all_bars, lambda dt: levels_map[dt], oos_fraction=0.30)
    print(format_report(res))


if __name__ == "__main__":
    main() 

