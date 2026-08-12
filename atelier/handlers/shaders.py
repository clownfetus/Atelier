"""Shader Studio backend — browse & disassemble Marvel Rivals' compiled shaders.

The game ships ~871k SM6/DXIL shaders inside pakchunkShaderAsset + global (IoStore FShaderCodeArchive).
Dumping every blob would be ~12GB, so we:
  1. build a lightweight SQLite index once (retoc `dump-shaders --index-only`, streamed in),
  2. browse/search it paginated, and
  3. extract + disassemble ONE shader on demand (retoc `extract-shader` → strip UE wrapper → dxc -dumpbin).

All three tools (retoc, dxc, oo2core) are bundled standalone under Tools/shaders — nothing external.
"""
import os, re, json, glob, sqlite3, subprocess, threading, struct, tempfile
from atelier.config import ROOT, TOOLS, PAKS, CNW

SHADER_TOOLS = os.path.join(TOOLS, "shaders")
RETOC        = os.path.join(SHADER_TOOLS, "retoc-rivals-cli.exe")
DXC          = os.path.join(SHADER_TOOLS, "dxc.exe")

CACHE   = os.path.join(ROOT, "_cache", "shaders")
DB_PATH = os.path.join(CACHE, "shaders.db")
IDX_DIR = os.path.join(CACHE, "idx")

FREQ_NAMES = {0: "Vertex", 1: "Hull", 2: "Domain", 3: "Pixel", 4: "Geometry", 5: "Compute"}

# ── shared build state (Shader Studio polls this) ────────────────────────────────
_BUILD  = {"running": False, "phase": "", "pct": 0, "count": 0, "error": "", "done": False}
_bldlk  = threading.Lock()


def _containers():
    """The shader containers to open (both — Global's groups dedupe into the big one)."""
    out = []
    for name in ("pakchunkShaderAsset-Windows.utoc", "global.utoc"):
        p = os.path.join(PAKS, name)
        if os.path.isfile(p):
            out.append(p)
    return out


def tools_ok():
    return os.path.isfile(RETOC) and os.path.isfile(DXC) and len(_containers()) > 0


def db_ready():
    if not os.path.isfile(DB_PATH):
        return False
    try:
        con = sqlite3.connect(DB_PATH)
        n = con.execute("SELECT COUNT(*) FROM shaders").fetchone()[0]
        con.close()
        return n > 0
    except Exception:
        return False


def status():
    st = {"tools_ok": tools_ok(), "db_ready": db_ready()}
    with _bldlk:
        st["build"] = dict(_BUILD)
    if st["db_ready"]:
        st["libraries"] = libraries()
    return st


def libraries():
    """Per-library totals + stage breakdown for the picker."""
    con = sqlite3.connect(DB_PATH)
    libs = []
    for (lib,) in con.execute("SELECT DISTINCT lib FROM shaders ORDER BY lib"):
        total = con.execute("SELECT COUNT(*) FROM shaders WHERE lib=?", (lib,)).fetchone()[0]
        freqs = {FREQ_NAMES.get(f, str(f)): c
                 for f, c in con.execute("SELECT freq, COUNT(*) FROM shaders WHERE lib=? GROUP BY freq", (lib,))}
        libs.append({"name": lib, "total": total, "freqs": freqs,
                     "short": _short_lib(lib)})
    con.close()
    return libs


def _short_lib(lib):
    # ShaderArchive-Global-PCD3D_SM6-PCD3D_SM6 -> Global
    parts = lib.split("-")
    return parts[1] if len(parts) > 1 else lib


# ── index build ──────────────────────────────────────────────────────────────────
def build_index_async():
    with _bldlk:
        if _BUILD["running"]:
            return {"ok": True, "already": True}
        _BUILD.update({"running": True, "phase": "starting", "pct": 0, "count": 0,
                       "error": "", "done": False})
    threading.Thread(target=_build_index, daemon=True).start()
    return {"ok": True}


def _set(**kw):
    with _bldlk:
        _BUILD.update(kw)


