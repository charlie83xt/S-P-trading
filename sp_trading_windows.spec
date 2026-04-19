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
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ============================================================================
# VERIFY CRITICAL FILES EXIST BEFORE BUILD
# ============================================================================

# Check templates folder exists
if not os.path.isdir('templates'):
    print("❌ ERROR: templates/ folder not found!")
    print("   Make sure templates/ exists in the same directory as this .spec file")
    print(f"   Current directory: {os.getcwd()}")
    sys.exit(1)

# Check dashboard.html exists
if not os.path.isfile('templates/dashboard.html'):
    print("❌ ERROR: templates/dashboard.html not found!")
    print("   This is the main UI file and must exist")
    sys.exit(1)

print("✓ Found templates/dashboard.html")

# List all templates being bundled
print("\n✓ Templates to bundle:")
for file in os.listdir('templates'):
    print(f"  - {file}")
print()

# ============================================================================
# HIDDEN IMPORTS
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
# DATA FILES - Explicit paths with verification
# ============================================================================

datas = []

# Templates folder (CRITICAL - Flask needs this)
templates_path = 'templates'
if os.path.isdir(templates_path):
    datas.append((templates_path, 'templates'))
    print(f"✓ Including: {templates_path} → templates/")
else:
    print(f"❌ ERROR: {templates_path} not found!")
    sys.exit(1)

# Static folder (if exists)
if os.path.isdir('static'):
    datas.append(('static', 'static'))
    print("✓ Including: static/ → static/")

# Config template
if os.path.isfile('.env.example'):
    datas.append(('.env.example', '.'))
    print("✓ Including: .env.example")

# Documentation
if os.path.isfile('README.md'):
    datas.append(('README.md', '.'))
    print("✓ Including: README.md")

# Version and debug config
if os.path.isfile('version.py'):
    datas.append(('version.py', '.'))
if os.path.isfile('debug_config.py'):
    datas.append(('debug_config.py', '.'))

print()

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'PIL',
        'tkinter',
        'pytest',
        'IPython',
        'notebook',
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ============================================================================
# EXECUTABLE
# ============================================================================

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='S-P Trading',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Show console for now (change to False to hide)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ============================================================================
# COLLECT
# ============================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='S-P Trading',
)

# ============================================================================
# POST-BUILD VERIFICATION
# ============================================================================

print("\n" + "="*70)
print("BUILD CONFIGURATION COMPLETE")
print("="*70)
print("\nTo build:")
print("  pyinstaller sp_trading_windows.spec")
print("\nOutput will be:")
print("  dist/S-P Trading/S-P Trading.exe")
print("  dist/S-P Trading/_internal/")
print("  dist/S-P Trading/templates/")
print("\nTo test:")
print('  cd "dist\\S-P Trading"')
print('  & ".\\S-P Trading.exe" --setup')
print("="*70 + "\n")
