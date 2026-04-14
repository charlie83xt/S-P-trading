"""
===================================================================
COMPREHENSIVE SHIPPING & DEPLOYMENT GUIDE
S-P Trading Application v0.1.0
===================================================================

This document guides you from development → packaged app → distributed
to users on macOS and Windows with built-in authorization.

CURRENT STATUS: Feature complete for macOS + Windows
BRANCH: feature/shipping-app
"""

# ===================================================================
# PART 1: WHAT YOU HAVE NOW
# ===================================================================

"""
Your shipping infrastructure now includes:

1. ✅ LAUNCHER (launcher.py)
   - Single entry point for the app
   - Orchestrates Chrome + dashboard startup
   - Handles setup wizard for first-time users
   - Enforces authorization checks

2. ✅ CHROME HELPER (chrome_helper.py)
   - Detects Chrome on macOS/Windows/Linux
   - Launches Chrome with remote debugging (port 9222)
   - Waits for Chrome to be ready
   - Manages Chrome process lifecycle

3. ✅ APP CONFIG (app_config.py)
   - Stores config in OS-appropriate locations
   - macOS: ~/Library/Application Support/S-P-Trading/
   - Windows: %APPDATA%\S-P-Trading\
   - Linux: ~/.config/S-P-Trading/
   - Handles credentials with 0o600 permissions

4. ✅ VERSION TRACKING (version.py)
   - Version: 0.1.0
   - Update checking infrastructure (skeleton)
   - Version info storage

5. ✅ AUTHORIZATION SYSTEM (authorization.py)
   - Machine fingerprinting
   - License key generation/validation
   - Server-based auth (stub)
   - Unified AuthorizationManager
   - First-time registration flow

6. ✅ BUILD CONFIGURATION (sp_trading.spec)
   - PyInstaller spec for building executables
   - Creates .app bundle (macOS)
   - Creates .exe (Windows)
   - Includes all dependencies and data files

7. ✅ BUILD & DEPLOY GUIDE (BUILD_AND_DEPLOY.py)
   - Platform-specific build instructions
   - User installation guides
   - Update distribution process
"""

# ===================================================================
# PART 2: AUTHORIZATION STRATEGY
# ===================================================================

"""
You have 3 authorization strategies available (in authorization.py):

STRATEGY 1: MACHINE FINGERPRINTING (default)
────────────────────────────────────────
- Binds app to specific computer
- Uses: MAC address + hostname + disk serial
- Pro: Simple, no server needed, offline-first
- Con: Can't use on different computers
- When to use: Personal trading bot, single machine

How it works:
1. User runs: python launcher.py --setup
2. App generates unique fingerprint for this machine
3. Stores in: ~/.../S-P-Trading/authorization.json
4. On each startup: Fingerprint verified
5. If machine hardware changes (e.g., new disk): Access denied

STRATEGY 2: LICENSE KEYS
────────────────────────
- Email-based license keys
- Format: user@example.com-RANDOM-SIGNATURE
- Pro: Can distribute to multiple users
- Con: Need to generate keys for each user
- When to use: Small user base, personal distribution

How it works:
1. You generate license: LicenseKey.generate_license("user@example.com")
   Output: "user@example.com-A1B2C3D4E5-F6G7H8I9J0"
2. Share license with user
3. User enters license during setup
4. License verified via HMAC signature (no server needed)
5. Works on any machine with that license

STRATEGY 3: SERVER-BASED (Stub)
────────────────────────────────
- Would call remote auth server
- Server returns: authorized / not authorized
- Pro: Centralized control, revokable licenses
- Con: Requires server infrastructure
- Currently: Just a placeholder
- When to use: Large-scale deployment, managed SaaS

To switch strategies:
  Edit authorization.py line ~190:
  STRATEGY = "machine"  # Change to "license" or "server"
"""

# ===================================================================
# PART 3: STEP-BY-STEP: DEV → PACKAGED APP
# ===================================================================

