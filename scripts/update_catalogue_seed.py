"""Refresh the shipped metadata seed through the normal verified catalogue parser.

Run explicitly before a release. Downloads stay in an optional artwork cache; only
metadata and source URLs are written to gui/catalogue.json. A failed refresh leaves
the shipped seed untouched.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atelier.catalogue import Catalogue, PARSER_VERSION
from atelier.storage import atomic_json


def validate_seed(path):
    data = Catalogue._read(Path(path))
    if not data or data.get('parser_version') != PARSER_VERSION:
        raise ValueError('Refresh gui/catalogue.json with scripts/update_catalogue_seed.py before packaging.')
    entries = data['entries']
    banners = sum(bool(e.get('banner') and e.get('badge') and not e.get('hero_fallback')) for e in entries.values())
    if not banners:
        raise ValueError('The release catalogue has no verified nameplates; refresh the seed before packaging.')
    return data, banners


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=Path, default=ROOT / '_cache' / 'catalogue-seed')
    args = parser.parse_args()
    seed = ROOT / 'gui' / 'catalogue.json'
    catalogue = Catalogue(args.cache_dir, seed)
    catalogue.update()
    if catalogue.status()['error']:
        raise SystemExit(catalogue.status()['error'])
    data, banners = validate_seed(args.cache_dir / 'catalogue.json')
    atomic_json(str(seed), data, indent=2, ensure_ascii=False)
    print(f'Catalogue seed: {len(data["entries"])} entries, {banners} verified nameplates and badges.')


if __name__ == '__main__':
    main()
