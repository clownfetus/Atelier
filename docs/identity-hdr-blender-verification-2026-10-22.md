# Shared identities, HDR cubemaps and Blender texture choices

Verified on Windows from the source checkout on 22 October 2026. All exports
used isolated application data and disposable projects under
`D:/AtelierDev/identity-update-20261021`; no mod was installed. The companion
[JSON receipt](identity-hdr-blender-verification-2026-10-22.json) records accepted
test runs, tool hashes, source hashes and local evidence locations.

## Names and artwork across the library

A common resolver recognizes consistent character and costume IDs throughout
content paths, including UI, VFX, plugin and low-quality branches. Folder cards,
breadcrumbs, saved pins, search, material/chroma pickers and custom asset picking
share the same names and artwork. File names containing known IDs receive
character/costume context. Physical names, selected destinations and package
paths stay unchanged and remain available in titles.

The actual installed `UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom`
folder contains **63 costume folders and one Common folder**. All 63 acquire
costume names and character context. Browser and Python identity results match
at **14,916 recognized folder locations**, with no page errors. Screenshots at
1400×900 and 1024×768 were inspected, including Compact cards and long captions.
Unknown costumes use an explicit fallback and hero artwork when available;
conflicting character IDs remain unlabelled rather than receiving guessed art.

## HDR TextureCube creation, replacement and export

Radiance panoramas and six-face strips now import through TextureCube game
templates. HDR DDS cube inputs retain authored faces and mips. The authoritative
project image is HDR DDS; the PNG is a separate, labelled tone-mapped preview.
Material reflection slots can store a custom HDR cube at a chosen package path.
The normal combined mod build retains its `TextureCube` import class.

The native run used real FloatRGBA and BC6H templates, including
`T_Cubemap` from Timestream Raid water materials and Ultron's `T_CubeCity`.
It created and replaced cubemaps, checked single-mip export, panorama projection,
blanking and a texture-group override, then built an actual IoStore mod with
**four cubemaps and one material**. Ultron's `CubeMap_Tex` slot resolves to the
new TextureCube. Source packages and the source material stayed unchanged.

A separately built reader used the exact pinned CUE4Parse assemblies extracted
from AtelierMesh, with .NET SDK **10.0.402**. It read the complete mod as
`UTextureCube` assets with six slices, without unread-byte/serialization warnings.
Every face of every mip matched its expected hash. Independent FloatRGBA values
reached **24.0625**; decoded BC6H values also retained the six distinct HDR levels.
The original game containers retained their size/timestamp metadata and the
isolated mod destination stayed empty.

The platform-data layout follows pinned upstream
[FTexturePlatformData](https://github.com/FabianFG/CUE4Parse/blob/ea85cf20d8df53556f399c5fabc2befb46b65d0d/CUE4Parse/UE4/Assets/Exports/Texture/FTexturePlatformData.cs)
and
[UTextureCube](https://github.com/FabianFG/CUE4Parse/blob/ea85cf20d8df53556f399c5fabc2befb46b65d0d/CUE4Parse/UE4/Assets/Exports/Texture/UTextureCube.cs).
Pixels bypass the native typed texture JSON writer; the completed raw export is
read back before publication. Texture-group edits copy only a verified property
prefix, retaining independently validated pixels and format-chain boundaries.

Inputs are bounded to 512 MB, 32 megapixels and 2048 pixels per cube face.
Missing faces/mips, nonfinite/out-of-range floats, incompatible classes, unsigned
BC6H inputs with negative values, unsafe stored paths and unsupported resource
layouts fail before replacing saved project files. Publication of DDS and preview
uses the existing conflict detection and rollback mechanism.

## Blender without project texture copies

The remembered **Settings → Behavior → Add model textures to the project when
opening in Blender** option defaults on. With it off, Edit in Blender prepares
images in a project-specific cache and packs them into the Blender file.

A real Jeff import produced **31 packed images**, a complete material manifest
and one mesh. Reopening the saved file in Blender confirmed every file image was
packed. The project gained only the model and its two sidecars: its one existing
painted texture stayed byte-identical and the texture file count stayed **1 → 1**.
Preparation took **53.34 seconds** on the first run and **7.11 seconds** on the
cached repeat, which also checked that the packed bytes match the existing paint.
These are workflow observations, not a general loading benchmark. Browser tests verify both toggle states,
persistence across reload and the request sent by Edit in Blender.

## Repeating the native checks

Use isolated configured application data and a fresh report directory for each:

```powershell
.\.venv\Scripts\python.exe -B tests/native_identity.py --data-dir D:/AtelierDev/identity-update-20261021/qa-data --report-dir D:/AtelierDev/new-identity-check
.\.venv\Scripts\python.exe -B tests/native_blender_texture_choice.py --data-dir D:/AtelierDev/identity-update-20261021/qa-data --report-dir D:/AtelierDev/new-blender-choice-check
.\.venv\Scripts\python.exe -B tests/native_hdr_textures.py --data-dir D:/AtelierDev/identity-update-20261021/qa-data --report-dir D:/AtelierDev/new-hdr-check --dotnet D:/AtelierDev/native-build-inputs-20261021/dotnet-10.0.402/dotnet.exe
```

The HDR probe's configured test-mod destination must be under its report's
parent. Runtime keys are passed privately to the independent reader over stdin;
game assets, configs, compiled probes and screenshots remain outside Git.

## Regression and safety results

All **24 selected backend suites** pass: **312 unit tests and 81 additional
script checks**. Two optional legacy Phase 4 native checks skip in their
disposable environments. The separate real HDR and Blender probes pass.
The complete browser suite passes **243 checks** with no page errors, including
both themes, all four card sizes, project isolation, material/texture controls,
Mod tray/Continue spacing and the new settings and pickers.

Additional targeted checks cover the final picker rendering, HDR HTTP response
type, locked thumbnail caches and rejection of PNG-only cube replacement.
Python/JavaScript parsing, dependency consistency, credential-literal scanning
and whitespace checks pass. No external dependencies were added. HDR conversion
uses the existing tracked child-process launcher, retaining cancellation,
timeouts and native/Wine path handling.

## Scope

This verifies Windows source workflows and native package readback. In-game
rendering, Linux and a new installer were not tested. HDR Texture2D, EXR,
virtual/external cube resources and cube arrays are unsupported. Existing
PNG-only cube imports must be re-imported or replaced with HDR before export.
Texture-group overrides require a template with an existing group property.
Blender materials consume the tone-mapped cube preview, not the HDR DDS pixels.
The earlier character and pinned shader/animation/import verifications remain
recorded in their separate dated reports; those native tools were not rebuilt
by this follow-up.
