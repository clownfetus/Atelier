# Material 3 foundation

Atelier remains a desktop creative application built with vanilla JavaScript, Bottle, Three.js and pywebview. This phase establishes shared visual rules and improves browsing without changing the asset pipeline, project format, native tool commands or mod container formats.

## Direction and sources

The palette uses graphite and blue-grey surfaces, ice-blue primary actions and muted teal secondary containers. Light mode uses pale blue-grey surfaces and a deeper blue primary. Red is reserved for errors and destructive actions. Texture and 3D preview surrounds remain neutral so changing the interface theme does not change the artwork being evaluated.

This is a desktop adaptation of [Material 3 color roles](https://m3.material.io/styles/color/roles), [typography](https://m3.material.io/styles/typography/applying-type), [buttons](https://m3.material.io/components/buttons/overview), [motion](https://m3.material.io/styles/motion/overview/how-it-works) and Google's [Material 3 Expressive research](https://design.google/library/expressive-material-design-google-research). It adopts their hierarchy, containment, shape and purposeful motion principles while keeping desktop density. It is not a claim of full Material component or accessibility conformance.

## Implementation map

| File | Responsibility |
| --- | --- |
| `gui/tokens.css` | Semantic color pairs, local font, type, spacing, shape and motion tokens |
| `gui/theme.js` | System/light/dark preference, OS changes and safe localStorage persistence |
| `gui/style.css` | Layout and component styling, including existing editors |
| `gui/icons.js` | Local Material Symbols SVG adapter; compatibility with existing icon calls |
| `gui/vendor/material-symbols/` | Vendored glyph paths, source URLs/hashes and Apache 2.0 license |
| `gui/brand/atelier-mark.png` | Transparent blue Atelier A mark, also exported as root PNG/ICO |
| `atelier/catalogue.py` | Optional character/skin metadata refresh and image cache |
| `gui/catalogue.js` | Non-blocking launch check and Settings status |

Use semantic foreground/background pairs instead of adding hexadecimal colors to individual components. Existing `--bg`, `--text`, `--acc` and related aliases keep dynamically generated editors compatible. Add a role to the token file when a new state needs one; do not use the primary color to mean an error.

| Role | Light | Dark |
| --- | --- | --- |
| Surface | `#f7f9fd` | `#10141c` |
| Low container | `#eef2f8` | `#181e29` |
| High container | `#e1e7f0` | `#283140` |
| Primary | `#335d9f` | `#accbff` |
| Primary container | `#d8e6ff` | `#264677` |
| Secondary container | `#d6e7e4` | `#304b48` |
| Main text | `#19202b` | `#e3eaf5` |
| Supporting text | `#454f60` | `#bcc8dc` |

Roboto is bundled locally with its SIL Open Font License; there is no font CDN request. The desktop scale uses 14px body text, 13px controls, 12px supporting labels and 20px titles. Controls are generally 36px tall; compact numeric editor controls remain 30px. The workspace has a 64px toolbar, 12px outer inset, 156px asset tiles and a resizable 240–520px export sidebar. Tested window sizes start at 1024×768.

Native buttons, selects and inputs provide keyboard behavior. Asset cards and breadcrumb ancestors are keyboard-operable buttons. Context menus support arrows, Home/End, Escape and focus return. Focus rings remain visible. Full modal focus containment, screen-reader workflow auditing, high-contrast mode and smaller windows remain follow-up work.

## Theme and motion

Appearance defaults to System and is persisted under `atelier.theme` in browser/WebView storage. Both selectors stay synchronized; selecting a theme never writes Python configuration or project metadata. The preference is applied before CSS to avoid an opposite-theme flash. Unavailable storage falls back to an in-session preference. Browser mode and the desktop profile have separate preferences.

Use 120ms for small state changes and 200ms for entering surfaces. Dialogs fade/translate 8px; buttons change corner shape on press; cards compress slightly and portraits ease into a subtle hover zoom. Loading uses the existing indicators. Avoid delaying input, animating layout in the asset grid, or adding idle animation to 3D previews. `prefers-reduced-motion: reduce` removes CSS animations and transitions.

## Symbols and brand assets

[Material Symbols Rounded](https://developers.google.com/fonts/docs/material_symbols) use filled glyphs for a coherent silhouette. Folder glyphs occupy 76% of their tile; toolbar glyphs stay compact. Existing `data-lucide` markers and `lucide.createIcons` calls are retained as a compatibility boundary; the production page loads the local Material adapter, not the old library. Glyph provenance is recorded in `gui/vendor/material-symbols/sources.json`, pinned to Google repository commit `49d4db35df873165d6bd6ba09b063c7dafbac2f4`. Keep accessible names on buttons; decorative SVGs are hidden from assistive technology.

The new A mark was generated with Image Gen through Creative Production and refined to a clear blue, preserving its rounded silhouette, separated strokes and transparent background. The final refinement prompt requested: "Preserve the exact geometry, negative spaces and transparency; recolor uniform flat clear blue #5487db, no gradients or shadows." `gui/brand/atelier-mark.png` is the working artwork for this implementation; `icon.png` and multi-size `icon.ico` are technical exports of the same image. No new logo/font/icon runtime dependency is required.

## Character and skin artwork

Names and numeric IDs come from [donutman07/MarvelRivalsCharacterIDs](https://github.com/donutman07/MarvelRivalsCharacterIDs); artwork and costume-page IDs come from [RivalSkins](https://rivalskins.com/heroes/). Settings links to both sources. Marvel Rivals artwork belongs to its respective owners; the bundled seed contains metadata and source links, not the remote artwork binaries.

Matching uses costume-page numeric game IDs first. When a recolor page omits an ID, only a unique normalized exact name within the same hero is accepted. No fuzzy matching is used. Conflicting IDs, ambiguous names and NPCs sharing a playable hero's name are not silently assigned unrelated skin art. Missing skin art uses a labelled hero portrait; unavailable heroes use the folder symbol. Default skin IDs are not invented.

The current seed contains 54 hero portraits and 690 matched costume artworks: 558 by source ID and 132 by exact name. Six named skins use hero fallbacks. Sixty entries have no artwork, mostly NPCs and future/unlisted heroes. Unknown skin folders can also fall back to their known hero. These counts describe the seed snapshot, not guaranteed future source coverage.

At every backend launch, the frontend starts one background catalogue check through `/api/catalogue/status`. The worker checks the ID list and roster; a changed source, changed parser version or 24-hour age triggers a full metadata refresh. Individual costume pages are cached for seven days. This avoids recrawling hundreds of pages on each launch. Images load lazily when browsing and are cached by source URL under `ATELIER_DATA_DIR/_cache/catalogue`. Changed URLs produce new cache files; artwork replaced at an identical URL remains cached until that cache entry is removed.

Network requests have time/size limits, an explicit HTTPS source allowlist, redirect validation and at most three concurrent artwork requests. Only verified WebP images are accepted. Metadata is published atomically after a successful refresh; offline or changed-source failures retain the last usable catalogue. Fresh installations need a connection to fetch images the first time; cached images remain available offline. Neither update checks nor image failure block editing or export. This is an artwork update check; Atelier's existing application updater is unchanged.

`/api/browse` keeps existing names, paths and type identifiers and adds optional `thumbnail`/`hero_fallback` fields plus display labels. The two new GET endpoints have no project writes. New previews do not enter imported assets, sidecars, built containers or mods folders.

## Verification and next steps

See `DEVELOPMENT.md` for reproducible commands. Automated coverage includes color contrast, theme persistence, OS preference changes, blocked storage, local fonts/logo, icon coverage, keyboard menus, four desktop sizes, reduced motion and preserving a live material draft while changing themes. Catalogue tests use offline fixtures for parsing, ID boundaries, ambiguity, source validation, failed refreshes and cached images.

This foundation retains the current information architecture. A later phase can improve asset filtering, material panel organization and preview/export workflows independently. Full game-version compatibility and end-to-end manual editor coverage remain release checks; the visual/browser tests do not replace them.
