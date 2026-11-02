# Spike 3: what can dye regions honestly be called?

Nov 1, 2026 · Phase 0 of [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md)

**Question:** dye regions are numbered 1–7 and nothing in the game files names them. Can Atelier
name them from where they sit on the body, from their colour, or should it number them and show
them on the model?

**Answer:** number them and show them. Regions are patterns, not garments: stripes, trims and
panels that run over the whole body, so names from where they sit say "Arms and torso" for most of
them. Names from their colour clash on dark costumes, where half the regions are some shade of
black. A numbered area that lights up on the model and shows its current colour as a swatch is the
only label that is always true and always tells two regions apart.

## Setup

- Repo code at `92e2592` plus the uncommitted branch work, the same scratch data folder as
  Spike 2 (installed app's tools and key), game build `1.1.3984769`.
- **Skins:** five that dye and have a body mesh of their own: Golden Panther (1026101), Blood
  Shield (1050101), Emerald Flames (1054101), Sacrificial Pawn (1058101) and Argent Archer
  (1021102). Default costumes don't dye (Spike 2), so these come from further down the ranking.
- For each dye material: the ColorID mask through the native import tool, region =
  `round(alpha / (255/7))` as in `atelier/handlers/dye.py`; each region's share of the texture;
  its default colour as the median of `dye.composite` over its texels; and where it sits, from every
  triangle sampled at its UV centre, weighted by surface area, with the bones its vertices follow
  (the Spike 2 rules).
- 24 dye materials, 21 on the body (the rest are weapons, which have no skin weights). 118 dyed
  regions on the body materials, 92 of them covering at least 1% of their part.
- Front and back renders of Golden Panther, Emerald Flames and Sacrificial Pawn with each region
  in the overlay colours of `region_overlay` (scratchpad, not committed).

## Results

| Policy | What it says | How often two visible regions of one part get the same label |
|---|---|---|
| (a) Area 1…N, largest first, lit on the model | "Area 1", "Area 2" | never |
| (b) Where it sits, Main for the largest | "Main", "Arms and torso", "Legs" | 39 of 92 regions |
| (c) Its default colour | "Black", "Charcoal", "Silver" | 55 of 92 regions |

- **Where it sits fails.** Regions are decoration, not garments. On Golden Panther every region is
  a stripe pattern spread over the whole suit, front and back. On Argent Archer's legs, four
  regions are all "Legs" or "Feet and legs". The names are true but don't help anyone choose.
- **Colour names fail on dark costumes.** Emerald Flames' body has six visible regions, five of
  them "Black". Argent Archer's legs are four shades of "Charcoal". The default colour also depends on
  the composite, which is a preview recipe: Golden Panther's gold reads as a dark brown in the
  median.
- **Size order is the honest order.** The largest region holds at least half its part in 9 of 21
  materials; in the rest no region dominates, so "largest first" is an order, not a claim that
  area 1 is the main colour. It is still the best stand-in for "main" in colour sets.
- **Small regions are common.** 26 of 118 dyed regions cover under 1% of their part: thin trims,
  rivets and logos. They should still be listed, after the rest.
- **Undyed areas exist.** 4 of 21 body materials have texels the dye system ignores (region 0),
  such as Argent Archer's bare hands. Those areas need saying plainly: they keep their painted
  colour, and only the Texture tab changes them.
- **A region number means nothing across materials.** Region 1 is near-black on one of Sacrificial
  Pawn's parts and light grey on another; across the five skins, the same number differs by up to
  340 (of 441) in RGB distance between parts. A skin-wide "Region 1" control would recolour
  unrelated things, so areas stay per part.

## Decision

**Policy (a).** Each dyeable part lists its areas largest first, numbered from 1, each with a
swatch of its current colour. Hovering an area lights it on the model (`region_overlay` already
paints them); clicking selects it. Tiny areas (under 1%) come last. Undyed texels get one line:
"Not dyeable: keeps its painted colour". The game's region index stays behind File details.

**Colour sets** take roles by size: the largest area is main, the next is secondary, the rest are
accents in size order.

**The words (owner, Nov 1).** A region is an **area**. A colour set, a whole recolour of the skin
saved under a name, is a **chroma**, which is what the word means to players of League of Legends
and Valorant.

Curated names for top skins can come later without changing the UI.
