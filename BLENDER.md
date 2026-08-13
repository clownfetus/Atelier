# Blender mesh editing — format spec, hard-won gotchas, and remaining work

Pipeline for editing Marvel Rivals SkeletalMesh geometry in Blender and packing the result
as a playable mod. Vertices may be added, removed, moved, subdivided or sculpted; the
skeleton and material set stay exactly as cooked.

    python -m atelier.handlers.meshedit preflight <game_rel>
    python -m atelier.handlers.meshedit extract   <game_rel> [--base PATH] [--blend PATH]
    python -m atelier.handlers.meshedit build     <game_rel> [--base PATH] [--blend PATH] [--name N]

Code: [`atelier/handlers/mesh.py`](atelier/handlers/mesh.py) (format + rebuild),
[`atelier/handlers/meshedit.py`](atelier/handlers/meshedit.py) (driver/CLI),
[`atelier/handlers/meshsurvey.py`](atelier/handlers/meshsurvey.py) (read-only format
survey + preflight), [`atelier/blender/*.py`](atelier/blender) (headless Blender steps).

The format was established against `SK_10290_1029304` (Magik, INFERNAL IDOL) on UE 5.3 /
S9.5, cross-checked against the CUE4Parse and UAssetToolRivals sources in `sources/`, and
validated in-game. **§4b widens that to every playable-character mesh in the game** — a
read-only survey of all 513 body meshes, which is what the priorities in §5 are ordered by.
Sections marked *Correction* are places where the single-asset reading turned out to be
locally true but not general.

---

## 1. Why this exists

UAssetTool parses a SkeletalMesh export only as far as the `FReferenceSkeleton`
(`SkeletalMeshExport.cs`) and keeps everything after it as one opaque
`RemainingExtraData` blob. There is no `inject_mesh` verb and no way to reach geometry
through `to_json`/`from_json`. `AtelierMesh.exe` decodes meshes for the viewport but is
one-way and lossy (see §3.6). So the render data is parsed and rewritten directly here.

---

## 2. Binary format

### 2.1 Export "Extras" layout

```
FStripDataFlags        2 bytes
FBoxSphereBounds       7 doubles (LWC)  — Origin xyz, BoxExtent xyz, SphereRadius
FSkeletalMaterial[]    int32 count, then per material:
                         FPackageIndex        4
                         MaterialSlotName     FName 8
                         ImportedSlotName     FName 8
                         FMeshUVChannelInfo   20
                         FGameplayTagContainer int32 count + 8 per tag   <- Marvel Rivals
FReferenceSkeleton     RefBoneInfo[]  (int32 count, then FName 8 + int32 parent = 12 each)
                       RefBonePose[]  (int32 count, then FTransform = 80 each, LWC doubles:
                                       FQuat xyzw 32, FVector translation 24, FVector scale 24)
                       NameToIndexMap (int32 count, then FName 8 + int32 = 12 each)
bCooked                uint32
LODCount               uint32
<per-LOD render data>
```

**Locating it without a header parser.** Replicating the versioned package header (custom
version containers, generation counts, engine-version blocks) is fragile. Instead
`find_extras()` scans for a candidate materials array followed by a structure satisfying the
invariant a real `FReferenceSkeleton` always has: **RefBoneInfo count == RefBonePose count
== NameToIndexMap count**. Requiring all *three* to agree (plus ≥8 bones) produced **exactly
one match across the whole 5.9 MB `.uexp`**. Requiring only two matched a bogus 4-bone
candidate at offset 322.

### 2.2 `FSkelMeshRenderSection`

`mesh.py` anchors on the BoneMap count field (`bm`) and reads fixed negative offsets from
it, because scanning for a distinctive field was the only way in before the export could be
walked structurally. The **full record**, per CUE4Parse
`FSkelMeshSection.SerializeRenderItem`, is:

```
FStripDataFlags       2      (reads as uint16 == 1 — the "magic")
MaterialIndex         int16
BaseIndex             uint32   offset into the index buffer
NumTriangles          uint32
bRecomputeTangent     uint32 bool
RecomputeTangentsVertexMaskChannel  uint8   (3 == None)
bCastShadow           uint32 bool
bVisibleInRayTracing  uint32 bool
BaseVertexIndex       uint32
ClothMappingDataLODs  TArray<TArray<FMeshToMeshVertData>>   64 B per entry
BoneMap               TArray<uint16>
NumVertices           int32
MaxBoneInfluences     uint32   bit 31 = unified-bonemap flag, mask it off
CorrespondClothAssetIndex  int16   (-1 == no cloth)
FClothingSectionData  20     (FGuid + int32)
DupVertData           int32 count + 4 B each
DupVertIndexData      int32 count + 8 B each
bDisabled             uint32 bool
```

