"""Model Studio's /api/model_gltf says why a model is unavailable instead of a bare 404.

The native decoder is replaced by a fake with the same contract (writes <out>/<asset>.glb or
nothing, and reports on stderr), so these checks cover the route's own decisions."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlencode
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="atelier-model-gltf-tests-")
os.environ["ATELIER_DATA_DIR"] = _data.name
from atelier import config as C, index as I
from atelier.web import routes as R

atexit.register(lambda: (R._observer.stop(), R._observer.join(), _data.cleanup()))

MESH = "Characters/1024/1024503/Meshes/SK_1024_1024503"
GLB = b"glTF\x02\x00\x00\x00fixture"


class ModelGltf(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-model-gltf-case-")
        root = Path(self.temp.name)
        (root / "projects" / "A").mkdir(parents=True)
        self.cache = root / "cache"
        self.patches = [patch.multiple(C, PROJECTS_ROOT=str(root / "projects"), _active_project="A"),
                        patch.multiple(R, PROJECTS_ROOT=str(root / "projects"), _CACHE=str(self.cache)),
                        patch.object(R, "pak_game_path", side_effect=lambda gr: "Marvel/Content/Marvel/" + gr),
                        patch.object(I, "index_lookup", return_value={MESH.lower() + ".uasset": (MESH, "c", "p")})]
        for p in self.patches:
            p.start()
        self.decode = patch.object(R, "atelier_mesh").start()
        self.patches.append(self.decode)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def call(self, game_rel=MESH):
        env = {}
        setup_testing_defaults(env)
        env.update(REQUEST_METHOD="GET", PATH_INFO="/api/model_gltf", QUERY_STRING=urlencode({"game_rel": game_rel}),
                   HTTP_X_ATELIER_PROJECT=quote("A", safe=""), **{"wsgi.input": io.BytesIO()})
        statuses = []
        result = R.app(env, lambda status, headers, exc_info=None: statuses.append(status))
        body = b"".join(result)
        if hasattr(result, "close"):
            result.close()
        return int(statuses[0].split()[0]), body

    def writes(self, relative):
        def run(asset, out_dir):
            target = Path(out_dir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(GLB)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run

    def test_a_decoded_mesh_is_served_and_cached(self):
        self.decode.side_effect = self.writes("Marvel/Content/Marvel/" + MESH + ".glb")
        self.assertEqual(self.call(), (200, GLB))
        self.assertEqual(self.call(), (200, GLB))
        self.decode.assert_called_once()

    def test_saved_geometry_precedes_the_native_import_server(self):
        from atelier import import_server
        from atelier.handlers import meshreplace
        path=Path(C.project_base(MESH,C.project_dir('A'))+'.asset.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        edited=path.with_suffix('.glb');edited.write_bytes(GLB)
        with patch.object(import_server,'available',return_value=True), \
             patch.object(import_server,'mesh',side_effect=AssertionError('Must keep saved geometry')), \
             patch.object(meshreplace,'preview',return_value=str(edited)):
            self.assertEqual(self.call(),(200,GLB))

    def test_a_decoder_failure_reports_the_decoders_reason(self):
        self.decode.return_value = SimpleNamespace(returncode=3, stdout="reading SK_1024_1024503\n",
                                                   stderr="\nunsupported skeletal mesh version 7\n")
        status, body = self.call()
        self.assertEqual(status, 500)
        error = json.loads(body)["error"]
        self.assertIn("Atelier could not decode SK_1024_1024503 (exit code 3)", error)
        self.assertIn("unsupported skeletal mesh version 7", error)
        self.assertIn("reading SK_1024_1024503", error)

    def test_a_silent_decoder_failure_still_says_so(self):
        self.decode.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
        status, body = self.call()
        self.assertEqual(status, 500)
        self.assertIn("gave no reason", json.loads(body)["error"])

    def test_a_failed_decode_that_saw_installed_mods_suggests_testing_without_them(self):
        """The reported failure: the decoder only says "export failed". When it could also read
        installed mods, the error names that and the step the user can take."""
        note = ("Atelier's data folder is on C: and the game is on D:, so Atelier could not keep "
                "installed mods out of this decode and also read ~mods")
        self.decode.return_value = SimpleNamespace(returncode=2, stdout="", stderr="export failed\n",
                                                   mods_note=note)
        status, body = self.call()
        self.assertEqual(status, 500)
        error = json.loads(body)["error"]
        self.assertIn("Atelier could not decode SK_1024_1024503 (exit code 2):\nexport failed", error)
        self.assertIn("Installed mods may be the cause: " + note, error)
        self.assertIn("move it out of the mods folder for now and reopen this model", error)

    def test_a_failed_decode_of_game_files_only_does_not_blame_mods(self):
        self.decode.return_value = SimpleNamespace(returncode=2, stdout="", stderr="export failed\n",
                                                   mods_note=None)
        status, body = self.call()
        self.assertEqual(status, 500)
        self.assertNotIn("Installed mods", json.loads(body)["error"])

    def test_a_mesh_missing_from_the_index_is_not_decoded(self):
        status, body = self.call("Characters/1024/1024503/Meshes/SK_Nope")
        self.assertEqual(status, 404)
        self.assertIn("SK_Nope is not in the game files", json.loads(body)["error"])
        self.decode.assert_not_called()

    def test_output_under_another_path_is_still_found(self):
        self.decode.side_effect = self.writes("marvel/content/marvel/characters/1024/1024503/meshes/sk_1024_1024503.glb")
        self.assertEqual(self.call(), (200, GLB))


class DecoderPaks(unittest.TestCase):
    """The decoder reads the game's Paks folder itself; AtelierNative registers only its top-level
    containers, so mods in ~mods (or the Galacta loader) can never shadow a vanilla package and
    there is no hardlinked mirror to fall back from."""
    def setUp(self):
        from atelier import tools as TL
        self.TL = TL
        self.temp = tempfile.TemporaryDirectory(prefix="atelier-decoder-paks-")
        self.paks = Path(self.temp.name) / "Paks"
        (self.paks / "~mods" / "Hela").mkdir(parents=True)
        self.patches = [patch.multiple(TL, PAKS=str(self.paks)),
                        patch.object(TL.hostos, "run_exe",
                                     return_value=SimpleNamespace(returncode=2, stdout="", stderr="export failed"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_reads_the_real_paks_folder_with_the_mesh_command(self):
        r = self.TL.atelier_mesh("Marvel/Content/Marvel/Characters/1024/1024503/Meshes/SK_1024_1024503", self.temp.name)
        argv = self.TL.hostos.run_exe.call_args[0][0]
        self.assertEqual(argv[:2], [self.TL.NATIVE, "mesh"])
        self.assertEqual(argv[argv.index("--paks") + 1], os.path.abspath(str(self.paks)))
        self.assertEqual(r.paks, str(self.paks))
        self.assertIsNone(r.mods_note)

    def test_no_mirror_is_built(self):
        self.assertFalse(hasattr(self.TL, "vanilla_paks"))
        self.TL.atelier_mesh("Marvel/Content/Marvel/Characters/1024/1024503/Meshes/SK_1024_1024503", self.temp.name)
        self.assertEqual(sorted(os.listdir(self.temp.name)), ["Paks"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
