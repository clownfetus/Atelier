# Running Atelier on Linux

Atelier started as a Windows app; this document covers both running it from source on Linux for
development, and building a packaged Linux copy with `linux/build_appimage.sh` (the Linux
counterpart to `BUILD.bat`; the output is a single-file AppImage).

The approach is deliberately minimal: the Windows asset tools in `Tools/` are kept as-is, and only
the things they cannot cover were ported. Where a **native Linux build** of a tool is dropped in
beside its `.exe` it is preferred automatically (`hostos.native_tool`); Wine is the fallback for
tools that have no native build.

## What had to change, and why

| Area | Windows | Linux |
|---|---|---|
| `Tools/*.exe` (UAssetTool, retoc, AtelierMesh, …) | run directly | native build beside the `.exe` if present, else Wine — `atelier/hostos.py` |
| Oodle decompression (`io_lib`) | `oo2core_9_win64.dll` | `Tools/libooz.so`, built by `linux/build_ooz.sh` |
| AES-256-ECB (`io_lib`) | CNG (bcrypt) | the `cryptography` package |
| Folder/file pickers | PowerShell + WinForms | `zenity` |
| "Show in Explorer" | `explorer /select,` | `org.freedesktop.FileManager1.ShowItems`, else `xdg-open` |
| Launch toast | WinRT toast | `notify-send` |
| Paks auto-detect | `C:/Program Files*/Steam` | `~/.local/share/Steam`, `~/.steam/*`, Flatpak, Snap |
| Blender auto-detect | `Program Files/Blender Foundation/*` | `PATH`, `/usr/bin`, Flatpak, `/opt/blender-*` |

