#define AppName "Atelier"
#ifndef AppVersion
  #define AppVersion "0.0.3"
#endif
#define AppPublisher "Atelier"
#define AppExeName "Atelier.exe"

; Direct compiler invocations must reject incomplete tool staging too.
#if !FileExists("dist\Atelier\Tools\UAssetTool.exe")
  #error Required UAssetTool.exe missing; run BUILD.bat with a complete Tools directory
#endif
#if !FileExists("dist\Atelier\Tools\AtelierMesh\AtelierMesh.exe")
  #error Required AtelierMesh.exe missing; run BUILD.bat with a complete Tools directory
#endif
#if !FileExists("dist\Atelier\Tools\AtelierMesh\CUE4Parse-Natives.dll")
  #error Required AtelierMesh native dependency missing
#endif
#if !FileExists("dist\Atelier\Tools\AtelierMesh\oo2core_9_win64.dll")
  #error Required AtelierMesh Oodle dependency missing
#endif

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

[Code]
// Older Atelier builds veto Restart Manager's synchronous shutdown while their
// native close handler drains managed jobs asynchronously. Ask the actual
// installed window to close normally, then wait before Restart Manager scans.
// No process is terminated and no registry key is renamed or written here.
type
  TAtelierWindow = record
    Window: HWND;
    Process: THandle;
    ProcessId: DWORD;
  end;

var
  AtelierWindows: array of TAtelierWindow;
  AtelierTargetExe: String;

function AtelierEnumWindows(Callback: NativeInt; Data: LPARAM): BOOL;
  external 'EnumWindows@user32.dll stdcall';
function AtelierWindowProcess(Window: HWND; var ProcessId: DWORD): DWORD;
  external 'GetWindowThreadProcessId@user32.dll stdcall';
function AtelierWindowText(Window: HWND; Text: String; Count: Integer): Integer;
  external 'GetWindowTextW@user32.dll stdcall';
function AtelierOpenProcess(Access: DWORD; Inherit: BOOL; ProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function AtelierProcessImage(Process: THandle; Flags: DWORD; Image: String; var Count: DWORD): BOOL;
  external 'QueryFullProcessImageNameW@kernel32.dll stdcall';
function AtelierPostClose(Window: HWND; Msg: UINT; WParam: WPARAM; LParam: LPARAM): BOOL;
  external 'PostMessageW@user32.dll stdcall';
function AtelierWait(Process: THandle; Milliseconds: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function AtelierCloseHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function CollectAtelierWindow(Window: HWND; Data: LPARAM): BOOL;
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
        if (ProcessId <> AtelierWindows[I].ProcessId) or
           (not AtelierPostClose(AtelierWindows[I].Window, $0010, 0, 0)) then begin
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
