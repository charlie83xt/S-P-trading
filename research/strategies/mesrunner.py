"""The live bot's MESStrategyRunner (mes_strategy_runner.py in the repo root), replayed on history
with exits like the live bot: the strategy's own stop, 10-pt target, breakeven at +4 locking 1,
flatten at 11:33 ET. Run the harness from the repo root so the import below resolves."""
import datetime
import logging
from zoneinfo import ZoneInfo

import mes_strategy_runner as M
from research.backtest import Entry

logging.getLogger("mes_strategies").setLevel(logging.CRITICAL)
ET = ZoneInfo("America/New_York")


class Strategy:
    name = "mesrunner_live_like"

    def __init__(self):
        self.params = {"target_pts": 10.0, "breakeven_at": 4.0, "breakeven_lock": 1.0, "exit_at_m": 123}

    def reset(self, day):
        self.runner = M.MESStrategyRunner(pdh=day.pdh, pdl=day.pdl, news_times=[])
        self.t0 = datetime.datetime.combine(day.date, datetime.time(9, 30), ET).timestamp()

    def on_bar(self, i, bars):
        m = int(bars.m[i])
        if m % 5 != 4 or i < 4 or int(bars.m[i - 4]) != m - 4:
            return None                            # act only when a full 5-minute bar completes
        s = slice(i - 4, i + 1)
        bar = {"ts": self.t0 + (m - 4) * 60, "o": float(bars.open[i - 4]), "h": float(bars.high[s].max()),
               "l": float(bars.low[s].min()), "c": float(bars.close[i]), "v": float(bars.volume[s].sum())}
        sig = self.runner.on_completed_chart_bar(bar)
        if not sig:
            return None
        self.runner.trade.reset()
        p = self.params
        return Entry(side=1 if sig.direction == M.Direction.LONG else -1,
                     stop_pts=max(abs(float(bars.close[i]) - sig.stop), 0.25),
                     target_pts=p["target_pts"], breakeven_at=p["breakeven_at"],
                     breakeven_lock=p["breakeven_lock"], exit_at_m=p["exit_at_m"])
