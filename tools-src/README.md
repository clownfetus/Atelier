# Native tool inputs

[`native-tools.lock.json`](native-tools.lock.json) is the build-input record for
Windows x64. It distinguishes a source build from a historical executable whose
source has not been recovered.

| Tool | Source/build status | Pinned inputs |
| --- | --- | --- |
| AtelierAnimation | Source is committed; two independent builds produced identical executables and manifests. | C# source and project hashes, .NET SDK 10.0.402, runtime 10.0.13, NuGet archive SHA-512 values, mesh bundle and 32 dependency DLL hashes, native libraries, build recipe. |
| Shader retoc | **Original custom fork source is unavailable. This is a verified legacy binary, not a reproducible source build.** | Exact `retoc-rivals-cli.exe` 3.4.1, Oodle and DXC files, release archive URLs and SHA-256 values, required custom commands. |
| AtelierImport | Source is committed; shares the animation decoder's pinned build recipe. | Its own source/project/restore lock plus the same verified compiler/runtime/dependency inputs. |

The shader source search covered the historical Atelier trees and source archives,
local working/archived checkouts, the author's public repositories/gists, and the
public repak/retoc branches and forks. Public
[repak-rivals v3.4.1](https://github.com/natimerry/repak-rivals/tree/c45019606900d5fd3c103b282814392295203272)
reports the same version but lacks the custom shader commands. Its ancestry to the
custom executable is unverified. Its source and Cargo.lock are **not** substituted
for the missing fork. `repository`, `revision`, `cargo_lock_sha256` and
`build_recipe` remain null in the shader source record.

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
python scripts/verify_native_inputs.py --tools D:/AtelierBuild/Tools
python scripts/build_animation_decoder.py --tools D:/AtelierBuild/Tools
python scripts/build_import_server.py --tools D:/AtelierBuild/Tools
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
No game files, mappings or encryption keys are used to build either helper.

The Windows release-candidate workflow verifies the native seed, replaces its
historical animation executable with this source build, builds AtelierImport,
and archives both input manifests in the verification report. Linux retains its
existing release inputs; this change does not claim a verified Linux rebuild.

## Checks

```powershell
python tests/run_checks.py --suite test_native_build_inputs.py --suite test_dxc_ir.py
python scripts/verify_native_inputs.py --tools D:/AtelierBuild/Tools --require-shader-source
```

The second command deliberately fails while the original shader source is
missing. Normal input verification reports that limitation while checking the
known executable and capabilities. Raw retoc help is never logged because it
contains an embedded game-key default.

Opt-in native probes are `tests/native_animation_smoke.py`,
`tests/native_shader_smoke.py` and `tests/native_viewer_smoke.py`; use their help
for the isolated data/report arguments. Run the shader index probe separately
from other memory-heavy native checks. Extracted shaders and animation tracks
stay in the external report directory. Probes never install a mod.

See [verification evidence](../docs/native-tool-inputs-verification-2026-10-21.md)
for the actual rebuild, shader validation/readback and desktop playback results.
