import os, re, sys, json, hashlib
from atelier.config import PAKS, _CACHE, dir_glob  # sets MR_TOOLS env var before io_lib reads it
import io_lib

_INDEX      = None
_FAILED     = []    # [{container, error}] from the most recent build — see index_warnings()
_CACHE_FILE = os.path.join(_CACHE, "cli_index_cache.json")
_CACHE_VER  = "v12"  # bump to invalidate cached indexes (v12: plugin mounts get their own root)

# Content mount prefixes we care about.  All pak formats (base and patch) embed raw utoc paths
# like ../../../Marvel/Content/Marvel/... or ../../../Marvel/Content/Marvel_LQ/... — the leading
# junk varies but Marvel/Content/Marvel[_LQ]/ is the stable anchor.  Using find() below handles
# any arbitrary prefix before that anchor without needing to enumerate all variants.
_CONTENT_PREFIXES = (
    "Marvel/Content/Marvel/",
    "Marvel/Content/Marvel_LQ/",
)
_JUNK_RE = re.compile(r"^(?:\.\./)+")

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
    root = plugin_root(mount)
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

    PLUGIN mounts (Marvel/Plugins/<Name>/Content/) are the exception: they get a 'Plugins/<Name>'
    virtual root of their own — see plugin_root() — and keep their FULL mount as the prefix so the
    path can be rebuilt. mount_join() is the inverse; nothing may concatenate the two by hand."""
    clean = raw.replace("\\", "/")
    cl = clean.lower()
    for pfx in _CONTENT_PREFIXES:
        idx = cl.find(pfx.lower())
        if idx >= 0:
            return clean[idx + len(pfx):], pfx
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
    return hit[2] if hit else "Marvel/Content/Marvel/"

def index_warnings():
    """Containers that failed to parse during the most recent index build: [{container, error}].

    A container fails almost exclusively because its directory index decrypted to garbage — i.e.
    the AES key is wrong for it — and the asset browser then silently misses everything inside it.
    The UI surfaces this so "Atelier shows nothing" is reportable instead of mysterious."""
    return list(_FAILED)


def ensure_index():
    global _INDEX, _FAILED
    if _INDEX is not None: return _INDEX
    key = _utoc_key()
    try:
        c = json.load(open(_CACHE_FILE, encoding="utf-8"))
        if c.get("key") == key:
            _INDEX = [tuple(e) for e in c["entries"]]
            _FAILED = [dict(f) for f in c.get("failed", [])]
            return _INDEX
    except Exception: pass
    utocs = _index_utocs()
    print(f"  Indexing {len(utocs)} pak containers (first run, cached after)...", file=sys.stderr)
    # Dedup by virtual path (lower-cased). Priority rules (highest wins):
    #   1. Patch paks (_P.utoc) always win — they are game updates.
    #   2. Marvel/ (HQ) beats Marvel_LQ/ for the same virtual path — prefer high-quality source.
    #   3. Within same prefix, later utoc (alphabetically) wins — chronological patch order.
    seen = {}  # virt_lower -> (virt, cont, pfx)
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
            if not p.lower().endswith(".uasset"):
                continue
            vp, pfx = _virtual_path(p)
            if vp is None:
                continue
            vp_key   = vp.lower()
            existing = seen.get(vp_key)
            if existing is not None:
                ex_pfx = existing[2]
                # HQ always beats LQ for the same virtual path.
                if ex_pfx == "Marvel/Content/Marvel/" and pfx == "Marvel/Content/Marvel_LQ/":
                    continue
            seen[vp_key] = (vp, cont, pfx)
    _INDEX  = list(seen.values())
    _FAILED = failed
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
        json.dump({"key": key, "entries": _INDEX, "failed": []}, open(_CACHE_FILE, "w"))
    return _INDEX
