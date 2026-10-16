"""Restoration and mip refresh retain editable assets, selection, paint and failure recovery."""
import atexit
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
data=tempfile.TemporaryDirectory(prefix='atelier-recovery-test-');atexit.register(data.cleanup)
os.environ['ATELIER_DATA_DIR']=data.name
from atelier import config as C,project_meta as PM
from atelier.handlers import projectedit as P,texturerefresh as R,meshreplace as M,texture
from atelier.web import browse


class Recovery(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.scope=C.project_context(str(self.root));self.scope.__enter__();self.addCleanup(self.scope.__exit__,None,None,None)
        self.gr='Characters/1040/1040001/Textures/T_1040304_10400_Equip_01_D'
        self.path=Path(C.project_base(self.gr)+'.png');self.path.parent.mkdir(parents=True)
        self.low=Image.new('RGBA',(8,8),(40,50,60,255));self.full=Image.new('RGBA',(16,16),(42,52,62,255))
        self.low.save(self.path)
        PM.set_deselected(str(self.root),[self.gr]);PM.set_asset_opts(str(self.root),self.gr,{'blank':True})

    def test_revert_keeps_file_and_export_selection(self):
        def decode(base,original):self.full.save(base+'.png');return base+'.png'
        with patch.object(texture,'ensure_work_base',return_value='source'),patch.object(texture,'decode_to_png',side_effect=decode): P.revert(self.gr)
        with Image.open(self.path) as image:self.assertEqual(image.size,(16,16));self.assertEqual(image.getpixel((0,0)),(42,52,62,255))
        self.assertEqual(len(browse.all_imported()),1)
        self.assertEqual(PM.get_deselected(str(self.root)),{self.gr});self.assertEqual(PM.get_asset_opts(str(self.root),self.gr),{})

    def test_failed_restore_preserves_edits_and_options(self):
        before=self.path.read_bytes()
        with patch.object(texture,'ensure_work_base',return_value=None),self.assertRaises(RuntimeError):P.revert(self.gr)
        self.assertEqual(self.path.read_bytes(),before);self.assertTrue(PM.get_asset_opts(str(self.root),self.gr)['blank'])

    def test_paint_and_alpha_survive_while_unpainted_areas_get_full_source(self):
        edited=self.low.copy();edited.putpixel((2,3),(230,2,10,0))
        merged,painted=R.merge_paint(edited,self.low,self.full)
        self.assertTrue(painted);self.assertEqual(merged.getpixel((4,6)),(230,2,10,0))
        self.assertEqual(merged.getpixel((0,0)),self.full.getpixel((0,0)))
        clean,painted=R.merge_paint(self.low,self.low,self.full)
        self.assertFalse(painted);self.assertTrue(np.array_equal(clean,self.full))

    def test_repair_backs_up_exact_saved_image_and_keeps_selection(self):
        self.low.putpixel((2,3),(230,2,10,127));self.low.save(self.path);before=self.path.read_bytes()
        baseline=Image.new('RGBA',(8,8),(40,50,60,255))
        def decode(base,original):self.full.save(base+'.png');return base+'.png'
        with patch.object(texture,'ensure_work_base',return_value='source'),patch.object(texture,'decode_to_png',side_effect=decode),patch.object(R,'source_mip',return_value=baseline):
            result=R.repair([{'game_rel':self.gr}])
        self.assertEqual(len(result['repaired']),1);self.assertEqual(result['skipped'],[])
        self.assertEqual((self.root/result['repaired'][0]['backup']).read_bytes(),before)
        with Image.open(self.path) as image:self.assertEqual(image.size,(16,16));self.assertEqual(image.getpixel((4,6)),(230,2,10,127))
        self.assertEqual(len(browse.all_imported()),1);self.assertEqual(PM.get_deselected(str(self.root)),{self.gr})

    def test_external_change_during_extraction_is_never_overwritten(self):
        def decode(base,original):
            Image.new('RGBA',(8,8),'magenta').save(self.path);self.full.save(base+'.png');return base+'.png'
        with patch.object(texture,'ensure_work_base',return_value='source'),patch.object(texture,'decode_to_png',side_effect=decode),patch.object(R,'source_mip',return_value=self.low):result=R.repair([{'game_rel':self.gr}])
        self.assertFalse(result['repaired']);self.assertIn('changed',result['skipped'][0]['reason'])
        with Image.open(self.path) as image:self.assertEqual(image.getpixel((0,0)),(255,0,255,255))

    def test_unknown_baseline_does_not_guess_over_paint(self):
        before=self.path.read_bytes()
        def decode(base,original):self.full.save(base+'.png');return base+'.png'
        with patch.object(texture,'ensure_work_base',return_value='source'),patch.object(texture,'decode_to_png',side_effect=decode),patch.object(R,'source_mip',return_value=None):result=R.repair([{'game_rel':self.gr}])
        self.assertFalse(result['repaired']);self.assertEqual(self.path.read_bytes(),before)

    def test_model_revert_keeps_edit_entry_and_detects_later_blender_edits(self):
        gr='Characters/1057/1057001/Meshes/SK_1057_1057001';M.add(gr)
        M.revert(gr);self.assertTrue(M.is_original(gr))
        base=C.project_base(gr);Path(base+'.blend').write_bytes(b'user sculpt')
        self.assertFalse(M.is_original(gr))
        from atelier.handlers import meshedit
        def extract(game_rel,**options):Path(options['blend_path']).write_bytes(b'original')
        def blender(script,args,label):Path(args[1]).write_bytes(b'original preview')
        with patch.object(meshedit,'_resolve_base',return_value='source'),patch.object(meshedit,'extract_blend',side_effect=extract),patch.object(meshedit,'_run_blender',side_effect=blender):M.revert(gr)
        self.assertTrue(M.is_original(gr));Path(base+'.blend').write_bytes(b'new sculpt');self.assertFalse(M.is_original(gr))
        self.assertEqual(len([row for row in browse.all_imported() if row['file_type']=='mesh']),1)


if __name__=='__main__':unittest.main()
