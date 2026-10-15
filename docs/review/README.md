# Review screenshots

These unmodified PNG captures come from the deterministic Chromium checks in
`tests/browser_smoke.py`. They contain synthetic folder/material fixtures, local
interface artwork and a disposable `Smoke A` project name. They contain no
extracted game portraits/textures or private project data.

- `studio-dark.png` and `studio-light.png`: category coverage fixture from
  `tests/category_icon_checks.py`, 1575 x 884.
- `material-editor-light.png`: material workflow fixture from
  `tests/material_workflow_checks.py`, 1400 x 900. The remaining unsaved parameter
  and warning demonstrate preservation of edits made during an in-flight save.

The files are copied without cropping, recoloring or other image edits. Run the
browser suite to regenerate the full evidence set, including both-theme material,
export, motion and compact-window captures.
