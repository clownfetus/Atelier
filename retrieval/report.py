"""Emit findings.jsonl + REPORT.md from the curated set of Atelier reports."""
import json, sys, pathlib
sys.path.insert(0, "retrieval")
from store import Store, ROOT

GUILD = "1419106202511609958"
st = Store()
names = {str(c["id"]): c["name"] for c in json.loads((ROOT / "channels.json").read_text())}
names["1519707061854670908"] = "atelier-thread"
names["1542171855807315978"] = "setup-and-guide"
names["1522768498642649128"] = "atelier-noobs"

def link(mid):
    m = st.by_id.get(str(mid))
    cid = m["channel_id"] if m else ""
    return f"https://discord.com/channels/{GUILD}/{cid}/{mid}"

def who(mid):
    m = st.by_id.get(str(mid))
    return (m.get("author_nick") or m.get("author") or "?") if m else "?"

def when(mid):
    m = st.by_id.get(str(mid))
    return m["ts"][:10] if m else ""

def chan(mid):
    m = st.by_id.get(str(mid))
    return names.get(str(m["channel_id"]), "?") if m else "?"

# ---- curated findings -------------------------------------------------
# (id, title, detail, status)
BUGS_CRIT = [
 ("1539099542690078790", "0.3.2 R2 overwrote every existing user project",
  "kadeschaos confirmed all projects were wiped by the update; winterwintour hit the same thing "
  "(1539011193648185476) and hbrd_ngl lost files to it too (1548049487380095028). You pulled the "
  "release the same day. Worth confirming the fix held and that a backup step exists on update.", "fixed / verify"),
 ("1548469209548456047", "Export hangs forever — mod never finishes packaging",
  "labyrinth22: \"it'll initiate the process but never finish\", 10+ minutes on only 7 textures, across "
  "restarts and renames; revenantreignvie confirmed \"yes\" independently. Re-pinged you directly at "
  "1548474313806454886. No resolution recorded.", "OPEN"),
 ("1535287902076928010", "Edited materials become a grey checkerboard after every season update",
  "diiea: \"edited materials turn into a grey checkerboard pattern each season update\" — a.wonders hit "
  "the same and asked outright whether materials can be made update-proof (1548795817073180806). "
  "labyrinth22 later reported the patch function in the newest build fixed one case, so partially addressed.", "partially fixed"),
 ("1538538248098422844", "ROOT CAUSE: spaces in a path send Explorer to Documents",
  "chopthememegod diagnosed it: \"if you export a mod and there are spaces it sends you to the documents "
  "folder — this also seems to apply for viewing textures in explorer.\" This explains the long-running "
  "'Open in Explorer' complaints from xynoah (1522696230759825538), muimifu (1524289532365770854) and "
  "ghostex101 (1546128491878285323). Quote/escape the path.", "OPEN — has a diagnosis"),
]

