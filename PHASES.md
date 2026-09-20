# Atelier — phased plan

Derived from `retrieval/ANALYSIS.md`, ordered so the **first three phases need no in-game
testing**. You can reach real confidence on a dev machine, with the game closed, before you
spend a single round-trip checking whether a mod shows up or whether materials checkerboard.

Mesh editing, the 3D preview, and preview-fidelity work (LUTs, labelling the dye preview) are
out of scope and parked at the bottom.

Nothing here is *proven* without eventually testing in game. The point of the ordering is that
Phases 0–3 have a **local pass/fail you can see in the app itself**, so if a later phase forces
a pivot you'll have lost days, not weeks.

---

## A finding that changes the sequencing

Entering the correct AES key in Setup **cannot recover a broken install.** Not "is unreliable" —
cannot.

`routes.py:616` resets the in-memory index to force a rebuild:

```python
_idx._INDEX = None  # force re-index with new path
```

But `ensure_index()` (`index.py:64-72`) then reloads the **disk** cache, and its key
(`_utoc_key`, `index.py:45-50`) is built only from `_CACHE_VER` and each `.utoc` file's
name/size/mtime. The paks didn't change, so the key matches and the poisoned index is handed
straight back. The rebuild never runs.

That closes the loop on every "just reinstall it" report — `reset_data` works only because it
deletes `_CACHE` wholesale. It also means **Phase 2 is the load-bearing phase**, and it has a
clean local repro that never touches the game:

> wrong key → browse tree empty → enter the correct key → **still empty** → today only a
> reinstall fixes it. After Phase 2, entering the right key must fix it.

---

## Phase 0 — Ship today, nothing to test

No code paths change. No verification needed beyond reading your own README.

| # | Change | Where |
|---|---|---|
| 28 | Ask an MRM op for an `#atelier-bugs` channel or a pinned post | Discord |
| 30 | Link leagueofthearcane's Master Class from the README and first-run screen | README, first-run |
| 29 | State the prerequisites on the export screen — UTOC signature bypass + Project Galacta | gui |
| 31 | Say where the exported mod went (`assets/projects/exported`) | gui |
| 33 | Reply to cartbuddy; open his repro zip | Discord |
| 34 | Publish a donation link | README |

**Confidence at the end:** total — none of it can regress.

**Why first:** #28 and #30 change what future reports look like. Every week without a bug
channel is another week of reports scattered across four channels and six DMs, which is how one
bug ended up with four reporters and nobody noticed.

---

## Phase 1 — Make failures visible, before fixing anything

Diagnostics first. This is the deliberate inversion: these changes are how you will *verify*
Phase 2 without launching the game. Do them first and Phase 2 becomes self-checking.

| # | Change | Where |
|---|---|---|
| 4 | Never cache an index that emitted warnings; surface them in the UI | `index.py:84-85, 103-104` |
| 5 | Split "not found in game paks" into absent / not-indexed / extraction-failed | `material.py:126`, `curve.py`, `text.py`, `vfx.py`, `world.py` |
| 7 | Wrap `_get_toc` in the try/except `index.py` already uses | `pak_thumb.py:53-74` |
| 6 | Timeouts on `uat()` and the `uat_json()` readline loop; stop discarding worker stderr | `tools.py:74-102` |
| 9 | Make `/api/open_explorer` report failure instead of returning `ok: true` | `routes.py:1720-1733` |

**Local verification, no game:**

- Point at a paks folder with one container renamed to something unreadable → the UI should now
  say which container failed and why, instead of showing an empty tree.
- Ask for a material that genuinely doesn't exist → "not in the index". Ask for one in a
  container that failed → "container failed to index". Two different sentences.
- Start an export, kill `UAssetTool.exe` mid-run → it should fail with a message instead of
  hanging forever behind the global lock.
- Click "Open in Explorer" on an asset that hasn't been imported → an error, not silence.

**Confidence at the end:** high, and self-evident — either the app tells you what went wrong or
it doesn't.

**Pivot signal:** if #6's timeouts start firing on legitimate long extractions, the timeout is
too tight — raise it rather than reverting, and note the real duration. The measured baseline is
14.4 s for a single UAT fallback versus 0.38 s for 26 assets straight from the pak.

