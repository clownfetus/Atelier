# Atelier 1.1.1

This patch brings together the work since 1.1.0: faster repeated model imports,
preview and texture export fixes, HDR cubemaps, and clearer names across the library.

## What changed

- **Find assets by their names.** Character and costume names and artwork now
  follow recognized IDs through UI, VFX and other asset folders, including
  legendary ultimate skins. Search, breadcrumbs, pins and asset pickers agree.
  The original game paths stay available on hover.
- **Import HDR cubemaps.** Add or replace a TextureCube from a Radiance panorama,
  six-face strip or HDR cubemap DDS, and use it in a material reflection slot.
  Six faces, HDR values and authored DDS mips are retained. The image shown in
  Atelier is a separate tone-mapped preview.
- **Keep Blender projects smaller.** Turn off **Settings → Behavior → Add model
  textures to the project when opening in Blender** to pack the images into the
  Blender file instead. Existing painted project textures are preserved. The
  option is remembered and starts on.
- **Spend less time preparing previews.** Windows reuses its game reader and
  batches model, material and texture work. The selected body and equipped
  weapons load first; other forms and attachments load when selected.
- **Get more accurate previews and exports.** Fixes cover character materials,
  tattoo and hair masks, weapon grips, Capwolf's alternate body, texture cache
  paths and the T_Visor serialization error. Asset renames retain cooked texture
  data. Lower mesh detail levels preserve section and skinning boundaries.
- **Updated library and editing feedback.** Cleaner filters, readable compact
  costume captions, consistent Mod tray and Continue spacing, refreshed Showcase
  composition and Krackle feedback that follows actual work and motion settings.
- **Safer local requests and verified tool inputs.** The local service checks
  request origins and Blender paths. The Windows shader tool is rebuilt from
  pinned source; animation and import builds use pinned native inputs.

## Updating

- **Windows:** close Atelier and run `AtelierSetup.exe` in your existing location.
  Projects and settings are retained. The portable ZIP contains the same files.
- **Linux:** download `Atelier-1.1.1-x86_64.AppImage`, mark it executable and launch.
  Bundled tools refresh while user data is retained.

Matching source, screenshots, release copy, `SHA256SUMS.txt` and
`VERIFICATION.json` belong to the candidate bundle. The verification file records
the tested commit and installer hashes. A candidate is ready for publication
only after every Windows and Linux gate passes.

## Verification and limits

Source verification includes real HDR mod build/readback, a reopened Blender
scene with packed textures, a character preview audit, and independent native
tool builds. Details are in the [consolidation record](https://github.com/clownfetus/Atelier/blob/1.1.1/docs/release-1.1.1-consolidation.md).
The release workflow checks the packaged Windows application, clean install,
upgrade from the published **1.1.0** installer, reinstall and uninstall on two
Windows runners, plus Linux startup and a **1.1.0 AppImage** upgrade.

In-game rendering remains unverified. HDR support covers complete inline UE5
TextureCube resources; HDR Texture2D, EXR, virtual textures and cube arrays are
unsupported. Blender uses the tone-mapped cubemap preview. Full animated and eye
shader graphs and 16-bit skeletal mesh rebuilds remain unsupported. Linux model
and animation workflows require Wine and have a separate validation scope.

[Full changelog](https://github.com/clownfetus/Atelier/blob/1.1.1/CHANGELOG.md)
