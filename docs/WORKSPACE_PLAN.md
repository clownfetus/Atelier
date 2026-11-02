# Atelier — workspace implementation plan

Oct 29, 2026

How to turn the first-recolour workspace prototype into the real app: what already exists, what
has to be proven first, and the order to build the rest. The prototype is the design reference:
<https://claude.ai/artifact/BTC3ZCn4QLqSReeX8L6f8M> (version 4).

The milestone it is built around: **someone who has never modded Marvel Rivals opens Atelier and
installs their first recolour without watching a tutorial.**

Effort uses TRIAGE.md's scale: Trivial (an afternoon) < Small < Medium < Large.

---

## The short version

Feasible, and mostly assembly of parts the app already has. The 3D viewport already picks parts,
verifies which material draws them, compares against the original, recolours dye regions live and
installs with rollback. What is missing is the **shell** (character-first workspace with Your mod
docked below), a **friendly layer of names** over raw materials and dye regions, **edit history**,
and the **ink moments**.

Three questions decide how much of that is cheap and how much is not, so they come first as
spikes (Phase 0). Nothing in Phases 1–5 should start until they have answers.

---

## What the app already has

| Prototype piece | In the app today | Gap |
|---|---|---|
| Click a part of the character | `viewport-inspection.js` raycasts the model; `assembly-data.js` `modelSections` / `hitSection` map hits to sections | None for picking |
| Honest part mapping | `verifiedBinding` accepts only package-import bindings; name matches get `bindingNotice` | Friendly names ("Hair", "Cape") over material slots |
| Areas of a part | Dye system (`atelier/handlers/dye.py`): ColorID mask, Regions 1–7, `dye_info`, `region_overlay` | Region names; regions are numbered |
| Live recolour on the model | `viewport.js` `dyeRebakeMesh`: 160 ms debounce, `/api/dye_preview` at 1024, texture swapped onto the mesh | Latency and fidelity unmeasured (Spike 1) |
| Colour editing and save | Viewport material editor (`colorField`), `/api/material_save`, `reset_material` | Sets, named colours, one-click areas |
| Compare with original | Viewport comparison modes: edited, original, wipe | Wire to a single switch |
| Rotate and zoom | OrbitControls | None |
| Replace texture, open in editor | Texture replace flow; `/api/texture_png` prefers the edited PNG | Move into the Texture tab |
| Part thumbnails | `captureModPoster` renders the viewport to an image | Per-section framing |
| Install to game | `_install_to_mods` with verification and rollback; `/api/check_mod_conflict` | None |
| Review moment and ink-well | Export review with the Krackle ink-well (`gui/motion/ink-well.js`) | Entry from the dock |
| Heroes, costumes, projects | `roster.js`, `catalogue.js`, the Projects screen with portfolio ink | Route into the workspace |
| Ink flights | `gui/motion/import-ink.js`, `project-ink.js`, the moment claim, `AtelierMotionPolicy` | A pin → dock flight and the halftone reveal |
| Undo and redo | Only the project-trash undo toast in `app.js` | An edit history (new) |

---

## Phase 0 — spikes

Each spike answers one question with a number, has a pass bar, and says what happens if it fails.
Run them against installed game assets with the packaged mesh tool: the dev server can't decode
meshes, so a fixture run proves nothing here.

### Spike 1 — Is live recolour fast and faithful enough?

The editor's promise is "click a colour, see it on Storm". Today every region edit re-bakes a
1024 texture on the server.

- **Measure** click-to-new-texture time for a set (all regions of a material at once) and for a
  single area, on three skins, cold and warm. Note the GPU and CPU.
- **Compare** the baked result against in-game screenshots for the same colours on the same
  three skins. Today the hue-correct composite is verified against the game on one skin
  (1060300).
- **Pass:** a set lands in **≤ 400 ms** warm, and colours match the game closely enough that a
  newcomer would not be surprised in-game.
- **If too slow:** port `composite()` to a three.js shader (ColorID alpha → region index →
  parameters) and keep the server bake for export. Medium. The halftone reveal hides up to about
  half a second either way.
- **If unfaithful:** fix the composite before building anything on it. The workspace's
  forgiveness depends on the preview telling the truth.

Effort: Small.

