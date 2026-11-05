# Spike 1: live recolour speed and fidelity

Oct 29, 2026 · Phase 0 of [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md)

**Question:** can the workspace's "click a colour, see it on the character" run on today's live
dye path (`dyeRebakeMesh` → `/api/dye_preview` → `dye.composite`), and does it match the game?

**Answer:** not at the plan's bar. A warm click takes about **500–550 ms** to reach the model,
against a 400 ms target, and almost all of it is the CPU composite. Fidelity is still unverified
beyond the one skin it was tuned on. The spike also found three faults in how materials are read
(see "Dye reads"). One may mean saved material edits are silently dropped. With a trusted reader,
28% of skins dye.

## Setup

- Ryzen 9 3900X (24 threads), RTX 2080 SUPER, Windows 11, installed Marvel Rivals paks.
- Repo code at `92e2592` plus the uncommitted Projects work, dev data `%USERPROFILE%\AtelierDev\default`.
- Materials: Coastal Kumiho (`1060300`) `MI_10600_1060300_Equip_01`, `_02` and `_03`, the skin the
  composite was tuned on. 2048² ColorID masks and diffuses, baked at 1024 as the viewport does.
  (The first scan suggested Kumiho was the only dyeable skin. The dye-read investigation below
  shows that was a reader fault: 186 skins dye.)
- Game build `1.1.3984769` (patched today at 14:10 UTC); mapping file `3962284`.
- Colours: the prototype's Smalt set across every region the mask uses. Medians of 8 runs.
- Scripts and output images are kept outside the repo; the numbers below are their output.

## Results

### One material, warm

| Material | Regions | Server bake | of which composite | PNG encode | Browser decode + upload |
|---|---|---|---|---|---|
| Equip_01 | 5 | 363 ms | 290 ms | 68 ms | 10 ms |
| Equip_02 | 1 | 365 ms | 305 ms | 59 ms | 9 ms |
| Equip_03 | 6 | 318 ms | 230 ms | 85 ms | 14 ms |

A single area costs the same as a whole set: the composite always re-runs the full texture.

**Click to colour on the model ≈ 160 ms debounce + 320–365 ms bake + transfer + ~10 ms decode
≈ 500–550 ms.**

### Several materials at once

A set on a part spanning three materials fires three bakes. Run together they finish in
**398 ms wall** (each 374–398 ms) against 1,069 ms one after another: numpy releases the GIL, so
multi-material parts cost little more than one.

### Cold

| Step | First material | Later materials |
|---|---|---|
| Read parameters (native reader) | 2.6 s (mounts the reader once) | 40–50 ms |
| Decode mask + diffuse | 4.1 s | 0.36–0.45 s |

The first open pays about 7 s. Selecting a part later pays about 0.4 s per material for its decode.

### What would help, measured

| Change | Saves |
|---|---|
| Prepare the 1024 sources once instead of per bake | ~40 ms (composite 290 → 249 ms) |
| Fast PNG compression (`compress_level=1`) | ~35–45 ms, files ~1.4× larger |
| Skip the 160 ms debounce for discrete clicks (sets, swatches) | 160 ms |

Together that gives an estimated **≈ 300–330 ms** for a set click, under the bar on this CPU.
That is the sum of the parts above, not an end-to-end measurement through the server. Dragging a
colour picker still re-bakes at 3 Hz at best.

## Findings

1. **Speed.** Fails the 400 ms bar as shipped; passes it with the three changes above for clicks,
   which is all the workspace's editor needs (sets and swatches, no drag). A three.js shader port
   of `composite()` would make it per-frame and is still the right end state, but it is no longer
   a prerequisite. The halftone reveal covers what remains.
2. **Fidelity is unverified.** `composite()` is empirically tuned (Kumiho only; the shader's
   colour chain is not reversed, see its comments). The bakes look coherent: shading survives,
   region edges are clean, ColorA→ColorB blends follow the mask. Whether they match the game can
   only be checked in-game, and that check has not been run.
