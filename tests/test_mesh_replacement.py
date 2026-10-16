"""Replacement input validation, project bookkeeping and transactional publication."""
import atexit
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='atelier-model-tests-');atexit.register(temporary.cleanup)
os.environ['ATELIER_DATA_DIR']=temporary.name
from atelier import config as C
from atelier.handlers import meshreplace as M,meshedit
from atelier.web import browse
spec=importlib.util.spec_from_file_location('psk_reader',ROOT/'atelier/blender/psk_reader.py')
psk=importlib.util.module_from_spec(spec);spec.loader.exec_module(psk)


def chunk(name,size,records):
    return struct.pack('<20s3i',name.encode(),1999801,size,len(records))+b''.join(records)


def fixture_psk():
    return b''.join([chunk('ACTRHEAD',0,[]),
      chunk('PNTS0000',12,[struct.pack('<3f',*p) for p in ((0,0,0),(100,0,0),(0,100,0))]),
      chunk('VTXW0000',16,[struct.pack('<IffBBH',i,*uv,0,0,0) for i,uv in enumerate(((0,0),(1,0),(0,1)))]),
      chunk('FACE0000',12,[struct.pack('<HHHBBI',0,1,2,0,0,1)]),
      chunk('MATT0000',88,[struct.pack('<64s6i',b'MI_Body',0,0,0,0,0,0)]),
      chunk('REFSKELT',120,[struct.pack('<64sIii4f3ff3f',b'root',0,0,0,0,0,0,1,0,0,0,0,0,0,0)]),
      chunk('RAWWEIGHTS',12,[struct.pack('<fii',1,i,0) for i in range(3)])])


class Replacement(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.context=C.project_context(str(self.root));self.context.__enter__();self.addCleanup(self.context.__exit__,None,None,None)
        self.gr='Characters/1057/1057001/Meshes/SK_1057_1057001'

    def test_actorx_keeps_vertex_uv_material_and_weight_indices(self):
        path=self.root/'model.psk';path.write_bytes(fixture_psk())
        data=psk.read_psk(path)
        self.assertEqual(data['points'][1],(100,0,0));self.assertEqual(data['wedges'][2],(2,0,1))
        self.assertEqual(data['faces'][0][:4],(0,1,2,0));self.assertEqual(data['bones'],['root'])
        self.assertEqual(data['weights'],[(1,0,0),(1,1,0),(1,2,0)])

    def test_actorx_rejects_truncation_bad_lengths_and_nan_weights(self):
        path=self.root/'model.psk'
        for payload in (fixture_psk()[:-1],b'bad',struct.pack('<20s3i',b'ACTRHEAD',0,-1,4),
                        fixture_psk()[:-36]+struct.pack('<fii',float('nan'),0,0)+fixture_psk()[-24:]):
            path.write_bytes(payload)
            with self.assertRaises(ValueError):psk.read_psk(path)

    def test_add_is_idempotent_and_lists_exactly_one_mesh(self):
        M.add(self.gr);M.add(self.gr)
        rows=browse.all_imported();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['game_rel'],self.gr);self.assertEqual(rows[0]['file_type'],'mesh')
        Path(C.project_base(self.gr)+'.blend').write_bytes(b'BLENDER')
        self.assertEqual(len(browse.all_imported()),1)
        self.assertTrue(browse._imported_exists(self.gr,'.blend'))

    def test_invalid_target_or_format_never_changes_edits(self):
        for gr in ('../outside','Characters/Test/T_Texture'):
            with self.assertRaises(ValueError):M.add(gr)
        with self.assertRaises(ValueError):M.prepare(self.gr,str(self.root/'model.exe'))
        self.assertFalse(Path(C.project_base(self.gr)+'.blend').exists())

    def test_failed_lod_validation_preserves_existing_model(self):
        base=C.project_base(self.gr);Path(base).parent.mkdir(parents=True)
        Path(base+'.blend').write_bytes(b'previous model')
        source=self.root/'model.glb';source.write_bytes(b'glTF')
        def blender(script,args,label):
            if label=='REPLACEMENT':
                Path(args[2]).write_bytes(b'candidate');Path(args[3]).write_text(json.dumps({'vertices':3}))
            return label+'_OK'
        with patch.object(meshedit,'_resolve_base',return_value='vanilla'),patch.object(meshedit,'extract_blend'), \
             patch.object(meshedit,'_run_blender',side_effect=blender),patch.object(meshedit,'stage_mesh',side_effect=ValueError('bad LOD')), \
             patch('atelier.handlers.meshsurvey.probe',return_value={'status':'ok','warnings':[]}):
            with self.assertRaisesRegex(ValueError,'bad LOD'):M.prepare(self.gr,str(source))
        self.assertEqual(Path(base+'.blend').read_bytes(),b'previous model')
        self.assertFalse(Path(base+'.mesh.glb').exists())

    def test_success_publishes_model_preview_and_metadata_together(self):
        source=self.root/'model.glb';source.write_bytes(b'glTF')
        def blender(script,args,label):
            if label=='REPLACEMENT':
                Path(args[2]).write_bytes(b'new model');Path(args[3]).write_text(json.dumps({'vertices':3}))
            else:Path(args[1]).write_bytes(b'preview')
            return label+'_OK'
        def preview(mesh,lod,path,**options):Path(path).write_bytes(b'preview')
        with patch.object(meshedit,'_resolve_base',return_value='vanilla'),patch.object(meshedit,'extract_blend'), \
             patch.object(meshedit,'_run_blender',side_effect=blender),patch.object(meshedit,'stage_mesh',return_value={'applied':[{}],'uasset':'staged.uasset'}), \
             patch('atelier.handlers.meshsurvey.probe',return_value={'status':'ok','warnings':[]}), \
             patch('atelier.handlers.mesh.Mesh'),patch('atelier.handlers.mesh.export_glb',side_effect=preview):
            result=M.prepare(self.gr,str(source))
        base=C.project_base(self.gr)
        self.assertEqual(Path(base+'.blend').read_bytes(),b'new model')
        self.assertEqual(Path(base+'.mesh.glb').read_bytes(),b'preview')
        self.assertEqual(json.loads(Path(base+'.mesh.json').read_text())['state'],'replacement')
        self.assertEqual(result['validation']['lods'],1)


if __name__=='__main__':unittest.main()
