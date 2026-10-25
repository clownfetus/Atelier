#define AppName "Atelier"
#ifndef AppVersion
  #error AppVersion must be supplied by the build pipeline
#endif
#define AppPublisher "Atelier"
#define AppExeName "Atelier.exe"

; Direct compiler invocations must reject incomplete tool staging too. scripts/build.py stages
; these from toolchain/tools.lock.json (tests/test_packaging.py keeps this list in sync).
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\UAssetTool.exe")
  #error Required tool missing: Tools\UAssetTool.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\AtelierNative\AtelierNative.exe")
  #error Required tool missing: Tools\AtelierNative\AtelierNative.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\AtelierNative\CUE4Parse-Natives.dll")
  #error Required tool missing: Tools\AtelierNative\CUE4Parse-Natives.dll. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\AtelierNative\oo2core_9_win64.dll")
  #error Required tool missing: Tools\AtelierNative\oo2core_9_win64.dll. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\retoc\retoc-rivals-cli.exe")
  #error Required tool missing: Tools\retoc\retoc-rivals-cli.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\shaders\retoc-rivals-cli.exe")
  #error Required tool missing: Tools\shaders\retoc-rivals-cli.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\shaders\oo2core_9_win64.dll")
  #error Required tool missing: Tools\shaders\oo2core_9_win64.dll. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\shaders\dxc.exe")
  #error Required tool missing: Tools\shaders\dxc.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\shaders\dxcompiler.dll")
  #error Required tool missing: Tools\shaders\dxcompiler.dll. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\shaders\dxil.dll")
  #error Required tool missing: Tools\shaders\dxil.dll. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\texconv.exe")
  #error Required tool missing: Tools\texconv.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\UAssetGUI.exe")
  #error Required tool missing: Tools\UAssetGUI.exe. Run scripts/build.py
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\MarvelRivalsCharacterIDs.md")
  #error Required tool missing: Tools\MarvelRivalsCharacterIDs.md. Run scripts/build.py
#endif

