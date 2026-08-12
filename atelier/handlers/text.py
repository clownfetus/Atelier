"""Text assets = StringTable (.uasset) under Marvel/Content/Marvel/Data/StringTable (named *_ST).
Editable content: the key->string pairs (Table.Value). Same edit model as world/vfx/curve — edits
persist as a <name>.json sidecar and are applied to the vanilla asset at export, bundling into the
SAME unified mod. StringTables are single-extension .uasset, so create_mod_iostore overrides them
cleanly (unlike .umap levels). Patch-resilient (config.USMAP auto-updates).

Note: MR's source strings are Chinese (NetEase); non-source locales (English, etc.) may be served
from .locres overrides. Editing the StringTable changes the source table; if a locale .locres wins
in-game, a future .locres editor would be needed. StringTable is the right first target."""
import os, re, glob, json, struct
from atelier.config import WORK_IMPORT_ROOT, PAKS, USMAP, _CACHE, project_base, project_base_legacy
from atelier.tools import uat
from atelier.paths import pak_game_path
import io_lib


def _fstr(s):
    """Serialize a UE FString: ANSI+null (positive length) if all-ASCII, else UTF-16LE+null
    (negative length). Matches UE's FString::operator<< so patched bytes deserialize correctly."""
    if s is None or s == "":
        return struct.pack("<i", 0)
    if all(ord(c) < 128 for c in s):
        b = s.encode("ascii") + b"\x00"
        return struct.pack("<i", len(b)) + b
    b = s.encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<i", -(len(s) + 1)) + b


def is_text(path_or_name):
    n = os.path.basename(path_or_name).lower()
    if n.endswith(".uasset"):
        n = n[:-7]
    return n.endswith("_st")

# ── StringTable enumeration for the browse "Text" section (not in the pak-asset index) ──
_STS = None
def _enum():
    """[{name, game_rel}] for every *_ST StringTable across containers. Cached. game_rel is
    browse-relative (Data/StringTable/...), no extension."""
    global _STS
    if _STS is not None: return _STS
    seen, out = set(), []
    for utoc in sorted(glob.glob(PAKS + "/*.utoc")):
        try:
            t = io_lib.parse_toc(utoc); entries = io_lib.parse_dir_index(t)
        except Exception:
            continue
        for p, _ud in entries:
            pl = p.lower()
            if not (pl.endswith(".uasset") and "/data/stringtable/" in pl): continue
            gr = re.sub(r"^(\.\./)+", "", p.replace("\\", "/"))
            gr = re.sub(r"^Marvel/Content/Marvel/", "", gr, flags=re.I)[:-7]   # -> Data/StringTable/X
            if gr.lower() in seen: continue
            seen.add(gr.lower()); out.append({"name": os.path.basename(gr), "game_rel": gr})
    _STS = sorted(out, key=lambda x: x["name"].lower())
    return _STS

def list_stringtables():
    return _enum()

# ── extraction + json ──────────────────────────────────────────────────────────
def full_pak_path(game_rel):
    """The real content-mount path for a StringTable.
    paths.pak_game_path() blindly prepends the content prefix, which DOUBLE-PREFIXES the
    MarvelGAS-plugin tables (their game_rel already carries its own mount), producing
    'Marvel/Content/Marvel/Marvel/Plugins/...' — a path that exists nowhere, so their staged mod
    would override nothing. Anything already rooted at a mount is returned as-is."""
    gr = game_rel.replace("\\", "/")
    if gr.lower().startswith("marvel/"):          # e.g. Marvel/Plugins/MarvelGAS/Content/...
        return gr
    return pak_game_path(gr)

def _find_extracted(name, game_rel=None):
    """Locate an extracted <name>.uasset under WORK_IMPORT_ROOT. Prefer the copy whose on-disk path
    matches game_rel's FULL mount path: 56 hero-ability tables exist twice under the same basename
    (Content/Marvel vs Plugins/MarvelGAS) with DIFFERENT contents, so a basename-only match silently
    returns the wrong table."""
    cands = glob.glob(os.path.join(WORK_IMPORT_ROOT, "**", name + ".uasset"), recursive=True)
    if not cands:
        return None
    if game_rel:
        want = "/" + full_pak_path(game_rel).lower()
        exact = sorted((p for p in cands if p.replace("\\", "/").lower()[:-7].endswith(want)), key=len)
        # A path was ASKED for, so a wrong-path copy is a MISS, not a substitute. Falling through to
        # the basename sort here is what made both colliding tables resolve to the same file (and
        # masked the miss, so the retoc fallback never ran).
        return exact[0][:-7] if exact else None
    cands.sort(key=lambda p: (0 if "stringtable" in p.lower() else 1, len(p)))
    return cands[0][:-7]

