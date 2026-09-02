; Inno Setup script for podharvest.
;
; Builds a conventional Windows installer (Start Menu shortcut, optional
; desktop icon, proper uninstaller) around the PyInstaller "onedir" build in
; dist\podharvest. Unlike the portable .zip build, this installer does NOT
; ship a portable.flag file, so podharvest correctly falls back to storing
; its models/cache/config under the current user's profile
; (%USERPROFILE%\.podharvest) rather than trying to write into Program Files.
;
; Build with (after running scripts/build_installer.ps1 to produce dist\podharvest):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\podharvest.iss
; or just: scripts\build_installer.ps1 -Inno

#define MyAppName "podharvest"
#define MyAppPublisher "podharvest contributors"
#define MyAppURL "https://github.com/community-access/podharvest"
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
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=podharvest-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
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
Source: "..\docs\GETTING_STARTED.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\MODELS.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\ACCESSIBILITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"
Name: "{group}\{#MyAppName} (command line)"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Getting started"; Filename: "{app}\docs\GETTING_STARTED.md"
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
