#define AppName "Atelier"
#ifndef AppVersion
  #define AppVersion "0.0.3"
#endif
#define AppPublisher "Atelier"
#define AppExeName "Atelier.exe"

[Setup]
AppId={{2E25ABE9-E3D5-4ABA-9E50-725BA75185AF}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=AtelierSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

; Every source is listed by name -- never "dist\Atelier\*". Running dist\Atelier\Atelier.exe to test
; a build writes assets\, _cache\ and mr_config.json beside it, and a wildcard would ship them.
; Tools entries mirror scripts/stage_tools.py's Windows manifest (tests/test_packaging.py checks
; both stay in sync). None carries skipifsourcedoesntexist on purpose: a missing tool fails the
; compile instead of producing an installer without UAssetTool (TRIAGE #39).
; Mappings and AES_KEY.txt are game-derived and never ship; the app fetches both on first run.
[Files]
Source: "dist\Atelier\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Atelier\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Atelier\Tools\UAssetTool.exe"; DestDir: "{app}\Tools"; Flags: ignoreversion
Source: "dist\Atelier\Tools\UAssetGUI.exe"; DestDir: "{app}\Tools"; Flags: ignoreversion
Source: "dist\Atelier\Tools\AtelierMesh\*"; DestDir: "{app}\Tools\AtelierMesh"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Atelier\Tools\shaders\retoc-rivals-cli.exe"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\oo2core_9_win64.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxc.exe"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxcompiler.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxil.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
; A seed only: browse._fetch_char_data writes fetched IDs back into it, so never overwrite.
Source: "dist\Atelier\Tools\MarvelRivalsCharacterIDs.md"; DestDir: "{app}\Tools"; Flags: onlyifdoesntexist uninsneveruninstall

; User data lives beside the exe. These are never installed, never deleted by an upgrade, and
; uninsneveruninstall keeps even an uninstall from removing them.
[Dirs]
Name: "{app}\assets\projects"; Flags: uninsneveruninstall
Name: "{app}\assets\exported"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

; Clear stale payload so a removed/renamed .pyd/.dll from an older build can't shadow the new
; one. [Files] uses ignoreversion, which overwrites everything that still ships but never removes
; what no longer does -- that gap is what this closes.
;
; THE RULE: only list a folder the installer owns outright and the app never writes to. NEVER
; "{app}", "{app}\Tools" or anything under assets\ -- user data lives in {app} (assets\projects,
; assets\exported, _cache, mr_config.json, Tools\Mappings, Tools\AES_KEY.txt) and a wipe of a
; parent deletes every project the user has ever made. tests/test_packaging.py enforces this list.
;   _internal                 PyInstaller output, read-only at runtime
;   Tools\AtelierMesh         vendor drop, shipped whole
;   Tools\retoc-rivals-cli    retired layout; nothing reads it any more
; Tools\shaders is NOT wiped: its files are overwritten by name above, and wiping the folder would
; also take anything a user put there. Mappings must never be listed: nothing ships into it.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\Tools\AtelierMesh"
Type: filesandordirs; Name: "{app}\Tools\retoc-rivals-cli"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall
