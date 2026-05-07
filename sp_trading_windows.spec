# sp_trading_windows.spec
# Production build configuration for S-P Trading App
#
# KEY PRINCIPLE for update channel:
#   Files in `datas` ONLY (not hiddenimports) = loaded from .py file at runtime
#   → these CAN be updated via the GitHub release update channel
#
#   Files in `hiddenimports` = compiled into the .exe bytecode archive
#   → these CANNOT be updated via the channel (needs full rebuild)
#
# Usage:
#   pyinstaller sp_trading_windows.spec
#
# Output:
#   dist/S-P Trading/S-P Trading.exe

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from PyInstaller.building.datastruct import Tree
import glob
import shutil

block_cipher = None

# ============================================================================
# VERIFY CRITICAL FILES EXIST BEFORE BUILD
# ============================================================================

print("\n" + "=" * 70)
print("S-P TRADING - PYINSTALLER BUILD")
print("=" * 70)

if not os.path.isfile('launcher.py'):
    print("ERROR: launcher.py not found!")
    print(f"   Current directory: {os.getcwd()}")
    sys.exit(1)

if not os.path.isdir('templates'):
    print("ERROR: templates/ folder not found!")
    sys.exit(1)

if not os.path.isfile('templates/dashboard.html'):
    print("ERROR: templates/dashboard.html not found!")
    sys.exit(1)

print("OK Found templates/dashboard.html")
print("\nTemplates to bundle:")
for file in os.listdir('templates'):
    print(f"  - {file}")
print()

# ============================================================================
# PYTHON MODULES
#
# SPLIT INTO TWO GROUPS:
#
# GROUP A — UPDATABLE via the update channel
#   Listed in `datas` only. Python loads these from the .py file in _internal
#   at runtime. The update channel overwrites the .py file → change takes effect
#   on next app restart.
#
# GROUP B — COMPILED into the .exe (launcher infrastructure)
#   Listed in `hiddenimports` only. Cannot be updated via channel.
#   Requires a full rebuild to change.
# ============================================================================

# ── GROUP A: Updatable modules (datas only, NOT in hiddenimports) ────────────
updatable_modules = [
    # Core trading logic
    'trading_bot.py',
    'web_app.py',
    'config.py',
    'data_manager.py',
    'risk_manager.py',
    'symbol_manager.py',
    'trade_analytics.py',

    # Trading platform integration
    'tradovate_web_ui_api.py',
    'tradovate_api.py',
    'binance_api.py',
    'ninjatrader_api.py',
    'api_factory.py',
    'api_interface.py',

    # Strategies — most likely to be tuned/updated
    'strategy_factory.py',
    'strategy_manager.py',
    'opening_range_strategy.py',
    'orb_retest_strategy.py',
    'previous_day_high_low_strategy.py',
    'mean_reversion_strategy.py',
    'mean_reversion_strategy_light.py',

    # Filters and detectors — tuned over time
    'intelligent_entry_filter.py',
    'market_regime_detector.py',
    'minute_bar_builder.py',

    # Analytics and helpers — may change
    'heartbeat_local.py',
    'query_analytics.py',

    # Distribution/update infrastructure
    'first_run.py',
    'update_manager.py',
    'authorization.py',
]

# ── GROUP B: Compiled into .exe (DO NOT add to datas) ────────────────────────
# These are listed in hiddenimports below.
# launcher.py, launch_web_dashboard.py, app_config.py,
# version.py, debug_config.py, chrome_helper.py

# ── Files intentionally excluded from the build ──────────────────────────────
# test_*.py              — test harnesses, not needed at runtime
# BUILD_AND_DEPLOY.py    — developer utility
# backup_database.py     — developer utility
# export_trades.py       — developer utility
# verify_mean_reversion.py — developer utility
# main.py                — superseded by launcher.py
# web_ui.py              — duplicate of web_app.py, unused
# config_additions.py    — documentation copy, unused
# late_test_paper_engine.py — test harness
# minimal_test_strategy.py  — test harness

# ── Verify each updatable module exists ──────────────────────────────────────
print("Checking updatable Python modules:")
missing_modules = []
for module in updatable_modules:
    if os.path.isfile(module):
        print(f"  OK {module}")
    else:
        print(f"  MISSING {module} - NOT FOUND (will skip)")
        missing_modules.append(module)

