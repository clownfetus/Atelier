"""Unit tests for Studio Fidelity PBR role detection and max_dim preview scaling."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


class StudioPbrTests(unittest.TestCase):
    def test_texture_roles_detects_normal_and_orm_by_name_and_suffix(self):
        script = """
            import { registerHooks } from 'node:module';
            import { pathToFileURL } from 'node:url';
            registerHooks({
              resolve(specifier, context, nextResolve) {
                if (specifier === 'three') {
                  return { url: pathToFileURL('./gui/vendor/three/three.module.min.js').href, shortCircuit: true };
                }
                return nextResolve(specifier, context);
              },
            });
            const { textureRoles } = await import('./gui/viewport-materials.js');
            const r1 = textureRoles({
              textures: {
                BaseColor: 'Characters/1060/1060501/Textures/T_Body_D',
                NormalMap: 'Characters/1060/1060501/Textures/T_Body_N',
                ORM: 'Characters/1060/1060501/Textures/T_Body_M',
              },
            });
            const r2 = textureRoles({
              textures: {
                Slot0: 'Characters/1029/1029001/Textures/T_Sword_Normal',
                Slot1: 'Characters/1029/1029001/Textures/T_Sword_ORM',
              },
            });
            console.log(JSON.stringify({ r1, r2 }));
        """
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout.strip())
        self.assertEqual(data["r1"]["basecolor"], "Characters/1060/1060501/Textures/T_Body_D")
        self.assertEqual(data["r1"]["normal"], "Characters/1060/1060501/Textures/T_Body_N")
        self.assertEqual(data["r1"]["orm"], "Characters/1060/1060501/Textures/T_Body_M")
        self.assertEqual(data["r2"]["normal"], "Characters/1029/1029001/Textures/T_Sword_Normal")
        self.assertEqual(data["r2"]["orm"], "Characters/1029/1029001/Textures/T_Sword_ORM")

    def test_scaled_texture_png_downscales_large_maps_and_skips_small_ones(self):
        from atelier.web import routes
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.png"
            small = Path(tmp) / "small.png"
            Image.new("RGBA", (2048, 1024), (128, 128, 255, 255)).save(big)
            Image.new("RGBA", (512, 512), (128, 128, 255, 255)).save(small)

            scaled_big = routes._scaled_texture_png(str(big), 1024)
            self.assertNotEqual(scaled_big, str(big))
            with Image.open(scaled_big) as im:
                self.assertEqual(im.size, (1024, 512))

            self.assertEqual(routes._scaled_texture_png(str(small), 1024), str(small))


if __name__ == "__main__":
    unittest.main()
