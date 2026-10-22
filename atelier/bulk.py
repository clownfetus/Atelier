"""Previewed, conflict-checked batch edits for materials, curves, Niagara LUTs and MPCs."""
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
from atelier.handlers import curve as CV, vfx as V, material as M
from atelier.storage import publish_project_json
from atelier.properties import mark_changed

_plans = {}
_lock = threading.RLock()
LIFETIME = 15 * 60
MAX_ASSETS = 1000
MAX_PLAN_BYTES = 128 * 1024 * 1024


def _hash(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Values must be finite numbers")
    return float(value)


def _stored_number(value):
    # UAssetAPI emits signed zero as "+0" / "-0" strings in cooked documents.
    # API inputs remain strictly numeric; only existing asset values use this reader.
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError as error:
            raise ValueError("Material has an unsupported numeric value") from error
    return _number(value)


def _spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("Choose a batch operation")
    operation = spec.get("operation")
    if operation in ("set_opacity", "set_scalar"):
        value = _number(spec.get("value"))
        if operation == "set_opacity":
            if not 0 <= value <= 1:
                raise ValueError("Opacity must be between 0 and 1")
            return {"operation": operation, "value": value}
        name = spec.get("parameter")
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ValueError("Enter the scalar parameter name")
        return {"operation": operation, "parameter": name.strip(), "value": value}
    if operation in ("replace_material", "reparent"):
        return {"operation": operation,
                "source": M._material_path(spec.get("source"), allow_base=operation == "reparent")}
    if operation not in ("multiply", "recolor"):
        raise ValueError("Choose a supported batch operation")
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


def _transform(values, spec, color=True, number=_number):
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
        old = number(out[i])
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


def _edit_material(document, spec):
    # The display reader rounds to five decimals. Transform the actual values so
    # small opacity overrides and HDR colours retain their precision.
    props = M._ex_props(document["Exports"][0])
    colors, scalars = [], []
    for entry in (M._gn(props, "VectorParameterValues") or {}).get("Value", []):
        name, color = M._mat_pname(entry), M._mat_color(entry)
        if name and color:
            colors.append({"name": name, "rgba": [color[k] for k in "RGBA"]})
    for entry in (M._gn(props, "ScalarParameterValues") or {}).get("Value", []):
        name, value = M._mat_pname(entry), M._gn(entry["Value"], "ParameterValue")
        if name and value is not None and not isinstance(value.get("Value"), (list, dict)):
            scalars.append({"name": name, "value": value.get("Value")})
    updated_colors, updated_scalars = {}, {}
    count, sample = 0, None
    note = None
    if spec["operation"] in ("set_opacity", "set_scalar"):
        names = {"opacity", "opacitymultiplier"} if spec["operation"] == "set_opacity" else {spec["parameter"].casefold()}
        matching = [s for s in scalars if s["name"].casefold() in names]
        if not matching:
            label = "Opacity / OpacityMultiplier" if spec["operation"] == "set_opacity" else spec["parameter"]
            note = "No existing scalar override named " + label
        for scalar in matching:
            old = _stored_number(scalar["value"])
            if old != spec["value"]:
                updated_scalars[scalar["name"]] = spec["value"]
                count += 1
                sample = sample or {"before": old, "after": spec["value"]}
    else:
        for color in colors:
            changed, n, example = _transform(color["rgba"], spec, number=_stored_number)
            if n:
                updated_colors[color["name"]] = changed
                count += n
                sample = sample or example
        for scalar in scalars:
            changed, n, example = _transform([scalar["value"]], spec, color=False, number=_stored_number)
            if n:
                updated_scalars[scalar["name"]] = changed[0]
                count += n
                sample = sample or example
    M._apply_mat_edits(document, updated_colors, updated_scalars)
    return count, sample, note, bool(updated_colors)


def preview(items, spec):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ASSETS:
        raise ValueError(f"Choose between 1 and {MAX_ASSETS} material/curve/VFX assets")
    items = ["/".join(C.validate_game_rel(gr)) for gr in items]
    if len({gr.casefold() for gr in items}) != len(items):
        raise ValueError("An asset may appear only once in a batch")
    for gr in items:
        if not CV.is_curve(gr) and not V.is_vfx(gr) and not M.is_material(gr):
            raise ValueError("Bulk editing supports materials, curves, Niagara VFX and material parameter collections")
    spec = _spec(spec)
    structural = spec["operation"] in ("reparent", "replace_material")
    if spec["operation"] not in ("multiply", "recolor") and not all(M.is_material(gr) for gr in items):
        raise ValueError("This operation requires a selection containing only materials")
    root = C.get_import_root()
    changes, rows, clear_options, material_documents, guards = [], [], {}, {}, {}
    plan_bytes = 0
    donor = parent_kind = None
    if spec["operation"] == "replace_material":
        donor = M._original_document(spec["source"])
        M._material_export(donor, spec["source"])
    elif spec["operation"] == "reparent":
        parent_kind = M._parent_class(spec["source"])
    # The existing readers may create JSON. Give them a temporary project copy,
    # so reviewing a previously unimported asset cannot edit the actual project.
    with tempfile.TemporaryDirectory(prefix="atelier-bulk-preview-") as scratch:
        for i, gr in enumerate(items):
            jobs.progress("Reviewing " + os.path.basename(gr), i, len(items))
            target = C.project_base(gr, root) + ".json"
            legacy = C.project_base_legacy(gr, root) + ".json"
            guards.update({target: _hash(target), legacy: _hash(legacy)})
            if not os.path.isfile(target) and os.path.isfile(legacy):
                target = legacy
            expected = guards[target]
            staged = C.project_base(gr, scratch) + ".json"
            if expected is not None and not M.is_material(gr):
                os.makedirs(os.path.dirname(staged), exist_ok=True)
                shutil.copy2(target, staged)
            note = None
            if M.is_material(gr):
                # Material originals may belong to this project's added assets;
                # read them in the real context, without importing them for review.
                document = json.loads(Path(target).read_text(encoding="utf-8-sig")) if expected else M._original_document(gr)
                document = copy.deepcopy(document)
                kind = "material"
                if spec["operation"] == "replace_material":
                    M._material_path(gr)
                    M._material_export(document, gr)
                    if gr.casefold() == spec["source"].casefold():
                        count, sample, note = 0, None, "Source material; left unchanged"
                    else:
                        document = M._retarget_material(copy.deepcopy(donor), spec["source"], gr)
                        document[M._SOURCE_KEY] = spec["source"]
                        count, sample = 1, {"before": "Saved material", "after": spec["source"]}
                        clear_options[gr] = ("custom_textures", "color_inten", "dye_off")
                elif spec["operation"] == "reparent":
                    M._material_path(gr)
                    old = M._mat_surface(document).get("parent_path") or "Original parent"
                    count = int(M._set_material_parent(document, gr, spec["source"], parent_kind))
                    sample = {"before": old, "after": spec["source"]} if count else None
                else:
                    count, sample, note, color_changed = _edit_material(document, spec)
                    if color_changed:
                        clear_options[gr] = ("color_inten",)
                if structural and count:
                    material_documents[gr] = document
            else:
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
                if count:
                    clear_options[gr] = ("color_inten",)
            if _hash(target) != expected:
                raise RuntimeError("An asset changed while reviewing. Review the batch again.")
            rows.append({"game_rel": gr, "kind": kind, "changes": count, "sample": sample,
                         "global": kind == "mpc", "note": note})
            if count:
                plan_bytes += len(json.dumps(document, allow_nan=False).encode("utf-8"))
                relative = Path(target).relative_to(root).as_posix()
                changes.append({"path": relative, "before": expected, "data": document})
    if material_documents:
        guards.update(M._check_project_parents(material_documents))
    # Invalidate saved intensity splits only for affected assets, in the same
    # transaction as the edits. Unrelated selection/export options stay intact.
    meta = Path(root) / ".atelier" / "project.json"
    meta_hash = _hash(meta)
    if clear_options:
        guards[str(meta)] = meta_hash
    if meta.is_file():
        document = json.loads(meta.read_text(encoding="utf-8-sig"))
        changed_meta = False
        for row in rows:
            options = (document.get("asset_opts") or {}).get(row["game_rel"], {})
            for key in clear_options.get(row["game_rel"], ()):
                if key in options:
                    del options[key]
                    changed_meta = True
        if changed_meta:
            changes.append({"path": ".atelier/project.json", "before": meta_hash, "data": document})
        if _hash(meta) != meta_hash:
            raise RuntimeError("Project options changed while reviewing. Review the batch again.")
    plan_id = str(uuid.uuid4())
    with _lock:
        for key in list(_plans):
            if time.monotonic() - _plans[key]["created"] > LIFETIME:
                del _plans[key]
        # Material snapshots can contain large cooked payloads. Retain the latest
        # review even when it alone exceeds the budget, and evict older snapshots.
        while _plans and (len(_plans) >= 40 or sum(p["bytes"] for p in _plans.values()) + plan_bytes > MAX_PLAN_BYTES):
            del _plans[min(_plans, key=lambda key: _plans[key]["created"])]
        _plans[plan_id] = dict(root=os.path.realpath(root), created=time.monotonic(), changes=changes,
                              rows=rows, material_documents=material_documents, guards=guards, bytes=plan_bytes)
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
        if any(_hash(path) != before for path, before in plan["guards"].items()):
            raise RuntimeError("An asset or its project options changed after preview. Review the batch again before saving.")
        if plan["material_documents"]:
            M._check_project_parents(plan["material_documents"])
        jobs.begin_publication("Saving reviewed batch edits…")
        publish_project_json(root, plan["changes"])
        del _plans[preview_id]
    return {"ok": True, "changed_assets": sum(row["changes"] > 0 for row in plan["rows"]),
            "assets": plan["rows"]}
