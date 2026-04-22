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
    'intelligent_entry_filter.py',
    'trade_analytics.py',
    'heartbeat_local.py',
    'query_analytics.py',
    'chrome_helper.py',
    'debug_config.py',
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

if missing_modules:
    print(f"\n⚠️  Warning: {len(missing_modules)} modules not found")
    print("   Build will continue but these won't be available at runtime")


# ============================================================================
# HIDDEN IMPORTS
# ============================================================================

# Hidden imports - modules that PyInstaller might miss
hiddenimports = [
    # Core application
    'trading_bot',
    'web_app',
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
    'gotrue',
    'postgrest',
    'realtime',
    'storage3',
    
    # Avoid warnings
    'pkg_resources.py2_warn',
    'pkg_resources.markers',
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
json_files = glob.glob('*.json')
print("\nJSON files to bundle:")
for json_file in json_files:
    if json_file not in ['package.json', 'package-lock.json']:
        datas.append((json_file, '.'))
        print(f"  → {json_file}")


# ============================================================================
# PLAYWRIGHT BUNDLING - Not needed for cdp mode
# ============================================================================

# ============================================================================
# PLAYWRIGHT BUNDLING - Manual file-by-file (no glob)
# ============================================================================
print("\n=== PLAYWRIGHT FILES ===")

try:
    import playwright
    from pathlib import Path
    
    pw_path = Path(playwright.__file__).parent
    driver_path = pw_path / 'driver'
    
    if driver_path.exists():
        print(f"Found Playwright at: {pw_path}")
        
        # Add ONLY the files we need for CDP mode
        
        # 1. Critical: programWithTestStub.js
        critical_file = driver_path / 'package' / 'lib' / 'cli' / 'programWithTestStub.js'
        if critical_file.exists():
            datas.append((str(critical_file), 'playwright/driver/package/lib/cli'))
            print(f"  ✓ programWithTestStub.js")
        else:
            print(f"  ✗ programWithTestStub.js NOT FOUND")
        
        # 2. Other critical files in lib/cli/
        cli_files = ['program.js', 'driver.js']
        for filename in cli_files:
            file_path = driver_path / 'package' / 'lib' / 'cli' / filename
            if file_path.exists():
                datas.append((str(file_path), 'playwright/driver/package/lib/cli'))
                print(f"  ✓ {filename}")
        
        # 3. cli.js (entry point)
        cli_js = driver_path / 'package' / 'cli.js'
        if cli_js.exists():
            datas.append((str(cli_js), 'playwright/driver/package'))
            print(f"  ✓ cli.js")
        
        # 4. package.json
        package_json = driver_path / 'package' / 'package.json'
        if package_json.exists():
            datas.append((str(package_json), 'playwright/driver/package'))
            print(f"  ✓ package.json")
        
        # 5. node binary for Windows
        node_exe = driver_path / 'node.exe'
        if node_exe.exists():
            datas.append((str(node_exe), 'playwright/driver'))
            print(f"  ✓ node.exe")
        
        print("✓ Playwright critical files bundled")
    else:
        print(f"⚠️ Playwright driver not found")
        
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
        'tkinter',
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

# Remove any test files that snuck in
a.datas = [x for x in a.datas if not any([
    'test' in x[0].lower() and 'pytest' not in x[0].lower(),
    '_test' in x[0].lower(),
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

