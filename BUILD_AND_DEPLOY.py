from debug_config import CHECK, CROSS, BOX, APPLE
"""
BUILD AND DEPLOYMENT GUIDE for S-P Trading App

This guide explains how to package and distribute the app to users.
"""

# ============================================================================
# 1. PREREQUISITES
# ============================================================================

# Install build dependencies (do this ONCE):
# pip install pyinstaller
# pip install dmg  # macOS only
# pip install cx_Freeze  # Windows alternative (optional)
# pip install nsis  # Windows installer (optional)

# ============================================================================
# 2. MACOS BUILD
# ============================================================================

# Step 1: Build the .app bundle
import subprocess
import sys

def build_macos():
    """Build macOS .app bundle."""
    print(f"{APPLE} Building for macOS...")
    
    # Build with PyInstaller
    result = subprocess.run(
        ["pyinstaller", "sp_trading.spec"],
        check=False
    )
    
    if result.returncode != 0:
        print(f"{CROSS} PyInstaller build failed")
        return False
    
    print(f"{CHECK} Built: dist/S-P Trading.app")
    
    # (Optional) Create DMG installer
    print(f"\n{BOX} Creating DMG installer...")
    
    # Manual DMG creation (requires macOS)
    steps = """
    1. cd dist/
    2. hdiutil create -volname "S-P Trading" -srcfolder . -ov -format UDZO sp_trading.dmg
    3. # Users download sp_trading.dmg and drag app to /Applications
    """
    
    print(steps)
    return True

# ============================================================================
# 3. WINDOWS BUILD
# ============================================================================

def build_windows():
    """Build Windows .exe."""
    print("🪟 Building for Windows...")
    
    # Build with PyInstaller
    result = subprocess.run(
        ["pyinstaller", "sp_trading.spec"],
        check=False
    )
    
    if result.returncode != 0:
        print(f"{CROSS} PyInstaller build failed")
        return False
    
    print(f"{CHECK} Built: dist/launcher.exe")
    
    # Create installer (using Inno Setup or NSIS)
    print(f"\n{BOX} Creating installer...")
    
    # Option 1: Use Inno Setup (recommended for Windows)
    inno_script = """
    [Setup]
    AppName=S-P Trading
    AppVersion=0.1.0
    DefaultDirName={pf}\\S-P Trading
    DefaultGroupName=S-P Trading
    OutputDir=.
    OutputBaseFilename=sp_trading_setup
    SetupIconFile=resources\\icon.ico
    
    [Files]
    Source: "dist\\launcher.exe"; DestDir: "{app}"
    Source: "dist\\_internal\\*"; DestDir: "{app}\\_internal"; Flags: recursesubdirs
    
    [Shortcuts]
    Name: "{group}\\S-P Trading"; Filename: "{app}\\launcher.exe"
    Name: "{commondesktop}\\S-P Trading"; Filename: "{app}\\launcher.exe"
    """
    
    print("""
    1. Install Inno Setup: https://jrsoftware.org/isdl.php
    2. Create 'installer.iss' with the script above
    3. Run: iscc installer.iss
    4. This creates: sp_trading_setup.exe
    """)
    
    return True

# ============================================================================
# 4. LINUX BUILD
# ============================================================================

def build_linux():
    """Build Linux AppImage."""
    print("🐧 Building for Linux...")
    
    # Build with PyInstaller
    result = subprocess.run(
        ["pyinstaller", "sp_trading.spec"],
        check=False
    )
    
    if result.returncode != 0:
        print(f"{CROSS} PyInstaller build failed")
        return False
    
    print(f"{CHECK} Built: dist/launcher")
    
    # Create AppImage
    print(f"\n{BOX} Creating AppImage...")
    print("""
    1. Install appimagetool:
       https://github.com/AppImage/AppImageKit/releases
    
    2. Create AppDir structure:
       mkdir -p AppDir/usr/bin
       cp dist/launcher AppDir/usr/bin/
    
    3. Create launcher.desktop:
       [Desktop Entry]
       Name=S-P Trading
       Exec=launcher
       Icon=launcher
       Type=Application
    
    4. Build AppImage:
       appimagetool AppDir sp_trading.AppImage
    """)
    
    return True

