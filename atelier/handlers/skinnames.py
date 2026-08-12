"""Human-readable skin/character names from Tools/MarvelRivalsCharacterIDs.md.

The pak folders are bare ids (Characters/1060/1060501), so the viewport's chroma picker would show
"1060501" instead of "COASTAL KUMIHO". This parses the shipped reference table into a lookup so the
UI can label them. Purely cosmetic — nothing downstream depends on the names.
"""
import os, re, glob
from atelier.config import TOOLS

_NAME = "MarvelRivalsCharacterIDs.md"
_CACHE = None      # {"skins": {skin_id: {"skin": name, "char": id, "char_name": name}}, "chars": {id: name}}


def _md_path():
    """The reference table ships in Tools/. TOOLS may point at a source tree that lacks it while the
    real copy is in the packaged dist (or vice-versa), so check a few likely spots before giving up."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(TOOLS, _NAME),
        os.path.join(here, "..", "..", "Tools", _NAME),
        os.path.join(here, "..", "..", "dist", "Atelier", "Tools", _NAME),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    hits = glob.glob(os.path.join(here, "..", "..", "**", _NAME), recursive=True)
    return hits[0] if hits else cands[0]


def _parse():
    """Table rows are `| ID | NAME | SKIN ID | SKIN NAME |`; a character row fills ID+NAME, skin rows
    leave them blank and carry the last character down. Trailing `|` is inconsistent, so split loosely."""
    skins, chars = {}, {}
    cur_char, cur_name = None, None
    try:
        lines = open(_md_path(), encoding="utf-8").read().splitlines()
    except OSError:
        return {"skins": {}, "chars": {}}
    for ln in lines:
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        cid, cname, sid, sname = cells[0], cells[1], cells[2], cells[3]
        if re.fullmatch(r"\d{4}", cid):           # a character row sets the running character
            cur_char, cur_name = cid, cname
            chars[cid] = cname
        if re.fullmatch(r"\d{6,7}", sid):         # a skin row (present on both char and skin lines)
            skins[sid] = {"skin": sname, "char": cur_char, "char_name": cur_name}
    return {"skins": skins, "chars": chars}


def _data():
    global _CACHE
    if _CACHE is None:
        _CACHE = _parse()
    return _CACHE


def skin_name(skin_id):
    """Display name for a skin id, or None if unknown."""
    e = _data()["skins"].get(str(skin_id))
    return e["skin"] if e else None


def char_name(char_id):
    return _data()["chars"].get(str(char_id))


def label_for(folder_id):
    """Best display label for a pak folder id: skin name if known, else character name, else None.
    (Handles both 6-7 digit skin ids and 4-digit character folders.)"""
    return skin_name(folder_id) or char_name(folder_id)
