# strategy_factory.py
"""
Strategy Factory - Creates strategy instances with proper parameter normalization.

Supported strategies:
- OpeningRange: Simple opening range breakout
- ORBRetest: Opening range break + retest with pattern confirmation (recommended)
- Test: Minimal test strategy for debugging
"""

from opening_range_strategy import OpeningRangeStrategy
from minimal_test_strategy import TestStrategy
from typing import Any, Dict

# Try to import ORB Retest strategy (your cousin's recommendation)
try:
    from orb_retest_strategy import ORBRetestStrategy
    _HAS_ORB_RETEST = True
except ImportError:
    _HAS_ORB_RETEST = False
    ORBRetestStrategy = None


_STRATEGIES = {
    "OpeningRange": {
        "class": OpeningRangeStrategy,
        "description": "Simple opening range breakout (0-2 trades/day)",
    },
    "ORBRetest": {
        "class": ORBRetestStrategy,
        "description": "ORB break + retest + pattern confirmation (2-6 trades/day)",
        "available": _HAS_ORB_RETEST,
    },
    "Test": {
        "class": TestStrategy,
        "description": "Minimal test strategy for debugging",
    },
}


def create(name: str, *, data_manager, **params):
    """
    Construct a strategy instance by name, normalizing param names.
    
    Args:
        name: Strategy name ("OpeningRange", "ORBRetest", "Test")
        data_manager: DataManager instance (required dependency)
        **params: Strategy-specific parameters
        
    Returns:
        Strategy instance
        
    Raises:
        ValueError: If strategy name is unknown or unavailable
    """
    name = (name or "OpeningRange").strip()

    # ========================================================================
    # OPENING RANGE STRATEGY (Simple - Original)
    # ========================================================================
    if name == "OpeningRange":
        # Normalize params from UI/config
        minutes = (
            params.get("opening_range_minutes")
            or params.get("minutes")
            or 30
        )
        threshold = (
            params.get("breakout_threshold")
            or params.get("threshold")
            or 0.05
        )
        stop_loss = params.get("stop_loss_percent", 2.0)
        take_profit = params.get("take_profit_percent", 4.0)
        
        # NEW: Pass breakout_points and min_move_from_or from config
        breakout_points = params.get("breakout_points", 2.0)
        min_move_from_or = params.get("min_move_from_or", 1.5)
        
        return OpeningRangeStrategy(
            data_manager=data_manager,
            opening_range_minutes=int(minutes),
            breakout_threshold=float(threshold),
            stop_loss_percent=float(stop_loss),
            take_profit_percent=float(take_profit),
            breakout_points=float(breakout_points),
            min_move_from_or=float(min_move_from_or),
        )

    # ========================================================================
    # ORB BREAK + RETEST STRATEGY (Recommended - Your Cousin's)
    # ========================================================================
    elif name == "ORBRetest":
        if not _HAS_ORB_RETEST:
            raise ValueError(
                "ORBRetest strategy not available. "
                "Make sure orb_retest_strategy.py is in your project directory."
            )
        
        return ORBRetestStrategy(
            data_manager=data_manager,
            opening_range_minutes=int(params.get("opening_range_minutes", 15)),
            breakout_points=float(params.get("breakout_points", 2.0)),
            breakout_threshold_pct=float(params.get("breakout_threshold_pct", 0.0)),
            retest_tolerance_points=float(params.get("retest_tolerance_points", 1.0)),
            max_stop_points=float(params.get("max_stop_points", 10.0)),
            min_signal_gap_sec=float(params.get("min_signal_gap_sec", 30.0)),
            max_trades_per_day=int(params.get("max_trades_per_day", 2)),
            allow_only_one_side_per_day=bool(params.get("allow_only_one_side_per_day", True)),
            trade_start_time_et=params.get("trade_start_time_et", (9, 45)),
            trade_end_time_et=params.get("trade_end_time_et", (12, 0)),
            use_sma_filter=bool(params.get("use_sma_filter", True)),
            sma_timeframe=params.get("sma_timeframe", "5m"),
        )

    # ========================================================================
    # TEST STRATEGY (Debugging)
    # ========================================================================
    elif name == "Test":
        # UI sends 'breakout_threshold' - map to pct_threshold
        pct = params.get("pct_threshold", params.get("breakout_threshold", 0.001))
        abs_thr = params.get("abs_threshold", 0.0)
        qty = int(params.get("qty", 1))
        
        try:
            return TestStrategy(
                data_manager=data_manager,
                pct_threshold=float(pct),
                abs_threshold=float(abs_thr),
                qty=qty
            )
        except TypeError:
            # Fallback to old signature
            s = TestStrategy(data_manager=data_manager)
            if hasattr(s, "threshold"):
                try:
                    s.threshold = float(pct)
                except Exception:
                    pass
            return s

    # ========================================================================
    # UNKNOWN STRATEGY
    # ========================================================================
    else:
        available = []
        for strat_name, info in _STRATEGIES.items():
            if isinstance(info, dict):
                if info.get("available", True):
                    desc = info.get("description", "")
                    available.append(f"{strat_name} - {desc}")
            else:
                available.append(strat_name)
        
        avail_str = "\n  ".join(available)
        raise ValueError(
            f"Unknown strategy '{name}'.\n"
            f"Available strategies:\n  {avail_str}"
        )


def list_strategies():
    """
    Returns list of available strategies with descriptions.
    
    Returns:
        List of dicts with keys: name, description, available
    """
    result = []
    for name, info in _STRATEGIES.items():
        if isinstance(info, dict):
            result.append({
                "name": name,
                "description": info.get("description", ""),
                "available": info.get("available", True),
            })
        else:
            result.append({
                "name": name,
                "description": "",
                "available": True,
            })
    return result
