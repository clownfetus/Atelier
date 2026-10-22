"""Release integrity: reject mixed builds, stale screenshots and failed platform gates."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_bundle as B
import release_screenshots as S


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-release-gate-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        self.art = Path(self.temp.name) / 'artifacts'
        self.out = Path(self.temp.name) / 'release'
        self.version = '1.1.1'
        self.write('version', self.version)
        self.write('gui/app.js', 'fixture interface')
        self.write('atelier/config.py', '# fixture source')
        self.write('docs/release-1.1.1.md', '# Atelier 1.1.1\nRelease fixture\n')
        self.write('docs/discord-1.1.1.md', '**Atelier 1.1.1**\nDiscord fixture\n')
        self.write('tests/fixtures/installer/release-1.1.1-inputs.json',
                   {'linux_seed_sha256': 'b' * 64, 'previous_windows_sha256': 'd' * 64})
        self.write('images/README.md', '# Actual interface capture inventory\n')
        names = ['studio-dark.png', 'studio-light.png', 'material-editor.png',
                 'model-studio.png', 'showcase.png']
        for name in names:
            self.write('images/' + name, b'PNG fixture ' + name.encode())
        self.receipt = {'version': self.version, 'page_errors': [],
                        'source_files': S.source_hashes(self.root),
                        'files': [{'path': name, 'sha256': B.sha(self.root / 'images' / name)}
                                  for name in names]}
        self.write('images/screenshots.json', self.receipt)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=Release fixture', '-c',
                        'user.email=release@example.invalid', 'commit', '-qm', 'Fixture'],
                       cwd=self.root, check=True, capture_output=True)
        self.commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()
        self.installer = b'verified installer'
        self.linux = b'verified AppImage'
        self.payload = b'verified portable payload'
        self.manifest = {'source_commit': self.commit, 'application_version': self.version,
                         'installer_sha256': digest(self.installer), 'installer_bytes': len(self.installer),
                         'files': [{'path': 'Atelier.exe', 'bytes': len(self.payload),
                                    'sha256': digest(self.payload)}]}
        self.artwrite('windows-installer/installer-manifest.json', self.manifest)
        self.artwrite('windows-installer/AtelierSetup.exe', self.installer)
        self.artwrite('linux-appimage/Atelier-1.1.1-x86_64.AppImage', self.linux)
        self.portable = self.art / 'windows-portable/Atelier-Windows-1.1.1.zip'
        self.portable.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.portable, 'w') as archive:
            archive.writestr('Atelier/Atelier.exe', self.payload)
        backend = {'results': [{'suite': 'fixture', 'exit_code': 0}], 'platform': 'fixture', 'python': 'fixture'}
        browser = {'checks': ['fixture'], 'page_errors': [], 'exe_sha256': digest(self.payload)}
        for name in ['windows-backend-report/backend/results.json', 'linux-reports/backend/results.json']:
            self.artwrite(name, backend)
        for name in ['windows-backend-report/browser/results.json', 'windows-backend-report/frozen/results.json']:
            self.artwrite(name, browser)
        for os_name in ['windows-2022', 'windows-2025']:
            self.artwrite(f'installer-report-{os_name}/results.json',
                          {'ok': True, 'page_errors': [], 'installer_sha256': digest(self.installer),
                           'previous_installer_sha256': 'd' * 64})
        self.artwrite('linux-reports/appimage-smoke/results.json',
                      {'ok': True, 'appimage_sha256': digest(self.linux), 'previous_appimage_sha256': 'b' * 64})

    def write(self, name, data, base=None):
        path = (base or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, dict):
            data = json.dumps(data)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())

    def artwrite(self, name, data):
        self.write(name, data, self.art)

    def assemble(self):
        with patch.object(B, 'ROOT', self.root), patch.object(sys, 'argv',
                  ['release_bundle.py', '--artifacts', str(self.art), '--output', str(self.out)]), redirect_stdout(io.StringIO()):
            B.main()

    def refused(self, message):
        with self.assertRaisesRegex((RuntimeError, FileNotFoundError), message):
            self.assemble()
        self.assertFalse(self.out.exists(), 'A refused candidate must not leave a publishable-looking bundle')

    def test_complete_bundle_has_matching_source_copy_screenshots_portable_and_checksums(self):
        self.assemble()
        expected = {'AtelierSetup.exe', 'Atelier-1.1.1-x86_64.AppImage', 'Atelier-Windows-1.1.1.zip',
                    'Atelier-1.1.1-source.zip', 'Atelier-1.1.1-screenshots.zip', 'RELEASE_NOTES.md',
                    'DISCORD.md', 'VERIFICATION.json', 'SHA256SUMS.txt'}
        self.assertEqual({p.name for p in self.out.iterdir()}, expected)
        for line in (self.out / 'SHA256SUMS.txt').read_text().splitlines():
            sha, name = line.split('  ', 1)
            self.assertEqual(sha, B.sha(self.out / name))
        receipt = json.loads((self.out / 'VERIFICATION.json').read_text())
        self.assertEqual(receipt['source_commit'], self.commit)
        self.assertEqual(receipt['portable_files_verified'], 1)
        with zipfile.ZipFile(self.out / 'Atelier-1.1.1-source.zip') as archive:
            self.assertEqual(archive.read('Atelier-source/version').decode(), self.version)
        with zipfile.ZipFile(self.out / 'Atelier-1.1.1-screenshots.zip') as archive:
            self.assertIn('studio-dark.png', archive.namelist())
            self.assertIn('screenshots.json', archive.namelist())

    def test_refuses_installer_from_another_commit(self):
        self.manifest['source_commit'] = '0' * 40
        self.artwrite('windows-installer/installer-manifest.json', self.manifest)
        self.refused('another source commit')

    def test_refuses_modified_installer(self):
        self.artwrite('windows-installer/AtelierSetup.exe', b'changed')
        self.refused('does not match')

    def test_refuses_modified_portable_file(self):
        with zipfile.ZipFile(self.portable, 'w') as archive:
            archive.writestr('Atelier/Atelier.exe', b'stale payload')
        self.refused('stale or corrupted')

    def test_refuses_extra_portable_file(self):
        with zipfile.ZipFile(self.portable, 'a') as archive:
            archive.writestr('Atelier/private-config.json', 'private fixture')
        self.refused('membership differs')

    def test_refuses_stale_screenshot_version(self):
        self.receipt['version'] = '1.1.0'
        self.write('images/screenshots.json', self.receipt)
        self.refused('Screenshot version')

    def test_refuses_interface_changed_after_capture(self):
        self.write('gui/app.js', 'changed after capture')
        self.refused('different interface source')

    def test_text_hashes_allow_git_checkout_line_endings_without_masking_content_changes(self):
        self.write('gui/app.js', b'first line\r\nsecond line\r\n')
        windows = S.source_hashes(self.root)
        self.write('gui/app.js', b'first line\nsecond line\n')
        self.assertEqual(windows, S.source_hashes(self.root))
        self.write('gui/app.js', b'first line\nchanged line\n')
        self.assertNotEqual(windows, S.source_hashes(self.root))

    def test_refuses_changed_image(self):
        self.write('images/studio-dark.png', b'changed image')
        self.refused('Screenshot hash mismatch')

    def test_refuses_screenshot_path_traversal(self):
        self.receipt['files'].append({'path': '../private.png', 'sha256': '0' * 64})
        self.write('images/screenshots.json', self.receipt)
        self.refused('Unsafe screenshot path')

    def test_refuses_failed_installer_gate(self):
        self.artwrite('installer-report-windows-2025/results.json', {'ok': False})
        self.refused('Installer gate failed')

    def test_refuses_frozen_report_for_another_executable(self):
        self.artwrite('windows-backend-report/frozen/results.json',
                      {'checks': ['fixture'], 'page_errors': [], 'exe_sha256': 'e' * 64})
        self.refused('does not match the installer executable')

    def test_refuses_wrong_previous_windows_release(self):
        self.artwrite('installer-report-windows-2025/results.json',
                      {'ok': True, 'page_errors': [], 'installer_sha256': digest(self.installer),
                       'previous_installer_sha256': 'e' * 64})
        self.refused('Windows upgrade gate did not use the pinned previous release')

    def test_refuses_copy_changed_after_source_commit(self):
        self.write('docs/release-1.1.1.md', '# Atelier 1.1.1\nChanged after commit\n')
        self.refused('Release inputs differ from committed HEAD')

    def test_refuses_wrong_previous_linux_release(self):
        self.artwrite('linux-reports/appimage-smoke/results.json',
                      {'ok': True, 'appimage_sha256': digest(self.linux), 'previous_appimage_sha256': 'c' * 64})
        self.refused('pinned previous release')

    def test_refuses_discord_copy_over_normal_message_limit(self):
        self.write('docs/discord-1.1.1.md', '1.1.1\n' + 'x' * 2000)
        self.refused('exceeds 2000')


if __name__ == '__main__':
    unittest.main()
