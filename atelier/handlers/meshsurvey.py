"""Read-only compatibility survey for SkeletalMesh assets.

Everything the mesh editor knows was learned from ONE asset (SK_10290_1029304). This
module answers the question that reorders all remaining work: which format variants does
the game actually ship? It parses every SK_* mesh in the paks -- no packing, no Blender,
no game launch -- and reports a compatibility matrix, plus a per-asset preflight verdict
so a user learns "unsupported because X" before spending an hour sculpting.

WHY A SECOND PARSER. `mesh.py` finds sections by scanning the whole .uexp for records
that look like FSkelMeshRenderSection, and rejects anything with cloth
(CorrespondClothAssetIndex != -1) as a false positive. That is fine for a writer that
refuses cloth anyway, but it makes cloth assets invisible to a survey, which is exactly
what the survey exists to count. So this module walks the export STRUCTURALLY instead --
from the end of the FReferenceSkeleton forward, per CUE4Parse
FStaticLODModel.SerializeRenderItem -- and never guesses:

    bCooked u32, LODCount u32, then per LOD:
      FStripDataFlags(2), bIsLODCookedOut(u32 bool), bInlined(u32 bool),
      RequiredBones TArray<i16>, Sections TArray<FSkelMeshRenderSection>,
      ActiveBoneIndices TArray<i16>, BuffersSize u32,
      if bInlined:  the LOD blob inline
      else:         DataResource index u32, then SerializeAvailabilityInfo

A section record (offsets confirmed against the values mesh.py already reads at bm-33 etc.):

      FStripDataFlags 2 | MaterialIndex i16 | BaseIndex u32 | NumTriangles u32
      bRecomputeTangent u32 | RecomputeTangentsVertexMaskChannel u8
      bCastShadow u32 | bVisibleInRayTracing u32 | BaseVertexIndex u32
      ClothMappingDataLODs  TArray<TArray<FMeshToMeshVertData(64B)>>   <- cloth lives HERE
      BoneMap TArray<u16> | NumVertices i32 | MaxBoneInfluences u32 (bit31 = unified bonemap)
      CorrespondClothAssetIndex i16 | FClothingSectionData 20
      DupVertData i32 count + 4B each | DupVertIndexData i32 count + 8B each | bDisabled u32

The cloth array sits BETWEEN BaseVertexIndex and BoneMap, so on a cloth asset the record
is not a fixed-size prefix and mesh.py's bm-relative anchoring cannot describe it. Walking
forward handles both cases with no special casing.

WHAT MAKES THIS TRUSTWORTHY. A LOD is only accepted if its sections chain exactly --
BaseVertexIndex and BaseIndex each form a running sum from 0 -- and, for a streamed LOD,
if the vertex and index totals derived from those sections equal the independent copies
stored in SerializeAvailabilityInfo. Two derivations from different parts of the file
agreeing is what distinguishes a real parse from a plausible one.

WHY .ubulk IS BARELY READ. SerializeAvailabilityInfo carries every field needed to compute
the streamed blob's byte layout (index width and count, vertex count, UV channels and
precision, tangent precision, skin-weight widths, colour presence). So the tail -- the only
part whose composition cannot be derived -- is read as a small slice at a computed offset
instead of loading a 15 MB .ubulk per asset. Verified on the reference mesh: the computed
LOD0 tail offset yields exactly the 200,140 bytes documented in BLENDER.md 2.4.
"""
import json
import os
import struct
import sys

import numpy as np

from atelier.handlers import mesh as _mesh

# FMeshToMeshVertData: 3x FVector4 + i16[4] + float + u32.
CLOTH_VERT_SIZE = 64
# FClothingSectionData: FGuid + int32.
CLOTHING_SECTION_DATA = 20
# How far past the computed end of a LOD record to look for its successor. The walk should
# land exactly, so this is a measurement instrument rather than slack: any asset needing a
# non-zero gap has a field this parser does not model, and reports it in the matrix.
AVAIL_GAP_SEARCH = 64


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _i32(d, o):
    return struct.unpack_from("<i", d, o)[0]


def _i16(d, o):
    return struct.unpack_from("<h", d, o)[0]


# ── locating the Extras blob quickly ──────────────────────────────────────────

def _try_extras_any_bonecount(d, o, limit):
    """`mesh._try_extras` without its `8 <= nbone` floor.

    That floor exists because the reference mesh's triple-count invariant (RefBoneInfo ==
    RefBonePose == NameToIndexMap) needed help to stay unique across a 5.9 MB file. It
    also silently excludes every prop, weapon and accessory mesh -- which are rigged to
    one or two bones and are a large share of what the game ships. The survey drops the
    floor and replaces it with a far stronger test applied by the caller: the LOD array
    that must follow has to parse and its section chain has to close (see `find_extras`).
    """
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
        (pkg,) = struct.unpack_from("<i", d, o)
        if not -100000 < pkg < 100000:
            return None
        slot = struct.unpack_from("<ii", d, o + 4)
        imported = struct.unpack_from("<ii", d, o + 12)
        o += 4 + 8 + 8 + 20
        if o + 4 > limit:
            return None
        (ntag,) = struct.unpack_from("<I", d, o)
        if not 0 <= ntag <= 64:
            return None
        o += 4 + ntag * 8
        mats.append({"pkg_idx": pkg, "slot_name_idx": slot[0],
                     "imported_slot_name_idx": imported[0]})
    if o + 4 > limit:
        return None
    (nbone,) = struct.unpack_from("<I", d, o)
    if not 1 <= nbone <= 8192:
        return None
    bones_off = o + 4
    bones_end = bones_off + nbone * 12
    if bones_end + 4 > limit:
        return None
    (npose,) = struct.unpack_from("<I", d, bones_end)
    if npose != nbone:
        return None
    pose_off = bones_end + 4
    pose_end = pose_off + nbone * 80
    if pose_end + 4 > limit:
        return None
    (nmap,) = struct.unpack_from("<I", d, pose_end)
    if nmap != nbone:
        return None
    return {"materials": mats, "n_bones": nbone, "bones_off": bones_off,
            "pose_off": pose_off, "skel_end": pose_end + 4 + nbone * 12}


