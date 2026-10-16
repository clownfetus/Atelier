# Changelog

Version 0.4 uses **0.4.0** in the app, installers and update checker.

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
