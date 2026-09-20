import os, sys, re, shutil, struct, concurrent.futures
from atelier.config import (IMPORT_ROOT, WORK_IMPORT_ROOT, ASSETS_MODS, PAKS, USMAP, _CACHE,
                            check_prereqs, get_import_root, project_base, project_base_legacy,
                            dir_glob)
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

# The format name UE reports is NOT always a legal DDS FOURCC. "BC5" in particular is not one --
# readers expect ATI2 (or BC5U) -- and BC6H/BC7 have no legacy code at all, so they need the DX10
# extension header. Writing the reported name verbatim made every BC5 NORMAL MAP fail to decode:
# PIL rejected the header, the caller silently fell back to UAssetTool, and that hits the
# stripped-top-mip problem this whole function exists to avoid -- yielding a 4x4 image that looks
# like a decode quirk and would ship as a destroyed normal map if painted and injected.
_FOURCC = {"DXT1": b"DXT1", "BC1": b"DXT1", "DXT3": b"DXT3", "DXT5": b"DXT5", "BC3": b"DXT5",
           "BC4": b"ATI1", "BC5": b"ATI2"}
_DXGI   = {"BC6H": 95, "BC7": 98}          # BC6H_UF16, BC7_UNORM

def _dds_header(w, h, fmt, linear):
    dxgi = _DXGI.get(fmt)
    hdr = bytearray(128); hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr, 4, 124)                                # dwSize
    struct.pack_into("<I", hdr, 8, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000) # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    struct.pack_into("<I", hdr, 12, h); struct.pack_into("<I", hdr, 16, w)
    struct.pack_into("<I", hdr, 20, linear)                            # dwPitchOrLinearSize
    struct.pack_into("<I", hdr, 28, 1)                                 # dwMipMapCount
    struct.pack_into("<I", hdr, 76, 32)                                # ddspf.dwSize
    struct.pack_into("<I", hdr, 80, 0x4)                               # ddspf.dwFlags = FOURCC
    hdr[84:88] = b"DX10" if dxgi else _FOURCC.get(fmt, (fmt + "\0\0\0\0")[:4].encode("ascii"))
    struct.pack_into("<I", hdr, 108, 0x1000)                           # dwCaps = TEXTURE
    if dxgi:                                                           # DDS_HEADER_DXT10
        ext = struct.pack("<IIIII", dxgi, 3, 0, 1, 0)                  # fmt, TEXTURE2D, 0, 1 slice, 0
        return bytes(hdr) + ext
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

# Where UAssetTool drops a PATCH-pak asset. Older builds used ent/Marvel[_LQ]/ instead of the full
# Marvel/Content/Marvel[_LQ]/ path that base paks use; the current build writes the mount path for
# both (verified 2026-09-19 against Patch_-Windows_1.1.3870120_P). Both layouts have to be
# considered, and not only for old tools: a work cache filled before the tool update still holds
# ent/ copies, so the same asset can exist on disk TWICE — one of them from before the game patch.
_PATCH_UAT_PREFIX = {
    "Marvel/Content/Marvel/":    "ent/Marvel/",
    "Marvel/Content/Marvel_LQ/": "ent/Marvel_LQ/",
}

_WORK_EXTS = (".uasset", ".uexp", ".ubulk", ".uptnl")


def _uat_candidates(virt_noext, pfx, is_patch):
    """Every on-disk path a UAssetTool build might have written this asset to, current layout first."""
    from atelier.index import mount_join
    prefixes = [pfx]
    if is_patch:
        legacy = _PATCH_UAT_PREFIX.get(pfx)
        if legacy:
            prefixes.append(legacy)
    return [os.path.join(WORK_IMPORT_ROOT, *mount_join(px, virt_noext).split("/")) for px in prefixes]


def work_candidates(game_rel):
    """The candidate work-cache paths for game_rel (see _uat_candidates), or [] if it is not indexed."""
    from atelier.index import index_lookup
    hit = index_lookup().get(game_rel.lower() + ".uasset")
    if not hit:
        return []
    virt_path, container, pfx = hit
    return _uat_candidates(virt_path[:-7], pfx, container.lower().endswith("_p.utoc"))

def extract_info(game_rel):
    """Return (cache_base_path, pak, pfx) from the pak index (no ext on path).
    cache_base_path is where UAssetTool drops the file in WORK_IMPORT_ROOT.
    Returns (None, None, None) if the asset is absent from the index."""
    from atelier.index import index_lookup
    hit = index_lookup().get(game_rel.lower() + ".uasset")
    if not hit:
        print(f"[extract_info] {game_rel}: NOT IN INDEX", file=sys.stderr, flush=True)
        return (None, None, None)
    virt_path, container, pfx = hit
    # Both layouts are candidates (see _PATCH_UAT_PREFIX). Take the one that is actually on disk;
    # with none there, keep the current-layout prediction so callers still get the path an
    # extraction is about to write.
    cands = _uat_candidates(virt_path[:-7], pfx, container.lower().endswith("_p.utoc"))
    cp = next((c for c in cands if os.path.exists(c + ".uasset")), cands[0])
    print(f"[extract_info] {game_rel}: container={container} pfx={pfx} "
          f"candidates={len(cands)} chosen={cp}", file=sys.stderr, flush=True)
    return (cp, container, pfx)