3. **Dye detection was unreliable; the causes are below** ("Dye reads"). The first version of this
   report blamed a saved project copy and suggested almost no skins dye. Both conclusions came
   from faults in the reads, one of them caused by this spike's own probe.
4. **About a quarter of skins dye.** With a trusted reader, 186 of 674 skins (28%) have a dyeable
   `Equip_01`. In a whole-costume sample (every 12th skin), 25 of 62 costumes (40%) have at least
   one dyeable material, which is 106 of 846 materials (13%). A colour editor built only on dye
   regions covers a minority of costumes, and only some materials within those.
5. **Storm's default costume is not a dye skin.** `MI_1015001_Body` has BaseColor, Normal, ORM and
   Emissive but no DyeingTexture or Region parameters. The prototype's recolour journey would run
   on texture edits or tints for Storm, not on dye regions.

## Pass / fail against the plan

| Bar | Result |
|---|---|
| A set lands in ≤ 400 ms warm | **Fail as shipped** (500–550 ms); **pass with fixes** (~300–330 ms, clicks) |
| Matches in-game colours on three skins | **Not tested**: timed on one skin; in-game check pending |

## Dye reads

Why dye detection failed, found after the first write-up.

### A. The native reader comes up good or bad per process, silently

**Resolved (Nov 5): tied patch priorities.** CUE4Parse assigned both
`Patch_-Windows_1.1.3962284_P.utoc` and `Patch_-Windows_1.1.3984769_P.utoc`
priority 103. Concurrent mounting randomly selected the older material; decoding
its `BasePropertyOverrides` with the current mapping failed, leaving the typed
parameter arrays empty. The same Cosmic Kumiho lobby material returned no
parameters in two of four fresh installed-reader processes, and 7 textures / 9
colours in the other two. `GameProvider.Open` now rebuilds the file and package-ID
indexes from one deterministically ordered container selection before decoding.
Six fresh patched processes returned identical complete reads for both outfit
and head materials; the real lobby preview regained its body/outfit textures.
`tests/native_material_stability.py` repeats this check without touching projects
or installed caches. A separate isolated import/replace/reopen check retained the
edited PNG bytes and the actual model texture through two reopens.

The same read of `MI_1039507_Equip_01`, in eight identical fresh processes, returned 7 textures and
50 colours five times, and nothing three times. Within one process the outcome holds for every
affected material, and the tool writes nothing to stderr. It is decided when the reader starts.

- **Effect in the app:** `import_server.material()` writes each result to the on-disk cache keyed
  by the game build. One bad start therefore leaves empty materials cached (no textures, no
  colours, no dye) for those skins until the next game update. The viewport, Assembly and the
  material editor would all show those skins as unpainted.
- **Ruled out:** the mapping file. Good starts read fully with the same `3962284` mapping that bad
  starts use.
- **Leading suspect, unproven:** container registration. `GameProvider.Open` registers every
  `.pak` and `.utoc` in the Paks folder, and Python's index covers only `.utoc`. If a package is in
  more than one container, which copy wins could vary per start. Confirming this needs logging in
  `AtelierNative`.
- **Fixed in part (Oct 29):** `import_server.material()` no longer publishes a read that has a
  parent but no textures and no colours. It holds that read in memory for the reader process that
  produced it, so the next process reads it again, and an empty entry left by an older version is
  read again too. On installed files, the 47 empty children read empty again and none was written
  to the cache. A bad start still shows those materials empty for the rest of that session.
- **Not done:** a canary check after the reader starts. Restarting the reader without a known-good
  reference does not improve the odds (3 in 8 starts are bad either way), and a hard-coded canary
  asset can vanish in a game update. The real fix is the root cause, which needs logging in
  `AtelierNative`.

### B. UAssetTool cannot decode these materials at all

