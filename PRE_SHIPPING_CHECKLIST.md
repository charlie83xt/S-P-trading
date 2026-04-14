"""
PRE-SHIPPING CHECKLIST
S-P Trading Application

Use this checklist to verify everything is ready before distributing
to users. Work through each section sequentially.
"""

# ===================================================================
# SECTION 1: CODE QUALITY & TESTING
# ===================================================================

PRE_SHIP_CODE = """
✓ CODE QUALITY:
  [ ] No print() or debug code left in production files
  [ ] All imports are used (no unused imports)
  [ ] No hardcoded credentials in code (use .env)
  [ ] Error handling covers edge cases
  [ ] Logging configured appropriately
  [ ] No SQL injection vulnerabilities
  [ ] No XSS vulnerabilities in web UI
  [ ] No file path traversal issues

✓ TESTING:
  [ ] python launcher.py --setup works
  [ ] python launcher.py starts app successfully
  [ ] python launcher.py --auth-info shows correct info
  [ ] python launcher.py --version shows correct version
  [ ] Setup wizard accepts all input correctly
  [ ] Chrome launches on port 9222
  [ ] Dashboard launches on port 5000
  [ ] Browser can connect to dashboard UI
  [ ] Strategy can load and display
  [ ] Risk manager settings apply correctly
  [ ] Dry-run mode prevents real trades
  [ ] Emergency stop works
  [ ] App graceful shutdown (Ctrl+C)

✓ AUTHORIZATION:
  [ ] First-time user required to register
  [ ] Authorization check cannot be bypassed
  [ ] Authorization info stored securely (0o600 permissions)
  [ ] Machine fingerprint verified correctly
  [ ] Or license key verified correctly (if using)
  [ ] Wrong fingerprint/key denies access

✓ CONFIGURATION:
  [ ] All required settings have defaults
  [ ] Missing .env doesn't crash app
  [ ] Config saved/loaded correctly
  [ ] Credentials not logged or printed
"""

# ===================================================================
# SECTION 2: BUILD PREPARATION
# ===================================================================

BUILD_PREP = """
✓ VERSION MANAGEMENT:
  [ ] Bumped version in version.py
  [ ] Version format is semantic (X.Y.Z)
  [ ] Version file is checked into git
  [ ] README.md lists version

✓ DEPENDENCIES:
  [ ] All Python dependencies listed in requirements.txt
  [ ] requirements.txt pip install clean on fresh Python
  [ ] No development dependencies in requirements.txt
  [ ] Version pinned for all major dependencies

✓ BUILD CONFIGURATION:
  [ ] sp_trading.spec exists and is complete
  [ ] sp_trading.spec includes all hidden imports
  [ ] sp_trading.spec includes .env.example
  [ ] sp_trading.spec includes templates/
  [ ] PyInstaller installed (pip install pyinstaller)

✓ BUILD ARTIFACTS:
  [ ] dist/ directory will be gitignored
  [ ] build/ directory will be gitignored
  [ ] *.spec file checked into git
  [ ] .gitignore updated if needed
"""

# ===================================================================
# SECTION 3: PLATFORM-SPECIFIC
# ===================================================================

PLATFORM_MACOS = """
✓ MACOS BUILD:
  [ ] Run: pyinstaller sp_trading.spec
  [ ] dist/S-P\ Trading.app exists
  [ ] dist/S-P\ Trading.app/Contents/MacOS/launcher exists
  [ ] App launches: open dist/S-P\ Trading.app
  [ ] App setup wizard works
  [ ] Quit app (Cmd+Q) - no hanging processes
  [ ] Chrome detection works (prints path)
  [ ] Dashboard starts on port 5000
  [ ] No errors in system logs

✓ MACOS DMG INSTALLER:
  [ ] Created DMG: hdiutil create ...
  [ ] DMG size reasonable (< 500MB)
  [ ] DMG mounts successfully
  [ ] App icon visible in DMG
  [ ] Drag-to-Applications works
  [ ] App runs from /Applications
  [ ] No symlinks or broken paths
  [ ] License/README in DMG (optional)

✓ MACOS CODE SIGNING (optional):
  [ ] App signed (or accept warning on first run)
  [ ] Or notarized (if distributing outside App Store)
  [ ] Or user accepts "Unknown Developer" prompt
"""

