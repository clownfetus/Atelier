import os, sys, glob, re, json, fnmatch, threading
from atelier import hostos as _hostos

ROOT        = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
               else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = os.path.join(ROOT, "mr_config.json")

def _load_config():
    try: return json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: return {}

_cfg_lock = threading.Lock()

def _save_config(**updates):
    """Read-modify-write CONFIG_FILE under a lock; a value of None removes the key.

    Every config write goes through here. _auto_fetch_aes runs on a background thread, so two
    read-modify-write cycles overlapping would drop whichever landed first, and a crash mid-dump
    left an unparseable config that _load_config silently read back as {} -- i.e. as a fresh
    install. The temp file plus os.replace makes the swap atomic."""
    with _cfg_lock:
        cfg = _load_config()
        for k, v in updates.items():
            if v is None: cfg.pop(k, None)
            else:         cfg[k] = v
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
        return cfg

def dir_glob(directory, pattern, recursive=False):
    """glob `pattern` inside `directory`, with the directory half escaped and the pattern left live.

    Nearly every path this app globs is user-controlled somewhere upstream: the game's Paks folder,
    the install root, a mod name. `[` and `]` are glob metacharacters AND legal in Windows
    filenames, so a Steam library at D:/[Steam]/... turns `glob(PAKS + "/*.utoc")` into a character
    class that matches nothing -- zero containers found, an empty asset browser, and no error
    anywhere saying so. Escaping only the directory keeps both halves meaning what they say."""
    return glob.glob(os.path.join(glob.escape(directory), pattern), recursive=recursive)

def has_pak_files(directory):
    """True when `directory` holds at least one vanilla pak container. THE answer to "is this a
    paks folder" -- Setup and the prereq check must never disagree about it again.

    They used to: Setup tested for a literal pakchunkCharacter-Windows.ucas while _prereq_issues()
    globbed pakchunk*.utoc, so on a bracketed path one said the folder was valid and the other said
    "No pak files found". scandir + fnmatchcase has no metacharacter surface at all, so the answer
    cannot depend on how the path happens to be spelled."""
    try:
        with os.scandir(directory) as it:
            return any(e.is_file() and fnmatch.fnmatchcase(e.name.lower(), "pakchunk*.utoc")
                       for e in it)
    except OSError:
        return False

_PAKS_SUFFIX = "/steamapps/common/MarvelRivals/MarvelGame/Marvel/Content/Paks"

def _steam_roots():
    """Steam install roots to search, most likely first. The Windows list is the historical one;
    on Linux the game runs under Proton but its files still live in a normal Steam library, so
    the same libraryfolders.vdf walk applies — only the roots differ."""
    if os.name == "nt":
        return [r"C:/Program Files (x86)/Steam", r"C:/Program Files/Steam"]
    home = os.path.expanduser("~")
    return [os.path.join(home, ".local/share/Steam"),
            os.path.join(home, ".steam/steam"),
            os.path.join(home, ".steam/root"),
            os.path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),  # flatpak
            os.path.join(home, "snap/steam/common/.local/share/Steam")]

def _build_paks_candidates():
    roots = _steam_roots()
    cands = [roots[0] + _PAKS_SUFFIX]
    for root in roots:
        try:
            vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
            for m in re.finditer(r'"path"\s*"([^"]+)"',
                                 open(vdf, encoding="utf-8", errors="ignore").read()):
                lib = m.group(1).replace("\\\\", "/").replace("\\", "/")
                cands.append(lib + _PAKS_SUFFIX)
        except Exception: pass
    return cands

def _detect_paks():
    cands = _build_paks_candidates()
    for c in cands:
        if has_pak_files(c): return c
    return cands[0]

def paks_suggestion():
    """Return the auto-detected valid paks path, or empty string if not found."""
    for c in _build_paks_candidates():
        if has_pak_files(c):
            return c
    return ""

def save_paks_config(paks_path):
    _save_config(paks=paks_path.replace("\\", "/"))

def save_setup_config(paks_path, aes_key, usmap_path=None):
    """Save paks path, AES key (without 0x prefix), and optionally USMAP path together.

    The key is recorded here but WRITTEN by set_aes_key() -- see its docstring for why there is
    exactly one writer for Tools/AES_KEY.txt."""
    updates = {"paks": paks_path.replace("\\", "/"), "aes_key": aes_key}
    if usmap_path is not None:
        updates["usmap"] = usmap_path.replace("\\", "/")
    _save_config(**updates)