This identifies what §2.2 previously called an unexplained "flag block" at `bm-21..bm-12`,
and it exposes the reason the `bm`-relative anchoring cannot describe every asset:
**`ClothMappingDataLODs` sits between `BaseVertexIndex` and `BoneMap`**, so on a cloth
section the prefix is not a fixed 33 bytes and `bm-8` is not `BaseVertexIndex`. Cloth
sections are therefore invisible to `find_sections`, not merely rejected by it. The survey
parser (`meshsurvey.py`) walks the record forward instead and handles both shapes.

Sections are **vertex-contiguous** and never share a vertex: a vertex on a material seam is
duplicated once per section. `BaseVertexIndex` and `BaseIndex` form exact running chains
(verified for all three LODs) — this chain is strong enough to serve as the *acceptance
test* for a candidate LOD, which is how the survey locates LOD boundaries without needing
to know every trailing field.

### 2.2b The export is walkable — no scanning required

From `skel_end` (§2.1) the render data is a plain structure, so sections need not be found
heuristically at all:

```
bCooked      uint32
LODCount     uint32
per LOD:
  FStripDataFlags   2
  bIsLODCookedOut   uint32 bool
  bInlined          uint32 bool
  RequiredBones     TArray<int16>
  Sections          TArray<FSkelMeshRenderSection>   (see §2.2)
  ActiveBoneIndices TArray<int16>
  BuffersSize       uint32          <- the LOD blob's byte length
  if bInlined:  the blob, inline
  else:         DataResource index uint32, then SerializeAvailabilityInfo (§2.7)
```

Verified end-to-end on the reference mesh: the walk consumes the export exactly, LOD counts
and vertex totals agree with the independently-stored copies, and it terminates 6 bytes
before the end of `.uexp` (§2.4).

### 2.3 LOD blob (streamed data)

Serialisation order per CUE4Parse `FStaticLODModel.SerializeStreamedData`:

| Buffer | Layout | LOD0 example |
|---|---|---|
| Index | strip(2) + DataTypeSize(u8) + ElemSize(u32) + Count(u32) + payload | 448,272 × 4 |
| Position | Stride(12), NumVertices, **ElementSize(12), Count** then payload | 123,018 × 12 |
| StaticMeshVertexBuffer | strip(2), NumTexCoords, NumVertices, bUseFullPrecisionUVs, bUseHighPrecisionTangentBasis | ntc=3 |
| ├ Tangents | bulk, 8 B/vertex | 123,018 × 8 |
| └ UVs | bulk, 8 B each, **flat N × ntc entries** | 369,054 × 8 |
| SkinWeight | strip(2), bVariableBonesPerVertex, MaxBoneInfluences, NumBones, NumVertices, bUse16BitBoneIndex, bUse16BitBoneWeight, then **byte** bulk array | 1,968,288 B |
| ├ Lookup | strip(2), NumLookupVertices, bulk (empty when influences are fixed) | 0 |
| Color | strip(2), Stride(4), NumVertices, bulk | 123,018 × 4 |
| Tail | see §2.4 | 200,140 B |

**LOD0 blob = 9,866,507 bytes and every extent chains exactly into the next header.** A
"null round-trip" (decompose into typed buffers, then rebuild the bytes purely from parsed
field values) is **byte-identical** for LOD0 and LOD1 — the correctness anchor for the
writer.

### 2.4 The tail (post-Color)

```
FSkinWeightProfilesData        TMap -> int32 count (+entries)
RayTracing                     int32 count + count bytes
bSerializeCompressedMorphTargets   int32 gate
  if set: FMorphTargetVertexInfoBuffers
FSkeletalMeshAttributeVertexBuffer  TMap -> int32 count
[newer engines] MeshDeformerStripFlags(2) + FSkeletalMeshHalfEdgeBuffer
```

Measured: `LOD0 = 4 + 4 + 4 + 200,124 + 4 = 200,140` exactly.

