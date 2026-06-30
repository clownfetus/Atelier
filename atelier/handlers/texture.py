import os, sys, glob, re, shutil, concurrent.futures
from atelier.config import IMPORT_ROOT, WORK_IMPORT_ROOT, ASSETS_MODS, PAKS, USMAP, _CACHE, check_prereqs
from atelier.tools import uat, uat_json
from atelier.paths import char_id, game_rel_for_skin, pak_game_path, skin_entries, filter_subpath, skin_rel

def decode_png(import_base, uasset_base):
    """Decode one extracted UE texture to .png. uasset_base is where .uasset lives; png goes to import_base."""
    if not os.path.exists(uasset_base + ".uasset"): return
    out_png = os.path.abspath(import_base + ".png")
    r = uat(["extract_texture", os.path.abspath(uasset_base + ".uasset"), out_png, "--usmap", USMAP])
    if not os.path.exists(out_png):
        print(f"  [warn] PNG decode failed for {os.path.basename(import_base)}: "
              f"{((r.stderr or '') + (r.stdout or '')).strip()[-200:]}", file=sys.stderr)

def decode_batch(uasset_paths, output_root=None, base_root=None):
    """Parallel-decode many extracted .uasset textures to .png.
    output_root: where PNGs go (default IMPORT_ROOT). base_root: root used to compute relative paths (default IMPORT_ROOT)."""
    paths = [os.path.abspath(p) for p in uasset_paths if os.path.exists(p)]
    if not paths: return {}
    return uat_json({"action": "batch_extract_texture_png", "file_paths": paths,
                     "output_path": os.path.abspath(output_root or IMPORT_ROOT),
                     "base_path":   os.path.abspath(base_root   or IMPORT_ROOT),
                     "usmap_path": USMAP, "format": "png", "parallel": True})

def decode_flat(game_rels, output_dir):
    """Parallel-decode extracted uassets to output_dir as flat basename.png (no subdirectory tree)."""
    import atelier.asset_cache as _ac
    os.makedirs(output_dir, exist_ok=True)
    def _one(gr):
        cb = _ac.cache_base(gr) or find_extracted(gr)
        if not cb or not os.path.exists(cb + ".uasset"): return
        decode_png(os.path.join(output_dir, os.path.basename(cb)), cb)
    grs = list(game_rels)
    if not grs: return
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(grs))) as ex:
        list(ex.map(_one, grs))

def decode_thumb(uasset_path, thumb_path):
    """Decode the lowest available mip to a small thumbnail PNG (tries mip 4 → 3 → 2 → 0)."""
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    for mip in (4, 3, 2, 0):
        uat(["extract_texture", os.path.abspath(uasset_path), os.path.abspath(thumb_path),
             "--usmap", USMAP, "--mip", str(mip)])
        if os.path.exists(thumb_path):
            return True
    return False

def extract_info(game_rel):
    """Return (cache_base_path, pak, pfx) from the pak index (no ext on path).
    cache_base_path is where UAssetTool drops the file in WORK_IMPORT_ROOT.
    Returns (None, None, None) if the asset is absent from the index."""
    from atelier.index import ensure_index
    target = game_rel.lower() + ".uasset"
    result = (None, None, None)
    for virt_path, container, pfx in ensure_index():
        if virt_path.lower() == target:
            cp = os.path.join(WORK_IMPORT_ROOT, *(pfx.rstrip("/") + "/" + virt_path[:-7]).split("/"))
            result = (cp, container, pfx)
    return result

def find_extracted(game_rel):
    """Fallback: walk WORK_IMPORT_ROOT for a .uasset matching the game_rel suffix.
    Used when the asset_cache has no entry (legacy state, stale index, etc.)."""
    suf = os.path.join(*game_rel.split("/")) + ".uasset"
    work_abs = os.path.abspath(WORK_IMPORT_ROOT)
    for dirpath, _, files in os.walk(work_abs):
        for fname in files:
            if not fname.lower().endswith(".uasset"):
                continue
            full = os.path.join(dirpath, fname)
            if full.lower().endswith(suf.lower()):
                return full[:-7]
    return None

def stage_inject(stage, game_rel):
    """Stage one texture: inject the edited PNG into the vanilla .uasset via UAssetTool.
    Staged file is placed at the pak game path so create_mod_iostore packs it correctly."""
    import atelier.asset_cache as _ac
    import_base = os.path.join(IMPORT_ROOT, os.path.basename(game_rel))
    work_base   = _ac.cache_base(game_rel) or find_extracted(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        raise RuntimeError("no base asset — run 'import' first")
    png = import_base + ".png"
    if not os.path.exists(png):
        decode_png(import_base, work_base)
        if not os.path.exists(png):
            raise RuntimeError("PNG missing and decode failed — re-import this texture")
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    r = uat(["inject_texture", os.path.abspath(work_base + ".uasset"), os.path.abspath(png),
             os.path.abspath(out_ua), "--usmap", USMAP])
    if not os.path.exists(out_ua):
        raise RuntimeError("inject failed: " + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "unknown"))
    return os.path.basename(game_rel)

