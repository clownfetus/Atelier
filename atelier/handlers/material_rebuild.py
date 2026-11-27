# SPDX-License-Identifier: GPL-3.0-only
# Parameter identity and raw-export recovery adapted from X-zant/Repak-X (GPL-3.0),
# revision 1bb9c9398305673bb8426f32ca191394257a9ed5:
# repak-x/src/modules/vfx-updater/lib/materialParams.ts and repak-x/src/vfx_updater/commands.rs.
# Modified for Atelier on 26 November 2026.
"""Rebuild cooked material overrides onto the equivalent current-patch material."""
import hashlib
import json
import math
import os
import struct
import tempfile

from atelier import config, jobs
from atelier.handlers import material
from atelier.paths import pak_game_path
from atelier.properties import mark_changed
from atelier.storage import publish_project_json


_PARAMETER_LISTS = {"scalar": "ScalarParameterValues", "vector": "VectorParameterValues"}
_ASSOCIATIONS = ("LayerParameter", "BlendParameter", "GlobalParameter")
_ZERO = {"scalar": 0.0, "vector": (0.0, 0.0, 0.0, 0.0)}


def _label(key):
    kind, name, association, index = key
    return f"{name} ({kind}, {association}, index {index})"


def _fields(value, owner):
    if not isinstance(value, list) or any(not isinstance(field, dict) for field in value):
        raise ValueError(f"Invalid material properties in {owner}")
    return value


def _field(fields, name):
    fields = [field for field in fields if field.get("Name") == name]
    if len(fields) > 1:
        raise ValueError(f"Ambiguous material property {name}")
    return fields[0] if fields else None


def _tag(node):
    tag = node.get("$type")
    return tag.split(",", 1)[0].rsplit(".", 1)[-1] if isinstance(tag, str) else ""


def _parameter_key(kind, fields):
    info = _field(fields, "ParameterInfo") or {}
    identity = _fields(info.get("Value"), "ParameterInfo")
    name = (_field(identity, "Name") or {}).get("Value")
    if not isinstance(name, str) or not name:
        raise ValueError(f"A material {kind} is missing its parameter name")
    association_field = _field(identity, "Association")
    association = "GlobalParameter"
    if association_field is not None:
        association = association_field.get("Value")
        if association is None and association_field.get("IsZero") is True:
            association = "LayerParameter"
        elif type(association) is int and 0 <= association < len(_ASSOCIATIONS):
            association = _ASSOCIATIONS[association]
        elif isinstance(association, str):
            association = association.rsplit("::", 1)[-1]
    index_field = _field(identity, "Index")
    index = -1
    if index_field is not None:
        index = 0 if index_field.get("IsZero") is True else index_field.get("Value")
    if association not in _ASSOCIATIONS or type(index) is not int:
        raise ValueError(f"Invalid material parameter association or index for {name}")
    return kind, name, association, index


def _number(value, key):
    if type(value) not in (int, float) and value not in ("+0", "-0"):
        raise ValueError(f"Invalid numeric value for {_label(key)}")
    try:
        number = float(value)
        if math.isfinite(number):
            struct.pack("<f", number)
            return number
    except OverflowError:
        pass
    raise ValueError(f"Invalid numeric value for {_label(key)}")


def _parameter_value(key, node):
    kind = key[0]
    if node is None:
        return _ZERO[kind]
    expected_type = "FloatPropertyData" if kind == "scalar" else "StructPropertyData"
    if _tag(node) not in ("", expected_type) or (kind == "vector" and
            node.get("StructType") not in (None, "LinearColor")):
        raise ValueError(f"Invalid parameter type for {_label(key)}")
    if node.get("IsZero") is True:
        return _ZERO[kind]
    if kind == "scalar":
        return _number(node.get("Value"), key)
    contents = _fields(node.get("Value"), _label(key))
    if len(contents) == 1 and _tag(contents[0]) in ("", "LinearColorPropertyData"):
        colour = contents[0].get("Value")
        if isinstance(colour, dict) and all(channel in colour for channel in "RGBA"):
            return tuple(_number(colour[channel], key) for channel in "RGBA")
    raise ValueError(f"Invalid colour value for {_label(key)}")