def find_extras(uexp):
    """Locate the materials + FReferenceSkeleton block, and prove it by parsing forward.

    Two changes from `mesh.find_extras`, both needed for breadth:

    SPEED -- the original validates a candidate at every one of ~6M byte offsets, which is
    fine once and far too slow across thousands of assets. A numpy prefilter narrows the
    offsets to those where the u32 could be a material count (1..64) and the next i32
    could be an FPackageIndex, cutting the candidate set by orders of magnitude without
    changing what counts as a match.

    CERTAINTY -- rather than leaning on a bone-count floor to stay unique, a candidate is
    accepted only if `bCooked` and `LODCount` that follow it are sane AND the first LOD
    record parses with its section chain closing exactly. A false positive would have to
    be followed by a byte-perfect LOD array, which does not happen by accident.
    """
    a = np.frombuffer(uexp, np.uint8)
    if a.size < 32:
        raise ValueError("uexp too small")
    n = a.size - 8

    def word(off):
        return (a[off:off + n].astype(np.uint32)
                | a[off + 1:off + 1 + n].astype(np.uint32) << 8
                | a[off + 2:off + 2 + n].astype(np.uint32) << 16
                | a[off + 3:off + 3 + n].astype(np.uint32) << 24)

    count = word(0)
    pkg = word(4).astype(np.int32)
    cand = np.nonzero((count >= 1) & (count <= 64) & (pkg > -100000) & (pkg < 100000))[0]
    limit = len(uexp)
    fallback = None
    for o in cand.tolist():
        r = _try_extras_any_bonecount(uexp, int(o), limit)
        if not r:
            continue
        end = r["skel_end"]
        if end + 8 > limit:
            continue
        cooked, n_lods = struct.unpack_from("<II", uexp, end)
        if cooked not in (0, 1) or not 1 <= n_lods <= 16:
            continue
        if _try_lod(uexp, end + 8, limit - 4) is not None:
            r["lod_count"] = n_lods
            r["cooked"] = cooked
            return r
        if fallback is None:
            fallback = r          # skeleton looked right but no LOD array followed
    if fallback is not None:
        raise ValueError("found a skeleton but no valid LOD array followed it")
    raise ValueError("no SkeletalMesh Extras (materials+skeleton) found")


# A package's exports each have a class default object named `Default__<Class>` in the
# name table, which is the cheapest reliable way to tell what an asset actually is
# without replicating the versioned export table. Ordered most- to least-specific so a
# SkeletalMesh that merely imports a PhysicsAsset is still reported as a SkeletalMesh.
_CLASS_PROBES = ("SkeletalMesh", "StaticMesh", "PhysicsAsset", "Skeleton",
                 "AnimSequence", "PhysicsConstraintTemplate", "Material",
                 "MaterialInstanceConstant", "Texture2D")


def asset_class(uasset):
    """Best-effort class of a package's primary export, or None if undetermined."""
    names = None
    # find_name_table's default 20-entry floor keeps it unique inside a multi-megabyte
    # character mesh; the trivial shell packages this survey also walks past have fewer
    # names than that in total, so retry lower before giving up.
    for min_run in (20, 6, 3):
        try:
            _, names = _mesh.find_name_table(uasset, min_run=min_run)
            break
        except Exception:
            continue
    if names is None:
        return None
    present = set(names)
    for c in _CLASS_PROBES:
        if "Default__" + c in present:
            return c
    return None


# ── structural walk ───────────────────────────────────────────────────────────

def _walk_sections(d, o, nsec, limit):
    """Parse `nsec` consecutive FSkelMeshRenderSection records starting at `o`."""
    secs = []
    for _ in range(nsec):
        start = o
        if o + 33 > limit or struct.unpack_from("<H", d, o)[0] != 1:
            raise ValueError("section strip flags")
        mat = _i16(d, o + 2)
        base_index = _u32(d, o + 4)
        num_tris = _u32(d, o + 8)
        recompute_tangent = _u32(d, o + 12)
        mask_channel = d[o + 16]
        cast_shadow = _u32(d, o + 17)
        ray_tracing = _u32(d, o + 21)
        base_vertex = _u32(d, o + 25)
        o += 29
        n_cloth_lods = _i32(d, o); o += 4
        if not 0 <= n_cloth_lods <= 64:
            raise ValueError("cloth LOD count")
        cloth_lods = []
        for _ in range(n_cloth_lods):
            c = _i32(d, o)
            if not 0 <= c <= 4_000_000:
                raise ValueError("cloth vert count")
            o += 4 + c * CLOTH_VERT_SIZE
            cloth_lods.append(c)
        n_bonemap = _i32(d, o)
        if not 0 <= n_bonemap <= 65536:
            raise ValueError("bonemap count")
        o += 4 + n_bonemap * 2
        num_verts = _i32(d, o); o += 4
        packed = _u32(d, o); o += 4
        cloth_asset = _i16(d, o); o += 2 + CLOTHING_SECTION_DATA
        n_dup = _i32(d, o)
        if not 0 <= n_dup <= 8_000_000:
            raise ValueError("dup vert count")
        o += 4 + n_dup * 4
        n_dup_idx = _i32(d, o)
        if not 0 <= n_dup_idx <= 8_000_000:
            raise ValueError("dup vert index count")
        o += 4 + n_dup_idx * 8
        disabled = _u32(d, o); o += 4
        if o > limit:
            raise ValueError("section overruns export")
        secs.append({
            "off": start, "mat": mat, "base_index": base_index, "num_tris": num_tris,
            "base_vertex": base_vertex, "num_verts": num_verts,
            "bonemap_count": n_bonemap,
            "max_infl": packed & 0x7FFFFFFF, "unified_bonemap": packed >> 31,
            "cloth_asset": cloth_asset, "cloth_lods": cloth_lods,
            "recompute_tangent": recompute_tangent, "mask_channel": mask_channel,
            "cast_shadow": cast_shadow, "ray_tracing": ray_tracing,
            "disabled": disabled, "n_dup": n_dup, "n_dup_idx": n_dup_idx,
        })
    return secs, o


