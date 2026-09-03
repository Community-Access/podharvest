; Inno Setup script for podharvest.
;
; Builds a conventional Windows installer (Start Menu shortcut, optional
; desktop icon, proper uninstaller) around the PyInstaller "onedir" build in
; dist\podharvest. Unlike the portable .zip build, this installer does NOT
; ship a portable.flag file, so podharvest correctly falls back to storing
; its models/cache/config under the current user's profile
; (%USERPROFILE%\.podharvest) rather than trying to write into Program Files.
;
; Requires Inno Setup 7. Two of its features are the reason:
;
;   SetupArchitecture=x64 builds a genuine 64-bit installer, matching the
;   64-bit PyInstaller build it wraps, and bringing high-entropy ASLR by
;   default.
;
;   Extended-length path support removes the MAX_PATH limit throughout Setup
;   and Uninstall. That matters here more than for most programs: podharvest
;   builds deep trees -- <output>\<show>\transcripts\<long-episode-slug>.md --
;   out of titles a publisher chose, and long-path limits are named in
;   SECURITY.md as a real source of bugs in this program.
;
; Build with (after scripts\build_installer.ps1 produces dist\podharvest):
;   "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" installer\podharvest.iss
; or just: scripts\build_installer.ps1 -Inno

#define MyAppName "podharvest"
#define MyAppPublisher "podharvest contributors"
#define MyAppURL "https://github.com/community-access/podharvest"
#define MyAppSupport "support@community-access.org"
#define MyAppExeName "podharvest.exe"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{B7B6C6C4-6E56-4B21-9B1E-2B7B3A8E9D01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppContact={#MyAppSupport}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=podharvest-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; -- Inno Setup 7 ----------------------------------------------------------
; A 64-bit installer for a 64-bit application. This also makes
; ArchitecturesAllowed and ArchitecturesInstallIn64BitMode default to
; x64compatible, so neither is restated below.
SetupArchitecture=x64
; Windows 10 and later: the bundled Python and wxPython require it, and saying
; so gives a clear refusal up front rather than a confusing failure later.
MinVersion=10.0
; Ask Windows' Restart Manager to close a running copy before overwriting it,
; so upgrading over an open podharvest works instead of failing on a locked
; file. Nothing is relaunched afterwards without being asked.
CloseApplications=yes
RestartApplications=no

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} setup

; Program Files requires elevation to write to, which is correct here since
; the app itself only ever writes to the current user's profile at runtime.
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything PyInstaller produced in dist\podharvest, except the portable
; marker (an installed copy is never "portable" - it belongs to one user
; profile, which is the whole point of an installer over a zip).
Source: "..\dist\podharvest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.flag"
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\GETTING_STARTED.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\REFERENCE.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\MODELS.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\ACCESSIBILITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"
Name: "{group}\{#MyAppName} (command line)"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Getting started"; Filename: "{app}\docs\GETTING_STARTED.md"
Name: "{group}\Technical reference"; Filename: "{app}\docs\REFERENCE.md"
Name: "{group}\Accessibility statement"; Filename: "{app}\docs\ACCESSIBILITY.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Never delete the user's models/cache/config on uninstall - that lives in
; the user profile (~/.podharvest), entirely outside {app}, and is left
; alone intentionally so re-installing doesn't force re-downloading models.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\tmp"