**Correction (from the structural walk, §2.2b).** LOD2's tail was recorded as 77,898 bytes
with a 10-byte suffix containing non-zero data (`00 00 00 00 | 01 03 | 00 00 00 00`). It is
actually **77,892 with the same 4-byte suffix as every other LOD**. The discrepancy was an
artefact of how the end was computed: a streamed LOD's end comes from the DataResourceMap
and is exact, but the inline LOD's end was taken as `len(uexp) - 4`, which swept up **6
bytes that belong to the export, after the LOD array**, not to LOD2. Those 6 bytes are what
§3.3 called "the 4 trailing bytes in LOD2 that remain unidentified". Using `BuffersSize`
(§2.2b) bounds the inline blob exactly and the anomaly disappears. Across 1,542 surveyed
LODs the tail suffix is 4 bytes on 1,538 — it is an invariant, not a per-LOD quirk.

Replaying the tail verbatim (§3.3) was still the right call and is unaffected: it carries
those 6 bytes through either way.

**The colour buffer is conditional.** `SerializeStreamedData` writes it only
`if (bHasVertexColors)`. A mesh without vertex colours has **no colour buffer at all**, not
an empty one — the 10-byte header is absent. Assuming it is always present silently eats
the front of the tail. (Near-universal in practice: 1,540 of 1,542 body-mesh LODs have
colours, which is exactly why this stayed hidden.)

### 2.5 Size bookkeeping outside the blob

| Field | Location | Value |
|---|---|---|
| DataResourceMap | `.uasset`, `count u32` + 44-byte entries | `flags u32, SerialOffset i64, DuplicateOffset i64 = -1, SerialSize i64, RawSize i64, pad u32, LegacyBulkDataFlags u32` |
| Export SerialSize | `.uasset` export table | adjacent `int64 SerialSize, int64 SerialOffset` |
| BulkDataStartOffset | package summary | `len(uasset) + len(uexp) - 4` |
| Metadata mirrors | `.uexp`, after each streamed LOD's sections | blob size, index count, NumVertices (×4), NumBones — decoded exactly in §2.7 |

All four are found by **self-validating structural search**, never hardcoded offsets: the
DataResourceMap by requiring entry offsets to chain from 0 and end exactly at the real
`.ubulk` length; the export SerialSize by `SerialOffset + SerialSize == len(uasset) +
len(uexp) - 4`. Only streamed LODs have metadata mirrors; the inline LOD has its data in
the `.uexp` directly.

### 2.6 NameMap

Length-prefixed strings + a `uint32` hash each. **Positive length = ASCII, negative =
UTF-16LE** (in code units). Marvel Rivals ships Chinese GameplayTag strings
(`MaterialTag.装备.衣服.上衣`), so an ASCII-only reader silently truncates the table —
initially returning 300 of 577 names, which made 214 of 496 bone `FName` indices resolve
out of range. Located by finding the longest unbroken run of valid entries.

### 2.7 `SerializeAvailabilityInfo` — the "metadata mirror", decoded

§2.5 lists a "metadata mirror" that `_patch_mirror` rewrites by find-and-replace inside a
byte window. It is not an ad-hoc mirror: it is
`FSkeletalMeshLODRenderData::SerializeAvailabilityInfo`, and it has an exact layout,
immediately after each streamed LOD's DataResource index:

```
DataTypeSize        uint8      index width, 2 or 4
NumIndices          int32
NumTexCoords        uint32     \
NumVertices         uint32      |  FStaticMeshVertexBuffer::SerializeMetaData
bUseFullPrecisionUVs        uint32  |
bUseHighPrecisionTangentBasis uint32 /
Stride, NumVertices uint32 x2  FPositionVertexBuffer
Stride, NumVertices uint32 x2  FColorVertexBuffer
bVariableBonesPerVertex, MaxBoneInfluences, NumBones, NumVertices,
bUse16BitBoneIndex, bUse16BitBoneWeight     uint32 x6   FSkinWeightDataVertexBuffer
NumLookupVertices   uint32     the LOOKUP buffer's metadata — easy to miss
[if the LOD has cloth]  int32 n + n*8 + 8 + n*4
SkinWeightProfiles  TArray<FName>
```

Two consequences worth stating plainly:

**The lookup-buffer field is real and load-bearing.** Omitting `NumLookupVertices` still
parses a mesh with fixed influences — the field is 0, and the `SkinWeightProfiles` count
read in its place is also 0 — and then desynchronises the moment
`bVariableBonesPerVertex` is set and the lookup buffer is populated. It presented as a
constant, mysterious "4-byte gap" between LODs until the variable-influence assets showed
up. CUE4Parse states it as `if (bNewWeightFormat) numBytes += 4` in
`FSkinWeightVertexBuffer.MetadataSize`.

**This makes the whole streamed blob's layout computable from `.uexp` alone**, which is
what lets the survey read a small tail slice at a computed offset rather than loading a
15 MB `.ubulk` per asset. It also means `_patch_mirror`'s find-and-replace can be replaced
by an exact structured patch (Stage B).



---

## 3. Hard-earned pointers

Each of these cost real debugging time or a crash. They are the reason the code looks the
way it does.

### 3.1 The position payload starts at +16, not +8
The header is **four** `uint32` (`Stride, NumVertices, ElementSize, Count`). Reading at +8
does *not* fail loudly — it rotates values between X/Y/Z, producing a bounding box with the
**same value set** and therefore a plausible-looking result. This led to "discovering" a
bogus `(z,y,x)` axis swizzle. Correctly aligned, **UE is plain Z-up** and section bboxes
read anatomically (head at Z 152–175). A uniform scale hides the bug entirely (scaling is
invariant under component permutation); only a non-uniform edit exposes it.

### 3.2 Never lower `NumTriangles` — the game crashes
Setting a section's `NumTriangles` to 0 (or any lower value) packs fine and then dies on
load with `EXCEPTION_ACCESS_VIOLATION reading 0xb0`. Cooked section counts feed the GPU
skin cache and ray-tracing segment setup, which assume every cooked section is non-empty.
**Hide geometry by collapsing triangles to degenerate indices instead** (all three indices
equal), keeping every count intact.

### 3.3 Never synthesise the tail — replay it
Writing a plausible 32 zero bytes for "no morphs" produced
`ObjectSerializationError: Serial size mismatch: Expected 5807979, Actual 5807969` — a
**10-byte** deficit exactly matching LOD2's real 10-byte suffix, which contains non-zero
strip flags. The correct empty tail is 16 bytes for LOD0/LOD1 and 22 for LOD2, but
computing that is the same guessing that broke it. `_locate_tail()` splits the real tail
into `(prefix, morph block, suffix)` and the rebuild **replays prefix and suffix verbatim**,
clearing only the 4-byte morph gate. This is also version-agnostic: it carries through
half-edge/ray-tracing structures other assets may have, including the 4 trailing bytes in
LOD2 that remain unidentified.

### 3.4 Skin weights are Struct-of-Arrays, not interleaved
`FSkinWeightInfo` is `BoneIndex[8]` **then** `BoneWeight[8]` per vertex (16 B). Reading it
as `(idx, weight)` pairs gave weight sums nowhere near 255 and indices past the BoneMap;
SoA gives exact 255 sums and every index in range. Note this only surfaced because of an
explicit check — `SwordTwin` duplicated raw 16-byte blocks and worked *despite* the layout
being misunderstood, because copying bytes verbatim doesn't care about their structure.

### 3.5 Bone indices are section-local and 8-bit
`BoneIndex` indexes the section's **BoneMap**, not the skeleton. That caps a section at
**256 distinct bones** — a hard format limit that must fail loudly, not truncate.

### 3.6 Do not trust AtelierMesh's glb for editing
Its glTF reorders vertices, and reports **8 UV channels where the asset has 3** (synthesised
padding). Matching sections through it is impossible: its per-section counts sum to 128,743
against a real LOD0 of 123,018, and `128743` appears nowhere in the files. Sliding-window
correlation on vertex order finds no match. It stays viewport-only; `export_glb()` generates
the editing glb from our own parser.

### 3.7 Blender silently truncates to 4 bone influences
The glTF exporter defaults to `export_influence_nb=4` and only *warns* that it keeps "the 4
with highest weight". This mesh uses 8. Always pass
`export_all_influences=True, export_influence_nb=8` — the file grows (13.4 → 16.3 MB) as
`JOINTS_1`/`WEIGHTS_1` appear.

