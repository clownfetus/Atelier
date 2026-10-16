# Atelier 0.4.1 — Your own textures

Atelier 0.4.1 lets a material use your own images in its texture slots, fixes mesh
editing in Blender, explains Model Studio load failures, and brings the Krackle
design language to Atelier's feedback. The app and installers identify this
release as **0.4.1**.

## Your own images in texture slots (experimental)

The material editor now lists the material's texture slots. Choose **Use my own
image…** on a 2D slot and your image ships as a **new texture** that only this
material uses. The game texture stays as it is, so other skins and chromas that
share it don't change.

Your image is encoded like the game texture it replaces, with the same format,
colour space and texture group, so a normal map stays a normal map. Each side must
be a power of two between 4 and 8192, such as 1024 or 2048. Use **Change image…**
or **Use game texture** per slot; **Restore game defaults** removes all of them.
Materials using your images show **own textures** in the edit list.

This is experimental. The export was checked against a stand-in for the native
tools, not yet in game, and it refuses to ship a texture whose rename changed its
pixels. Model Studio doesn't show these textures yet, and repatching an older mod
doesn't carry them. Reports from real exports are welcome.

## Fixes

- **Open in Blender works again.** Mesh editing could fail with "all the input
  array dimensions … must match exactly" in Blender 4.5–5.1. A Blender importer
  bug, triggered by the morph tracking added in 0.4.0, failed about every other
  attempt and could otherwise swap two tracking values. Atelier now works around
  it, which was verified with Blender 5.1.2's own importer.
- **Model Studio says why a model can't load.** Instead of "404: Not Found", it
  reports when a mesh isn't in the indexed game files, or shows the decoder's own
  error. A decoded model saved under a different path is now found.
- **Fewer lost edits.** The Curve, VFX, Level and Text editors ask before closing
  with unsaved changes. Their **Reset** buttons and **Revert to original** ask
  before replacing saved edits.

## Krackle feedback

Progress, success, warning and error moments, empty states and the export and
import dialogs use the Krackle design language: comic-style energy and bubbles
without outlines. It is kept for substantial feedback; routine interaction stays
plain. Outcomes are named in text, such as **Mod exported with warnings**.

## Download and update

Get **AtelierSetup.exe** for Windows or **Atelier-0.4.1-x86_64.AppImage** for Linux
from the [0.4.1 release](https://github.com/clownfetus/Atelier/releases/tag/0.4.1).
Source, checksums and `VERIFICATION.json` are included with the release assets.

On Windows, restart Atelier and choose **Update Now**, or close Atelier and run the
installer using the existing installation directory. On Linux, download the new
AppImage and mark it executable; it refreshes its bundled tools on first launch
and keeps your projects. See [LINUX.md](../LINUX.md) for Wine and other system
dependencies.

## Verification

[The release workflow](https://github.com/clownfetus/Atelier/actions/runs/38955861759)
passed 25 backend suites and 10 focused browser checks on Windows. Clean install,
running upgrade from the 0.4.0 installer, reinstall and uninstall passed on
Windows 2022 and 2025, checking all 511 payload files. The Linux AppImage built and
passed native startup on Ubuntu 24.04.

Separately, on Ubuntu 24.04 with the released AppImages, upgrading from 0.4.0 to
0.4.1 re-staged the bundled tools and kept an existing project. In the packaged
0.4.1 app, custom-texture assignment, size checks, previews, the edit-list marker
and the material editor's texture slots worked, and Model Studio returned its new
error message. The Blender import fix passed under eight hash seeds with Blender
5.1.2 (the workflow skips that check because it has no Blender).

These checks don't cover a custom texture in game, which needs a real export, or
Wine-dependent Linux asset workflows beyond the documented setup.

Application build: `d77cfc07c4a29d709412d2c430e4f424fc56590d`. Later documentation
changes don't change the tested application payload.

See the [full changelog](../CHANGELOG.md).
