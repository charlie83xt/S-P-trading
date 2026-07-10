"""
SetupClassifier -- the 'fat detector'.

It tags every setup it evaluates with a human-readable reason, fired or not, so
the backtest has data to study (including near-miss rejects). It makes NO
trade decision and applies NO risk rule -- that is the gate's job (gate.py),
which stays strict and unchanged from the document.

Naming: the document already defines Setup D = VWAP Bounce (trend days). So the
three NEW interior setups are E / F / G, not D / E / F -- reusing 'D' would
corrupt the logs.

    A  Return to Value (80% rule)        15-min, documented
    B  Fade VA extreme                   5-min,  documented
    C  PDH/PDL break-retest              5-min,  documented
    D  VWAP Bounce (trend days only)     5-min,  documented
    E  VWAP reclaim                      5-min,  NEW interior
    F  POC rotation                      5-min,  NEW interior
    G  VA edge fade (lighter than B)     5-min,  NEW interior, inside-VA opens
"""

from __future__ import annotations

from typing import Optional

from .types import (Bar, Detection, OpenLocation, SessionLevels, Side,
                    VwapColor)
from .profile import inside_va


class _Agg15:
    """Builds completed 15-min bars from a stream of 5-min bars."""

    def __init__(self) -> None:
        self._key = None
        self._buf: list[Bar] = []

    def push(self, bar: Bar) -> Optional[Bar]:
        key = (bar.ts.date(), bar.ts.hour, bar.ts.minute // 15)
        completed = None
        if self._key is not None and key != self._key and self._buf:
            completed = self._finalize()
        self._key = key
        self._buf.append(bar)
        return completed

    def _finalize(self) -> Bar:
        b = self._buf
        bar15 = Bar(ts=b[0].ts, open=b[0].open,
                    high=max(x.high for x in b), low=min(x.low for x in b),
                    close=b[-1].close, volume=sum(x.volume for x in b),
                    minutes=15)
        self._buf = []
        return bar15

    def flush(self) -> Optional[Bar]:
        if self._buf:
            return self._finalize()
        return None


class SetupClassifier:
    """Per-session detector. Call on_bar(...) with each 5-min bar in order."""

    def __init__(self, levels: SessionLevels, rth_open: float, *,
                 edge_tol: float = 1.5,
                 c_break_points: float = 2.0,
                 c_accept_closes: int = 2,
                 e_min_opposite_bars: int = 2,
                 f_rotation_distance: float = 8.0,
                 f_stall_bars: int = 2):
        self.levels = levels
        self.open_loc = levels.classify_open(rth_open)
        self.edge_tol = edge_tol
        self.c_break_points = c_break_points
        self.c_accept_closes = c_accept_closes
        self.e_min_opposite_bars = e_min_opposite_bars
        self.f_rotation_distance = f_rotation_distance
        self.f_stall_bars = f_stall_bars

        # --- per-session detector state ---
        self._agg = _Agg15()
        self._a_inside_streak = 0          # consecutive 15-min bodies back inside
        self._vwap_side_hist: list[str] = []   # 'above'/'below' per 5-min close
        self._c_closes_beyond = 0
        self._c_broken_level: Optional[str] = None   # 'pdh'/'pdl'
        self._c_awaiting_retest = False
        self._f_departed_dir = 0           # +1 above POC, -1 below, 0 none
        self._f_max_dist = 0.0
        self._f_stall = 0
        self._prev_close: Optional[float] = None

    # ---- helpers ----------------------------------------------------------
    def _vwap_side(self, price: float, vwap: float) -> str:
        return "above" if price >= vwap else "below"

    # ---- main entry -------------------------------------------------------
    def on_bar(self, bar: Bar, vwap: Optional[float],
               color: VwapColor) -> list[Detection]:
        out: list[Detection] = []

        # A is evaluated on completed 15-min bars.
        bar15 = self._agg.push(bar)
        if bar15 is not None:
            d = self._setup_a(bar15, vwap, color)
            if d:
                out.append(d)

        if vwap is not None:
            for det in (self._setup_b(bar, vwap, color),
                        self._setup_c(bar, vwap, color),
                        self._setup_d(bar, vwap, color),
                        self._setup_e(bar, vwap, color),
                        self._setup_f(bar, vwap, color),
                        self._setup_g(bar, vwap, color)):
                if det:
                    out.append(det)

            # update vwap-side history AFTER detectors read prior state
            self._vwap_side_hist.append(self._vwap_side(bar.close, vwap))

        self._prev_close = bar.close
        return out

    # ---- Setup A: Return to Value (80% rule), 15-min ----------------------
    def _setup_a(self, bar15: Bar, vwap, color) -> Optional[Detection]:
        L = self.levels
        if self.open_loc not in (OpenLocation.ABOVE_VAH, OpenLocation.BELOW_VAL):
            return None  # no context

        if self.open_loc == OpenLocation.ABOVE_VAH:
            inside = bar15.close < L.vah
            side, want_color, target = Side.SHORT, VwapColor.RED, L.poc
        else:
            inside = bar15.close > L.val
            side, want_color, target = Side.LONG, VwapColor.GREEN, L.poc

        if not inside:
            self._a_inside_streak = 0
            return None
        self._a_inside_streak += 1
        if self._a_inside_streak < 2:
            return Detection(bar15.ts, "A", False,
                             f"1/2 15-min bodies back inside VA (need 2)",
                             side=side, level=L.vah if side == Side.SHORT else L.val,
                             vwap=vwap, vwap_color=color)
        if color != want_color:
            return Detection(bar15.ts, "A", False,
                             f"two bodies inside but VWAP {color.value} != {want_color.value}",
                             side=side, vwap=vwap, vwap_color=color)
        return Detection(bar15.ts, "A", True,
                         "outside-VA open, 2 consecutive 15-min bodies back inside VA, VWAP confirms",
                         side=side, entry_ref=bar15.close, target=target,
                         level=L.vah if side == Side.SHORT else L.val,
                         vwap=vwap, vwap_color=color)

    # ---- Setup B: Fade VA extreme (inside-VA day), 5-min ------------------
    def _setup_b(self, bar: Bar, vwap, color) -> Optional[Detection]:
        L = self.levels
        if self.open_loc != OpenLocation.INSIDE_VA:
            return None
        if bar.rng <= 0:
            return None
        tests_vah = bar.high >= L.vah - self.edge_tol
        tests_val = bar.low <= L.val + self.edge_tol
        if not (tests_vah or tests_val):
            return None

        if tests_vah:
            side, want_color = Side.SHORT, VwapColor.RED
            wick = bar.upper_wick()
            closed_inside = bar.close < L.vah
            level = L.vah
        else:
            side, want_color = Side.LONG, VwapColor.GREEN
            wick = bar.lower_wick()
            closed_inside = bar.close > L.val
            level = L.val

        wick_ok = wick >= 0.5 * bar.rng
        if not wick_ok:
            return Detection(bar.ts, "B", False,
                             f"edge test but rejection wick {wick/bar.rng:.0%} < 50%",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        if not closed_inside:
            return Detection(bar.ts, "B", False, "50% wick but body did not close back inside VA",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        if color != want_color:
            return Detection(bar.ts, "B", False,
                             f"valid fade but VWAP {color.value} != {want_color.value} (counter-VWAP: gate may allow 1 contract)",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        return Detection(bar.ts, "B", True,
                         "inside-VA day, edge test with >=50% rejection wick, body back inside, VWAP confirms",
                         side=side, entry_ref=bar.close, target=L.poc, level=level,
                         vwap=vwap, vwap_color=color)

    # ---- Setup C: PDH/PDL break-retest, 5-min -----------------------------
    def _setup_c(self, bar: Bar, vwap, color) -> Optional[Detection]:
        L = self.levels
        broke_up = bar.close >= L.pdh + self.c_break_points
        broke_dn = bar.close <= L.pdl - self.c_break_points

        # phase 1: accumulate acceptance
        if self._c_broken_level is None:
            if broke_up or broke_dn:
                self._c_closes_beyond += 1
                lvl = "pdh" if broke_up else "pdl"
                if self._c_closes_beyond >= self.c_accept_closes:
                    self._c_broken_level = lvl
                    self._c_awaiting_retest = True
                    return Detection(bar.ts, "C", False,
                                     f"{lvl.upper()} accepted ({self._c_closes_beyond} closes beyond); awaiting first retest",
                                     vwap=vwap, vwap_color=color)
                return Detection(bar.ts, "C", False,
                                 f"break of {lvl.upper()} ({self._c_closes_beyond}/{self.c_accept_closes} closes); first breaks fail, waiting for acceptance",
                                 vwap=vwap, vwap_color=color)
            else:
                self._c_closes_beyond = 0
            return None

        # phase 2: awaiting retest of the broken level
        lvl_price = L.pdh if self._c_broken_level == "pdh" else L.pdl
        if self._c_broken_level == "pdh":
            side, want_color = Side.LONG, VwapColor.GREEN
            retests = bar.low <= lvl_price + self.edge_tol
            strength = bar.close > lvl_price and bar.is_up
        else:
            side, want_color = Side.SHORT, VwapColor.RED
            retests = bar.high >= lvl_price - self.edge_tol
            strength = bar.close < lvl_price and not bar.is_up

        if not retests:
            return None
        if not strength:
            return Detection(bar.ts, "C", False, "retest of broken level but no strength close in breakout direction",
                             side=side, level=lvl_price, vwap=vwap, vwap_color=color)
        if color != want_color:
            return Detection(bar.ts, "C", False,
                             f"retest+strength but VWAP {color.value} != {want_color.value}",
                             side=side, level=lvl_price, vwap=vwap, vwap_color=color)
        self._c_awaiting_retest = False
        target = L.vah if side == Side.LONG else L.val
        return Detection(bar.ts, "C", True,
                         f"{self._c_broken_level.upper()} broke+accepted, first retest held with strength, VWAP confirms",
                         side=side, entry_ref=bar.close, target=target, level=lvl_price,
                         vwap=vwap, vwap_color=color)

    # ---- Setup D: VWAP Bounce (trend days only), 5-min --------------------
    def _setup_d(self, bar: Bar, vwap, color) -> Optional[Detection]:
        # Trend-day proxy: strong directional VWAP color AND price testing VWAP
        # from the trend side. Conservative on purpose; this only fires when the
        # day actually looks like a trend. Sub-VWAP trap is left to the gate's
        # body-close requirement (handled by entry_ref being a close).
        if color == VwapColor.WHITE:
            return None
        tests_vwap = bar.low <= vwap <= bar.high
        if not tests_vwap:
            return None
        if color == VwapColor.GREEN:
            side = Side.LONG
            strength = bar.close > vwap and bar.is_up
        else:
            side = Side.SHORT
            strength = bar.close < vwap and not bar.is_up
        if not strength:
            return Detection(bar.ts, "D", False, "VWAP test but no strength close in trend direction (possible sub-VWAP trap)",
                             side=side, level=vwap, vwap=vwap, vwap_color=color)
        return Detection(bar.ts, "D", True,
                         "trend-colored VWAP, first-test strength close in trend direction",
                         side=side, entry_ref=bar.close, target=None, level=vwap,
                         vwap=vwap, vwap_color=color)

    # ---- Setup E: VWAP reclaim (NEW interior), 5-min ----------------------
    def _setup_e(self, bar: Bar, vwap, color) -> Optional[Detection]:
        hist = self._vwap_side_hist
        if len(hist) < self.e_min_opposite_bars:
            return None
        recent = hist[-self.e_min_opposite_bars:]
        now_side = self._vwap_side(bar.close, vwap)

        # reclaim above: were below for N bars, now body closes above
        if all(s == "below" for s in recent) and now_side == "above":
            side, want_color = Side.LONG, VwapColor.GREEN
            body_through = bar.body_low <= vwap <= bar.close  # body, not just wick
            if not body_through:
                return Detection(bar.ts, "E", False, "tagged VWAP from below but no body close through (wick only)",
                                 side=side, level=vwap, vwap=vwap, vwap_color=color)
            if color != want_color:
                return Detection(bar.ts, "E", False, f"reclaim above but VWAP {color.value} != green",
                                 side=side, level=vwap, vwap=vwap, vwap_color=color)
            return Detection(bar.ts, "E", True,
                             f"{self.e_min_opposite_bars}+ bars below VWAP, 5-min body reclaim above, color confirms",
                             side=side, entry_ref=bar.close, target=None, level=vwap,
                             vwap=vwap, vwap_color=color)

        if all(s == "above" for s in recent) and now_side == "below":
            side, want_color = Side.SHORT, VwapColor.RED
            body_through = bar.close <= vwap <= bar.body_high
            if not body_through:
                return Detection(bar.ts, "E", False, "tagged VWAP from above but no body close through (wick only)",
                                 side=side, level=vwap, vwap=vwap, vwap_color=color)
            if color != want_color:
                return Detection(bar.ts, "E", False, f"reclaim below but VWAP {color.value} != red",
                                 side=side, level=vwap, vwap=vwap, vwap_color=color)
            return Detection(bar.ts, "E", True,
                             f"{self.e_min_opposite_bars}+ bars above VWAP, 5-min body reclaim below, color confirms",
                             side=side, entry_ref=bar.close, target=None, level=vwap,
                             vwap=vwap, vwap_color=color)
        return None

    # ---- Setup F: POC rotation (NEW interior), 5-min ----------------------
    def _setup_f(self, bar: Bar, vwap, color) -> Optional[Detection]:
        L = self.levels
        dist = bar.close - L.poc
        adist = abs(dist)
        cur_dir = 1 if dist > 0 else (-1 if dist < 0 else 0)

        # track departure from POC
        if self._f_departed_dir == 0 and adist >= self.f_rotation_distance:
            self._f_departed_dir = cur_dir
            self._f_max_dist = adist
            self._f_stall = 0
            return Detection(bar.ts, "F", False,
                             f"left POC by {adist:.1f}pt ({'above' if cur_dir>0 else 'below'}); watching for stall+rotation",
                             vwap=vwap, vwap_color=color)
        if self._f_departed_dir == 0:
            return None

        # we are departed; check continuation vs stall
        if cur_dir == self._f_departed_dir and adist > self._f_max_dist:
            self._f_max_dist = adist
            self._f_stall = 0
            return Detection(bar.ts, "F", False, "still extending away from POC (no rotation yet)",
                             vwap=vwap, vwap_color=color)

        self._f_stall += 1
        if self._f_stall < self.f_stall_bars:
            return None

        # stalled: look for a body close back toward POC
        moving_back = (self._prev_close is not None and
                       abs(bar.close - L.poc) < abs(self._prev_close - L.poc))
        if not moving_back:
            return None
        side = Side.SHORT if self._f_departed_dir > 0 else Side.LONG
        # reset departure tracking after a rotation fires
        det = Detection(bar.ts, "F", True,
                        f"left POC {self._f_max_dist:.1f}pt, stalled {self._f_stall} bars, body rotating back toward POC",
                        side=side, entry_ref=bar.close, target=L.poc, level=L.poc,
                        vwap=vwap, vwap_color=color)
        self._f_departed_dir = 0
        self._f_max_dist = 0.0
        self._f_stall = 0
        return det

    # ---- Setup G: VA edge fade, lighter than B (NEW interior), 5-min ------
    def _setup_g(self, bar: Bar, vwap, color) -> Optional[Detection]:
        L = self.levels
        if self.open_loc != OpenLocation.INSIDE_VA:
            return None
        tests_vah = bar.high >= L.vah - self.edge_tol
        tests_val = bar.low <= L.val + self.edge_tol
        if not (tests_vah or tests_val):
            return None

        if tests_vah:
            side, want_color = Side.SHORT, VwapColor.RED
            closed_inside = bar.close < L.vah
            wick = bar.upper_wick()
            level = L.vah
        else:
            side, want_color = Side.LONG, VwapColor.GREEN
            closed_inside = bar.close > L.val
            wick = bar.lower_wick()
            level = L.val

        if not closed_inside:
            return Detection(bar.ts, "G", False, "edge test but body did not close back inside VA",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        # G is the LIGHTER cousin of B: no 50% wick required. If the wick IS
        # >=50%, this is really a B -> mark superseded so we don't double-count.
        if wick >= 0.5 * bar.rng and color == want_color:
            return Detection(bar.ts, "G", False, "qualifies as Setup B (>=50% wick); not double-counting as G",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        if color != want_color:
            return Detection(bar.ts, "G", False, f"light fade but VWAP {color.value} != {want_color.value}",
                             side=side, level=level, vwap=vwap, vwap_color=color)
        return Detection(bar.ts, "G", True,
                         "inside-VA day, edge test, body back inside VA (light confirmation, no 50% wick required)",
                         side=side, entry_ref=bar.close, target=L.poc, level=level,
                         vwap=vwap, vwap_color=color) 
