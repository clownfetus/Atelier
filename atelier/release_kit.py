"""Batch profile variant planning and local Release Kit packaging (ZIPs + README)."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import zipfile

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SKIN_RE = re.compile(r"(?:^|/)Characters/(\d{4})/(\d{6,10})(?:/|$)", re.I)
_MOD_EXTS = (".pak", ".utoc", ".ucas")


def sanitize_stem(name: str, fallback: str = "variant") -> str:
    cleaned = _SLUG_RE.sub("_", (name or "").strip()).strip("._-")
    return cleaned[:80] or fallback


def plan_profile_variants(profiles: dict, exportable_items: list[str], base_mod_name: str, selected_names=None):
    """Build deterministic variant specs from saved Selection Profiles.

    Returns a list of dicts:
        {"profile", "mod_stem", "items", "excluded_count", "skipped_reason"}
    """
    base = sanitize_stem(base_mod_name, "AtelierMod")
    ordered_names = list(profiles.keys())
    if selected_names:
        wanted = set(selected_names)
        ordered_names = [name for name in ordered_names if name in wanted]

    used_stems: set[str] = set()
    plan = []
    for name in ordered_names:
        entry = profiles.get(name) or {}
        deselected = {str(g) for g in (entry.get("deselected") or []) if g}
        included = [g for g in exportable_items if g not in deselected]
        excluded_count = len(exportable_items) - len(included)
        custom_stem = (entry.get("mod_name") or "").strip()
        raw_stem = sanitize_stem(custom_stem, "") if custom_stem else f"{base}_{sanitize_stem(name, 'variant')}"
        stem = raw_stem or base
        if stem.casefold() in used_stems:
            n = 2
            while f"{stem}_{n}".casefold() in used_stems:
                n += 1
            stem = f"{stem}_{n}"
        used_stems.add(stem.casefold())
        plan.append({
            "profile": name,
            "mod_stem": stem,
            "items": included,
            "excluded_count": excluded_count,
            "skipped_reason": "" if included else "All edited assets are excluded in this profile.",
        })
    return plan


def _classify_asset_path(game_rel: str) -> str:
    low = (game_rel or "").replace("\\", "/").lower()
    base = low.rsplit("/", 1)[-1]
    if "/meshes/" in low or base.startswith(("sk_", "sm_")):
        return "Meshes"
    if "/materials/" in low or base.startswith(("mi_", "m_", "mat_")):
        return "Materials"
    if "/vfx/" in low or base.startswith(("ns_", "ne_", "fx_")):
        return "VFX"
    if base.startswith(("c_", "curve_")):
        return "Curves"
    if "/stringtable/" in low or base.endswith("_st"):
        return "Text"
    if "/maps/" in low or low.endswith(".umap"):
        return "Worlds"
    return "Textures"


def detect_targets(items: list[str]) -> list[str]:
    """Identify hero/costume targets referenced by the exported paths."""
    found: dict[tuple[str, str], str] = {}
    lookup = None
    try:
        from atelier.handlers import skinnames
        lookup = getattr(skinnames, "lookup", None)
    except Exception:
        lookup = None

    for rel in items:
        m = _SKIN_RE.search((rel or "").replace("\\", "/"))
        if not m:
            continue
        hero_id, skin_id = m.group(1), m.group(2)
        key = (hero_id, skin_id)
        if key in found:
            continue
        label = f"Hero {hero_id} · Skin {skin_id}"
        if callable(lookup):
            try:
                info = lookup(skin_id) or {}
                hero_name = info.get("char_name")
                skin_name = info.get("skin")
                if hero_name and skin_name:
                    label = f"{hero_name} — {skin_name} ({skin_id})"
                elif hero_name:
                    label = f"{hero_name} ({skin_id})"
            except Exception:
                pass
        found[key] = label
    return list(found.values())


def package_variant_zip(out_dir: str, mod_stem: str, artifacts: list[str], kit_dir: str) -> str | None:
    """Bundle a built variant's container files into ``<kit_dir>/<mod_stem>.zip``."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path):
        if p.is_file():
            key = os.path.normcase(str(p.resolve()))
            if key not in seen:
                seen.add(key)
                candidates.append(p)

    for art in artifacts or []:
        _add(Path(art))
    base_dir = Path(out_dir)
    for ext in _MOD_EXTS:
        _add(base_dir / f"{mod_stem}{ext}")
        _add(base_dir / f"{mod_stem}_P{ext}")

    if not candidates:
        return None
    os.makedirs(kit_dir, exist_ok=True)
    zip_path = Path(kit_dir) / f"{mod_stem}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in candidates:
            zf.write(file_path, arcname=file_path.name)
    return str(zip_path).replace("\\", "/")


