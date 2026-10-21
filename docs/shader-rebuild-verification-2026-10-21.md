# Shader reconstruction and verification â€” 21 October 2026

Atelier now has a maintained shader-tool reconstruction from pinned upstream
source. The original custom fork remains unavailable; its executable and search
history are retained under `shader.legacy` in the native input lock. The Windows
release workflow builds the replacement before packaging and rejects the legacy
seed as a source build.

## Source and build inputs

- [AtelierShader](../tools-src/AtelierShader) contains the CLI, shader extension
  and complete Cargo lock. It implements the six interfaces Atelier calls:
  `dump-shaders --index-only`, `extract-shader`, `patch-shader`, `pack`, `unpack`
  and `info`. Repeated unpack filters and game dependency containers are supported.
- [repak-rivals 40e42b9](https://github.com/natimerry/repak-rivals/tree/40e42b9130f52038a10d261f9f032e4dc661d1a2)
  and its [retoc-rivals e6c985e submodule](https://github.com/natimerry/retoc-rivals/tree/e6c985eac480275348976dcc6e8729c1de1bef40)
  provide the Unreal serializers, group decompression and container conversion.
  Their source archives have explicit SHA-256 pins.
- [The shader build lock](../tools-src/AtelierShader/build.lock.json) pins Rust
  **1.96.0**, compiler revision `ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96`, its
  Cargo/standard-library/MinGW archives, and **LLVM-MinGW 20261020** with its
  compiler, linker and Windows development libraries. It pins both git
  dependencies, every local source/recipe input and the Oodle DLL. Cargo.lock
  supplies exact registry versions and checksums.
- [The build recipe](../scripts/build_shader_tool.py) extracts a fresh verified
  compiler and uses a fresh private Cargo cache. Dependencies are fetched with
  `--locked`; compilation and native tests use `--frozen`. Release flags, stable
  path mapping and zero PE timestamps are recorded in the output manifest.
  Starting lock bytes and copied source/native snapshots identify the build
  even if the checkout changes while compilation runs.
- The recipe removes upstream's inherited standalone key default and writer
  fallback, and replaces its game-key test literal with a fixture. Shader Studio
  supplies the configured key through the child environment. Existing `-a`
  callers remain compatible. The companion pak preserves Rivals' encrypted
  index format. A changed Oodle sidecar is rejected before loading.
- Repak's MIT/Apache notices and retoc's MIT notice ship with the tool. The
  upstream GUI and managed physics porter are not built. The existing managed
  animation/import source and .NET pins remain in the
  [native input lock](../tools-src/native-tools.lock.json).

## Implementation and regression checks

Indexing reads only archive headers and derives shader sizes from group offsets.
It does not materialize or decompress every shader. Extraction reads the selected
group. Patching streams a complete loose library and preserves shader lookup
hashes, map membership and UE wrappers while rebuilding offsets and preload
ranges for changed code sizes. The library and asset metadata retain the same
Unreal content directory on Windows.

Native tests cover bounded headers, malformed DXBC, conflicting ranges, escaping
paths, concurrent package writes, metadata placement, command compatibility and
preserving existing output. The broader asset probe exposed a directory-creation
race in the extraction guard; it was repaired and covered by a 32-worker native
regression. Conversion failures now produce visible errors and a nonzero exit
status even with redirected progress output.

The real shader probe compares every index byte with the verified legacy
baseline, edits a float from **1.0 to 0.5**, signs the resulting DXIL through the
app's COM path, validates it independently with Microsoft DXV, and verifies
mod-only readback plus an untouched shader. It also tests malformed inputs,
existing outputs, the absence of the configured key in the executable, and a
tampered Oodle sidecar. Shader Studio's actual backend and the curve/MPC/Niagara
export paths are exercised separately.

Tests and extracted data stay under
`D:/AtelierDev/shader-rebuild-20261021/`. No game mod is installed. Windows x64 is
the verified build target; Linux retains its existing release inputs. The full
large shader library is indexed; edit/repack checks use the Global library.
In-game rendering and a new full installer are outside this verification.

Build commands are in [tools-src/README.md](../tools-src/README.md). The prior
[native-tool report](native-tool-inputs-verification-2026-10-21.md) records the
animation/import rebuilds and historical shader baseline.

## Verified results

| Check | Result |
| --- | --- |
| Independent source builds | Identical executable and build-input manifest |
| Native Rust tests | 6 format/extraction tests and 3 CLI tests passed |
| Backend regression suites | 49 passed; 503 reported unit tests plus 138 additional checks |
| Complete index parity | Every byte matches legacy: 8,455 Global and 1,133,918 Marvel shaders |
| Native metadata index | 0.953 seconds in a fresh output directory |
| Single native shader extraction | 0.062 seconds |
| App index, including SQLite | 7.907 seconds |
| App browse/disassembly/IR | 0.328 seconds |
| App signed export | 3.422 seconds, exact mod-only readback |
| Shader validation and safety | All 14 checks passed, including DXV, metadata placement, key scan and tampered Oodle |
| Curve/MPC/Niagara exports | All edited values and LUT samples survived readback; blocked output failed safely |

These are local measurements; the output directories are fresh and the OS file
cache was not cleared. The backend total includes the existing optional Blender
and legacy native-tool skips. Native probes used the actual reconstructed tool.

Executable SHA-256:
`3eaf66d4e48b13d00e63c46e5703e709556af709dc51b54c1d09c8b4b9c49165`.

The [machine-readable evidence](shader-rebuild-verification-2026-10-21.json)
records exact build inputs, matching outputs, native commands, index hashes,
shader-container stamps and application results. No extracted shader or game
asset is committed.