BUGS = [
 ("1541350850830663780", "UI mods come out lower quality than Unreal",
  "diiea, side-by-side screenshot: left Atelier, right Unreal. You acknowledged it.", "noted"),
 ("1549175558557011969", "UI mod packing produces a 'manifest missing' error",
  "leagueofthearcane built the same mod twice — Atelier's copy errored, the Unreal copy didn't. "
  "Likely the same packing path as the UI quality issue.", "OPEN"),
 ("1549224452242542592", "Ability icon recolors get replaced by the MR logo in game",
  "leagueofthearcane: Warlock's soul bond and similar; the same mod built in UE works. Still open as of 09-15.", "OPEN"),
 ("1548492908074762421", "\"No pak files\" despite every path validating in settings",
  "everikreal, right after a game update. You replied that a lot was broken by the new update.", "OPEN"),
 ("1522374095852011671", "\"Edit failed: material not found\" on Epic Games installs",
  "kadeschaos on 0.2.3; noobmasterpro traced it to the Epic install path and said \"I swore we fixed this\". "
  "kyr.xem hit the same wording later (1548325131624120441).", "regression?"),
 ("1540805205040566403", "Marvel_LQ missing from the browse tree",
  "fawnls had no Marvel_LQ node, which silently breaks UI mods since they need the LQ copy. "
  "skyfallx_x had asked for exactly these paths back in June (1520182837934821456).", "OPEN"),
 ("1546219020783718440", "Plugins path (MarvelGAS ability icons) not reachable",
  "shafsta needed Marvel/Plugins/MarvelGAS/... for team-up ability icons; wendall555 asked the same in July "
  "(1526603800457117919). shafsta eventually found them under a different name in Atelier than in FModel, "
  "so at minimum the path naming diverges confusingly.", "partially there"),
 ("1548185116956827818", "Project thumbnails all blank",
  "diiea noticed the regression; finngmin and a.wonders confirmed it had been that way a while. You said it "
  "should reflect the most recent edited item.", "OPEN"),
 ("1550192065831247986", "Icons break whenever a texture is replaced",
  "diiea. kadeschaos found the workaround: switch project and switch back — so it's a refresh bug, not data loss.", "OPEN"),
 ("1541855276326592685", "String tables don't show up in game", "chopthememegod. You noted it.", "noted"),
 ("1540345749915566130", "Mesh edits show the base model in game on some skins",
  "a.wonders: removals worked on C&D Twilight Duo but not Blade; additions never applied; game crashed "
  "periodically with mesh edits. ch3rr13 reproduced the whole pattern (1543554830898036797) — her mod "
  "only ever registered as a texture mod. You called the current mesh method 'very ai-generated'.", "OPEN — alpha"),
 ("1523746455712694272", "Exported skin mod flickers in game and breaks configs",
  "boncchickenx; noobmasterpro fixed it by changing texture settings, so possibly an export default.", "workaround"),
 ("1536852341582602343", "PNG imports turn grey or don't show",
  "labyrinth22 recommended re-saving as JPEG as a workaround. Possibly related to the checkerboard bug.", "OPEN"),
 ("1523826318213644529", "Material loading hangs/slow after first load",
  "psycheduck: \"the first time i had to load materials it was instant but every time after was a chore\" — "
  "suggests the cache helps once then stops. \"this happens a lot\".", "OPEN"),
 ("1550396254566228000", "Texture extracted at 4x4 pixels",
  "finngmin; noobmasterpro says it happens with non-power-of-two textures.", "OPEN"),
 ("1524882123016765480", "Eyedropper in material colour editing hangs the app",
  "kadeschaos had to kill it via Task Manager. Was on the Atelier-Noobs branch.", "branch in stasis"),
 ("1522249660633190560", "3D view showed the modded mesh instead of vanilla",
  "skyfallx_x. You fixed it — it was scanning ~mods\\ as well as Paks\\.", "fixed"),
 ("1521366349908283442", "0.1.6 packed only the top texture",
  "finngmin; you found and shipped the fix in 0.1.7.", "fixed"),
 ("1520412002432974988", "Auto-updater silently not running",
  "skyfallx_x had to install from GitHub manually; pushingpetals independently couldn't find any update path "
  "in the UI. You said \"might be bugged\".", "OPEN"),
 ("1520172580420452423", "Textures in patch paks not found on export",
  "skyfallx_x. You diagnosed it as a patch-pak issue and noted only pakchunkCharacter and Patch_-Windows*_P "
  "were hooked; xz4nt argued loading all paks costs nothing. Same root cause as surrept.'s missing Luna skin "
  "(1531121429662273586) and skyfallx_x's missing Widow skin (1520100062829482036).", "OPEN — recurring"),
 ("1523483221189333102", "Non-C: / HDD installs misbehave",
  "muimifu asked; you said one person reported it buggy. xynoah's image opening only started working after "
  "moving to the main drive. Overlaps with the spaces-in-path root cause.", "OPEN"),
 ("1550135621912236085", "Repatcher stopped working", "a.wonders, unanswered.", "OPEN"),
 ("1540429063913472201", "Fresh install errors despite correct game path", "driz._. — you asked for logs.", "OPEN"),
]

FEATURES = [
 ("1550486297418801153", "Search in the projects screen", "shafsta. noobmasterpro: \"ask clown.\"", "requested 09-18"),
 ("1539762262594822275", "Multi-select on edited assets for deletion",
  "winterwintour. You shipped Shift-click X in 0.3.3 as a partial answer; bulk select is still not there.", "partial"),
 ("1527369530861686874", "Persist the hex/255/float toggle",
  "taylorlinnay — hex paste already works but the mode resets every time. noobmasterpro: \"it doesn't save\".", "OPEN"),
 ("1542999697369595934", "Disable the colour overlay entirely for chroma retextures",
  "finngmin, so retextures can be painted directly instead of fighting the dye system. You replied \"i will try "
  "thats a good suggestion\" — the single most-repeated workflow request.", "accepted"),
 ("1526791319702470726", "Audio modding", "pushingpetals, asked twice. noobmasterpro: \"on the bucket list\".", "backlog"),
 ("1528496559887487076", "Nameplate support",
  "winterwintour found the nameplate node empty; ghostex101 and diiea later hunted for the same files and "
  "needed shafsta to point them at three separate paths. Worth surfacing all three in-app.", "OPEN"),
 ("1526674465826537542", "KO prompt modding", "winterwintour. noobmasterpro: \"Atelier cant do everything\".", "declined-ish"),
 ("1523098845372878990", "Bulk edit for curves / VFX",
  "boncchickenx. You: \"no mass edit features yet\". This is the specific gap you named as the reason to send "
  "people to Saturn's editor, and leagueofthearcane cites it in his guides too.", "OPEN"),
 ("1523575305011200040", "UV/ID-mask overlay showing which texture region is which",
  "muimifu asked for a Blender-style UV map view; you said no. norskpl independently described exporting UV "
  "maps from Blender as his whole recolour workflow, so there's real demand.", "declined"),
 ("1548775604856291430", "Extend the dyed-texture download to the other texture types",
  "chopthememegod. You noted it and credited the feature to noobmasterpro.", "noted"),
 ("1549599709000368262", "Remove a texture outright (not just replace it)",
  "pushingpetals, e.g. dropping Gorr's EquipVFX_D goo. Answered with 'make it transparent'.", "workaround"),
 ("1540085955267133480", "Checkboxes for which materials to import on mesh import",
  "You proposed it to finngmin and ch3rr13 and said it needs a broader material-handling pass.", "your own TODO"),
 ("1534666276599894248", "Post-process animation blueprint / post physics editing",
  "brinklebop_76102 — \"Back to 15 minute exports it seems.\" Related to neko_bosu's original in-game config "
  "switch request (1520030517574242445), which was declined over anti-cheat risk.", "OPEN"),
 ("1520475042197143675", "Open/import an already-packed mod",
  "criticalcondition asked twice; a.wonders repeated it (\"too bad atelier wont let us open mods directly\"). "
  "Declined deliberately over mod theft — and leagueofthearcane later cited that exact failsafe as the right "
  "design when a third-party tool did allow it (1549887853041942599). Worth keeping as a stated principle.", "declined by design"),
 ("1520182837934821456", "More asset roots (UI/Textures, Marvel_LQ, Plugins)",
  "skyfallx_x started it; fawnls and shafsta hit the consequences later. Partly shipped.", "partial"),
]

