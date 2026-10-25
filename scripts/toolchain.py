"""Atelier's native toolchain: fetch, build and verify everything in toolchain/tools.lock.json.

    python scripts/toolchain.py fetch    [--platform windows|linux] [--dest Tools]
    python scripts/toolchain.py build    [--platform ...] [--dest Tools] [--only NAME ...]
    python scripts/toolchain.py install  [--platform ...] [--dest Tools]      # fetch + build
    python scripts/toolchain.py verify   [--platform ...] [--dest Tools] [--no-probe]
    python scripts/toolchain.py outdated                                       # newer upstream releases
    python scripts/toolchain.py bump NAME VERSION                              # re-pin an updatable tool
    python scripts/toolchain.py channel  [--out toolchain/channel.json]        # in-app updater feed

Nothing it produces is committed. Release-sourced files are hash-checked on download and after
extraction; built tools come from pinned commits plus the patches in toolchain/patches.

Building on Windows needs the .NET 10 SDK. The two small C/C++ libraries (CUE4Parse-Natives,
libooz) build with CMake+MSVC when available, otherwise inside WSL (MinGW for Windows targets).
The shader-capable retoc (Windows only) builds with the pinned Rust and llvm-mingw archives
named in native/AtelierShader/build.lock.json, downloaded and hash-checked by scripts/build_shader_tool.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "toolchain" / "tools.lock.json"
CACHE = Path(os.environ.get("ATELIER_TOOLCHAIN_CACHE", ROOT / "build" / "toolchain"))
HOST = "windows" if os.name == "nt" else "linux"
RID = {"windows": "win-x64", "linux": "linux-x64"}
UA = {"User-Agent": "Atelier-toolchain"}


class ToolchainError(RuntimeError):
    pass



# ---------------------------------------------------------------------------------------- lock
def load_lock(path: Path = LOCK) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_lock(lock: dict, path: Path = LOCK) -> None:
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")


def tool(lock: dict, name: str) -> dict:
    for entry in lock["tools"]:
        if entry["name"] == name:
            return entry
    raise ToolchainError(f"No tool named {name!r} in {LOCK.name}")


def applies(entry: dict, platform: str) -> bool:
    if "platforms" in entry:
        return platform in entry["platforms"]
    assets = entry.get("assets") or {}
    return platform in assets or "any" in assets or entry.get("kind") == "build"


def asset_for(entry: dict, platform: str) -> dict | None:
    assets = entry.get("assets") or {}
    return assets.get(platform) or assets.get("any")


def expected_files(entry: dict, platform: str) -> list[str]:
    """Paths (relative to Tools/) this tool must provide on `platform`."""
    if entry["kind"] == "build":
        return list((entry.get("files") or {}).get(platform, []))
    asset = asset_for(entry, platform)
    if not asset:
        return []
    if "extract" in asset:
        return [m["to"] for m in asset["extract"].values()]
    targets = asset["to"]
    return list(targets) if isinstance(targets, list) else [targets]


# ----------------------------------------------------------------------------------- downloads
sys.path.insert(0, str(ROOT))
from atelier.toolfiles import (ToolFileError, asset_files, materialize, place,  # noqa: E402
                               read_member, sha256_bytes, sha256_file)
from atelier import toolfiles as _files  # noqa: E402


def download(url: str, sha256: str | None) -> Path:
    return _files.download(url, sha256, CACHE / "downloads")


def fetch_tool(entry: dict, platform: str, dest: Path) -> list[str]:
    asset = asset_for(entry, platform)
    if not asset:
        return []
    files = materialize(asset, download(asset["url"], asset["sha256"]))
    executable = {rel: x for rel, _sha, x in asset_files(asset)}
    for rel, data in files.items():
        place(data, dest, rel, executable.get(rel, False))
    return list(files)


RECORD = "tools.json"


def write_record(lock: dict, platform: str, dest: Path) -> None:
    """Tools/tools.json: which version of each tool is installed, for the in-app updater."""
    record = {"schema": 1, "platform": platform, "tools": {}}
    for entry in lock["tools"]:
        if applies(entry, platform):
            files = {rel: sha256_file(dest / rel) for rel in expected_files(entry, platform) if (dest / rel).is_file()}
            record["tools"][entry["name"]] = {"version": entry.get("version") or tool_build_version(lock, entry),
                                              "updatable": bool(entry.get("updatable")), "files": files}
    (dest / RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def write_notices(lock: dict, platform: str, dest: Path) -> None:
    """Tools/THIRD_PARTY_TOOLS.md: version, licence and exact source of every shipped tool. The
    GPL tools (UAssetTool, libooz) are built from the pinned commits and patches named here."""
    lines = ["# Third-party tools shipped with Atelier", "",
             "Built or downloaded by scripts/toolchain.py from toolchain/tools.lock.json in the matching",
             "Atelier source release. Pinned upstream sources:", ""]
    for name, source in lock["sources"].items():
        patches = f" + patches in {source['patches']}" if source.get("patches") else ""
        lines.append(f"- {name}: {source['repo']} @ {source['commit']}{patches} ({source.get('license', '')})")
    lines += ["", "| Tool | Version | Licence | Source |", "|---|---|---|---|"]
    for entry in lock["tools"]:
        if applies(entry, platform):
            version = entry.get("version") or tool_build_version(lock, entry)
            lines.append(f"| {entry['name']} | {version} | {entry.get('license', '')} | {entry.get('source', '')} |")
    (dest / "THIRD_PARTY_TOOLS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tool_build_version(lock: dict, entry: dict) -> str:
    source = {"atelier-native": "cue4parse", "uassettool": "uassettool", "ooz": "ooz",
              "atelier-shader": "retoc-rivals"}.get(entry.get("builder"))
    return f"{source}@{lock['sources'][source]['commit'][:7]}" if source else ""


# -------------------------------------------------------------------------------------- builds
def run(cmd: list[str], **kw) -> None:
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def checkout(source: dict, name: str) -> Path:
    """A clean checkout of `source` at its pinned commit (cached by commit), patches applied."""
    patches = sorted((ROOT / source["patches"]).glob("*.patch")) if source.get("patches") else []
    stamp = hashlib.sha256(b"".join(p.read_bytes() for p in patches)).hexdigest()[:12] if patches else "clean"
    path = CACHE / "src" / f"{name}-{source['commit'][:12]}-{stamp}"
    if (path / ".atelier-ready").exists():
        return path
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    run(["git", "init", "-q"], cwd=path)
    run(["git", "-c", "core.autocrlf=false", "fetch", "-q", "--depth", "1", source["repo"], source["commit"]], cwd=path)
    run(["git", "-c", "core.autocrlf=false", "checkout", "-q", "FETCH_HEAD"], cwd=path)
    for sub in source.get("submodules", []):
        run(["git", "submodule", "update", "-q", "--init", "--recursive", "--depth", "1", sub], cwd=path)
    for patch in patches:
        run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(patch)], cwd=path)
    (path / ".atelier-ready").write_text(source["commit"])
    return path


def to_wsl(path: Path) -> str:
    resolved = str(path.resolve())
    drive, rest = resolved[0].lower(), resolved[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def wsl(script: str) -> None:
    """Run a bash script inside WSL (Windows hosts building C/C++ parts without MSVC)."""
    if not shutil.which("wsl"):
        raise ToolchainError("Building native C/C++ parts on Windows needs CMake+MSVC or WSL")
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, newline="\n", dir=CACHE) as handle:
        handle.write("set -euo pipefail\n" + script)
    try:
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        run(["wsl", "--", "bash", to_wsl(Path(handle.name))], env=env)
    finally:
        os.unlink(handle.name)


def build_cmake_library(src: Path, platform: str, out_dir: Path, name: str) -> Path:
    """Build a small CMake shared library for `platform`; returns the produced file."""
    suffix = ".dll" if platform == "windows" else ".so"
    build = src / f"build-{platform}"
    product = build / (name + suffix)
    # Native build when targeting this host: g++ on Linux; on Windows CMake finds Visual Studio
    # itself (GitHub's runners have both, without cl on PATH). Otherwise build inside WSL.
    if platform == HOST and (HOST == "linux" or shutil.which("cmake")):
        if HOST == "windows":
            run(["cmake", "-S", src, "-B", build, "-A", "x64"])
            run(["cmake", "--build", build, "--config", "Release"])
            product = next(build.rglob(name + suffix))
        else:
            run(["cmake", "-S", src, "-B", build, "-DCMAKE_BUILD_TYPE=Release"])
            run(["cmake", "--build", build])
    else:
        toolchain = ""
        if platform == "windows":
            (CACHE / "mingw.cmake").write_text(
                "set(CMAKE_SYSTEM_NAME Windows)\nset(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)\n"
                "set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)\n"
                'set(CMAKE_SHARED_LINKER_FLAGS "-static -static-libgcc -static-libstdc++")\n', encoding="utf-8")
            toolchain = f"-DCMAKE_TOOLCHAIN_FILE={to_wsl(CACHE / 'mingw.cmake')}"
        script = (f"cmake -S '{to_wsl(src)}' -B '{to_wsl(build)}' -DCMAKE_BUILD_TYPE=Release {toolchain} >/dev/null\n"
                  f"cmake --build '{to_wsl(build)}'\n")
        if HOST == "windows":
            wsl(script)
        else:
            run(["bash", "-c", script.replace(to_wsl(src), str(src)).replace(to_wsl(build), str(build))])
    if not product.exists():
        raise ToolchainError(f"{name}{suffix} was not produced")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / product.name
    shutil.copy2(product, target)
    return target


def dotnet_publish(project: Path, platform: str, out_dir: Path, *props: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    run(["dotnet", "publish", project, "-c", "Release", "-r", RID[platform], "--self-contained", "true",
         "-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true",
         "-p:DebugType=none", "-p:GenerateDocumentationFile=false", *props, "-o", out_dir], env=env)
    for leftover in out_dir.glob("*.pdb"):
        leftover.unlink()


def build_atelier_native(lock: dict, platform: str, dest: Path) -> None:
    src = checkout(lock["sources"]["cue4parse"], "cue4parse")
    out = dest / "AtelierNative"
    dotnet_publish(ROOT / "native" / "AtelierNative" / "AtelierNative.csproj", platform, out,
                   f"-p:Cue4ParseSource={src}")
    build_cmake_library(src / "CUE4Parse-Natives", platform, out, "CUE4Parse-Natives")


def build_uassettool(lock: dict, platform: str, dest: Path) -> None:
    src = checkout(lock["sources"]["uassettool"], "uassettool")
    with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
        dotnet_publish(src / "src" / "UAssetTool" / "UAssetTool.csproj", platform, Path(tmp),
                       f"-p:Version={uassettool_version(src)}")
        name = "UAssetTool.exe" if platform == "windows" else "UAssetTool"
        shutil.copy2(Path(tmp) / name, dest / name)


def uassettool_version(src: Path) -> str:
    import re
    project = (src / "src" / "UAssetTool" / "UAssetTool.csproj").read_text(encoding="utf-8")
    base = re.search(r"<Version>([^<]+)</Version>", project).group(1)
    return f"{base}-atelier.{len(list((ROOT / 'toolchain' / 'patches' / 'UAssetToolRivals').glob('*.patch')))}"


def build_ooz(lock: dict, platform: str, dest: Path) -> None:
    if platform != "linux":
        return
    src = checkout(lock["sources"]["ooz"], "ooz")
    script = ROOT / "packaging" / "linux" / "build_ooz.sh"
    out = dest / "libooz.so"
    if HOST == "linux":
        run(["bash", script], env={**os.environ, "OOZ_SRC": str(src), "OOZ_OUT": str(out)})
    else:
        wsl(f"OOZ_SRC='{to_wsl(src)}' OOZ_OUT='{to_wsl(out)}' bash '{to_wsl(script)}'\n")


def build_atelier_shader(lock: dict, platform: str, dest: Path) -> None:
    """Shader-capable retoc via scripts/build_shader_tool.py (pinned Rust + llvm-mingw, Windows
    host only). Skipped when Tools/shaders already holds this exact build: it takes minutes."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_shader_tool as shader
    folder = dest / "shaders"
    if shader.provenance_matches(folder):
        print("  up to date (build-inputs.json matches native/AtelierShader/build.lock.json)", flush=True)
        return
    if HOST != "windows":
        raise ToolchainError("retoc-shaders builds on a Windows host (pinned x86_64-pc-windows-gnu toolchain)")
    # Rust's archives and Cargo's target tree nest deeply: keep the workspace short (system temp,
    # or ATELIER_SHADER_WORK) so it stays under Windows' 260-character path limit.
    with tempfile.TemporaryDirectory(prefix="as-", dir=os.environ.get("ATELIER_SHADER_WORK") or None) as tmp:
        output = Path(tmp) / "out"
        shader.build(dest, output, CACHE / "downloads" / "shader", CACHE / "shader-build.log")
        for item in output.rglob("*"):
            if item.is_file():
                target = folder / item.relative_to(output)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)


