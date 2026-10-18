"""Offline upgrade notes, acknowledgement persistence and fresh-install behavior."""
import atexit
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-changelog-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import changelog, config as C
from atelier.web import routes as R


def cleanup():
    R.shutdown(5)
    data.cleanup()


atexit.register(cleanup)

NOTES = '''# Changelog
## Unreleased
- Not shipped yet.
## 2.0.0 — 20 October 2026
- A future release.
## 1.0.0 — 18 October 2026
- **Material replacement** keeps the donor's
  cooked shader data.
### Fixes
- Fixed `preview` loading.

Read the [release notes](docs/release-1.0.0.md).
## 0.4.1 — 16 October 2026
- Custom textures.
## 0.4.0 — 16 October 2026
- Model Studio.
'''


def http(path, body=None, project=None):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body).encode() if body is not None else b''
    env.update(PATH_INFO=path, REQUEST_METHOD='POST' if body is not None else 'GET',
               CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(payload)),
               **{'wsgi.input': io.BytesIO(payload)})
    if project is not None:
        env['HTTP_X_ATELIER_PROJECT'] = project
    replies = []
    result = R.app(env, lambda status, headers, exc_info=None: replies.append(int(status.split()[0])))
    try:
        value = json.loads(b''.join(result))
    finally:
        if hasattr(result, 'close'):
            result.close()
    return replies[0], value


class Changelog(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=data.name)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.version = self.root / 'version'
        self.version.write_text('1.0.0\n', encoding='utf-8')
        (self.root / 'CHANGELOG.md').write_text(NOTES, encoding='utf-8')
        for patcher in (patch.object(C, 'CONFIG_FILE', str(self.root / 'mr_config.json')),
                        patch.object(R, 'VERSION_FILE', str(self.version))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fresh_install_has_no_popup_then_detects_its_first_upgrade(self):
        status = changelog.status(self.version)
        self.assertFalse(status['available'])
        self.assertEqual(C._load_config()['changelog_version'], '1.0.0')
        C._save_config(paks='fixture/Paks')
        self.assertFalse(changelog.status(self.version)['available'])
        self.version.write_text('1.0.1', encoding='utf-8')
        self.assertTrue(changelog.status(self.version)['available'])

    def test_existing_install_gets_notes_until_dismissed_and_keeps_its_settings(self):
        C._save_config(paks='fixture/Paks', mods_folder='fixture/mods', unrelated={'keep': True})
        for _ in range(2):
            self.assertTrue(changelog.status(self.version)['available'])
            self.assertNotIn('changelog_version', C._load_config())
        changelog.acknowledge(self.version, '1.0.0')
        self.assertFalse(changelog.status(self.version)['available'])
        self.assertEqual(C._load_config(), {'paks': 'fixture/Paks', 'mods_folder': 'fixture/mods',
                                          'unrelated': {'keep': True}, 'changelog_version': '1.0.0'})

    def test_skipped_releases_exclude_seen_unreleased_and_future_notes(self):
        C._save_config(paks='fixture/Paks', changelog_version='0.4.0')
        result = changelog.status(self.version)
        self.assertTrue(result['available'])
        self.assertEqual([release['version'] for release in result['releases']], ['1.0.0', '0.4.1'])
        blocks = result['releases'][0]['blocks']
        self.assertEqual(blocks[0]['items'], ["**Material replacement** keeps the donor's cooked shader data."])
        self.assertEqual(blocks[1], {'type': 'heading', 'text': 'Fixes'})
        self.assertNotIn('Not shipped yet', json.dumps(result))
        self.assertNotIn('A future release', json.dumps(result))

    def test_same_version_is_silent_and_manual_notes_remain_available(self):
        C._save_config(paks='fixture/Paks', changelog_version='1.0.0')
        result = changelog.status(self.version)
        self.assertFalse(result['available'])
        self.assertEqual([release['version'] for release in result['releases']], ['1.0.0'])

    def test_versions_compare_numerically_and_accept_equivalent_precision(self):
        C._save_config(paks='fixture/Paks', changelog_version='1.9.0')
        self.version.write_text('1.10.0', encoding='utf-8')
        self.assertTrue(changelog.status(self.version)['available'])
        C._save_config(changelog_version='1.10')
        self.assertFalse(changelog.status(self.version)['available'])

    def test_downgrade_does_not_reset_a_newer_acknowledgement(self):
        C._save_config(paks='fixture/Paks', changelog_version='2.0.0')
        self.assertFalse(changelog.status(self.version)['available'])
        changelog.acknowledge(self.version, '1.0.0')
        self.assertEqual(C._load_config()['changelog_version'], '2.0.0')

    def test_missing_notes_offer_a_readable_fallback_without_network(self):
        C._save_config(paks='fixture/Paks', changelog_version='0.4.1')
        (self.root / 'CHANGELOG.md').unlink()
        with patch('urllib.request.urlopen', side_effect=AssertionError('Release notes must be local')):
            result = changelog.status(self.version)
        self.assertTrue(result['available'])
        self.assertIn('full changelog', result['releases'][0]['blocks'][0]['text'])

    def test_missing_or_invalid_build_version_never_triggers_popup(self):
        C._save_config(paks='fixture/Paks', changelog_version='0.4.1')
        for version in ('development', '', 'v1.0.0'):
            self.version.write_text(version, encoding='utf-8')
            self.assertFalse(changelog.status(self.version)['available'])
        self.version.unlink()
        self.assertFalse(changelog.status(self.version)['available'])
        self.assertEqual(C._load_config()['changelog_version'], '0.4.1')

    def test_http_notes_and_acknowledgement_are_independent_of_active_project(self):
        C._save_config(paks='fixture/Paks', changelog_version='0.4.1')
        status, value = http('/api/changelog', project='A deleted project')
        self.assertEqual(status, 200)
        self.assertTrue(value['available'])
        status, value = http('/api/changelog/acknowledge', {'version': '1.0.0'}, project='A deleted project')
        self.assertEqual((status, value), (200, {'ok': True}))
        self.assertFalse(http('/api/changelog')[1]['available'])
        self.assertEqual(json.loads((self.root / 'mr_config.json').read_text())['changelog_version'], '1.0.0')

    def test_http_rejects_stale_or_forged_acknowledgements(self):
        C._save_config(paks='fixture/Paks', changelog_version='0.4.1')
        for value in ('0.4.1', '9.9.9', None, {'invalid': True}):
            status, result = http('/api/changelog/acknowledge', {'version': value})
            self.assertEqual(status, 400)
            self.assertFalse(result['ok'])
            self.assertEqual(C._load_config()['changelog_version'], '0.4.1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
