"""
MNQ backtest runner — wires Supabase 1-min bars into the mnq_sim package.
Sim/research only. No broker, no orders.

    python run_mnq_backtest.py --days 60
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo

from supabase import create_client
from config import Config

from mnq_sim.types import Bar, SessionLevels
from mnq_sim.profile import compute_profile
from mnq_sim.backtest import run_backtest, format_report

ET = ZoneInfo("America/New_York")
SYMBOL_DB = "MNQ_CONTFUT"


def _client():
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)


def _parse_ts(s: str) -> datetime:
    # Supabase format: "2026-06-22 02:48:00+00"
    s = str(s).replace(" ", "T")
    if s.endswith("+00"):
        s = s[:-3] + "+00:00"
    return datetime.fromisoformat(s)


def fetch_1m(sb, start_utc: datetime, end_utc: datetime) -> list[dict]:
    start_ts = start_utc.strftime("%Y-%m-%d %H:%M:%S+00")
    end_ts = end_utc.strftime("%Y-%m-%d %H:%M:%S+00")
    resp = (sb.table("market_bars_1m").select("*")
            .eq("symbol", SYMBOL_DB)
            .gte("ts", start_ts).lte("ts", end_ts)
            .order("ts", desc=False).execute())
    return resp.data or []


def aggregate_5m(rows: list[dict]) -> list[Bar]:
    buckets: dict[int, list] = {}
    for r in rows:
        dt_et = _parse_ts(r["ts"]).astimezone(ET)
        key = int(dt_et.timestamp() // 300)
        buckets.setdefault(key, []).append((dt_et, r))
    bars = []
    for key in sorted(buckets):
        items = sorted(buckets[key], key=lambda x: x[0])
        ts0 = items[0][0].replace(second=0, microsecond=0)
        bars.append(Bar(
            ts=ts0,
            open=float(items[0][1]["open"]),
            high=max(float(x[1]["high"]) for x in items),
            low=min(float(x[1]["low"]) for x in items),
            close=float(items[-1][1]["close"]),
            volume=max(sum(float(x[1].get("volume") or 0) for x in items), 1.0),
        ))
    return bars


def rth_window_utc(d: date, start_hm, end_hm):
    s = datetime.combine(d, time(*start_hm), tzinfo=ET).astimezone(timezone.utc)
    e = datetime.combine(d, time(*end_hm), tzinfo=ET).astimezone(timezone.utc)
    return s, e


def levels_from_prior_day(sb, d: date):
    """Compute FRVP from the most recent prior trading day (walk back up to 5)."""
    pday = d - timedelta(days=1)
    for _ in range(5):
        ps, pe = rth_window_utc(pday, (9, 30), (16, 0))
        pbars = aggregate_5m(fetch_1m(sb, ps, pe))
        if pbars:
            pdh = max(b.high for b in pbars)
            pdl = min(b.low for b in pbars)
            try:
                return compute_profile(pbars, d, pdh, pdl, bin_size=1.0)
            except ValueError:
                return None
        pday -= timedelta(days=1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60, help="calendar days back to test")
    ap.add_argument("--oos", type=float, default=0.30, help="out-of-sample fraction")
    args = ap.parse_args()

    sb = _client()
    today = datetime.now(ET).date()

    all_bars: list[Bar] = []
    levels_map: dict[date, SessionLevels] = {}

    d = today - timedelta(days=args.days)
    while d < today:
        if d.weekday() < 5:  # weekdays only
            s, e = rth_window_utc(d, (9, 30), (12, 0))
            sbars = aggregate_5m(fetch_1m(sb, s, e))
            if sbars:
                lv = levels_from_prior_day(sb, d)
                if lv is not None:
                    all_bars.extend(sbars)
                    levels_map[d] = lv
                    print(f"  {d}: {len(sbars)} 5m bars, "
                          f"POC={lv.poc:.0f} VAH={lv.vah:.0f} VAL={lv.val:.0f}")
        d += timedelta(days=1)

    if not levels_map:
        print("No sessions with data + prior-day levels. Check symbol/date range.")
        return

    print(f"\nRunning backtest over {len(levels_map)} sessions...\n")
    res = run_backtest(all_bars, lambda dd: levels_map[dd], oos_fraction=args.oos)
    print(format_report(res))


if __name__ == "__main__":
    main()