if missing_modules:
    print(f"\nWARNING: {len(missing_modules)} modules not found")
    print("   Build will continue but these won't be available at runtime")

# ============================================================================
# HIDDEN IMPORTS
# Only third-party libraries and launcher infrastructure here.
# Application .py files are loaded from disk via datas — NOT compiled in.
# ============================================================================

hiddenimports = [
    # ── Launcher infrastructure (compiled in — never updated via channel) ──
    'launcher',
    'launch_web_dashboard',
    'app_config',
    'version',
    'debug_config',
    'chrome_helper',

    # ── Flask and web ──
    'flask',
    'flask.json',
    'flask.templating',
    'werkzeug',
    'werkzeug.routing',
    'werkzeug.serving',
    'werkzeug.middleware',
    'werkzeug.middleware.proxy_fix',
    'jinja2',
    'jinja2.ext',
    'click',

    # ── Data processing ──
    'pandas',
    'pandas.core',
    'pandas.core.arrays',
    'numpy',
    'numpy.core',
    'numpy.lib',
    'sqlite3',

    # ── HTTP and async ──
    'requests',
    'urllib3',
    'aiohttp',
    'asyncio',

    # ── Playwright ──
    'playwright',
    'playwright.sync_api',
    'playwright._impl',
    'playwright._impl._browser',
    'playwright._impl._page',

    # ── Standard library (ensure available) ──
    'dotenv',
    'json',
    'pathlib',
    'logging',
    'logging.handlers',
    'threading',
    'queue',
    'datetime',
    'time',
    'os',
    'sys',
    'platform',
    'subprocess',
    'socket',
    'hashlib',
    'hmac',
    'base64',
    'uuid',
    'shutil',
    'tempfile',

    # ── Supabase and dependencies ──
    'supabase',
    'httpx',
    'packaging',
    'packaging.version',
    'gotrue',
    'postgrest',
    'realtime',
    'storage3',

    # ── Misc ──
    'pkg_resources.py2_warn',
    'pkg_resources.markers',
]

# ============================================================================
# DATA FILES
# ============================================================================

datas = []

# ── Add all updatable .py modules as data files ───────────────────────────────
print("\nAdding updatable modules to datas:")
for module in updatable_modules:
    if os.path.isfile(module) and module not in missing_modules:
        datas.append((module, '.'))
        print(f"  → {module}")

# ── Templates (CRITICAL for Flask) ───────────────────────────────────────────
if os.path.isdir('templates'):
    template_files = glob.glob('templates/**/*', recursive=True)
    for template_file in template_files:
        if os.path.isfile(template_file):
            dest_folder = os.path.dirname(template_file)
            datas.append((template_file, dest_folder))
            print(f"  → {template_file}")

# ── Static files ──────────────────────────────────────────────────────────────
if os.path.isdir('static'):
    static_files = glob.glob('static/**/*', recursive=True)
    for static_file in static_files:
        if os.path.isfile(static_file):
            dest_folder = os.path.dirname(static_file)
            datas.append((static_file, dest_folder))

# ── Config and doc files ──────────────────────────────────────────────────────
config_files = [
    '.env.example',
    'README.md',
    'version.py',      # also in datas so update channel can reach it
    'debug_config.py', # also in datas for completeness
    'app_config.py',   # also in datas for completeness
    'chrome_helper.py',
]
for config_file in config_files:
    if os.path.isfile(config_file):
        datas.append((config_file, '.'))
        print(f"  → {config_file}")

# ── JSON files ────────────────────────────────────────────────────────────────
print("\nJSON files to bundle:")
json_files = glob.glob('*.json')
for json_file in json_files:
    if json_file not in ['package.json', 'package-lock.json', 'update_manifest.json']:
        datas.append((json_file, '.'))
        print(f"  → {json_file}")

# ── Icon ──────────────────────────────────────────────────────────────────────
icon_path = 'assets/icon.ico'
if os.path.isfile(icon_path):
    print(f"\nOK Icon found: {icon_path} ({os.path.getsize(icon_path)} bytes)")
else:
    print(f"\nWARNING Icon NOT found at: {icon_path}")
    icon_path = None

# ============================================================================
# PLAYWRIGHT BUNDLING
# ============================================================================

