# Atelier — triage board

Every change proposed in `retrieval/ANALYSIS.md`, scored by value and effort, with the number of
real user reports each one would close. This is the flat backlog; `PHASES.md` is the same work
ordered into a delivery sequence. Where the two disagree on a line number, `ANALYSIS.md` is the
original and both were written against the same commit.

Interactive version: <https://claude.ai/artifact/Ng5HzAGKBEbQP2yYMCXPbF>

| | |
|---|---|
| **Source** | 24,343 messages · 6 DMs · 2 user logs · cross-referenced against the code |
| **Window** | 2026-03-20 → 2026-09-18 |
| **Excludes** | mesh editing and the 3D preview (parked as a unit — see PHASES.md) |

**Scales.** Value: Critical > High > Medium > Low. Effort: Trivial (an afternoon) < Small <
Medium < Large. **Reports** = distinct user reports traced in the corpus that the change would
resolve; they *overlap* where several changes address one cluster, so they do not sum to a total.
Items 35–36 are new engineering work with no report behind them.

**The shape of it.** 36 proposals; 11 at trivial effort; 16 rated high or critical. One cluster —
items 1, 2, 4 and 8, all the same underlying AES-key cause — accounts for **12 reports**, the
largest in the corpus. Four trivial items (the cache key, the `_get_toc` guard, the export-screen
prerequisites, the guide link) between them cover more reports than the rest of the board combined.

---

## Status

Implemented and verified as of 2026-09-19 (see `tests/test_phase1.py`, `tests/test_phase2.py`):

- **Phase 1 — diagnostics:** items **4, 5, 6, 7, 9**
- **Phase 2 — the index/key cluster:** items **1, 3, 8**, plus the `enc_guid` recording that
  Phase 5 (item 2) needs

Phase 2's three repros were run against a real game install: wrong key → 0 assets → correct key →
546,297 assets with no reinstall; real paks reached through a `[Steam]` path; a bracketed mod
folder locking and resolving. That run also turned up a defect of its own — `global.utoc`
legitimately carries no directory index, and treating it as a failed container put a false
"wrong AES key" warning on screen at every launch *and* stopped the index from ever being cached
(19 s rebuild every launch instead of a 1.2 s load). Fixed in `io_lib.parse_dir_index`.

Everything else below is unstarted.

---

## Bugs

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 1 | Put the AES key in the index cache key | Critical | Trivial | 12 | `atelier/index.py:45-50` | A wrong key yields an empty index that is cached and then served forever, because the cache key only covers .utoc stats. One line. Retires "just reinstall it" as support advice. |
| 2 | Per-container keys via `enc_guid` | Critical | Medium | 12 | `io_lib.py:59` · `atelier/config.py:113` | The root fix behind #1. `enc_guid` — the field that says which key a container needs — is already parsed and thrown away, and only `mainKey` is ever fetched. Patch paks under a second key decrypt to garbage. |
| 3 | `glob.escape` user paths; bracket-safe mod names | High | Small | 2 | `index.py:43` · `config.py:26/32/278` · `routes.py:1928` | A `[Steam]` folder makes glob match nothing, so zero containers are found. Confirmed by everikreal; leagueofthearcane had seen it before. `glob.escape` appears nowhere in the codebase. |
| 6 | Timeouts on `uat()` and the `uat_json` read loop | High | Small | 2 | `atelier/tools.py:74-102` | An unbounded `readline()` while holding a module-global lock blocks every UAT call in the app. This is the export hang: never finishes, retrying does not help, only restarting clears it. Worker stderr goes to DEVNULL. |
| 7 | Wrap `_get_toc` in the try/except `index.py` already uses | High | Trivial | 3 | `atelier/handlers/pak_thumb.py:53-74` | Same two parser calls, two different error policies. In the thumbnail path an exception kills the background thread, no cache entry is written, and the spinner runs forever with no error. |
| 8 | One writer for `AES_KEY.txt`; re-read on change | High | Small | 12 | `atelier/config.py:143-153` | A background fetch thread and a config write both target the file while `io_lib` reads it once at import. A stale saved key overwrites the fetched one every startup, and `io_lib` and UAssetTool can end up on different keys in one session. |
| 9 | Make `/api/open_explorer` report failure | Medium | Trivial | 4 | `atelier/web/routes.py:1720-1733` | When neither branch matches it does nothing and still returns `ok:true`. With `game_rel` the path does not exist until the texture is imported — which is the "nothing pops up" report. |
| 10 | Verify the Marvel_LQ root actually shipped | Medium | Small | 2 | browse / index | Reported fixed in June; fawnls still had no Marvel_LQ node in August, which silently breaks UI mods because they need the LQ copy. |

## Diagnostics

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 4 | Never cache an index that warned — and show the warnings | High | Small | 12 | `atelier/index.py:84-85, 103-104` | Failed containers are skipped with a stderr warning and the empty result is written to disk anyway. Surfacing it turns a silent dead app into a reportable error. |
| 5 | Split "not found in game paks" into three states | High | Small | 6 | `material.py:126` · `curve.py` · `text.py` · `vfx.py` · `world.py` | Absent vs not-indexed vs extraction-failed all produce one sentence. Four reporters used identical wording with potentially different causes, and none could be triaged. `texture.py:181` already concedes the problem in a comment. |