def _build_index():
    try:
        os.makedirs(CACHE, exist_ok=True)
        # 1) dump the per-library index.json (no blobs) — ~2 min on the real game.
        _set(phase="Extracting shader index from the game (~2 min)…", pct=5)
        if os.path.isdir(IDX_DIR):
            import shutil
            shutil.rmtree(IDX_DIR, ignore_errors=True)
        os.makedirs(IDX_DIR, exist_ok=True)
        cmd = [RETOC, "dump-shaders", *_containers(), "-o", IDX_DIR, "--index-only"]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "dump-shaders failed").strip().splitlines()[-1])

        # 2) stream each line-delimited index.json into SQLite.
        index_files = glob.glob(os.path.join(IDX_DIR, "*", "index.json"))
        if not index_files:
            raise RuntimeError("no index.json produced")
        if os.path.isfile(DB_PATH):
            os.remove(DB_PATH)
        con = sqlite3.connect(DB_PATH)
        con.execute("CREATE TABLE shaders (lib TEXT, idx INTEGER, freq INTEGER, hash TEXT, size INTEGER)")
        total_lines = sum(_count_lines(f) for f in index_files)
        done = 0
        for f in index_files:
            lib = os.path.basename(os.path.dirname(f))
            _set(phase=f"Indexing {_short_lib(lib)}…")
            batch = []
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip().rstrip(",")
                    if not s.startswith('{"index"'):
                        continue
                    try:
                        e = json.loads(s)
                    except Exception:
                        continue
                    batch.append((lib, e["index"], e["frequency"], e["hash"], e["size"]))
                    if len(batch) >= 5000:
                        con.executemany("INSERT INTO shaders VALUES (?,?,?,?,?)", batch)
                        done += len(batch); batch = []
                        _set(pct=min(98, int(done * 100 / max(1, total_lines))), count=done)
            if batch:
                con.executemany("INSERT INTO shaders VALUES (?,?,?,?,?)", batch)
                done += len(batch)
                _set(pct=min(98, int(done * 100 / max(1, total_lines))), count=done)
        con.execute("CREATE INDEX ix_lib_freq ON shaders(lib, freq)")
        con.execute("CREATE INDEX ix_hash ON shaders(hash)")
        con.commit(); con.close()
        _set(phase="Done", pct=100, count=done, running=False, done=True)
    except Exception as e:
        _set(phase="", error=str(e), running=False, done=True)


def _count_lines(path):
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n


# ── browse ───────────────────────────────────────────────────────────────────────
def list_shaders(lib="", freq=None, q="", page=0, page_size=200):
    con = sqlite3.connect(DB_PATH)
    where, args = [], []
    if lib:
        where.append("lib=?"); args.append(lib)
    if freq is not None and freq != "":
        where.append("freq=?"); args.append(int(freq))
    if q:
        where.append("hash LIKE ?"); args.append(q.lower().strip() + "%")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    total = con.execute("SELECT COUNT(*) FROM shaders" + wsql, args).fetchone()[0]
    rows = con.execute(
        "SELECT lib, idx, freq, hash, size FROM shaders" + wsql + " ORDER BY lib, idx LIMIT ? OFFSET ?",
        args + [page_size, page * page_size]).fetchall()
    con.close()
    return {
        "total": total, "page": page, "page_size": page_size,
        "rows": [{"lib": l, "idx": i, "freq": f, "freq_name": FREQ_NAMES.get(f, str(f)),
                  "hash": h, "size": s} for (l, i, f, h, s) in rows],
    }