> **It fired, on 2026-09-20, and the signal was right.** Not on an extraction — on an *encode*.
> `inject_texture` rebuilds a texture's whole mip chain, and BC7 is the slowest encoder in the
> set: three 2048×2048 BC7 injections plus the pack measured **804 s**, ~270 s each, against a
> 300 s cap. Two of three legitimate injections were killed and reported to the user as
> "inject failed: UAssetTool timed out after 300s" on work that was only large. Raised per the
> instruction above — encoding commands now get their own cap (`tools.UAT_SLOW_COMMANDS`:
> 1800 s for `inject_texture`, 3600 s for the batch form) while everything else keeps 300 s,
> because the hang this exists to catch is unbounded rather than slow.

---

## Phase 2 — The index / key cluster

The largest cluster in the corpus: **12 traced reports**, one underlying cause.

| # | Change | Where |
|---|---|---|
| 1 | Put the AES key in the index cache key — and invalidate the **disk** cache, not just `_INDEX` | `index.py:45-50` |
| 8 | One writer for `AES_KEY.txt`; propagate the background fetch into `io_lib.AES_KEY` | `config.py:143-153` |
| 3 | `glob.escape()` user paths; add `[` `]` to `_mod_stem`; unify the two paks checks | `index.py:43`, `config.py:26/32/278`, `routes.py:1928`, `modlock.py`, `repatch.py`, `text.py`, `world.py`, `texture.py:529` |

**Local verification, no game:**

1. **The key repro.** Set a deliberately wrong AES key → browse tree empty. Set the correct key
   in Setup → the tree must repopulate **without a reinstall**. That single test is the whole
   phase.
2. **The bracket repro.** Copy or symlink a paks folder under a path containing `[Steam]` and
   point Atelier at it. Today: Settings reports the path valid while the prereq check says "No
   pak files found". After: both agree, and the tree populates.
3. **The mod-name repro.** Export a mod named `[WIP] Test`. Today the lock/repatch steps glob
   over a bracketed path and silently no-op.

**Confidence at the end:** high for the mechanism, because each has a deterministic local test.
Note what is *not* covered: whether a **patch pak under a second key** now decrypts — that needs
live paks and is Phase 5.

**Note on #8:** `routes.py:607` already assigns `_io_lib_mod.AES_KEY` when you save Setup, so the
Setup path is handled. The gap is `_auto_fetch_aes` in `config.py`, which still writes only the
file — a rotation fetched at runtime doesn't reach `io_lib` until restart, and the startup
config write can still clobber it.

---

## Phase 3 — In-app wins, still no game

Everything here is judged by looking at the app. None of it requires exporting a mod and
launching Marvel Rivals.

| # | Change | Where |
|---|---|---|
| 11 | ID-mask / colour-region overlay | `dye.py` |
| 15 | Plugins path for MarvelGAS ability icons | index / browse |
| 14 | Surface all three nameplate paths | browse |
| 19 | Add the missing recolor entries to the VFX editor | `vfx.py` |
| 16 | Search in the projects screen | routes / gui |
| 17 | Persist the hex / 255 / float toggle | gui |
| 18 | Multi-select edited assets for deletion | gui |

**On #11:** `dye.py` already builds `reg`, a full-resolution per-texel region index, and already
parses the `Region 1..7` params. The overlay is that array coloured by index instead of by dye
parameter. Seven people have asked for it in some form. *This is a texture-panel feature, not
the 3D viewport — say the word if you'd rather it waited for the viewport rework.*

**Local verification:** open a dyeable skin and check the overlay names regions that match the
ColorID defaults. Everything else is "the control exists and does what it says".

**Confidence at the end:** high for 14–19. For #11, high that it renders; whether the region
labelling is *useful* is a judgement call you'll make by looking at it.

---

## Phase 4 — First phase that needs your game

From here a mod has to be exported and looked at in-engine. Everything above should already be
settled, so a failure here points at this phase's own work.

| # | Change | Where |
|---|---|---|
| 10 | Verify the Marvel_LQ root actually shipped | browse / index |
| 12 | Let people turn the chroma/dye overlay off | `dye.py` / `material.py` |
| 21 | Auto-duplicate UI textures into Marvel_LQ | `texture.py` |
| 20 | NoMipMaps / texture-group setting | `texture.py` |
| 22 | Remove a texture outright | `texture.py` |
| 23 | Extend dyed-texture download to the other texture types | `dye.py` |
| 13 | Bulk curve / VFX editing | `curve.py`, `vfx.py` |

**What testing costs here:** each item is one export plus one look in game. #12 is the one worth
doing carefully — it's the most-repeated workflow request, and the check is whether a
hand-painted texture survives onto a chroma instead of being overwritten by the overlay. A
manual 100%-alpha ColorID workaround already circulates, so you have a known-good result to
compare against.

