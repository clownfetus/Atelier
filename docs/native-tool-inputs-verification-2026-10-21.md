# Native tool provenance and verification — 21 October 2026

AtelierAnimation now rebuilds from checksum-pinned inputs. The original custom
shader retoc fork source was **not found**. Its exact historical executable is
pinned and tested, and the lock explicitly records that it is not source
rebuildable. This follow-up also fixes DXIL signing and a reproduced Windows
import-cache race.

## Inputs and source availability

- The [native input lock](../tools-src/native-tools.lock.json) identifies the
  historical Windows tools seed by SHA-256, pins the mesh/native/DXC files, and
  records 32 exact managed dependency DLLs extracted from AtelierMesh. Its
  CUE4Parse assemblies identify upstream revision
  `ea85cf20d8df53556f399c5fabc2befb46b65d0d`; that revision alone is not claimed to
  reproduce the developer's bundled assemblies.
- Both managed helpers pin their source/project/restore-lock files, the build
  recipe, .NET SDK **10.0.402**, runtime **10.0.13**, and the exact ILLink/runtime
  NuGet archives. SDK roll-forward is disabled. Restores use verified archives
  and a private package cache. Builds preserve existing installations and publish
  only after successful compilation.
- The official SDK ZIP was downloaded from the URL in Microsoft's release
  metadata, its SHA-512 verified, and 5,577 files extracted into a fresh compiler
  directory. Builds using that compiler match the earlier independent builds.
- The installed shader retoc matches both the historical 0.3.3 bundle and the
  pinned 0.4.0 tools seed: SHA-256
  `f6a9b08183c778cad9a8b2872046c7d8a52baa59eea0998610da041f1f89e77d`.
  Its `dump-shaders`, `extract-shader`, patch, map and pack commands are checked
  after verifying the executable hash. Raw help is not logged because it embeds
  a game-key default.
- Searches covered local working/archived trees, source ZIPs, historical Atelier
  trees, public repositories/gists, and public repak/retoc branches and forks.
  [repak-rivals v3.4.1](https://github.com/natimerry/repak-rivals/tree/c45019606900d5fd3c103b282814392295203272)
  and the current public CLI lack the custom shader commands. A matching version
  number does not establish the custom fork's ancestry. Its original repository,
  revision, Cargo.lock, linker and build flags remain unavailable; corresponding
  lock fields remain null. `--require-shader-source` correctly fails.

The [build instructions](../tools-src/README.md) include a fresh-directory seed
fetcher that excludes keys, mappings and other runtime data. The Windows release
workflow now verifies inputs, rebuilds AtelierAnimation and AtelierImport, and
archives both build-input manifests.

## Rebuild and native checks

- Independent animation builds produce byte-identical executables **and input
  manifests**. The official SDK build matches them. Animation executable SHA-256:
  `a3dea66d1aa295d9fc1047611995586a67798dffa7ba01d15350d63737b8f127`.
  The import server also matches its official-SDK rebuild.
- A real Black Widow lobby idle matches the previously installed decoder exactly:
  **655 bone tracks, 340 frames**, including all metadata and every sample. All
  tracks have finite, aligned values and normalized rotations; 372 bones have
  measured rotation changes. The glTF local coordinate schema is retained.
- The native retoc index contains **1,142,373 shaders**: 8,455 Global and 1,133,918
  Marvel shaders. Extraction, DXC disassembly, application COM assembly, retoc
  patching/packing and mod-only readback pass. An untouched shader remains
  byte-identical, and an out-of-range index fails without publishing a blob.
- The final signed round trip reuses the earlier successful full index after
  checking tool hashes, original container stamps and library totals; its index
  files are fingerprinted in the final report. The changed shader is signed and
  passes the separate pinned Microsoft DXV executable. The packed mod reads back
  exactly, including the changed DXBC bytes.
- Two independent desktop runs start with empty preview/animation caches. Both
  load real geometry, materials and textures, play/pause/rest a real idle, render
  both themes, exercise bloom and close. Neither has page or asset errors. One
  persistent reader serves each run and exits with its test application.

## Repairs and safety

The original validator CLSID in `dxc_ir.py` was incorrect. The replacement matches
[Microsoft's API header](https://github.com/microsoft/DirectXShaderCompiler/blob/cdbd4e6c5cfb327b4481b8386464770401805f59/include/dxc/dxcapi.h).
The code now also checks the validation HRESULT and operation status before
reporting success. A validation failure stops the shader build, even if the input
already has a nonzero checksum. The existing explicit unsigned fallback remains
for installations without a usable validator; the pinned DLLs successfully sign.

A strict desktop run reproduced `Import cache path is outside the cache` for two
textures during parallel cold imports. Windows `realpath` can retain `\\?\` on
only one operand while directories are being created. The import client now uses
Atelier's existing drive/UNC comparison normalization for containment and native
reply paths, retaining the original resolved spelling for file I/O. Regression
checks still reject other drives, shares, sibling directories and device paths.
Both subsequent cold desktop runs pass with no asset failures. This addresses the
captured error; it does not retroactively identify the cause of an earlier
unrecorded Capwolf texture warning.

All **48 backend suites** pass after the final repairs. Tests cover changed source,
SDK and bundle inputs, tampered NuGet archives, private restores, failed builds,
existing-install preservation, archive filtering, path escapes, reader lifecycle
and DXIL validation errors. Existing isolated-runner skips remain one unavailable
`bpy` case and two legacy UAssetTool cases. Python parsing, dependency consistency,
source credential and whitespace checks pass.

One parallel full shader-index retry aborted on a native memory allocation while
other native work was active; the first full index succeeded. Heavy checks were
subsequently separated, and the signed follow-up reused that verified index.
The old source-less indexer's peak memory behavior is not repaired by these pins.
The initial desktop run under that pressure also failed to start its idle; clean
sequential desktop runs pass.

Tests write only to fresh external report/application directories under
`D:/AtelierDev/native-build-inputs-20261021`. They install no game mod and do not
write game containers or the user's live projects. Extracted shader/animation
data, compiler downloads, keys and mappings are not committed. These checks do
not establish in-game rendering or provide the missing shader fork's source/build
inputs. No new full installer or Linux build was exercised in this follow-up.

The [verification JSON](native-tool-inputs-verification-2026-10-21.json) records
source hashes, build manifests, native outcomes and external evidence locations.
