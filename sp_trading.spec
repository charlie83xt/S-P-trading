"""
PyInstaller spec file for building S-P Trading App as standalone executable.

Build commands:
  
  macOS:
    pyinstaller sp_trading.spec
    # Creates: dist/launcher.app and launcher_mac.dmg
  
  Windows:
    pyinstaller sp_trading.spec
    # Creates: dist/launcher.exe and installer_windows.exe
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Add current directory to Python path
sys.path.insert(0, os.path.abspath('.'))

# Collect hidden imports
hidden_imports = [
    'dotenv',
    'selenium',
    'flask',
    'sqlalchemy',
    'supabase',
]

# Collect hidden imports from submodules
for module in ['strategy_factory', 'api_factory', 'data_manager']:
    hidden_imports.extend(collect_submodules(module, with_pkg=True))

# Files to include (data files, resources, etc)
datas = []

# Add .env example
if os.path.exists('.env.example'):
    datas.append(('.env.example', '.'))

# Add templates if they exist
if os.path.isdir('templates'):
    datas.append(('templates', 'templates'))

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Show console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = Collection(exe,
                 a.binaries,
                 a.zipfiles,
                 a.datas,
                 strip=False,
                 upx=True,
                 name='launcher')

# Platform-specific handling
import platform
system = platform.system()

if system == "Darwin":
    # macOS: create .app bundle
    app = BUNDLE(
        coll,
        name='S-P Trading.app',
        icon='resources/icon.icns',  # Optional: add icon file
        bundle_identifier='com.sptrading.app',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': 'True',
        },
    )

elif system == "Windows":
    # Windows: create .exe (bundled collection already created above)
    pass

else:
    # Linux: use the collection as-is
    pass
