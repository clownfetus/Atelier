# Character preview verification — 2026-10-21

The cross-character audit uses the installed Windows game assets, a rebuilt
pinned shader tool and an independently rebuilt persistent importer. All work
runs in disposable application data with an empty `test-mods` destination.
No project edits or game mods are published by the roster harness.

## Corrections

- Recognize left/right cannon and launcher names without an underscore, and
  recognize the authored joints of tridents, wands, batons, nunchaku and other
  weapon families. Prefer explicit alignment joints over deforming joints.
  Ultron's hand-mounted cannon rigs align at the wrist rather than the palm.
  The browser and portable Blender assembly use matching grip rules.
- Keep equipment with its authored body form. Banner's gun is not equipped on
  Hulk's larger forms automatically. Static duplicate weapons and ability props
  remain selectable without occupying a hand on open.
- Select the canonical character mesh ahead of secondary forms. Emote props,
  cue geometry, animation/control assets, first-person meshes and accessory-only
  assets no longer replace a character's default body. This corrects Captain
  America's horn, Moon Knight's rope and Iron Fist's animation helper.
- Preserve the exact parent material package through both native imports and
  editable material documents. Missing translucent opacity follows that package;
  explicit child values win. A unique-name fallback supports older cached data,
  while ambiguous names never pick another costume's material. Inherited fields
  are display metadata and do not become new editable child parameters.
- Composite iris and sclera colour layers with the authored iris radius,
  brightness and sclera tint. Use the exact common eye textures when the eye
  master supplies those defaults. Colour layers are not tinted a second time.
  Draft recolouring, revert, saved edits, custom texture inputs and Original
  comparison use separate versioned composites. Original ignores draft colours
  and custom images.
- Respect disabled effect alpha. Unsupported flipbook/layered effects from
  `M_BPStdMoAni` and `M_StdAdv` are explicitly omitted from the preview instead
  of displaying as solid white sheets. This also follows exact MI parents.
  Their controls explain the preview omission; their parameters and exported
  section visibility are unchanged.
- Publish the already-complete first-LOD GLB bytes synchronously. The pinned
  upstream exporter's [`TryWriteToDir` starts an unawaited file write](https://github.com/FabianFG/CUE4Parse/blob/ea85cf20d8df53556f399c5fabc2befb46b65d0d/CUE4Parse-Conversion/Meshes/Mesh.cs#L31).
  Reading or deleting that staging file caused intermittent Windows sharing
  violations. The importer now publishes `MeshLods[0].FileData` directly.
- Use Windows extended paths for long import-cache files and atomic JSON
  publication. The audit reproduced a long material path failure on Magneto.
  Existing containment checks still reject other drives, shares and devices.

## Reproduction and evidence

The combined checks cover **54 installed characters, 63 body forms and 62
ordinary weapons**, with **178 idle/rest views**. All discovered forms and
ordinary weapons became visible and passed the material/attachment assertions.
No page or critical asset request errors occurred. The 158 optional props remain
available for explicit selection; they are not part of this attachment audit.
Nightcrawler, Forge and Amaranth have no body mesh in this game installation.

The roster was tested in two overlapping batches, followed by focused checks of
the six characters needing shared eye defaults. The first batch was stopped
after its covered subset to avoid repeating characters in the second batch.
The receipt retains each batch's source hashes and identifies which report
supplies every final character result.

The full 225-check browser suite passes. The combined latest regression reports
contain 285 unit tests and 81 additional script checks, all passing. Two optional
Phase 4 native checks are skipped in their disposable test environments; separate
real native texture import/build/readback probes pass as described in the
[custom texture follow-up](texture-import-verification-2026-10-21.md).

`tests/native_character_previews.py` exercises the real application's browser,
mesh/material/texture APIs, installed geometry and standing idle animations.
Use a separately configured application with its own `test-mods` folder:

```powershell
.venv/Scripts/python.exe tests/native_character_previews.py --url http://127.0.0.1:8890 --report-dir D:/AtelierQA/roster --all-parts
```

The report checkpoints every character, records source hashes and captures
whole-model idle/rest views and face close-ups. It also selects each additional
body form and ordinary held weapon. Assertions cover material package mapping,
diffuse/opacity/emission and eye layers, inherited opacity, disabled emission,
one active body, weapon attachment position/orientation and shared-rig alignment.
The command fails if a character, page or asset request reports a problem.
Ability props are inventoried separately from ordinary equipment.

The companion [verification receipt](character-preview-verification-2026-10-21.json)
records final coverage, follow-up checks, executable/input hashes and regression
results without game asset payloads, local configuration or encryption keys.
Full screenshots and detailed asset reports remain outside the repository.

Two independent final importer builds produce byte-identical executables and
input manifests. Their executable SHA-256 is
`eba1941fac070a25e7bb8edad510bc9ccead9891dd2a598c4f63bfe439a8934c`.
The updated input lock SHA-256 is
`1e82d06ae292cc845d51908bf8d8cc34b40dacb8d4b7cd02765edcb692988d98`.
The shader and animation sources/toolchains are unchanged in this follow-up.

## Scope

Coverage targets every installed playable character's default costume and its
discovered body forms/ordinary weapons. It does not cover every alternate
costume, NPC, summoned prop or animation. Characters absent from the installed
packages are reported separately.

The eye composite supplies static colour layers; Unreal's refraction, parallax,
full pupil controls and animated material graphs are not reproduced. Unsupported
animated effect layers are omitted explicitly, not represented as a faithful
game shader. In-game rendering and a new installer are not exercised here.