def find_extracted(game_rel):
    """Fallback: walk WORK_IMPORT_ROOT for the extracted .uasset.
    Used when the predicted path doesn't exist (e.g. stale index, unexpected UAT output prefix).

    Two passes, and the order is the point:
      1. the FULL mount path (Marvel/Plugins/MarvelGAS/Content/UI/T_X) — exact, cannot cross mounts;
      2. only for non-plugin assets, the bare game_rel tail, because UAT writes patch-pak assets
         under 'ent/Marvel/...' instead of their mount path (see _PATCH_UAT_PREFIX) and pass 1
         cannot see through that.
    Pass 2 is withheld from plugin assets deliberately: a tail like 'Marvel/Wwise/.../sfx.uasset'
    also matches the MAIN mount's copy at 'Marvel/Content/Marvel/Wwise/.../sfx.uasset', so the
    "fallback" silently answers with a different asset -- the exact substitution text.py documents.
    """
    from atelier.index import split_plugin_root
    root, _rest = split_plugin_root(game_rel)
    work_abs = os.path.abspath(WORK_IMPORT_ROOT)
    wants = ["/" + pak_game_path(game_rel).replace("\\", "/").lower() + ".uasset"]
    if not root:
        # the legacy patch layout (ent/Marvel/...) and, last, the bare game_rel tail
        wants += ["/" + c.replace("\\", "/").lower()[len(work_abs) + 1:] + ".uasset"
                  for c in work_candidates(game_rel)[1:]]
        wants.append("/" + game_rel.replace("\\", "/").lower() + ".uasset")
    for want in wants:
        for dirpath, _, files in os.walk(work_abs):
            for fname in files:
                if not fname.lower().endswith(".uasset"):
                    continue
                full = os.path.join(dirpath, fname)
                if full.replace("\\", "/").lower().endswith(want):
                    print(f"[find_extracted] {game_rel}: found at {full}", file=sys.stderr, flush=True)
                    return full[:-7]
    print(f"[find_extracted] {game_rel}: NOT FOUND in {work_abs}", file=sys.stderr, flush=True)
    return None

def missing_reason(game_rel, kind="asset", check_index=True):
    """Explain WHY an asset could not be resolved, distinguishing three very different states.

    All three used to surface as the single sentence "not found in game paks", which made four
    unrelated reports look identical and none of them triageable:

      * not indexed      - no container Atelier read contains it (it may genuinely not exist)
      * container failed - some containers did not parse, so the asset may be inside one of them.
                           Almost always a wrong or stale AES key.
      * extract failed   - it IS in the index, but UAssetTool produced no file for it.

    check_index=False for asset kinds the index does not carry (levels are .umap; index.py only
    records .uasset), so the caller never claims "not in the index" about something that was
    never indexable in the first place.
    """
    from atelier.index import ensure_index, index_warnings
    try:
        ensure_index()
        failed = index_warnings()
    except Exception:
        failed = []

    cp = pak = None
    if check_index:
        try:
            cp, pak, _pfx = extract_info(game_rel)
        except Exception:
            cp = pak = None

    if cp is not None:
        return (f"{kind} could not be extracted: {game_rel}. It IS in the asset index "
                f"(container {pak}), but the extractor produced no file for it. Check the newest "
                f"log in _logs for an extract failure.")

    if failed:
        names = ", ".join(f["container"] for f in failed[:3])
        more  = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
        return (f"{kind} not found: {game_rel}. {len(failed)} pak container(s) failed to read - "
                f"{names}{more} - so it may be inside one of them. That is usually a wrong or "
                f"stale AES key; re-check the key in Settings.")

    if check_index:
        return (f"{kind} not found: {game_rel}. It is not in any indexed pak container - check "
                f"the asset path, or that the game files are up to date.")
    return (f"{kind} not found: {game_rel}. Every pak container read cleanly, so the paks do not "
            f"appear to contain it - check the path, or that the game files are up to date.")


def is_plugin_asset(game_rel):
    """True for a virtual path under a plugin mount (Plugins/MarvelGAS/...) — see index.plugin_root."""
    from atelier.index import split_plugin_root
    return bool(split_plugin_root(game_rel)[0])

def prefers_retoc():
    """True when container reads should go through retoc rather than UAssetTool.

    Always on Linux. The native UAssetTool build refuses to decompress without Oodle
    (`liboo2corelinux64.so.9`, which is not redistributable and is not the ABI Tools/libooz.so
    provides), while retoc decodes the same chunks on its own. It is also far faster on any host —
    a full path goes straight to the right container instead of scanning ~548k packages for a
    basename — and that full path is what disambiguates assets that share a basename across mounts.
    Windows keeps the UAssetTool path it has always used; nothing there changes.
    """
    from atelier import hostos
    return not hostos.IS_WINDOWS


