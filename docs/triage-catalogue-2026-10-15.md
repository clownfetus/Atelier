# Atelier triage catalogue — 15 October 2026

Source: https://claude.ai/artifact/Ng5HzAGKBEbQP2yYMCXPbF

Transcribed from the user-supplied Chrome accessibility snapshot and screenshot, not a live browser sweep. The snapshot exposes full notes for 24 active proposals and titles/statuses for 25 closed proposals. Source claims are preserved here separately from the [current-code audit](triage-code-audit-2026-10-15.md).

The board cites 29,871 messages, 6 DMs and 2 user logs, cross-referenced against code, covering 20 March–15 October 2026. Mesh editing and 3D preview are excluded. Reports count distinct reports per proposal and overlap; do not sum them. There are 49 proposals, 25 closed, 7 active with high/critical value, 12 new since the prior sweep and 1 fixed on main awaiting release.

## Active proposals

Unless specified otherwise, source status is Open. “Active” includes fixed-on-main #39 and needs-logs #45.

| # | Proposal | Value | Effort | Reports |
|---|---|---|---|---:|
|39|Installer missing UAssetTool.exe and AtelierMesh — fixed on main|Critical|Trivial|5|
|40|Ability icons export as white boxes under Plugins|High|Small|3|
|41|Existing VFX projects retain stale material JSON after patches|High|Medium|1|
|45|Export contains materials but no textures — needs logs|High|Medium|1|
|29|Explain export prerequisites|High|Trivial|3|
|30|Link leagueofthearcane’s Master Class|High|Trivial|6|
|28|Establish a bug channel or pinned reporting post|High|Trivial|2|
|42|Exported textures appear brighter than vanilla|Medium|Medium|2|
|43|Linux build requires glibc 2.44|Medium|Small|1|
|44|Mr Fantastic Maker form packed into wrong folder|Medium|Small|1|
|13|Bulk curve / VFX editing|Medium|Medium|3|
|46|Default UI textures to NoMipMaps|Medium|Trivial|1|
|47|Hide an entire material part using MI_Hide|Medium|Medium|4|
|31|Show export/download destination|Medium|Trivial|3|
|32|Label dye preview as approximate|Medium|Trivial|1|
|33|Review cartbuddy’s reproduction ZIP and reply|Medium|Trivial|1|
|36|Real texture-injection and pak-path regression suite|Medium|Large|0|
|24|Copy material parameters to an instance|Low|Medium|2|
|25|LUT support for recolour preview|Low|Large|1|
|26|Audio modding|Low|Large|2|
|27|KO prompt modding|Low|Medium|1|
|48|Add textures with new names|Low|Small|1|
|49|Include hair and iris textures in previews|Low|Small|1|
|34|Publish a donation link|Low|Trivial|2|

### Source evidence and next steps

- **39:** Source says 0.3.4 is about 44 MB versus 0.3.3’s 490 MB, with no Tools folder. Five reporters. Claims `a712532` adds required-tool staging via `scripts/stage_tools.py`; unreleased.
- **40:** Luna/Thor icons reported white, slotted UI missing/stretched. Similar output reported from UE/FModel. Cause not investigated; compare exported icons against vanilla before assigning blame.
- **41:** Code-checked but not reproduced: project JSON is a full old material copy; `stage_material` calls `mat_json` and rebuilds that copy. Proposed remedy: apply saved edits to fresh vanilla, as `repatch.py` does.
- **42:** Unchanged vanilla diffuse reportedly looks brighter in game. Injection tool / PNG decode are hypotheses, not established causes.
- **43:** Fedora incompatibility inferred from a report and an Arch build environment. AppImage not inspected.
- **44:** Maker skin reportedly crashes; one of three forms appears outside its folder. Report only.
- **45:** Logs requested 1 October. Before claimed `a712532`, missing base assets caused skipped texture injection; symptom matches code but reporter case unconfirmed.
- **13:** Repeated request for bulk curve/VFX editing; original board says deliberately excluded from Phase 4.
- **24:** Copying parameters to an instance currently described as requiring Unreal.
- **25:** LUT recolour-preview support requested; related to dye/overlay subsystem.
- **26:** Audio subsystem requested twice.
- **27:** Level-1 KO path reportedly visible but cannot be opened by VFX editor.
- **46:** Request to default all UI textures to NoMipMaps, following the existing manual option.
- **47:** MI_Hide proposed for belts, hair layers and coats; texture blanking does not universally hide geometry. Report-only explanation.
- **48:** Additional named colour variants requested; source quotes maintainer as considering it feasible.
- **49:** Hair/iris preview requested alongside thumbnail fix #38.
- **29:** Source requests UTOC signature-bypass and Project Galacta prerequisites plus context around reported UI-mod risk. These are source claims, not independently verified current requirements.
- **30:** Link Master Class in README/first-run help.
- **31:** Show exported mod location and downloaded dyed texture location; source mentions users needing a cache path.
- **32:** Dye preview uses hardcoded `DYE_BASE = 0.35`; label its approximation.
- **28:** Reports dispersed across mod-help/setup channels; establish a reporting destination.
- **33:** Reproduction ZIP provided 12 September; noted again on 28 September.
- **34:** Publish a public donation link.
- **36:** Board says existing stage-injection tests fake UAssetTool; wants real injection and cross-character pak-path checks.

## Closed proposals

Only matrix metadata was exposed for these entries; full closed-item notes were not supplied.

| # | Proposal | Source status |
|---|---|---|
|1|Include AES key in index cache key|Done|
|2|Per-container keys through enc_guid|Superseded|
|3|Escape glob paths; support brackets in mod names|Done|
|4|Reject warned indexes from cache and show warnings|Done|
|5|Split “not found in game paks” into three states|Done|
|6|Add uat() and JSON-read timeouts|Done|
|7|Wrap _get_toc with exception handling|Done|
|8|Single writer for AES_KEY.txt; reload on change|Done|
|9|Report /api/open_explorer failures|Done|
|10|Verify shipped Marvel_LQ root|Answered|
|11|ID-mask / colour-region overlay|Done|
|12|Allow disabling chroma/dye overlay|Done|
|14|Surface all three nameplate paths|Done|
|15|Expose MarvelGAS ability-icon plugin path|Done|
|16|Project-screen search|Done|
|17|Persist hex / 255 / float preference|Done|
|18|Multi-select edited assets for deletion|Done|
|19|Add missing VFX recolour entries|Done|
|20|NoMipMaps / texture-group setting|Done|
|21|Automatically duplicate UI textures into Marvel_LQ|Done|
|22|Remove a texture|Done|
|23|Extend dyed-texture downloads to other texture types|Done|
|35|Test pak override order and differently keyed patches|Done|
|37|Invalidate work cache when HQ texture DLC changes|Done|
|38|Fix indefinitely loading preview thumbnails|Done|

## Page controls and limitations

Clickable value/effort matrix; status filters (Open, Closed, New since 09-18, All); category filters; title/file/note search; sorting by value, effort and reports. Behaviour was not exercised live.

Source says Done items were verified on Linux only, with outstanding Windows verification in LINUX.md. It claims phases 1–4 shipped in 0.3.4 and two Windows-only fixes were restored to main in `4f2e007`. These historical claims require repository/build evidence and are not treated as verified by this transcription.