def save_usmap_config(usmap_path):
    _save_config(usmap=usmap_path.replace("\\", "/"))

def get_usmap_checked_at():
    return _load_config().get("usmap_checked_at", 0)

def save_usmap_checked_at(ts):
    _save_config(usmap_checked_at=ts)

_cfg            = _load_config()
CONFIG_HAS_PAKS = bool(_cfg.get("paks"))
TOOLS = _cfg.get("tools") or os.path.join(ROOT, "Tools")
AES_KEY_FILE = os.path.join(TOOLS, "AES_KEY.txt")  # written ONLY by set_aes_key()

def _unblock_bundled_tools():
    """Strip the Mark-of-the-Web (:Zone.Identifier ADS) from bundled tools so .NET/Oodle will load
    them. Windows tags every file extracted from a downloaded .zip as 'came from another computer';
    .NET then refuses to load those assemblies (UAssetTool / AtelierMesh / retoc bootstrap errors)
    and SmartScreen warns harder. Run FIRST — before MR_TOOLS / io_lib / any native DLL load."""
    if os.name != "nt":
        return
    try:
        for base in (ROOT, TOOLS):
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.lower().endswith((".exe", ".dll", ".pyd")):
                        try:
                            os.remove(os.path.join(root, f) + ":Zone.Identifier")
                        except OSError:
                            pass  # no ADS on this file — fine
    except Exception:
        pass

if getattr(sys, "frozen", False):
    _unblock_bundled_tools()   # BEFORE MR_TOOLS / io_lib so the Oodle & .NET DLLs load un-tainted

PAKS  = (_cfg.get("paks") or _detect_paks()).replace("\\", "/")
os.environ["MR_TOOLS"] = TOOLS  # must be set before io_lib is imported anywhere


