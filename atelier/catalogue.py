"""Optional, cached browsing artwork. Never participates in asset import or mod export.

Names come from donutman07; costume IDs and images are verified on RivalSkins, whose
card name replaces a different listed name when its page verifies exactly one game ID.
Missing costumes use a labelled hero portrait, never a guessed skin image.
Network work is explicit (start_update/thumbnail), bounded and independent of projects.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image
from atelier import config as C
from atelier.storage import atomic_json
from atelier.identity import resolve_ids, identity_tokens

IDS_URL = 'https://raw.githubusercontent.com/donutman07/MarvelRivalsCharacterIDs/main/MarvelRivalsCharacterIDs.md'
HEROES_URL = 'https://rivalskins.com/heroes/'
NAMEPLATES_URL = 'https://rivalskins.com/wp-content/themes/astra-child/js/generated/item-data.js'
DAY = 86400
PARSER_VERSION = 7
ALIASES = {'punisher': 'thepunisher', 'mrfantastic': 'misterfantastic',
           'jeffthelandshark': 'jeffthelandshark', 'ironfistlinlie': 'ironfist',
           'gorr': 'gorrthegodbutcher'}


def normalized(name):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', name).casefold())


def parse_ids(text):
    """Tolerate missing trailing pipes; never replace current IDs with '(Old)' rows."""
    chars, current = {}, None
    for line in text.splitlines():
        if not line.lstrip().startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) < 4:
            continue
        cid, name, sid, skin = cells[:4]
        if re.fullmatch(r'\d{4}', cid):
            current = None
            if name and '(old)' not in name.lower() and cid not in chars:
                chars[cid] = {'name': name, 'skins': {}}
                current = cid
        if current and re.fullmatch(current + r'\d{3}', sid) and skin:
            chars[current]['skins'][sid] = skin
    return chars


def icon_url(image):
    """img_<name>.webp -> img_icon_<name>.webp in the same costume folder, or None."""
    if not isinstance(image, str):
        return None
    match = re.fullmatch(r'(.*/items/costume/\d+/img_)(?!icon_)([^/]+\.webp)', image)
    return match[1] + 'icon_' + match[2] if match else None


def nameplate_url(icon):
    """A nameplate card's img_icon_<name>.webp -> its 848x192 banner img_<name>.webp, or None."""
    if not isinstance(icon, str):
        return None
    match = re.fullmatch(r'(.*/items/nameplate/(?:\d+|universal)/img_)icon_([^/]+\.webp)', icon)
    return match[1] + match[2] if match and allowed_url(match[1] + match[2]) else None


def allowed_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != 'https' or parsed.username or parsed.password or port:
        return False
    return (parsed.netloc == 'rivalskins.com' and (
        url == NAMEPLATES_URL
        or parsed.path in ('/heroes/', '/assets/hero-logos/', '/assets/hero-icons-avatars/', '/assets/hero-story-images/',
                        '/assets/lord-icons/', '/assets/kill-icons/', '/assets/hero-prestige-images/', '/assets/hero-signatures/')
        or parsed.path.startswith(('/hero/', '/item/', '/wp-content/uploads/marvel-assets/items/costume/',
                                   '/wp-content/uploads/marvel-assets/items/nameplate/',
                                   '/wp-content/uploads/marvel-assets/items/spray/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-logos/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-icons-avatars/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-story-images/'))
        or bool(re.fullmatch(r'/wp-content/uploads/marvel-assets/assets/hero-prestige-images/'
                             r'img_prestige_10\d{2}00(?:10|13)_hero\.(?:png|webp)', parsed.path))
        or bool(re.fullmatch(r'/wp-content/uploads/marvel-assets/assets/hero-signatures/'
                             r'img_story_herosign_10\d{2}_sign\.(?:png|webp)', parsed.path))
        or bool(re.fullmatch(r'/wp-content/uploads/marvel-assets/assets/(?:'
                             r'lord-icons/(?:item_herohead_\d+|img_squarehead_\d+_avatar|'
                             r'(?:[A-Za-z0-9_&-]|%20|%27)+%20Deluxe%20Avatar(?:%20\d+)?)|'
                             r'kill-icons/(?:item_kill_\d+|(?:[A-Za-z0-9_&-]|%20|%27)+'
                             r'%20Deluxe%20KO%20Prompt%20[12]))\.(?:png|webp)', parsed.path))
    )) or url == IDS_URL


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError('Unexpected catalogue redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, headers=None, limit=8 * 1024 * 1024):
    if not allowed_url(url):
        raise ValueError('Unexpected catalogue source')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Atelier/1.0 (optional browsing artwork cache)', **(headers or {})})
    with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=8) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Catalogue response too large')
        return data, dict(response.headers)


