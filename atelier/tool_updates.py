"""Verified in-app updates and repair for the native tools that follow game patches.

The channel (toolchain/channel.json on Atelier's main branch, generated from tools.lock.json) lists
each updatable tool with exact download URLs and SHA-256 hashes. An update:

  1. downloads the release archive and checks its hash, then every extracted file's hash;
  2. stages the files beside the live ones and runs the tool's probe (its help must still list
     the commands Atelier calls) -- a tool that cannot do Atelier's job is never switched in;
  3. moves the current files into Tools/.rollback/<tool>/ and the new ones into place, then
     records the new version in Tools/tools.json. Any failure restores the previous files.

Only a reviewed channel entry is ever installed: "latest upstream release" is not trusted on its
own. Repair re-installs the channel version of any updatable tool whose files are missing or have
been altered (the "UAssetTool.exe not found" / [WinError 2] reports).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from atelier import config, hostos, toolfiles

CHANNEL_URL = os.environ.get(
    "ATELIER_TOOL_CHANNEL",
    "https://raw.githubusercontent.com/clownfetus/Atelier/main/toolchain/channel.json")
PLATFORM = "windows" if hostos.IS_WINDOWS else "linux"
RECORD = "tools.json"
_lock = threading.Lock()
_channel_cache = {"at": 0.0, "data": None, "error": None}


def _tools():
    return Path(config.TOOLS)


def installed():
    """Tools/tools.json as written by the build or the last update; {} for older installs."""
    try:
        return json.loads((_tools() / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_record(record):
    tmp = _tools() / (RECORD + ".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _tools() / RECORD)


def fetch_channel(force=False, timeout=10):
    """The update channel, cached for 15 minutes. Never raises: errors are returned in status()."""
    now = time.time()
    if not force and _channel_cache["data"] is not None and now - _channel_cache["at"] < 900:
        return _channel_cache["data"]
    try:
        request = urllib.request.Request(CHANNEL_URL, headers=toolfiles.UA)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("tools"), list):
            raise ValueError("unrecognised channel format")
        _channel_cache.update(at=now, data=data, error=None)
    except Exception as error:
        _channel_cache.update(at=now, error=str(error))
    return _channel_cache["data"]


def _channel_tool(name, channel=None):
    channel = channel or fetch_channel() or {}
    return next((t for t in channel.get("tools", []) if t["name"] == name), None)


def _files_state(files):
    """'ok' | 'missing' | 'modified' for a {relative path: sha256} map."""
    for rel, sha in files.items():
        path = _tools() / rel
        if not path.is_file():
            return "missing"
        if sha and toolfiles.sha256_file(path) != sha:
            return "modified"
    return "ok"


def status(check=False):
    """Every recorded tool with its installed version, state, and any channel update."""
    record = installed()
    channel = fetch_channel(force=check) if check else _channel_cache["data"]
    rows = []
    for name, info in sorted((record.get("tools") or {}).items()):
        row = {"name": name, "version": info.get("version", ""), "updatable": bool(info.get("updatable")),
               "state": _files_state(info.get("files") or {}), "available": None}
        entry = _channel_tool(name, channel) if channel else None
        if entry and PLATFORM in entry.get("assets", {}) and entry.get("version") != row["version"]:
            row["available"] = entry["version"]
        rows.append(row)
    return {"ok": True, "platform": PLATFORM, "tools": rows, "recorded": bool(record),
            "channel_error": _channel_cache["error"], "checked_at": _channel_cache["at"] or None}


def _probe(entry, staged):
    spec = entry.get("probe")
    if not spec:
        return
    exe = next((staged / rel for rel, _s, _x in toolfiles.asset_files(entry["assets"][PLATFORM])
                if rel.endswith(".exe") or (PLATFORM == "linux" and "." not in Path(rel).name)), None)
    if exe is None:
        return
    result = subprocess.run([str(exe), *spec["args"]], capture_output=True, text=True, timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = (result.stdout or "") + (result.stderr or "")
    missing = [token for token in spec.get("expect", []) if token not in output]
    if missing:
        raise toolfiles.ToolFileError(f"the new {entry['name']} does not offer {', '.join(missing)}; not installed")


def install(name, entry=None, reason="update"):
    """Install the channel version of `name`. Returns the new status row. Rolls back on failure."""
    with _lock:
        entry = entry or _channel_tool(name, fetch_channel(force=True))
        if not entry or PLATFORM not in entry.get("assets", {}):
            raise toolfiles.ToolFileError(f"No {PLATFORM} build of {name} is offered by the update channel")
        asset = entry["assets"][PLATFORM]
        tools = _tools()
        archive = toolfiles.download(asset["url"], asset["sha256"], Path(config._CACHE) / "tool-downloads")
        files = toolfiles.materialize(asset, archive)
        executable = {rel: x for rel, _sha, x in toolfiles.asset_files(asset)}
        staged = tools / ".staging" / name
        shutil.rmtree(staged, ignore_errors=True)
        try:
            for rel, data in files.items():
                toolfiles.place(data, staged, rel, executable.get(rel, False))
            _probe(entry, staged)
        except Exception:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        record = installed() or {"schema": 1, "platform": PLATFORM, "tools": {}}
        previous = record.get("tools", {}).get(name, {})
        # An update keeps what it replaced for rollback. A repair restores the current version, so
        # it must not overwrite that slot: its displaced files go to a scratch folder instead.
        repairing = reason == "repair"
        backup = tools / ".staging" / (name + "-displaced") if repairing else tools / ".rollback" / name
        shutil.rmtree(backup, ignore_errors=True)
        if name == "UAssetTool":
            from atelier import tools as _tools_module
            _tools_module.stop_workers()
        moved = []
        try:
            for rel in files:
                live = tools.joinpath(*toolfiles.safe_relative(rel).parts)
                if live.exists():
                    keep = backup.joinpath(*toolfiles.safe_relative(rel).parts)
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live, keep)
                    moved.append((keep, live))
                live.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged.joinpath(*toolfiles.safe_relative(rel).parts), live)
        except Exception:
            for keep, live in reversed(moved):
                try:
                    os.replace(keep, live)
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        if repairing:
            shutil.rmtree(backup, ignore_errors=True)
            earlier = previous.get("previous")
        else:
            (backup / "version.txt").parent.mkdir(parents=True, exist_ok=True)
            (backup / "version.txt").write_text(previous.get("version", "unknown"), encoding="utf-8")
            earlier = previous.get("version")
        record.setdefault("tools", {})[name] = {
            "version": entry["version"], "updatable": True,
            "files": {rel: toolfiles.sha256_bytes(data) for rel, data in files.items()},
            "installed_by": reason, "previous": earlier}
        _write_record(record)
        print(f"  [tools] {name} {previous.get('version', '?')} -> {entry['version']} ({reason})",
              file=sys.stderr, flush=True)
        return next(r for r in status()["tools"] if r["name"] == name)


def rollback(name):
    """Put back the files the last update replaced."""
    with _lock:
        backup = _tools() / ".rollback" / name
        version = (backup / "version.txt").read_text(encoding="utf-8").strip() if (backup / "version.txt").is_file() else None
        if not version:
            raise toolfiles.ToolFileError(f"There is no earlier {name} to go back to")
        record = installed()
        files = {}
        for path in backup.rglob("*"):
            if path.is_file() and path.name != "version.txt":
                rel = path.relative_to(backup).as_posix()
                os.replace(path, _tools() / rel)
                files[rel] = toolfiles.sha256_file(_tools() / rel)
        shutil.rmtree(backup, ignore_errors=True)
        record.setdefault("tools", {})[name] = {"version": version, "updatable": True, "files": files,
                                                "installed_by": "rollback"}
        _write_record(record)
        return next(r for r in status()["tools"] if r["name"] == name)


def repair():
    """Re-install every updatable tool whose files are missing or altered. Returns what it did."""
    done, problems = [], []
    for row in status(check=True)["tools"]:
        if row["state"] == "ok":
            continue
        if not row["updatable"]:
            problems.append(f"{row['name']} is {row['state']}; reinstall Atelier to restore it")
            continue
        try:
            install(row["name"], reason="repair")
            done.append(row["name"])
        except Exception as error:
            problems.append(f"{row['name']}: {error}")
    return {"ok": not problems, "repaired": done, "problems": problems}


def update_all():
    """Install every update the channel offers. Returns {updated, problems}."""
    done, problems = [], []
    for row in status(check=True)["tools"]:
        if row["available"]:
            try:
                install(row["name"])
                done.append(f"{row['name']} {row['available']}")
            except Exception as error:
                problems.append(f"{row['name']}: {error}")
    return {"ok": not problems, "updated": done, "problems": problems}
