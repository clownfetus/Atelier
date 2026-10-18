# Changelog

The app, installers and update checker identify each release by its full number, such as
**1.0.0**.

## 1.0.0 — 18 October 2026

- Consolidates the unmerged UI waves, motion review and latest Krackle A mark.
- Hero-led Home, Everywhere search, costume entry points and Continue editing.
- Recoverable project trash, Undo, themed confirmations and guided setup.
- Mod tray / Build mod workflow, guarded image drops, readable caption results,
  updated surfaces and palettes, and measured Krackle inks.
- Full / Calm / Off motion with system reduced-motion precedence, shared timing
  and once-per-launch presentation. Optional formation sounds are off by default.
- Inspect / Showcase rendering, posters, turntables and client-created Mod cards.
- Material replacement and restoration use the same themed confirmations as
  other editors; confirmations cannot apply to a subsequently opened material.
- Linux prerequisite checks accept its native UAssetTool without requiring a
  Windows executable; packaged checks cover this after an actual 0.4.1 upgrade.
- Pinned Windows compiler/build dependencies, complete candidate checks, native
  WebKit AppImage checks and upgrade preservation from 0.4.1.


- **Replace material** in the material editor searches installed materials by
  character, skin, name or path and applies one to the target, preserving the
  donor's parent, textures, static switches and cooked shader data through export.
  The target retains its identity; its replacement parameters remain editable.
- **Restore game defaults** returns the original target material after a swap.
  Material replacement/default restoration and removal of incompatible texture,
  dye and intensity options publish together with rollback on failure.
- Circular donor parent chains are refused. Cross-character native container
  build/readback and browser checks pass; appearance has not been tested in game.

## 0.4.1 — 16 October 2026

### Your own images in material texture slots (experimental)

- The material editor now lists the material's texture slots. Any 2D slot can use
  **your own image** as a new texture that only that material uses. The game
  texture is left untouched, so other skins and chromas sharing it don't change.
- Your image is encoded like the game texture it replaces (same format, colour
  space and texture group), so a normal map stays a normal map. Each side must be
  a power of two between 4 and 8192; other sizes are refused with the reason.
- Change or remove the image per slot. **Restore game defaults** removes them all.
  Materials using your images show **own textures** in the edit list.
- Experimental: the export was checked against a stand-in for the native tools,
  not yet in game. It refuses to ship a texture whose rename changed its pixels.
  Model Studio doesn't show these textures yet, and repatching an older mod
  doesn't carry them.

### Fixes

- Fixed mesh editing (**Open in Blender** and mesh extraction) failing with
  "all the input array dimensions … must match exactly" in Blender 4.5–5.1. A
  Blender importer bug, triggered by the morph tracking added in 0.4.0, failed
  about every other attempt and could otherwise swap two tracking values.
- Model Studio says why a model can't load — the mesh isn't in the indexed game
  files, or the decoder's own error — instead of "404: Not Found", and finds a
  decoded model saved under a different path.
- The Curve, VFX, Level and Text editors ask before closing with unsaved changes,
  as the Material editor already did. Their **Reset** buttons and **Revert to
  original** ask before replacing saved edits.

### Look and feel

- Progress, success, warning and error feedback, empty states and the export and
  import dialogs use the Krackle design language: comic-style energy and bubbles
  without outlines. It is kept for substantial feedback; routine interaction
  stays plain.
- Spinners are a charge ring. Outcomes are named in text, such as **Mod exported
  with warnings** and **Succeeded with warnings** in Activity.

### Packaging and verification

- Passed 25 backend suites and 10 focused browser checks on Windows.
- Passed clean install, running upgrade from the 0.4.0 installer, reinstall and
  uninstall on Windows 2022 and 2025, checking all 511 payload files.
- Built and checked native AppImage startup on Ubuntu 24.04. Separately, the
  released AppImages upgraded from 0.4.0 to 0.4.1 with tools re-staged and an
  existing project kept, and the packaged 0.4.1 app passed the custom-texture
  and Model Studio error checks.
- Verified the Blender import fix with Blender 5.1.2's own importer.
- A release build starts by pushing the release commit to
  `release/<version>-candidate`; build inputs come from
  `tests/fixtures/installer/release-<version>-inputs.json`.

Custom textures in game and Wine-dependent Linux asset workflows still need the
checks described in [the release notes](docs/release-0.4.1.md).

[Verification workflow](https://github.com/clownfetus/Atelier/actions/runs/38955861759)

## 0.4.0 — 16 October 2026

### Model Studio

- Redesigned the viewer as a distinct workspace with editing controls that appear
  when a part or material is selected. Model and View settings group other options.
- Saved edited textures load by default, with originals used otherwise.
  Original/Edited comparison and the before/after wipe remain available.
- Compatible standing idle animations loop automatically. Play, Pause and Rest
  pose controls work after playback starts.
- Removed rim lighting and opaque rim shells that obscured the model. Loading
  feedback is visible on the model while its appearance loads.
- Fixed cramped Model controls and long mesh/material names.

### Model replacement

- Meshes can join the edit list and be replaced with BLEND, FBX, GLB, PSK/PSKX or
  cooked UASSET files with their matching UEXP/UBULK companions.
- Import offers **Keep original skeleton**, **Preserve compatible weights** and
  **Keep facial and corrective morph targets**. All start enabled and persist
  with the saved model for later builds.
- Compatible weights are retained; missing weights, vertex colours and secondary
  UVs transfer from the original. Disabling weight preservation transfers all
  weights from the original instead.
- Original morph names and bindings are retained, with their movements mapped
  to replacement geometry at each rebuilt detail level.
- Available LODs and the cooked result are validated before saving. Replacements
  export in the same mod as other selected edits.
- Disabling skeleton preservation requires an embedded armature with matching
  bone names and hierarchy; arbitrary added bones are not supported.

### Library and editing

- Texture imports update in place instead of rebuilding the library and every
  edit-list thumbnail, fixing the repeated screen flash.
- **Revert to original** keeps the edit-list entry and its export selection.
- Newly available high-resolution texture data is recovered automatically while
  preserving painted pixels and backing up the previous image.
- Edited assets have a stronger border and an explicit **Editing** badge.
- Character folders retain transparent artwork, the roster uses side arrows,
  and costume-name backgrounds use colours sampled from their artwork.
- Fixed The Hood's missing portrait. Character banners use story art matched by
  character code.
- Removed the duplicate 3D action. Bulk VFX/curve controls appear only inside a
  loaded compatible editor.
- Successful build results use a green theme; incomplete and failed results keep
  their outcome states.

### Packaging and verification

- Built Windows and Linux packages from the same application commit.
- Passed 22 backend suites and 10 focused browser checks, including consecutive
  texture imports that retain existing grid and thumbnail nodes.
- Passed clean install, running upgrade, reinstall and uninstall on disposable
  Windows 2022 and 2025 runners, checking all 503 payload files.
- Built and checked native AppImage startup on Ubuntu 24.04.
- Independently decoded preserved morph data and verified its identities and
  counts through a cooked-mod pack/extract round trip.
- Fixed Windows short-path aliases in project operations and platform-aware
  collection of distribution licences.

Wine-dependent Linux asset workflows and animation quality on substantially
changed faces still need the setup and manual checks described in
[the release notes](docs/release-0.4.0.md).

[Verification workflow](https://github.com/clownfetus/Atelier/actions/runs/38870854575)
· [Earlier releases](https://github.com/clownfetus/Atelier/releases)