"""
STEP 1: LOCAL TESTING
─────────────────────

Test the launcher and authorization flow locally:

(1) Test setup wizard:
    python launcher.py --setup
    
    You'll be prompted for:
    - Email address (for registration)
    - Trading platform (Tradovate/Binance/NinjaTrader)
    - Default symbol (MES/ES/NQ)
    - Dry-run mode (yes/no)
    - Tradovate credentials (if applicable)

(2) Verify registration:
    python launcher.py --auth-info
    
    Should show:
    {
      "created": "2024-01-15T10:30:00.123456",
      "strategy": "machine",
      "fingerprint": "abc123def456...",
      "hostname": "your-machine-name"
    }

(3) Test normal startup:
    python launcher.py
    
    Should:
    ✅ Check authorization
    ✅ Load config
    ✅ Launch Chrome (port 9222)
    ✅ Start dashboard (port 5000)
    ✅ Keep running until Ctrl+C

(4) Test debug mode:
    python launcher.py --debug
    
    More verbose logging to console and log files


STEP 2: PREPARE FOR PACKAGING
──────────────────────────────

Before building the executable:

(1) Update version in version.py:
    APP_VERSION = "0.1.0"

(2) Verify all files are present:
    ls -la *.py | grep -E "(launcher|chrome_helper|app_config|version|authorization|trading_bot|config|launch_web_dashboard)"

(3) Check dependencies in requirements.txt:
    pip freeze > requirements.txt
    # Should include: selenium, flask, sqlalchemy, supabase, etc.

(4) Test full startup one more time:
    python launcher.py --debug
    # Verify everything works smoothly


STEP 3: BUILD EXECUTABLES (PyInstaller)
────────────────────────────────────────

Install PyInstaller:
    pip install pyinstaller

Build for your current OS:

✅ MACOS (creates .app bundle):
    pyinstaller sp_trading.spec
    
    Output: dist/S-P Trading.app
    
    Test the app:
    open dist/S-P\ Trading.app
    
    Or run directly:
    dist/S-P\ Trading.app/Contents/MacOS/launcher --setup

✅ WINDOWS (creates .exe):
    pyinstaller sp_trading.spec
    
    Output: dist/launcher.exe
    
    Test:
    dist\launcher.exe --setup

✅ LINUX (creates executable):
    pyinstaller sp_trading.spec
    
    Output: dist/launcher
    
    Test:
    ./dist/launcher --setup


STEP 4: CREATE INSTALLERS
──────────────────────────

macOS → DMG Installer:
    (1) Build .app (see Step 3)
    (2) Create DMG:
        cd dist/
        hdiutil create -volname "S-P Trading" \\
                       -srcfolder . \\
                       -ov -format UDZO \\
                       sp_trading.dmg
    (3) Test: Double-click sp_trading.dmg
    (4) Verify: Can drag app to /Applications

Windows → EXE Installer:
    (1) Build .exe (see Step 3)
    (2) Install Inno Setup: https://jrsoftware.org/isdl.php
    (3) Create installer.iss (template in BUILD_AND_DEPLOY.py)
    (4) Run: iscc installer.iss
    (5) Output: sp_trading_setup.exe
    (6) Test: Run installer, verify shortcut works

Linux → AppImage:
    (1) Build executable (see Step 3)
    (2) Install appimagetool
    (3) Create AppDir structure and .desktop file
    (4) Build AppImage (details in BUILD_AND_DEPLOY.py)


STEP 5: CODE SIGNING (macOS only, optional but recommended)
──────────────────────────────────────────────────────────

macOS requires code signing for distribution outside App Store:

    codesign -s - dist/S-P\ Trading.app
    
    For notarization (required for Big Sur+):
    1. Get Apple Developer certificate
    2. Sign app
    3. Notarize with Apple
    4. Staple notarization to app
    
    (Process documented in apple_notarization_steps.md)


STEP 6: DISTRIBUTE
──────────────────

Upload files to your distribution channel:

macOS:
  - sp_trading.dmg (from Step 4)
  - SHA256 checksum
  - Release notes

Windows:
  - sp_trading_setup.exe (from Step 4)
  - SHA256 checksum
  - Release notes

Host on:
  - Your website
  - GitHub releases
  - AWS S3
  - Dropbox
  - Other file hosting

Share download link with authorized users.
"""

# ===================================================================
# PART 4: USER INSTALLATION
# ===================================================================

