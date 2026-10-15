# Atelier active-backlog code audit — 15 October 2026

Companion to the [source catalogue](triage-catalogue-2026-10-15.md). Scope: all 24 proposals shown by the source board’s Open filter. The initial audit was read-only. The implementation follow-up below records the subsequently requested fixes for #39, #41 and the missing-base failure in #45.

**Latest status:** #39 now rejects incomplete installer tool bundles; #41 rebases saved parameters onto current vanilla package data; #45 recovers missing texture bases. Changes and verification are in the separate `Atelier-triage-fixes` worktree on `codex/triage-export-packaging-fixes`, based on `7ec32d1`. Existing GUI work in the original checkout was preserved. See [Implementation follow-up](#implementation-follow-up).

## Baseline and method

Inspected local working tree at HEAD `7ec32d19a9adea61cb728c32f16b9a15d041fa40` (`Add recoverable jobs, bulk VFX editing and native export checks`). Existing uncommitted GUI and test changes were present before this audit and are included in the inspected code; they were left intact. This is a working-tree audit, not an assertion about upstream main or a shipped installer.

Read handlers, API routes, UI, build scripts, tests and local development notes. Searches for missing features were scoped to application code and user-facing documentation; absence in those locations is not proof about external services. No browser interaction, current game extraction, installer execution, Linux binary inspection, in-game validation or external communication was performed. No network refresh was needed to assess local code. Source claims about current mod prerequisites and external services were not independently validated.

## Initial findings for every active item

