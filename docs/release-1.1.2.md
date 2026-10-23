# Atelier 1.1.2

This patch fixes textures that came out brighter than the game's own, makes BC7 texture exports
fast again, adds three editors, and rebuilds every bundled tool from pinned source with one
toolchain.

## What changed

- **Exported textures match the game's brightness.** Character, weapon and world textures keep
  their mip chain again (only UI textures skip it, where it prevents blur), and the mips Atelier
  builds now match the game's own. They were averaged in the wrong colour space, which made
  textures look brighter or glarey at a distance.
- **BC7 exports finish in seconds.** A 1366×1366 BC7 texture with mips took about 44 seconds and
  now takes about 2, so multi-texture builds no longer appear to hang.
- **Textures added at a custom path no longer crash the game** with "Serial size mismatch".
  Atelier refuses to ship a renamed texture whose size differs from a normal edit of the same image.
- **Assembly View.** Beside Inspect and Showcase, select a model surface to see its geometry,
  verified material and connected texture slots. Texture and material selections highlight the
  surfaces that actually use them.
- **VFX Motionboard.** Edit Niagara LUT tracks on a synchronized timeline with playback,
  original/edited comparison and per-point or per-track restores. Untouched LUTs are preserved.
- **Bulk edit materials.** Review and save opacity, scalar, colour, parent or full material
  changes for up to 1,000 assets at once.
- **Settings → Tools.** See each bundled tool's version, update the container tool between Atelier
  releases when a game patch needs it, repair missing or damaged tools, and roll back an update.
  Every download is hash-checked and must still offer the commands Atelier uses.
- **Clearer tool errors.** A missing tool now says which one and how to restore it, instead of
  "[WinError 2] The system cannot find the file specified".
- **Linux AppImage runs on newer distributions.** It uses the system's GTK and WebKit together,
  runs model previews and idle animations natively instead of through Wine, and is built on
  Ubuntu 24.04 so it also runs on current Fedora, Debian 13 and Ubuntu.

## Under the hood

- One native helper, **AtelierNative**, replaces the separate mesh, animation and import tools.
  It is built from the same CUE4Parse version as before, so previews are byte-for-byte unchanged.
- Every bundled tool is listed with its exact source and hashes in `toolchain/tools.lock.json`
  and built by one script. The shader tool's source-built executable reproduces exactly.
- On Windows, container unpacking and packing use Atelier's source-built retoc 3.10.2, which keeps
  extracted files inside their output folder and fails when an asset cannot be written.
- UAssetTool is built from current upstream source with Atelier's texture fixes.
- Atelier runs on Python 3.15.

## Updating

- **Windows:** close Atelier and run `AtelierSetup.exe` in your existing location.
  Projects and settings are retained. The portable ZIP contains the same files.
- **Linux:** download `Atelier-1.1.2-x86_64.AppImage`, mark it executable and launch.
  Bundled tools refresh while user data is retained.

Matching source, screenshots, release copy, `SHA256SUMS.txt` and `VERIFICATION.json` are attached.
The verification file records the tested commit and installer hashes.

## Verification and limits

Mesh and animation output from AtelierNative was compared byte for byte with the previous tools on
Windows and Linux. Real game files were used for texture, dye, added-asset, material-replacement,
bulk-edit, triage and shader round-trip checks. The release workflow checks the packaged Windows
application, clean install, upgrade from the published **1.1.1** installer, reinstall and
uninstall on two Windows runners, plus Linux startup and a **1.1.1 AppImage** upgrade.

In-game rendering remains unverified. The texture brightness fix was measured against the game's
own mips, not checked in game. HDR Texture2D, EXR, virtual textures and cube arrays remain
unsupported. Live Blender and model replacement on Linux have a separate validation scope.

[Full changelog](https://github.com/clownfetus/Atelier/blob/1.1.2/CHANGELOG.md)
