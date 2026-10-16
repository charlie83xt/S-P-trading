"""Live PreviousDayHighLowStrategy (previous_day_high_low_strategy.py), settings as built by
strategy_manager.py. Tested in the morning window, your trading period."""
import previous_day_high_low_strategy as mod
from research.replay import LiveStrategyReplay


class Strategy(LiveStrategyReplay):
    name = "live_prev_day_hl"
    modules = (mod,)
    entry_window = (0, 120)                       # 09:30-11:30 ET

    def build(self, dm):
        return mod.PreviousDayHighLowStrategy(data_manager=dm, shadow_ratio=2.0, max_other_shadow=0.3,
                                              min_body_pct=0.05, tolerance_pct=0.002,
                                              max_trades_per_day=4, qty=1)