`to_json` on a cooked material returns a `RawExport` with no properties, with every mapping file
on disk (`3922109`, `3939753`, `3962284`). It warns that the referenced parent and textures aren't
on disk, then falls back without decoding. This JSON is what Atelier uses whenever a project copy
of a material exists:

- `read_material` on a project copy sees no colours, textures or dye. A project copy is created
  by any non-viewport `read_material()`, which is how this spike's probe wrote three copies into
  the dev project `yo`.
- `save_material` applies edits to that JSON. With no parameter list, colour edits are dropped
  and nothing reports an error. This follows from the code; a save was not run.

Whether UAssetTool decoded these before today's game patch is unknown: no older UAssetTool
material JSON survives in this data to compare.

**Checked (Nov 2): the mapping was out of date.** The patch moved the game to build 3984769, and
the matching mapping arrived on Oct 30 at 23:01, after this spike. Decoding `MI_1031306_Equip_01`
and `MI_1015001_Body` with each mapping on disk gives a `RawExport` (a 205–208 KB byte blob) for
3922109, 3939753 and 3962284, and a `NormalExport` with every parameter list for 3984769. With the
current mapping, a real `save_material` on both (BaseTint set to 0.16, 0.61, 0.37) reopened with
the new colour in a fresh project.

So saving is not broken today, but it breaks silently after every game update until a new mapping
is downloaded and Atelier restarts, which can take days: the update check runs every three days,
and a downloaded mapping applies only at the next launch. In that gap `save_material` wrote the
blob back and reported success, export failed with "Current material no longer has saved
parameters", and an undecoded project copy shipped vanilla colours. The installed app's 64 project
materials and 117 cached ones are all decoded, so none were damaged here.

Fixed the same day: `material.py` refuses an undecoded material on read, save and export with a
message naming the out-of-date mapping, and never publishes one to a project or the cache. Copies
that earlier versions wrote that way hold no edits, so they are read again from the game, unless
they record a replacement donor or parent, which still refuse. The viewport's save toast now
gives the reason instead of "retry Save". Still open: nothing compares the mapping's build with
the game's (the container names carry it, `Patch_-Windows_1.1.3984769_P.utoc`), so the gap is
found only when a read fails.

### C. Child materials inherit everything, but not dye

47 skins' `Equip_01` read empty even on a good reader. Each has another material instance as its
parent (`MI_1011001_1011_Equip_01`, `MI_1018001_Equip_01`, …) and overrides nothing. `dye_slots`
read only the material's own textures, so a child of a dyeing parent would never count as dyeable.

Following the chain showed that this never happens in the current game files. None of the 47
parent chains contains a dye mask: each ends at a plain body shader (`M_Common_Body` for 14 of
them). Across 1,525 sampled character material instances (every sixth of 9,147), no material takes
its mask from a parent, and no dyeing material inherits a Region colour. **Dye coverage stays at
186 of 674 skins.**

A parent-following dye check was built and tested (the nearest material that sets each slot or
colour wins; inherited values previewed only), then removed: it cost extra parent reads when a
material first opens, for no gain on today's files. `dye_slots` and `dye_regions` still read only
the material itself. If a game update starts putting dye masks on parent instances, the check is
worth bringing back.

### Housekeeping done during the investigation

- Removed the three material copies this spike's probe wrote into the dev project `yo` today. The
  project is back to only its `project.json`.
- Removed 715 empty native-cache entries written today by the spike's scans. No empty entries
  from before today existed.
- Both are backed up in the session's scratch folder.

## Next

- A is resolved (Nov 5): deterministic native patch selection; see the reproduction and
  regression check above. B is checked (Nov 2): an out-of-date mapping, now refused
  instead of dropped; see B above.
- Then make the three speed changes in `viewport.js` and `dye.py`. Small effort.
- Run the in-game fidelity check: install a Kumiho recolour, capture the same three materials in
  game and compare against the bakes. It needs the game, so it is the owner's step.
- Decide the guided recolour's hero by coverage. Storm only works there if non-dye recolouring
  (tints or texture edits) is in scope.
