# Bundled frontend dependencies

These local dependencies are included in the source tree and in desktop builds
through `Atelier.spec`'s `gui` data directory. Preserve the linked license files
when redistributing them.

| Local files | Version or source snapshot | Source | License |
| --- | --- | --- | --- |
| `three/three.core.min.js`, `three/three.module.min.js`, `three/jsm/` | Three.js r185 / 0.185.0 (revision declared by the bundled core) | [three.js r185](https://github.com/mrdoob/three.js/tree/r185) | [MIT](three/LICENSE) |
| `inter/InterVariable.woff2` | Inter v4.1 variable font (Inter and Inter Display), downloaded 2026-11-07 | [Source and SHA-256](inter/README.md) | [SIL Open Font License 1.1](inter/OFL.txt) |
| `fragment-mono/FragmentMono-Latin.woff2` | Latin subset from the identity sheet v1.0, copied 2026-10-28 | [Source and SHA-256](fragment-mono/README.md) | [SIL Open Font License 1.1](fragment-mono/OFL.txt) |
| `material-symbols/symbols.js` | Material Symbols Sharp paths from commit `49d4db35df873165d6bd6ba09b063c7dafbac2f4` | [Per-symbol source URLs and hashes](material-symbols/sources.json) | [Apache 2.0](material-symbols/LICENSE) |

Atelier's adapter preserves existing icon aliases while using the Material Symbols
paths. Adapted animation artwork and its provenance are documented separately in
the [motion inventory](../motion/README.md).
