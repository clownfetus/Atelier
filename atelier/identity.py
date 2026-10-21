"""Resolve display identities without changing asset paths or guessing costume artwork."""
import re

_ID = re.compile(r'[0-9]{4}(?:[0-9]{3})?\Z')
_TOKENS = re.compile(r'(?<![0-9])([0-9]{7}|[0-9]{4})(?![0-9])')


def identity_tokens(value):
    return _TOKENS.findall(value)


def resolve_ids(path, entries, *, leaf_only=False):
    """Find consistent character/skin IDs in any content branch.

    Only catalogue IDs, the conventional Characters hierarchy, and unknown skins
    belonging to a known character qualify. Conflicting owners remain unnamed.
    Filename tokens provide context only when they are exact, known IDs.
    """
    if not isinstance(path, str) or not path:
        return None
    path = path.replace('\\', '/')
    if path.startswith('/Game/Marvel/'):
        path = path[len('/Game/Marvel/'):]
    if path.startswith('/') or re.search(r'[:?#\x00-\x1f\x7f]', path):
        return None
    parts = path.rstrip('/').split('/')
    if any(part in ('', '.', '..') for part in parts):
        return None
    if leaf_only and not _ID.fullmatch(parts[-1]):
        return None
    cid = sid = hero_path = skin_path = None
    for index, part in enumerate(parts):
        tokens = [part] if _ID.fullmatch(part) else (
            _TOKENS.findall(part) if index == len(parts) - 1 and not leaf_only else [])
        for key in tokens:
            entry = entries.get(key)
            conventional = (index > 0 and parts[index - 1].lower() == 'characters'
                            and len(key) == 4)
            owner = key[:4]
            if key == part and len(key) == 7 and hero_path and owner != cid:
                return None
            if not entry and not conventional:
                if key != part or len(key) != 7 or owner not in entries and owner != cid:
                    continue
            if entry and entry.get('kind', 'hero' if len(key) == 4 else 'skin') != (
                    'hero' if len(key) == 4 else 'skin'):
                continue
            if entry and len(key) == 7 and entry.get('hero', owner) != owner:
                return None
            if (cid and cid != owner) or (sid and len(key) == 7 and sid != key):
                return None
            cid = owner
            source = '/'.join(parts[:index + 1])
            if len(key) == 4:
                hero_path = source
            else:
                sid, skin_path = key, source
    return {'char_id': cid, 'skin_id': sid, 'hero_path': hero_path,
            'skin_path': skin_path} if cid else None