BUILDERS = {"atelier-native": build_atelier_native, "uassettool": build_uassettool, "ooz": build_ooz,
            "atelier-shader": build_atelier_shader}


# ------------------------------------------------------------------------------------ commands
def cmd_fetch(lock: dict, platform: str, dest: Path, only=None) -> None:
    for entry in lock["tools"]:
        if entry["kind"] != "release" or not applies(entry, platform) or (only and entry["name"] not in only):
            continue
        placed = fetch_tool(entry, platform, dest)
        print(f"fetched {entry['name']} {entry.get('version', '')}: {', '.join(placed)}", flush=True)


def cmd_build(lock: dict, platform: str, dest: Path, only=None) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for entry in lock["tools"]:
        if entry["kind"] != "build" or not applies(entry, platform) or (only and entry["name"] not in only):
            continue
        print(f"building {entry['name']} for {platform}", flush=True)
        try:
            BUILDERS[entry["builder"]](lock, platform, dest)
        except Exception as error:
            if entry.get("optional"):
                print(f"  [optional] {entry['name']} not built: {error}", flush=True)
                continue
            raise


def probe(entry: dict, dest: Path, platform: str) -> str | None:
    spec = entry.get("probe")
    if not spec or platform != HOST:
        return None
    is_exe = (lambda f: f.endswith(".exe")) if platform == "windows" else (lambda f: "." not in PurePosixPath(f).name)
    exe = next((dest / f for f in expected_files(entry, platform) if is_exe(f)), None)
    if exe is None:
        return None
    try:
        result = subprocess.run([str(exe), *spec["args"]], capture_output=True, text=True, timeout=60)
    except Exception as error:
        return f"{entry['name']}: could not run ({error})"
    output = (result.stdout or "") + (result.stderr or "")
    missing = [token for token in spec["expect"] if token not in output]
    return f"{entry['name']}: probe output lacks {missing}" if missing else None