def _extract_via_retoc(game_rel):
    """UAssetTool's extract_iostore_legacy --filter matches BASENAMES only, so it can never reach the
    MarvelGAS-plugin tables (it returns the Content/Marvel copy instead). retoc takes a full path —
    the '../../../<mount>/...' form — so use it for anything the basename extract can't resolve."""
    import subprocess
    from atelier.config import get_aes_key
    from atelier.handlers.world import RETOC, CNW
    filt = "../../../" + full_pak_path(game_rel) + ".uasset"
    # PATCH containers override base chunks in-game, so they must win here too — 106_Lobby_ST is
    # 371 entries in pakchunk0 but 374 in Patch_-Windows_1.1.3702450_P, and the game loads the 374.
    # (Alphabetical order happens to put "Patch_" first today; don't depend on that.)
    utocs = sorted(glob.glob(os.path.join(PAKS, "*.utoc")))
    utocs.sort(key=lambda p: 0 if "patch" in os.path.basename(p).lower() else 1)
    for utoc in utocs:
        subprocess.run([RETOC, "-a", "0x" + get_aes_key(), "unpack", utoc, "--filter", filt,
                        "--game-paks-dir", PAKS, "-o", os.path.abspath(WORK_IMPORT_ROOT)],
                       capture_output=True, creationflags=CNW)
        base = _find_extracted(os.path.basename(game_rel), game_rel)
        if base:
            return base
    return None

def _ensure_extracted(game_rel):
    """Extract via RETOC (full path), never via UAssetTool's basename filter.
    `extract_iostore_legacy --filter <basename>` is actively unsafe for StringTables: 56 hero-ability
    tables share a basename across two mounts (Content/Marvel vs Plugins/MarvelGAS) with DIFFERENT
    contents, and given the ambiguous name it writes ONE asset's bytes to the OTHER asset's path —
    silently. Verified: --filter 604_Ability_1011_ST writes the plugin's 824-byte table to the main
    table's Content/Marvel path. retoc filters on the real '../../../<mount>/...' path, so each copy
    lands where it belongs."""
    name = os.path.basename(game_rel)
    base = _find_extracted(name, game_rel)
    if base:
        return base
    os.makedirs(WORK_IMPORT_ROOT, exist_ok=True)
    base = _extract_via_retoc(game_rel)
    if base:
        return base
    raise RuntimeError("StringTable not found in game paks: " + game_rel)

def _to_json(base):
    outdir = os.path.join(_CACHE, "text_tj"); os.makedirs(outdir, exist_ok=True)
    uat(["to_json", os.path.abspath(base + ".uasset"), USMAP, os.path.abspath(outdir)])
    jp = os.path.join(outdir, os.path.basename(base) + ".json")
    if not os.path.exists(jp):
        raise RuntimeError("to_json produced no JSON")
    return jp

def _table(d):
    """The StringTable export's Table dict {TableNamespace, Value:[[key,str],...]} + its export index."""
    for i, e in enumerate(d.get("Exports", [])):
        t = e.get("Table")
        if isinstance(t, dict) and isinstance(t.get("Value"), list):
            return i, t
    return None, None


# ── read the table straight from the .uexp (to_json CANNOT be trusted here) ──────
# UAssetTool's to_json mis-parses StringTables: each entry is THREE FStrings —
# Key, SourceString, and a trailing empty — but to_json assumes two, so it drifts,
# reports 243 rows for a declared 371, pairs Chinese values into the key slot, and
# emits null for the rest. Those nulls are why ~half of every table silently refused
# to save: _fstr(None) is an empty string, so stage_text's locator never matched.
def _rd_fstring(b, o):
    """UE FString: int32 len; >0 = ANSI (len incl null); <0 = UTF-16LE (-len code units incl null)."""
    (n,) = struct.unpack_from("<i", b, o); o += 4
    if n == 0:
        return "", o
    if n > 0:
        return b[o:o + n - 1].decode("utf-8", "replace"), o + n
    cu = -n
    return b[o:o + (cu - 1) * 2].decode("utf-16-le", "replace"), o + cu * 2

def parse_table_uexp(base):
    """[{key, value, val_off, val_len}] parsed from the .uexp, in on-disk order.
    val_off/val_len bracket the value's FString bytes so edits can be spliced by offset
    instead of by a byte-search that assumes global uniqueness."""
    ux = open(base + ".uexp", "rb").read()
    ns = os.path.basename(base)                       # TableNamespace == asset basename in MR
    a = ux.find(_fstr(ns))
    if a < 0:
        raise RuntimeError("StringTable namespace not found in .uexp: " + ns)
    o = a + len(_fstr(ns))
    (count,) = struct.unpack_from("<i", ux, o); o += 4
    out = []
    for _ in range(count):
        k, o = _rd_fstring(ux, o)
        v_off = o
        v, o = _rd_fstring(ux, o)
        v_len = o - v_off
        _extra, o = _rd_fstring(ux, o)                # the third, always-empty FString
        out.append({"key": k, "value": v, "val_off": v_off, "val_len": v_len})
    return out

