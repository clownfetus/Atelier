import os, sys, glob, re, shutil, struct, concurrent.futures
from atelier.config import (IMPORT_ROOT, WORK_IMPORT_ROOT, ASSETS_MODS, PAKS, USMAP, _CACHE,
                            check_prereqs, get_import_root, project_base, project_base_legacy)
from atelier.tools import uat, uat_json
from atelier.paths import char_id, game_rel_for_skin, pak_game_path, skin_entries, filter_subpath, skin_rel

# ── DDS passthrough ────────────────────────────────────────────────────────────
# Some textures MUST keep their exact block data, not be re-encoded from PNG. The dyeing/recolour
# masks (T_*_ColorID, slot "DyeingTexture" on M_Common_* masters) pack a REGION INDEX into alpha as
# 7 quantised steps of 255/7 ≈ 36.43 — Region 1..7 in the material's "Region N - ColorA/ColorB/
# ColorGChannel/ColorBChannel" params. They ship DXT5 (independent alpha block), Filter=TF_Nearest
# and SRGB=false precisely so a sample snaps to an exact step. Round-tripping that through a
# recompressor can drift alpha across a step boundary and silently reassign a patch to the wrong
# region — a normal map tolerates that kind of drift, an index map does not.
_BPB = {"DXT1": 8, "BC1": 8, "DXT5": 16, "BC3": 16, "BC5": 16, "BC7": 16, "BC4": 8, "BC6H": 16}

def _dds_header(w, h, fourcc, linear):
    hdr = bytearray(128); hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr, 4, 124)                                # dwSize
    struct.pack_into("<I", hdr, 8, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000) # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    struct.pack_into("<I", hdr, 12, h); struct.pack_into("<I", hdr, 16, w)
    struct.pack_into("<I", hdr, 20, linear)                            # dwPitchOrLinearSize
    struct.pack_into("<I", hdr, 28, 1)                                 # dwMipMapCount
    struct.pack_into("<I", hdr, 76, 32)                                # ddspf.dwSize
    struct.pack_into("<I", hdr, 80, 0x4)                               # ddspf.dwFlags = FOURCC
    hdr[84:88] = fourcc.encode("ascii")
    struct.pack_into("<I", hdr, 108, 0x1000)                           # dwCaps = TEXTURE
    return bytes(hdr)

def _tex_info(uasset_base):
    """(declared_w, declared_h, fourcc) from UAssetTool's own decode log."""
    probe = os.path.join(_CACHE, "_texinfo.png")
    r = uat(["extract_texture", os.path.abspath(uasset_base + ".uasset"), os.path.abspath(probe),
             "--usmap", USMAP])
    log = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"Texture:\s*(\d+)x(\d+),\s*format=PF_(\w+)", log)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else (0, 0, "")

