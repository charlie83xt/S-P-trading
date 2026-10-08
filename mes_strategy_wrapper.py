"""
MES Strategy wrapper — plugs MESStrategyRunner into the bot's existing interface.

Entry signal generation only. Bot's risk_manager handles stops / exits.
MESStrategyRunner.on_completed_chart_bar() is called with aggregated 5-minute
bars built from LiveBarStore's 1-minute bars (volume is tick count, which is
sufficient for VWAP colour and regime detection).
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from notifier import notify
from mes_strategy_runner import MESStrategyRunner

ET_TZ = ZoneInfo("America/New_York")

TRADE_START = (9, 45)
TRADE_END   = (11, 30)


class MESStrategyWrapper:
    """
    Wraps MESStrategyRunner as a pluggable bot strategy.

    Public interface (matches bot's strategy contract):
      check_signal(symbol)        → signal dict or None
      check_breakout(symbol, px)  → alias
      ingest_tick(symbol, ts, px) → feed price/bar data
      record_trade_result(pnl)    → notify strategy of closed-trade PnL
      analyze_market_context(sym) → dashboard data dict
      reset_strategy()            → force session reset
    """

    VALID_SYMBOLS = {"MES", "ES"}

    def __init__(self, data_manager, symbol: str = "MES", qty: int = 1):
        sym = symbol.upper()
        if sym not in self.VALID_SYMBOLS:
            raise ValueError(
                f"MESStrategyWrapper only supports {self.VALID_SYMBOLS}, got {sym!r}"
            )
        self.dm = data_manager
        self.symbol = sym
        self.qty = qty
        self.logger = logging.getLogger(__name__)

        self._session_date: Optional[date] = None
        self._runner: Optional[MESStrategyRunner] = None
        self._pending_signal = None
        self._last_5m_window: Optional[int] = None
        self._pdh: float = 0.0
        self._pdl: float = 0.0

    # ------------------------------------------------------------------ #
    # Session management                                                    #
    # ------------------------------------------------------------------ #

    def _reset_if_new_session(self) -> None:
        today = datetime.now(ET_TZ).date()
        if self._session_date == today:
            return

        self._session_date = today
        self._pending_signal = None
        self._last_5m_window = None

        self._pdh, self._pdl = self._get_prev_day_hl()

        self._runner = MESStrategyRunner(
            pdh=self._pdh,
            pdl=self._pdl,
            news_times=[],
        )
        self._seed_today()

        if not getattr(self, "_levels_ok", False):
            # stale or invented levels: switch the PDH/PDL setup off for today
            self._runner.pdh_pdl.pdh_traded = True
            self._runner.pdh_pdl.pdl_traded = True
            self.logger.warning("MESWrapper: PDH/PDL setup DISABLED today - previous-day bars missing in Supabase")
            notify("⚠️ No previous-day bars in Supabase - PDH/PDL setup disabled today. Check the IBKR ingester.")

        self.logger.info(
            "MESStrategy session reset | date=%s | PDH=%.2f PDL=%.2f",
            today, self._pdh, self._pdl,
        )

    def _get_prev_day_hl(self):
        """Return (PDH, PDL) from the most recent *trading* day.
            Walks back day-by-day (skips weekends/holidays). Calendar-yesterday
            breaks on Mondays (Sunday = 0 bars) and used to fall back to garbage
            current-price ± 20 levels, silently disabling the PDH/PDL setup.
        """
        self._levels_ok = False
        try:
            if hasattr(self.dm, "get_historical_bars") and hasattr(self.dm, "_et_to_utc_timestamp"):
                for back in range(1, 8):
                    d = (date.today() - timedelta(days=back)).strftime("%Y-%m-%d")
                    start = self.dm._et_to_utc_timestamp(d, "09:30:00")
                    end   = self.dm._et_to_utc_timestamp(d, "16:00:00")
                    bars = self.dm.get_historical_bars(self.symbol, start, end) or []

                    if bars:
                        pdh = max(float(b.get("high") or b.get("h", 0)) for b in bars)
                        pdl = min(float(b.get("low")  or b.get("l", 0)) for b in bars)
                        expected = date.today() - timedelta(days=1)
                        while expected.weekday() >= 5:          # skip Sat/Sun
                            expected -= timedelta(days=1)
                        self._levels_ok = (d == expected.strftime("%Y-%m-%d"))
                        if self._levels_ok:
                            self.logger.info("MESWrapper: prev-day levels from %s -> PDH=%.2f PDL=%.2f",
                                             d, pdh, pdl)
                        else:
                            self.logger.warning("MESWrapper: STALE prev-day levels from %s (expected %s) "
                                                "-> PDH=%.2f PDL=%.2f", d, expected, pdh, pdl)
                        return pdh, pdl


                self.logger.warning("MESWrapper: no trading day with bars in last 7 days")

            # Legacy fallbacks (only if the helpers above are unavailable)
            bars = []
            if hasattr(self.dm, "get_previous_day_bars"):
                bars = self.dm.get_previous_day_bars(self.symbol) or []
            elif hasattr(self.dm, "query_yesterday_bars"):
                bars = self.dm.query_yesterday_bars(self.symbol, start_hour=9, start_min=30,
                                                    end_hour=16, end_min=0) or []
            if bars:
                pdh = max(float(b.get("high") or b.get("h", 0)) for b in bars)
                pdl = min(float(b.get("low")  or b.get("l", 0)) for b in bars)
                return pdh, pdl

            px = float(self.dm.get_current_price(self.symbol) or 5000.0)
            self.logger.warning("MESWrapper: FALLBACK PDH/PDL around current price %.2f (no history)", px)
            return px + 20.0, px - 20.0

        except Exception as exc:
            self.logger.warning("MESWrapper: could not fetch prev-day bars: %s", exc)
            return 5020.0, 4980.0

    # ------------------------------------------------------------------ #
    # Bar feeding with 5-minute aggregation                              #
    # ------------------------------------------------------------------ #

    def ingest_tick(self, symbol: str, ts_epoch: float, price: Optional[float]) -> None:
        if price is None:
            return
        self._reset_if_new_session()
        if not self._runner:
            return

        try:
            raw_bars = self.dm.live.get_last_n(symbol, n=7)
            if not raw_bars:
                return

            tagged = []
            for b in raw_bars:
                ts = float(getattr(b, "ts_open", 0))
                tagged.append({
                    "ts": ts,
                    "win5": int(ts // 300) * 300,
                    "o": float(b.open),
                    "h": float(b.high),
                    "l": float(b.low),
                    "c": float(b.close),
                    "v": float(getattr(b, "volume", 1)),
                })

            current_win = tagged[-1]["win5"]

            unseen = sorted(
                win for win in set(b["win5"] for b in tagged)
                if win < current_win
                and (self._last_5m_window is None or win > self._last_5m_window)
            )

            for win in unseen:
                wb = [b for b in tagged if b["win5"] == win]
                agg = {
                    "o": wb[0]["o"],
                    "h": max(b["h"] for b in wb),
                    "l": min(b["l"] for b in wb),
                    "c": wb[-1]["c"],
                    "v": sum(b["v"] for b in wb),
                    "ts": win,
                }
                self._last_5m_window = win

                sig = self._runner.on_completed_chart_bar(agg)
                if sig is not None and self._pending_signal is None:
                    self._pending_signal = sig

        except Exception as exc:
            self.logger.debug("MESWrapper ingest_tick failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Signal check                                                          #
    # ------------------------------------------------------------------ #

    def check_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        self._reset_if_new_session()
        if not self._runner:
            return None

        now_et = datetime.now(ET_TZ)
        h, m = now_et.hour, now_et.minute
        if (h, m) < TRADE_START or (h, m) >= TRADE_END:
            return None

        if self._pending_signal is None:
            return None

        sig = self._pending_signal
        self._pending_signal = None

        # Normalise direction — handle both enum and string
        raw_dir = getattr(sig, "direction", None)
        if raw_dir is None:
            return None
        dir_name = raw_dir.name if hasattr(raw_dir, "name") else str(raw_dir).upper()
        direction = "BUY" if "LONG" in dir_name else "SELL"

        entry  = float(getattr(sig, "entry",    0.0))
        stop   = float(getattr(sig, "stop",     0.0))
        target = float(getattr(sig, "target_1", 0.0)) or float(getattr(sig, "target", 0.0))
        setup  = str(getattr(getattr(sig, "setup", None), "value", "signal"))

        return {
            "type":   direction,
            "symbol": symbol,
            "price":  entry,
            "qty":    self.qty,
            "reason": f"MESRunner-{setup}",
            "context": {
                "setup":       setup,
                "stop_price":  stop,
                "stop_est_points": abs(entry - stop),
                "target_1":    target,
                "pdh":         self._pdh,
                "pdl":         self._pdl,
            },
        }

    def check_breakout(self, symbol: str, current_price=None) -> Optional[Dict[str, Any]]:
        return self.check_signal(symbol)

    # ------------------------------------------------------------------ #
    # Trade result                                                          #
    # ------------------------------------------------------------------ #

    def record_trade_result(self, pnl_usd: float) -> None:
        if not self._runner:
            return
        rm = getattr(self._runner, "risk_manager", None)
        if rm and hasattr(rm, "record"):
            rm.record(pnl_usd)

    # ------------------------------------------------------------------ #
    # Dashboard                                                             #
    # ------------------------------------------------------------------ #

    def reset_strategy(self) -> None:
        self._session_date = None

    def analyze_market_context(self, symbol: str = None) -> Dict[str, Any]:
        self._reset_if_new_session()
        now_et = datetime.now(ET_TZ)
        h, m = now_et.hour, now_et.minute
        in_session = TRADE_START <= (h, m) < TRADE_END

        daily_pnl = 0.0
        locked = False
        if self._runner:
            rm = getattr(self._runner, "risk_manager", None)
            if rm:
                daily_pnl = float(getattr(rm, "daily_pnl", 0.0))
                locked = bool(getattr(rm, "locked", False))

        return {
            "strategy":    "MESRunner",
            "symbol":      symbol or self.symbol,
            "pdh":         self._pdh,
            "pdl":         self._pdl,
            "daily_pnl":   daily_pnl,
            "bot_paused":  locked,
            "in_session":  in_session,
        }


    def _seed_today(self) -> None:
        """Seed the runner with today's completed 5-min bars (09:30 ET → now) from
        Supabase, so the opening range (built 09:30–09:45) and VWAP exist even when
        the bot starts after 09:45. Without this, a late start = no OR = no ORB all day."""
        try:
            if not (hasattr(self.dm, "get_historical_bars") and
                    hasattr(self.dm, "_et_to_utc_timestamp")):
                return
            from datetime import timezone, timedelta
            now_et = datetime.now(ET_TZ)
            if (now_et.hour, now_et.minute) < (9, 30):
                return
            today = now_et.date().strftime("%Y-%m-%d")
            start = self.dm._et_to_utc_timestamp(today, "09:30:00")
            end   = (now_et - timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
            rows = self.dm.get_historical_bars(self.symbol, start, end) or []
            if not rows:
                self.logger.info("MESWrapper: no today bars to seed (OR builds from live)")
                return

            buckets = {}
            for r in rows:
                s = str(r.get("ts") or "").replace(" ", "T")
                if s.endswith("+00"):
                    s = s[:-3] + "+00:00"
                try:
                    epoch = datetime.fromisoformat(s).timestamp()
                except Exception:
                    continue
                buckets.setdefault(int(epoch // 300) * 300, []).append(r)

            now_win = int(now_et.timestamp() // 300) * 300
            bars5 = []
            for win in sorted(buckets):
                if win >= now_win:
                    continue
                grp = buckets[win]
                bars5.append({
                    "ts": float(win),
                    "o": float(grp[0].get("open")  or grp[0].get("o", 0)),
                    "h": max(float(g.get("high") or g.get("h", 0)) for g in grp),
                    "l": min(float(g.get("low")  or g.get("l", 0)) for g in grp),
                    "c": float(grp[-1].get("close") or grp[-1].get("c", 0)),
                    "v": sum(float(g.get("volume") or g.get("v", 1)) for g in grp),
                })
            if not bars5:
                return
            self._runner.rebuild_from_bars(bars5)
            self._last_5m_window = bars5[-1]["ts"]
            self.logger.info("MESWrapper: seeded %d today 5-min bars (OR + VWAP ready)", len(bars5))
        except Exception as exc:
            self.logger.warning("MESWrapper: today-seed failed: %s", exc)