def build_mod(mod_name, tex_items, mat_items, out_dir, force=True):
    """Pack texture edits (inject) + material param edits (from_json) into one mod.
    tex_items: [game_rel]; mat_items: [{game_rel, colors:{name:[r,g,b,a]}, scalars:{name:val}}]."""
    from atelier.handlers.material import stage_material
    out_dir = os.path.abspath(out_dir); stem = f"{mod_name}_9999999_P"; base = os.path.join(out_dir, stem)
    for ext in (".pak", ".ucas", ".utoc"):
        if os.path.exists(base + ext): os.remove(base + ext)
    stage = os.path.join(_CACHE, "build_stage", mod_name)
    shutil.rmtree(os.path.join(_CACHE, "build_stage"), ignore_errors=True); os.makedirs(stage)
    applied, skipped = [], []
    for game_rel in tex_items:
        try: applied.append("tex " + stage_inject(stage, game_rel))
        except Exception as e: skipped.append(f"{os.path.basename(game_rel)}: {e}")
    for m in mat_items:
        try: applied.append("mat " + stage_material(stage, m["game_rel"],
                                                    m.get("colors", {}), m.get("scalars", {})))
        except Exception as e: skipped.append(f"{os.path.basename(m.get('game_rel',''))}: {e}")
    if not applied:
        return {"ok": False, "error": "nothing staged: " + "; ".join(skipped)}
    os.makedirs(out_dir, exist_ok=True)
    uat(["create_mod_iostore", os.path.abspath(base), os.path.abspath(stage), "--usmap", USMAP])
    if not os.path.exists(base + ".utoc"):
        return {"ok": False, "error": "create_mod_iostore failed"}
    return {"ok": True, "applied": applied, "skipped": skipped, "pak": base + ".pak"}

# ── CLI commands ───────────────────────────────────────────────────────────────

def cmd_list(arg):
    check_prereqs(need_tool=False)
    arg     = arg.replace("\\", "/")
    skin_id, _, subpath = arg.partition("/")
    entries = skin_entries(skin_id)
    if not entries:
        print(f"No entries found for skin {skin_id}"); return
    if subpath:
        entries = filter_subpath(entries, skin_id, subpath)
    if not entries:
        print(f"No entries matched under {arg!r}"); return
    seen = set()
    for p, _ in sorted(entries, key=lambda x: x[0].lower()):
        line = f"{skin_id}/{skin_rel(p, skin_id)}"
        if line not in seen:
            seen.add(line); print(line)

def cmd_import(arg):
    check_prereqs()
    import atelier.asset_cache as _ac
    arg     = arg.replace("\\", "/")
    skin_id, _, subpath = arg.partition("/")
    entries = skin_entries(skin_id)
    if not entries:
        print(f"No entries found for skin {skin_id}"); return
    if subpath:
        entries = filter_subpath(entries, skin_id, subpath)
    if not entries:
        print(f"No entries matched {arg!r}"); return

    game_rels = []
    seen = set()
    for p, _ in entries:
        sr = skin_rel(p, skin_id)
        if sr.lower().endswith(".uasset"): sr = sr[:-7]
        gr = game_rel_for_skin(skin_id, sr)
        if gr.lower() not in seen:
            seen.add(gr.lower()); game_rels.append(gr)

    names = sorted({os.path.basename(p)[:-7] for p, _ in entries})
    print(f"  Extracting {len(names)} asset(s) from game via UAssetTool...", file=sys.stderr)
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    r = uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT), "--filter"] + names)
    if "Extraction complete" not in (r.stdout or ""):
        print(f"  [warn] extract: {((r.stderr or '') + (r.stdout or '')).strip()[-300:]}", file=sys.stderr)

    cache_entries = []
    for gr in game_rels:
        cp, pak, pfx = extract_info(gr)
        if cp: cache_entries.append((gr, cp, pak, pfx))
    _ac.record_many(cache_entries)

    decode_flat(game_rels, IMPORT_ROOT)

    n_png = sum(1 for gr in game_rels
                if os.path.exists(os.path.join(IMPORT_ROOT, os.path.basename(gr) + ".png")))
    print(f"Extracted {len(names)} asset(s), decoded {n_png} PNG -> {IMPORT_ROOT}")

def _split_glob_prefix(prefix):
    if "/" in prefix:
        d, f = prefix.rsplit("/", 1)
        return d, f
    return "", prefix