print("\n=== PLAYWRIGHT FILES ===")
try:
    import playwright
    pw_path = Path(playwright.__file__).parent
    driver_path = pw_path / 'driver' / 'package'

    if driver_path.exists():
        print(f"Found Playwright at: {pw_path}")

        critical_files = [
            ('lib/cli/programWithTestStub.js', 'playwright/driver/package/lib/cli'),
            ('lib/cli/program.js',             'playwright/driver/package/lib/cli'),
            ('lib/cli/driver.js',              'playwright/driver/package/lib/cli'),
            ('cli.js',                         'playwright/driver/package'),
            ('package.json',                   'playwright/driver/package'),
        ]

        for src_rel, dest_dir in critical_files:
            src_file = driver_path / src_rel.replace('/', os.sep)
            if src_file.exists():
                datas.append((str(src_file), dest_dir))
                print(f"  OK {src_rel}")
            else:
                print(f"  MISSING {src_rel}")

        node_exe = pw_path / 'driver' / 'node.exe'
        if node_exe.exists():
            datas.append((str(node_exe), 'playwright/driver'))
            print(f"  OK node.exe")

        pw_count = len([x for x in datas if 'playwright' in x[1]])
        print(f"OK Added {pw_count} Playwright files")
    else:
        print(f"WARNING Playwright driver not found at {driver_path}")

except Exception as e:
    print(f"ERROR Playwright bundling error: {e}")
    import traceback
    traceback.print_exc()

print()

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    ['launcher.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Large unused packages
        'matplotlib',
        'scipy',
        'PIL',
        'tkinter',
        'pytest',
        'IPython',
        'notebook',

        # Test/dev files — excluded from production build
        'test_tradovate_api',
        'test_tradovate_ui',
        'test_supabase',
        'test_supabase_daily_bars',
        'test_prev_day_strategy',
        'late_test_paper_engine',
        'minimal_test_strategy',
        'verify_mean_reversion',
        'BUILD_AND_DEPLOY',
        'backup_database',
        'export_trades',
        'main',
        'web_ui',
        'config_additions',

        # Legacy
        'export_trades',
        'web_ui',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================================
# FILTER OUT TEST/DEBUG FILES that snuck through
# ============================================================================

a.datas = [x for x in a.datas if not any([
    'test_' in x[0].lower(),
    '_test.' in x[0].lower(),
    'late_test' in x[0].lower(),
    'minimal_test' in x[0].lower(),
    'verify_mean' in x[0].lower(),
    'backup_database' in x[0].lower(),
    'export_trades' in x[0].lower(),
    'BUILD_AND_DEPLOY' in x[0],
    'web_ui.py' in x[0],
    'config_additions' in x[0].lower(),
])]

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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
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
# POST-BUILD SUMMARY
# ============================================================================

print("\n" + "=" * 70)
print("BUILD CONFIGURATION COMPLETE")
print("=" * 70)
print("\nExpected output:")
print("  dist/S-P Trading/S-P Trading.exe")
print("  dist/S-P Trading/_internal/")
print("  dist/S-P Trading/_internal/web_app.py       ← updatable via channel")
print("  dist/S-P Trading/_internal/trading_bot.py   ← updatable via channel")
print("  dist/S-P Trading/_internal/tradovate_web_ui_api.py ← updatable")
print("  dist/S-P Trading/templates/dashboard.html   ← updatable via channel")
print("\nTo test:")
print('  cd "dist\\S-P Trading"')
print('  & ".\\S-P Trading.exe"')
print("=" * 70 + "\n")

# ============================================================================
# POST-BUILD — Copy missing Playwright file
# ============================================================================

print("\n=== POST-BUILD: Copying missing Playwright file ===")
try:
    import playwright
    pw_path = Path(playwright.__file__).parent
    src_file = (
        pw_path / 'driver' / 'package' / 'lib' / 'cli' / 'programWithTestStub.js'
    )
    dest_file = (
        Path('dist') / 'S-P Trading' / '_internal' / 'playwright'
        / 'driver' / 'package' / 'lib' / 'cli' / 'programWithTestStub.js'
    )

    if src_file.exists():
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest_file)
        print(f"OK Copied programWithTestStub.js ({dest_file.stat().st_size} bytes)")
    else:
        print(f"MISSING Source not found: {src_file}")

except Exception as e:
    print(f"ERROR Post-build failed: {e}")

print("=" * 70)