def cmd_verify(lock: dict, platform: str, dest: Path, run_probes: bool = True, only=None) -> list[str]:
    problems = []
    for entry in lock["tools"]:
        if not applies(entry, platform) or (only and entry["name"] not in only):
            continue
        files = expected_files(entry, platform)
        missing = [f for f in files if not (dest / f).is_file() or (dest / f).stat().st_size == 0]
        if missing:
            if not entry.get("optional"):
                problems.append(f"{entry['name']}: missing {', '.join(missing)}")
            continue
        asset = asset_for(entry, platform) if entry["kind"] == "release" else None
        if asset:
            pinned = ({spec["to"]: spec["sha256"] for spec in asset["extract"].values()} if "extract" in asset
                      else {t: asset["sha256"] for t in (asset["to"] if isinstance(asset["to"], list) else [asset["to"]])})
            for rel, sha in pinned.items():
                if sha256_file(dest / rel) != sha:
                    problems.append(f"{entry['name']}: {rel} does not match the lock")
        for rel, sha in (entry.get("reproducible") or {}).items():
            if sha256_file(dest / rel) != sha:
                problems.append(f"{entry['name']}: {rel} differs from the reproducible build in the lock")
        if run_probes and (issue := probe(entry, dest, platform)):
            problems.append(issue)
    return problems


