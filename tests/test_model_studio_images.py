"""Regressions for rectangular streamed normals and inline HDR cube inputs."""
import atexit
import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
environment=tempfile.TemporaryDirectory(prefix='atelier-studio-images-');atexit.register(environment.cleanup)
os.environ['ATELIER_DATA_DIR']=environment.name
from atelier.handlers import texture,meshimages


class TextureRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.target=self.root/'decoded'

    def test_stripped_rectangular_normal_retains_aspect_ratio_and_top_blocks(self):
        block_data=bytes(range(256))*2731
        # Largest shipped mip is 1024 x 512, followed by its complete tail.
        payload=block_data[:699056];self.source.with_suffix('.ubulk').write_bytes(payload)
        with patch.object(texture,'_tex_info',return_value=(2048,1024,'BC5')):
            output=Path(texture.decode_dds(str(self.target),str(self.source))).read_bytes()
        self.assertEqual(struct.unpack_from('<II',output,12),(512,1024))
        self.assertEqual(output[84:88],b'ATI2')
        self.assertEqual(output[128:],payload[:524288])

    def test_bc_blocks_include_partial_edge_blocks(self):
        self.source.with_suffix('.uptnl').write_bytes(b'x'*32)
        with patch.object(texture,'_tex_info',return_value=(5,3,'BC5')):
            output=Path(texture.decode_dds(str(self.target),str(self.source))).read_bytes()
        self.assertEqual(struct.unpack_from('<II',output,12),(3,5))
        self.assertEqual(output[128:],b'x'*32)

    def cube(self):
        data=bytes(range(96));self.source.with_suffix('.uexp').write_bytes(b'header!'+data+b'trailer')
        document={'Imports':[{'ClassName':'Class','ObjectName':'TextureCube'}],
                  'Exports':[{'PlatformData':{'PixelFormat':'PF_BC6H','Mips':[{
                      'SizeX':4,'SizeY':4,'BulkData':{'Header':{'IsInline':True,'IsInSeparateFile':False,
                          'OffsetInFile':7,'SizeOnDisk':96}}}]}}]}
        return document,data

    def test_hdr_cube_keeps_every_face_without_clamping_pixels(self):
        document,data=self.cube()
        self.assertEqual(meshimages.inline_hdr_blocks(document,str(self.source)),(data,4,4,6))

    def test_hdr_2d_does_not_read_six_faces(self):
        document,data=self.cube();document['Imports']=[]
        document['Exports'][0]['PlatformData']['Mips'][0]['BulkData']['Header']['SizeOnDisk']=16
        self.assertEqual(meshimages.inline_hdr_blocks(document,str(self.source)),(data[:16],4,4,1))

    def test_hdr_payload_range_and_shape_must_match_before_conversion(self):
        original,_=self.cube()
        for offset,size in ((-1,96),(1000,96),(7,16),(7,97)):
            document=copy.deepcopy(original)
            document['Exports'][0]['PlatformData']['Mips'][0]['BulkData']['Header'].update(OffsetInFile=offset,SizeOnDisk=size)
            with self.assertRaisesRegex(ValueError,'range'):meshimages.inline_hdr_blocks(document,str(self.source))

    def test_non_hdr_textures_keep_the_normal_decoder(self):
        document,_=self.cube();document['Exports'][0]['PlatformData']['PixelFormat']='PF_BC5'
        self.assertIsNone(meshimages.inline_hdr_blocks(document,str(self.source)))

    def test_partial_cube_blocks_are_not_silently_merged_between_faces(self):
        document,_=self.cube();document['Exports'][0]['PlatformData']['Mips'][0]['SizeY']=2
        with self.assertRaisesRegex(ValueError,'padding'):meshimages.inline_hdr_blocks(document,str(self.source))


if __name__=='__main__':unittest.main()
