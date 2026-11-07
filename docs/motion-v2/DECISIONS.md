# Decisions (Phase 0)

The brand bible (v1.2) and the current app disagree on these points. Each has a
recommended answer. An entry is settled only once its *Status* says `confirmed`.
Phase 0 is: show this file to Thiago, record his answer in the *Decision* line,
set *Status* to `confirmed`, and only then start Phase 1. Where an answer differs
from the recommendation, follow the answer and update `SPEC.md` to match.

---

## D1 · Typeface

- **Today:** Roboto (UI) and Bricolage Grotesque at 80% width (titles), both
  vendored under `gui/vendor/` and declared in `gui/tokens.css`.
  _Correction from the repo check:_ `gui/identity.css` and `gui/workspace.css`
  also use Instrument Sans (`--font-ui`) and Fragment Mono (`--font-mono`).
- **Bible:** Inter for UI, Inter Display for large sizes. Letter-spacing only on
  uppercase labels.
- **Recommended:** move to Inter + Inter Display, vendored locally (SIL OFL, no
  CDN). Remove Bricolage. Keep Roboto only if Inter fails a layout check.
- **Decision:** as recommended, and also:
  - Remove Instrument Sans.
  - Keep Fragment Mono for paths and code; Inter has no monospaced cut.
  - Keep the app's current 14, 13 and 12 px sizes, not the bible's 15–17 px body.
  - No −1.2% tracking on Display (bible p.7 conflicts with p.14). Only uppercase
    labels get letter-spacing (+9%).

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D2 · Category colours

- **Today:** 13 muted category hues in `tokens.css` (`--studio-icon-*`,
  `--studio-texture`, `--studio-mesh`). Texture is teal `#3f6872`, mesh brown
  `#795b48`, material green `#4b6b55`.
  _Correction from the repo check:_ there are 22 `--studio-icon-*` tokens, so 19
  others rather than 10. Only 8 paint a glyph (folder, texture, VFX, material,
  curve, mesh, text, unknown); the other 14 appear only as the 2 px rule under
  the library heading. Folder cards don't use these tokens at all: they paint 36
  separate inks from `EMBLEM_INKS` (`scripts/krackle_art.py:420`).
  `--studio-texture`, `--studio-mesh` and `--studio-vfx` have no consumers.
- **Bible:** texture blue `#6C98CA`, mesh teal `#5AAA9A`, material copper
  `#DF8F6B`. These name asset types and nothing else.
- **Recommended:** adopt the three bible hues for texture, mesh and material.
  Re-pick the other 10 categories (folder, character, UI, VFX, curve, text,
  nameplate, plugin, weapon, unknown) so none sits within 25° of hue of the
  three category colours or of the status hues (see SPEC.md).
- **Decision:** option B, neutral first. This differs from the recommendation:
  no hues are re-picked.
  - Only texture, mesh and material carry colour, on file glyphs and folder
    emblems alike. Every other category is neutral and told apart by shape.
  - Values are in SPEC §2. Mist, Guide and their light equivalents count as
    neutrals, so the 25° rule doesn't apply to them despite their slight blue
    tint.
  - P1.2 covers `EMBLEM_INKS` as well as the tokens. Emblem shape is a separate
    call (D9).
  - Non-asset folders that borrow a category token today (Physics, Shapes,
    Deformers, Abilities, Prototypes and others) become neutral.
  - Delete `--studio-texture`, `--studio-mesh` and `--studio-vfx` rather than
    remap them.
  - P1.2 rewrites `tests/category_icon_checks.py:100` and
    `tests/surfaces_checks.py:152`, which require 36 distinct colours.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D3 · Themes and custom palettes

- **Today:** Atelier, Darcula and Repak X presets, each light and dark, plus up
  to 24 custom palettes (`gui/theme.js`, storage key `atelier.appearance` v2).
  `theme.js` already derives text and accents for ≥ 4.5:1 contrast.
  _Correction from the repo check:_ `theme.js` has six presets, not three. High
  contrast, Blueprint and Comic are the others.
