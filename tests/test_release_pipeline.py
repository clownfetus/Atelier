"""Publishing binds the exact commit, platform reports and signed payload digests."""
import base64
from contextlib import redirect_stderr
import copy
import io
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from atelier import update_protocol as P
import assemble_release as A
import prepare_release as R
import verify_update_results as V
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ReleasePlanning(unittest.TestCase):
    def previous(self):
        return {'tag_name': '1.1.3', 'assets': [
            {'name': name, 'size': 123, 'digest': 'sha256:' + 'a' * 64,
             'browser_download_url': 'https://github.com/clownfetus/Atelier/releases/download/1.1.3/' + name}
            for name in ['AtelierSetup.exe', 'Atelier-1.1.3-x86_64.AppImage']]}

    def test_any_update_uses_latest_release_as_its_upgrade_baseline(self):
        with patch.object(R, 'git', side_effect=['b' * 40, 'gui/app.js\natelier/catalogue.py']), \
             patch.object(R, 'native_cache_key', return_value='stable-native-key'):
            context, inputs = R.prepare('1.1.4', self.previous())
        self.assertEqual(context['previous_version'], '1.1.3')
        self.assertFalse(context['full_checks'])
        self.assertIn('/1.1.3/AtelierSetup.exe', inputs['previous_windows_url'])
        self.assertEqual(inputs['previous_linux_sha256'], 'a' * 64)

    def test_dependency_installer_and_export_changes_require_full_checks(self):
        for name in ['packaging/Atelier.iss', 'packaging/Atelier.spec', 'requirements.txt', 'native/a.cs',
                     'atelier/handlers/texture.py', 'atelier/update_protocol.py', 'packaging/linux/build_appimage.sh']:
            self.assertTrue(R.needs_full_checks([name]), name)
        self.assertTrue(R.needs_full_checks([]), 'Unknown comparison must fail closed.')
        self.assertFalse(R.needs_full_checks(['gui/style.css', 'atelier/catalogue.py']))

    def test_same_or_lower_version_is_refused_before_building(self):
        for number in ['1.1.3', '1.1.2', '0.9.9']:
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, 'higher'):
                R.prepare(number, self.previous())

    def test_native_reuse_depends_on_native_sources_and_recipes(self):
        self.assertTrue(R.can_reuse_native(['gui/app.js', 'atelier/catalogue.py']))
        for name in ['native/AtelierNative/Program.cs', 'toolchain/tools.lock.json',
                     'scripts/toolchain.py', 'scripts/build_shader_tool.py', 'requirements-build.txt']:
            self.assertFalse(R.can_reuse_native([name]), name)
        self.assertFalse(R.can_reuse_native([]))

    def test_missing_published_asset_digest_is_refused(self):
        previous = self.previous()
        previous['assets'][0]['digest'] = None
        with patch.object(R, 'git', side_effect=['b' * 40, 'gui/app.js']):
            with self.assertRaises((ValueError, AttributeError)):
                R.prepare('1.1.4', previous)


