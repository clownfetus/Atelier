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
import os
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
            "tris_off": o - 25, "after": end + 10}


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

    def save(self, out_dir, name):
        os.makedirs(out_dir, exist_ok=True)
        for ext, data in ((".uexp", self.uexp), (".ubulk", self.ubulk)):
            if data:
                open(os.path.join(out_dir, name + ext), "wb").write(bytes(data))
        src = self.base + ".uasset"
        if os.path.exists(src):
            open(os.path.join(out_dir, name + ".uasset"), "wb").write(open(src, "rb").read())


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
