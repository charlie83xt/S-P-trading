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
from mean_reversion_strategy import MeanReversionStrategy
from mean_reversion_strategy_light import MeanReversionStrategyLight
from previous_day_high_low_strategy import PreviousDayHighLowStrategy
from typing import Any, Dict
from datetime import time

# Try to import ORB Retest strategy (your cousin's recommendation)
try:
    from orb_retest_strategy import ORBRetestStrategy
    _HAS_ORB_RETEST = True
except ImportError:
    _HAS_ORB_RETEST = False
    ORBRetestStrategy = None

# Try to import MNQ VWAP strategy (another cousin's recommendation)
try:
    from mnq_vwap_strategy import MNQVwapStrategy
    _HAS_MNQ_VWAP = True
except ImportError:
    _HAS_MNQ_VWAP = False
    MNQVwapStrategy = None

# Try to import MES Runner strategy (another cousin's recommendation)
try:
    from mes_strategy_wrapper import MESStrategyWrapper
    _HAS_MES_RUNNER = True
except ImportError:
    _HAS_MES_RUNNER = False
    MESStrategyWrapper = None


_STRATEGIES = {
    "ORBRetest": {
        "class": ORBRetestStrategy,
        "description": "ORB break + retest + pattern confirmation (2-6 trades/day)",
        "available": _HAS_ORB_RETEST,
        "enabled": True, # Default Strategy
    },
    "MeanReversion": {
        "class": MeanReversionStrategy,
        "description": "Bollinger Bands mean reversion (12 PM - 4 PM ET)",
        "available": _HAS_ORB_RETEST,
        "enabled": True, # Default strategy
    },
    "MeanReversionOld": {
        "class": MeanReversionStrategyLight,
        "description": "Bollinger Bands mean reversion (12 PM - 4 PM ET)",
        "available": _HAS_ORB_RETEST,
        "enabled": True, # Default strategy
    },
    "OpeningRange": {
        "class": OpeningRangeStrategy,
        "description": "Simple opening range breakout (0-2 trades/day)",
        "available": True,
        "enabled": False, # DISABLED - superseded by ORBRetest
    },
    "MNQVwap": {
        "class": MNQVwapStrategy,
        "description": "VWAP Fade + Volume Profile for NQ/MNQ",
        "available": _HAS_MNQ_VWAP,
        "enabled": True, # Default strategy
    },
    "Test": {
        "class": TestStrategy,
        "description": "Minimal test strategy for debugging",
        "available": True,
        "enabled": False, # Only for testing
    },
    "MESRunner": {
        "class": MESStrategyWrapper,
        "description": "ORB + PDH/PDL + VWAP Reclaim suite for MES/ES (9:45-11:30 ET)",
        "available": _HAS_MES_RUNNER,
        "enabled": True, #
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
            trade_end_time_et=params.get("trade_end_time_et", (11, 30)),
            use_sma_filter=bool(params.get("use_sma_filter", True)),
            sma_timeframe=params.get("sma_timeframe", "5m"),
        )

    # ========================================================================
    # MEAN REVERSION STRATEGY (Afternoon Session)
    # ========================================================================

    elif name == "MeanReversion":
        return MeanReversionStrategy(
            data_manager=data_manager,
            lookback=int(params.get("lookback", 20)),
            std_dev=float(params.get("std_dev", 2.0)),
            max_trades_per_day=int(params.get("max_trades_per_day", 4)),
            qty=int(params.get("qty", 1)),
            session_start=time(12, 0),
            session_end=time(16, 0),
            use_session_filter=True,
            min_bandwidth_pct=float(params.get("min_bandwidth_pct", 0.0010)),
            cooldown_bars=int(params.get("cooldown_bars", 3)),
            require_reentry_confirmation=bool(params.get("require_reentry_confirmation", True)),
        )

    # ========================================================================
    # MEAN REVERSION STRATEGY (Afternoon Session)
    # ========================================================================

    elif name == "MeanReversionOld":
        return MeanReversionStrategyLight(
            data_manager=data_manager,
            lookback=int(params.get("lookback", 20)),
            std_dev=float(params.get("std_dev", 2.0)),
            max_trades_per_day=int(params.get("max_trades_per_day", 4)),
        )

    # ========================================================================
    # MEAN REVERSION STRATEGY (Afternoon Session)
    # ========================================================================

    elif name == "MNQVwap":
        return MNQVwapStrategy(
            data_manager=data_manager,
            symbol=params.get("symbol", "MNQ"),
            qty=int(params.get("qty", 1)),
        )

    # ========================================================================
    # MES STRATEGY RUNNER (ORB + PDH/PDL + VWAP Reclaim suite)
    # ========================================================================
    elif name == "MESRunner":
        if not _HAS_MES_RUNNER:
            raise ValueError(
                "MESRunner not available. "
                "Make sure mes_strategy_runner.py and mes_strategy_wrapper.py are present."
            )
        return MESStrategyWrapper(
            data_manager=data_manager,
            symbol=params.get("symbol", "MES"),
            qty=int(params.get("qty", 1)),
        )

    # ========================================================================
    # PREVIOUS DAY HIGH/LOW REVERSAL (Afternoon Session)
    # ========================================================================

    elif name == "PreviousDayHL":
        return PreviousDayHighLowStrategy(
            data_manager=data_manager,
            shadow_ratio=float(params.get("shadow_ratio", 2.0)),
            max_other_shadow=float(params.get("max_other_shadow", 0.3)),
            min_body_pct=float(params.get("min_body_pct", 0.05)),
            tolerance_pct=float(params.get("tolerance_pct", 0.002)),
            max_trades_per_day=int(params.get("max_trades", 4)),
            qty=int(params.get("qty", 1)),
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
                # if info.get("available", True):
                if info.get("available", True) and info.get("enabled", True):
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
                "enabled": info.get("enabled", True),
            })
        else:
            result.append({
                "name": name,
                "description": "",
                "available": True,
                "enabled": True,
            })
    return result
