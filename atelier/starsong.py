"""The versioned Psylocke.gg game data feed and its catalogue artwork."""
from itertools import batched
import json
import re
from urllib.parse import urlencode

from atelier.skin_name_fixes import correct_skin_name

API = 'https://data.starsong.dev/marvel-rivals/graphql'
CDN = 'https://cdn.starsong.dev/marvel-rivals/objects'
CACHE_VERSION = 1
HERO_ART = ('avatar', 'logo', 'signature')
_MAX_WIDTH = 1600
_SKIN_TYPES = ('SKIN', 'SKIN_COLOR')
_IMAGE_URL = re.compile(re.escape(CDN) + r'/([a-f0-9]{2})/\1[a-f0-9]{62}\?width=([1-9][0-9]{0,3})')

_LATEST = 'query CatalogueRevision { revision { pin } }'
_HEROES = '''
query CatalogueHeroes($after: String) {
  revision {
    pin
    heroes(first: 100, after: $after) {
      nodes {
        id name playable forms { shapeId }
        defaultForm { portrait { ...ImageFields } icon { ...ImageFields } }
        logo { ...ImageFields }
        signature { ...ImageFields }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
'''
_SKINS = '''
query CatalogueSkins($after: String) {
  revision {
    pin
    items(first: 100, after: $after, type: [SKIN, SKIN_COLOR]) {
      nodes {
        id name type heroes { id }
        art { poster { ...ImageFields } icon { ...ImageFields } }
        bundles(first: 10) {
          nodes {
            items {
              id type
              art {
                icon { ...ImageFields }
                nameplate { plate { ...ImageFields } }
                spray { still { ...ImageFields } }
              }
            }
          }
          pageInfo { hasNextPage }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
'''
_NAMEPLATES = '''
query CatalogueNameplates($after: String, $ids: [ID!]!) {
  revision {
    pin
    items(first: 100, after: $after, type: [NAMEPLATE], id: $ids) {
      nodes { id type art { icon { ...ImageFields } nameplate { plate { ...ImageFields } } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
'''
_IMAGE_FIELDS = 'fragment ImageFields on Image { hash width height }'


def valid_pin(value):
    return isinstance(value, str) and len(value) <= 64 and bool(re.fullmatch(
        r'[0-9]+(?:\.[0-9]+)*:[1-9][0-9]*', value))


def is_image_url(url):
    match = _IMAGE_URL.fullmatch(url) if isinstance(url, str) else None
    return bool(match and int(match[2]) <= _MAX_WIDTH)


def _image_url(image):
    if not isinstance(image, dict):
        return None
    digest, width, height = image.get('hash'), image.get('width'), image.get('height')
    if (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
            or type(width) is not int or type(height) is not int or min(width, height) < 1):
        return None
    # A width rendition is a WebP, including when requested at the native width.
    return f'{CDN}/{digest[:2]}/{digest}?width={min(width, _MAX_WIDTH)}'


def _revision(fetch, query, pin=None, variables=None):
    params = {'query': query}
    if pin:
        params['at'] = pin
    if variables:
        params['variables'] = json.dumps(variables, separators=(',', ':'))
    raw, _ = fetch(f'{API}?{urlencode(params)}')
    payload = json.loads(raw)
    if payload.get('errors'):
        raise ValueError('Starsong could not complete the catalogue query')
    revision = payload['data']['revision']
    actual = revision.get('pin')
    if not valid_pin(actual) or (pin and pin != actual):
        raise ValueError('Starsong returned an unexpected catalogue revision')
    return revision


def latest_pin(fetch):
    return _revision(fetch, _LATEST)['pin']


def _pages(fetch, pin, query, field, **variables):
    after, seen = None, set()
    while True:
        page = _revision(fetch, query + _IMAGE_FIELDS, pin, {**variables, 'after': after})[field]
        yield from page['nodes']
        if not page['pageInfo']['hasNextPage']:
            return
        after = page['pageInfo']['endCursor']
        if not isinstance(after, str) or not after or after in seen or not page['nodes']:
            raise ValueError('Starsong returned an incomplete catalogue page')
        seen.add(after)


def _nameplate_art(item):
    art = item['art']
    return {'banner': _image_url((art.get('nameplate') or {}).get('plate')),
            'badge': _image_url(art.get('icon'))}


def _bundle_art(skin):
    bundles = skin['bundles']
    if bundles['pageInfo']['hasNextPage']:
        return {}
    candidates = {'NAMEPLATE': {}, 'SPRAY': {}}
    for bundle in bundles['nodes']:
        items = bundle['items']
        if {item['id'] for item in items if item['type'] in _SKIN_TYPES} != {skin['id']}:
            continue
        for item in items:
            if item['type'] in candidates:
                candidates[item['type']][item['id']] = item
    result = {}
    plate, spray = candidates['NAMEPLATE'], candidates['SPRAY']
    if len(plate) == 1:
        result.update(_nameplate_art(next(iter(plate.values()))))
    if len(spray) == 1:
        art = next(iter(spray.values()))['art']
        result['spray'] = _image_url((art.get('spray') or {}).get('still'))
    return result


def read_entries(fetch, pin):
    """Read every page from a single revision, then map assets to exact game IDs."""
    entries, playable = {}, set()
    for hero in _pages(fetch, pin, _HEROES, 'heroes'):
        cid, name = hero['id'], hero['name'].strip()
        if not re.fullmatch(r'[0-9]{4}', cid) or not name:
            continue
        if cid == '1011' and name == 'Bruce Banner':
            name = 'Hulk'  # The roster labels the whole character, including his forms.
        entry = entries[cid] = {'name': name, 'kind': 'hero', 'source': API}
        if hero['playable']:
            playable.add(cid)
            form = hero['defaultForm']
            entry.update(image=_image_url(form['portrait']), avatar=_image_url(form['icon']),
                         logo=_image_url(hero['logo']), signature=_image_url(hero['signature']))
            if len(hero['forms']) > 1:
                entry['multiple_forms'] = True

    skin_count = 0
    for skin in _pages(fetch, pin, _SKINS, 'items'):
        sid, name = skin['id'], skin['name'].strip()
        # The feed prefixes alternate-colour items; cooked paths use the numeric ID.
        if skin['type'] == 'SKIN_COLOR' and sid.startswith('ps'):
            sid = sid[2:]
            if sid in entries:
                continue
        cid = sid[:4]
        owners = {hero['id'] for hero in skin['heroes']}
        if not re.fullmatch(r'[0-9]{7}', sid) or cid not in entries or (owners and cid not in owners) or not name:
            continue
        art = skin['art']
        entries[sid] = {'name': correct_skin_name(sid, name), 'kind': 'skin', 'hero': cid,
                        'source': API, 'image': _image_url(art.get('poster')), 'icon': _image_url(art.get('icon')),
                        **_bundle_art(skin)}
        skin_count += 1
    if not playable or not skin_count:
        raise ValueError('Starsong returned no usable hero or skin catalogue')

    plate_ids = {f'3{cid}{suffix}': (cid, suffix) for cid in sorted(playable) for suffix in ('001', '002')}
    # Leave space for the API's other bound parameters in each ID filter.
    for ids in batched(plate_ids, 50):
        for item in _pages(fetch, pin, _NAMEPLATES, 'items', ids=ids):
            if item['id'] not in plate_ids or item['type'] != 'NAMEPLATE':
                continue
            cid, suffix = plate_ids[item['id']]
            art = _nameplate_art(item)
            if suffix == '001':
                entries[cid].update(art, banner_style='default')
            else:
                entries[cid]['proficiency'] = art['badge']
    return entries