- **Recommended:** the mark's three colours never change with the theme. The
  glyph's halo always equals the surface it sits on. Status hues keep their hue
  and `theme.js` adjusts only their lightness for contrast, keeping each at
  least 30° of hue from the user's accent. The bible's Charcoal / Surface /
  Paper / Mist / Guide become the dark variant of the Atelier preset.
- **Decision:** as recommended for the mark and the halo, with these changes:
  - Status hues move in lightness only, and the 30° rule goes. It can't hold in
    Darcula, Repak X or Comic without changing what the colour means: Repak X's
    error would be 325° (magenta) and Darcula's warning 61° (yellow-green).
  - The Atelier preset uses the values in SPEC §2. Dark takes the bible's
    neutrals. Light takes the prototype's light values. `#212E3B` is added as the
    raised surface, because texture blue reaches only 4.36:1 on `#24323F`.
  - Atelier's accent turns neutral: Paper on dark, Charcoal on light (bible
    p.11). Today's blue sits 2–3° from texture blue, so buttons would read as
    "texture". Info text moves to Mist (`#4E5F73` on light) for the same reason.
  - Where accent-coloured text is the only cue in Atelier (text buttons such as
    `.vp-text-button` and `.mat-restore`, "Edited" markers), P1.3 adds an
    underline or heavier weight.
  - Other presets and custom palettes keep their own accents.
  - Progress bars use the theme's text colour, not the accent.
  - The two warning lines that use the accent (`gui/viewport.css:123`, `:243`)
    move to the warning colour in P1.3.
  - P1.7 covers all six presets.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D4 · The `info` state (neutral, cancelled)

- **Today:** a neutral Krackle glyph for notices and cancelled jobs.
- **Bible:** no neutral state (only working, complete, warning, error).
- **Recommended:** "at rest": the three pieces side by side in a row, category
  colours, still. Never the A (the A is reserved for success).
- **Decision:** as recommended, with the order set: mesh, tile, disc, on one
  baseline. Tile then mesh would sit side by side as the A's two legs, and tile,
  disc, mesh is the mark's own order spread out. Size and spacing get signed off at
  P2.8.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D5 · Costume-coloured effects

- **Today:** `gui/motion/krackle-context.js` tints effects with the current
  hero's or costume's colours (`AtelierMotion.energy`).
- **Recommended:** retire it. It breaks "colour means asset type". Hero artwork
  keeps its own colours; the motion system stays out of them.
- **Decision:** as recommended. Artwork-sampled tints outside the motion system
  stay: the Library hero banner (`gui/continuity.css:18`), the viewer's header line
  and glow (`gui/viewport.css:334`, `:340`) and the roster (`gui/roster.css:17`,
  `:40`). They bend bible p.11, so check them against the new surfaces in the P1.7
  screenshots.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D6 · Header logo

- **Today:** Krackle A mark, monochrome (black in light, white in dark), from
  `gui/brand/atelier-mark.svg` via `scripts/brand_mark.py`.
- **Bible:** the mark never changes colour; the wordmark follows the theme.
  _Correction from the repo check:_ the header's name is typed, in the UI font. The
  start page's setup hero has its own lockup, not in `SURFACE_MAP.md`: the Krackle A
  with Bricolage letters, a RIVALS logotype and the tagline "Every skin starts as a
  drop of ink."
- **Recommended:** full-colour mark, wordmark in Paper (dark) or Ink (light). Use the
  bible's lockup on the start page too.
- **Decision:** as recommended.
  - Header: the master mark at 32.4 px and the outlined wordmark at cap height 12, with
    a 15.6 px gap (bible p.12: mark 2.7 × cap height, gap 1.3 × cap height). The brand
    block grows from 93 px to about 140 px. At 1100 px and under, the name hides as it
    does today and the mark stands alone, about 50 px wide.
  - The wordmark is inline SVG, so its letters take the theme's text colour through
    `currentColor`. Its disc stays copper. The block keeps an accessible name.
  - The monochrome filter goes from the header and the startup splash. The Library hero
    signature (`gui/continuity.css:33`) is game art, so it stays monochrome under a
    token of its own.
  - Start page: replace the lockup with the bible's, at cap height 24. RIVALS and the
    ink tagline go.
  - On light themes the pieces reach only 2.3–3.0:1 against the canvas. This is
    accepted, because the mark keeps its exact colours and the name sits beside it.

  Confirmed by Thiago, 7 Nov 2026, from a mock-up of all six presets.
