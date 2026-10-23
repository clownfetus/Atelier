# Running Atelier on Linux

## Install and update

1. Download `Atelier-<version>-x86_64.AppImage` from an
   [official release](https://github.com/clownfetus/Atelier/releases).
2. Install your distribution's WebKitGTK 4.1 runtime and `zenity` for file/folder
   pickers. Install Blender for Blender workflows.
3. Mark the downloaded file executable and open it. For example, once you have
   downloaded the 1.1.1 asset:

   ```sh
   chmod +x Atelier-1.1.1-x86_64.AppImage
   ./Atelier-1.1.1-x86_64.AppImage
   ```

4. Follow **Find the game → Unlock the paks → Make it yours**. Choose the game
   installation and supply a current mapping and AES key if automatic retrieval
   is unavailable. Set the mods folder and Blender executable in **Menu → Settings**.

To update, close Atelier, download the newer AppImage, mark it executable and
launch it. Linux does not run the Windows installer. Keep the previous AppImage
until the replacement opens successfully. Projects, settings, mappings and keys
live in `~/.local/share/Atelier` by default, independently of the downloaded file.
Do not delete that data directory when replacing the AppImage. If you use
`XDG_DATA_HOME` or `ATELIER_HOME`, keep the same value across launches.

The AppImage needs FUSE 2 to mount normally. If FUSE is unavailable, use the
same downloaded filename with `--appimage-extract-and-run`:

```sh
./Atelier-1.1.1-x86_64.AppImage --appimage-extract-and-run
```

## Desktop dependencies and feature support

Releases build on Ubuntu 24.04 (glibc 2.39) with Python 3.15 and run on that or anything newer:
current Fedora, Arch, Debian 13 and Ubuntu. The AppImage does not bundle WebKitGTK, Blender or
zenity. Package names vary by distribution. On Arch:

```sh
sudo pacman -S webkit2gtk-4.1 zenity fuse2
sudo pacman -S blender          # for Blender workflows
```

| Feature | Linux requirement or limit |
| --- | --- |
| Desktop window | GTK/WebKitGTK 4.1 runtime |
| Folder and file pickers | `zenity` |
| Asset reading, textures and packing | Bundled native UAssetTool, retoc and Linux Oodle inputs |
| Model and standing-idle decoding | Bundled native `AtelierNative` (no Wine) |
| Portable `.blend` and per-mesh editing | Native Blender executable configured in Settings |
| **Send to Blender (live)** | Running Blender with the bundled Atelier Live Bridge enabled; see [Blender setup](BLENDER.md#send-to-blender-or-export-a-portable-scene) |
| Reveal files and desktop notifications | Desktop file manager / `xdg-open`, D-Bus and optional `notify-send` |
| DXIL shader editing | Unsupported on Linux |
| Level/world editing through UAssetGUI | Unsupported on Linux |
| Updating | Download and launch a newer AppImage (Settings > Tools updates the container tool) |

Every tool Atelier ships has a native Linux build: UAssetTool, retoc and **AtelierNative** (mesh
export, idle animations and the persistent import server). The Linux AtelierNative mesh output was
checked byte-for-byte against the Windows build. Wine is only a fallback for a `.exe` tool with no
native build beside it (`hostos.native_tool`).

The release-candidate workflow checks native tool launches, the GTK/WebKit window, packaged frontend
files, bundled extension contents and upgrade from the previous AppImage, including retained user
files and projects. The final release's `VERIFICATION.json` records which gates passed and the exact
artifact hashes. Live Blender and model-replacement workflows need separate Linux runtime
verification; the desktop gate does not establish those results. In-game rendering remains
unverified.

HDR cubemap inputs and limits are described in the [HDR guide](../README.md#hdr-cubemaps).
Blender uses tone-mapped cubemap previews. Windows source verification of HDR
readback does not establish Linux game rendering.

## What differs from Windows

| Area | Windows | Linux |
|---|---|---|
| `Tools/*.exe` (UAssetTool, retoc, AtelierNative, …) | run directly | the native build beside the `.exe` (all shipped tools have one), else Wine — `atelier/hostos.py` |
| Oodle decompression (`io_lib`) | `oo2core_9_win64.dll` | `Tools/libooz.so`, built from pinned source by `scripts/toolchain.py` |
| AES-256-ECB (`io_lib`) | CNG (bcrypt) | the `cryptography` package |
| Folder/file pickers | PowerShell + WinForms | `zenity` |
| "Show in Explorer" | `explorer /select,` | `org.freedesktop.FileManager1.ShowItems`, else `xdg-open` |
| Launch toast | WinRT toast | `notify-send` |
| Paks auto-detect | `C:/Program Files*/Steam` | `~/.local/share/Steam`, `~/.steam/*`, Flatpak, Snap |
| Blender auto-detect | `Program Files/Blender Foundation/*` | `PATH`, `/usr/bin`, Flatpak, `/opt/blender-*` |

`io_lib` decodes pak chunks **in-process** via `ctypes`, and a Linux Python process cannot load a
Windows DLL. Oodle has no redistributable Linux build, so the toolchain builds
[powzix/ooz](https://github.com/powzix/ooz), an open-source decoder for the
Kraken/Mermaid/Selkie/Leviathan codecs UE5 containers use. It is decode-only, which is all that is
needed: `container_merge` writes uncompressed blocks. A real `liboo2corelinux64.so.9` in `Tools/`
(or `ATELIER_OODLE`) takes precedence.

## Run from source

Source setup is for development. The AppImage above already contains Python and the application
dependencies.

1. **System packages** (Ubuntu/Debian names; Fedora and Arch have the same libraries):

   ```bash
   sudo apt install gir1.2-webkit2-4.1 libgirepository-2.0-dev libcairo2-dev pkg-config zenity
   sudo apt install build-essential cmake   # only to build the native tools
   ```

   `libgirepository-2.0-dev` and `libcairo2-dev` let pip build PyGObject/pycairo for the pinned
   Python, so no `--system-site-packages` venv is needed.

2. **Python 3.15 and the venv.** Any CPython 3.15 works (distro package, pyenv or
   `uv python install 3.15`):

   ```bash
   python3.15 -m venv .venv
   .venv/bin/python -m pip install -r requirements-dev.txt
   ```

3. **Native tools** (needs the .NET 10 SDK):

   ```bash
   .venv/bin/python scripts/toolchain.py install --dest Tools
   ```

   This fetches and builds everything in `toolchain/tools.lock.json`, including `libooz.so`, and
   verifies hashes and commands. Keys, mappings, caches and user configuration are runtime data
   and do not belong in a source archive; the app fetches mappings and the AES key on first run.

4. **Run it** with an isolated data directory:

   ```sh
   ATELIER_DATA_DIR="$HOME/AtelierDevData" .venv/bin/python window.py
   # Or serve the interface locally without the desktop shell:
   ATELIER_DATA_DIR="$HOME/AtelierDevData" .venv/bin/python server.py
   ```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the broader development workflow.

## Build an AppImage

```bash
.venv/bin/python scripts/build.py --platform linux          # -> dist/Atelier-<version>-x86_64.AppImage
.venv/bin/python scripts/build.py --platform linux --version 1.2.0
```

`build.py` installs the toolchain, freezes with `packaging/Atelier.spec` (including the bundled
Blender extension), stages and audits `dist/Atelier/Tools` from the lockfile, collects licences, then
`packaging/linux/build_appimage.sh` assembles the AppImage with a pinned, hash-checked
appimagetool. Missing required native tools or the Skin Swapper template pair stop staging. Build on
the **oldest** distro you want to support: everything frozen in needs the build machine's glibc or
newer. For the full verified release process see [PACKAGING.md](PACKAGING.md).

GTK, GLib, GObject-introspection, cairo, pango and the base C/C++ runtime libraries are
deliberately **not** bundled: WebKitGTK always comes from the user's system, and pairing it with an
older bundled GTK stack is what made the 1.0 AppImage fail on newer distros ("Could not locate
webkit_get_major_version"). `window.py` also drops PyInstaller's runtime-hook variables that would
point GTK into the bundle.

The AppImage's launcher stages its writable bootloader and bundled tools into the user data
directory and links `_internal` to the mounted payload. A version change refreshes bundled tools
while preserving user-authored files, mappings, keys and projects.

## Still to verify on Windows

The Linux port changed code that **Windows also runs**. None of these are known to be broken; the
list exists so the gap is visible rather than assumed away.

| What | Why it is in doubt | How to check |
|---|---|---|
| `texture.uat_filter()` patterns-**file** fallback | Switches from inline `--filter` args to a `.txt` past ~8 KB, because full virtual paths blow Windows' ~32 KB command-line cap. | Import ~500 assets at once. It must succeed and write `_cache/_uat_filter.txt`. |
| `hostos._prepare_dotnet_bundle()` | Mirrors `.so` files into a single-file .NET app's extracted bundle. It is meant to be **inert on Windows**. | Run any UAssetTool operation. `_cache/netbundle` must not be created. |
| The patch-decryption material reports | Reported on Windows; on Linux **every container reports `enc_guid=0`**, so the second-AES-key hypothesis (TRIAGE #2) does not reproduce. | Reproduce a broken material on Windows against a current install. |

## Environment variables

| Variable | Effect |
| --- | --- |
| `ATELIER_HOME` | AppImage user data directory |
| `XDG_DATA_HOME` | Default data root when `ATELIER_HOME` is unset |
| `ATELIER_DATA_DIR` | Separate source-development/test data directory |
| `ATELIER_WINE` | Wine executable for a tool without a native build; otherwise `wine64`, then `wine` on `PATH` |
| `ATELIER_OODLE` | Explicit native Oodle library path |
| `ATELIER_BLENDER` | Blender executable override |
| `ATELIER_DEBUG` | Open webview developer tools |