def _auto_fetch_aes():
    """Best-effort background fetch of the current MR AES key from the community depot, so a key
    rotation is handled without a config edit or app rebuild. Goes through set_aes_key(), so the
    fetched key reaches Tools/AES_KEY.txt (read by UAssetTool), io_lib and the saved config in one
    step -- a rotation used to reach only the file, and the stale saved key then clobbered it on
    the next launch. The key has been stable since launch; this is a safety net. Never blocks startup."""
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/SpaceDepot/rivals-depot/refs/heads/main/AES.json",
            headers={"User-Agent": "Atelier/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.loads(r.read().decode("utf-8", "replace"))
        # Only mainKey is read. Per-container keys published alongside it (enc_guid -> key) are a
        # separate piece of work — see PHASES.md #2.
        if set_aes_key(str(data.get("mainKey", "")).strip()):
            print("  [aes] key rotated — updated from the depot, re-indexing", file=sys.stderr)
    except Exception:
        pass


def get_aes_key():
    """Current AES key (no 0x prefix), for passing to retoc via -a so a key rotation needs no
    rebuild. Returns "" if AES_KEY.txt is missing — callers are only reachable once
    _prereq_issues() has confirmed the file exists."""
    try:
        k = open(AES_KEY_FILE, encoding="utf-8").read().strip()
        return k[2:] if k[:2].lower() == "0x" else k
    except Exception:
        return ""


def normalize_aes_key(key):
    """A 64-hex-char key without the 0x prefix. Raises ValueError on anything else."""
    key = (key or "").strip()
    if key[:2].lower() == "0x":
        key = key[2:]
    if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
        raise ValueError("AES key must be 64 hexadecimal characters (an optional 0x prefix is fine)")
    return key


def invalidate_index():
    """Drop the in-memory asset index so the next browse rebuilds it.

    The DISK cache needs no explicit purge: index._utoc_key() now folds in a fingerprint of the
    AES key, so a cache built under a different key can never be served back. That is the whole
    reason entering the correct key in Setup used to do nothing — the rebuild was forced, then
    immediately satisfied from a disk cache whose key covered only the .utoc files."""
    idx = sys.modules.get("atelier.index")
    if idx is not None:
        idx._INDEX = None


def set_aes_key(key, persist=True):
    """THE writer for Tools/AES_KEY.txt. Returns True if the key actually changed.

    There used to be three: the startup write from config, the background depot fetch, and Setup's
    save handler — none of them agreeing on who won. A stale saved key overwrote a freshly fetched
    one on every launch, and a fetch landing after io_lib's import left io_lib and UAssetTool
    (which reads the file) decrypting with DIFFERENT keys inside one session. Routing every write
    through here keeps the file, io_lib.AES_KEY, the saved config and the asset index consistent by
    construction. persist=False records nothing in the config — used for the startup write, where
    the config IS the source.

    Raises ValueError if the key isn't 64 hex chars, so a typo in Setup is reported as a typo
    instead of being written out and resurfacing later as an empty asset browser."""
    key     = normalize_aes_key(key)
    changed = get_aes_key().lower() != key.lower()
    os.makedirs(TOOLS, exist_ok=True)
    with open(AES_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    if persist:
        _save_config(aes_key=key)
    # io_lib reads the file exactly once, at import. Without this assignment an in-session key
    # change reaches UAssetTool but not our own pak reader.
    try:
        import io_lib
        io_lib.AES_KEY = bytes.fromhex(key)
    except Exception:
        pass
    if changed:
        invalidate_index()
    return changed


# Startup, in a defined order. The saved key goes in FIRST and synchronously, so io_lib (imported
# right after this module) and UAssetTool agree from the very first pak read. The depot fetch is
# started after: it is the only source that knows about a rotation, and because set_aes_key()
# persists it, what it finds survives the next launch instead of being clobbered by the old key.
_aes_key_cfg = _cfg.get("aes_key", "").strip()
if _aes_key_cfg:
    try:
        set_aes_key(_aes_key_cfg, persist=False)
    except Exception:
        pass   # an unusable saved key surfaces through _prereq_issues(), not as an import crash

if getattr(sys, "frozen", False):
    threading.Thread(target=_auto_fetch_aes, daemon=True).start()

def _usmap_build(p):
    """Build number from a usmap filename (5.3.2-3684529+++… → 3684529), or -1 if it has none."""
    m = re.search(r"-(\d{6,})", os.path.basename(p))
    return int(m.group(1)) if m else -1

# Mappings are NEVER bundled with the installer — they are game-derived data and shipping them is a
# copyright risk. Tools/Mappings is therefore empty on a fresh install and every .usmap in it got
# there remotely: Setup pulls the newest from GitHub (routes.api_download_usmap) and the 3-day
# check keeps it current, re-pinning cfg["usmap"] each time it fetches a newer one.
#
# That is also why the configured path can simply win here. The pin only ever goes stale if some
# NEWER usmap appears that the downloader didn't place — which used to happen when the installer
# shipped its own copies, and meant a pinned path shadowed them forever. With nothing bundled,
# there is no such source, so no ranking against the pin is needed.
_usmap_cfg = _cfg.get("usmap", "").strip()
if _usmap_cfg and os.path.exists(_usmap_cfg):
    USMAP = _usmap_cfg
else:
    # Fallback when the pin is unset or dangling. Rank by build number, never by filename —
    # alphabetical sort picks the older build, and parsing a fresh season with old mappings makes
    # UAssetTool fail to deserialize PostProcessSettings and base64-dump the PPV (slow + unusable).
    _usmaps = [u for u in dir_glob(os.path.join(TOOLS, "Mappings"), "*.usmap")
               if "_latest" not in os.path.basename(u).lower()]
    # "" is the correct answer for a fresh install: _prereq_issues() turns it into the Setup
    # error that drives the user to the download button.
    USMAP = max(_usmaps, key=_usmap_build) if _usmaps else ""
from atelier.hostos import CNW  # noqa: E402  (re-exported: many modules import it from config)

ASSETS           = os.path.join(ROOT, "assets")
IMPORT_ROOT      = os.path.join(ROOT, "assets", "imported")
PROJECTS_ROOT    = os.path.join(ROOT, "assets", "projects")
ASSETS_MODS      = os.path.join(ROOT, "assets", "exported")
_CACHE           = os.path.join(ROOT, "_cache")
WORK_IMPORT_ROOT = os.path.join(_CACHE, "import")
CACHE_3DVIEW     = os.path.join(_CACHE, "3dview")  # material jsons + texture pngs for viewport-only reads
GUI_DIR     = os.path.join(getattr(sys, "_MEIPASS", ROOT), "gui")
# Bundled data, NOT user data: frozen it lands in _internal/ alongside gui/, not next to the exe.
# Reading it as ROOT/version silently failed in every packaged build, so the update check bailed
# out early and no user was ever offered an in-app update.
VERSION_FILE = os.path.join(getattr(sys, "_MEIPASS", ROOT), "version")

_active_project = _cfg.get("active_project", "")

def get_import_root():
    global _active_project
    if _active_project:
        return os.path.join(PROJECTS_ROOT, _active_project)
    return IMPORT_ROOT

def project_base(game_rel, root=None):
    """Unique on-disk stem (no extension) for a project asset. Mirrors the game_rel's folder path as
    subfolders so two assets that share a basename (e.g. same-named materials under different skins)
    never collide — the old flat basename layout silently overwrote them. Legacy flat files are still
    read via project_base_legacy() for back-compat."""
    return os.path.join(root or get_import_root(), *game_rel.replace("\\", "/").split("/"))

def project_base_legacy(game_rel, root=None):
    """The old flat layout: <import_root>/<basename>. Kept only so pre-existing projects still load."""
    return os.path.join(root or get_import_root(), os.path.basename(game_rel.replace("\\", "/")))

def project_game_rel(path, root=None):
    """Reverse of project_base: a project file path -> its game_rel (relative subfolder path, no ext)."""
    rel = os.path.relpath(path, root or get_import_root()).replace("\\", "/")
    return rel.rsplit(".", 1)[0] if "." in os.path.basename(rel) else rel

def get_active_project():
    global _active_project
    return _active_project

def set_active_project(name):
    global _active_project
    _active_project = name
    cfg = _load_config()
    if name:
        cfg["active_project"] = name
    else:
        cfg.pop("active_project", None)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def get_mods_folder():
    """The folder mods are installed into when 'Copy to %s/' is on (the game's ~mods dir, which can
    be named anything). Empty string when unset — copy-on-install is gated on this being configured.
    Read fresh from disk each call so edits in Settings take effect without a restart."""
    return (_load_config().get("mods_folder", "") or "").replace("\\", "/")

def save_mods_folder(path):
    cfg = _load_config()
    if path:
        cfg["mods_folder"] = path.replace("\\", "/")
    else:
        cfg.pop("mods_folder", None)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def get_blender_path():
    """User-configured blender.exe path from Settings, empty string when unset (falls back to
    ATELIER_BLENDER / auto-detection — see atelier.handlers.meshedit.find_blender).
    Read fresh from disk each call so edits in Settings take effect without a restart."""
    return (_load_config().get("blender_path", "") or "").replace("\\", "/")

def save_blender_path(path):
    cfg = _load_config()
    if path:
        cfg["blender_path"] = path.replace("\\", "/")
    else:
        cfg.pop("blender_path", None)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def get_export_password():
    """The default 'Protection Password' set in Settings, used when Password Protect is toggled
    on for Install Mod. Read fresh from disk so edits in Settings take effect without a restart."""
    return _load_config().get("export_password", "") or ""

def save_export_password(password):
    cfg = _load_config()
    if password:
        cfg["export_password"] = password
    else:
        cfg.pop("export_password", None)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def _prereq_issues(need_tool=True):
    issues = []
    if not has_pak_files(PAKS):
        issues.append(("error", f"No pak files found at: {PAKS}"))
    if not os.path.exists(AES_KEY_FILE):
        issues.append(("error", f"AES_KEY.txt not found at: {AES_KEY_FILE}"))
    if need_tool and not os.path.exists(os.path.join(TOOLS, "UAssetTool.exe")):
        issues.append(("error", f"UAssetTool.exe not found at: {os.path.join(TOOLS, 'UAssetTool.exe')}"))
    if need_tool:
        level, msg = _hostos.tools_ready()
        if level != "ok":
            issues.append((level, msg))
    if need_tool and not USMAP:
        issues.append(("error", f"No .usmap mapping file found in: {os.path.join(TOOLS, 'Mappings')}"))
    if not os.path.exists(os.path.join(TOOLS, "MarvelRivalsCharacterIDs.md")):
        issues.append(("warning", "MarvelRivalsCharacterIDs.md not found — character names will show as IDs"))
    return issues

def check_prereqs(need_tool=True):
    errors = [msg for level, msg in _prereq_issues(need_tool) if level == "error"]
    if errors:
        raise RuntimeError("\n".join(errors))

def get_prereq_status():
    issues = _prereq_issues(need_tool=True)
    # Containers that failed to read are reported here too. Never force a build — if the index
    # has not been built yet this is simply empty, and the browse path reports it instead.
    try:
        import atelier.index as _idx
        for f in _idx.index_warnings():
            issues.append(("warning",
                           f"Pak container {f['container']} could not be read ({f['error']}). "
                           f"Assets inside it are missing from the browser — usually a wrong or "
                           f"stale AES key."))
    except Exception:
        pass
    return {
        "ok":     not any(level == "error" for level, _ in issues),
        "issues": [{"level": level, "message": msg} for level, msg in issues],
    }