- **Status:** confirmed

## D7 · Interruption

- **Today (`gui/motion/README.md`):** "An animation is never entitled to finish
  its performance. A real result replaces whatever is playing at once."
- **New rule (tested and agreed in the prototype):** status text and controls
  still update immediately. The glyph lets the piece already in flight land
  (≤ 640 ms), then moves to the new state. Cutting a move off mid-flight is
  what produced the visible pop Thiago rejected.
- **Recommended:** adopt the new rule and rewrite that README paragraph.
- **Decision:** as recommended. The glyph can lag the text by up to 640 ms, which is
  accepted. P3.13 updates the surfaces and P4.4 rewrites the paragraph.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D8 · Logo entrance

Added during Phase 0.

- **Today:** the header logo plays a Krackle entrance on launch
  (`gui/motion/logo-entrance-ui.js:55`). `SURFACE_MAP.md` row 5 and P3.8 have the new A
  assemble once on launch, then stay still.
- **Conflict:** invariant 5 says only a confirmed success forms the A. Invariant 10 and
  bible p.10 and p.14 keep the brand mark static and apart from the status glyph. An
  entrance forms the A when nothing has succeeded.
- **Recommended:** a static logo, with no entrance. P3.8 removes the mount, so the logo
  is simply there on launch. P4.1 deletes the entrance files and P4.2 its test
  (`logo_motion_checks.py`). The prototype's Brand mark button stays as a demo control
  only; production has no route that builds the A except Complete.
- **Decision:** the A assembles once on launch, as the surface map has it. This differs
  from the recommendation, so invariants 5 and 10 each carry an exception, and SPEC
  takes priority over bible p.10 and p.14 on this point. To keep it apart from a real
  success, it's a brand moment, not a status (SPEC §4.8):
  - Category colours only, with no green, click, punch, ripple or sound.
  - Full motion only, and never when the window is hidden. Calm and Off show the still
    logo, as the entrance does today.
  - Once per launch. Today's click on the logo to replay it goes, and the logo stops
    being a button.
  - It waits for the startup splash and never delays start-up, as it does today.

  Size and timing at 32 px get signed off at P2.8.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D9 · Folder icons

Added during Phase 0. `SURFACE_MAP.md` doesn't cover these, and P4.1 deletes the
script that generates them (`scripts/krackle_art.py`).

- **Today:** 36 category emblems plus the plain folder art (`folder-flap`), with
  Krackle bubbles punched through them. Each emblem has its own ink. Icons are
  assigned by folder name (`gui/folder-icons.js`), with no check of what a folder
  holds.
- **Thiago's direction, 7 Nov 2026:** no holes on any folder icon, and fit the new
  shape language. Folders that are empty, or hold nothing a modder could or would
  edit, don't get an icon.
- **Measured:** the game index cached on 2 Nov 2026 (583,759 entries), classified
  with the Library's own rules (`atelier/web/browse.py:228`). Listed means the
  Library would show that asset.

  | Plain folder instead | Assets listed under that name |
  | --- | --- |
  | Fonts, Security, Statistics, Prototypes, Deformers, Pipelines, Mobile, Shapes | 0 |
  | VR, AI, Resources, Functions, Tools, Sky, Movies, Physics | 1, 4, 5, 6, 9, 24, 57, 62 |
  | Controls: 33 of 38 folders empty, and most of the rest are the Control game mode | 106 |
  | Lights: 504 of 517 folders empty | 183 |
  | Animation: 1,406 of 1,490 folders empty, animation assets aren't listed | 653 |
  | Audio: 2,044 of 2,325 folders empty, `Cues` are gameplay cues, `Wwise` lists 0 | 1,683 |