def _parameters(export):
    values = {}
    props = _fields(export.get("Data", export.get("Value")), "the material export")
    for kind, name in _PARAMETER_LISTS.items():
        array = _field(props, name)
        if array is None or array.get("IsZero") is True:
            continue
        for entry in _fields(array.get("Value"), name):
            fields = _fields(entry.get("Value"), name)
            key = _parameter_key(kind, fields)
            node = _field(fields, "ParameterValue")
            values.setdefault(key, []).append((entry, node, _parameter_value(key, node)))
    return values


def parameter_values(export):
    """Read full-precision overrides while detecting ambiguous source identities."""
    parameters = _parameters(export)
    ambiguous = [_label(key) for key, matches in parameters.items() if len(matches) != 1]
    if ambiguous:
        raise ValueError("Ambiguous material parameters: " + ", ".join(ambiguous))
    return {key: entries[0][2] for key, entries in parameters.items()}


def _matches(export, edits, missing_message):
    target = _parameters(export)
    missing = [_label(key) for key in edits if key not in target]
    ambiguous = [_label(key) for key in edits if key in target and len(target[key]) != 1]
    problems = []
    if missing:
        problems.append(missing_message + ", ".join(missing))
    if ambiguous:
        problems.append("Ambiguous current material parameters: " + ", ".join(ambiguous))
    if problems:
        raise RuntimeError(". ".join(problems))
    return {key: target[key][0] for key in edits}


def _float_bytes(value):
    if isinstance(value, tuple):
        return struct.pack("<4f", *value)
    return struct.pack("<f", value)


def _write_value(entry, node, value):
    is_vector = isinstance(value, tuple)
    if node is None:
        node = {"Name": "ParameterValue", "IsZero": True,
                "$type": ("UAssetAPI.PropertyTypes.Structs.StructPropertyData, UAssetAPI"
                          if is_vector else
                          "UAssetAPI.PropertyTypes.Objects.FloatPropertyData, UAssetAPI")}
        if is_vector:
            node["StructType"] = "LinearColor"
        entry["Value"].append(node)
    was_zero = node.get("IsZero") is True
    mark_changed(entry, node)
    if is_vector:
        if was_zero or not node.get("Value"):
            node["Value"] = [{
                "$type": "UAssetAPI.PropertyTypes.Structs.LinearColorPropertyData, UAssetAPI",
                "Name": "ParameterValue",
                "Value": {"$type": "UAssetAPI.UnrealTypes.FLinearColor, UAssetAPI"},
            }]
        node["Value"][0]["Value"].update(zip("RGBA", value))
    else:
        node["Value"] = value


def transfer_parameters(export, edits, *, missing_message="Missing current material parameters: "):
    """Set values on their matching current entries and retain the current struct metadata."""
    for key, (entry, node, before) in _matches(export, edits, missing_message).items():
        value = edits[key]
        if _float_bytes(before) != _float_bytes(value):
            _write_value(entry, node, value)


def _decode(asset, game_rel, mapping, work, converter):
    with tempfile.TemporaryDirectory(prefix=".material-read-", dir=work) as conversion:
        jobs.checkpoint()
        result = converter(["to_json", os.path.abspath(asset), mapping, conversion])
        if result.returncode != 0:
            reason = (result.stderr or result.stdout or "to_json failed").strip()[-500:]
            raise RuntimeError(f"Material decode failed: {reason}")
        expected = os.path.join(conversion, os.path.basename(game_rel) + ".json")
        if not os.path.isfile(expected):
            raise RuntimeError("Material conversion produced no JSON")
        with open(expected, encoding="utf-8-sig") as stream:
            document = json.load(stream)

    if not isinstance(document, dict) or not isinstance(document.get("Exports"), list):
        raise ValueError("Material conversion produced invalid JSON")
    _fields(document["Exports"], "the exports table")
    _fields(document.get("Imports"), "the imports table")
    export = material._material_export(document, game_rel)
    if _tag(export) == "RawExport":
        raise material.UndecodedMaterial(f"{os.path.basename(game_rel)} is undecoded with {os.path.basename(mapping)}")
    if _tag(export) != "NormalExport" or not isinstance(export.get("Data"), list):
        raise ValueError("MaterialInstanceConstant conversion produced invalid export data")
    return document, export


