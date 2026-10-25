# Native toolchain

Atelier drives a handful of native tools. None of them are committed: every one is described in
[`tools.lock.json`](tools.lock.json) and produced by [`scripts/toolchain.py`](../scripts/toolchain.py),
for development (`toolchain.py install --dest Tools`), for releases (`scripts/build.py` runs the same
step) and in CI.

| Tool | How it is sourced | Updated in the field? |
|---|---|---|
| **AtelierNative** (mesh export, idle animations, persistent imports, mod readback check) | built from [`native/AtelierNative`](../native/AtelierNative) against CUE4Parse at a pinned commit; CUE4Parse-Natives built from the same commit | with app releases |
| **UAssetTool** | built from [UAssetToolRivals](https://github.com/X-zant/UAssetToolRivals) at a pinned commit + [`patches/UAssetToolRivals`](patches/UAssetToolRivals) | with app releases |
| **retoc** (container unpack/pack) | upstream [repak-rivals](https://github.com/natimerry/repak-rivals) release, hash-pinned | **yes**: Settings > Tools |
| **retoc-shaders** (shader dump/extract/patch, Windows) | built from [`native/AtelierShader`](../native/AtelierShader) on pinned upstream retoc-rivals with a pinned Rust (see below) | with app releases |
| **dxc**, **texconv**, **UAssetGUI** | official releases, hash-pinned (Windows) | with app releases |
| **Oodle** | as redistributed by repak-rivals, hash-pinned | with app releases |
| **libooz** (Linux Oodle fallback) | built from [ooz](https://github.com/powzix/ooz) at a pinned commit | with app releases |
| **character IDs** seed | pinned commit of MarvelRivalsCharacterIDs; the app refreshes it at runtime | runtime |

## Commands

```bash
python scripts/toolchain.py install  [--platform windows|linux] [--dest Tools]   # fetch + build + verify
python scripts/toolchain.py fetch|build|verify ...                               # individual steps
python scripts/toolchain.py outdated                                             # newer upstream releases
python scripts/toolchain.py bump retoc 3.11.0                                    # re-pin, hashes recomputed
python scripts/toolchain.py channel                                              # regenerate channel.json
```

Building needs the .NET 10 SDK, plus CMake (+MSVC on Windows) **or** WSL with
`build-essential cmake mingw-w64` for the two small C/C++ libraries. The shader tool needs nothing
installed: its Rust and llvm-mingw compilers are downloaded as hash-pinned archives. Downloads and source checkouts
are cached under `build/toolchain/`.

`verify` checks every expected file, compares release-sourced files with their pinned hashes, and
runs each tool's probe (its help must still list the commands Atelier calls).

## Patches to UAssetToolRivals

`0001` — generate mips with the engine's linear-light 2×2 box filter (the previous sRGB-space
bicubic resize darkened every mip: the "exported textures look brighter/glarey" reports), and encode
BC7 with texconv when available (24× faster end to end; the "export never finishes" reports).

Patches are plain `git format-patch` files applied in order to the pinned commit. To change one,
check the commit out, edit, commit, and re-export with `git format-patch -1 --zero-commit`.

## In-app tool updates

`channel.json` is generated from the lock (`toolchain.py channel`) and lists only `updatable`
tools. Atelier reads it from this repository's `main` branch (Settings > Tools). An update downloads
the release, checks every hash, runs the probe on the staged files, keeps the replaced files for
rollback, and records the result in `Tools/tools.json`. "Latest upstream" is never trusted on its
own: the daily [tool-updates workflow](../.github/workflows/tool-updates.yml) proposes a pull
request, and only a merged channel reaches users. Run the native suites (`tests/native_*.py`)
against a real game install before merging one.

## The shader tool

`retoc-shaders` is retoc-rivals-cli with Atelier's shader commands (`dump-shaders`,
`extract-shader`, `patch-shader`, plus `pack`/`unpack`/`info`). The original 3.4.1 fork's source was
never published, so the commands were reconstructed in [`native/AtelierShader`](../native/AtelierShader)
on top of pinned upstream [retoc-rivals](https://github.com/natimerry/retoc-rivals) and repak-rivals.

[`native/AtelierShader/build.lock.json`](../native/AtelierShader/build.lock.json) pins everything the
build reads: upstream archives, the Rust 1.96.0 and llvm-mingw archives, the Cargo git revisions,
Oodle, the source files and the build script itself (`scripts/build_shader_tool.py`). The build is
reproducible, so the lock entry also pins the resulting executable's hash; `verify` reports any
difference. The builder records its inputs in `Tools/shaders/build-inputs.json` and skips the
rebuild while that record still matches the lock.

After editing a file listed in `build.lock.json` (including `scripts/build_shader_tool.py`), update
its hash there, rebuild, and update the `reproducible` hash in `tools.lock.json` if the executable
changed. Windows only; keep the workspace short (`ATELIER_SHADER_WORK`) if paths exceed 260 characters.
