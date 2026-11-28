"""Game Patch Radar — detect when a Marvel Rivals update changes vanilla assets edited in a project.

Never copies game containers to disk. Records only lightweight per-target container metadata
(winning container name, mount prefix, container byte size and mtime_ns) in
``<project>/.atelier/patch_baseline.json`` whenever a project exports or sets a baseline.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from atelier import config
from atelier.asset_refs import infer_file_type
from atelier.storage import atomic_json

_BASELINE_FILE = os.path.join(".atelier", "patch_baseline.json")
_RISK_BY_TYPE = {
    "mesh": ("high", "Check skeleton, weights and silhouette in Model Studio, then re-export."),
    "material": ("high", "Open in Material Editor or run Repatcher / material check before exporting."),
    "world": ("high", "Re-verify level parameters and re-export against the updated map."),
    "vfx": ("medium", "Check gradient timelines in VFX Motionboard, then re-export."),
    "curve": ("medium", "Inspect curve keyframes and re-export."),
    "text": ("medium", "Verify StringTable entries still align and re-export."),
    "texture": ("low", "Preview side-by-side (Wipe) against the new original texture, then re-export."),
}


def _baseline_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / _BASELINE_FILE


def _container_stat(paks_dir: str | Path, container: str) -> tuple[int, int]:
    if not paks_dir or not container:
        return 0, 0
    target = Path(paks_dir) / container
    try:
        st = target.stat()
        return int(st.st_size), int(st.st_mtime_ns)
    except OSError:
        return 0, 0


def _resolve_entry(game_rel: str, lookup: dict):
    low = (game_rel or "").replace("\\", "/").strip("/").lower()
    if not low:
        return None
    for suffix in (".uasset", ".umap", ""):
        hit = lookup.get(low + suffix) if suffix else lookup.get(low)
        if hit:
            return hit
    return None


def snapshot_targets(items: list[str], *, paks_dir: str | Path | None = None, lookup: dict | None = None) -> dict:
    """Capture lightweight vanilla container fingerprints for ``items``."""
    if lookup is None:
        from atelier.index import index_lookup
        lookup = index_lookup()
    if paks_dir is None:
        paks_dir = config.PAKS

    stat_cache: dict[str, tuple[int, int]] = {}
    targets: dict[str, dict] = {}
    for raw in items or []:
        rel = (raw or "").replace("\\", "/").strip("/")
        if not rel:
            continue
        hit = _resolve_entry(rel, lookup)
        if not hit:
            continue
        _vp, container, mount = hit
        if container not in stat_cache:
            stat_cache[container] = _container_stat(paks_dir, container)
        size, mtime_ns = stat_cache[container]
        targets[rel] = {
            "container": container,
            "mount": mount,
            "size": size,
            "mtime_ns": mtime_ns,
            "file_type": infer_file_type(rel),
        }
    return targets


def load_baseline(project_dir: str | Path) -> dict | None:
    path = _baseline_path(project_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("targets"), dict):
            return data
    except Exception:
        pass
    return None


def record_baseline(
    project_dir: str | Path,
    items: list[str],
    *,
    paks_dir: str | Path | None = None,
    lookup: dict | None = None,
) -> dict:
    """Store the current vanilla pak fingerprint for this project's edited targets."""
    targets = snapshot_targets(items, paks_dir=paks_dir, lookup=lookup)
    payload = {
        "version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "targets": targets,
    }
    atomic_json(_baseline_path(project_dir), payload)
    return payload


def scan_project(
    project_dir: str | Path,
    items: list[str],
    *,
    paks_dir: str | Path | None = None,
    lookup: dict | None = None,
) -> dict:
    """Compare current edited targets against the saved baseline to flag post-patch changes."""
    baseline = load_baseline(project_dir)
    clean_items = [str(g).replace("\\", "/").strip("/") for g in (items or []) if g]
    if baseline is None:
        return {
            "ok": True,
            "has_baseline": False,
            "recorded_at": "",
            "needs_attention": False,
            "changed": [],
            "removed": [],
            "unchanged_count": len(clean_items),
            "tracked_count": 0,
            "summary": "No baseline recorded yet. Export once or click Record baseline to start tracking game updates.",
        }

    current = snapshot_targets(clean_items, paks_dir=paks_dir, lookup=lookup)
    base_targets = baseline.get("targets") or {}
    changed = []
    removed = []
    unchanged = 0
    untracked = 0

    for rel in clean_items:
        old = base_targets.get(rel)
        if old is None:
            untracked += 1
            continue
        now = current.get(rel)
        ft = old.get("file_type") or infer_file_type(rel)
        risk, advice = _RISK_BY_TYPE.get(ft, ("medium", "Inspect this asset and re-export."))
        name = rel.rsplit("/", 1)[-1]
        if now is None:
            removed.append({
                "game_rel": rel,
                "name": name,
                "file_type": ft,
                "risk": "high",
                "reason": "Vanilla asset is missing or renamed in the current game files.",
                "advice": "Check whether the game moved this asset before exporting.",
                "old_container": old.get("container", ""),
                "new_container": "",
            })
            continue
        container_changed = old.get("container") != now.get("container")
        bytes_changed = (
            (old.get("size", 0) and now.get("size", 0) and old["size"] != now["size"])
            or (old.get("mtime_ns", 0) and now.get("mtime_ns", 0) and old["mtime_ns"] != now["mtime_ns"])
        )
        if container_changed or bytes_changed:
            reason = (
                f"Overridden by a newer patch container ({now['container']})"
                if container_changed
                else f"Game container updated on disk ({now['container']})"
            )
            changed.append({
                "game_rel": rel,
                "name": name,
                "file_type": ft,
                "risk": risk,
                "reason": reason,
                "advice": advice,
                "old_container": old.get("container", ""),
                "new_container": now.get("container", ""),
            })
        else:
            unchanged += 1

    risk_rank = {"high": 0, "medium": 1, "low": 2}
    changed.sort(key=lambda item: (risk_rank.get(item["risk"], 9), item["name"].casefold()))
    removed.sort(key=lambda item: item["name"].casefold())
    affected = len(changed) + len(removed)
    if affected:
        summary = f"Game update affected {affected} edited asset{'s' if affected != 1 else ''} in this project."
    else:
        summary = "All tracked vanilla targets match your last baseline."
    return {
        "ok": True,
        "has_baseline": True,
        "recorded_at": baseline.get("recorded_at", ""),
        "needs_attention": affected > 0,
        "changed": changed,
        "removed": removed,
        "unchanged_count": unchanged,
        "untracked_count": untracked,
        "tracked_count": unchanged + affected,
        "summary": summary,
    }