def github(path: str) -> dict:
    headers = {**UA, "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request("https://api.github.com" + path, headers=headers), timeout=60) as r:
        return json.loads(r.read())


def cmd_outdated(lock: dict) -> list[tuple[str, str, str]]:
    found = []
    for entry in lock["tools"]:
        upstream = entry.get("upstream")
        if not entry.get("updatable") or not upstream:
            continue
        latest = github(f"/repos/{upstream['github']}/releases/latest")["tag_name"]
        version = latest.removeprefix(upstream.get("tag_prefix", ""))
        if version != entry["version"]:
            found.append((entry["name"], entry["version"], version))
    return found


def cmd_bump(lock: dict, name: str, version: str, path: Path = LOCK) -> None:
    """Re-pin an updatable release tool to `version`, recomputing every hash from upstream."""
    entry = tool(lock, name)
    upstream = entry.get("upstream") or {}
    if not upstream:
        raise ToolchainError(f"{name} has no upstream release feed")
    tag = upstream.get("tag_prefix", "") + version
    release = github(f"/repos/{upstream['github']}/releases/tags/{tag}")
    for platform, asset in entry["assets"].items():
        wanted = upstream["asset_pattern"][platform]
        match = next((a for a in release["assets"] if a["name"] == wanted), None)
        if not match:
            raise ToolchainError(f"{tag} has no {wanted}")
        archive = download(match["browser_download_url"], None)
        asset["url"], asset["sha256"] = match["browser_download_url"], sha256_file(archive)
        for member, spec in asset.get("extract", {}).items():
            spec["sha256"] = sha256_bytes(read_member(archive, asset["url"], member))
    entry["version"] = version
    save_lock(lock, path)
    print(f"{name} pinned to {version}")


def cmd_channel(lock: dict, out: Path) -> None:
    """The subset of the lock the in-app updater may act on: updatable tools only."""
    channel = {"schema": 1, "tools": []}
    for entry in lock["tools"]:
        if entry.get("updatable"):
            channel["tools"].append({k: entry[k] for k in ("name", "version", "assets", "probe") if k in entry})
    out.write_text(json.dumps(channel, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "build", "install", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--platform", choices=sorted(RID), default=HOST)
        p.add_argument("--dest", type=Path, default=ROOT / "Tools")
        p.add_argument("--only", nargs="*")
        if name == "verify":
            p.add_argument("--no-probe", action="store_true")
    sub.add_parser("outdated")
    p = sub.add_parser("bump")
    p.add_argument("name")
    p.add_argument("version")
    p = sub.add_parser("channel")
    p.add_argument("--out", type=Path, default=ROOT / "toolchain" / "channel.json")
    args = parser.parse_args(argv)
    lock = load_lock()
    try:
        if args.command in ("fetch", "build", "install", "verify"):
            dest = args.dest.resolve()
            dest.mkdir(parents=True, exist_ok=True)
            if args.command in ("fetch", "install"):
                cmd_fetch(lock, args.platform, dest, args.only)
            if args.command in ("build", "install"):
                cmd_build(lock, args.platform, dest, args.only)
            if args.command in ("fetch", "build", "install"):
                write_record(lock, args.platform, dest)
            if args.command in ("verify", "install"):
                problems = cmd_verify(lock, args.platform, dest, not getattr(args, "no_probe", False), args.only)
                for problem in problems:
                    print("PROBLEM " + problem)
                print("toolchain verified" if not problems else f"{len(problems)} problem(s)")
                return 1 if problems else 0
        elif args.command == "outdated":
            rows = cmd_outdated(lock)
            for name, have, latest in rows:
                print(f"{name}: {have} -> {latest}")
            if not rows:
                print("all updatable tools are current")
        elif args.command == "bump":
            cmd_bump(lock, args.name, args.version)
        elif args.command == "channel":
            cmd_channel(lock, args.out)
    except (ToolchainError, ToolFileError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
