@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: S-P TRADING — COMPLETE BUILD + INSTALLER SCRIPT
:: ============================================================
:: Usage:
::   build_installer.bat              (builds current version)
::   build_installer.bat 1.2.0        (sets version before building)
:: ============================================================

set VERSION=%~1
if "%VERSION%"=="" (
    :: Read version from version.py
    for /f "tokens=2 delims==''" %%A in ('findstr /i "APP_VERSION" version.py') do (
        set VERSION=%%A
    )
)
if "%VERSION%"=="" set VERSION=1.0.0

echo.
echo ============================================================
echo  S-P TRADING — FULL BUILD
echo  Version: %VERSION%
echo ============================================================
echo.

:: ── Check prerequisites ──────────────────────────────────────────────────────
echo [PRE] Checking prerequisites...

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    pause & exit /b 1
)

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found. Run: pip install pyinstaller
    pause & exit /b 1
)

if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
) else (
    echo [ERROR] Inno Setup 6 not found.
    echo         Download from: https://jrsoftware.org/isdl.php
    pause & exit /b 1
)


echo [OK]  All prerequisites found.
echo.

:: ── Step 1: Clean previous builds ───────────────────────────────────────────
echo [1/6] Cleaning previous builds...
if exist build        rmdir /s /q build
if exist dist         rmdir /s /q dist
if exist installer_output rmdir /s /q installer_output
echo [OK]  Clean complete.
echo.

:: ── Step 2: Update version.py ───────────────────────────────────────────────
echo [2/6] Updating version to %VERSION%...
python -c "
import re, sys
with open('version.py', 'r') as f:
    content = f.read()
content = re.sub(r'APP_VERSION\s*=\s*[\"''][^\"'']*[\"'']', 'APP_VERSION = \"%s\"' % sys.argv[1], content)
with open('version.py', 'w') as f:
    f.write(content)
print('  version.py updated to %s' % sys.argv[1])
" %VERSION%
if errorlevel 1 (
    echo [WARN] Could not auto-update version.py — update manually if needed
)
echo.

:: ── Step 3: PyInstaller build ────────────────────────────────────────────────
echo [3/6] Building application with PyInstaller...
pyinstaller sp_trading_windows.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    pause & exit /b 1
)
echo [OK]  PyInstaller build complete.
echo.

:: ── Step 4: Copy distribution assets ────────────────────────────────────────
echo [4/6] Preparing distribution assets...

if not exist dist_assets mkdir dist_assets

:: Copy docs to dist folder and dist_assets
if exist README.md (
    copy /y README.md "dist\S-P Trading\README.txt" >nul
    copy /y README.md "dist_assets\README.txt" >nul
)
if exist LICENSE.txt (
    copy /y LICENSE.txt "dist\S-P Trading\LICENSE.txt" >nul
    copy /y LICENSE.txt "dist_assets\LICENSE.txt" >nul
)
if exist CHANGELOG.md (
    copy /y CHANGELOG.md "dist\S-P Trading\CHANGELOG.txt" >nul
    copy /y CHANGELOG.md "dist_assets\CHANGELOG.txt" >nul
)

:: Create INSTALL_INFO.txt if it doesn't exist
if not exist dist_assets\INSTALL_INFO.txt (
    echo Welcome to S-P Trading v%VERSION% > dist_assets\INSTALL_INFO.txt
    echo. >> dist_assets\INSTALL_INFO.txt
    echo SYSTEM REQUIREMENTS: >> dist_assets\INSTALL_INFO.txt
    echo - Windows 10 or later ^(64-bit^) >> dist_assets\INSTALL_INFO.txt
    echo - Google Chrome installed >> dist_assets\INSTALL_INFO.txt
    echo - Internet connection >> dist_assets\INSTALL_INFO.txt
    echo. >> dist_assets\INSTALL_INFO.txt
    echo A free 14-day trial is available - no credit card required. >> dist_assets\INSTALL_INFO.txt
)

:: Create POST_INSTALL.txt if it doesn't exist
if not exist dist_assets\POST_INSTALL.txt (
    echo Installation complete! >> dist_assets\POST_INSTALL.txt
    echo. >> dist_assets\POST_INSTALL.txt
    echo Launch S-P Trading from your Start Menu or Desktop. >> dist_assets\POST_INSTALL.txt
    echo. >> dist_assets\POST_INSTALL.txt
    echo On first launch, a browser window will open for setup. >> dist_assets\POST_INSTALL.txt
    echo Follow the on-screen instructions to activate your license. >> dist_assets\POST_INSTALL.txt
)

echo [OK]  Assets prepared.
echo.

:: ── Step 5: Build installer ──────────────────────────────────────────────────
echo [5/6] Building installer with Inno Setup...
%ISCC% /DMyAppVersion=%VERSION% installer.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup build failed!
    pause & exit /b 1
)
echo [OK]  Installer built.
echo.

:: ── Step 6: Generate checksum ────────────────────────────────────────────────
echo [6/6] Generating SHA-256 checksum...
set INSTALLER=installer_output\SP-Trading-Setup-v%VERSION%.exe
if exist "%INSTALLER%" (
    certutil -hashfile "%INSTALLER%" SHA256 > "%INSTALLER%.sha256"
    echo [OK]  Checksum written to %INSTALLER%.sha256
) else (
    echo [WARN] Installer file not found — skipping checksum
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Installer : %INSTALLER%
echo.
if exist "%INSTALLER%.sha256" (
    echo  Checksum:
    type "%INSTALLER%.sha256"
)
echo.
echo  Next steps:
echo    1. Test installer on a clean Windows machine
echo    2. Upload to your download page
echo    3. Tag the release: git tag v%VERSION%
echo.
pause
