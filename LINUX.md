# Running Atelier on Linux (development)

Atelier is a Windows app. This document covers running it from source on Linux for development —
there is no Linux packaging, and `BUILD.bat` / `Atelier.iss` remain Windows-only.

The approach is deliberately minimal: the Windows asset tools in `Tools/` are kept as-is and run
under Wine, and only the things Wine cannot cover were ported.

## What had to change, and why

| Area | Windows | Linux |
|---|---|---|
| `Tools/*.exe` (UAssetTool, retoc, AtelierMesh, …) | run directly | run under Wine via `atelier/hostos.py` |
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

## Status

Working natively, no Wine involved:

- pak indexing and the whole asset browser, including character/skin names
- everything in `io_lib`: container parsing, AES, Oodle decode, `container_merge`

Working through Wine (`Tools/*.exe`):

- texture import/export, mod packing and install, repatch — everything that calls UAssetTool or retoc

Not ported (raises `hostos.UnsupportedOnLinux` with a clear message):

- **DXIL shader editing** (`atelier/handlers/dxc_ir.py`) — reached through DXC's COM API in our own
  process, so Wine does not apply.
- **Level/world editing** (`atelier/handlers/world.py`) — UAssetGUI is a WinForms app whose CLI
  still initialises the GUI stack, and the hang-recovery path uses `taskkill`.
- **In-app updater** — releases ship an Inno Setup `.exe`. Update the checkout with git instead.

Untested on Linux: the **3D viewport**. `AtelierMesh.exe` is a self-contained .NET build, so it may
well run under Wine as-is; nobody has tried it yet.

## Environment variables

| Variable | Effect |
|---|---|
| `ATELIER_WINE` | wine binary to use (default: `wine64`, then `wine`, from `PATH`) |
| `ATELIER_OODLE` | path to a real `liboo2corelinux64.so`, preferred over `Tools/libooz.so` |
| `ATELIER_BLENDER` | path to the Blender executable, wins over auto-detection |
| `ATELIER_DEBUG` | opens webview devtools |
