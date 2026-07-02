import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Callable
from zoneinfo import ZoneInfo

try:
    import websocket  # websocket-client
except Exception:
    websocket = None

ET = ZoneInfo("America/New_York")
log = logging.getLogger("mes_strategies")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

TICK_SIZE          = 0.25
DOLLARS_PER_POINT  = 5.0
DEFAULT_SIZE       = 1
MAX_STOP_PTS       = 20.0
DAILY_LOSS_LIMIT   = 200.0
MAX_LOSSES         = 2
TRADE_START        = (9, 45)
TRADE_END          = (11, 30)
FORCE_FLAT_ENABLED = True
FORCE_FLAT_TIME    = (15, 58)

TRADOVATE_MD_WS_URL      = "wss://md.tradovateapi.com/v1/websocket"
TRADOVATE_HEARTBEAT_SECS = 2.5
TRADOVATE_RESYNC_BARS    = 20
TRADOVATE_CHART_UNIT     = "Minute"
TRADOVATE_CHART_PERIOD   = 5


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def round_tick(price: float) -> float:
    return round(round(price / TICK_SIZE) * TICK_SIZE, 2)


def now_et() -> datetime:
    return datetime.now(ET)


def _time_at_or_after(hour_min: tuple[int, int], t: datetime) -> bool:
    h, m = t.hour, t.minute
    return (h > hour_min[0]) or (h == hour_min[0] and m >= hour_min[1])


def in_trade_window(ts: Optional[float] = None) -> bool:
    t = now_et() if ts is None else datetime.fromtimestamp(ts, tz=ET)
    after_start = _time_at_or_after(TRADE_START, t)
    before_end  = (t.hour < TRADE_END[0]) or (t.hour == TRADE_END[0] and t.minute < TRADE_END[1])
    return after_start and before_end


def after_force_flat(ts: Optional[float] = None) -> bool:
    t = now_et() if ts is None else datetime.fromtimestamp(ts, tz=ET)
    return _time_at_or_after(FORCE_FLAT_TIME, t)


def pts_to_dollars(pts: float, size: int) -> float:
    return pts * DOLLARS_PER_POINT * size


def bar_ts(bar: dict) -> float:
    for key in ("ts", "timestamp", "t"):
        if key in bar:
            return float(bar[key])
    return time.time()


# ─────────────────────────────────────────────
# ENUMS & DATA CLASSES
# ─────────────────────────────────────────────

class Direction(Enum):
    LONG  = "long"
    SHORT = "short"


class VwapColor(Enum):
    GREEN = "green"
    RED   = "red"
    WHITE = "white"


@dataclass
class Signal:
    strategy: str
    direction: Direction
    entry: float
    stop: float
    size: int
    reason: str


@dataclass
class SessionState:
    daily_pnl: float = 0.0
    loss_count: int = 0
    paused: bool = False
    date: str = field(default_factory=lambda: now_et().date().isoformat())

    def reset(self):
        self.daily_pnl = 0.0
        self.loss_count = 0
        self.paused = False
        self.date = now_et().date().isoformat()


# ─────────────────────────────────────────────
# SHARED RISK MANAGER
# ─────────────────────────────────────────────

class RiskManager:
    def __init__(self, news_times: Optional[List[datetime]] = None):
        self.session = SessionState()
        self.news_times = news_times or []

    def _ensure_session(self):
        today = now_et().date().isoformat()
        if self.session.date != today:
            self.session.reset()

    def _in_news_window(self, ts: Optional[float] = None) -> bool:
        t = now_et() if ts is None else datetime.fromtimestamp(ts, tz=ET)
        for news_dt in self.news_times:
            block_start = news_dt - timedelta(minutes=10)
            block_end = news_dt + timedelta(minutes=10)
            if block_start <= t <= block_end:
                return True
        return False

    def can_trade(self, ts: Optional[float] = None) -> bool:
        self._ensure_session()
        if self.session.paused:
            return False
        if FORCE_FLAT_ENABLED and after_force_flat(ts):
            return False
        if self._in_news_window(ts):
            log.info("RiskManager: blocked — news window active")
            return False
        return in_trade_window(ts)

    def record(self, pnl_usd: float):
        self._ensure_session()
        self.session.daily_pnl += pnl_usd

        if pnl_usd < 0:
            self.session.loss_count += 1
            log.warning(f"Loss #{self.session.loss_count} | Daily P&L: ${self.session.daily_pnl:.2f}")
            if self.session.loss_count >= MAX_LOSSES:
                self.session.paused = True
                log.warning("MAX LOSSES HIT — bot paused until manual reset.")

        if self.session.daily_pnl <= -DAILY_LOSS_LIMIT:
            self.session.paused = True
            log.warning(f"DAILY LOSS LIMIT ${DAILY_LOSS_LIMIT} — bot off.")

    def new_session(self, news_times: Optional[List[datetime]] = None):
        self.session.reset()
        if news_times is not None:
            self.news_times = news_times
        log.info("Session reset — bot active.")


