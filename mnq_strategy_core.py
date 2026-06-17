import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
log = logging.getLogger("mnq_strategy")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────


TICK_SIZE         = 0.25
DOLLARS_PER_POINT = 2.0
MAX_STOP_PTS      = 30.0
MAX_DAILY_LOSS    = 400.0
PROFIT_LOCK_EARLY = 300.0
PROFIT_LOCK_ANY   = 500.0
MAX_LOSSES        = 2
COOLDOWN_MINUTES  = 10
ENTRY_START       = (9, 45)
LAST_ENTRY        = (11, 0)
FORCE_FLAT_TIME   = (15, 55)
NEWS_BLOCK_START  = (9, 50)
NEWS_BLOCK_END    = (10, 10)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────


def now_et() -> datetime:
    return datetime.now(ET)

def round_tick(price: float) -> float:
    return round(round(price / TICK_SIZE) * TICK_SIZE, 2)

def pts_to_dollars(pts: float, size: int) -> float:
    return round(pts * DOLLARS_PER_POINT * size, 2)

def dt_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=ET)

def time_at_or_after(hm: tuple[int, int], ts: float) -> bool:
    t = dt_from_ts(ts)
    return (t.hour > hm[0]) or (t.hour == hm[0] and t.minute >= hm[1])

def time_before(hm: tuple[int, int], ts: float) -> bool:
    t = dt_from_ts(ts)
    return (t.hour < hm[0]) or (t.hour == hm[0] and t.minute < hm[1])

def in_time_window(start: tuple[int, int], end: tuple[int, int], ts: float) -> bool:
    return time_at_or_after(start, ts) and time_before(end, ts)

def body_high(bar: dict) -> float:
    return max(bar["o"], bar["c"])

def body_low(bar: dict) -> float:
    return min(bar["o"], bar["c"])

def candle_range(bar: dict) -> float:
    return max(0.0, bar["h"] - bar["l"])

def bar_mid(bar: dict) -> float:
    return (bar["h"] + bar["l"]) / 2.0

def points_between(a: float, b: float) -> float:
    return abs(a - b)

def rejection(module: str, reason: str):
    log.info(f"{module}: blocked — {reason}")


# ─────────────────────────────────────────────
# ENUMS & DATA
# ─────────────────────────────────────────────

