import os, re, sys, json, hashlib, threading
from atelier.config import PAKS, _CACHE, dir_glob  # sets MR_TOOLS env var before io_lib reads it
import io_lib

_INDEX      = None
_INDEX_LOCK = threading.Lock()  # serialises ensure_index builds across request threads
_FAILED     = []    # [{container, error}] from the most recent build — see index_warnings()
_OPT_MIPS   = set() # virtual paths (lower, no ext) with a .uptnl available — see has_optional_mip
_CACHE_FILE = os.path.join(_CACHE, "cli_index_cache.json")
_CACHE_VER  = "v14"  # bump to invalidate cached indexes (v14: optional top mips are recorded)

# Content mount prefixes we care about.  All pak formats (base and patch) embed raw utoc paths
# like ../../../Marvel/Content/Marvel/... or ../../../Marvel/Content/Marvel_LQ/... — the leading
# junk varies but Marvel/Content/Marvel[_LQ]/ is the stable anchor.  Using find() below handles
# any arbitrary prefix before that anchor without needing to enumerate all variants.
_CONTENT_PREFIXES = (
    "Marvel/Content/Marvel/",
    "Marvel/Content/Marvel_LQ/",
)
_JUNK_RE = re.compile(r"^(?:\.\./)+")

# Marvel_LQ is a SECOND content mount holding low-quality twins of Marvel/ assets, and the two
# share subpaths exactly (UI/Textures/X exists in both). Flattening both to the browse root made
# them one virtual path, and the dedup below then kept the HQ one and dropped the LQ one — so an
# LQ asset was unreachable whenever its HQ twin existed, which is every one of them. That is
# fawnls' missing "Marvel_LQ" node (2026-08-22), and it is the same collision the MarvelGAS plugin
# mount hit; the fix is the same fix — give it its own synthetic root and keep the full mount as
# the reconstruction prefix.
_LQ_PREFIX = "Marvel/Content/Marvel_LQ/"
_LQ_ROOT   = "Marvel_LQ"

def plugin_root(mount):
    """'Marvel/Plugins/MarvelGAS/Content/' -> 'Plugins/MarvelGAS'; '' for any non-plugin mount.

    A plugin mounts at its OWN root in the engine, so its content must not be flattened into the
    main tree the way Engine/Content is. MarvelGAS ships 'UI/Common/Textures/AbilityIcon' and so
    does Marvel/Content/Marvel — as bare subpaths the two are the same virtual path, so the dedup
    in ensure_index() silently kept whichever container it read last, and the loser's assets were
    simply absent. That is how the team-up ability icons ended up unreachable (wendall555,
    shafsta) and why the ones that did show up answered to a different path than FModel's."""
    parts = mount.strip("/").split("/")
    if len(parts) >= 3 and parts[-1].lower() == "content" and parts[-3].lower() == "plugins":
        return "Plugins/" + parts[-2]
    return ""

def virtual_root(mount):
    """The synthetic browse root this mount's content is filed under, '' when it mounts at the root.

    Two mounts get one: a plugin ('Plugins/<Name>', see plugin_root) and Marvel_LQ. Both name the
    MOUNT rather than a folder inside it, so mount_join has to take them back off before joining —
    nothing may concatenate a virtual path onto a prefix by hand."""
    if mount == _LQ_PREFIX:
        return _LQ_ROOT
    return plugin_root(mount)


def is_lq(game_rel):
    """True for a virtual path under the Marvel_LQ mount."""
    gr = (game_rel or "").replace("\\", "/")
    return gr.lower() == _LQ_ROOT.lower() or gr.lower().startswith(_LQ_ROOT.lower() + "/")


def lq_counterpart(game_rel):
    """The Marvel_LQ twin of an HQ virtual path (or the HQ twin of an LQ one). Pure string work —
    it says nothing about whether that asset exists; ask the index for that."""
    gr = (game_rel or "").replace("\\", "/")
    if is_lq(gr):
        return gr[len(_LQ_ROOT) + 1:]
    return _LQ_ROOT + "/" + gr if gr else gr


def split_plugin_root(game_rel):
    """('Plugins/MarvelGAS', 'UI/...') for a plugin virtual path, else ('', game_rel)."""
    gr = (game_rel or "").replace("\\", "/")
    parts = gr.split("/")
    if len(parts) >= 3 and parts[0].lower() == "plugins":
        return "/".join(parts[:2]), "/".join(parts[2:])
    return "", gr

