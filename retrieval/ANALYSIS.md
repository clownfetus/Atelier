# Atelier — report analysis, verified against the code

Third pass. The first two passes read ~24k server messages, six DM exports and the attached
user logs. This pass cross-references those findings against the source, corrects what was
wrong, and names root causes by file and line. It also folds in #setup-and-guide
(thread `1542171855807315978`, 67 messages + 5 videos, pulled with `retrieval/fetch.py`),
which turned out to contain a solved bug nobody wrote down.

**Scope note:** mesh editing and the 3D preview are deliberately excluded — they're being
reworked as a unit later. What was found about them is parked in the last section rather than
deleted.

**Corrections to the previous draft** are called out inline as `CORRECTED`. Two of my earlier
root causes were wrong, and one thing I reported as open is already fixed.

---

## 1. The single AES key is the root cause of most of the report volume

`CORRECTED` — I previously blamed a fragile container parser. The parser is fine. It is being
fed garbage.

### The chain

`io_lib.py:4-6`

```python
AES_KEY = b""
if os.path.exists(AES_PATH := os.path.join(_TOOLS, "AES_KEY.txt")):
    with open(AES_PATH) as AES_FILE: AES_KEY = bytes.fromhex(AES_FILE.read().strip())
```

One key. Module-level. Read **once at import**, never re-read.

`io_lib.py:121-122`, inside `parse_dir_index`:

```python
if t.encrypted:
    blob = aes_decrypt(blob[:(len(blob) // 16) * 16])
```

AES-ECB with the wrong key doesn't fail — it returns garbage. Nothing verifies the plaintext.
That garbage goes straight into `fstr()` at `io_lib.py:128-133`:

```python
n = i32()
if n > 0:  s = blob[o[0]:o[0] + n - 1].decode("latin1"); o[0] += n
else:      n = -n; s = blob[o[0]:o[0] + (n-1)*2].decode("utf-16-le"); o[0] += n*2
```

A garbage length is either negative → UTF-16 decode of random bytes, or a large positive →
`o[0]` jumps past the buffer. **Those are exactly the two error shapes in driz's log**, and they
are the same bug, not two:

```
[warn] pakchunkHQ-Windows.utoc: 'utf-16-le' codec can't decode bytes ... illegal UTF-16 surrogate
[warn] pakchunkCharacter-Windows.utoc: unpack_from requires a buffer of at least 235310493 bytes
```

`io_lib.py:59` reads the field that would fix this and throws it away:

```python
t.enc_guid = buf[b+44:b+60]
```

**`enc_guid` is parsed and never used anywhere in the codebase.** That is the per-container
encryption GUID — the thing that selects which key a container needs. The data required for
multi-key support is already in hand. (`t.version` at `io_lib.py:52` is likewise parsed and
never validated.)

### The failure is then cached

`atelier/index.py:84-85` — a container that fails to parse is warned about and skipped:

```python
except Exception as e:
    print(f"  [warn] {os.path.basename(utoc)}: {e}", file=sys.stderr); continue
```

`atelier/index.py:103-104` — the resulting index is written to disk **unconditionally**, even
if every container failed and the index is empty.

`atelier/index.py:45-50` — and the cache key is:

```python
parts = [_CACHE_VER]
for f in _index_utocs():
    s = os.stat(f)
    parts.append(f"{os.path.basename(f)}:{s.st_size}:{int(s.st_mtime)}")
```

**The AES key is not part of the cache key.** So: wrong key → empty index → cached → user fixes
the key → paks haven't changed → *the broken index is served forever*. Only wiping `_cache` or a
game patch clears it.

**This is why reinstalling "works."** driz did it six times; diiea redownloaded; ch3rr13
reinstalled. Your own words to driz — *"reinstalling a couple times seems to do the trick for
some people its weird"* — and your instinct to tell him to clear `AppData\Local\Atelier\_cache`
was correct. The cache key is the actual fix, and it's one line.

### A race makes it worse

`atelier/config.py:143-153`:

```python
if getattr(sys, "frozen", False):
    _threading.Thread(target=_auto_fetch_aes, daemon=True).start()   # writes AES_KEY.txt

_aes_key_cfg = _cfg.get("aes_key", "").strip()
if _aes_key_cfg:
    with open(os.path.join(TOOLS, "AES_KEY.txt"), "w", encoding="utf-8") as _f:
        _f.write(_aes_key_cfg)                                        # writes AES_KEY.txt
```

Two writers to the same file, one of them a background thread, with `io_lib` reading it once at
import. Three consequences:

- A user's stale saved key **overwrites the freshly fetched correct one** on every startup.
- If the thread lands after `io_lib` imported, `io_lib.AES_KEY` and the file disagree — so
  `io_lib` and UAssetTool (which reads the file) can be using *different keys in the same session*.