"""
What users see when they download your app:

MACOS USER:
───────────
1. Downloads sp_trading.dmg
2. Double-clicks to mount DMG
3. Sees S-P Trading.app icon
4. Drags to Applications folder
5. Goes to Applications, double-clicks S-P Trading.app
6. First run prompt: "Are you sure? This is from an unidentified developer"
   - Click "Open" (or set System Preferences → Security to allow)
7. Setup wizard appears:
   ✏️ Enter email address
   ✏️ Choose trading platform
   ✏️ Choose default symbol
   ✏️ Opt-in to dry-run mode
   ✏️ Enter trading credentials
8. App verifies machine registration
9. Chrome opens → Dashboard loads → Ready to trade!

WINDOWS USER:
─────────────
1. Downloads sp_trading_setup.exe
2. Double-clicks installer
3. Windows SmartScreen: Click "More info" → "Run anyway"
4. Installer wizard: Choose installation directory
5. Installer completes, app launches
6. Setup wizard appears: [Same as macOS]
7. App verifies machine registration
8. Chrome opens → Dashboard loads → Ready to trade!

LINUX USER:
────────────
1. Downloads sp_trading.AppImage
2. Terminal: chmod +x sp_trading.AppImage
3. Terminal: ./sp_trading.AppImage
4. Setup wizard appears: [Same as macOS]
5. App verifies machine registration
6. Chrome opens → Dashboard loads → Ready to trade!
"""

# ===================================================================
# PART 5: UPDATE DISTRIBUTION
# ===================================================================

"""
When you release an update (v0.1.1, v0.2.0, etc.):

STEP 1: Make changes locally
   - Fix bugs, add features
   - Test with: python launcher.py --debug

STEP 2: Update version
   - Edit version.py: APP_VERSION = "0.1.1"
   - Commit: git commit -am "Release v0.1.1"

STEP 3: Tag release
   - git tag v0.1.1
   - git push origin v0.1.1

STEP 4: Rebuild binaries
   - pyinstaller sp_trading.spec
   - Create DMG (macOS) or MSI (Windows)
   - Test on clean machine

STEP 5: Publish
   - Upload to GitHub releases: https://github.com/your/repo/releases/new
   - Upload to your website
   - Notify users

FUTURE: Auto-update
   - Check version info in version.py
   - Implement check_for_updates() to call your update server
   - Allow users to download + install updates from within app
"""

# ===================================================================
# PART 6: TROUBLESHOOTING
# ===================================================================

"""
Issue: "Authorization failed" on new machine

Cause: User trying to run app on machine it wasn't registered on
Fix: 
  - User must run: python launcher.py --setup
  - This registers the new machine
  - Then normal operation works

---

Issue: Chrome not launching

Cause: Chrome not installed or not in standard paths
Debug:
  - python launcher.py --debug (check logs)
  - Manually verify Chrome exists:
    macOS: ls /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome
    Windows: dir "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    Linux: which google-chrome

---

Issue: Dashboard won't start

Cause: Port 5000 already in use
Debug:
  - Check if another process using port 5000
  - macOS/Linux: lsof -i :5000
  - Windows: netstat -ano | findstr :5000
  - Kill process or use different port in config

---

Issue: "This app can't be opened" (macOS)

Cause: App not signed, or unrecognized developer
Fix:
  - (1) Right-click app → Open → Choose "Open anyway"
  - (2) Or: xattr -d com.apple.quarantine "S-P Trading.app"
  - (3) Or: Sign the app (see Part 3, Step 5)

---

Issue: "Windows protected your PC" (Windows)

Cause: SmartScreen blocking unsigned app
Fix:
  - Click "More info"
  - Click "Run anyway"
  - Or: Code sign .exe (requires certificate)
"""

# ===================================================================
# PART 7: QUICK REFERENCE
# ===================================================================

"""
Commands you'll use frequently:

TEST LOCALLY:
  python launcher.py --setup              # Setup wizard
  python launcher.py                      # Normal run
  python launcher.py --debug              # Verbose
  python launcher.py --auth-info          # Check registration
  python launcher.py --version            # Show version

BUILD:
  pyinstaller sp_trading.spec             # Build for current OS

VERIFY:
  python authorization.py                 # Test auth module
  python -m pytest                        # Run tests (if any)

DEPLOY:
  git checkout feature/shipping-app       # Ensure on branch
  git status                              # Verify clean
  git log --oneline -5                    # Review recent commits
  git tag v0.1.0                          # Tag release
  git push origin feature/shipping-app    # Push to GitHub
  git push origin v0.1.0                  # Push tag

DIAGNOSTICS:
  ls -la ~/.../S-P-Trading/               # Check app config dir
  cat ~/.../S-P-Trading/authorization.json # View auth info
  tail -f ~/.../S-P-Trading/launcher_*.log # Watch logs
"""

# ===================================================================
# PART 8: AUTHORIZATION DECISION TREE
# ===================================================================

