"""
PyInstaller Runtime Hook for S-P Trading.

This file is executed by PyInstaller BEFORE any application code runs.
It ensures that _internal is on sys.path so that Python can import
our .py data files (web_app, trading_bot, etc.) at runtime.

Without this, modules in `datas` (not `hiddenimports`) cannot be
imported because Python doesn't automatically know to look in _internal.
"""
import sys
import os
from pathlib import Path


def _setup_path():
    if not hasattr(sys, '_MEIPASS'):
        return  # Not a frozen/packaged app — nothing to do

    meipass = Path(sys._MEIPASS)

    # _MEIPASS IS _internal — add it first so our .py files take priority
    meipass_str = str(meipass)
    if meipass_str not in sys.path:
        sys.path.insert(0, meipass_str)

    # Also add the app root (parent of _internal) for completeness
    app_root_str = str(meipass.parent)
    if app_root_str not in sys.path:
        sys.path.insert(1, app_root_str)


_setup_path()
