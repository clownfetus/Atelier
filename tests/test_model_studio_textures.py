"""Real pixel conversion and failure atomicity for local weapon material bundles."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
environment=tempfile.TemporaryDirectory(prefix='atelier-bundle-tests-');atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR']=environment.name
from atelier import config, project_meta
from atelier.handlers import material,mesh,meshmat,meshreplace,meshtextures as bundle


class Bundles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.project=self.folder/'project'
        context=config.project_context(str(self.project));context.__enter__();self.addCleanup(context.__exit__,None,None,None)
        self.target='Characters/1066/1066001/Weapons/Gun_R/Meshes/SK_Gun_R'
        self.material='Characters/1066/1066001/Weapons/Gun_L/Materials/MI_Gun'
        self.files=[]
        for suffix,color in [('',(80,90,100,255)),('NM',(255,128,90,192)),('PBR',(51,204,255,99)),('AO',(15,37,77,255))]:
            path=self.folder/('Gun'+suffix+'.png');Image.new('RGBA',(4,4),color).save(path);self.files.append(path)
        # A nonconstant alpha is typical of a packed A/G normal.
        normal=Image.open(self.files[1]);normal.putpixel((0,0),(255,128,90,64));normal.save(self.files[1])
        self.json=self.folder/'Gun.json'
        self.document={'m_Shader':{'Name':'Example/PBR'},'m_SavedProperties':{'m_TexEnvs':{
            key:{'m_Texture':{'Name':'Gun'+suffix,'IsNull':False}}
            for key,suffix in [('_MainTex',''),('_BumpMap','NM'),('_PBRMask','PBR'),('_MaskTex','AO')]}}}
        self.json.write_text(json.dumps(self.document));self.files.append(self.json)
        self.source=self.folder/'Gun.fbx';self.source.write_bytes(b'FBX selected but never executed by these unit checks')

    def pixel(self,maps,role):return Image.open(io.BytesIO(maps[role]['png'])).getpixel((0,0))

    def test_unity_ag_normal_and_pbr_mask_are_converted_to_game_channels(self):
        result=bundle.convert(self.source,self.files,{})
        self.assertEqual(result['normal_encoding'],'unity_ag')
        red,green,blue=self.pixel(result['maps'],'normal')
        self.assertEqual((red,green),(64,127));self.assertGreater(blue,230)
        self.assertEqual(self.pixel(result['maps'],'orm'),(255,51,204))
        self.assertEqual(self.pixel(result['maps'],'basecolor'),(80,90,100,255))
        self.assertEqual(len(result['originals']),4)

    def test_channel_choices_change_packed_pixels_without_overwriting_sources(self):
        before={path:path.read_bytes() for path in self.files}
        result=bundle.convert(self.source,self.files,{'normal_encoding':'directx','pbr_layout':'metal_r_smooth_a','ao_channel':'g','ao_invert':True})
        self.assertEqual(self.pixel(result['maps'],'orm'),(218,156,51))
        self.assertEqual(self.pixel(result['maps'],'normal')[:2],(255,128))
        self.assertTrue(all(path.read_bytes()==data for path,data in before.items()))

    def test_material_document_cannot_load_unselected_or_external_files(self):
        for reference in ('../outside','C:/private/image','https://example.test/image','Unselected'):
            self.document['m_SavedProperties']['m_TexEnvs']['_MainTex']['m_Texture']['Name']=reference
            self.json.write_text(json.dumps(self.document))
            with self.assertRaises(ValueError):bundle.convert(self.source,self.files,{})

    def test_multi_material_mesh_requires_explicit_assignment(self):
        with patch.object(mesh,'Mesh'),patch.object(meshmat,'resolve_mesh_materials',return_value=[{'mi':'Materials/MI_A'},{'mi':'Materials/MI_B'}]):
            with self.assertRaisesRegex(ValueError,'one destination material'):
                bundle.prepare(self.target,self.source,self.files,{},self.folder/'stage','original')
        self.assertFalse(self.project.exists())

    def test_failed_native_texture_build_keeps_model_material_and_metadata(self):
        project_meta.set_asset_opts(str(self.project),self.material,{'custom_note':'keep'})
        mat=Path(config.project_base(self.material)+'.json');mat.parent.mkdir(parents=True);mat.write_text('{"existing":"material"}')
        before={path.relative_to(self.project):path.read_bytes() for path in self.project.rglob('*') if path.is_file()}
        slots={name:{'game_rel':'Textures/T_'+name,'class':'Texture2D'} for name in ('BaseColor','Normal','ORM','SpecularTexture')}
        with patch.object(mesh,'Mesh'),patch.object(meshmat,'resolve_mesh_materials',return_value=[{'mi':self.material,'slot':'MI_Gun'}]), \
             patch.object(material,'mat_json',return_value=str(mat)),patch.object(material,'texture_slots',return_value=slots), \
             patch.object(material,'_mat_params',return_value=([],[])),patch.object(material,'_apply_mat_edits'), \
             patch.object(material,'stage_material',side_effect=RuntimeError('texture encode failed')):
            with self.assertRaisesRegex(RuntimeError,'texture encode failed'):
                bundle.prepare(self.target,self.source,self.files,{},self.folder/'stage','original')
        after={path.relative_to(self.project):path.read_bytes() for path in self.project.rglob('*') if path.is_file()}
        self.assertEqual(before,after)

    def test_alignment_options_reject_nonfinite_values_and_invalid_units(self):
        for options in ({'scale':0},{'scale':float('nan')},{'rotate_x':float('inf')},{'offset_z':10001},{'normal_encoding':'guess'}):
            with self.assertRaises(ValueError):meshreplace.import_options(options)
        self.assertEqual(meshreplace.import_options(),meshreplace.IMPORT_DEFAULTS)

    def test_nested_model_zip_matches_explicit_bundle_selection(self):
        archive=self.folder/'Gun.zip'
        with zipfile.ZipFile(archive,'w') as output:
            output.write(self.source,'Gun/Gun.fbx')
            for path in self.files:output.write(path,'Gun/'+('Materials/' if path.suffix=='.json' else '')+path.name)
        model,companions=bundle.unpack_archive(archive,self.folder/'unpacked')
        direct=bundle.convert(self.source,self.files,{})
        archived=bundle.convert(model,companions,{})
        self.assertEqual(archived['maps'],direct['maps'])
        self.assertEqual(archived['normal_encoding'],'unity_ag')

    def test_archive_rejects_traversal_and_multiple_models(self):
        for files in ({'../outside.fbx':b'bad'},{'A.fbx':b'a','B.fbx':b'b'}):
            archive=self.folder/'invalid.zip'
            with zipfile.ZipFile(archive,'w') as output:
                for name,data in files.items():output.writestr(name,data)
            with self.assertRaises(ValueError):bundle.unpack_archive(archive,self.folder/'invalid-unpacked')
        self.assertFalse((self.folder/'outside.fbx').exists())


if __name__=='__main__':unittest.main()
