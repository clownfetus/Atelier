# Model Studio design QA

**Final findings:** No actionable P0/P1/P2 findings remain. The selected layout is implemented as the requested distinct working environment, with contextual controls and real game content.

## Evidence and comparison state

- Source visual truth: `docs/viewer-design/option-1.png`, the first displayed option chosen by the user.
- Implementation: `docs/viewer-design/studio-light-draft.png`, the actual packaged Windows WebView2 app with Magik / Amethyst Armor, one mesh, Body selected, an unsaved purple colour draft and Advanced closed. The draft was reverted without saving.
- Full comparison: `docs/viewer-design/comparison-final.png`. Focused comparisons: `comparison-inspector-final.png` and `comparison-header-final.png` in the same directory. Both source and implementation are included in each comparison image.
- Source pixels: 1581 × 995. Implementation: 1582 × 995 CSS and screenshot pixels, scale 1. The paired comparison normalizes the implementation by one pixel in width. No browser/device chrome is included.
- Additional evidence: `docs/viewer-design/studio-dark-view.png`; compact layouts, settings, advanced parameters, original/wipe comparison, loader states and captures are saved in the external verification directory `D:/AtelierDev/viewer-redesign-20261016/`.

## Comparison history and resolved findings

1. First native comparison (`comparison-1.png` and `comparison-inspector-1.png` in the external verification directory):
   - [P1] The transformed rig had only three mapped materials and was mostly white. The material-name canonicalizer removed five-digit rig IDs and caused the two forms to collide. It now preserves rig IDs while normalizing the longer skin ID. The same form now has ten editable materials in five groups, with real textures. The second form remains separately selectable. Real Original/Wipe material reads and animation decoding pass.
   - [P2] The inspector was only 340px and type too small at the target viewport. It is now 27% of the workspace (420px maximum), with 19px headings, 15px material choices and 14px colour labels.
   - [P2] Global bounding-box corners left too much empty space around the model. Framing now fits each visible mesh part with 8% padding and a more frontal default camera. Camera presets still contain the geometry at all tested sizes.
   - [P2] New icon aliases initially fell back to a file symbol. They now use the matching official pinned Material Symbols from the offline bundle.
2. Subsequent native comparison (`native-qa-2` / `native-qa-3`): mapped textures, readable sizing and framing were corrected. Repeated numbered material rows were consolidated into related groups, with a contextual part picker.
3. Final paired comparison linked above: all earlier findings are resolved. The Save action is enabled for the same unsaved state as the reference. Native draft checks confirm the chosen hex survives selection; revert restores saved values. The loader retains a dark studio surface for bright linework in both themes and hides irrelevant stage tools during decoding.

## Required fidelity surfaces

- **Fonts and typography:** local bundled Roboto, matching the established Atelier font. Titles, material choices, input values and supporting labels have a clear hierarchy. Exact font rendering differs slightly from the generated mock. Text truncation retains full names in tooltips/advanced details; compact layouts keep controls reachable.
- **Spacing and layout:** matches the reference's header, dominant stage, right inspector and bottom playback. The header explicitly labels Model Studio and uses a blue border to distinguish the environment. Controls do not overlap at 1024×768, 1400×900 or 1920×1080; 800×700 and 680×900 use a narrower or stacked inspector. Menus remain within the viewport.
- **Colours/tokens:** studio-local blue/slate surfaces and paired foreground tokens distinguish it from the main library while supporting light/dark mode. The selected state and primary Save action use the reference's blue emphasis. Saved/Current swatches display real material colours; selection and focus have visible states.
- **Image quality/assets:** real decoded game geometry, textures and skeletons are rendered by Three.js. The mock's illustrative model merges visual characteristics; it is not a substitute asset. Authentic rig geometry, pose, shader parameters and lighting explain residual content differences. Icons are official offline Material Symbols. No generated model raster or decorative placeholder substitutes for working content.
- **Copy/content:** the studio uses Save changes, Model, View settings, Main colour/Glow colour, Saved/Current, Advanced parameters and Revert material. Material groups use real available parts. Raw identifiers and shader-specific names are deferred to details. No implementation instructions appear in the product flow.

## Intentional product differences from the mock

The user asked for editing only when needed and an environment distinct from the main window. No material is selected initially. Selecting a group or clicking the model reveals its inspector; closing selection hides it. Five actual material groups replace the mock's three illustrative categories. A part picker appears only for groups with several materials. Only supported shader parameters are exposed; the mock's generic glow-percentage slider is not fabricated. The existing full editor remains available under Advanced for scalar and other parameters. Model can show a single rig or combine mesh parts explicitly. A secondary Capture menu preserves existing PNG/WebP functionality.

## Interaction and regression evidence

