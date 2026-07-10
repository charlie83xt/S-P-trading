"""
Backtest harness.

What it measures, per setup tag:
    - signals/day (fired by the detector)
    - signals/day that also pass the strict gate
    - win rate, avg win, avg loss, expectancy (per-trade and per-day)
    - the same, split chronologically into in-sample vs out-of-sample

Fill model (deliberately conservative -- it should not flatter results):
    - entry  = OPEN of the next 5-min bar after the confirming bar
    - stop/target = a bracket; target defaults to TARGET_R x stop distance when
      the setup has no structural target (D, E)
    - walk forward bar by bar; if a single bar's range contains BOTH stop and
      target, count the STOP (pessimistic tie-break)
    - exit at the 11:30 hard-flat close if neither is hit
    - 1 contract throughout, to isolate each setup's edge from sizing

This is a simplified model: no slippage/commission unless you add it, no
partial fills, no intrabar path beyond high/low. Treat results as directional,
not as a P&L promise -- and read the out-of-sample column, not the in-sample one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from statistics import mean
from typing import Callable, Iterable, Optional

from .types import (Bar, Detection, SessionLevels, Side, SimTrade, VwapColor,
                    POINT_VALUE)
from .vwap import VwapEngine
from .classifier import SetupClassifier
from .gate import Gate, SessionRiskState, _structural_stop

TARGET_R = 1.5            # default reward multiple when no structural target
RTH_OPEN = time(9, 30)
HARD_FLAT = time(11, 30)


def true_range(prev_close: Optional[float], bar: Bar) -> float:
    if prev_close is None:
        return bar.rng
    return max(bar.high - bar.low, abs(bar.high - prev_close),
               abs(bar.low - prev_close))


def rolling_atr(bars: list[Bar], idx: int, period: int = 14) -> float:
    start = max(1, idx - period + 1)
    trs = [true_range(bars[j - 1].close, bars[j]) for j in range(start, idx + 1)]
    return mean(trs) if trs else bars[idx].rng


def _simulate(detection: Detection, bars: list[Bar], conf_idx: int,
              stop: float, side: Side) -> Optional[SimTrade]:
    """Bracket sim from the bar AFTER the confirming bar."""
    if conf_idx + 1 >= len(bars):
        return None
    entry_bar = bars[conf_idx + 1]
    entry = entry_bar.open

    if detection.target is not None:
        target = detection.target
    else:
        risk = abs(entry - stop)
        target = entry + TARGET_R * risk if side == Side.LONG else entry - TARGET_R * risk

    # validate geometry
    if side == Side.LONG and not (stop < entry < target):
        return None
    if side == Side.SHORT and not (target < entry < stop):
        return None

    for j in range(conf_idx + 1, len(bars)):
        b = bars[j]
        if b.ts.time() > HARD_FLAT:
            ex = bars[j - 1].close
            pts = (ex - entry) if side == Side.LONG else (entry - ex)
            return SimTrade(detection.tag, side, entry_bar.ts, entry, stop, target,
                            bars[j - 1].ts, ex, pts, pts > 0, "flat_1130")
        hit_stop = b.low <= stop if side == Side.LONG else b.high >= stop
        hit_tgt = b.high >= target if side == Side.LONG else b.low <= target
        if hit_stop and hit_tgt:
            hit_tgt = False  # pessimistic: stop first
        if hit_stop:
            pts = (stop - entry) if side == Side.LONG else (entry - stop)
            return SimTrade(detection.tag, side, entry_bar.ts, entry, stop, target,
                            b.ts, stop, pts, False, "stop")
        if hit_tgt:
            pts = (target - entry) if side == Side.LONG else (entry - target)
            return SimTrade(detection.tag, side, entry_bar.ts, entry, stop, target,
                            b.ts, target, pts, True, "target")
    # ran out of bars
    last = bars[-1]
    pts = (last.close - entry) if side == Side.LONG else (entry - last.close)
    return SimTrade(detection.tag, side, entry_bar.ts, entry, stop, target,
                    last.ts, last.close, pts, pts > 0, "flat_1130")


@dataclass
class TagStats:
    tag: str
    n: int = 0
    wins: int = 0
    win_pts: list[float] = field(default_factory=list)
    loss_pts: list[float] = field(default_factory=list)

    def add(self, t: SimTrade) -> None:
        self.n += 1
        if t.win:
            self.wins += 1
            self.win_pts.append(t.points)
        else:
            self.loss_pts.append(t.points)

    def summary(self, n_days: int) -> dict:
        win_rate = self.wins / self.n if self.n else 0.0
        avg_win = mean(self.win_pts) if self.win_pts else 0.0
        avg_loss = mean(self.loss_pts) if self.loss_pts else 0.0  # negative
        exp_pts = win_rate * avg_win + (1 - win_rate) * avg_loss
        return {
            "tag": self.tag,
            "trades": self.n,
            "win_rate": win_rate,
            "avg_win_usd": avg_win * POINT_VALUE,
            "avg_loss_usd": avg_loss * POINT_VALUE,
            "expectancy_usd_per_trade": exp_pts * POINT_VALUE,
            "expectancy_usd_per_day": exp_pts * POINT_VALUE * (self.n / n_days if n_days else 0),
            "signals_per_day": self.n / n_days if n_days else 0,
        }


def _session_bars(bars: list[Bar]) -> dict:
    sessions: dict = defaultdict(list)
    for b in bars:
        if RTH_OPEN <= b.ts.time():
            sessions[b.ts.date()].append(b)
    return dict(sorted(sessions.items()))


def run_backtest(bars: list[Bar],
                 levels_for: Callable[[object], SessionLevels],
                 *, oos_fraction: float = 0.30,
                 vwap_kwargs: Optional[dict] = None,
                 classifier_kwargs: Optional[dict] = None) -> dict:
    """Run the full pipeline over historical bars.

    `levels_for(session_date)` returns the SessionLevels for that day (your
    pre-session FRVP). Returns a dict with per-tag stats for all / in-sample /
    out-of-sample plus gate-passed signal counts.
    """
    vwap_kwargs = vwap_kwargs or {}
    classifier_kwargs = classifier_kwargs or {}
    sessions = _session_bars(bars)
    session_dates = list(sessions.keys())
    if not session_dates:
        raise ValueError("no RTH bars found")

    split = int(len(session_dates) * (1 - oos_fraction))
    is_dates = set(session_dates[:split])
    oos_dates = set(session_dates[split:])

    fired: dict[str, TagStats] = defaultdict(lambda: TagStats(""))
    fired_is: dict[str, TagStats] = defaultdict(lambda: TagStats(""))
    fired_oos: dict[str, TagStats] = defaultdict(lambda: TagStats(""))
    gated_counts: dict[str, int] = defaultdict(int)
    fired_counts: dict[str, int] = defaultdict(int)
    reject_counts: dict[str, int] = defaultdict(int)
    reject_reasons: dict[str, list[str]] = defaultdict(list)

    for sdate, sbars in sessions.items():
        sbars.sort(key=lambda b: b.ts)
        levels = levels_for(sdate)
        rth_open_price = sbars[0].open
        vwap = VwapEngine(**vwap_kwargs)
        clf = SetupClassifier(levels, rth_open_price, **classifier_kwargs)
        gate = Gate()
        state = SessionRiskState()

        for i, b in enumerate(sbars):
            vwap.update(b)
            v = vwap.value
            color = vwap.color()
            dets = clf.on_bar(b, v, color)
            atr = rolling_atr(sbars, i)
            for d in dets:
                if not d.fired:
                    reject_counts[d.tag] += 1
                    if len(reject_reasons[d.tag]) < 6:
                        reject_reasons[d.tag].append(d.reason)
                    continue
                fired_counts[d.tag] += 1
                # raw edge sim (independent, 1 contract)
                stop, pts = _structural_stop(d, b, atr)
                if pts <= 0 or pts > 60:   # guard absurd geometry in sim
                    continue
                tr = _simulate(d, sbars, i, stop, d.side)
                if tr is None:
                    continue
                for store in (fired, (fired_is if sdate in is_dates else fired_oos)):
                    if store[d.tag].tag == "":
                        store[d.tag] = TagStats(d.tag)
                    store[d.tag].add(tr)
                # gate pass (realistic frequency, updates risk state)
                gd = gate.evaluate(d, b, b.ts, atr, state)
                if gd.allow:
                    gated_counts[d.tag] += 1
                    pnl = tr.points * POINT_VALUE * gd.size
                    state.register_fill(b.ts, pnl, d.level)

    n_all = len(session_dates)
    n_is = len(is_dates)
    n_oos = len(oos_dates)

    def pack(store, ndays):
        return {tag: st.summary(ndays) for tag, st in sorted(store.items())}

    return {
        "sessions": n_all,
        "in_sample_sessions": n_is,
        "out_of_sample_sessions": n_oos,
        "fired_counts": dict(sorted(fired_counts.items())),
        "gated_counts": dict(sorted(gated_counts.items())),
        "reject_counts": dict(sorted(reject_counts.items())),
        "reject_reason_samples": {k: v for k, v in sorted(reject_reasons.items())},
        "all": pack(fired, n_all),
        "in_sample": pack(fired_is, n_is),
        "out_of_sample": pack(fired_oos, n_oos),
    }


def format_report(res: dict) -> str:
    lines = []
    lines.append(f"Sessions: {res['sessions']}  "
                 f"(in-sample {res['in_sample_sessions']} / "
                 f"out-of-sample {res['out_of_sample_sessions']})")
    lines.append("")
    hdr = f"{'tag':<4}{'trades':>7}{'win%':>7}{'avgW$':>8}{'avgL$':>8}{'E$/trade':>10}{'E$/day':>9}{'sig/day':>9}"

    def block(title, table, ndays):
        lines.append(title)
        lines.append(hdr)
        if not table:
            lines.append("  (none)")
        for tag, s in table.items():
            lines.append(f"{s['tag']:<4}{s['trades']:>7}{s['win_rate']*100:>6.0f}%"
                         f"{s['avg_win_usd']:>8.0f}{s['avg_loss_usd']:>8.0f}"
                         f"{s['expectancy_usd_per_trade']:>10.2f}"
                         f"{s['expectancy_usd_per_day']:>9.2f}"
                         f"{s['signals_per_day']:>9.2f}")
        lines.append("")

    block("ALL HISTORY (in-sample inflates this -- do not trust in isolation):",
          res["all"], res["sessions"])
    block("OUT-OF-SAMPLE (this is the column that matters):",
          res["out_of_sample"], res["out_of_sample_sessions"])
    block("IN-SAMPLE (for comparison only):",
          res["in_sample"], res["in_sample_sessions"])

    lines.append("Fired vs gate-passed signals (detector frequency vs tradeable frequency):")
    for tag in sorted(set(res["fired_counts"]) | set(res["gated_counts"])):
        f = res["fired_counts"].get(tag, 0)
        g = res["gated_counts"].get(tag, 0)
        lines.append(f"  {tag}: fired {f}, passed gate {g}")
    lines.append("")
    lines.append("Sample-size note: any tag with < ~30 out-of-sample trades is "
                 "noise, not an edge. Per your own Part 15, prove one setup at a "
                 "time before trusting it.")
    return "\n".join(lines) 
