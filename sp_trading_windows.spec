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
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from PyInstaller.building.datastruct import Tree
import glob

block_cipher = None

# ============================================================================
# VERIFY CRITICAL FILES EXIST BEFORE BUILD
# ============================================================================

print("\n" + "="*70)
print("S-P TRADING - PYINSTALLER BUILD")
print("="*70)

# Verify we're in the right directory
if not os.path.isfile('launcher.py'):
    print("❌ ERROR: launcher.py not found!")
    print(f"   Current directory: {os.getcwd()}")
    print("   Make sure you're running from project root")
    sys.exit(1)

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
# COLLECT ALL PYTHON FILES AS DATA
# ============================================================================


# List all your .py files that need to be accessible at runtime
python_modules = [
    'trading_bot.py',
    'web_app.py',
    'config.py',
    'app_config.py',
    'version.py',
    'authorization.py',
    'debug_config.py',
    'data_manager.py',
    'api_factory.py',
    'api_interface.py',
    'tradovate_api.py',
    'binance_api.py',
    'ninjatrader_api.py',
    'tradovate_web_ui_api.py',
    'risk_manager.py',
    'symbol_manager.py',
    'strategy_factory.py',
    'strategy_manager.py',
    'opening_range_strategy.py',
    'orb_retest_strategy.py',
    'previous_day_high_low_strategy.py',
    'mean_reversion_strategy.py',
    'mean_reversion_strategy_light.py',
    'mnq_vwap_strategy.py',
    'intelligent_entry_filter.py',
    'market_regime_detector.py',
    'minute_bar_builder.py',
    'trade_analytics.py',
    'heartbeat_local.py',
    'query_analytics.py',
    'chrome_helper.py',
    'debug_config.py',
    # -- New Phase 2/3 modules --
    'first_run.py',
    'update_manager.py',
    'launch_web_dashboard.py'
    'mes_strategy_runner.py',
    'mes_strategy_wrapper.py',
    'mnq_sim_strategy.py',
    'mnq_strategy_core.py',
]

# Verify each module exists
print("\nChecking Python modules:")
missing_modules = []
for module in python_modules:
    if os.path.isfile(module):
        print(f"  ✓ {module}")
    else:
        print(f"  ✗ {module} - NOT FOUND (will skip)")
        missing_modules.append(module)

# --- mnq_sim/ package (preserve folder structure) ---
for pyf in glob.glob('mnq_sim/*.py'):
    datas.append((pyf, 'mnq_sim'))
    print(f"  → {pyf}")

if missing_modules:
    print(f"\n⚠️  Warning: {len(missing_modules)} modules not found")
    print("   Build will continue but these won't be available at runtime")


# ============================================================================
# HIDDEN IMPORTS
# ============================================================================

# Hidden imports - modules that PyInstaller might miss
hiddenimports = [
    # Core application
    # 'trading_bot',
    # 'web_app',
    'launcher',
    'launch_web_dashboard',
    # 'config',
    'app_config',
    'version',
    # 'authorization',
    # 'first_run',
    # 'update_manager',
    
    # Data & API
    'data_manager',
    'api_factory',
    'api_interface',
    'tradovate_api',
    'binance_api',
    'ninjatrader_api',
    'tradovate_web_ui_api',
    # 'risk_manager',
    # 'symbol_manager',
    
    # Strategies
    # 'strategy_factory',
    # 'strategy_manager',
    # 'opening_range_strategy',
    # 'orb_retest_strategy',
    # 'previous_day_high_low_strategy',
    # 'mean_reversion_strategy',
    # 'mean_reversion_strategy_light',
    
    # Filters
    'intelligent_entry_filter',
    
    # Analytics
    # 'trade_analytics',
    'heartbeat_local',
    'query_analytics',
    
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
    'werkzeug.middleware',
    'werkzeug.middleware.proxy.fix',
    'jinja2',
    'jinja2.ext',
    'click',
    
    # Data processing
    'pandas',
    'pandas.core',
    'pandas.core.arrays',
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
    'playwright._impl._browser',
    'playwright._impl._page',
    
    # Environment and config
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
    
    # Supabase (optional but include if installed)
    'supabase',
    'httpx',
    'packaging',
    'packaging.version',
    'gotrue',
    'postgrest',
    'realtime',
    'storage3',

    # Timezone data (required on Windows - no system tz database)
    'zoneinfo',
    'tzdata',
    'tzdata.zoneinfo',
    'tzdata.zoneinfo.America',
    
    # Avoid warnings
    'pkg_resources.py2_warn',
    'pkg_resources.markers',

    'mes_strategy_runner', 
    'mes_strategy_wrapper', 
    'mnq_sim_strategy',
    'mnq_sim', 
    'mnq_sim.types', 
    'mnq_sim.vwap', 
    'mnq_sim.profile',
    'mnq_sim.classifier', 
    'mnq_sim.gate', 
    'mnq_sim.backtest',
]

# ============================================================================
# DATA FILES - Explicit paths with verification
# ============================================================================

datas = []

# Add all Python modules as data files (so launcher can find them)
for module in python_modules:
    if os.path.isfile(module) and module not in missing_modules:
        datas.append((module, '.'))
        print(f"  → {module} will be bundled")

# Templates (CRITICAL for Flask)
if os.path.isdir('templates'):
    # Add entire templates folder
    import glob
    template_files = glob.glob('templates/**/*', recursive=True)
    for template_file in template_files:
        if os.path.isfile(template_file):
            # Preserve folder structure
            dest_folder = os.path.dirname(template_file)
            datas.append((template_file, dest_folder))
            print(f"  → {template_file}")

