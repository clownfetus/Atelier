# Spike 2: friendly part names from rules alone

Nov 1, 2026 · Phase 0 of [WORKSPACE_PLAN.md](WORKSPACE_PLAN.md)

**Question:** how many skins get friendly part names from slot-name rules alone, and what share
of costume materials dye at all?

**Answer:** the bar passes as written and fails in practice. 26 of the 30 most-modded skins get
three or more named parts, but almost always only Body, Head, Eyes, Hair and Teeth. The costume
pieces themselves are slots called `Equip_01` to `Equip_11`, the most common slot name in the game
(36% of visible slots), and 71% of the slots that dye. Leave the anatomy names out and **1 of 30**
passes. Separately: **none of the 30 most-modded skins dyes.** Every one is a default costume, and
no default costume in the game has a dye mask.

## Setup

- Repo code at `92e2592` plus the uncommitted Projects work. A scratch data folder reading the
  installed app's tools and key (`D:\Atelier\Tools`), so neither the dev data nor the installed
  app's data was written. The dev data has no key at the moment.
- Game build `1.1.3984769`, mapping file `3984769`, installed paks.
- **Skins:** all 761 skins in `gui/catalogue.json`. For each one, the body meshes the app opens
  for it (`meshstudio.skin_meshes`: every form of a multi-form hero, Lobby meshes excluded) are
  read through the native import tool, and each slot's material through the same tool, on a
  reader confirmed good by Spike 1's canary. 249 skins have no body mesh of their own; their own
  folder's material instances stand in for slots. 3 skins failed (`The selected asset is not a
  mesh`): Binary Fist, King of Clubs, Presidential Attire. 758 are scored.
- **Most-modded:** no ranking existed, so this one is built from Nexus Mods. The public API
  served 7,965 of the 9,945 Marvel Rivals mods it reports; each mod's title and summary was matched
  against catalogue skin names. A mod that names a hero but none of the hero's skins counts for the
  hero's default costume, because most character mods that say only "Storm" replace her default
  look. That attribution is a proxy, and it decides the whole top 30: every one is a default
  costume. The most-named alternate skin, Lady Loki, is 40th. The top 30 of skins named by title
  alone (all alternates) was scored too, as a check.
- **Rules:** a slot's name is reduced to words (`MI_1025001_Dagger_Equip` → `equip`; form names
  like Dagger, Cloak, Banner and HeroHulk are dropped) and the first matching rule gives its part:
  Hidden (LOD, Hide, lambert), FX, Weapon, Eyes, Mouth, Hair, Head, Cape, Clothing, Accessory
  (tail, wings, gem…), Body, Equip. An Equip or unmatched slot takes its material's name when that
  says more. The game's own typos are matched (`Eqiup`, `EyesBall`, `Hightlight`).
- Scripts and output are kept outside the repo; the numbers below are their output.

## Results

### Against the bar

| | Skins | ≥ 3 named parts | ≥ 3 without Body, Head, Eyes, Mouth | Median Equip slots | Any dye |
|---|---|---|---|---|---|
| 30 most-modded (defaults) | 30 | **26 (87%)** | 1 | 4 | **0** |
| 30 most-named alternates | 30 | 28 | 2 | 5 | 0 |
| Every skin | 758 | 619 (82%) | 59 (8%) | 4 | 230 (30%) |

### What the slots are called

Visible slots across every skin (Hidden left out), 9,690 in all:

| Part | Slots | of which dye |
|---|---|---|
| **Equip** | **3,525 (36%)** | **727** |
| Eyes | 1,467 | 0 |
| Hair | 1,459 | 6 |
| Body | 1,063 | 137 |
| Head | 736 | 37 |
| Weapon | 459 | 92 |
| Mouth | 347 | 0 |
| FX | 274 | 1 |
| Accessory | 163 | 11 |
| Unknown | 152 | 7 |
| Clothing | 28 | 3 |
| Cape | 17 | 0 |

The rules leave 1.6% of slots unknown (`Punches`, `Line`, `Gen`, `Laser`, and pinyin like
`dazhaodizuo` and `shoubi`). The naming problem is not unknown slots. It is that the game names the
costume by number. Clothing and Cape together are 45 slots in 9,690: the artists do not name
outfit pieces.

### The 30 most-modded skins

| Skin | Named parts | Equip slots |
|---|---|---|
| Spider-Man | Body, Head | 2 |
| Invisible Woman | Body, Eyes, Hair, Head, Mouth | 2 |
| Luna Snow | Body, Eyes, Hair, Head, Mouth | 8 |
| Magik | Body, Eyes, Hair, Head, Mouth, Weapon | 6 |
| Iron Fist | Body, Eyes, Hair, Head, Mouth | 2 |
| Phoenix | Body, Eyes, Hair, Head, Mouth | 2 |
| Psylocke | Body, Eyes, Hair, Head, Mouth | 4 |
| Deadpool | Weapon | 5 |
| Rogue | Body, Eyes, Hair, Head | 2 |
| Black Panther | Body, Clothing, Eyes, Head | 1 |
| Daredevil | Body, Eyes, FX, Hair, Head, Mouth | 3 |
| Captain America | Body, Eyes, Hair, Head, Mouth | 2 |
| Jeff the Land Shark | Body, Eyes, FX, Head, Mouth | 0 |
| Scarlet Witch | Body, Eyes, Hair, Head | 4 |
| Mantis | Body, Eyes, Hair, Head, Mouth, Weapon | 1 |
| Hela | Body, Eyes, Head, Mouth, Weapon | 4 |
| Cloak & Dagger | Body, Eyes, Hair, Head, Mouth | 3 |
| Storm | Body, Eyes, Hair, Head, Mouth | 5 |
| Venom | Body, Head | 1 |
| Iron Man | Body, FX, Head, Weapon | 7 |
| Winter Soldier | Body, Eyes, Hair, Head, Mouth | 11 |
| Emma Frost | Body, Eyes, Hair, Head, Mouth | 4 |
| Gambit | Body, Eyes, Hair, Head | 3 |
| Jubilee | Body, Eyes, Hair, Head | 5 |
| Cyclops | Eyes, Hair, Head | 4 |
| Black Cat | Body, Eyes, Hair, Head | 6 |
| Ultron | Body, Head | 4 |
| White Fox | Accessory, Body, Eyes, FX, Hair, Head, Weapon | 3 |
| Bruce Banner (Hulk) | Body, Clothing, Eyes, Hair, Head, Mouth | 5 |
| Blade | Body, Eyes, Hair, Head, Mouth, Weapon | 4 |

Deadpool's whole costume is five Equip slots and three weapons. The four that miss the bar
(Spider-Man, Deadpool, Venom, Ultron) are suits with no separate hair or eyes, which is exactly
where the costume is the character. Across the 30 there are **103 distinct Equip materials**:
that is the size of a curated naming pass for them.

### Dye

| Skins | Dye | No dye |
|---|---|---|
| Default costumes | **0** | 54 |
| Alternates with their own mesh | 41 (9%) | 414 |
| Skins with no mesh of their own | **189 (76%)** | 60 |

1,009 of the 8,772 distinct materials read (11.5%) dye. Dye is how the game makes its colour
variants: the skins without a mesh of their own (Will of Galacta and the other material swaps of
an existing costume) are three quarters of everything that dyes. The costumes people mod are the
ones without it.

Of the 1,009 dyeing materials, 770 define all seven Region colours, and 239 define one to six.
That counts the parameters, not the regions the mask actually paints; Spike 3 needs the mask.

## Pass / fail against the plan

| Bar | Result |
|---|---|
| ≥ 80% of the 30 most-modded skins get three or more named parts | **Pass as written** (26 of 30) · **fail in practice** (1 of 30 once Body, Head, Eyes and Mouth are left out) |
| What share of costume materials dye | **11.5% of materials; 30% of skins; none of the most-modded** |

## What it means for the plan

- **Rules alone give a parts list that names the person and numbers the outfit.** A newcomer who
  wants Storm's cape blue would pick between "Equip 1" and "Equip 5". The fallback, the
  material's name labelled as such, is honest but would be the main way most costume pieces
  appear.
- **The curated `parts.json` from the plan is needed, and is cheap for a launch set.** 103 Equip
  materials across the top 30, named in the Assembly view, is Small. All 758 skins hold 3,525
  Equip slots, which is not.
- **Automatic names from the skeleton** cover every skin without curation; tested below
  ("Automatic names").
- **Decision 2 (non-dye materials) decides the milestone.** With no dye on any default costume, a
  guided first recolour on a most-modded skin can't use dye regions at all. Sets need base tint,
  or the first recolour has to be on one of the 230 skins that dye, mostly colour variants
  newcomers are less likely to own.
- **Decision 3 (scope):** "all heroes with fallback names" works for the head and hair and leaves
  the outfit numbered. A curated launch set of the most-modded defaults is affordable.

## Automatic names

Tested the same day, after decision 3 (hand-name the top 30, try automatic names for the rest).

**Method.** Each piece (one cooked material slot in the mesh's glTF) sums its vertices' skin
weights per bone. The skeletons are the standard Unreal set (`spine_01`…, `upperarm_l`, `thigh_r`,
`head`) plus descriptive helper bones that the riggers named: `cloak_Askin_*`, `ribbon_l_*`,
`Scarf_B_*`, `Belt_01_Jnt`, `Glasses_001_A02`, `Necklace_02_Jnt`, `Cope_LC_06`. A helper word names
the piece when its bones carry at least 35% of the weight and outweigh any body region (Cape,
Skirt, Belt, Glasses, Necklace, Shoulder armour…). Otherwise the piece takes its body region:
Head, Torso, Arms, Hands, Hips, Legs, Feet, with "Left"/"Right" when one side holds it and a second
region added above 30% ("Legs and feet"). A piece spread thin over three or more regions is a
Suit. Correction bones (`L_Elbow_Fix`, `Breast_vol_ft`, `Scapula`, `Collar`) count toward their
region.

**Checked against slots the game names:** of 199 Hair, Head, Eyes and Teeth slots on the top 30,
the automatic name agrees 192 times (96%).

**Checked by eye on the 113 Equip pieces of the top 30.** Each piece was drawn highlighted on its
character's front silhouette with its automatic name, and judged:

| Verdict | Pieces | Examples |
|---|---|---|
| Right | **72 (64%)** | Storm's cape and its ribbon trim, Hela's headdress and cape, Winter Soldier's metal arm, the Hulk forms' shorts and belts, Jubilee's glasses, Iron Man's shoulder armour, every "Legs" on a pair of trousers |
| Roughly right | 28 (25%) | Jackets named "Arms" or "Suit", Luna Snow's shorts named "Legs", Emma Frost's skirt named "Hips", Cyclops' visor-and-straps named "Head" |
| Wrong | 13 (11%) | Psylocke's bodysuit-and-boots named "Feet", Iron Man's chest named "Arms", Venom's legs named "Suit", Blade's coat skirt named "Head", Cloak's hood named "Necklace" |

The misses have one cause: a material that covers unrelated bits. The game groups pieces by
texture sheet, not by garment, so Captain America's gloves, belt and boots share one material,
and no single body word fits them. "Suit" is also doing two jobs: a whole outfit (Mantis, Bruce
Banner's clothes, which is right) and scattered gear (Deadpool's pads and gloves, which is not).

**What it means.**

- **Automatic names beat "Equip 3" for most pieces and mislead for about one in ten.** As the
  default for skins nobody has named, with hand names overriding them, they are worth having.
  They should read as places, not garments ("Legs", not "Trousers"), because the rules can't
  tell trousers from boots.
- **A highlight does the rest.** If the Phase 2 parts list lights the piece on the model when
  it's hovered or selected, a roughly right name plus the highlight answers "which one is the
  jacket?".
- **The rules can improve.** Name a piece by its two largest separate regions when they are not
  neighbours ("Hands and feet" for gloves and boots), and keep "Suit" for pieces that are mostly
  continuous. Not tried yet.
- **Cost:** one glTF export per mesh (the import tool already does it when a model opens) and a
  pass over its skin weights; no curation. Effort: Small to wire into the parts list.

The judgement is one reviewer's, from low-resolution silhouettes; a piece on the back of the
model is harder to see from the front.

## Not covered

- **"Body" is not checked on the model.** On many costumes the Body material is most of the suit,
  not skin. The label is the game's word, not a look at what it paints.
- **The ranking is a proxy.** It comes from mod titles and summaries, about 80% of Nexus' listing,
  and gives hero-only mentions to the default costume.
- **Skins with no mesh of their own** are scored by their own materials. How the app opens one
  (which mesh carries those materials) was not checked.
- **Weapons and summons** are listed per skin but not scored as parts; the plan shows them under
  Extra parts.
