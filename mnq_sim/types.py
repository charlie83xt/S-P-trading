"""
Core data types for the MNQ sim/backtest tool.

Strategy-logic only. No broker, no credentials, no order execution.
Everything here is plain stdlib so it drops into an existing project cleanly.

MNQ contract facts used downstream:
    point value = $2.00 / point
    tick size   = 0.25
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional

POINT_VALUE = 2.0      # USD per MNQ point
TICK = 0.25            # MNQ tick size


def round_tick(price: float) -> float:
    """Round a price to the nearest MNQ tick (0.25)."""
    return round(price / TICK) * TICK


class OpenLocation(str, Enum):
    """Where price opened relative to the prior-session value area.

    Part 4 of the strategy maps this to which setups are even allowed.
    """
    ABOVE_VAH = "above_vah"
    BELOW_VAL = "below_val"
    INSIDE_VA = "inside_va"
    AT_PDH = "at_pdh"
    AT_PDL = "at_pdl"


class VwapColor(str, Enum):
    """VWAP direction filter (Part 2). Modeled from VWAP slope.

    GREEN  -> longs only
    RED    -> shorts only
    WHITE  -> no trade (flat / undecided)
    """
    GREEN = "green"
    RED = "red"
    WHITE = "white"


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Bar:
    """A single OHLCV bar. ts must be timezone-aware (ET expected)."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    minutes: int = 5  # bar interval in minutes

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("Bar.ts must be timezone-aware (use ET)")

    @property
    def rng(self) -> float:
        return self.high - self.low

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def is_up(self) -> bool:
        return self.close >= self.open

    @property
    def typical(self) -> float:
        """Typical price (HLC/3) used for VWAP accumulation."""
        return (self.high + self.low + self.close) / 3.0

    def upper_wick(self) -> float:
        return self.high - self.body_high

    def lower_wick(self) -> float:
        return self.body_low - self.low


@dataclass
class SessionLevels:
    """Pre-session FRVP levels (Part 3), drawn from the prior ETH session.

    In the real bot these are computed pre-9:20 and passed in. Open location
    is derived from the RTH open vs these levels (or supplied explicitly).
    """
    session_date: date
    vah: float
    poc: float
    val: float
    pdh: float
    pdl: float
    lvns: list[float] = field(default_factory=list)
    open_location: Optional[OpenLocation] = None

    def classify_open(self, rth_open: float, pdh_tol: float = 1.0,
                      pdl_tol: float = 1.0) -> OpenLocation:
        """Derive open location from the first RTH price if not supplied."""
        if self.open_location is not None:
            return self.open_location
        if abs(rth_open - self.pdh) <= pdh_tol:
            loc = OpenLocation.AT_PDH
        elif abs(rth_open - self.pdl) <= pdl_tol:
            loc = OpenLocation.AT_PDL
        elif rth_open > self.vah:
            loc = OpenLocation.ABOVE_VAH
        elif rth_open < self.val:
            loc = OpenLocation.BELOW_VAL
        else:
            loc = OpenLocation.INSIDE_VA
        self.open_location = loc
        return loc


@dataclass
class Detection:
    """One setup evaluation on one bar.

    The DETECTOR emits one of these for every setup it looked at, whether or
    not it fired, with a human-readable reason. This is the 'fat detector':
    we log everything so the backtest has data, including rejects.
    """
    ts: datetime
    tag: str                 # 'A'..'G'
    fired: bool
    reason: str
    side: Optional[Side] = None
    entry_ref: Optional[float] = None   # price the confirming bar closed at
    target: Optional[float] = None
    level: Optional[float] = None       # structural level involved (for first-touch)
    vwap: Optional[float] = None
    vwap_color: Optional[VwapColor] = None


@dataclass
class GateDecision:
    """Whether a fired detection would actually be tradeable, per Parts 6-10.

    The GATE is strict and unchanged from the document. A detection can fire
    and still be gated out — that is the normal, healthy case.
    """
    allow: bool
    reason: str
    size: int = 0
    stop: Optional[float] = None
    stop_points: Optional[float] = None


@dataclass
class SimTrade:
    """A simulated fill result for one allowed signal (1 contract by default)."""
    tag: str
    side: Side
    entry_ts: datetime
    entry: float
    stop: float
    target: float
    exit_ts: datetime
    exit: float
    points: float            # signed, in MNQ points (1 contract)
    win: bool
    reason_exit: str         # 'target' | 'stop' | 'flat_1130' 
