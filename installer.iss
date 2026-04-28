; ============================================================
; S-P Trading - Inno Setup 6.x Installer Script
; ============================================================
; Build with:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; Or run:  build_installer.bat
; ============================================================

#define MyAppName      "S-P Trading"
#define MyAppVersion   "0.1.2"
#define MyAppPublisher "The G-House"
#define MyAppURL       "https://dont-go-in.com"
#define MyAppExeName   "S-P Trading.exe"
#define MyAppDataDir   "S-P-Trading"

[Setup]
; Unique app identifier — DO NOT change after first release (breaks upgrades)
; Generate a new one at https://www.guidgenerator.com/
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}

AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/support
AppUpdatesURL={#MyAppURL}/updates
VersionInfoVersion={#MyAppVersion}

; Installation directory — user-level (no admin needed)
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Require 64-bit Windows
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

; No admin rights required (installs per-user)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Output
OutputDir=installer_output
OutputBaseFilename=SP-Trading-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra64

; UI
WizardStyle=modern
; Uncomment these when you have the image assets:
SetupIconFile=assets\icon.ico
; WizardImageFile=assets\installer_banner.bmp
; WizardSmallImageFile=assets\installer_icon.bmp

; License & info pages shown in the wizard
LicenseFile=dist_assets\LICENSE.txt
InfoBeforeFile=dist_assets\INSTALL_INFO.txt
InfoAfterFile=dist_assets\POST_INSTALL.txt

; Auto-create uninstaller
Uninstallable=yes
UninstallDisplayName={#MyAppName}
; UninstallDisplayIcon={app}\{#MyAppExeName}

; Misc
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ============================================================
; TASKS  (checkboxes shown to user during install)
; ============================================================
[Tasks]
Name: "desktopicon";     Description: "Create a &desktop shortcut";           GroupDescription: "Additional shortcuts:"
Name: "startmenufolder"; Description: "Create a &Start Menu folder";           GroupDescription: "Additional shortcuts:"
Name: "autostart";       Description: "Launch S-P Trading on Windows &startup"; GroupDescription: "Startup:"; Flags: unchecked

; ============================================================
; FILES  — copy the PyInstaller dist folder
; ============================================================
[Files]
; Main application (everything PyInstaller produced)
Source: "dist\S-P Trading\*";  DestDir: "{app}";  Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation
Source: "dist_assets\INSTALL_INFO.txt";     DestDir: "{app}"; Flags: isreadme ignoreversion
Source: "dist_assets\LICENSE.txt";    DestDir: "{app}"; Flags: ignoreversion
Source: "dist_assets\POST_INSTALL.txt";  DestDir: "{app}"; Flags: ignoreversion

; ============================================================
; SHORTCUTS
; ============================================================
[Icons]
; Start Menu
Name: "{group}\{#MyAppName}";                        Filename: "{app}\{#MyAppExeName}"; Tasks: startmenufolder
Name: "{group}\Uninstall {#MyAppName}";              Filename: "{uninstallexe}";         Tasks: startmenufolder

; Desktop
Name: "{autodesktop}\{#MyAppName}";                  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Windows startup (optional, user opt-in)
Name: "{userstartup}\{#MyAppName}";                  Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

; ============================================================
; REGISTRY  — store install path for the app to read
; ============================================================
[Registry]
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "InstallDir";  ValueData: "{app}";            Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "Version";     ValueData: "{#MyAppVersion}";  Flags: uninsdeletevalue

; ============================================================
; CLEAN UP on uninstall
; ============================================================
[UninstallDelete]
; Remove the app folder completely
Type: filesandordirs; Name: "{app}"

; ============================================================
; PASCAL CODE  — custom wizard pages
; ============================================================
[Code]

// ── Variables ────────────────────────────────────────────────────────────────
var
  LicensePage : TInputQueryWizardPage;
  ChromePage  : TInputQueryWizardPage;

// ── Wizard initialisation ─────────────────────────────────────────────────────
procedure InitializeWizard;
begin
  // PAGE 1 — License key (optional, can start trial in-app)
  LicensePage := CreateInputQueryPage(
    wpWelcome,
    'License Activation',
    'Enter your license key (optional)',
    'If you have purchased a license, enter your key and expiry below.' + #13#10 +
    'Leave blank to start a free 14-day trial after installation.'
  );
  LicensePage.Add('License Key (SP-XXXX-XXXX-XXXX-XXXX):', False);
  LicensePage.Add('Expiry Code (from purchase email, or "none" for lifetime):', False);
  LicensePage.Add('Your email address (optional):', False);
  LicensePage.Values[0] := '';
  LicensePage.Values[1] := '';
  LicensePage.Values[2] := '';

  // PAGE 2 — Tradovate credentials (optional, can be entered in dashboard)
  ChromePage := CreateInputQueryPage(
    LicensePage.ID,
    'Tradovate Account',
    'Enter your Tradovate credentials (optional)',
    'You can also enter these later in the app dashboard.' + #13#10 +
    'Credentials are stored locally on your machine only.'
  );
  ChromePage.Add('Tradovate username:', False);
  ChromePage.Add('Tradovate password:', True);   // True = masked input
  ChromePage.Values[0] := '';
  ChromePage.Values[1] := '';
end;

// ── After installation completes ──────────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDataDir    : String;
  LicenseFile   : String;
  EnvFile       : String;
  LicKey        : String;
  LicExpiry     : String;
  LicEmail      : String;
  TradoUser     : String;
  TradoPass     : String;
begin
  if CurStep = ssPostInstall then
  begin
    // Create per-user app data directory
    AppDataDir := ExpandConstant('{userappdata}\{#MyAppDataDir}');
    ForceDirectories(AppDataDir);
    ForceDirectories(AppDataDir + '\logs');

    LicKey    := Trim(LicensePage.Values[0]);
    LicExpiry := Trim(LicensePage.Values[1]);
    LicEmail  := Trim(LicensePage.Values[2]);
    TradoUser := Trim(ChromePage.Values[0]);
    TradoPass := Trim(ChromePage.Values[1]);

    // ── Write pending_license.json if a key was entered ─────────────────────
    if LicKey <> '' then
    begin
      LicenseFile := AppDataDir + '\pending_license.json';
      SaveStringToFile(
        LicenseFile,
        '{' + #13#10 +
        '  "license_key": "' + LicKey + '",' + #13#10 +
        '  "expiry_str": "' + LicExpiry + '",' + #13#10 +
        '  "user_email": "' + LicEmail + '",' + #13#10 +
        '  "source": "installer"' + #13#10 +
        '}',
        False
      );
    end;

    // ── Write .env file if Tradovate credentials were entered ────────────────
    if TradoUser <> '' then
    begin
      EnvFile := AppDataDir + '\.env';
      SaveStringToFile(
        EnvFile,
        'TRADOVATE_USERNAME=' + TradoUser + #13#10 +
        'TRADOVATE_PASSWORD=' + TradoPass + #13#10,
        False
      );
    end;

    // ── Write first_run marker so the app shows setup UI ────────────────────
    SaveStringToFile(
      AppDataDir + '\first_run',
      GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':'),
      False
    );
  end;
end;

// ── Launch the app after install if user ticked the checkbox ─────────────────
procedure CurPageChanged(CurPageID: Integer);
begin
  // Nothing extra needed here — handled by [Run] section below
end;

// ── Prevent install if 32-bit Windows ────────────────────────────────────────
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not Is64BitInstallMode then
  begin
    MsgBox(
      'S-P Trading requires a 64-bit version of Windows.' + #13#10 +
      'Please upgrade your operating system and try again.',
      mbError, MB_OK
    );
    Result := False;
  end;
end;

// ============================================================
// [Run] — post-install actions shown on the final wizard page
// ============================================================
[Run]
; Offer to launch the app immediately
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent shellexec

; Offer to open README
Filename: "{app}\README.txt"; \
  Description: "View the README"; \
  Flags: postinstall shellexec skipifsilent unchecked