META = [
 ("1535345616375390321", "Users want somewhere to file bugs",
  "diiea: \"i wish there was a place for bug reports\" — said while she and a.wonders debugged a broken "
  "material for an hour in #mod-help. You later started telling people to use the Atelier thread "
  "(1549308461130219724-ish), but there's no channel and nothing pinned. finngmin also asked you to pin "
  "releases and you said you can't — only server ops can.", "actionable"),
 ("1543420772679290963", "Repeated demand for a video guide / docs",
  "dovestone17, adamkk_apenas (1539710700266594394) and bachiral. (1539912192797843468, specifically lost on "
  "the Blender side) all asked. leagueofthearcane filled the gap himself with a written+video Master Class in "
  "#setup-and-guide, and finngmin offered to make one. This is community-solved but undocumented by you.", "community-solved"),
 ("1519879647460855950", "A more efficient texture-replace flow was removed",
  "noobmasterpro: \"I preferred my method of left click on texture -> browse files and upload file. I don't "
  "know why we removed it since it was far more efficient than the current method.\" Worth revisiting.", "regression"),
]

def block(title, rows):
    out = [f"\n## {title}\n"]
    for mid, head, detail, status in rows:
        out.append(f"### {head}")
        out.append(f"`{status}` — **{who(mid)}**, {when(mid)}, #{chan(mid)} · [jump]({link(mid)})  ")
        out.append(f"{detail}\n")
    return "\n".join(out)

total = sum(len(v) for v in st.by_channel.values())
media = len(list((ROOT / "attachments").rglob("*"))) if (ROOT / "attachments").exists() else 0

md = [f"""# Atelier — everything reported in the MRM Discord

Swept {total:,} messages across {len(st.by_channel)} channels/threads of guild `{GUILD}`,
plus {media} downloaded images/files. Sources: the full #atelier-thread (726 messages,
complete history), a guild-wide search for *Atelier* (398 hits), every message mentioning
your account (531 hits, which includes reply-pings), every mention of *clownfetus* (38),
and the full conversation around each of those rather than the matching line alone.

Every entry links to the exact message.
"""]
md.append(block("Critical", BUGS_CRIT))
md.append(block("Bugs", BUGS))
md.append(block("Feature requests", FEATURES))
md.append(block("Themes worth acting on", META))
md.append("""
## Against your current TODO.md

Already tracked there: the material regressions (Lumi/diz), A Wonders' mesh report — which is
the same message this sweep surfaces — the stringtable issue (you have it under GigaWheezer;
the report in-server is from chopthememegod) and dia's UI-quality issue.

Not in TODO.md and worth adding: the export hang, the spaces-in-path root cause, the missing
Marvel_LQ and Plugins roots, the UI-pack manifest error, the MR-logo icon substitution, "no pak
files" after updates, the Epic-install "material not found", the silent auto-updater, patch-pak
skins not appearing, blank project thumbnails, icons breaking on texture replace, PNG imports
going grey, material-load slowness after the first load, and the repatcher. On the feature side:
projects search, persisting the hex toggle, disabling the colour overlay, bulk curve editing,
nameplates, audio, and post-physics.

Two non-code items: people have nowhere to file bugs (diiea said so outright) and you can't pin
releases in the thread — both need a server op, and both are cheap wins.
""")
(pathlib.Path("retrieval/REPORT.md")).write_text("\n".join(md), encoding="utf-8")

with (ROOT / "findings.jsonl").open("w", encoding="utf-8") as fh:
    for cat, rows in [("critical", BUGS_CRIT), ("bug", BUGS), ("feature", FEATURES), ("meta", META)]:
        for mid, head, detail, status in rows:
            fh.write(json.dumps({"msg": mid, "tag": cat, "why": head, "status": status,
                                 "channel": chan(mid), "author": who(mid), "date": when(mid),
                                 "url": link(mid)}, ensure_ascii=False) + "\n")
print(f"REPORT.md: {len(BUGS_CRIT)+len(BUGS)+len(FEATURES)+len(META)} findings")
print(f"corpus: {total} messages, {media} media files")
