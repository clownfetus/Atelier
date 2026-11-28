"""Portable Look Presets and guided One-Click Hero Colour Theme engine."""
import json
import math
import os
from pathlib import Path
import re

from atelier import config, project_meta
from atelier.asset_refs import infer_file_type
from atelier.storage import atomic_json

_LOOKS_FILE = os.path.join(".atelier", "looks.json")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SKIN_PATH_RE = re.compile(r"^Characters/(\d{4})/(\d{6,10})(?:/|$)", re.I)

BUILTIN_LOOKS = (
    {
        "id": "24k-gold",
        "name": "24k Brushed Gold",
        "description": "Warm antique gold trim over deep obsidian fabric with amber energy glow.",
        "primary": "#e2b857",
        "secondary": "#1c1d24",
        "accent": "#fff0b3",
        "energy": "#ffbe44",
        "builtin": True,
    },
    {
        "id": "symbiote",
        "name": "Symbiote Gloss",
        "description": "Ink-black organic armour with stark white accents and violet venom glow.",
        "primary": "#14141b",
        "secondary": "#281e36",
        "accent": "#e8ecf2",
        "energy": "#a855f7",
        "builtin": True,
    },
    {
        "id": "cyber-neon",
        "name": "Tokyo 2099 Neon",
        "description": "Midnight indigo suit lit with electric cyan trim and hot magenta energy.",
        "primary": "#1b203b",
        "secondary": "#0f1428",
        "accent": "#22d3ee",
        "energy": "#f43f97",
        "builtin": True,
    },
    {
        "id": "frost-crystal",
        "name": "Frost Crystal",
        "description": "Glacial ice-white shell with deep winter slate and crystalline cyan glow.",
        "primary": "#dceeff",
        "secondary": "#264366",
        "accent": "#7dd3fc",
        "energy": "#38bdf8",
        "builtin": True,
    },
    {
        "id": "crimson-noir",
        "name": "Crimson Noir",
        "description": "Charcoal monochrome base punctuated by sharp crimson accents.",
        "primary": "#1c1d22",
        "secondary": "#343740",
        "accent": "#dc2626",
        "energy": "#fb7185",
        "builtin": True,
    },
    {
        "id": "jade-mystic",
        "name": "Jade Mystic",
        "description": "Deep forest emerald cloth with burnished jade highlights and spirit glow.",
        "primary": "#11382d",
        "secondary": "#1d2428",
        "accent": "#34d399",
        "energy": "#10b981",
        "builtin": True,
    },
)


def normalize_hex(value: str, fallback: str = "#ffffff") -> str:
    s = str(value or "").strip()
    if _HEX_RE.fullmatch(s):
        return s.lower()
    return fallback.lower()


def srgb_hex_to_linear(hex_color: str) -> list[float]:
    clean = normalize_hex(hex_color)
    out = []
    for offset in (1, 3, 5):
        c = int(clean[offset:offset + 2], 16) / 255.0
        lin = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        out.append(round(lin, 6))
    return out


def _looks_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / _LOOKS_FILE