class Cards(HTMLParser):
    """Read only roster portraits / one kind of hero-page card (costume or nameplate), ignoring
    ads and other cosmetics."""
    def __init__(self, roster=False, kind='costume'):
        super().__init__(convert_charrefs=True)
        self.roster, self.kind, self.items, self.card, self.webp = roster, kind, [], None, None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'a':
            href = attrs.get('href', '').strip()
            self.card = {'page': href} if (
                self.roster and href.startswith('https://rivalskins.com/hero/') or
                not self.roster and attrs.get('data-type') == self.kind) else None
            self.webp = None
        elif self.card is not None and tag == 'source' and attrs.get('type') == 'image/webp':
            self.webp = attrs.get('srcset', '').split(' ')[0]
        elif self.card is not None and tag == 'img':
            image = self.webp or attrs.get('src', '')
            if f'/items/{"costume" if self.roster else self.kind}/' in image and allowed_url(image):
                self.items.append({**self.card, 'name': attrs.get('alt', ''), 'image': image})
                self.card = None

    def handle_endtag(self, tag):
        if tag == 'a':
            self.card = None


def parse_cards(text, roster=False, kind='costume'):
    parser = Cards(roster, kind)
    parser.feed(text)
    return parser.items


class ItemArtwork(HTMLParser):
    """Use the costume stage's supplied WebP and the page's copyable numeric ID."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.image, self.stage_depth = [], None, 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'div' and (self.stage_depth or 'rs-stage' in attrs.get('class', '').split()):
            self.stage_depth += 1
        if self.stage_depth and tag == 'source' and attrs.get('type') == 'image/webp' and not self.image:
            url = attrs.get('srcset', '').split(' ')[0]
            if '/items/costume/' in url and allowed_url(url):
                self.image = url
        value = attrs.get('data-copy', '')
        if re.fullmatch(r'\d{7}', value):
            self.ids.append(value)

    def handle_endtag(self, tag):
        if tag == 'div' and self.stage_depth:
            self.stage_depth -= 1


def parse_item(text):
    parser = ItemArtwork()
    parser.feed(text)
    if not parser.image:
        raise ValueError('Costume artwork format changed')
    return {'ids': sorted(set(parser.ids)), 'image': parser.image}


def parse_published_catalogue(text):
    """Read the site's published JSON wire data without executing JavaScript."""
    marker = re.search(r'\bvar D=', text)
    if not marker:
        raise ValueError('Published catalogue format changed')
    data, _ = json.JSONDecoder().raw_decode(text, marker.end())
    if (not isinstance(data, dict) or data.get('p') != '/wp-content/uploads/marvel-assets/'
            or not isinstance(data.get('t'), list) or not isinstance(data.get('rows'), list)):
        raise ValueError('Published catalogue format changed')
    return data


def parse_hero_nameplates(text):
    """Default and Fantastic plates have explicit game IDs 3<hero>001/002.

    Hero pages omit universal plates; catalogue HTML shows only its newest items.
    """
    data = parse_published_catalogue(text)
    candidates = {}
    for row in data['rows']:
        if (not isinstance(row, list) or len(row) < 12 or not isinstance(row[1], str)
                or not isinstance(row[2], str) or not isinstance(row[5], int)
                or not 0 <= row[5] < len(data['t']) or data['t'][row[5]] != 'nameplate'
                or not isinstance(row[11], str)):
            continue
        match = re.fullmatch(r'3(10\d{2})(001|002)', row[1])
        image = 'https://rivalskins.com' + data['p'] + re.sub(r'\.png$', '.webp', row[11])
        if not match or not nameplate_url(image):
            continue
        kind = 'default' if match[2] == '001' else 'fantastic'
        candidates.setdefault((match[1], kind), []).append({'name': row[2], 'image': image})
    result = {}
    for (cid, kind), plates in candidates.items():
        if len(plates) == 1:
            result.setdefault(cid, {})[kind] = plates[0]
    return result


