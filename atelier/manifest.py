"""Per-project manifest: on-disk flat filename <-> game_rel, collision-safe.

The active project folder (assets/projects/<name>/) stores every imported asset flat
(no subfolders) as <stem>.png or <stem>.json. Most of the time <stem> is just the pak
basename of the game_rel. But some basenames occur at more than one path in the paks
(e.g. Characters/<cid>/<skin>/Materials/MI_X vs .../Materials/Lobby/MI_X) — a plain
basename can't tell those apart once flattened. This module is the single place that
assigns and remembers the on-disk stem for a game_rel, disambiguating on collision
instead of letting two different assets silently share one file.

Stored at <project_dir>/.atelier/manifest.json — nested under the project dir so it
travels for free with the existing os.rename/shutil.copytree/shutil.rmtree project
operations in atelier/web/routes.py, and is skipped by directory listings that only
look at files (all_imported(), _list_projects()).
"""
import os, json, hashlib, threading

_MANIFEST_SUBDIR = ".atelier"
_MANIFEST_FILE   = "manifest.json"
_VERSION         = 1

_lock  = threading.Lock()
_cache: dict = {}  # abspath(project_dir) -> {"stems": {stem: {"game_rel", "kind"}}, "by_gr": {game_rel: stem}}


def _paths(project_dir):
    d = os.path.join(project_dir, _MANIFEST_SUBDIR)
    return d, os.path.join(d, _MANIFEST_FILE)


def _load(project_dir):
    key = os.path.abspath(project_dir)
    data = _cache.get(key)
    if data is not None:
        return data
    _, mp = _paths(project_dir)
    stems = {}
    if os.path.exists(mp):
        try:
            stems = json.load(open(mp, encoding="utf-8")).get("entries") or {}
        except Exception:
            stems = {}
    by_gr = {v["game_rel"]: stem for stem, v in stems.items()}
    data = {"stems": stems, "by_gr": by_gr}
    _cache[key] = data
    return data


def _save(project_dir):
    key  = os.path.abspath(project_dir)
    data = _cache.get(key)
    if data is None:
        return
    dir_, mp = _paths(project_dir)
    os.makedirs(dir_, exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump({"version": _VERSION, "entries": data["stems"]}, f)


def invalidate(project_dir):
    """Drop the in-memory cache for a project dir (call after it's renamed away from or deleted,
    so a future project at the same path doesn't inherit stale in-memory entries)."""
    _cache.pop(os.path.abspath(project_dir), None)


def lookup_game_rel(project_dir, stem):
    """Read-only: stem -> game_rel, or None."""
    return _load(project_dir)["stems"].get(stem, {}).get("game_rel")


def lookup_kind(project_dir, stem):
    return _load(project_dir)["stems"].get(stem, {}).get("kind")


def lookup_stem(project_dir, game_rel):
    """Read-only: game_rel -> its on-disk stem if already imported into this project, else None.
    Never creates an entry — use stem_for() when you're about to write the file."""
    return _load(project_dir)["by_gr"].get(game_rel)


def stem_for(project_dir, game_rel, kind):
    """Get-or-create the on-disk filename stem for game_rel in this project.
    Same game_rel always returns the same stem (idempotent). A different game_rel whose
    plain basename is already taken gets disambiguated (parent-folder suffix, then a short
    hash) instead of clobbering the existing entry."""
    with _lock:
        data = _load(project_dir)
        stems, by_gr = data["stems"], data["by_gr"]
        existing = by_gr.get(game_rel)
        if existing is not None:
            return existing
        candidate = os.path.basename(game_rel)
        if candidate not in stems:
            chosen = candidate
        else:
            parent = os.path.basename(os.path.dirname(game_rel))
            alt = f"{candidate}__{parent}" if parent else candidate
            chosen = alt if alt not in stems else f"{candidate}__{hashlib.sha1(game_rel.encode()).hexdigest()[:6]}"
        stems[chosen] = {"game_rel": game_rel, "kind": kind}
        by_gr[game_rel] = chosen
        _save(project_dir)
        return chosen


def remove(project_dir, game_rel):
    with _lock:
        data = _load(project_dir)
        stems, by_gr = data["stems"], data["by_gr"]
        stem = by_gr.pop(game_rel, None)
        if stem is not None:
            stems.pop(stem, None)
            _save(project_dir)


def all_entries(project_dir):
    """[(stem, game_rel, kind), ...] for every recorded entry in this project."""
    data = _load(project_dir)
    return [(stem, v["game_rel"], v["kind"]) for stem, v in data["stems"].items()]


def ensure_migrated(project_dir):
    """Backfill a manifest for a pre-existing flat project folder that predates this system,
    using the global asset_cache basename index as the best available (lossy) source of
    truth. Any collision that already silently clobbered a file on disk can't be undone here
    — this only records what asset_cache currently believes each surviving file is."""
    if not os.path.isdir(project_dir):
        return
    _, mp = _paths(project_dir)
    if os.path.exists(mp):
        return
    import atelier.asset_cache as _ac
    from atelier.web.browse import _classify_file, JSON_EDIT_TYPES
    with _lock:
        data = _load(project_dir)
        stems, by_gr = data["stems"], data["by_gr"]
        for fname in os.listdir(project_dir):
            fpath = os.path.join(project_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if fname.endswith(".png"):
                name, kind = fname[:-4], "texture"
            elif fname.endswith(".json"):
                name = fname[:-5]
                kind = _classify_file(name)
                if kind not in JSON_EDIT_TYPES:
                    continue
            else:
                continue
            gr = _ac.by_name(name) or name
            stems.setdefault(name, {"game_rel": gr, "kind": kind})
            by_gr.setdefault(gr, name)
        _save(project_dir)