def _try_lod(d, o, limit):
    """Validate a LOD record starting at `o`, or return None.

    Acceptance requires the section chain to be exact: BaseVertexIndex and BaseIndex are
    running sums over the sections in order (BLENDER.md 2.2). That invariant is strong
    enough to locate LOD boundaries without knowing every trailing field, which is what
    lets the walk survive the unidentified bytes after SerializeAvailabilityInfo.
    """
    try:
        if o + 18 > limit or struct.unpack_from("<H", d, o)[0] != 1:
            return None
        cooked_out, inlined = _i32(d, o + 2), _i32(d, o + 6)
        if cooked_out not in (0, 1) or inlined not in (0, 1):
            return None
        n_required = _i32(d, o + 10)
        if not 0 <= n_required <= 65536:
            return None
        p = o + 14 + n_required * 2
        if p + 4 > limit:
            return None
        nsec = _i32(d, p)
        if not 1 <= nsec <= 256:
            return None
        secs, end = _walk_sections(d, p + 4, nsec, limit)
        base_vertex = base_index = 0
        for s in secs:
            if s["base_vertex"] != base_vertex or s["base_index"] != base_index:
                return None
            base_vertex += s["num_verts"]
            base_index += s["num_tris"] * 3
        return {"start": o, "cooked_out": cooked_out, "inlined": inlined,
                "n_required_bones": n_required, "sections": secs,
                "after_sections": end, "num_verts": base_vertex, "n_indices": base_index}
    except (struct.error, ValueError, IndexError):
        return None


def _read_availability(d, o, has_cloth, limit):
    """FSkeletalMeshLODRenderData::SerializeAvailabilityInfo -- the .uexp's copy of every
    streamed buffer's header. This is the record `mesh.Mesh._patch_mirror` currently
    rewrites by find-and-replace within a byte window; parsed here it is exact."""
    a = {}
    a["idx_stride"] = d[o]; o += 1
    a["n_indices"] = _i32(d, o); o += 4
    (a["num_tex_coords"], a["smvb_num_verts"], a["full_prec_uv"],
     a["hi_prec_tangent"]) = struct.unpack_from("<IIII", d, o); o += 16
    a["pos_stride"], a["pos_num_verts"] = struct.unpack_from("<II", d, o); o += 8
    a["col_stride"], a["col_num_verts"] = struct.unpack_from("<II", d, o); o += 8
    (a["variable_bones"], a["max_bone_influences"], a["num_bones"],
     a["sw_num_verts"], a["bone_index_16"], a["bone_weight_16"]) = \
        struct.unpack_from("<IIIIII", d, o); o += 24
    # FSkinWeightVertexBuffer::SerializeMetaData writes the DATA buffer's fields and then
    # the LOOKUP buffer's NumVertices (CUE4Parse MetadataSize: "if (bNewWeightFormat)
    # numBytes += 4"). Omitting it happens to survive on a mesh with fixed influences --
    # the field reads 0, and the SkinWeightProfiles count that gets read in its place is
    # also 0 -- then desynchronises the moment bVariableBonesPerVertex is set and the
    # lookup buffer is actually populated.
    a["num_lookup_verts"] = _u32(d, o); o += 4
    if has_cloth:
        n = _i32(d, o); o += 4 + n * 8 + 8 + n * 4      # FSkeletalMeshVertexClothBuffer meta
        a["cloth_mappings"] = n
    n_profiles = _i32(d, o); o += 4 + n_profiles * 8    # TArray<FName>
    a["skin_weight_profiles"] = n_profiles
    if o > limit:
        raise ValueError("availability info overruns export")
    return a, o


def _tail_candidates(a):
    """Candidate byte offsets of the tail within a streamed LOD blob, computed purely from
    the availability-info fields -- so the tail can be read as a small slice instead of
    loading a 15 MB .ubulk per asset. Mirrors SerializeStreamedData's buffer order.

    Verified against the reference mesh: LOD0 lands at 9,666,367 of a 9,866,507-byte blob,
    leaving exactly the 200,140-byte tail BLENDER.md 2.4 measured by hand.

    Two candidates, because the colour buffer is CONDITIONAL. SerializeStreamedData writes
    it only `if (bHasVertexColors)` -- when a mesh has no vertex colours the buffer is
    absent outright, not present-and-empty. The availability mirror always carries colour
    metadata, so a zero NumVertices there is ambiguous between "empty buffer written" and
    "no buffer written", and the ambiguity is 10 bytes wide. Assuming the wrong one
    silently eats the front of the tail; the caller picks whichever walks to the blob's
    end exactly.
    """
    nv = a["pos_num_verts"]
    ntc = a["num_tex_coords"]
    tan_size = 16 if a["hi_prec_tangent"] else 8
    uv_size = 8 if a["full_prec_uv"] else 4
    idx_bytes = a["n_indices"] * a["idx_stride"]
    # NumBones is the total influence slot count, so this holds for variable-influence
    # meshes as well as fixed ones.
    sw_bytes = a["num_bones"] * ((2 if a["bone_index_16"] else 1)
                                 + (2 if a["bone_weight_16"] else 1))
    o = 2 + 1 + 8 + idx_bytes                                   # strip, DataTypeSize, bulk
    o += 8 + 8 + nv * a["pos_stride"]                           # position
    o += 2 + 16                                                 # FStaticMeshVertexBuffer hdr
    o += 8 + nv * tan_size                                      # tangents
    o += 8 + nv * ntc * uv_size                                 # UVs
    o += 2 + 24 + 8 + sw_bytes                                  # skin weights
    o += 2 + 4 + 8 + a.get("num_lookup_verts", 0) * 4           # lookup buffer
    if a["col_num_verts"]:
        return [o + 2 + 8 + 8 + a["col_num_verts"] * a["col_stride"]]
    return [o, o + 2 + 8]                                       # absent, or present-empty


