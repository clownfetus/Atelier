import re
from atelier.index import ensure_index

PAK_GAME_PREFIX = "Marvel/Content/Marvel"

def char_id(skin_id): return skin_id[:4]

def _clean_pak_path(p):
    return re.sub(r"^(\.\./)+", "", p.replace("\\", "/"))

def _skin_prefix(skin_id):
    return f"{PAK_GAME_PREFIX}/Characters/{char_id(skin_id)}/{skin_id}/".lower()

def skin_rel(pak_path, skin_id):
    """Pak path -> relative path from the skin folder (original case, no .uasset ext)."""
    pfx   = _skin_prefix(skin_id)
    clean = _clean_pak_path(pak_path)
    if not clean.lower().startswith(pfx):
        return pak_path
    rel = clean[len(pfx):]
    return rel[:-7] if rel.lower().endswith(".uasset") else rel

def pak_rel(pak_path):
    """Strip ../../../ prefix (and .uasset ext) -> mount-relative path."""
    r = _clean_pak_path(pak_path)
    return r[:-7] if r.lower().endswith(".uasset") else r

def game_rel_for_skin(skin_id, tex_rel):
    """Storage-relative path for a skin asset: Characters/{cid}/{skin_id}/{tex_rel}"""
    cid = char_id(skin_id)
    return f"Characters/{cid}/{skin_id}/{tex_rel}"

def pak_game_path(game_rel):
    """Prefix a storage-relative game_rel with Marvel/Content/Marvel/ for pak operations."""
    return f"{PAK_GAME_PREFIX}/{game_rel}"

def skin_entries(skin_id):
    pfx = _skin_prefix(skin_id)
    return [(p, c) for p, c in ensure_index() if _clean_pak_path(p).lower().startswith(pfx)]

def filter_subpath(entries, skin_id, subpath):
    """Narrow entries to those whose skin-relative path starts with subpath."""
    if not subpath: return entries
    pfx = _skin_prefix(skin_id)
    sp  = subpath.lower().replace("\\", "/").strip("/")
    if sp.endswith("/*"): sp = sp[:-2].strip("/")
    elif sp.endswith("*"): sp = sp[:-1]
    full = (pfx + sp + "/") if sp else pfx
    return [(p, c) for p, c in entries if _clean_pak_path(p).lower().startswith(full)]
