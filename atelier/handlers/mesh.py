"""SkeletalMesh geometry editing: per-section deformation and triangle-count edits.

UAssetTool parses a SkeletalMesh export only as far as the FReferenceSkeleton (see
SkeletalMeshExport.cs) and keeps everything past it as one opaque `RemainingExtraData`
blob, so there is no existing path to the geometry. This module reads that blob directly.

WHAT IT CAN DO: move vertices (proportion editing) and change how many triangles a
section draws. Both are byte-for-byte in-place patches -- no buffer grows or shrinks, so
export SerialSize, the bulk-data descriptors and the ImportMap are all untouched. That is
what makes this safe to ship through the ordinary create_mod_iostore path with no extra
bookkeeping (contrast with the world builder, which must patch vanilla chunks in place for
exactly the same reason -- see the comment in texture.py::build_mod).

WHAT IT CANNOT DO: change the VERTEX count. Vertices are stored in parallel buffers
(positions, packed tangents, UVs, colors, skin weights) that are concatenated one after
another inside the streamed blob, so adding or removing vertices resizes every buffer and
shifts everything downstream. That needs a full re-serialisation and is not implemented.
Removing geometry is still possible via `tri_fraction`/`hide`, which only rewrites a
section's NumTriangles.

BINARY LAYOUT (Marvel Rivals, UE 5.3, verified against SK_10290_1029304)

  Export "Extras" blob, in order:
    FStripDataFlags(2), FBoxSphereBounds(7 doubles, LWC), FSkeletalMaterial[],
    FReferenceSkeleton, bCooked(u32), LODCount(u32), then per-LOD render data.

  FSkelMeshRenderSection -- every offset is relative to the BoneMap count field (`bm`),
  which is the only field distinctive enough to anchor on reliably:
    bm-33 u16 magic == 1        bm-31 u16 MaterialIndex
    bm-29 u32 BaseIndex         bm-25 u32 NumTriangles
    bm-8  u32 BaseVertexIndex   bm    u32 BoneMapCount, then u16[BoneMapCount]
    then  u32 NumVertices, u32 MaxBoneInfluences, i16 CorrespondClothAssetIndex == -1

  FPositionVertexBuffer: header is FOUR u32 -- Stride(12), NumVertices, then the inner
  TStaticMeshVertexData's ElementSize(12) and Count -- so the float payload begins at
  +16. Reading it at +8 still yields a plausible-looking bounding box because the values
  are merely rotated between components; it is wrong. Positions are UE centimetres, Z up.

  The lowest-detail LOD is inline in the .uexp; the higher-detail LODs stream from .ubulk.
"""
import json
import os
import re
import struct

import numpy as np

POS_STRIDE = 12
POS_HEADER = 16          # Stride, NumVertices, ElementSize, Count -- payload follows


# ── parsing ───────────────────────────────────────────────────────────────────

def _bonemap_at(d, o):
    """Validate an FSkelMeshRenderSection whose BoneMap count field sits at `o`."""
    if o < 33 or o + 4 > len(d):
        return None
    (c,) = struct.unpack_from("<I", d, o)
    if not 1 <= c <= 512:
        return None
    end = o + 4 + c * 2
    if end + 10 > len(d):
        return None
    if max(struct.unpack_from("<%dH" % c, d, o + 4)) >= 4096:
        return None
    nverts, max_infl = struct.unpack_from("<II", d, end)
    if not (1 <= nverts <= 500000 and 1 <= max_infl <= 12):
        return None
    if struct.unpack_from("<h", d, end + 8)[0] != -1:      # CorrespondClothAssetIndex
        return None
    magic, mat = struct.unpack_from("<HH", d, o - 33)
    if magic != 1 or mat >= 32:
        return None
    base_index, num_tris = struct.unpack_from("<II", d, o - 29)
    (base_vertex,) = struct.unpack_from("<I", d, o - 8)
    return {"bm": o, "mat": mat, "base_index": base_index, "num_tris": num_tris,
            "base_vertex": base_vertex, "num_verts": nverts, "max_infl": max_infl,
            "tris_off": o - 25, "after": end + 10,
            # Field byte offsets, for patching VALUES in-place without resizing the record.
            "base_index_off": o - 29, "base_vertex_off": o - 8, "num_verts_off": end,
            "bonemap_off": o + 4, "bonemap_count": c}


def find_sections(uexp):
    """All FSkelMeshRenderSection records in the .uexp, in LOD order."""
    out, o = [], 0
    while o < len(uexp) - 48:
        hit = _bonemap_at(uexp, o)
        if hit:
            out.append(hit)
            o = hit["after"]
        else:
            o += 1
    return out


def find_position_buffers(blob):
    """Offsets of every FPositionVertexBuffer payload in `blob`, as {num_verts: payload_off}."""
    found, o = {}, 0
    while True:
        i = blob.find(b"\x0c\x00\x00\x00", o)
        if i < 0 or i + POS_HEADER > len(blob):
            break
        o = i + 1
        stride, n, elem, n2 = struct.unpack_from("<IIII", blob, i)
        if stride != 12 or elem != 12 or n != n2 or not 100 < n < 3_000_000:
            continue
        if i + POS_HEADER + n * POS_STRIDE > len(blob):
            continue
        found.setdefault(n, i + POS_HEADER)
    return found


# ── name table, materials, skeleton ────────────────────────────────────────────
# UAssetTool parses a SkeletalMesh export's Extras only as far as the FReferenceSkeleton
# (SkeletalMeshExport.cs), and never resolves FName -> string at all -- the .uasset's own
# name table isn't exposed anywhere we can reach from Python. Parsed independently here.

def _try_name_entry(d, o):
    """One legacy-uasset NameMap entry: int32 length (positive=ASCII incl. null,
    negative=UTF-16LE incl. null, in code units) + a uint32 hash. Confirmed against a
    known name ('MorphTarget') in SK_10290_1029304.uasset."""
    if o + 4 > len(d):
        return None
    (n,) = struct.unpack_from("<i", d, o)
    if n == 0 or not -1024 <= n <= 1024:
        return None
    if n > 0:
        if o + 4 + n + 4 > len(d):
            return None
        s = d[o + 4:o + 4 + n]
        if s[-1] != 0 or any(c == 0 for c in s[:-1]):
            return None
        if not all(32 <= c < 127 or c == 9 for c in s[:-1]):
            return None
        return {"text": s[:-1].decode("ascii"), "next": o + 4 + n + 4}
    m = -n
    if o + 4 + m * 2 + 4 > len(d):
        return None
    raw = d[o + 4:o + 4 + m * 2]
    if raw[-2:] != b"\x00\x00":
        return None
    try:
        text = raw[:-2].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if not text or "\x00" in text:
        return None
    return {"text": text, "next": o + 4 + m * 2 + 4}


def find_name_table(uasset, min_run=20):
    """Locate the legacy-uasset NameMap by finding the longest unbroken run of valid
    entries, rather than hand-parsing the whole versioned package header (custom version
    containers etc. are fragile to replicate). A long run of plausible length-prefixed
    strings essentially never occurs by chance. Returns (start_offset, names)."""
    best, best_start, o = None, None, 0
    while o < len(uasset) - 8:
        e = _try_name_entry(uasset, o)
        if not e:
            o += 1
            continue
        start, names, cur = o, [], o
        while True:
            e = _try_name_entry(uasset, cur)
            if not e:
                break
            names.append(e["text"])
            cur = e["next"]
        if len(names) >= min_run and (best is None or len(names) > len(best)):
            best, best_start = names, start
        o = cur if len(names) >= min_run else o + 1
    if best is None:
        raise ValueError("no NameMap found")
    return best_start, best


def _try_extras(d, o, limit):
    """Validate a candidate FSkeletalMaterial[] + FReferenceSkeleton starting at `o`.
    Requires the triple invariant a real RefSkeleton always satisfies -- RefBoneInfo count
    == RefBonePose count == NameToIndexMap count -- which essentially never holds by
    accident, so no header parsing is needed to locate the Extras section reliably."""
    start = o
    if o + 4 > limit:
        return None
    (count,) = struct.unpack_from("<I", d, o)
    if not 1 <= count <= 64:
        return None
    o += 4
    mats = []
    for _ in range(count):
        if o + 40 > limit:
            return None
        pkg_off = o                        # MaterialInterface: patched in place by meshgraft
        (pkg,) = struct.unpack_from("<i", d, o)
        if not -100000 < pkg < 100000:
            return None
        slot, imported = struct.unpack_from("<ii", d, o + 4), struct.unpack_from("<ii", d, o + 12)
        o += 4 + 8 + 8 + 20
        if o + 4 > limit:
            return None
        (ntag,) = struct.unpack_from("<I", d, o)
        if not 0 <= ntag <= 64:
            return None
        o += 4 + ntag * 8
        mats.append({"pkg_idx": pkg, "pkg_off": pkg_off,
                     "slot_name_idx": slot[0], "imported_slot_name_idx": imported[0]})
    if o + 4 > limit:
        return None
    (nbone,) = struct.unpack_from("<I", d, o)
    if not 8 <= nbone <= 8192:
        return None
    bones_off = o + 4
    bones_end = bones_off + nbone * 12
    if bones_end + 4 > limit:
        return None
    (npose,) = struct.unpack_from("<I", d, bones_end)
    if npose != nbone:
        return None
    pose_off = bones_end + 4
    pose_end = pose_off + nbone * 80          # FTransform: FQuat+FVector+FVector, LWC doubles
    if pose_end + 4 > limit:
        return None
    (nmap,) = struct.unpack_from("<I", d, pose_end)
    if nmap != nbone:
        return None
    return {"materials": mats, "n_bones": nbone, "bones_off": bones_off,
            "pose_off": pose_off, "skel_end": pose_end + 4 + nbone * 12}


def find_extras(uexp):
    """Locate materials + skeleton anywhere in the .uexp. Confirmed to produce exactly one
    match across the full 5.9MB SK_10290_1029304.uexp -- the triple-count invariant has no
    false positives in practice."""
    for o in range(len(uexp) - 8):
        r = _try_extras(uexp, o, len(uexp))
        if r:
            return r
    raise ValueError("no SkeletalMesh Extras (materials+skeleton) found")


