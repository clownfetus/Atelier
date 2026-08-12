import os, sys, glob, re, json

ROOT        = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
               else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = os.path.join(ROOT, "mr_config.json")

def _load_config():
    try: return json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: return {}

def _build_paks_candidates():
    cands = [r"C:/Program Files (x86)/Steam/steamapps/common/MarvelRivals/MarvelGame/Marvel/Content/Paks"]
    for vdf in (r"C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
                r"C:/Program Files/Steam/steamapps/libraryfolders.vdf"):
        try:
            for m in re.finditer(r'"path"\s*"([^"]+)"',
                                 open(vdf, encoding="utf-8", errors="ignore").read()):
                lib = m.group(1).replace("\\\\", "/").replace("\\", "/")
                cands.append(lib + "/steamapps/common/MarvelRivals/MarvelGame/Marvel/Content/Paks")
        except Exception: pass
    return cands

def _detect_paks():
    cands = _build_paks_candidates()
    for c in cands:
        if os.path.isdir(c) and glob.glob(c + "/pakchunk*.utoc"): return c
    return cands[0]

def paks_suggestion():
    """Return the auto-detected valid paks path, or empty string if not found."""
    for c in _build_paks_candidates():
        if os.path.isdir(c) and glob.glob(c + "/pakchunk*.utoc"):
            return c
    return ""

def save_paks_config(paks_path):
    cfg = {}
    try: cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: pass
    cfg["paks"] = paks_path.replace("\\", "/")
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def save_setup_config(paks_path, aes_key, usmap_path=None):
    """Save paks path, AES key (without 0x prefix), and optionally USMAP path together."""
    cfg = {}
    try: cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: pass
    cfg["paks"]    = paks_path.replace("\\", "/")
    cfg["aes_key"] = aes_key
    if usmap_path is not None:
        cfg["usmap"] = usmap_path.replace("\\", "/")
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def save_usmap_config(usmap_path):
    cfg = {}
    try: cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: pass
    cfg["usmap"] = usmap_path.replace("\\", "/")
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def get_usmap_checked_at():
    return _load_config().get("usmap_checked_at", 0)

def save_usmap_checked_at(ts):
    cfg = {}
    try: cfg = json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception: pass
    cfg["usmap_checked_at"] = ts
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

_cfg            = _load_config()
CONFIG_HAS_PAKS = bool(_cfg.get("paks"))
TOOLS = _cfg.get("tools") or os.path.join(ROOT, "Tools")

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
    rotation is handled without a config edit or app rebuild. Updates Tools/AES_KEY.txt (read by
    io_lib + UAssetTool); retoc calls should pass get_aes_key() via -a for full coverage. The key
    has been stable since launch — this is a safety net for the rare rotation. Never blocks startup."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/SpaceDepot/rivals-depot/main/AES",
            headers={"User-Agent": "Atelier/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            key = r.read().decode("utf-8", "replace").strip()
        if key[:2].lower() == "0x":
            key = key[2:]
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            kf = os.path.join(TOOLS, "AES_KEY.txt")
            try:
                cur = open(kf, encoding="utf-8").read().strip()
            except Exception:
                cur = ""
            if cur.lower() != key.lower():
                os.makedirs(TOOLS, exist_ok=True)
                with open(kf, "w", encoding="utf-8") as _f:
                    _f.write(key)
    except Exception:
        pass


_DEFAULT_AES = "0C263D8C22DCB085894899C3A3796383E9BF9DE0CBFB08C9BF2DEF2E84F29D74"

def get_aes_key():
    """Current AES key (no 0x prefix), for passing to retoc via -a so a key rotation needs no
    rebuild. Falls back to the long-stable default if AES_KEY.txt is missing."""
    try:
        k = open(os.path.join(TOOLS, "AES_KEY.txt"), encoding="utf-8").read().strip()
        return (k[2:] if k[:2].lower() == "0x" else k) or _DEFAULT_AES
    except Exception:
        return _DEFAULT_AES


# Packaged app: keep the AES key current (patch-resilience). Tools are un-tainted earlier (before
# any DLL load) via _unblock_bundled_tools() right after TOOLS is defined.
if getattr(sys, "frozen", False):
    import threading as _threading
    _threading.Thread(target=_auto_fetch_aes, daemon=True).start()

# Write AES_KEY.txt from config on startup so UAssetTool can read it
_aes_key_cfg = _cfg.get("aes_key", "").strip()
if _aes_key_cfg:
    try:
        os.makedirs(TOOLS, exist_ok=True)
        with open(os.path.join(TOOLS, "AES_KEY.txt"), "w", encoding="utf-8") as _f:
            _f.write(_aes_key_cfg)
    except Exception: pass

_usmap_cfg = _cfg.get("usmap", "").strip()
if _usmap_cfg and os.path.exists(_usmap_cfg):
    USMAP = _usmap_cfg
else:
    # Pick the NEWEST usmap by build number (e.g. 5.3.2-3684529 = S9.0 beats 3656487 = S8.5).
    # Alphabetical sort picked the older build, so a fresh S9.0 game got parsed with S8.5 mappings
    # → UAssetTool couldn't deserialize PostProcessSettings and base64-dumped the PPV (slow + unusable).
    _usmaps = [u for u in glob.glob(os.path.join(TOOLS, "Mappings", "*.usmap"))
               if "_latest" not in os.path.basename(u).lower()]
    def _usmap_build(p):
        m = re.search(r"-(\d{6,})", os.path.basename(p))
        return int(m.group(1)) if m else -1
    USMAP = max(_usmaps, key=_usmap_build) if _usmaps else ""
CNW     = 0x08000000 if os.name == "nt" else 0

ASSETS           = os.path.join(ROOT, "assets")
IMPORT_ROOT      = os.path.join(ROOT, "assets", "imported")
PROJECTS_ROOT    = os.path.join(ROOT, "assets", "projects")
ASSETS_MODS      = os.path.join(ROOT, "assets", "exported")
_CACHE           = os.path.join(ROOT, "_cache")
WORK_IMPORT_ROOT = os.path.join(_CACHE, "import")
CACHE_3DVIEW     = os.path.join(_CACHE, "3dview")  # material jsons + texture pngs for viewport-only reads
GUI_DIR     = os.path.join(getattr(sys, "_MEIPASS", ROOT), "gui")

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
    """The folder mods are installed into by 'Build & Install' (the game's ~mods dir, which can be
    named anything). Empty string when unset — install is gated on this being configured. Read fresh
    from disk each call so edits in the Paths panel take effect without a restart."""
    return (_load_config().get("mods_folder", "") or "").replace("\\", "/")

def save_mods_folder(path):
    cfg = _load_config()
    if path:
        cfg["mods_folder"] = path.replace("\\", "/")
    else:
        cfg.pop("mods_folder", None)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), indent=2)

def _prereq_issues(need_tool=True):
    issues = []
    if not glob.glob(PAKS + "/pakchunk*.utoc"):
        issues.append(("error", f"No pak files found at: {PAKS}"))
    if not os.path.exists(os.path.join(TOOLS, "AES_KEY.txt")):
        issues.append(("error", f"AES_KEY.txt not found at: {os.path.join(TOOLS, 'AES_KEY.txt')}"))
    if need_tool and not os.path.exists(os.path.join(TOOLS, "UAssetTool.exe")):
        issues.append(("error", f"UAssetTool.exe not found at: {os.path.join(TOOLS, 'UAssetTool.exe')}"))
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
    return {
        "ok":     not any(level == "error" for level, _ in issues),
        "issues": [{"level": level, "message": msg} for level, msg in issues],
    }