| # | Current assessment | Code evidence and limits | Next verification/action |
|---|---|---|---|
|39|**Claimed fix absent from this checkout**|`scripts/stage_tools.py` does not exist. `BUILD.bat:27` runs PyInstaller, then line 30 copies Tools with xcopy without checking the copy result or requiring UAssetTool/AtelierMesh. `Atelier.iss:43` recursively includes whatever dist contains. Claimed commits `a712532` and `4f2e007` cannot be resolved in this local object database. `scripts/package_release.py:1` describes a separate contributor review package that intentionally excludes tools; that exclusion is not the installer bug.|Do not assume releasing this checkout delivers the source board’s fix. Require tool presence/completeness in the official staging path; inspect an actual installer and clean-install it. No shipped installer was examined here.|
|40|**Unresolved; thumbnail-path gap identified, white-box cause unproven**|`atelier/handlers/pak_thumb.py:10` lists only Marvel/Marvel_LQ content roots; `_path_to_gr` at line 30 does not map plugin mounts. However `atelier/web/routes.py:1300` falls back from direct pak thumbnails to cached/native extraction, so this alone does not establish a user-visible failure. Texture staging uses the shared mount-aware `pak_game_path` (`atelier/paths.py:36`).|Compare vanilla and exported Luna/Thor icons, including alpha/format/path. Test plugin fallback separately from exported white pixels.|
|41|**Code supports stale-project-material diagnosis**|`material.py:95` gives project JSON priority. `stage_material` at line 199 calls that reader, applies color/scalar values to the returned full document and serializes it. It does not fetch fresh vanilla first. `read_material_original` at line 139 is separate and is not called by export. The new original-comparison feature therefore does not resolve this issue.|Reproduce with an old project and changed vanilla schema, then rebase authored values onto current vanilla with explicit missing-parameter handling. Do not blindly copy repatcher calls: it also calls `stage_material`, and freshness depends on its surrounding context/cache.|
|45|**Failure mechanism still exists; reporter case unconfirmed**|`texture.py:824` (`stage_inject`) looks for a cached/extracted base and raises “no base asset — run 'import' first” when missing; it does not call `ensure_work_base` to recover. `_build_mod_impl` around line 1000 catches per-texture failures and records skips while other assets can build. Unlike an entirely silent failure, `routes.py:2372` returns applied/skipped details and `gui/export-review.js` displays results.|Get reporter logs to establish causality. Exercise a texture-plus-material project after clearing only disposable work cache; verify skipped output and recovery.|
|29|**Requested prerequisite copy not found**|Export review (`gui/export-review.js:70`), export sidebar (`gui/index.html:94`) and README Usage explain destination/install controls, but no user-facing UTOC bypass/Project Galacta prerequisite copy was found. Internal Galacta-related index handling would not satisfy export-screen documentation.|Verify supported loading requirements before adding exact guidance. The board’s dated ban-wave statements are unverified source context.|
|30|**Requested guide link not found**|`README.md` Installation/Help and the application HTML/JS do not expose the named Master Class link. Mentions in `retrieval/ANALYSIS.md` are analysis notes, not product help.|Obtain/validate the intended public guide URL and add a clear help entry.|
|28|**External process status cannot be established from code**|No canonical bug-report destination was found in README Help. Code cannot establish whether an MRM operator created a channel or pinned a post.|Check the actual community destination; no messages were sent.|
|42|**Unresolved; code does not establish brightness cause**|`texture.py:870` sends the base asset and authored DDS/PNG to `inject_texture`; this call adds mip options but no explicit sRGB override. `texture_props` around line 695 can read SRGB, so “no sRGB handling anywhere” would be too broad. `routes.py:2205` converts replacement uploads to RGBA PNG. Neither observation proves a gamma/colour-management defect.|Perform an unchanged vanilla round trip, compare decoded pixels plus SRGB/compression metadata, then compare in game. Separate upload conversion, decode and injection.|
|43|**Portability risk remains; exact glibc requirement unverified**|`linux/build_appimage.sh:30` uses the host `.venv/bin/python` and later copies local native Tools. It does not enforce an older distribution/container or inspect symbol versions. An AppImage wrapper does not itself establish compatibility.|Inspect GLIBC symbol requirements in the actual executable, Python runtime and native tools; test a supported older distro. Do not treat reported glibc 2.44 as measured here.|
|44|**Specific Maker-form defect unconfirmed**|`atelier/paths.py:36` resolves mount-aware pak paths, and material/texture staging both use that shared function. No Maker-specific three-form packing branch was identified. General correct-path code does not rule out bad input identity or a particular asset layout.|Obtain the exact project/pak and expected three paths; compare exported directory index against vanilla.|
|13|**Implemented locally; source board is stale**|`atelier/bulk.py:153` previews edits across curves, MPCs and Niagara groups using scratch project data; `apply` validates project/expiry and publishes a conflict-checked batch. Routes are `routes.py:161` and `:171`; UI entry is `gui/index.html:94` and `gui/bulk-edit.js`. README Usage and TRIAGE.md already describe it. Focused jobs/bulk tests pass in this audit.|Mark implemented for this checkout. Existing DEVELOPMENT.md native-export claims were read, not rerun; in-game appearance remains separate. Bulk editing regular MI instances is not implied.|
|46|**Manual option exists; requested UI default absent**|`texture.py:872` adds `--no-mips` only for a truthy saved option. `gui/app.js:3291` initializes `no_mips: false`; routes validate the explicit option (`routes.py:2618`). No automatic UI-texture default was found.|Define reliable UI classification and preserve explicit user choices before changing defaults.|
|47|**MI_Hide workflow not found**|Material editor backend (`material.py:77`, `:184`) updates existing vector/scalar parameters. Texture blanking (`texture.py:794`, `:843`) emits transparent pixels and warns about formats without alpha. No MI_Hide reference-replacement operation was found.|Investigate mesh material-slot/reference substitution using real assets; distinguish it from blanking or deleting a project edit.|
|31|**Substantially implemented; download-location limitation remains**|`gui/export-review.js:112` shows exported pak and installed directory. `gui/app.js:2262` reports those destinations; `routes.py:2477` exposes opening the export folder. Dyed downloads use browser attachments (`routes.py:538`, `gui/app.js:979`), showing a filename rather than an absolute browser-chosen save path.|Update the mod-export portion of the board. Browser download destination is controlled by the browser; verify actual download UX separately.|
|32|**Requested approximation label not found**|`dye.py:26` still sets `DYE_BASE = 0.35`; composite comments explain the stand-in/heuristics. No corresponding approximation label was found in `gui/index.html`, `gui/app.js` or the dye UI code.|Add concise preview copy; do not imply the shader has been reproduced exactly.|
|33|**External follow-up unverified**|Historical cartbuddy discussion exists in `retrieval/ANALYSIS.md`, including the unanswered follow-up. It is not proof of present contact or repro review, and no specific supplied repro ZIP was identified by this audit.|Locate the actual ZIP and later correspondence before assigning current status. No reply was sent.|
|36|**Partial: real native checks now exist; broad suite still missing**|`tests/native_smoke.py:1` performs real extraction, pixel modification, injection/build, IoStore parsing, unpack/decode and format/dimension checks on `UI/Textures/img_empty`. `tests/native_material_dye.py` and `tests/native_bulk_smoke.py` extend native coverage. Thus “nothing runs a real inject” is outdated. This is not a cross-character texture-path matrix, and the generic phase-4 runner still skips native tests without tools.|Keep the cross-character/path suite open, but narrow its wording. Review/run opt-in native checks with isolated data when required; not executed here.|
|24|**Requested cross-instance copy workflow not found**|`material.py:77` applies values only to parameters already present in the target document. The UI’s saved/original comparison copies data internally, but no source-instance→target-instance copy operation or parameter creation flow was found.|Specify matching-name/type policy and whether absent overrides should be created; compare a real source/target pair.|
|25|**Requested colour-grading LUT preview not found**|`dye.py` composites diffuse/region colours with heuristics. Niagara LUT editing in `vfx.py` and `bulk.py` concerns sampled effect curves, not colour-grading LUTs for the recolour preview.|Identify actual LUT assets and shader transform before implementation; avoid equating the two LUT uses.|
|26|**Dedicated audio modding workflow not found**|Reviewed handler inventory, browse dispatch and export item routing (`routes.py:2300`); supported export families are textures/materials/curves/VFX/world/text/meshes. No dedicated audio handler/editor/export path was identified.|Treat as an unimplemented subsystem; confirm asset formats and native tool support.|
|27|**Dedicated KO prompt workflow not found; asset compatibility unknown**|`vfx.py:24` recognizes specific name prefixes and edits Niagara curve/LUT content, not arbitrary prompt assets. No dedicated KO editor/routing was found. A visible browse path alone does not establish edit support.|Obtain the exact KO asset path/class and determine which references/data need editing.|
|48|**New named texture creation workflow not found**|`routes.py:2205` only replaces a PNG for an already imported asset. `texture.py:824` requires a vanilla base and stages to the resolved existing game path; no rename/new-package/reference rewrite UI was found.|New variants require valid package identity and material references, not only renaming a PNG. Validate on an isolated fixture.|
|49|**Ambiguous scope; generic previews exist, combined preview not established**|Generic thumbnails accept texture game paths through `routes.py:1300`; no hair/iris exclusion is evident there. Dye preview uses only mask/diffuse slots (`dye.py:59`) rather than composing a full material/character. `material.py:49` resolves texture parameters for supported /Game/Marvel imports. No dedicated hair/iris composite feature was found.|Clarify whether the report concerns missing individual thumbnails, slot resolution, or inclusion in the dye composite; test named hair/iris assets before declaring the generic preview feature absent.|

