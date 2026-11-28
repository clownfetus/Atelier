"""Shared-asset reference inspection and 1-click Safe Fork to a private package path.

Marvel Rivals shares textures and materials heavily across chromas and hero CommonMaterial
buckets. This module answers "what else will change if I edit this asset?" quickly using:
  1. Structural game-index inspection (instant, zero extraction).
  2. Cached cooked JSON import tables (exact reverse-reference verification via unreal_refs).
And offers a 1-click Safe Fork using Atelier's independent added_assets pipeline.
"""
import json
import os
from pathlib import Path
import re

from atelier import config
from atelier.unreal_refs import imported_package

_CHAR_RE = re.compile(r"^Characters/(\d{4})/([^/]+)(?:/|$)", re.I)
_SKIN_DIR_RE = re.compile(r"^\d{6,10}$")
_SHARED_SEGMENT_RE = re.compile(r"(?:common|shared|master|base|global)", re.I)
_FORKABLE_TYPES = frozenset(("texture", "material", "mesh"))
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def infer_file_type(game_rel: str) -> str:
    low = (game_rel or "").replace("\\", "/").lower()
    base = low.rsplit("/", 1)[-1]
    if "/meshes/" in low or base.startswith(("sk_", "sm_")):
        return "mesh"
    if "/materials/" in low or base.startswith(("mi_", "m_", "mat_")) or "commonmaterial" in low:
        return "material"
    if "/vfx/" in low or base.startswith(("ns_", "ne_", "fx_")):
        return "vfx"
    if base.startswith(("c_", "curve_")):
        return "curve"
    if "/stringtable/" in low or base.endswith("_st"):
        return "text"
    if "/maps/" in low or low.endswith(".umap"):
        return "world"
    return "texture"


def _skin_label(skin_id: str, hero_id: str = "") -> dict:
    info = {}
    try:
        from atelier.handlers import skinnames
        lookup = getattr(skinnames, "lookup", None)
        if callable(lookup):
            info = lookup(skin_id) or {}
    except Exception:
        info = {}
    hero_name = info.get("char_name") or (f"Hero {hero_id}" if hero_id else "")
    skin_name = info.get("skin") or skin_id
    return {
        "skin_id": skin_id,
        "hero_id": info.get("char") or hero_id,
        "hero_name": hero_name,
        "skin_name": skin_name,
        "label": f"{skin_name} ({skin_id})" if skin_name != skin_id else skin_id,
    }


def _hero_costumes(hero_id: str) -> list[dict]:
    from atelier.index import prefix_entries
    skins: set[str] = set()
    for path, *_ in prefix_entries(f"characters/{hero_id}/"):
        parts = path.split("/")
        if len(parts) >= 3 and _SKIN_DIR_RE.fullmatch(parts[2]):
            skins.add(parts[2])
    return [_skin_label(sid, hero_id) for sid in sorted(skins)]


def _scan_cached_referrers(target_rel: str, cache_dirs: list[Path], limit: int = 40) -> list[dict]:
    """Scan already-extracted cooked JSONs in cache/project folders for exact Imports matching ``target_rel``."""
    target_cf = target_rel.replace("\\", "/").strip("/").casefold()
    referrers: dict[str, dict] = {}
    for root in cache_dirs:
        if not root or not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", ".trash", "gltf", "animations", "shaders")]
            for fname in files:
                if not fname.endswith(".json") or fname.endswith((".asset.json", ".mesh.json", ".blend.mat.json")):
                    continue
                if fname in ("project.json", "clean_test_state.json", "manifest.json", "tools.json"):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size > 16 * 1024 * 1024:
                        continue
                    raw = fpath.read_text(encoding="utf-8-sig", errors="ignore")
                except OSError:
                    continue
                if target_cf.rsplit("/", 1)[-1] not in raw.casefold():
                    continue
                try:
                    doc = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(doc, dict) or not isinstance(doc.get("Imports"), list):
                    continue
                matched = False
                for idx in range(len(doc["Imports"])):
                    pkg = imported_package(doc, -idx - 1)
                    if pkg and pkg[1].casefold() == target_cf:
                        matched = True
                        break
                if not matched:
                    continue
                folder = str(doc.get("FolderName") or "")
                ref_rel = folder[len("/Game/Marvel/"):] if folder.startswith("/Game/Marvel/") else fpath.stem
                ref_key = ref_rel.casefold()
                if ref_key == target_cf or ref_key in referrers:
                    continue
                m = _CHAR_RE.match(ref_rel)
                skin_info = _skin_label(m.group(2), m.group(1)) if (m and _SKIN_DIR_RE.fullmatch(m.group(2))) else None
                referrers[ref_key] = {
                    "game_rel": ref_rel,
                    "name": ref_rel.rsplit("/", 1)[-1],
                    "file_type": infer_file_type(ref_rel),
                    "skin_id": skin_info["skin_id"] if skin_info else "",
                    "skin_label": skin_info["label"] if skin_info else "",
                }
                if len(referrers) >= limit:
                    return list(referrers.values())
    return list(referrers.values())


def suggest_fork_target(game_rel: str, file_type: str | None = None) -> dict:
    """Propose a clean, collision-free private package folder and name."""
    ft = file_type or infer_file_type(game_rel)
    norm = (game_rel or "").replace("\\", "/").strip("/")
    base = norm.rsplit("/", 1)[-1]
    clean_base = _SAFE_NAME_RE.sub("_", base).strip("_")[:56] or "Asset"
    if not clean_base.lower().endswith("_private"):
        clean_base = f"{clean_base}_Private"

    m = _CHAR_RE.match(norm)
    sub = f"Hero_{m.group(1)}" if m else "Shared"
    folder = f"Atelier/Private/{sub}"
    return {"file_type": ft, "folder": folder, "name": clean_base, "forkable": ft in _FORKABLE_TYPES}


