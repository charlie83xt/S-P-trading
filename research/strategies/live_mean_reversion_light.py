"""Live MeanReversionStrategyLight ("MeanReversionOld"), settings as built by strategy_manager.py.
No session filter of its own; tested in the morning window, your trading period."""
import mean_reversion_strategy_light as mod
from research.replay import LiveStrategyReplay


class Strategy(LiveStrategyReplay):
    name = "live_mean_reversion_light"
    modules = (mod,)
    entry_window = (15, 120)

    def build(self, dm):
        return mod.MeanReversionStrategyLight(data_manager=dm, lookback=20, std_dev=2.0, max_trades_per_day=4)
