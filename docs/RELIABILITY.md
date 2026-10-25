# Phases 0–1: reliability changes

Baseline: commit `2a3f4e2`; implementation branch: `codex/phase-0-1-reliability`.

## Environment and baseline

- Python 3.12.14 in `.venv`, pinned runtime/dev dependencies, Chromium and a reproducible native-tool installer.
- Isolated runtime directory and launcher; no changes to the existing installation, user projects or live game mods.
- Original automated baseline: **136 passed, 2 failed, 2 skipped**. Both failures came from test doubles that accidentally invoked absent native tools. The tests now mock the missing texture-size lookup and Windows extraction fallback explicitly.
- Current backend suites: **138 existing checks passed, 26 new failure/concurrency tests passed, 2 native-dependent legacy checks skipped**.
- Chromium smoke: **9 checks passed**, including configured startup with an unavailable remote key service and the optional real-GLB render/disposal test. No uncaught page errors. Desktop-sized screenshots retained locally.
- Real BC7 texture import/edit/build/install/readback passed with format and dimensions preserved. Test installation hashes match exports. AtelierMesh produced a valid 15,713,244-byte GLB from a real game mesh.
- Native WebView2 loaded the real asset browser (69 root entries), active project and viewport module. PyInstaller compilation/package collection passed.

## Changes to review

| Area | Problem and resulting behavior |
| --- | --- |
| Project ownership | Requests and background imports used a changing global active project. A context now pins each operation to its originating directory. The frontend sends that identity, including delayed selection writes and viewport requests. |
| Conflicting operations | Rename, delete and reset could invalidate running work. Process-local reservations reject these conflicts; project writes are serialized. Bulk-import admission claims the job before starting its worker. Multi-project archives acquire locks in a stable order and use independent output directories. |
| Paths | Project and asset path validation rejects traversal, invalid names and project directories resolving outside their root. Legacy flat project files still load alongside the nested layout. |
| Imports | Removed an undefined `cache_entries` reference after extraction. Missing decoded textures now report partial failure instead of success. |
| CLI | Fixed the undefined import-completion count. CLI exports retain overwrite confirmation and use the same protected build path; build failure now reaches the existing CLI error handler. |
| Sidecars/configuration | Edited material, curve, VFX/MPC, text and world JSON uses same-directory atomic replacement. Configuration setters use the shared locked writer instead of independent read/modify/write cycles. |
| Builds | Each build uses a private workspace. A process-wide build lock protects legacy helpers that still share scratch files. Previous exports survive staging/packing/validation failures. |
| Publication/install | Require nonempty `.pak/.ucas/.utoc`, stage and hash-check copies, back up replaced files, and roll back the set on failure. Return the exact artifact manifest so world-only and unmerged multi-container builds install all actual outputs. |
| Recovery | A durable publication journal permits recovery on the **next publication to the same destination** after interruption. If rollback is blocked, backups/journal remain with a diagnostic path; they are not silently deleted. |
| World compatibility | The known-damaging world round-trip fallback is disabled by default. Unsupported in-place edits report failure/skips. Advanced callers can explicitly request the existing unsafe fallback. Colliding world output names are rejected before staging. |
| Save feedback | Export success and installation failure are distinguished. Failed viewport saves retain drafts; successful saves clear only submitted values that were not edited again while waiting. |
| Preview lifecycle | Generation guards reject obsolete mesh/material/texture responses. Unsaved recolors prompt before leaving, saves block premature close, live dye textures are disposed, idle cached textures are bounded, and closing releases skeleton bone textures and stops animation. The real-model test caught and verified the skeleton-texture leak. |
| Frontend concurrency | Grid/sidebar responses from obsolete requests are ignored. SSE uses one EventSource and its built-in reconnect; reconnect reconciles import status. |
| Startup | Configured launches no longer wait for remote AES/mapping downloads. Initial setup still downloads them, and the browser's AES request has a timeout. |

## Compatibility

No framework migration, project schema migration, container-format rewrite, theme change or visual redesign is included.

Existing Python handler signatures and routes remain usable. Optional additions:

- `X-Atelier-Project`: URL-encoded project name; empty means the legacy import directory. Requests without it retain active-project behavior. Image-loader URLs can use `_project` instead.
- Missing explicitly named projects return an error instead of falling back to another project. Conflicting destructive operations return HTTP 409.
- Successful builds include `artifacts`, preserving existing `pak` and `world_mods`. Install responses preserve existing fields and include `built` when export succeeded but installation failed.
- `allow_unsafe_world` is an explicit opt-in for the old world fallback. The normal UI does not enable it.
- `ATELIER_DATA_DIR` is optional; absence preserves installed paths.

## Practical limits and next work

- Reservations, write locks and publication locks coordinate **one Python process**. Use separate data directories for multiple instances. Cross-process locks and a persistent job manager belong in the architecture phase.
- A three-file mod cannot be replaced as one atomic filesystem object. Rollback handles ordinary errors; interruption recovery runs on the next publication, not automatically before the game starts. Do not treat this as a fully transactional filesystem or publish while the game is reading the same mod.
- Files modified externally by Photoshop/Blender are not locked by these guards. Save the editor before exporting. PNG replacement, repatching, shader background jobs and graceful shutdown deserve additional transactional/lifecycle work.
- Independent archive outputs are retained under the cache; add managed retention with a future job/artifact service.
- Native checks cover a small BC7 texture and one skeletal mesh. The two skipped legacy native cases, full material/chroma fidelity, world edits, Blender rebuilds, password protection and repatching still need dedicated real-asset fixtures and manual/in-game validation before release.
- Existing source-string tests remain in the legacy suites. New reliability tests assert filesystem effects, concurrent-operation behavior, actual HTTP responses, browser state and GPU resource counts.
- The UI remains the baseline design. Material 3 tokens, typography, light/dark themes, components, navigation and expressive motion can now be introduced in reviewable later phases against these checks.
## Submission follow-up: thumbnail and Windows path races

Thumbnail status rechecks the file when a worker reaches `ready` between the
initial file lookup and state read. It cannot report a newly published preview as
missing solely because those observations straddled publication. A deterministic
test covers that ordering.

On Windows, `realpath()` can retain an extended-length `\\?\` prefix on only one
path during concurrent directory creation. Project containment compares equivalent
drive and UNC spellings consistently while preserving the original resolved paths
for file I/O. Different drives, shares, outside directories and device namespaces
remain rejected. Regression cases cover both accepted and rejected spellings.

## Managed work and reviewed bulk saves (15 October 2026)

`atelier/jobs.py` now owns the current UI's import/export/repatch and bulk jobs.
Jobs reserve their originating project through cleanup, persist status/results,
cancel owned native calls, stop admission during shutdown and protect the final
publication step from cancellation. Startup marks unfinished jobs interrupted
and recovers configured publication destinations. No automatic retry runs.

`atelier/bulk.py` previews in temporary project copies and compares content hashes
before a save. Project-local transaction journals restore every previous JSON
byte on failure, including metadata; interrupted batches recover before project
access. Native import decoding publishes only validated complete PNGs and retains
existing painted textures on retry. `tests/test_jobs_bulk.py` covers cancellation,
queued ownership, restart recovery, protected publication, stale previews,
failure rollback, scalar/color curves, MPCs and Niagara groups.

The real native material/dye check also fixed serialization of formerly omitted
zero parameters. The native curve/MPC/Niagara check verifies the new bulk edits
through packing and readback. See the final section in `DEVELOPMENT.md` for paths,
commands and current evidence. Shader appearance still needs an in-game check;
cross-process locks, unmanaged shader work and a new installer remain separate.
