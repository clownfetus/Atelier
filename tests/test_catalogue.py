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
from atelier.catalogue import (Catalogue, PARSER_VERSION, NAMEPLATES_URL, allowed_url,
                               apply_hero_nameplates, build_entries, bundled_sprays, discover_characters, icon_url,
                               matched_sprays, nameplate_url, parse_hero_nameplates, parse_item, parse_cards, parse_ids)

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
        self.assertEqual(entries['1029100']['name'], 'Amethyst Armor')  # The verified card, not the list's typo.
        self.assertEqual(entries['1029101']['name'], 'Unknown')
        self.assertTrue(entries['1029101']['hero_fallback'])
        self.assertNotIn('1029000', entries)  # Never invent a default game ID.
        self.assertNotIn('1036100', entries)

    def test_card_name_only_names_a_single_verified_id(self):
        chars = {'1029': {'name': 'Magik', 'skins': {'1029100': 'AMETHEYST ARMOR', '1029101': 'Amethyst Armor (Alt.)'}}}
        roster = [{'name': 'Magik', 'image': IMAGE, 'page': HERO}]
        entries = build_entries(chars, roster, lambda _: CARDS,
                                lambda _: [{'ids': ['1029100', '1029101'], 'image': IMAGE}])
        self.assertEqual(entries['1029100']['name'], 'AMETHEYST ARMOR')  # One card can't name two IDs.
        self.assertEqual(entries['1029101']['name'], 'Amethyst Armor (Alt.)')
        one = lambda _: [{'ids': ['1029100'], 'image': IMAGE}]
        blank = CARDS.replace('alt="Amethyst Armor"', 'alt=" "')
        self.assertEqual(build_entries(chars, roster, lambda _: blank, one)['1029100']['name'], 'AMETHEYST ARMOR')
        chars['1029']['skins']['1029100'] = 'AMETHYST ARMOR'  # Same words: keep the list's spelling.
        self.assertEqual(build_entries(chars, roster, lambda _: CARDS, one)['1029100']['name'], 'AMETHYST ARMOR')

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

    def test_published_nameplates_match_explicit_default_and_fantastic_ids(self):
        def row(key, name, image, kind=0):
            return [1, key, name, 'slug', 2, kind, 53, -1, 2, 0, 0, image]
        data = {'p': '/wp-content/uploads/marvel-assets/', 't': ['nameplate', 'costume'], 'rows': [
            row('31066001', 'THE HOOD', 'items/nameplate/universal/img_icon_the-hood.png'),
            row('31066002', 'Fantastic The Hood', 'items/nameplate/53/img_icon_fantastic-the-hood.png'),
            row('31066208', 'Fantastic Beach Dad', 'items/nameplate/53/img_icon_beach-dad.png'),
            row('31036002', 'Fantastic Spider-Man', 'items/costume/23/img_icon_spider-man.png'),
            row('31029002', 'Fantastic Magik', 'items/nameplate/29/img_icon_magik.png', kind=1)]}
        text = 'const itemsData=(function(){var D=' + json.dumps(data) + ';throw Error("never execute");})();'
        plates = parse_hero_nameplates(text)
        self.assertEqual(set(plates), {'1066'})
        entry = {'name': 'The Hood', 'kind': 'hero', 'image': IMAGE,
                 'banner': PLATES+'img_immortal-the-hood.webp', 'banner_style': 'immortal'}
        apply_hero_nameplates(entry, '1066', plates)
        self.assertEqual(entry['banner'], 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/nameplate/universal/img_the-hood.webp')
        self.assertEqual(entry['banner_style'], 'default')
        self.assertEqual(entry['proficiency'], 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/nameplate/53/img_icon_fantastic-the-hood.webp')
        wrong = {'name': 'Spider-Man', 'kind': 'hero', 'image': IMAGE}
        apply_hero_nameplates(wrong, '1066', plates)
        self.assertNotIn('banner', wrong)
        self.assertNotIn('proficiency', wrong)
        data['rows'].append(data['rows'][0])
        duplicate = parse_hero_nameplates('var D='+json.dumps(data))
        self.assertNotIn('default', duplicate['1066'])
        for changed in ('<html>changed</html>', 'var D={"rows":[]}'):
            with self.assertRaises(ValueError): parse_hero_nameplates(changed)
        self.assertTrue(allowed_url(NAMEPLATES_URL))
        self.assertFalse(allowed_url(NAMEPLATES_URL.replace('item-data.js', 'other.js')))

    def test_common_material_folders_use_only_their_own_proficiency_reward(self):
        icon = PLATES+'img_icon_fantastic-magik.webp'
        self.catalogue.data['entries']['1029']['proficiency'] = icon
        for path in ('Characters/1029/1029CommonMaterial', 'Characters/1029/CommonMaterial', 'UI/1029CommonMaterial'):
            original = {'type': 'folder', 'name': path.rsplit('/', 1)[-1], 'rel_path': path}
            result = self.catalogue.decorate(original)
            self.assertEqual(result['thumbnail'], '/api/catalogue/proficiency/1029')
            self.assertFalse(result['hero_fallback'])
            self.assertEqual({key: result[key] for key in original}, original)
        for path in ('Characters/1029', 'UI/1029OtherMaterial'):
            result = self.catalogue.decorate({'type': 'folder', 'name': path.rsplit('/', 1)[-1], 'rel_path': path})
            self.assertEqual(result['thumbnail'], '/api/catalogue/thumbnail/1029')
        self.assertNotIn('thumbnail', self.catalogue.decorate({'type': 'folder', 'name': '1036CommonMaterial', 'rel_path': 'Characters/1029/1036CommonMaterial'}))
        raw = io.BytesIO(); Image.new('RGBA', (16, 16)).save(raw, 'WEBP')
        with patch('atelier.catalogue.fetch', return_value=(raw.getvalue(), {})) as get:
            self.assertTrue(self.catalogue.proficiency('1029').is_file())
            get.assert_called_once_with(icon)
            self.assertIsNone(self.catalogue.proficiency('1029100'))
            self.assertIsNone(self.catalogue.proficiency('1036'))

    def test_site_discovers_new_heroes_and_skins_without_a_reference_list_release(self):
        image = IMAGE.replace('/1/', '/23/')
        roster = [{'name': 'Spider-Man', 'image': image, 'page': HERO}]
        costumes = [{'id': '1036100', 'name': 'Future suit', 'image': image, 'site_hero': '23'}]
        result = discover_characters({}, roster, costumes)
        self.assertEqual(result['1036'], {'name': 'Spider-Man', 'skins': {'1036100': 'Future suit'}})
        existing = {'1036': {'name': 'Spider-Man', 'skins': {'1036001': 'Original suit'}}}
        self.assertEqual(set(discover_characters(existing, roster, costumes)['1036']['skins']), {'1036001', '1036100'})
        self.assertNotIn('1036100', existing['1036']['skins'])
        conflicting = costumes + [{**costumes[0], 'id': '1029100'}]
        self.assertEqual(discover_characters({}, roster, conflicting), {})
        self.assertEqual(discover_characters({}, roster + roster, costumes), {})

    def test_sprays_require_unambiguous_published_bundle_membership(self):
        costume = 'items/costume/5/img_icon_yggroot.png'
        spray = 'items/spray/5/img_icon_yggroot.png'
        def item(key, kind, image):
            return [1, key, 'Different names are fine', 'slug', 2, kind, 5, -1, 0, 2, 0, image, 0, 0, 0]
        bundle = item('bundle-id', 2, 0)
        bundle[14] = [[costume, 0], [spray, 1]]
        data = {'p': '/wp-content/uploads/marvel-assets/', 't': ['costume', 'spray', 'bundle'],
                'rows': [item('1027301', 0, costume), item('41027203', 1, spray), bundle]}
        parse = lambda: bundled_sprays('var D='+json.dumps(data))
        url = 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/spray/5/img_yggroot.webp'
        self.assertEqual(parse(), {'1027301': url})
        self.catalogue.data['entries']['1027301'] = {'name': 'Yggroot', 'kind': 'skin', 'image': IMAGE, 'spray': url}
        self.assertEqual(self.catalogue.describe('Characters/1027/1027301')['spray'], '/api/catalogue/spray/1027301')
        raw = io.BytesIO(); Image.new('RGBA', (32, 32)).save(raw, 'WEBP')
        with patch('atelier.catalogue.fetch', return_value=(raw.getvalue(), {})) as get:
            self.assertTrue(self.catalogue.spray('1027301').is_file())
            get.assert_called_once_with(url)
            self.assertIsNone(self.catalogue.spray('1027'))
        other = 'items/spray/23/img_icon_yggroot.png'
        data['rows'][1][11] = other; bundle[14][1][0] = other
        self.assertEqual(parse(), {})  # A same-named spray belonging to a different hero.
        data['rows'][1][11] = spray; bundle[14][1][0] = spray
        extra = 'items/costume/5/img_icon_other.png'
        data['rows'].append(item('1027302', 0, extra)); bundle[14].append([extra, 0])
        self.assertEqual(parse(), {})  # Multi-costume bundles cannot establish one skin's spray.

    def test_non_bundle_spray_matches_only_one_same_hero_and_skin_name(self):
        def item(key, kind, hero, name, file):
            return [1, key, name, 'slug', 2, kind, hero, -1, 0, 2, 0, file, 0, 0, 0]
        data = {'p': '/wp-content/uploads/marvel-assets/', 't': ['costume', 'spray', 'bundle'], 'rows': [
            item('1024503', 0, 7, 'THE REDEEMED', 'items/costume/7/img_icon_the-redeemed.png'),
            item('41024215', 1, 7, 'The Redeemed', 'items/spray/7/img_icon_the-redeemed.png'),
            item('1036503', 0, 23, 'The Redeemed', 'items/costume/23/img_icon_the-redeemed.png')]}
        parse = lambda: matched_sprays('var D='+json.dumps(data))
        self.assertEqual(parse(), {'1024503': 'https://rivalskins.com/wp-content/uploads/marvel-assets/items/spray/7/img_the-redeemed.webp'})
        data['rows'].append(item('1024504', 0, 7, 'The Redeemed', 'items/costume/7/img_icon_duplicate.png'))
        self.assertEqual(parse(), {})
        data['rows'].pop()
        data['rows'][1][2] = 'Redeemed Queen'
        self.assertEqual(parse(), {})

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

    def test_only_exact_identity_folder_paths(self):
        for path in ('Characters/1029/1029100/Textures', 'Characters/1036/1029100', '../1029', 'UI/Com'):
            self.assertIsNone(self.catalogue.describe(path))
        self.assertEqual(self.catalogue.describe('UI/1029')['name'], 'Magik')
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
        published = [entry for cid, entry in data['entries'].items() if len(cid) == 4 and cid.startswith('10') and entry.get('image')]
        self.assertTrue(all(entry.get('proficiency') and entry.get('banner_style') == 'default' for entry in published))
        self.assertTrue(data['entries']['1036']['proficiency'].endswith('/23/img_icon_fantastic-spider-man.webp'))
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
        plates = {cid: {} for cid in chars}
        costumes = [{'id': cid+'100', 'site_hero': '1', 'name': char['name'], 'image': IMAGE} for cid, char in chars.items()]
        self.catalogue.data.update(parser_version=PARSER_VERSION,
                                   content_hash=hashlib.sha256(json.dumps([chars, roster, plates, costumes, {}], sort_keys=True).encode()).hexdigest(), refreshed_at=1000)
        with patch('atelier.catalogue.time.time', return_value=1001), \
             patch('atelier.catalogue.fetch', return_value=(b'source', {})) as get, \
             patch('atelier.catalogue.parse_ids', return_value=chars), \
             patch('atelier.catalogue.parse_cards', return_value=roster), \
             patch('atelier.catalogue.parse_hero_nameplates', return_value=plates), \
             patch('atelier.catalogue.published_costumes', return_value=costumes), \
             patch('atelier.catalogue.matched_sprays', return_value={}), \
             patch('atelier.catalogue.build_entries') as build:
            self.catalogue.update()
        self.assertEqual(get.call_count, 3)
        build.assert_not_called()
        self.assertEqual(self.catalogue.status()['checked_at'], 1001)
        costumes.append({**costumes[0], 'id': costumes[0]['id'][:4]+'999', 'name': 'New website skin'})
        with patch('atelier.catalogue.time.time', return_value=1002), \
             patch('atelier.catalogue.fetch', return_value=(b'source', {})), \
             patch('atelier.catalogue.parse_ids', return_value=chars), \
             patch('atelier.catalogue.parse_cards', return_value=roster), \
             patch('atelier.catalogue.parse_hero_nameplates', return_value=plates), \
             patch('atelier.catalogue.published_costumes', return_value=costumes), \
             patch('atelier.catalogue.matched_sprays', return_value={}), \
             patch('atelier.catalogue.build_entries', return_value={cid: {'name': char['name'], 'image': IMAGE} for cid, char in chars.items()}) as build:
            self.catalogue.update()
        build.assert_called_once()  # Website additions refresh immediately, even within the daily cache window.
        self.assertIsNone(self.catalogue.status()['error'])


if __name__ == '__main__':
    unittest.main()