def parse_skeleton(uexp, extras, names):
    """Bone hierarchy: name, parent index, and local rest-pose transform (translation,
    rotation as XYZW quaternion, scale) -- all doubles (LWC)."""
    bones = []
    o = extras["bones_off"]
    for i in range(extras["n_bones"]):
        idx, num = struct.unpack_from("<ii", uexp, o)
        (parent,) = struct.unpack_from("<i", uexp, o + 8)
        name = names[idx] if 0 <= idx < len(names) else f"<bone_{i}>"
        bones.append({"name": name, "number": num, "parent": parent})
        o += 12
    o = extras["pose_off"]
    for b in bones:
        qx, qy, qz, qw, tx, ty, tz, sx, sy, sz = struct.unpack_from("<10d", uexp, o)
        b["rotation"] = (qx, qy, qz, qw)
        b["translation"] = (tx, ty, tz)
        b["scale"] = (sx, sy, sz)
        o += 80
    return bones


def find_data_resource_map(uasset, ubulk_len):
    """Locate the .uasset's DataResourceMap (the DATA_RESOURCES mechanism -- same one
    the streaming-mip texture work uses, applied here to whole LOD blobs) by validating
    candidates against the one thing we can check independently: the entries' offsets must
    be contiguous starting at 0, and the last one must end EXACTLY at the real .ubulk
    length. Each entry: flags(u32), SerialOffset(i64), DuplicateOffset(i64)==-1,
    SerialSize(i64)==RawSize(i64), pad(u32)==0, LegacyBulkDataFlags(u32) -- 44 bytes."""
    for o in range(len(uasset) - 4):
        (n,) = struct.unpack_from("<I", uasset, o)
        if not 1 <= n <= 8:
            continue
        e, prev_end, ok = o + 4, 0, True
        for _ in range(n):
            if e + 44 > len(uasset):
                ok = False; break
            (off,) = struct.unpack_from("<q", uasset, e + 4)
            (dup,) = struct.unpack_from("<q", uasset, e + 12)
            (size,) = struct.unpack_from("<q", uasset, e + 20)
            (raw,) = struct.unpack_from("<q", uasset, e + 28)
            (pad,) = struct.unpack_from("<I", uasset, e + 36)
            if off != prev_end or size != raw or size <= 0 or dup != -1 or pad != 0:
                ok = False; break
            prev_end = off + size
            e += 44
        if ok and prev_end == ubulk_len:
            return o
    return None


def find_last_export_serial_size(uasset, uexp_len):
    """Locate the export table's (SerialSize:i64, SerialOffset:i64) pair for the LAST
    export (SkeletalMesh is always last here, confirmed by every export's data ending
    exactly at .uexp's end). Legacy FObjectExport serialises these as adjacent int64
    fields (Export.cs), so the self-consistent invariant for the LAST export is
    SerialOffset + SerialSize == len(uasset) + len(uexp) - 4 (the 4-byte package tag) --
    verified against SK_10290_1029304 (0x54CA + 5963613 == 19180 + 5966143 - 4)."""
    target = len(uasset) + uexp_len - 4
    for o in range(len(uasset) - 16):
        (size,) = struct.unpack_from("<q", uasset, o)
        (off,) = struct.unpack_from("<q", uasset, o + 8)
        if size > 0 and off >= len(uasset) and off + size == target:
            return o
    return None


def find_bulk_data_start_offset(uasset, uexp_len, search_limit):
    """Locate the package summary's BulkDataStartOffset (i64): with no trailing bulk
    section inside .uexp (real bulk data lives in .ubulk), it equals the same
    end-of-package-data value as the last export -- len(uasset)+len(uexp)-4. Restricted to
    before the name table (`search_limit`), since header fields all precede it and a random
    8-byte match inside string data further in the file is otherwise possible."""
    target = len(uasset) + uexp_len - 4
    for o in range(0, min(search_limit, len(uasset) - 8)):
        (v,) = struct.unpack_from("<q", uasset, o)
        if v == target:
            return o
    return None


def resolve_materials(mats, names):
    for m in mats:
        m["slot_name"] = names[m["slot_name_idx"]] if 0 <= m["slot_name_idx"] < len(names) else None
        m["imported_slot_name"] = (names[m["imported_slot_name_idx"]]
                                   if 0 <= m["imported_slot_name_idx"] < len(names) else None)
    return mats


