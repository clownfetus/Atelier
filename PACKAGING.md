# Preparing a public release

For 1.1.1, dispatch `.github/workflows/release-candidate.yml` against the
consolidated `main` commit (or push a `codex/release-*` candidate branch).
It builds the Windows installer and Linux AppImage, verifies upgrade from the
pinned 1.1.0 installer on disposable Windows runners, checks the actual Linux
GTK/WebKit window and tool refresh, then assembles the matching source archive,
checksums and `VERIFICATION.json`. The bundle also includes the matching Windows
portable ZIP, screenshots, release notes and Discord paste. Every gate must pass
before the `Atelier-1.1.1-release` artifact exists.

Windows build inputs and Inno Setup are pinned in `requirements-build.txt` and
`scripts/windows_toolchain.json`; bootstrap with `scripts/bootstrap_windows.ps1`.
The native tools seed and previous release are pinned in
`tests/fixtures/installer/release-1.1.1-inputs.json`. The Galacta template pair is
provided through the two `GALACTA_TEMPLATE_*_B64` encrypted repository inputs.
It is bundled only inside Atelier and is never added to Git or source archives.

Do not run installer integration checks on a normal workstation. The current
harness deliberately admits only explicitly configured disposable GitHub-hosted
Windows runners. Upgrade/uninstall checks preserve synthetic projects, exports,
settings, paths, user tools, mappings and browser preferences. The normal stable
AppId remains unchanged so existing installations are found.

The workflow does not publish a release. Review the passing workflow and exact
hashes, prepare a draft with the release assets and `docs/release-1.1.1.md`, then
publish the tested commit when ready. `scripts/release_bundle.py` rejects an
installer or Linux artifact whose hash disagrees with its test report, and a
Windows manifest whose source commit/version differs from the checkout. Portable
files must match that manifest. Screenshot hashes and version must match
`images/screenshots.json`; stale or missing release copy stops bundle assembly.

## Windows review package

Windows builds now require `Tools/AtelierImport/AtelierImport.exe` and its two
native DLLs. This service reuses the initialized CUE4Parse game reader for model,
material and texture previews. It uses private inherited pipes, without opening
an additional HTTP port. Its caches remain under the selected app data directory.

Build it with .NET SDK 10 against the exact assemblies already in AtelierMesh:

```powershell
.\.venv\Scripts\python.exe scripts/build_import_server.py --tools 'D:\AtelierTools'
```

The command creates a fresh `AtelierImport` folder; it refuses to overwrite an
existing one. Use `--output` to build a revision in another folder and `--dotnet`
for a portable SDK. Builds do not read game data, keys or mappings. Tools staging
and the installer require the service and both native dependencies on Windows;
the older decoder remains the compatibility path for older external tool sets
and Linux, where this service has not been verified.

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