# ── extract + disassemble one shader ──────────────────────────────────────────────
def disasm(lib, idx):
    if not tools_ok():
        return {"ok": False, "error": "shader tools not found under Tools/shaders"}
    tmp = tempfile.mkdtemp(prefix="atelier_sh_")
    blob_path = os.path.join(tmp, "shader.bin")
    try:
        cmd = [RETOC, "extract-shader", *_containers(), "-l", lib, "-s", str(idx), "-o", blob_path]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0 or not os.path.isfile(blob_path):
            return {"ok": False, "error": (r.stderr or r.stdout or "extract failed").strip().splitlines()[-1]}
        data = open(blob_path, "rb").read()
        # UE FShaderCode wrapper -> DXBC container inside.
        pos = data.find(b"DXBC")
        if pos < 0:
            return {"ok": False, "error": "no DXBC container in shader blob"}
        size = struct.unpack_from("<I", data, pos + 24)[0]
        dxbc = data[pos:pos + size]
        dxbc_path = os.path.join(tmp, "shader.dxbc")
        open(dxbc_path, "wb").write(dxbc)
        d = subprocess.run([DXC, "-dumpbin", dxbc_path], capture_output=True, text=True,
                           cwd=SHADER_TOOLS, creationflags=CNW)
        text = d.stdout or ""
        if not text.strip():
            return {"ok": False, "error": (d.stderr or "dxc produced no output").strip()}
        props = _parse_properties(text)
        props["dxbc_size"] = len(dxbc)
        return {"ok": True, "disasm": text, "properties": props,
                "meta": {"stage": props["stage"], "entry": props["entry"], "dxbc_size": len(dxbc)}}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _dxbc(data):
    """Locate the DXBC container inside a UE FShaderCode-wrapped blob. Returns (pos, size)."""
    pos = data.find(b"DXBC")
    if pos < 0:
        return None, None
    size = struct.unpack_from("<I", data, pos + 24)[0]
    return pos, size


_FLOAT_RE = re.compile(r"float (0x[0-9A-Fa-f]{16}|-?\d+\.\d+e[+-]\d+|-?\d+(?:\.\d+)?)")


