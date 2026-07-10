"""
Archive market_bars_1m out of Supabase before the 3-month downsample deletes it.
One CSV per symbol per day under data/archive/. Idempotent (skips fully-archived
past days, always refreshes today). Run weekly, or set a cron.

    python archive_bars.py
"""
from __future__ import annotations
import csv, os
from datetime import datetime, timedelta, timezone
from supabase import create_client
from config import Config

SYMBOLS = ("MNQ_CONTFUT", "MES_CONTFUT", "NQ_CONTFUT", "ES_CONTFUT")
OUT_ROOT = "data/archive"
PAGE = 1000


def _client():
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)


def _bounds(d):
    s = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    e = s + timedelta(days=1)
    return s.strftime("%Y-%m-%d %H:%M:%S+00"), e.strftime("%Y-%m-%d %H:%M:%S+00")


def fetch_day(sb, sym, d):
    start, end = _bounds(d)
    rows, offset = [], 0
    while True:
        chunk = (sb.table("market_bars_1m").select("*")
                 .eq("symbol", sym).gte("ts", start).lt("ts", end)
                 .order("ts").range(offset, offset + PAGE - 1).execute()).data or []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    return rows


def main():
    sb = _client()
    today = datetime.now(timezone.utc).date()
    for sym in SYMBOLS:
        lo = (sb.table("market_bars_1m").select("ts").eq("symbol", sym)
              .order("ts").limit(1).execute()).data
        if not lo:
            print(f"{sym}: no data"); continue
        first = datetime.fromisoformat(
            str(lo[0]["ts"]).replace(" ", "T").replace("+00", "+00:00")).date()
        out_dir = os.path.join(OUT_ROOT, sym)
        os.makedirs(out_dir, exist_ok=True)
        d = first
        while d <= today:
            path = os.path.join(out_dir, f"{d.isoformat()}.csv")
            if os.path.exists(path) and d < today:   # past day already saved
                d += timedelta(days=1); continue
            rows = fetch_day(sb, sym, d)
            if rows:
                cols = ["symbol", "ts", "open", "high", "low", "close", "volume"]
                with open(path, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    for r in rows:
                        w.writerow(r)
                print(f"{sym} {d}: {len(rows)} bars -> {path}")
            d += timedelta(days=1)


if __name__ == "__main__":
    main()