def published_costumes(text):
    data = parse_published_catalogue(text)
    costumes = []
    for row in data['rows']:
        if (not isinstance(row, list) or len(row) < 14 or not isinstance(row[1], str)
                or not re.fullmatch(r'10\d{5}', row[1]) or not isinstance(row[2], str)
                or not isinstance(row[5], int) or not 0 <= row[5] < len(data['t'])
                or data['t'][row[5]] != 'costume' or not isinstance(row[13], str)):
            continue
        image = 'https://rivalskins.com' + data['p'] + re.sub(r'\.png$', '.webp', row[13])
        folder = re.search(r'/items/costume/(\d+)/', image)
        if folder and allowed_url(image) and icon_url(image):
            costumes.append({'id': row[1], 'name': row[2], 'image': image, 'site_hero': folder[1]})
    return costumes


def discover_characters(chars, roster, costumes):
    """New site heroes need an explicit costume game ID and an exact roster folder."""
    chars = {cid: {**char, 'skins': dict(char['skins'])} for cid, char in chars.items()}
    heroes, owners = {}, {}
    for hero in roster:
        folder = re.search(r'/items/costume/(\d+)/', hero['image'])
        if folder:
            heroes.setdefault(folder[1], []).append(hero)
    for costume in costumes:
        owners.setdefault(costume['site_hero'], set()).add(costume['id'][:4])
    for costume in costumes:
        site = costume['site_hero']
        if len(heroes.get(site, [])) != 1 or len(owners[site]) != 1:
            continue
        cid, hero = costume['id'][:4], heroes[site][0]
        if cid in chars:
            name = normalized(chars[cid]['name'])
            if ALIASES.get(name, name) != normalized(hero['name']):
                continue
        char = chars.setdefault(cid, {'name': hero['name'], 'skins': {}})
        char['skins'].setdefault(costume['id'], costume['name'])
    return chars


def bundled_sprays(text):
    """Match one costume and one spray listed together in a published bundle."""
    data = parse_published_catalogue(text)
    costumes, sprays, bundles = {}, {}, []
    prefix = 'https://rivalskins.com' + data['p']
    for row in data['rows']:
        if not isinstance(row, list) or len(row) < 15 or not isinstance(row[5], int) or not 0 <= row[5] < len(data['t']):
            continue
        kind = data['t'][row[5]]
        if kind == 'bundle' and isinstance(row[14], list):
            bundles.append(row[14])
        elif isinstance(row[11], str):
            if kind == 'costume' and isinstance(row[1], str) and re.fullmatch(r'10\d{5}', row[1]):
                costumes.setdefault(row[11], set()).add(row[1])
            elif kind == 'spray':
                image = row[13] if isinstance(row[13], str) else row[11].replace('/img_icon_', '/img_', 1)
                url = prefix + re.sub(r'\.png$', '.webp', image)
                if allowed_url(url) and re.fullmatch(r'.*/items/spray/\d+/img_(?!icon_)[^/]+\.webp', url):
                    sprays.setdefault(row[11], set()).add(url)
    candidates = {}
    for bundle in bundles:
        icons = [part[0] for part in bundle if isinstance(part, list) and len(part) == 2 and isinstance(part[0], str)]
        outfits = [icon for icon in icons if icon in costumes]
        art = [icon for icon in icons if icon in sprays]
        if len(outfits) != 1 or len(art) != 1 or len(costumes[outfits[0]]) != 1 or len(sprays[art[0]]) != 1:
            continue
        # A matching bundle must also publish both items under the same hero folder.
        if outfits[0].split('/')[2] != art[0].split('/')[2]:
            continue
        sid = next(iter(costumes[outfits[0]]))
        candidates.setdefault(sid, set()).update(sprays[art[0]])
    return {sid: next(iter(urls)) for sid, urls in candidates.items() if len(urls) == 1}


