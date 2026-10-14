# Local development and reliability checks

This branch implements the environment/baseline and critical reliability work before the Material 3 redesign. The application still uses Bottle, vanilla JavaScript, Three.js and pywebview. Project sidecars, Unreal paths and mod container formats are unchanged.

## This machine

The configured development directory is **`D:\AtelierDev\phase-0-1`**. It contains the native tools, a separate configuration, disposable projects, test exports, reports and screenshots. Its mods destination is `D:\AtelierDev\phase-0-1\test-mods`; it does not install into the game's mods folder. The existing `D:\Atelier` installation and projects were not edited.

From this repository in PowerShell:

```powershell
.\Start-AtelierDev.ps1 -DataDir 'D:\AtelierDev\phase-0-1'
# Open http://127.0.0.1:8767; Ctrl+C stops the browser-mode backend.

.\Start-AtelierDev.ps1 -Mode Desktop -DataDir 'D:\AtelierDev\phase-0-1'
```

Use one instance per data directory. Browser mode supports `-Port 8770`; the existing desktop shell uses port 8767. Desktop mode enables developer tools. The source frontend is served with caching disabled, so reload after JavaScript/CSS changes; restart Python after backend changes.

`ATELIER_DATA_DIR` relocates configuration, projects, caches, exports, sets, logs and the desktop browser profile. GUI files still load from the source checkout. Without this variable, existing installations retain their original paths. Choose a normal local NTFS directory, preferably on the game's drive: the mesh tool uses hardlinks to a vanilla-only pak mirror. Codex's redirected Windows app-data storage rejected access to those hardlinks during testing; the directory above works.

## Recreate the environment

Use 64-bit Python 3.12 and Node.js (Node is needed by existing JavaScript regression tests, not by the application). On Windows the desktop shell also needs Microsoft Edge WebView2.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\Install-AtelierTools.ps1 -DataDir 'D:\AtelierDev\phase-0-1'
```

The installer script verifies release SHA-256 digests and extracts files without running AtelierSetup or changing registry/install settings. It preserves existing tool directories, keys and mappings. The full [Atelier 0.3.3 Windows bundle](https://github.com/clownfetus/Atelier/releases/tag/0.3.3) contains the fork's custom shader `retoc-rivals-cli`; the ordinary newer retoc release does **not** expose `dump-shaders` and `extract-shader`. Extraction uses the [maintained Inno Unpacker release](https://github.com/jrathlev/InnoUnpacker-Windows-GUI/releases/tag/ui_2_2_13). `tools-manifest.json` records installed binary hashes.

This machine additionally has the official Microsoft DXC 1.9.2609.5 tools, and AtelierMesh from the developer's [0.3.4 release bundle](https://github.com/clownfetus/Atelier/releases/tag/0.3.4). Native smoke checks verify the commands Atelier actually calls. Do not replace these tools based on version numbers alone.

For a fresh directory, use Atelier's Setup/Settings to select the game Paks folder, current mapping, Blender executable and a **development test-mods directory**. Keep native tools, AES keys, mappings, extracted game assets and local configuration out of Git. The source checkout contains none of those dependencies.

## Automated checks

```powershell
.\.venv\Scripts\python.exe tests/run_checks.py --report-dir 'D:\AtelierDev\phase-0-1\checks'
.\.venv\Scripts\python.exe tests/browser_smoke.py --report-dir 'D:\AtelierDev\phase-0-1\browser-checks'
node --check gui/app.js
node --check gui/viewport.js
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

`run_checks.py` copies the source into a fresh temporary directory for each suite. It never reads the development tools or user projects. Native-dependent legacy cases therefore explicitly skip. Use `--suite test_reliability.py` for focused backend failure tests. Logs, package versions, timings and exit codes are saved with the report.

Browser checks run the real frontend and Bottle server in temporary app data. They use named fixtures for game browsing and native/network services, plus actual project HTTP requests. They exercise failed/partial saves, retry, editing while a save is in flight, project headers, stale preview responses and SSE errors. Test-only viewport access is injected into the intercepted module; production JavaScript has no test hooks. Screenshots cover 1280×800, 1400×900 and 1920×1080. The visual baseline uses `gui/app.js` from commit `2a3f4e2` with the unchanged HTML/CSS/vendor files and deterministic fixture data.

## Native checks

```powershell
$env:ATELIER_DATA_DIR = 'D:\AtelierDev\phase-0-1'
.\.venv\Scripts\python.exe tests/native_smoke.py
.\.venv\Scripts\python.exe tests/desktop_smoke.py
```

`native_smoke.py` reads a small real game texture, creates a new disposable project, edits it, builds the `.pak/.ucas/.utoc` set, publishes to a test folder, compares hashes, unpacks it and checks texture format/dimensions. The game's global container is copied into the readback fixture so native tools can resolve script imports. Reports stay under `native-checks`. This is a pipeline smoke test; it does not establish every texture format, game patch, material, world or mesh as compatible.

`desktop_smoke.py` opens and closes a hidden WebView2 window. It checks the real asset browser, icons, active project and viewport module; its middleware suppresses update downloads and thumbnail prefetch. The verified run loaded 69 root entries and 154 icons. The report is `desktop-smoke.json`.

AtelierMesh was also exercised on `Characters/1029/1029100/Meshes/10291/SK_10291_1029100`. To repeat Chromium rendering/disposal checks with that decoded file:

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py `
  --report-dir 'D:\AtelierDev\phase-0-1\browser-checks' `
  --mesh 'D:\AtelierDev\phase-0-1\native-checks\mesh\Marvel\Content\Marvel\Characters\1029\1029100\Meshes\10291\SK_10291_1029100.glb'
```

This checks geometry rendering and resource disposal through three open/close cycles. Its material API is deliberately stubbed: the screenshot is a geometry preview, not evidence of material fidelity.

## Packaging

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm `
  --distpath 'D:\AtelierDev\phase-0-1\build\dist' `
  --workpath 'D:\AtelierDev\phase-0-1\build\work' Atelier.spec
```

The existing spec packages the GUI, vendor libraries and Blender scripts. Native tools remain external. Set `ATELIER_DATA_DIR` before launching the built executable to use the isolated tools/configuration. This command builds a local executable; it does not publish a release or run the installer.

## Review and follow-up

See [RELIABILITY.md](RELIABILITY.md) for the fixes, evidence, API compatibility and remaining limitations. Before release, manually validate representative texture/material/dye, VFX/curve/text, world, Blender, protected-mod and repatch workflows with a supported game version. In-game verification remains a separate release gate.