- **Recommended:** 17 icons stay: Textures, Meshes, Materials, Characters, UI, VFX,
  Weapons, Abilities, Environment, Blueprints, Plugins, Nameplates, Data, Text,
  Languages, Maps and the plain folder. Each is one to four solid pieces, with the
  mark's corners, gaps and concentric bites, and no enclosed holes. Textures,
  Meshes and Materials are the mark's own tile, block and disc. Names that earn
  nothing leave the rules that stay, such as `EngineMaterials` (3 listed, 3,139
  hidden), `Levels` and `DataTable`. P1.2 replaces the emblem artwork and removes
  the dropped rules; the generator moves out of `scripts/krackle_art.py`.
- **Decision:** as recommended. Textures, Meshes and Materials use the pieces, not
  pictures of the thing. Details are in SPEC §3.5, and the approved drawings are
  in `assets/emblems/`.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D10 · Krackle the surface map missed

Added during Phase 0. `SURFACE_MAP.md` doesn't list these, and Phase 4's gate can't
pass while they remain.

- **Today and recommended:**

  | Surface | Today | Recommended |
  | --- | --- | --- |
  | Model appearance loading (`gui/viewport-effects.js:56`, `gui/viewport-inspection.js:75`) | A band of energy climbs the model's silhouette while its appearance loads, and a last sweep reveals it | Remove both. The texture loader (D16), Inline in a corner, reports the loading, and the model stays in view. Materials and rendering don't change |
  | Setup-status check (`gui/motion/config-discovery.js`, `gui/app.js:3615`) | An animated scanner while the request runs | The same glyph as first-run setup (surface map row 4), driven by the real result |
  | Showcase backdrop (`gui/motion/showcase-art.js`) | A still dot screen and burst behind the model, also in exported Showcase images | Keep the neutral gradient and remove the dots and burst. Exported images change |
  | Thumbnail loading (`gui/thumbnails.css:16`) | Dots breathing on the Krackle beat | A still tonal plate, and the image cross-fades in. No glyph, because a grid can hold hundreds |
  | Cards being edited (`gui/polish.css:13`, `gui/app.js:651`) | The preview dissolves into a dot lattice, and edited materials draw their saved colours as dots | The preview stays whole beside the "Edited" marker. Edited materials show their saved colours as flat diagonal bands |
  | Deleting a row (`gui/polish.js:144`, `gui/style.css:1519`) | The row drains away with bubbles | A plain 200 ms fade, like the Mod tray row |
  | Project ink (`gui/motion/project-ink.js`) | Not loaded by `gui/index.html`, and nothing calls it | Delete it in P4.1. Nothing visible changes |

  The HDR swatch ring (`gui/polish.js:303`) only names its dots "bubble". It reports a
  material's intensity, so it stays, and only the name changes.
- **Decision:** as recommended, including the change to exported Showcase images. The
  surfaces are in `SURFACE_MAP.md`, and P3.12b carries them out.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D11 · What "no Krackle left" means

Added during Phase 0. The Phase 4 gate can't pass as written, and it misses files.

- **Today:** `grep -rli krackle gui tests scripts docs` must return nothing except
  CHANGELOG history. CHANGELOG isn't in those folders, and `docs` holds 33 matching
  files, 30 of them records of earlier work or this pack: 15 release notes, Discord
  posts and announcements, 5 verification records, a checkpoint, 3 review files and the
  6 files in this pack. Only 3 describe the app as it is: `DESIGN_SYSTEM.md`,
  `DEVELOPMENT.md` and `WORKSPACE_PLAN.md`.
- **Missed:** the search doesn't reach `README.md:77`, `images/README.md`,
  `images/screenshots.json` and `images/krackle-examples.png`, `packaging/Atelier.iss:72`
  or `CLAUDE.md`. It also counts untracked test output: 29 files in `tests`, against 16
  tracked.
- **Recommended:** leave history as it was written, and search everything else that's
  tracked, by content and by file name. These must both return nothing:

  ```sh
  git grep -il krackle -- . ':!CHANGELOG.md' ':!docs/release-*' ':!docs/discord-*' ':!docs/announcements' ':!docs/*-verification-*.json' ':!docs/*checkpoint*' ':!docs/review' ':!docs/motion-v2'
  git ls-files | grep -i krackle | grep -vE '^(docs/review|docs/motion-v2)/'
  ```

  P4.4 clears the missed files, and P5.2's recapture replaces the screenshot. The
  definition of done then reads "no Krackle remains outside history".