class Assembly(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-release-pipeline-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        self.artifacts = Path(self.temp.name) / 'artifacts'
        self.output = Path(self.temp.name) / 'release'
        self.private = Ed25519PrivateKey.generate()
        self.secret = base64.b64encode(self.private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        import hashlib
        self.key_id = hashlib.sha256(public).hexdigest()[:16]
        self.keys = {self.key_id: base64.b64encode(public).decode()}
        self.write(self.root / 'update_keys.json', self.keys)
        self.write(self.root / 'version', b'1.1.3\n')
        self.write(self.root / 'CHANGELOG.md', b'# Changelog\n\n## 1.1.3\n\nPrevious release\n')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Update tests', '-c', 'user.email=tests@example.invalid',
                        'commit', '-qm', 'Original source'], cwd=self.root, check=True, capture_output=True)
        self.commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()
        self.write(self.root / 'version', b'1.1.4\n')
        self.write(self.root / 'CHANGELOG.md', b'# Changelog\n\n## 1.1.4\n\n- Fixture improvement\n')
        self.write(self.root / '_release/inputs.json', {'previous_windows_sha256': 'd' * 64, 'previous_linux_sha256': 'e' * 64})
        self.context = {'version': '1.1.4', 'source_commit': self.commit, 'full_checks': False}
        self.windows = self.artifacts / 'release-windows'
        payload = Path(self.temp.name) / 'payload'
        self.write(payload / 'Atelier.exe', b'new executable')
        self.write(payload / '_internal/version', b'1.1.4')
        inventory = P.make_inventory(payload, '1.1.4', self.commit)
        self.write(self.windows / 'Atelier-Windows-1.1.4-inventory.json', inventory)
        self.full = self.windows / 'Atelier-Windows-1.1.4.zip'
        with zipfile.ZipFile(self.full, 'w') as archive:
            for path in payload.rglob('*'):
                if path.is_file():
                    archive.write(path, 'Atelier/' + path.relative_to(payload).as_posix())
        self.write(self.windows / 'AtelierSetup.exe', b'installer')
        self.manifest = {'source_commit': self.commit, 'application_version': '1.1.4',
                         'installer_sha256': P.digest(self.windows / 'AtelierSetup.exe'),
                         'files': [P.file_record(path) | {'path': path.relative_to(payload).as_posix()}
                                   for path in payload.rglob('*') if path.is_file()]}
        self.write(self.windows / 'installer-manifest.json', self.manifest)
        self.write(self.windows / 'windows-update.json', {'full': P.file_record(self.full), 'patches': [],
                   'runtime_id': inventory['runtime_id'], 'installer': P.file_record(self.windows / 'AtelierSetup.exe')})
        self.image = self.artifacts / 'release-linux/Atelier-1.1.4-x86_64.AppImage'
        self.write(self.image, b'\x7fELF appimage fixture')
        backend = {'results': [{'suite': 'test_updates.py', 'exit_code': 0}]}
        browser = {'checks': ['real UI loaded'], 'page_errors': [], 'exe_sha256': P.digest(payload / 'Atelier.exe')}
        for name in ('windows', 'linux'):
            self.write(self.artifacts / f'release-{name}-reports/backend/results.json', backend)
            self.write(self.artifacts / f'release-{name}-reports/browser/results.json', browser)
        self.write(self.artifacts / 'release-windows-reports/frozen/results.json', browser)
        self.write(self.artifacts / 'release-linux-reports/appimage/results.json',
                   {'ok': True, 'appimage_sha256': P.digest(self.image), 'previous_appimage_sha256': 'e' * 64})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(P.canonical(value) if isinstance(value, dict) else value)

    def assemble(self):
        with patch.object(A, 'ROOT', self.root):
            A.assemble(self.artifacts, self.output, self.context, self.secret)

    def test_complete_release_has_verified_signed_updates_and_matching_source_metadata(self):
        self.assemble()
        envelope = json.loads((self.output / P.FEED).read_bytes())
        data = P.verify_feed(envelope, self.keys)
        self.assertEqual(data['version'], '1.1.4')
        for platform in data['platforms'].values():
            row = platform['full']
            self.assertEqual(P.digest(self.output / row['name']), row['sha256'])
        for line in (self.output / 'SHA256SUMS.txt').read_text().splitlines():
            checksum, name = line.split('  ')
            self.assertEqual(P.digest(self.output / name), checksum)
        with zipfile.ZipFile(self.output / 'Atelier-1.1.4-source.zip') as archive:
            self.assertEqual(archive.read('Atelier-source/version'), b'1.1.4\n')
            self.assertIn(b'Fixture improvement', archive.read('Atelier-source/CHANGELOG.md'))

    def test_tampered_installer_prevents_assembly(self):
        self.write(self.windows / 'AtelierSetup.exe', b'tampered')
        with self.assertRaisesRegex(ValueError, 'Installer differs'):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_windows_report_must_match_actual_executable(self):
        report = self.artifacts / 'release-windows-reports/frozen/results.json'
        data = json.loads(report.read_bytes())
        data['exe_sha256'] = '0' * 64
        self.write(report, data)
        with self.assertRaisesRegex(ValueError, 'Windows application gate'):
            self.assemble()

    def test_failed_or_missing_suite_blocks_publication(self):
        for results in ([], [{'suite': 'failed.py', 'exit_code': 1}]):
            self.write(self.artifacts / 'release-linux-reports/backend/results.json', {'results': results})
            with self.assertRaisesRegex(ValueError, 'backend gate'):
                self.assemble()

    def test_linux_report_must_match_both_images(self):
        self.write(self.artifacts / 'release-linux-reports/appimage/results.json',
                   {'ok': True, 'appimage_sha256': P.digest(self.image), 'previous_appimage_sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'Linux application/upgrade'):
            self.assemble()

    def test_full_gate_cannot_publish_without_installer_reports(self):
        self.context['full_checks'] = True
        with self.assertRaises(FileNotFoundError):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_another_commits_build_is_rejected(self):
        self.manifest['source_commit'] = 'f' * 40
        self.write(self.windows / 'installer-manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'another source commit'):
            self.assemble()

    def test_changed_update_archive_is_rejected(self):
        self.full.write_bytes(b'wrong portable zip')
        with self.assertRaisesRegex(ValueError, 'Update package differs'):
            self.assemble()

    def native_results(self):
        feed = json.loads((self.output / P.FEED).read_bytes())['signed']
        reports = Path(self.temp.name) / 'native-results'
        for runner, platform in [('windows-2022', 'windows-x64'), ('ubuntu-24.04', 'linux-x64')]:
            self.write(reports / f'in-app-update-{runner}/results.json', {'ok': True, 'platform': platform,
                       'version': '1.1.4', 'source_commit': self.commit,
                       'package_sha256': feed['platforms'][platform]['full']['sha256']})
        return reports

    def test_native_handoff_results_are_bound_to_this_exact_release(self):
        self.assemble()
        reports = self.native_results()
        with patch.object(V, 'ROOT', self.root):
            V.verify(self.output, reports)
        receipt = json.loads((self.output / 'VERIFICATION.json').read_bytes())
        self.assertTrue(receipt['checks']['windows-x64_in_app_update']['ok'])
        self.assertTrue(receipt['checks']['linux-x64_in_app_update']['ok'])

    def test_handoff_report_from_another_binary_is_rejected(self):
        self.assemble()
        reports = self.native_results()
        path = reports / 'in-app-update-windows-2022/results.json'
        data = json.loads(path.read_bytes())
        data['package_sha256'] = '0' * 64
        self.write(path, data)
        with patch.object(V, 'ROOT', self.root), self.assertRaisesRegex(ValueError, 'does not match'):
            V.verify(self.output, reports)


if __name__ == '__main__':
    unittest.main()
