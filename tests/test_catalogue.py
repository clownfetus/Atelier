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
from atelier.catalogue import (Catalogue, PARSER_VERSION, allowed_url, build_entries, icon_url,
                               nameplate_url, parse_item, parse_cards, parse_ids)

IMAGE = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/1/hero.webp'
HERO = 'https://rivalskins.com/hero/magik/'
CARDS = f'''<a data-type="costume" href="https://rivalskins.com/item/1/magik/">
 <picture><source srcset="{IMAGE}" type="image/webp"><img alt="Amethyst Armor" src="fallback.png"></picture></a>
 <a data-type="spray"><img src="{IMAGE}" alt="Wrong cosmetic"></a>'''
PLATES = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/nameplate/29/'


def nameplate(name, slug='amethyst-armor'):
    return f'''<a href="https://rivalskins.com/item/2/magik-nameplate-{slug}/" data-type="nameplate">
     <picture><source srcset="{PLATES}img_icon_{slug}.webp" type="image/webp"><img alt="{name}" src="x.png"></picture></a>'''


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

    def test_costume_icons_sit_beside_their_art_and_fallbacks_have_none(self):
        base = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/costume/1/'
        self.assertEqual(icon_url(base + 'img_king-in-white.webp'), base + 'img_icon_king-in-white.webp')
        self.assertIsNone(icon_url(base + 'img_icon_king-in-white.webp'))
        self.assertIsNone(icon_url('https://rivalskins.com/wp-content/uploads/marvel-assets/items/nameplate/46/img_nurse-pool.webp'))
        self.assertIsNone(icon_url(None))
        self.assertIsNone(self.catalogue.icon('1029'))
        with patch.dict(self.catalogue.data['entries'], {'1029101': {'name': 'Fallback', 'kind': 'skin', 'image': IMAGE, 'hero_fallback': True}}):
            self.assertIsNone(self.catalogue.icon('1029101'))

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

    def test_nameplate_banners_sit_beside_their_card_icons(self):
        self.assertEqual(nameplate_url(PLATES + 'img_icon_nurse-pool.webp'), PLATES + 'img_nurse-pool.webp')
        self.assertTrue(allowed_url(PLATES + 'img_nurse-pool.webp'))
        for icon in (PLATES + 'img_nurse-pool.webp', IMAGE.replace('hero.webp', 'img_icon_hero.webp'),
                     'https://rivalskins.com.evil/wp-content/uploads/marvel-assets/items/nameplate/29/img_icon_x.webp', None):
            self.assertIsNone(nameplate_url(icon))
        cards = parse_cards(CARDS + nameplate('AMETHYST ARMOR'), kind='nameplate')
        self.assertEqual([(card['name'], card['image']) for card in cards],
                         [('AMETHYST ARMOR', PLATES + 'img_icon_amethyst-armor.webp')])
        self.assertEqual(len(parse_cards(CARDS + nameplate('AMETHYST ARMOR'))), 1)  # Costumes stay costumes.
        wrong_folder = f'<a data-type="nameplate"><img src="{IMAGE}" alt="Amethyst Armor"></a>'
        self.assertEqual(parse_cards(wrong_folder, kind='nameplate'), [])

    def test_new_artwork_paths_are_narrowly_allowlisted(self):
        prefix = 'https://rivalskins.com/wp-content/uploads/marvel-assets/assets/'
        for path in ('lord-icons/item_herohead_21029020.png', 'lord-icons/Magik%20Deluxe%20Avatar.png',
                     'kill-icons/item_kill_2102912.webp', 'kill-icons/Magik%20Deluxe%20KO%20Prompt%201.png'):
            self.assertTrue(allowed_url(prefix + path), path)
        for path in ('lord-icons/../../evil.png', 'lord-icons/%2fetc.png', 'lord-icons/unknown.png',
                     'kill-icons/item_kill_21.svg', 'lord-icons/sub/item_herohead_21.png'):
            self.assertFalse(allowed_url(prefix + path), path)

    def test_nameplate_matches_only_a_unique_same_named_costume(self):
        chars = {'1029': {'name': 'Magik', 'skins': {'1029100': 'Amethyst Armor', '1029101': 'Unknown'}}}
        roster = [{'name': 'Magik', 'image': IMAGE, 'page': HERO}]
        def build(page):
            return build_entries(chars, roster, lambda _: page,
                                 lambda pages: [{'ids': ['1029100'], 'image': IMAGE} for _ in pages])
        entries = build(CARDS + nameplate('AMETHYST ARMOR') + nameplate('Immortal Magik', 'immortal-magik'))
        self.assertEqual(entries['1029100']['banner'], PLATES + 'img_amethyst-armor.webp')
        self.assertEqual(entries['1029100']['badge'], PLATES + 'img_icon_amethyst-armor.webp')
        self.assertNotIn('banner', entries['1029101'])  # Hero-portrait fallbacks never get one.
        self.assertEqual(entries['1029']['banner'], PLATES + 'img_immortal-magik.webp')
        for page in (CARDS,  # No nameplate in the bundle.
                     CARDS + nameplate('Amethyst Armour'),  # Close is not the same name.
                     CARDS + nameplate('AMETHYST ARMOR') + nameplate('Amethyst Armor', 'amethyst-armor-2'),
                     CARDS * 2 + nameplate('AMETHYST ARMOR')):  # Ambiguous on either side.
            self.assertNotIn('banner', build(page)['1029100'])

    def test_skin_banner_is_served_only_for_a_matched_nameplate(self):
        data = io.BytesIO()
        Image.new('RGBA', (16, 4)).save(data, format='WEBP')
        banner = PLATES + 'img_amethyst-armor.webp'
        entries = {'1029100': {'name': 'Amethyst Armor', 'kind': 'skin', 'image': IMAGE, 'banner': banner},
                   '1029101': {'name': 'Fallback', 'kind': 'skin', 'image': IMAGE, 'banner': banner, 'hero_fallback': True},
                   '1029102': {'name': 'No plate', 'kind': 'skin', 'image': IMAGE},
                   '1029103': {'name': 'Not a plate', 'kind': 'skin', 'image': IMAGE, 'banner': IMAGE}}
        with patch.dict(self.catalogue.data['entries'], entries), \
             patch('atelier.catalogue.fetch', return_value=(data.getvalue(), {})) as get:
            self.assertTrue(self.catalogue.banner('1029100').is_file())
            get.assert_called_once_with(banner)
            for key in ('1029', '1029101', '1029102', '1029103', '1029999', '../1029100'):
                self.assertIsNone(self.catalogue.banner(key))
            self.assertEqual(self.catalogue.describe('Characters/1029/1029100')['banner'], '/api/catalogue/banner/1029100')
            for path in ('Characters/1029', 'Characters/1029/1029101', 'Characters/1029/1029102', 'Characters/1029/1029999'):
                self.assertIsNone(self.catalogue.describe(path)['banner'])

    def test_hero_nameplate_uses_the_exact_name_on_its_own_page(self):
        chars = {'1067': {'name': 'Gorr', 'skins': {}}}
        roster = [{'name': 'Gorr The God Butcher', 'image': IMAGE,
                   'page': 'https://rivalskins.com/hero/gorr-the-god-butcher/'}]
        def build(extra):
            return build_entries(chars, roster, lambda _: CARDS + extra,
                                 lambda pages: [{'ids': [], 'image': IMAGE} for _ in pages])
        plate = nameplate('GORR THE GOD BUTCHER', 'gorr-the-god-butcher')
        entries = build(plate + nameplate('Immortal Gorr the God Butcher', 'immortal-gorr'))
        self.assertEqual(entries['1067']['banner'], PLATES + 'img_gorr-the-god-butcher.webp')
        self.catalogue.data['entries'].update(entries)
        self.assertEqual(self.catalogue.describe('Characters/1067')['banner'], '/api/catalogue/banner/1067')
        data = io.BytesIO(); Image.new('RGBA', (8,4)).save(data, 'WEBP')
        with patch('atelier.catalogue.fetch', return_value=(data.getvalue(), {})):
            self.assertTrue(self.catalogue.banner('1067').is_file())
        for extra in (plate + plate, nameplate('Gorr', 'gorr'), nameplate('Divine Destroyer', 'divine-destroyer')):
            self.assertNotIn('banner', build(extra)['1067'])
        rank_plate = build(nameplate('Immortal Gorr the God Butcher', 'immortal-gorr'))['1067']
        self.assertEqual(rank_plate['banner'], PLATES+'img_immortal-gorr.webp')
        self.assertEqual(rank_plate['banner_style'], 'immortal')
        self.assertEqual(entries['1067']['banner_style'], 'default')

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

    def test_hidpi_banner_returns_original_while_one_worker_sharpens_it(self):
        data = io.BytesIO()
        Image.new('RGBA', (8, 4), (10, 30, 180, 120)).save(data, 'WEBP', lossless=True)
        self.catalogue.data['entries']['1029100'].update(banner=PLATES+'img_amethyst-armor.webp',
                                                       badge=PLATES+'img_icon_amethyst-armor.webp')
        with patch('atelier.catalogue.fetch', return_value=(data.getvalue(), {})), \
             patch('atelier.catalogue.threading.Thread') as thread:
            path = self.catalogue.banner('1029100', sharp=True)
            self.assertTrue(path.is_file())
            self.assertEqual(self.catalogue.banner('1029100', sharp=True), path)
            self.assertEqual(len(self.catalogue.sharp_pending), 1)
            thread.assert_called_once()
            self.assertIsNotNone(self.catalogue.badge('1029100'))
        with patch('atelier.upscale.upscale', side_effect=lambda im: im.resize((32,16))):
            self.catalogue._sharpen_banners()
        sharp = self.catalogue.banner('1029100', sharp=True)
        self.assertTrue(sharp.name.endswith('-x4.webp'))
        with Image.open(sharp) as image:
            self.assertEqual(image.size, (32,16))
        sharp.unlink()
        with patch('atelier.catalogue.threading.Thread'), patch('atelier.upscale.upscale', side_effect=MemoryError):
            self.catalogue.banner('1029100', sharp=True)
            self.catalogue._sharpen_banners()
            self.assertEqual(self.catalogue.banner('1029100', sharp=True), path)
            self.assertFalse(self.catalogue.sharp_pending)

    def test_malformed_cache_uses_seed(self):
        self.catalogue.root.mkdir()
        (self.catalogue.root / 'catalogue.json').write_text('{broken')
        loaded = Catalogue(self.catalogue.root, self.seed)
        self.assertEqual(loaded.describe('Characters/1029')['name'], 'Magik')

    def test_updated_seed_replaces_older_matching_metadata_without_waiting_for_network(self):
        self.catalogue.root.mkdir()
        cache = self.catalogue.root / 'catalogue.json'
        old = {**self.catalogue.data, 'parser_version': PARSER_VERSION - 1}
        cache.write_text(json.dumps(old), encoding='utf-8')
        current = json.loads(self.seed.read_text())
        current['parser_version'] = PARSER_VERSION
        current['entries']['1029'].update(banner=PLATES + 'img_magik.webp',
                                          badge=PLATES + 'img_icon_magik.webp')
        self.seed.write_text(json.dumps(current), encoding='utf-8')
        with patch('atelier.catalogue.fetch', side_effect=TimeoutError('offline')) as get:
            loaded = Catalogue(self.catalogue.root, self.seed)
            self.assertEqual(loaded.describe('Characters/1029')['banner'], '/api/catalogue/banner/1029')
            get.assert_not_called()
            loaded.update()
            self.assertEqual(loaded.describe('Characters/1029')['banner'], '/api/catalogue/banner/1029')
        self.assertEqual(json.loads(cache.read_text()), old)
        current['entries']['1029']['name'] = 'Refreshed Magik'
        cache.write_text(json.dumps(current), encoding='utf-8')
        self.assertEqual(Catalogue(self.catalogue.root, self.seed).describe('Characters/1029')['name'],
                         'Refreshed Magik')
        self.seed.unlink()
        cache.write_text(json.dumps(old), encoding='utf-8')
        self.assertEqual(Catalogue(self.catalogue.root, self.seed).describe('Characters/1029')['name'], 'Magik')

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

    def test_release_seed_requires_current_parser_and_paired_nameplates(self):
        from scripts.update_catalogue_seed import validate_seed
        seed = Path(__file__).resolve().parents[1] / 'gui' / 'catalogue.json'
        data, count = validate_seed(seed)
        self.assertGreater(count, 0)
        for sid, entry in data['entries'].items():
            if entry.get('banner'):
                self.assertFalse(entry.get('hero_fallback'))
                if len(sid) == 4:
                    self.assertEqual(entry['kind'], 'hero')
                    self.assertTrue(entry['source'].startswith('https://rivalskins.com/hero/'))
                else:
                    self.assertEqual(entry['kind'], 'skin')
                    self.assertTrue(sid.startswith(entry['hero']))
                self.assertEqual(nameplate_url(entry['badge']), entry['banner'])
        invalid = self.root / 'invalid-seed.json'
        for content in ({**data, 'parser_version': 0}, {'schema': 1, 'parser_version': PARSER_VERSION, 'entries': {}}):
            invalid.write_text(json.dumps(content), encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_seed(invalid)

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