_ROWS = {}
def _load_rows(base):
    """parse_table_uexp cached per extracted asset (the .uexp doesn't change under us)."""
    st = os.path.getmtime(base + ".uexp")
    hit = _ROWS.get(base)
    if hit and hit[0] == st:
        return hit[1]
    rows = parse_table_uexp(base)
    _ROWS[base] = (st, rows)
    return rows

# ── edit sidecar (persisted) ────────────────────────────────────────────────────
def text_sidecar(game_rel):
    return project_base(game_rel) + ".json"

def _load_edits(game_rel):
    for p in (text_sidecar(game_rel), project_base_legacy(game_rel) + ".json"):
        if os.path.exists(p):
            try: return json.load(open(p, encoding="utf-8-sig")).get("text_edits") or {}
            except Exception: return {}
    return {}

def read_text(game_rel):
    """{ok, name, namespace, entries:[{key, value}], edits}. entries keep on-disk order; edits are
    keyed by key string (values are overlaid so the UI shows the edited state).
    Parsed from the .uexp, NOT to_json — see parse_table_uexp for why (to_json drifts and nulls
    out roughly half of every table, which is what made those rows unsaveable)."""
    base = _ensure_extracted(game_rel)
    rows = _load_rows(base)
    edits = _load_edits(game_rel)
    entries = [{"key": r["key"], "value": edits.get(r["key"], r["value"])} for r in rows]
    return {"ok": True, "name": os.path.basename(game_rel), "namespace": os.path.basename(base),
            "entries": entries, "edits": edits}

def save_text(game_rel, edits):
    _ensure_extracted(game_rel)
    clean = {str(k): ("" if v is None else str(v)) for k, v in (edits or {}).items()}
    p = text_sidecar(game_rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"text_edits": clean}, open(p, "w", encoding="utf-8"))
    return read_text(game_rel)

def reset_text(game_rel):
    for p in (text_sidecar(game_rel), project_base_legacy(game_rel) + ".json"):
        if os.path.exists(p): os.remove(p)
    return read_text(game_rel)

# ── stage into the unified export (FAITHFUL BINARY-PATCH) ───────────────────────
# UAssetTool's from_json does NOT round-trip StringTables — it drops the per-key metadata
# (KeysToMetaData), producing a smaller, misaligned .uexp that crashes the game ("resize TArray to
# an invalid size"). So we keep the vanilla .uasset/.uexp byte-for-byte and only splice the edited
# strings: locate each entry by its exact [key FString][value FString] bytes, swap the value's bytes,
# then fix the export SerialSize (int64 in the .uasset) by the total byte delta.
def stage_text(stage, game_rel, edits=None):
    base = _ensure_extracted(game_rel)
    ed = edits if edits is not None else _load_edits(game_rel)
    if not ed:
        raise RuntimeError("no text edits to stage")
    ua = bytearray(open(base + ".uasset", "rb").read())
    ux = bytearray(open(base + ".uexp", "rb").read())
    orig_ux_len = len(ux)
    rows = _load_rows(base)
    # Splice each edited value at its PARSED offset. The old code searched for
    # _fstr(key)+_fstr(value) and required a globally-unique hit — which silently skipped every
    # row to_json had nulled out, i.e. about half the table. Offsets can't collide, so nothing
    # is skipped; applied back-to-front so earlier offsets stay valid as lengths change.
    delta, changed, missing = 0, 0, [k for k in ed if not any(r["key"] == k for r in rows)]
    for r in sorted(rows, key=lambda r: -r["val_off"]):
        if r["key"] not in ed:
            continue
        new = _fstr(ed[r["key"]])
        ux[r["val_off"]:r["val_off"] + r["val_len"]] = new
        delta += len(new) - r["val_len"]
        changed += 1
    if not changed:
        raise RuntimeError("none of the edited keys exist in this table: " + ", ".join(map(str, list(ed)[:5])))
    if missing:
        print("[stage_text] %s: %d edited key(s) not in table: %s" %
              (os.path.basename(game_rel), len(missing), ", ".join(map(str, missing[:5]))))
    # fix the export SerialSize (int64 == vanilla .uexp length minus the 4-byte package tag)
    ss = struct.pack("<q", orig_ux_len - 4)
    if ua.count(ss) == 1:
        j = ua.find(ss); ua[j:j + 8] = struct.pack("<q", (orig_ux_len - 4) + delta)
    pak_gr = full_pak_path(game_rel)          # NOT pak_game_path — it double-prefixes plugin mounts
    if pak_gr.lower().endswith(".uasset"): pak_gr = pak_gr[:-7]
    out = os.path.join(stage, *pak_gr.split("/"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out + ".uasset", "wb").write(bytes(ua))
    open(out + ".uexp", "wb").write(bytes(ux))
    return os.path.basename(game_rel)
