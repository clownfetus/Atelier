"""VFX + Material Repatcher. Takes a broken/old mod (zip or .pak/.ucas/.utoc) and re-derives it for
the CURRENT patch: unpack the mod → decode each asset back to its data → re-apply that data onto
FRESH current-patch vanilla (via the same handlers the editors use) → repack under the current
usmap + AES. The output is structurally native to the live patch, so it just works — unlike Repak,
which re-encodes the old bytes (stale name map / imports) and breaks on most files + VFX.

Rebuilds material overrides and textures."""
import os
import re
import shutil
import tempfile
import zipfile

from atelier import hostos, jobs
from atelier.config import PAKS, _CACHE, USMAP, dir_glob, get_aes_key, project_base, validate_game_rel
from atelier.handlers.material_rebuild import decode_source, save_rebuilt_material, stage_rebuilt_material
from atelier.handlers.world import RETOC
from atelier.paths import pak_game_path
from atelier.repair_mappings import OlderMappings
from atelier.storage import container_files, publish_files
from atelier.tools import uat

_PREFIX = "Marvel/Content/Marvel/"

def _vanilla_base(gr):
    """Extract the CURRENT-patch vanilla asset for game_rel; return its base path (no ext) or None."""
    # the shared resolver: exact --filter path, both patch layouts, provenance-checked asset cache
    from atelier.handlers.texture import ensure_work_base
    wb = ensure_work_base(gr)
    return wb if wb and os.path.exists(wb + ".uasset") else None

def _game_rel(asset_path):
    """Unpacked asset path → Atelier game_rel (everything after Marvel/Content/Marvel/, no .uasset)."""
    p = asset_path.replace("\\", "/")
    i = p.find(_PREFIX)
    if i < 0:
        return None
    gr = p[i + len(_PREFIX):]
    return gr[:-7] if gr.lower().endswith(".uasset") else gr

def _resolve_source(mod_source, work):
    """Return a directory containing the mod's .pak/.ucas/.utoc (unzipping if needed)."""
    src = os.path.join(work, "src"); os.makedirs(src, exist_ok=True)
    if os.path.isdir(mod_source):
        for f in dir_glob(mod_source, "**/*", recursive=True):
            if f.lower().endswith((".pak", ".ucas", ".utoc", ".zip")):
                if f.lower().endswith(".zip"):
                    with zipfile.ZipFile(f) as z: z.extractall(src)
                else:
                    shutil.copy(f, src)
    elif mod_source.lower().endswith(".zip"):
        with zipfile.ZipFile(mod_source) as z: z.extractall(src)
    else:  # a .pak/.ucas/.utoc — copy the whole trio
        base = mod_source.rsplit(".", 1)[0]
        for ext in (".pak", ".ucas", ".utoc"):
            if os.path.exists(base + ext): shutil.copy(base + ext, src)
    return src

