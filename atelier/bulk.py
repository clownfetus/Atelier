"""Previewed, conflict-checked batch edits for curves, Niagara LUTs and MPCs."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid

from atelier import config as C, jobs
from atelier.handlers import curve as CV, vfx as V
from atelier.storage import publish_project_json
from atelier.properties import mark_changed

_plans = {}
_lock = threading.RLock()
LIFETIME = 15 * 60
MAX_ASSETS = 100


def _hash(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Values must be finite numbers")
    return float(value)


def _spec(spec):
    if not isinstance(spec, dict) or spec.get("operation") not in ("multiply", "recolor"):
        raise ValueError("Choose multiply or recolor")
    scope = spec.get("scope", "rgb")
    if scope not in ("rgb", "alpha", "all"):
        raise ValueError("Choose RGB, alpha or all values")
    clean = {"operation": spec["operation"], "scope": scope}
    if clean["operation"] == "multiply":
        clean["factor"] = _number(spec.get("factor"))
        if abs(clean["factor"]) > 10000:
            raise ValueError("Multiplier must be between -10000 and 10000")
    else:
        color = spec.get("color")
        if not isinstance(color, list) or len(color) != 3:
            raise ValueError("Recolor needs three RGB values")
        clean.update(color=[_number(v) for v in color], scope="rgb")
    return clean


def _transform(values, spec, color=True):
    """Preserve all unselected channels, including alpha and HDR values."""
    out = list(values)
    if spec["scope"] == "rgb":
        indices = range(min(3, len(out))) if color else []
    elif spec["scope"] == "alpha":
        indices = [3] if len(out) == 4 else []
    else:
        indices = range(len(out))
    count, sample = 0, None
    for i in indices:
        old = _number(out[i])
        new = spec["color"][i] if spec["operation"] == "recolor" else old * spec["factor"]
        if not math.isfinite(new):
            raise ValueError("Result exceeds the supported numeric range")
        if new != old:
            out[i] = new
            count += 1
            sample = sample or {"before": old, "after": new}
    return out, count, sample


def _edit_curve(document, spec):
    fcs = CV._float_curves(document)
    if len(fcs) != 4 and spec["scope"] != "all":
        raise ValueError("RGB/alpha edits require a four-channel color curve")
    count, sample = 0, None
    for index, fc in enumerate(fcs[:4]):
        if spec["scope"] == "rgb" and index >= 3 or spec["scope"] == "alpha" and index != 3:
            continue
        for key in CV._keys_of(fc):
            raw = CV._rich_key(key)
            if not raw:
                raise ValueError("Unsupported curve key layout")
            old = CV._f(raw.get("Value"))
            new = spec["color"][index] if spec["operation"] == "recolor" else old * spec["factor"]
            if not math.isfinite(new):
                raise ValueError("Result exceeds the supported numeric range")
            if new != old:
                raw["Value"] = new
                # Values and slopes scale together; replacing a channel by a
                # constant zeros its slopes while retaining time/interpolation.
                for field in ("ArriveTangent", "LeaveTangent"):
                    raw[field] = 0.0 if spec["operation"] == "recolor" else CV._f(raw.get(field)) * spec["factor"]
                count += 1
                sample = sample or {"before": old, "after": new}
    return count, sample


def _edit_mpc(document, spec):
    scalars, vectors = V._mpc_lists(document)
    count, sample = 0, None
    for entry in vectors:
        default = V._gn(entry.get("Value"), "DefaultValue")
        color = V._unwrap(default.get("Value")) if default else None
        if color:
            changed, n, example = _transform([V._f(color.get(k)) for k in "RGBA"], spec)
            if n:
                mark_changed(entry, default)
                color.update(dict(zip("RGBA", changed)))
                count += n
                sample = sample or example
    if spec["scope"] == "all":
        for entry in scalars:
            default = V._gn(entry.get("Value"), "DefaultValue")
            if default:
                changed, n, example = _transform([V._f(default.get("Value"))], spec, color=False)
                if n:
                    mark_changed(entry, default)
                    default["Value"] = changed[0]
                    count += n
                    sample = sample or example
    return count, sample


def _edit_niagara(gr, document, spec):
    original = copy.deepcopy(document.get("vfx_edits") or [])
    count, sample = 0, None
    for group in V.read_vfx(gr)["groups"]:
        color = group.get("channels") == 4 and group.get("kind") in ("color", "emission")
        updated = copy.deepcopy(group)
        changed_group = False
        for stop_index, stop in enumerate(group.get("stops") or []):
            values, n, example = _transform(stop, spec, color=color)
            if n:
                updated["stops"][stop_index] = values
                changed_group = True
                count += n
                sample = sample or example
        if changed_group:
            indices = set(group["export_indices"])
            original = [g for g in original if not indices.intersection(g.get("export_indices") or [])]
            original.append({k: updated[k] for k in ("export_indices", "stops", "sample_count", "channels")})
    document["vfx_edits"] = original
    return count, sample


def preview(items, spec):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ASSETS:
        raise ValueError(f"Choose between 1 and {MAX_ASSETS} curve/VFX assets")
    if len(set(items)) != len(items):
        raise ValueError("An asset may appear only once in a batch")
    for gr in items:
        C.validate_game_rel(gr)
        if not CV.is_curve(gr) and not V.is_vfx(gr):
            raise ValueError("Bulk editing supports curves, Niagara VFX and material parameter collections")
    spec = _spec(spec)
    root = C.get_import_root()
    changes, rows = [], []
    # The existing readers may create JSON. Give them a temporary project copy,
    # so reviewing a previously unimported asset cannot edit the actual project.
    with tempfile.TemporaryDirectory(prefix="atelier-bulk-preview-") as scratch:
        for i, gr in enumerate(items):
            jobs.progress("Reviewing " + os.path.basename(gr), i, len(items))
            target = C.project_base(gr, root) + ".json"
            legacy = C.project_base_legacy(gr, root) + ".json"
            if not os.path.isfile(target) and os.path.isfile(legacy):
                target = legacy
            expected = _hash(target)
            staged = C.project_base(gr, scratch) + ".json"
            if expected is not None:
                os.makedirs(os.path.dirname(staged), exist_ok=True)
                shutil.copy2(target, staged)
            with C.project_context(scratch):
                if CV.is_curve(gr):
                    source = CV.curve_json(gr)
                    document = json.loads(Path(source).read_text(encoding="utf-8-sig"))
                    count, sample = _edit_curve(document, spec)
                    kind = "curve"
                elif V.is_mpc(gr):
                    source = V.mpc_json(gr)
                    document = json.loads(Path(source).read_text(encoding="utf-8-sig"))
                    count, sample = _edit_mpc(document, spec)
                    kind = "mpc"
                else:
                    document = json.loads(Path(staged).read_text(encoding="utf-8-sig")) if expected else {}
                    count, sample = _edit_niagara(gr, document, spec)
                    kind = "vfx"
            if _hash(target) != expected:
                raise RuntimeError("An asset changed while reviewing. Review the batch again.")
            rows.append({"game_rel": gr, "kind": kind, "changes": count, "sample": sample,
                         "global": kind == "mpc"})
            if count:
                json.dumps(document, allow_nan=False)
                relative = Path(target).relative_to(root).as_posix()
                changes.append({"path": relative, "before": expected, "data": document})
    # Invalidate saved intensity splits only for affected assets, in the same
    # transaction as the edits. Unrelated selection/export options stay intact.
    meta = Path(root) / ".atelier" / "project.json"
    if meta.is_file():
        meta_hash = _hash(meta)
        document = json.loads(meta.read_text(encoding="utf-8-sig"))
        changed_meta = False
        for row in rows:
            options = (document.get("asset_opts") or {}).get(row["game_rel"], {})
            if row["changes"] and "color_inten" in options:
                del options["color_inten"]
                changed_meta = True
        if changed_meta:
            changes.append({"path": ".atelier/project.json", "before": meta_hash, "data": document})
    plan_id = str(uuid.uuid4())
    with _lock:
        for key in list(_plans):
            if time.monotonic() - _plans[key]["created"] > LIFETIME:
                del _plans[key]
        if len(_plans) >= 40:
            del _plans[min(_plans, key=lambda key: _plans[key]["created"])]
        _plans[plan_id] = dict(root=os.path.realpath(root), created=time.monotonic(), changes=changes, rows=rows)
    return {"ok": True, "preview_id": plan_id, "assets": rows,
            "changed_assets": sum(row["changes"] > 0 for row in rows),
            "changed_values": sum(row["changes"] for row in rows), "expires_in": LIFETIME}


def apply(preview_id):
    root = C.get_import_root()
    with _lock:
        plan = _plans.get(preview_id)
        if not plan or plan["root"] != os.path.realpath(root) or time.monotonic()-plan["created"] > LIFETIME:
            raise ValueError("Preview expired or belongs to another project. Review the batch again.")
        if not plan["changes"]:
            return {"ok": True, "changed_assets": 0, "assets": plan["rows"]}
        jobs.begin_publication("Saving reviewed VFX/curve edits…")
        publish_project_json(root, plan["changes"])
        del _plans[preview_id]
    return {"ok": True, "changed_assets": sum(row["changes"] > 0 for row in plan["rows"]),
            "assets": plan["rows"]}
