# Atelier — everything reported in the MRM Discord

Swept 24,343 messages across 56 channels/threads of guild `1419106202511609958`,
plus 614 downloaded images/files. Sources: the full #atelier-thread (726 messages,
complete history), a guild-wide search for *Atelier* (398 hits), every message mentioning
your account (531 hits, which includes reply-pings), every mention of *clownfetus* (38),
and the full conversation around each of those rather than the matching line alone.

Every entry links to the exact message.


## Critical

### 0.3.2 R2 overwrote every existing user project
`fixed / verify` — **kadeschaos**, 2026-08-18, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1539099542690078790)  
kadeschaos confirmed all projects were wiped by the update; winterwintour hit the same thing (1539011193648185476) and hbrd_ngl lost files to it too (1548049487380095028). You pulled the release the same day. Worth confirming the fix held and that a backup step exists on update.

### Export hangs forever — mod never finishes packaging
`OPEN` — **labyrinth22**, 2026-09-12, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1548469209548456047)  
labyrinth22: "it'll initiate the process but never finish", 10+ minutes on only 7 textures, across restarts and renames; revenantreignvie confirmed "yes" independently. Re-pinged you directly at 1548474313806454886. No resolution recorded.

### Edited materials become a grey checkerboard after every season update
`partially fixed` — **diiea**, 2026-08-07, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1535287902076928010)  
diiea: "edited materials turn into a grey checkerboard pattern each season update" — a.wonders hit the same and asked outright whether materials can be made update-proof (1548795817073180806). labyrinth22 later reported the patch function in the newest build fixed one case, so partially addressed.

### ROOT CAUSE: spaces in a path send Explorer to Documents
`OPEN — has a diagnosis` — **chopthememegod**, 2026-08-16, #💬︱mod-general · [jump](https://discord.com/channels/1419106202511609958/1419106204373880955/1538538248098422844)  
chopthememegod diagnosed it: "if you export a mod and there are spaces it sends you to the documents folder — this also seems to apply for viewing textures in explorer." This explains the long-running 'Open in Explorer' complaints from xynoah (1522696230759825538), muimifu (1524289532365770854) and ghostex101 (1546128491878285323). Quote/escape the path.


## Bugs

### UI mods come out lower quality than Unreal
`noted` — **diiea**, 2026-08-24, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1541350850830663780)  
diiea, side-by-side screenshot: left Atelier, right Unreal. You acknowledged it.

### UI mod packing produces a 'manifest missing' error
`OPEN` — **leagueofthearcane**, 2026-09-14, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1549175558557011969)  
leagueofthearcane built the same mod twice — Atelier's copy errored, the Unreal copy didn't. Likely the same packing path as the UI quality issue.

### Ability icon recolors get replaced by the MR logo in game
`OPEN` — **leagueofthearcane**, 2026-09-15, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1549224452242542592)  
leagueofthearcane: Warlock's soul bond and similar; the same mod built in UE works. Still open as of 09-15.

### "No pak files" despite every path validating in settings
`OPEN` — **everikreal**, 2026-09-13, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1548492908074762421)  
everikreal, right after a game update. You replied that a lot was broken by the new update.

### "Edit failed: material not found" on Epic Games installs
`regression?` — **kadeschaos**, 2026-07-02, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1522374095852011671)  
kadeschaos on 0.2.3; noobmasterpro traced it to the Epic install path and said "I swore we fixed this". kyr.xem hit the same wording later (1548325131624120441).

### Marvel_LQ missing from the browse tree
`OPEN` — **fawnls**, 2026-08-22, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1540805205040566403)  
fawnls had no Marvel_LQ node, which silently breaks UI mods since they need the LQ copy. skyfallx_x had asked for exactly these paths back in June (1520182837934821456).

### Plugins path (MarvelGAS ability icons) not reachable
`partially there` — **shafsta**, 2026-09-06, #📱︱mod-ui · [jump](https://discord.com/channels/1419106202511609958/1419106204512424001/1546219020783718440)  
shafsta needed Marvel/Plugins/MarvelGAS/... for team-up ability icons; wendall555 asked the same in July (1526603800457117919). shafsta eventually found them under a different name in Atelier than in FModel, so at minimum the path naming diverges confusingly.

### Project thumbnails all blank
`OPEN` — **diiea**, 2026-09-12, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1548185116956827818)  
diiea noticed the regression; finngmin and a.wonders confirmed it had been that way a while. You said it should reflect the most recent edited item.