def repatch_mod(mod_source, out_base, unlock=None, stage_as_project=False, work_dir=None):
    """Repatch one mod → out_base.{pak,ucas,utoc}. Returns {ok, applied, skipped, manifest, pak}.
    unlock: password to open a mod an older Atelier locked; the repatched output is never locked.
    stage_as_project: ALSO load each asset into the active project (pre-edited) for remixing."""
    from atelier.handlers import modlock
    if modlock.is_locked(mod_source) and not modlock.unlock(mod_source, unlock):
        return {"ok": False, "locked": True,
                "error": "This mod is password-protected — enter the password to repatch it."}
    aes = "0x" + get_aes_key()
    work = work_dir or os.path.join(_CACHE, "repatch", re.sub(r"\W+", "_", os.path.basename(mod_source))[:48] or "mod")
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    src = _resolve_source(mod_source, work)
    utocs = dir_glob(src, "**/*.utoc", recursive=True)
    if not utocs:
        return {"ok": False, "error": "no .pak/.ucas/.utoc found in the mod"}

    unpacked = os.path.join(work, "unpacked"); os.makedirs(unpacked)
    for utoc in utocs:
        hostos.run_exe([RETOC, "-a", aes, "unpack", utoc, "--game-paks-dir", PAKS, "-o", unpacked],
                       capture_output=True)
    assets = sorted(set(dir_glob(unpacked, "**/*.uasset", recursive=True)))
    if not assets:
        return {"ok": False, "error": "retoc could not unpack the mod's assets"}

    stage = os.path.join(work, "stage"); os.makedirs(stage)
    applied, skipped = [], []
    project_materials, project_textures = [], []
    older_mappings = OlderMappings(USMAP)
    manifest = {"packages": len(assets), "materials": 0, "textures": 0, "skipped": 0,
                "staged_project": 0, "recovered_materials": 0}
    for index, asset in enumerate(assets, 1):
        base = os.path.basename(asset)
        gr = _game_rel(asset)
        jobs.progress(f"Rebuilding {base}", index, len(assets))
        if gr is None:
            skipped.append(f"{base}: path not under {_PREFIX}")
            continue
        try:
            parts = validate_game_rel(gr)
            low = base.lower()
            if low.startswith("mi_"):
                edits, recovered = decode_source(asset, gr, USMAP, older_mappings, work, uat)
                rebuilt = stage_rebuilt_material(stage, gr, edits, USMAP, work)
                if stage_as_project:
                    project_materials.append((gr, edits, rebuilt))
                scalars = sum(key[0] == "scalar" for key in edits)
                applied.append(f"material {base} ({scalars} scalars, {len(edits) - scalars} colours)")
                manifest["materials"] += 1
                manifest["recovered_materials"] += int(recovered)
            elif low.startswith("t_"):
                mod_png = os.path.join(work, "tex", *parts) + ".png"
                os.makedirs(os.path.dirname(mod_png), exist_ok=True)
                uat(["extract_texture", os.path.abspath(asset), os.path.abspath(mod_png), "--usmap", USMAP])
                if not os.path.exists(mod_png):
                    skipped.append(f"{base}: mod texture decode failed")
                    continue
                vanilla = _vanilla_base(gr)
                if not vanilla:
                    skipped.append(f"{base}: current vanilla texture not found")
                    continue
                out_ua = os.path.join(stage, *pak_game_path(gr).split("/")) + ".uasset"
                os.makedirs(os.path.dirname(out_ua), exist_ok=True)
                uat(["inject_texture", os.path.abspath(vanilla + ".uasset"), os.path.abspath(mod_png),
                     os.path.abspath(out_ua), "--usmap", USMAP])
                if not os.path.exists(out_ua):
                    skipped.append(f"{base}: inject failed")
                    continue
                if stage_as_project:
                    project_textures.append((gr, mod_png))
                applied.append(f"texture {base}")
                manifest["textures"] += 1
            else:
                skipped.append(f"{base}: unsupported type")
        except Exception as error:
            skipped.append(f"{base}: {error}")
    manifest["skipped"] = len(skipped)

    if not applied:
        return {"ok": False, "error": "nothing repatched", "skipped": skipped, "manifest": manifest}
    try:
        jobs.progress("Packing rebuilt files…")
        with tempfile.TemporaryDirectory(prefix=".repatch-pack-", dir=work) as temporary:
            packed = os.path.join(temporary, os.path.basename(out_base))
            result = uat(["create_mod_iostore", packed, os.path.abspath(stage), "--usmap", USMAP])
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "native packaging failed").strip()[-500:]
                raise RuntimeError(detail)
            publish_files(container_files(packed), os.path.dirname(os.path.abspath(out_base)))
    except (OSError, RuntimeError) as error:
        return {"ok": False, "error": f"create_mod_iostore failed: {error}", "applied": applied,
                "skipped": skipped, "manifest": manifest}

    if project_materials or project_textures:
        jobs.begin_publication("Staging rebuilt project assets…")
    for gr, edits, rebuilt in project_materials:
        try:
            save_rebuilt_material(gr, edits, rebuilt)
            manifest["staged_project"] += 1
        except Exception as error:
            skipped.append(f"{os.path.basename(gr)}: could not stage in project: {error}")
    for gr, image in project_textures:
        try:
            publish_files([image], os.path.dirname(project_base(gr)))
            manifest["staged_project"] += 1
        except Exception as error:
            skipped.append(f"{os.path.basename(gr)}: could not stage in project: {error}")
    manifest["skipped"] = len(skipped)
    return {"ok": True, "applied": applied, "skipped": skipped, "manifest": manifest, "pak": out_base + ".pak"}
