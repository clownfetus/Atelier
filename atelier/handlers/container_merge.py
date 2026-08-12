"""Merge N finished MR IoStore containers (.utoc/.ucas) into ONE, at the container level.

This does NOT re-pack or re-serialize any package. It reads the FINISHED chunks each builder already
produced, unions the chunk tables, rebuilds the .ucas with uncompressed blocks (exactly like
world.build_world_mod already does for a single level), and serializes a fresh directory index.

Because IoStore resolves overrides by FIoChunkId (not by path), and because the level's package bytes
are copied verbatim (byte-identical read-back verified), this cannot reintroduce the level round-trip
corruption. It runs strictly AFTER build_world_mod / create_mod_iostore — it never changes how a world
file is edited or built.
"""
import struct, hashlib
from collections import OrderedDict
import io_lib

INV = 0xFFFFFFFF

def _wstr(s):
    if s == "":
        return struct.pack("<i", 0)
    b = s.encode("latin1")
    return struct.pack("<i", len(b) + 1) + b + b"\x00"

def serialize_dir_index(rel_entries, mount="../../../"):
    """Inverse of io_lib.parse_dir_index. rel_entries: [(relpath, userdata)], relpath mount-relative
    and '/'-separated (e.g. 'Engine/EngineSky/T_Sky_Stars.uasset'). Reproduces create_mod_iostore's
    collapsed layout: root dir + one sibling dir per unique directory path (the whole dir path is one
    string). Path text is cosmetic for loading (chunk id drives resolution); structure must be valid."""
    strings = []; sidx = {}
    def sid(s):
        if s not in sidx:
            sidx[s] = len(strings); strings.append(s)
        return sidx[s]
    groups = OrderedDict()                       # dirpath -> [(filename, userdata)]
    for path, ud in rel_entries:
        d, _, f = path.rpartition("/")
        groups.setdefault(d, []).append((f, ud))
    dirs = []; files = []
    def add_files(file_list):
        if not file_list:
            return INV
        first = len(files)
        for i, (fn, ud) in enumerate(file_list):
            nxt = len(files) + 1 if i < len(file_list) - 1 else INV
            files.append((sid(fn), nxt, ud))
        return first
    dirs.append(None)                            # root placeholder at index 0
    child_paths = [d for d in groups if d != ""]
    child_indices = []
    for dp in child_paths:
        child_indices.append(len(dirs))
        ff = add_files(groups[dp])
        dirs.append([sid(dp), INV, INV, ff])     # [name, firstchild, nextsib, firstfile]
    for i, idx in enumerate(child_indices):
        dirs[idx][2] = child_indices[i + 1] if i < len(child_indices) - 1 else INV
    root_firstchild = child_indices[0] if child_indices else INV
    root_firstfile = add_files(groups.get("", []))
    dirs[0] = [INV, root_firstchild, INV, root_firstfile]
    out = bytearray()
    out += _wstr(mount)
    out += struct.pack("<I", len(dirs))
    for name, fc, ns, ff in dirs:
        out += struct.pack("<IIII", name, fc, ns, ff)
    out += struct.pack("<I", len(files))
    for name, nx, ud in files:
        out += struct.pack("<III", name, nx, ud)
    out += struct.pack("<I", len(strings))
    for s in strings:
        out += _wstr(s)
    return bytes(out)

def _rel(path):
    return path[len("../../../"):] if path.startswith("../../../") else path.lstrip("/")

def merge_containers(pairs, out_base):
    """pairs: [(utoc_path, ucas_path), ...]. The first pair is the header/methods donor. Writes
    out_base.{utoc,ucas} (caller supplies the .pak marker). Returns a small stats dict.
    Safe to pass an input path as out_base — all chunk data is read into memory before writing."""
    tocs = [(io_lib.parse_toc(u), c) for (u, c) in pairs]
    base = tocs[0][0]
    CB = base.cblk_size
    chunk_ids = []; datas = []; metas = []; rel_entries = []
    seen = set()
    for t, ucas in tocs:
        idx_to_path = {idx: path for path, idx in io_lib.parse_dir_index(t)}
        for i in range(t.entry_count):
            cid = t.chunk_ids[i]
            if cid in seen:                                  # identical chunk id -> keep first
                continue
            seen.add(cid)
            new_idx = len(chunk_ids)
            chunk_ids.append(cid)
            datas.append(io_lib.read_chunk(t, ucas, i))
            metas.append(bytearray(t.meta[i]))
            p = idx_to_path.get(i)
            if p is not None:
                rel_entries.append((_rel(p), new_idx))
    N = len(chunk_ids)
    ucas = bytearray(); blocks = []; offlen = []
    def split(dd):
        return [dd[x:x + CB] for x in range(0, len(dd), CB)] or [b""]
    for i in range(N):
        dat = datas[i]
        offlen.append((len(blocks) * CB, len(dat)))
        for piece in split(dat):
            blocks.append((len(ucas), len(piece), len(piece), 0))
            ucas += piece
        metas[i][:20] = hashlib.sha1(dat).digest()
    dir_blob = serialize_dir_index(rel_entries)
    hdr = bytearray(base.buf[:144])
    struct.pack_into("<I", hdr, 24, N)                       # entry_count      (b+4)
    struct.pack_into("<I", hdr, 28, len(blocks))             # cblk_count       (b+8)
    struct.pack_into("<I", hdr, 48, len(dir_blob))           # dir_index_size   (b+28)
    struct.pack_into("<I", hdr, 84, 0)                       # phash_seed_count (b+64)
    struct.pack_into("<I", hdr, 96, 0)                       # chunks_wo_phash  (b+76)
    buf = bytearray(hdr)
    for cid in chunk_ids:
        buf += cid
    for o, l in offlen:
        buf += o.to_bytes(5, "big") + l.to_bytes(5, "big")
    for bo, cs, us, mi in blocks:
        buf += bo.to_bytes(5, "little") + cs.to_bytes(3, "little") + us.to_bytes(3, "little") + bytes([mi])
    buf += base.buf[base.off_methods: base.off_methods + base.cm_name_count * base.cm_name_len]
    buf += dir_blob
    for i in range(N):
        buf += bytes(metas[i])
    open(out_base + ".utoc", "wb").write(bytes(buf))
    open(out_base + ".ucas", "wb").write(bytes(ucas))
    return {"chunks": N, "blocks": len(blocks), "dir_entries": len(rel_entries)}
