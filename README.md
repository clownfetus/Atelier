# Atelier: Modding Studio

Atelier is a desktop modding studio for Marvel Rivals. Browse game assets, edit
textures and material parameters, preview models, and build mods from one interface.

[Download the latest release](https://github.com/clownfetus/Atelier/releases/latest)
· [Development guide](DEVELOPMENT.md)
· [Changelog](CHANGELOG.md)
· [Report an issue](https://github.com/clownfetus/Atelier/issues)

![Atelier asset library in dark mode, with category folders, search, filters and edited assets](images/studio-dark.png)

Screenshots show the current source interface with example data. The published
installer can contain an earlier interface until a new release is published.
See [screenshot details](images/README.md).

**Atelier 0.4.1** lets a material use your own images in its texture slots
(experimental), fixes mesh editing in Blender, explains Model Studio load failures
and brings the Krackle design language to Atelier's feedback. It builds on 0.4's
redesigned Model Studio and model replacement. See the
[release notes](docs/release-0.4.1.md) for details and verification.

## Features

- **Find assets:** character and skin names, current-folder search by name, ID or
  path, type/status filters, sorting, adjustable tile sizes and pinned folders.
- **Edit materials:** grouped color, dye-region and scalar parameters, explicit
  unsaved changes, comparison with saved values or the original game material,
  and individual value restoration.
- **Work with textures and meshes:** import replacement textures, add meshes to
  the edit list, replace them with BLEND/FBX/GLB/PSK or cooked Unreal models,
  and open supported mesh workflows in Blender.
- **Inspect models:** switch Original/Edited textures or drag a before/after wipe,
  click a material on the model, inspect labelled dye regions, choose lighting,
  isolate objects, loop a compatible standing idle automatically, and capture a
  poster or turntable. Select a part or material to reveal its editing controls.
- **Review exports:** choose which edited assets to include, check the destination
  before building, and optionally copy the mod into your configured mods folder.
- **Track work:** Activity records imports, exports and repatches. Bulk VFX / curves
  previews supported parameter changes before saving them to the project.
- **Process S maps:** pair edited D textures with S maps in the same folder,
  resize with Bicubic, and apply Color blending at 100% inside Atelier.
- **Choose your appearance:** Light, Dark or System mode, Atelier/Darcula/Repak X
  palettes, and saved custom palettes with separate light and dark colors.
- **Build Skin Swapper mods:** export an edited character mesh in Project Galacta's
  Skin Swapper format, for its Companion App to load. See [Skin Swapper mods](#skin-swapper-mods).

<details>
<summary>View the light theme</summary>

![Atelier asset library in light mode with the same example project](images/studio-light.png)

</details>

## Material editing

### Process S maps

Click **Process S maps** under **Edited Assets** to process every imported texture
whose name ends in `_D`. The export checkboxes and library filters do not limit
this action. Matching uses the same game folder and the corresponding `_S` name;
numbered D maps can share an unnumbered S map, with a pairing chooser whenever
several D maps could drive the same S map. Unmatched textures are skipped.

Atelier uses a saved project S map when present, otherwise imports it from the
game. Each D is resized to the S map's dimensions using Bicubic, then applied
with built-in Color blending at 100% opacity. D files remain unchanged; S alpha
is retained and transparent D pixels mask the color change. Photoshop is not
required. The blend follows the [standard non-separable Color formula](https://www.w3.org/TR/compositing-1/#blendingcolor),
rather than relying on a native Photoshop document or its color-profile settings.

Processed S maps appear in Edited Assets for normal export. Activity lists the
pairings and skipped paths. Original S inputs and a batch record are retained
inside the project's `.atelier/s-map-backups/` directory. Cancellation and failures
before publication leave project images untouched; a failed publication rolls
back the batch.

### Material parameters

Inspect surface colors, dye regions and scalar groups together. Compare against
the project's saved values or **Game original**, restore individual values, and
save when ready. New edits made during a save remain marked as unsaved.

![Material editor showing color and dye-region groups, scalar parameters and saved-value comparisons](images/material-editor.png)

## Appearance

Open **Menu → Settings → Appearance** to choose a mode and palette. Use **Custom**
to change the background, foreground, surface and accent, then name and save the
palette to reuse it. Appearance is also available during first-run configuration.

![Appearance settings showing dark mode, palette presets and editable custom colors](images/appearance-settings.png)

## Installation

### Windows

1. Download **AtelierSetup.exe** from the
   [latest official release](https://github.com/clownfetus/Atelier/releases/latest).
2. Run the installer, then launch Atelier.
3. In **Initial Configuration**, select your Marvel Rivals installation folder
   and provide the current USMAP mapping and AES key when requested. The
   [Help section](#help) has links if automatic retrieval is unavailable.
4. In **Menu → Settings**, choose your mods folder to enable **Copy to ~mods/**.

The Windows desktop window uses Microsoft Edge WebView2. **Edit in Blender** and
**Open in Blender** also require a separate Blender installation; set its
executable path in Settings.

### Linux

Download an `.AppImage` from a [release with a Linux build](https://github.com/clownfetus/Atelier/releases),
mark it executable, and launch it. See [LINUX.md](LINUX.md) for platform setup.
Download a new AppImage when updating; the in-app installer update flow is Windows-only.

## Updates

Atelier checks the main repository's latest published release at launch. On
Windows, a newer version offers **Update Now** or **Later**. **Update Now**
downloads `AtelierSetup.exe`, launches the installer and closes Atelier.
Installation requires that choice; updates are not installed silently at launch.

If the update prompt is unavailable, close Atelier and download/run the latest
official `AtelierSetup.exe` manually. Use the existing installation directory;
the installer is designed to retain projects, exports and settings.

Commits and merged pull requests do not update installed copies. Maintainers
must build and publish a higher-version release with the installer attached.
Source checkouts are updated through Git; see [DEVELOPMENT.md](DEVELOPMENT.md).

## Basic workflow

1. Create or open a project. The project button beside the Atelier logo shows
   the open project and its edit count; click it to switch projects.
2. Browse to the assets you want to change. Edit material parameters or
   right-click a texture to replace it with an external image.
3. Select the assets to include under **Edited Assets** and enter a mod filename.
   Enable **Copy to ~mods/** to install into your configured mods folder. Optional
   **Password Protect** uses the protection password from Settings.
4. Click **Export Mod**, review the included assets and destination, then confirm.

Open **Activity** to review job progress and results or cancel work before file
publication. Interrupted work is recorded after reopening and does not restart
automatically.

Deleting edits moves their files and export options into that project's trash.
Choose **Undo** within 10 seconds to restore the batch; hovering pauses the toast.
Shift-click Delete skips the prompt and keeps Undo available. Trash is kept for
7 days, up to 20 batches, and is excluded from mods and project archives.
Deleting an entire project remains permanent and asks for confirmation.

Use **Bulk VFX / curves** to preview a multiplier or RGB replacement across
supported assets in the selection or current folder. RGB edits preserve alpha.
Global material parameter collections are labelled because changes can affect
every referencing material. Save the reviewed batch, then export separately.

## Skin Swapper mods

Atelier can export an edited character mesh as a mod for Project Galacta's
Skin Swapper, which its Companion App then loads.

1. Edit a skin's mesh in Blender or replace it with **Replace model…** using your
   own BLEND, FBX, GLB or PSK file, then select it under **Edited Assets**.
2. Set the mod filename. It becomes the Galacta folder name, so use letters,
   digits and underscores only.
3. Click **Export Mod** and choose **Skin Swapper mod (Project Galacta)**. The hero
   and skin come from the mesh and cannot be changed. Enter the skin name and
   author, and pick a form for multi-form heroes (Form 0 is the default).
4. Click **Build Skin Swapper mod**, then add the mod in the Companion App.

The mod holds only your mesh and a Galacta config for it, under
`/Game/Marvel/ProjectGalacta/Meshes/{HeroID}/{SkinID}/{ModFolder}/`. Atelier
never ships game assets in these mods: unedited meshes and models imported from
cooked game files are refused. The top-level mesh geometry must differ from the
game's: re-saving in Blender or recooking alone does not qualify. It never creates
or edits `skins.txt`; the Companion App manages that. Project Galacta can switch this export off, and the
review then says why.

To test the integration from source, see [Testing Skin Swapper export](docs/skin-swapper-testing.md).

## Help

<a id="get-marvelrivals-path"></a>
To find the game folder in Steam, right-click **Marvel Rivals → Manage → Browse
local files**, then select that installation folder in Atelier.

<details>
<summary>Steam folder location</summary>

![Steam menu showing Manage and Browse local files for Marvel Rivals](images/rivals_path.png)

</details>

If automatic key or mapping retrieval is unavailable, obtain the current files
and update them in **Menu → Settings**:

- [AES key help on Discord](https://discord.com/channels/1419106202511609958/1485413590310584374/1485417747834863616)
- [USMAP mapping files from SpaceHost](https://spacedepot.github.io/SpaceHost/)

### Windows notices

Releases are unsigned, so Windows may show an unrecognized-app warning. Confirm
that the download came from the official repository before deciding to run it.
If antivirus software blocks a file, review the specific detection and include
its details when reporting an issue; a warning alone does not establish whether
a file is safe.

## Development and release builds

See [DEVELOPMENT.md](DEVELOPMENT.md) for isolated source setup and verification,
[CONTRIBUTION_NOTES.md](CONTRIBUTION_NOTES.md) for the feature/review map, and
[PACKAGING.md](PACKAGING.md) for portable review packages. A portable review ZIP
must be extracted in full; `Atelier.exe` needs its adjacent `_internal` directory.

To make a Windows release discoverable by existing installations:

1. Build the intended source with a higher numeric version, such as `0.4.0`.
   [BUILD.bat](BUILD.bat) writes the application version and supplies the matching
   version to the installer compiler. Verify the installer and upgrade behavior
   using the [installer checks](DEVELOPMENT.md#disposable-windows-installer-verification).
2. Publish a stable release in **clownfetus/Atelier**, using that numeric tag
   (`0.4.0` or `v0.4.0`) and attaching the installer named **AtelierSetup.exe**.
3. Make it the latest release. The updater requires a version higher than the
   installed version; replacing an EXE under the same version will not trigger it.

Drafts and prereleases are not the stable update channel. The Windows installer
verification workflow checks candidate installers; it does not build or publish
a release automatically.

## Collaborators

- Tendo ([tendo625](https://github.com/tendo625))

## Credits

- Noobmaster and Clownfetus
- Xzant ([UAssetToolRivals](https://github.com/XzantGaming/UAssetToolRivals))
- Natimerry ([repak-rivals retoc](https://github.com/natimerry/repak-rivals/))
- Saturn ([Repak-X](https://github.com/XzantGaming/Repak-X), [SpaceHost](https://spacedepot.github.io/SpaceHost/))
- donutman07 ([Character IDs](https://github.com/donutman07/MarvelRivalsCharacterIDs/))
- [RivalSkins](https://rivalskins.com/heroes/) for optional hero and skin artwork
