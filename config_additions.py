# ===================================================================
# CONFIG.PY ADDITIONS FOR ORB RETEST STRATEGY
# ===================================================================
# Add these lines to your existing config.py file
# (These complement your existing config settings)
# ===================================================================

import os

# -------------------------------------------------------------------
# ORB BREAK + RETEST STRATEGY (Cousin's Recommendation)
# -------------------------------------------------------------------
ORB_RETEST_OR_MINUTES = int(os.getenv("ORB_RETEST_OR_MINUTES", "15"))
ORB_RETEST_BREAKOUT_POINTS = float(os.getenv("ORB_RETEST_BREAKOUT_PTS", "2.0"))
ORB_RETEST_BREAKOUT_PCT = float(os.getenv("ORB_RETEST_BREAKOUT_PCT", "0.0"))
ORB_RETEST_TOLERANCE = float(os.getenv("ORB_RETEST_TOLERANCE", "1.0"))
ORB_RETEST_MAX_STOP = float(os.getenv("ORB_RETEST_MAX_STOP", "10.0"))
ORB_RETEST_MIN_GAP_SEC = float(os.getenv("ORB_RETEST_MIN_GAP_SEC", "30.0"))
ORB_RETEST_MAX_TRADES = int(os.getenv("ORB_RETEST_MAX_TRADES", "2"))
ORB_RETEST_ONE_SIDE_ONLY = bool(os.getenv("ORB_RETEST_ONE_SIDE", "true").lower() == "true")

# Parse trade window times (format: "9,45" → (9, 45))
_start_str = os.getenv("ORB_RETEST_START", "9,45")
_end_str = os.getenv("ORB_RETEST_END", "12,0")
ORB_RETEST_TRADE_START = tuple(map(int, _start_str.split(",")))
ORB_RETEST_TRADE_END = tuple(map(int, _end_str.split(",")))

ORB_RETEST_USE_SMA = bool(os.getenv("ORB_RETEST_USE_SMA", "true").lower() == "true")
ORB_RETEST_SMA_TIMEFRAME = os.getenv("ORB_RETEST_SMA_TF", "5m")

# -------------------------------------------------------------------
# SIMPLE OR STRATEGY FIXES (New Parameters)
# -------------------------------------------------------------------
# These were previously read directly from env in strategy - now in config
BREAKOUT_POINTS = float(os.getenv("BREAKOUT_POINTS", "2.0"))
MIN_MOVE_FROM_OR = float(os.getenv("MIN_MOVE_FROM_OR", "1.5"))

# -------------------------------------------------------------------
# RISK MANAGEMENT (Points-Based - NEW)
# -------------------------------------------------------------------
STOP_LOSS_POINTS = float(os.getenv("STOP_LOSS_POINTS", "4.0"))
TAKE_PROFIT_POINTS = float(os.getenv("TAKE_PROFIT_POINTS", "6.0"))

# Adaptive stops (bounds for dynamic calculation)
STOP_LOSS_BASE_POINTS = float(os.getenv("STOP_LOSS_BASE_POINTS", "4.0"))
TAKE_PROFIT_BASE_POINTS = float(os.getenv("TAKE_PROFIT_BASE_POINTS", "6.0"))
MIN_STOP_LOSS_POINTS = float(os.getenv("MIN_STOP_LOSS_POINTS", "2.0"))
MAX_STOP_LOSS_POINTS = float(os.getenv("MAX_STOP_LOSS_POINTS", "12.0"))
MIN_TAKE_PROFIT_POINTS = float(os.getenv("MIN_TAKE_PROFIT_POINTS", "4.0"))
MAX_TAKE_PROFIT_POINTS = float(os.getenv("MAX_TAKE_PROFIT_POINTS", "20.0"))

# -------------------------------------------------------------------
# VOLUME TRACKING (NEW)
# -------------------------------------------------------------------
VOLUME_LOOKBACK_BARS = int(os.getenv("VOLUME_LOOKBACK_BARS", "20"))
HIGH_VOLUME_THRESHOLD = float(os.getenv("HIGH_VOLUME_THRESHOLD", "1.5"))
LOW_VOLUME_THRESHOLD = float(os.getenv("LOW_VOLUME_THRESHOLD", "0.5"))

