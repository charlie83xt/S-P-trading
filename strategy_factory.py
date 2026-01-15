# strategy_factory.py
from opening_range_strategy import OpeningRangeStrategy
# from test_strategy import TestStrategy
from minimal_test_strategy import TestStrategy
from typing import Any, Dict


_STRATEGIES = {
    "OpeningRange": OpeningRangeStrategy,
    "Test": TestStrategy
}

def create(name: str, *, data_manager, **params):
    """
    Construct a strategy instance by name, normalising param names.
    Required dependency: data_manager (injected by the TradingBot)
    """
    name = (name or "OpeningRange").strip()

    if name == "OpeningRange":
        # normalise params coming from UI/config
        minutes = (
            params.get("opening_range_minutes")
            or params.get("minutes")
            or 30
        )
        threshold = (
            params.get("breakout_threshold")
            or params.get("threshold")
            or 0.1
        )
        # return OpeningRangeStrategy(
        #     data_manager = data_manager, 
        #     opening_range_minutes = minutes, 
        #     breakout_threshold = threshold
        # )
        stop_loss = params.get("stop_loss_percent", 2.0)
        take_profit = params.get("take_profit_percent", 4.0)
        return OpeningRangeStrategy(
            data_manager=data_manager,
            opening_range_minutes=float(minutes),
            breakout_threshold=float(threshold),
            stop_loss_percent=float(stop_loss),
            take_profit_percent=float(take_profit),
        )


    if name == "Test":
        # UI sends 'breakout_threshold' - map to pct_threshold
        pct = params.get("pct_threshold", params.get("breakout_threshold", 0.001))
        abs_thr = params.get("abs_threshold", 0.0)
        qty = int(params.get("qty", 1))
        # Adapt to our TestStrategy signature as needed
        # threshold = (
        #     params.get("breakout_threshold") 
        #     or params.get("threshold") 
        #     or 0.001
        # )
        # Some versions or TestStrategy accept 'threshold' in __init__, some don't
        try:
            return TestStrategy(
                data_manager=data_manager, 
                pct_threshold=float(pct),
                abs_threshold=float(abs_thr),
                qty=qty
            )
        except TypeError:
            # Fallback to old signature: set attribute after construction if present.
            s = TestStrategy(data_manager=data_manager)
            if hasattr(s, "threshold"):
                try:
                    s.threshold = float(threshold)
                except Exception:
                    pass
            return s

    # else:
    #     avail = ", ".join(sorted(_STRATEGIES.keys()))
    # cls = _STRATEGIES.get(name)
    avail = ", ".join(sorted(_STRATEGIES.keys()))
    raise ValueError(f"Unknown strategy '{name}' .Available: {avail}")
    # return cls(**params)