def load_custom_looks(project_dir: str | Path) -> list[dict]:
    path = _looks_path(project_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        clean = []
        for item in data[:24]:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            clean.append({
                "id": str(item.get("id") or item["name"]).strip()[:64],
                "name": str(item["name"]).strip()[:48],
                "description": str(item.get("description") or "Custom saved look")[:140],
                "primary": normalize_hex(item.get("primary"), "#4f80cc"),
                "secondary": normalize_hex(item.get("secondary"), "#1c2430"),
                "accent": normalize_hex(item.get("accent"), "#eb9a72"),
                "energy": normalize_hex(item.get("energy"), "#45ab91"),
                "builtin": False,
            })
        return clean
    except Exception:
        return []


def list_looks(project_dir: str | Path) -> list[dict]:
    return [dict(item) for item in BUILTIN_LOOKS] + load_custom_looks(project_dir)


def save_custom_look(project_dir: str | Path, payload: dict) -> list[dict]:
    name = str((payload or {}).get("name") or "").strip()[:48]
    if not name:
        raise ValueError("Enter a name for this look preset.")
    existing = load_custom_looks(project_dir)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom-look"
    entry = {
        "id": f"custom-{slug}",
        "name": name,
        "description": str(payload.get("description") or "Saved custom look preset")[:140],
        "primary": normalize_hex(payload.get("primary"), "#4f80cc"),
        "secondary": normalize_hex(payload.get("secondary"), "#1c2430"),
        "accent": normalize_hex(payload.get("accent"), "#eb9a72"),
        "energy": normalize_hex(payload.get("energy"), "#45ab91"),
        "builtin": False,
    }
    updated = [item for item in existing if item["name"].casefold() != name.casefold()]
    if len(updated) >= 24:
        raise ValueError("A project can store at most 24 custom look presets.")
    updated.append(entry)
    atomic_json(_looks_path(project_dir), updated)
    return list_looks(project_dir)


def delete_custom_look(project_dir: str | Path, look_id: str) -> list[dict]:
    target = str(look_id or "").strip().casefold()
    existing = load_custom_looks(project_dir)
    updated = [item for item in existing if item["id"].casefold() != target and item["name"].casefold() != target]
    atomic_json(_looks_path(project_dir), updated)
    return list_looks(project_dir)


def classify_param_role(param_name: str) -> str:
    """Map a UE5 material colour parameter name to a semantic theme swatch role."""
    n = re.sub(r"[^a-z0-9]+", "", str(param_name or "").lower())
    if any(tok in n for tok in ("emiss", "glow", "energy", "light", "beam", "neon", "flame", "fire", "spark", "rim")):
        return "energy"
    if any(tok in n for tok in ("region5", "region6", "region7", "accent", "trim", "metal", "gold", "stripe", "detail", "edge", "line")):
        return "accent"
    if any(tok in n for tok in ("region3", "region4", "colorb", "second", "subcolor", "shadow", "dark", "cloth", "inner")):
        return "secondary"
    if any(tok in n for tok in ("region1", "region2", "colora", "base", "albedo", "diffuse", "main", "tint", "body", "color")):
        return "primary"
    return ""


def compute_material_colour_edits(colors: list[dict], theme: dict) -> dict[str, list[float]]:
    """Produce ``{param_name: [r, g, b, a]}`` overrides preserving alpha and existing HDR intensity."""
    lin = {
        "primary": srgb_hex_to_linear(theme.get("primary", "#4f80cc")),
        "secondary": srgb_hex_to_linear(theme.get("secondary", "#1c2430")),
        "accent": srgb_hex_to_linear(theme.get("accent", "#eb9a72")),
        "energy": srgb_hex_to_linear(theme.get("energy", "#45ab91")),
    }
    edits: dict[str, list[float]] = {}
    for entry in colors or []:
        name = entry.get("name")
        rgba = entry.get("rgba") or [1.0, 1.0, 1.0, 1.0]
        if not name or len(rgba) < 3:
            continue
        role = classify_param_role(name)
        if not role:
            continue
        old_rgb = [float(rgba[i]) if math.isfinite(float(rgba[i])) else 0.0 for i in range(3)]
        old_alpha = float(rgba[3]) if len(rgba) >= 4 and math.isfinite(float(rgba[3])) else 1.0
        # Preserve HDR emission intensity (> 1.0) so glowing VFX / weapon edges stay luminous.
        peak = max(old_rgb) if old_rgb else 1.0
        scale = peak if (role == "energy" and peak > 1.05) else 1.0
        base = lin[role]
        edits[name] = [round(base[0] * scale, 6), round(base[1] * scale, 6), round(base[2] * scale, 6), round(old_alpha, 6)]
    return edits


def propose_theme_targets(
    *,
    skin_id: str = "",
    hero_id: str = "",
    project_items: list[str] | None = None,
    index_entries=None,
) -> dict:
    """Build a reviewable checklist of materials, weapons, VFX and curves for a costume/hero."""
    skin = re.sub(r"[^0-9]", "", str(skin_id or ""))
    hero = re.sub(r"[^0-9]", "", str(hero_id or ""))
    if not hero and len(skin) >= 4:
        hero = skin[:4]
    if not hero and project_items:
        for rel in project_items:
            m = _SKIN_PATH_RE.match((rel or "").replace("\\", "/"))
            if m:
                hero, skin = m.group(1), skin or m.group(2)
                break

    candidates: dict[str, dict] = {}

    def _add(game_rel: str, group: str, *, checked: bool, shared: bool = False):
        norm = game_rel.replace("\\", "/").strip("/")
        key = norm.casefold()
        if key in candidates:
            return
        ft = infer_file_type(norm)
        if ft not in ("material", "vfx", "curve"):
            return
        candidates[key] = {
            "game_rel": norm,
            "name": norm.rsplit("/", 1)[-1],
            "file_type": ft,
            "group": group,
            "checked": checked,
            "shared": shared,
        }

    # Include any already-edited project materials / VFX / curves first.
    for rel in project_items or []:
        norm = str(rel or "").replace("\\", "/").strip("/")
        ft = infer_file_type(norm)
        if ft not in ("material", "vfx", "curve"):
            continue
        low = norm.lower()
        shared = "commonmaterial" in low or "/common/" in low
        group = "Weapon materials" if ("weapon" in low and ft == "material") else (
            "Costume materials" if ft == "material" else "Ability VFX & curves"
        )
        _add(norm, group, checked=not shared, shared=shared)

    if hero:
        if index_entries is None:
            from atelier.index import prefix_entries
            index_entries = list(prefix_entries(f"characters/{hero}/"))
        for path, *_ in index_entries:
            if not path.lower().endswith(".uasset"):
                continue
            rel = path[:-7]
            low = rel.lower()
            ft = infer_file_type(rel)
            if ft not in ("material", "vfx", "curve"):
                continue
            if skin and low.startswith(f"characters/{hero}/{skin}/"):
                group = "Weapon materials" if ("weapon" in low and ft == "material") else (
                    "Costume materials" if ft == "material" else "Ability VFX & curves"
                )
                _add(rel, group, checked=True, shared=False)
            elif "commonmaterial" in low and ft == "material":
                _add(rel, "Shared hero materials", checked=False, shared=True)
            elif ft in ("vfx", "curve") and f"characters/{hero}/" in low:
                _add(rel, "Ability VFX & curves", checked=False, shared=True)

    group_order = {"Costume materials": 0, "Weapon materials": 1, "Ability VFX & curves": 2, "Shared hero materials": 3}
    items = sorted(candidates.values(), key=lambda x: (group_order.get(x["group"], 9), x["name"].casefold()))[:60]
    return {
        "ok": True,
        "hero_id": hero,
        "skin_id": skin,
        "targets": items,
        "checked_count": sum(1 for t in items if t["checked"]),
    }


def apply_theme(project_dir: str | Path, targets: list[dict], theme: dict) -> dict:
    """Apply a confirmed theme checklist to materials, VFX and curves, updating Project Palette."""
    from atelier import bulk
    from atelier.handlers import material as M

    if not targets:
        raise ValueError("Select at least one asset to theme.")
    clean_theme = {
        "primary": normalize_hex(theme.get("primary"), "#4f80cc"),
        "secondary": normalize_hex(theme.get("secondary"), "#1c2430"),
        "accent": normalize_hex(theme.get("accent"), "#eb9a72"),
        "energy": normalize_hex(theme.get("energy"), "#45ab91"),
    }

    applied = []
    skipped = []
    vfx_and_curves = []

    for entry in targets:
        rel = str((entry or {}).get("game_rel") or "").strip()
        if not rel:
            continue
        config.validate_game_rel(rel)
        ft = (entry.get("file_type") or infer_file_type(rel)).lower()
        if ft == "material":
            try:
                info = M.read_material(rel)
                color_edits = compute_material_colour_edits(info.get("colors") or [], clean_theme)
                if not color_edits:
                    skipped.append(f"{rel.rsplit('/', 1)[-1]}: no themeable colour parameters")
                    continue
                res = M.save_material(rel, color_edits, {})
                if res.get("ok"):
                    applied.append({"game_rel": rel, "file_type": "material", "params_changed": len(color_edits)})
                else:
                    skipped.append(f"{rel.rsplit('/', 1)[-1]}: {res.get('error', 'save failed')}")
            except Exception as exc:
                skipped.append(f"{rel.rsplit('/', 1)[-1]}: {exc}")
        elif ft in ("vfx", "curve"):
            vfx_and_curves.append(rel)

    if vfx_and_curves:
        try:
            spec = {"operation": "recolor", "color": srgb_hex_to_linear(clean_theme["energy"]), "scope": "rgb"}
            plan = bulk.preview(vfx_and_curves, spec)
            plan_id = plan.get("plan_id")
            if plan_id:
                res = bulk.apply(plan_id)
                for row in res.get("applied") or []:
                    applied.append({"game_rel": row, "file_type": infer_file_type(row), "params_changed": 1})
                for row in res.get("skipped") or []:
                    skipped.append(str(row))
        except Exception as exc:
            skipped.append(f"VFX/Curves: {exc}")

    # Sync the 4 theme swatches into Project Palette so they stay handy everywhere in Atelier.
    try:
        existing_pal = project_meta.get_palette(project_dir)
        merged = list(existing_pal)
        for swatch in (clean_theme["primary"], clean_theme["secondary"], clean_theme["accent"], clean_theme["energy"]):
            if swatch not in merged and len(merged) < 16:
                merged.append(swatch)
        project_meta.set_palette(project_dir, merged)
    except Exception:
        pass

    return {
        "ok": len(applied) > 0,
        "applied_count": len(applied),
        "applied": applied,
        "skipped": skipped,
        "theme": clean_theme,
        "error": "" if applied else "No matching parameters could be themed on the selected assets.",
    }
