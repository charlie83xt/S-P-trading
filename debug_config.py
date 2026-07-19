# debug_config.py

import sys
import platform

"""
Debug Configuration Toggle


Set DEBUG = False for production builds to clean up console output.
Set DEBUG = True for development to see detailed logs.


This controls:
- Console output verbosity
- Debug print statements
- Log levels
- Heartbeat frequency logging
- Status polling logs
- Strategy state logs
"""


# ============================================================================
# MAIN DEBUG TOGGLE - Change this for production builds
# ============================================================================


DEBUG = True # Set to False before building for distribution


# ============================================================================
# LOG CONFIGURATION
# ============================================================================


if DEBUG:
    # DEVELOPMENT MODE
    LOG_LEVEL = "DEBUG"
    LOG_TO_CONSOLE = True
    LOG_TO_FILE = True
    
    # Feature flags
    VERBOSE_LOGGING = True
    PRINT_SIGNALS = True
    PRINT_POSITIONS = True
    PRINT_HEARTBEATS = True
    PRINT_STATUS_POLLS = True
    PRINT_STRATEGY_STATE = True
    PRINT_API_CALLS = True
    PRINT_RISK_UPDATES = True
    
else:
    # PRODUCTION MODE
    LOG_LEVEL = "INFO"
    LOG_TO_CONSOLE = False  # No console spam
    LOG_TO_FILE = True      # Still log to file
    
    # Feature flags - all disabled
    VERBOSE_LOGGING = False
    PRINT_SIGNALS = False
    PRINT_POSITIONS = False
    PRINT_HEARTBEATS = False      # ← Stops "HB: price=..." logs
    PRINT_STATUS_POLLS = False    # ← Stops "STATUS OUT: sym=..." logs
    PRINT_STRATEGY_STATE = False  # ← Stops "📊 PrevDayHL Active..." logs
    PRINT_API_CALLS = False
    PRINT_RISK_UPDATES = False


# ============================================================================
# SPECIFIC LOG SUPPRESSIONS (Production)
# ============================================================================


if not DEBUG:
    # Suppress specific repetitive logs
    SUPPRESS_WERKZEUG = True      # Flask HTTP request logs
    SUPPRESS_NO_TRADES_WARNING = True  # "No trades found when expected"
    SUPPRESS_STRATEGY_HEARTBEAT = True # Strategy status every second
else:
    SUPPRESS_WERKZEUG = False
    SUPPRESS_NO_TRADES_WARNING = False
    SUPPRESS_STRATEGY_HEARTBEAT = False


# ============================================================================
# LOGGING FREQUENCY (Production)
# ============================================================================


if DEBUG:
    # Log frequently in development
    HEARTBEAT_LOG_INTERVAL = 1    # Log every heartbeat (every ~1 sec)
    STATUS_LOG_INTERVAL = 1       # Log every status update
    STRATEGY_LOG_INTERVAL = 1     # Log every strategy check
else:
    # Log sparingly in production
    HEARTBEAT_LOG_INTERVAL = 60   # Log every 60 heartbeats (~1 min)
    STATUS_LOG_INTERVAL = 30      # Log every 30 status updates
    STRATEGY_LOG_INTERVAL = 300   # Log every 300 checks (~5 min)


# ============================================================================
# CONSOLE OUTPUT FORMATTING
# ============================================================================


if DEBUG:
    # Colorful, detailed output for development
    USE_COLORS = True
    SHOW_TIMESTAMPS = True
    SHOW_THREAD_INFO = True
else:
    # Clean, minimal output for production
    USE_COLORS = False
    SHOW_TIMESTAMPS = False
    SHOW_THREAD_INFO = False


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Detect if emojis are supported
_platform = platform.system()

# IMPORTANT: Windows console (cmd.exe/PowerShell) cannot handle emojis properly
# Even if sys.stdout.encoding reports 'utf-8', the console still uses cp1252
# and will throw UnicodeEncodeError when trying to print emojis
 
if _platform == 'Windows':
   # Windows: NEVER use emojis (console can't handle them)
   USE_EMOJIS = False
else:
   # Mac/Linux: Emojis work fine
   USE_EMOJIS = True


def emoji(char: str, fallback: str = "") -> str:
    """
    Return emoji on supported platforms, text fallback otherwise.
    
    Args:
        char: Emoji character
        fallback: Text to use if emoji not supported
    
    Returns:
        Emoji or fallback text
    
    Example:
        >>> emoji("✅", "[OK]")
        "✅"  # On Mac/Linux
        "[OK]"  # On Windows
    """
    return char if USE_EMOJIS else fallback


