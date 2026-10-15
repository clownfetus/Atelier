# README screenshots

The four current-interface screenshots were captured on 15 October 2026 from
source commit `f0e4328b68f8cc7346a922516d7cf5c86ea57e43`. They show the actual
Bottle-served frontend in Chromium at 1400 × 900, without cropping, compositing
or image edits.

| File | View |
| --- | --- |
| `studio-dark.png` | Asset library, Atelier palette, dark mode |
| `studio-light.png` | The same library and project in light mode |
| `material-editor.png` | Material color/dye groups, scalar values and comparisons |
| `appearance-settings.png` | Appearance settings with the Repak X palette |

All asset lists, material values, configured paths and validation responses use
explicit synthetic fixtures in a disposable **Example Mod** project. There is
no extracted game artwork, real project data or live AES key in these captures.
No mod was built or installed. The screenshots demonstrate the interface, not
native game compatibility or a completed installer release.

The capture run reported no uncaught page errors. The complete existing
Chromium/Bottle suite also passed all 88 groups with no page errors on the same
source tree. Re-run that suite with:

```powershell
.\.venv\Scripts\python.exe tests/browser_smoke.py --report-dir _work/readme-browser-checks
```

Its deterministic review captures use `Smoke A` and additional workflow fixtures;
see [the review screenshot notes](../docs/review/README.md) for their scope.

The original `screenshot.png` and `skin_ids.png` remain available for historical
references. `rivals_path.png` remains the Steam folder-location illustration.