def mount_join(mount, game_rel):
    """mount + virtual path -> the real content-mount path, undoing plugin_root()'s synthetic root.

    Plain concatenation is wrong for plugins: the synthetic root ('Plugins/MarvelGAS') names the
    mount, it is not a folder inside it, so joining it blindly produces
    'Marvel/Plugins/MarvelGAS/Content/Plugins/MarvelGAS/UI/...' — a path that exists nowhere, and a
    mod staged there overrides nothing (the same trap text.py's full_pak_path already documents)."""
    root = virtual_root(mount)
    gr = (game_rel or "").replace("\\", "/")
    if root and gr.lower().startswith(root.lower() + "/"):
        gr = gr[len(root) + 1:]
    return mount.rstrip("/") + "/" + gr

def _virtual_path(raw):
    """Find the content-mount anchor anywhere in the raw path; return (virtual_rel_path, content_prefix) or (None, None).
    Using find() instead of startswith-after-strip handles any leading junk (../../, ent/, etc.).

    Marvel[_LQ] game content mounts at the browse ROOT (Characters/..., Textures/...). ANY other mount
    (Engine/Content/EngineSky/T_Sky_Stars, Engine/Content/MapTemplates/..., etc.) is indexed too — its
    subpath after '/Content/' becomes the virtual path (MapTemplates/Sky/T_Sky_Stars) and its mount
    ('Engine/Content/') is the reconstruction prefix, so pfx+virtual still rebuilds the real pak path
    and the top folder shows up as a browsable/searchable section.

    Marvel_LQ and PLUGIN mounts (Marvel/Plugins/<Name>/Content/) are the exceptions: they get a
    virtual root of their own ('Marvel_LQ', 'Plugins/<Name>' — see virtual_root()) and keep their
    FULL mount as the prefix so the path can be rebuilt. mount_join() is the inverse; nothing may
    concatenate the two by hand."""
    clean = raw.replace("\\", "/")
    cl = clean.lower()
    for pfx in _CONTENT_PREFIXES:
        idx = cl.find(pfx.lower())
        if idx >= 0:
            sub = clean[idx + len(pfx):]
            return ((_LQ_ROOT + "/" + sub) if pfx == _LQ_PREFIX else sub), pfx
    ci = cl.find("/content/")
    if ci >= 0:
        # The FULL mount, not just its last folder: 'MarvelGAS/Content/' loses the 'Marvel/Plugins/'
        # it lives under, and every path rebuilt from it points nowhere.
        mount = _JUNK_RE.sub("", clean[:ci].lstrip("/")) + "/Content/"
        sub   = clean[ci + len("/content/"):]         # subpath after /Content/
        root  = plugin_root(mount)
        return ((root + "/" + sub) if root else sub), mount
    return None, None

def _index_utocs():
    # Ascending ASCII/Unicode order (case-insensitive): '-' (45) before '_' (95), so base paks
    # (pakchunkFoo-Windows) sort before patch paks (Patch_-Windows_YYYYMMDD_P), and patch paks
    # sort chronologically.  Later entries override earlier ones for the same virtual path.
    # dir_glob, not glob: PAKS is user-supplied and a library under D:/[Steam]/... would otherwise
    # match zero containers and index nothing, silently.
    return sorted(dir_glob(PAKS, "*.utoc"), key=lambda p: os.path.basename(p).lower())

def _aes_fingerprint():
    """Identifies the key an index was built under, without writing the key itself into the cache.
    Read live from io_lib (not captured at import) because config.set_aes_key rewrites it in place."""
    return hashlib.sha256(io_lib.AES_KEY or b"").hexdigest()[:16]

def _utoc_key():
    """Cache identity for a built index: the containers it was built FROM and the key it was built
    WITH.  The key half is the whole point — an index built with a wrong AES key is empty or
    partial, and without it that empty index was served back forever because the paks themselves
    never changed.  Correcting the key in Setup therefore did nothing and only a reinstall (which
    wipes _cache wholesale) appeared to help."""
    parts = [_CACHE_VER, "aes:" + _aes_fingerprint()]
    for f in _index_utocs():
        s = os.stat(f)
        parts.append(f"{os.path.basename(f)}:{s.st_size}:{int(s.st_mtime)}")
    return "|".join(parts)

