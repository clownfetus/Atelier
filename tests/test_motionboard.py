"""Real VFX readers/sidecars/export operations; native decoding is an explicit fixture."""
import atexit
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix='atelier-motionboard-')
os.environ['ATELIER_DATA_DIR'] = _data.name
from atelier import config as C
from atelier.handlers import vfx as V
from motionboard_fixtures import ASSET, details, bindings
atexit.register(_data.cleanup)


class MotionboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-motionboard-case-')
        self.root = Path(self.temp.name).resolve()
        self.project = self.root/'project'; self.project.mkdir()
        self.cache = self.root/'cache'; self.cache.mkdir()
        self.base = self.root/'original'/Path(ASSET).name
        self.base.parent.mkdir(); self.base.with_suffix('.uasset').write_bytes(b'original cooked package')
        self.base.with_suffix('.uexp').write_bytes(b'original untouched payload')
        self.native = details(); self.payload = None
        self.stack = ExitStack()
        self.stack.enter_context(C.project_context(str(self.project)))
        self.stack.enter_context(patch.object(V, '_CACHE', str(self.cache)))
        self.stack.enter_context(patch.object(V, '_ensure_extracted', return_value=str(self.base)))
        self.label_reader = V._vfx_labels
        self.stack.enter_context(patch.object(V, '_vfx_labels', return_value=bindings()))
        self.stack.enter_context(patch.object(V, 'pak_game_path', side_effect=lambda gr:'Marvel/Content/Marvel/'+gr))
        self.tool = self.stack.enter_context(patch.object(V, 'uat', side_effect=self.uat))

    def tearDown(self):
        self.stack.close(); self.temp.cleanup()

    def uat(self, args):
        if args[0] == 'niagara_details':
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.native), stderr='')
        if args[0] == 'niagara_edit':
            self.payload = json.loads(Path(args[args.index('--edits-file')+1]).read_text())
            Path(args[args.index('--output')+1]).write_bytes(b'edited package')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        self.fail('Unexpected native command: '+args[0])

    def path(self):
        return Path(V.vfx_sidecar(ASSET))

    def group(self, index=0):
        group = V.read_vfx(ASSET)['groups'][index]
        return {key: copy.deepcopy(group[key]) for key in ('export_indices','stops','sample_count','channels')}

    def test_reader_retains_pristine_lut_bindings_dimensions_and_unsupported_exports(self):
        result = V.read_vfx(ASSET)
        self.assertEqual(len(result['groups']), 6)
        color = result['groups'][0]
        self.assertEqual(color['export_indices'], [1,2])
        self.assertEqual(color['original_samples'], self.native['exports'][0]['shaderLut']['samples'])
        self.assertEqual(color['time_range'], [0,1])
        self.assertEqual(color['bindings'][0]['names'], ['Sparks.ScaleColor.ColorScale'])
        self.assertEqual(color['bindings'][1]['source'], 'owner')
        self.assertEqual(color['classification_source'], 'samples')
        self.assertFalse(color['has_saved_edit'])
        self.assertEqual(result['unsupported_exports'][0]['export_index'], 8)
        self.assertFalse(self.path().exists())

    def test_grouping_never_merges_differences_outside_preview_stops(self):
        samples = [[i/39] for i in range(40)]
        a = {'exportIndex':20,'channels':1,'shaderLut':{'sampleCount':40,'floatCount':40,'samples':samples}}
        b = copy.deepcopy(a); b['exportIndex']=21; b['shaderLut']['samples'][1][0]=.123456789
        self.native['exports']=[a,b]
        self.assertEqual(V._downsample(a['shaderLut']['samples'],16), V._downsample(b['shaderLut']['samples'],16))
        self.assertEqual(len(V.read_vfx(ASSET)['groups']),2)

    def test_editing_handles_sample_exact_uniform_lut_positions(self):
        stops=V._downsample([[0],[0],[1],[0]],3)
        self.assertEqual(stops,[[0],[.5],[0]])

    def test_bindings_preserve_all_named_uses_and_cache_matches_source(self):
        def entry(name):
            return {'Value':[{'Name':'Name','Value':name},{'Name':'ResolvedDataInterface','Value':1}]}
        document={'Exports':[{'ObjectName':'Curve','OuterIndex':2},
                            {'ObjectName':'UpdateScript','OuterIndex':3,'Data':[{'Name':'ResolvedDataInterfaces','Value':[
                                entry('Emitter.ScaleColor.ColorScale'),entry('Emitter.ScaleColor.AlphaScale')]}]},
                            {'ObjectName':'Emitter','OuterIndex':0}]}
        def to_json(args):
            Path(args[3],Path(ASSET).name+'.json').write_text(json.dumps(document))
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch.object(V,'uat',side_effect=to_json) as tool:
            first=self.label_reader(ASSET,str(self.base),metadata=True)
            self.assertEqual(first[0]['source'],'binding')
            self.assertEqual(first[0]['names'],['Emitter.ScaleColor.ColorScale','Emitter.ScaleColor.AlphaScale'])
            self.assertEqual(first[1]['source'],'owner')
            self.assertEqual(self.label_reader(ASSET,str(self.base))[0],'Emitter · ScaleColor · ColorScale')
            self.assertEqual(tool.call_count,1)
            self.base.with_suffix('.uasset').write_bytes(b'updated source package')
            self.label_reader(ASSET,str(self.base),metadata=True)
            self.assertEqual(tool.call_count,2)

    def test_timeline_math_and_preview_binding_contract(self):
        test=Path(__file__).with_name('motionboard_data_checks.js')
        result=subprocess.run(['node',str(test)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_saved_edits_overlay_without_replacing_game_reference_or_losing_precision(self):
        group=self.group(); group['stops'][2][0]=.123456789
        V.save_vfx(ASSET,[group])
        result=V.read_vfx(ASSET)['groups'][0]
        self.assertEqual(result['stops'][2][0],.123456789)
        self.assertEqual(result['original_stops'][2][0],.5)
        self.assertTrue(result['has_saved_edit'])
        self.assertEqual(V.read_vfx(ASSET,original=True)['groups'][0]['stops'][2][0],.5)
        self.assertEqual(set(json.loads(self.path().read_text())['vfx_edits'][0]), {'export_indices','stops','sample_count','channels'})

    def test_timeline_edits_use_existing_lut_rebuilder_and_only_changed_exports(self):
        group=self.group(); group['stops'][1]=[4,.3,.2,.15]
        V.save_vfx(ASSET,[group])
        V.stage_vfx(str(self.root/'stage'),ASSET)
        expected=V._rebuild_lut(group['stops'],group['sample_count'],group['channels'])
        self.assertEqual([p['exportIndex'] for p in self.payload],[1,2])
        self.assertTrue(all(p['flatLut']==expected for p in self.payload))
        self.assertEqual(len(expected),group['sample_count']*4)

    def test_restoring_all_tracks_exports_the_unchanged_cooked_asset(self):
        V.save_vfx(ASSET,[])
        stage=self.root/'stage'; V.stage_vfx(str(stage),ASSET)
        self.assertIsNone(self.payload)
        self.assertEqual(next(stage.rglob('NS_Motionboard.uasset')).read_bytes(),self.base.with_suffix('.uasset').read_bytes())
        self.assertEqual(next(stage.rglob('NS_Motionboard.uexp')).read_bytes(),self.base.with_suffix('.uexp').read_bytes())

    def test_legacy_sidecar_and_unavailable_edits_and_metadata_survive_save(self):
        group=self.group(); group['stops'][0][0]=.75
        unavailable={**self.group(1),'export_indices':[999]}
        legacy=Path(C.project_base_legacy(ASSET)+'.json')
        legacy.write_text(json.dumps({'vfx_edits':[group,unavailable],'custom_metadata':'keep'}))
        self.assertEqual(V.read_vfx(ASSET)['groups'][0]['stops'][0][0],.75)
        V.save_vfx(ASSET,[group])
        saved=json.loads(self.path().read_text())
        self.assertEqual(saved['custom_metadata'],'keep')
        self.assertEqual(saved['vfx_edits'][1],unavailable)
        self.assertEqual(V.read_vfx(ASSET)['unmatched_edits'],1)
        with self.assertRaisesRegex(ValueError,'no longer'):
            V.stage_vfx(str(self.root/'stage'),ASSET)
        self.assertIsNone(self.payload)

    def test_partly_unavailable_saved_clone_group_is_reported(self):
        group=self.group(); group['export_indices'].append(999)
        self.path().parent.mkdir(parents=True,exist_ok=True)
        self.path().write_text(json.dumps({'vfx_edits':[group]}))
        result=V.read_vfx(ASSET)
        self.assertTrue(result['groups'][0]['has_saved_edit'])
        self.assertEqual(result['unmatched_edits'],1)

    def test_invalid_edits_fail_before_publication_and_cannot_rewrite_other_exports(self):
        valid=self.group(); V.save_vfx(ASSET,[valid]); before=self.path().read_bytes()
        for field,value in [('channels',3),('sample_count',1024),('export_indices',[1,999]),('stops',[[float('nan')]*4]),
                            ('stops',[[1e100]*4]),('stops',[[True]*4]),('stops',[[1,2]])]:
            group=copy.deepcopy(valid); group[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): V.save_vfx(ASSET,[group])
            self.assertEqual(self.path().read_bytes(),before)
        with self.assertRaises(ValueError): V.save_vfx(ASSET,[valid,valid])
        for invalid in ({},False,'',1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): V.save_vfx(ASSET,invalid)
            self.assertEqual(self.path().read_bytes(),before)

    def test_reset_reads_pristine_before_removing_existing_edits(self):
        group=self.group(); group['stops'][0][0]=.3; V.save_vfx(ASSET,[group]); before=self.path().read_bytes()
        with patch.object(V,'uat',side_effect=RuntimeError('native read failed')), self.assertRaises(RuntimeError):
            V.reset_vfx(ASSET)
        self.assertEqual(self.path().read_bytes(),before)
        result=V.reset_vfx(ASSET)
        self.assertFalse(self.path().exists())
        self.assertEqual(result['groups'][0]['stops'],result['groups'][0]['original_stops'])


if __name__=='__main__':
    unittest.main()