def _walk_tail(blob, o, end, has_cloth=False):
    """Split the post-colour tail, reporting composition rather than assuming it.

    Order per FStaticLODModel.SerializeStreamedData: the cloth buffer (only when the LOD
    has cloth), FSkinWeightProfilesData, ray-tracing data, the
    bSerializeCompressedMorphTargets gate and its buffers, the vertex-attribute map, then
    a half-edge buffer on newer engines.
    """
    t = {"tail_bytes": end - o}
    start = o
    if has_cloth:
        # FSkeletalMeshVertexClothBuffer: strip flags, a bulk array of per-vertex mapping
        # data, then TArray<uint64> ClothIndexMapping and a per-entry LOD-bias int32.
        o += 2
        esz, cnt = struct.unpack_from("<II", blob, o); o += 8 + esz * cnt
        n_map = _i32(blob, o); o += 4 + n_map * 8 + n_map * 4
        t["cloth_buffer_bytes"] = o - start
        t["cloth_verts"] = cnt
        t["cloth_index_mappings"] = n_map
    t["skin_weight_profiles"] = _i32(blob, o); o += 4
    rt = _i32(blob, o); o += 4 + rt
    t["ray_tracing_bytes"] = rt
    t["prefix_bytes"] = o - start
    gate = _i32(blob, o); o += 4
    t["has_morphs"] = bool(gate)
    if gate:
        morph_start = o
        n_words = _i32(blob, o); o += 4 + n_words * 4
        for _ in range(2):                                      # Min/MaximumValuePerMorph
            c = _i32(blob, o); o += 4 + c * 16
        for _ in range(2):                                      # BatchStartOffset/BatchesPerMorph
            c = _i32(blob, o); o += 4 + c * 4
        o += 12                                                 # NumTotalBatches + 2 precisions
        t["morph_bytes"] = o - morph_start
        t["morph_words"] = n_words
    else:
        t["morph_bytes"] = 0
    t["suffix_bytes"] = end - o
    if t["suffix_bytes"] < 0:
        raise ValueError("tail walk overran the blob")
    return t


def _resolve_tail(read_tail, candidates, has_cloth):
    """Walk the tail at each candidate offset and keep the reading that lands exactly on
    the blob's end.

    A tail walk is self-checking: every structure in it is length-prefixed, so a wrong
    starting offset almost always either overruns the blob or finishes with bytes left
    over. Requiring zero leftover bytes turns the colour-buffer ambiguity into a decision
    the data makes rather than one this parser guesses at. `suffix_bytes` is what remains
    after the vertex-attribute map, so a residue of 0 or 4 is expected; anything else
    means an unmodelled trailing structure and is reported, not smoothed over.
    """
    best, first_error = None, None
    for off in candidates:
        try:
            chunk = read_tail(off)
            t = _walk_tail(chunk, 0, len(chunk), has_cloth)
        except (struct.error, ValueError, OSError, IndexError) as e:
            if first_error is None:
                first_error = str(e)
            continue
        t["tail_off"] = off
        if t["suffix_bytes"] in (0, 4):
            return t
        if best is None or t["suffix_bytes"] < best["suffix_bytes"]:
            best = t
    if best is not None:
        return best
    return {"tail_error": first_error or "no tail candidate walked cleanly"}


# ── the probe ─────────────────────────────────────────────────────────────────

# Each entry is a format variant the rebuild path does not implement. Names are stable so
# the matrix can be aggregated across runs.
UNSUPPORTED = {
    "cloth": "sections carry cloth mapping data (vertex-indexed; a rebuild invalidates it)",
    "half_precision_uv": "bUseFullPrecisionUVs == 0",
    "high_precision_tangent": "bUseHighPrecisionTangentBasis == 1",
    "bone_index_16": "bUse16BitBoneIndex == 1",
    "bone_weight_16": "bUse16BitBoneWeight == 1",
    "skin_weight_profiles": "FSkinWeightProfilesData is non-empty",
    "unified_bonemap": "section uses the UE5 unified-bonemap packing",
    "bonemap_overflow": "a section's BoneMap exceeds 256 bones (8-bit local indices)",
    "no_sections": "no LOD parsed",
}

WARNINGS = {
    "morphs": "morph targets present -- a Blender rebuild drops them",
    "index_16_headroom": "a 16-bit LOD is close to the 65,536-vertex ceiling",
    "cooked_out_lod": "a LOD is cooked out (bIsLODCookedOut)",
    "disabled_section": "a section is flagged bDisabled",
    "variable_bones": "bVariableBonesPerVertex == 1 -- decoded via the per-vertex lookup "
                       "table; influence counts above 8 are capped to the 8 heaviest and "
                       "renormalised (mean measured at ~3.24/vertex, so this is rarely lossy)",
}