def _retoc_container(game_rel):
    """The .utoc holding this asset, from the index, or None to mean 'try them all'."""
    try:
        _cp, pak, _pfx = extract_info(game_rel)
    except Exception:
        return None
    if not pak:
        return None
    path = os.path.join(PAKS, pak)
    return path if os.path.exists(path) else None


def extract_via_retoc(game_rels):
    """Unpack assets by their FULL mount paths. Takes one game_rel or many.

    Returns {game_rel: (stem, pak, pfx)}. Locating the extracted file already costs an index
    lookup, so the container and prefix it yields are handed back with it — callers record those
    in the asset cache and would otherwise repeat the same lookup per asset.

    Two reasons this is the better extractor, and one that is a correctness issue:
    `extract_iostore_legacy --filter` matches BASENAMES, and MarvelGAS ships assets whose basenames
    also exist under Marvel/Content/Marvel — given the ambiguous name UAssetTool writes one asset's
    bytes to the other asset's path, silently (verified for the hero-ability StringTables; see
    text.py::_extract_via_retoc). retoc names the exact package instead. It also takes repeated
    --filter flags, so a whole batch is one call, and the index already knows which container each
    asset lives in, so there is nothing to scan.
    """
    from atelier.config import get_aes_key, dir_glob
    from atelier.handlers.world import RETOC
    from atelier import hostos
    if isinstance(game_rels, str):
        game_rels = [game_rels]
    game_rels = [g for g in game_rels if g]
    if not game_rels:
        return {}
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)

    # Group by the container the index says holds each asset; anything unplaced gets the full sweep.
    by_cont = {}
    for gr in game_rels:
        by_cont.setdefault(_retoc_container(gr), []).append(gr)
    sweep = by_cont.pop(None, [])
    if sweep:
        # Patch containers override base chunks in-game, so they must win here too.
        utocs = sorted(dir_glob(PAKS, "*.utoc"))
        utocs.sort(key=lambda p: 0 if "patch" in os.path.basename(p).lower() else 1)
        for utoc in utocs:
            by_cont.setdefault(utoc, []).extend(sweep)

    found = {}
    for utoc, grs in by_cont.items():
        todo = [g for g in grs if g not in found]
        if not todo:
            continue
        args = [RETOC, "-a", "0x" + get_aes_key(), "unpack", utoc]
        for gr in todo:
            args += ["--filter", "../../../" + pak_game_path(gr) + ".uasset"]
        args += ["--game-paks-dir", PAKS, "-o", os.path.abspath(WORK_IMPORT_ROOT)]
        try:
            r = hostos.run_exe(args, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  [warn] retoc unpack rc={r.returncode} on {os.path.basename(utoc)}: "
                      f"{((r.stdout or '') + (r.stderr or '')).strip()[-300:]}",
                      file=sys.stderr, flush=True)
        except Exception as e:
            print(f"  [warn] retoc unpack failed on {os.path.basename(utoc)}: {e}",
                  file=sys.stderr, flush=True)
            continue
        for gr in todo:
            cp, pak, pfx = extract_info(gr)
            if cp and os.path.exists(cp + ".uasset"):
                found[gr] = (cp, pak, pfx)
    return found


def extract_many(game_rels):
    """Extract a batch and record it in the asset cache. {game_rel: stem} for everything that landed.

    The batch entry point for import-all / thumbnail prefetch / export, so those paths get retoc's
    one-call extract on Linux instead of a per-asset UAssetTool scan.
    """
    import atelier.asset_cache as _ac
    game_rels = [g for g in (game_rels or []) if g]
    if not game_rels:
        return {}
    found = {}  # game_rel -> (stem, pak, pfx)
    if prefers_retoc() or any(is_plugin_asset(g) for g in game_rels):
        found = extract_via_retoc(game_rels)
    missing = [g for g in game_rels if g not in found]
    if missing and not prefers_retoc():
        os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
        uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT)] + uat_filter(missing))
        for gr in missing:
            cp, pak, pfx = extract_info(gr)
            if cp and os.path.exists(cp + ".uasset"):
                found[gr] = (cp, pak, pfx)
    entries = [(gr, stem, pak or "", pfx or "") for gr, (stem, pak, pfx) in found.items()]
    if entries:
        _ac.record_many(entries)
    return {gr: stem for gr, (stem, _pak, _pfx) in found.items()}


def missing_optional_mip(game_rel, cache_base):
    """True when this cached copy predates the HQ texture DLC and the paks now offer its top mip.

    The DLC ships as pakchunk<X>optional-Windows containers carrying ONLY .uptnl files — the top
    mip of textures whose .uasset stays in its ordinary chunk. Nothing else can see that a copy is
    out of date: ensure_work_base's provenance check compares the container the index names for the
    .uasset, and that container did not change — a DIFFERENT container appeared beside it. So a
    machine that installs the DLC would keep serving its pre-DLC, half-resolution copies forever,
    which is the opposite of what the person just downloaded.

    Deliberately one-directional. Uninstalling the DLC makes has_optional_mip False again, and a
    cached copy that still holds the top mip is then BETTER than anything the paks can hand back —
    so this never asks for it to be thrown away.
    """
    if not cache_base or not os.path.exists(cache_base + ".uasset"):
        return False
    if os.path.exists(cache_base + ".uptnl"):
        return False
    try:
        from atelier.index import has_optional_mip
        return has_optional_mip(game_rel)
    except Exception:
        return False


