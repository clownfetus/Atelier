# Worktree consolidation and repository integrations — 20 October 2026

The working branch is `codex/consolidated-integrations`. Work was reviewed in
the requested priority order. Existing user changes in the asset pipeline were
preserved before integrations; no remote branch or release was published.

## Worktrees

Twelve registered worktrees became one active checkout. All eleven retired
directories were moved intact, including untracked and ignored files. Dirty
tracked/untracked source also has snapshot commits under
`codex/archive-20261020/*`; patches, file hashes and the original paths are in
`D:/AtelierDev/consolidation-20261020/manifest.json`.

- Former C: worktrees: `C:/Users/thiag/.codex/worktree-archive/atelier-20261020/`.
- Former D: worktrees: `D:/AtelierDev/consolidation-20261020/retired-worktrees/`.
- The appearance/Model Studio snapshots were compared using three-way merge
  previews. Their conflicting versions predate integrated catalogue, shader,
  attachment, loading and export repairs. Those later repairs were retained.
- Duplicate changelog sections and option constants in the snapshots were not
  reintroduced. The portrait double-click and icon sizing changes are already
  represented in the integrated checkout.
- `harden-local-api` was merged normally, bringing same-origin/loopback request
  checks, JSON mutation requirements and Blender executable validation.
- Local agent launch configuration remains outside committed source.

## Reviewed sources and resulting changes

These are focused integrations into Atelier's existing architecture. No whole
application or Unreal editor plugin was copied into Atelier. Except for the
explicitly vendored meshoptimizer module, implementations are local adaptations
of the reviewed behavior, formats and interfaces.

| Order | Source and inspected revision | License | Result |
| --- | --- | --- | --- |
| 1 | [RivalsPorting](https://github.com/Bmarquez1997/RivalsPorting/tree/8dab506d24fbc77b2c0ecceaacfb21795361bf98) | GPL-3.0 | Cache Blender images by full path and color space, avoiding duplicate shared data maps. Existing material-family mapping, rigs and portable scene assembly remain integrated. The upstream import HTTP server was not added. |
| 2 | [CUE4Parse](https://github.com/FabianFG/CUE4Parse/tree/54582177126a0acd6e2bee2aec21a721c02e897f) | Apache-2.0 | Decode independently sized 8/16-bit bone indices and weights, validate variable-influence lookup bounds, and retain the strongest eight influences. Rebuilding 16-bit source buffers is explicitly blocked. Existing native package/texture decoding keeps its compatible bundled assemblies. |
| 3 | [UAssetToolRivals](https://github.com/X-zant/UAssetToolRivals/tree/deb6f32fef1fbc8d6b6cfd37588627d62ddb3bcf) | GPL-3.0 | Check JSON success and PNG integrity before atomic publication; preserve existing output on failure; expire metadata on companion changes; retain pooled workers, batch extraction and legacy fallback. The former XzantGaming URL has moved to X-zant. |
| 4 | [repak-rivals](https://github.com/natimerry/repak-rivals/tree/fd193f1922742686c2ceba495c6aa3db4b0ad63a), [retoc submodule](https://github.com/natimerry/retoc-rivals/tree/e6c985eac480275348976dcc6e8729c1de1bef40) | repak mixed MIT/Apache/GPL; inspected retoc MIT | Retain the FGameplayTagContainer name/index data in cooked mesh parsing, with bounded reads and valid FNames. Existing exact IoStore extraction, streamed LOD recovery and all-LOD hiding were checked. No replacement native binaries were downloaded. |
| 5 | [RivalsMeshMaterialManager](https://github.com/X-zant/RivalsMeshMaterialManager/tree/16279b825619b0dab6101be24a31492f75b4125f) | Apache-2.0 | Carry exact slot gameplay tags through preview bindings and portable Blender metadata. Per-LOD hidden defaults and dynamic gameplay tags were distinguished from the user's explicit all-LOD hide edit; tags do not automatically hide a part. The editor plugin was used as a format reference. |
| 6 | [FModel](https://github.com/4sval/FModel/tree/d132bc46e279f1bcb8e71737827c05e26f3f8707) | GPL-3.0 | Use one package-reference resolver for textures/materials; follow nested outer imports, retain live package records, reject cycles, invalid indices and traversal paths. |
| 7 | [UEFormat](https://github.com/h4lfheart/UEFormat/tree/d858fe38b2b5b8c63ac4b7481b4386ebfabbf935) | No root license found at inspected revision | Review only; no UEFormat source or runtime was copied. Independently repaired ActorX influence accumulation and normalization, applying the same needed behavior to the existing PSK importer. Existing UV, normal, color, rig and morph paths were tested. This does not add `.uemodel` support. |
| 8 | [meshoptimizer](https://github.com/zeux/meshoptimizer/tree/f0a684f11ead064e176775c9b796f82a55910e92) | MIT | Integrate the official checked WASM simplifier into lower-LOD builds, preserve retained vertex streams and boundaries, package its license and runtime, and provide a reproducible extraction script. |

## Visual cleanup

- Mod tray actions now occupy a padded group with aligned, centered buttons and
  enough room for their labels at the minimum tray width.
- The Continue card has vertical clearance from the heading divider, a stable
  thumbnail and action, and a full-width action on a narrow library pane.
- Controls and tray header/footer retain their height while content scrolls.
- Browser checks cover both themes, four card sizes, 900/1024/1400 pixel windows
  and 240/300/420 pixel trays. Screenshot artwork in these checks is synthetic.

## Safety and verification

Tests run in disposable application/project directories. Game packages and user
projects were not written. The native Blender fixture uses generated geometry.
The [machine-readable verification record](repository-integrations-2026-10-20-verification.json)
records the tested code commit, source digests and evidence locations.

- All 44 backend regression suites passed. Focused follow-ups also passed after
  the final texture staging repair and the two explicit safety regressions.
- The complete browser workflow suite passed in 285 seconds with no uncaught
  page errors. Both-theme compact-surface screenshots are under
  `D:/AtelierDev/consolidation-20261020/visual-verified/` and the full browser report.
- A packaged optimizer probe loaded its bundled Wasmtime DLL, verified the
  module digest and compiled the module successfully.
- A real cached game texture decoded identically through the pooled worker and
  one-shot fallback. Its copied input and original cached source stayed unchanged.
- All 284 saved files in the retired worktrees matched their backup digests;
  all eleven retired snapshots are ancestors of the integrated code history.

- Backend suites, browser workflows, request isolation, rollback, import identity,
  invalid buffers and project-collision tests are recorded under the external
  `checks-*` directories alongside the consolidation manifest.
- Real Blender import/export followed by meshoptimizer and cooked-buffer rebuild
  reduced each generated section from 1,058 to 422 triangles. Both UV channels,
  vertex colors, skin weights and morph tracking remained aligned.
- The WASM SHA-256 is enforced, its imports list is empty, and memory/fuel are
  bounded. See the vendored module's README for runtime-advisory applicability
  and the disabled GC/exception features. Dependency resolution passes.
- Archive directories and snapshot refs preserve the original work. Destructive
  reset/delete operations were exercised only against test fixtures.

In-game behavior, Linux native execution and a rebuilt installer are separate
verification steps; this work does not claim those checks. The all-suite results
also identify optional native tests skipped without installed game tools.
