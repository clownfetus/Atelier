# Model loading follow-up — 21 October 2026

The earlier repository work was a set of focused adaptations, as documented in
[the integration review](repository-integrations-2026-10-20.md). It did **not** add
RivalsPorting's persistent import server. AtelierMesh still starts a decoder for
each uncached mesh. The earlier 163.03-second Magik result was not sufficient
evidence that loading was fast.

## Reproduction and changes

The slow preview in the user's log was **Black Widow, skin 1033001**, with
`Characters/1033/1033001/Meshes/SK_1033_1033001_Lobby` selected. Initial progress
updates incorrectly called this Punisher; all measurements used the same asset.

The viewer decoded every mesh before requesting materials, including hidden body
forms, physics and first-person assets, duplicate weapons and unused attachments.
It also downloaded shared texture images repeatedly before they entered the GPU
cache. Material-slot discovery constructed a full editable mesh unnecessarily.

- Load one selected body and only compatible equipped weapons initially. Retain
  alternate forms and attachments in the picker and decode them on demand.
- Append new materials while retaining existing recolour drafts, dye maps and
  decoded geometry. Keep capture/export controls unavailable during transitions.
- Exclude `_PA`, first-person meshes and first-person hand assets from automatic
  character discovery. Keep optional equipment selectable.
- Batch source mesh packages, material packages and required viewport texture
  channels. Bound parameter conversions to four workers, deduplicate shared
  material paths, and copy project/cancellation context into every worker.
- Read material headers through the existing structural parser, retaining exact
  package-import/slot provenance without loading streamed geometry for editing.
- Deduplicate in-flight image downloads and serialize same-asset JSON conversion.
  Project edits retain priority; validated output is still published atomically.
- Keep decoded maps for unmapped slots. Original/Compare clones those sections
  without requesting a null material; mapped-material failures remain visible.
- Preserve the Model menu when restoring an all-hidden model, so the Blender
  action remains accessible.

## Measured preview loading

These are local observations on the same Windows machine and game installation,
using actual source-app WebView2 rendering and native tools. Cold runs had empty
Atelier model/material/texture caches. The reusable game asset index and Windows
filesystem cache are separate from those preview caches. Startup/index creation
is outside the measured viewer-open interval.

| State | First visible body | Geometry, materials and textures ready | Model requests | Texture requests |
| --- | ---: | ---: | ---: | ---: |
| Previous viewer | 24.12 s | Still unready at the approximately 264 s deadline | 15 | 47 started |
| Revised, cold preview | 17.83 s | 75.02 s | 3 | 15 |
| Final revision, cached preview | 4.48 s | 9.01 s | 3 | 15 |

The intermediate revision took 83.02 seconds. The final cold run rendered the
selected body and both sticks, exposed thirteen material slots in twelve groups,
played a real standing idle, rendered both themes and closed without page or
shader errors. Hidden choices remained available without delaying that load.
The final revision also passed native form switching, parameter edits/revert,
Original/Compare, idle playback and both themes. Selecting the cached other form
took 6.09 seconds. The cold timing precedes the final menu and unmapped-slot fixes;
the final revision was verified with cached inputs.

This is a measured improvement for one character, not a general instant-load
claim. Fresh native geometry preparation, patch-container compatibility fallbacks
and first-time selection of other forms still incur work.

## Validation and safety

- All **45 backend suites** pass: **450** reported unittest cases and **138**
  additional checks. The existing unavailable-`bpy` case and two legacy native
  cases retain their isolated-runner skips.
- **52 viewer browser checks** cover lazy form loading, retained recolour drafts,
  shared image downloads, project scope, cancellation, comparisons, capture,
  error/retry states, geometry disposal and both themes.
- **12 Blender-export browser checks** cover restoring hidden bodies, choosing one body,
  project-scoped export jobs, duplicate-click protection, errors and retries.
- **16 Showcase browser checks** pass, including restoration of exact editable
  material objects, capture and separate presentation settings. Startup checks
  overlap between these browser runs; these are per-run counts.
- Real native header results exactly match the former editable-mesh slot reader
  for the lobby body and both weapons. The cached body-header comparison took
  **0.212 s**, versus **4.859 s** for constructing the editable mesh.
- Performance/native checks use disposable projects and report-local `test-mods`
  folders under `D:/AtelierDev/viewer-performance-20261021`. Game containers are
  inputs; these preview checks do not build or install a game mod.
- Existing loopback/same-origin checks, cancellation checkpoints, precise section
  mapping, PNG validation and atomic publication remain enforced.

Machine-readable evidence and final browser/native outcomes are recorded in
[the loading verification JSON](model-loading-verification-2026-10-21.json).
The earlier full Blender/LOD/Skin Swapper validation remains in
[the feature verification](feature-verification-2026-10-21.md).