### Icons break whenever a texture is replaced
`OPEN` — **diiea**, 2026-09-17, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1550192065831247986)  
diiea. kadeschaos found the workaround: switch project and switch back — so it's a refresh bug, not data loss.

### String tables don't show up in game
`noted` — **chopthememegod**, 2026-08-25, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1541855276326592685)  
chopthememegod. You noted it.

### Mesh edits show the base model in game on some skins
`OPEN — alpha` — **a.wonders**, 2026-08-21, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1540345749915566130)  
a.wonders: removals worked on C&D Twilight Duo but not Blade; additions never applied; game crashed periodically with mesh edits. ch3rr13 reproduced the whole pattern (1543554830898036797) — her mod only ever registered as a texture mod. You called the current mesh method 'very ai-generated'.

### Exported skin mod flickers in game and breaks configs
`workaround` — **boncchickenx**, 2026-07-06, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1523746455712694272)  
boncchickenx; noobmasterpro fixed it by changing texture settings, so possibly an export default.

### PNG imports turn grey or don't show
`OPEN` — **labyrinth22**, 2026-08-11, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1536852341582602343)  
labyrinth22 recommended re-saving as JPEG as a workaround. Possibly related to the checkerboard bug.

### Material loading hangs/slow after first load
`OPEN` — **psycheduck**, 2026-07-06, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1523826318213644529)  
psycheduck: "the first time i had to load materials it was instant but every time after was a chore" — suggests the cache helps once then stops. "this happens a lot".

### Texture extracted at 4x4 pixels
`OPEN` — **finngmin**, 2026-09-18, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1550396254566228000)  
finngmin; noobmasterpro says it happens with non-power-of-two textures.

### Eyedropper in material colour editing hangs the app
`branch in stasis` — **kadeschaos**, 2026-07-09, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1524882123016765480)  
kadeschaos had to kill it via Task Manager. Was on the Atelier-Noobs branch.

### 3D view showed the modded mesh instead of vanilla
`fixed` — **.clownfetus**, 2026-07-02, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1522249660633190560)  
skyfallx_x. You fixed it — it was scanning ~mods\ as well as Paks\.

### 0.1.6 packed only the top texture
`fixed` — **.clownfetus**, 2026-06-30, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1521366349908283442)  
finngmin; you found and shipped the fix in 0.1.7.

### Auto-updater silently not running
`OPEN` — **skyfallx_x**, 2026-06-27, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1520412002432974988)  
skyfallx_x had to install from GitHub manually; pushingpetals independently couldn't find any update path in the UI. You said "might be bugged".

### Textures in patch paks not found on export
`OPEN — recurring` — **skyfallx_x**, 2026-06-26, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1520172580420452423)  
skyfallx_x. You diagnosed it as a patch-pak issue and noted only pakchunkCharacter and Patch_-Windows*_P were hooked; xz4nt argued loading all paks costs nothing. Same root cause as surrept.'s missing Luna skin (1531121429662273586) and skyfallx_x's missing Widow skin (1520100062829482036).

### Non-C: / HDD installs misbehave
`OPEN` — **muimifu**, 2026-07-06, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1523483221189333102)  
muimifu asked; you said one person reported it buggy. xynoah's image opening only started working after moving to the main drive. Overlaps with the spaces-in-path root cause.

### Repatcher stopped working
`OPEN` — **a.wonders**, 2026-09-17, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1550135621912236085)  
a.wonders, unanswered.

### Fresh install errors despite correct game path
`OPEN` — **driz._.**, 2026-08-21, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1540429063913472201)  
driz._. — you asked for logs.


## Feature requests

### Search in the projects screen
`requested 09-18` — **shafsta**, 2026-09-18, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1550486297418801153)  
shafsta. noobmasterpro: "ask clown."

### Multi-select on edited assets for deletion
`partial` — **winterwintour**, 2026-08-19, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1539762262594822275)  
winterwintour. You shipped Shift-click X in 0.3.3 as a partial answer; bulk select is still not there.

### Persist the hex/255/float toggle
`OPEN` — **taylorlinnay**, 2026-07-16, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1527369530861686874)  
taylorlinnay — hex paste already works but the mode resets every time. noobmasterpro: "it doesn't save".

### Disable the colour overlay entirely for chroma retextures
`accepted` — **finngmin**, 2026-08-28, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1542999697369595934)  
finngmin, so retextures can be painted directly instead of fighting the dye system. You replied "i will try thats a good suggestion" — the single most-repeated workflow request.