def matched_sprays(text):
    """Use bundles first, then a unique exact cosmetic name within the same hero."""
    result = bundled_sprays(text)
    data = parse_published_catalogue(text)
    costumes, sprays = {}, {}
    prefix = 'https://rivalskins.com' + data['p']
    for row in data['rows']:
        if (not isinstance(row, list) or len(row) < 14 or not isinstance(row[2], str)
                or not isinstance(row[5], int) or not 0 <= row[5] < len(data['t'])
                or not isinstance(row[11], str)):
            continue
        kind = data['t'][row[5]]
        folder = re.fullmatch(r'items/(costume|spray)/(\d+)/img_icon_[^/]+\.png', row[11])
        if not folder or folder[1] != kind or folder[2] != str(row[6]):
            continue
        key = (folder[2], normalized(row[2]))
        if not key[1]:
            continue
        if kind == 'costume' and isinstance(row[1], str) and re.fullmatch(r'10\d{5}', row[1]):
            costumes.setdefault(key, set()).add(row[1])
        elif kind == 'spray':
            image = row[13] if isinstance(row[13], str) else row[11].replace('/img_icon_', '/img_', 1)
            url = prefix + re.sub(r'\.png$', '.webp', image)
            if allowed_url(url) and re.fullmatch(r'.*/items/spray/'+folder[2]+r'/img_(?!icon_)[^/]+\.webp', url):
                sprays.setdefault(key, set()).add(url)
    for key, ids in costumes.items():
        urls = sprays.get(key, set())
        if len(ids) == len(urls) == 1:
            result.setdefault(next(iter(ids)), next(iter(urls)))
    return result


def apply_hero_nameplates(entry, cid, plates):
    """Require both the plate's explicit hero ID and exact hero name."""
    if entry.get('kind') != 'hero' or not cid.startswith('10') or not entry.get('image'):
        return
    name = normalized(entry['name'])
    name = ALIASES.get(name, name)
    for kind, plate in plates.get(cid, {}).items():
        expected = name if kind == 'default' else 'fantastic' + name
        if normalized(plate['name']) != expected:
            continue
        if kind == 'default':
            entry.update(banner=nameplate_url(plate['image']), badge=plate['image'], banner_style='default')
        elif kind == 'fantastic':
            entry['proficiency'] = plate['image']


