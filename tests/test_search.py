"""Search normalization, caps, generation invalidation and the full-index query budget."""
import atexit
import io
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
data=tempfile.TemporaryDirectory(prefix='atelier-search-');atexit.register(data.cleanup)
os.environ['ATELIER_DATA_DIR']=data.name
from atelier import index as I, search as S
from atelier.catalogue import catalogue
from atelier.web import routes as R
atexit.register(lambda: R.shutdown(5))


class Search(unittest.TestCase):
    def setUp(self):
        entries=[(f'Characters/1029/1029001/Textures/T_Café_{i}.uasset','fixture','mount') for i in range(75)]
        entries += [('Effects/Curve_Glow.uasset','fixture','mount')]
        self.scope=patch.object(I,'_INDEX',entries);self.scope.start();self.addCleanup(self.scope.stop)
        self.names=patch.object(catalogue,'data',{'entries':{
            '1029':{'kind':'hero','name':'Éclair'},'1029001':{'kind':'skin','name':'Café armour','hero':'1029'}}})
        self.names.start();self.addCleanup(self.names.stop)

    def test_groups_accent_case_and_context_names_agree(self):
        result=S.search('ECLAIR')
        self.assertEqual(result['heroes'][0]['id'],'1029')
        self.assertEqual(result['skins'][0]['id'],'1029001')
        self.assertEqual(result['totals']['assets'],75)
        self.assertTrue(result['folders'])
        result=S.search('CAFE')
        self.assertEqual(result['skins'][0]['id'],'1029001')
        self.assertEqual(result['assets'][0]['type'],'texture')
        self.assertEqual(result['assets'][0]['parent'],'Characters/1029/1029001/Textures')
        self.assertEqual(S.search('1029001 café_7')['totals']['assets'],6)

    def test_caps_totals_empty_and_invalid_limits(self):
        result=S.search('cafe',3)
        self.assertEqual(len(result['assets']),3);self.assertEqual(result['totals']['assets'],75)
        self.assertEqual(len(S.search('cafe',1000)['assets']),50)
        self.assertEqual(S.search('')['totals']['assets'],0)
        self.assertEqual(len(S.search('cafe','bad')['assets']),50)

    def test_names_resolve_in_flat_ui_vfx_and_plugin_paths(self):
        paths = ['UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom/1029001/T_Portrait',
                 'VFX/1029/1029001/Textures/T_Glow', 'Plugins/MarvelGAS/UI/1029001/T_Icon', 'UI/T_1029001_Card']
        with patch.object(I, '_INDEX', [(path+'.uasset', 'fixture', 'mount') for path in paths]):
            result = S.search('eclair cafe')
            self.assertEqual(result['totals']['assets'], 4)
            self.assertTrue(all(item['char_name'] == 'Éclair' and item['skin_name'] == 'Café armour'
                                for item in result['assets']))
            folder = next(item for item in result['folders'] if item['path'].endswith('/1029001'))
            self.assertEqual(folder['display_name'], 'Café armour')
            self.assertIn('1029001', folder['path'])

    def test_replaced_index_and_catalogue_invalidate_cached_table(self):
        S.search('cafe');first=S._table
        S.search('cafe');self.assertIs(first,S._table)
        with patch.object(I,'_INDEX',[('New/T_Next.uasset','fixture','mount')]):
            self.assertEqual(S.search('cafe')['totals']['assets'],0)
            self.assertEqual(S.search('next')['assets'][0]['game_rel'],'New/T_Next')
        with patch.object(catalogue,'data',{'entries':{'1029':{'kind':'hero','name':'Updated name'}}}):
            self.assertEqual(S.search('updated')['totals']['assets'],75)

    def test_pending_builder_is_not_waited_on(self):
        with patch.object(I,'_INDEX',None),patch.object(I,'index_progress',return_value={'stage':'indexing'}),patch.object(I,'ensure_index') as ensure:
            self.assertTrue(S.search('next')['building']);ensure.assert_not_called()

    def test_http_route_preserves_group_totals_and_limit(self):
        env={};setup_testing_defaults(env)
        env.update(REQUEST_METHOD='GET',PATH_INFO='/api/search',QUERY_STRING=urlencode({'q':'café','limit':2}),**{'wsgi.input':io.BytesIO(b'')})
        status=[];result=json.loads(b''.join(R.app(env,lambda code,*args:status.append(code))))
        self.assertTrue(status[0].startswith('200'))
        self.assertEqual(result['totals']['assets'],75);self.assertEqual(len(result['assets']),2)

    def test_full_index_cached_query_budget(self):
        entries=[(f'Characters/{1000+i%50}/{1000000+i%700}/Textures/T_Asset_{i:06d}.uasset','fixture','mount') for i in range(550000)]
        with patch.object(I,'_INDEX',entries):
            S.search('warm')
            timings=[]
            for query in ('1234','9876','3456','5432','6789'):
                start=time.perf_counter();result=S.search(query);timings.append((time.perf_counter()-start)*1000)
                self.assertLessEqual(len(result['assets']),50)
            median=statistics.median(timings)
            print(f'Search 550000 assets: median {median:.1f} ms; samples '+', '.join(f'{v:.1f}' for v in timings),flush=True)
            self.assertLess(median,100,'Cached typical queries exceeded the 100 ms budget')


if __name__=='__main__':unittest.main()