PLATFORM_WINDOWS = """
✓ WINDOWS BUILD:
  [ ] Run: pyinstaller sp_trading.spec
  [ ] dist\launcher.exe exists
  [ ] dist\_internal\ directory exists with dependencies
  [ ] Exe launches: dist\launcher.exe
  [ ] .exe setup wizard works
  [ ] Right-click properties shows no warnings
  [ ] Close app (Alt+F4) - no hanging processes
  [ ] Chrome detection works on typical Windows paths
  [ ] Dashboard starts on port 5000
  [ ] No antivirus false positives (or whitelist if needed)

✓ WINDOWS INSTALLER (Inno Setup):
  [ ] Inno Setup installed https://jrsoftware.org/isdl.php
  [ ] installer.iss generated from template
  [ ] Run: iscc installer.iss (creates .exe installer)
  [ ] sp_trading_setup.exe created
  [ ] Installer runs on test machine
  [ ] Installer can choose install directory
  [ ] Installer creates Start Menu shortcuts
  [ ] Installer creates Desktop shortcut
  [ ] Uninstaller works (removes files, not user data)
  [ ] Old install settings preserved after update

✓ WINDOWS CODE SIGNING (optional):
  [ ] .exe signed with certificate (or accept UAC warning)
  [ ] Or users accept SmartScreen warning on first run
"""

PLATFORM_LINUX = """
✓ LINUX BUILD:
  [ ] Run: pyinstaller sp_trading.spec
  [ ] dist/launcher executable exists
  [ ] Run: ./dist/launcher
  [ ] Setup wizard works
  [ ] Close app - no hanging processes
  [ ] Chrome detection works
  [ ] Dashboard starts

✓ LINUX APPIMAGE (optional):
  [ ] appimagetool installed
  [ ] AppDir structure created with launcher binary
  [ ] launcher.desktop created
  [ ] Run: appimagetool AppDir sp_trading.AppImage
  [ ] sp_trading.AppImage executable
  [ ] Run: ./sp_trading.AppImage
  [ ] Setup works from AppImage
"""

# ===================================================================
# SECTION 4: SECURITY & PRIVACY
# ===================================================================

SECURITY = """
✓ CREDENTIALS & SECRETS:
  [ ] No API keys in source code
  [ ] No passwords in source code
  [ ] No auth tokens in git history
  [ ] Use only environment variables (.env)
  [ ] .env file in .gitignore
  [ ] Credentials file (auth.json) permissions 0o600
  [ ] Credentials never logged to console
  [ ] Credentials never sent in unencrypted requests

✓ DATA & PRIVACY:
  [ ] Trades logged locally only
  [ ] Logs don't contain PII except username
  [ ] Config doesn't contain user data
  [ ] User data stored only in app config dir
  [ ] No telemetry without user consent
  [ ] Privacy policy accessible (if applicable)

✓ NETWORK SECURITY:
  [ ] API calls use HTTPS where possible
  [ ] SSL certificate validation enabled
  [ ] No insecure HTTP endpoints
  [ ] User credentials not sent in URLs
  [ ] Rate limiting configured

✓ FRONTEND SECURITY:
  [ ] Dashboard CSRF tokens implemented if needed
  [ ] SQL injection prevented (use ORM, parameterized queries)
  [ ] XSS prevented (escape user input in templates)
  [ ] Session timeouts configured
"""

# ===================================================================
# SECTION 5: AUTHORIZATION (CRITICAL)
# ===================================================================

AUTHORIZATION = """
✓ AUTHORIZATION STRATEGY CHOSEN:
  [ ] One selected: Machine Fingerprint / License Key / Server
  [ ] authorization.py STRATEGY variable set correctly
  [ ] Strategy appropriate for user base

✓ MACHINE FINGERPRINT (if using):
  [ ] Fingerprint generation tested
  [ ] Verified on same machine: True
  [ ] Blocked on different machine: Yes (or change hardware)

✓ LICENSE KEYS (if using):
  [ ] Key generation works: LicenseKey.generate_license("user@email.com")
  [ ] Key verification works: LicenseKey.verify_license(key)
  [ ] Signature check prevents tampering
  [ ] Format documented for your team

✓ SERVER AUTH (if using):
  [ ] Auth server deployed and responsive
  [ ] Endpoint documented (URL, port, protocol)
  [ ] Fail-open strategy decided (allow offline: YES/NO)
  [ ] Timeout configured for network delays
  [ ] Token refresh mechanism working

✓ LAUNCHER INTEGRATION:
  [ ] Authorization check happens before app starts
  [ ] Unauthorized users see clear error message
  [ ] Setup wizard prompts for registration email
  [ ] Registration happens during first --setup
  [ ] Authorization verified on every startup
  [ ] Users can check status: python launcher.py --auth-info
"""

# ===================================================================
# SECTION 6: DOCUMENTATION
# ===================================================================

DOCUMENTATION = """
✓ README.md:
  [ ] Installation instructions for users
  [ ] Quick start guide
  [ ] Known issues/limitations listed
  [ ] Support contact info
  [ ] License terms
  [ ] Version number current

✓ SETUP WIZARD:
  [ ] Clear instructions on screen
  [ ] Input validation with helpful errors
  [ ] Credentials example format shown
  [ ] Dry-run mode explained
  [ ] What happens next after setup is clear

✓ ERROR MESSAGES:
  [ ] Authorization failed → explain how to fix
  [ ] Chrome not found → system requirements listed
  [ ] Port already in use → troubleshooting step provided
  [ ] Config error → suggest checking .env.example

✓ USER GUIDE (README_SHIPPING.md):
  [ ] How to install on macOS written
  [ ] How to install on Windows written
  [ ] How to update to new version written
  [ ] Troubleshooting section included
  [ ] FAQ section if needed
"""