### 3.8 Blender exits 0 when its embedded script raises
A failed edit leaves no error code. Combined with an existing output file from a previous
run, the driver silently rebuilt a **stale glb from a different test** into the mod (LOD2
came out with another test's bbox). Two rules: **delete the output before every Blender
invocation**, and **judge success by a marker the script prints**, never the return code.

### 3.9 Match primitives to sections by material NAME
The sword is slot 11 in LOD0/LOD1 but slot **9** in LOD2, because decimated LODs drop whole
sections (LOD2 has 10 of 12). Positional matching silently swaps geometry between materials.

### 3.10 Decimated LODs have smaller BoneMaps
The cooker removes bones for lower LODs (`BonesToRemove: 48 items` on LOD1). Generating
LOD1 by decimating LOD0 therefore yields geometry weighted to bones LOD1 does not keep.
`collapse_weights_to_bonemap()` mirrors the cooker: influence from a dropped bone moves to
its **nearest retained ancestor**, duplicate targets are **summed** (not overwritten), and
weights renormalised. Verified to be an exact no-op when weights already fit.

### 3.11 Bone rotation quaternions are wrong in the exported glb
Positions convert cleanly (UE → glTF via a proper rotation), but quaternions do not survive
the left-handed → right-handed change with only an axis rotation applied. Posed (Object
Mode) display explodes the mesh into radial spikes. **This never reaches the game** — the
rebuild reuses the cooked skeleton and reads back only positions and weights — so the
armature is unbound and hidden in the `.blend` and re-bound at export. See §5.1.

### 3.12 The armature must exist at export time
Blender's glTF exporter derives the skin from the mesh's ARMATURE modifier. Without it the
export omits `JOINTS`/`WEIGHTS` entirely and every vertex returns unweighted. Vertex groups
live on the *mesh*, so weights survive unbinding untouched.

### 3.13 `uat fix` uses its own SerialSize convention
It sets the last export's `SerialSize` to `uexp portion + entire .ubulk + a hardcoded 432`,
unlike vanilla's `.uexp`-portion-only. It also fully re-serialises the `.uasset` via
`asset.Write()`, which can relocate fields — so re-locate offsets after running it rather
than reusing cached ones. It must run on **every** rebuild, including streamed-only edits,
because the `.ubulk` length feeds its formula.

### 3.14 `FColor` is B,G,R,A in memory
`StructLayout.Sequential` order. Swizzle for glTF's `COLOR_0`. MR vertex colours are mask
data, mostly (0,0,0) — never "fix" them to white.

### 3.15 Test design is as failure-prone as the code
Four separate results were unreadable, not wrong:
- **LOD0-only edits** are invisible at LOD1 distance and pop constantly while moving. Edit
  **every** LOD.
- **Occluded geometry**: deleting the body skin below Z=40 changed nothing visible because
  mat 1 (skirt, x±37.4) and mat 10 (boots, x±32.8) fully enclose mat 4 (x±26.8). The
  "Hair_03/Hair_04" materials are actually skirt/cape geometry — names mislead.
- **Ambiguous edits**: "subdivide + scale" can't distinguish denser from bigger. Displace
  **only the new vertices** and leave originals in place.
- **A no-change mod is indistinguishable from one that didn't load.** Prefer
  self-diagnosing tests: the head test was built so *floating half head* = success,
  *floating whole head* = count change failed, *nothing* = mod not loading.

### 3.16 Validate assumptions with mathematically exact bounds
An assertion that new subdivision vertices lie within the selection *band* ±0.15 m was
wrong — faces are selected by their **centre**, so their corners legitimately fall outside,
more so on decimated LODs. The exact bound is the selected faces' own vertex span, which
subdivision cannot exceed.

---

### 3.17 Tangent handedness lives in TangentZ.W, not TangentX.W
The packed tangent basis is `TangentX(4) | TangentZ(4)`. The bitangent handedness sign is
in **TangentZ.W — byte 7**. `TangentX.W` (byte 3) is the constant `127` on every vertex of
every asset checked and carries no information.

`normals_tangents` originally took `np.sign` of byte 3, which is therefore always `+1`, and
`rebuild_lod_buffers` wrote that into `TangentX.W` while hardcoding `TangentZ.W = +1`. Both
halves were wrong in the same direction, so **every rebuilt mesh came out right-handed
everywhere** — flipping the bitangent on each vertex whose UV island is mirrored: 35,783 of
Magik's 123,018 LOD0 vertices (29%), 3,343 of 101,789 on `SK_10251_1025302` (3%). The
symptom is an inverted green channel in normal-map lighting on those islands, which is
subtle enough to pass a visual check — it was found only by byte-comparing a null
round-trip on a *second* asset, not by looking at the result.

Note the cooker writes `-1` as byte `129` (decoding to `-0.992`), whereas re-encoding a
clean `np.sign(-1)` yields byte `128`. Identical meaning, and the engine reads only the
sign, but `normals_tangents` now returns the decoded value rather than its sign so the
round-trip stays byte-exact; `export_glb` applies `np.sign` at the glTF boundary, where
`TANGENT.w` must be exactly ±1.

**The null round-trip is the regression test that catches this class of bug.** Decompose a
LOD into per-section arrays through the same path the Blender import uses, rebuild the blob
from those values alone, and compare bytes. It is now byte-identical on all three LODs of
`SK_10251_1025302` (24 sections, never seen by the writer), and identical up to the morph
gate on Magik — where the only difference is the intentional morph strip, 9,666,375 of
9,666,383 bytes matching. Worth codifying as an automated test (Stage B).

## 4. Design constraints (deliberate, enforced)

1. **BoneMaps are never resized.** Edits may only weight bones a section already used;
   otherwise `map_to_fixed_bonemap()` raises naming the section and the offending bones.
   This is what keeps a rebuild a *value-only* patch of existing section records — a
   changing BoneMap size would cascade into resizing the section table, `RequiredBones`,
   and every later LOD's position in the `.uexp`.
2. **Section count, order and materials are fixed.**
3. **The skeleton is passed through verbatim.** Verified byte-identical: RefSkeleton
   (51,596 B), whole pre-LOD region (57,922 B), `RequiredBones`/`ActiveBoneIndices`
   (1,010 B), and every BoneMap in all 3 LODs. The mod ships **one package** (the mesh);
   `SK_10290_1029001_Skeleton` remains an unchanged import. No "custom skeleton", so no
   enemy-attack-animation penalty.
4. **Morph targets are stripped on any rebuilt LOD** — their deltas are vertex-indexed and
   a rebuild renumbers vertices. Costs Magik's 22 body correctives (arm/knee/thigh); there
   are no facial morphs on this mesh.

---

## 4b. The compatibility survey (Stage A) — what the game actually ships

Everything above was learned from one asset, which made every priority below it a guess.
`atelier/handlers/meshsurvey.py` removes the guessing: it walks every `SK_*` package in the
paks read-only (no packing, no Blender, no game launch) and reports what formats exist.

    python -m atelier.handlers.meshsurvey survey --prefix "" --bodies 1   # collect
    python -m atelier.handlers.meshsurvey report --segment body           # matrix
    python -m atelier.handlers.meshedit  preflight <game_rel>             # one asset

**Segment on body meshes.** Of 4,996 `SK_*` packages, only **513** are playable-character
body meshes (`Characters/<char>/<skin>/Meshes/**/SK_*<skin>`). The rest are weapon shells,
emote props, lobby stand-ins and PhysicsAssets that merely start with `SK_`. They are
simpler and ~9× more numerous, and mixing them in inverts the conclusions — half-precision
UVs look like an 86% problem across the whole corpus and are a 6% problem where it matters.
Numbers below are the **513 body meshes (514 records, 100% coverage)**.

| | meshes | share |
|---|---|---|
| **Editable today** | **262** | **51.0%** |
| Blocked: `bVariableBonesPerVertex` | 226 | 44.0% |
| Blocked: half-precision UVs | 33 | 6.4% |
| Blocked: high-precision tangents | 6 | 1.2% |
| Blocked: cloth | 4 | 0.8% |
| Blocked: 16-bit bone index | 3 | 0.6% |
| Blocked: BoneMap > 256 | 3 | 0.6% |
| Blocked: 16-bit bone weight | 1 | 0.2% |
| Warn: has morph targets | 405 | 78.8% |
| Warn: 16-bit LOD near the index ceiling | 152 | 29.6% |

Per-LOD (1,542 LODs): UV channels 3/1/2/4 = 995/261/196/90 · index width 16-bit 1,030,
32-bit 512 · MaxBoneInfluences 8/4/12 = 915/400/227 · vertex colours on 1,540 of 1,542 ·
morphs on 1,214 · `FSkinWeightProfilesData` non-empty **zero times** · unified BoneMap
**zero times**.

Four findings that change the plan:

**Cloth is a non-issue — 4 meshes, 0.8%.** The prior worry that cloth might be everywhere
(and would therefore dominate the roadmap) is dead. Detect-and-refuse is sufficient
forever; a cloth-preserving rebuild would be work spent on 0.8% of characters.

**`bVariableBonesPerVertex` is the whole story — 44%.** §5.5 filed this as a footnote
("read but the writer always emits fixed 8"). It is single-handedly the reason half the
roster is uneditable. It is also **much cheaper to fix than its share suggests**, because
it needs a *decoder only*: the existing writer already emits a valid fixed-8 buffer with an
empty lookup table, which is a legal encoding of the same data. The variable format is
simple — `LookupData[i] >> 8` is the byte offset of vertex *i*'s influences and
`LookupData[i] & 0xFF` is how many it has, then that many bone indices followed by that
many weights. Measured across 12 such LODs the mean is **3.24 influences per vertex**
(declared max 12), so re-encoding to fixed 8 is very nearly lossless — only the thin tail
above 8 influences would be dropped and renormalised, and the glTF round-trip already caps
at 8 anyway.

**Index-width promotion (§5.3) is not a corner case — it is a wall.** The largest 16-bit
LODs in the game sit at **65,479 / 65,465 / 65,406** vertices against the 65,536 ceiling.
That is 57 vertices of headroom. Those meshes cannot absorb *any* vertex-adding edit
without promotion, and 152 meshes (29.6%) are close enough to matter.

**Morphs matter more than the reference mesh suggested — 78.8%.** Magik's 22 body
correctives made morph loss look like a minor cosmetic cost. Four out of five characters
carry morph data, so §5.2 is a fidelity problem for most of the roster, not a few.

Two things the survey also settled cheaply: `FSkinWeightProfilesData` and the UE5 unified
BoneMap **never occur**, so the `NotImplementedError` paths guarding them are dead weight
that can stay as assertions and never be implemented.

**Parser confidence.** Across 1,542 LODs the walk landed exactly: `avail_gap == 0` on all
1,028 streamed LODs (i.e. the computed end of each LOD record is byte-exact) and the tail
resolved with `suffix_bytes == 4` on 1,538 of 1,542. Only 2 LODs failed a tail walk and 1
mesh failed to parse at all. That is the same standard used elsewhere here — two
independent derivations agreeing — applied at scale.

---

## 5. Incomplete / not yet done

*Priorities below are ordered by the survey in §4b, not by intrinsic interest.*

### 5.1 Quaternion handedness (posed preview) — cosmetic
Bone rest rotations in the exported glb are wrong (§3.11), so deformation cannot be
previewed in Blender. Fix: convert each bone's quaternion for the LH→RH change rather than
rotating only the root. Currently worked around by unbinding the armature. **No effect on
shipped mods.**

### 5.2 Morph target preservation — **78.8% of characters carry morphs**
Magik's 22 body correctives made this look like a minor cosmetic loss; the survey shows
405 of 514 body meshes ship morph data, so a rebuild degrades four characters in five.
Morphs are dropped unconditionally. Two tiers worth having:
- **Same topology** (deform-only edits): carry the morph block through verbatim; the
  vertex indices are still valid. Cheap and would cover most proportion edits.
- **Changed topology**: rebuild deltas by nearest-surface transfer. The stored format is
  UE5's bit-packed quantised GPU morph data (`FMorphTargetVertexInfoBuffers`:
  `MorphData` word array, per-morph min/max `FVector4`, batch offsets, `NumTotalBatches`,
  `PositionPrecision`, `TangentZPrecision`), so this needs a **decoder and an encoder**.

