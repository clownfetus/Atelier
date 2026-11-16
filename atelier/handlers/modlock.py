"""Reads the SOFT mod-lock that older Atelier releases could write (a deterrent, NOT encryption).
Those releases appended a marker to a mod's .ucas: the literal tag `UE5SCO` + the password
REVERSED + `UE5SCO` again. Atelier no longer writes it, because the game now flags containers that
carry it. On unpack (open/repatch), Atelier still scans a mod's files for the tag; if present it
asks for the password, reverses the input, and compares it to the stored (reversed) code. Repatch
rebuilds the container from its assets, so a repatched copy never carries the marker."""
import os, zipfile
from atelier.config import dir_glob

TAG = b"UE5SCO"

def _rev(s):
    return s[::-1]

def _scan_bytes(b):
    """Return the stored CODE (reversed password) between the two tags, or None."""
    i = b.find(TAG)
    if i < 0:
        return None
    j = b.find(TAG, i + len(TAG))
    if j <= i:
        return None
    try:
        return b[i + len(TAG):j].decode("utf-8")
    except Exception:
        return None

def _scan_zip(zpath):
    try:
        with zipfile.ZipFile(zpath) as z:
            for n in z.namelist():
                if n.lower().endswith((".ucas", ".utoc", ".pak")):
                    code = _scan_bytes(z.read(n))
                    if code:
                        return code
    except Exception:
        pass
    return None

def lock_code(mod_source):
    """The stored lock CODE (reversed password) for a mod, or None if it isn't locked.
    mod_source = a directory, a .zip, or a base/.pak/.ucas/.utoc path."""
    if os.path.isdir(mod_source):
        # dir_glob: mod_source carries the user's mod name, and a mod called "[WIP] Recolor"
        # made every one of these match nothing — so a locked mod reported itself as unlocked.
        for f in (dir_glob(mod_source, "**/*.ucas", recursive=True) +
                  dir_glob(mod_source, "**/*.utoc", recursive=True) +
                  dir_glob(mod_source, "**/*.pak",  recursive=True)):
            code = _scan_bytes(open(f, "rb").read())
            if code:
                return code
        for z in dir_glob(mod_source, "**/*.zip", recursive=True):
            code = _scan_zip(z)
            if code:
                return code
        return None
    if mod_source.lower().endswith(".zip"):
        return _scan_zip(mod_source)
    base = mod_source.rsplit(".", 1)[0] if mod_source.lower().endswith((".pak", ".ucas", ".utoc")) else mod_source
    for e in (".ucas", ".utoc", ".pak"):
        if os.path.exists(base + e):
            code = _scan_bytes(open(base + e, "rb").read())
            if code:
                return code
    return None

def is_locked(mod_source):
    return lock_code(mod_source) is not None

def verify(entered, code):
    """User's design: reverse the entered password and match it to the stored code."""
    return bool(code) and _rev(entered or "") == code

def unlock(mod_source, entered):
    """True if `entered` opens the mod (or the mod isn't locked at all)."""
    code = lock_code(mod_source)
    return code is None or verify(entered, code)