def render_release_readme(
    project_name: str,
    mod_name: str,
    built_variants: list[dict],
    all_items: list[str],
    atelier_version: str = "",
) -> str:
    """Render a clean British English release README ready for Nexus or GameBanana."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    targets = detect_targets(all_items)
    counts: dict[str, int] = {}
    for rel in all_items:
        cat = _classify_asset_path(rel)
        counts[cat] = counts.get(cat, 0) + 1

    lines = [
        f"# {mod_name}",
        "",
        f"Built with **Atelier**{f' {atelier_version}' if atelier_version else ''} from project `{project_name}` on {stamp}.",
        "",
    ]
    if targets:
        lines.append("## Replaced heroes & costumes")
        lines.append("")
        for target in targets:
            lines.append(f"- {target}")
        lines.append("")

    if built_variants:
        lines.append("## Included variants")
        lines.append("")
        lines.append("| Variant | Archive | Included edits | Notes |")
        lines.append("| --- | --- | ---: | --- |")
        for var in built_variants:
            archive = Path(var["zip_path"]).name if var.get("zip_path") else f"{var['mod_stem']}.pak"
            note = "Built cleanly" if var.get("ok") else (var.get("error") or var.get("skipped_reason") or "Skipped")
            if var.get("ok") and var.get("skipped"):
                note = f"{len(var['skipped'])} warning(s)"
            lines.append(f"| {var.get('profile') or mod_name} | `{archive}` | {len(var.get('items') or [])} | {note} |")
        lines.append("")

    if counts:
        lines.append("## Edited asset breakdown")
        lines.append("")
        for cat in sorted(counts):
            lines.append(f"- **{cat}:** {counts[cat]}")
        lines.append("")

    lines.extend([
        "## Installation",
        "",
        "1. Extract the `.pak`, `.utoc` and `.ucas` files for **one** variant into your Marvel Rivals `~mods` folder (`MarvelRivals/MarvelGame/Marvel/Content/Paks/~mods`).",
        "2. Do not install multiple variants of the same mod at the same time.",
        "3. Launch Marvel Rivals.",
        "",
    ])
    return "\n".join(lines)


def write_release_kit(
    kit_dir: str,
    project_name: str,
    mod_name: str,
    built_variants: list[dict],
    all_items: list[str],
    out_dir: str,
    atelier_version: str = "",
) -> dict:
    """Create ``kit_dir`` containing per-variant ZIP archives and ``README.md``."""
    os.makedirs(kit_dir, exist_ok=True)
    zips = []
    enriched = []
    for var in built_variants:
        entry = dict(var)
        if entry.get("ok"):
            zip_path = package_variant_zip(out_dir, entry["mod_stem"], entry.get("artifacts") or [], kit_dir)
            if zip_path:
                entry["zip_path"] = zip_path
                zips.append(zip_path)
        enriched.append(entry)

    readme_path = Path(kit_dir) / "README.md"
    readme_text = render_release_readme(project_name, mod_name, enriched, all_items, atelier_version=atelier_version)
    readme_path.write_text(readme_text, encoding="utf-8")
    return {
        "kit_dir": str(kit_dir).replace("\\", "/"),
        "readme_path": str(readme_path).replace("\\", "/"),
        "zips": zips,
        "variants": enriched,
    }
