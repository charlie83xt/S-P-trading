"""
Session VWAP engine + the corrected seeding logic from Task 1.

The seeding bug (Task 1): the old ET-string conversion chain produced a start
timestamp that, after round-tripping through parse/format, landed AFTER the end
timestamp -> Supabase got start > end -> 0 rows -> VWAP seeded empty.

Fix: convert `now_et - 5min` straight to UTC and format with an explicit +00
offset, so no ET<->str round-trip can flip the order. The DB call itself stays
out of this module (no credentials here) -- you pass in a fetch callable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Iterable, Optional

from .types import Bar, VwapColor


def seed_window_utc(now_et: datetime, lookback_minutes: int = 5):
    """Return (start_ts, end_ts) UTC strings for the VWAP seed query.

    This is the Task-1 fix in isolated, testable form. `now_et` must be a
    timezone-aware ET datetime. start is the RTH open of `now_et`'s date
    (09:30 ET); end is `now_et - lookback` converted directly to UTC.
    """
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware (ET)")

    # RTH open for the session = 09:30 ET on now_et's date.
    rth_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    start_utc = rth_open_et.astimezone(_tz.utc)
    seed_end_utc = (now_et - timedelta(minutes=lookback_minutes)).astimezone(_tz.utc)

    start_ts = start_utc.strftime("%Y-%m-%d %H:%M:%S+00")
    end_ts = seed_end_utc.strftime("%Y-%m-%d %H:%M:%S+00")

    # The guard the bug slipped past. Cheap, and it would have caught the original.
    assert start_ts < end_ts, ("inverted seed window", start_ts, end_ts)
    return start_ts, end_ts


class VwapEngine:
    """Running session VWAP with a slope-derived color.

    Color is modeled from the VWAP slope over `color_lookback` updates:
        rising  beyond +threshold  -> GREEN (longs only)
        falling beyond -threshold  -> RED   (shorts only)
        within  the flat band      -> WHITE (no trade)

    Real charting packages color VWAP a few different ways; slope is a simple,
    transparent proxy and is documented as a modeling choice, not gospel.
    """

    def __init__(self, color_lookback: int = 3, flat_band_points: float = 0.75):
        self._cum_pv = 0.0      # sum(typical * volume)
        self._cum_v = 0.0       # sum(volume)
        self._history: list[float] = []
        self.color_lookback = color_lookback
        self.flat_band = flat_band_points

    def reset(self) -> None:
        self._cum_pv = 0.0
        self._cum_v = 0.0
        self._history.clear()

    def _add(self, bar: Bar) -> None:
        self._cum_pv += bar.typical * bar.volume
        self._cum_v += bar.volume

    def seed(self, bars: Iterable[Bar]) -> int:
        """Seed the session VWAP from pre-connect bars. Returns count seeded."""
        n = 0
        for b in bars:
            self._add(b)
            n += 1
        if self._cum_v > 0:
            self._history.append(self.value)
        return n

    def update(self, bar: Bar) -> None:
        """Fold one new live/historical bar into the running VWAP."""
        self._add(bar)
        self._history.append(self.value)

    @property
    def value(self) -> Optional[float]:
        if self._cum_v <= 0:
            return None
        return self._cum_pv / self._cum_v

    def color(self) -> VwapColor:
        if len(self._history) <= self.color_lookback:
            return VwapColor.WHITE
        slope = self._history[-1] - self._history[-1 - self.color_lookback]
        if slope > self.flat_band:
            return VwapColor.GREEN
        if slope < -self.flat_band:
            return VwapColor.RED
        return VwapColor.WHITE


def seed_from_fetch(
    engine: VwapEngine,
    now_et: datetime,
    fetch_bars: Callable[[str, str], Iterable[Bar]],
    lookback_minutes: int = 5,
) -> dict:
    """Glue for the live bot: build the corrected window, fetch, seed, verify.

    `fetch_bars(start_ts, end_ts)` is YOUR Supabase call (kept out of this
    module so no credentials live here). Returns a small report dict you can
    log and eyeball against TradingView's VWAP for the same minute.
    """
    start_ts, end_ts = seed_window_utc(now_et, lookback_minutes)
    bars = list(fetch_bars(start_ts, end_ts))
    n = engine.seed(bars)
    report = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "ordered_ok": start_ts < end_ts,
        "bars_returned": len(bars),
        "bars_seeded": n,
        "seeded_vwap": engine.value,
    }
    return report 
