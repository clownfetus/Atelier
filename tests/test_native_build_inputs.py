"""Reject changed native inputs before publication and preserve existing installs."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dotnet_bundle
import native_inputs as N
import pinned_dotnet as B
import fetch_native_inputs as F


def sha(data, algorithm='sha256'):
    return hashlib.new(algorithm, data).hexdigest()


def bundle(name='CUE4Parse.dll', data=b'fixture DLL'):
    entry = name.encode()
    header = struct.pack('<III', 6, 0, 1) + b'\0' + bytes(40)
    header += struct.pack('<qqqB', 256, len(data), 0, 1) + bytes([len(entry)]) + entry
    prefix = struct.pack('<q', 64) + dotnet_bundle.SIGNATURE
    return prefix.ljust(64, b'\0') + header.ljust(192, b'\0') + data


class NativeInputChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-native-input-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tools = self.root / 'Tools'
        mesh = self.tools / 'AtelierMesh'
        mesh.mkdir(parents=True)
        files = {'AtelierMesh.exe': bundle(), 'CUE4Parse-Natives.dll': b'native',
                 'oo2core_9_win64.dll': b'decompressor'}
        for name, data in files.items():
            (mesh / name).write_bytes(data)
        source = self.root / 'tools-src'
        (source / 'AtelierAnimation').mkdir(parents=True)
        inputs = ['global.json', 'Directory.Build.props', 'AtelierAnimation/Program.cs',
                  'AtelierAnimation/AtelierAnimation.csproj', 'AtelierAnimation/packages.lock.json']
        for name in inputs:
            (source / name).write_text('fixture ' + name, encoding='utf-8')
        self.lock = dict(schema=1, recipe={}, dotnet=dict(sdk='10.0.402', runtime='10.0.13',
            sdk_archive={'url': 'https://example.invalid/fixture-sdk.zip', 'sha512': 'fixture'}, packages=[]),
            mesh=dict(files={name: sha(data) for name, data in files.items()},
                      assemblies={'CUE4Parse.dll': sha(b'fixture DLL')}),
            managed={'AtelierAnimation': dict(project='AtelierAnimation/AtelierAnimation.csproj',
                sources={name: N.digest(source / name) for name in inputs})})
        self.lock_path = source / 'native-tools.lock.json'
        self.lock_path.write_text(json.dumps(self.lock), encoding='utf-8')
        self.output = self.root / 'output'
        self.calls = []

    def run_build(self, action=None):
        def run(command, **kwargs):
            self.calls.append((command, kwargs))
            if command[1] == '--version':
                return '10.0.402'
            if action:
                action(command, kwargs)
            if command[1] == 'publish':
                target = Path(command[command.index('-o') + 1])
                target.mkdir()
                (target / 'AtelierAnimation.exe').write_bytes(b'fixture published helper')
            return ''
        with patch.object(B, 'ROOT', self.root), patch.object(B, 'LOCK_PATH', self.lock_path), \
             patch.object(B, 'load_lock', return_value=self.lock), patch.object(B, 'checked_run', side_effect=run):
            return B.build('AtelierAnimation', self.tools, self.output)

    def test_tampered_bundle_native_and_source_stop_before_compiler_or_output(self):
        paths = [self.tools / 'AtelierMesh/AtelierMesh.exe',
                 self.tools / 'AtelierMesh/oo2core_9_win64.dll',
                 self.root / 'tools-src/AtelierAnimation/Program.cs']
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    self.run_build()
                self.assertFalse(self.output.exists())
                self.assertEqual(self.calls, [])
                path.write_bytes(original)

    def test_existing_install_remains_untouched(self):
        self.output.mkdir()
        (self.output / 'user-file').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'Output exists'):
            self.run_build()
        self.assertEqual((self.output / 'user-file').read_bytes(), b'keep')
        self.assertEqual(self.calls, [])

    def test_wrong_sdk_is_rejected(self):
        with patch.object(B, 'ROOT', self.root), patch.object(B, 'load_lock', return_value=self.lock), \
             patch.object(B, 'checked_run', return_value='10.0.403'):
            with self.assertRaisesRegex(ValueError, 'exactly .NET SDK 10.0.402'):
                B.build('AtelierAnimation', self.tools, self.output)
        self.assertFalse(self.output.exists())

    def test_restore_failure_never_publishes_partial_helper(self):
        def fail(command, _kwargs):
            if command[1] == 'restore':
                raise RuntimeError('fixture restore failure')
        with self.assertRaisesRegex(RuntimeError, 'restore failure'):
            self.run_build(fail)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.atelier-native-build-*')), [])

    def test_build_uses_private_packages_offline_restore_and_records_source_and_outputs(self):
        record = self.run_build()
        restore, publish = self.calls[1:]
        self.assertIn('--locked-mode', restore[0])
        self.assertIn('--no-restore', publish[0])
        self.assertIn('--source', restore[0])
        self.assertTrue(Path(restore[1]['env']['NUGET_PACKAGES']).is_relative_to(self.root))
        self.assertEqual(record['sources'], self.lock['managed']['AtelierAnimation']['sources'])
        self.assertEqual(record['lock_sha256'], N.digest(self.lock_path))
        self.assertEqual(record['outputs']['AtelierAnimation.exe'], N.digest(self.output / 'AtelierAnimation.exe'))
        self.assertEqual((self.output / 'oo2core_9_win64.dll').read_bytes(), b'decompressor')
        self.assertNotIn(str(self.root), (self.output / 'build-inputs.json').read_text())

    def test_modified_cached_nuget_archive_is_rejected_before_restore(self):
        cached = self.root / 'cache/example/1.0'
        cached.mkdir(parents=True)
        (cached / 'example.1.0.nupkg').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'NuGet archive SHA-512 mismatch'):
            B.prepare_feed(self.root / 'feed',
                           [dict(name='example', version='1.0', sha512=sha(b'expected', 'sha512'))],
                           cache=self.root / 'cache')

    def test_verified_archive_is_copied_without_using_extracted_global_cache(self):
        cached = self.root / 'cache/example/1.0'
        cached.mkdir(parents=True)
        (cached / 'example.1.0.nupkg').write_bytes(b'verified archive')
        (cached / 'example.dll').write_bytes(b'poisoned extracted assembly')
        B.prepare_feed(self.root / 'feed',
                       [dict(name='example', version='1.0', sha512=sha(b'verified archive', 'sha512'))],
                       cache=self.root / 'cache')
        self.assertEqual([p.name for p in (self.root / 'feed').iterdir()], ['example.1.0.nupkg'])

    def test_lock_cannot_reference_files_outside_input_directory(self):
        outside = self.root / 'outside.dll'
        outside.write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'unsafe pinned input'):
            N.verify_files(self.tools, {'../outside.dll': N.digest(outside)})

    def test_bundle_cannot_extract_a_traversal_entry(self):
        (self.root / 'bad.exe').write_bytes(bundle('../outside.dll'))
        with self.assertRaisesRegex(ValueError, 'Invalid bundle entry'):
            dotnet_bundle.extract_assemblies(self.root / 'bad.exe', self.root / 'libraries')
        self.assertFalse((self.root / 'outside.dll').exists())

    def test_shader_hash_is_checked_before_executing_help(self):
        folder = self.tools / 'shaders'
        folder.mkdir()
        (folder / 'retoc-rivals-cli.exe').write_bytes(b'wrong version with familiar name')
        lock = dict(shader=dict(files={'retoc-rivals-cli.exe': sha(b'expected custom shader fork')}))
        with patch.object(N.subprocess, 'run') as execute:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                N.verify_shaders(self.tools, lock)
            execute.assert_not_called()

    def seed(self, changed=False):
        archive = self.root / 'seed.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            for name in self.lock['mesh']['files']:
                output.write(self.tools / 'AtelierMesh' / name, 'Tools/AtelierMesh/' + name)
            output.writestr('Tools/shaders/retoc-rivals-cli.exe', b'changed' if changed else b'fixture shader')
            output.writestr('Tools/AES_KEY.txt', b'fixture private configuration - exclude')
            output.writestr('../outside.txt', b'fixture traversal entry - exclude')
        self.lock['seed'] = {'sha256': N.digest(archive)}
        self.lock['shader'] = dict(files={'retoc-rivals-cli.exe': sha(b'fixture shader')},
                                   source={'status': 'unavailable'})
        return archive

    def test_seed_extracts_only_pinned_tools_excluding_configuration_and_traversal(self):
        archive = self.seed()
        F.stage_seed(archive, self.output, self.lock)
        self.assertEqual((self.output / 'shaders/retoc-rivals-cli.exe').read_bytes(), b'fixture shader')
        self.assertFalse((self.output / 'AES_KEY.txt').exists())
        self.assertFalse((self.root / 'outside.txt').exists())
        self.assertEqual(set(path.name for path in self.output.iterdir()),
                         {'AtelierMesh', 'shaders', 'input-provenance.json'})

    def test_changed_seed_is_rejected_without_creating_output(self):
        archive = self.seed()
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'seed SHA-256 mismatch'):
            F.stage_seed(archive, self.output, self.lock)
        self.assertFalse(self.output.exists())

    def test_changed_member_is_rejected_before_publication(self):
        archive = self.seed(changed=True)
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            F.stage_seed(archive, self.output, self.lock)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.atelier-inputs-*')), [])

    def test_seed_stager_preserves_existing_tool_installation(self):
        archive = self.seed()
        self.output.mkdir()
        (self.output / 'user-file').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'Output exists'):
            F.stage_seed(archive, self.output, self.lock)
        self.assertEqual((self.output / 'user-file').read_bytes(), b'keep')

    def test_repository_locks_all_managed_sources_and_discloses_missing_shader_source(self):
        lock = N.load_lock()
        N.verify_files(ROOT, lock['recipe'])
        for tool, project in lock['managed'].items():
            self.assertIn(f'{tool}/packages.lock.json', project['sources'])
            N.verify_files(ROOT / 'tools-src', project['sources'])
        sdk = json.loads((ROOT / 'tools-src/global.json').read_text())['sdk']
        self.assertEqual(sdk['version'], lock['dotnet']['sdk'])
        self.assertEqual(sdk['rollForward'], 'disable')
        self.assertEqual(lock['shader']['source']['status'], 'unavailable')
        self.assertIsNone(lock['shader']['source']['revision'])
        self.assertEqual(len(lock['shader']['files']['retoc-rivals-cli.exe']), 64)


if __name__ == '__main__':
    unittest.main()
