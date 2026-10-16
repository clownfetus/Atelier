# Standing idle decoder

Build with `scripts/build_animation_decoder.py --tools <Tools-directory>` and .NET
SDK 10. The builder extracts the exact CUE4Parse assemblies from the installed
AtelierMesh bundle and publishes a self-contained Windows helper with the same
native decompression libraries. There are no runtime SDK or network dependencies.
CUE4Parse is [Apache 2.0 licensed](https://github.com/FabianFG/CUE4Parse).

The helper reads a mesh and a non-additive standing idle from the local game paks.
It checks shared bone names and parents and samples the real sequence at its
authored frame rate. The mesh exporter's Y/Z-swapped skeleton is compensated by
its inverse bind matrices in rest pose. Simply assigning Unreal animation tracks
to that skeleton distorts the character. This helper applies physical animation
deltas through the original exported world-space bind matrices and converts the
result back into local glTF tracks. This also handles reparented weapon bones and
preserves skin-specific attachment offsets.

Output schema version 2 uses `space: atelier-gltf-local`. The cache includes both
asset paths, helper modification time and mapping modification time. Preview
tracks and extracted game data are cache artifacts, never release/source assets.
Unit bone scales follow the current mesh export; runtime cloth/hair physics and
gameplay VFX are not simulated. Windows playback was verified with a real
`Lobby_Stand_Idle` clip. Wine playback needs separate validation.
