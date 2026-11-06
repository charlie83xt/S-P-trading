"""Build data/overnight_closes.csv for the bot's 200-day filter from the Databento MES files.

Daily close = last regular-hours (16:00 ET) 1-minute close of the most-traded contract. Older
contracts are back-adjusted (ratio at each roll) so the series is on the latest contract's price
level, like a continuous chart.

    python -m research.make_overnight_seed analysis/2024-2025.ohlcv-1m.csv.zst \
        analysis/2025-2026.ohlcv-1m.csv.zst --out data/overnight_closes.csv
"""
import argparse

import pandas as pd

from .data import RTH_END, RTH_START, _read_csv, ET


def daily_closes(paths):
    df = pd.concat([_read_csv(p) for p in paths])
    df = df[~df.symbol.str.contains("-")]
    ts = pd.to_datetime(df.ts_event, utc=True).dt.tz_convert(ET)
    mins = ts.dt.hour * 60 + ts.dt.minute
    df = df.assign(date=ts.dt.date, mins=mins)[(mins >= RTH_START) & (mins < RTH_END)]
    df = df.sort_values(["date", "symbol", "mins"])
    per = df.groupby(["date", "symbol"]).agg(close=("close", "last"), volume=("volume", "sum"),
                                             bars=("close", "size")).reset_index()
    per = per[per.bars >= 380]
    front = per.sort_values("volume").groupby("date").tail(1).set_index("date").sort_index()
    closes = per.set_index(["date", "symbol"]).close
    out = front[["symbol", "close"]].copy()
    adj = pd.Series(1.0, index=out.index)
    dates = list(out.index)
    for i in range(len(dates) - 1, 0, -1):                 # walk back, scaling older contracts
        new, old = out.symbol.iloc[i], out.symbol.iloc[i - 1]
        if new != old and (dates[i - 1], new) in closes.index:
            ratio = closes[(dates[i - 1], new)] / closes[(dates[i - 1], old)]
            adj.iloc[:i] *= ratio
    out["close_adj"] = (out.close * adj).round(2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="data/overnight_closes.csv")
    a = ap.parse_args()
    out = daily_closes(a.files)
    pd.DataFrame({"date": [d.isoformat() for d in out.index], "close": out.close_adj.values}).to_csv(a.out, index=False)
    rolls = out.symbol.ne(out.symbol.shift()).sum() - 1
    print(f"wrote {len(out)} daily closes ({out.index[0]} .. {out.index[-1]}, {rolls} rolls adjusted, "
          f"latest contract {out.symbol.iloc[-1]}) to {a.out}")


if __name__ == "__main__":
    main()
