# Assembly View: real-character verification

The Windows Chromium run passed all ten checks against installed Marvel Rivals
assets for Magik / Infernal Idol (`1029304`). Geometry, material, texture and
editor HTTP requests used the production native tools without fixtures.
Read-only browser hooks observed scene state and loader counts.

## What was verified

Mouse clicks selected exact decoded mesh primitives and triangles. Their material
paths matched the native cooked mesh slot metadata, and the displayed texture
slots matched the material bindings exactly:

| Material | Cooked slot | Clicked triangle | Bound texture slots |
| --- | ---: | ---: | ---: |
| `MI_1029304_10290_Weapon` | 0 | 3749 | 7 |
| `MI_1029304_10290_Hair_03` | 1 | 17483 | 6 |
| `MI_1029304_10290_Body` | 4 | 14264 | 4 |

Clicking the material swatch highlighted only its assigned sections. Clicking a
texture highlighted only materials referencing the same complete package path.
Actual texture thumbnails and the full texture preview loaded successfully.

After a real camera orbit, opening and closing the existing material editor kept
the exact selected triangle, material, texture, camera position, orbit target,
object visibility and loaded geometry. Saving `BaseTint` refreshed Assembly while
retaining that context. Assigning an authored 64×64 normal image through the real
material slot editor updated the selected slot and package reference; reading its
project preview returned the authored pixels. Only the original two model loads
occurred throughout the editor round trips. UV inspection used the same material.

With twelve surfaces at 1024×768, the geometry list scrolled independently and
all three geometry actions remained visible. There were no browser errors or
failed core asset requests. Game container sizes/timestamps stayed unchanged and
the test mods destination remained empty.

## Corrections and regression coverage

- Clear residual orbit inertia at editor handoff while retaining the exact pose;
  resumed rendering previously continued the pre-editor drag.
- Keep geometry actions separate from the scrolling surface list and collapse
  detailed geometry properties. Prevent the selection area shrinking below its
  actions at compact sizes.
- Give compact panel widths the same theme specificity as the workspace defaults.

The focused browser suite passed 18 checks, including deliberate orbit inertia,
editor and replacement handoffs, exact path relationships, both themes, compact
layout, reduced motion and switching back to Inspect/Showcase. The Assembly,
Model Studio, frontend and UV regression suites passed 37 tests after integration
with main's UV inspector safeguards.

## Evidence and limits

[The machine-readable receipt](assembly-verification-2026-10-22.json) contains
the exact references, triangles, final retained context and tested source hashes.
Local screenshots and detailed runtime observations are in
`D:/AtelierDev/assembly-view-20261022-a5a5ec/report-final`; focused browser and
regression reports are in the adjacent `browser-final-compact` and
`regressions-final` directories.

The active project was the isolated `Assembly Real Character Final`; the installed
application's project was not used. This verifies studio workflows for this
character. Animation checks used Rest pose because the existing standing-idle
compatibility check rejected this costume's skeleton. Native Blender execution,
VFX playback and in-game appearance were outside this run.

Native tool SHA-256:

```text
UAssetTool.exe d011149a2cef5541dd0795c20c335394b93bd87dc76d8a4617543ce5a5aa7dfe
texconv.exe   dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06
```
