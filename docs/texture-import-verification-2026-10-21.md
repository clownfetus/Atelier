# Custom texture import verification — 2026-10-21

The image/template importer reproduced the reported `T_Visor` crash exactly:
the exported texture declared **524436** bytes while the game's texture format
chain consumed **524428**. An additional eight-byte `None` terminator remained
after that chain.

## Correction

Added textures now preserve the original cooked export bytes during package
renaming, with a byte-for-byte check before image injection. The resulting
texture is validated before it is saved to the project.

Exports of older added assets repair the confirmed duplicate terminator in
private staging. The saved source package and image stay unchanged. Re-export
the existing project to obtain the corrected mod; re-importing the image is
unnecessary. Custom material-slot textures use the same trailer validation.
Texture group changes are checked before an optional low-quality twin is copied.

The validator follows the UE5 relative pixel-format skip offsets and final name
terminator, matching the structure in [CUE4Parse's texture reader](https://github.com/FabianFG/CUE4Parse/blob/ea85cf20d8df53556f399c5fabc2befb46b65d0d/CUE4Parse/UE4/Assets/Exports/Texture/UTexture.cs#L91).
It does not strip everything the JSON decoder calls `Extras`: that field also
contains legitimate bytes in some healthy textures. Ambiguous extents and
unknown trailing data are rejected. A repair must preserve every other payload
byte; a failed rebuild leaves both staged package files unchanged.

## Validation

- The reported 1024×1024 DXT1 texture reproduces the precise eight-byte mismatch
  before the fix. New imports, single-mip exports, mip-chain exports and exports
  of a copied legacy project now have no unconsumed texture bytes.
- The single-mip export has serial size **524428**. Native mod creation and
  container readback retain that size, the requested package/name, image
  dimensions and decoded pixels.
- The legacy source and copied project hashes remain unchanged during export.
  Installed game container sizes/timestamps are unchanged; no mod is installed.
- Real custom diffuse/normal slot assignments also pass native build and
  container readback, retaining their selected paths, formats, dimensions,
  pixel hashes and untouched material inputs.
- Eight generated binary regression cases cover exact extents, nonzero name
  indices, multiple format entries, legitimate JSON `Extras`, idempotent repair,
  unknown data, invalid ranges and failed native rebuilds. Added-asset,
  custom-texture, export-option and rollback tests also pass.

The [cross-character verification receipt](character-preview-verification-2026-10-21.json)
includes the native texture results and final regression summary. Raw packages,
images and local configuration stay outside the repository. In-game confirmation
remains pending.

## Reproduce

Use isolated configured app data and a fresh report outside the game directory:

```powershell
$env:ATELIER_DATA_DIR = 'D:/AtelierQA/Data'
.venv/Scripts/python.exe tests/native_added_texture.py --report-dir D:/AtelierQA/Visor --legacy-project D:/AtelierQA/OldProject
```

The optional legacy project is copied before testing. Its original files are
read-only. Without that argument the probe verifies new imports and their native
container readback.