- **Decision:** as recommended.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D12 · Tier gaps

Added during Phase 0.

- **Today:** SPEC §5 has Stage at 96 px and up, Inline at 32–64 and Micro at 24 and
  under, so a host of 25–31 or 65–95 px has no tier. The tier comes from the host's
  rendered height.
- **Measured:** what the surfaces render at today.

  | Height | Surfaces |
  | --- | --- |
  | 112–240 | First-run setup 240, startup 156 or 224, export review 216 (164 when narrow), viewport loader 112, index failure 112 |
  | 65–95 (no tier) | Setup-status check 88, first-run setup's line 72 |
  | 32–64 | Material save 36–44, toasts 40, header logo 32 |
  | 25–31 (no tier) | Install button 28, and one spinner at `gui/index.html:704`, 28 |
  | 24 and under | Activity rows and setup rows 20–24, spinners 20 |

- **Recommended:** no gaps. Stage at 96 and up, Inline at 32–95, Micro under 32. The
  small mark and Micro's other rules ("24 px and under") then apply under 32, because
  32 is where the master mark starts. So the install button gets the small mark and the
  jostle, and the setup-status check gets the fits at ×0.8 with no ripple. Loaders
  still stop at 32.
- **Decision:** as recommended.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D13 · The older identity palette

Added during Phase 0. `SPEC.md` and D3 don't cover it.

- **Today:** `gui/identity.css:24-80` has its own palette under `.at-identity`: warm
  paper and charcoal, smalt blue for selection and focus, and its own green, ochre and
  madder. It has only a light and a dark version, and `theme.js` never touches it, so
  these ignore the six presets and custom palettes: the project workspace, the Edit All
  import dialog, the project name, delete and export dialogs, the mod-open dialog and
  the first-run setup page.
- **Conflict:** smalt (hue 226°) sits 14° from texture blue, which is the problem D3
  fixed in the accent. Its status colours aren't the ones in SPEC §2. The Rivals colour
  has one use left, and D6 removes it.
- **Recommended:** keep the `.at-identity` class and its role names, so no component
  changes, and point the roles at the app's themed tokens in P1.3. Delete the pigments.

  | Role | Becomes (Atelier values in SPEC §2) |
  | --- | --- |
  | `--surface`, `--surface-panel`, `--surface-sunk` | Canvas, Container, Lowest surface |
  | `--line` | Rules |
  | `--text`, `--text-muted` | Text, Muted text |
  | `--action`, `--on-action`, `--drop`, `--drop-text`, `--on-drop` | Accent and Text on accent. Selection turns neutral, as D3 did for buttons |
  | `--drop-wash` | Raised |
  | `--done`, `--caution`, `--caution-text`, `--fault` | Status icons and sentences |
  | `--energy*` | Removed in P4.1, with the Krackle that reads them |
  | `--rivals` | Removed in P1.5 |

  Type follows D1. The spacing and shape tokens stay. These surfaces lose the warm
  paper and start following the theme, so someone on Darcula sees Darcula there. P1.7's
  screenshots add them.
- **Decision:** as recommended.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D14 · The mark

Added during Phase 0. This replaces the mark drawn on bible v1.2 p.3 and p.4.

- **Today:** the v1.2 mark: tile with a leaning face, parallelogram mesh, disc r 46,
  uniform corners. The disc's halo cuts the bites on the animated A (invariant 3).
- **Thiago's direction, 7 Nov 2026:** a new drawing he supplied, with a notch on the
  tile's top left, softer and uneven corners, and a broader mesh.
- **Tested:** it keeps the three pieces, the concentric bites and an even gap. The
  `!` and X don't change. A straight piece and a halo can't make its rounded bite
  lips, so the animated A would differ from the static mark.
- **Recommended:** adopt it, with the tile and mesh carrying their bites in every
  pose so the two always match. This rewords invariant 3.
