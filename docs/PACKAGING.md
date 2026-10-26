# Preparing a public release

For normal updates, use **Actions → Release Atelier** or push a numeric `v*` tag.
See [automatic releases and in-app updates](automatic-releases.md) for the release
controls, signing, patch compatibility and verification. The candidate procedure
below remains available for historical/manual verification.

Dispatch `.github/workflows/release-candidate.yml` against the release commit (or push a
`codex/release-*` / `release/*-candidate` branch). It builds the Windows installer and the Linux
AppImage **from source** with the pinned toolchain, runs the backend and browser suites, verifies the
frozen WebView2 app, upgrades from the previous installer on disposable Windows runners, checks the
real Linux GTK/WebKit window and upgrade preservation, and assembles the source archive, checksums
and `VERIFICATION.json`, with the matching Windows portable ZIP, screenshots, release notes and
Discord paste. Every gate must pass before the `Atelier-<version>-release` artifact exists.

What is pinned, and where:

| Input | Pinned in |
|---|---|
| Python 3.15 packages | `requirements.txt`, `requirements-dev.txt`, `requirements-build.txt` |
| Every native tool (source commits, patches, release hashes) | `toolchain/tools.lock.json` |
| Shader tool build inputs (upstream archives, Rust, llvm-mingw) | `native/AtelierShader/build.lock.json` |
| Inno Setup 6.7.3 | `scripts/windows_toolchain.json` (`scripts/bootstrap_windows.ps1`) |
| appimagetool 1.9.1 | `packaging/linux/build_appimage.sh` |
| Previous release for upgrade tests | `tests/fixtures/installer/release-<version>-inputs.json` |

Create the inputs file for a new version before dispatching (copy the previous one and point it at
the last published installer and AppImage with their SHA-256). The Galacta template pair comes from
the two `GALACTA_TEMPLATE_*_B64` encrypted repository inputs; it is bundled only inside Atelier and
never added to Git or source archives.

Do not run installer integration checks on a normal workstation: the harness admits only
disposable GitHub-hosted Windows runners. The stable AppId is unchanged so existing installations
are found and upgraded in place.

The workflow does not publish. Review the run and its hashes, prepare a draft release with the
assets and the release notes, then publish the tested commit. `scripts/release_bundle.py` rejects an
installer or AppImage whose hash disagrees with its test report, and a Windows manifest whose source
commit/version differs from the checkout. Portable files must match that manifest. Screenshot hashes
and version must match `images/screenshots.json`; stale or missing release copy stops bundle assembly.

## Local builds

```powershell
.\BUILD.bat                     # Windows installer: dist\AtelierSetup.exe
```

```bash
.venv/bin/python scripts/build.py --platform linux   # dist/Atelier-<version>-x86_64.AppImage
```

`scripts/build.py --no-package` stops after `dist/Atelier` is staged and audited. The installed
`Tools/tools.json` records each tool's version for Settings > Tools, and
`Tools/THIRD_PARTY_TOOLS.md` lists every tool's licence and exact source (the GPL tools are built
from the pinned commits and patches it names).

## Windows review package

The portable review package contains `Atelier.exe` and its required `_internal`
directory. It excludes native modding tools, local configuration, projects, game
files, AES keys and mappings. It is unsigned and does not run an installer or
publish a release.

Install the pinned development requirements first, then commit the intended
changes. Run from a clean checkout using 64-bit Python on Windows:

```powershell
.\.venv\Scripts\python.exe scripts/package_release.py --output-dir 'D:\AtelierBuilds\review'
```

Use an output directory outside the repository. The script builds with the
existing PyInstaller spec, verifies all GUI and standalone Blender files against
source, checks for unwanted local/game data, and includes runtime and vendor
license notices. It creates:

- `Atelier-Studio-Windows-x64-<commit>.zip`: the portable application.
- `Atelier-Studio-source-<commit>.zip`: the matching committed source from Git.
- `SHA256SUMS.txt`: SHA-256 hashes of both archives.
- `package-<commit>/MANIFEST.json` and `build.log`: provenance, packaged-file
  hashes and build output. The manifest is also inside the application ZIP.

Keep the binary and matching source archives together when sharing a build.
Each commit gets its own build/report directory; use a fresh output directory to
repeat a previously packaged commit. No official application version is changed
by this script.

## Test the actual executable

After building, run the frozen smoke against the emitted executable path:

```powershell
.\.venv\Scripts\python.exe tests/frozen_smoke.py `
  --exe 'D:\AtelierBuilds\review\build\<commit>\dist\Atelier\Atelier.exe' `
  --report-dir 'D:\AtelierBuilds\review\frozen-smoke' `
  --app-port 8778 --debug-port 9338
```

This opens the actual frozen program in a hidden WebView2 window and connects
Playwright to that window. It creates fresh, isolated test data under the report
directory and refuses to stop or replace an application already using either
port. The run checks module loading, all six motion sets, both themes, the local
font/logo and the original-material route's path validation. The screenshots,
results and disposable profile remain in the report directory. Use a new report
directory for each run.

Asset browsing and remote checks use explicit HTTP fixtures. The frozen backend
and packaged frontend are real; this check does not run native game tools, build
mods or validate in-game rendering. Windows must already have WebView2 installed.
See [DEVELOPMENT.md](DEVELOPMENT.md) for source browser, native tool and export
round-trip checks.

For manual testing, extract the whole application archive into a new writable
directory and choose isolated data and a free port before launching:

```powershell
$env:ATELIER_DATA_DIR = 'D:\AtelierReviewData'
$env:ATELIER_PORT = '8778'
.\Atelier.exe
```

Configure external tools and a separate test-mods destination through
Setup/Settings. Keep the EXE beside `_internal`; copying the EXE alone is not a
complete installation. An installed Atelier using the default port 8767 can
remain open, provided it uses a different data directory.
