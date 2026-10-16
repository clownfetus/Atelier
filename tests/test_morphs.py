"""GPU morph binary layout, geometric remapping and default-on import choices."""
import atexit
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temporary=tempfile.TemporaryDirectory(prefix='atelier-morph-test-');atexit.register(temporary.cleanup)
os.environ['ATELIER_DATA_DIR']=temporary.name
from atelier.handlers import morph,meshreplace,mesh


def target(ids,values):return {'indices':np.array(ids,dtype='u4'),'deltas':np.array(values,dtype='f4').reshape(-1,6)}


class Morphs(unittest.TestCase):
    def test_codec_crosses_words_handles_signed_deltas_and_multiple_batches(self):
        ids=np.arange(140,dtype='u4')*3
        values=np.column_stack((np.sin(ids),np.cos(ids),ids*.01,np.zeros(140),np.sin(ids)*.1,np.zeros(140))).astype('f4')
        sources=[target(ids,values),target([],[])];raw=morph.encode(sources,.001,.0001);decoded=morph.decode(raw,420)
        self.assertEqual(decoded['batches'],3);self.assertEqual(len(decoded['targets']),2)
        self.assertTrue(np.array_equal(decoded['targets'][0]['indices'],ids))
        self.assertTrue(np.all(abs(decoded['targets'][0]['deltas']-values)<=np.array([.00051]*3+[.000051]*3)))
        self.assertEqual(len(decoded['targets'][1]['indices']),0)

    def test_decode_known_external_layout(self):
        # Two deltas: indices 5 and 8. Index residuals 0,2; X residuals 0,3.
        bits=2|(2<<5)|(2<<21)
        header=struct.pack('<III3iI3i',40,bits,5,-2,0,0,0,0,0,0)
        payload=struct.pack('<I',0 | (2<<4) | (3<<6))
        packed=header+payload
        raw=struct.pack('<i',len(packed)//4)+packed+struct.pack('<i4f',1,-.2,0,0,0)+struct.pack('<i4f',1,.1,0,0,0)
        raw+=struct.pack('<iI',1,0)+struct.pack('<iI',1,1)+struct.pack('<iff',1,.1,.01)
        decoded=morph.decode(raw,9)['targets'][0]
        self.assertEqual(decoded['indices'].tolist(),[5,8]);np.testing.assert_allclose(decoded['deltas'][:,0],[-.2,.1])

    def test_malformed_buffers_are_rejected(self):
        raw=morph.encode([target([3],[[1,0,0,0,0,0]])],.01,.001)
        for bad in (raw[:-1],struct.pack('<i',-1)+raw[4:],raw[:4]+struct.pack('<I',0xffffffff)+raw[8:]):
            with self.assertRaises(ValueError):morph.decode(bad,8)
        with self.assertRaises(ValueError):morph.decode(raw,3)
        with self.assertRaises(ValueError):morph.encode([target([3,2],[[1,0,0,0,0,0]]*2)],.01,.01)

    def fixture(self):
        positions=np.array([[0,0,0],[1,0,0],[0,1,0]],dtype='f4')
        section={'base_vertex':0,'num_verts':3,'base_index':0,'num_tris':1}
        lod={'sections':[section],'num_verts':3,'idx_stride':2,'idx_off':0}
        model=SimpleNamespace(positions=lambda l:positions,_blob=lambda l:struct.pack('<3H',0,1,2))
        return model,lod,positions

    def test_vertex_reordering_maps_deltas_to_correct_vertex(self):
        model,lod,points=self.fixture();original=morph.decode(morph.encode([target([0],[[.2,0,0,0,0,0]])],.001,.001),3)
        raw,targets,identity=morph.remap(model,lod,[{'positions':points[[2,0,1]]}],original)
        self.assertFalse(identity);again=morph.decode(raw,3)['targets'][0]
        self.assertEqual(again['indices'].tolist(),[1]);np.testing.assert_allclose(again['deltas'][0,0],.2)

    def test_new_geometry_receives_barycentric_facial_movement(self):
        model,lod,points=self.fixture();original=morph.decode(morph.encode([target([0,1,2],[[0,0,0,0,0,0],[1,0,0,0,0,0],[0,1,0,0,0,0]])],.001,.001),3)
        replacement=np.vstack((points,[.25,.25,0]))
        raw,targets,identity=morph.remap(model,lod,[{'positions':replacement}],original)
        again=morph.decode(raw,4)['targets'][0];index=again['indices'].tolist().index(3)
        np.testing.assert_allclose(again['deltas'][index,:3],[.25,.25,0],atol=.001)

    def test_unchanged_geometry_retains_morph_bytes_exactly(self):
        model,lod,points=self.fixture();original=morph.decode(morph.encode([target([0],[[.2,0,0,0,0,0]])],.001,.001),3)
        raw,targets,identity=morph.remap(model,lod,[{'positions':points}],original)
        self.assertTrue(identity);self.assertEqual(raw,original['raw'])

    def test_coincident_vertices_use_uvs_to_keep_distinct_movements(self):
        points=np.array([[0,0,0],[0,0,0],[1,0,0],[0,1,0]],dtype='f4')
        uv=np.array([[[0,0]],[[1,1]],[[1,0]],[[0,1]]],dtype='f4')
        section={'base_vertex':0,'num_verts':4,'base_index':0,'num_tris':1}
        lod={'sections':[section],'num_verts':4,'idx_stride':2,'idx_off':0}
        model=SimpleNamespace(positions=lambda l:points,uvs=lambda l:uv,_blob=lambda l:struct.pack('<3H',0,2,3))
        original=morph.decode(morph.encode([target([1],[[.2,0,0,0,0,0]])],.001,.001),4)
        raw,targets,identity=morph.remap(model,lod,[{'positions':points[[1,0,2,3]],'uv':uv[[1,0,2,3]]}],original)
        self.assertEqual(morph.decode(raw,4)['targets'][0]['indices'].tolist(),[0])

    def test_closest_triangle_handles_edge_and_degenerate_case(self):
        triangles=np.array([[[0,0,0],[1,0,0],[0,1,0]],[[0,0,0],[0,0,0],[0,0,0]]],dtype='f8')
        weights,distance=morph.closest_triangles(np.array([[2,0,0],[0,0,1]]),triangles)
        np.testing.assert_allclose(weights.sum(-1),1);np.testing.assert_allclose(distance,[1,1])

    def test_saved_rest_coordinates_keep_morphs_attached_after_sculpting(self):
        model,lod,points=self.fixture();lod['layout']={'source_index':0}
        original=morph.decode(morph.encode([target([1],[[.2,0,0,0,0,0]])],.001,.001),3)
        sculpted=points.copy();sculpted[1]=[4,4,4]
        raw,targets,identity=morph.remap(model,lod,[{'positions':sculpted,'morph_rest':points,'morph_ids':np.arange(3),'morph_lods':np.zeros(3)}],original)
        self.assertTrue(identity);self.assertEqual(raw,original['raw'])

    def test_quantized_zero_deltas_do_not_inflate_cpu_metadata_counts(self):
        model,lod,points=self.fixture();original=morph.decode(morph.encode([target([1],[[1,0,0,0,0,0]])],1,.01),3)
        raw,targets,identity=morph.remap(model,lod,[{'positions':np.vstack((points,[.5,0,0]))}],original)
        self.assertEqual(len(targets[0]['indices']),len(morph.decode(raw,4)['targets'][0]['indices']))
        self.assertNotIn(3,targets[0]['indices'])

    def test_import_defaults_and_explicit_disabling(self):
        self.assertEqual(meshreplace.import_options(),{'keep_skeleton':True,'keep_weights':True,'keep_morphs':True})
        self.assertEqual(meshreplace.import_options({'keep_morphs':False})['keep_morphs'],False)
        for bad in ({'keep_morphs':'false'},{'oops':True},[]):
            with self.assertRaises(ValueError):meshreplace.import_options(bad)


if __name__=='__main__':unittest.main()