# -------------------------------------------------------------------
# DATA MANAGEMENT (NEW)
# -------------------------------------------------------------------
KEEP_BARS = int(os.getenv("KEEP_BARS", "480"))  # 8 hours of 1m bars
DATA_REFRESH_INTERVAL = float(os.getenv("DATA_REFRESH_INTERVAL", "1.0"))


# ===================================================================
# USAGE IN TRADING BOT
# ===================================================================
"""
# In your trading_bot.py or wherever you create strategies:

from config import Config
from strategy_factory import create

cfg = Config()

# Create ORB Retest strategy with config values
orb_retest = create("ORBRetest", data_manager=dm, **{
    "opening_range_minutes": cfg.ORB_RETEST_OR_MINUTES,
    "breakout_points": cfg.ORB_RETEST_BREAKOUT_POINTS,
    "breakout_threshold_pct": cfg.ORB_RETEST_BREAKOUT_PCT,
    "retest_tolerance_points": cfg.ORB_RETEST_TOLERANCE,
    "max_stop_points": cfg.ORB_RETEST_MAX_STOP,
    "min_signal_gap_sec": cfg.ORB_RETEST_MIN_GAP_SEC,
    "max_trades_per_day": cfg.ORB_RETEST_MAX_TRADES,
    "allow_only_one_side_per_day": cfg.ORB_RETEST_ONE_SIDE_ONLY,
    "trade_start_time_et": cfg.ORB_RETEST_TRADE_START,
    "trade_end_time_et": cfg.ORB_RETEST_TRADE_END,
    "use_sma_filter": cfg.ORB_RETEST_USE_SMA,
    "sma_timeframe": cfg.ORB_RETEST_SMA_TIMEFRAME,
})

# Or let strategy_factory handle defaults:
orb_retest = create("ORBRetest", data_manager=dm)

# Create Simple OR strategy with FIXED parameters
simple_or = create("OpeningRange", data_manager=dm, **{
    "opening_range_minutes": cfg.OPENING_RANGE_MINUTES,
    "breakout_threshold": cfg.BREAKOUT_THRESHOLD_PERCENT,
    "breakout_points": cfg.BREAKOUT_POINTS,           # ← Now from config!
    "min_move_from_or": cfg.MIN_MOVE_FROM_OR,         # ← Now from config!
    "stop_loss_percent": cfg.STOP_LOSS_PERCENTAGE,
    "take_profit_percent": cfg.TAKE_PROFIT_PERCENTAGE,
})
"""

# ===================================================================
# PARAMETER EXPLANATIONS
# ===================================================================
"""
ORB_RETEST_OR_MINUTES (15):
  - Opening range period in minutes after 9:30 AM ET
  - 15 minutes = 9:30-9:45 AM (standard OR period)
  - Shorter = more volatile OR, more signals
  - Longer = more stable OR, fewer signals

ORB_RETEST_BREAKOUT_POINTS (2.0):
  - Price must close beyond OR boundary by this many points
  - MES: 2pts = $10 move
  - Lower = more signals (more sensitive)
  - Higher = fewer signals (more conservative)

ORB_RETEST_TOLERANCE (1.0):
  - How close retest must get to OR level
  - 1pt = retest must touch within 1pt of OR boundary
  - Lower = stricter retest requirement
  - Higher = more lenient (more signals)

ORB_RETEST_MAX_STOP (10.0):
  - Maximum risk per trade in points
  - 10pts on MES = $50 risk
  - If trigger candle has >10pt stop, signal rejected
  - This prevents high-risk setups

ORB_RETEST_MAX_TRADES (2):
  - Max trades per day for this strategy
  - Prevents overtrading
  - Recommended: 2-4 for discipline

ORB_RETEST_ONE_SIDE (true):
  - If true: after first breakout, ignore opposite side
  - Prevents whipsaw if OR breaks both ways
  - Recommended: true for beginners

ORB_RETEST_USE_SMA (true):
  - Enable SMA20/200 trend filter
  - Longs only if price > SMA200 and SMA20 rising
  - Shorts only if price < SMA200 and SMA20 falling
  - Recommended: true for higher win rate

BREAKOUT_POINTS (2.0) - Simple OR:
  - Same concept as ORB Retest but for simple strategy
  - Now properly wired through config.py

MIN_MOVE_FROM_OR (1.5) - Simple OR:
  - Additional filter: price must move 1.5pts beyond trigger
  - Prevents tiny wiggle entries
  - Now properly wired through config.py
"""