def uptnl_dimension(uptnl_path):
    """The pixel dimension of a .uptnl top mip, from its byte length alone. None if it doesn't fit.

    A .uptnl is exactly one square mip of block-compressed data, so len == (d/4)^2 * bytes_per_block
    and d is a power of two. The two block sizes cannot collide: solving (d/4)^2*16 == (d'/4)^2*8
    gives d' = d*sqrt(2), which is never also a power of two. That makes this exact without asking
    the asset what format it is -- which matters, because the alternative is a UAssetTool call per
    texture just to answer "is this one bigger now".
    """
    try:
        n = os.path.getsize(uptnl_path)
    except OSError:
        return None
    for p2 in range(14, 1, -1):
        d = 1 << p2
        blocks = max(1, d // 4) ** 2
        if n in (blocks * 8, blocks * 16):
            return d
    return None


def stale_mip_imports(import_root=None):
    """Project textures whose PNG is below the resolution the paks can now give: [{game_rel, ...}].

    The work cache repairs itself (see ensure_work_base), but a project PNG does not: import
    deliberately never overwrites one, because it is the user's artwork. So after the HQ texture
    DLC lands, the textures already in a project stay at the resolution they were decoded at, and
    nothing says so.

    Measured off the PNG rather than off cache state, so the answer does not change depending on
    whether the work copy has been re-extracted yet. This only REPORTS -- re-importing is the
    user's call, because for an edited texture it means redoing the edit at the larger size.
    """
    from atelier.config import get_import_root, project_game_rel
    root = import_root or get_import_root()
    if not os.path.isdir(root):
        return []
    try:
        from atelier.index import optional_mips
        opts = optional_mips()
    except Exception:
        return []
    if not opts:
        return []
    import atelier.asset_cache as _ac
    from PIL import Image
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".atelier"]
        for fname in files:
            if not fname.endswith(".png"):
                continue
            fpath = os.path.join(dirpath, fname)
            gr = project_game_rel(fpath, root)
            if "/" not in gr:
                gr = _ac.by_name(gr) or gr
            if gr.lower() not in opts:
                continue
            try:
                with Image.open(fpath) as im:
                    have = max(im.size)
            except Exception:
                continue
            cb  = _ac.cache_base(gr)
            top = uptnl_dimension(cb + ".uptnl") if cb and os.path.exists(cb + ".uptnl") else None
            if top is None:
                # The paks have a top mip and the work copy does not, so this PNG was decoded
                # before the DLC. We cannot say how much bigger it should be until the re-extract
                # happens, only that it is not current.
                out.append({"game_rel": gr, "name": os.path.basename(gr), "have": have, "full": 0})
            elif have < top:
                out.append({"game_rel": gr, "name": os.path.basename(gr), "have": have, "full": top})
    return out


def _purge_ambiguous(game_rel):
    """Delete every work-cache copy when there is more than one, so the re-extract cannot lose.

    A game patch moves an asset from a base chunk into a patch chunk. Extract it before the patch
    and again after, with a tool update in between, and BOTH layouts end up on disk — the same
    asset twice, one of them pre-patch. Nothing on disk says which is which, so the only answer
    that cannot serve stale bytes is to drop both and extract again.

    Deliberately a no-op when there is a single copy: extraction overwrites that path anyway, and
    deleting it would throw away a usable asset if the extractor then fails.
    """
    cands = [c for c in work_candidates(game_rel) if os.path.exists(c + ".uasset")]
    if len(cands) < 2:
        return False
    print(f"  [warn] {game_rel}: {len(cands)} work-cache copies (a patch moved it); re-extracting",
          file=sys.stderr, flush=True)
    _purge_work(game_rel)
    return True


def _purge_work(game_rel):
    """Delete every work-cache copy of game_rel, whichever layout it is in. Returns the count.

    Used where a copy is KNOWN stale rather than merely ambiguous. Leaving it would be worse than
    losing it: extract_info happily finds it again afterwards and the asset cache re-records the
    pre-patch bytes under the new container, so the invalidation would achieve nothing at all.
    """
    n = 0
    for c in work_candidates(game_rel):
        if os.path.exists(c + ".uasset"):
            n += 1
        for ext in _WORK_EXTS:
            try: os.remove(c + ext)
            except OSError: pass
    return n


def uat_filter(game_rels):
    """`--filter` arguments for these assets: full virtual paths, never basenames.

    `--filter` matches against the VIRTUAL path, so it takes a game_rel as-is (verified: the
    basename MI_1011001_1011_Body extracts 2 assets, the game_rel extracts the 1 that was asked
    for, and the mount-prefixed form matches nothing). A basename is both wasteful — every
    same-named asset in the game gets converted — and unsafe: where two mounts share one, the
    tool writes one asset's bytes to the other's path, which is the substitution text.py
    documents for the hero-ability StringTables.

    Long batches go through the patterns-FILE form the tool also accepts. 500 paths is ~40 KB of
    command line and Windows caps at ~32 KB, so a large import would otherwise fail on the
    argument list rather than on anything real.
    """
    pats = sorted({str(g).replace("\\", "/") for g in game_rels if g})
    if not pats:
        return []
    if sum(len(x) + 1 for x in pats) > 8000:
        fp = os.path.join(_CACHE, "_uat_filter.txt")
        os.makedirs(_CACHE, exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(pats) + "\n")
        return ["--filter", os.path.abspath(fp)]
    return ["--filter"] + pats