## Features

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 11 | ID-mask / colour-region overlay | High | Small | 7 | `atelier/handlers/dye.py` | `dye.py` already builds `reg` — a full-resolution per-texel region index — and parses the Region 1..7 params. Colour that array by index instead of by dye parameter. Seven askers; the decline was noobmasterpro's and predates his own dye code. |
| 12 | Let people turn the chroma/dye overlay off | High | Medium | 3 | `dye.py` / `material.py` | The overlay trumps the texture PNG, so painted edits never show except on hair and eyes. Most-repeated workflow request, and a manual 100%-alpha ColorID workaround already circulates in the guides. |
| 13 | Bulk curve / VFX editing | Medium | Medium | 2 | `curve.py` · `vfx.py` | The named reason people get sent to Saturn's editor. Deferred by noobmasterpro on capacity, not merit. |
| 14 | Surface all three nameplate paths | Medium | Small | 3 | browse | Profile, cosmetic menu and cropped icon live in three different directories; users needed another user to list them. |
| 15 | Plugins path for MarvelGAS ability icons | Medium | Small | 2 | index / browse | Team-up icons live under a plugin mount. Atelier's naming also diverges from FModel's, which cost shafsta an entire support thread before he found it himself. |
| 16 | Search in the projects screen | Medium | Small | 1 | routes / gui | Asked 2026-09-18. noobmasterpro's answer was "ask clown." |
| 17 | Persist the hex / 255 / float toggle | Medium | Trivial | 1 | gui | Hex paste already works; the mode resets every time. "It's 2 clicks regardless, but it doesn't save." |
| 18 | Multi-select edited assets for deletion | Medium | Small | 1 | gui | Shift-click X shipped in 0.3.3 as a partial answer; bulk selection is still missing. |
| 19 | Add the missing recolor entries to the VFX editor | Medium | Small | 1 | `vfx.py` | diiea could not find skin 1031306 in the editor. "I meant to do that, forgor." |
| 20 | NoMipMaps / texture-group setting | Medium | Small | 2 | `texture.py` | Currently forces users back into Unreal for a single checkbox — the exact thing Atelier exists to avoid. |
| 21 | Auto-duplicate UI textures into Marvel_LQ | Medium | Small | 1 | `texture.py` | Without the LQ copy a UI mod only shows on high texture settings, which reads to the user as the mod not working. |
| 22 | Remove a texture outright, not just replace it | Low | Small | 1 | `texture.py` | Answered with "make it transparent", which is not the same thing for VFX overlays. |
| 23 | Extend dyed-texture download to the other texture types | Low | Small | 1 | `dye.py` | Noted and credited to noobmasterpro; never built. |
| 24 | Copy material parameters to an instance | Low | Medium | 1 | `material.py` | Needs Unreal today — "Atelier can't handle it." |
| 25 | LUT support for recolor preview | Low | Large | 1 | `dye.py` / `material.py` | noobmasterpro believed it was doable — "I know how to do it, I genuinely do" — and his stated blocker was the backend, not the idea. Same subsystem as #11. |
| 26 | Audio modding | Low | Large | 2 | new subsystem | Asked twice. "On the bucket list." |
| 27 | KO prompt modding | Low | Medium | 1 | new subsystem | "Atelier cant do everything." Fair, but it is a standing request. |

## Docs

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 29 | State the prerequisites on the export screen | High | Trivial | 3 | gui | Mods need the UTOC signature bypass plus Project Galacta to load at all. The app says nothing, so people export, see no change in game, and conclude Atelier is broken. |
| 30 | Link leagueofthearcane's Master Class | High | Trivial | 6 | README · first-run | Three people asked for a guide; he wrote one — written plus video — and two more volunteers offered. None of it is linked from anywhere you control. |
| 31 | Show where the exported mod went | Medium | Trivial | 2 | gui | "Where do i find the exported mod?" — answered by another user with `assets/projects/exported`. The export screen never says. |
| 32 | Label the dye preview as approximate | Medium | Trivial | 1 | gui | `DYE_BASE = 0.35` is a hardcoded stand-in for a shader constant that was never found, commented "Tune 0.4–0.8". That is the named cause of the live colour preview not matching in game. |

## Process

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 28 | Ask an MRM op for a bug channel or a pinned post | High | Trivial | 1 | — | diiea asked outright: "i wish there was a place for bug reports". Reports are spread over four channels, six DMs and a 726-message thread — which is why nobody noticed one bug had four reporters. You also cannot pin releases yourself. |
| 33 | Reply to cartbuddy and open his repro zip | Medium | Trivial | 1 | — | He handed over a reproducible broken mod on 09-12 and you said "alright". His 09-13 follow-up is unanswered, and it is the same flicker boncchickenx reported. |
| 34 | Publish a donation link | Low | Trivial | 2 | README | Two people fund the app. There is no public link anywhere; both offers came to you unprompted. |

## Testing

| # | Change | Value | Effort | Reports | Where | Why it's here |
|---|---|---|---|---|---|---|
| 35 | Test pak override order, including a differently-keyed patch | Medium | Medium | 0 | new test | Already on your TODO. It now has a concrete second case: the same asset in a base chunk and in a patch chunk encrypted differently. |
| 36 | Texture-path regression suite | Medium | Large | 0 | new test | Promised twice — "ill set up some unit tests" and "this is why a test suite is wise" — two weeks apart. The premise of the first ("no one reported issues with texture modding") was already false. |