Backend suites, the full browser suite, packaged WebView2 checks and live game checks are recorded in the external `verification.json`. Tests cover selection, grouped drafts, entered hex, Saved/Current restore, save failures/retry/concurrent edits, close/export guards, menu Escape and focus return, framing, lighting, comparison, dye overlays, bloom allocation/cleanup, reduced motion, transparent poster/WebP downloads, capture cancellation/camera restoration and real standing-idle playback. No page or shader errors were reported in the completed packaged/live-game runs.

The whole-app browser suite uses disposable projects and intercepted game/native operations. Native game checks create and revert in-memory drafts, with no material save, mod export or installation. Native capture checks inspect encoded files before the OS Save As dialog; the standalone browser verifies actual downloads. Windows verification does not establish Linux/WebKitGTK/Wine or in-game shader, cloth and VFX fidelity.

## Implementation checklist

- [x] Resolve exact selected image and preserve it with the source.
- [x] Implement the selected composition with contextual controls and separate workspace identity.
- [x] Compare full view, inspector and header against the source.
- [x] Fix all P0/P1/P2 findings and inspect post-fix native captures.
- [x] Verify both themes, narrow layouts, primary interactions and failure/draft safety.

## Follow-up polish

[P3] Model shading and the exact silhouette depend on the real game rig and supported preview shaders; further in-game parity is separate from this layout redesign. Screen-reader workflow and Windows high-contrast audits were not performed.

final result: passed

## Roster follow-up — 16 October 2026

The user requested The Hood's missing portrait, side arrows in place of horizontal
scrollbars, and costume-name backgrounds sampled from their artwork. Both rows
now have keyboard-operable arrows that disable at their limits and respect reduced
motion. Skin names sample their own cached portrait and retain 4.5:1 text contrast
in light and dark themes. Theme changes repaint the local tints. The published
Hood 0011 portrait replaces the upstream 0010 silhouette.

Verified with four artwork unit checks, nine focused browser checks and eleven
checks in the rebuilt native WebView2 executable. Read-only integration checks
and inspected screenshots confirm distinct tints with real Adam Warlock costumes
and the correct Hood portrait. The packaged roster and sampler match source.
Reports and screenshots are under D:/AtelierDev/hood-icon-fix-20261016.

## Viewer and project follow-ups — 16 October 2026

Character-folder portraits retain their transparency. Banner artwork uses numeric
character codes from the hero-story-images catalogue. Batch VFX/curve actions
appear only within a loaded compatible editor; mesh menus expose one 3D action.
The Model menu stacks its fields, constrains long names, and can add its mesh to
the edit list. Imported grid cards have a three-pixel green border and an Editing
badge. Successfully completed build dialogs use green surfaces and controls;
warnings and failures retain their outcome states.

Model Studio prefers saved textures and falls back to originals, plays a compatible
standing idle on repeat, omits rim lighting and opaque rim shells, and shows a
moving scan on the model during appearance loading. Native idle discovery includes
flat mesh folders as well as rig subfolders. Pause, Play and Rest pose work after
automatic playback.

Model replacements accept BLEND, FBX, GLB, PSK/PSKX and cooked UASSET companions.
They retain the original skeleton and compatible weights, transfer absent weights,
vertex colours and secondary UVs, rebuild available LODs, and validate the cooked
result before publishing the model, preview and metadata together. Import exposes
Keep original skeleton, Preserve compatible weights, and Keep facial/corrective
morph targets; all start enabled. A compatible embedded rig can be used when the
skeleton option is off; weight preservation off transfers every vertex instead.

The GPU morph codec preserves target identities, remaps per-vertex deltas and
updates cooked CPU metadata for every rebuilt LOD. Unchanged vertex bindings
retain their original data; new geometry receives nearest-surface interpolation.
Saved rest coordinates and vertex/LOD identifiers keep morphs attached when the
mesh is sculpted or decimated later. UVs and normals disambiguate coincident points.
Sparse GLB targets preserve morphs in replacement previews. Independent CUE4Parse
decoding, native import-option tests and a cooked-mod extraction verify the data;
game runtime facial performance remains an in-game validation step.

Revert to original restores saved content without removing the edit-list entry or
changing export selection. Reverted unchanged models stage the original cooked
bytes. Newly available texture mips are refreshed automatically; unpainted areas
receive full-resolution source pixels, painted RGBA values survive, and the old
PNG is backed up under .atelier/texture-backups. A missing baseline or concurrent
external edit leaves the saved file intact.

Focused browser and native WebView2 checks cover these additions. Native format,
texture-recovery and mod round-trip evidence is kept outside the distributable
under D:/AtelierDev/viewer-followups-20261016. All tests use isolated projects and
export directories; game runtime fidelity still requires an in-game check.
