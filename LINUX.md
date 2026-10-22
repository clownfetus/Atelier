# Running Atelier on Linux

## Install and update

1. Download `Atelier-<version>-x86_64.AppImage` from an
   [official release](https://github.com/clownfetus/Atelier/releases).
2. Install your distribution’s WebKitGTK 4.1 runtime and `zenity` for file/folder
   pickers. Install Wine if you need model or animation decoding, and Blender
   for Blender workflows.
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

The AppImage does not bundle WebKitGTK, Wine, Blender or zenity. Package names
vary by distribution. On Arch, the usual desktop dependencies are:

```sh
sudo pacman -S webkit2gtk-4.1 python-gobject zenity fuse2
sudo pacman -S wine blender     # for model/Blender workflows
```

| Feature | Linux requirement or limit |
| --- | --- |
| Desktop window | GTK/WebKitGTK 4.1 runtime |
| Folder and file pickers | `zenity` |
| Asset reading, textures and packing | Bundled native UAssetTool, retoc and Linux Oodle inputs |
| Model and standing-idle decoding | Wine for bundled `AtelierMesh.exe` and `AtelierAnimation.exe` |
| Portable `.blend` and per-mesh editing | Native Blender executable configured in Settings; model decoding still requires Wine |
| **Send to Blender (live)** | Running Blender with the bundled Atelier Live Bridge enabled; see [Blender setup](BLENDER.md#send-to-blender-or-export-a-portable-scene) |
| Reveal files and desktop notifications | Desktop file manager / `xdg-open`, D-Bus and optional `notify-send` |
| DXIL shader editing | Unsupported on Linux |
| Level/world editing through UAssetGUI | Unsupported on Linux |
| Updating | Download and launch a newer AppImage |

The release-candidate workflow builds on Ubuntu 24.04 and checks native tool
launches, the GTK/WebKit window, packaged frontend files, bundled extension
contents and upgrade from the pinned **1.1.0 AppImage**, including retained user
files and projects. The final release’s `VERIFICATION.json` records which gates
passed and the exact artifact hashes. Wine-dependent 3D, live Blender and model
replacement workflows need separate Linux runtime verification; the desktop
gate does not establish those results. In-game rendering remains unverified.

HDR cubemap inputs and limits are described in the [HDR guide](README.md#hdr-cubemaps).
Blender uses tone-mapped cubemap previews. Windows source verification of HDR
readback does not establish Linux game rendering or Wine compatibility.

## Run from source

Source setup is for development. The AppImage above already contains Python and
the application dependencies.

1. Install Python 3.12, Git and development packages for your distribution. The
   GTK desktop also needs system PyGObject and WebKitGTK 4.1. For example, the
   Ubuntu 24.04 build uses `python3-venv`, `python3-gi` and `gir1.2-webkit2-4.1`.
2. Create an environment that can see the system GTK bindings, then install the
   repository’s pinned dependencies:

   ```sh
   python3 -m venv --system-site-packages .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Provide the matching native `Tools/` from an official Linux payload. A
   Windows-only tools directory does not provide the native Linux executables
   and libraries. Keys, mappings, caches and user configuration are separate
   runtime data and do not belong in a source archive.
4. Use an isolated data directory for development:

   ```sh
   ATELIER_DATA_DIR="$HOME/AtelierDevData" .venv/bin/python window.py
   # Or serve the interface locally without the desktop shell:
   ATELIER_DATA_DIR="$HOME/AtelierDevData" .venv/bin/python server.py
   ```

The server prints its loopback address. Set tool/game paths in the isolated
configuration. See [DEVELOPMENT.md](DEVELOPMENT.md) for the broader development
workflow. Optional `linux/build_ooz.sh` builds the fallback decoder into
`Tools/libooz.so`; a supplied `liboo2corelinux64.so.9` takes precedence.

## Build an AppImage

Install the build dependencies in the same environment and stage the required
native inputs before building:

```sh
.venv/bin/python -m pip install -r requirements-build.txt
bash linux/build_appimage.sh       # version comes from ./version
```

The script builds the Python application, generates the bundled Blender
extension, stages only allowlisted tools and creates
`dist/Atelier-<version>-x86_64.AppImage`. Missing required native tools or the
Skin Swapper template pair stop staging. For the full verified release process,
including pinned seed inputs, use [PACKAGING.md](PACKAGING.md).

The build downloads `appimagetool` on first use. The AppImage’s launcher stages
its writable bootloader and bundled tools into the user data directory and
links `_internal` to the mounted payload. A version change refreshes bundled
tools while preserving user-authored files, mappings, keys and projects.

## Environment variables

| Variable | Effect |
| --- | --- |
| `ATELIER_HOME` | AppImage user data directory |
| `XDG_DATA_HOME` | Default data root when `ATELIER_HOME` is unset |
| `ATELIER_DATA_DIR` | Separate source-development/test data directory |
| `ATELIER_WINE` | Wine executable; otherwise `wine64`, then `wine` on `PATH` |
| `ATELIER_OODLE` | Explicit native Oodle library path |
| `ATELIER_BLENDER` | Blender executable override |
| `ATELIER_DEBUG` | Open webview developer tools |
