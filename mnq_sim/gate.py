"""
The gate -- strict, and unchanged from the document (Parts 6-10).

A fired detection is only a *candidate*. The gate decides whether it would
actually be tradeable: entry window, sizing, structural stop / 30-point skip,
2-loss off, $400 daily stop, profit lock, cooldowns, and the first-touch
guardrail. This is the half that protects the account; it is intentionally
NOT loosened to raise frequency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .types import (Bar, Detection, GateDecision, Side, VwapColor, round_tick)


@dataclass
class SessionRiskState:
    """Mutable per-session risk bookkeeping the gate reads and updates."""
    realized_pnl: float = 0.0           # USD, realized this session
    consecutive_losses: int = 0
    trades_taken: int = 0
    last_trade_ts: Optional[datetime] = None
    locked: bool = False                # set once a hard stop/lock trips
    lock_reason: str = ""
    levels_traded: list[float] = field(default_factory=list)  # first-touch guard

    def register_fill(self, ts: datetime, pnl_usd: float, level: Optional[float]) -> None:
        self.realized_pnl += pnl_usd
        self.trades_taken += 1
        self.last_trade_ts = ts
        if pnl_usd < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if level is not None:
            self.levels_traded.append(level)


# --- fixed gate parameters from the document --------------------------------
ENTRY_OPEN = (9, 45)      # earliest entry
A_EARLIEST = (10, 0)      # Setup A earliest entry
LAST_ENTRY = (11, 0)      # last entry
MAX_STOP_POINTS = 30.0
DAILY_LOSS_USD = 400.0
COOLDOWN_MIN = 10
PROFIT_LOCK_EARLY_USD = 300.0
PROFIT_LOCK_EARLY_CUTOFF = (10, 30)
PROFIT_LOCK_HARD_USD = 500.0
POINT_VALUE = 2.0


def _hm(now: datetime) -> tuple[int, int]:
    return (now.hour, now.minute)


def _structural_stop(detection: Detection, bar: Bar, atr5: float
                     ) -> tuple[float, float]:
    """Return (stop_price, stop_points). Closer of structural vs 1.5xATR."""
    entry = detection.entry_ref if detection.entry_ref is not None else bar.close
    if detection.side == Side.LONG:
        structural = bar.low - 2.5            # ~2-3 pts beyond the wick
        atr_stop = entry - 1.5 * atr5
        stop = max(structural, atr_stop)      # closer to entry = higher price
        pts = entry - stop
    else:
        structural = bar.high + 2.5
        atr_stop = entry + 1.5 * atr5
        stop = min(structural, atr_stop)      # closer = lower price
        pts = stop - entry
    return round_tick(stop), pts


class Gate:
    def __init__(self, trend_conflicts_vwap: bool = False,
                 first_touch_tol: float = 1.5):
        self.trend_conflicts = trend_conflicts_vwap
        self.first_touch_tol = first_touch_tol

    def _size(self, detection: Detection, now: datetime) -> int:
        hm = _hm(now)
        base = 1 if hm < A_EARLIEST else 3
        size = base
        if detection.tag == "A":
            size = 1                               # A starts at 1, scales after POC
        if detection.vwap_color is not None and detection.side is not None:
            counter_vwap = (
                (detection.side == Side.LONG and detection.vwap_color == VwapColor.RED) or
                (detection.side == Side.SHORT and detection.vwap_color == VwapColor.GREEN))
            if counter_vwap:
                # counter-VWAP allowed in B only, 1 contract
                size = 1 if detection.tag == "B" else 0
        if self.trend_conflicts:
            size = min(size, 1)
        return size

    def evaluate(self, detection: Detection, bar: Bar, now: datetime,
                 atr5: float, state: SessionRiskState) -> GateDecision:
        if not detection.fired:
            return GateDecision(False, "detection did not fire")

        # --- hard locks first ---
        if state.locked:
            return GateDecision(False, f"session locked: {state.lock_reason}")
        if state.consecutive_losses >= 2:
            state.locked = True
            state.lock_reason = "2 losses -> platform off"
            return GateDecision(False, state.lock_reason)
        if state.realized_pnl <= -DAILY_LOSS_USD:
            state.locked = True
            state.lock_reason = "$400 daily loss reached"
            return GateDecision(False, state.lock_reason)
        hm = _hm(now)
        if state.realized_pnl >= PROFIT_LOCK_HARD_USD:
            state.locked = True
            state.lock_reason = "+$500 profit lock"
            return GateDecision(False, state.lock_reason)
        if (state.realized_pnl >= PROFIT_LOCK_EARLY_USD
                and hm < PROFIT_LOCK_EARLY_CUTOFF):
            state.locked = True
            state.lock_reason = "+$300 before 10:30 profit lock"
            return GateDecision(False, state.lock_reason)

        # --- entry window ---
        if hm < ENTRY_OPEN:
            return GateDecision(False, "before 9:45 entry window")
        if hm > LAST_ENTRY:
            return GateDecision(False, "after 11:00 last-entry cutoff")
        if detection.tag == "A" and hm < A_EARLIEST:
            return GateDecision(False, "Setup A not allowed before 10:00")

        # --- cooldowns ---
        if state.last_trade_ts is not None:
            mins = (now - state.last_trade_ts).total_seconds() / 60.0
            if mins < COOLDOWN_MIN:
                return GateDecision(False, f"10-min cooldown ({mins:.0f}m since last)")
        # loss before 10:00 -> wait until 10:00 AND a 10-min cooldown
        if (state.consecutive_losses >= 1 and state.last_trade_ts is not None
                and state.last_trade_ts.hour < 10 and hm < A_EARLIEST):
            return GateDecision(False, "loss before 10:00 -> wait until 10:00 + cooldown")

        # --- first-touch guardrail (Part 10) ---
        if detection.level is not None:
            for lv in state.levels_traded:
                if abs(lv - detection.level) <= self.first_touch_tol:
                    return GateDecision(False, "level already traded today (first-touch decay; not re-running a stale level)")

        # --- sizing ---
        size = self._size(detection, now)
        if size <= 0:
            return GateDecision(False, "sizing -> 0 (counter-VWAP outside B, or trend conflict)")

        # --- stop / 30-point skip ---
        stop, pts = _structural_stop(detection, bar, atr5)
        if pts > MAX_STOP_POINTS:
            return GateDecision(False, f"required stop {pts:.1f}pt > 30pt -> skip", size=0,
                                stop=stop, stop_points=pts)
        if pts <= 0:
            return GateDecision(False, "non-positive stop distance (bad geometry)")

        return GateDecision(True, "all gates passed", size=size, stop=stop, stop_points=pts) 