def find_references(game_rel: str, *, deep: bool = False, cache_dirs: list[Path] | None = None) -> dict:
    """Analyse whether ``game_rel`` is shared across costumes or assets."""
    config.validate_game_rel(game_rel)
    norm = game_rel.replace("\\", "/").strip("/")
    ft = infer_file_type(norm)
    parts = norm.split("/")

    is_shared = False
    scope = "skin"
    summary = "This asset belongs to a single costume folder."
    hero_id = ""
    skin_id = ""
    affected_skins: list[dict] = []

    m = _CHAR_RE.match(norm)
    if m:
        hero_id, bucket = m.group(1), m.group(2)
        costumes = _hero_costumes(hero_id)
        if _SKIN_DIR_RE.fullmatch(bucket):
            skin_id = bucket
            # Base hero costumes (ending in 001) or shared texture/material folders are often sampled by chromas.
            base_chromas = [c for c in costumes if c["skin_id"] != skin_id and c["skin_id"][:5] == skin_id[:5]]
            if bucket.endswith("001") and len(costumes) > 1 and ft in ("texture", "material"):
                is_shared = True
                scope = "hero_base"
                affected_skins = costumes
                hero_label = costumes[0]["hero_name"] or f"Hero {hero_id}"
                summary = f"Base {hero_label} asset — often shared by multiple costumes and chromas."
            elif base_chromas and ft == "texture":
                is_shared = True
                scope = "chroma_family"
                affected_skins = [_skin_label(skin_id, hero_id)] + base_chromas
                summary = f"Texture in a costume family with {len(affected_skins)} variants — chromas often share this diffuse or mask."
            else:
                affected_skins = [_skin_label(skin_id, hero_id)]
        else:
            # e.g. Characters/1060/1060CommonMaterial/... or Characters/1060/Common/...
            is_shared = True
            scope = "hero_shared"
            affected_skins = costumes
            hero_label = costumes[0]["hero_name"] if costumes else f"Hero {hero_id}"
            count = len(costumes)
            summary = (
                f"Shared across {count} {hero_label} costume{'s' if count != 1 else ''}. "
                "Editing it directly changes every costume that uses this bucket."
            )
    elif len(parts) >= 2 and (parts[0].lower() in ("vfx", "materials", "textures", "environment") or any(_SHARED_SEGMENT_RE.search(p) for p in parts[:-1])):
        is_shared = True
        scope = "global_shared"
        summary = "Shared game asset outside a single costume folder — edits here can affect multiple heroes or maps."

    scan_roots = cache_dirs
    if scan_roots is None and deep:
        scan_roots = [Path(config.CACHE_3DVIEW), Path(config._CACHE), Path(config.get_import_root())]
    verified = _scan_cached_referrers(norm, scan_roots) if (deep and scan_roots) else []

    if verified:
        verified_skins = {r["skin_id"] for r in verified if r.get("skin_id")}
        if len(verified_skins) > 1 or (skin_id and verified_skins - {skin_id}):
            is_shared = True
            known_ids = {s["skin_id"] for s in affected_skins}
            for sid in sorted(verified_skins - known_ids):
                affected_skins.append(_skin_label(sid, hero_id))
            if scope == "skin":
                scope = "verified_shared"
                summary = f"Referenced by {len(verified)} inspected assets across {len(verified_skins)} costumes."

    suggestion = suggest_fork_target(norm, ft)
    return {
        "ok": True,
        "game_rel": norm,
        "name": norm.rsplit("/", 1)[-1],
        "file_type": ft,
        "is_shared": is_shared,
        "scope": scope,
        "summary": summary,
        "hero_id": hero_id,
        "skin_id": skin_id,
        "affected_skins": affected_skins,
        "verified_referrers": verified,
        "deep_scanned": bool(deep),
        "fork": suggestion,
    }


def safe_fork(game_rel: str, file_type: str | None = None, *, folder: str | None = None, name: str | None = None) -> dict:
    """Clone a shared game asset into a private project path via Atelier's added_assets pipeline."""
    from atelier import added_assets
    config.validate_game_rel(game_rel)
    suggestion = suggest_fork_target(game_rel, file_type)
    ft = suggestion["file_type"]
    if ft not in _FORKABLE_TYPES:
        raise ValueError("Safe Fork supports textures, materials and meshes.")
    target_folder = folder if folder is not None else suggestion["folder"]
    base_name = (name or suggestion["name"]).strip()

    # Find an available name without forcing the user to manually bump suffixes.
    candidate = base_name
    last_error = None
    for attempt in range(1, 20):
        try:
            result = added_assets.add(ft, target_folder, candidate, source=game_rel)
            hint = {
                "material": "Private copy created. Replace your costume's material or assign it to a mesh slot so other skins stay unchanged.",
                "texture": "Private copy created. Assign it to a specific material's texture slot so other skins stay unchanged.",
                "mesh": "Private copy created in your project.",
            }[ft]
            return {"ok": True, "asset": result, "hint": hint}
        except ValueError as exc:
            last_error = exc
            if "already exists" in str(exc).lower() or "already uses" in str(exc).lower():
                candidate = f"{base_name}_{attempt + 1}"
                continue
            raise
    raise ValueError(str(last_error or "Could not find an available private asset name."))