def edit_constants(lib, idx):
    """Scan a shader for float constants that are uniquely byte-locatable in the DXIL (from the
    disassembly) so the UI can list them as editable properties. Offset is relative to DXBC start."""
    if not tools_ok():
        return {"ok": False, "error": "shader tools not found"}
    tmp = tempfile.mkdtemp(prefix="atelier_shc_")
    blob_path = os.path.join(tmp, "shader.bin")
    try:
        r = subprocess.run([RETOC, "extract-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-o", blob_path], capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0 or not os.path.isfile(blob_path):
            return {"ok": False, "error": (r.stderr or "extract failed").strip().splitlines()[-1]}
        data = open(blob_path, "rb").read()
        pos, size = _dxbc(data)
        if pos is None:
            return {"ok": False, "error": "no DXBC container"}
        dxbc = data[pos:pos + size]
        open(os.path.join(tmp, "c.dxbc"), "wb").write(dxbc)
        dis = subprocess.run([DXC, "-dumpbin", os.path.join(tmp, "c.dxbc")], capture_output=True,
                             text=True, cwd=SHADER_TOOLS, creationflags=CNW).stdout

        by_off = {}
        # 1) Constants actually USED in the code (float immediates from the disassembly), located at
        #    their real byte offsets. These are the meaningful, impactful values (marked used=True).
        for m in _FLOAT_RE.finditer(dis):
            s = m.group(1)
            try:
                v = (struct.unpack("<d", struct.pack("<Q", int(s, 16)))[0]
                     if s.startswith("0x") else float(s))
            except Exception:
                continue
            if v == 0.0 or not (1e-4 <= abs(v) <= 1e7):
                continue                       # 0.0 (all-zero bytes) matches everywhere — skip
            b = struct.pack("<f", v)
            start = 0
            while True:
                o = dxbc.find(b, start)
                if o < 0:
                    break
                by_off[o] = {"offset": o, "value": round(v, 6), "used": True}
                start = o + 1
        # 2) Other plausible float32 constants in the bytecode (4-byte aligned), so there's plenty to
        #    work with. Marked used=False — best-effort, but real byte locations.
        for off in range(0, len(dxbc) - 3, 4):
            if off in by_off:
                continue
            v = struct.unpack_from("<f", dxbc, off)[0]
            if v == v and abs(v) != float("inf") and 1e-3 <= abs(v) <= 1e6:
                by_off[off] = {"offset": off, "value": round(v, 6), "used": False}

        consts = sorted(by_off.values(), key=lambda c: (not c["used"], c["offset"]))
        return {"ok": True, "constants": consts[:800],
                "used_count": sum(1 for c in consts if c["used"])}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def build_shader_mod(lib, idx, edits, mod_name=""):
    """Phase-4 round-trip: apply constant edits to a shader and produce an override mod
    (.pak/.ucas/.utoc) in the mods folder. extract -> patch bytes -> retoc patch-shader
    (rebuild loose library) -> retoc pack. edits = [{offset, value}] (offset relative to DXBC)."""
    if not tools_ok():
        return {"ok": False, "error": "shader tools not found"}
    from atelier.config import get_mods_folder
    import shutil
    tmp = tempfile.mkdtemp(prefix="atelier_shmod_")
    try:
        blob_path = os.path.join(tmp, "shader.bin")
        r = subprocess.run([RETOC, "extract-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-o", blob_path], capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0 or not os.path.isfile(blob_path):
            return {"ok": False, "error": (r.stderr or "extract failed").strip().splitlines()[-1]}
        data = bytearray(open(blob_path, "rb").read())
        pos, size = _dxbc(data)
        if pos is None:
            return {"ok": False, "error": "no DXBC container"}
        n = 0
        for e in edits or []:
            off = int(e["offset"]); val = float(e["value"])
            if 0 <= off <= size - 4:
                struct.pack_into("<f", data, pos + off, val); n += 1
        open(blob_path, "wb").write(data)

        stage = os.path.join(tmp, "stage")
        r = subprocess.run([RETOC, "patch-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-b", blob_path, "-o", stage], capture_output=True, text=True,
                           cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "patch-shader failed").strip().splitlines()[-1]}

        modout = os.path.join(tmp, "mod")
        r = subprocess.run([RETOC, "pack", stage, "-o", modout], capture_output=True, text=True,
                           cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "pack failed").strip().splitlines()[-1]}

        triple = [f for f in glob.glob(os.path.join(modout, "*"))
                  if f.lower().endswith((".pak", ".ucas", ".utoc"))]
        if not triple:
            return {"ok": False, "error": "pack produced no mod files"}

        dest = get_mods_folder() or os.path.join(CACHE, "shader_mods")
        os.makedirs(dest, exist_ok=True)
        base = _sanitize(mod_name) or f"AtelierShader_{_short_lib(lib)}_{idx}"
        out_files = []
        for f in triple:
            dst = os.path.join(dest, base + "_P" + os.path.splitext(f)[1])
            shutil.copy2(f, dst); out_files.append(dst)
        return {"ok": True, "edits_applied": n, "mod_dir": dest,
                "files": [os.path.basename(f) for f in out_files]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def disassemble_ir(lib, idx):
    """Extract a shader and disassemble it to editable LLVM IR text (the real 'raw code segments')."""
    if not tools_ok():
        return {"ok": False, "error": "shader tools not found"}
    import shutil
    tmp = tempfile.mkdtemp(prefix="atelier_shir_")
    try:
        bp = os.path.join(tmp, "s.bin")
        r = subprocess.run([RETOC, "extract-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-o", bp], capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0 or not os.path.isfile(bp):
            return {"ok": False, "error": (r.stderr or "extract failed").strip().splitlines()[-1]}
        data = open(bp, "rb").read()
        pos, size = _dxbc(data)
        if pos is None:
            return {"ok": False, "error": "no DXBC container"}
        from atelier.handlers import dxc_ir
        ir = dxc_ir.disassemble(data[pos:pos + size]).decode("utf-8", "replace")
        return {"ok": True, "ir": ir, "lines": ir.count("\n") + 1}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_shader_mod_ir(lib, idx, ir_text, mod_name=""):
    """Phase-4 REAL edit: assemble edited LLVM IR -> DXBC -> splice into the UE wrapper -> patch-shader
    -> pack -> override mod. Returns {ok, signed, files, mod_dir, note}."""
    if not tools_ok():
        return {"ok": False, "error": "shader tools not found"}
    from atelier.config import get_mods_folder
    from atelier.handlers import dxc_ir
    import shutil
    tmp = tempfile.mkdtemp(prefix="atelier_shirmod_")
    try:
        try:
            new_dxbc, signed = dxc_ir.assemble((ir_text or "").encode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": "assemble failed: " + str(e)}

        bp = os.path.join(tmp, "s.bin")
        r = subprocess.run([RETOC, "extract-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-o", bp], capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0 or not os.path.isfile(bp):
            return {"ok": False, "error": (r.stderr or "extract failed").strip().splitlines()[-1]}
        data = open(bp, "rb").read()
        pos, size = _dxbc(data)
        if pos is None:
            return {"ok": False, "error": "no DXBC container"}
        # splice: [UE header][new DXBC (self-sized)][UE trailer]
        open(bp, "wb").write(data[:pos] + new_dxbc + data[pos + size:])

        stage = os.path.join(tmp, "stage")
        r = subprocess.run([RETOC, "patch-shader", *_containers(), "-l", lib, "-s", str(idx),
                            "-b", bp, "-o", stage], capture_output=True, text=True, cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "patch-shader failed").strip().splitlines()[-1]}
        modout = os.path.join(tmp, "mod")
        r = subprocess.run([RETOC, "pack", stage, "-o", modout], capture_output=True, text=True,
                           cwd=SHADER_TOOLS, creationflags=CNW)
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "pack failed").strip().splitlines()[-1]}
        triple = [f for f in glob.glob(os.path.join(modout, "*"))
                  if f.lower().endswith((".pak", ".ucas", ".utoc"))]
        if not triple:
            return {"ok": False, "error": "pack produced no mod files"}

        dest = get_mods_folder() or os.path.join(CACHE, "shader_mods")
        os.makedirs(dest, exist_ok=True)
        base = _sanitize(mod_name) or f"AtelierShader_{_short_lib(lib)}_{idx}"
        out_files = []
        for f in triple:
            dst = os.path.join(dest, base + "_P" + os.path.splitext(f)[1])
            shutil.copy2(f, dst); out_files.append(os.path.basename(dst))
        note = ("" if signed else
                "Shader is UNSIGNED (bundled dxil.dll can't sign). Test in-game — if it fails to "
                "load, signing is the remaining step.")
        return {"ok": True, "signed": signed, "mod_dir": dest, "files": out_files, "note": note}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _sanitize(name):
    return re.sub(r"[^A-Za-z0-9_-]", "", (name or "").strip().replace(" ", "_"))


_RES_TYPE = re.compile(r"\b(cbuffer|texture|sampler|UAV|byteaddress|structured|typed)\b", re.I)


def _parse_properties(text):
    """Pull the shader's interface out of the dxc disassembly: I/O signatures + resource bindings
    (constant buffers = the param banks, textures t#, samplers s#). This is what the Properties
    panel scrolls through. UE ships these shaders with reflection stripped, so there are no named
    cbuffer members — params bind by register/offset (surfaced here; per-value edit = Phase 4)."""
    props = {"stage": "", "entry": "", "input": [], "output": [], "resources": []}
    section = None
    in_table = False
    for raw in text.splitlines():
        if not raw.startswith(";"):
            section = None
            in_table = False
            continue
        st = raw[1:].strip()
        if not st:
            # a blank comment line ends the current table (tables are contiguous rows).
            if in_table:
                section, in_table = None, False
            continue
        low = st.lower()

        if low.endswith("shader") and not props["stage"]:
            props["stage"] = st
        elif low.startswith("entryfunctionname:"):
            props["entry"] = st.split(":", 1)[1].strip()
        elif low.startswith("input signature"):
            section, in_table = "input", False
        elif low.startswith("output signature"):
            section, in_table = "output", False
        elif low.startswith("resource binding"):
            section, in_table = "resources", False
        elif section and st and set(st) <= set("- "):
            in_table = True
        elif section and in_table and st:
            if "Name" in st and ("Format" in st or "Bind" in st):
                continue
            cols = st.split()
            if section in ("input", "output") and len(cols) >= 6:
                props[section].append({"name": cols[0], "mask": cols[2], "register": cols[3],
                                       "sysvalue": cols[4], "format": cols[5]})
            elif section == "resources" and len(cols) >= 5:
                # cols = [Name?, Type, Format, Dim, ID, HLSL-Bind, Count]; Name is often blank →
                # dropped by split(). Bind is the 2nd-to-last col, ID the 3rd-to-last.
                mt = _RES_TYPE.search(st)
                typ = mt.group(1).lower() if mt else "?"
                bind = cols[-2]
                rid = cols[-3]
                name = cols[0] if not _RES_TYPE.match(cols[0]) else ""
                props["resources"].append({"name": name or rid, "type": typ,
                                           "bind": bind, "fmt": cols[-5] if len(cols) >= 5 else ""})
    return props