[Setup]
; This script lives in packaging/; every Source path is relative to the repository root.
SourceDir=..
AppId={{2E25ABE9-E3D5-4ABA-9E50-725BA75185AF}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName=Atelier {#AppVersion}
VersionInfoVersion={#AppVersion}
SetupIconFile=icon.ico
LicenseFile=LICENSE
ArchitecturesAllowed=x64compatible
MinVersion=10.0
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/clownfetus/Atelier
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=AtelierSetup
Compression=lzma2
SolidCompression=yes
; Native controls retain keyboard, screen-reader, high-contrast and DPI support.
; Generated plates share the app's A silhouette and connected Krackle ink system.
WizardStyle=modern dynamic windows11 hidebevels
WizardSizePercent=125,125
DisableWelcomePage=no
WizardBackColor=#eee5cf
WizardBackColorDynamicDark=#121216
WizardImageFile=gui\brand\installer\wizard-light.png
WizardImageFileDynamicDark=gui\brand\installer\wizard-dark.png
WizardImageBackColor=#eee5cf
WizardImageBackColorDynamicDark=#121216
WizardSmallImageFile=gui\brand\installer\wizard-mark.png
WizardSmallImageFileDynamicDark=gui\brand\installer\wizard-mark.png
WizardSmallImageBackColor=#eee5cf
WizardSmallImageBackColorDynamicDark=#121216
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\{#AppExeName}
; An upgrade keeps the exe's path, so Explorer keeps showing its cached icon; this asks it to
; refresh at the end of setup so a redrawn mark reaches existing shortcuts.
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[LangOptions]
DialogFontName=Segoe UI
DialogFontSize=10
WelcomeFontName=Segoe UI
WelcomeFontSize=20

[Messages]
WelcomeLabel1=Welcome to Atelier
WelcomeLabel2=Your workspace for Marvel Rivals mods.%n%nCreate textures, shape materials, and bring your ideas into the game.%n%nSetup will install Atelier {#AppVersion} and its editing tools for your Windows account.
WizardSelectDir=Give Atelier a home
SelectDirDesc=Choose where to install your workspace.
WizardSelectTasks=Make yourself at home
SelectTasksDesc=Choose your shortcuts.
WizardReady=Ready to install Atelier
ReadyLabel1=Your workspace is ready to be installed. Review the details below, then choose Install.
WizardInstalling=Setting up your workspace
InstallingLabel=Installing Atelier and its editing tools. Your workspace will be ready shortly.
FinishedHeadingLabel=Atelier is ready
FinishedLabelNoIcons=Your workspace is installed.%n%nOpen Atelier to find your game and start creating.
FinishedLabel=Your workspace is installed.%n%nOpen Atelier to find your game and start creating.
BeveledLabel=Atelier  /  {#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

; Every source is listed by name -- never "dist\Atelier\*". Running dist\Atelier\Atelier.exe to test
; a build writes assets\, _cache\ and mr_config.json beside it, and a wildcard would ship them.
; Tools entries mirror toolchain/tools.lock.json via stage_tools.py (tests/test_packaging.py checks
; both stay in sync). None carries skipifsourcedoesntexist on purpose: a missing tool fails the
; compile instead of producing an installer without UAssetTool (TRIAGE #39).
; Mappings and AES_KEY.txt are game-derived and never ship; the app fetches both on first run.
[Files]
Source: "dist\Atelier\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Atelier\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Atelier\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Atelier\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Atelier\Tools\UAssetTool.exe"; DestDir: "{app}\Tools"; Flags: ignoreversion
Source: "dist\Atelier\Tools\AtelierNative\AtelierNative.exe"; DestDir: "{app}\Tools\AtelierNative"; Flags: ignoreversion
Source: "dist\Atelier\Tools\AtelierNative\CUE4Parse-Natives.dll"; DestDir: "{app}\Tools\AtelierNative"; Flags: ignoreversion
Source: "dist\Atelier\Tools\AtelierNative\oo2core_9_win64.dll"; DestDir: "{app}\Tools\AtelierNative"; Flags: ignoreversion
Source: "dist\Atelier\Tools\retoc\retoc-rivals-cli.exe"; DestDir: "{app}\Tools\retoc"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\retoc-rivals-cli.exe"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\build-inputs.json"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\licenses\*"; DestDir: "{app}\Tools\shaders\licenses"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\oo2core_9_win64.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxc.exe"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxcompiler.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\shaders\dxil.dll"; DestDir: "{app}\Tools\shaders"; Flags: ignoreversion
Source: "dist\Atelier\Tools\texconv.exe"; DestDir: "{app}\Tools"; Flags: ignoreversion
Source: "dist\Atelier\Tools\UAssetGUI.exe"; DestDir: "{app}\Tools"; Flags: ignoreversion
; Versions of the shipped tools, for the in-app tool updater (Settings > Tools).
Source: "dist\Atelier\Tools\tools.json"; DestDir: "{app}\Tools"; Flags: ignoreversion
Source: "dist\Atelier\Tools\THIRD_PARTY_TOOLS.md"; DestDir: "{app}\Tools"; Flags: ignoreversion
; A seed only: browse._fetch_char_data writes fetched IDs back into it, so never overwrite.
Source: "dist\Atelier\Tools\MarvelRivalsCharacterIDs.md"; DestDir: "{app}\Tools"; Flags: onlyifdoesntexist uninsneveruninstall
; Project Galacta's Skin Swapper template is optional (stage_tools.py GALACTA_TEMPLATE): it is never in
; git, so a build without it simply cannot export Skin Swapper mods. A compile-time check, not
; skipifsourcedoesntexist, so a required tool can still never be skipped silently.
#if FileExists(AddBackslash(SourcePath) + "..\dist\Atelier\Tools\Galacta\GAL_ConfigTemplate.uasset")
Source: "dist\Atelier\Tools\Galacta\GAL_ConfigTemplate.uasset"; DestDir: "{app}\Tools\Galacta"; Flags: ignoreversion
Source: "dist\Atelier\Tools\Galacta\GAL_ConfigTemplate.uexp"; DestDir: "{app}\Tools\Galacta"; Flags: ignoreversion
#endif

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
;   Tools\AtelierNative       built by scripts/toolchain.py, shipped whole
;   Tools\retoc               upstream retoc; the in-app tool updater keeps its rollback copy inside
;   Tools\AtelierMesh, Tools\AtelierAnimation, Tools\AtelierImport, Tools\retoc-rivals-cli
;                             retired layouts (merged into AtelierNative / retoc); nothing reads them
; Tools\shaders is NOT wiped: its files are overwritten by name above, and wiping the folder would
; also take anything a user put there. Mappings must never be listed: nothing ships into it.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\Tools\AtelierNative"
Type: filesandordirs; Name: "{app}\Tools\retoc"
Type: filesandordirs; Name: "{app}\Tools\AtelierMesh"
Type: filesandordirs; Name: "{app}\Tools\AtelierAnimation"
Type: filesandordirs; Name: "{app}\Tools\AtelierImport"
Type: filesandordirs; Name: "{app}\Tools\retoc-rivals-cli"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall

[Code]
// Older Atelier builds veto Restart Manager's synchronous shutdown while their
// native close handler drains managed jobs asynchronously. Ask the actual
// installed window to close normally, then wait before Restart Manager scans.
// No process is terminated and no registry key is renamed or written here.
type
#if Ver < 0x07000000
  // Inno Setup 6 is a 32-bit process; version 7 adds native-width script types.
  TAtelierPointer = LongWord;
#else
  TAtelierPointer = NativeInt;
#endif
  TAtelierWindow = record
    Window: HWND;
    Process: THandle;
    ProcessId: DWORD;
  end;

var
  AtelierWindows: array of TAtelierWindow;
  AtelierTargetExe: String;

function AtelierEnumWindows(Callback: TAtelierPointer; Data: TAtelierPointer): BOOL;
  external 'EnumWindows@user32.dll stdcall';
function AtelierWindowProcess(Window: HWND; var ProcessId: DWORD): DWORD;
  external 'GetWindowThreadProcessId@user32.dll stdcall';
function AtelierWindowText(Window: HWND; Text: String; Count: Integer): Integer;
  external 'GetWindowTextW@user32.dll stdcall';
function AtelierOpenProcess(Access: DWORD; Inherit: BOOL; ProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function AtelierProcessImage(Process: THandle; Flags: DWORD; Image: String; var Count: DWORD): BOOL;
  external 'QueryFullProcessImageNameW@kernel32.dll stdcall';
function AtelierPostClose(Window: HWND; Msg: UINT; WParam: TAtelierPointer; LParam: TAtelierPointer): BOOL;
  external 'PostMessageW@user32.dll stdcall';
function AtelierWait(Process: THandle; Milliseconds: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function AtelierCloseHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function CollectAtelierWindow(Window: HWND; Data: TAtelierPointer): BOOL;
var
  ProcessId, Count: DWORD;
  Process: THandle;
  Image, Title: String;
  I, N: Integer;
  Retained: Boolean;
begin
  Result := True;
  ProcessId := 0;
  AtelierWindowProcess(Window, ProcessId);
  if ProcessId = 0 then Exit;
  // SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; never PROCESS_TERMINATE.
  Process := AtelierOpenProcess($00101000, False, ProcessId);
  if Process = 0 then Exit;
  Retained := False;
  try
    Count := 32768;
    SetLength(Image, Count);
    if not AtelierProcessImage(Process, 0, Image, Count) then Exit;
    SetLength(Image, Count);
    if CompareText(ExpandFileName(Image), AtelierTargetExe) <> 0 then Exit;
    // The title identifies the main window only AFTER its executable is matched.
    SetLength(Title, 256);
    SetLength(Title, AtelierWindowText(Window, Title, 256));
    if Title <> '{#AppName}' then Exit;
    for I := 0 to GetArrayLength(AtelierWindows) - 1 do
      if AtelierWindows[I].ProcessId = ProcessId then Exit;
    N := GetArrayLength(AtelierWindows);
    SetArrayLength(AtelierWindows, N + 1);
    AtelierWindows[N].Window := Window;
    AtelierWindows[N].Process := Process;
    AtelierWindows[N].ProcessId := ProcessId;
    Retained := True;
  finally
    if not Retained then AtelierCloseHandle(Process);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I, Poll: Integer;
  ProcessId, WaitResult: DWORD;
  AllExited: Boolean;
begin
  Result := '';
  // Preserve the documented command-line choice to leave applications alone.
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOCLOSEAPPLICATIONS') = 0 then Exit;
  AtelierTargetExe := ExpandFileName(ExpandConstant('{app}\{#AppExeName}'));
  SetArrayLength(AtelierWindows, 0);
  try
    if not AtelierEnumWindows(CreateCallback(@CollectAtelierWindow), 0) then begin
      Result := 'Could not inspect running applications. Close Atelier and try again.';
      Exit;
    end;
    if GetArrayLength(AtelierWindows) = 0 then Exit;
    if not WizardSilent then
      if SuppressibleMsgBox('Atelier must close before updating. Active jobs will be allowed to finish shutting down. Close Atelier now?',
          mbConfirmation, MB_YESNO, IDYES) <> IDYES then begin
        Result := 'Close Atelier when ready, then try the update again.';
        Exit;
      end;
    for I := 0 to GetArrayLength(AtelierWindows) - 1 do begin
      if AtelierWait(AtelierWindows[I].Process, 0) <> 0 then begin
        ProcessId := 0;
        AtelierWindowProcess(AtelierWindows[I].Window, ProcessId);
        if ProcessId <> AtelierWindows[I].ProcessId then begin
          Result := 'The Atelier window changed while preparing the update. Close Atelier and try again.';
          Exit;
        end;
        if not AtelierPostClose(AtelierWindows[I].Window, $0010, 0, 0) then begin
          Result := 'Could not request a normal Atelier shutdown. Close Atelier and try again.';
          Exit;
        end;
        Log(Format('Requested graceful close of %s (PID %d).', [AtelierTargetExe, ProcessId]));
      end;
    end;
    // Retained process handles avoid confusing recycled PIDs with the old app.
    // One shared 90-second budget; a timeout aborts BEFORE any payload changes.
    for Poll := 1 to 900 do begin
      AllExited := True;
      for I := 0 to GetArrayLength(AtelierWindows) - 1 do begin
        WaitResult := AtelierWait(AtelierWindows[I].Process, 0);
        if WaitResult = $00000102 then
          AllExited := False
        else if WaitResult <> 0 then begin
          Result := 'Could not verify Atelier shutdown. Close Atelier and try again.';
          Exit;
        end;
      end;
      if AllExited then begin
        Log('Atelier completed graceful shutdown before the Restart Manager scan.');
        Exit;
      end;
      Sleep(100);
    end;
    Result := 'Atelier is still shutting down after 90 seconds. Let active jobs finish, close Atelier, and try again. No application was force-closed.';
  finally
    for I := 0 to GetArrayLength(AtelierWindows) - 1 do
      AtelierCloseHandle(AtelierWindows[I].Process);
    SetArrayLength(AtelierWindows, 0);
  end;
end;
