# Bundled frontend dependencies

These local dependencies are included in the source tree and in desktop builds
through `Atelier.spec`'s `gui` data directory. Preserve the linked license files
when redistributing them.

| Local files | Version or source snapshot | Source | License |
| --- | --- | --- | --- |
| `three/three.core.min.js`, `three/three.module.min.js`, `three/jsm/` | Three.js r185 / 0.185.0 (revision declared by the bundled core) | [three.js r185](https://github.com/mrdoob/three.js/tree/r185) | [MIT](three/LICENSE) |
| `roboto/Roboto-Variable.ttf` | Google Fonts snapshot; SHA-256 `d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134` | [Roboto source and download record](roboto/README.md) | [SIL Open Font License 1.1](roboto/OFL.txt) |
| `bricolage-grotesque/BricolageGrotesque-Latin.woff2` | Google Fonts v9 Latin variable subset, retrieved 2026-10-18 | [Source and SHA-256](bricolage-grotesque/README.md) | [SIL Open Font License 1.1](bricolage-grotesque/OFL.txt) |
| `instrument-sans/InstrumentSans-Latin.woff2` | Latin variable subset from the identity sheet v1.0, copied 2026-10-28 | [Source and SHA-256](instrument-sans/README.md) | [SIL Open Font License 1.1](instrument-sans/OFL.txt) |
| `fragment-mono/FragmentMono-Latin.woff2` | Latin subset from the identity sheet v1.0, copied 2026-10-28 | [Source and SHA-256](fragment-mono/README.md) | [SIL Open Font License 1.1](fragment-mono/OFL.txt) |
| `material-symbols/symbols.js` | Material Symbols Sharp paths from commit `49d4db35df873165d6bd6ba09b063c7dafbac2f4` | [Per-symbol source URLs and hashes](material-symbols/sources.json) | [Apache 2.0](material-symbols/LICENSE) |

Atelier's adapter preserves existing icon aliases while using the Material Symbols
paths. Adapted animation artwork and its provenance are documented separately in
the [motion inventory](../motion/README.md).