def ensure_work_base(game_rel):
    """Extracted .uasset stem (no ext) under WORK_IMPORT_ROOT, extracting from the paks on a miss.
    Returns None if the asset isn't in the game at all."""
    import atelier.asset_cache as _ac
    cached = _ac.get(game_rel)
    if cached:
        cb  = cached.get("cache_path") or ""
        rec = (cached.get("pak") or "").lower()
        _cp, pak, _pfx = extract_info(game_rel)
        # Provenance check: the container the index names now vs the one this copy came from. They
        # differ exactly when a game patch has taken the asset over, and the cached bytes are then
        # the pre-patch ones -- the shape of "my materials broke after the update".
        stale_mip = missing_optional_mip(game_rel, cb)
        if os.path.exists(cb + ".uasset") and (not rec or not pak or rec == pak.lower()) \
                and not stale_mip:
            return cb
        if stale_mip:
            print(f"  [warn] {game_rel}: cached before the HQ texture DLC (no .uptnl, and the paks "
                  f"now have one) — re-extracting", file=sys.stderr, flush=True)
            _purge_work(game_rel)
        elif rec and pak and rec != pak.lower():
            print(f"  [warn] {game_rel}: cached from {rec}, index now says {pak.lower()} — re-extracting",
                  file=sys.stderr, flush=True)
            _purge_work(game_rel)      # the copy on disk is pre-patch too, not just the entry
        _ac.remove(game_rel)
    _purge_ambiguous(game_rel)
    # Full-path extract first wherever it applies: on Linux (UAssetTool cannot read containers
    # without Oodle) and for plugin assets anywhere (a basename cannot tell them from their twins).
    if prefers_retoc() or is_plugin_asset(game_rel):
        hit = extract_via_retoc([game_rel]).get(game_rel)
        if hit:
            rb, pak, pfx = hit
            _ac.record(game_rel, rb, pak or "", pfx or "")
            return rb
        # Fall through to UAssetTool rather than giving up: retoc cannot currently extract from a
        # PATCH container ("FPackageId(...) has no path name entry"), which is ~5% of the index but
        # includes the most recently changed assets. On Windows UAssetTool covers those; on Linux it
        # reports the missing-Oodle reason, which is the honest answer rather than "not found".
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    r = uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT)]
            + uat_filter([game_rel]))
    # A tool crash, a file lock, or a MOTW-tainted DLL all leave the asset unextracted, and the
    # caller can only report "not found in the game paks" — indistinguishable from an asset the
    # game genuinely doesn't have. Log the failure so a transient one is diagnosable from _logs.
    if r.returncode != 0:
        print(f"  [warn] extract_iostore_legacy rc={r.returncode} for {game_rel}: "
              f"{((r.stdout or '') + (r.stderr or '')).strip()[-500:]}", file=sys.stderr, flush=True)
    cp, pak, pfx = extract_info(game_rel)
    if cp and os.path.exists(cp + ".uasset"):
        _ac.record(game_rel, cp, pak, pfx)
        return cp
    base = find_extracted(game_rel)
    if base and os.path.exists(base + ".uasset"):
        # Record the fallback too. Only the predicted-path branch used to, so every asset whose
        # layout the prediction missed -- which was EVERY patch-pak asset while _PATCH_UAT_PREFIX
        # was stale -- was re-extracted on every single operation and never cached at all.
        _ac.record(game_rel, base, pak or "", pfx or "")
        return base
    return None

def decode_to_png(import_base, uasset_base):
    """Decode one extracted texture to import_base + '.png', preferring the largest SHIPPED mip.

    MR strips the top mip on big textures, so UAssetTool on its own can degrade to the 4x4 tail
    (see decode_dds); recover the real block data first and convert that, falling back to
    UAssetTool's decode. Leaves a .dds beside import_base as a by-product of the recovery, so
    callers that must not produce one (a PROJECT folder, where a .dds outranks the .png at inject
    time) should decode into a cache dir and copy only the .png out."""
    os.makedirs(os.path.dirname(import_base), exist_ok=True)
    out_png = import_base + ".png"
    dds = None
    try:
        dds = decode_dds(import_base, uasset_base)
    except Exception as e:
        print(f"  [warn] decode_dds failed for {os.path.basename(import_base)}: {e}", file=sys.stderr)
    if dds and os.path.exists(dds):
        try:
            from PIL import Image
            Image.open(dds).convert("RGBA").save(out_png)
        except Exception as e:
            print(f"  [warn] dds->png failed for {os.path.basename(import_base)}: {e}", file=sys.stderr)
    if not os.path.exists(out_png):
        decode_png(import_base, uasset_base)
    return out_png if os.path.exists(out_png) else None