## Verification performed now

Command, run with local Python 3.12.14 on Windows, using the repository’s disposable-copy test runner:

```powershell
.\.venv\Scripts\python.exe tests/run_checks.py --suite test_jobs_bulk.py --suite test_phase4.py --suite test_material_original.py --report-dir _work/triage-audit-2026-10-15
```

- `test_jobs_bulk.py`: 23 tests passed.
- `test_phase4.py`: 46 passed, 0 failed, 2 skipped (UAssetTool not installed in the disposable test environment).
- `test_material_original.py`: 8 tests passed.
- Total: **77 passed, 2 skipped**. Logs and machine-readable summary: `_work/triage-audit-2026-10-15/`.

These tests exercise batch safety, texture-option behaviour and original-material reading; they do not reproduce white icons, brightness, old-project patch migration, Maker paths or Linux compatibility. DEVELOPMENT.md’s earlier native/UI reports are historical local documentation, not fresh results from this audit.

## Initial recommended board corrections

1. Mark #13 implemented for this checkout, with in-game appearance outside the verified scope.
2. Mark #31’s exported-mod destination implemented; retain any distinct browser-download UX work.
3. Rewrite #36 to request cross-character real-tool path coverage; acknowledge existing opt-in native tests.
4. Do not carry #39’s fixed-on-main status into this fork without the missing staging fix. The two claimed commits are not available locally; this says nothing definitive about the remote repository.
5. Keep #41 open with a code-supported diagnosis. Keep #45 open pending logs, noting the surviving missing-base path and improved skip reporting.
6. Clarify #49 before assigning implementation effort: individual thumbnails and a combined dye preview are different requests.

No source-board statuses were silently overwritten. The catalogue retains the supplied snapshot; this document records differences found in the current working tree.

## Implementation follow-up

Implemented on 15 October 2026 after the initial audit, on branch `codex/triage-export-packaging-fixes` in the sibling worktree `Atelier-triage-fixes`. This section supersedes the initial findings for #39, #41 and the missing-base portion of #45. It does not confirm the individual reporters’ cases or change the source snapshot.

### #39 — incomplete installer tools