def decode_dds(import_base, uasset_base):
    """Write the LARGEST SHIPPED mip as a .dds next to import_base, block data untouched.

    MR strips the top mip on big textures: the header still declares e.g. 4096x4096 while the
    largest data actually shipped is 2048x2048. UAssetTool maps mip[i] -> DataResource[i], so with
    mip0 absent every level is off by one, each size check fails, and it degrades to the 4x4 tail
    (measured: T_1037303_Hair_D/-Hair_ID decode as 4x4). Storage varies — .uptnl holds the top mip
    when present, otherwise the .ubulk chain starts at it — so find it rather than assume.
    Returns the dds path, or None if no block data is recoverable."""
    w, h, fmt = _tex_info(uasset_base)
    bpb = _BPB.get(fmt)
    if not bpb or not w:
        return None
    blocks = lambda d: max(1, d // 4) * max(1, d // 4)
    for src in (".uptnl", ".ubulk"):
        p = uasset_base + src
        if not os.path.exists(p):
            continue
        data = open(p, "rb").read()
        for p2 in range(14, 1, -1):
            d = 1 << p2
            if d > w:
                continue
            size = blocks(d) * bpb
            # .uptnl is exactly the top mip; .ubulk is a chain whose head is ~3/4 of the whole
            if size == len(data) or (src == ".ubulk" and size <= len(data) and size > len(data) * 0.6):
                out = import_base + ".dds"
                os.makedirs(os.path.dirname(out), exist_ok=True)
                open(out, "wb").write(_dds_header(d, d, fmt, size) + data[:size])
                return out
    return None

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
    """Parallel-decode extracted uassets to output_dir mirrored by game_rel subfolders (project_base),
    so same-named textures under different skins don't overwrite each other."""
    import atelier.asset_cache as _ac
    os.makedirs(output_dir, exist_ok=True)
    def _one(gr):
        cb = _ac.cache_base(gr) or find_extracted(gr)
        if not cb or not os.path.exists(cb + ".uasset"): return
        dst = project_base(gr, output_dir)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        decode_png(dst, cb)
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

# UAT extract_iostore_legacy drops patch pak assets under ent/Marvel[_LQ]/ instead of the full
# Marvel/Content/Marvel[_LQ]/ path that base paks use.  Map index pfx → UAT output prefix.
_PATCH_UAT_PREFIX = {
    "Marvel/Content/Marvel/":    "ent/Marvel/",
    "Marvel/Content/Marvel_LQ/": "ent/Marvel_LQ/",
}

def extract_info(game_rel):
    """Return (cache_base_path, pak, pfx) from the pak index (no ext on path).
    cache_base_path is where UAssetTool drops the file in WORK_IMPORT_ROOT.
    Returns (None, None, None) if the asset is absent from the index."""
    from atelier.index import ensure_index
    target = game_rel.lower() + ".uasset"
    result = (None, None, None)
    for virt_path, container, pfx in ensure_index():
        if virt_path.lower() == target:
            is_patch = container.lower().endswith("_p.utoc")
            uat_pfx  = _PATCH_UAT_PREFIX.get(pfx, pfx) if is_patch else pfx
            cp = os.path.join(WORK_IMPORT_ROOT, *(uat_pfx.rstrip("/") + "/" + virt_path[:-7]).split("/"))
            print(f"[extract_info] {game_rel}: container={container} pfx={pfx} uat_pfx={uat_pfx} predicted={cp}", file=sys.stderr, flush=True)
            result = (cp, container, pfx)
    if result == (None, None, None):
        print(f"[extract_info] {game_rel}: NOT IN INDEX", file=sys.stderr, flush=True)
    return result

def find_extracted(game_rel):
    """Fallback: walk WORK_IMPORT_ROOT for a .uasset matching the game_rel suffix.
    Used when the predicted path doesn't exist (e.g. stale index, unexpected UAT output prefix)."""
    suf = os.path.join(*game_rel.split("/")) + ".uasset"
    work_abs = os.path.abspath(WORK_IMPORT_ROOT)
    for dirpath, _, files in os.walk(work_abs):
        for fname in files:
            if not fname.lower().endswith(".uasset"):
                continue
            full = os.path.join(dirpath, fname)
            if full.lower().endswith(suf.lower()):
                print(f"[find_extracted] {game_rel}: found at {full}", file=sys.stderr, flush=True)
                return full[:-7]
    print(f"[find_extracted] {game_rel}: NOT FOUND in {work_abs}", file=sys.stderr, flush=True)
    return None

def stage_inject(stage, game_rel):
    """Stage one texture: inject the edited PNG into the vanilla .uasset via UAssetTool.
    Staged file is placed at the pak game path so create_mod_iostore packs it correctly."""
    import atelier.asset_cache as _ac
    # Prefer the unique subfolder path; fall back to a legacy flat png if that's where it already lives.
    import_base = project_base(game_rel)
    if not os.path.exists(import_base + ".png") and os.path.exists(project_base_legacy(game_rel) + ".png"):
        import_base = project_base_legacy(game_rel)
    work_base   = _ac.cache_base(game_rel) or find_extracted(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        raise RuntimeError("no base asset — run 'import' first")
    # An authored .dds wins over the .png: UAssetTool takes DDS directly and keeps the base's pixel
    # format, so hand-authored block data ships as-is instead of being recompressed from RGBA. That
    # matters for index maps like the ColorID/DyeingTexture masks (see decode_dds) — a recompressor
    # can nudge alpha across one of the 255/7 region steps and reassign the region.
    src = import_base + ".dds"
    if not os.path.exists(src):
        src = import_base + ".png"
        if not os.path.exists(src):
            os.makedirs(os.path.dirname(import_base), exist_ok=True)
            decode_png(import_base, work_base)
            if not os.path.exists(src):
                raise RuntimeError("PNG missing and decode failed — re-import this texture")
    pak_gr = pak_game_path(game_rel)
    out_ua = os.path.join(stage, *pak_gr.split("/")) + ".uasset"
    print(f"[stage_inject] {game_rel}: pak_game_path={pak_gr}  src={os.path.basename(src)}  stage_ua={out_ua}",
          file=sys.stderr, flush=True)
    os.makedirs(os.path.dirname(out_ua), exist_ok=True)
    r = uat(["inject_texture", os.path.abspath(work_base + ".uasset"), os.path.abspath(src),
             os.path.abspath(out_ua), "--usmap", USMAP])
    if not os.path.exists(out_ua):
        raise RuntimeError("inject failed: " + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "unknown"))
    return os.path.basename(game_rel)

def build_mod(mod_name, tex_items, mat_items, out_dir, force=True, curve_items=None, vfx_items=None,
              world_items=None, text_items=None, password=None):
    """Pack texture edits (inject) + material/curve param edits + Niagara curve edits + level (world)
    edits + StringTable (text) edits into one mod. tex_items: [game_rel]; mat_items: [{game_rel,
    colors, scalars}]; curve_items: [{game_rel, edits}]; vfx_items/world_items/text_items: [game_rel]
    (edits come from the sidecar)."""
    from atelier.handlers.material import stage_material
    from atelier.handlers.curve import stage_curve
    from atelier.handlers.vfx import stage_vfx
    from atelier.handlers.world import stage_world
    from atelier.handlers.text import stage_text
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
    for c in (curve_items or []):
        try: applied.append("curve " + stage_curve(stage, c["game_rel"], c.get("edits", {})))
        except Exception as e: skipped.append(f"{os.path.basename(c.get('game_rel',''))}: {e}")
    for gr in (vfx_items or []):
        try: applied.append("vfx " + stage_vfx(stage, gr))
        except Exception as e: skipped.append(f"{os.path.basename(gr)}: {e}")
    for gr in (text_items or []):
        try: applied.append("text " + stage_text(stage, gr))
        except Exception as e: skipped.append(f"{os.path.basename(gr)}: {e}")
    staged_any = bool(applied)   # anything that must go through create_mod_iostore (small assets)
    # WORLD (levels): patch the VANILLA Zen chunk in place (build_world_mod) and only fall back to
    # the UAssetGUI round-trip (build_world_uag) if nothing could be patched faithfully.
    #
    # WHY the order matters — measured on TimeSquare_HighQuality:
    #   retoc CANNOT round-trip a level. `retoc unpack -> retoc pack` with NO edits and no other
    #   tool involved returns 199 imports where vanilla has 166, one ImportedPublicExportHash short,
    #   and +256 bytes; the ImportMap gets RENUMBERED 0,1,2... instead of vanilla's real hash indices
    #   (only 90/166 entries survive). The engine then can't resolve those imports — including the
    #   BlueprintGeneratedClass refs — and drops placeholder actors (mesh + camera-facing billboard)
    #   at world origin. That happens for ANY edit, because the damage is in the repack, not the edit.
    #   build_world_mod never repacks the package: it patches vanilla's chunk bytes and reuses
    #   vanilla's store entry, so the same light edit comes out as FIVE changed bytes with
    #   imports 166->166 and hashes 78->78.
    # build_world_uag remains the fallback ONLY because it can ADD settings vanilla never serialized
    # (turning an override ON), which an in-place patch physically cannot do — but it corrupts the
    # package, so it must never be the default path.
    from atelier.handlers.world import build_world_mod, build_world_uag
    world_out = []
    for gr in (world_items or []):
        sub = os.path.basename(gr); sub = sub[:-5] if sub.lower().endswith(".umap") else sub
        try:
            r = build_world_mod(gr, None, os.path.join(out_dir, f"{sub}_9999999_P"))
            if not r.get("ok"):
                r = build_world_uag(gr, None, os.path.join(out_dir, f"{sub}_9999999_P"))
                if r.get("ok"):
                    skipped.append(f"{sub}: in-place patch unavailable — used the round-trip builder, "
                                   f"which breaks blueprint refs (placeholders at world origin)")
            if r.get("ok"):
                applied.append(f"world {sub} ({', '.join(r.get('applied') or [])})")
                world_out.append(os.path.join(out_dir, f"{sub}_9999999_P.pak"))
                skipped += [f"{sub}: {s}" for s in (r.get("skipped") or [])]
            else:
                skipped.append(f"{sub}: {r.get('error')}")
        except Exception as e:
            skipped.append(f"{sub}: {e}")
    if not applied:
        return {"ok": False, "error": "nothing staged: " + "; ".join(skipped)}
    os.makedirs(out_dir, exist_ok=True)
    if staged_any:
        uat(["create_mod_iostore", os.path.abspath(base), os.path.abspath(stage), "--usmap", USMAP])
        if not os.path.exists(base + ".utoc"):
            return {"ok": False, "error": "create_mod_iostore failed"}
    pak = (base + ".pak") if staged_any else (world_out[0] if world_out else base + ".pak")
    # COMBINE into one container. This runs AFTER both builders and only copies their finished chunks
    # (world edits stay exactly as build_world_mod produced them — no re-pack, byte-identical). If the
    # merge fails for any reason, we keep today's separate-paks behavior untouched.
    containers = ([base] if staged_any else []) + [w[:-4] for w in world_out]   # strip .pak -> base path
    if len(containers) >= 2:
        try:
            from atelier.handlers.container_merge import merge_containers
            tmp = base + "__merge_tmp"
            merge_containers([(c + ".utoc", c + ".ucas") for c in containers], tmp)
            for ext in (".utoc", ".ucas"):                 # swap merged result into the single base name
                if os.path.exists(base + ext): os.remove(base + ext)
                os.replace(tmp + ext, base + ext)
            if not os.path.exists(base + ".pak"):
                shutil.copy(containers[0] + ".pak", base + ".pak")
            for w in world_out:                            # drop the now-merged separate world paks
                for ext in (".pak", ".ucas", ".utoc"):
                    p = w[:-4] + ext
                    if os.path.abspath(p) != os.path.abspath(base + ext) and os.path.exists(p):
                        os.remove(p)
            pak = base + ".pak"; world_out = []
            applied.append(f"combined {len(containers)} containers into one pak")
        except Exception as e:
            skipped.append(f"pak-combine skipped (kept separate paks): {e}")
    if password:                                         # optional soft mod-lock on the exported mod
        from atelier.handlers import modlock
        for p in ([pak] + world_out):
            if p and p.endswith(".pak"): modlock.embed(p[:-4], password)
    return {"ok": True, "applied": applied, "skipped": skipped, "pak": pak, "world_mods": world_out}

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
                if os.path.exists(project_base(gr, IMPORT_ROOT) + ".png"))
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