`io_lib` is the one place Wine genuinely cannot help: it decodes pak chunks **in-process** via
`ctypes`, and a Linux Python process cannot load a Windows DLL. Oodle has no redistributable Linux
build, so `linux/build_ooz.sh` builds [powzix/ooz](https://github.com/powzix/ooz) — an open-source
decoder for the Kraken/Mermaid/Selkie/Leviathan codecs UE5 containers actually use. It is
decode-only, which is all that is needed: `container_merge` writes uncompressed blocks. If you have
a real `liboo2corelinux64.so.9`, drop it in `Tools/` (or point `ATELIER_OODLE` at it) and it wins.

## Setup

1. **System packages** (Arch; adapt for your distro):

   ```sh
   sudo pacman -S wine zenity webkit2gtk-4.1 python-gobject gcc git
   sudo pacman -S blender          # only for mesh editing
   ```

   `webkit2gtk-4.1` + `python-gobject` are what pywebview renders the UI with. They are only
   needed for `window.py`; `server.py` runs headless without them.

2. **Python environment.** pywebview needs the system PyGObject, so the venv must see it:

   ```sh
   python -m venv --system-site-packages .venv
   .venv/bin/pip install bottle watchdog pillow numpy scipy cryptography pywebview
   ```

3. **Build the Oodle decoder:**

   ```sh
   ./linux/build_ooz.sh        # writes Tools/libooz.so
   ```

4. **Provide `Tools/`.** It is gitignored and not in the repo. Copy it from a Windows checkout or
   an installed Atelier. `Tools/Mappings/*.usmap` and `Tools/AES_KEY.txt` are game-derived and are
   never shipped — the app fetches both itself on first run (Setup → Download).

5. **Run:**

   ```sh
   .venv/bin/python window.py    # full app
   .venv/bin/python server.py    # headless, http://localhost:8767
   ```

## Building a packaged copy

```sh
linux/build_appimage.sh            # uses the version already in ./version
linux/build_appimage.sh 0.3.4      # or pass one explicitly, same N.N.N format BUILD.bat expects
```

This runs `PyInstaller` against the same `Atelier.spec` Windows uses (no Linux-specific spec
needed — PyInstaller freezes the GTK/WebKit webview backend the same way it freezes any other
extension module), then assembles `dist/Atelier/` the way `BUILD.bat` assembles `dist\Atelier\`:
`Tools/` is copied in, and the same two categories of file are stripped for the same reasons —

- **Game-derived data** (`Tools/Mappings/`, `Tools/AES_KEY.txt`) — never shipped on either
  platform; the app fetches both itself on first run.
- **Dead weight for this platform** — mirrored in the other direction from `BUILD.bat`, which
  drops the *Linux* native builds from a *Windows* dist. Here it's the reverse: `UAssetGUI.exe`
  and `shaders/dxc.exe`/`dxcompiler.dll`/`dxil.dll` back features (`world.py`, `dxc_ir.py`) that
  call `hostos.unsupported()` unconditionally on Linux — Wine or not, they're never invoked, so
  there's no reason to ship them. `UAssetTool.exe` and `shaders/retoc-rivals-cli.exe` are dropped
  too, but for a different reason: `hostos.native_tool()` always prefers the extensionless native
  binary sitting beside them when one is present, so once that binary is in `Tools/` the `.exe`
  is simply dead code, not a fallback.

Output: `dist/Atelier-<version>-x86_64.AppImage` (the intermediate `dist/Atelier/` folder is also runnable directly).
The prereqs are the same four setup steps above — the script checks each one (venv exists and
was built `--system-site-packages`, PyInstaller installed, `Tools/` present, `libooz.so` built)
and fails with a specific message rather than guessing.

### AppImage

```sh
linux/build_appimage.sh   # -> dist/Atelier-<version>-x86_64.AppImage
```

The script downloads `appimagetool` into `linux/_appimagetool/` on first use (needs
network) and wraps `dist/Atelier`. Because an AppImage mounts read-only while Atelier writes its
config, cache, projects and downloaded mappings beside the executable, `AppRun` stages a writable
copy of the bootloader and `Tools/` in `~/.local/share/Atelier` (override with `ATELIER_HOME`) and
links the large read-only `_internal/` back into the image. All user data lives in that directory,
so deleting it resets the app; upgrading the AppImage refreshes the staged tools without touching
Mappings, the AES key or your projects.

The AppImage does **not** bundle WebKitGTK, Wine or zenity — install those from the table below.
Running it needs FUSE 2 (Arch: `sudo pacman -S fuse2`); without it, run
`./Atelier-*.AppImage --appimage-extract-and-run`.

**What a machine running the packaged build needs installed**, separate from what *building* it
needs:

| Dependency | Why | If missing |
|---|---|---|
| `webkit2gtk-4.1` + `python-gobject` (system, not pip) | pywebview's GTK backend, which is what got frozen in | window fails to open; `server.py`-only use is unaffected since headless mode never touches it |
| `zenity` | folder/file pickers (Setup's paks path, texture import/export) | pickers raise a clear "zenity is not installed" error when opened; nothing else is affected |
| **Wine** (`wine64` or `wine`) | only for `Tools/AtelierMesh/AtelierMesh.exe` — the 3D viewport's mesh→glTF decoder has no native Linux build (unlike UAssetTool and retoc, which do, and so never touch Wine at all on a packaged Linux build) | opening the 3D viewport fails with a clear "Wine not found" error; **everything else — browsing, texture/material editing, mod build/install, repatch — works with no Wine installed at all** |
| `notify-send`, `xdg-open` / `gio`, `dbus-send` | desktop notifications and "show in file manager" | best-effort; their absence is swallowed silently (notify) or falls back to just opening the folder (reveal) |

In short: **Wine is optional**, and the one thing it gates (the 3D skin viewport) is the one
Linux path nobody has verified yet (see Status below) — a Wine build there is untested, not
just unwired. Everything else in the table can be skipped if you don't need that specific
feature, but a normal end user should just install all four system packages up front:

```sh
sudo pacman -S wine zenity webkit2gtk-4.1 python-gobject   # Arch; adapt for your distro
```

## Status

Working natively, no Wine involved:

- pak indexing and the whole asset browser, including character/skin names
- everything in `io_lib`: container parsing, AES, Oodle decode, `container_merge`

Working natively where a Linux build of the tool is installed beside its `.exe` (UAssetTool and
retoc both have one):

- texture import/export, mod packing and install, repatch — including extraction from a **patch
  container**, verified end to end with no Wine in the path

Falling back to Wine only for bundled tools with no native build.

Not ported (raises `hostos.UnsupportedOnLinux` with a clear message):

- **DXIL shader editing** (`atelier/handlers/dxc_ir.py`) — reached through DXC's COM API in our own
  process, so Wine does not apply.
- **Level/world editing** (`atelier/handlers/world.py`) — UAssetGUI is a WinForms app whose CLI
  still initialises the GUI stack, and the hang-recovery path uses `taskkill`.
- **In-app updater** — releases ship an Inno Setup `.exe`. Update the checkout with git instead.

Untested on Linux: the **3D viewport**. `AtelierMesh.exe` is a self-contained .NET build, so it may
well run under Wine as-is; nobody has tried it yet.

## Still to verify on Windows

The Linux port changed code that **Windows also runs**, and all of it has so far only been exercised
on Linux. None of these are known to be broken; they are untested, and the list exists so the gap is
visible rather than assumed away. Each is cheap to check on a Windows box with the game installed.

| What | Why it is in doubt | How to check |
|---|---|---|
| `texture.uat_filter()` patterns-**file** fallback | Switches from inline `--filter` args to a `.txt` past ~8 KB, specifically because full virtual paths blow Windows' ~32 KB command-line cap. The cap does not exist on Linux, so the branch that matters most has never run where it matters. | Import ~500 assets at once. It must succeed and write `_cache/_uat_filter.txt`, not fail on the argument list. |
| `hostos._prepare_dotnet_bundle()` | Mirrors `.so` files into a single-file .NET app's extracted bundle and pins `DOTNET_BUNDLE_EXTRACT_BASE_DIR`. It is meant to be **inert on Windows**; nothing has confirmed it does not misfire or slow startup there. | Run any UAssetTool operation. `_cache/netbundle` must not be created and no extra `--help` probe should run. |
| `hostos._resolve()` / `native_tool()` | Every bundled-tool call now goes through this. On Windows it must return the `.exe` unchanged, with arguments untouched by `to_host_path()`'s `Z:\` rewriting. | Any export. Paths with spaces and `[brackets]` are the interesting case. |
| The patch-decryption material reports | The bug that started this (Lumi/diz, a.wonders — see `TODO.md`) was reported on Windows. On this Linux install **every container reports `enc_guid=0`**, so the second-AES-key hypothesis (TRIAGE #2) does not reproduce here at all. Either it is Windows-specific, or the real cause was the resolution bug TRIAGE #35 fixed. | Reproduce a broken material on Windows against a current install, and check whether it still breaks. |

`tests/test_patch_override.py` covers the resolution layer on staged files and is platform-neutral,
so it is worth running on Windows too — but it deliberately does **not** re-verify that the
extractor pulls the patch chunk rather than the base chunk. That needs a real install.

## Environment variables

| Variable | Effect |
|---|---|
| `ATELIER_WINE` | wine binary to use (default: `wine64`, then `wine`, from `PATH`) |
| `ATELIER_OODLE` | path to a real `liboo2corelinux64.so`, preferred over `Tools/libooz.so` |
| `ATELIER_BLENDER` | path to the Blender executable, wins over auto-detection |
| `ATELIER_DEBUG` | opens webview devtools |
