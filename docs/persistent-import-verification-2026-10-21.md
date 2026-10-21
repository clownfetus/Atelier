# Persistent import verification — 21 October 2026

Windows previews now use a persistent native import server. One CUE4Parse reader
serves mesh geometry, material parameters and texture pixels throughout the app
session. This supersedes the [75-second loading revision](model-loading-verification-2026-10-21.md).

## Implementation

- The app owns the decoder through inherited JSON pipes. Keys travel through the
  initialization pipe; there is no additional HTTP listener or command-line key.
  Requests are serialized because package deserialization is not thread safe.
- Use the same compatible CUE4Parse assemblies already bundled in AtelierMesh.
  Read top-level game archives directly, excluding nested mods, loose files and
  the known top-level Galacta loader. No cross-volume game-container copy is needed.
- Retain source-keyed caches outside project edit files. A change to the game
  containers, mappings, tool or key identity selects a new cache and reader.
  Saved mesh edits, material documents, painted PNGs and custom maps retain priority.
- Publish geometry and metadata atomically. Validate exact paths, dimensions,
  compressed block lengths, GLB headers and PNG integrity before use. Cancelling
  an active import terminates its owned reader; a cancelled queued request leaves
  another project's active request alone. Invalid protocol frames/timeouts reset
  the reader; framed per-asset errors keep a healthy reader reusable.
- Omit the 37 unused facial morph targets from the static viewer GLB. The Black
  Widow body shrank from 73,822,932 to 15,006,272 bytes. All 168 compared geometry
  attributes, indices, inverse-bind matrices and 580 rig nodes remained exact.
  Full Blender exports and mesh editing retain their separate complete morph path.
- Transfer compressed texture blocks unchanged and decode them with the existing
  DDS/Pillow decoder. A real dye test exposed rounding differences in the initial
  native pixel decoder, including five changed region texels. The final path
  restores pixel-identical masks and all fifteen compared viewer images.

The inspected [RivalsPorting listener](https://github.com/Bmarquez1997/RivalsPorting/blob/8dab506d24fbc77b2c0ecceaacfb21795361bf98/FortnitePorting.Plugins/Blender/rivals_porting/server.py)
runs inside Blender. Atelier's new service retains the game reader in the preview
backend, where the measured delay occurred; it does not install that HTTP listener.

## Measurements

Same Windows machine, game installation, Black Widow skin `1033001` and lobby body.
Cold means empty source-specific geometry/material/image preview caches. The game
asset index and Windows filesystem cache are separate; app startup and initial
asset-index creation are outside the viewer-open interval.

| Revision | First body | Geometry, materials and images ready |
| --- | ---: | ---: |
| Previous batching revision, cold | 17.83 s | 75.02 s |
| Persistent reader with complete Studio checks, cold | 11.45 s | 18.20 s |
| Final archive-filter revision, cold | 11.39 s | 18.17 s |
| Final revision, cached new app session | 2.42 s | 7.30 s |

Both final runs requested three models and fifteen images and exposed thirteen
material slots in twelve groups. The full Studio run used one reader PID for
thirty initial requests and forty-six total requests across form changes, with
one initialization. Its private allocation after those checks was approximately
794 MiB. The final archive-filter
run also initialized once, used the same reader throughout and left no native
child process running after closing its parent. These are local observations for
one character, not a broad performance guarantee.

## Verification

- All **46 backend suites** pass: **468 reported unittest cases** and **138
  additional checks**. One unavailable-`bpy` case and two legacy native-tool cases
  retain their isolated-runner skips. The final archive exclusion and changelog
  follow-up also passed the targeted suites. The sixteen import-client tests
  exercise real child pipes, request contention, process crashes, cancellation,
  shutdown during initialization, cache invalidation, corrupt output and overrides.
- **52 viewer**, **12 Blender-export** and **16 Showcase** browser checks pass
  without page errors. These are per-run counts; shared startup checks overlap.
- Actual WebView2/native checks pass geometry/material/image loading, both themes,
  contextual controls, live colour draft/revert, lazy body switching, Original and
  side-by-side comparison including unmapped slots, standing idle playback,
  pause/rest pose, bloom and close. Screenshots were inspected for real rendering.
- Eleven Black Widow material parameter sets exactly match the legacy reader.
  All fifteen compared viewer images have the same dimensions and RGBA pixels.
- White Fox `1060300` Equip_01 verifies seven dye regions, a 2048×2048 mask with
  exact RGBA and region indices, live recolouring, Original comparison, region
  overlays, exact material parameters and reader reuse. No project files were
  created. The decoder rounding regression was repaired before final verification.
- The self-contained native tool builds with .NET SDK 10.0.402 using the existing
  mesh assemblies. Windows staging, installer requirements and missing-tool
  diagnostics include its three files. The release-candidate workflow builds it
  after retrieving the pinned native seed. Linux retains the prior path.
- Dependency consistency, source compilation, whitespace and changed-source
  credential checks pass. These preview checks use isolated projects and
  `test-mods` folders, read game containers, and install no mods.

Machine-readable outcomes, source/tool hashes and evidence locations are in
[the verification JSON](persistent-import-verification-2026-10-21.json).
The earlier real Blender/LOD/Skin Swapper workflows remain documented in
[the feature verification](feature-verification-2026-10-21.md).

## Limits

The acceleration is verified on Windows x64. Older external tool sets and Linux
retain compatibility decoding. Unsupported material or texture layouts fall back
to the existing decoder. Standing-idle decoding retains its separate existing
tool. A new full installer, Linux and in-game rendering were not exercised in this
follow-up. Fresh geometry and first-time selection of other forms still take time.