- `_auto_fetch_aes` reads only `mainKey` from the depot JSON (`config.py:113`). Any per-container
  keys published alongside it are ignored.

That also explains driz's two logs. On 0.3.2 the base chunks indexed fine; 80 minutes later on
0.2.3 **all 23 failed** — same machine, same game files. A key clobbered on the downgrade path
fits; a parser that regressed backwards in time does not.

### What this one cause explains

- **"material not found in game paks"** — kadeschaos, kyr.xem, surrept., driz
- **empty / partial browse tree** — driz, *"now its just empty on the older version"*
  (everikreal's *"no pak files"* looked like this too, but it turned out to be §2 — see there)
- **skins missing from the app** — surrept. (Carmine Cassette), skyfallx_x (Widow), surrept. (Luna)
- **blank project thumbnails** — diiea; driz's log shows `GET /api/project/thumb → 404`

surrept.'s DM is the cleanest confirmation anyone could ask for: reinstalling prompted her to
reconfigure the key, Luna's Carmine Cassette patch **needed an additional key**, she entered it and
the skin appeared — and then *"ill need to reset the data again to get all the other assets back
with the original key."* One key slot, two keys needed. She described the architecture limit
exactly.

### Also: the thumbnail path has no error handling at all

`atelier/handlers/pak_thumb.py:53-74` calls the same two functions with **no try/except**:

```python
t = io_lib.parse_toc(utoc)
ents = io_lib.parse_dir_index(t)
```

Run from `_warmup()` background threads, so a bad container kills the thread, `_toc_cache` never
gets an entry, and the spinner runs forever with no error. `index.py` catches this exact
exception; `pak_thumb.py` doesn't. That inconsistency is your TODO line *"preview thumbnails
sometimes infinitely load until revisit/triggered refresh."*

---

## 2. Special characters in paths — a whole class of silent failure

The #setup-and-guide thread contains a bug that was diagnosed, fixed and never recorded.
everikreal's Atelier showed "no pak files" while Settings reported every path valid. On
2026-09-16 you guessed it:

> **.clownfetus:** *"shit it might be cuz ur steam folder has weird characters `[Steam]`"*
> **leagueofthearcane:** *"Yeah that's almost definitely the problem. Seen it before. They had to
> rename their folders because the path just kept breaking."*

He renamed the folder and it worked. **You were right, and the code says exactly why.**

### Square brackets are glob metacharacters

`atelier/index.py:43`

```python
return sorted(glob.glob(PAKS + "/*.utoc"), key=lambda p: os.path.basename(p).lower())
```

With `PAKS = D:\[Steam]\steamapps\...\Paks`, `glob` reads `[Steam]` as a **character class**
matching one of `S t e a m`. The pattern matches nothing, so **zero containers are found** and the
index is empty. Of the characters glob treats specially — `*`, `?`, `[`, `]` — only the brackets
are legal in Windows filenames, so brackets are the whole practical surface. `[Steam]`, `[SSD]`,
`[Games]` are all common folder names.

**`glob.escape` does not appear anywhere in the codebase**, and there are 25+ glob calls built by
concatenating user-controlled paths.

### Why it was undiagnosable

Two different checks answer the same question by different means and disagree:

| check | mechanism | verdict on `[Steam]` |
|---|---|---|
| `routes.py` `api_validate_paks` | `os.path.exists(paks + "/pakchunkCharacter-Windows.ucas")` | **ok** |
| `config.py:278` `_prereq_issues` | `glob.glob(PAKS + "/pakchunk*.utoc")` | **"No pak files found"** |

That is everikreal's report word for word — *"wdym no pak files / it says every path is valid in
the settings"*. The settings validator uses a literal path test; the prereq check uses glob.

`_detect_paks()` and `paks_suggestion()` (`config.py:26`, `config.py:32`) also glob, so
auto-detection silently fails for these users too — they browse manually, get told the path is
valid, and are then told there are no pak files.

### It isn't only the paks path

`routes.py:1928`

```python
def _mod_stem(mod_name):
    return re.sub(r'[/\\:*?"<>|.]', '', (mod_name or "Mod").strip()) or "Mod"
```

Strips the Windows-illegal set — **and does not strip `[` or `]`**. A mod called `[WIP] Recolor`
keeps its brackets into `_cache/build_stage/<name>` and the output filenames. Anything that
globs those paths then finds nothing, silently:

- `modlock.py:43-49` — globs `mod_source` for `.ucas`/`.utoc`/`.pak`/`.zip`
- `repatch.py:45`, `:71`, `:79`, `:96` — globs `mod_source` and its unpack dirs
- `texture.py:529` — `glob.glob(os.path.join(out_dir, "*_P.utoc"))`

So a bracketed mod or folder name can make locking and repatching quietly do nothing.

### Relation to the spaces bug

chopthememegod's spaces report was a **different** bug in a **different** layer — Explorer
argument parsing, fixed at `routes.py:1710-1717`. Spaces are harmless to glob. Brackets are
harmless to Explorer. They are two separate path-handling problems that produce similar-sounding
complaints, which is part of why neither got pinned down for months.

### Fix

`glob.escape()` the directory portion at every call site (the pattern half must stay unescaped),
or replace directory scans with `os.scandir` + `fnmatch` on the basename. Add `[` and `]` to
`_mod_stem`. And make the two paks checks share one implementation so they can never disagree
again.

*Confidence: high. The mechanism is deterministic, the code is unambiguous, and there is a
confirmed user case that resolved by renaming the folder.*

---

## 3. The patch system — corrected

`CORRECTED` — I read `uat_pfx=ent/Marvel/` as an 11-character slicing bug. **It is not a bug.**
`atelier/handlers/texture.py:130-135` is a deliberate, commented mapping:

```python
# UAT extract_iostore_legacy drops patch pak assets under ent/Marvel[_LQ]/ instead of the full
# Marvel/Content/Marvel[_LQ]/ path that base paks use.  Map index pfx → UAT output prefix.
_PATCH_UAT_PREFIX = {
    "Marvel/Content/Marvel/":    "ent/Marvel/",
    "Marvel/Content/Marvel_LQ/": "ent/Marvel_LQ/",
}
```

The predicted path was right. `find_extracted` returned NOT FOUND because **the asset was never
extracted** — the failure is upstream, and §1 is the reason.

### How the patch system actually works

- New skins ship as **patches — separate pak files** alongside the base chunks.
- **Patch paks sometimes carry a different AES key** from the main key.
- **Patch contents get assimilated into the main paks** in a later update, at which point the
  separate patch pak stops mattering.

That model makes the "missing skin" reports coherent, and it makes them a **time-boxed** class of
bug: an asset is unreachable only while it lives in a patch pak under a key Atelier can't hold,
and fixes itself when NetEase folds it into the base paks. Luna Snow's **Carmine Cassette** and
Black Widow's **Aquatic Assassin** are almost certainly this. surrept.'s *"i just had to wait a
few more days and it showed up!"* is assimilation happening on its own.

`atelier/index.py:39-43` already sorts so patch paks override base ones, and the priority comment
at `index.py:75-78` says patch wins. That part is right. The gap is purely the key.

**Open question, needs live paks.** cartbuddy's results don't fit one story: some of his mods on
new skins worked while older material edits broke. Could be NetEase adding a skin straight to the
base paks instead of patching it; could be one patch pak encrypted and another not. Not
determinable from chat logs — flagging it for testing against live paks rather than guessing.

Your TODO line *"test pak override order... ensure latest patch's item is used"* is the right test
to write, and it now has a second case worth covering: the same asset in a base chunk and in a
patch chunk **encrypted differently**.

---

## 4. What the season update broke

cartbuddy isolated this across five of his own mods:

| mod | contents | after S10 |
|---|---|---|
| Angela | flame VFX + materials | broke |
| Cyclops (red) | materials, **no** emissive change | **survived** |
| Cyclops (other colours) | materials incl. emissive/visor | broke |
| Iron Man | materials only, no VFX | broke |
| White Fox | materials only | broke |
| built fresh after S10 | textures + materials | fine |

**Material-level edits made before the update break; texture-only work survives; rebuilding from
scratch mostly fixes it.** VFX behaves as a material here — the one in-chat call of yours that the
evidence fully supports.

The Repak X log he sent reinforces it; the parameters that fail to re-apply are the tint/emissive
family:

```
Warning: Could not apply EmissiveColor: path not found
Warning: Could not apply IrisBleedTint: path not found
Warning: Could not apply ScleraTint: path not found
```

Which is why the red Cyclops variant — the only one that never touched emissive — came through
intact.

**The `blake3_dotnet` error in that log is Repak X's, not yours.** You were right. Worth telling
him plainly; he's still stuck on it.

---

## 5. Export hangs — root cause found

labyrinth22, corroborated by revenantreignvie: *"it'll initiate the process but never finish"*,
10+ minutes on 7 textures, across restarts and renames.

`atelier/tools.py:74-77`:

```python
def uat(args):
    return subprocess.run([UAT] + args, capture_output=True, text=True, cwd=ROOT, creationflags=CNW)
```

No `timeout=`. Blocks forever if UAT hangs.

`atelier/tools.py:82-102` is the worse one:

```python
with _lock:                                    # module-global lock
    ...
    _proc.stdin.write(json.dumps(req) + "\n"); _proc.stdin.flush()
    while True:
        line = _proc.stdout.readline()         # no timeout
```

An unbounded `readline()` **while holding a global lock**. If the worker stays alive but stops
emitting a JSON line, every UAT request in the whole app queues behind it forever. That is
precisely the reported symptom: the operation never completes, retrying doesn't help, and only
restarting the app clears it. `stderr=subprocess.DEVNULL` on that worker means whatever it was
complaining about was discarded.

Three fixes, cheap: a timeout on `uat()`, a deadline on the `readline()` loop, and stop swallowing
the worker's stderr.

---

## 6. Error messages are destroying your own diagnostics

`atelier/handlers/material.py:113-126` runs the extraction and never checks the return code —
it just looks for the file afterwards and raises:

```python
raise RuntimeError("material not found in game paks")
```

`atelier/handlers/texture.py:181-183` already admits the problem in a comment:

> *A tool crash, a file lock, or a MOTW-tainted DLL all leave the asset unextracted, and the
> caller can only report "not found in the game paks" — indistinguishable from an asset the game
> genuinely doesn't have.*

So four separate causes — asset genuinely absent, container dropped from the index by a key
mismatch, UAT crash, DLL taint — all surface as one sentence. That is why four different reporters
produced identical wording and none of them could be triaged, and why this sat unsolved for months.
Same pattern at `curve.py:49`, `text.py:129`, `vfx.py:40`, `world.py:162`.

**Distinguishing these three states in the message would have surfaced §1 in August.**

---

## 7. The repak step — resolved externally, but undocumented

`CORRECTED` — I framed this as an Atelier gap. It was neither Atelier-specific nor permanent.

For a window around S9.5/S10, **every mod from every tool** needed a manual repak/encrypt pass to
load at all. In #setup-and-guide lmaolena exported, launched, saw nothing, and leagueofthearcane
answered (09-10):

> *"you have to run it through repak first (this is a makeshift fix until the modders release
> their new fix that shouldn't need anything (probably updating utoc))"*

The fix he was anticipating arrived two days later: **Project Galacta**, a mod loader by
saturnooooooo (Nexus 12806, ~09-12), which restores mod loading globally when paired with the
signature bypass. The manual step is gone:

- labyrinth22, 09-13: *"Project galacta enables the mod loading / provides season 9.5/10 fix"*
- ragnarok_17_krishna, 09-15: *"With project galacta and sig bypass, mods work now without the
  use of repak GUI"*
- xz4nt, 09-17: *"you dont need the encryption if you have project Galacta"*
- fubukibestogal, 09-16: *"project galacta the mod fix which u dont have to do anything to make it
  work. Mods just work as long as its in the mods folder"*

So the **"built-in repak step" request is effectively obsolete** — reclassified in §11.

### What does remain

Atelier still tells a new user nothing about what a working install needs. The app has no
statement of prerequisites, and the loader is now one of them. People are still arriving at the
wrong conclusion from the right symptom — marangely (09-16): *"Is there now a new way to pack mods
in Unreal Engine because of Project Galacta? I was working on a mod and tried replacing only the
textures but it didnt seem to work"*.

A single line on the export screen — *"mods require the UTOC signature bypass + Project Galacta to
load"*, with a link — costs nothing and pre-empts a recurring class of "Atelier is broken" report.
You already told ch3rr13 on 09-11 that *"that galacta thing will likely make my life way easier"*;
saying so in the app is the cheap half of that.

## 8. Your in-chat diagnoses, re-checked

| what was said | verdict |
|---|---|
| *"might be today's game update changing things up with materials"* (surrept.) | **No.** She downgraded Atelier and it worked again — same game build. That's an Atelier-side regression, and §1 gives the mechanism. You half-caught it: *"if its a regression issue i can j revert whatevers wrong"* |
| *"very likely a patch pak issue"* (cartbuddy) | **Right instinct, wrong target.** Patch paks are involved (§3) but via the key, not the pak. You retracted it yourself two messages later |
| *"so it seems to be materials in general, vfx count as materials"* | **Yes.** Best call you made |
| *"its missing blake3 a dependency, does not seem specific to atelier"* | **Yes**, confirmed |
| *"this is the issue, its in a patch pak"* (skyfallx_x) | **Right area.** §3 refines it |
| *"reinstalling a couple times seems to do the trick"* | A symptom of the uncached-key bug, and the clue that cracks §1 |
| *"thats weird, never seen a disconnect between game and lobby yet"* | **You have, three times** — surrept., cartbuddy, finngmin. Worth treating lobby-vs-ingame divergence as its own bug |
| noobmaster: *"Complex Materials take time to unpack"* | Partly — §9 shows it's the UAT fallback path specifically |
| noobmaster: *"Its there, don't worry, it's just not updated visually"* | Real bug; your TODO already concedes the sidebar doesn't refresh on edit |
| *"shit it might be cuz ur steam folder has weird characters `[Steam]`"* (everikreal) | **Correct, and the code proves it (§2).** The one field diagnosis in the whole dataset that landed squarely on a real root cause. leagueofthearcane confirmed he'd seen it before and that affected users had to rename folders |
| leagueofthearcane: *"this issue also sometimes happens if Antivirus blocks atelier"* | Plausible and a genuine confound — Defender quarantining has its own thread of reports (xynoah, finngmin, kadeschaos). Two unrelated causes, one symptom, which is why §6's message conflation hurts so much |
| *"if you export a mod and there are spaces it sends you to the documents folder"* (chopthememegod) | **He was right, and it's already fixed** — `routes.py:1710-1717` now builds a quoted string command and the docstring documents his exact symptom |

---

## 9. The logs answer two open TODO questions

**"diagnose import/export times (ui mods for LQ using UAT fallback?)"** — answered:

```
[PREFETCH] pass-1 done: 26 pak-ok, 1 need UAT  (0.38s)
[PREFETCH] batch extract 1 assets via UAT...
[PREFETCH] extract done in 14.44s
[PREFETCH] total 17.42s  (1 batched UAT fallbacks)
```

26 assets from the pak: **0.38s**. One asset via UAT: **14.44s** — 97% of runtime for 4% of the
assets. Your hunch was right. Reducing fallback frequency beats optimising the fast path, and §1
is a major cause of fallbacks.

**"confirm version/auto-update works"** — the check works (`[update] update available: (0,2,3) ->
(0,3,2)`). Nothing acts on it: skyfallx_x *"there is no auto update in the app so i manually
download the installer"*, pushingpetals *"There's no area to manually update/check for updates
within it and I've never seen an update prompt on startup."* Detection is fine; the prompt is the gap.

---

## 10. Still-open bug: "Open in Explorer" does nothing

The spaces bug is fixed, but `atelier/web/routes.py:1720-1733`:

```python
if os.path.exists(abs_path):        _explorer_reveal(abs_path, select=True)
elif os.path.isdir(os.path.dirname(abs_path)): _explorer_reveal(..., select=False)
return json.dumps({"ok": True})
```

If neither branch matches, **nothing happens and it still reports success**. With `game_rel` the
path is `_import_base(gr) + ".png"`, which doesn't exist until the texture has been imported. That
is ghostex101's *"Nothing pops up"* and yunggwetto's *"i dont get an option to open in external
app"* — a silent no-op returning `ok: True`.

---

## 11. Every feature request on record

Mesh and 3D-preview requests are parked in §15.

### Shipped

| want | who | outcome |
|---|---|---|
| Right-click → Show in Explorer | finngmin, 06-26 | shipped |
| Stop the "open with" popup on every queued texture | cinarette (DM), 08-04 | **shipped 08-16 as a settings toggle, confirmed by her** — the only clean verified close in the dataset |
| Shift-click X to delete without the confirm dialog | criticalcondition, winterwintour | shipped 0.3.3 |
| Sidebar selection state surviving restart / project switch | — | shipped 0.3.3 |
| More asset roots (UI/Textures, Marvel_LQ) | skyfallx_x, 06-26 | *"it should be fixed now"* — **partial**: fawnls still had no Marvel_LQ on 08-22 |
| Mod patcher / repatcher | noobmasterpro, 0.3.0 | shipped; a.wonders reports it stopped working |

### Accepted, not delivered

| want | who | what was said |
|---|---|---|
| Disable the chroma/dye overlay so textures can be painted directly | finngmin | *"i will try thats a good suggestion"* — **most-repeated workflow request in the corpus**. finn's full spec: the material overlay trumps the texture PNG, so user edits never show except on unique textures like hair and eyes. **There is already a manual workaround in the wild**: replace the ColorID texture with a 100%-alpha image (leagueofthearcane, #setup-and-guide). thetruedaveed tried a *black* image first and it still shaded — so the trick is non-obvious and undocumented in-app. The feature is just automating a procedure people already perform |
| Multi-AES-key support | you, 08-28 | *"ill add support for multiple keys"*. §1 says this is no longer a nice-to-have — it's the top bug |
| Dyed-texture download for the other texture types | chopthememegod | *"noted"* |
| VFX editor missing recolor entries (skin 1031306) | diiea | you: *"gotta add that to atelier"*; noobmasterpro: *"I meant to do that, forgor"* |
| **ID-mask / colour-region overlay** | muimifu, finngmin, paillettelebeau, norskpl, leagueofthearcane | **Reopened — see §11a.** Declined by noobmasterpro as *"No ID mask integration yet, really low priority"* (07-09). With his features handed over, that call is yours again, and the code has moved since he made it |

### Open, never answered

| want | who |
|---|---|
| Search in the projects screen | shafsta, 09-18 |
| Persist the hex/255/float toggle between uses | taylorlinnay |
| Multi-select edited assets for deletion | winterwintour |
| Bulk edit for curves / VFX | boncchickenx — the named reason people get sent to Saturn's editor |
| Nameplates (three separate paths, none surfaced in-app) | winterwintour, ghostex101, diiea |
| Audio modding | pushingpetals, twice — *"on the bucket list"* |
| Plugins path for MarvelGAS ability icons | wendall555, shafsta |
| Remove a texture outright rather than replace it | pushingpetals |
| NoMipMaps / texture-group setting (needs UE today) | ch3rr13 + hobbyr34 |
| Copy material parameters to an instance | labyrinth22 |
| Auto-duplicate UI textures into Marvel_LQ | norskpl |
| ~~Built-in repak step~~ | finngmin, lmaolena — **obsolete**: Project Galacta removed the manual pass (§7). Close it |
| KO prompt modding | winterwintour |
| Toggle select/deselect all on the circled number | diiea — **already exists**; pure discoverability. Your TODO wants it as a toggle |
| Show where the exported mod went | lmaolena, #setup-and-guide — *"Where do i find the exported mod?"*; answered by another user with `assets/projects/exported`. The export screen never says |
| A way to tell which colour region maps to which part | paillettelebeau, #setup-and-guide — *"how do you know wich exact color you need to modify"*. leagueofthearcane's method is eyeballing ColorID default colours, and for VFX *"I just use trial and error a LOT"*. Third independent request for the ID-mask overlay you declined (muimifu, norskpl) |

### Inherited decisions — every "no" below was noobmasterpro's

With his features handed over, these are yours to re-decide rather than settled policy. Listing
them because several were deferred on *his* capacity or *his* read of the backend, not on merit.

| item | his call | date |
|---|---|---|
| ID-mask / colour-region overlay | *"No ID mask integration yet, really low priority"* | 07-09 — **reopened, §11a** |
| Bulk curve / VFX editing | *"not yet, curves and NS are still new. Currently have my hands full with other projects to fix it ATM"* | 07-05 |
| LUT support for recolor preview | *"IDEK if we CAN do LUTs"* → *"We'll put that down as a QoL for 0.2.2"* → *"I know how to do it, I genuinely do. I just don't know if the editor can handle it with its current backend"* | 07-02 |
| VFX editor missing recolor entries | *"I meant to do that, forgor"* | 07-02 |
| Persisting the hex/255/float toggle | *"It's 2 clicks regardless, but it doesn't save"* | 07-16 |
| Audio modding | *"on the bucket list"* | 07-15 |
| KO prompt modding | *"Atelier cant do everything"* | 07-15 |

The LUT one is worth a second look alongside §11a — it's the same subsystem, he believed it was
doable, and his stated blocker was the backend rather than the idea.

### 11a. The ID-mask overlay is now nearly free — reconsider it

This is the single request with the most independent askers, and the reason it was declined no
longer holds.

**Who asked, in their own words:**

- **muimifu** — *"yk how in blender u can do uv mapping... it highlights which part on the texture
  is which, does atelier have a feature like that"*
- **finngmin** — wanted to preview material colour changes on recolors, where there's no mesh to
  reference. This is the ask noobmasterpro answered with *"No ID mask integration yet, really low
  priority"* (07-09)
- **paillettelebeau** — *"how do you know wich exact color you need to modify"*
- **leagueofthearcane**, answering that — he eyeballs the ColorID region default colours, and for
  VFX *"I just use trial and error a LOT"*
- **norskpl** — doesn't use Atelier, and his whole recolour workflow is exporting UV maps from
  Blender *"because you know which part of the texture corresponds to which part of the model"*
- adjacent: **thetruedaveed** (blank-vs-alpha ColorID confusion), **kadeschaos** (*"we don't have
  the tools to correctly change colorID files yet"*)

**Why the decline made sense then.** noobmasterpro's worry, 07-02: *"Then there's mapping the RGBA
layers of the ID mask to the regions of the materials themselves — and THATS what I am most
worried about."* Fair at the time.

**Why it doesn't now: he then built exactly that.** `atelier/handlers/dye.py` already does the
hard part and ships:

```python
STEP = 255.0 / 7.0          # alpha per region step; region = round(alpha / STEP), 0 = undyed
...
reg = np.rint(mask[..., 3] / STEP).astype(np.int32)     # full-res per-texel region index
```

The module docstring states the format outright — the ColorID mask's **alpha is a region index**
quantised into 7 steps mapping to the MI's `Region 1..7 - ColorA/ColorB/...` params — and
`dye_regions()` already parses those params into `{region_idx: {param: rgba}}`. `composite()`
already builds `reg`, a per-texel region map at full resolution, and `/api/dye_texture` already
serves a composited PNG over HTTP.

**So the overlay is: colour `reg` by index instead of by dye parameter, and serve it from a sibling
route.** The mask decode, the region quantisation and the MI parameter mapping — the three things
that made it expensive — are done, tested against the game (the docstring notes verification on
1060300 Coastal Kumiho), and already running on every dyeable material. The docstring also confirms
it is preview-only and never ships into a mod, so an overlay is purely additive.

That turns "which colour do I edit?" from trial and error into a labelled picture, for five
requesters and one non-user who cites it as the reason he stays in Blender.

**Related, while you're in there:** `DYE_BASE = 0.35` is a hardcoded stand-in for a shader constant
that was never found, with the comment *"Tune 0.4–0.8"*. That is the named cause of finngmin's
complaint that noob's live colour preview *"didn't really work in game"* — the preview is
approximate by construction. Worth labelling in-app rather than letting people trust it.

### Declined on purpose — worth keeping declined

| want | who | why it stays no |
|---|---|---|
| Open / import an already-packed mod | criticalcondition ×2, a.wonders | mod theft. **leagueofthearcane publicly cited this exact failsafe as the right design** when a third-party tool shipped without it: *"you can also take the best possible route and add failsafes, like Atelier and Project Galacta, that offload mods from their readers."* Reputational credit worth stating in the README |
| In-game config switching (CNS-style) | neko_bosu | anti-cheat risk |

---

## 12. Promises and considerations on record

| said | when | status |
|---|---|---|
| *"ill patch this up as soon as opportune"* — surrept.'s material bug | 07-28 (DM) | outstanding |
| *"if its a regression issue i can j revert whatevers wrong"* | 08-21 (DM) | outstanding; §1 is the mechanism |
| *"alr ill dm u for more details in the coming days then"* — cartbuddy | 09-11 (DM) | **never happened; his 09-13 message is still unanswered** |
| *"thanks for reporting that, ima be back on developing atelier soon"* | 09-11 (DM) | pending |
| *"gonna try to clean up atelier in one good sprint soon"* | 08-28 (DM) | pending |
| *"ill set up some unit tests"* | 08-30 | not done — and the premise (*"no one reported issues with texture modding so far"*) was already false |
| *"this is why a test suite is wise"* | 09-13 | said twice in two weeks |
| *"ill also wait till season 10 to continue development"* | 09-06 | S10 landed 09-11 |
| *"ill add support for multiple keys"* | 08-28 | **now the highest-value item in the backlog** |
| *"both issues noted"* — diiea UI quality + chopthememegod stringtables | thread | still open |
| *"gotcha, any other issues drop em in the atelier thread plz"* | 09-15 | the only bug process that exists — see §13 |

Roadmap floated but written down nowhere: broadening Atelier to other Unreal games, NTE named
(to ch3rr13, 09-10).

---

## 13. Community, docs and project health

### There is nowhere to report bugs

diiea, after an hour debugging a broken material with a.wonders in #mod-help:
**"i wish there was a place for bug reports"** (08-07).

You've told people to use the Atelier thread — once, in passing, 726 messages deep. And you
**can't pin releases**: finngmin asked, you replied *"i cant pin either, only server ops can"*.

Reports are scattered across #mod-help, #mod-general, #mod-ui, #mod-vfx, six DMs and the thread.
That fragmentation is exactly why nobody — including you — noticed that "material not found in
game paks" had four reporters, or that lobby/in-game divergence had three. **One ask to an MRM op
for a pinned post or an `#atelier-bugs` channel buys more than any fix in this report.**

### Docs are being written by users, uncoordinated

Three people asked for a guide — dovestone17, adamkk_apenas, and bachiral. who was specifically
lost. What happened instead:

- **leagueofthearcane wrote a full Master Class** — written guides plus video, in #setup-and-guide,
  including a ColorID tutorial that documents the `{AtelierPath}\_cache\dye\preview\...` path
  better than you have.
- **finngmin offered to make a video.**
- **lovefrills offered to write a beginners guide.**

Linking leagueofthearcane's guide from the README and the first-run screen costs nothing.

### Atelier is now the default recommendation

Regulars send newcomers to it instead of Unreal — norskpl (who says outright he doesn't use it),
shii604, labyrinth22, haliro, revenantreignvie, leagueofthearcane. diiea: *"most of us who do
retextures use that instead of unreal"*. labyrinth22: *"It uses less space and is quicker at
exporting"*. cartbuddy: *"i love that i can see the names for skins and heros unlike Fmodel"*.

The asymmetry that creates: those regulars field the resulting questions but can't answer
app-specific ones, so threads end in a shrug when you're not around. A bug channel fixes that too.

### Funding is two people

finngmin (PayPal) and ch3rr13 (skin gifting, twice). Your words: *"god you and finn are
singlehandedly funding this app"*. There's no public donation link anywhere.

### Standing context

- **noobmasterpro is gone, and you've taken his features over** — he left the MRM server ~07-26;
  *"hes not rly active in the rivals modding rn"* as of 09-11. **The VFX/material/dye code was
  his**, which is precisely what §4 says breaks every season, so the handover puts the
  most-broken subsystem and its least-documented code in the same pair of hands. Two consequences
  run through this report: his deferrals are now yours to re-decide (§11, *Inherited decisions*),
  and `dye.py` — his best work — turns out to already contain most of what §11a needs.
- **Atelier-Noobs** is in stasis, merged into 0.3.2. Some users are still on 0.2.3 because
  noobmasterpro recommended it as late as 07-05.
- **Asset-sharing policy**: noobmasterpro asked saturnooooooo whether Atelier-baked ID-mask
  diffuse textures fall under rule 5. Answer: don't host them in the server, use GitHub.
- **Repak X**: you offered to isolate its drag-and-drop issues and report them; saturno invited
  detailed reports. Never followed up, and Repak X's updater is now part of several users' broken
  workflows (§4).

---

## 14. What I'd do first

1. **Put the AES key in the index cache key** (`atelier/index.py:45-50`). One line. Stops a wrong
   key from poisoning the index permanently, and retires "just reinstall it" as support advice.
2. **`glob.escape()` every user-controlled path fed to `glob`** (`index.py:43`, `config.py:26/32/278`,
   `modlock.py`, `repatch.py`, `text.py`, `world.py`, `texture.py:529`), and add `[` `]` to
   `_mod_stem` (`routes.py:1928`). Confirmed user case, deterministic, small. **Make the two paks
   checks share one implementation** so Settings can never say "valid" while the prereq says
   "no pak files" (§2).
3. **Don't cache an index that produced warnings**, and surface those warnings in the UI
   (`index.py:84-85`, `103-104`).
4. **Ship the ID-mask overlay** (§11a). Five independent requesters, and `dye.py` already computes
   the per-texel region map — it's a recolour of an array you're already building. Highest
   value-per-hour item in the report.
5. **Use `enc_guid`** (`io_lib.py:59`) to support per-container keys, and fetch more than
   `mainKey` (`config.py:113`). This is §1's real fix and the thing you already promised.
6. **Fix the key-file race** (`config.py:143-153`) — one writer, and make `io_lib` re-read on change.
7. **Split the "not found in game paks" message** into absent / not-indexed / extraction-failed
   (`material.py:126` and siblings). Cheapest diagnostic win available.
8. **Add timeouts to `uat()` and the `uat_json()` readline loop**, and stop discarding worker
   stderr (`tools.py:74-102`).
9. **Wrap `_get_toc`** in the same try/except `index.py` already uses (`pak_thumb.py:53-74`).
10. **Make `/api/open_explorer` report failure** instead of returning `ok: True` after doing
   nothing (`routes.py:1720-1733`).
11. **Ask an MRM op for a bug channel or a pinned post.** Zero code, biggest signal gain.
12. **Reply to cartbuddy and open his zip** — reproducible broken mod, handed over 09-12, unanswered.

## Still open / needs live paks

- **cartbuddy's inconsistency** (§3): new-skin mods working while older material edits broke.
  Could be a skin added straight to the base paks rather than patched, or one patch pak encrypted
  and another not. Not decidable from logs — needs testing against live paks.
- Whether the Marvel_LQ root shipped and regressed or never fully shipped (§11).
- Why `global.utoc` read as a 0-byte buffer on driz's machine.
- Whether driz's concurrent Steam "verify integrity" contributed to that one log.

---

## 15. Parked: mesh editing and 3D preview

Excluded above by request, kept here so it isn't lost when you rework them as a unit.

- **Mesh edits save to `.blend` but never reach the game.** Three independent careful reporters:
  finngmin (two mods, verified edits persisted in the `.blend`, absent in lobby and in game),
  a.wonders (removals worked on one skin, not Blade; additions never applied; periodic crashes),
  ch3rr13 (edits registering only as a texture mod). The blend round-trip works; the blend→pak
  export doesn't.
- **The Atelier viewport doesn't reflect mesh edits** while texture changes do — finngmin. Your
  TODO already has *"change viewport to match modded?"*.
- **cinarette (Eesa) is a mesh modder and offered to help** on 08-16 — *"im lowkey a mesh
  modder... i can help... if need"* — right after you said you were winging it in the dark. You
  said *"hell yeahh appreciate that"* and it went nowhere. Worth taking up when this restarts.
- Requests parked with it: checkboxes for which materials import on mesh open (you proposed it),
  toggling material visibility in Blender (your idea: separate objects), post-process animbp /
  post physics (brinklebop_76102), not auto-dumping every associated texture into the sidebar
  (finngmin).
- Roadmap parked with it: cross-character part grafting with separate materials and physics,
  lobby-model support in the mesh editor.
- Your 3D-viewport notes already concede VFX/Niagara and material flow *"can't be reproduced
  faithfully, only the static emissive approximation"*. finngmin hit exactly that without knowing —
  noob's live colour-wheel preview *"didn't really work in game"*. Whenever this returns, label the
  preview as approximate in-app.
