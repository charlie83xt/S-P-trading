"""Load Databento GLBX.MDP3 ohlcv-1m files (all MES contracts) into per-day regular-hours sessions.

Each day uses its most-traded contract (handles quarterly rolls). Previous-day levels come from
the SAME contract, so roll gaps never leak into PDH/PDL. Results are cached next to the source file.
"""
import io
import os
import pickle
from dataclasses import dataclass

import numpy as np
import pandas as pd

ET = "America/New_York"
RTH_START = 9 * 60 + 30          # 09:30 ET
RTH_END = 16 * 60                # 16:00 ET
CACHE_VERSION = 1


@dataclass
class Day:
    date: object                 # datetime.date
    contract: str                # e.g. "MESZ5"
    m: np.ndarray                # minute of session, 0 = 09:30 ET ... 389 = 15:59 ET
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    pdh: float                   # previous regular-hours high (same contract)
    pdl: float                   # previous regular-hours low
    pclose: float                # previous regular-hours close


def _read_csv(path):
    if path.endswith(".zst"):
        import zstandard
        with open(path, "rb") as fh:
            raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
        return pd.read_csv(io.BytesIO(raw))
    return pd.read_csv(path)


def load_days(path, min_bars=380):
    """Return a list of Day objects (full regular-hours sessions that have a previous day)."""
    cache = f"{path}.days.v{CACHE_VERSION}.pkl"
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        with open(cache, "rb") as fh:
            return pickle.load(fh)

    df = _read_csv(path)
    df = df[~df.symbol.str.contains("-")]                          # outrights only, no spreads
    ts = pd.to_datetime(df.ts_event, utc=True).dt.tz_convert(ET)
    df = df.assign(date=ts.dt.date, mins=ts.dt.hour * 60 + ts.dt.minute)
    r = df[(df.mins >= RTH_START) & (df.mins < RTH_END)].copy()
    r["m"] = r.mins - RTH_START

    front = (r.groupby(["date", "symbol"]).volume.sum().reset_index()
               .sort_values("volume").groupby("date").tail(1).set_index("date").symbol)
    sessions = {k: g.sort_values("m") for k, g in r.groupby(["date", "symbol"])}
    dates = [d for d in sorted(front.index) if len(sessions[(d, front[d])]) >= min_bars]

    days = []
    for i, d in enumerate(dates):
        c = front[d]
        prev = None
        for j in range(i - 1, max(i - 6, -1), -1):
            k = (dates[j], c)
            if k in sessions and len(sessions[k]) >= min_bars:
                prev = sessions[k]
                break
        if prev is None:
            continue
        g = sessions[(d, c)]
        days.append(Day(d, c, g.m.to_numpy(), g.open.to_numpy(float), g.high.to_numpy(float),
                        g.low.to_numpy(float), g.close.to_numpy(float), g.volume.to_numpy(float),
                        float(prev.high.max()), float(prev.low.min()), float(prev.close.iloc[-1])))
    with open(cache, "wb") as fh:
        pickle.dump(days, fh)
    return days
