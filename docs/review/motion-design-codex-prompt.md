# Codex prompt: motion review proposals 6–10

Paste everything below the line into Codex.

---

You are continuing work on Atelier, a desktop modding studio with a Bottle backend and a
vanilla JS frontend. Its motion language, Krackle, lives in `gui/motion/`. Read these
before editing:

1. `gui/motion/README.md`: the Krackle rules.
2. `docs/review/motion-design-review.md`: a ranked motion-design review. Proposals 1–5 are
   already implemented; each has an "Implemented" note.

## Where to start

- Check out branch `claude/blissful-thompson-03aa46` at `bf3ad13`, or later, and create
  your own branch from it. Its history is `6aee64b` (Wave 4b, `claude/jolly-lamport-a8bc3d`)
  → `8869c03` (review doc) → `bf3ad13` (proposals 1–5).
- **Neither branch is pushed** (remotes: `origin`/`upstream` = clownfetus/Atelier,
  `fork` = tendo625/Atelier). A local Codex can use the branch directly. A cloud Codex
  needs the user to push it first.
- Keep every file LF (`.gitattributes` has `* text=auto eol=lf`). Check line endings by
  counting `b'\r'` in Python; `grep $'\r'` is unreliable in Git Bash on this machine.

## Task: implement proposals 6–10 from the review doc

The doc gives the file, line and before/after values for each item. Summary:

6. **Viewport loader show-delay.** In `gui/motion/viewport-loader.js`, add 150 ms to the
   assembly delays of the dots and the sphere, using `fill: 'backwards'`. Keep mounting
   immediate so the static fallback icon never flashes. Empty and error stay immediate.
7. **One busy tempo.** Add `--krackle-beat: 1040ms` to `gui/tokens.css`. Change the stage
   head in `gui/motion/krackle-stage.js` (`headAngle`: `tau * 0.7 * TAU`) to
   `tau * (1000 / 2080) * TAU`, two beats per revolution. Change `SAVING_LOOP_MS` in
   `material-save.js` from 960 to 1040. Change `LOOP_DURATION_MS` in `viewport-loader.js`
   from 1200 to 1040, and keep bob, boil and drift as multiples of the beat.
8. **Logo entrance.**
   - Remove the opacity dip at the start: `logo-entrance.js` `ENTRANCE_START_OPACITY` 0.58
     becomes a full-opacity squash-stretch stamp: `translateY(1px) scale(1.04,.94)` →
     `scale(.98,1.02)` @ .45 → `none`, 320 ms, linear timing with per-keyframe easing. The
     test expects the first `animate()` call to have duration 320.
   - When the Full launch formation is drawing (`surface-adapters.js` `startupProgress`,
     kind `launch`), hold the topbar entrance and play it from
     `AtelierSurfaces.startupDone()`.
   - Delete the unused `am-logo-entrance-reveal` keyframes in `logo-entrance.css`.
9. **Exits accelerate.**
   - Trash drain in `gui/polish.js` (~line 119): clip the snapshot with
     `inset(100% 0 0 0)` and ease the dots with `cubic-bezier(.55,0,1,.45)`. Give `play()`
     an optional easing argument.
   - Add a 120 ms crossfade before the export button glyph reverts (`reset` in
     `export-feedback-ui.js`).
   - In `krackle-glyph.js`, add the same 140 ms busy → result fade (scale .7) that
     `export-feedback.js:296-301` uses.
   - Change `width .3s ease` at `style.css:596` and `:1191` to `width 200ms linear`.
10. **Cleanup.**
    - Remove the dead `.card` 150 ms transition at `style.css:180`; the rule at
      `style.css:1426-1427` already sets 120 ms.
    - Add `box-shadow` to that 120 ms transition list, for `.card.imported:hover`
      (`polish.css:17`).
    - Remove the never-set `[data-reduced-motion]` selectors in `folder-flap.css:63-64`.
    - Add `--studio-easing-exit: cubic-bezier(.3,0,1,1)` and
      `--studio-motion-exit: 120ms` to `tokens.css` and use them for the stray `ease`
      curves the doc lists.
    - In the README, the Empty Edited Assets entrance actually lasts ~625 ms, not "about
      480ms".
    - Use `background: inherit` in `texture-reconstruction.css:12`.

## Constraints (do not break)

- Krackle shapes are solid energy with punched bubbles. Use no outlines, gradients or symbols.
- Motion tiers come from `AtelierMotionPolicy`: Full/Calm/Off = 3/1/0, with
  `allows(tier)` as the gate. OS reduced motion forces Off, and Off is stills only.
  Under Off, `polish.css:69` stops every CSS animation and transition.
- Only one large stage at a time (`gui/motion/moment.js`).
- Particle frames must stay under the 8 ms median CPU budget. `surfaces_checks.py` measures
  it; it is currently ~0.6 ms.
- Krackle inks keep 3:1 contrast. Do not change ink values.
- Toasts: a dismissed toast leaves `#toast-area` at once and fades from an inert
  `#toast-exit-layer` (`AtelierPolish.leave`). Tests must target live toasts under
  `#toast-area`.

## Verification

Run these from the repo root:

- Python: `D:\AtelierDev\review-fixes-20261018\.venv\Scripts\python.exe`.
- Git: `C:\Users\thiag\AppData\Local\GitHubDesktop\app-3.6.7\resources\app\git\cmd\git.exe`.

The browser smokes must launch the installed Edge. Save this wrapper **outside the repo**,
for example as `edge_smoke.py` in a temp folder:

```python
import runpy, sys
from pathlib import Path
from playwright.sync_api._generated import BrowserType
_launch = BrowserType.launch
def launch(self, *args, **kwargs):
    kwargs.setdefault('channel', 'msedge')
    return _launch(self, *args, **kwargs)
BrowserType.launch = launch
script = Path.cwd() / 'tests' / 'browser_smoke.py'
sys.path.insert(0, str(script.parent))
sys.argv = [str(script)] + sys.argv[1:]
runpy.run_path(str(script), run_name='__main__')
```

Required, all must pass. These are the counts at `bf3ad13`:

```
python edge_smoke.py --surfaces-only --report-dir <tmp>/surfaces                 # 12 PASS
python edge_smoke.py --inks-dial-only --report-dir <tmp>/inks                   # 9 PASS
python edge_smoke.py --polish-only --report-dir <tmp>/polish                    # 13 PASS
python edge_smoke.py --texture-reconstruction-only --report-dir <tmp>/texture   # 11 PASS
python edge_smoke.py --report-dir <tmp>/full                                    # 156 PASS, ~3 min
```

The full run covers `logo_motion_checks`, `viewport_motion_checks`,
`material_save_motion_checks` and `export_motion_checks`, which are the suites most likely
to notice items 6–9.

## Done means

- Proposals 6–10 are committed on your branch with LF endings.
- All five runs above pass.
- Each of items 6–10 in `docs/review/motion-design-review.md` gets an "Implemented" note
  that records any deviation, and the status line at the top is updated.
- A short report lists the commits, test counts and anything not verified.