**Result (Oct 29):** see [dye-latency-spike-2026-10-29.md](dye-latency-spike-2026-10-29.md).
Warm clicks take 500–550 ms as shipped and about 300–330 ms with three small fixes, so a shader
port is no longer a prerequisite. Fidelity has not been checked in-game. Reading materials has
two faults: a native reader that sometimes starts unable to read some materials (it no longer
caches those empty results, but the root cause is open), and UAssetTool JSON with no properties.
The second was an out-of-date mapping after the Oct 29 patch: saves work with the current one,
and since Nov 2 a stale mapping is refused with a reason instead of silently dropping edits. No current material inherits its dye from a parent, so dye checks
read only the material itself. With a trusted reader, 186 of 674 skins (28%) dye, and 40% of sampled costumes
have at least one dyeable material.

### Spike 2 — How many skins get friendly part names from rules alone?

- **Script** over the catalogue: for each skin, list mesh material slots and classify them with
  name rules (Body, Hair, Head, Cape, Cloth, Weapon, Equip, Eye, FX). Record which are dyeable and
  how many regions each uses.
- **Pass:** at least 80% of the 30 most-modded skins get three or more named parts, with the rest
  falling back to the material name, labelled as such.
- **If not:** a curated `parts.json` per skin, built with the Assembly view. Budget it per skin,
  starting with the most-modded heroes.
- Also answer: **what share of costume materials are dyeable at all?** Non-dyeable parts can only
  offer the Texture tab and base tints, and the editor has to say so plainly.

Effort: Small.

**Result (Nov 1):** see [parts-naming-spike-2026-11-01.md](parts-naming-spike-2026-11-01.md).
Passes as written, fails in practice: 26 of the 30 most-modded skins get three or more named
parts, but only from Body, Head, Eyes, Hair and Teeth. The outfit is `Equip_01`–`Equip_11`, 36%
of all visible slots and 71% of the ones that dye; without the anatomy names 1 of 30 passes.
Curating the top 30 means naming 103 Equip materials. None of the 30 dyes: no default costume has
a dye mask, and three quarters of the skins that dye are material-only colour variants. 11.5% of
costume materials dye.

### Spike 3 — What can dye regions honestly be called?

Regions are numbered 1–7 and nothing in the files names them. The prototype's "Main / Shadow /
Belt" were invented.

- **Try** two policies on five skins:
  - **(a)** "Area 1…N", with the region lit on the model while hovered (`region_overlay` already
    paints regions).
  - **(b)** Inferred names from where a region sits on the part plus how much of it there is
    (largest = Main), shown as suggestions the user can rename.
- **Decide** one policy. Curated names can come later for top skins without changing the UI.
- **Colour sets** need a role per region (main, shadow, accent). Under (a), roles follow region
  area: largest is main, and so on. Write down which one ships.

Effort: Small.

**Result (Nov 1):** see [dye-regions-spike-2026-11-01.md](dye-regions-spike-2026-11-01.md).
Policy (a) ships: areas numbered largest first, each with a swatch of its current colour, lit on
the model on hover. Regions are patterns (stripes, trims, panels) spread over the body, so names
from where they sit repeat for 39 of 92 visible regions on five dye skins, and colour names repeat
for 55 of 92 ("Black", "Charcoal"). Colour sets take roles by size: largest is main. A region
number means different things on different parts of one skin, so areas stay per part.
**Decided (Nov 1): the words.** A region is an **area** ("Area 1", "Area 2"). A colour set, a
whole recolour of the skin saved under a name, is a **chroma**, as in League of Legends and
Valorant.

### Decisions to make (owner)

1. **Home.** Does the character workspace become the landing view, with the file library as
   "Explore game assets", or sit beside the library as a mode? The prototype assumes the former.
   **Decided (Nov 1): neither; Atelier opens on Projects.** The last opened project is the
   largest thing on the page and one click from its workspace; the rest of the portfolio sits
   below it. The workspace is where a project opens, not the landing view, and the file library
   stays reachable as it is today. With no projects yet, the same spot holds the way in for a
   first recolour (pick a hero and costume, land in the workspace), so the milestone's newcomer
   still starts in one click.