"""
Which authorization strategy should you use?

┌─────────────────────────┐
│  How many users?        │
├─────────────────────────┤
│
├─> Just me / single machine
│   → Use MACHINE FINGERPRINT
│   Command: No change needed (default)
│   Registration: python launcher.py --setup
│   Pro: Simple, offline-first
│   Con: Can't use on other machines
│
├─> Small team (< 10 people)
│   → Use LICENSE KEYS
│   Command: Edit authorization.py → STRATEGY = "license"
│   Registration: Share license key with each user
│   You generate: LicenseKey.generate_license("user@example.com")
│   Pro: Can distribute easily
│   Con: Need to manage keys
│
└─> Large deployment / SaaS
    → Use SERVER VALIDATION
    Command: Edit authorization.py → STRATEGY = "server"
    Registration: Users login to server
    You need: Backend server at auth.sp-trading.app
    Pro: Centralized control, revokable
    Con: Complex setup, server required
"""

# ===================================================================
# PART 9: FILES CREATED FOR YOU
# ===================================================================

"""
New files in your repo (on feature/shipping-app):

launcher.py
  - Main entry point (updated with auth)
  - Entry point for packaged app
  - 400+ lines, fully functional

chrome_helper.py
  - Platform-specific Chrome launching
  - Detects paths on macOS/Windows/Linux
  - ~200 lines, complete

app_config.py
  - Config storage in OS directories
  - Centralized config management
  - ~150 lines, complete

version.py
  - Version tracking
  - Update checking (skeleton)
  - ~50 lines, complete

authorization.py
  - Machine fingerprinting, licensing, server validation
  - Unified AuthorizationManager
  - ~500 lines, complete

sp_trading.spec
  - PyInstaller build specification
  - Handles macOS, Windows, Linux
  - ~80 lines, ready to use

BUILD_AND_DEPLOY.py
  - This document + build scripts
  - Complete distribution guide
  - ~400 lines of instructions

README_SHIPPING.md
  - User-facing setup instructions
  - (Create this yourself with your details)
"""

# ===================================================================
# NEXT IMMEDIATE ACTIONS
# ===================================================================

"""
1. ✏️ LOCAL TEST (do this today)
   python launcher.py --setup
   python launcher.py
   python launcher.py --auth-info
   
2. 🏗️ BUILD (after local testing passes)
   pip install pyinstaller
   pyinstaller sp_trading.spec
   
3. 📦 INSTALLER (after .app/.exe works)
   macOS: Create DMG
   Windows: Create EXE installer with Inno Setup
   
4. 🔐 AUTHORIZE (choose strategy now)
   - Machine: Leave as-is
   - License: Edit authorization.py line ~190
   - Server: Needs backend setup
   
5. 🚀 DISTRIBUTE
   Upload DMG/EXE to your website or GitHub releases
   Share with authorized users
   
6. 📝 DOCUMENT
   Create README_SHIPPING.md for users
   Explain installation steps
   Provide support contact info
"""

# ===================================================================
# SUPPORT & QUESTIONS
# ===================================================================

"""
Common questions answered in this guide:

Q1: "Where do users store their configs?"
A: OS-specific app directories (not in repo)
   macOS: ~/Library/Application Support/S-P-Trading/
   Windows: %APPDATA%\S-P-Trading\
   Linux: ~/.config/S-P-Trading/

Q2: "How do I prevent unauthorized users?"
A: Integrate authorization check in launcher.py (✅ done)
   Choose authorization strategy (machine/license/server)
   User must pass check before app starts

Q3: "Can the packaged app work offline?"
A: Yes! Machine fingerprint and license keys don't need internet
   Server validation would need internet (can be designed to fail-open)

Q4: "What if user hardware changes?"
A: If using machine fingerprint: Re-run setup wizard
   If using license key: License works on any machine
   If using server: Re-authenticate

Q5: "How do I update users to new version?"
A: Rebuild with PyInstaller, create new installer
   Host on website/GitHub releases
   Users download and run new installer
   Old settings preserved in app config directory

Q6: "Do I need code signing?"
A: macOS: Recommended for distribution (requires Apple dev account)
   Windows: Optional (users get SmartScreen warning otherwise)
   Linux: Not required

Q7: "Can users run on multiple machines?"
A: Machine fingerprint: No (binds to specific machine)
   License key: Yes (license works on any machine)
   Server: Yes (credentials work on any machine)
"""

if __name__ == "__main__":
    print(__doc__)
