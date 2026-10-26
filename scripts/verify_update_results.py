"""Require real native updater handoffs before publishing the signed release."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as P


def verify(release, reports):
    feed = P.verify_feed(json.loads((release / P.FEED).read_bytes()), json.loads((ROOT / 'update_keys.json').read_bytes()))
    receipt = json.loads((release / 'VERIFICATION.json').read_bytes())
    for target in feed['platforms'].values():
        for row in [target['full'], *target.get('patches', []), *([target['installer']] if target.get('installer') else [])]:
            if P.file_record(release / row['name']) != {key: row[key] for key in ('name', 'bytes', 'sha256')}:
                raise ValueError('Release asset differs from its signed update metadata.')
    for runner, platform in [('windows-2022', 'windows-x64'), ('ubuntu-24.04', 'linux-x64')]:
        result = json.loads((reports / f'in-app-update-{runner}/results.json').read_bytes())
        if not result.get('ok') or result.get('source_commit') != feed['source_commit'] or result.get('version') != feed['version'] or result.get('platform') != platform or result.get('package_sha256') != feed['platforms'][platform]['full']['sha256']:
            raise ValueError('Native updater verification does not match this release: ' + runner)
        receipt['checks'][platform + '_in_app_update'] = result
    P.atomic_json(release / 'VERIFICATION.json', receipt)
    sums = ''.join(f'{P.digest(path)}  {path.name}\n' for path in sorted(release.iterdir()) if path.name != 'SHA256SUMS.txt')
    (release / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    args = parser.parse_args()
    verify(args.release, args.reports)
