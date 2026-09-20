"""Per-project state that isn't a file on disk: sidebar selection, per-asset export options,
and the Atelier version that authored the project.

Stored at <project_dir>/.atelier/project.json — nested inside the project folder so it travels
for free with the os.rename / shutil.copytree / shutil.rmtree project operations in
atelier/web/routes.py (a duplicated project correctly inherits the source's selection).
(.atelier/ is the subdir atelier/manifest.py reserved for the same purpose; that module is
currently unreferenced, so project.json is in practice the only file there.)

TWO DELIBERATE CHOICES HERE:

1. Selection is stored as the DESELECTED set, not the selected one. Everything in a project
   defaults to "will be exported", and an asset that appears later (imported, or dropped in
   externally) must inherit that default rather than arriving switched off. A selected-list
   would silently exclude every new asset from the next export; a deselected-list can only
   ever exclude something the user actually turned off. It also makes a missing file mean
   exactly "nothing turned off", which is the correct reading for every pre-existing project.

2. A project.json backfilled onto a project that predates this module records
   created_version="unknown" — NOT the running version. Claiming a legacy project was authored
   by the current build is a lie that a future compatibility check or auto-porter would act on,
   skipping the very projects most likely to need porting. "unknown" means "older than version
   tracking", which is the truth and is what a porter should key off.

THE THIRD THING STORED HERE — per-asset export options (asset_opts) — follows the same rule as
selection: absent means "the defaults", never "off". An option only exists in the file once the
user has actually set it, so a project made before Phase 4 opens with every texture on the normal
mip chain and its vanilla texture group, which is what it was built with.

Nothing here warns or blocks on version. The texture/material/curve/vfx project formats are
unchanged from 0.2.3 and pre-Noobs builds, so those projects load as-is; this only records
provenance so a LATER version has the facts it needs to decide.
"""
import os, json, threading

from atelier.config import VERSION_FILE

_SUBDIR   = ".atelier"
_FILE     = "project.json"
_VERSION  = 1
_UNKNOWN  = "unknown"   # project predates version stamping — never guess a number here

_lock = threading.Lock()


def current_version():
    """The running Atelier version string, or "" if it can't be read (never fatal)."""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _paths(project_dir):
    d = os.path.join(project_dir, _SUBDIR)
    return d, os.path.join(d, _FILE)


def load(project_dir):
    """Read the project's metadata. A project with no project.json (every project made before
    this existed) reads as an empty, fully-selected, unknown-provenance project — not an error."""
    _, p = _paths(project_dir)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except Exception:
        d = {}
    return {
        "version":         d.get("version", _VERSION),
        "created_version": d.get("created_version", _UNKNOWN),
        "last_version":    d.get("last_version", _UNKNOWN),
        "deselected":      [s for s in (d.get("deselected") or []) if isinstance(s, str)],
        "asset_opts":      {k: v for k, v in (d.get("asset_opts") or {}).items()
                            if isinstance(k, str) and isinstance(v, dict)},
    }


def _write(project_dir, data):
    dir_, p = _paths(project_dir)
    os.makedirs(dir_, exist_ok=True)
    data["version"]      = _VERSION
    data["last_version"] = current_version() or data.get("last_version") or _UNKNOWN
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)   # atomic: a crash mid-write can't leave a half-parsed project.json


def stamp_new(project_dir):
    """Record that THIS build authored a brand-new project. Call only on project creation —
    calling it on an existing folder would overwrite genuine provenance with the current version."""
    with _lock:
        dir_, p = _paths(project_dir)
        if os.path.exists(p):
            return
        _write(project_dir, {"created_version": current_version() or _UNKNOWN, "deselected": []})


def get_deselected(project_dir):
    """Set of game_rels the user has switched OFF for export in this project."""
    return set(load(project_dir)["deselected"])


def set_deselected(project_dir, game_rels):
    with _lock:
        d = load(project_dir)
        d["deselected"] = sorted({g for g in game_rels if isinstance(g, str) and g})
        _write(project_dir, d)


def get_asset_opts(project_dir, game_rel=None):
    """Per-asset export options. One asset's dict with game_rel, or the whole {game_rel: opts} map.

    Keys in use (all optional, all defaulting to "vanilla behaviour" when absent):
      no_mips   bool - ship a single top mip instead of the full chain (inject_texture --no-mips)
      lod_group str  - override the texture's LODGroup/TEXTUREGROUP_* (its texture group)
      blank     bool - ship the texture fully transparent instead of the edited PNG
      dye_off   bool - on a MATERIAL: also ship a neutral ColorID mask so the dye system stops
                       overpainting the BaseColor (see handlers/dye.py::stage_dye_off)
      lq_twin   bool - also stage the Marvel_LQ copy of this asset (only if that mount exists)
    """
    opts = load(project_dir)["asset_opts"]
    if game_rel is None:
        return opts
    return dict(opts.get(game_rel) or {})


def set_asset_opts(project_dir, game_rel, opts):
    """Merge `opts` into one asset's options. A key set to None/False/"" is REMOVED rather than
    stored false: "not in the file" and "explicitly off" must stay the same state, or a later
    default change would silently not reach projects that had only ever looked at the control."""
    if not game_rel:
        return {}
    with _lock:
        d   = load(project_dir)
        cur = dict(d["asset_opts"].get(game_rel) or {})
        for k, v in (opts or {}).items():
            if v in (None, False, ""):
                cur.pop(k, None)
            else:
                cur[k] = v
        if cur:
            d["asset_opts"][game_rel] = cur
        else:
            d["asset_opts"].pop(game_rel, None)
        _write(project_dir, d)
        return cur


def forget_asset(project_dir, game_rel):
    """Drop an asset's options — called when the asset itself is deleted from the project, so a
    re-import doesn't silently inherit settings from an edit the user threw away."""
    with _lock:
        d = load(project_dir)
        if d["asset_opts"].pop(game_rel, None) is not None:
            _write(project_dir, d)