class Mesh:
    """A parsed SkeletalMesh: sections grouped per LOD, each LOD bound to its position buffer."""

    def __init__(self, base):
        self.base = base
        self.uexp = bytearray(open(base + ".uexp", "rb").read())
        ub = base + ".ubulk"
        self.ubulk = bytearray(open(ub, "rb").read()) if os.path.exists(ub) else bytearray()

        pos = dict(find_position_buffers(bytes(self.uexp)))
        for n, off in find_position_buffers(bytes(self.ubulk)).items():
            pos.setdefault(n, None)
            pos[n] = ("ubulk", off)
        for n in list(pos):
            if not isinstance(pos[n], tuple):
                pos[n] = ("uexp", pos[n])

        # Group sections into LODs: sections are stored in LOD order and a LOD's sections
        # partition its position buffer exactly, so close a group the moment the running
        # vertex total equals one of the buffer sizes we found.
        self.lods, run, grp = [], 0, []
        for s in find_sections(self.uexp):
            grp.append(s)
            run += s["num_verts"]
            if run in pos:
                where, off = pos.pop(run)
                self.lods.append({"sections": grp, "num_verts": run,
                                  "buf": where, "pos_off": off})
                run, grp = 0, []
        for lod in self.lods:
            self._locate_index_buffer(lod)
            self._locate_vertex_buffers(lod)

        ua = base + ".uasset"
        self.names, self.materials, self.bones = [], [], []
        self.uasset = bytearray()
        self._drm_off = self._drm_entries = self._drm_map = None
        self._export_ss_off = self._bulk_start_off = None
        if os.path.exists(ua):
            self.uasset = bytearray(open(ua, "rb").read())
            name_start, self.names = find_name_table(bytes(self.uasset))
            extras = find_extras(bytes(self.uexp))
            self.materials = resolve_materials(extras["materials"], self.names)
            self.bones = parse_skeleton(self.uexp, extras, self.names)
            self._index_bookkeeping(name_start)

    def _index_bookkeeping(self, name_start):
        """Locate everything Mesh.rebuild_lod needs to patch on a resize: the
        DataResourceMap (streamed-LOD blob sizes/offsets), the last export's SerialSize,
        and the package summary's BulkDataStartOffset. All found by self-validating
        structural search, not hardcoded offsets -- see each finder's docstring."""
        self._export_ss_off = find_last_export_serial_size(bytes(self.uasset), len(self.uexp))
        self._bulk_start_off = find_bulk_data_start_offset(
            bytes(self.uasset), len(self.uexp), name_start)

        ubulk_len = len(self.ubulk)
        self._drm_off = find_data_resource_map(bytes(self.uasset), ubulk_len) if ubulk_len else None
        self._drm_entries = []
        if self._drm_off is not None:
            (n,) = struct.unpack_from("<I", self.uasset, self._drm_off)
            e = self._drm_off + 4
            for _ in range(n):
                self._drm_entries.append({"rec_off": e})
                e += 44
        # Streamed LODs (buf == "ubulk"), in LOD order, map 1:1 onto DataResourceMap
        # entries in order -- confirmed for this asset (2 streamed LODs, 2 entries,
        # entry[i].SerialOffset chain matches LOD i's position in .ubulk exactly).
        self._drm_map = {}
        streamed = [i for i, l in enumerate(self.lods) if l["buf"] == "ubulk"]
        for entry_i, lod_i in enumerate(streamed):
            if entry_i < len(self._drm_entries):
                self._drm_map[lod_i] = entry_i
        for i, lod in enumerate(self.lods):
            self._locate_tail(i, lod)

    def _lod_blob_end(self, lod_index, lod):
        """A LOD blob's exclusive end offset within its file: from the DataResourceMap for
        a streamed LOD, or the .uexp's 4-byte package tag for the inline one."""
        if lod["buf"] == "ubulk":
            rec = self._drm_entries[self._drm_map[lod_index]]["rec_off"]
            (off,) = struct.unpack_from("<q", self.uasset, rec + 4)
            (size,) = struct.unpack_from("<q", self.uasset, rec + 20)
            return off + size
        return len(self.uexp) - 4

    def _locate_tail(self, lod_index, lod):
        """Split the post-ColorVertexBuffer tail into (prefix, morph block, suffix).

        Per CUE4Parse FStaticLODModel.SerializeStreamedData the tail is, in order:
        FSkinWeightProfilesData (TMap), ray-tracing data, an int32
        bSerializeCompressedMorphTargets gate, the morph buffers if that gate is set,
        FSkeletalMeshAttributeVertexBuffer map, and (newer engine versions only) a
        half-edge buffer. Verified exactly against this asset: LOD0's tail decomposes to
        4 + 4 + 4 + 200124 + 4 == 200140 bytes with nothing left over.

        Rather than re-synthesising these structures -- which is how the first attempt
        broke, by writing a plausible-looking 32 zero bytes when the real empty tail here
        is 16 and the engine rejected the leftover slack with a serial-size mismatch --
        the prefix and suffix are kept as raw bytes and replayed verbatim on rebuild. That
        also makes the writer agnostic to engine-version-dependent trailing structures
        (half-edge etc.) that this asset happens not to have."""
        blob = self._blob(lod)
        end = self._lod_blob_end(lod_index, lod)
        start = o = lod["tail_off"]
        (swp,) = struct.unpack_from("<I", blob, o); o += 4
        if swp:
            raise NotImplementedError("SkinWeightProfiles present -- not handled by rebuild")
        (rt,) = struct.unpack_from("<I", blob, o); o += 4 + rt
        prefix_end = o
        (has_morphs,) = struct.unpack_from("<i", blob, o); o += 4
        if has_morphs:
            (nwords,) = struct.unpack_from("<i", blob, o); o += 4 + nwords * 4
            for _ in range(2):                                    # Min/MaximumValuePerMorph
                (c,) = struct.unpack_from("<i", blob, o); o += 4 + c * 16
            for _ in range(2):                                    # BatchStartOffset/BatchesPerMorph
                (c,) = struct.unpack_from("<i", blob, o); o += 4 + c * 4
            o += 12                                               # NumTotalBatches + 2 precisions
        lod["tail_prefix"] = bytes(blob[start:prefix_end])
        lod["tail_suffix"] = bytes(blob[o:end])
        lod["had_morphs"] = bool(has_morphs)

    def _locate_vertex_buffers(self, lod):
        """Walk the fixed CUE4Parse serialisation order forward from the (already-known)
        end of the position buffer: FStaticMeshVertexBuffer (tangents, UVs), then
        FSkinWeightVertexBuffer (+ its lookup buffer), then FColorVertexBuffer. Every
        extent chains exactly into the next header -- confirmed as a byte-identical T0
        round-trip on this mesh's LOD0 and LOD1 blobs."""
        blob = self._blob(lod)
        o = lod["pos_off"] + lod["num_verts"] * POS_STRIDE
        o += 2                                            # FStaticMeshVertexBuffer StripFlags
        ntc, nv, full_uv, hi_tan = struct.unpack_from("<IIII", blob, o); o += 16
        lod["num_tex_coords"], lod["full_prec_uv"], lod["hi_prec_tangent"] = ntc, full_uv, hi_tan
        tan_esz, tan_cnt = struct.unpack_from("<II", blob, o); o += 8
        lod["tan_off"] = o; o += tan_esz * tan_cnt
        uv_esz, uv_cnt = struct.unpack_from("<II", blob, o); o += 8
        lod["uv_off"] = o; o += uv_esz * uv_cnt
        o += 2                                            # FSkinWeightVertexBuffer StripFlags
        sw_var, sw_maxinf, sw_nbones, sw_nv, sw_16i, sw_16w = struct.unpack_from("<IIIIII", blob, o)
        o += 24
        lod["max_bone_influences"] = sw_maxinf
        lod["variable_bones"] = bool(sw_var)
        lod["bone_index_16"] = bool(sw_16i)
        lod["bone_weight_16"] = bool(sw_16w)
        sw_esz, sw_cnt = struct.unpack_from("<II", blob, o); o += 8
        lod["sw_off"], lod["sw_esz"], lod["sw_cnt"] = o, sw_esz, sw_cnt
        o += sw_esz * sw_cnt
        o += 2                                            # lookup StripFlags
        o += 4                                            # NumLookupVertices
        lk_esz, lk_cnt = struct.unpack_from("<II", blob, o); o += 8
        lod["lookup_off"], lod["lookup_esz"], lod["lookup_cnt"] = o, lk_esz, lk_cnt
        o += lk_esz * lk_cnt
        o += 2                                            # FColorVertexBuffer StripFlags
        col_stride, col_nv = struct.unpack_from("<II", blob, o); o += 8
        if col_nv > 0:
            col_esz, col_cnt = struct.unpack_from("<II", blob, o); o += 8
            lod["col_off"] = o; o += col_esz * col_cnt
        else:
            lod["col_off"] = None
        lod["tail_off"] = o

    def _locate_index_buffer(self, lod):
        """The index buffer sits immediately before the position buffer, so its payload
        start is derivable rather than searched for. Index width is per-LOD: a decimated
        LOD that fits under 65536 vertices is cooked with 16-bit indices, so the stride
        must be probed, not assumed. Both candidates are confirmed against the buffer's
        own 11-byte header (`01 00 <size>`, u32 ElementSize, u32 Count)."""
        blob = self._blob(lod)
        n_idx = sum(s["num_tris"] for s in lod["sections"]) * 3
        hdr = lod["pos_off"] - POS_HEADER
        lod["n_indices"] = n_idx
        for stride in (4, 2):
            start = hdr - n_idx * stride
            if start < 8:
                continue
            elem, count = struct.unpack_from("<II", blob, start - 8)
            if elem == stride and count == n_idx:
                lod["idx_off"], lod["idx_stride"] = start, stride
                return
        raise ValueError("could not locate index buffer for LOD")

    def _blob(self, lod):
        return self.ubulk if lod["buf"] == "ubulk" else self.uexp

    def positions(self, lod):
        n = lod["num_verts"]
        return np.frombuffer(bytes(self._blob(lod)), "<f4",
                             n * 3, lod["pos_off"]).reshape(n, 3)

    def write_positions(self, lod, lo, hi, verts):
        """Write vertices [lo, hi) of a LOD back into its position buffer."""
        off = lod["pos_off"] + lo * POS_STRIDE
        struct.pack_into("<%df" % verts.size, self._blob(lod), off,
                         *verts.astype("<f4").ravel())

    def degenerate_triangles(self, lod, sec, keep_fraction):
        """Hide the tail of a section's geometry by collapsing its triangles to a single
        repeated vertex index. The GPU discards zero-area triangles, so the geometry
        disappears with no structural change at all.

        Do NOT hide geometry by lowering FSkelMeshRenderSection::NumTriangles instead.
        That reads as the obvious edit and it packs fine, but the game crashes on load
        with EXCEPTION_ACCESS_VIOLATION: the cooked section count feeds the GPU skin cache
        and the ray-tracing segment setup, which assume every cooked section is non-empty.
        Degenerating indices keeps every count the engine relies on intact.
        """
        blob = self._blob(lod)
        stride = lod["idx_stride"]
        fmt = "<I" if stride == 4 else "<H"
        keep = int(sec["num_tris"] * keep_fraction)
        # Collapse onto the section's own first vertex so the index stays in range.
        fill = sec["base_vertex"]
        base = lod["idx_off"] + (sec["base_index"] + keep * 3) * stride
        for i in range((sec["num_tris"] - keep) * 3):
            struct.pack_into(fmt, blob, base + i * stride, fill)
        return keep

    def scale_bounds(self, factor):
        """Grow ImportedBounds so deformed geometry is never frustum-culled. The bounds are
        the 7 doubles immediately before the FSkeletalMaterial array's count field."""
        i = self.uexp.find(struct.pack("<I", 12))       # material count for this mesh
        while i > 0:
            (pkg,) = struct.unpack_from("<i", self.uexp, i + 4)
            if -10000 < pkg < 0 and i >= 56:
                break
            i = self.uexp.find(struct.pack("<I", 12), i + 1)
        if i < 56:
            return False
        o = i - 56
        b = list(struct.unpack_from("<7d", self.uexp, o))
        for k in (3, 4, 5, 6):                          # BoxExtent xyz + SphereRadius
            b[k] *= factor
        struct.pack_into("<7d", self.uexp, o, *b)
        return True

    # ── vertex attribute decode ─────────────────────────────────────────────────

    def normals_tangents(self, lod):
        """Decode packed tangent basis -> (normal[N,3], tangent[N,3], tangent_w[N]).
        FPackedNormal: each byte (b^0x80)/127.5-1 (the XOR is UE5's IncreaseNormalPrecision
        flag; confirmed required here -- without it the sign byte decodes to ~0 instead of
        the expected +-1). Stored as TangentX (tangent) then TangentZ (normal), 4 bytes each.

        HANDEDNESS LIVES IN TangentZ.W (byte 7), NOT TangentX.W (byte 3). This read the
        sign out of byte 3 originally, which silently always yields +1: across every vertex
        of every asset checked, byte 3 is the constant 127 and carries no information,
        while byte 7 is 127 (+1) or 129 (-1) -- 35,783 of Magik's 123,018 LOD0 vertices are
        negative. Taking the sign from the wrong byte made every rebuilt mesh
        right-handed everywhere, flipping the bitangent on the ~29% of vertices whose UV
        island is mirrored. That inverts the green channel of normal-map lighting, which is
        subtle enough to survive a visual check and is why it went unnoticed.

        The W is returned as its DECODED VALUE, not np.sign of it. Only the sign carries
        meaning, but the cooker writes -1 as byte 129 (decoding to -0.992) while
        round-tripping np.sign(-1) through encode_packed_normal yields byte 128. Both mean
        "left-handed" and the engine reads only the sign, so the difference is harmless --
        but passing the value through unchanged makes a null round-trip byte-identical,
        which is worth far more as a regression invariant than the distinction costs.
        Consumers that need a true +-1 (glTF's TANGENT.w) take np.sign at that boundary."""
        n = lod["num_verts"]
        raw = np.frombuffer(bytes(self._blob(lod)), np.uint8, n * 8, lod["tan_off"]).reshape(n, 8)
        v = (raw.astype(np.int16) ^ 0x80).astype(np.float32) / 127.5 - 1.0
        tangent, normal_w = v[:, 0:4], v[:, 4:8]
        return normal_w[:, :3], tangent[:, :3], normal_w[:, 3]

    def uvs(self, lod):
        """[N, NumTexCoords, 2] float32. Always full-precision on this game; a
        half-precision path would need decoding here if fullPrecUV is ever 0."""
        n, c = lod["num_verts"], lod["num_tex_coords"]
        if not lod["full_prec_uv"]:
            raise NotImplementedError("half-precision UVs not encountered/decoded yet")
        return np.frombuffer(bytes(self._blob(lod)), "<f4", n * c * 2, lod["uv_off"]).reshape(n, c, 2)

    def colors(self, lod):
        """[N,4] float32 RGBA in [0,1], or None if the LOD has no color buffer.
        FColor's in-memory field order is B,G,R,A (StructLayout.Sequential) -- swizzled."""
        if lod["col_off"] is None:
            return None
        n = lod["num_verts"]
        bgra = np.frombuffer(bytes(self._blob(lod)), np.uint8, n * 4, lod["col_off"]).reshape(n, 4)
        return bgra[:, [2, 1, 0, 3]].astype(np.float32) / 255.0

    def skin_weights(self, lod):
        """(bone_idx[N,8] section-local, weight[N,8] in [0,1]). FSkinWeightInfo is
        Struct-of-Arrays per vertex -- BoneIndex[8] THEN BoneWeight[8], not interleaved
        pairs (confirmed: interleaved gave weight sums far from 255 and out-of-BoneMap-
        range indices; SoA gives exact 255 sums and every index within its section's
        BoneMap). Only the first `max_bone_influences` columns are meaningful.

        bVariableBonesPerVertex meshes (44% of the game's body meshes -- see BLENDER.md
        S5.3b) pack a different layout: MeshWeightData is one flat byte array, and a
        per-vertex LookupData[N] (uint32) gives each vertex's (byte_offset << 8 | count)
        into it -- BoneIndex[count] then BoneWeight[count], same SoA convention as the
        fixed layout, just variable-length per vertex instead of a constant stride of 16.
        Counts above 8 (observed up to 12 on this game's meshes) are capped to the 8
        heaviest influences and renormalised to sum 255: the glTF round-trip already caps
        at 8 (export_all_influences/export_influence_nb=8, see BLENDER.md S3.7) and the
        writer always emits a fixed-8 buffer regardless of source format (see
        rebuild_lod_buffers) -- a legal re-encoding of the same data, lossy only on the
        thin tail past 8 influences (mean measured at 3.24/vertex)."""
        n = lod["num_verts"]
        if lod.get("bone_index_16") or lod.get("bone_weight_16"):
            raise NotImplementedError("16-bit bone index/weight skin buffers not decoded")
        blob = bytes(self._blob(lod))
        if not lod.get("variable_bones"):
            raw = np.frombuffer(blob, np.uint8, n * 16, lod["sw_off"]).reshape(n, 16)
            idx, wgt = raw[:, :8].copy(), raw[:, 8:].copy()
            mi = lod["max_bone_influences"]
            if mi < 8:
                idx[:, mi:] = 0; wgt[:, mi:] = 0
            return idx, wgt.astype(np.float32) / 255.0

        lookup = np.frombuffer(blob, "<u4", n, lod["lookup_off"])
        data = np.frombuffer(blob, np.uint8, lod["sw_cnt"] * lod["sw_esz"], lod["sw_off"])
        offs, cnts = (lookup >> 8).astype(np.int64), (lookup & 0xFF).astype(np.int64)

        idx = np.zeros((n, 8), np.uint8)
        wgt = np.zeros((n, 8), np.uint8)
        for i in range(n):
            c, o = int(cnts[i]), int(offs[i])
            if c == 0:
                continue
            bi, bw = data[o:o + c], data[o + c:o + 2 * c]
            if c > 8:
                order = np.argsort(-bw.astype(np.int64))[:8]
                bi, bw = bi[order], bw[order].astype(np.int64)
                bw = (bw * 255 // max(int(bw.sum()), 1)).astype(np.int64)
                bw[0] += 255 - int(bw.sum())
                bw = bw.astype(np.uint8)
                c = 8
            idx[i, :c], wgt[i, :c] = bi, bw
        return idx, wgt.astype(np.float32) / 255.0

    def section_bonemap(self, sec):
        c, = struct.unpack_from("<I", self.uexp, sec["bm"])
        return list(struct.unpack_from("<%dH" % c, self.uexp, sec["bm"] + 4))

    # ── general rebuild (vertex add/remove/move, any section, fixed BoneMaps) ──────

    def rebuild_lod(self, lod_index, sections_in):
        """Replace one LOD's geometry entirely. `sections_in` is the FULL per-section-
        local data for EVERY section in this LOD, edited or not, in original section
        order -- see rebuild_lod_buffers for the per-section dict shape and the fixed-
        BoneMap constraint that makes this a value-only patch: section count and every
        section's BoneMap are unchanged, so the section-table region's byte layout never
        moves, only its field VALUES (NumVertices/NumTriangles/BaseVertexIndex/BaseIndex)
        do. Only the LOD's blob resizes -- in .ubulk for a streamed LOD (DataResourceMap
        sizes/offsets cascade to later entries) or in-place in .uexp for an inline LOD
        (export SerialSize + package BulkDataStartOffset shift; only valid because
        SkeletalMesh is confirmed the LAST export, so nothing else needs to move)."""
        lod = self.lods[lod_index]
        orig_sections = lod["sections"]
        if len(sections_in) != len(orig_sections):
            raise ValueError("section count must match the original (BoneMaps/section "
                            "table are never resized -- see rebuild_lod_buffers)")
        for si, osec in zip(sections_in, orig_sections):
            if si["mat"] != osec["mat"]:
                raise ValueError("section order/materials must match the original")

        new_blob, new_secs, total_nv, idx_stride, n_idx = rebuild_lod_buffers(
            sections_in, lod["tail_prefix"], lod["tail_suffix"])

        blob_start = lod["idx_off"] - 11      # index buffer's own strip+dts+bulk header
        old_nv, old_n_idx = lod["num_verts"], lod["n_indices"]

        if lod["buf"] == "ubulk":
            entry = self._drm_entries[self._drm_map[lod_index]]
            (old_offset,) = struct.unpack_from("<q", self.uasset, entry["rec_off"] + 4)
            (old_size,) = struct.unpack_from("<q", self.uasset, entry["rec_off"] + 20)
            self.ubulk[old_offset:old_offset + old_size] = new_blob
            struct.pack_into("<q", self.uasset, entry["rec_off"] + 20, len(new_blob))
            struct.pack_into("<q", self.uasset, entry["rec_off"] + 28, len(new_blob))
            delta = len(new_blob) - old_size
            entry_i = self._drm_map[lod_index]
            for later in self._drm_entries[entry_i + 1:]:
                (o,) = struct.unpack_from("<q", self.uasset, later["rec_off"] + 4)
                struct.pack_into("<q", self.uasset, later["rec_off"] + 4, o + delta)
            self._patch_mirror(lod, old_size, len(new_blob), old_n_idx, n_idx, old_nv, total_nv)
        else:
            old_size = (len(self.uexp) - 4) - blob_start
            self.uexp[blob_start:blob_start + old_size] = new_blob
            delta = len(new_blob) - old_size
            (old_ss,) = struct.unpack_from("<q", self.uasset, self._export_ss_off)
            struct.pack_into("<q", self.uasset, self._export_ss_off, old_ss + delta)
            (old_bd,) = struct.unpack_from("<q", self.uasset, self._bulk_start_off)
            struct.pack_into("<q", self.uasset, self._bulk_start_off, old_bd + delta)

        for osec, ns in zip(orig_sections, new_secs):
            struct.pack_into("<I", self.uexp, osec["tris_off"], ns["num_tris"])
            struct.pack_into("<I", self.uexp, osec["base_index_off"], ns["base_index"])
            struct.pack_into("<I", self.uexp, osec["base_vertex_off"], ns["base_vertex"])
            struct.pack_into("<I", self.uexp, osec["num_verts_off"], ns["num_verts"])
            osec["num_verts"], osec["num_tris"] = ns["num_verts"], ns["num_tris"]
            osec["base_vertex"], osec["base_index"] = ns["base_vertex"], ns["base_index"]

        lod["num_verts"], lod["n_indices"], lod["idx_stride"] = total_nv, n_idx, idx_stride
        self._reindex_after_resize()
        return {"total_nv": total_nv, "idx_stride": idx_stride, "n_idx": n_idx}

    def _patch_mirror(self, lod, old_size, new_size, old_n_idx, new_n_idx, old_nv, new_nv):
        """The .uexp carries small mirrors of a streamed LOD's blob size + derived counts
        (index count, vertex count, NumBones=NumVerts*8) near that LOD's own section
        table -- find+replace within a bounded window starting right after this LOD's own
        sections, so an edit to one LOD can't accidentally match another LOD's mirror."""
        near = max(s["after"] for s in lod["sections"])
        mir = self.uexp.find(struct.pack("<I", old_size), near)
        if mir < 0:
            raise ValueError("could not find this LOD's metadata mirror in .uexp")
        seg = bytearray(self.uexp[mir:mir + 0x50])
        for old, new in ((old_size, new_size), (old_n_idx, new_n_idx),
                         (old_nv * 8, new_nv * 8), (old_nv, new_nv)):
            op, npv, j = struct.pack("<I", old), struct.pack("<I", new), 0
            while (j := seg.find(op, j)) >= 0:
                seg[j:j + 4] = npv; j += 4
        self.uexp[mir:mir + 0x50] = seg

    def _reindex_after_resize(self):
        """Re-locate every LOD's buffer offsets after a blob splice -- a resized LOD can
        shift where a LATER LOD's data lives within the same file (e.g. editing LOD0
        shifts LOD1's position within .ubulk). Section byte offsets are untouched by
        design (see rebuild_lod) so sections themselves are not re-scanned."""
        pos = dict(find_position_buffers(bytes(self.uexp)))
        for n, off in find_position_buffers(bytes(self.ubulk)).items():
            pos[n] = ("ubulk", off)
        for n in list(pos):
            if not isinstance(pos[n], tuple):
                pos[n] = ("uexp", pos[n])
        for i, lod in enumerate(self.lods):
            n = lod["num_verts"]
            if n not in pos:
                raise ValueError(f"could not re-locate the position buffer for a "
                                f"{n}-vertex LOD after resize")
            lod["buf"], lod["pos_off"] = pos[n]
            self._locate_index_buffer(lod)
            self._locate_vertex_buffers(lod)
            # Re-split the tail too: it now holds a cleared morph gate, and _lod_blob_end
            # reads the DataResourceMap entries this rebuild has already updated.
            self._locate_tail(i, lod)

    def save(self, out_dir, name):
        os.makedirs(out_dir, exist_ok=True)
        for ext, data in ((".uexp", self.uexp), (".ubulk", self.ubulk)):
            if data:
                open(os.path.join(out_dir, name + ext), "wb").write(bytes(data))
        # self.uasset is tracked in memory (DataResourceMap/SerialSize/BulkDataStartOffset
        # are patched there by rebuild_lod) -- write it, not a fresh disk copy, once it has
        # actually been loaded; a Mesh with no .uasset alongside it never populates it.
        if self.uasset:
            open(os.path.join(out_dir, name + ".uasset"), "wb").write(bytes(self.uasset))


# ── edits ─────────────────────────────────────────────────────────────────────

def transform_section(mesh, sec_index, scale=(1.0, 1.0, 1.0), pivot="origin"):
    """Scale one material's geometry in every LOD.

    Sections are matched across LODs by MaterialIndex, not position, because decimation
    drops whole sections from lower LODs (LOD2 of the reference mesh has 10 sections, not
    12) -- so the same material lives at a different section index per LOD.

    pivot: "origin" keeps the component origin fixed; "centroid" scales about the
    section's own centre, which is what you want for making a body part bigger in place;
    an explicit (x, y, z) shares one pivot across several sections, which is required when
    a body part spans more than one material -- scaling a head and its eyes about their
    own separate centroids pulls them apart.
    """
    applied = []
    for lod in mesh.lods:
        sec = next((s for s in lod["sections"] if s["mat"] == sec_index), None)
        if sec is None:
            continue
        lo = sec["base_vertex"]
        hi = lo + sec["num_verts"]
        v = mesh.positions(lod)[lo:hi].copy()
        if not isinstance(pivot, str):
            c = np.asarray(pivot, "f4")
        elif pivot == "centroid":
            c = v.mean(axis=0)
        else:
            c = np.zeros(3, "f4")
        mesh.write_positions(lod, lo, hi, (v - c) * np.asarray(scale, "f4") + c)
        applied.append(hi - lo)
    return applied


def material_centroid(mesh, sec_indices, lod_index=0):
    """Centroid of several materials' vertices in one LOD -- a shared pivot for a body
    part that spans multiple sections."""
    lod = mesh.lods[lod_index]
    pos = mesh.positions(lod)
    chunks = [pos[s["base_vertex"]:s["base_vertex"] + s["num_verts"]]
              for s in lod["sections"] if s["mat"] in sec_indices]
    if not chunks:
        raise ValueError("no matching sections")
    return np.concatenate(chunks).mean(axis=0)


def set_material_triangles(mesh, sec_index, fraction):
    """Keep `fraction` of a material's triangles in every LOD (0.0 hides it entirely)."""
    applied = []
    for lod in mesh.lods:
        sec = next((s for s in lod["sections"] if s["mat"] == sec_index), None)
        if sec is None:
            continue
        applied.append(mesh.degenerate_triangles(lod, sec, fraction))
    return applied


# ── write-side encoders ─────────────────────────────────────────────────────────
# Inverses of Mesh.normals_tangents / Mesh.skin_weights, needed to turn edited/generated
# geometry back into the game's packed formats.

def encode_packed_normal(xyz):
    """Inverse of the FPackedNormal decode: byte = round((v+1)*127.5) ^ 0x80. `xyz` is
    [...,3] in [-1,1]; returns uint8 bytes of the same leading shape + (3,)."""
    v = np.clip(np.round((np.asarray(xyz, "f8") + 1.0) * 127.5), 0, 255).astype(np.uint8)
    return v ^ 0x80


def quantize_weights(weights):
    """[N,8] float weights (assumed to sum to ~1 per vertex, zero-padded past the vertex's
    real influence count) -> [N,8] uint8 summing to EXACTLY 255 per vertex. Largest-
    remainder rounding: floor everything, then hand out the leftover units to the
    largest-fraction entries first -- plain per-element round() can under/overshoot 255,
    which the engine's skin cache does not tolerate gracefully."""
    w = np.asarray(weights, "f8")
    scaled = w * 255.0
    base = np.floor(scaled).astype(np.int64)
    frac = scaled - base
    deficit = 255 - base.sum(axis=1)
    order = np.argsort(-frac, axis=1)
    out = base.copy()
    for i in range(w.shape[0]):
        d = deficit[i]
        if d > 0:
            out[i, order[i, :d]] += 1
        elif d < 0:                                        # only possible from float overshoot
            out[i, order[i, d:]] -= 1
    return np.clip(out, 0, 255).astype(np.uint8)


def collapse_weights_to_bonemap(global_idx, weight, bonemap, bones):
    """Redirect weights from bones a section's BoneMap doesn't contain onto the nearest
    ANCESTOR bone that it does, merging any duplicates and renormalising.

    This is what the cooker itself does when it drops bones from a lower LOD (the LOD
    properties literally carry a `BonesToRemove` list): influence collapses up the
    hierarchy to the surviving parent. It becomes necessary the moment lower LODs are
    generated by decimating the top LOD, because the top LOD's geometry references the full
    bone set while a lower LOD's fixed BoneMap is a strict subset -- LOD1 here keeps 138 of
    LOD0's 152 bones for the same material. Without this, every decimated LOD would be
    rejected by map_to_fixed_bonemap.

    Weights are merged rather than overwritten: two influences can collapse onto the same
    ancestor, and dropping one of them instead of summing would quietly change the skinning.
    """
    keep = set(int(b) for b in bonemap)
    remap = np.full(len(bones), -1, np.int64)
    for i in range(len(bones)):
        j = i
        while j != -1 and j not in keep:
            j = bones[j]["parent"]
        remap[i] = j
    tgt = remap[np.asarray(global_idx, np.int64)]
    w = np.array(weight, "f8", copy=True)
    w[tgt < 0] = 0.0                      # no retained ancestor: influence cannot be kept
    tgt = np.where(tgt < 0, 0, tgt)
    k = w.shape[1]
    for a in range(k):                    # merge duplicate targets within each vertex
        for b in range(a + 1, k):
            dup = (tgt[:, a] == tgt[:, b]) & (w[:, b] > 0)
            w[dup, a] += w[dup, b]
            w[dup, b] = 0.0
    tgt = np.where(w > 0, tgt, 0)
    tot = w.sum(1, keepdims=True)
    w = np.where(tot > 0, w / np.where(tot == 0, 1, tot), 0.0)
    return tgt.astype(np.uint16), w.astype("f4")


def map_to_fixed_bonemap(global_idx, weight, bonemap, section_label=""):
    """Remap GLOBAL skeleton bone indices to LOCAL indices into a section's EXISTING,
    UNCHANGED BoneMap. The BoneMap is never recomputed or resized -- see the module note
    above `rebuild_lod_buffers` for why. Raises if any vertex with nonzero weight
    references a bone the section's original BoneMap doesn't contain; a vertex with zero
    weight in a slot is unconstrained (dead weight, decodes to 0 either way) and maps to
    local index 0 regardless of its global value."""
    bonemap = np.asarray(bonemap, np.int64)
    gi = np.asarray(global_idx, np.int64)
    lut_size = int(max(bonemap.max(initial=-1), gi.max(initial=-1))) + 1
    lut = np.full(lut_size, -1, np.int64)
    lut[bonemap] = np.arange(len(bonemap))
    local = lut[gi]
    bad = (local < 0) & (np.asarray(weight) > 0)
    if bad.any():
        missing = sorted(set(gi[bad].tolist()))
        raise ValueError(
            f"section {section_label!r}: edited geometry weights {len(missing)} bone(s) "
            f"not in the section's original BoneMap ({missing[:10]}{'...' if len(missing)>10 else ''}) "
            f"-- edits may only reference bones the section already used (BoneMaps are "
            f"never resized by design; see rebuild_lod_buffers)")
    return np.where(local < 0, 0, local).astype(global_idx.dtype)


def rebuild_lod_buffers(sections_in, tail_prefix=b"", tail_suffix=b"", idx_stride=None):
    """Build a complete LOD blob + section metadata from PER-SECTION-LOCAL vertex data --
    each section owns its own vertex arrays (indices 0..Ni-1), not a shared cross-section
    pool. This matches how real glTF exporters (Blender included) actually emit a multi-
    material mesh: each primitive gets its own bufferViews, since different materials can
    have different UV seams/smoothing and therefore genuinely different per-vertex data at
    a shared position. It also matches the cooked format directly -- sections are already
    vertex-CONTIGUOUS and never share a vertex (confirmed against vanilla data: a vertex
    sitting on a material seam is duplicated once per section, not shared) -- so no
    dedup/reindex step is needed; whatever the caller provides per section is used as-is.

    sections_in: list of dicts, in section order (SAME COUNT AND ORDER as the original --
    see DESIGN CONSTRAINT below), each with:
        mat: material/section index (must match an existing section)
        positions [Ni,3], normal/tangent [Ni,3] (unit vectors), tan_w [Ni] (+-1),
        uv [Ni,ntc,2], color [Ni,4] or None, global_idx [Ni,8] (u16), weight [Ni,8] (0..1),
        triangles [Ti,3] LOCAL (0..Ni-1) vertex indices,
        bonemap: that section's EXISTING BoneMap (list of global bone indices, unmodified)

    DESIGN CONSTRAINT: BoneMaps and section count/order are fixed, never recomputed. A
    section's BoneMap is the one piece of the format that, if it changes size, cascades
    into resizing the section-table region and everything after it in .uexp (RequiredBones,
    every later LOD's position) -- real added complexity Phase 1 never had to touch because
    every edit there only changed FIELD VALUES inside existing, fixed-size records. Refusing
    to let edits introduce a bone a section didn't already reference keeps that constraint
    permanently true, so a rebuild is always just: new blob + value-only patches to already-
    existing section records (see Mesh.rebuild_lod). Vertex ADD/REMOVE/MOVE is fully
    supported under this constraint -- only reweighting onto a genuinely new bone is not.

    idx_stride: force 4 or 2; None picks 2 when the rebuilt vertex count fits (<65536), else 4.
    """
    ntc = np.asarray(sections_in[0]["uv"]).shape[1]
    has_color = sections_in[0]["color"] is not None

    sections, all_pos, all_tan8, all_uv, all_col, all_sw16, all_idx = [], [], [], [], [], [], []
    base_vertex = base_index = 0
    for si in sections_in:
        mat, bonemap = si["mat"], si["bonemap"]
        pos = np.asarray(si["positions"], "f4")
        normal = np.asarray(si["normal"], "f4"); tangent = np.asarray(si["tangent"], "f4")
        tan_w = np.asarray(si["tan_w"], "f4"); uv = np.asarray(si["uv"], "f4")
        gidx = np.asarray(si["global_idx"], np.uint16); w = np.asarray(si["weight"], "f4")
        tris = np.asarray(si["triangles"], np.uint32)
        n_verts, n_tris = len(pos), len(tris)

        # Handedness belongs in TangentZ.W -- see Mesh.normals_tangents. TangentX.W is the
        # constant +1 every cooked asset carries there; writing the sign into it instead
        # (and +1 into TangentZ.W) discards handedness entirely, because TangentZ.W is the
        # slot the engine reads.
        tan_full = encode_packed_normal(
            np.concatenate([tangent, np.ones((n_verts, 1), "f4")], 1))
        nrm_full = encode_packed_normal(np.concatenate([normal, tan_w[:, None]], 1))
        local_idx = map_to_fixed_bonemap(gidx, w, bonemap, section_label=f"mat{mat}")
        qw = quantize_weights(w)
        sw_bytes = np.concatenate([local_idx.astype(np.uint8), qw], axis=1)

        all_pos.append(pos)
        all_tan8.append(np.concatenate([tan_full, nrm_full], axis=1))
        all_uv.append(uv)
        if has_color: all_col.append(np.asarray(si["color"], "f4"))
        all_sw16.append(sw_bytes)
        all_idx.append(tris + base_vertex)

        sections.append({"mat": mat, "base_vertex": base_vertex, "num_verts": n_verts,
                         "base_index": base_index, "num_tris": n_tris,
                         "bonemap": list(bonemap), "max_infl": 8})
        base_vertex += n_verts; base_index += n_tris * 3

    pos = np.concatenate(all_pos); tan8 = np.concatenate(all_tan8)
    uvs = np.concatenate(all_uv); sw16 = np.concatenate(all_sw16)
    col = np.concatenate(all_col) if has_color else None
    idx = np.concatenate(all_idx)
    total_nv = base_vertex
    if idx_stride is None:
        idx_stride = 2 if total_nv <= 65536 else 4
    elif idx_stride == 2 and total_nv > 65536:
        raise ValueError("rebuilt vertex count exceeds 16-bit index range")
    idx = idx.astype("<u2" if idx_stride == 2 else "<u4")

    def bulk(esz, data):
        return struct.pack("<II", esz, len(data) // esz if esz else 0) + bytes(data)

    o = bytearray()
    o += b"\x01\x00"; o.append(idx_stride)
    o += bulk(idx_stride, idx.tobytes())
    o += struct.pack("<II", 12, total_nv)
    o += bulk(12, pos.astype("<f4").tobytes())
    o += b"\x01\x00"
    o += struct.pack("<IIII", ntc, total_nv, 1, 0)                    # fullPrecUV=1, hiPrecTangent=0
    o += bulk(8, tan8.astype(np.uint8).tobytes())
    o += bulk(8, uvs.astype("<f4").tobytes())
    o += b"\x01\x00"
    o += struct.pack("<IIIIII", 0, 8, total_nv * 8, total_nv, 0, 0)   # fixed 8 influences, 8-bit
    o += bulk(1, sw16.astype(np.uint8).tobytes())
    o += b"\x01\x00" + struct.pack("<I", 0) + bulk(4, b"")            # empty lookup buffer
    o += b"\x01\x00" + struct.pack("<II", 4, total_nv if has_color else 0)
    if has_color:
        bgra = col[:, [2, 1, 0, 3]] * 255.0
        o += bulk(4, np.clip(np.round(bgra), 0, 255).astype(np.uint8).tobytes())

    # Tail: replay the ORIGINAL surrounding structures byte-for-byte (see
    # Mesh._locate_tail) and only clear the int32 bSerializeCompressedMorphTargets gate
    # between them. Morphs must go because their deltas are vertex-indexed and this
    # rebuild can renumber/drop vertices, which would silently misapply them; everything
    # else in the tail is preserved rather than re-synthesised, since guessing its
    # composition is exactly what produced a serial-size mismatch on the first attempt.
    o += tail_prefix
    o += struct.pack("<i", 0)
    o += tail_suffix

    return bytes(o), sections, total_nv, idx_stride, idx.size


# ── glTF import (edited mesh -> section data for rebuild_lod) ───────────────────

_GLTF_COMP = {5120: ("i1", 127.0), 5121: ("u1", 255.0), 5122: ("<i2", 32767.0),
              5123: ("<u2", 65535.0), 5125: ("<u4", None), 5126: ("<f4", None)}
_GLTF_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path):
    """Split a .glb into (json, binary chunk)."""
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError("not a .glb")
    o, js, bin_ = 12, None, b""
    while o < len(d):
        clen, ctype = struct.unpack_from("<II", d, o)
        chunk = d[o + 8:o + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_ = chunk
        o += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
    return js, bin_


def gltf_accessor(g, bin_, index):
    """Read an accessor as float64 (or integer dtype for index/joint data), honouring
    bufferView.byteStride -- exporters may interleave, and reading such a buffer densely
    silently yields rotated garbage rather than failing."""
    a = g["accessors"][index]
    n, ncomp = a["count"], _GLTF_NCOMP[a["type"]]
    dtype, norm_div = _GLTF_COMP[a["componentType"]]
    itemsize = np.dtype(dtype).itemsize
    bv = g["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or (itemsize * ncomp)
    raw = np.frombuffer(bin_, np.uint8, n * stride, base).reshape(n, stride)
    out = raw[:, :itemsize * ncomp].copy().view(dtype).reshape(n, ncomp)
    if a.get("normalized") and norm_div:
        out = np.clip(out.astype("f8") / norm_div, -1.0, 1.0)
    return out


def _compute_tangents(pos, uv0, normal, tris):
    """Per-vertex tangent basis from UV0, for exporters that omit TANGENT. Standard
    accumulate-per-triangle then Gram-Schmidt against the normal; handedness from the
    bitangent. Not mikktspace-identical, but the game stores an 8-bit quantised basis and
    normal maps here are low-frequency enough that the difference is not visible."""
    tan = np.zeros_like(pos); bit = np.zeros_like(pos)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    w0, w1, w2 = uv0[tris[:, 0]], uv0[tris[:, 1]], uv0[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    denom = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(denom) < 1e-12, 0.0, 1.0 / np.where(denom == 0, 1, denom))
    t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]
    b = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r[:, None]
    for k in range(3):
        np.add.at(tan, tris[:, k], t)
        np.add.at(bit, tris[:, k], b)
    tan -= normal * (normal * tan).sum(1, keepdims=True)
    ln = np.linalg.norm(tan, axis=1, keepdims=True)
    tan = np.where(ln > 1e-8, tan / np.where(ln == 0, 1, ln), np.array([1.0, 0.0, 0.0]))
    w = np.where((np.cross(normal, tan) * bit).sum(1) < 0.0, -1.0, 1.0)
    return tan.astype("f4"), w.astype("f4")


def transfer_weights_from_vanilla(mesh, lod, sec, positions):
    """Re-rig geometry onto the TARGET skeleton by copying skinning from this section's own
    VANILLA vertices, nearest-neighbour in model space. Returns (global_idx, weight, dist).

    Geometry grafted in from another character arrives weighted to the DONOR's bones. Those
    bone names do not exist in this skeleton, so Blender's glTF exporter -- which pairs vertex
    groups to armature bones by name -- drops them silently and the vertices export with no
    influences at all. Nothing downstream catches that: zero weights survive normalisation and
    reach quantize_weights, whose largest-remainder pass then hands out 255 units across only
    8 columns and emits rows summing to 8. The result is geometry pinned near the component
    origin rather than a crash, which is the worst way for it to fail.

    Copying from the vanilla section fixes it in the frame that actually matters. The source
    is the same LOD being rebuilt, so every bone copied is already in that LOD's own BoneMap
    (BoneMaps are never resized -- design constraint 1), and the grafted hair inherits
    whatever real rig the target's own hair used, jiggle-bone chains included, instead of
    being rigidly pinned to one bone. It is also near-idempotent on untouched geometry: each
    vanilla vertex's nearest source is itself.
    """
    from scipy.spatial import cKDTree

    lo = sec["base_vertex"]
    hi = lo + sec["num_verts"]
    src_pos = np.asarray(mesh.positions(lod)[lo:hi], "f8")
    sidx, swgt = mesh.skin_weights(lod)
    bonemap = np.asarray(mesh.section_bonemap(sec), np.uint16)
    src_gi = bonemap[np.asarray(sidx[lo:hi], np.int64)]        # section-local -> global
    src_w = np.asarray(swgt[lo:hi], "f8")

    dist, j = cKDTree(src_pos).query(np.asarray(positions, "f8"), k=1)
    return src_gi[j], src_w[j], dist, src_pos


def glb_to_sections(mesh, lod_index, glb_path, reweight=None):
    """Convert an edited .glb back into the per-section arrays rebuild_lod expects.

    `reweight` is {slot name: 'all'|'zero_weight'} from the graft sidecar: those sections have
    their skinning recomputed from the vanilla mesh by transfer_weights_from_vanilla, which is
    what makes geometry transplanted from another character follow this skeleton.

    Primitives are matched to sections by MATERIAL NAME (the same names export_glb wrote),
    not by order -- Blender reorders primitives freely, and matching positionally would
    silently swap geometry between materials. Joints are likewise resolved through the
    skin's joint list and node NAMES back to skeleton bone indices, since an exporter may
    renumber joints.

    Some skeletons carry genuine DUPLICATE bone names (observed on SK_1024_1024307: 361
    bones include 'hela_weapon' x6, real weapon-rig bones the Weapon section is actually
    skinned to -- not unused). export_glb writes one glTF node per bone verbatim in
    mesh.bones order, so Blender's round-trip -- which refuses duplicate bone names within
    one Armature -- renames all but the first occurrence on import ('hela_weapon' ->
    'hela_weapon.001', ...), breaking a plain name match for those joints on export back
    out. Since the armature is never restructured (glb_to_blend.py locks it) Blender's own
    bone order is stable and mirrors mesh.bones order, so occurrences of one base name are
    resolved POSITIONALLY: the Nth glTF joint sharing a base name is matched to the Nth
    bone of that name in mesh.bones, in encounter order. A joint that still can't be
    resolved (an unknown name, or more occurrences than the original skeleton had) only
    raises if some vertex actually carries nonzero weight on it (checked below, once
    JOINTS/WEIGHTS are read) -- the same "dead weight is unconstrained" philosophy as
    map_to_fixed_bonemap.

    Vertex counts per section are whatever the file says: Blender splits vertices at UV and
    normal seams, so even an unedited round-trip usually comes back with MORE vertices than
    vanilla. That is expected and fine -- the rebuild is count-agnostic.
    """
    g, bin_ = load_glb(glb_path)
    lod = mesh.lods[lod_index]

    bone_occurrences = {}
    for i, b in enumerate(mesh.bones):
        bone_occurrences.setdefault(b["name"], []).append(i)
    nodes = g.get("nodes", [])
    if not g.get("skins"):
        raise ValueError("glb has no skin -- skinning data is required")
    joints = g["skins"][0]["joints"]
    joint_to_bone = np.zeros(len(joints), np.uint16)
    unresolved = {}
    seen = {}
    _suffix_re = re.compile(r"^(.*)\.\d{3}$")
    for ji, node_i in enumerate(joints):
        nm = nodes[node_i].get("name")
        base = nm if nm in bone_occurrences else None
        if base is None:
            m = _suffix_re.match(nm or "")
            if m and m.group(1) in bone_occurrences:
                base = m.group(1)
        occ = bone_occurrences.get(base) if base else None
        k = seen.get(base, 0)
        if not occ or k >= len(occ):
            unresolved[ji] = nm
            continue
        joint_to_bone[ji] = occ[k]
        seen[base] = k + 1

    mat_names = [m.get("name") for m in g.get("materials", [])]
    by_mat = {}
    for gmesh in g.get("meshes", []):
        for prim in gmesh["primitives"]:
            if prim.get("mode", 4) != 4:
                raise ValueError("only triangle primitives are supported")
            nm = mat_names[prim["material"]] if prim.get("material") is not None else None
            by_mat.setdefault(nm, []).append(prim)

    ntc = lod["num_tex_coords"]
    reweight = reweight or {}

    # Geometry on a material that is not a slot on this MESH is DROPPED -- sections only ever
    # consume their own slot name, so anything else in `by_mat` is simply never read. That is
    # the natural mistake when grafting (donor geometry arrives carrying the donor's own
    # material, or gets parked on a new Blender slot) and it would otherwise show up as a mod
    # that builds cleanly and is missing the transplant.
    #
    # Checked against every slot on the mesh, NOT against this LOD's sections: decimated LODs
    # legitimately drop whole sections (LOD2 has 10 of this mesh's 12 -- S3.9) while the
    # .blend still carries all of the materials, so scoping this to one LOD would reject
    # every ordinary multi-LOD build.
    known = {m["slot_name"] for m in mesh.materials}
    stray = sorted(n for n in by_mat if n is not None and n not in known)
    if stray:
        raise ValueError(
            f"{len(stray)} material(s) in the .blend are not slots on this mesh, so their "
            f"geometry would be silently dropped: {', '.join(stray)}. Assign that geometry to "
            f"one of the existing slots instead: {', '.join(sorted(n for n in known if n))}")

    sections_in = []
    for sec in lod["sections"]:
        slot = mesh.materials[sec["mat"]]["slot_name"]
        prims = by_mat.get(slot)
        if not prims:
            raise ValueError(f"no primitive in the glb uses material {slot!r} -- every "
                            "original material must still be present")
        P, N, T, TW, UV, C, GI, W, TRI = [], [], [], [], [], [], [], [], []
        voff = 0
        for prim in prims:
            at = prim["attributes"]
            pos = gltf_accessor(g, bin_, at["POSITION"]).astype("f8")
            nv = len(pos)
            # export_glb swaps winding CW->CCW for glTF; undo it here so the rebuilt UE
            # index buffer keeps the game's CW winding (export-flip + import-flip is the
            # identity on untouched geometry, preserving the byte-exact null round-trip).
            tris = gltf_accessor(g, bin_, prim["indices"]).reshape(-1, 3)[:, [0, 2, 1]].astype(np.int64)
            nrm = (gltf_accessor(g, bin_, at["NORMAL"]).astype("f8") if "NORMAL" in at
                   else np.tile([0.0, 0.0, 1.0], (nv, 1)))
            uvs = np.zeros((nv, ntc, 2), "f4")
            for c in range(ntc):
                key = f"TEXCOORD_{c}"
                if key in at:
                    uvs[:, c, :] = gltf_accessor(g, bin_, at[key]).astype("f4")
            if "TANGENT" in at:
                t4 = gltf_accessor(g, bin_, at["TANGENT"]).astype("f8")
                tan, tw = t4[:, :3], t4[:, 3]
            else:
                tan, tw = _compute_tangents(pos, uvs[:, 0, :].astype("f8"), nrm, tris)
            gi = np.zeros((nv, 8), np.uint16); w = np.zeros((nv, 8), "f8")
            for s in range(2):
                jk, wk = f"JOINTS_{s}", f"WEIGHTS_{s}"
                if jk in at and wk in at:
                    j = gltf_accessor(g, bin_, at[jk]).astype(np.int64)
                    wv = gltf_accessor(g, bin_, at[wk]).astype("f8")
                    if unresolved:
                        bad = np.isin(j, list(unresolved.keys())) & (wv > 0)
                        if bad.any():
                            names = sorted({unresolved[bj] for bj in set(j[bad].tolist())})
                            raise ValueError(
                                f"section mat{sec['mat']}: {int(bad.sum())} vertex-influence(s) "
                                f"weight unresolvable joint node(s) {names} -- likely a "
                                f"duplicate bone name in the original skeleton that Blender "
                                f"renamed on round-trip; these can only be safely ignored "
                                f"while carrying zero weight")
                    gi[:, s*4:(s+1)*4] = joint_to_bone[j]
                    w[:, s*4:(s+1)*4] = wv
            tot = w.sum(1, keepdims=True)
            w = np.where(tot > 0, w / np.where(tot == 0, 1, tot), 0.0)
            col = (gltf_accessor(g, bin_, at["COLOR_0"]).astype("f4") if "COLOR_0" in at
                   else None)
            if col is not None and col.shape[1] == 3:
                col = np.concatenate([col, np.ones((nv, 1), "f4")], 1)

            # glTF (Y-up, metres, right-handed) -> UE (Z-up, centimetres). _AXIS_R is the
            # UE->glTF rotation; being orthogonal, the inverse is a right-multiply by R.
            P.append((pos @ _AXIS_R) * 100.0)
            N.append(nrm @ _AXIS_R)
            T.append(tan @ _AXIS_R)
            TW.append(tw); UV.append(uvs); GI.append(gi); W.append(w)
            if col is not None: C.append(col)
            TRI.append(tris + voff)
            voff += nv

        has_col = lod["col_off"] is not None
        if has_col and not C:
            # The vanilla mesh carries a vertex-colour buffer (MR uses it as mask data, mostly
            # (0,0,0) -- see BLENDER.md S3.14), but this section's primitive(s) exported no
            # COLOR_0 at all. That is never expected -- blend_to_glb.py separates the mesh by
            # material before export specifically so every material gets real COLOR_0 (S3.25);
            # a primitive with none at all past that means the Color Attribute itself is gone
            # from the .blend for this material (deleted, or never existed on newly-created
            # geometry). Silently defaulting to white would ship a mask that reads as "fully
            # on" for exactly the edited geometry -- raise instead of guessing.
            raise ValueError(
                f"section {slot!r}: no vertex colours in the exported glb, but the original "
                f"mesh has a colour buffer -- the Color Attribute is missing for this material "
                f"(check Object Data Properties > Color Attributes)")
        pos = np.concatenate(P).astype("f4")
        gi, w = np.concatenate(GI), np.concatenate(W)

        mode = reweight.get(slot)
        if mode:
            src_gi, src_w, dist, src_pos = transfer_weights_from_vanilla(mesh, lod, sec, pos)
            take = (np.ones(len(pos), bool) if mode == "all"
                    else w.sum(1) <= 0)
            gi = gi.copy(); w = w.copy()
            gi[take], w[take] = src_gi[take], src_w[take]
            # A graft that was never moved onto the target's head gets weights copied from
            # whatever vanilla vertex happens to be closest, which is meaningless. The
            # section's own extent is the natural scale to judge that against.
            span = float(np.linalg.norm(src_pos.max(0) - src_pos.min(0))) if len(src_pos) else 0.0
            far = int((dist[take] > span).sum()) if span else 0
            print(f"[graft] LOD{lod_index} {slot!r}: reweighted {int(take.sum())}/{len(pos)} "
                  f"vertices from vanilla (max dist {float(dist[take].max()) if take.any() else 0:.1f}cm, "
                  f"section span {span:.1f}cm)", flush=True)
            if far:
                print(f"[graft] WARNING {far} vertex/vertices are further from any vanilla "
                      f"{slot!r} vertex than that section is wide -- if this is grafted "
                      f"geometry it probably was not positioned onto the target yet, and "
                      f"its skinning will be arbitrary", flush=True)

        # Collapse influences onto this LOD's own (smaller) BoneMap before they reach the
        # rebuilder -- required whenever a lower LOD is generated by decimating the top LOD,
        # whose geometry references the full bone set. Runs after any reweight so transferred
        # bones are checked too (they come from this LOD, so this is a no-op for them).
        gi, w = collapse_weights_to_bonemap(gi, w, mesh.section_bonemap(sec), mesh.bones)

        dead = w.sum(1) <= 0
        if dead.any():
            raise ValueError(
                f"section {slot!r}: {int(dead.sum())} vertex/vertices carry no skin weight at "
                f"all. Weightless vertices do not reach the game as anything sane -- they "
                f"quantise to a malformed influence row and collapse toward the component "
                f"origin. This is what geometry grafted from another character looks like "
                f"before it is re-rigged: add \"reweight\": \"all\" for this slot to the "
                f"graft sidecar, or give the vertices groups naming bones this skeleton has.")

        sections_in.append({
            "mat": sec["mat"],
            "positions": pos,
            "normal": np.concatenate(N).astype("f4"),
            "tangent": np.concatenate(T).astype("f4"),
            "tan_w": np.concatenate(TW).astype("f4"),
            "uv": np.concatenate(UV).astype("f4"),
            "color": (np.concatenate(C).astype("f4") if has_col else None),
            "global_idx": gi.astype(np.uint16),
            "weight": w.astype("f4"),
            "triangles": np.concatenate(TRI).astype(np.uint32),
            "bonemap": mesh.section_bonemap(sec),
        })
    return sections_in


# ── glTF export ─────────────────────────────────────────────────────────────────
# UE is left-handed, Z-up, centimetres. glTF is right-handed, Y-up, metres. The map
# (x,y,z) -> (x,z,-y) is a proper rotation (determinant +1: -90 deg about X), not a
# reflection, which is what makes this simple -- no triangle-winding flip is needed, and
# the whole skinned hierarchy converts by rotating ONLY the root bone's local transform
# (translation and rotation) and leaving every other bone's LOCAL (parent-relative)
# transform untouched (just /100 on translations for cm->m): each child inherits the
# rotation through the hierarchy automatically, so mesh vertices (which live in the same
# component space) only need that same single rotation applied directly, not per-bone.
_AXIS_R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], "f8")
_AXIS_Q = np.array([-0.7071067811865476, 0.0, 0.0, 0.7071067811865476])   # -90 deg about X, XYZW