### Audio modding
`backlog` — **pushingpetals**, 2026-07-15, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1526791319702470726)  
pushingpetals, asked twice. noobmasterpro: "on the bucket list".

### Nameplate support
`OPEN` — **winterwintour**, 2026-07-19, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1528496559887487076)  
winterwintour found the nameplate node empty; ghostex101 and diiea later hunted for the same files and needed shafsta to point them at three separate paths. Worth surfacing all three in-app.

### KO prompt modding
`declined-ish` — **winterwintour**, 2026-07-14, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1526674465826537542)  
winterwintour. noobmasterpro: "Atelier cant do everything".

### Bulk edit for curves / VFX
`OPEN` — **boncchickenx**, 2026-07-04, #💥︱mod-vfx · [jump](https://discord.com/channels/1419106202511609958/1419106204512424002/1523098845372878990)  
boncchickenx. You: "no mass edit features yet". This is the specific gap you named as the reason to send people to Saturn's editor, and leagueofthearcane cites it in his guides too.

### UV/ID-mask overlay showing which texture region is which
`declined` — **muimifu**, 2026-07-06, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1523575305011200040)  
muimifu asked for a Blender-style UV map view; you said no. norskpl independently described exporting UV maps from Blender as his whole recolour workflow, so there's real demand.

### Extend the dyed-texture download to the other texture types
`noted` — **chopthememegod**, 2026-09-13, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1548775604856291430)  
chopthememegod. You noted it and credited the feature to noobmasterpro.

### Remove a texture outright (not just replace it)
`workaround` — **pushingpetals**, 2026-09-16, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1549599709000368262)  
pushingpetals, e.g. dropping Gorr's EquipVFX_D goo. Answered with 'make it transparent'.

### Checkboxes for which materials to import on mesh import
`your own TODO` — **.clownfetus**, 2026-08-20, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1540085955267133480)  
You proposed it to finngmin and ch3rr13 and said it needs a broader material-handling pass.

### Post-process animation blueprint / post physics editing
`OPEN` — **brinklebop_76102**, 2026-08-05, #💬︱mod-general · [jump](https://discord.com/channels/1419106202511609958/1419106204373880955/1534666276599894248)  
brinklebop_76102 — "Back to 15 minute exports it seems." Related to neko_bosu's original in-game config switch request (1520030517574242445), which was declined over anti-cheat risk.

### Open/import an already-packed mod
`declined by design` — **criticalcondition_89977**, 2026-06-27, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1520475042197143675)  
criticalcondition asked twice; a.wonders repeated it ("too bad atelier wont let us open mods directly"). Declined deliberately over mod theft — and leagueofthearcane later cited that exact failsafe as the right design when a third-party tool did allow it (1549887853041942599). Worth keeping as a stated principle.

### More asset roots (UI/Textures, Marvel_LQ, Plugins)
`partial` — **skyfallx_x**, 2026-06-26, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1520182837934821456)  
skyfallx_x started it; fawnls and shafsta hit the consequences later. Partly shipped.


## Themes worth acting on

### Users want somewhere to file bugs
`actionable` — **diiea**, 2026-08-07, #🔎︱mod-help · [jump](https://discord.com/channels/1419106202511609958/1419106204373880956/1535345616375390321)  
diiea: "i wish there was a place for bug reports" — said while she and a.wonders debugged a broken material for an hour in #mod-help. You later started telling people to use the Atelier thread (1549308461130219724-ish), but there's no channel and nothing pinned. finngmin also asked you to pin releases and you said you can't — only server ops can.

### Repeated demand for a video guide / docs
`community-solved` — **dovestone17**, 2026-08-30, #atelier-thread · [jump](https://discord.com/channels/1419106202511609958/1519707061854670908/1543420772679290963)  
dovestone17, adamkk_apenas (1539710700266594394) and bachiral. (1539912192797843468, specifically lost on the Blender side) all asked. leagueofthearcane filled the gap himself with a written+video Master Class in #setup-and-guide, and finngmin offered to make one. This is community-solved but undocumented by you.

### A more efficient texture-replace flow was removed
`regression` — **noobmasterpro**, 2026-06-26, #💬︱mod-general · [jump](https://discord.com/channels/1419106202511609958/1419106204373880955/1519879647460855950)  
noobmasterpro: "I preferred my method of left click on texture -> browse files and upload file. I don't know why we removed it since it was far more efficient than the current method." Worth revisiting.


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
