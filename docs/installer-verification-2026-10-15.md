# Windows installer build and payload verification — 15 October 2026

**Result: passed.** Installed Inno Setup 6.7.3, compiled the installer from the fixes worktree, unpacked its tool payload and verified hashes. Atelier itself was not installed or launched by this verification.

## Provenance and artifact

| Field | Value |
|---|---|
| Source commit | `1ecdc4094841fb0fcdf5d1d1889f4e7c0b57910b` |
| Source worktree | `C:/Users/thiag/OneDrive/Documents(1)/GitHub/Atelier-triage-fixes` |
| Application version | `0.3.4` (unchanged source version; local fixes build) |
| Python / PyInstaller | 3.12.14 / 6.22.3 |
| Inno Setup | 6.7.3, installed for the current user with winget |
| Compiler | `C:/Users/thiag/AppData/Local/Programs/Inno Setup 6/ISCC.exe` |
| Installer | `dist/AtelierSetup.exe` in the fixes worktree |
| Size | 148,666,585 bytes |
| SHA-256 | `5b4c19adb7fea3e3dd95fa50012f1dbc13bdea96f25e6aef0cf7d6ab3ba2bad4` |
| Adjacent checksum file | `dist/AtelierSetup.exe.sha256` |
| Native tools source | `D:/AtelierDev/phase-0-1/Tools` |
| Archive verification tool | Inno Unpacker 2.71.1, already present in the isolated development downloads |

Installation used the [official Inno Setup package](https://jrsoftware.org/isdl.php): `winget install --id JRSoftware.InnoSetup --exact --version 6.7.3 --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity`. Winget verified the downloaded installer hash before installing.

The source worktree was clean during the build. PyInstaller’s module table identifies this worktree’s `atelier/handlers/material.py`, `atelier/handlers/texture.py` and `atelier/asset_cache.py`, rather than files from the original checkout containing ongoing GUI work.

## Build commands

Executed from the fixes worktree, with logs redirected under `_work/installer-verification`:

```powershell
& '..\Atelier\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean Atelier.spec
& '..\Atelier\.venv\Scripts\python.exe' scripts/stage_tools.py `
  'D:\AtelierDev\phase-0-1\Tools' 'dist\Atelier\Tools'
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" '/DAppVersion=0.3.4' Atelier.iss
```

The compiler completed successfully in 81.172 seconds. These are the build pipeline’s PyInstaller/staging/Inno steps executed explicitly with the external development tools and the installed per-user compiler. `BUILD.bat` itself still assumes a worktree-local Tools folder and a compiler under Program Files (x86).

## Verified contents

The finished installer was listed and extracted with Inno Unpacker. All **23 tool files** in the staged Tools directory were present in the extracted installer payload with identical SHA-256 hashes. The following required files also matched their original development-tool copies:

| Archive path under `{app}/Tools/` | Bytes | SHA-256 |
|---|---:|---|
| `UAssetTool.exe` | 72,967,783 | `d011149a2cef5541dd0795c20c335394b93bd87dc76d8a4617543ce5a5aa7dfe` |
| `AtelierMesh/AtelierMesh.exe` | 90,846,578 | `5e47848be9e0d027ee014be50b96c8df85ac05bf06b79eeb593a8028dc708cc5` |
| `AtelierMesh/CUE4Parse-Natives.dll` | 38,912 | `b363f3bb51a7bbfcee15aa84dd45da41be273a9605efa2fee76661cb3790dc1b` |
| `AtelierMesh/oo2core_9_win64.dll` | 637,952 | `6f5d41a7892ea6b2db420f2458dad2f84a63901c9a93ce9497337b16c195f457` |

The archive listing contained neither `AES_KEY.txt` nor files under a Mappings directory. No tool was substituted or downloaded again for this build.

Each of the four Inno preprocessor guards was exercised by compiling a disposable copy of `Atelier.iss` with exactly one required file absent. All four rejected compilation with the expected missing-file message and produced no installer. The successful full compilation exercised the same guards with all required files present.

## Evidence and limits

- Worktree-local report: `_work/installer-verification/results.json`, containing installer hash, all tool hashes and compiler-guard outcomes.
- Logs: `pyinstaller.log`, `inno-compile.log`, `installer-contents.txt`, `installer-extraction.log`, and `compiler-guard-0.log` through `compiler-guard-3.log` in that same directory.
- Verification procedure: `_work/installer-verification/verify_installer.py`.
- Extracted tools: `D:/AtelierDev/triage-installer-20261015/unpacked/{app}/Tools`.
- Installer and reports remain local; no binary release was published. Existing Atelier installations, projects and game mods were not changed.
- Verified archive contents and compiler guards. A clean install, installed-app launch, upgrade behavior and in-game appearance were not tested.

This resolves the missing-compiler limitation in the [triage audit](triage-code-audit-2026-10-15.md#implementation-follow-up).