def probe(base, read_tails=True):
    """Parse one mesh and report its format. Never raises: a failure is a result.

    `base` is a path with no extension; `base + '.uasset'` and `.uexp` must exist.
    """
    rec = {"base": base, "name": os.path.basename(base), "status": "ok",
           "unsupported": [], "warnings": [], "error": None}
    try:
        uexp = open(base + ".uexp", "rb").read()
        uasset = open(base + ".uasset", "rb").read()
    except OSError as e:
        rec["status"] = "error"; rec["error"] = f"read: {e}"
        return rec
    ubulk_path = base + ".ubulk"
    ubulk_len = os.path.getsize(ubulk_path) if os.path.exists(ubulk_path) else 0
    rec["uexp_bytes"], rec["uasset_bytes"], rec["ubulk_bytes"] = \
        len(uexp), len(uasset), ubulk_len

    rec["asset_class"] = asset_class(uasset)
    try:
        extras = find_extras(uexp)
    except Exception as e:
        # A .uasset whose name is SK_* is not necessarily a SkeletalMesh -- the game ships
        # PhysicsAssets called SK_Physics_Death, and SK_*_Skeleton/_PhysicsAsset siblings.
        # Those are "not applicable", not parser failures, and must not pollute the matrix.
        if rec["asset_class"] and rec["asset_class"] != "SkeletalMesh":
            rec["status"] = "skipped"
            rec["error"] = f"not a SkeletalMesh (class {rec['asset_class']})"
        else:
            rec["status"] = "error"
            rec["error"] = f"extras: {e}"
        return rec
    rec["n_bones"] = extras["n_bones"]
    rec["n_materials"] = len(extras["materials"])
    rec["cooked"] = extras["cooked"]
    n_lods = extras["lod_count"]
    rec["lod_count"] = n_lods
    o = extras["skel_end"] + 8

    # DataResourceMap: streamed LOD blob extents, needed to bound each tail.
    drm = []
    if ubulk_len:
        drm_off = _mesh.find_data_resource_map(uasset, ubulk_len)
        if drm_off is not None:
            n = _u32(uasset, drm_off)
            e = drm_off + 4
            for _ in range(n):
                drm.append((struct.unpack_from("<q", uasset, e + 4)[0],
                            struct.unpack_from("<q", uasset, e + 20)[0]))
                e += 44
    rec["data_resources"] = len(drm)

    limit = len(uexp) - 4
    lods, ubulk_fh = [], None
    try:
        for i in range(n_lods):
            h = _try_lod(uexp, o, limit)
            if h is None:
                raise ValueError(f"LOD{i} header/section chain did not validate at {o}")
            p = h["after_sections"]
            n_active = _i32(uexp, p); p += 4 + n_active * 2
            buffers_size = _u32(uexp, p); p += 4
            has_cloth = any(s["cloth_lods"] for s in h["sections"])
            lod = {"index": i, "inlined": bool(h["inlined"]),
                   "cooked_out": bool(h["cooked_out"]),
                   "n_required_bones": h["n_required_bones"],
                   "n_active_bones": n_active, "n_sections": len(h["sections"]),
                   "num_verts": h["num_verts"], "n_indices": h["n_indices"],
                   "buffers_size": buffers_size, "has_cloth": has_cloth,
                   "max_bonemap": max(s["bonemap_count"] for s in h["sections"]),
                   "max_section_infl": max(s["max_infl"] for s in h["sections"]),
                   "cloth_sections": sum(1 for s in h["sections"] if s["cloth_lods"]),
                   "disabled_sections": sum(1 for s in h["sections"] if s["disabled"]),
                   "unified_bonemap": any(s["unified_bonemap"] for s in h["sections"]),
                   "sections": [{k: s[k] for k in
                                 ("mat", "num_verts", "num_tris", "bonemap_count",
                                  "max_infl", "cloth_asset", "cloth_lods", "disabled")}
                                for s in h["sections"]]}

            if h["inlined"]:
                blob_start, blob_end, where = p, p + buffers_size, "uexp"
                p += buffers_size
                # An inline LOD stores no availability info; read its real headers instead.
                a = _read_inline_headers(uexp, blob_start)
                lod["avail_gap"] = None
            else:
                res_idx = _u32(uexp, p); p += 4
                a, p = _read_availability(uexp, p, has_cloth, limit)
                if a["n_indices"] != h["n_indices"] or a["pos_num_verts"] != h["num_verts"]:
                    raise ValueError(
                        f"LOD{i} availability info disagrees with the section chain "
                        f"(idx {a['n_indices']} vs {h['n_indices']}, "
                        f"verts {a['pos_num_verts']} vs {h['num_verts']})")
                lod["data_resource"] = res_idx
                if res_idx < len(drm):
                    blob_start, size = drm[res_idx]
                    blob_end, where = blob_start + size, "ubulk"
                else:
                    blob_start = blob_end = None; where = "missing"
                # The successor is located by validation rather than trusted from the
                # summation, and the difference is recorded. It should be 0 now that the
                # lookup-buffer field is accounted for; any asset where it is not has a
                # field this parser does not know about, and says so in the matrix.
                gap = None
                if i + 1 < n_lods:
                    for g in range(AVAIL_GAP_SEARCH):
                        if _try_lod(uexp, p + g, limit):
                            gap = g; break
                    if gap is None:
                        raise ValueError(f"could not locate LOD{i+1} after LOD{i}")
                    p += gap
                lod["avail_gap"] = gap
            lod.update({k: a[k] for k in
                        ("num_tex_coords", "full_prec_uv", "hi_prec_tangent",
                         "idx_stride", "max_bone_influences", "variable_bones",
                         "bone_index_16", "bone_weight_16", "col_num_verts",
                         "skin_weight_profiles")})
            # NumBones is the TOTAL influence-slot count across the LOD, so
            # num_bones/num_verts is the mean influences per vertex -- the number that
            # says how much a variable-influence mesh would actually lose if it were
            # re-encoded as fixed 8.
            lod["num_bones"] = a["num_bones"]
            lod["num_lookup_verts"] = a.get("num_lookup_verts", 0)
            lod["blob"] = where

            if read_tails and blob_start is not None:
                cands = _tail_candidates(a) if where == "ubulk" else a["_tail_offs"]
                if where == "ubulk":
                    if ubulk_fh is None:
                        ubulk_fh = open(ubulk_path, "rb")

                    def read_tail(off, _fh=ubulk_fh, _s=blob_start, _e=blob_end):
                        _fh.seek(_s + off)
                        return _fh.read(_e - _s - off)
                else:
                    def read_tail(off, _s=blob_start, _e=blob_end):
                        return uexp[_s + off:_e]
                lod.update(_resolve_tail(read_tail, cands, has_cloth))
            lods.append(lod)
            o = p
        rec["trailing_bytes"] = limit - o
    except (struct.error, ValueError, IndexError) as e:
        rec["status"] = "error"
        rec["error"] = str(e)
        rec["lods"] = lods
        return rec
    finally:
        if ubulk_fh is not None:
            ubulk_fh.close()

    rec["lods"] = lods
    _classify(rec)
    return rec


