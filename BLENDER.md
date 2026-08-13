# Blender mesh editing — format spec, hard-won gotchas, and remaining work

Pipeline for editing Marvel Rivals SkeletalMesh geometry in Blender and packing the result
as a playable mod. Vertices may be added, removed, moved, subdivided or sculpted; the
skeleton and material set stay exactly as cooked.

    python -m atelier.handlers.meshedit extract <game_rel> [--base PATH] [--blend PATH]
    python -m atelier.handlers.meshedit build   <game_rel> [--base PATH] [--blend PATH] [--name N]

Code: [`atelier/handlers/mesh.py`](atelier/handlers/mesh.py) (format + rebuild),
[`atelier/handlers/meshedit.py`](atelier/handlers/meshedit.py) (driver/CLI),
[`atelier/blender/*.py`](atelier/blender) (headless Blender steps).

Everything below was established against `SK_10290_1029304` (Magik, INFERNAL IDOL) on
UE 5.3 / S9.5, cross-checked against the CUE4Parse and UAssetToolRivals sources in
`sources/`, and validated in-game.

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

Anchor on the BoneMap count field (`bm`) — it is the only field distinctive enough to find
reliably. All offsets are relative to it:

```
bm-33  uint16  magic == 1
bm-31  uint16  MaterialIndex
bm-29  uint32  BaseIndex          (offset into the index buffer)
bm-25  uint32  NumTriangles
bm-21  uint32  0
bm-17  uint8   0x03               flag block (recompute-tangents / cast-shadow / ray-tracing)
bm-16  uint8   0x01
bm-12  uint8   0x01
bm-8   uint32  BaseVertexIndex
bm-4   uint32  0
bm     uint32  BoneMapCount, then uint16[BoneMapCount]
   +   uint32  NumVertices
   +   uint32  MaxBoneInfluences
   +   int16   CorrespondClothAssetIndex   (-1 == no cloth)
```

Sections are **vertex-contiguous** and never share a vertex: a vertex on a material seam is
duplicated once per section. `BaseVertexIndex` and `BaseIndex` form exact running chains
(verified for all three LODs).

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
`LOD2 = 4 + 4 + 4 + 77,872 + 10 = 77,898` — LOD2's suffix is **10 bytes and contains real
non-zero data** (`00 00 00 00 | 01 03 | 00 00 00 00`), where LOD0/LOD1's is 4 zero bytes.

### 2.5 Size bookkeeping outside the blob

| Field | Location | Value |
|---|---|---|
| DataResourceMap | `.uasset`, `count u32` + 44-byte entries | `flags u32, SerialOffset i64, DuplicateOffset i64 = -1, SerialSize i64, RawSize i64, pad u32, LegacyBulkDataFlags u32` |
| Export SerialSize | `.uasset` export table | adjacent `int64 SerialSize, int64 SerialOffset` |
| BulkDataStartOffset | package summary | `len(uasset) + len(uexp) - 4` |
| Metadata mirrors | `.uexp`, after each streamed LOD's sections | blob size, index count, NumVertices (×4), NumBones |

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

## 5. Incomplete / not yet done

### 5.1 Quaternion handedness (posed preview) — cosmetic
Bone rest rotations in the exported glb are wrong (§3.11), so deformation cannot be
previewed in Blender. Fix: convert each bone's quaternion for the LH→RH change rather than
rotating only the root. Currently worked around by unbinding the armature. **No effect on
shipped mods.**

### 5.2 Morph target preservation
Morphs are dropped unconditionally. Two tiers worth having:
- **Same topology** (deform-only edits): carry the morph block through verbatim; the
  vertex indices are still valid. Cheap and would cover most proportion edits.
- **Changed topology**: rebuild deltas by nearest-surface transfer. The stored format is
  UE5's bit-packed quantised GPU morph data (`FMorphTargetVertexInfoBuffers`:
  `MorphData` word array, per-morph min/max `FVector4`, batch offsets, `NumTotalBatches`,
  `PositionPrecision`, `TangentZPrecision`), so this needs a **decoder and an encoder**.

### 5.3 Index-width promotion on growth
`rebuild_lod_buffers` picks 16-bit indices when a LOD fits under 65,536 vertices and raises
if a forced 16-bit LOD would overflow. It does **not** yet promote an existing 16-bit LOD to
32-bit. LOD2 is the exposure: it sits at 45,281 vanilla and reached 57,047 in one test.
Promotion changes the payload size and the `DataTypeSize` byte — all handled by the existing
resize path, but currently unimplemented and untested.

### 5.4 Cloth
No section in this asset has cloth (`CorrespondClothAssetIndex == -1` on all 34). The parser
would fail to walk a blob containing `FSkeletalMeshVertexClothBuffer`, and cloth data is
vertex-indexed so count changes invalidate it. Needs: detection, and refusing count changes
on cloth sections rather than corrupting them.

### 5.5 Unhandled format variants
Each raises rather than guessing, but none is implemented:
- `bUseFullPrecisionUVs == 0` (half-precision UVs) — `NotImplementedError` in `Mesh.uvs`.
- `FSkinWeightProfilesData` non-empty — `NotImplementedError` in `_locate_tail`.
- `bUse16BitBoneIndex` / `bUse16BitBoneWeight` — read but assumed 0 on write.
- `bVariableBonesPerVertex` — read but the writer always emits fixed 8 influences.
- `bUseHighPrecisionTangentBasis` — read, writer hardcodes 0.

### 5.6 Only one asset validated
Everything is verified against `SK_10290_1029304`. Other characters may have different UV
counts, cloth, morph layouts, LOD counts, or >256 bones in a section. The locators are
written to be general and to fail loudly, but this is untested breadth.

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