def build_entries(chars, roster, load_page, load_items, hero_nameplates=None, skin_sprays=None):
    heroes = {normalized(hero['name']): hero for hero in roster}
    entries = {}
    for cid, char in chars.items():
        key = normalized(char['name'])
        # NPCs with a playable hero's name aren't the same model/costume.
        hero = heroes.get(ALIASES.get(key, key)) if cid.startswith('10') else None
        entry = {'name': char['name'], 'kind': 'hero', 'image': hero['image'] if hero else None,
                 'source': hero['page'] if hero else IDS_URL}
        entries[cid] = entry
        page = load_page(hero['page']) if hero else ''
        costumes = parse_cards(page)
        if hero and not costumes:
            raise ValueError(f'No costume cards found for {char["name"]}; retaining previous catalogue')
        plates = {}
        for plate in parse_cards(page, kind='nameplate'):
            plates.setdefault(normalized(plate['name']), []).append(plate)
        if hero:
            # A hero's named progression plate is safe when no plain plate is published.
            # A costume's unrelated plate is never borrowed for the hero header.
            for plate_name, style in ((hero['name'], 'default'), ('Immortal '+hero['name'], 'immortal')):
                hero_plates = plates.get(normalized(plate_name), [])
                if not hero_plates:
                    continue
                if len(hero_plates) == 1:
                    banner = nameplate_url(hero_plates[0]['image'])
                    if banner:
                        entry.update(banner=banner, badge=hero_plates[0]['image'], banner_style=style)
                break
            apply_hero_nameplates(entry, cid, hero_nameplates or {})
        for sid, name in char['skins'].items():
            entries[sid] = {'name': name, 'kind': 'skin', 'hero': cid,
                            'image': entry['image'], 'source': entry['source'], 'hero_fallback': True}
        for costume, artwork in zip(costumes, load_items([c['page'] for c in costumes])):
            name = normalized(costume['name'])
            same_name = [c for c in costumes if normalized(c['name']) == name]
            skin_ids = artwork['ids']
            # Some recolor pages omit game IDs. Accept only a unique exact name
            # within this hero, never a fuzzy match or a conflicting supplied ID.
            if not skin_ids:
                matches = [sid for sid, skin in char['skins'].items() if normalized(skin) == name]
                skin_ids = matches if len(matches) == len(same_name) == 1 else []
            # A bundle's nameplate shares its costume's name on the same hero page. Pair them only
            # when that name is unique on both sides; anything else uses the hero's banner fallback.
            plate = plates.get(name, []) if name else []
            matched = plate[0] if len(plate) == len(same_name) == 1 else None
            banner = nameplate_url(matched['image']) if matched else None
            # Never cross hero boundaries, including transformation/NPC IDs.
            own_ids = [sid for sid in skin_ids if sid.startswith(cid)]
            # A card whose page verifies exactly one game ID names that costume. donutman07's list
            # carries typos and stale names (Cyclops' Shadowed Gaze is listed as SHADOWED NEMESIS).
            verified = costume['name'].strip() if artwork['ids'] and len(own_ids) == 1 else ''
            for sid in own_ids:
                name = char['skins'].get(sid, costume['name'])
                if verified and normalized(verified) != normalized(name):
                    name = verified  # The same words in another case or punctuation keep the list's spelling.
                entries[sid] = {'name': name, 'kind': 'skin', 'hero': cid,
                                'image': artwork['image'], 'source': costume['page'], 'hero_fallback': False,
                                'match': 'id' if artwork['ids'] else 'name',
                                **({'banner': banner, 'badge': matched['image']} if banner else {})}
    for sid, url in (skin_sprays or {}).items():
        if sid in entries and not entries[sid].get('hero_fallback'):
            entries[sid]['spray'] = url
    return entries