# ── per-texture export options ────────────────────────────────────────────────
# Three requests that all land on the same call (inject_texture) and were each answered with "you
# need UE for that":
#   #20 ch3rr13 + hobbyr34 — NoMipMaps / texture group. UAssetTool already takes `--no-mips`
#       (Mode A: one inline mip, no .ubulk); the texture GROUP is an ordinary LODGroup enum on the
#       export, so it is a to_json/from_json edit on the asset we just injected.
#   #21 norskpl — duplicate UI textures into Marvel_LQ, so an LQ-quality client sees the edit too.
#   #22 pushingpetals — remove a texture rather than replace it.
#
# On #22, plainly: a mod pak CANNOT delete an asset. It can only override one. "Remove" therefore
# means shipping a fully transparent texture over it, which is what people do by hand today — so
# the option is named for what it does (blank) rather than for what it is wished to be.

# Offered in the UI; anything else the user's asset already declares is preserved rather than
# forced onto this list. TEXTUREGROUP_UI is the one that matters for the request (UI textures
# being mip-blurred), the rest are here so a character/VFX texture can be put back.
TEXTURE_GROUPS = ("TEXTUREGROUP_Character", "TEXTUREGROUP_CharacterNormalMap",
                  "TEXTUREGROUP_CharacterSpecular", "TEXTUREGROUP_UI", "TEXTUREGROUP_Effects",
                  "TEXTUREGROUP_EffectsNotFiltered", "TEXTUREGROUP_World",
                  "TEXTUREGROUP_WorldNormalMap", "TEXTUREGROUP_Skybox")


def texture_props(work_base):
    """{lod_group, filter, srgb} as the vanilla asset declares them, or {} if it can't be read.

    The UI needs the CURRENT texture group to show as the starting value — offering a dropdown
    that defaults to something the asset isn't is how a user "sets" a group they already had and
    ships a changed asset for no reason."""
    out_dir = os.path.join(_CACHE, "texprops")
    os.makedirs(out_dir, exist_ok=True)
    jp = os.path.join(out_dir, os.path.basename(work_base) + ".json")
    try:
        if os.path.exists(jp):
            os.remove(jp)
        uat(["to_json", os.path.abspath(work_base + ".uasset"), USMAP, os.path.abspath(out_dir)])
        import json as _json
        d = _json.load(open(jp, encoding="utf-8-sig"))
        ex = d["Exports"][0]
        props = ex.get("Data") or ex.get("Value") or []
        got = {}
        for pr in props:
            if pr.get("Name") == "LODGroup":   got["lod_group"] = pr.get("Value")
            elif pr.get("Name") == "Filter":   got["filter"]     = pr.get("Value")
            elif pr.get("Name") == "SRGB":     got["srgb"]       = pr.get("Value")
        return got
    except Exception as e:
        print(f"  [warn] texture_props failed for {os.path.basename(work_base)}: {e}",
              file=sys.stderr, flush=True)
        return {}


def set_texture_group(out_ua, group):
    """Rewrite an already-staged texture's LODGroup in place. Returns True if it was changed.

    Deliberately a SECOND pass over inject_texture's output rather than an edit of the vanilla
    asset before injection: injection is the step that rebuilds the mip chain and the bulk files,
    so anything done before it is thrown away. from_json writes only .uasset/.uexp, which is why
    this can run over a staged asset at all — the .ubulk/.uptnl beside it are left exactly as
    inject_texture wrote them, and the mips still resolve (verified end to end: inject -> set
    group -> extract_texture returns the same 1024x1024 image with the new group in its JSON).
    """
    if not group or group not in TEXTURE_GROUPS:
        return False
    import json as _json
    work = os.path.join(_CACHE, "texgroup")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    stem = os.path.basename(out_ua)[:-7]
    uat(["to_json", os.path.abspath(out_ua), USMAP, os.path.abspath(work)])
    jp = os.path.join(work, stem + ".json")
    if not os.path.exists(jp):
        raise RuntimeError("texture group: to_json produced no JSON")
    d = _json.load(open(jp, encoding="utf-8-sig"))
    ex = d["Exports"][0]
    props = ex.get("Data") or ex.get("Value") or []
    hit = next((pr for pr in props if pr.get("Name") == "LODGroup"), None)
    if hit is None:
        # The property is only serialised when it differs from the class default, so a texture
        # sitting on the default group has no LODGroup entry to edit. Say so instead of appending
        # a property whose wrapper type we would be guessing at.
        raise RuntimeError("this texture does not serialise a LODGroup, so it cannot be retargeted")
    if hit.get("Value") == group:
        return False
    hit["Value"] = group
    _json.dump(d, open(jp, "w"))
    tmp_ua = os.path.join(work, "out", stem + ".uasset")
    os.makedirs(os.path.dirname(tmp_ua), exist_ok=True)
    uat(["from_json", os.path.abspath(jp), os.path.abspath(tmp_ua), USMAP])
    if not os.path.exists(tmp_ua):
        raise RuntimeError("texture group: from_json produced no uasset")
    for ext in (".uasset", ".uexp"):                  # NOT .ubulk/.uptnl — those stay as injected
        src = tmp_ua[:-7] + ext
        if os.path.exists(src):
            shutil.copyfile(src, out_ua[:-7] + ext)
    return True


