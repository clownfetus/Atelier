# UV X-Ray native verification — 22 October 2026

Validated the real Black Widow lobby model
`Characters/1033/1033001/Meshes/SK_1033_1033001_Lobby` through Model Studio,
Chromium and Atelier's native game reader. Geometry, material bindings and texture
APIs were not mocked. A real decoded `T_1033001_Body_D` image was copied into a
disposable validation project's texture path; its project PNG was 2048 × 2048.

| Picked material | Cooked slot | Triangles | PNG size | Sampled UV edge alignment |
| --- | ---: | ---: | --- | ---: |
| `MI_1033001_Body` | 5 | 24,468 | 2048 × 2048 | 100% |
| `MI_1033001_Equip_02` | 3 | 23,213 | 2048 × 2048 | 100% |

- Real mouse clicks resolved the expected cooked slot, material asset and source
  texture. Clicked UV readouts agreed with barycentric UV coordinates within
  0.000002.
- Independently parsed GLB accessors, including their interleaved buffer strides,
  matched the complete Three.js UV and index attributes for both sections.
- Exported PNGs contained white UV lines and transparency, without source-image
  pixels or the click marker. Sampled native triangle-edge midpoints matched the
  exports within a two-pixel neighborhood. Incorrect vertical mirroring reduced
  matching coverage to approximately 62% and 56%, respectively.
- The texture API's response SHA-256 matched the project PNG. Export dimensions
  matched its 2048 × 2048 pixels exactly.
- Three.js texture counts did not increase. UV/index byte hashes, project file
  hashes and game-container sizes/timestamps stayed unchanged.
- Showcase closed and disabled UV X-Ray; Inspect restored availability. No
  browser page errors occurred. No UV alignment or export defect was found on
  these two sections.

The [verification receipt](uv-xray-verification-2026-10-22.json) records the
results and export hashes. Game packages, texture images, model data and
screenshots remain outside Git. Validation covers this model's decoded UV0;
shader-driven mappings, transformed textures and tiled/UDIM layouts retain the
explicit v1 limitations.

To repeat with configured isolated application data and an existing project PNG:

```powershell
python tests/uv_xray_real_checks.py --data-dir D:/AtelierDev/uv-xray-20261022/data --report-dir D:/AtelierDev/uv-xray-20261022/report --project "UV X-Ray real validation" --mesh Characters/1033/1033001/Meshes/SK_1033_1033001_Lobby --texture Characters/1033/1033001/Texture/T_1033001_Body_D
```