_LOOKUP = None          # virt_lower -> (virt, container, pfx), rebuilt when _INDEX is replaced
_LOOKUP_FOR = None


def index_lookup():
    """The index keyed by lower-cased virtual path.

    ensure_index() returns a ~550k-entry LIST, and the per-asset resolvers scan it linearly. One
    scan per asset was tolerable; the patch-layout work needs several per asset, and a bulk import
    is hundreds of assets — that product is what turns a quadratic into a stall. Built once per
    index and handed out thereafter.
    """
    global _LOOKUP, _LOOKUP_FOR
    idx = ensure_index()
    if _LOOKUP is None or _LOOKUP_FOR is not idx:
        _LOOKUP = {vp.lower(): (vp, cont, pfx) for vp, cont, pfx in idx}   # later entries win
        _LOOKUP_FOR = idx
    return _LOOKUP


def get_content_prefix(game_rel):
    """Return the content mount prefix for a virtual game_rel (used to reconstruct full pak paths).
    Falls back to the primary HQ prefix for assets not in the index."""
    gr = game_rel.lower()
    if not gr.endswith(".uasset"):
        gr += ".uasset"
    hit = index_lookup().get(gr)
    if hit:
        return hit[2]
    # Not indexed. The fallback still has to respect the synthetic root, or an LQ path rebuilds
    # against the HQ mount and the staged mod overrides the wrong asset (silently, as always).
    return _LQ_PREFIX if is_lq(game_rel) else "Marvel/Content/Marvel/"

def index_warnings():
    """Containers that failed to parse during the most recent index build: [{container, error}].

    A container fails almost exclusively because its directory index decrypted to garbage — i.e.
    the AES key is wrong for it — and the asset browser then silently misses everything inside it.
    The UI surfaces this so "Atelier shows nothing" is reportable instead of mysterious."""
    return list(_FAILED)


def ensure_index():
    global _INDEX, _FAILED, _OPT_MIPS
    # Fast path without the lock: once built, _INDEX is only ever replaced wholesale.
    if _INDEX is not None: return _INDEX
    with _INDEX_LOCK:
        # Re-check under the lock. _INDEX is not assigned until the whole walk below finishes,
        # so without this a second request arriving during a build (the threaded server runs
        # each one in its own thread) sees None and redundantly indexes every container again.
        if _INDEX is not None: return _INDEX
        key = _utoc_key()
        try:
            c = json.load(open(_CACHE_FILE, encoding="utf-8"))
            if c.get("key") == key:
                _INDEX = [tuple(e) for e in c["entries"]]
                _FAILED = [dict(f) for f in c.get("failed", [])]
                _OPT_MIPS = set(c.get("optional_mips") or [])
                return _INDEX
        except Exception: pass
        utocs = _index_utocs()
        print(f"  Indexing {len(utocs)} pak containers (first run, cached after)...", file=sys.stderr)
        # Dedup by virtual path (lower-cased). Priority rules (highest wins):
        #   1. Patch paks (_P.utoc) always win — they are game updates.
        #   2. Within same prefix, later utoc (alphabetically) wins — chronological patch order.
        # There is deliberately NO "HQ beats LQ" rule any more: Marvel_LQ now carries its own virtual
        # root, so an HQ asset and its LQ twin are two different paths and neither can evict the other.
        # The old rule was the reason the LQ mount was invisible even where the game shipped one.
        seen = {}  # virt_lower -> (virt, cont, pfx)
        opt_mips = set()
        failed = []
        for utoc in utocs:
            t = None
            try:
                t    = io_lib.parse_toc(utoc)
                ents = io_lib.parse_dir_index(t)
            except Exception as e:
                print(f"  [warn] {os.path.basename(utoc)}: {e}", file=sys.stderr)
                # enc_guid identifies WHICH key a container wants. Recording it on every failure means
                # a patch pak shipped under a second key shows up as a distinct non-zero guid in the
                # warning list instead of having to be re-derived from scratch (PHASES.md #2).
                failed.append({"container": os.path.basename(utoc), "error": str(e),
                               "encrypted": bool(t.encrypted) if t is not None else None,
                               "enc_guid":  t.enc_guid.hex() if t is not None else ""})
                continue
            cont     = os.path.basename(utoc)
            is_patch = cont.lower().endswith("_p.utoc")
            for p, _ in ents:
                pl = p.lower()
                if pl.endswith(".uptnl"):
                    # The HQ texture DLC ships as pakchunk<X>optional-Windows containers holding
                    # NOTHING but .uptnl files — the top mip of textures whose .uasset stays in the
                    # ordinary chunk. Recording which assets have one is what lets ensure_work_base
                    # tell a work-cache copy extracted before the DLC from one extracted after: the
                    # .uasset's container never changes, so nothing else can see the difference.
                    # Free here, because this loop already walks every entry of every container.
                    vp, _pfx = _virtual_path(p[:-6] + ".uasset")
                    if vp is not None:
                        opt_mips.add(vp[:-7].lower())
                    continue
                if not pl.endswith(".uasset"):
                    continue
                vp, pfx = _virtual_path(p)
                if vp is None:
                    continue
                seen[vp.lower()] = (vp, cont, pfx)
        _INDEX    = list(seen.values())
        _FAILED   = failed
        _OPT_MIPS = opt_mips
        # Only persist a CLEAN index. A build where containers failed is usually a wrong/stale AES key,
        # and the cache key (_utoc_key) covers only the .utoc files — so caching that result pins the
        # damage until the paks change or _cache is wiped, which is why "reinstall it" was the only
        # cure. Leaving it uncached costs one re-index per launch and lets fixing the key recover.
        if failed:
            print(f"  [warn] {len(failed)} of {len(utocs)} containers failed to index — "
                  f"not caching this build", file=sys.stderr)
            try:
                if os.path.exists(_CACHE_FILE): os.remove(_CACHE_FILE)
            except OSError: pass
        else:
            os.makedirs(_CACHE, exist_ok=True)
            json.dump({"key": key, "entries": _INDEX, "failed": [],
                       "optional_mips": sorted(_OPT_MIPS)}, open(_CACHE_FILE, "w"))
        return _INDEX