- **Decision:** adopt it, in the bible's exact colours, not the slightly different
  ones in the supplied image. The tile and mesh carry their notch and bites in the A
  and the wrong fits, and flatten into plain bars for the `!` and X.

  The motion changes with it, because the gap under the bites is narrower than the
  disc and the disc has no room to dip below its seat: the mesh stands off until the
  disc is in, then closes, and the click runs sideways (SPEC §4.1, §4.3). Clearance is
  measured on the outlines actually drawn. SPEC takes priority over bible v1.2 p.3 and
  p.4 until the bible is updated.

  Confirmed by Thiago, 7 Nov 2026. He signed off the clean artwork and the motion the
  same day, from the sign-off sheet and a recording of every state at stage size. D15
  then changed Working, Complete and the colour after success.
- **Status:** confirmed

## D15 · Working, Complete and the colour after success

Added during Phase 0, from Thiago's review of the motion signed off under D14.

- **Signed off under D14:** Working runs six fits, about 3.6 s each, with two taps.
  Complete takes about 3.1 s to reach the click. The A then stays green.
- **Thiago's review, 7 Nov 2026:** six wrong fits risk saying Atelier keeps failing.
  Complete should be the star and take about a second. Permanent green loses the link
  between the three pieces and what they stand for.
- **Tested:** the first version went straight between Head, Bench and Ramp, at 1.9 s
  an attempt. Straight moves stay clear only between Head and Ramp. All four moves in
  or out of Bench cross another piece, and no other fit from the original six connects
  cleanly to both. Those crossings put one piece over another in 6.9% of Working
  frames, which invariant 4's "rare" doesn't cover.
- **Decision:** adopt all three, keeping Bench and coming apart around it.
  - Working: three fits, Head, Bench and Ramp, with one tap and a 180 ms hold. Between
    Head and Ramp the pieces go straight across, about 1.8 s. To or from Bench they
    come apart first, about 3.4 s. No piece passes over another between attempts.
    Thiago chose this over Head and Ramp alone (1.8 s, but the same two fits in turn)
    after seeing all three side by side. D16 then made the first move out of an outcome
    a single brisk one.
  - Complete: all three pieces move together for 340 ms, the mesh comes in for 110 ms,
    then the click as signed off. This is an exception to "one piece at a time" in
    invariant 4, and D16 adds the opening as the other.
  - Colour: green on contact, then back to the three colours 160 ms after the effects
    finish, over 380 ms. The status sentence stays green. Micro (under 32 px, D12)
    stays green, because three colours at that size read as the logo. Thiago's "adopt
    all three" answered a proposal that included this exception.
  - The click comes 720 ms after the result (median; at most 1.2 s), and the effects
    finish at about 1.4 s (at most 1.8 s).

  Small sizes and engine cost, from the same review, need no decision: they're in SPEC
  §5 and HANDOFF P2.4, P2.8 and the Phase 2 gate.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D16 · Per-asset loaders and the opening

Added during Phase 0, from Thiago's question about how a mesh, texture or material
should load.

- **Before:** every job, whatever it handles, runs Working. Getting there from an
  outcome took about 3.2 s, one piece at a time.
- **Thiago's direction, 7 Nov 2026:** each asset type gets its own loader, drawn on its
  own piece. The first move out of an outcome should be faster.
- **Tested:** three loaders from the at-rest row, in the prototype. The row is the base
  and the other two pieces stay still, so nothing looks like an A. For the texture, blue
  bands were recommended and colour bands were the alternative.