# ===================================================================
# SECTION 7: DEPLOYMENT
# ===================================================================

DEPLOYMENT = """
✓ GIT REPOSITORY:
  [ ] On feature/shipping-app branch (or merge to main)
  [ ] All changes committed
  [ ] No uncommitted changes (git status clean)
  [ ] History is clean and logical
  [ ] No temporary files or build artifacts

✓ VERSIONING:
  [ ] Version bumped in version.py
  [ ] Git tag created: git tag v0.1.0
  [ ] Tag pushed: git push origin v0.1.0
  [ ] GitHub release created with notes

✓ DISTRIBUTION SETUP:
  [ ] Download hosting selected (GitHub/S3/Website/Dropbox)
  [ ] DMG uploaded (macOS)
  [ ] setup.exe uploaded (Windows)
  [ ] AppImage uploaded (Linux, if applicable)
  [ ] SHA256 checksum calculated and published
  [ ] Download links documented

✓ USER COMMUNICATION:
  [ ] Release notes written
  [ ] Installation instructions shared
  [ ] Known issues documented
  [ ] Support contact method provided
"""

# ===================================================================
# SECTION 8: POST-DEPLOYMENT
# ===================================================================

POST_DEPLOYMENT = """
✓ MONITORING:
  [ ] Check user questions/issues daily
  [ ] Monitor error logs if available
  [ ] Be ready for critical bug fixes

✓ UPDATES (for v0.1.1):
  [ ] Branching strategy for bug fixes
  [ ] Hotfix vs feature decision process
  [ ] Update distribution process documented

✓ USER FEEDBACK:
  [ ] Channel for bug reports created
  [ ] Channel for feature requests created
  [ ] Response time SLA defined
"""

# ===================================================================
# SIGN-OFF CHECKLIST
# ===================================================================

SIGNIN = """
FINAL SIGN-OFF - Are you ready to ship?

Read each statement. Mark YES or NO.

[ ] YES/NO  Code quality and testing complete
[ ] YES/NO  Build preparation complete
[ ] YES/NO  Platform-specific builds tested
[ ] YES/NO  Security & privacy verified
[ ] YES/NO  Authorization system working
[ ] YES/NO  Documentation complete
[ ] YES/NO  Ready for deployment

If all are YES:
  ✅ READY TO SHIP!
  
If any are NO:
  ❌ STOP - Go back and fix the NO items before shipping
"""

# ===================================================================
# QUICK COMMAND REFERENCE
# ===================================================================

COMMANDS = """
COMMANDS TO RUN IN ORDER:

(1) Update version
    vim version.py
    # Change APP_VERSION = "0.1.1"
    
(2) Test locally
    python launcher.py --setup
    python launcher.py --debug
    # Verify everything works
    
(3) Build
    pyinstaller sp_trading.spec
    
(4) Test executable
    # macOS:
    open dist/S-P\ Trading.app
    # Windows:
    dist\\launcher.exe --setup
    # Linux:
    ./dist/launcher --setup
    
(5) Create installer
    # macOS: Create DMG (see SHIPPING_GUIDE.md)
    # Windows: Use Inno Setup (see SHIPPING_GUIDE.md)
    
(6) Version control
    git add -A
    git commit -m "Release v0.1.1"
    git tag v0.1.1
    git push origin v0.1.1
    
(7) Upload
    # Upload dist/ files to hosting
    # Calculate SHA256: sha256sum dist/*
    
(8) Announce
    # Share download links with users
    # Post on website or GitHub Releases
"""

# ===================================================================
# PRINT ALL SECTIONS
# ===================================================================

if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*70 + "\n")
    print(PRE_SHIP_CODE)
    print("\n" + "="*70 + "\n")
    print(BUILD_PREP)
    print("\n" + "="*70 + "\n")
    print(PLATFORM_MACOS)
    print("\n" + "="*70 + "\n")
    print(PLATFORM_WINDOWS)
    print("\n" + "="*70 + "\n")
    print(PLATFORM_LINUX)
    print("\n" + "="*70 + "\n")
    print(SECURITY)
    print("\n" + "="*70 + "\n")
    print(AUTHORIZATION)
    print("\n" + "="*70 + "\n")
    print(DOCUMENTATION)
    print("\n" + "="*70 + "\n")
    print(DEPLOYMENT)
    print("\n" + "="*70 + "\n")
    print(POST_DEPLOYMENT)
    print("\n" + "="*70 + "\n")
    print(SIGNIN)
    print("\n" + "="*70 + "\n")
    print(COMMANDS)
