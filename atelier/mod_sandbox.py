"""Installed mods listing, atomic enable/disable toggling, and reversible Clean-Test mode."""
import json
import os
from pathlib import Path
import re

from atelier.storage import atomic_json

_ACTIVE_EXTS = (".pak", ".utoc", ".ucas")
_DISABLED_MAP = (
    (".pak.disabled", ".pak"),
    (".utoc.disabled", ".utoc"),
    (".ucas.disabled", ".ucas"),
    (".pak_disabled", ".pak"),
    (".utoc_disabled", ".utoc"),
    (".ucas_disabled", ".ucas"),
    (".bak_repak", ".pak"),
)
_PARTITION_RE = re.compile(r"^(.+)_s[1-9]\d*$", re.I)


def _split_mod_filename(name: str):
    """Return ``(stem, base_ext, enabled)`` or ``None`` if not a mod container file."""
    lower = name.casefold()
    for suffix, base_ext in _DISABLED_MAP:
        if lower.endswith(suffix):
            return name[: -len(suffix)], base_ext, False
    for ext in _ACTIVE_EXTS:
        if lower.endswith(ext):
            return name[: -len(ext)], ext, True
    return None


def _bundle_key_and_stem(rel_parent: str, stem: str, known_stems: set[tuple[str, str]]):
    """Fold secondary ``_s1`` / ``_s2`` IoStore partition files into their main bundle."""
    m = _PARTITION_RE.fullmatch(stem)
    if m and (rel_parent.casefold(), m.group(1).casefold()) in known_stems:
        stem = m.group(1)
    rel_id = f"{rel_parent}/{stem}" if rel_parent else stem
    return rel_id.casefold(), rel_id, stem


def _norm_mod_stem(name: str) -> str:
    stem = (name or "").strip().casefold()
    if stem.endswith("_p"):
        stem = stem[:-2]
    return stem


