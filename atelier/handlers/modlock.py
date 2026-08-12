"""Optional SOFT mod-lock (anti-theft deterrent, NOT encryption). On export, Atelier can embed a
marker in a mod's .ucas: the literal tag `UE5SCO` + the password REVERSED + `UE5SCO` again. On
unpack (repatch/import), Atelier scans the mod's files for that tag; if present it prompts for the
password, reverses the input, and compares it to the stored (reversed) code — unlocking only on a
match. The marker sits in the offset-indexed .ucas tail so it's inert to the game but recoverable by
anyone with a hex editor: this deters casual theft *inside Atelier*, it does not protect the data."""
import os, glob, zipfile

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
        for f in (glob.glob(os.path.join(mod_source, "**", "*.ucas"), recursive=True) +
                  glob.glob(os.path.join(mod_source, "**", "*.utoc"), recursive=True) +
                  glob.glob(os.path.join(mod_source, "**", "*.pak"), recursive=True)):
            code = _scan_bytes(open(f, "rb").read())
            if code:
                return code
        for z in glob.glob(os.path.join(mod_source, "**", "*.zip"), recursive=True):
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

def embed(mod_base, password):
    """Append the lock marker to mod_base.ucas. Strips any existing marker first (no dupes)."""
    ucas = mod_base + ".ucas"
    if not password or not os.path.exists(ucas):
        return False
    strip(mod_base)
    with open(ucas, "ab") as f:
        f.write(TAG + _rev(password).encode("utf-8") + TAG)
    return True

def strip(mod_base):
    """Remove the lock marker from mod_base.ucas if present."""
    ucas = mod_base + ".ucas"
    if not os.path.exists(ucas):
        return
    b = open(ucas, "rb").read()
    i = b.find(TAG)
    if i < 0:
        return
    j = b.find(TAG, i + len(TAG))
    if j > i:
        open(ucas, "wb").write(b[:i] + b[j + len(TAG):])