### 5.3 Index-width promotion on growth — **29.6% of characters, do this first**
`rebuild_lod_buffers` picks 16-bit indices when a LOD fits under 65,536 vertices and raises
if a forced 16-bit LOD would overflow. It does **not** yet promote an existing 16-bit LOD to
32-bit. LOD2 of the reference mesh is the mild exposure: 45,281 vanilla, 57,047 in one test.
The survey found the severe one — real 16-bit LODs at **65,479 vertices, 57 short of the
ceiling** (§4b). Promotion changes the payload size and the `DataTypeSize` byte, both
already handled by the existing resize path, but it is unimplemented and untested.

### 5.3b `bVariableBonesPerVertex` — **44% of characters, the largest single blocker**
See §4b. Needs a **decoder only**; the existing fixed-8 writer is already a legal
re-encoding, and at a measured mean of 3.24 influences per vertex it is nearly lossless.
This is the highest value-per-unit-effort item in this document.

### 5.4 Cloth — **0.8% of characters, detect and refuse; do not build more**
No section of the reference asset has cloth (`CorrespondClothAssetIndex == -1` on all 34),
and the survey found cloth on only 4 body meshes game-wide. `mesh.py` cannot even walk a
blob containing `FSkeletalMeshVertexClothBuffer` — worse, cloth sections are *invisible* to
`find_sections` rather than merely rejected, because `ClothMappingDataLODs` shifts every
`bm`-relative offset (§2.2). Detection now exists via `meshsurvey.probe`, which the
preflight refuses on. Preserving cloth through a rebuild is not worth building.