- **Decision:** adopt, with the colour texture. This differs from the recommendation.
  Details are in SPEC §4.7.
  - Mesh: the block lifts and cuts into chunks, snapping to a new arrangement with a
    small lean this way and that.
  - Texture: the tile lifts and splits into five bands that slide out of register in
    flat colours, then fall back top to bottom, each landing on the tile's own blue.
  - Material: the disc rolls along the baseline as a band of light crosses it.
  - Only where the real asset type is known: the viewport loader (mesh), model
    appearance loading (texture, D10), material save (material), and jobs whose `kind`
    alone names one asset type, such as `mesh-replace`. Moving from the mesh loader to
    the texture loader takes two real events. Jobs have `kind` and a free-text `stage`
    but no asset-type field, so never pick a loader by guess or timer. Everything else
    keeps Working.
  - Loaders stop at 32 px, and Micro keeps its jostle. Off shows the still row. Calm is
    designed at P2.8.
  - The texture's colours and the material's light are flat and opaque, but they aren't
    the three piece colours, and the mesh cuts are drawn in the halo's colour. Invariant
    1 and SPEC §2 carry the exception.

  The opening: the first move out of an outcome, into the row or the first Working fit,
  takes 420 ms with all three moving together, and the mesh hops over the tile if they
  swap sides. That's about 3.2 s down to 0.4 s from the A. The cost is about 200–280 ms
  where a piece passes over another, so 1.5% of Working frames now overlap, against 0%
  before. Invariant 4 carries the exception. The assembly stays for moves to or from
  Bench and into the `!`, the X and the Brand mark.

  Size of the row, the light theme and the texture's colours at small sizes get signed
  off at P2.8.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D17 · The last Krackle the surface map missed

Added during Phase 0, from a sweep of every file in `gui/motion/` and every Krackle
reference elsewhere in `gui/`.

- **Today and recommended:**

  | Surface | Today | Recommended |
  | --- | --- | --- |
  | Startup stage (`gui/motion/surface-adapters.js:22`) | While containers index, a 224 px stage replaces the splash logo and builds on the logo's own silhouette, or a 156 px stage without it | Working at Stage, beside the counted progress bar, with no silhouette. The A must not form here (invariant 5). The logo entrance still follows (D8). Calm and Off keep the still logo and the bar, as they do today |
  | Index failure (`gui/motion/surface-adapters.js:35`) | A 112 px error stage in the failure notice | The X at Stage, with the notice's text unchanged |
  | First-export moment (`gui/polish.js:194`) | Once ever, the exported skin's inks pour across the install button | Remove it. Complete is the celebration, and the moment uses the costume colours D5 retired |
  | Theme change (`gui/preferences.js:38`) | A scalloped print wash crosses the page from the chosen control | A plain cross-fade of the page, 200 ms, in Full and Calm, as interface chrome. Off stays instant |
  | Toast captions (`gui/motion/surfaces.css:10-22`) | Cream paper with a hard black border and comic shadow, in every theme | The theme's Card surface and text, with a left rule in the status colour and no comic shadow |
  | Toast repeat count (`surfaces.css`, `gui/app.js:191`) | A row of dots for up to 5 repeats, then a number | Always a number, such as "×3" |
  | Selection count (`#sel-count::before`, `surfaces.css`) | A small ink bubble beside the count | Remove the bubble. The count stays |
  | Texture drop target (`.card.k-texture-pool`, `gui/app.js:4294`) | An ink outline with a pool along the bottom of the card | A plain outline in the theme's text colour |
  | Dot lattice (`.k-screen`, `--screen-dot`, `gui/polish.js:324`) | Halftone dots behind empty states | Remove it. Empty states sit on the plain surface |

  Primary-button dots (`.k-button-pop`) go with the workflow gestures already retired,
  and the model-loading inks (`gui/viewport-effects.js:212`) go with D10. The other
  references are tokens, comments and `data-krackle`, which P4.3 and P4.4 rename.
- **Decision:** as recommended, including removing the first-export moment. The surfaces
  are in `SURFACE_MAP.md`, and P3.12b carries them out.

  Confirmed by Thiago, 7 Nov 2026.
- **Status:** confirmed

## D18 · The setup page's stages

Added at the P1.7 checkpoint, from Thiago's note on the first-run setup sheet.

- **Decision:** the three blocks split the page's three stages, and the rows lose their
  rules. In the page's order and the mark's: tile for the unlock key, mesh block for the
  mapping file, disc for the game folder.
- **Limits:** the blocks stay still and always use the exact piece colours, so they aren't
  a progress bar (SPEC §2) and don't form an A (invariant 5). Each row's status stays in a
  20 px glyph and its sentence. Which block goes with which stage is by order only, and
  Thiago can change it.
- **Status:** asked for by Thiago, 7 Nov 2026; the drawing awaits his sign-off at P1.7.