def _read_inline_headers(uexp, o):
    """An inline LOD has its real buffer headers in the .uexp, so read them directly
    rather than the availability mirror a streamed LOD carries."""
    a = {}
    start = o
    o += 2                                              # FStripDataFlags
    a["idx_stride"] = uexp[o]; o += 1
    esz, cnt = struct.unpack_from("<II", uexp, o); o += 8
    a["n_indices"] = cnt; o += esz * cnt
    a["pos_stride"], a["pos_num_verts"] = struct.unpack_from("<II", uexp, o); o += 8
    pesz, pcnt = struct.unpack_from("<II", uexp, o); o += 8 + pesz * pcnt
    o += 2
    (a["num_tex_coords"], a["smvb_num_verts"], a["full_prec_uv"],
     a["hi_prec_tangent"]) = struct.unpack_from("<IIII", uexp, o); o += 16
    tesz, tcnt = struct.unpack_from("<II", uexp, o); o += 8 + tesz * tcnt
    uesz, ucnt = struct.unpack_from("<II", uexp, o); o += 8 + uesz * ucnt
    o += 2
    (a["variable_bones"], a["max_bone_influences"], a["num_bones"], a["sw_num_verts"],
     a["bone_index_16"], a["bone_weight_16"]) = struct.unpack_from("<IIIIII", uexp, o)
    o += 24
    sesz, scnt = struct.unpack_from("<II", uexp, o); o += 8 + sesz * scnt
    o += 2 + 4                                          # lookup strip + NumLookupVertices
    lesz, lcnt = struct.unpack_from("<II", uexp, o); o += 8 + lesz * lcnt
    # As in _tail_candidates, the colour buffer may be absent rather than empty; offer both
    # readings and let the tail walk decide which reaches the blob end.
    pre_colour = o
    a["col_stride"], a["col_num_verts"] = struct.unpack_from("<II", uexp, o + 2)
    a["skin_weight_profiles"] = 0
    if a["col_num_verts"]:
        cesz, ccnt = struct.unpack_from("<II", uexp, o + 10)
        a["_tail_offs"] = [o + 10 + 8 + cesz * ccnt - start]
    else:
        a["_tail_offs"] = [pre_colour - start, pre_colour + 10 - start]
    return a


def _classify(rec):
    """Turn parsed fields into the supported/unsupported verdict the preflight reports."""
    bad, warn = set(), set()
    for lod in rec["lods"]:
        if lod["has_cloth"]:
            bad.add("cloth")
        if not lod["full_prec_uv"]:
            bad.add("half_precision_uv")
        if lod["hi_prec_tangent"]:
            bad.add("high_precision_tangent")
        if lod["bone_index_16"]:
            bad.add("bone_index_16")
        if lod["bone_weight_16"]:
            bad.add("bone_weight_16")
        if lod["variable_bones"]:
            warn.add("variable_bones")
        if lod["skin_weight_profiles"]:
            bad.add("skin_weight_profiles")
        if lod["unified_bonemap"]:
            bad.add("unified_bonemap")
        if lod["max_bonemap"] > 256:
            bad.add("bonemap_overflow")
        if lod.get("has_morphs"):
            warn.add("morphs")
        if lod["idx_stride"] == 2 and lod["num_verts"] > 55000:
            warn.add("index_16_headroom")
        if lod["cooked_out"]:
            warn.add("cooked_out_lod")
        if lod["disabled_sections"]:
            warn.add("disabled_section")
    if not rec["lods"]:
        bad.add("no_sections")
    rec["unsupported"] = sorted(bad)
    rec["warnings"] = sorted(warn)
    if bad:
        rec["status"] = "unsupported"
    return rec


# ── batch survey ──────────────────────────────────────────────────────────────

_SKIP_SUFFIXES = ("_Skeleton", "_PhysicsAsset", "_PhysicalAsset")


def candidate_meshes(prefix="Characters/", bodies_only=False):
    """Every SK_* package in the paks that could be a SkeletalMesh, as game_rel paths.

    Name-based filtering only narrows the list -- the game ships PhysicsAssets called
    SK_Physics_Death, so the authoritative check is `asset_class` after extraction. The
    suffix skips here just avoid extracting thousands of packages known not to be meshes.

    `bodies_only` restricts to playable character body meshes (see `_BODY_MESH`). They are
    ~10% of the candidates and carry essentially all of the decision-relevant variance --
    the rest are weapon shells, emote props and lobby stand-ins -- so surveying them first
    gets the matrix to a usable state long before the full sweep finishes.
    """
    from atelier.index import ensure_index
    out = []
    for virt, _container, _pfx in ensure_index():
        if not virt.lower().endswith(".uasset"):
            continue
        stem = os.path.basename(virt)[:-7]
        if not stem.lower().startswith("sk_"):
            continue
        if any(stem.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        if prefix and not virt.startswith(prefix):
            continue
        if bodies_only and not _BODY_MESH.match(virt[:-7]):
            continue
        out.append(virt[:-7])
    return sorted(set(out))


def _probe_tree(root):
    """Probe every SK_* package under `root`, keyed by content-relative PATH.

    Keying by basename would collapse real coverage: the game ships one SK_Shell_Lobby
    and one SK_Physics_Death per character, so a single UAssetTool name filter extracts
    dozens of distinct packages that happen to share a name. Each is a separate asset and
    gets its own record.
    """
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".uasset") or not f.lower().startswith("sk_"):
                continue
            stem = f[:-7]
            if any(stem.endswith(s) for s in _SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, stem)
            rec = probe(full)
            rec.pop("base", None)
            rec["path"] = os.path.relpath(full, root).replace("\\", "/")
            out[rec["path"]] = rec
    return out


