# Testing Skin Swapper export

This guide is for the Project Galacta team. It sets up Atelier from source and builds a
Skin Swapper mod you can load in the Companion App. Each of your integration conditions is
listed with how Atelier meets it and how you can check it.

Skin Swapper export is on `main` (PR #15, merge commit `e416af4`). It is not in a published
release yet. The newest installer, 0.4.1, does not include it.

## What you need

- Windows 10 or 11, 64-bit, with Marvel Rivals installed.
- 64-bit [Python 3.12](https://www.python.org/downloads/) with the `py` launcher.
- [Git](https://git-scm.com/), or the [ZIP of main](https://github.com/clownfetus/Atelier/archive/refs/heads/main.zip).
- [Blender](https://www.blender.org/) 4.5 to 5.1, used to edit or rebuild a mesh.
- Microsoft Edge WebView2. Windows 11 already has it.
- Your `GAL_ConfigTemplate.uasset` and `GAL_ConfigTemplate.uexp`.
- A Companion App build that includes `GAL_ModSkinConfig`.

## Setup

```powershell
git clone https://github.com/clownfetus/Atelier.git
cd Atelier
.\scripts\Setup-SkinSwapperTest.ps1 -Template 'D:\Galacta\template' -DataDir 'D:\AtelierGalactaTest' -Launch
```

`-Template` is the folder holding the two template files. `-DataDir` is where this test copy
of Atelier keeps its settings, projects, exports, logs and tools. Put it on the same drive as
the game: the 3D viewer hardlinks the game's containers so that installed mods stay out of
its reads, and hardlinks only work within one drive.

The script:

1. creates `.venv` with Python 3.12 and installs `requirements.txt`;
2. installs Atelier's native tools into `<DataDir>\Tools`. It downloads the 0.4.1 release
   installer, checks its SHA-256 and unpacks the tools from it without running it. To skip
   the 150 MB download, add `-ToolsFrom 'C:\Path\To\Atelier'`, naming an existing Atelier
   0.4.x install folder;
3. copies your template into `<DataDir>\Tools\Galacta` and prints both SHA-256 hashes, so
   you can confirm they are your files;
4. asks Atelier whether Skin Swapper export is available. It should print
   `Available: template installed, Galacta switch on.`;
5. with `-Launch`, opens Atelier in a desktop window.

Nothing is written to the game folder, the registry or an installed Atelier. The template
stays in `<DataDir>`, outside the checkout, and git ignores `GAL_ConfigTemplate.*` everywhere.

To start Atelier again later:

```powershell
.\Start-AtelierDev.ps1 -Mode Desktop -DataDir 'D:\AtelierGalactaTest'
```

## First run

1. In **Initial Configuration**, choose the Marvel Rivals install folder. Atelier fetches the
   current USMAP mapping and AES key; paste the key yourself if fetching fails.
2. Create a project when asked, for example `GalactaTest`.
3. Open **Menu → Settings**:
   - Set the **Blender** path.
   - Set the mods folder to the game's `Paks\~mods` if you want Atelier to copy finished mods
     there. Otherwise leave it empty and copy the files yourself.

## Build a test mod

1. **Pick a skin.** From the home screen, open the hero and skin, then the skin's `Meshes`
   folder. Mesh paths look like `Characters/1024/1024503/Meshes/SK_1024_1024503`.
2. **Make an edited mesh.** Either way works:
   - Right-click the mesh and choose **Add to edit list**. In the **Replace** dialog that opens,
     pick your BLEND, FBX, GLB or PSK model. The defaults keep the game's skeleton, weights and
     morph targets. Later, right-click the mesh and choose **Replace model…** to swap it again.
   - Right-click the mesh, choose **Edit in Blender**, change the mesh, and save the `.blend`.

   The mesh then appears under **Edited Assets** on the right.
3. **Name the mod.** Under **Mod filename**, type the name. It becomes the Galacta folder name,
   so use letters, digits and underscores only, for example `RedeemedRedux`.
4. **Choose the format.** Click **Export Mod**, then **Skin Swapper mod (Project Galacta)**. The
   review shows:
   - the hero and skin, read-only;
   - the Galacta folder the mod will use;
   - **Skin name** and **Author**;
   - a **Form** choice for each mesh. Form 0 is the default; use one mesh per form for
     multi-form heroes.

   Any rule the mod breaks is listed, and **Build Skin Swapper mod** stays disabled until it is
   fixed.
5. **Build.** Click **Build Skin Swapper mod**. The result shows the Galacta folder and output
   path. **Show exported files** opens `<DataDir>\assets\exported`.
6. **Load it.** Add the mod in the Companion App and test it in game.

## What Atelier builds

For mod `RedeemedRedux`, one mesh, form 0:

```
RedeemedRedux_9999999_P.pak / .utoc / .ucas      one IoStore container
  /Game/Marvel/ProjectGalacta/Meshes/1024/1024503/RedeemedRedux/
    SK_1024_1024503        the edited mesh (same asset name as the game's)
    GAL_RedeemedRedux      its config (form n > 0: GAL_RedeemedRedux_S{n})
```

The config is your template with its name map and property values patched, then read back
and checked before it can ship:

| Field | Value |
| --- | --- |
| Package | `/Game/Marvel/ProjectGalacta/Meshes/{HeroID}/{SkinID}/{ModFolder}/GAL_{ModFolder}[_S{n}]` |
| Class import | `GAL_ModSkinConfig_C` (`/Script/Engine`, `BlueprintGeneratedClass`) in `/Game/Marvel/ProjectGalacta/Blueprints/GAL_ModSkinConfig` |
| Default object import | `Default__GAL_ModSkinConfig_C` (class `GAL_ModSkinConfig_C`) in the same package |
| `TargetHeroID` | int, 4 digits, from the mesh path |
| `TargetSkinID` | int, 7 digits, from the mesh path |
| `TargetSculptID` | int 0 to 9, the form chosen in the review |
| `SkinName`, `Author` | strings from the review, one line, at most 64 characters |
| `MeshToSwap` | hard reference to the mesh package in the same folder |

Properties keep their property tags. The template you provided names its class and
default-object imports `Export_0` and `Export_1`; Atelier renames them to the names above.

## How each condition is met

| Condition | What Atelier does | How to check |
| --- | --- | --- |
| 1. Format | Mesh and config in one Galacta folder and one container; the config is patched from your template, never built from scratch, and must pass a read-back check of every field above. | Unpack the container (below) and inspect `GAL_*` in FModel or UAssetGUI. |
| 1. Moving the mesh | Only the mesh's package header changes. The build stops unless the mesh's `.uexp` comes back byte-identical. | Compare the exported mesh with the project's edit; the geometry is unchanged. |
| 2. No paid-skin bypass | Unedited meshes, meshes whose cooked data equals the game's, and replacements imported from cooked `.uasset` files are refused. | Try exporting an unedited mesh, or one replaced from a game `.uasset`; the review lists why it can't build. |
| 2. No manual IDs | Hero and skin come from the mesh's game path and are only displayed. The build request carries no IDs; the server derives them again. | The review has no ID fields; `TargetHeroID`/`TargetSkinID` match the source mesh. |
| 3. Galacta folder only | The stage is audited before packing: only the planned mesh and config packages may be in it. | The unpacked container holds only the Galacta folder. |
| 4. No `skins.txt` | Atelier never creates, reads or writes it; the stage audit refuses a build containing one. | Your `skins.txt` is untouched after building and installing. |
| 5. Revocation | `integrations.json` on Atelier's `main` switches the export off for every install. It is re-read before each build; the review then shows Galacta's message and the build refuses. | See "Off switch" below. |

## Inspect the output

Unpack the container with the retoc that Setup installed:

```powershell
$tools = 'D:\AtelierGalactaTest\Tools'
& "$tools\shaders\retoc-rivals-cli.exe" -a 0x<AES key> unpack `
  'D:\AtelierGalactaTest\assets\exported\RedeemedRedux_9999999_P.utoc' `
  --game-paks-dir '<game>\MarvelGame\Marvel\Content\Paks' -o '.\unpacked'
```

You should see exactly two packages per form under
`Marvel/Content/Marvel/ProjectGalacta/Meshes/{HeroID}/{SkinID}/{ModFolder}/`. retoc
reports the `GAL_ModSkinConfig` imports as unresolved unless your Companion App container is
in the folder you pass to `--game-paks-dir`.

Atelier's log for the session is in `<DataDir>\_logs`. Each build writes a line starting with
`[skin_swapper] built`, listing the mesh and config it made.

## Things to try

- An unedited mesh (added to the edit list, not changed): refused.
- A mesh replaced from a cooked game `.uasset`: refused.
- A mod name with a space or hyphen: refused, with the reason.
- Two meshes on the same form, or meshes from two different skins: refused.
- A multi-form hero: one mesh per form; expect `GAL_{Mod}` for form 0 and `GAL_{Mod}_S{n}` for
  the others.

## Off switch

Atelier reads `https://raw.githubusercontent.com/clownfetus/Atelier/main/integrations.json`:

```json
{ "version": 1, "skin_swapper": { "enabled": true, "message": "" } }
```

To see the switched-off state without changing `main`, work offline so Atelier keeps its last
known value:

1. Disconnect from the network, or block `raw.githubusercontent.com`.
2. Write `<DataDir>\_cache\integrations-flag.json`:
   ```json
   { "enabled": false, "message": "Paused for testing", "checked_at": 9999999999 }
   ```
3. Open the export review again. The Skin Swapper option is disabled and shows your message,
   and a build is refused.

Once back online, the next build or review reads `main` again. To switch generation off for
everyone, ask the Atelier maintainers to set `enabled` to `false` on `main`.

## Questions for you

1. **Form 0 naming.** Atelier names form 0 `GAL_{ModFolder}` and form n `GAL_{ModFolder}_S{n}`.
   Your example only shows `_S1`. Should form 0 of a multi-form skin be `_S0`?
2. **Import names.** The template's class imports are named `Export_0`/`Export_1`, and Atelier
   renames them to `GAL_ModSkinConfig_C`/`Default__GAL_ModSkinConfig_C`. Is that what the
   Companion App expects?
3. **Cooked replacements.** Refusing models imported from cooked `.uasset` files is our
   reading of "no paid-skin bypass". Is that stricter or looser than you intend?

## Reporting back

Please send:

- the newest log from `<DataDir>\_logs`;
- the build report from the result screen (screenshot or copied text);
- the exported `.pak`, `.utoc` and `.ucas`, if the problem shows up in game.

Open an issue at https://github.com/clownfetus/Atelier/issues or message the Atelier team.