# Which pixel formats carry a real alpha channel. This decides whether "blank" can mean INVISIBLE
# or only BLACK, and it is not a detail: inject_texture keeps the base asset's pixel format, so a
# fully transparent PNG injected into a DXT1 texture comes back opaque black (measured on
# T_1050103_Body_01_D). Shipping that as "removed" would be the same trap thetruedaveed fell into
# from the other side — a black image that still renders — so the app has to say which of the two
# it is about to do rather than promise transparency it cannot deliver.
_ALPHA_FORMATS = {"DXT5", "BC3", "DXT3", "BC2", "BC7", "B8G8R8A8", "R8G8B8A8", "A8R8G8B8", "A8",
                  "FloatRGBA", "A16B16G16R16"}


def texture_format(work_base):
    """The pixel format UE declares for this texture ('DXT1', 'BC7', …), or '' if unreadable."""
    try:
        return _tex_info(work_base)[2] or ""
    except Exception:
        return ""


def format_has_alpha(fmt):
    """Whether a texture in this format can be made transparent at all."""
    return (fmt or "") in _ALPHA_FORMATS


def blank_png(out_png, size):
    """A fully transparent RGBA PNG — the only thing a mod pak can do that reads as "removed"."""
    from PIL import Image
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    w, h = size
    Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0)).save(out_png)
    return out_png


def texture_size(game_rel, work_base=None):
    """(w, h) for a texture: the project PNG's size if it has one, else what the asset declares.

    The project copy wins because it is what the user is looking at — blanking a texture they have
    been painting at 2048 should not quietly ship a 4096 one because that is the size in a header
    whose top mip the game strips (see decode_dds)."""
    for base in (project_base(game_rel), project_base_legacy(game_rel)):
        png = base + ".png"
        if os.path.exists(png):
            try:
                from PIL import Image
                with Image.open(png) as im:
                    return im.size
            except Exception:
                pass
    if work_base:
        w, h, _fmt = _tex_info(work_base)
        if w and h:
            return (w, h)
    return (1024, 1024)


def stage_inject(stage, game_rel, opts=None):
    """Stage one texture: inject the edited PNG into the vanilla .uasset via UAssetTool.
    Staged file is placed at the pak game path so create_mod_iostore packs it correctly.

    opts (from project_meta.get_asset_opts) may carry:
      blank      - ship a fully transparent texture instead of the edited PNG (#22)
      no_mips    - single inline mip instead of the full chain (#20)
      lod_group  - retarget the texture's LODGroup (#20)
      lq_twin    - also stage the Marvel_LQ copy, when this install has that mount (#21)
    """
    import atelier.asset_cache as _ac
    opts = opts or {}
    # Prefer the unique subfolder path; fall back to a legacy flat png if that's where it already lives.
    import_base = project_base(game_rel)
    if not os.path.exists(import_base + ".png") and os.path.exists(project_base_legacy(game_rel) + ".png"):
        import_base = project_base_legacy(game_rel)
    work_base   = _ac.cache_base(game_rel) or find_extracted(game_rel)
    if not work_base or not os.path.exists(work_base + ".uasset"):
        raise RuntimeError("no base asset — run 'import' first")
    blank_note = ""
    if opts.get("blank"):
        # Generated fresh into the cache, never into the project: the project PNG is the user's
        # artwork, and blanking is an EXPORT choice they can switch off again without having lost it.
        src = blank_png(project_base(game_rel, os.path.join(_CACHE, "blank")) + ".png",
                        texture_size(game_rel, work_base))
        fmt = texture_format(work_base)
        blank_note = ("blanked" if format_has_alpha(fmt)
                      else f"blanked to opaque black — {fmt or 'this format'} has no alpha channel")
    else:
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
    args = ["inject_texture", os.path.abspath(work_base + ".uasset"), os.path.abspath(src),
            os.path.abspath(out_ua), "--usmap", USMAP]
    if opts.get("no_mips"):
        args.append("--no-mips")
    r = uat(args)
    if not os.path.exists(out_ua):
        raise RuntimeError("inject failed: " + (((r.stderr or "") + (r.stdout or "")).strip()[-200:] or "unknown"))
    notes = []
    if opts.get("no_mips"):
        notes.append("no mips")
    if opts.get("lod_group"):
        # A failure here must not take the texture edit down with it: the injected asset is already
        # correct and shippable, the group is an extra the user asked for. Report, keep the texture.
        try:
            if set_texture_group(out_ua, opts["lod_group"]):
                notes.append(opts["lod_group"].replace("TEXTUREGROUP_", "group "))
        except Exception as e:
            print(f"  [warn] {game_rel}: texture group not applied: {e}", file=sys.stderr, flush=True)
            notes.append("texture group FAILED: %s" % e)
    if opts.get("lq_twin"):
        n = stage_lq_twin(stage, game_rel, out_ua)
        notes.append("+Marvel_LQ copy" if n else "no Marvel_LQ mount in these paks")
    name = os.path.basename(game_rel)
    if blank_note:
        notes.insert(0, blank_note)
    return name + (" (" + ", ".join(notes) + ")" if notes else "")