def survey(out_path, prefix="Characters/", batch_size=64, limit=None, log=print,
           bodies_only=False):
    """Extract, probe and discard every candidate mesh, appending one JSON record per
    line to `out_path`. Resumable: names already present are not re-extracted.

    Extraction is batched because UAssetTool spends ~8s indexing the pak containers on
    every invocation regardless of how much is asked for, so a batch of 64 costs about
    the same as a batch of 3. It is also deliberately greedy: the tool's `--filter` is a
    substring match, so asking for one mesh routinely yields a dozen related packages.
    Those are probed too rather than thrown away -- they are meshes the survey wants
    anyway, and counting them here removes them from later batches.
    """
    import shutil
    from atelier.config import PAKS, _CACHE
    from atelier.tools import uat

    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["name"])
                except Exception:
                    continue
        log(f"resuming: {len(done)} already probed")

    targets = candidate_meshes(prefix, bodies_only=bodies_only)
    if limit:
        targets = targets[:limit]
    todo = [t for t in targets if os.path.basename(t) not in done]
    log(f"{len(targets)} candidates, {len(todo)} to go")

    stage = os.path.join(_CACHE, "mesh_survey")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    n_written = 0
    with open(out_path, "a", encoding="utf-8") as out:
        i = 0
        while i < len(todo):
            names = []
            while i < len(todo) and len(names) < batch_size:
                nm = os.path.basename(todo[i])
                i += 1
                if nm in done:
                    continue
                names.append(nm); done.add(nm)
            if not names:
                continue
            shutil.rmtree(stage, ignore_errors=True)
            os.makedirs(stage, exist_ok=True)
            try:
                uat(["extract_iostore_legacy", PAKS, os.path.abspath(stage),
                     "--filter"] + names)
                recs = _probe_tree(stage)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
            # A name filter extracts every copy of that name at once, so once a name has
            # been requested it is fully covered and later batches need not ask again.
            # Records whose name was already covered by an EARLIER batch are dropped here
            # to avoid duplicate lines; names first seen in this batch are kept in full.
            for rec in recs.values():
                stem = rec["name"]
                if stem in done and stem not in names:
                    continue
                done.add(stem)
                out.write(json.dumps(rec) + "\n")
                n_written += 1
            out.flush()
            log(f"  {i}/{len(todo)} requested, {n_written} records written")
    return n_written


# A playable character's body mesh lives at Characters/<charId>/<skinId>/Meshes/**/ and is
# named for the skin it belongs to (SK_10290_1029304 under .../1029304/). That is the thing
# a modder actually sculpts; the same folders also hold weapon shells, emote props and
# lobby-only variants, which are far more numerous and far simpler, and which would swamp
# the matrix if counted together.
_BODY_MESH = __import__("re").compile(
    r"^Characters/(\d{4})/(\d{6,8})/Meshes/.*/?SK_[^/]*\2$")


def is_body_mesh(rec):
    p = (rec.get("path") or "")
    i = p.find("Characters/")
    return bool(i >= 0 and _BODY_MESH.match(p[i:]))


