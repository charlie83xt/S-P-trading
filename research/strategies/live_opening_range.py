"""Live OpeningRangeStrategy (opening_range_strategy.py), settings as built by strategy_manager.py.
Tested in the morning window (it has no session filter of its own)."""
from research.replay import LiveStrategyReplay   # must come first: installs the data_manager stub
import opening_range_strategy as mod  # noqa: E402


class Strategy(LiveStrategyReplay):
    name = "live_opening_range"
    modules = (mod,)
    entry_window = (15, 120)

    def build(self, dm):
        return mod.OpeningRangeStrategy(data_manager=dm, opening_range_minutes=30, breakout_threshold=0.05,
                                        stop_loss_percent=2.0, take_profit_percent=4.0,
                                        breakout_points=2.0, min_move_from_or=1.5)