def expand_export_args(args):
    """Resolve export args to [(game_rel_no_ext, display_label), ...], expanding wildcards."""
    results = []
    for arg in args:
        arg = arg.replace("\\", "/")
        if os.path.isabs(arg):
            abs_arg = arg.replace("/", os.sep)
            try:
                rel = os.path.relpath(abs_arg, WORK_IMPORT_ROOT)
                if not rel.startswith(".."):
                    arg = rel.replace("\\", "/")
                else:
                    arg = os.path.relpath(abs_arg, IMPORT_ROOT).replace("\\", "/")
            except ValueError:
                print(f"  [warn] path not under import roots: {arg}", file=sys.stderr); continue
        noext = arg[:-7] if arg.lower().endswith(".uasset") else arg
        if re.match(r"^\d{7}(/|$)", noext):
            skin_id  = noext[:7]
            tex_part = noext[8:] if len(noext) > 8 else ""
            if not tex_part:
                print(f"  [warn] no texture path after skin_id in {arg!r}", file=sys.stderr); continue
            if "*" in tex_part:
                dir_part, file_prefix = _split_glob_prefix(tex_part.split("*")[0])
                import atelier.asset_cache as _ac
                cid      = char_id(skin_id)
                skin_pfx = f"characters/{cid.lower()}/{skin_id.lower()}/"
                for gr, info in _ac.iter_skin(cid, skin_id):
                    if not os.path.exists(info["cache_path"] + ".uasset"): continue
                    r = gr[len(skin_pfx):]
                    if dir_part and not r.lower().startswith(dir_part.lower()): continue
                    if file_prefix and not os.path.basename(r).lower().startswith(file_prefix.lower()): continue
                    results.append((gr, f"{skin_id}/{r}"))
            else:
                results.append((game_rel_for_skin(skin_id, tex_part), f"{skin_id}/{tex_part}"))
        else:
            if "*" in noext:
                dir_part, file_prefix = _split_glob_prefix(noext.split("*")[0])
                import atelier.asset_cache as _ac
                for gr, info in (_ac.iter_prefix(dir_part) if dir_part else _ac.iter_prefix("")):
                    if not os.path.exists(info["cache_path"] + ".uasset"): continue
                    if file_prefix and not os.path.basename(gr).lower().startswith(file_prefix.lower()): continue
                    results.append((gr, gr))
            else:
                results.append((noext, noext))
    seen = set(); out = []
    for item in results:
        if item[0] not in seen: seen.add(item[0]); out.append(item)
    return out

def cmd_export(mod_name, tex_args, out_dir, force):
    check_prereqs()
    pairs = expand_export_args(tex_args)
    if not pairs:
        print("No files resolved for export"); return

    out_dir  = os.path.abspath(out_dir)
    stem     = f"{mod_name}_9999999_P"
    existing = [fp for ext in (".pak", ".ucas", ".utoc")
                for fp in (os.path.join(out_dir, stem + ext),) if os.path.exists(fp)]
    if existing and not force:
        print(f"Mod '{stem}' already exists in {out_dir}.")
        try:   ans = input("Overwrite? [y/N] ").strip().lower()
        except EOFError: ans = ""
        if ans != "y":
            print("Aborted."); return
    for fp in existing:
        os.remove(fp)

    stage = os.path.join(_CACHE, "cli_export_stage", mod_name)
    shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage)
    try:
        staged = 0; skipped = []
        for game_rel, label in pairs:
            try:
                desc = stage_inject(stage, game_rel)
                staged += 1
                print(f"  staged {label} -> {desc}")
            except Exception as e:
                skipped.append(f"{label}: {e}")
        if skipped:
            for s in skipped: print(f"  [warn] skipped: {s}", file=sys.stderr)
        if not staged:
            print("Nothing staged — check warnings above"); return

        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, stem)
        r    = uat(["create_mod_iostore", os.path.abspath(base), os.path.abspath(stage),
                    "--usmap", USMAP])
        if not os.path.exists(base + ".utoc"):
            print(f"create_mod_iostore failed:\n{((r.stderr or '') + (r.stdout or '')).strip()[:500]}"); return

        if os.path.exists(base + ".utoc"):
            print(f"Packed {staged} texture(s) -> {os.path.abspath(base)}.{{pak,ucas,utoc}}")
        else:
            made = sorted(glob.glob(os.path.join(out_dir, "*_P.utoc")))
            if made:
                base = made[-1][:-5]
                print(f"Packed {staged} texture(s) -> {os.path.abspath(base)}.{{pak,ucas,utoc}}")
            else:
                print(f"retoc exit 0 but no .utoc found in {out_dir}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
