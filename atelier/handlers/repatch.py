"""VFX + Material Repatcher. Takes a broken/old mod (zip or .pak/.ucas/.utoc) and re-derives it for
the CURRENT patch: unpack the mod → decode each asset back to its data → re-apply that data onto
FRESH current-patch vanilla (via the same handlers the editors use) → repack under the current
usmap + AES. The output is structurally native to the live patch, so it just works — unlike Repak,
which re-encodes the old bytes (stale name map / imports) and breaks on most files + VFX.

Phase 1: materials (read params → stage_material). Textures / VFX curves next."""
import os, re, glob, json, shutil, subprocess, zipfile
from atelier.config import PAKS, _CACHE, USMAP, get_aes_key, CNW, WORK_IMPORT_ROOT, project_base
from atelier.tools import uat
from atelier.handlers.world import RETOC
from atelier.handlers.material import _mat_params, stage_material
from atelier.paths import pak_game_path

_PREFIX = "Marvel/Content/Marvel/"

def _vanilla_base(gr):
    """Extract the CURRENT-patch vanilla asset for game_rel; return its base path (no ext) or None."""
    import atelier.asset_cache as _ac
    from atelier.handlers.texture import extract_info, find_extracted
    wb = _ac.cache_base(gr)
    if not wb or not os.path.exists(wb + ".uasset"):
        pg = pak_game_path(gr)
        uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT), "--filter", os.path.basename(pg)])
        cp, pak, pfx = extract_info(gr)
        if cp and os.path.exists(cp + ".uasset"):
            _ac.record(gr, cp, pak, pfx); wb = cp
        else:
            wb = find_extracted(gr)
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
        for f in glob.glob(os.path.join(mod_source, "**", "*"), recursive=True):
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

def repatch_mod(mod_source, out_base, unlock=None, stage_as_project=False, relock=None):
    """Repatch one mod → out_base.{pak,ucas,utoc}. Returns {ok, applied, skipped, manifest, pak}.
    unlock: password to open a password-protected source mod. stage_as_project: ALSO load each asset
    into the active project (pre-edited) for remixing. relock: password to lock the repatched output."""
    from atelier.handlers import modlock
    if modlock.is_locked(mod_source) and not modlock.unlock(mod_source, unlock):
        return {"ok": False, "locked": True,
                "error": "This mod is password-protected — enter the password to repatch it."}
    aes = "0x" + get_aes_key()
    work = os.path.join(_CACHE, "repatch", re.sub(r"\W+", "_", os.path.basename(mod_source))[:48] or "mod")
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    src = _resolve_source(mod_source, work)
    utocs = glob.glob(src + "/**/*.utoc", recursive=True)
    if not utocs:
        return {"ok": False, "error": "no .pak/.ucas/.utoc found in the mod"}

    unpacked = os.path.join(work, "unpacked"); os.makedirs(unpacked)
    for utoc in utocs:
        subprocess.run([RETOC, "-a", aes, "unpack", utoc, "--game-paks-dir", PAKS, "-o", unpacked],
                       capture_output=True, creationflags=CNW)
    assets = sorted(set(glob.glob(unpacked + "/**/*.uasset", recursive=True)))
    if not assets:
        return {"ok": False, "error": "retoc could not unpack the mod's assets"}

    stage = os.path.join(work, "stage"); os.makedirs(stage)
    tjd = os.path.join(work, "tj")
    applied, skipped = [], []
    manifest = {"packages": len(assets), "materials": 0, "textures": 0, "skipped": 0, "staged_project": 0}
    for a in assets:
        base = os.path.basename(a); gr = _game_rel(a)
        if gr is None:
            skipped.append(f"{base}: path not under {_PREFIX}"); continue
        low = base.lower()
        if low.startswith("mi_"):
            try:
                shutil.rmtree(tjd, ignore_errors=True); os.makedirs(tjd)
                uat(["to_json", os.path.abspath(a), USMAP, os.path.abspath(tjd)])
                jf = glob.glob(tjd + "/**/*.json", recursive=True)
                if not jf:
                    skipped.append(f"{base}: mod decode failed"); continue
                d = json.load(open(jf[0], encoding="utf-8-sig"))
                cols, scals = _mat_params(d)
                cd = {c["name"]: c["rgba"] for c in cols}
                sd = {s["name"]: s["value"] for s in scals}
                stage_material(stage, gr, cd, sd)          # extract CURRENT vanilla + apply + stage
                if stage_as_project:
                    from atelier.handlers.material import save_material
                    save_material(gr, cd, sd); manifest["staged_project"] += 1
                applied.append(f"material {base} ({len(sd)} scalars, {len(cd)} colors)")
                manifest["materials"] += 1
            except Exception as e:
                skipped.append(f"{base}: {e}")
        elif low.startswith("t_"):
            try:
                mod_png = os.path.join(work, "tex", base[:-7] + ".png")
                os.makedirs(os.path.dirname(mod_png), exist_ok=True)
                uat(["extract_texture", os.path.abspath(a), os.path.abspath(mod_png), "--usmap", USMAP])
                if not os.path.exists(mod_png):
                    skipped.append(f"{base}: mod texture decode failed"); continue
                vb = _vanilla_base(gr)
                if not vb:
                    skipped.append(f"{base}: current vanilla texture not found"); continue
                pg = pak_game_path(gr)
                out_ua = os.path.join(stage, *pg.split("/")) + ".uasset"
                os.makedirs(os.path.dirname(out_ua), exist_ok=True)
                uat(["inject_texture", os.path.abspath(vb + ".uasset"), os.path.abspath(mod_png),
                     os.path.abspath(out_ua), "--usmap", USMAP])
                if os.path.exists(out_ua):
                    if stage_as_project:
                        dst = project_base(gr) + ".png"
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy(mod_png, dst); manifest["staged_project"] += 1
                    applied.append(f"texture {base}")
                    manifest["textures"] += 1
                else:
                    skipped.append(f"{base}: inject failed")
            except Exception as e:
                skipped.append(f"{base}: {e}")
        else:
            skipped.append(f"{base}: unsupported type")
    manifest["skipped"] = len(skipped)

    if not applied:
        return {"ok": False, "error": "nothing repatched", "skipped": skipped, "manifest": manifest}
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    uat(["create_mod_iostore", os.path.abspath(out_base), os.path.abspath(stage), "--usmap", USMAP])
    if not os.path.exists(out_base + ".utoc"):
        return {"ok": False, "error": "create_mod_iostore failed", "applied": applied,
                "skipped": skipped, "manifest": manifest}
    if relock:
        from atelier.handlers import modlock
        modlock.embed(out_base, relock)
    return {"ok": True, "applied": applied, "skipped": skipped, "manifest": manifest, "pak": out_base + ".pak"}