class Direction(Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class VwapColor(Enum):
    GREEN = "green"
    RED = "red"
    WHITE = "white"



class SetupType(Enum):
    A = "SETUP_A"
    B = "SETUP_B"
    C = "SETUP_C"



class OpenLocation(Enum):
    ABOVE_VAH = "above_vah"
    BELOW_VAL = "below_val"
    INSIDE_VA = "inside_va"
    AT_PDH = "at_pdh"
    AT_PDL = "at_pdl"
    OTHER = "other"


@dataclass
class Signal:
    setup: SetupType
    direction: Direction
    entry: float
    stop: float
    size: int
    reason: str
    profile_target_1: Optional[float] = None
    profile_target_2: Optional[float] = None
    counter_vwap: bool = False
    conflict_240: bool = False


@dataclass
class SessionState:
    date: str = field(default_factory=lambda: now_et().date().isoformat())
    daily_pnl: float = 0.0
    losses: int = 0
    locked: bool = False
    last_trade_exit_ts: Optional[float] = None
    cooldown_until_ts: Optional[float] = None


    def reset(self):
        self.date = now_et().date().isoformat()
        self.daily_pnl = 0.0
        self.losses = 0
        self.locked = False
        self.last_trade_exit_ts = None
        self.cooldown_until_ts = None


@dataclass
class ProfileSnapshot:
    vah: float
    poc: float
    val: float
    pdh: float
    pdl: float
    lvns: List[float]
    open_price: float


    @property
    def mid(self) -> float:
        return (self.vah + self.val) / 2.0


    @property
    def middle_50_upper(self) -> float:
        return self.mid + (self.vah - self.val) / 4.0


    @property
    def middle_50_lower(self) -> float:
        return self.mid - (self.vah - self.val) / 4.0



@dataclass
class SetupDecision:
    setup: Optional[SetupType]
    direction: Direction
    reason: str
    counter_vwap: bool = False
    conflict_240: bool = False
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    scale_allowed: bool = False



# ─────────────────────────────────────────────
# MODULE 1 — SESSION RISK GOVERNOR
# ─────────────────────────────────────────────

class SessionRiskGovernor:
    def __init__(self, news_times: List[datetime]):
        self.news_times = news_times
        self.state = SessionState()


    def new_session(self, news_times: List[datetime]):
        self.state.reset()
        self.news_times = news_times


    def _ensure_session(self):
        today = now_et().date().isoformat()
        if self.state.date != today:
            self.state.reset()


    def _in_news_window(self, ts: float) -> bool:
        t = dt_from_ts(ts)
        for news_dt in self.news_times:
            block_start = news_dt - timedelta(minutes=10)
            block_end = news_dt + timedelta(minutes=10)
            if block_start <= t <= block_end:
                return True
        return False


    def can_enter(self, ts: float) -> bool:
        self._ensure_session()


        if self.state.locked:
            rejection("SessionRiskGovernor", "session locked")
            return False


        if time_before(ENTRY_START, ts):
            rejection("SessionRiskGovernor", "before 9:45 ET")
            return False


        if not time_before(LAST_ENTRY, ts):
            rejection("SessionRiskGovernor", "after 11:00 ET, no new entries")
            return False


        if self._in_news_window(ts):
            rejection("SessionRiskGovernor", "news window active")
            return False


        if self.state.losses >= MAX_LOSSES:
            self.state.locked = True
            rejection("SessionRiskGovernor", "2 losses hit")
            return False


        if self.state.daily_pnl <= -MAX_DAILY_LOSS:
            self.state.locked = True
            rejection("SessionRiskGovernor", "daily loss limit hit")
            return False


        t = dt_from_ts(ts)
        if self.state.daily_pnl >= PROFIT_LOCK_EARLY and (t.hour < 10 or (t.hour == 10 and t.minute < 30)):
            self.state.locked = True
            rejection("SessionRiskGovernor", "$300 profit before 10:30 lock hit")
            return False


        if self.state.daily_pnl >= PROFIT_LOCK_ANY:
            self.state.locked = True
            rejection("SessionRiskGovernor", "$500 profit lock hit")
            return False


        if self.state.cooldown_until_ts and ts < self.state.cooldown_until_ts:
            rejection("SessionRiskGovernor", "cooldown active")
            return False


        return True


    def must_flatten(self, ts: float) -> bool:
        return not time_before(FORCE_FLAT_TIME, ts)


    def record_trade_result(self, pnl_usd: float, exit_ts: float):
        self._ensure_session()
        self.state.daily_pnl += pnl_usd
        self.state.last_trade_exit_ts = exit_ts
        self.state.cooldown_until_ts = exit_ts + COOLDOWN_MINUTES * 60
        if pnl_usd < 0:
            self.state.losses += 1
            if self.state.losses >= MAX_LOSSES:
                self.state.locked = True
        if self.state.daily_pnl <= -MAX_DAILY_LOSS:
            self.state.locked = True



# ─────────────────────────────────────────────
# MODULE 2 — PROFILE LEVELS
# ─────────────────────────────────────────────


class ProfileLevels:
    LVN_TOLERANCE = 1.0
    POC_BUFFER = 5.0


    def __init__(self, snapshot: ProfileSnapshot):
        self.snapshot = snapshot
        self.open_location = self._classify_open(snapshot.open_price)


    def _classify_open(self, price: float) -> OpenLocation:
        if abs(price - self.snapshot.pdh) <= 1.0:
            return OpenLocation.AT_PDH
        if abs(price - self.snapshot.pdl) <= 1.0:
            return OpenLocation.AT_PDL
        if price > self.snapshot.vah:
            return OpenLocation.ABOVE_VAH
        if price < self.snapshot.val:
            return OpenLocation.BELOW_VAL
        if self.snapshot.val <= price <= self.snapshot.vah:
            return OpenLocation.INSIDE_VA
        return OpenLocation.OTHER


    def in_middle_of_va(self, price: float) -> bool:
        return self.snapshot.middle_50_lower <= price <= self.snapshot.middle_50_upper


    def near_poc(self, price: float) -> bool:
        return points_between(price, self.snapshot.poc) <= self.POC_BUFFER


    def on_lvn(self, price: float) -> bool:
        return any(points_between(price, x) <= self.LVN_TOLERANCE for x in self.snapshot.lvns)


    def no_trade_zone(self, price: float) -> bool:
        if self.open_location == OpenLocation.INSIDE_VA and self.in_middle_of_va(price):
            rejection("ProfileLevels", "price in middle of VA")
            return True
        if self.near_poc(price):
            rejection("ProfileLevels", "within 5 pts of POC")
            return True
        if self.on_lvn(price):
            rejection("ProfileLevels", "price at LVN")
            return True
        return False



# ─────────────────────────────────────────────
# MODULE 3 — VWAP TREND FILTER
# ─────────────────────────────────────────────

class VWAPTrendFilter:
    def __init__(self):
        self.bars_5m: List[dict] = []
        self._vwap_history: List[float] = []
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self.swing_low_240: Optional[float] = None
        self.swing_high_240: Optional[float] = None


    def reset(self):
        self.bars_5m = []
        self._vwap_history = []
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self.swing_low_240 = None
        self.swing_high_240 = None


    def update_5m(self, bar: dict) -> float:
        self.bars_5m.append(bar)
        typical = (bar["h"] + bar["l"] + bar["c"]) / 3
        vol = max(bar["v"], 1)
        self._cum_pv += typical * vol
        self._cum_vol += vol
        vwap = self._cum_pv / self._cum_vol
        self._vwap_history.append(vwap)
        return vwap


    def set_240_trend_levels(self, swing_low: float, swing_high: float):
        self.swing_low_240 = swing_low
        self.swing_high_240 = swing_high


    @property
    def vwap(self) -> float:
        return self._vwap_history[-1] if self._vwap_history else 0.0


    def color(self) -> VwapColor:
        if len(self._vwap_history) < 4:
            rejection("VWAPTrendFilter", "insufficient VWAP history")
            return VwapColor.WHITE
        delta = self._vwap_history[-1] - self._vwap_history[-4]
        if delta >= 2.0:
            return VwapColor.GREEN
        if delta <= -2.0:
            return VwapColor.RED
        rejection("VWAPTrendFilter", "VWAP white, no direction")
        return VwapColor.WHITE


    def trend_240(self, price: float) -> Direction:
        if self.swing_low_240 is None or self.swing_high_240 is None:
            return Direction.NONE
        if price > self.swing_low_240:
            return Direction.LONG
        if price < self.swing_high_240:
            return Direction.SHORT
        return Direction.NONE


    def conflict_flag(self, price: float) -> bool:
        color = self.color()
        trend = self.trend_240(price)
        if color == VwapColor.GREEN and trend == Direction.SHORT:
            return True
        if color == VwapColor.RED and trend == Direction.LONG:
            return True
        return False



# ─────────────────────────────────────────────
# MODULE 4 — SETUP CLASSIFIER
# ─────────────────────────────────────────────

class SetupClassifier:
    LEVEL_TOL = 2.0


    def __init__(self, profile: ProfileLevels, vwap_filter: VWAPTrendFilter):
        self.profile = profile
        self.vwap_filter = vwap_filter
        self.bars_5m: List[dict] = []
        self.bars_15m: List[dict] = []


    def reset(self):
        self.bars_5m = []
        self.bars_15m = []


    def add_5m_bar(self, bar: dict):
        self.bars_5m.append(bar)
        if len(self.bars_5m) % 3 == 0:
            chunk = self.bars_5m[-3:]
            agg = {
                "o": chunk[0]["o"],
                "h": max(x["h"] for x in chunk),
                "l": min(x["l"] for x in chunk),
                "c": chunk[-1]["c"],
                "v": sum(x["v"] for x in chunk),
                "ts": chunk[-1]["ts"],
            }
            self.bars_15m.append(agg)


    def _wick_pct(self, bar: dict, direction: Direction) -> float:
        rng = candle_range(bar)
        if rng == 0:
            return 0.0
        if direction == Direction.SHORT:
            return (bar["h"] - body_high(bar)) / rng
        return (body_low(bar) - bar["l"]) / rng


    def _inside_value_body(self, bar: dict) -> bool:
        return body_low(bar) >= self.profile.snapshot.val and body_high(bar) <= self.profile.snapshot.vah


    def _setup_a(self, ts: float) -> Optional[SetupDecision]:
        if len(self.bars_15m) < 2:
            return None
        if time_before((10, 0), ts):
            rejection("SetupClassifier", "Setup A before 10:00 ET")
            return None
        if self.profile.open_location not in (OpenLocation.ABOVE_VAH, OpenLocation.BELOW_VAL):
            return None


        last2 = self.bars_15m[-2:]
        if not all(self._inside_value_body(b) for b in last2):
            return None


        color = self.vwap_filter.color()
        if self.profile.open_location == OpenLocation.ABOVE_VAH and color != VwapColor.RED:
            rejection("SetupClassifier", "Setup A needs red VWAP from above VAH")
            return None
        if self.profile.open_location == OpenLocation.BELOW_VAL and color != VwapColor.GREEN:
            rejection("SetupClassifier", "Setup A needs green VWAP from below VAL")
            return None


        direction = Direction.SHORT if self.profile.open_location == OpenLocation.ABOVE_VAH else Direction.LONG
        return SetupDecision(
            setup=SetupType.A,
            direction=direction,
            reason="80% rule confirmed",
            target_1=self.profile.snapshot.poc,
            target_2=self.profile.snapshot.val if direction == Direction.SHORT else self.profile.snapshot.vah,
            scale_allowed=True,
            conflict_240=self.vwap_filter.conflict_flag(self.bars_5m[-1]["c"]),
        )


    def _setup_b(self) -> Optional[SetupDecision]:
        if not self.bars_5m:
            return None
        bar = self.bars_5m[-1]
        color = self.vwap_filter.color()


        at_vah = abs(bar["h"] - self.profile.snapshot.vah) <= self.LEVEL_TOL
        at_val = abs(bar["l"] - self.profile.snapshot.val) <= self.LEVEL_TOL


        if at_vah and self._wick_pct(bar, Direction.SHORT) >= 0.50 and body_high(bar) <= self.profile.snapshot.vah:
            if color == VwapColor.RED:
                return SetupDecision(
                    setup=SetupType.B,
                    direction=Direction.SHORT,
                    reason="VAH rejection confirmed",
                    target_1=self.profile.snapshot.poc,
                    counter_vwap=False,
                    conflict_240=self.vwap_filter.conflict_flag(bar["c"]),
                )
            if color == VwapColor.GREEN:
                return SetupDecision(
                    setup=SetupType.B,
                    direction=Direction.SHORT,
                    reason="VAH rejection counter-VWAP A+",
                    target_1=self.profile.snapshot.poc,
                    counter_vwap=True,
                    conflict_240=True,
                )


        if at_val and self._wick_pct(bar, Direction.LONG) >= 0.50 and body_low(bar) >= self.profile.snapshot.val:
            if color == VwapColor.GREEN:
                return SetupDecision(
                    setup=SetupType.B,
                    direction=Direction.LONG,
                    reason="VAL rejection confirmed",
                    target_1=self.profile.snapshot.poc,
                    counter_vwap=False,
                    conflict_240=self.vwap_filter.conflict_flag(bar["c"]),
                )
            if color == VwapColor.RED:
                return SetupDecision(
                    setup=SetupType.B,
                    direction=Direction.LONG,
                    reason="VAL rejection counter-VWAP A+",
                    target_1=self.profile.snapshot.poc,
                    counter_vwap=True,
                    conflict_240=True,
                )
        return None


    def _setup_c(self) -> Optional[SetupDecision]:
        if len(self.bars_5m) < 2:
            return None


        prev = self.bars_5m[-2]
        bar = self.bars_5m[-1]
        color = self.vwap_filter.color()


        broke_pdh = prev["c"] > self.profile.snapshot.pdh + 2.0
        retest_pdh = bar["l"] <= self.profile.snapshot.pdh + self.LEVEL_TOL
        body_above_pdh = body_low(bar) > self.profile.snapshot.pdh


        if broke_pdh and retest_pdh and body_above_pdh and color == VwapColor.GREEN:
            return SetupDecision(
                setup=SetupType.C,
                direction=Direction.LONG,
                reason="PDH break-retest confirmed",
                target_1=self.profile.snapshot.poc,
                target_2=self.profile.snapshot.vah,
                conflict_240=self.vwap_filter.conflict_flag(bar["c"]),
            )


        broke_pdl = prev["c"] < self.profile.snapshot.pdl - 2.0
        retest_pdl = bar["h"] >= self.profile.snapshot.pdl - self.LEVEL_TOL
        body_below_pdl = body_high(bar) < self.profile.snapshot.pdl


        if broke_pdl and retest_pdl and body_below_pdl and color == VwapColor.RED:
            return SetupDecision(
                setup=SetupType.C,
                direction=Direction.SHORT,
                reason="PDL break-retest confirmed",
                target_1=self.profile.snapshot.poc,
                target_2=self.profile.snapshot.val,
                conflict_240=self.vwap_filter.conflict_flag(bar["c"]),
            )
        return None


    def calc_20_80(self, session_low: float, session_high: float) -> tuple[float, float]:
        rng = session_high - session_low
        level_80 = session_low + 0.80 * rng
        level_20 = session_low + 0.20 * rng
        return round_tick(level_20), round_tick(level_80)


    def valid_20_80(self, level: float) -> bool:
        if points_between(level, self.vwap_filter.vwap) < 5.0:
            rejection("SetupClassifier", "20/80 level too close to VWAP")
            return False
        return True


    def classify(self, ts: float, session_low: float, session_high: float) -> Optional[SetupDecision]:
        a = self._setup_a(ts)
        if a:
            return a


        b = self._setup_b()
        if b:
            return b


        c = self._setup_c()
        if c:
            return c


        rejection("SetupClassifier", "no setup identified")
        return None



# ────────────────────────────────────────────
# MODULE 5 — SIZING ENGINE
# ─────────────────────────────────────────────

class SizingEngine:
    def size(self, setup: SetupDecision, stop_pts: float, ts: float) -> int:
        if stop_pts > MAX_STOP_PTS:
            rejection("SizingEngine", f"stop {stop_pts:.2f} pts exceeds max")
            return 0


        base = 1 if time_before((10, 0), ts) else 3


        if setup.setup == SetupType.A:
            return 1
        if setup.counter_vwap:
            return 1
        if setup.conflict_240:
            return 1
        return base



# ─────────────────────────────────────────────
# MODULE 6 — ENTRY TRIGGER
# ─────────────────────────────────────────────

class EntryTrigger:
    def __init__(self, profile: ProfileLevels):
        self.profile = profile
        self.atr_5m: Optional[float] = None


    def set_atr(self, atr_5m: float):
        self.atr_5m = atr_5m


    def compute_stop(self, setup: SetupDecision, confirm_bar: dict) -> Optional[float]:
        structural = None
        if setup.direction == Direction.LONG:
            outside_va = self.profile.snapshot.val - 2.0
            wick_stop = confirm_bar["l"] - 2.5
            structural = min(outside_va, wick_stop)
            atr_stop = confirm_bar["c"] - (1.5 * self.atr_5m if self.atr_5m else 999)
            stop = max(structural, atr_stop)
        else:
            outside_va = self.profile.snapshot.vah + 2.0
            wick_stop = confirm_bar["h"] + 2.5
            structural = max(outside_va, wick_stop)
            atr_stop = confirm_bar["c"] + (1.5 * self.atr_5m if self.atr_5m else 999)
            stop = min(structural, atr_stop)
        return round_tick(stop)


    def trigger(self, setup: SetupDecision, confirm_bar: dict, next_bar_open: float, size: int) -> Optional[Signal]:
        entry = round_tick(next_bar_open)
        stop = self.compute_stop(setup, confirm_bar)
        stop_pts = abs(entry - stop)
        if stop_pts > MAX_STOP_PTS:
            rejection("EntryTrigger", f"stop {stop_pts:.2f} pts exceeds max")
            return None
        return Signal(
            setup=setup.setup,
            direction=setup.direction,
            entry=entry,
            stop=stop,
            size=size,
            reason=setup.reason,
            profile_target_1=setup.target_1,
            profile_target_2=setup.target_2,
            counter_vwap=setup.counter_vwap,
            conflict_240=setup.conflict_240,
        )



# ─────────────────────────────────────────────
# MODULE 7 — TRADE MANAGER
# ─────────────────────────────────────────────

class TradeManager:
    def __init__(self):
        self.signal: Optional[Signal] = None
        self.stop: float = 0.0
        self.best: float = 0.0
        self.next_profile_hit = False
        self.poc_hit = False


    @property
    def in_trade(self) -> bool:
        return self.signal is not None


    def reset(self):
        self.signal = None
        self.stop = 0.0
        self.best = 0.0
        self.next_profile_hit = False
        self.poc_hit = False


    def open(self, signal: Signal):
        self.signal = signal
        self.stop = signal.stop
        self.best = signal.entry
        self.next_profile_hit = False
        self.poc_hit = False
        log.info(f"TradeManager: open {signal.setup.value} {signal.direction.value} @ {signal.entry} stop={signal.stop}")


    def update_trail(self, price: float) -> Optional[float]:
        if not self.signal:
            return None


        is_long = self.signal.direction == Direction.LONG
        improved = price > self.best if is_long else price < self.best
        if improved:
            self.best = price


        trail = 10.0
        if self.poc_hit:
            trail = 5.0
        if self.next_profile_hit:
            trail = 3.0


        new_stop = round_tick(self.best - trail if is_long else self.best + trail)
        if (is_long and new_stop > self.stop) or (not is_long and new_stop < self.stop):
            self.stop = new_stop
            return new_stop
        return None


    def mark_poc_hit(self):
        self.poc_hit = True


    def mark_next_profile_hit(self):
        self.next_profile_hit = True


    def stop_hit(self, price: float) -> bool:
        if not self.signal:
            return False
        if self.signal.direction == Direction.LONG:
            return price <= self.stop
        return price >= self.stop


    def close(self, exit_price: float) -> dict:
        sig = self.signal
        pts = (exit_price - sig.entry) * (1 if sig.direction == Direction.LONG else -1)
        result = {
            "setup": sig.setup.value,
            "direction": sig.direction.value,
            "entry": sig.entry,
            "exit": round_tick(exit_price),
            "pts": round(pts, 2),
            "pnl_usd": pts_to_dollars(pts, sig.size),
        }
        self.reset()
        return result



# ─────────────────────────────────────────────
# STRATEGY ORCHESTRATOR
# ─────────────────────────────────────────────

class MNQStrategySuite:
    """
    Strategy logic only.


    Execution-layer note:
    - Trailing updates, hard-flat checks, and stop-hit checks must run on every tick via
      on_price_update(price, ts) and broker/execution logic, not only on completed 5-minute bars.
    - on_new_5m_bar() handles signal generation only.
    - Signal generation and trade management are two separate loops.
    All external inputs are passed in at session start:
    - VAH, POC, VAL, PDH, PDL, LVNs
    - news times
    - 240-min swing low/high
    No credentials or broker execution layer included.
    """
    def __init__(
        self,
        profile_snapshot: ProfileSnapshot,
        news_times: List[datetime],
        swing_low_240: Optional[float] = None,
        swing_high_240: Optional[float] = None,
    ):
        self.governor = SessionRiskGovernor(news_times)
        self.profile = ProfileLevels(profile_snapshot)
        self.vwap_filter = VWAPTrendFilter()
        if swing_low_240 is not None and swing_high_240 is not None:
            self.vwap_filter.set_240_trend_levels(swing_low_240, swing_high_240)
        self.classifier = SetupClassifier(self.profile, self.vwap_filter)
        self.sizing = SizingEngine()
        self.entry = EntryTrigger(self.profile)
        self.trade = TradeManager()
        self.bars_5m: List[dict] = []
        self.pending_decision: Optional[SetupDecision] = None


    def new_session(
        self,
        profile_snapshot: ProfileSnapshot,
        news_times: List[datetime],
        swing_low_240: Optional[float] = None,
        swing_high_240: Optional[float] = None,
    ):
        self.governor.new_session(news_times)
        self.profile = ProfileLevels(profile_snapshot)
        self.vwap_filter.reset()
        if swing_low_240 is not None and swing_high_240 is not None:
            self.vwap_filter.set_240_trend_levels(swing_low_240, swing_high_240)
        self.classifier = SetupClassifier(self.profile, self.vwap_filter)
        self.entry = EntryTrigger(self.profile)
        self.trade.reset()
        self.bars_5m = []
        self.pending_decision = None


    def set_atr_5m(self, atr_5m: float):
        self.entry.set_atr(atr_5m)


    def on_new_5m_bar(self, bar: dict, next_bar_open: Optional[float] = None) -> Optional[Signal]:
        ts = bar["ts"]
        px = bar["c"]


        self.bars_5m.append(bar)
        self.vwap_filter.update_5m(bar)
        self.classifier.add_5m_bar(bar)


        if self.trade.in_trade:
            return None


        if self.governor.must_flatten(ts):
            rejection("SessionRiskGovernor", "hard flat 15:55 ET")
            return None


        if not self.governor.can_enter(ts):
            return None


        if self.profile.no_trade_zone(px):
            return None


        session_low = min(x["l"] for x in self.bars_5m)
        session_high = max(x["h"] for x in self.bars_5m)


        decision = self.classifier.classify(ts, session_low, session_high)
        if not decision:
            return None


        stop = self.entry.compute_stop(decision, bar)
        stop_pts = abs(round_tick((next_bar_open if next_bar_open is not None else bar["c"])) - stop)
        size = self.sizing.size(decision, stop_pts, ts)
        if size <= 0:
            return None


        if next_bar_open is None:
            rejection("EntryTrigger", "next bar open not provided")
            return None


        signal = self.entry.trigger(decision, bar, next_bar_open, size)
        if signal is None:
            return None


        log.info(f"MNQStrategySuite: signal {signal.setup.value} {signal.direction.value} entry={signal.entry} stop={signal.stop} size={signal.size}")
        return signal


    def on_price_update(self, price: float, ts: float):
        if not self.trade.in_trade:
            return None


        moved_stop = self.trade.update_trail(price)


        if self.governor.must_flatten(ts):
            result = self.trade.close(price)
            self.governor.record_trade_result(result["pnl_usd"], ts)
            log.info(f"MNQStrategySuite: hard flat close pnl=${result['pnl_usd']:.2f}")
            return {"event": "hard_flat", "result": result, "new_stop": moved_stop}


        if self.trade.stop_hit(price):
            result = self.trade.close(price)
            self.governor.record_trade_result(result["pnl_usd"], ts)
            log.info(f"MNQStrategySuite: stop hit pnl=${result['pnl_usd']:.2f}")
            return {"event": "stop_hit", "result": result, "new_stop": moved_stop}


        if moved_stop is not None:
            return {"event": "trail_update", "new_stop": moved_stop}


        return None


    def open_trade(self, signal: Signal):
        self.trade.open(signal)


    def on_target_hit(self, target_name: str):
        if target_name == "POC":
            self.trade.mark_poc_hit()
        else:
            self.trade.mark_next_profile_hit()


    def on_trade_closed(self, exit_price: float, exit_ts: float) -> dict:
        result = self.trade.close(exit_price)
        self.governor.record_trade_result(result["pnl_usd"], exit_ts)
        log.info(f"MNQStrategySuite: trade closed pnl=${result['pnl_usd']:.2f}")
        return result 