def stage_lq_twin(stage, game_rel, staged_ua):
    """Copy an already-staged asset to its Marvel_LQ path as well. Returns True if it was staged.

    norskpl's ask (#21): a client running low texture quality loads the Marvel_LQ copy, so a mod
    that only overrides the HQ one does nothing for it. The copy is the same injected bytes at the
    other mount path — the LQ asset is a lower-res twin, not a different asset, and an override
    replaces it whole.

    Returns False, and stages nothing, when the install has no Marvel_LQ mount. That is the case on
    a current install (checked on build 3870120: zero Marvel_LQ paths in any of the 21 containers),
    and staging into a mount the game does not have would only pad the mod with a path nothing ever
    looks up."""
    from atelier.index import has_lq_mount, lq_counterpart, is_lq
    if is_lq(game_rel) or not has_lq_mount():
        return False
    lq_pak = pak_game_path(lq_counterpart(game_rel))
    dst = os.path.join(stage, *lq_pak.split("/")) + ".uasset"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for ext in _WORK_EXTS:
        src = staged_ua[:-7] + ext
        if os.path.exists(src):
            shutil.copyfile(src, dst[:-7] + ext)
    return True


def build_mod(mod_name, tex_items, mat_items, out_dir, force=True, curve_items=None, vfx_items=None,
              world_items=None, text_items=None, password=None, mesh_items=None, asset_opts=None):
    """Pack texture edits (inject) + material/curve param edits + Niagara curve edits + level (world)
    edits + StringTable (text) edits + Blender mesh edits into one mod. tex_items: [game_rel];
    mat_items: [{game_rel, colors, scalars}]; curve_items: [{game_rel, edits}];
    vfx_items/world_items/text_items/mesh_items: [game_rel] (edits come from the sidecar / .blend).
    asset_opts: {game_rel: opts} per-asset export options — see project_meta.get_asset_opts."""
    from atelier.handlers.material import stage_material
    from atelier.handlers.curve import stage_curve
    from atelier.handlers.vfx import stage_vfx
    from atelier.handlers.world import stage_world
    from atelier.handlers.text import stage_text
    asset_opts = asset_opts or {}
    out_dir = os.path.abspath(out_dir); stem = f"{mod_name}_9999999_P"; base = os.path.join(out_dir, stem)
    for ext in (".pak", ".ucas", ".utoc"):
        if os.path.exists(base + ext): os.remove(base + ext)
    stage = os.path.join(_CACHE, "build_stage", mod_name)
    shutil.rmtree(os.path.join(_CACHE, "build_stage"), ignore_errors=True); os.makedirs(stage)
    applied, skipped = [], []
    # MESH FIRST, before any texture is injected. Staging a mesh runs Blender, which flushes any
    # still-modified image datablock onto the project PNGs stage_inject then reads. Injecting
    # first would ship the pre-flush version -- one build behind, looking exactly like "my
    # texture edit didn't apply".
    for gr in (mesh_items or []):
        try:
            from atelier.handlers.meshedit import stage_mesh
            info = stage_mesh(gr, stage)
            applied.append(f"mesh {os.path.basename(gr)} ({len(info['applied'])} LODs)")
        except Exception as e: skipped.append(f"{os.path.basename(gr)}: {e}")
    for game_rel in tex_items:
        try: applied.append("tex " + stage_inject(stage, game_rel, asset_opts.get(game_rel)))
        except Exception as e: skipped.append(f"{os.path.basename(game_rel)}: {e}")
    for m in mat_items:
        gr = m["game_rel"]
        try: applied.append("mat " + stage_material(stage, gr,
                                                    m.get("colors", {}), m.get("scalars", {})))
        except Exception as e: skipped.append(f"{os.path.basename(gr)}: {e}"); continue
        # "Turn the dye overlay off" ships a NEUTRAL ColorID mask beside the material, so it is a
        # second staged asset rather than a parameter on this one — see dye.stage_dye_off for why
        # there is no material parameter that does this.
        if (asset_opts.get(gr) or {}).get("dye_off"):
            try:
                from atelier.handlers.dye import stage_dye_off
                applied.append("dye-off " + stage_dye_off(stage, gr))
            except Exception as e:
                skipped.append(f"{os.path.basename(gr)}: dye overlay not disabled: {e}")
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

    print(f"  Extracting {len(game_rels)} asset(s) from game via UAssetTool...", file=sys.stderr)
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    r = uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT)] + uat_filter(game_rels))
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
            made = sorted(dir_glob(out_dir, "*_P.utoc"))
            if made:
                base = made[-1][:-5]
                print(f"Packed {staged} texture(s) -> {os.path.abspath(base)}.{{pak,ucas,utoc}}")
            else:
                print(f"retoc exit 0 but no .utoc found in {out_dir}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
