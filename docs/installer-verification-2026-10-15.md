# Windows installer build and payload verification — 15 October 2026

**Result: passed.** Installed Inno Setup 6.7.3, compiled the installer from the fixes worktree, unpacked its tool payload and verified hashes. Atelier itself was not installed or launched by this verification.

## Provenance and artifact

| Field | Value |
|---|---|
| Source commit | `de6f8857c69ccbc03734c70282217eca9e438544` (includes reconciled upstream packaging changes) |
| Source worktree | `C:/Users/thiag/OneDrive/Documents(1)/GitHub/Atelier-triage-fixes` |
| Application version | `0.3.4` (unchanged source version; local fixes build) |
| Python / PyInstaller | 3.12.14 / 6.22.3 |
| Inno Setup | 6.7.3, installed for the current user with winget |
| Compiler | `C:/Users/thiag/AppData/Local/Programs/Inno Setup 6/ISCC.exe` |
| Installer | `dist/AtelierSetup.exe` in the fixes worktree |
| Size | 120,291,944 bytes |
| SHA-256 | `c4ddcb3741333b608f353681c1175de3502d847b4f5f8e8c9e2e4b7a746ba177` |
| Adjacent checksum file | `dist/AtelierSetup.exe.sha256` |
| Native tools source | `D:/AtelierDev/phase-0-1/Tools` |
| Archive verification tool | Inno Unpacker 2.71.1, already present in the isolated development downloads |

Installation used the [official Inno Setup package](https://jrsoftware.org/isdl.php): `winget install --id JRSoftware.InnoSetup --exact --version 6.7.3 --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity`. Winget verified the downloaded installer hash before installing.

The source worktree was clean during the build. PyInstaller’s module table identifies this worktree’s `atelier/handlers/material.py`, `atelier/handlers/texture.py` and `atelier/asset_cache.py`, rather than files from the original checkout containing ongoing GUI work.

## Build commands

Executed from the fixes worktree, with logs redirected under `_work/installer-verification-reconciled`. The build uses a fresh output directory and an exact copy of the committed Inno script:

```powershell
Copy-Item Atelier.iss _work/installer-build-reconciled/Atelier.iss
& '..\Atelier\.venv\Scripts\python.exe' -m PyInstaller --noconfirm `
  --distpath _work/installer-build-reconciled/dist `
  --workpath _work/installer-build-reconciled/build Atelier.spec
& '..\Atelier\.venv\Scripts\python.exe' scripts/stage_tools.py `
  --platform windows --src 'D:\AtelierDev\phase-0-1\Tools' `
  --dist _work/installer-build-reconciled/dist/Atelier
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" '/DAppVersion=0.3.4' `
  _work/installer-build-reconciled/Atelier.iss
```

The compiler completed successfully in 79.937 seconds. The compiled Inno script was hash-checked against the committed source script. After verification, the installer was copied to `dist/AtelierSetup.exe` for delivery. These are the build pipeline’s PyInstaller/staging/audit/Inno steps executed explicitly with the external development tools and the installed per-user compiler. `BUILD.bat` itself still assumes a worktree-local Tools folder and a compiler under Program Files (x86).

An initial build at `1ecdc40` passed verification with 23 tools and a 148,666,585-byte installer. The remote branch advanced during the task; its upstream packaging reconciliation was preserved and the installer rebuilt. The delivered build uses the current allowlist (11 files), and the first installer is retained under `D:/AtelierDev/triage-installer-20261015/first-build-1ecdc40`. Its earlier reports remain under `_work/installer-verification`.

## Verified contents

The finished installer was listed and extracted with Inno Unpacker. All **11 tool files** in the allowlisted staging directory were present in the extracted installer payload with identical SHA-256 hashes, and all 11 matched their original development-tool copies. The four files specifically relevant to the original missing-tool defect are:

| Archive path under `{app}/Tools/` | Bytes | SHA-256 |
|---|---:|---|
| `UAssetTool.exe` | 72,967,783 | `d011149a2cef5541dd0795c20c335394b93bd87dc76d8a4617543ce5a5aa7dfe` |
| `AtelierMesh/AtelierMesh.exe` | 90,846,578 | `5e47848be9e0d027ee014be50b96c8df85ac05bf06b79eeb593a8028dc708cc5` |
| `AtelierMesh/CUE4Parse-Natives.dll` | 38,912 | `b363f3bb51a7bbfcee15aa84dd45da41be273a9605efa2fee76661cb3790dc1b` |
| `AtelierMesh/oo2core_9_win64.dll` | 637,952 | `6f5d41a7892ea6b2db420f2458dad2f84a63901c9a93ce9497337b16c195f457` |

The archive listing contained neither `AES_KEY.txt` nor files under a Mappings directory. No tool was substituted or downloaded again for this build.

Each of the four Inno preprocessor guards was exercised by compiling a disposable copy of `Atelier.iss` with exactly one required file absent. All four rejected compilation with the expected missing-file message and produced no installer. The successful full compilation exercised the same guards with all required files present.

## Evidence and limits

- Worktree-local report: `_work/installer-verification-reconciled/results.json`, containing installer hash, all tool hashes and compiler-guard outcomes.
- Logs: `pyinstaller.log`, `inno-compile.log`, `installer-contents.txt`, `installer-extraction.log`, and `compiler-guard-0.log` through `compiler-guard-3.log` in that same directory.
- Verification procedure: `_work/installer-verification-reconciled/verify_installer.py`.
- Extracted tools: `D:/AtelierDev/triage-installer-20261015-reconciled/unpacked/{app}/Tools`.
- Current packaging and triage export regressions: 35 passed (14 packaging, 21 triage); reports under `_work/installer-reconciled-checks`.
- Installer and reports remain local; no binary release was published. Existing Atelier installations, projects and game mods were not changed.
- Verified archive contents and compiler guards. A clean install, installed-app launch, upgrade behavior and in-game appearance were not tested.

This resolves the missing-compiler limitation in the [triage audit](triage-code-audit-2026-10-15.md#implementation-follow-up).