def _load_clean_test_state(state_path: str | Path | None) -> dict | None:
    if not state_path:
        return None
    p = Path(state_path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("active") and isinstance(data.get("paused_ids"), list):
            return data
    except Exception:
        pass
    return None


def _save_clean_test_state(state_path: str | Path | None, state: dict | None):
    if not state_path:
        return
    p = Path(state_path)
    if state is None:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
        return
    atomic_json(p, state)


def scan_installed_mods(mods_dir: str | Path, *, current_mod_name: str = "", state_path: str | Path | None = None) -> dict:
    """List installed mod bundles in ``mods_dir`` without unpacking containers."""
    root = Path(mods_dir)
    if not mods_dir or not root.is_dir():
        return {
            "ok": True,
            "mods": [],
            "enabled_count": 0,
            "total_count": 0,
            "clean_test": _load_clean_test_state(state_path),
            "mods_folder": str(mods_dir or ""),
            "exists": False,
        }

    raw_files = []
    known_stems: set[tuple[str, str]] = set()
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted((d for d in dirs if not d.startswith(".atelier-publish-")), key=str.casefold)
        rel_dir = Path(folder).relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        for fname in sorted(names, key=str.casefold):
            parsed = _split_mod_filename(fname)
            if not parsed:
                continue
            stem, base_ext, enabled = parsed
            full_path = Path(folder) / fname
            raw_files.append((rel_dir, stem, base_ext, enabled, full_path))
            if base_ext in (".pak", ".utoc"):
                known_stems.add((rel_dir.casefold(), stem.casefold()))

    bundles: dict[str, dict] = {}
    for rel_dir, stem, base_ext, enabled, full_path in raw_files:
        key, rel_id, bundle_stem = _bundle_key_and_stem(rel_dir, stem, known_stems)
        b = bundles.get(key)
        if b is None:
            b = {
                "id": rel_id,
                "name": bundle_stem,
                "folder": rel_dir,
                "enabled": False,
                "partial": False,
                "size_bytes": 0,
                "modified": 0.0,
                "files": [],
                "exts": set(),
                "_enabled_flags": set(),
                "_paths": [],
            }
            bundles[key] = b
        try:
            st = full_path.stat()
            b["size_bytes"] += st.st_size
            b["modified"] = max(b["modified"], st.st_mtime)
        except OSError:
            pass
        b["files"].append(full_path.name)
        b["exts"].add(base_ext)
        b["_enabled_flags"].add(enabled)
        b["_paths"].append((full_path, base_ext, enabled))

    target_norm = _norm_mod_stem(current_mod_name)
    mods = []
    for b in bundles.values():
        flags = b.pop("_enabled_flags")
        b.pop("_paths")
        exts = b.pop("exts")
        b["enabled"] = True in flags
        b["partial"] = len(flags) > 1
        b["kind"] = "IoStore" if (".utoc" in exts or ".ucas" in exts) else "PAK"
        b["is_current"] = bool(target_norm and _norm_mod_stem(b["name"]) == target_norm)
        mods.append(b)

    mods.sort(key=lambda item: (not item["is_current"], not item["enabled"], item["name"].casefold(), item["folder"].casefold()))
    enabled_count = sum(1 for m in mods if m["enabled"])
    return {
        "ok": True,
        "mods": mods,
        "enabled_count": enabled_count,
        "total_count": len(mods),
        "clean_test": _load_clean_test_state(state_path),
        "mods_folder": str(root).replace("\\", "/"),
        "exists": True,
    }


def _collect_bundle_files(mods_dir: Path, mod_id: str) -> list[tuple[Path, str, bool]]:
    """Resolve all container files belonging to ``mod_id`` safely inside ``mods_dir``."""
    clean_id = (mod_id or "").replace("\\", "/").strip("/")
    if not clean_id or ".." in clean_id.split("/"):
        raise ValueError("Invalid mod identifier.")
    root = mods_dir.resolve()
    parts = clean_id.split("/")
    rel_dir = "/".join(parts[:-1])
    target_stem = parts[-1]
    folder = (root / rel_dir).resolve() if rel_dir else root
    if folder != root and root not in folder.parents:
        raise ValueError("Mod path escapes the mods folder.")
    if not folder.is_dir():
        return []

    found = []
    target_cf = target_stem.casefold()
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not entry.is_file():
            continue
        parsed = _split_mod_filename(entry.name)
        if not parsed:
            continue
        stem, base_ext, enabled = parsed
        m = _PARTITION_RE.fullmatch(stem)
        stem_cf = stem.casefold()
        if stem_cf == target_cf or (m and m.group(1).casefold() == target_cf):
            found.append((entry, base_ext, enabled))
    return found


def _rename_bundle(files: list[tuple[Path, str, bool]], enable: bool):
    """Atomically enable or disable every file in a bundle, rolling back on error."""
    plan: list[tuple[Path, Path]] = []
    for path, base_ext, currently_enabled in files:
        if enable == currently_enabled:
            continue
        if enable:
            parsed = _split_mod_filename(path.name)
            if not parsed:
                continue
            stem, ext, _ = parsed
            dest = path.with_name(f"{stem}{ext}")
        else:
            dest = path.with_name(f"{path.name}.disabled")
        if dest.exists():
            raise FileExistsError(f"Cannot rename {path.name}: {dest.name} already exists.")
        plan.append((path, dest))

    done: list[tuple[Path, Path]] = []
    try:
        for src, dst in plan:
            os.rename(src, dst)
            done.append((src, dst))
    except OSError as exc:
        for src, dst in reversed(done):
            try:
                os.rename(dst, src)
            except OSError:
                pass
        raise OSError(f"Could not update {src.name} (file may be in use): {exc}") from exc


def toggle_mod(
    mods_dir: str | Path,
    mod_id: str,
    enabled: bool,
    *,
    game_running_check=None,
) -> dict:
    """Enable or disable a single installed mod bundle."""
    if callable(game_running_check) and game_running_check():
        raise RuntimeError("Close Marvel Rivals before enabling or disabling installed mods.")
    root = Path(mods_dir)
    if not mods_dir or not root.is_dir():
        raise FileNotFoundError("Mods folder is not configured or does not exist.")
    files = _collect_bundle_files(root, mod_id)
    if not files:
        raise FileNotFoundError(f"Mod '{mod_id}' was not found in your mods folder.")
    _rename_bundle(files, bool(enabled))
    return {"ok": True, "id": mod_id, "enabled": bool(enabled), "files_updated": len(files)}


def set_clean_test(
    mods_dir: str | Path,
    *,
    enable: bool,
    keep_mod: str = "",
    state_path: str | Path | None = None,
    game_running_check=None,
) -> dict:
    """Pause every other installed mod for clean testing, or restore the paused set."""
    if callable(game_running_check) and game_running_check():
        raise RuntimeError("Close Marvel Rivals before changing clean-test mode.")
    root = Path(mods_dir)
    if not mods_dir or not root.is_dir():
        raise FileNotFoundError("Mods folder is not configured or does not exist.")

    existing_state = _load_clean_test_state(state_path)

    if not enable:
        if not existing_state:
            return {"ok": True, "active": False, "restored": 0}
        restored = 0
        errors = []
        for mod_id in existing_state.get("paused_ids") or []:
            try:
                files = _collect_bundle_files(root, mod_id)
                if files:
                    _rename_bundle(files, True)
                    restored += 1
            except Exception as exc:
                errors.append(f"{mod_id}: {exc}")
        _save_clean_test_state(state_path, None)
        return {"ok": True, "active": False, "restored": restored, "warnings": errors}

    if existing_state:
        return {"ok": True, "active": True, "paused": len(existing_state.get("paused_ids") or []),
                "keep_mod": existing_state.get("keep_mod", "")}

    listing = scan_installed_mods(root, current_mod_name=keep_mod, state_path=state_path)
    mods = listing["mods"]
    target_norm = _norm_mod_stem(keep_mod)
    keep_entry = next((m for m in mods if m["id"].casefold() == (keep_mod or "").casefold()), None)
    if keep_entry is None and target_norm:
        keep_entry = next((m for m in mods if _norm_mod_stem(m["name"]) == target_norm), None)

    to_pause = [m for m in mods if m["enabled"] and (keep_entry is None or m["id"] != keep_entry["id"])]
    paused_ids: list[str] = []
    re_enabled_keep = False
    try:
        if keep_entry and not keep_entry["enabled"]:
            _rename_bundle(_collect_bundle_files(root, keep_entry["id"]), True)
            re_enabled_keep = True
        for mod in to_pause:
            _rename_bundle(_collect_bundle_files(root, mod["id"]), False)
            paused_ids.append(mod["id"])
    except Exception:
        for mod_id in reversed(paused_ids):
            try:
                _rename_bundle(_collect_bundle_files(root, mod_id), True)
            except Exception:
                pass
        if re_enabled_keep and keep_entry:
            try:
                _rename_bundle(_collect_bundle_files(root, keep_entry["id"]), False)
            except Exception:
                pass
        raise

    state = {
        "active": True,
        "keep_mod": keep_entry["name"] if keep_entry else (keep_mod or ""),
        "keep_id": keep_entry["id"] if keep_entry else "",
        "paused_ids": paused_ids,
    }
    _save_clean_test_state(state_path, state)
    return {
        "ok": True,
        "active": True,
        "paused": len(paused_ids),
        "keep_mod": state["keep_mod"],
        "keep_found": keep_entry is not None,
    }