**Pivot signal:** if #12 can't be made to work through the material path, the fallback is
shipping the alpha-ColorID trick as a one-click action rather than a real toggle.

> **Update (2026-09-20): built, and less of it needed the game than this phase assumed.**
> Items **10, 12, 20, 21, 22, 23** are implemented (`tests/test_phase4.py`, 28 checks). **13 was
> deliberately left out** and stays on the board.
>
> The premise that everything here costs an export-plus-a-look turned out to be too pessimistic.
> What decides whether a mod is *correct* — which path an asset is staged at, what the injected
> pixels actually are, whether an option reaches the builder — is all checkable on this side of
> the game, and two of the checks run against the real UAssetTool on a real extracted texture.
> Three things genuinely still need the game, and only three:
>
> - whether the shader honours a zero-alpha ColorID the way the region arithmetic says (#12)
> - whether a UI texture stops being mip-blurred once its group is `TEXTUREGROUP_UI` (#20)
> - whether "removed" reads as gone rather than as a black hole on a given material (#22)
>
> **#10 is answered, and the answer is no.** Marvel_LQ does not ship. Not "is hidden" — every
> container was parsed and **zero paths anywhere contain `Marvel_LQ`**. Re-checked 2026-09-20
> **with the HQ texture DLC installed** — 36 containers, still zero — so "the LQ tree is in the
> part of the game I had not downloaded" is ruled out. The DLC in fact adds **no asset paths at
> all**: the index is 546,297 entries before it and 546,297 after, because its 41,746 entries are
> `.uptnl` bulk data for assets that were already there. fawnls was looking for a
> mount his game no longer had, and nothing in the app could tell him that. Two changes follow. The index had a real bug that would
> have hidden the mount *even where one exists*: both Marvel mounts flattened onto the browse
> root, so an LQ asset and its HQ twin were one virtual path and the dedup kept HQ — and every LQ
> asset has an HQ twin. It now gets its own root, exactly like the MarvelGAS plugin mount did for
> exactly this reason. And Settings now lists the content mounts actually read, so "your install
> does not have one" is a sentence the app can say.
>
> **#21 follows #10 rather than ignoring it.** The duplicate-into-LQ option stages the twin when
> the mount exists and does nothing — saying so — when it does not. Staging into a mount the game
> never looks up would only pad the mod.
>
> **What replaced the HQ/LQ split, and why it does not bring #21 back.** The texture DLC ships as
> `pakchunk<X>optional-Windows` containers holding **nothing but `.uptnl` files** — 41,746 of them,
> the top mip of textures whose `.uasset` stays in the ordinary chunk. So the quality split is now
> *bulk data for one asset*, not a second asset tree: there is no second path to browse and nothing
> to duplicate an edit into. It also settles where `decode_dds`'s "MR strips the top mip" comes
> from — the mip is not stripped, it is in a chunk the machine had not downloaded. With the DLC in,
> retoc pulls the `.uptnl` across containers on its own and a 2048² texture recovers at 2048²
> (verified on `T_1031306_Equip_01_D`). **This has a sharp edge — see TRIAGE #37.**
>
> **#12 took the pivot this phase wrote down.** There is no material parameter for it: the real
> dyeing MIs expose `BaseTint`, `UseDyeingGBChannel` and the `Region N` sets, and nothing that
> switches dyeing off. So the toggle ships a neutral ColorID mask — the circulating workaround,
> made one click and explained in place. The arithmetic is the module's own: alpha is the region
> index, 0 is undyed, and a uniform zero alpha is exact in DXT5 (verified through a real
> inject → extract round trip, alpha came back 0 everywhere). Two things came with it: the dye
> preview now reads the project's painted PNG instead of the vanilla texture — otherwise it
> reproduces finngmin's complaint instead of answering it — and `stage_dye_off` refuses outright
> if a mask's format has no alpha channel, because a "neutral" mask would then read as region 7
> and dye the whole surface.
>
> **#22 cannot always mean invisible, and now says which it is.** `inject_texture` keeps the base
> asset's pixel format, so a transparent PNG injected into a **DXT1** texture comes back opaque
> black (measured on `T_1050103_Body_01_D`). The control names the format and says "opaque black"
> before it is used rather than in the export log afterwards — this is thetruedaveed's
> black-image confusion arriving from the other direction.
>
> **#20 needed no new capability, only the wiring.** `inject_texture --no-mips` already existed
> and nothing passed it; the texture group is an ordinary `LODGroup` enum, rewritten on the staged
> asset after injection (from_json writes `.uasset`/`.uexp` only, so the injected `.ubulk` survives
> — verified by decoding the retargeted texture back). A group edit that fails is reported and the
> texture still ships.
>
> Options are stored per **project**, not per app (`project_meta.asset_opts`), absent means
> default, and switching one off removes it rather than storing false.

---

## Phase 5 — Blocked on live paks

Cannot be confirmed until the game hands you the right conditions: a patch pak under a second
key, or a season boundary.

| # | Change | Where |
|---|---|---|
| 2 | Per-container keys via `enc_guid` | `io_lib.py:146`, `config.py:113` |
| 35 | Test pak override order, including a differently-keyed patch | new test |

`enc_guid` is already parsed and discarded, and `_auto_fetch_aes` only ever reads `mainKey`, so
the plumbing is short. The reason it's late isn't difficulty — it's that you can't prove it
works without a live patch pak that actually uses a different key.

> **Update (2026-09-19, re-checked 2026-09-20): the premise did not survive contact with a real
> install.** Every container reports `enc_guid=0`, and the patch container's directory index
> decrypts with the main key — so
> patched materials were never a second-key problem. The actual cause was *resolution*: which
> on-disk copy the work cache handed back once a patch had moved an asset. That is item **35**,
> which is now done (`tests/test_patch_override.py`). Item 2 is therefore **superseded rather than
> completed** — it stays on the board only because a differently-keyed pak could still ship one day,
> and `enc_guid` is now recorded on every failed container so that day is a log read, not an
> investigation. The original reports came from Windows; see `LINUX.md` → *Still to verify on
> Windows*.

**Re-check, 2026-09-20 (HQ texture DLC installed).** All **36** containers parse cleanly, every
one reports `enc_guid=0`, and every one decrypts with the main key — including the 15 new
`*optional` chunks. There is still exactly **one** patch container, `Patch_-Windows_1.1.3870120_P`,
unchanged since 2026-09-18; no base chunk changed either, so what arrived was the DLC download and
not a game update. A differently-keyed pak has now failed to appear twice, across a content
download that added 47k assets. Item 2 stays parked, not reopened.

**Still open, per your read:** cartbuddy's inconsistency (new-skin mods working while older
material edits broke) could be a skin added straight to the base paks rather than patched, or
one patch pak encrypted and another not. Not decidable from logs. Worth capturing a copy of the
paks at the next season boundary so this can be settled offline instead of live.

**Worth doing in Phase 2 anyway:** have the index record which container an asset came from and
whether that container failed to decrypt. Costs nothing then, and turns Phase 5 into reading a
log rather than re-deriving the problem.

---

## Phase 6 — Long-haul

| # | Change | Where |
|---|---|---|
| 36 | Texture-path regression suite | new test |
| 24 | Copy material parameters to an instance | `material.py` |
| 26 | Audio modding | new subsystem |
| 27 | KO prompt modding | new subsystem |

#36 was promised twice, two weeks apart. After Phases 1–2 it's also much easier to write: the
error states are distinguishable and the index is deterministic, so a test can assert something
more useful than "it didn't throw".

---

## Parked

**Viewport / mesh editing**, to be reworked as a unit:

- Mesh edits save to `.blend` but never reach the game — finngmin, a.wonders, ch3rr13 all
  confirm the round-trip works and the export doesn't
- The viewport doesn't reflect mesh edits while texture changes show
- Checkboxes for which materials import on mesh open; toggling material visibility in Blender
- Cross-character part grafting; lobby-model support
- **LUT support for recolor preview** — noobmasterpro believed it doable, blocker was the backend
- **Labelling the dye preview as approximate** — `DYE_BASE = 0.35` is a hardcoded stand-in,
  commented "Tune 0.4–0.8"
- **cinarette (Eesa) is a mesh modder and offered to help**, 2026-08-16, never taken up. Worth
  reopening when this restarts.

---

## Order at a glance

```
Phase 0  docs & process          no testing at all
Phase 1  diagnostics             read the app's own output
Phase 2  index / key cluster     two local repros, no game      ← load-bearing
Phase 3  in-app features         look at the app
─────────────────────────────────────────────────────────────── game required below
Phase 4  texture & material      one export + one look, each
Phase 5  multi-key              blocked on live patch paks
Phase 6  long-haul
```