class Catalogue:
    def __init__(self, root, seed):
        self.root, self.seed = Path(root), Path(seed)
        self.lock, self.download_slots = threading.Lock(), threading.BoundedSemaphore(3)
        self.started = False
        self.failed_images = {}
        self.sharp_pending, self.sharp_failed, self.sharp_running = [], {}, False
        cached, bundled = self._read(self.root / 'catalogue.json'), self._read(self.seed)
        # Updated matching rules ship with verified metadata; use it immediately even offline.
        if (bundled and bundled.get('parser_version') == PARSER_VERSION
                and (not cached or cached.get('parser_version') != PARSER_VERSION)):
            self.data = bundled
        else:
            self.data = cached or bundled or {'entries': {}}
        self.state = {'updating': False, 'error': None, 'checked_at': self.data.get('checked_at')}

    @staticmethod
    def _read(path):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('schema') != 1 or not isinstance(data.get('entries'), dict):
                return None
            if not all(re.fullmatch(r'\d{4}(?:\d{3})?', key) and isinstance(entry, dict)
                       and isinstance(entry.get('name'), str)
                       and (entry.get('image') is None or allowed_url(entry['image']))
                       and (entry.get('banner') is None or allowed_url(entry['banner']))
                       and (entry.get('badge') is None or allowed_url(entry['badge']))
                       and (entry.get('proficiency') is None or nameplate_url(entry['proficiency']))
                       and (entry.get('spray') is None or allowed_url(entry['spray']))
                       for key, entry in data['entries'].items()):
                return None
            return data
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def status(self):
        with self.lock:
            entries = self.data.get('entries', {})
            return {**self.state, 'entries': len(entries), 'portraits': sum(bool(e.get('image')) for e in entries.values())}

    def describe(self, path):
        entries = self.data.get('entries', {})
        ids = resolve_ids(path, entries, leaf_only=True)
        if not ids:
            return None
        return self._describe_id(ids['skin_id'] or ids['char_id'], entries)

    def _describe_id(self, value, entries=None):
        entries = self.data.get('entries', {}) if entries is None else entries
        cid, sid = value[:4], value if len(value) == 7 else None
        key = sid or cid
        entry = entries.get(key)
        if not entry and sid:
            hero = entries.get(cid)
            if hero:
                entry = {**hero, 'name': None, 'hero_fallback': True}
                key = cid
        if not entry:
            return None
        return {'name': entry.get('name'), 'thumbnail': f'/api/catalogue/thumbnail/{key}' if entry.get('image') else None,
                'hero_fallback': entry.get('hero_fallback', False),
                'banner': f'/api/catalogue/banner/{key}' if entry.get('banner') and not entry.get('hero_fallback') else None,
                'spray': f'/api/catalogue/spray/{key}' if sid and entry.get('spray') and not entry.get('hero_fallback') else None,
                'badge': f'/api/catalogue/badge/{key}' if sid and entry.get('badge') and not entry.get('hero_fallback') else None}

    def identity(self, path):
        entries = self.data.get('entries', {})
        ids = resolve_ids(path, entries)
        if not ids:
            return None
        cid, sid = ids['char_id'], ids['skin_id']
        hero, skin = self._describe_id(cid, entries), self._describe_id(sid, entries) if sid else None
        return {**ids, 'char_name': (hero or {}).get('name') or '',
                'skin_name': (skin or {}).get('name') or '',
                'hero': hero, 'skin': skin}

    def identity_entries(self):
        """Local display metadata for all known IDs, including entries without artwork."""
        entries = self.data.get('entries', {})
        return {key: {**self._describe_id(key, entries), 'id': key,
                      'kind': entry.get('kind', 'hero' if len(key) == 4 else 'skin'),
                      'hero': key[:4]}
                for key, entry in entries.items()}

    def decorate(self, item):
        """Attach presentation metadata while preserving every original name and path."""
        path = item.get('game_rel') or item.get('rel_path') or item.get('path') or ''
        identity = self.identity(path)
        if not identity:
            return item
        result = dict(item)
        for key in ('char_id', 'skin_id', 'char_name', 'skin_name'):
            if identity.get(key):
                result[key] = identity[key]
        result['identity_label'] = ' · '.join(filter(None, (identity['char_name'], identity['skin_name'])))
        if item.get('type') != 'folder':
            if resolve_ids(path.rpartition('/')[0], self.data.get('entries', {})) is None:
                result['context_label'] = result['identity_label']
            # These UI portraits duplicate the catalogue art. Do not decode all
            # of their game textures just to populate the library grid.
            skin = identity['skin']
            portrait_path = path.replace('\\', '/').removeprefix('/Game/Marvel/')
            match = re.fullmatch(r'(?:Marvel_LQ/)?UI/Textures/Show/Skin/img_skin_(10\d{5})(?:\.uasset)?',
                                 portrait_path, re.IGNORECASE)
            if (item.get('file_type') == 'texture' and not item.get('imported')
                    and match and match[1] == identity['skin_id'] and skin
                    and skin['thumbnail'] and not skin['hero_fallback']):
                result['thumbnail'] = skin['thumbnail']
            return result
        portrait = self.describe(path)
        if not portrait:
            leaf = path.rsplit('/', 1)[-1]
            if not resolve_ids(leaf, self.data.get('entries', {})) and normalized(leaf) != 'commonmaterial':
                return result
            portrait = identity['skin'] or identity['hero']
            if not portrait: return result
            label = leaf
            for token in identity_tokens(leaf):
                if token in (identity['char_id'], identity['skin_id']): label = label.replace(token, '')
            label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', label).strip('_ -') or leaf
            result.update(label=result['identity_label']+' — '+leaf, display_name=label,
                          context_label=result['identity_label'], thumbnail=portrait['thumbnail'],
                          hero_fallback=portrait['hero_fallback'])
            cid = identity['char_id']
            if (normalized(leaf) in ('commonmaterial', cid + 'commonmaterial')
                    and self.data['entries'].get(cid, {}).get('proficiency')):
                result['thumbnail'] = f'/api/catalogue/proficiency/{cid}'
                result['hero_fallback'] = False
            return result
        key = path.rstrip('/').rsplit('/', 1)[-1]
        name = portrait.get('name') or (f'Skin {key[-3:]}' if len(key) == 7 else None)
        if name:
            label_id = key[-3:] if len(key) == 7 and identity['hero_path'] else key
            context = identity['char_name'] if len(key) == 7 and not identity['hero_path'] else ''
            result['label'] = ' — '.join(filter(None, (label_id, context, name)))
            result['display_name'] = name
            result['context_label'] = context
        result.update(thumbnail=portrait['thumbnail'], hero_fallback=portrait['hero_fallback'])
        if portrait.get('banner'):
            result['banner'] = portrait['banner']
        return result

    def start_update(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            self.state.update(updating=True, error=None)
        threading.Thread(target=self.update, name='atelier-catalogue', daemon=True).start()

    def update(self):
        try:
            md, _ = fetch(IDS_URL)
            roster_html, _ = fetch(HEROES_URL)
            nameplates, _ = fetch(NAMEPLATES_URL)
            published = nameplates.decode('utf-8')
            hero_nameplates = parse_hero_nameplates(published)
            costumes = published_costumes(published)
            skin_sprays = matched_sprays(published)
            chars = parse_ids(md.decode('utf-8'))
            roster = parse_cards(roster_html.decode('utf-8'), roster=True)
            if len(chars) < 20 or len(roster) < 20 or len(hero_nameplates) < 20 or len(costumes) < 20:
                raise ValueError('Catalogue sources changed format; keeping the previous catalogue')
            chars = discover_characters(chars, roster, costumes)
            # Compare useful content, not ad timestamps / scripts embedded in the page.
            content_hash = hashlib.sha256(json.dumps([chars, roster, hero_nameplates, costumes, skin_sprays], sort_keys=True).encode()).hexdigest()
            now = time.time()
            previous = self.data
            if (previous.get('parser_version') != PARSER_VERSION
                    or content_hash != previous.get('content_hash')
                    or now - previous.get('refreshed_at', 0) >= DAY):
                with ThreadPoolExecutor(max_workers=3, thread_name_prefix='catalogue-page') as pool:
                    entries = build_entries(chars, roster, lambda url: fetch(url)[0].decode('utf-8'),
                                            lambda pages: list(pool.map(self.item_artwork, pages)), hero_nameplates, skin_sprays)
                if sum(bool(e.get('image')) for e in entries.values()) < 20:
                    raise ValueError('No usable portraits; keeping the previous catalogue')
                data = {'schema': 1, 'parser_version': PARSER_VERSION,
                        'entries': entries, 'refreshed_at': now, 'content_hash': content_hash,
                        'sources': [IDS_URL, HEROES_URL, NAMEPLATES_URL],
                        'source_digest': hashlib.sha256(md + roster_html + nameplates).hexdigest()}
            else:
                data = dict(previous)
            data['checked_at'] = now
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_json(str(self.root / 'catalogue.json'), data)
            with self.lock:
                self.data = data
                self.state.update(checked_at=now, error=None)
        except Exception as exc:
            with self.lock:
                self.state['error'] = str(exc)
        finally:
            with self.lock:
                self.state['updating'] = False

    def item_artwork(self, url):
        path = self.root / 'items' / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        try:
            cached = json.loads(path.read_text(encoding='utf-8'))
            if (time.time() - cached['checked_at'] < 7 * DAY and allowed_url(cached['image'])
                    and all(re.fullmatch(r'\d{7}', sid) for sid in cached['ids'])):
                return cached
        except (OSError, ValueError, KeyError, TypeError):
            pass
        artwork = {**parse_item(fetch(url)[0].decode('utf-8')), 'checked_at': time.time()}
        atomic_json(str(path), artwork)
        return artwork

    def thumbnail(self, key):
        if not re.fullmatch(r'\d{4}(?:\d{3})?', key):
            return None
        return self._cached(self.data.get('entries', {}).get(key, {}).get('image'))

    def icon(self, key):
        """A costume's square head-and-shoulders icon, published beside its art as img_icon_<name>.
        Hero-portrait fallbacks have no costume of their own, so they get none."""
        if not re.fullmatch(r'\d{7}', key):
            return None
        entry = self.data.get('entries', {}).get(key, {})
        return None if entry.get('hero_fallback') else self._cached(icon_url(entry.get('image')))

    def badge(self, key):
        """The square icon of the uniquely matched same-hero nameplate, never a guessed skin."""
        if not re.fullmatch(r'\d{7}', key):
            return None
        entry = self.data.get('entries', {}).get(key, {})
        url = entry.get('badge')
        if entry.get('hero_fallback') or not isinstance(url, str) or not nameplate_url(url):
            return None
        return self._cached(url)

    def proficiency(self, key):
        """The hero's verified Fantastic proficiency reward icon."""
        if not re.fullmatch(r'10\d{2}', key):
            return None
        url = self.data.get('entries', {}).get(key, {}).get('proficiency')
        return self._cached(url) if nameplate_url(url) else None

    def spray(self, key):
        if not re.fullmatch(r'10\d{5}', key):
            return None
        entry = self.data.get('entries', {}).get(key, {})
        url = entry.get('spray')
        if entry.get('hero_fallback') or not isinstance(url, str) or not re.fullmatch(r'.*/items/spray/\d+/img_(?!icon_)[^/]+\.webp', url):
            return None
        return self._cached(url)

    @staticmethod
    def _sharp_path(path):
        return path.with_name(path.stem + '-x4.webp')

    def banner(self, key, sharp=False):
        """The hero or costume's published nameplate, or None when no plate is verified."""
        if not re.fullmatch(r'\d{4}(?:\d{3})?', key):
            return None
        entry = self.data.get('entries', {}).get(key, {})
        url = entry.get('banner')
        if entry.get('hero_fallback') or not isinstance(url, str) or '/items/nameplate/' not in url:
            return None
        path = self._cached(url)
        if path:
            target = self._sharp_path(path)
            if target.is_file():
                return target
            if sharp:
                with self.lock:
                    if path not in self.sharp_pending and time.time() - self.sharp_failed.get(path, 0) >= 300:
                        self.sharp_pending.append(path)
                    if self.sharp_pending and not self.sharp_running:
                        self.sharp_running = True
                        threading.Thread(target=self._sharpen_banners, name='catalogue-banners', daemon=True).start()
        return path

    def _sharpen_banners(self):
        """One background worker; HTTP reads keep returning originals while CPU work runs."""
        while True:
            with self.lock:
                if not self.sharp_pending:
                    self.sharp_running = False
                    return
                path = self.sharp_pending[0]
            target = self._sharp_path(path)
            staged = target.with_suffix(f'.{threading.get_ident()}.tmp')
            try:
                if not target.is_file():
                    from atelier.upscale import upscale
                    with Image.open(path) as image:
                        image = upscale(image)
                    image.save(staged, format='WEBP', quality=95, method=6)
                    staged.replace(target)
            except Exception:
                with self.lock:
                    self.sharp_failed[path] = time.time()
            finally:
                staged.unlink(missing_ok=True)
                with self.lock:
                    self.sharp_pending.remove(path)

    def _cached(self, url):
        if not url or not allowed_url(url):
            return None
        cache_key = hashlib.sha256(url.encode()).hexdigest()
        path = self.root / 'images' / (cache_key + '.webp')
        if path.is_file():
            return path
        if time.time() - self.failed_images.get(cache_key, 0) < 300:
            return None
        if not self.download_slots.acquire(timeout=25):
            return None
        try:
            if path.is_file():
                return path
            raw, _ = fetch(url)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'WEBP' or image.width * image.height > 16_000_000:
                    raise ValueError('Unexpected portrait format or dimensions')
                image.verify()
            path.parent.mkdir(parents=True, exist_ok=True)
            # Per-thread staging also makes duplicate simultaneous requests harmless.
            staged = path.with_suffix(f'.{threading.get_ident()}.tmp')
            try:
                staged.write_bytes(raw)
                staged.replace(path)
            finally:
                staged.unlink(missing_ok=True)
            return path
        except Exception:
            self.failed_images[cache_key] = time.time()
            return None
        finally:
            self.download_slots.release()


catalogue = Catalogue(Path(C.DATA_ROOT) / '_cache' / 'catalogue', Path(C.GUI_DIR) / 'catalogue.json')
