# Atelier 1.0 — One studio for your mods

Atelier 1.0 brings the outstanding interface and workflow updates into one
release for Windows and Linux. The application and download files use **1.0.0**.

## Find your next edit

Home now starts with hero portraits, costume lists and edit counts. Filter to
Edited or Recently opened, or use Continue editing to return to your latest
project edit. Search Everywhere across heroes, costumes, folders and assets;
switch to This folder when you want a local filter.

![Atelier 1.0 hero library](https://raw.githubusercontent.com/clownfetus/Atelier/codex/release-1.0.0/images/studio-dark.png)

## Swap materials and keep editing

Use **Replace material** to find an installed material by character, skin, name
or path and apply it to your target. The donor's parent, textures, static
switches and cooked shader data are retained while the target keeps its identity.
Its exposed parameters remain editable. **Restore game defaults** brings back
the target's original material and removes incompatible replacement options.

Replacement and restoration use themed confirmations. A confirmation belonging
to an editor you have closed cannot change a newly opened material.

![Material replacement](https://raw.githubusercontent.com/clownfetus/Atelier/codex/release-1.0.0/images/material-replacement.png)

## Inspect, then present

Model Studio offers **Inspect** for material picking, original/edited comparison
and a before/after wipe. **Showcase** adds cel lighting and a skin-colour dot
backdrop. Returning to Inspect restores the editable materials without saving
presentation effects into the mod. Posters and turntables are available, and
completed builds can offer a **Mod card** with actual completed asset counts,
version/date, Copy image and Save PNG.

![Model Studio](https://raw.githubusercontent.com/clownfetus/Atelier/codex/release-1.0.0/images/model-studio.png)

![Showcase](https://raw.githubusercontent.com/clownfetus/Atelier/codex/release-1.0.0/images/showcase.png)

## A clearer, more recoverable workflow

- Three-step first-run setup: Find the game, Unlock the paks, Make it yours.
- **Mod tray** collects edits; **Build mod** reviews assets and destination first.
- Drop an image onto an edited texture card to open the existing replacement
  flow, with confirmation before overwriting.
- Deleted edits and their export options go to project trash. Undo is available
  immediately; deleted files are retained for up to seven days and twenty batches.
- Activity tracks imports, builds and repatches. Bulk VFX / curves previews
  changes before saving; S map processing stays inside Atelier.
- Update checks run alongside startup, so a slow or offline release service
  does not hold up the library or setup.

## Krackle, at your pace

The latest Krackle A mark is used throughout the app and installers. Updated
surfaces, palettes, caption notifications and feedback make progress and results
clearer in both themes. Choose **Full**, **Calm** or **Off** motion. System
reduced-motion preferences take precedence. Optional formation sounds start off
and stay silent in Calm, Off or a hidden window.

## Download and update

- **Windows:** `AtelierSetup.exe`. Close Atelier and run the installer using the
  existing installation directory, or choose Update Now after publication.
- **Linux:** `Atelier-1.0.0-x86_64.AppImage`. Mark it executable and launch it.
  The first run refreshes bundled tools while retaining user data. See
  [Linux setup and limitations](https://github.com/clownfetus/Atelier/blob/codex/release-1.0.0/LINUX.md).
- Matching source, SHA-256 checksums and `VERIFICATION.json` accompany the release.

## Verification and limits

Release checks cover the combined backend and browser workflows, packaged
Windows WebView2, clean installation, running upgrade from **0.4.1**, reinstall
and uninstall on two disposable Windows runners, and real Linux GTK/WebKit
startup plus version-refresh preservation. Exact outcomes, build commit and
artifact hashes are recorded in `VERIFICATION.json`; a failed gate prevents
creation of the final release bundle.

Local native-tool checks also verify cross-character material container
build/readback and curve, global material collection and Niagara edits through
export/readback. Screenshots use the actual interface with isolated game data;
no screenshot run saves material edits or installs a mod.

Material replacement appearance and arbitrary custom models still need checking
in game. UVs and character-specific shader inputs can affect a material used on
another model. Custom texture slots remain experimental; animated shaders are
not fully represented in the preview. Linux model/animation workflows require
Wine; Windows-only DXIL editing and the external world editor are unavailable
on Linux. Project Galacta controls Skin Swapper availability with its live switch.