# ─────────────────────────────────────────────
# VWAP
# ─────────────────────────────────────────────

class Vwap:
    def __init__(self):
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._history: List[float] = []

    def reset(self):
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._history = []

    def update(self, bar: dict) -> float:
        typical = (bar["h"] + bar["l"] + bar["c"]) / 3
        vol = max(bar["v"], 1)
        self._cum_pv += typical * vol
        self._cum_vol += vol
        value = self._cum_pv / self._cum_vol
        self._history.append(value)
        return value

    @property
    def value(self) -> float:
        return self._history[-1] if self._history else 0.0

    def value_at(self, index: int) -> float:
        if not self._history:
            return 0.0
        idx = max(0, min(index, len(self._history) - 1))
        return self._history[idx]

    def rebuild(self, bars: List[dict]):
        self.reset()
        for bar in bars:
            self.update(bar)

    def color(self, lookback: int = 3) -> VwapColor:
        if len(self._history) < lookback + 1:
            return VwapColor.WHITE
        delta = self._history[-1] - self._history[-(lookback + 1)]
        if delta > 0.5:
            return VwapColor.GREEN
        if delta < -0.5:
            return VwapColor.RED
        return VwapColor.WHITE


# ─────────────────────────────────────────────
# BAR BUILDER (kept active until chart-feed migration is fully demo-tested)
# ─────────────────────────────────────────────

class BarBuilder:
    def __init__(self, seconds: int):
        self.seconds = seconds
        self._bar: Optional[dict] = None
        self._start: Optional[float] = None

    def reset(self):
        self._bar = None
        self._start = None

    def tick(self, price: float, volume: float, ts: float) -> Optional[dict]:
        if self._start is None:
            self._start = ts
            self._bar = {"o": price, "h": price, "l": price, "c": price, "v": volume, "ts": ts}
            return None

        self._bar["h"] = max(self._bar["h"], price)
        self._bar["l"] = min(self._bar["l"], price)
        self._bar["c"] = price
        self._bar["v"] += volume

        if ts - self._start >= self.seconds:
            completed = dict(self._bar)
            self._start = ts
            self._bar = {"o": price, "h": price, "l": price, "c": price, "v": volume, "ts": ts}
            return completed
        return None


# ─────────────────────────────────────────────
# TRADOVATE CHART FEED (replacement target, not forced into prod path yet)
# ─────────────────────────────────────────────

