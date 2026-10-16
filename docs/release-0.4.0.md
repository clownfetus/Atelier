# Atelier 0.4 — Model Studio

Atelier 0.4 makes the viewer easier to work in, adds model replacements to the
edit list, and fixes the screen flashing when textures are loaded. The app and
installers identify this release as **0.4.0**.

## A clearer 3D workspace

Model Studio has its own appearance and shows editing controls when you select a
part or material. Edited textures load automatically, with originals used where
there are no edits. Compatible idle animations loop by default, rim lighting no
longer obscures the model, and loading progress is visible on the model itself.

## Replace models from the edit list

Add a mesh to the edit list, choose **Replace model**, and select a BLEND, FBX,
GLB, PSK/PSKX or cooked Unreal mesh. For cooked files, include matching UEXP and
UBULK companions when present.

Three import options start enabled:

- **Keep original skeleton** uses the character's game rig.
- **Preserve compatible weights** keeps usable weights and fills missing weights
  from the original.
- **Keep facial and corrective morph targets** retains original morph names and
  maps their movements onto the replacement at each rebuilt detail level.

Choices persist with the saved model. Available LODs are rebuilt and checked
before saving, and the replacement joins other edits in the same exported mod.
Disabling skeleton preservation still requires matching bone names and hierarchy.
Substantially changed facial geometry needs an in-game animation check.

## Less disruption while editing

Texture imports keep the grid, banner and existing edit-list thumbnails in place.
Revert to original keeps the asset in the list and preserves its export selection.
New high-resolution texture data is recovered automatically, with painted pixels
preserved and the previous image backed up.

The library has clearer editing borders, transparent character artwork, roster
arrows, artwork-coloured costume names, a repaired Hood portrait, and one 3D
preview action. VFX/curve batch controls stay hidden until a compatible editor is
loaded. Successful mod builds have a green result panel.

## Download and update

Get **AtelierSetup.exe** for Windows or **Atelier-0.4.0-x86_64.AppImage** for Linux
from the [0.4 release](https://github.com/clownfetus/Atelier/releases/tag/0.4.0).
Source, checksums and `VERIFICATION.json` are included with the release assets.

On Windows, restart Atelier to check for the update and choose **Update Now**.
For a manual update, close Atelier and run the installer using the existing
installation directory. Upgrade tests verified preservation of synthetic user
files, settings and browser preferences.

On Linux, download the new AppImage and mark it executable. See
[LINUX.md](../LINUX.md) for system dependencies, including Wine for the Windows
mesh and animation decoders. Native AppImage startup was checked on Ubuntu 24.04;
that does not establish every Wine-dependent modding workflow.

## Verification

[The successful workflow](https://github.com/clownfetus/Atelier/actions/runs/38870854575)
passed 22 backend suites, 10 focused browser checks, and Windows clean install,
running upgrade, reinstall and uninstall on Windows 2022 and 2025. Each installer
test verified all 503 payload files. Linux passed its AppImage build and native
startup check.

Separate native checks retained all 38 original morph identities through a
cooked-mod round trip, matched GPU/CPU counts at both available LODs, and decoded
the result with an independent CUE4Parse reader. Three.js preview deformation was
also checked. These data checks do not establish facial likeness or in-game
animation quality for every replacement.

Application build: `8e26d87636c735320b553ffbfeeb12e8d901c55c`. Subsequent documentation
changes do not change the tested application payload.

See the [full changelog](../CHANGELOG.md).
