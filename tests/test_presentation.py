"""Launch-cache, metadata preview and real indexing progress regressions. No game/native tools."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-presentation-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier.window_theme import WindowTheme
from atelier import index as I
from atelier.ui_preview import saved_preview
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    data.cleanup()


atexit.register(cleanup)


class Presentation(unittest.TestCase):
    def test_validated_cache_resolves_system_theme_at_launch(self):
        with tempfile.TemporaryDirectory() as root, patch('atelier.window_theme._system_dark', return_value=False):
            appearance = WindowTheme(root)
            self.assertEqual(appearance._background(), '#f5f6f8')
            self.assertFalse(appearance.set_window_theme('dark', 'url(invalid)')['ok'])
            self.assertFalse(appearance._path.exists())
            self.assertTrue(appearance.set_window_theme('dark', '#112233', 'system', '#fafafa', '#112233')['ok'])
            self.assertEqual(WindowTheme(root)._background(), '#fafafa')
            with patch('atelier.window_theme._system_dark', return_value=True):
                self.assertEqual(WindowTheme(root)._background(), '#112233')
            appearance._path.write_text('{broken', encoding='utf-8')
            self.assertEqual(WindowTheme(root)._background(), '#f5f6f8')
            appearance._path.write_text('[]', encoding='utf-8')
            self.assertEqual(WindowTheme(root)._background(), '#f5f6f8')

    def test_previews_use_only_existing_json_and_keep_it_unchanged(self):
        root = Path(data.name, 'preview'); root.mkdir(exist_ok=True)
        base = root / 'MI_Test'
        material = {'Exports':[{'Data':[{'Name':'VectorParameterValues','Value':[
            {'Value':[{'Name':'ParameterInfo','Value':[{'Name':'Name','Value':'BaseColor'}]},
                      {'Name':'ParameterValue','Value':[{'Value':{'R':9,'G':.3,'B':.2,'A':.5}}]}]}]}]}]}
        path = base.with_suffix('.json'); path.write_text(json.dumps(material), encoding='utf-8')
        before = path.read_bytes()
        with patch('atelier.ui_preview.project_base', return_value=str(base)), patch('atelier.ui_preview.project_base_legacy', return_value=str(base)):
            self.assertEqual(saved_preview('Fixture/MI_Test', 'material'), {'colors':[[9.0,.3,.2,.5]]})
            self.assertEqual(path.read_bytes(), before)
            curve = {'Exports':[{'Data':[{'Name':'FloatCurves','Value':[{'Name':'Keys','Value':[
                {'Value':[{'Value':{'Time':0,'Value':0}}]}, {'Value':[{'Value':{'Time':1,'Value':1}}]}]}]}]}]}
            path.write_text(json.dumps(curve), encoding='utf-8')
            self.assertEqual(saved_preview('Fixture/Curve', 'curve'), {'points':[[2.0,25.0],[38.0,3.0]]})
            path.write_text('{broken', encoding='utf-8'); self.assertIsNone(saved_preview('Fixture/MI_Test','material'))
            path.unlink(); self.assertIsNone(saved_preview('Fixture/MI_Test','material'))

    def test_index_progress_tracks_actual_completed_containers(self):
        observed = []
        def parse(path):
            observed.append(I.index_progress())
            return object()
        with tempfile.TemporaryDirectory() as root, patch.object(I,'_INDEX',None), patch.object(I,'_utoc_key',return_value='fixture'), \
             patch.object(I,'_CACHE_FILE',str(Path(root,'cache.json'))), patch.object(I,'_CACHE',root), \
             patch.object(I,'_index_utocs',return_value=['one.utoc','two.utoc']), \
             patch.object(I.io_lib,'parse_toc',side_effect=parse), patch.object(I.io_lib,'parse_dir_index',return_value=[]):
            I.ensure_index()
            self.assertEqual([step['current'] for step in observed],[0,1])
            self.assertTrue(all(step['total']==2 and step['stage']=='indexing' for step in observed))
            self.assertEqual(I.index_progress(), {'stage':'ready','current':2,'total':2})

    def test_catalogue_home_is_metadata_only(self):
        from atelier.catalogue import catalogue
        entries={'1029':{'name':'Hero','kind':'hero','image':'https://example.invalid/hero.png'},
                 '1029001':{'name':'Skin','kind':'skin','hero':'1029','image':'https://example.invalid/skin.png'},
                 '9999':{'name':'NPC','kind':'hero','image':None}}
        env={};setup_testing_defaults(env);env.update(PATH_INFO='/api/catalogue/library',QUERY_STRING='',**{'wsgi.input':io.BytesIO()})
        statuses=[]
        with patch.object(catalogue,'data',{'entries':entries}):
            response=R.app(env,lambda status,headers,exc_info=None:statuses.append(status))
            result=json.loads(b''.join(response))
        self.assertEqual(statuses,['200 OK'])
        self.assertEqual(len(result['heroes']),1)
        self.assertEqual(result['heroes'][0]['skins'][0]['path'],'Characters/1029/1029001')
        self.assertNotIn('https:',json.dumps(result))


if __name__ == '__main__':
    unittest.main()