2. **Non-dye materials.** Do they get sets through base tint, or only the Texture tab?
   **Decided (Nov 1): Texture tab only.** A base tint washes the whole texture in one colour,
   which is the crude overlay the current editor already has. Non-dye parts are recoloured in
   the texture instead, with blend modes (Phase 3). Every default costume is non-dye, so this is
   the path most first recolours take.
3. **Scope of the first release.** All heroes from day one with fallback names, or a curated
   launch set?
   **Decided (Nov 1): all heroes, automatic names only; no hand-naming.** The game numbers
   costume pieces (`Equip_01`…), and the automatic names come from where a piece sits on the
   body, read from the bones its vertices follow ("Torso piece", "Left arm piece"). On the top
   30's 113 costume pieces they are right for 64%, roughly right for 25% and wrong for 11%, and
   agree with 96% of the slots the game does name. That is enough because names are only labels:
   people find a part by selecting it on the model (Phase 3's box select), and can rename it.
   Hand-naming the top 30 was the earlier decision, dropped once box select tested well; a
   material often holds several garments (one of Bruce Banner's holds his shirt, trousers, shoes
   and glasses frames), so one name per material was never going to fit. See
   [parts-naming-spike-2026-11-01.md](parts-naming-spike-2026-11-01.md).

---

## Phase 1 — Workspace shell and the Your mod dock

The character stays on screen; the mod collects below it.

- Mount the viewport as the workspace stage instead of an overlay, keeping one renderer and the
  shared `texCache` (never per-open texture loads; WebView2's GPU chokes on those).
- Your mod dock is derived from project state: edited materials and textures, grouped by part.
  Each slot has a name, before → after swatch and Restore, and the count drop. The project's
  autosave already exists; surface it as the saved dot.
- Atelier opens on Projects (Decision 1): the last opened project leads the page as a large card,
  one click into its workspace. An empty portfolio shows Start a recolour in that place.
- **Review & install** opens the existing export review; install keeps `_install_to_mods`.
- The library, Edit All import and Projects stay reachable unchanged.

**Done when** Atelier opens on Projects with the last project one click away, a project opened
from Projects lands in the workspace, edits made in the existing
material editor appear in the dock, and Review & install installs through the current path.
Effort: Medium–Large. Gate: no GPU stalls after twenty skin switches in one session.

## Phase 2 — Parts list and stage tools

- Parts list from Spike 2: named parts, then **Extra parts** (weapons, FX) shown isolated with
  Back to character. Unverified bindings keep their notice.
- Thumbnails rendered per section by framing its bounding box, cached per skin and costume.
- Under the model: a Compare original switch (viewport comparison), Rotate and Zoom to part
  (OrbitControls target), Undo and Redo (Phase 3 fills them in).
- The Smalt drop pin, anchored to the selected section's projected centre each frame.

**Done when** every part on three test skins is selectable from the list or the model, and
Compare matches the existing original view. Effort: Medium.

## Phase 3 — The colour editor and edit history

- Colour and Texture tabs. Colour: areas (dye regions, numbered largest first with a swatch and
  lit on hover, per Spike 3; undyed texels say so in one line), the current colour
  with its pigment name, the picker, chromas (colour sets, mapped onto areas by role), and
  Restore original. Texture:
  Replace texture and Open in editor, moved from where they live now.
- **Recolour in the texture, with blend modes.** Non-dye parts (every default costume) are
  recoloured by baking colour into the part's texture, not by tinting the material: today's
  editor sets the base colour, which multiplies over the whole map (`retint` in `viewport.js`).
  Pick a colour and a blend mode (Multiply, Screen, Overlay, Soft light, Hue, Colour) with a
  strength, limited to the selected area and, optionally, to a range of its existing colours,
  so a red-and-white jacket can turn blue-and-white. The result is an ordinary edited PNG through
  the texture pipeline, so it ships, undoes and compares like any texture edit. The modes have to
  be baked: the game's shader applies a material colour one fixed way, so a blend mode on the
  material itself would show in Atelier and not in the game.
- **Box select on the model.** Drag a box over the model to pick what to recolour. Atelier
  redraws the view off-screen with each triangle in its own colour and reads the box, so only
  visible triangles count and the posed, skinned model works. Each hit grows to its whole UV
  island (triangles joined through vertices that share position and UV), and an island joins
  when it fills at least 2% of the box and a quarter of what is visible of it lies inside. Shift
  adds, Alt removes. The selected islands are drawn into a mask in the texture, grown 2 px so
  seams don't show, and the recolour stays inside it. Other islands whose UVs land on the mask
  are shown in a second colour with "This also changes…", because one texture serves both: a
  pair of shoes sharing one patch can't be recoloured apart. A box over two materials makes one
  mask per texture.
  **Tested (Nov 1)** on Bruce Banner's default costume, front view, real GPU: boxes over the
  glasses, shirt badge, a rolled cuff and one shoe each picked the right garment out of a
  material shared by shirt, trousers, shoes and frames, and the other shoe was flagged as
  sharing the texture. Extras slipped in (eyebrows under the glasses, a shirt strip by the
  badge; the cuff took its whole sleeve), which is what Shift and Alt are for. Islands take
  0.05 s to prepare per skin, a selection 0.25 s and a mask 0.2 s, all before optimising
  (read back only the box; draw the mask on the GPU). Still to check: a caped skin, a dyeing
  skin, back views, and a posed model.
- The existing advanced controls (hex fields, every parameter) stay behind File details,
  revealed progressively rather than as an expert mode.
- **Edit history:** one stack per project covering parameter edits, texture replacements and
  restores. Undo and Redo are in the toolbar and on Ctrl Z / Ctrl Shift Z. Texture replacements
  keep the previous file so undo is real, not a confirm dialog.

**Done when** a newcomer can box-select and recolour three parts of a default costume in the
texture, including one that shares its material with other garments, and three
parts of a dyeing skin with a chroma, undo all of it, and the saved MI JSON matches what the old
editor writes for the same colours. Effort: Large; the texture recolour is most of it.

## Phase 4 — Ink moments

All full-motion only: still poses under Calm, Off and reduced motion. One stage owner through the
moment claim. Ink only for real state changes.

- **Joins your mod:** the first change to a part sends a drop from the pin to its dock slot.
- **New colour arrives:** a screen-space halftone. Capture the frame before the change, lay it
  over the canvas and mask it with dots swelling on a 45° lattice, 12 fps stepped, about 420 ms.
  It starts when the new texture is on the mesh, not on click.
- **Restored:** the slot melts, ink returns to the part, and the original arrives through the same
  halftone.
- **Install:** dock slots drain into the review's ink-well, which already counts until the real
  result.

**Done when** each moment has a browser check in the style of `tests/ink_flow_checks.py` and
none plays under reduced motion. Effort: Medium.

## Phase 5 — Guided first recolour, and measuring the milestone

- Home leads with Create a skin, Edit an existing mod and Explore game assets.
- Hero → costume → workspace through the roster and catalogue. Choosing a costume creates the
  project (the project-born drop).
- The optional guided run: Atelier picks a part, you pick a set, see it beside the original, then
  install. Three steps, never a lock.
- **Measure it:** time five people who have never modded the game from launch to an installed
  recolour, with no help. That number is the milestone.

Effort: Small–Medium, plus the sessions.

---

## Risks

| Risk | Mitigation |
|---|---|
| Preview colours don't match the game | Spike 1 gates everything; fix the composite first |
| Many skins only get material names | Automatic body-place names, worded as places; box select finds the part, and users can rename it |
| One texture serves several garments | Box select flags every island sharing the mask before the recolour applies |
| Keeping the viewport mounted costs memory | Phase 1 gate; dispose per skin, keep the shared cache |
| The shell change disorients existing users | The library, import and Projects stay as they are; the workspace is added, not swapped in silently |
| Edit history and file replacement get out of step | One history stack owned by the project, with files kept until the history drops them |

## Testing

- Per phase: browser checks in `tests/` against fixtures for layout, state and motion policy.
- Per phase with 3D: a real-asset verification report in `docs/`, in the shape of
  `assembly-verification-2026-10-22.md`, run with installed game assets and the native tools.
- Before release: an in-game check of three recolours, one per test skin.

## Out of scope

Mesh editing, new heroes or costumes beyond the catalogue, and preview LUT work beyond what
Spike 1 needs.
