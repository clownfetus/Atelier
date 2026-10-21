# Blade preview verification — 2026-10-21

Blade's lobby preview rendered white tattoos, hair and eyebrows, and attached
the dagger with its blade pointing in the opposite direction. These were
preview material and attachment errors; rebuilding shader-container tools
does not reproduce Unreal's material graph inside Three.js.

## Corrections

- Use the actual `EmissiveColor` before unrelated `BaseGlowColor` parameters.
  Preserve `EmissiveStrength=0` and small positive strengths. Clear emission
  when its texture is removed. Edited and Original views use the same helper.
- Resolve a material shared by several cooked slots when every candidate names
  the same full material package. Blade's hair and outline slots share
  `MI_1044001_Hair_02`; its diffuse and opacity maps now reach the hairline and
  eyebrows. A shared preview material has no guessed individual section index,
  so its separate section-visibility control remains disabled. Conflicting
  material packages remain ambiguous.
- Attach Blade's dagger using its authored `WP_Sword` grip below `WP_Root`.
  Preserve explicit handle/grip and hand-socket priority. The browser and
  portable Blender assembly both use this selection rule.

## Validation

Windows x64, installed game assets, rebuilt pinned shader tool, disposable
application data and its own `test-mods` directory:

- 21 Model Studio, 6 frontend and 29 Blender/material/attachment unit tests pass.
- The complete browser suite passes 225 checks with no page errors; the 13
  viewport feature and 4 frontend cache tests also pass. Dependency consistency,
  Python parsing, credential-literal scanning and whitespace checks pass.
- `tests/native_blade_preview.py` loads the real lobby body, dagger, material
  parameters, textures and standing idle through the application API. It checks
  both hair materials, disabled tattoo emission, shared-material identity and
  Original comparison. No page or asset errors occurred.
- Actual skinned tip vertices point along the hand socket in both idle and
  rest poses (direction dot product effectively 1); grip error is below
  0.00001 metres. The real extracted mesh also passes the Blender attachment
  matrix check, with maximum element error `1.11e-16`.
- Dark-theme whole-model and face close-ups were inspected. Final cached load
  took 11.03 seconds on this machine; this is a local observation, not a general
  performance guarantee.

The test does not save material changes or install mods. A new installer and
in-game rendering were not exercised. Verification metadata without game asset
payloads or private configuration is recorded in
[the companion receipt](blade-preview-verification-2026-10-21.json).
