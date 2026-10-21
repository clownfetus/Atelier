# Feature verification — 21 October 2026

Verification of the consolidated Windows source checkout using disposable app
data under `D:/AtelierDev/feature-tests-20261021`. Game files were inputs; exports
and test installations stayed in report-local folders.

## Repairs found by feature testing

1. **Cold Model Studio material loading.** A real two-form Magik preview exceeded
   the native check's four-minute material deadline. Its materials were extracted
   individually, repeating game-container scans. The route now prefetches their
   exact package paths as a batch, then reads parameters in the originating
   project's context. Individual reads remain available if prefetch fails.
   A repeat from an empty model cache loaded both forms and twelve material
   groups in **163.03 seconds**, including geometry and texture preparation.
   This is one cold-load observation, not an instant-load or broad benchmark claim.

2. **Dense mesh imports stopped at the simplifier limit.** A real Luna Snow
   section needed about 1.31 billion WASM fuel units, exceeding the fixed billion
   limit. Fuel now scales with index/attribute counts, with a hard 50-billion
   ceiling. The 512 MiB guest-memory cap, pinned checksum, no-import requirement
   and disabled optional WASM features remain in force. Exhaustion returns a
   readable error without modifying the source mesh. Regression coverage includes
   a dense 72,962-triangle generated section and a deliberately constrained run.

3. **Numbered package/export names could not serialize.** Skin Swapper's real
   template failed for `SK_1015_1015502`: its new name-map entries omitted the base
   expected by the native JSON reader. A shared append-only helper now retains
   existing indices and includes the needed bases for numbered names. Skin Swapper,
   added packages, custom textures, material replacements and imported material
   references use it. Leading-zero suffixes remain literal. This follows
   [UAssetAPI's FName parsing](https://github.com/atenfyr/UAssetAPI/blob/master/UAssetAPI/UnrealTypes/FName.cs)
   and was verified with the installed serializer and template.

## Coverage and evidence

All **45 backend suites** passed: 445 reported unittest cases (one skipped) and
138 additional checks. Two legacy native-tool cases also skip in the isolated
runner. The complete browser pass contains **223 checks** and no page errors.

The machine-readable companion, `feature-verification-2026-10-21.json`, records
accepted results, source hashes, checks skipped by isolated runners and paths to
the full local evidence. Earlier failing runs remain in the evidence folder.

| Feature | Verification |
| --- | --- |
| Library, hero/skin navigation, search, filters, pins, Continue | Real browser interactions with labelled catalogue fixtures |
| Projects, recovery/trash, project isolation, partial-save retry | Real local HTTP/file operations in disposable projects |
| Themes, palettes, keyboard input, uploads, captures | Chromium and native WebView2 interactions; both themes and compact layouts |
| Material edits and replacement | Real native build/unpack, parameter/import-graph readback and original restoration |
| Texture edit, dye neutralization, custom texture locations | Real extraction, encoding, build/unpack and decoded pixel/format checks |
| Process S maps | Real local jobs with matched fixture images, alpha/D preservation, unmatched-map reporting and explicit shared-map pairing |
| Added texture, material and mesh packages | Native creation, editing, preview, combined build and package identity readback, including numbered names |
| Curves, global material parameters and Niagara batch changes | Native build/unpack and key/tangent, scalar/vector and LUT readback |
| Model Studio | Real Magik geometry, twelve material groups, two forms, standing idle, comparison and bloom in WebView2; no page/shader errors |
| Portable Blender export | Real Luna Snow scene with eleven materials and fifty-two packed, connected textures, deformation bones and verified resting geometry |
| Model replacement and LOD generation | Authored Blender sculpt, original skeleton, every cooked detail level, complete mod container and native geometry readback |
| Skin Swapper | Real installed template and publisher availability flag; edited mesh/config build and native package readback |
| Hidden mesh sections and original restoration | Every cooked LOD, unchanged vertex geometry, untouched other sections and byte-identical restoration |
| Jobs and closing the desktop window | Real hidden WebView2 close cancels an owned child and persists terminal job state |
| Local API and optimizer boundaries | Loopback/origin guards, JSON writes, executable validation, checksum/import rejection and bounded optimizer execution |

The browser suite contains **223 checks**. Its game/native actions use explicit
fixtures; the separate native runs above use the installed tools and real game
packages. Native generated-geometry checks also exercise Blender and the pinned
WASM module together. Successful source checks do not imply that an installer or
the installed executable was rebuilt.

Representative screenshots were inspected from the native model and compact
library/Mod tray runs. Screenshot evidence remains local rather than adding game
artwork or cooked assets to this repository.

## Repeating the checks

Run `tests/run_checks.py` for isolated backend suites and select
`--suite browser_smoke.py` for the complete browser pass. The development guide's
[native model instructions](../DEVELOPMENT.md#native-model-feature-checks-21-october-2026)
cover `native_viewer_smoke.py --source` and `native_model_workflows.py`.
All native reports must use fresh directories. The source viewer requires
completed setup settings, an active disposable project and its own `test-mods`
destination.

The other opt-in native scripts are `native_smoke.py`, `native_added_assets.py`,
`native_custom_textures.py`, `native_material_replacement.py`,
`native_material_dye.py`, `native_bulk_smoke.py`, `native_triage_exports.py`,
`native_mesh_optimizer.py` and `window_job_smoke.py`. Use
`native_custom_textures.py --name T_FeaturePaint_7` to repeat the numbered custom
texture case.

## Limits

This pass tests Windows source features and native file round trips. In-game
rendering, the Galacta Companion App, a newly built full installer and Linux were
not exercised. Cold character preparation can still take several minutes. The
existing unsupported-format boundaries remain: there is no `.uemodel` importer,
and skeletal layouts with 16-bit bone indices or bone weights may be previewed
but are refused by the mesh rebuild path. The isolated backend runner skips its unavailable `bpy` test
and two legacy native-tool cases; actual Blender/native workflows are verified
separately above.