### 5.5 Unhandled format variants
Each raises rather than guessing. Survey share of body meshes in brackets:
- `bUseFullPrecisionUVs == 0` (half-precision UVs) **[6.4%]** — `NotImplementedError` in
  `Mesh.uvs`.
- `FSkinWeightProfilesData` non-empty **[0 of 514 — never occurs]** —
  `NotImplementedError` in `_locate_tail`. Keep the guard, never implement it.
- `bUse16BitBoneIndex` **[0.6%]** / `bUse16BitBoneWeight` **[0.2%]** — read but assumed 0
  on write.
- `bVariableBonesPerVertex` **[44%]** — read but the writer always emits fixed 8
  influences. Promoted to §5.3b; this is the top priority.
- `bUseHighPrecisionTangentBasis` **[1.2%]** — read, writer hardcodes 0.
- UE5 unified BoneMap packing **[0 of 514 — never occurs]** — bit 31 of a section's
  `MaxBoneInfluences`. Detected by the survey; keep the assertion.

### 5.6 Breadth — **resolved for body meshes, open elsewhere**
Superseded by §4b. All 513 playable-character body meshes are surveyed (100% coverage) and
51% parse as editable. What remains untested is the *rebuild* on any asset other than
`SK_10290_1029304`: the survey proves the parser generalises, not the writer. The full
sweep over the other ~4,480 non-body `SK_*` packages (props, weapons, environment) is
partially done and resumable:

    python -m atelier.handlers.meshsurvey survey --prefix "" --batch 64

