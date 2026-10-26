"""Package provenance, exact section identity and bounded Assembly previews."""
import atexit
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
environment = tempfile.TemporaryDirectory(prefix='atelier-assembly-')
atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR'] = environment.name
from atelier.handlers.assembly import effect_references


class Assembly(unittest.TestCase):
    def test_vfx_identity_requires_an_actual_classed_package_reference(self):
        document = {'Imports': [
            {'ObjectName': 'NS_Fire', 'ClassName': 'NiagaraSystem', 'OuterIndex': -2},
            {'ObjectName': '/Game/Marvel/VFX/Actual/NS_Fire'},
            {'ObjectName': 'NS_Fire', 'ClassName': 'Texture2D', 'OuterIndex': -4},
            {'ObjectName': '/Game/Marvel/VFX/Wrong/NS_Fire'},
            {'ObjectName': 'NE_Missing', 'ClassName': 'NiagaraEmitter', 'OuterIndex': -99},
            {'ObjectName': 'NS_Cycle', 'ClassName': 'NiagaraSystem', 'OuterIndex': -6},
        ]}
        result = effect_references(document, 'Meshes/SK_Body')
        self.assertEqual(result, [{'game_rel': 'VFX/Actual/NS_Fire', 'name': 'NS_Fire',
                                  'class': 'NiagaraSystem', 'source': 'Meshes/SK_Body'}])

    def test_thumbnail_preserves_pixels_and_caps_client_image_size(self):
        from atelier.web import routes as routes
        from bottle import LocalRequest, LocalResponse
        source = Path(environment.name)/'large.png'
        Image.new('RGBA', (2048, 1024), (37, 93, 141, 213)).save(source)
        req = LocalRequest({'QUERY_STRING': 'game_rel=Textures/T_Actual'})
        with patch.object(routes, 'request', req), patch.object(routes, 'response', LocalResponse()), \
                patch.object(routes, '_texture_png', return_value=str(source)) as read:
            data = routes.api_assembly_thumbnail()
        read.assert_called_once_with('Textures/T_Actual')
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (160, 80))
            self.assertEqual(image.getpixel((30, 30)), (37, 93, 141, 213))

    def test_custom_thumbnail_resolves_the_material_slot_without_extracting_a_game_texture(self):
        from atelier.web import routes as routes
        from bottle import LocalRequest, LocalResponse
        source = Path(environment.name)/'custom.png'
        Image.new('RGB', (64, 64), (51, 127, 203)).save(source)
        req = LocalRequest({'QUERY_STRING': 'game_rel=Materials/MI_Actual&slot=Normal'})
        with patch.object(routes, 'request', req), patch.object(routes, 'response', LocalResponse()), \
                patch.object(routes._custom_tex, 'image_path', return_value=str(source)) as custom, \
                patch.object(routes, '_texture_png') as game:
            data = routes.api_assembly_thumbnail()
        custom.assert_called_once_with('Materials/MI_Actual', 'Normal'); game.assert_not_called()
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.getpixel((20, 20)), (51, 127, 203, 255))

    @unittest.skipUnless(shutil.which('node'), 'Node is unavailable')
    def test_references_and_sections_do_not_merge_by_name(self):
        script = r'''
import assert from 'node:assert/strict';
const D = await import(process.argv[1]);
const exact = {game_rel:'Body/Materials/MI_Same',mapping_via:'imports',texture_sources:[
 {game_rel:'Body/Textures/T_Same',slot:'BaseColor',url:'/actual'},
 {game_rel:'Eye/Textures/T_Default',slot:'Iris',url:'/default',inferred:true}]};
const data = {body:exact, shared:{...exact}, weapon:{...exact,game_rel:'Weapon/Materials/MI_Same',
 texture_sources:[{game_rel:'Weapon/Textures/T_Same',slot:'BaseColor',url:'/other'}]},
 guessed:{...exact,mapping_via:'name'},chroma:{...exact,material_set_override:true}};
assert.deepEqual(D.relatedMaterials(data,'body/materials/MI_Same'),['body','shared']);
assert.deepEqual(D.textureUsers(data,{game_rel:'Body/Textures/T_Same'}),['body','shared']);
assert.deepEqual(D.boundTextures(data.guessed),[]);
assert.deepEqual(D.boundTextures(data.chroma),[]);
assert.equal(D.boundTextures(exact).length,1,'Preview defaults are not explicit references');
const material={name:'body',visible:true,userData:{}};
const mesh={uuid:'mesh',isMesh:true,material:[material],geometry:{index:{count:6},
 attributes:{position:{count:6}},drawRange:{start:0,count:Infinity},groups:[
 {start:0,count:3,materialIndex:0},{start:3,count:3,materialIndex:0}]}};
const owner={loaded:true,root:{visible:true,traverseVisible:fn=>fn(mesh)}};
const sections=D.modelSections([owner],[{game_rel:'Meshes/SK_Actual'}]);
assert.equal(sections.length,2);
assert.notEqual(sections[0].id,sections[1].id);
assert.equal(D.hitSection(sections,{object:mesh,face:{materialIndex:0},faceIndex:1}),sections[1]);
assert.equal(D.hitSection(sections,{object:{...mesh},face:{materialIndex:0},faceIndex:1}),null);
mesh.material=material;assert.equal(D.modelSections([owner],[{}]).length,1,'Single-material meshes follow Three draw semantics');
owner.root.visible=false;assert.equal(D.modelSections([owner],[{}]).length,0);
console.log('PASS exact package references and clicked geometry group identity');
'''
        result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script,
                                 (ROOT/'gui/assembly-data.js').as_uri()], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
