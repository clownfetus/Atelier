"""Hero avatars and emblems, checked once per launch and cached independently of costumes."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote, urlsplit

from PIL import Image
from atelier import config
from atelier.catalogue import allowed_url, fetch, normalized, ALIASES
from atelier.storage import atomic_json

PAGES = {'avatar': 'https://rivalskins.com/assets/hero-icons-avatars/',
         'logo': 'https://rivalskins.com/assets/hero-logos/',
         'story': 'https://rivalskins.com/assets/hero-story-images/'}
PREFIX = 'https://rivalskins.com/wp-content/uploads/marvel-assets/assets/'
# The Hood's published 0010 image is a blank silhouette; 0011 is the usable portrait.
PREFERRED_AVATARS = {'img_squarehead_10660011_avatar': '1066'}


def asset_url(url, kind):
    folder = {'avatar':'hero-icons-avatars/', 'logo':'hero-logos/', 'story':'hero-story-images/'}.get(kind)
    return bool(folder) and isinstance(url, str) and url.startswith(PREFIX + folder) and allowed_url(url)


class Assets(HTMLParser):
    def __init__(self, kind, names):
        super().__init__(convert_charrefs=True)
        self.kind, self.names, self.entries, self.ranks = kind, names, {}, {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        url = attrs.get('src' if tag == 'img' else 'href', '')
        if tag not in ('img', 'a') or not asset_url(url, self.kind):
            return
        name = Path(unquote(urlsplit(url).path)).stem
        if self.kind == 'story':
            numeric = re.fullmatch(r'img_herostory_(\d{4})(\d{2})_hover', name, re.I)
            if numeric:
                cid, rank = numeric[1], 100-int(numeric[2])
                if rank > self.ranks.get(cid, -1):
                    self.entries[cid], self.ranks[cid] = url, rank
            return
        numeric = re.fullmatch(r'img_squarehead_(\d{4})0010_avatar' if self.kind == 'avatar'
                               else r'img_herologo_(\d{4})_logo', name, re.I)
        cid, rank = (numeric[1], 2) if numeric else (None, 1)
        if self.kind == 'avatar' and name.lower() in PREFERRED_AVATARS:
            cid, rank = PREFERRED_AVATARS[name.lower()], 3
        if cid is None:
            label = re.sub(r'_avatar$| Hero Logo$', '', name, flags=re.I)
            cid = self.names.get(normalized(label))
        if cid and rank > self.ranks.get(cid, 0):
            self.entries[cid], self.ranks[cid] = url, rank


def parse_assets(html, kind, names):
    parser = Assets(kind, names)
    parser.feed(html)
    return parser.entries


class HeroArtwork:
    def __init__(self, root):
        self.root = Path(root)
        self.lock, self.slots = threading.Lock(), threading.BoundedSemaphore(3)
        self.started = False
        self.state = {'updating': False, 'error': None, 'checked_at': None}
        try:
            data = json.loads((self.root / 'hero-artwork.json').read_text(encoding='utf-8'))
            self.entries = {cid: {kind: url for kind, url in entry.items()
                                  if kind in PAGES and asset_url(url, kind)}
                            for cid, entry in data['entries'].items() if re.fullmatch(r'\d{4}', cid)}
            self.state['checked_at'] = data.get('checked_at')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.entries = {}

    def status(self):
        with self.lock:
            return {**self.state, **{('stories' if kind == 'story' else kind + 's'): sum(kind in entry for entry in self.entries.values()) for kind in PAGES}}

    def start_update(self, entries):
        with self.lock:
            if self.started:
                return
            self.started = True
            self.state.update(updating=True, error=None)
        names = {}
        for cid, entry in entries.items():
            if re.fullmatch(r'\d{4}', cid):
                key = normalized(entry.get('name', ''))
                names[ALIASES.get(key, key)] = cid
        threading.Thread(target=self.update, args=(names,), name='atelier-hero-artwork', daemon=True).start()

    def _image(self, url):
        path = self.root / 'hero-images' / (hashlib.sha256(url.encode()).hexdigest() + '.webp')
        if path.is_file():
            return path
        with self.slots:
            if path.is_file():
                return path
            raw, _ = fetch(url)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'WEBP') or image.width * image.height > 16_000_000:
                    raise ValueError('Unexpected hero artwork format or dimensions')
                image.load()
                image = image.convert('RGBA')
                image.thumbnail((1600, 1600) if '/hero-story-images/' in url else (512, 512), Image.Resampling.LANCZOS)
                path.parent.mkdir(parents=True, exist_ok=True)
                staged = path.with_suffix(f'.{threading.get_ident()}.tmp')
                try:
                    image.save(staged, format='WEBP', lossless=True)
                    staged.replace(path)
                finally:
                    staged.unlink(missing_ok=True)
        return path

    def update(self, names):
        errors, discovered = [], {}
        try:
            for kind, page in PAGES.items():
                try:
                    found = parse_assets(fetch(page)[0].decode('utf-8'), kind, names)
                    if not found:
                        raise ValueError('No hero artwork found; keeping the saved artwork')
                    for cid, url in found.items():
                        discovered[cid, kind] = url
                except Exception as exc:
                    errors.append(str(exc))
            def download(item):
                (cid, kind), url = item
                try:
                    self._image(url)
                    return cid, kind, url
                except Exception:
                    return None
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='hero-artwork') as pool:
                for result in pool.map(download, discovered.items()):
                    if result:
                        cid, kind, url = result
                        with self.lock:
                            self.entries.setdefault(cid, {})[kind] = url
                    else:
                        errors.append('Some artwork could not be downloaded; keeping cached copies')
            now = time.time()
            with self.lock:
                data = {'schema': 1, 'entries': self.entries, 'checked_at': now, 'sources': list(PAGES.values())}
                atomic_json(str(self.root / 'hero-artwork.json'), data)
                self.state.update(checked_at=now, error='; '.join(dict.fromkeys(errors)) or None)
        except Exception as exc:
            with self.lock:
                self.state['error'] = str(exc)
        finally:
            with self.lock:
                self.state['updating'] = False

    def image(self, cid, kind):
        if not re.fullmatch(r'\d{4}', cid) or kind not in PAGES:
            return None
        with self.lock:
            url = self.entries.get(cid, {}).get(kind)
        # UI reads are local: a slow or offline artwork source never blocks navigation.
        path = self.root / 'hero-images' / (hashlib.sha256(url.encode()).hexdigest() + '.webp') if url else None
        return path if path and path.is_file() else None


hero_artwork = HeroArtwork(Path(config.DATA_ROOT) / '_cache' / 'catalogue')
