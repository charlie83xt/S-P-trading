"""Live MeanReversionStrategy (mean_reversion_strategy.py), settings as built by strategy_manager.py.
Its own session filter only allows 12:00-16:00 ET, so it is tested in that window."""
from datetime import time

import mean_reversion_strategy as mod
from research.replay import DEFAULT_EXITS, LiveStrategyReplay


class Strategy(LiveStrategyReplay):
    name = "live_mean_reversion"
    modules = (mod,)
    entry_window = (150, 385)                     # 12:00-15:55 ET
    exits = {**DEFAULT_EXITS, "exit_at_m": 385}

    def build(self, dm):
        return mod.MeanReversionStrategy(
            data_manager=dm, lookback=20, std_dev=2.0, max_trades_per_day=4, qty=1,
            session_start=time(12, 0), session_end=time(16, 0), use_session_filter=True,
            min_bandwidth_pct=0.0010, cooldown_bars=3, require_reentry_confirmation=True)
