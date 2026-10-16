"""Hero artwork refreshes use saved icons offline and discover additions at each launch."""
from collections import Counter
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from atelier.hero_artwork import HeroArtwork, PAGES, PREFIX, parse_assets


def page(kind, ids):
    folder, filename = {'avatar':('hero-icons-avatars', 'img_squarehead_{}0010_avatar'),
        'logo':('hero-logos', 'img_herologo_{}_logo'), 'story':('hero-story-images', 'img_herostory_{}01_hover')}[kind]
    return ''.join(f'<img src="{PREFIX}{folder}/{filename.format(cid)}.png">' for cid in ids).encode()


class Artwork(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = BytesIO()
        Image.new('RGBA', (136,136), (10,100,200,120)).save(raw, 'PNG')
        self.raw = raw.getvalue()

    def test_parser_uses_default_numeric_avatar_and_ignores_navigation_and_alternate_forms(self):
        html = f'''<img src="https://rivalskins.com/wp-content/uploads/marvel-assets/ui/heroes/avatar/magik_avatar.png">
          <img src="{PREFIX}hero-icons-avatars/magik_avatar.png">
          <img src="{PREFIX}hero-icons-avatars/img_squarehead_10290011_avatar.png">
          <img src="{PREFIX}hero-icons-avatars/img_squarehead_10290010_avatar.png">'''
        result = parse_assets(html, 'avatar', {'magik':'1029'})
        self.assertEqual(list(result), ['1029'])
        self.assertTrue(result['1029'].endswith('10290010_avatar.png'))

    def test_each_launch_checks_all_pages_and_downloads_only_new_artwork(self):
        ids, calls = ['1029'], []
        def fetch(url):
            calls.append(url)
            kind = next((k for k,v in PAGES.items() if v==url), None)
            return (page(kind, ids) if kind else self.raw), {}
        with patch('atelier.hero_artwork.fetch', side_effect=fetch):
            first = HeroArtwork(self.root)
            first.update({})
            self.assertIsNotNone(first.image('1029', 'avatar'))
            self.assertIsNotNone(first.image('1029', 'logo'))
            ids.append('1035')
            second = HeroArtwork(self.root)
            second.update({})
        self.assertEqual(Counter(calls)[PAGES['avatar']], 2)
        self.assertEqual(Counter(calls)[PAGES['logo']], 2)
        self.assertEqual(Counter(calls)[PAGES['story']], 2)
        self.assertEqual(len([url for url in calls if url not in PAGES.values()]), 6)
        self.assertEqual(second.status()['avatars'], 2)
        self.assertEqual(second.status()['logos'], 2)
        self.assertIsNotNone(second.image('1035','avatar'))
        self.assertIsNotNone(second.image('1035','story'))

    def test_story_matches_only_url_character_codes_and_prefers_first_story(self):
        urls=[f'{PREFIX}hero-story-images/img_herostory_105702_hover.png',
              f'{PREFIX}hero-story-images/img_herostory_105701_hover.png',
              f'{PREFIX}hero-story-images/img_herostory_102901_hover.png',
              f'{PREFIX}hero-story-images/Deadpool%20Story.png']
        for order in (urls,urls[::-1]):
            result=parse_assets(''.join(f'<img src="{url}" alt="Wrong hero">' for url in order),'story',{'deadpool story':'1111'})
            self.assertEqual(result,{'1057':urls[1],'1029':urls[2]})

    def test_hood_uses_published_portrait_instead_of_silhouette_in_either_page_order(self):
        urls=[f'{PREFIX}hero-icons-avatars/img_squarehead_10660010_avatar.png',
              f'{PREFIX}hero-icons-avatars/img_squarehead_10660011_avatar.png']
        for order in (urls,urls[::-1]):
            html=''.join(f'<img src="{url}">' for url in order)
            self.assertEqual(parse_assets(html,'avatar',{}),{'1066':urls[1]})
        self.assertEqual(parse_assets(f'<img src="{PREFIX}hero-icons-avatars/img_squarehead_10290011_avatar.png">','avatar',{}),{})

    def test_offline_launch_keeps_cached_icons_and_transparency(self):
        def fetch(url):
            kind = next((k for k,v in PAGES.items() if v==url), None)
            return (page(kind, ['1029']) if kind else self.raw), {}
        with patch('atelier.hero_artwork.fetch', side_effect=fetch):
            artwork = HeroArtwork(self.root)
            artwork.update({})
        offline = HeroArtwork(self.root)
        with patch('atelier.hero_artwork.fetch', side_effect=OSError('offline')):
            offline.update({})
            icon = offline.image('1029','avatar')
            self.assertIsNotNone(icon)
            with Image.open(icon) as image:
                self.assertEqual(image.getpixel((0,0))[3],120)
        self.assertIn('offline', offline.status()['error'])
        self.assertFalse(offline.status()['updating'])


if __name__ == '__main__':
    unittest.main()