# Static files (if exists)
if os.path.isdir('static'):
    import glob
    static_files = glob.glob('static/**/*', recursive=True)
    for static_file in static_files:
        if os.path.isfile(static_file):
            dest_folder = os.path.dirname(static_file)
            datas.append((static_file, dest_folder))

# Verify icon exists before building
icon_path = 'assets/icon.ico'
if os.path.isfile(icon_path):
    print(f"✓ Icon found: {icon_path} ({os.path.getsize(icon_path)} bytes)")
else:
    print(f"✗ Icon NOT found at: {icon_path}")
    icon_path = None


# Config and docs
config_files = [
    '.env.example',
    'README.md',
    'version.py',
    'debug_config.py',
]

for config_file in config_files:
    if os.path.isfile(config_file):
        datas.append((config_file, '.'))
        print(f"  → {config_file}")

print()

# JSON files (IMPORTANT for Tradovate)
_SECRET_JSON = {"credentials.json", "client_secret.json", "token.json", "service_account.json"}
json_files = [j for j in glob.glob('*.json')
              if j not in ('package.json', 'package-lock.json') and j not in _SECRET_JSON]
print("\nJSON files to bundle:")
for json_file in json_files:
    datas.append((json_file, '.'))
    print(f"  → {json_file}")



# ============================================================================
# PLAYWRIGHT BUNDLING - Using correct TOC format
# ============================================================================
print("\n=== PLAYWRIGHT FILES ===")


try:
    import playwright
    from pathlib import Path
    
    pw_path = Path(playwright.__file__).parent
    driver_path = pw_path / 'driver' / 'package'
    
    if driver_path.exists():
        print(f"Found Playwright at: {pw_path}")
        
        # Critical files to bundle
        critical_files = [
            ('lib/cli/programWithTestStub.js', 'playwright/driver/package/lib/cli'),
            ('lib/cli/program.js', 'playwright/driver/package/lib/cli'),
            ('lib/cli/driver.js', 'playwright/driver/package/lib/cli'),
            ('cli.js', 'playwright/driver/package'),
            ('package.json', 'playwright/driver/package'),
        ]
        
        for src_rel, dest_dir in critical_files:
            src_file = driver_path / src_rel.replace('/', os.sep)
            if src_file.exists():
                # Use absolute path for source, relative for dest
                datas.append((str(src_file), dest_dir))
                print(f"  ✓ {src_rel}")
            else:
                print(f"  ✗ {src_rel} - NOT FOUND")
        
        # Add node.exe
        node_exe = pw_path / 'driver' / 'node.exe'
        if node_exe.exists():
            datas.append((str(node_exe), 'playwright/driver'))
            print(f"  ✓ node.exe")
        
        print(f"✓ Added {len([x for x in datas if 'playwright' in x[1]])} Playwright files")
    else:
        print(f"⚠️ Playwright driver not found at {driver_path}")
        
except Exception as e:
    print(f"❌ Playwright bundling error: {e}")
    import traceback
    traceback.print_exc()

print()


# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    ['launcher.py'],
    pathex=[os.getcwd()], # Explicitly set path to current directory
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[ 
        # Exclude large unused packages
        'matplotlib',
        'scipy',
        'PIL',
        'pytest',
        'IPython',
        'notebook',
        'tests',
        'test',
        '_test',
        # Exclude invalid modules
        'export_trades',  # Invalid module from launcher.py
        'web_ui',         # Invalid module from launcher.py

    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================================
# FILTER OUT TEST/DEBUG FILES
# ============================================================================

# With this — only exclude files that START with test_ or end with _test.py:
a.datas = [x for x in a.datas if not any([
    os.path.basename(x[0]).lower().startswith('test_'),
    os.path.basename(x[0]).lower().endswith('_test.py'),
    os.path.basename(x[0]).lower() in [
        'late_test_paper_engine.py',
        'minimal_test_strategy.py',
        'verify_mean_reversion.py',
    ],
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
    console=False,  # Show console for now (change to False to hide)
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
# POST-BUILD VERIFICATION
# ============================================================================

print("\n" + "="*70)
print("BUILD CONFIGURATION COMPLETE")
print("="*70)
print("\nExpected output:")
print("  dist/S-P Trading/S-P Trading.exe")
print("  dist/S-P Trading/_internal/")
print("  dist/S-P Trading/templates/dashboard.html")
print("  dist/S-P Trading/trading_bot.py")
print("  dist/S-P Trading/web_app.py")
print("  dist/S-P Trading/[all other .py files]")
print("\nTo test:")
print('  cd "dist\\S-P Trading"')
print('  & ".\\S-P Trading.exe" --setup')
print("="*70 + "\n")

# ============================================================================
# POST-BUILD - Copy missing Playwright file
# ============================================================================


import shutil

print("\n=== POST-BUILD: Copying missing Playwright file ===")

try:
    import playwright
    pw_path = Path(playwright.__file__).parent
    src_file = pw_path / 'driver' / 'package' / 'lib' / 'cli' / 'programWithTestStub.js'
    
    dest_file = Path('dist') / 'S-P Trading' / '_internal' / 'playwright' / 'driver' / 'package' / 'lib' / 'cli' / 'programWithTestStub.js'
    
    if src_file.exists():
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest_file)
        print(f"✓ Copied programWithTestStub.js ({dest_file.stat().st_size} bytes)")
    else:
        print(f"✗ Source not found: {src_file}")
        
except Exception as e:
    print(f"❌ Post-build failed: {e}")

print("="*70)

