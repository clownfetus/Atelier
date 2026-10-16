"""glb_to_blend.py imports Atelier's GLB intact under Blender's real glTF importer.

Blender 4.5-5.1 pairs custom attribute names (a set) with their data (a list in file order), so a
primitive with several custom attributes crashed or silently swapped them depending on the
per-run string hash seed. glb_to_blend now passes only _ATELIER_MORPH_ID through the importer and
rebuilds the rest by ID. This runs the script under several hash seeds and checks every vertex.

Needs the `bpy` module (pip install bpy matching your Blender); skipped when it is absent."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HAS_BPY = importlib.util.find_spec("bpy") is not None

CHECK = r'''
import json, runpy, struct, sys
import numpy as np
repo, glb, blend = sys.argv[1:4]
sys.argv = ["blender", "--", glb, blend]
runpy.run_path(repo + "/atelier/blender/glb_to_blend.py", run_name="__main__")
import bpy
me = bpy.data.objects["SkeletalMesh"].data
out = {}
for name, width in (("_ATELIER_MORPH_ID", 1), ("_ATELIER_MORPH_REST", 3), ("_ATELIER_MORPH_LOD", 1)):
    a = me.attributes[name]
    buf = np.empty(len(me.vertices) * width, np.float32)
    a.data.foreach_get("vector" if width == 3 else "value", buf)
    out[name] = {"type": a.data_type, "domain": a.domain, "values": buf.reshape(-1, width).tolist()}
print("RESULT " + json.dumps(out))
'''


class FakeMesh:
    """Two sections of a 4x4 grid, two bones: enough for mesh.export_glb's real output."""

    def __init__(self, side=4, sections=2):
        tris = [v for y in range(side - 1) for x in range(side - 1)
                for v in (y * side + x, y * side + x + 1, (y + 1) * side + x,
                          y * side + x + 1, (y + 1) * side + x + 1, (y + 1) * side + x)]
        per, idx, secs, pos = side * side, [], [], []
        for s in range(sections):
            secs.append({"base_vertex": s * per, "num_verts": per, "num_tris": len(tris) // 3,
                         "base_index": len(idx), "mat": s})
            idx += [s * per + t for t in tris]
            pos += [[x * 10.0 + s * 50, y * 10.0, s * 3.0 + x * y * .25] for y in range(side) for x in range(side)]
        self.pos, self.idx = np.array(pos, "f4"), np.array(idx, "<u4")
        self.lods = [{"num_verts": len(pos), "sections": secs, "idx_stride": 4, "idx_off": 0,
                      "max_bone_influences": 4, "num_tex_coords": 1, "layout": {"source_index": 2}}]
        self.materials = [{"slot_name": f"Slot_{s}"} for s in range(sections)]
        self.bones = [{"name": "root", "parent": -1, "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                      {"name": "spine", "parent": 0, "translation": [0, 0, 50], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}]

    def positions(self, lod): return self.pos
    def normals_tangents(self, lod):
        n = len(self.pos)
        return np.tile([0, 0, 1], (n, 1)).astype("f4"), np.tile([1, 0, 0], (n, 1)).astype("f4"), np.ones(n, "f4")
    def uvs(self, lod): return (self.pos[:, None, :2] / 100).astype("f4")
    def colors(self, lod): return None
    def skin_weights(self, lod):
        n = len(self.pos)
        li = np.zeros((n, 8), np.uint16); li[:, 1] = 1
        w = np.zeros((n, 8), "f4"); w[:, 0], w[:, 1] = .75, .25
        return li, w
    def section_bonemap(self, sec): return [0, 1]
    def _blob(self, lod): return self.idx.tobytes()


@unittest.skipUnless(HAS_BPY, "bpy is not installed; this check needs Blender's Python module")
class BlenderImport(unittest.TestCase):
    def test_tracking_attributes_survive_the_importer_under_any_hash_seed(self):
        from atelier.handlers import mesh as M
        with tempfile.TemporaryDirectory(prefix="atelier-blender-import-") as tmp:
            glb = os.path.join(tmp, "mesh.glb")
            M.export_glb(FakeMesh(), 0, glb)
            data = open(glb, "rb").read()
            jlen = struct.unpack_from("<I", data, 12)[0]
            g, binary = json.loads(data[20:20 + jlen]), data[20 + jlen + 8:]
            def acc(i):
                a, n = g["accessors"][i], {"SCALAR": 1, "VEC3": 3}[g["accessors"][i]["type"]]
                v = g["bufferViews"][a["bufferView"]]
                return np.frombuffer(binary, "<f4", a["count"] * n, v.get("byteOffset", 0)).reshape(-1, n)
            want = {}
            for p in g["meshes"][0]["primitives"]:
                at = p["attributes"]
                for i, r, l in zip(acc(at["_ATELIER_MORPH_ID"])[:, 0], acc(at["_ATELIER_MORPH_REST"]),
                                   acc(at["_ATELIER_MORPH_LOD"])[:, 0]):
                    want[int(i)] = ([float(x) for x in r], float(l))
            self.assertEqual(len(want), 32)
            for seed in range(8):           # on the unfixed script about half of these crash
                with self.subTest(seed=seed):
                    env = dict(os.environ, PYTHONHASHSEED=str(seed))
                    r = subprocess.run([sys.executable, "-c", CHECK, str(ROOT), glb, os.path.join(tmp, f"{seed}.blend")],
                                       capture_output=True, text=True, env=env, timeout=300)
                    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
                    self.assertIsNotNone(line, (r.stdout + r.stderr)[-1500:])
                    self.assertIn("BLEND_OK", r.stdout)
                    got = json.loads(line[7:])
                    self.assertEqual({k: (v["type"], v["domain"]) for k, v in got.items()},
                                     {"_ATELIER_MORPH_ID": ("FLOAT", "POINT"),
                                      "_ATELIER_MORPH_REST": ("FLOAT_VECTOR", "POINT"),
                                      "_ATELIER_MORPH_LOD": ("FLOAT", "POINT")})
                    for vid, rest, lod in zip(got["_ATELIER_MORPH_ID"]["values"], got["_ATELIER_MORPH_REST"]["values"],
                                              got["_ATELIER_MORPH_LOD"]["values"]):
                        self.assertEqual(want[int(vid[0])], (rest, lod[0]))
                    self.assertFalse(list(Path(tempfile.gettempdir()).glob("atelier-import-*.glb")), "the stripped copy is cleaned up")


if __name__ == "__main__":
    unittest.main(verbosity=2)
