"""Unit tests for Pre-Flight Mesh QA (vanilla original glTF bypass + geometry audit)."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class MeshQaTests(unittest.TestCase):
    def test_analyse_mesh_objects_detects_healthy_and_unweighted_vertices(self):
        script = """
            import { analyseMeshObjects } from './gui/viewport-mesh-qa.js';
            const makeObj = (weights) => ({
              root: {
                visible: true,
                traverse(fn) {
                  fn({ isBone: true, uuid: 'b1' });
                  fn({ isBone: true, uuid: 'b2' });
                  fn({
                    isMesh: true,
                    isSkinnedMesh: true,
                    geometry: {
                      attributes: {
                        position: { count: 3 },
                        skinWeight: { count: 3, itemSize: 4, array: new Float32Array(weights) },
                      },
                      index: { count: 3 },
                    },
                  });
                },
              },
            });
            const healthy = analyseMeshObjects([makeObj([1,0,0,0, 0.5,0.5,0,0, 0,1,0,0])]);
            const broken  = analyseMeshObjects([makeObj([1,0,0,0, 0,0,0,0, 0,0,0,0])]);
            console.log(JSON.stringify({ healthy, broken }));
        """
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout.strip())
        self.assertTrue(data["healthy"]["healthy"])
        self.assertEqual(data["healthy"]["triangles"], 1)
        self.assertEqual(data["healthy"]["bones"], 2)
        self.assertEqual(data["healthy"]["unweighted"], 0)

        self.assertFalse(data["broken"]["healthy"])
        self.assertEqual(data["broken"]["unweighted"], 2)
        self.assertTrue(any("unweighted" in w for w in data["broken"]["warnings"]))

    def test_model_glb_original_flag_bypasses_edited_blend(self):
        from atelier.web import routes
        with patch.object(routes.os.path, "isfile", return_value=True), \
             patch.object(routes.import_server, "available", return_value=True), \
             patch.object(routes.import_server, "mesh", return_value="/vanilla/SK_Test.glb") as mesh_mock, \
             patch("atelier.handlers.meshreplace.preview", return_value="/edited/SK_Test.glb") as edited_mock:
            self.assertEqual(routes._model_glb("Characters/1060/1060501/Meshes/SK_Test"), "/edited/SK_Test.glb")
            self.assertEqual(routes._model_glb("Characters/1060/1060501/Meshes/SK_Test", original=True), "/vanilla/SK_Test.glb")
            edited_mock.assert_called_once()
            mesh_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
