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

IDS_URL = 'https://raw.githubusercontent.com/donutman07/MarvelRivalsCharacterIDs/main/MarvelRivalsCharacterIDs.md'
HEROES_URL = 'https://rivalskins.com/heroes/'
DAY = 86400
PARSER_VERSION = 6
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
    match = re.fullmatch(r'(.*/items/nameplate/\d+/img_)icon_([^/]+\.webp)', icon)
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
        parsed.path in ('/heroes/', '/assets/hero-logos/', '/assets/hero-icons-avatars/', '/assets/hero-story-images/',
                        '/assets/lord-icons/', '/assets/kill-icons/')
        or parsed.path.startswith(('/hero/', '/item/', '/wp-content/uploads/marvel-assets/items/costume/',
                                   '/wp-content/uploads/marvel-assets/items/nameplate/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-logos/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-icons-avatars/',
                                   '/wp-content/uploads/marvel-assets/assets/hero-story-images/'))
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


def build_entries(chars, roster, load_page, load_items):
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
        match = re.fullmatch(r'(?:Characters|VFX/Materials/Characters)/(\d{4})(?:/(\d{7}))?', path, re.I)
        if not match:
            return None
        cid, sid = match.groups()
        if sid and not sid.startswith(cid):
            return None
        key = sid or cid
        entry = self.data.get('entries', {}).get(key)
        if not entry and sid:
            hero = self.data.get('entries', {}).get(cid)
            if hero:
                entry = {**hero, 'name': None, 'hero_fallback': True}
                key = cid
        if not entry:
            return None
        return {'name': entry.get('name'), 'thumbnail': f'/api/catalogue/thumbnail/{key}' if entry.get('image') else None,
                'hero_fallback': entry.get('hero_fallback', False),
                'banner': f'/api/catalogue/banner/{key}' if entry.get('banner') and not entry.get('hero_fallback') else None,
                'badge': f'/api/catalogue/badge/{key}' if sid and entry.get('badge') and not entry.get('hero_fallback') else None}

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
            digest = hashlib.sha256(md + roster_html).hexdigest()
            chars = parse_ids(md.decode('utf-8'))
            roster = parse_cards(roster_html.decode('utf-8'), roster=True)
            if len(chars) < 20 or len(roster) < 20:
                raise ValueError('Catalogue sources changed format; keeping the previous catalogue')
            # Compare useful content, not ad timestamps / scripts embedded in the page.
            content_hash = hashlib.sha256(json.dumps([chars, roster], sort_keys=True).encode()).hexdigest()
            now = time.time()
            previous = self.data
            if (previous.get('parser_version') != PARSER_VERSION
                    or content_hash != previous.get('content_hash')
                    or now - previous.get('refreshed_at', 0) >= DAY):
                with ThreadPoolExecutor(max_workers=3, thread_name_prefix='catalogue-page') as pool:
                    entries = build_entries(chars, roster, lambda url: fetch(url)[0].decode('utf-8'),
                                            lambda pages: list(pool.map(self.item_artwork, pages)))
                if sum(bool(e.get('image')) for e in entries.values()) < 20:
                    raise ValueError('No usable portraits; keeping the previous catalogue')
                data = {'schema': 1, 'parser_version': PARSER_VERSION,
                        'entries': entries, 'refreshed_at': now, 'content_hash': content_hash,
                        'sources': [IDS_URL, HEROES_URL], 'source_digest': digest}
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