_MOUNTS = None          # {prefix: count}, rebuilt when _INDEX is replaced — see index_lookup
_MOUNTS_FOR = None


def content_mounts():
    """{mount_prefix: asset_count} for every content mount the index actually read.

    "More asset roots (UI/Textures, Marvel_LQ)" was answered with "it should be fixed now" and then
    reopened by fawnls, who still had no Marvel_LQ — and there was no way to tell whether the root
    was hidden by a bug or simply not in his install. This makes that a fact the app can state.

    Cached against the index it was counted from, for the same reason index_lookup is: this is a
    full scan of ~550k entries, and has_lq_mount() below is asked once per staged texture during an
    export. One scan per index, not one per asset.
    """
    global _MOUNTS, _MOUNTS_FOR
    idx = ensure_index()
    if _MOUNTS is None or _MOUNTS_FOR is not idx:
        counts = {}
        for _vp, _cont, pfx in idx:
            counts[pfx] = counts.get(pfx, 0) + 1
        _MOUNTS, _MOUNTS_FOR = counts, idx
    return dict(_MOUNTS)


def has_lq_mount():
    """Whether THIS install ships the Marvel_LQ content mount at all.

    Checked on a full Season 10 install (build 3870120, 21 containers): it does not — zero paths
    anywhere contain Marvel_LQ. Anything that duplicates an asset into that mount therefore has to
    ask first and do nothing when the answer is no, rather than staging a path the game will never
    look up (texture.stage_lq_twin)."""
    return _LQ_PREFIX in content_mounts()


def optional_mips():
    """The set of virtual paths (lower-cased, no extension) that have a .uptnl in the paks."""
    ensure_index()
    return _OPT_MIPS


def has_optional_mip(game_rel):
    """Whether the paks currently offer a separate top mip for this texture.

    True only while the HQ texture DLC is installed. Uninstalling it makes this False again, which
    is the correct answer: a cached copy that still HAS the top mip is better than what the paks
    can now provide, and nothing should throw it away.
    """
    gr = (game_rel or "").replace("\\", "/")
    if gr.lower().endswith(".uasset"):
        gr = gr[:-7]
    return gr.lower() in optional_mips()
