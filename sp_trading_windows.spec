# sp_trading_windows.spec
# Production build configuration for S-P Trading App
# 
# Usage:
#   pyinstaller sp_trading_windows.spec
#
# Output:
#   dist/S-P Trading/S-P Trading.exe

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ============================================================================
# CRITICAL: List ONLY files actually used in production
# ============================================================================

# Hidden imports - modules that PyInstaller might miss
hiddenimports = [
    # Core application
    'trading_bot',
    'web_app',
    'web_ui',
    'launcher',
    'launch_web_dashboard',
    'config',
    'app_config',
    'version',
    'authorization',
    
    # Data & API
    'data_manager',
    'api_factory',
    'api_interface',
    'tradovate_api',
    'binance_api',
    'ninjatrader_api',
    'tradovate_web_ui_api',
    'risk_manager',
    'symbol_manager',
    
    # Strategies
    'strategy_factory',
    'strategy_manager',
    'base_strategy',
    'opening_range_strategy',
    'orb_retest_strategy',
    'previous_day_high_low_strategy',
    'mean_reversion_strategy',
    'mean_reversion_strategy_light',
    
    # Filters
    'intelligent_entry_filter',
    
    # Analytics
    'trade_analytics',
    'heartbeat_local',
    'query_analytics',
    'export_trades',
    
    # Helpers
    'chrome_helper',
    'debug_config',
    
    # Flask and web dependencies
    'flask',
    'flask.json',
    'flask.templating',
    'werkzeug',
    'werkzeug.routing',
    'werkzeug.serving',
    'jinja2',
    'jinja2.ext',
    'click',
    
    # Data processing
    'pandas',
    'numpy',
    'numpy.core',
    'numpy.lib',
    'sqlite3',
    
    # HTTP and async
    'requests',
    'urllib3',
    'aiohttp',
    'asyncio',
    
    # Playwright
    'playwright',
    'playwright.sync_api',
    'playwright._impl',
    
    # Environment and config
    'dotenv',
    'json',
    'pathlib',
    'logging',
    'threading',
    'queue',
    'datetime',
    'time',
    'os',
    'sys',
    'platform',
    'subprocess',
    'socket',
    
    # Supabase (optional but include if installed)
    'supabase',
    
    # Avoid warnings
    'pkg_resources.py2_warn',
    'pkg_resources.markers',
]

# ============================================================================
# DATA FILES - Files that need to be bundled
# ============================================================================

datas = [
    # Flask templates (REQUIRED for web UI)
    ('templates', 'templates'),
    
    # Static files (if you have CSS/JS/images)
    # ('static', 'static'),  # Uncomment if you have static folder
    
    # Configuration templates
    ('.env.example', '.'),
    
    # Documentation
    ('README.md', '.'),
    
    # Version and config
    ('version.py', '.'),
    ('debug_config.py', '.'),
    
    # IMPORTANT: Do NOT include .env (credentials)
    # IMPORTANT: Do NOT include data/ folder (user-specific)
]

# ============================================================================
# ANALYSIS - What to include/exclude
# ============================================================================

a = Analysis(
    ['launcher.py'],  # Entry point
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude large unused packages
        'matplotlib',  # Unless you're plotting
        'scipy',       # Unless you're using it
        'PIL',         # Unless you have images
        'tkinter',     # GUI toolkit (not needed for web app)
        'pytest',      # Testing framework
        'IPython',     # Interactive shell
        'notebook',    # Jupyter
        
        # Exclude test files
        'tests',
        'test_*',
        '_test',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================================
# REMOVE TEST/DEBUG FILES
# ============================================================================

# Filter out any test or debug files that snuck in
a.datas = [x for x in a.datas if not any([
    'test' in x[0].lower(),
    'debug' in x[0].lower() and x[0] != 'debug_config.py',
    '_test' in x[0].lower(),
    'pytest' in x[0].lower(),
])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ============================================================================
# EXECUTABLE CONFIGURATION
# ============================================================================

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='S-P Trading',  # Name of the .exe
    debug=False,          # Set to True only for debugging builds
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,             # Compress with UPX
    console=True,         # Show console window (set False to hide)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add 'icon.ico' if you have an app icon
)

# ============================================================================
# COLLECT FILES INTO DISTRIBUTION FOLDER
# ============================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='S-P Trading',  # Name of the distribution folder
)

# ============================================================================
# BUILD NOTES
# ============================================================================

"""
AFTER BUILDING:

1. Test the executable:
   cd "dist/S-P Trading"
   "S-P Trading.exe" --setup

2. Create installer with Inno Setup:
   - Install Inno Setup: https://jrsoftware.org/isdl.php
   - Use installer_script.iss
   - Run: iscc installer_script.iss
   - Creates: S-P-Trading-Setup-v1.0.0.exe

3. Distribute:
   - Share installer with users
   - Users run installer
   - App installs to Program Files
   - Desktop shortcut created
   - First run: setup wizard

4. Updates:
   - Bump version in version.py
   - Rebuild: pyinstaller sp_trading_windows.spec
   - Create new installer
   - Users download and reinstall (settings preserved)
"""