# ============================================================================
# 5. DISTRIBUTION CHECKLIST
# ============================================================================

DISTRIBUTION_CHECKLIST = """
Before releasing to users:

[ ] Code is on feature/shipping-app branch
[ ] Version number updated in version.py
[ ] README updated with setup instructions
[ ] .env.example file configured with placeholders
[ ] All tests pass (pytest)
[ ] No hardcoded credentials in code
[ ] Logging configured for production
[ ] Error handling covers all edge cases

For macOS:
[ ] Build with sp_trading.spec
[ ] Test on clean macOS machine
[ ] Create DMG installer
[ ] Sign app with developer certificate

For Windows:
[ ] Build with sp_trading.spec
[ ] Test on clean Windows machine
[ ] Create MSI/EXE installer with Inno Setup
[ ] Test installer on separate machine

For Linux:
[ ] Build with sp_trading.spec
[ ] Create AppImage
[ ] Test on multiple Linux distributions
"""

# ============================================================================
# 6. USER INSTALLATION
# ============================================================================

USER_INSTALL_MACOS = """
===== MACOS INSTALLATION =====

1. Download sp_trading.dmg
2. Double-click to open
3. Drag S-P Trading.app to Applications folder
4. Wait for copy to complete
5. Open Applications folder
6. Double-click S-P Trading.app

First time:
- App will ask for your Tradovate credentials
- Choose DRY-RUN mode to test first
- Follow on-screen setup wizard
"""

USER_INSTALL_WINDOWS = """
===== WINDOWS INSTALLATION =====

1. Download sp_trading_setup.exe
2. Double-click installer
3. Follow on-screen instructions
4. Choose installation directory
5. Complete installation
6. App will launch automatically

First time:
- Follow the setup wizard
- Enter Tradovate credentials
- Choose DRY-RUN mode to test
"""

USER_INSTALL_LINUX = """
===== LINUX INSTALLATION =====

1. Download sp_trading.AppImage
2. Make executable: chmod +x sp_trading.AppImage
3. Run: ./sp_trading.AppImage

First time:
- Follow the setup wizard
- Enter Tradovate credentials
- Choose DRY-RUN mode to test
"""

# ============================================================================
# 7. UPDATE DISTRIBUTION
# ============================================================================

UPDATE_PROCESS = """
===== HANDLING UPDATES =====

For development updates:
1. Make changes on feature/shipping-app
2. Commit and test locally
3. Merge to main
4. Tag version: git tag v0.1.1
5. Rebuild app with PyInstaller
6. Create installer
7. Publish release

For users:
Option A - Manual update:
1. Download new installer
2. Run installer (replaces old version)
3. Old settings preserved in ~/Library/Application Support/S-P-Trading

Option B - Auto-update (future):
1. App checks for updates on startup
2. If available, downloads new version
3. User prompted to install
4. App restarts with new version
"""

# ============================================================================
# 8. SAMPLE BUILD SCRIPT
# ============================================================================

def build_all():
    """Build for all platforms."""
    import platform
    
    system = platform.system()
    
    print("🔨 Starting build process...")
    print(f"Platform: {system}\n")
    
    if system == "Darwin":
        build_macos()
    elif system == "Windows":
        build_windows()
    else:
        build_linux()
    
    print(f"\n{CHECK} Build complete!")
    print("\nNext steps:")
    print("1. Test the application thoroughly")
    print("2. Create installer (DMG/EXE/AppImage)")
    print("3. Distribute to users")

if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*70 + "\n")
    print(DISTRIBUTION_CHECKLIST)
    print("\n" + "="*70 + "\n")
    print(USER_INSTALL_MACOS)
    print("\n" + "="*70 + "\n")
    print(USER_INSTALL_WINDOWS)
    print("\n" + "="*70 + "\n")
    print(UPDATE_PROCESS)