# Predefined common emojis
CHECK = emoji("✅", "[OK]")
CROSS = emoji("❌", "[X]")
ROCKET = emoji("🚀", ">>")
CHART = emoji("📊", "[Chart]")
WRENCH = emoji("🔧", "[Tool]")
WARNING = emoji("⚠️", "[!]")
INFO = emoji("ℹ️", "[i]")
NOTE = emoji("📝", "[Note]")
TRASH = emoji("🗑", "[Trash]")
BOX = emoji("📦", "[Box]")
CALENDAR = emoji("📆", "[Date]")
APPLE = emoji("🍎", "[Apple]")
GREEN = emoji("🟢", "[Green]")
RED = emoji("🔴", "[Red]")
YELLOW = emoji("🟡", "[Yellow]")
BLUE = emoji("🔵", "[Blue]")
MAGNI = emoji("🔍", "[Magnifier]") 
FIRE = emoji("🔥", "[Fire]")
FOLDER = emoji("📁", "[Folder]")
TREND = emoji("📈", "[Trend]")
DISK = emoji("💾", "[Disk]")
LOADING = emoji("🔄", "[Loading...]")
STICKS = emoji("⏸️", "[||]")
TERRA = emoji("🌐", "[@]")
BULB = emoji("💡", "[Bulb]")
BOT = emoji("🤖", "[Bot]")
UP_R = emoji("🔺", "[^]")
DO_R = emoji("🔻", "[v]")
SANDTIME = emoji("⏳", "[9+3]")
TARGET = emoji("🎯", "[=>]")
SNOW = emoji("❄️", "[*]")
BLOCKED = emoji("⛔️", "[(-)]")
MONEY = emoji("💰", "[$]")


# Counter for throttling logs
_log_counters = {}


def should_log_throttled(key: str, interval: int) -> bool:
    """
    Throttle repetitive logs.
    
    Args:
        key: Unique identifier for this log type
        interval: Log once every N calls
    
    Returns:
        True if should log, False if should skip
    """
    if DEBUG:
        return True  # Always log in debug mode
    
    _log_counters[key] = _log_counters.get(key, 0) + 1
    
    if _log_counters[key] >= interval:
        _log_counters[key] = 0
        return True
    
    return False


def debug_print(*args, **kwargs):
    """
    Print only in DEBUG mode.
    
    Usage:
        debug_print("Debug message", var1, var2)
    """
    if DEBUG:
        print(*args, **kwargs)


def production_print(*args, **kwargs):
    """
    Print in both DEBUG and PRODUCTION modes.
    Use for important user-facing messages.
    
    Usage:
        production_print("✅ Bot started successfully")
    """
    print(*args, **kwargs)


# _encoding = sys.stdout.encoding if sys.stdout else 'utf-8'
# Windows cmd.exe doesn't support emojis well
# USE_EMOJIS = _platform != 'Windows' or _encoding == 'utf-8'


# ============================================================================
# EXPORTS
# ============================================================================


__all__ = [
   'DEBUG',
   'LOG_LEVEL',
   'LOG_TO_CONSOLE',
   'LOG_TO_FILE',
   'VERBOSE_LOGGING',
   'PRINT_SIGNALS',
   'PRINT_POSITIONS',
   'PRINT_HEARTBEATS',
   'PRINT_STATUS_POLLS',
   'PRINT_STRATEGY_STATE',
   'PRINT_API_CALLS',
   'PRINT_RISK_UPDATES',
   'SUPPRESS_WERKZEUG',
   'SUPPRESS_NO_TRADES_WARNING',
   'SUPPRESS_STRATEGY_HEARTBEAT',
   'HEARTBEAT_LOG_INTERVAL',
   'STATUS_LOG_INTERVAL',
   'STRATEGY_LOG_INTERVAL',
   'USE_EMOJIS',
   'emoji',
   'CHECK',
   'CROSS',
   'ROCKET',
   'CHART',
   'WRENCH',
   'WARNING',
   'INFO',
   'NOTE',
   'TRASH',
   'BOX',
   'CALENDAR',
   'APPLE',
   'GREEN',
   'RED',
   'YELLOW',
   'BLUE',
   'MAGNI',
   'FOLDER',
   'TREND',
   'DISK',
   'LOADING',
   'STICKS',
   'TERRA',
   'BULB',
   'BOT',
   'UP_R',
   'DO_R',
   'SANDTIME',
   'TARGET',
   'SNOW',
   'BLOCKED',
   'MONEY',
   'FIRE',
   'should_log_throttled',
   'debug_print',
   'production_print',
]


# ============================================================================
# STARTUP DEBUG INFO
# ============================================================================
 
if DEBUG:
   print(f"Debug Config Loaded:")
   print(f"  Platform: {_platform}")
   print(f"  USE_EMOJIS: {USE_EMOJIS}")
   print(f"  CHECK: '{CHECK}'")
   print(f"  sys.stdout.encoding: {sys.stdout.encoding if sys.stdout else 'None (no console)'}")



