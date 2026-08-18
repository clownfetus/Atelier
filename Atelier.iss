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

; Excludes game-derived data — shipping either of these in the installer is a copyright risk, and
; the app already obtains both remotely, so neither needs to ship:
;   Tools\Mappings\*.usmap — pulled by api_download_usmap on first run, kept current by the 3-day
;                            check (api_usmap_update_check).
;   Tools\AES_KEY.txt      — Setup prefills the key from the rivals-depot (_fetchAesKeyValue in
;                            app.js) and save_paks writes the file + updates io_lib.AES_KEY live;
;                            config._auto_fetch_aes then refreshes it on each frozen launch.
; Neither absence blocks first run: setup_status reports configured=false (it keys off
; mr_config.json and USMAP, never off these files), so the Setup overlay opens and collects both.
; BUILD.bat also strips them from dist before this runs — belt and braces, since a stale dist would
; otherwise leak them.
[Files]
Source: "dist\Atelier\*"; DestDir: "{app}"; Excludes: "Tools\Mappings\*,Tools\AES_KEY.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

; Clear stale payload so a removed/renamed .pyd/.dll from an older build can't shadow the new
; one. [Files] uses ignoreversion, which overwrites everything that still ships but never removes
; what no longer does — that gap is what this closes.
;
; THE RULE: only list a path the app never writes to at runtime. NEVER "{app}" — user data lives
; there (assets\projects, assets\exported, _cache, mr_config.json) and a filesandordirs wipe of
; {app} deletes every project the user has ever made.
;
; Tools\ is listed per-subdir, NOT wholesale, because three things in it are runtime-authored:
;   Tools\Mappings\*.usmap        — downloaded on the 3-day check (routes.api_usmap_update_check)
;   Tools\AES_KEY.txt             — rewritten on a key rotation (config._auto_fetch_aes)
;   Tools\MarvelRivalsCharacterIDs.md — written back with fetched IDs (browse._fetch_char_data)
; Mappings must never be listed here. Nothing ships into it (see [Files] Excludes), so a wipe does
; not fall back to a bundled copy — it leaves the user with NO mappings at all, and since
; save_usmap_config() has already pinned the deleted path in mr_config.json while usmap_checked_at
; is still fresh, the 3-day gate blocks an automatic re-fetch. The app would sit unusable behind a
; Setup prereq error until the user re-downloads by hand.
; The loose exes (UAssetTool, UAssetGUI, texconv) always ship, so ignoreversion covers them.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\Tools\AtelierMesh"
Type: filesandordirs; Name: "{app}\Tools\retoc-rivals-cli"
Type: filesandordirs; Name: "{app}\Tools\shaders"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall
