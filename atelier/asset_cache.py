import os, json, threading
from atelier.config import _CACHE

_PATH = os.path.join(_CACHE, "extracted_assets.json")
_lock = threading.Lock()
_data: dict = {}   # game_rel → {cache_path, pak, pfx}
_names: dict = {}  # basename.lower() → game_rel

def _rebuild():
    global _names
    _names = {os.path.basename(gr).lower(): gr for gr in _data}

def _load():
    global _data
    if os.path.exists(_PATH):
        try:
            with open(_PATH, encoding="utf-8") as f:
                _data = json.load(f)
        except Exception:
            _data = {}
    _rebuild()

def _save():
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(_data, f)

_load()

def get(game_rel: str):
    return _data.get(game_rel) or _data.get(game_rel.lower())

def by_name(basename: str):
    """game_rel for basename (no ext, case-insensitive), or None."""
    return _names.get(basename.lower())

def cache_base(game_rel: str) -> str:
    """Extracted cache path (no ext) for game_rel, or empty string if not recorded."""
    e = get(game_rel)
    return e["cache_path"] if e else ""

def record(game_rel: str, cache_path: str, pak: str, pfx: str):
    with _lock:
        _data[game_rel] = {"cache_path": os.path.abspath(cache_path), "pak": pak, "pfx": pfx}
        _names[os.path.basename(game_rel).lower()] = game_rel
        _save()

def record_many(entries):
    """entries: iterable of (game_rel, cache_path, pak, pfx)"""
    with _lock:
        for game_rel, cache_path, pak, pfx in entries:
            _data[game_rel] = {"cache_path": os.path.abspath(cache_path), "pak": pak, "pfx": pfx}
            _names[os.path.basename(game_rel).lower()] = game_rel
        _save()

def remove(game_rel: str):
    with _lock:
        name_key = os.path.basename(game_rel).lower()
        removed  = _data.pop(game_rel, None) or _data.pop(game_rel.lower(), None)
        if removed and _names.get(name_key) in (game_rel, game_rel.lower()):
            _names.pop(name_key, None)
        _save()

def iter_skin(cid: str, skin_id: str):
    """Yield (game_rel, info) for extracted assets under Characters/{cid}/{skin_id}/."""
    pfx = f"characters/{cid.lower()}/{skin_id.lower()}/"
    for gr, info in list(_data.items()):
        if gr.lower().startswith(pfx):
            yield gr, info

def iter_prefix(prefix: str):
    """Yield (game_rel, info) for extracted assets with game_rel starting with prefix.
    Empty prefix yields all entries."""
    if not prefix:
        yield from list(_data.items())
        return
    p = prefix.lower().rstrip("/") + "/"
    for gr, info in list(_data.items()):
        if gr.lower().startswith(p):
            yield gr, info
