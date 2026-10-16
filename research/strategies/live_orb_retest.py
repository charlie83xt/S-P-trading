"""Live ORBRetestStrategy (orb_retest_strategy.py), settings as built by strategy_manager.py."""
from datetime import time

import orb_retest_strategy as mod
from research.replay import LiveStrategyReplay


class Strategy(LiveStrategyReplay):
    name = "live_orb_retest"
    modules = (mod,)
    entry_window = (15, 120)                      # its live window 09:45-11:30 ET

    def build(self, dm):
        return mod.ORBRetestStrategy(
            data_manager=dm, opening_range_minutes=30, breakout_points=2.0, breakout_threshold_pct=0.0,
            retest_tolerance_points=1.0, max_stop_points=10.0, min_signal_gap_sec=30.0,
            max_trades_per_day=2, allow_only_one_side_per_day=True,
            trade_start_time_et=(9, 45), trade_end_time_et=(11, 30),
            use_sma_filter=True, sma_timeframe="5m")