def summarize(path, segment=None):
    """Aggregate a survey .jsonl into the compatibility matrix.

    `segment` may be "body" (playable character body meshes only), "other" (everything
    else), or None for all parsed meshes.
    """
    import collections
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except Exception:
                continue
    meshes = [r for r in recs if r["status"] in ("ok", "unsupported")]
    if segment == "body":
        meshes = [r for r in meshes if is_body_mesh(r)]
    elif segment == "other":
        meshes = [r for r in meshes if not is_body_mesh(r)]
    counts = collections.Counter(r["status"] for r in recs)
    lods = [l for r in meshes for l in r["lods"]]

    def dist(fn, src=lods):
        return dict(sorted(collections.Counter(fn(x) for x in src).items(),
                           key=lambda kv: (-kv[1], str(kv[0]))))

    n = len(meshes)
    blocked = collections.Counter(k for r in meshes for k in r["unsupported"])
    return {
        "segment": segment or "all",
        "records": len(recs),
        "status": dict(counts),
        "classes": dist(lambda r: r.get("asset_class"), recs),
        "parsed_meshes": n,
        "editable": sum(1 for r in meshes if r["status"] == "ok"),
        "editable_pct": round(100.0 * sum(1 for r in meshes if r["status"] == "ok")
                              / n, 1) if n else 0.0,
        "blocked_by": {k: {"meshes": v, "pct": round(100.0 * v / n, 1)}
                       for k, v in blocked.most_common()},
        "warnings": dict(collections.Counter(k for r in meshes for k in r["warnings"])),
        "lod_count": dist(lambda r: r["lod_count"], meshes),
        "uv_channels": dist(lambda l: l["num_tex_coords"]),
        "full_precision_uv": dist(lambda l: bool(l["full_prec_uv"])),
        "high_precision_tangent": dist(lambda l: bool(l["hi_prec_tangent"])),
        "index_width_bits": dist(lambda l: l["idx_stride"] * 8),
        "max_bone_influences": dist(lambda l: l["max_bone_influences"]),
        "variable_bones_per_vertex": dist(lambda l: bool(l["variable_bones"])),
        "bone_index_16": dist(lambda l: bool(l["bone_index_16"])),
        "bone_weight_16": dist(lambda l: bool(l["bone_weight_16"])),
        "skin_weight_profiles": dist(lambda l: bool(l["skin_weight_profiles"])),
        "cloth_lods": dist(lambda l: l["has_cloth"]),
        "vertex_colors": dist(lambda l: bool(l["col_num_verts"])),
        "morphs_per_lod": dist(lambda l: l.get("has_morphs")),
        "tail_suffix_bytes": dist(lambda l: l.get("suffix_bytes")),
        "avail_gap": dist(lambda l: l.get("avail_gap")),
        "sections_per_lod": dist(lambda l: min(l["n_sections"], 40)),
        "max_bonemap_bucket": dist(lambda l: min(l["max_bonemap"] // 32 * 32, 512)),
        "mean_influences_per_vertex": (
            round(sum(l["num_bones"] for l in lods if l.get("num_bones")
                      and l["variable_bones"])
                  / max(1, sum(l["num_verts"] for l in lods
                               if l.get("num_bones") and l["variable_bones"])), 2)
            if any(l["variable_bones"] and l.get("num_bones") for l in lods) else None),
        "bonemap_over_256": sum(1 for l in lods if l["max_bonemap"] > 256),
        "unified_bonemap": sum(1 for l in lods if l["unified_bonemap"]),
        "index16_headroom": sorted(
            ((l["num_verts"], r["name"]) for r in meshes for l in r["lods"]
             if l["idx_stride"] == 2), reverse=True)[:10],
        "errors": dict(collections.Counter(
            str(r.get("error"))[:70] for r in recs if r["status"] == "error")),
        "tail_errors": sum(1 for l in lods if "tail_error" in l),
    }


def verdict_text(rec):
    """One-paragraph human answer to 'can I edit this mesh?'."""
    if rec["status"] == "error":
        return f"{rec['name']}: PARSE FAILED -- {rec['error']}"
    lines = []
    if rec["status"] == "unsupported":
        lines.append(f"{rec['name']}: NOT SUPPORTED")
        for k in rec["unsupported"]:
            lines.append(f"  - {k}: {UNSUPPORTED.get(k, k)}")
    else:
        lines.append(f"{rec['name']}: supported")
    for k in rec["warnings"]:
        lines.append(f"  ! {k}: {WARNINGS.get(k, k)}")
    lines.append(f"  {rec['lod_count']} LOD(s), {rec['n_materials']} material(s), "
                 f"{rec['n_bones']} bones")
    for lod in rec["lods"]:
        lines.append(
            f"  LOD{lod['index']}: {lod['num_verts']} verts, {lod['n_indices']//3} tris, "
            f"{lod['n_sections']} sections, {lod['num_tex_coords']} UV, "
            f"idx{lod['idx_stride']*8}bit, maxinfl {lod['max_bone_influences']}, "
            f"bonemap<={lod['max_bonemap']}, {lod['blob']}"
            + (", morphs" if lod.get("has_morphs") else ""))
    return "\n".join(lines)


def preflight(game_rel, base_path=None):
    """Probe one asset by game_rel, extracting it first if it is not already cached.

    This is the "will this work before I spend an hour sculpting" check.
    """
    if base_path is None:
        import atelier.asset_cache as _ac
        from atelier.handlers.texture import find_extracted
        base_path = _ac.cache_base(game_rel) or find_extracted(game_rel)
        if not base_path or not os.path.exists(base_path + ".uasset"):
            from atelier.config import PAKS, WORK_IMPORT_ROOT
            from atelier.tools import uat
            uat(["extract_iostore_legacy", PAKS, os.path.abspath(WORK_IMPORT_ROOT),
                 "--filter", os.path.basename(game_rel)])
            base_path = find_extracted(game_rel)
        if not base_path:
            raise RuntimeError(f"could not extract {game_rel}")
    return probe(base_path)


def _main(argv):
    if not argv or argv[0] not in ("survey", "report", "preflight"):
        print("usage:\n"
              "  python -m atelier.handlers.meshsurvey survey [--out PATH] "
              "[--prefix P] [--limit N] [--batch N]\n"
              "  python -m atelier.handlers.meshsurvey report [--out PATH]\n"
              "  python -m atelier.handlers.meshsurvey preflight <game_rel|--base PATH>")
        return 2
    cmd = argv[0]
    opts, rest = {}, argv[1:]
    pos = [a for a in rest if not a.startswith("--")]
    for i, a in enumerate(rest):
        if a.startswith("--") and i + 1 < len(rest):
            opts[a[2:]] = rest[i + 1]
            if rest[i + 1] in pos:
                pos.remove(rest[i + 1])
    from atelier.config import _CACHE
    out = opts.get("out") or os.path.join(_CACHE, "mesh_survey.jsonl")

    if cmd == "survey":
        n = survey(out, prefix=opts.get("prefix", "Characters/"),
                   batch_size=int(opts.get("batch", 64)),
                   limit=int(opts["limit"]) if "limit" in opts else None,
                   bodies_only=bool(opts.get("bodies")),
                   log=lambda m: print(m, flush=True))
        print(f"\n{n} records -> {out}")
        print(json.dumps(summarize(out), indent=2))
    elif cmd == "report":
        print(json.dumps(summarize(out, segment=opts.get("segment")), indent=2))
    else:
        rec = preflight(pos[0] if pos else None, base_path=opts.get("base"))
        print(verdict_text(rec))
        return 0 if rec["status"] == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