Keep the batch at ~64. UAssetTool's `--filter` is a substring match and it re-indexes all
567k packages per invocation, so batches amortise that cost — but at 400 filters it
ballooned past 3 GB of RAM and stalled, and larger batches of character meshes extract
gigabytes at a time.

### 5.7 Auto-LOD quality
Lower LODs are Blender `DECIMATE` (COLLAPSE, triangulated) at each LOD's original triangle
ratio (LOD1 ≈ 0.53, LOD2 ≈ 0.295 for this mesh). It is not the cooker's simplifier; silhouette
quality at distance may differ from vanilla. If decimation removes every face of a material
the build fails with a clear message naming it, since an empty section is a crash (§3.2).

### 5.8 Ergonomics
- **Armature-free `.blend`**: the armature exists only so the exporter emits skinning
  (§3.12). It could be reconstructed at export time from the source asset's bone list and
  stripped from the `.blend` entirely.
- **App UI wiring**: `meshedit` is CLI-only. Nothing in `build_mod()`
  ([`texture.py`](atelier/handlers/texture.py)) or the web routes calls it, so mesh editing
  is unreachable from the GUI. Deliberately deferred.
- **Blender version**: tested on 5.0. `export_colors` does not exist there (it is
  `export_vertex_color` / `export_all_vertex_colors`); 4.x may differ again.
- Third-party add-ons in the user's Blender profile can inject stray objects (fast64 adds a
  bone-shape `Icosphere`); both scripts delete anything not named `SkeletalMesh`/`Armature`.

### 5.9 Custom skeletons (explicit future opt-in)
Adding skirt/hair bones for KawaiiPhysics needs new bones, which grows BoneMaps (violating
§4.1) *and* requires shipping a modified skeleton — which in Marvel Rivals breaks enemy
attack animations (only locomotion plays; it looks fine when playing the character
yourself). If ever built this must be an explicit mode with a warning, never something an
edit can trigger accidentally.
