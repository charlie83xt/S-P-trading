from __future__ import annotations
from typing import Dict, Any, Optional
import time
import logging
from collections import deque

class TestStrategy:
    """
    A very simple strategy fir wiring/plumbing tests.
        - Generates BUY if price > last_price * (1 + threshold)
        - Generates SELL if price < last_price * (1 - threshold)
        - Keeps small internal state so UI can display something
    """

    def __init__(self, data_manager, threshold: float = 0.001, pct_threshold: Optional[float] = None, abs_threshold: float = 0.25, qty: int = 1, cooldown_sec: float = 1.0):
        self.log = logging.getLogger("test_strategy")
        self.data_manager = data_manager

        # accept either 'threshold' or the explicit 'pct_threshold'
        self.pct_threshold = float(pct_threshold if pct_threshold is not None else threshold)
        self.abs_threshold = float(abs_threshold)
        self.qty = int(qty)

        self.last_price: float | None = None
        self.last_signal_ts:  float = 0.0
        self.min_gap_sec: float = float(cooldown_sec) # debounce
        self.signals_generated = 0
        self._last_debug_ts = 0.0

        self.anchor_price: Optional[float] = None
        self.last_tick_price: Optional[float] = None
        self.rearm_pct: float = max(self.pct_threshold * 0.5, 1e-06) # small band to rearm
        self.rearm_abs: float = max(self.abs_threshold * 0.5, 0.01) # small band to rearm

        self.recent_prices = deque(maxlen=300)

    # Bot to call this every tick it presents
    def ingest_tick(self, symbol: str, ts: float, price: float | None):
        # guard bad price (None / NaN / non-numeric)
        if price is None or not isinstance(price, (int, float)) or price != price:
            return

        self.last_tick_price = float(price)

        # initialize anchor if needed, otherwise keep it for breakout logic
        if self.anchor_price is None:
            self.anchor_price = float(price)

        # periodic debug so we can see state while running
        if (ts - getattr(self, "_last_debug_ts", 0.0)) >= 2.0 and self.anchor_price is not None:
            ap = self.anchor_price
            up_abs = ap + self.abs_threshold
            dn_abs = ap - self.abs_threshold
            up_pct = ap * (1.0 + self.pct_threshold)
            dn_pct = ap * (1.0 - self.pct_threshold)
            self.log.debug(
                "tick p=%.4f last=%.4f up_abs=%.4f dn_abs=%.4f up_pct=%.4f dn_pct=%.4f",
                float(price),
                float(lp) if lp is not None else float("nan"),
                float(up_abs) if up_abs is not None else float("nan"),
                float(dn_abs) if dn_abs is not None else float("nan"),
                float(up_pct) if up_pct is not None else float("nan"),
                float(dn_pct) if dn_pct is not None else float("nan"),
            )
            self._last_debug_ts = ts

        self.recent_prices.append(float(price))

    # called by bot when symbol changes (your bot already calls reset_strategy())
    def reset_strategy(self):
        self.last_price = None
        self.signals_generated = 0
        self.last_signal_ts = 0.0
        self.log.info("TestStrategy reset")


    def check_breakout(self, symbol: str, current_price: Optional[float]) -> Optional[Dict[str, Any]]:
        now = time.time()
        if current_price is None or not isinstance(current_price, (int, float)) or current_price != current_price:
            return None

        # Warm-up baseline
        if self.anchor_price is None:
            self.anchor_price = float(current_price)
            return None

         # Debounce
        if (now - self.last_signal_ts) < self.min_gap_sec:
            # self.last_price = float(current_price)
            return None

        # simple cooldown
        # if now - self._last_signal_ts < self._cooldown:
        #     return None

        ap = float(self.anchor_price)
        up_trig = (current_price > ap * (1.0 + self.pct_threshold)) or (current_price >= ap + self.abs_threshold)
        dn_trig = (current_price < ap * (1.0 - self.pct_threshold)) or (current_price <= ap - self.abs_threshold)

        sig = None
        # if self.last_price is not None:
        #     up_pct = self.last_price * (1.0 + self.pct_threshold)
        #     dn_pct = self.last_price * (1.0 - self.pct_threshold)
        #     up_abs = self.last_price + self.abs_threshold
        #     dn_abs = self.last_price - self.abs_threshold

        #     up_trig = (current_price > up_pct) or (current_price >= up_abs)
        #     dn_trig = (current_price < dn_pct) or (current_price <= dn_abs)

        if up_trig:
            sig = {"type": "BUY", "symbol": symbol, "price": float(current_price), "qty": self.qty, "reason": "test_up"}
        elif dn_trig:
            sig = {"type": "SELL", "symbol": symbol, "price": float(current_price), "qty": self.qty, "reason": "test_dn"}

        # update state
        if sig:          
            self.signals_generated += 1
            self.last_signal_ts = now
            # Re-arm anchor **at** the signal price so new moves can trigger again
            self.anchor_price = float(current_price)
            return sig

        # No signal: optional "re-entry band" to re-center anchor when price drifts back
        # If price returns close to anchor (inside a small band), snap anchor to current
        if abs(current_price - ap) <= max(self.rearm_abs, ap * self.rearm_pct):
            self.anchor_price = float(current_price)

        return None


    def get_strategy_status(self) -> Dict[str, Any]:
        return {
            "name": "TestStrategy",
            "pct_threshold": self.pct_threshold,
            "abs_threshold": self.abs_threshold,
            "qty": self.qty,
            "anchor_price": self.anchor_price,
            "last_tick_price": self.last_tick_price,
            "signals_generated": self.signals_generated 
        }

    # used by your dashboard for "Market Analysis"
    def analyze_market_context(self, symbol: str) -> Dict[str, Any]:
        price =  self.data_manager.get_current_price(symbol)
        rp = "unknown"
        if price is not None and len(self.recent_prices) >= 10:
            lo = min(self.recent_prices)
            hi = max(self.recent_prices)
            if hi > lo:
                pct = (price - lo) / (hi - lo)
                if pct >= 0.95:
                    rp = "near_high"
                elif pct >= 0.66:
                    rp = "upper"
                elif pct >= 0.33:
                    rp = "middle"
                elif pct >= 0.05:
                    rp = "lower"
                else:
                    rp = "low"
        return {
            "current_price": price,
            "range_position": rp,
            "opening_range": None,
            "yesterday_day_range": None,
        }
