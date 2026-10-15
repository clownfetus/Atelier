# Appearance review — 15 October 2026

This interface change adds persistent palettes, themed dropdowns and monochrome
branding. Its changes are limited to `gui/`, UI/browser/desktop tests and design/review documentation.
Packaging, native modding tools, Python backend behavior and project formats have
not been modified. The original logo artwork remains intact.

## Result

- First-run configuration and Menu → Settings offer Light, Dark and System.
  The toolbar theme selector is removed. Mode and palette choices persist before
  the first paint, follow OS changes in System and synchronize other windows.
- Atelier, Darcula and Repak X each show four adjacent color circles, with light
  and dark variants. Repak X uses near-black/dark-grey/red. The final + Custom
  control exposes background, foreground, surface and accent native color inputs.
- Custom drafts retain separate light/dark colors. Name and save multiple reusable
  palettes, select them later or delete them. Stored data is versioned and checked;
  corrupt or blocked storage still permits in-session use. Names render as text.
- Semantic surfaces, text, accents, statuses and component foregrounds derive from
  the palette. Low-contrast choices retain their requested colors in storage while
  rendered text/surface shades adapt to remain readable. Settings explains this.
- The logo and wordmark use matching black/white tones, including the animated
  mark and fallback. Custom backgrounds also select a readable monochrome tone.
  Menu sits at the far right after Activity; search and back/forward remain usable.

The four-color system uses Material 3 semantic roles. It does not implement
Android wallpaper extraction or HCT tonal-palette generation.

## Dropdown, menu and popup audit

| Surface | Coverage |
| --- | --- |
| Library Type, Status and Sort | Shared select, option, border, hover/focus and selected roles |
| Settings appearance | Same real select semantics and Light/Dark/System values |
| Curve interpolation, generated after opening a curve | Same global select and popup rules |
| Texture export group, generated after opening export options | Same global rules; existing values unchanged |
| Shader library and stage | Same global rules; existing filtering unchanged |
| Bulk source, operation and channel selects | Global popup rules; corrected previously undefined surface variable |
| Main, asset, edited-asset and project context menus | Shared menu surface, text, hover/focus and danger roles; existing arrow/Escape/focus return behavior |
| Settings, editors, export review, Activity and preview dialogs | Existing semantic-role styling inherits the selected palette |
| Tooltips, including dynamic controls | Delegated title tooltips use palette surfaces/text, preserve accessible names/descriptions and support Escape |

Selects remain real HTML controls. Supporting browsers and WebView2 use
`appearance: base-select`/`::picker(select)` for styled popup surfaces, option
hover/focus, selection and checkmarks. A feature query preserves classic native
selects on older engines. Explicit color and color-scheme roles still apply, but
OS-owned highlights, native color-picker chrome and native input context menus
cannot be fully recolored by page CSS. See the [platform behavior documented by
MDN](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms/Customizable_select).

Keyboard behavior is retained rather than reimplemented with custom listboxes.
Select labels, focus outlines and option semantics remain; context menus return
focus to their opener. This is targeted keyboard/semantic verification, not a
claim of a complete screen-reader accessibility audit.

## Validation

- Full Chromium/Bottle suite: **89 passing groups, no page errors**, including
  material drafts/saves, bulk editing, Activity, export review, keyboard navigation
  and a real decoded GLB with repeated preview disposal. Report:
  `_work/appearance/acceptance/results.json`.
- Final contrast/branding refinement: **15 passing focused groups, no page errors**.
  All six preset variants and custom colors pass measured 4.5:1 text/semantic
  role checks across surfaces, including lowest/highest containers. Extreme
  white-on-white/black-on-black choices adapt without losing stored choices.
  Report: `_work/appearance/final-colors/results.json`.
- Actual Windows **WebView2 / Edge 155**: six preset variants, option roles,
  monochrome branding, native color inputs, saved palette creation/deletion,
  actual mouse-open/ArrowDown/Enter/Escape selection, and named palette/mode
  persistence after reload pass. Desktop screenshot capture required briefly
  showing the disposable fixture window; it closed after the checks. Report:
  `_work/appearance/desktop-final-captures/desktop-smoke.json`.
- Forced classic-select CSS fallback passes in both modes. This exercises fallback
  behavior on the installed engine, not a separately installed older WebView2.
- JavaScript syntax, Python test syntax, DOM smoke and whitespace checks pass.

The first full run encountered a bulk-save timeout; its focused rerun and the
subsequent complete runs passed. A test fixture that intentionally left remote
startup requests unresolved was completed when opening Settings, including after
reload. No backend workaround was introduced.

Repeat with isolated temporary/data directories:

```powershell
$env:TEMP = Join-Path (Get-Location) '_work/test-temp'
$env:TMP = $env:TEMP
.venv/Scripts/python.exe -B tests/browser_smoke.py --appearance-only --report-dir _work/new-theme-check
$env:ATELIER_DATA_DIR = Join-Path (Get-Location) '_work/new-theme-desktop'
.venv/Scripts/python.exe -B tests/desktop_smoke.py --fixtures --interactions
```

`--interactions` briefly shows the Windows fixture window for real input and
screenshots. Without it, the desktop smoke stays hidden. No game tools or installs
run in these checks. No packaged executable was rebuilt.

## Screenshots

These are unaltered captures of synthetic folder/project fixtures, without private
projects or extracted game artwork.

| Browser | Windows WebView2 |
| --- | --- |
| [Repak X dark Settings](settings-repak-dark.png) | [Saved custom dark Settings](windows-settings-dark.png) |
| [Darcula light Settings](settings-darcula-light.png) | [Light Settings](windows-settings-light.png) |
| [Dark workspace](workspace-dark.png), [light workspace](workspace-light.png) | [Dark workspace](windows-workspace-dark.png) |
| [Open light dropdown](dropdown-light.png), [first-run setup](first-run.png) | [Open light dropdown](windows-dropdown-light.png) |

Upstream main through `d592133` is now integrated into the PR branch. The
[merge-resolution report](../pr3-merge.md) records how both tool-staging changes
were retained and the complete checks run after resolving the conflicts.