def _read_source_values(asset, game_rel, mapping, work, converter):
    _, export = _decode(asset, game_rel, mapping, work, converter)
    values = parameter_values(export)
    if not values:
        raise ValueError("Source material has no scalar or vector overrides")
    return values


def decode_source(asset, game_rel, mapping, older_mappings, work, converter):
    """Only a confirmed raw material is eligible for older source mappings."""
    try:
        return _read_source_values(asset, game_rel, mapping, work, converter), False
    except material.UndecodedMaterial as error:
        attempts = 0
        detail = ""
        for older in older_mappings.paths():
            attempts += 1
            try:
                return _read_source_values(asset, game_rel, older, work, converter), True
            except material.UndecodedMaterial:
                continue
            except (ValueError, RuntimeError, OSError) as rejected:
                detail = detail or f" {os.path.basename(older)}: {rejected}"
        raise RuntimeError(
            f"Material remained undecoded after trying the current mapping and {attempts} "
            f"older mapping{'s' if attempts != 1 else ''}.{detail}"
        ) from error


def stage_rebuilt_material(stage, game_rel, edits, mapping, work):
    """Build and read back the current material before adding its files to the package stage."""
    from atelier.handlers.texture import ensure_work_base, missing_reason

    config.validate_game_rel(game_rel)
    with tempfile.TemporaryDirectory(prefix=".material-rebuild-", dir=work) as temporary:
        # Added packages belong to the selected project and can share a path with a live asset.
        with config.project_context(temporary):
            base = ensure_work_base(game_rel, prefer_exact=True)
            if not base or not os.path.isfile(base + ".uasset"):
                raise RuntimeError(missing_reason(game_rel, "material"))
        document, export = _decode(base + ".uasset", game_rel, mapping, temporary, material.uat)
        transfer_parameters(export, edits)
        name = os.path.basename(game_rel)
        converted = os.path.join(temporary, name + ".json")
        compiled = os.path.join(temporary, "compiled", name + ".uasset")
        material._compile_material(document, converted, compiled, mapping)
        try:
            readback, checked = _decode(compiled, game_rel, mapping, temporary, material.uat)
            target = _matches(checked, edits, "Missing parameters: ")
        except (ValueError, RuntimeError, OSError) as error:
            raise RuntimeError(f"Rebuilt material read-back failed: {error}") from error
        mismatches = [_label(key) for key, (_, _, actual) in target.items()
                      if _float_bytes(edits[key]) != _float_bytes(actual)]
        if mismatches:
            raise RuntimeError("Rebuilt material read-back did not preserve: " + ", ".join(mismatches))
        destination = os.path.join(stage, *pak_game_path(game_rel).split("/"))
        material._publish_material(compiled, os.path.dirname(destination))
        return readback


def save_rebuilt_material(game_rel, edits, readback):
    """Stage a verified result in the existing project layout, preserving unrelated edits."""
    root = os.path.realpath(config.get_import_root())
    target = config.project_base(game_rel, root) + ".json"
    path = next((path for path in (target, config.project_base_legacy(game_rel, root) + ".json")
                 if os.path.isfile(path)), target)
    before = None
    document = readback
    if os.path.isfile(path):
        with open(path, "rb") as stream:
            previous = stream.read()
        before = hashlib.sha256(previous).hexdigest()
        saved = json.loads(previous.decode("utf-8-sig"))
        if not material._holds_nothing(saved):
            material._require_decoded(saved, game_rel)
            transfer_parameters(saved["Exports"][0], edits, missing_message="Missing project parameters: ")
            document = saved
    publish_project_json(root, [{"path": os.path.relpath(path, root).replace("\\", "/"),
                                 "before": before, "data": document}])