class TradovateChartFeed:
    def __init__(
        self,
        access_token: str,
        contract_id: int,
        on_completed_bar: Callable[[dict], None],
        on_resync_bars: Callable[[List[dict]], None],
        ws_url: str = TRADOVATE_MD_WS_URL,
    ):
        self.access_token = access_token
        self.contract_id = contract_id
        self.on_completed_bar = on_completed_bar
        self.on_resync_bars = on_resync_bars
        self.ws_url = ws_url

        self.ws = None
        self._thread = None
        self._hb_thread = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._resyncing = True
        self._last_bar_id = None

    @property
    def resyncing(self) -> bool:
        return self._resyncing

    def start(self):
        if websocket is None:
            raise RuntimeError("websocket-client package is required for TradovateChartFeed")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._connected.clear()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _run_forever(self):
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self._connect_and_stream()
                backoff = 2.0
            except Exception as e:
                self._connected.clear()
                self._resyncing = True
                log.exception(f"TradovateChartFeed reconnect loop error: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 15.0)

    def _connect_and_stream(self):
        headers = [f"Authorization: Bearer {self.access_token}"]
        self.ws = websocket.WebSocket()
        self.ws.connect(self.ws_url, header=headers)
        self._connected.set()
        self._resyncing = True

        self._start_heartbeat()
        self._resync_from_history()
        self._subscribe_chart()

        while not self._stop.is_set():
            raw = self.ws.recv()
            if raw is None:
                raise ConnectionError("Tradovate websocket returned None")
            self._handle_message(raw)

    def _start_heartbeat(self):
        def loop():
            while not self._stop.is_set() and self._connected.is_set():
                try:
                    if self.ws:
                        self.ws.send("[]")
                except Exception as e:
                    log.warning(f"Heartbeat send failed: {e}")
                    break
                time.sleep(TRADOVATE_HEARTBEAT_SECS)

        self._hb_thread = threading.Thread(target=loop, daemon=True)
        self._hb_thread.start()

    def _subscribe_chart(self):
        body = {
            "contractId": self.contract_id,
            "underlyingType": TRADOVATE_CHART_UNIT,
            "elementSize": TRADOVATE_CHART_PERIOD,
        }
        msg = f"md/subscribeChart\n0\n\n{json.dumps(body)}"
        self.ws.send(msg)
        log.info("TradovateChartFeed: subscribed to 5-minute chart stream")

    def _get_chart(self, elements: int) -> List[dict]:
        body = {
            "contractId": self.contract_id,
            "underlyingType": TRADOVATE_CHART_UNIT,
            "elementSize": TRADOVATE_CHART_PERIOD,
            "elements": elements,
        }
        msg = f"md/getChart\n0\n\n{json.dumps(body)}"
        self.ws.send(msg)

        deadline = time.time() + 10
        while time.time() < deadline and not self._stop.is_set():
            raw = self.ws.recv()
            bars = self._extract_chart_history(raw)
            if bars is not None:
                return [self._normalize_bar(b) for b in bars]
        raise TimeoutError("Timed out waiting for md/getChart history")

    def _resync_from_history(self):
        bars = self._get_chart(TRADOVATE_RESYNC_BARS)
        completed = [b for b in bars if self._is_completed_bar(b)]
        if completed:
            self._last_bar_id = self._bar_identity(completed[-1])
        self.on_resync_bars(completed)
        self._resyncing = False
        log.info(f"TradovateChartFeed: resynced {len(completed)} bars from history")

    def _handle_message(self, raw: str):
        if raw == "o":
            return
        try:
            msg = json.loads(raw)
        except Exception:
            return

        bar = self._extract_chart_bar(msg)
        if bar is None:
            return

        bar = self._normalize_bar(bar)
        if not self._is_completed_bar(bar):
            return

        ident = self._bar_identity(bar)
        if ident == self._last_bar_id:
            return

        self._last_bar_id = ident

        if self._resyncing:
            return

        self.on_completed_bar(bar)

    def _extract_chart_history(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return None
        if isinstance(msg, dict):
            d = msg.get("d") or msg.get("data") or msg.get("result")
            if isinstance(d, dict):
                for key in ("chart", "bars", "elements"):
                    if isinstance(d.get(key), list):
                        return d.get(key)
            if isinstance(d, list):
                return d
        return None

    def _extract_chart_bar(self, msg):
        if not isinstance(msg, dict):
            return None
        d = msg.get("d") or msg.get("data") or msg.get("event") or msg
        if isinstance(d, dict):
            for key in ("bar", "chartBar", "element"):
                if isinstance(d.get(key), dict):
                    return d[key]
        return None

    def _normalize_bar(self, bar: dict) -> dict:
        ts = bar.get("timestamp") or bar.get("ts") or bar.get("t") or time.time()
        if ts > 1e12:
            ts = ts / 1000.0
        return {
            "o": float(bar.get("open", bar.get("o", 0.0))),
            "h": float(bar.get("high", bar.get("h", 0.0))),
            "l": float(bar.get("low", bar.get("l", 0.0))),
            "c": float(bar.get("close", bar.get("c", 0.0))),
            "v": float(bar.get("volume", bar.get("v", 0.0))),
            "ts": float(ts),
            "isClosed": bool(bar.get("isClosed", bar.get("closed", True))),
        }

    def _is_completed_bar(self, bar: dict) -> bool:
        return bool(bar.get("isClosed", True))

    def _bar_identity(self, bar: dict):
        return (bar.get("ts"), bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c"), bar.get("v"))


# ─────────────────────────────────────────────
# STRATEGY 1 — ORB RETEST
# ─────────────────────────────────────────────

class ORBRetestStrategy:
    BREAKOUT_PTS = 2.0
    RETEST_TOLERANCE = 1.5

    def __init__(self, vwap: Vwap, risk: RiskManager):
        self.vwap = vwap
        self.risk = risk
        self.reset()

    def reset(self):
        self.or_high = None
        self.or_low = None
        self.or_done = False
        self.or_bars: List[dict] = []
        self.phase = "BUILD_OR"
        self.side = None
        self.level = None
        self.traded_today = False
        self.bars_5m: List[dict] = []

    def add_bar(self, bar: dict):
        t = datetime.fromtimestamp(bar["ts"], tz=ET)
        if not self.or_done:
            if t.hour == 9 and 30 <= t.minute < 45:
                self.or_bars.append(bar)
                return
            if t.hour == 9 and t.minute >= 45 and self.or_bars:
                self.or_high = max(b["h"] for b in self.or_bars)
                self.or_low = min(b["l"] for b in self.or_bars)
                self.or_done = True
                self.phase = "WAIT_BREAK"
                log.info(f"ORB: OR built — high={self.or_high} low={self.or_low}")
        if self.or_done:
            self.bars_5m.append(bar)

    def evaluate(self, ts: Optional[float] = None) -> Optional[Signal]:
        if not self.or_done or self.traded_today:
            return None
        if not self.risk.can_trade(ts):
            return None
        if not self.bars_5m:
            return None

        bar = self.bars_5m[-1]
        color = self.vwap.color()

        if self.phase == "WAIT_BREAK":
            if bar["c"] > self.or_high + self.BREAKOUT_PTS and color == VwapColor.GREEN:
                self.side = "UP"
                self.level = self.or_high
                self.phase = "WAIT_RETEST"
                log.info(f"ORB: Upward break confirmed at {bar['c']:.2f}")
            elif bar["c"] < self.or_low - self.BREAKOUT_PTS and color == VwapColor.RED:
                self.side = "DOWN"
                self.level = self.or_low
                self.phase = "WAIT_RETEST"
                log.info(f"ORB: Downward break confirmed at {bar['c']:.2f}")
            return None

        if self.phase == "WAIT_RETEST":
            level = self.level
            touched = bar["l"] <= level + self.RETEST_TOLERANCE and bar["h"] >= level - self.RETEST_TOLERANCE
            if touched:
                self.phase = "WAIT_TRIGGER"
                log.info(f"ORB: Retest seen at level={level:.2f}")
            return None

        if self.phase == "WAIT_TRIGGER":
            color = self.vwap.color()

            if self.side == "UP" and color == VwapColor.GREEN:
                body_confirms = min(bar["o"], bar["c"]) > self.level - self.RETEST_TOLERANCE
                wick_ok = (bar["h"] - max(bar["o"], bar["c"])) < abs(bar["c"] - bar["o"])
                if body_confirms and wick_ok:
                    entry = round_tick(bar["c"])
                    stop = round_tick(bar["l"] - 1.0)
                    if abs(entry - stop) > MAX_STOP_PTS:
                        log.info("ORB: Stop > max, skipping.")
                        self.phase = "WAIT_BREAK"
                        return None
                    self.traded_today = True
                    self.phase = "DONE"
                    return Signal("ORB_RETEST", Direction.LONG, entry, stop, DEFAULT_SIZE, "ORB break+retest long")

            elif self.side == "DOWN" and color == VwapColor.RED:
                body_confirms = max(bar["o"], bar["c"]) < self.level + self.RETEST_TOLERANCE
                wick_ok = (min(bar["o"], bar["c"]) - bar["l"]) < abs(bar["c"] - bar["o"])
                if body_confirms and wick_ok:
                    entry = round_tick(bar["c"])
                    stop = round_tick(bar["h"] + 1.0)
                    if abs(entry - stop) > MAX_STOP_PTS:
                        log.info("ORB: Stop > max, skipping.")
                        self.phase = "WAIT_BREAK"
                        return None
                    self.traded_today = True
                    self.phase = "DONE"
                    return Signal("ORB_RETEST", Direction.SHORT, entry, stop, DEFAULT_SIZE, "ORB break+retest short")

        return None


# ─────────────────────────────────────────────
# STRATEGY 2 — PDH/PDL REVERSAL
# ─────────────────────────────────────────────

class PDHPDLStrategy:
    LEVEL_TOLERANCE = 3.0

    def __init__(self, pdh: float, pdl: float, vwap: Vwap, risk: RiskManager):
        self.vwap = vwap
        self.risk = risk
        self.bars_5m: List[dict] = []
        self.set_levels(pdh, pdl)

    def reset(self):
        self.bars_5m = []
        self.pdh_traded = False
        self.pdl_traded = False

    def set_levels(self, pdh: float, pdl: float):
        self.pdh = pdh
        self.pdl = pdl
        self.pdh_traded = False
        self.pdl_traded = False

    def add_bar(self, bar: dict):
        self.bars_5m.append(bar)

    def _wick_pct(self, bar: dict, direction: Direction) -> float:
        rng = bar["h"] - bar["l"]
        if rng == 0:
            return 0.0
        if direction == Direction.SHORT:
            return (bar["h"] - max(bar["o"], bar["c"])) / rng
        return (min(bar["o"], bar["c"]) - bar["l"]) / rng

    def evaluate(self, ts: Optional[float] = None) -> Optional[Signal]:
        if not self.risk.can_trade(ts):
            return None
        if not self.bars_5m:
            return None

        bar = self.bars_5m[-1]
        color = self.vwap.color()

        if not self.pdh_traded and color == VwapColor.RED:
            at_pdh = abs(bar["h"] - self.pdh) <= self.LEVEL_TOLERANCE
            if at_pdh and self._wick_pct(bar, Direction.SHORT) >= 0.50:
                body_below = max(bar["o"], bar["c"]) < self.pdh
                if body_below:
                    entry = round_tick(bar["c"])
                    stop = round_tick(bar["h"] + 2.0)
                    if abs(entry - stop) > MAX_STOP_PTS:
                        log.info("PDH: Stop > max, skipping.")
                        return None
                    self.pdh_traded = True
                    log.info(f"PDH/PDL: Short at PDH {self.pdh:.2f} with 5-min body close confirmation")
                    return Signal("PDH_REVERSAL", Direction.SHORT, entry, stop, DEFAULT_SIZE, f"Rejection at PDH {self.pdh:.2f} with body-close confirm")

        if not self.pdl_traded and color == VwapColor.GREEN:
            at_pdl = abs(bar["l"] - self.pdl) <= self.LEVEL_TOLERANCE
            if at_pdl and self._wick_pct(bar, Direction.LONG) >= 0.50:
                body_above = min(bar["o"], bar["c"]) > self.pdl
                if body_above:
                    entry = round_tick(bar["c"])
                    stop = round_tick(bar["l"] - 2.0)
                    if abs(entry - stop) > MAX_STOP_PTS:
                        log.info("PDL: Stop > max, skipping.")
                        return None
                    self.pdl_traded = True
                    log.info(f"PDH/PDL: Long at PDL {self.pdl:.2f} with 5-min body close confirmation")
                    return Signal("PDL_REVERSAL", Direction.LONG, entry, stop, DEFAULT_SIZE, f"Rejection at PDL {self.pdl:.2f} with body-close confirm")

        return None


# ─────────────────────────────────────────────
# STRATEGY 3 — VWAP RECLAIM
# ─────────────────────────────────────────────

class VwapReclaimStrategy:
    BARS_BEYOND_MIN = 2
    MAX_TRADES = 2
    COOLDOWN_BARS = 10

    def __init__(self, vwap: Vwap, risk: RiskManager):
        self.vwap = vwap
        self.risk = risk
        self.reset()

    def reset(self):
        self.bars_5m: List[dict] = []
        self.trades_today = 0
        self.bars_since_trade = 999

    def add_bar(self, bar: dict):
        self.bars_5m.append(bar)
        self.bars_since_trade += 1

    def _bars_on_wrong_side(self, direction: Direction) -> int:
        if len(self.bars_5m) != len(self.vwap._history):
            return 0
        if len(self.bars_5m) < 2:
            return 0

        limit = len(self.bars_5m)
        count = 0
        for i in range(limit - 2, -1, -1):
            bar = self.bars_5m[i]
            vwap_at_bar = self.vwap.value_at(i)

            if direction == Direction.LONG and bar["c"] < vwap_at_bar:
                count += 1
            elif direction == Direction.SHORT and bar["c"] > vwap_at_bar:
                count += 1
            else:
                break

        return count

    def evaluate(self, ts: Optional[float] = None) -> Optional[Signal]:
        if not self.risk.can_trade(ts):
            return None
        if self.trades_today >= self.MAX_TRADES:
            return None
        if self.bars_since_trade < self.COOLDOWN_BARS:
            return None
        if len(self.bars_5m) < self.BARS_BEYOND_MIN + 1:
            return None

        bar = self.bars_5m[-1]
        vwap = self.vwap.value
        body_hi = max(bar["o"], bar["c"])
        body_lo = min(bar["o"], bar["c"])

        if body_lo > vwap and body_hi > vwap:
            if self._bars_on_wrong_side(Direction.LONG) >= self.BARS_BEYOND_MIN:
                entry = round_tick(bar["c"])
                stop = round_tick(bar["l"] - 1.0)
                if abs(entry - stop) > MAX_STOP_PTS:
                    return None
                self.trades_today += 1
                self.bars_since_trade = 0
                log.info(f"VWAP Reclaim: Long at {entry:.2f}")
                return Signal("VWAP_RECLAIM", Direction.LONG, entry, stop, DEFAULT_SIZE, "VWAP reclaim long")

        if body_hi < vwap and body_lo < vwap:
            if self._bars_on_wrong_side(Direction.SHORT) >= self.BARS_BEYOND_MIN:
                entry = round_tick(bar["c"])
                stop = round_tick(bar["h"] + 1.0)
                if abs(entry - stop) > MAX_STOP_PTS:
                    return None
                self.trades_today += 1
                self.bars_since_trade = 0
                log.info(f"VWAP Reclaim: Short at {entry:.2f}")
                return Signal("VWAP_RECLAIM", Direction.SHORT, entry, stop, DEFAULT_SIZE, "VWAP reclaim short")

        return None


# ─────────────────────────────────────────────
# TRADE MANAGER
# ─────────────────────────────────────────────

class TradeManager:
    TRAIL_DEFAULT = 8.0
    TRAIL_TIGHT = 4.0

    def __init__(self):
        self.signal: Optional[Signal] = None
        self.stop: float = 0.0
        self.best: float = 0.0

    @property
    def in_trade(self) -> bool:
        return self.signal is not None

    def reset(self):
        self.signal = None
        self.stop = 0.0
        self.best = 0.0

    def open(self, signal: Signal):
        self.signal = signal
        self.stop = signal.stop
        self.best = signal.entry
        log.info(f"Trade open: {signal.strategy} {signal.direction.value} @ {signal.entry} stop={signal.stop}")

    def update_trail(self, price: float) -> Optional[float]:
        if not self.signal:
            return None

        is_long = self.signal.direction == Direction.LONG
        improved = price > self.best if is_long else price < self.best

        if improved:
            self.best = price

        moved = abs(self.best - self.signal.entry)
        trail = self.TRAIL_TIGHT if moved > 10 else self.TRAIL_DEFAULT
        new_stop = round_tick(self.best - trail if is_long else self.best + trail)

        if (is_long and new_stop > self.stop) or (not is_long and new_stop < self.stop):
            self.stop = new_stop
            return new_stop
        return None

    def stop_hit(self, price: float) -> bool:
        if not self.signal:
            return False
        is_long = self.signal.direction == Direction.LONG
        return (is_long and price <= self.stop) or (not is_long and price >= self.stop)

    def close(self, exit_price: float) -> dict:
        sig = self.signal
        pts = (exit_price - sig.entry) * (1 if sig.direction == Direction.LONG else -1)
        result = {
            "strategy": sig.strategy,
            "direction": sig.direction.value,
            "entry": sig.entry,
            "exit": exit_price,
            "pts": round(pts, 2),
            "pnl_usd": round(pts_to_dollars(pts, sig.size), 2),
        }
        self.reset()
        return result


# ─────────────────────────────────────────────
# STRATEGY RUNNER
# ─────────────────────────────────────────────

class MESStrategyRunner:
    """
    Current production-safe runner keeps BarBuilder in place.

    TradovateChartFeed is implemented but should only replace BarBuilder after
    reconnect/resync is validated in demo. During feed resync, signals must be blocked.

    Execution-layer note:
    - Trailing updates and stop-hit checks must run on every tick via price updates,
      not only on completed 5-minute bars.
    - on_completed_chart_bar() and tick()->bar flow handle signal generation only.
    """
    def __init__(self, pdh: float, pdl: float, news_times: Optional[List[datetime]] = None):
        self.risk = RiskManager(news_times=news_times)
        self.vwap = Vwap()
        self.builder = BarBuilder(300)

        self.orb = ORBRetestStrategy(self.vwap, self.risk)
        self.pdh_pdl = PDHPDLStrategy(pdh, pdl, self.vwap, self.risk)
        self.reclaim = VwapReclaimStrategy(self.vwap, self.risk)
        self.trade = TradeManager()

        self.force_flat_done = False
        self.resyncing = False
        self.chart_feed: Optional[TradovateChartFeed] = None

    def set_pdh_pdl(self, pdh: float, pdl: float):
        self.pdh_pdl.set_levels(pdh, pdl)

    def new_session(self, news_times: Optional[List[datetime]] = None):
        self.risk.new_session(news_times=news_times)
        self.vwap.reset()
        self.orb.reset()
        self.pdh_pdl.reset()
        self.reclaim.reset()
        self.trade.reset()
        self.builder.reset()
        self.force_flat_done = False
        self.resyncing = False
        log.info("MES runner: new session started.")

    def rebuild_from_bars(self, bars: List[dict]):
        self.vwap.rebuild(bars)
        self.orb.reset()
        self.pdh_pdl.reset()
        self.reclaim.reset()
        for bar in bars:
            self.orb.add_bar(bar)
            self.pdh_pdl.add_bar(bar)
            self.reclaim.add_bar(bar)
        log.info(f"MES runner: rebuilt state from {len(bars)} bars")

    def attach_tradovate_chart_feed(self, feed: TradovateChartFeed):
        self.chart_feed = feed

    def on_chart_resync(self, bars: List[dict]):
        self.resyncing = True
        self.rebuild_from_bars(bars)
        self.resyncing = False

    def on_completed_chart_bar(self, bar: dict) -> Optional[Signal]:
        self.vwap.update(bar)
        self.orb.add_bar(bar)
        self.pdh_pdl.add_bar(bar)
        self.reclaim.add_bar(bar)

        if self.resyncing:
            return None
        if not self.risk.can_trade(bar_ts(bar)):
            return None

        for strategy in (self.orb, self.pdh_pdl, self.reclaim):
            sig = strategy.evaluate(bar_ts(bar))
            if sig:
                self.trade.open(sig)
                log.info(f"Signal: {sig.strategy} {sig.direction.value} entry={sig.entry} stop={sig.stop}")
                return sig
        return None

    def tick(self, price: float, volume: float, ts: float) -> Optional[Signal]:
        if FORCE_FLAT_ENABLED and after_force_flat(ts):
            if not self.force_flat_done:
                if self.trade.in_trade:
                    result = self.trade.close(price)
                    pnl_usd = result["pnl_usd"]
                    self.risk.record(pnl_usd)
                    log.warning(f"FORCE FLAT: {result['strategy']} exited @ {price:.2f} P&L=${pnl_usd:.2f}")
                self.force_flat_done = True
            return None

        if self.trade.in_trade:
            new_stop = self.trade.update_trail(price)
            if new_stop:
                log.info(f"Trail stop → {new_stop:.2f}")

            if self.trade.stop_hit(price):
                result = self.trade.close(price)
                pnl_usd = result["pnl_usd"]
                self.risk.record(pnl_usd)
                log.info(f"Trade closed: {result['strategy']} P&L=${pnl_usd:.2f}")
            return None

        if self.resyncing:
            return None

        if not self.risk.can_trade(ts):
            return None

        bar = self.builder.tick(price, volume, ts)
        if not bar:
            return None

        return self.on_completed_chart_bar(bar)

    def on_fill(self, fill_price: float):
        if not self.trade.in_trade:
            return
        result = self.trade.close(fill_price)
        pnl_usd = result["pnl_usd"]
        self.risk.record(pnl_usd)
        log.info(f"Fill confirmed: {result['strategy']} P&L=${pnl_usd:.2f}")



