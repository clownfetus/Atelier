"""Offline regression tests for optional catalogue matching and failure handling."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from atelier.catalogue import (Catalogue, PARSER_VERSION, allowed_url,
                               build_entries, parse_item, parse_cards, parse_ids)

IMAGE = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/1/hero.webp'
HERO = 'https://rivalskins.com/hero/magik/'
CARDS = f'''<a data-type="costume" href="https://rivalskins.com/item/1/magik/">
 <picture><source srcset="{IMAGE}" type="image/webp"><img alt="Amethyst Armor" src="fallback.png"></picture></a>
 <a data-type="spray"><img src="{IMAGE}" alt="Wrong cosmetic"></a>'''


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / 'seed.json'
        self.seed.write_text(json.dumps({'schema': 1, 'entries': {
            '1029': {'name': 'Magik', 'kind': 'hero', 'image': IMAGE},
            '1029100': {'name': 'Amethyst Armor', 'kind': 'skin', 'image': IMAGE}}}))
        self.catalogue = Catalogue(self.root / 'cache', self.seed)

    def test_missing_trailing_pipe_and_old_duplicate(self):
        chars = parse_ids('| 1057 | Deadpool | 1057100 | X-Force?\n'
                          '| | | 1057500 | Workwear Woes |\n'
                          '| 1057 | Professor X (Old) | | |\n'
                          '| | | 1057999 | Never carry old rows |')
        self.assertEqual(chars['1057']['name'], 'Deadpool')
        self.assertEqual(set(chars['1057']['skins']), {'1057100', '1057500'})

    def test_only_costume_artwork(self):
        cards = parse_cards(CARDS)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['image'], IMAGE)

    def test_item_artwork_is_scoped_to_stage(self):
        stage = f'<div class="rs-stage"><div><picture><source type="image/webp" srcset="{IMAGE}"></picture></div></div>'
        parsed = parse_item(stage + '<button data-copy="1029100"></button>')
        self.assertEqual(parsed, {'ids': ['1029100'], 'image': IMAGE})
        self.assertEqual(parse_item(stage)['ids'], [])  # Recolor pages may omit IDs.
        with self.assertRaises(ValueError):
            parse_item(f'<div class="rs-stage"></div><source type="image/webp" srcset="{IMAGE}">')

    def test_scoped_alias_and_labelled_fallback(self):
        chars = {'1029': {'name': 'Magik', 'skins': {'1029100': 'AMETHEYST ARMOR', '1029101': 'Unknown'}}}
        entries = build_entries(chars, [{'name': 'Magik', 'image': IMAGE, 'page': HERO}], lambda _: CARDS,
                                lambda _: [{'ids': ['1029100', '1036100'], 'image': IMAGE}])
        self.assertFalse(entries['1029100']['hero_fallback'])
        self.assertEqual(entries['1029100']['name'], 'AMETHEYST ARMOR')
        self.assertTrue(entries['1029101']['hero_fallback'])
        self.assertNotIn('1029000', entries)  # Never invent a default game ID.
        self.assertNotIn('1036100', entries)

    def test_unique_exact_name_only_when_source_omits_id(self):
        chars = {'1029': {'name': 'Magik', 'skins': {'1029100': 'AMETHYST ARMOR', '1029101': 'Amethyst Armor (Alt.)'}}}
        roster = [{'name': 'Magik', 'image': IMAGE, 'page': HERO}]
        load = lambda pages: [{'ids': [], 'image': IMAGE} for _ in pages]
        entries = build_entries(chars, roster, lambda _: CARDS, load)
        self.assertEqual(entries['1029100']['match'], 'name')
        self.assertTrue(entries['1029101']['hero_fallback'])
        entries = build_entries(chars, roster, lambda _: CARDS * 2, load)
        self.assertTrue(entries['1029100']['hero_fallback'])  # Ambiguous source name.
        entries = build_entries(chars, roster, lambda _: CARDS,
                                lambda _: [{'ids': ['1036100'], 'image': IMAGE}])
        self.assertTrue(entries['1029100']['hero_fallback'])  # Conflicting ID overrides the name.

    def test_npcs_are_not_playable_heroes(self):
        entries = build_entries({'4057': {'name': 'Deadpool', 'skins': {}}},
                                [{'name': 'Deadpool', 'image': IMAGE, 'page': HERO}], lambda _: CARDS, lambda _: [])
        self.assertIsNone(entries['4057']['image'])

    def test_changed_site_format_does_not_silently_replace_skins(self):
        with self.assertRaises(ValueError):
            build_entries({'1029': {'name': 'Magik', 'skins': {}}},
                          [{'name': 'Magik', 'image': IMAGE, 'page': HERO}], lambda _: '<html>Changed</html>', lambda _: [])

    def test_only_character_and_skin_folder_paths(self):
        for path in ('Characters/1029/1029100/Textures', 'Characters/1036/1029100', '../1029', 'UI/1029'):
            self.assertIsNone(self.catalogue.describe(path))
        self.assertIn('1029100', self.catalogue.describe('Characters/1029/1029100')['thumbnail'])
        self.assertTrue(self.catalogue.describe('Characters/1029/1029999')['hero_fallback'])

    def test_sources_are_allowlisted(self):
        self.assertTrue(allowed_url(IMAGE))
        for url in ('http://rivalskins.com/hero/a/', 'https://rivalskins.com.evil/hero/a/',
                    'https://rivalskins.com:bad/hero/a/', 'file:///test', 'https://rivalskins.com@127.0.0.1/hero/a/'):
            self.assertFalse(allowed_url(url))

    def test_offline_update_keeps_good_entries(self):
        previous = self.catalogue.data
        with patch('atelier.catalogue.fetch', side_effect=TimeoutError('offline')):
            self.catalogue.update()
        self.assertIs(self.catalogue.data, previous)
        self.assertFalse(self.catalogue.status()['updating'])
        self.assertEqual(self.catalogue.status()['error'], 'offline')

    def test_malformed_cache_uses_seed(self):
        self.catalogue.root.mkdir()
        (self.catalogue.root / 'catalogue.json').write_text('{broken')
        loaded = Catalogue(self.catalogue.root, self.seed)
        self.assertEqual(loaded.describe('Characters/1029')['name'], 'Magik')

    def test_image_cache_survives_offline_and_rejects_non_image(self):
        data = io.BytesIO()
        Image.new('RGB', (8, 8)).save(data, format='WEBP')
        with patch('atelier.catalogue.fetch', return_value=(data.getvalue(), {})) as get:
            path = self.catalogue.thumbnail('1029')
            self.assertTrue(path.is_file())
            self.assertEqual(self.catalogue.thumbnail('1029100'), path)
            get.assert_called_once()
        with patch('atelier.catalogue.fetch', side_effect=TimeoutError('offline')):
            self.assertEqual(self.catalogue.thumbnail('1029'), path)
        path.unlink()
        with patch('atelier.catalogue.fetch', return_value=(b'<html>not artwork</html>', {})) as get:
            self.assertIsNone(self.catalogue.thumbnail('1029'))
            self.assertIsNone(self.catalogue.thumbnail('1029'))
            get.assert_called_once()  # short failure cooldown

    def test_one_background_update_per_process(self):
        with patch('atelier.catalogue.threading.Thread') as worker:
            self.catalogue.start_update()
            self.catalogue.start_update()
            worker.assert_called_once()
            worker.return_value.start.assert_called_once()

    def test_unchanged_catalogue_skips_full_crawl(self):
        import hashlib
        chars = {str(1000+i): {'name': f'Hero {i}', 'skins': {}} for i in range(20)}
        roster = [{'name': f'Hero {i}', 'image': IMAGE, 'page': HERO} for i in range(20)]
        self.catalogue.data.update(parser_version=PARSER_VERSION,
                                   content_hash=hashlib.sha256(json.dumps([chars, roster], sort_keys=True).encode()).hexdigest(), refreshed_at=1000)
        with patch('atelier.catalogue.time.time', return_value=1001), \
             patch('atelier.catalogue.fetch', return_value=(b'source', {})) as get, \
             patch('atelier.catalogue.parse_ids', return_value=chars), \
             patch('atelier.catalogue.parse_cards', return_value=roster), \
             patch('atelier.catalogue.build_entries') as build:
            self.catalogue.update()
        self.assertEqual(get.call_count, 2)
        build.assert_not_called()
        self.assertEqual(self.catalogue.status()['checked_at'], 1001)


if __name__ == '__main__':
    unittest.main()
