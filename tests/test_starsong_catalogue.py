"""Catalogue refresh and artwork checks with a versioned Game Data API fixture."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from atelier.catalogue import Catalogue, fetch


API = 'https://data.starsong.dev/marvel-rivals/graphql'
CDN = 'https://cdn.starsong.dev/marvel-rivals/objects'
PIN = '1.1.4066382:1'
RIVAL_POSTER = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/29/img_amethyst-armor.webp'
RIVAL_RECOLOUR = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/29/img_recolour.webp'


def image(letter, width=219, height=219):
    return {'hash': letter * 64, 'width': width, 'height': height}


def connection(nodes, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}


def colour_webp(colour):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(buffer, 'WEBP', lossless=True)
    return buffer.getvalue()


class GameData:
    def __init__(self):
        self.pin = PIN
        self.skin_name = 'Amethyst Armor'
        self.requests = []
        self.fail_poster = False
        self.wrong_page_revision = False
        self.ambiguous_bundle = False
        self.extra_heroes = 0
        self.hero_forms = [{'shapeId': 0}]

    def fetch(self, url, *args, **kwargs):
        self.requests.append(url)
        if url == RIVAL_POSTER or url == RIVAL_RECOLOUR:
            return colour_webp((180, 20, 10)), {}
        if url.startswith(CDN + '/'):
            if self.fail_poster and '/aa/' in url:
                raise OSError('Missing CDN object')
            return colour_webp((32, 106, 160)), {}
        if not url.startswith(API + '?'):
            raise AssertionError(f'Unexpected source {url}')
        params = parse_qs(urlsplit(url).query)
        query = params['query'][0]
        variables = json.loads(params.get('variables', ['{}'])[0])
        revision = {'pin': self.pin}
        if 'CatalogueHeroes' in query:
            hero = {
                'id': '1029', 'name': 'Magik', 'playable': True,
                'forms': self.hero_forms,
                'defaultForm': {'portrait': image('c', 683, 683), 'icon': image('d', 342, 342)},
                'logo': image('e', 600, 600), 'signature': None,
            }
            revision['heroes'] = connection([hero, *[
                {**hero, 'id': str(1100 + index)} for index in range(self.extra_heroes)
            ]])
        elif 'CatalogueSkins' in query:
            after = variables.get('after')
            if after:
                if self.wrong_page_revision:
                    revision['pin'] = '1.1.4066382:3'
                revision['items'] = connection([{
                    'id': 'ps1029101', 'name': 'New Recolour', 'type': 'SKIN_COLOR',
                    'heroes': [{'id': '1029'}], 'art': {'poster': None, 'icon': None},
                    'bundles': connection([]),
                }])
            else:
                skin = {'id': '1029100', 'type': 'SKIN', 'art': {}}
                plate = {'id': '31029200', 'type': 'NAMEPLATE',
                         'art': {'nameplate': {'plate': image('f', 848, 192)}, 'icon': image('e')}}
                spray = {'id': '41029200', 'type': 'SPRAY',
                         'art': {'spray': {'still': image('b', 1024, 1024)}}}
                cosmetics = [skin, plate, spray]
                if self.ambiguous_bundle:
                    cosmetics.append({'id': 'ps1029101', 'type': 'SKIN_COLOR', 'art': {}})
                revision['items'] = connection([{
                    **skin, 'name': self.skin_name, 'heroes': [{'id': '1029'}],
                    'art': {'poster': image('a', 683, 683), 'icon': image('b')},
                    'bundles': connection([{'items': cosmetics}]),
                }], 'second')
        elif 'CatalogueNameplates' in query:
            # Longer ID filters exceed the API's bound-parameter limit.
            if len(variables['ids']) > 90:
                return json.dumps({'errors': [{'message': 'too many SQL variables'}]}).encode(), {}
            revision['items'] = connection([{
                'id': '31029001', 'type': 'NAMEPLATE', 'art': {
                    'nameplate': {'plate': image('f', 848, 192)}, 'icon': image('e'),
                },
            }] if '31029001' in variables['ids'] else [])
        elif 'CatalogueRevision' not in query:
            raise AssertionError(query)
        return json.dumps({'data': {'revision': revision}}).encode(), {}


class StarsongCatalogueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        self.seed = path / 'seed.json'
        self.root = path / 'cache'
        self.seed.write_text(json.dumps({'schema': 1, 'entries': {
            '1029': {'name': 'Older Magik', 'kind': 'hero', 'image': RIVAL_POSTER},
            '1029100': {'name': 'Old name', 'kind': 'skin', 'hero': '1029', 'image': RIVAL_POSTER},
            '1029101': {'name': 'Old Recolour', 'kind': 'skin', 'hero': '1029', 'image': RIVAL_RECOLOUR},
        }}), encoding='utf-8')
        self.game = GameData()
        self.catalogue = Catalogue(self.root, self.seed)

    def test_refresh_pins_every_page_and_reuses_a_saved_revision(self):
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertIsNone(self.catalogue.status()['error'])
            self.assertEqual(self.catalogue.status()['revision'], PIN)
            self.assertEqual(self.catalogue.identity('Characters/1029/1029100')['skin_name'], 'Amethyst Armor')
            self.assertEqual(self.catalogue.identity('Characters/1029/1029101')['skin_name'], 'New Recolour')
            self.assertNotIn('at', parse_qs(urlsplit(self.game.requests[0]).query))
            self.assertTrue(all(parse_qs(urlsplit(url).query).get('at') == [PIN]
                                for url in self.game.requests[1:]))

            restarted = Catalogue(self.root, self.seed)
            self.assertEqual(restarted.status()['revision'], PIN)
            self.game.requests.clear()
            restarted.update()
            self.assertEqual(len(self.game.requests), 1)

    def test_incomplete_refresh_retains_the_last_successful_revision_on_disk(self):
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertIsNone(self.catalogue.status()['error'])
            self.game.pin = '1.1.4066382:2'
            self.game.skin_name = 'Partial replacement'
            self.game.wrong_page_revision = True
            self.catalogue.update()
            self.assertIsNotNone(self.catalogue.status()['error'])
        for instance in (self.catalogue, Catalogue(self.root, self.seed)):
            self.assertEqual(instance.status()['revision'], PIN)
            self.assertEqual(instance.identity('Characters/1029/1029100')['skin_name'], 'Amethyst Armor')

    def test_primary_artwork_is_cached_and_missing_art_uses_rivalskins(self):
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            primary = self.catalogue.thumbnail('1029100')
            self.assertIsNotNone(primary)
            with Image.open(primary) as picture:
                self.assertEqual(picture.getpixel((0, 0)), (32, 106, 160))
            self.assertIsNotNone(self.catalogue.icon('1029100'))
            self.assertIsNotNone(self.catalogue.hero_image('1029', 'avatar'))
            self.assertIsNotNone(self.catalogue.banner('1029100'))
            self.assertIsNotNone(self.catalogue.spray('1029100'))
            fallback = self.catalogue.thumbnail('1029101')
            with Image.open(fallback) as picture:
                self.assertEqual(picture.getpixel((0, 0)), (180, 20, 10))
            self.assertIn(RIVAL_RECOLOUR, self.game.requests)
            self.assertNotIn(RIVAL_POSTER, self.game.requests)
        with patch('atelier.catalogue.fetch', side_effect=OSError('offline')):
            self.assertEqual(Catalogue(self.root, self.seed).thumbnail('1029100'), primary)

    def test_failed_cdn_download_uses_the_verified_skin_art(self):
        self.game.fail_poster = True
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertIsNone(self.catalogue.status()['error'])
            with Image.open(self.catalogue.thumbnail('1029100')) as picture:
                self.assertEqual(picture.getpixel((0, 0)), (180, 20, 10))
        self.assertIn(RIVAL_POSTER, self.game.requests)

    def test_multi_form_portrait_prefers_existing_verified_art_and_can_use_the_default_for_new_heroes(self):
        self.game.hero_forms = [{'shapeId': 0}, {'shapeId': 1}]
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertEqual(self.catalogue.data['entries']['1029']['image'], RIVAL_POSTER)
            new = Catalogue(self.root, self.root / 'no-offline-seed.json')
            self.assertEqual(new.status()['revision'], PIN)
            path = new.thumbnail('1029')
            self.assertIsNotNone(path)
            with Image.open(path) as picture:
                self.assertEqual(picture.getpixel((0, 0)), (32, 106, 160))

    def test_nameplate_filters_fit_the_service_limit_for_a_full_roster(self):
        self.game.extra_heroes = 55
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertIsNone(self.catalogue.status()['error'])
            self.assertIsNotNone(self.catalogue.banner('1029'))

    def test_bundle_with_two_skins_does_not_assign_either_cosmetic(self):
        self.game.ambiguous_bundle = True
        with patch('atelier.catalogue.fetch', side_effect=self.game.fetch):
            self.catalogue.update()
            self.assertIsNone(self.catalogue.status()['error'])
            self.assertIsNone(self.catalogue.banner('1029100'))
            self.assertIsNone(self.catalogue.spray('1029100'))

    def test_requests_identify_atelier_to_starsong(self):
        with patch('atelier.catalogue.urllib.request.build_opener') as opener:
            stream = opener.return_value.open.return_value.__enter__.return_value
            stream.read.return_value = b'{}'
            stream.headers = {}
            for url in (API + '?query=%7Brevision%7Bpin%7D%7D',
                        CDN + '/aa/' + 'a' * 64 + '?width=683'):
                fetch(url)
                request = opener.return_value.open.call_args.args[0]
                self.assertTrue(request.get_header('User-agent').startswith('Atelier/'))
                self.assertIn('https://github.com/clownfetus/Atelier', request.get_header('User-agent'))


if __name__ == '__main__':
    unittest.main()