- `scripts/stage_tools.py` validates nonempty `UAssetTool.exe`, `AtelierMesh/AtelierMesh.exe`, `CUE4Parse-Natives.dll` and `oo2core_9_win64.dll` before and after copying. Failed copying removes only the new staging tree. Existing or overlapping destinations are rejected.
- `BUILD.bat` invokes that helper and stops on failure before calling Inno Setup. Direct `Atelier.iss` compilation also has required-file guards.
- Staging excludes mappings, AES keys, caches and the Linux binaries previously stripped by the batch file. Contributor review ZIPs continue to intentionally exclude tools.
- Verified the actual Windows batch’s failure gate in a disposable fixture, with only PyInstaller replaced by a fixture module. Verified every required-file omission, empty binary, copy failure and destination/source preservation.
- Successfully staged the real development Tools directory into `D:/AtelierDev/triage-fixes-20261015-tools`; confirmed required files, source/staged UAssetTool and AtelierMesh executable SHA-256 equality, and absence of `AES_KEY.txt`/Mappings.
- **Not verified:** a newly compiled Inno installer or clean installation. Inno Setup’s compiler is unavailable on this machine. Direct-compiler guards were inspected, not executed.

### #41 — old material JSON after a patch

- Export reads saved color/scalar values from the current or legacy project JSON, resolves the current vanilla base, and decodes it into a private temporary directory. It bypasses both project package metadata and the viewport JSON cache.
- Saved values are applied to the current package structure; explicit caller values take precedence. Newly added vanilla parameters retain their defaults. Removed saved parameter names produce an actionable item error instead of silently losing values.
- Compiled `.uasset` and companion files are published into the export stage together through the existing rollback/verification helper. Failed decoding/serialization does not stage a partial package or overwrite project JSON.
- Repatch explicitly opts out of inheriting the active project’s unrelated parameter values.
- Source cache entries now record `.utoc`/`.ucas` size and modification time. A changed source is refreshed even if its container filename stays the same; unverifiable older cache entries refresh once. This closes the remaining stale-base route beneath the fresh JSON conversion. Source fingerprints are metadata checks, not cryptographic content verification.
- Verified real native serialization and readback using `MI_1031306_Equip_01`: a deliberately stale import in isolated project JSON was absent from the rebuilt package; saved color/scalar values and current texture references survived; source JSON hash was unchanged.
- Legacy full-document projects do not identify which values differ from their original vanilla baseline. All saved scalar/vector values are therefore retained. Texture/reference editing is outside this parameter-rebase workflow.

### #45 — missing extracted texture base

- `stage_inject` now calls the shared `ensure_work_base` resolver, recovering from a deleted/missing extracted base and applying source/mip freshness checks. A genuine extraction failure uses `missing_reason` diagnostics.
- Authored project PNG/DDS files remain the injection source; recovery does not re-import or overwrite them. Existing per-item skip reporting remains intact if recovery fails.
- Fixtures cover missing bases with PNG and DDS, unavailable recovery, and a stale base whose container name did not change.
- A real native check imported and painted `UI/Textures/img_empty`, deleted only its report-local extracted base, exported it again, and decoded the staged asset. The base was recreated, painted pixel values/dimensions survived readback, and the authored PNG hash stayed unchanged.
- This fixes the identified missing-base code path. The original reporter’s missing-texture case remains unconfirmed without their logs.

### Fresh verification results

```powershell
# From the fixes worktree; Python is shared with the original checkout.
& '..\Atelier\.venv\Scripts\python.exe' tests/run_checks.py --report-dir _work/triage-fixes-verified
& '..\Atelier\.venv\Scripts\python.exe' tests/native_triage_exports.py `
  --tools-data-dir 'D:\AtelierDev\phase-0-1' `
  --report-dir 'D:\AtelierDev\triage-fixes-20261015-native-final'
```

- **246 backend checks passed, 0 failed, 2 skipped**, including 21 new triage checks. The two skips are the existing legacy native cases in the disposable-copy runner, which deliberately excludes real tools.
- Real native material-rebase and missing-texture-base checks **both passed**. Machine-readable result: `D:/AtelierDev/triage-fixes-20261015-native-final/results.json` (`ok: true`, `in_game_verified: false`). All test projects/caches/staged assets were new and report-local. No live mods were installed.
- The initial native run under the long OneDrive worktree path failed during extraction with a native “Could not find file” error. The successful checks used a short path under `D:/AtelierDev`. This remains a native path-length limitation, not a successful check at the long path.
- Full-suite source fingerprint validation exposed two obsolete fixtures: one demanded indefinite reuse of cache entries without provenance; the other returned a supposedly successful extracted base without recreating its file. The former now verifies a single legacy refresh plus subsequent cache reuse; the latter recreates the base while continuing to omit its optional top mip. Both pass with the existing patch/mip coverage.
- No in-game appearance, real historical-patch upgrade, new installer, Linux runtime or reporter-specific reproduction is claimed. Native checks establish the data paths and preserved source files described above.