def _qmul(a, b):
    """Hamilton product, XYZW convention: qmul(a,b) applies b first, then a."""
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
        aw*bw - ax*bx - ay*by - az*bz])


def _qmat(q):
    x, y, z, w = q
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)]])


def _bone_world_matrices(bones):
    """4x4 world matrices for every bone, and the glTF-space local TRS used to build the
    node hierarchy (root converted, everyone else passed through -- see module note)."""
    world = [None] * len(bones)
    node_trs = []
    for i, b in enumerate(bones):
        t = np.array(b["translation"], "f8") / 100.0
        q = np.array(b["rotation"], "f8")
        s = np.array(b["scale"], "f8")
        if b["parent"] == -1:
            t = _AXIS_R @ t
            q = _qmul(_AXIS_Q, q)
        node_trs.append((t, q, s))
        m = np.eye(4)
        m[:3, :3] = _qmat(q) * s[np.newaxis, :]
        m[:3, 3] = t
        world[i] = m if b["parent"] == -1 else world[b["parent"]] @ m
    return world, node_trs


def export_glb(mesh, lod_index, out_path):
    """Write a fully skinned glTF binary for one LOD: real bone hierarchy (names, rest
    pose, inverse bind matrices), one primitive per material section, true UV channel
    count, vertex colors, and up to 8 bone influences via JOINTS_0/1 + WEIGHTS_0/1."""
    lod = mesh.lods[lod_index]
    n = lod["num_verts"]
    pos = (mesh.positions(lod).astype("f8") / 100.0) @ _AXIS_R.T
    normal, tangent, tan_w = mesh.normals_tangents(lod)
    normal = normal.astype("f8") @ _AXIS_R.T
    tangent = tangent.astype("f8") @ _AXIS_R.T
    uv = mesh.uvs(lod)
    color = mesh.colors(lod)
    local_idx, weight = mesh.skin_weights(lod)
    global_idx = np.zeros_like(local_idx, dtype=np.uint16)
    for sec in lod["sections"]:
        lo, hi = sec["base_vertex"], sec["base_vertex"] + sec["num_verts"]
        bonemap = np.asarray(mesh.section_bonemap(sec), np.uint16)
        global_idx[lo:hi] = bonemap[local_idx[lo:hi]]

    world, node_trs = _bone_world_matrices(mesh.bones)
    ibm = np.linalg.inv(np.stack(world)).astype("f4")

    buf = bytearray()
    def add(arr):
        arr = np.ascontiguousarray(arr)
        off = len(buf); buf.extend(arr.tobytes())
        while len(buf) % 4: buf.append(0)
        return off, arr.nbytes

    bufferViews, accessors = [], []
    def bv(off, length, target=None):
        bufferViews.append({"buffer": 0, "byteOffset": off, "byteLength": length,
                            **({"target": target} if target else {})})
        return len(bufferViews) - 1

    def accessor(data, comp_type, atype, target=None, normalized=False, minmax=False):
        off, length = add(data)
        a = {"bufferView": bv(off, length, target), "componentType": comp_type,
             "count": len(data), "type": atype}
        if normalized: a["normalized"] = True
        if minmax:
            a["min"] = data.min(0).tolist(); a["max"] = data.max(0).tolist()
        accessors.append(a)
        return len(accessors) - 1

    ARRAY, ELEM = 34962, 34963
    F32, U16 = 5126, 5123

    # One glTF material PER SLOT, indexed by slot -- NOT keyed by the material ASSET the slot
    # points at. Several slots can share one asset (SK_1033_1033504 does it four times over:
    # Equip_01/Equip_01_01 both point at MI_1033504_Equip_01, and likewise for Equip_04,
    # Equip_02, Equip_03). Keying on pkg_idx made the second slot of each pair overwrite the
    # first, so BOTH sections exported pointing at one glTF material; Blender then merged the
    # pair into a single slot and dropped the other, and the mesh came back with 12 materials
    # for 16 sections. glb_to_sections matches sections to primitives by slot NAME, so the
    # four missing names made the mesh fail to rebuild at all -- it was not editable before
    # this. Slot names are unique where asset names are not, which is exactly why they are
    # the key (S3.9, S3.18).
    materials_json = [
        # doubleSided so Blender's importer doesn't backface-cull thin geometry (skirts,
        # capes, hair cards) while the mesh is being edited -- purely a display aid, since
        # winding below is corrected to read right in a single-sided viewer too.
        {"name": m["slot_name"] or f"mat_{i}", "doubleSided": True}
        for i, m in enumerate(mesh.materials)]

    # One vertex pool PER PRIMITIVE, with section-local indices. Sharing a single pool
    # across primitives is legal glTF but means every primitive nominally spans the whole
    # mesh, which round-trips badly; per-primitive pools also match both how the cooked
    # format stores sections and how Blender re-exports a multi-material mesh.
    primitives = []
    for sec in lod["sections"]:
        lo, hi = sec["base_vertex"], sec["base_vertex"] + sec["num_verts"]
        idx = np.frombuffer(bytes(mesh._blob(lod)), "<u4" if lod["idx_stride"] == 4 else "<u2",
                            sec["num_tris"] * 3,
                            lod["idx_off"] + sec["base_index"] * lod["idx_stride"])
        # UE winds front faces clockwise; glTF/OpenGL define front as counter-clockwise.
        # _AXIS_R only rotates axes (det +1), so it cannot fix this -- without the swap,
        # every front face is culled on import and only interior back faces render,
        # reading as an inside-out / concave mesh. glb_to_sections swaps back on rebuild.
        idx = idx.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
        attrs = {
            "POSITION":  accessor(pos[lo:hi].astype("f4"), F32, "VEC3", ARRAY, minmax=True),
            "NORMAL":    accessor(normal[lo:hi].astype("f4"), F32, "VEC3", ARRAY),
            # glTF requires TANGENT.w to be exactly +-1; the cooked value is +-0.992.
            "TANGENT":   accessor(np.concatenate(
                             [tangent[lo:hi], np.sign(tan_w[lo:hi])[:, None]], 1).astype("f4"),
                             F32, "VEC4", ARRAY),
            "JOINTS_0":  accessor(global_idx[lo:hi, :4].astype("u2"), U16, "VEC4", ARRAY),
            "WEIGHTS_0": accessor(weight[lo:hi, :4].astype("f4"), F32, "VEC4", ARRAY),
        }
        if lod["max_bone_influences"] > 4:
            attrs["JOINTS_1"]  = accessor(global_idx[lo:hi, 4:8].astype("u2"), U16, "VEC4", ARRAY)
            attrs["WEIGHTS_1"] = accessor(weight[lo:hi, 4:8].astype("f4"), F32, "VEC4", ARRAY)
        for c in range(lod["num_tex_coords"]):
            attrs[f"TEXCOORD_{c}"] = accessor(uv[lo:hi, c, :].astype("f4"), F32, "VEC2", ARRAY)
        if color is not None:
            attrs["COLOR_0"] = accessor(color[lo:hi].astype("f4"), F32, "VEC4", ARRAY)
        primitives.append({
            "attributes": attrs,
            "indices": accessor((idx - lo).astype("<u4"), 5125, "SCALAR", ELEM),
            # The section's own slot index IS the material index -- one glTF material per slot.
            "material": (sec["mat"] if sec["mat"] < len(materials_json) else 0)
                        if materials_json else None,
        })

    nodes = [{"name": b["name"], "children": [], "translation": t.tolist(),
             "rotation": q.tolist(), "scale": s.tolist()}
             for b, (t, q, s) in zip(mesh.bones, node_trs)]
    for i, b in enumerate(mesh.bones):
        if b["parent"] != -1:
            nodes[b["parent"]]["children"].append(i)
    ibm_off, ibm_len = add(ibm)
    skin = {"joints": list(range(len(mesh.bones))), "skeleton": 0,
           "inverseBindMatrices": accessor(ibm, F32, "MAT4")}

    mesh_node = len(nodes)
    nodes.append({"name": "SkeletalMesh", "mesh": 0, "skin": 0})

    gltf = {
        "asset": {"version": "2.0", "generator": "Atelier mesh.py"},
        "scenes": [{"nodes": [0, mesh_node]}], "scene": 0,
        "nodes": nodes,
        "meshes": [{"name": "LOD%d" % lod_index, "primitives": primitives}],
        "materials": materials_json,
        "skins": [skin],
        "accessors": accessors, "bufferViews": bufferViews,
        "buffers": [{"byteLength": len(buf)}],
    }

    json_bytes = json.dumps(gltf).encode("utf-8")
    while len(json_bytes) % 4: json_bytes += b" "
    while len(buf) % 4: buf.append(0)
    with open(out_path, "wb") as f:
        total = 12 + 8 + len(json_bytes) + 8 + len(buf)
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A)); f.write(json_bytes)
        f.write(struct.pack("<II", len(buf), 0x004E4942)); f.write(bytes(buf))
    return out_path
