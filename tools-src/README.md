# Native tool inputs

[`native-tools.lock.json`](native-tools.lock.json) is the build-input record for
Windows x64. Shader build details are in
[`AtelierShader/build.lock.json`](AtelierShader/build.lock.json).

| Tool | Source/build status | Pinned inputs |
| --- | --- | --- |
| AtelierAnimation | Source is committed; two independent builds produced identical executables and manifests. | C# source and project hashes, .NET SDK 10.0.402, runtime 10.0.13, NuGet archive SHA-512 values, mesh bundle and 32 dependency DLL hashes, native libraries, build recipe. |
| Shader retoc | Maintained reconstruction from pinned upstream source. The original private fork remains unavailable. | Committed shader commands and Cargo.lock, upstream archive hashes/revisions, both git dependencies, Rust 1.96.0 compiler/standard-library/Cargo archives, LLVM-MinGW 20261020 compiler/linker/Windows headers and libraries, Oodle, build recipe and output hashes. DXC remains a separately pinned runtime dependency. |
| AtelierImport | Source is committed; shares the animation decoder's pinned build recipe. | Its own source/project/restore lock plus the same verified compiler/runtime/dependency inputs. |

The reconstructed shader tool uses
[repak-rivals 40e42b9](https://github.com/natimerry/repak-rivals/tree/40e42b9130f52038a10d261f9f032e4dc661d1a2)
and its exact
[retoc-rivals submodule e6c985e](https://github.com/natimerry/retoc-rivals/tree/e6c985eac480275348976dcc6e8729c1de1bef40).
Atelier's committed CLI and shader extension reuse that library's serializers,
decompression and packing code. This is a new fork, not recovered original source.
The old executable/source-search record stays under `shader.legacy`; the seed
binary is retained only as an input/parity baseline and is replaced before packaging.

Supported application interfaces are `dump-shaders --index-only`, `extract-shader`,
`patch-shader`, `pack`, `unpack` (including repeated `--filter` and
`--game-paks-dir`) and `info`. Other historical custom commands are not advertised.
Indexing derives sizes from headers without decompressing groups; extraction reads
one group. Patching streams a complete loose library, preserves shader lookup hashes,
map membership and UE wrappers, and updates offsets/preloads for changed shader sizes.
Upstream packing rebuilds its groups into a self-contained mod container.

Keys are runtime inputs, never compiled defaults. Shader Studio passes the current
key through `ATELIER_RETOC_AES_KEY`; existing `-a` container callers remain compatible.
IoStore output remains unencrypted, while the companion pak retains Rivals' encrypted
index format. Changed Oodle sidecars are rejected before loading.
Parallel package extraction validates each output directory while allowing other
workers to create it. Conversion failures are logged and return a failing exit
status, including when ordinary redirected output hides upstream's progress bar.

The matching CUE4Parse assemblies embed revision
[`ea85cf20d8df53556f399c5fabc2befb46b65d0d`](https://github.com/FabianFG/CUE4Parse/commit/ea85cf20d8df53556f399c5fabc2befb46b65d0d).
The exact DLL bytes extracted from the pinned AtelierMesh bundle are the build
inputs. This does not assert that recompiling that upstream revision reproduces
the developer's bundled DLLs.

## Build on Windows

Install .NET SDK **10.0.402**. Its Windows SDK ZIP URL and SHA-512 are recorded in
the lock, from Microsoft's
[10.0 release metadata](https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json).
`global.json` disables SDK roll-forward. The two project restore locks pin the
ILLink dependency, and the recipe separately verifies the exact runtime package
archives before an offline restore into a new private package cache.

From the checkout, choose a fresh tools directory:

```powershell
python scripts/fetch_native_inputs.py --tools D:/AtelierBuild/Tools
python scripts/verify_native_inputs.py --tools D:/AtelierBuild/Tools --tool animation
python scripts/build_animation_decoder.py --tools D:/AtelierBuild/Tools
python scripts/build_import_server.py --tools D:/AtelierBuild/Tools
python scripts/build_shader_tool.py --tools D:/AtelierBuild/Tools --output D:/AtelierBuild/Shader-built --cache D:/AtelierBuild/archives --log D:/AtelierBuild/shader-build.log
foreach ($name in @('retoc-rivals-cli.exe', 'oo2core_9_win64.dll', 'build-inputs.json')) {
    Copy-Item -LiteralPath "D:/AtelierBuild/Shader-built/$name" -Destination "D:/AtelierBuild/Tools/shaders/$name" -Force
}
Copy-Item -LiteralPath D:/AtelierBuild/Shader-built/licenses -Destination D:/AtelierBuild/Tools/shaders -Recurse -Force
python scripts/verify_native_inputs.py --tools D:/AtelierBuild/Tools --require-shader-source
```

The fetcher verifies the 0.4.0 `windows-tools.zip` seed and copies only the pinned
mesh/shader inputs. It excludes configuration, keys, mappings, user data and other
tools. For an already downloaded archive, pass `--seed <windows-tools.zip>`.
There is no installer execution. These inputs alone are for building/testing the
helpers, not a complete runnable Atelier installation.

If the SDK is portable, pass `--dotnet <absolute-path-to-dotnet.exe>` to either
builder. `--output <fresh-folder>` selects an independent output. Existing output
directories are refused. Each build snapshots and verifies its input files,
publishes only after restore/compilation succeeds, and writes `build-inputs.json`
with the recipe, input and output hashes. Builds use Release, win-x64,
self-contained single-file output, embedded debug data and a stable source map.
Builds require no game files, mappings or configured encryption key.

The shader recipe installs no system compiler. It verifies downloaded source and
compiler archives before extracting a fresh private toolchain. Cargo fetches with
`--locked` into a fresh private cache, then builds/tests with `--frozen`. The committed
Cargo lock includes checksums for the registry packages and exact git commits.
Release flags, path remapping and zero PE timestamps are recorded in the build manifest.
The initial lock bytes identify the build even if the checkout changes later;
copied sources and the native DLL are verified again before compilation.
The recipe removes upstream's standalone CLI key default and obfuscated-writer
fallback, and replaces the inherited game-key test literal with a fixture key.
Failed builds publish no partial executable; existing output directories are refused.
The build log stays outside the release payload. MIT/Apache notices for repak and the
retoc MIT notice ship beside the tool. The parent GUI and its GPL components are not built.

The Windows release-candidate workflow verifies the native seed, replaces its
historical animation and shader executables with source builds, builds AtelierImport,
requires matching shader build provenance, and archives all three input manifests.
Linux retains its
existing release inputs; this change does not claim a verified Linux rebuild.

## Checks

```powershell
python tests/run_checks.py --suite test_native_build_inputs.py --suite test_shader_build_inputs.py --suite test_dxc_ir.py
python scripts/verify_native_inputs.py --tools D:/AtelierBuild/Tools --require-shader-source
```

The source guard now requires the reconstructed executable, its exact input lock
and its matching build manifest. It rejects the legacy seed. Raw historical retoc
help is still never logged because older builds include an embedded key default.

Opt-in native probes are `tests/native_animation_smoke.py`,
`tests/native_shader_smoke.py`, `tests/native_shader_app_smoke.py` and
`tests/native_viewer_smoke.py`; use their help
for the isolated data/report arguments. Run the shader index probe separately
from other memory-heavy native checks. Extracted shaders and animation tracks
stay in the external report directory. Probes never install a mod.

See [shader reconstruction verification](../docs/shader-rebuild-verification-2026-10-21.md)
and the earlier [native tool verification](../docs/native-tool-inputs-verification-2026-10-21.md)
for the actual rebuild, shader validation/readback and desktop playback results.
