"""Source-build provenance, poisoned-cache rejection and private shader credentials."""
import hashlib
import io
import json
import os
import stat
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
import build_shader_tool as B
import toolchain as T
from atelier import config as C


class ShaderBuildInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-shader-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_source_lock_identifies_the_complete_cargo_graph_and_reconstruction(self):
        lock = B.load_shader_lock()
        native = T.tool(T.load_lock(), 'retoc-shaders')
        self.assertEqual((native['kind'], native['builder'], native['platforms']), ('build', 'atelier-shader', ['windows']))
        self.assertIn('shaders/build-inputs.json', native['files']['windows'])
        self.assertEqual(set(native['probe']['expect']), set(B.COMMANDS))
        self.assertEqual(B.SOURCE, ROOT / 'native/AtelierShader')
        self.assertEqual(len(lock['compiler']['rust_commit']), 40)
        self.assertIn('Cargo.lock', lock['sources'])
        self.assertEqual(set(B.COMMANDS), {'dump-shaders', 'extract-shader', 'patch-shader', 'unpack', 'pack', 'info'})
        for pin in lock['upstream'].values():
            self.assertEqual(len(pin['revision']), 40)
            self.assertTrue(pin['url'].endswith(pin['revision']))

    def test_changed_sources_stop_before_network_compilers_or_output(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'Cargo.lock').write_text('changed lock')
        lock = dict(schema=1, recipe={}, sources={'Cargo.lock': hashlib.sha256(b'expected').hexdigest()})
        path = self.root / 'build.lock.json'
        path.write_text(json.dumps(lock))
        with patch.object(B, 'SOURCE', source), patch.object(B, 'LOCK', path), patch.object(B.urllib.request, 'urlopen') as network, \
             patch.object(B.subprocess, 'run') as compiler:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                B.load_shader_lock()
            network.assert_not_called()
            compiler.assert_not_called()

    def test_modified_cached_archives_are_rejected_instead_of_executed(self):
        cache = self.root / 'cache'
        cache.mkdir()
        expected = hashlib.sha256(b'known compiler').hexdigest()
        (cache / (expected + '.zip')).write_bytes(b'changed compiler')
        with patch.object(B.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'Cached.*SHA-256 mismatch'):
                B.archive_input(dict(url='https://example.invalid/compiler.zip', sha256=expected), cache)
            network.assert_not_called()

    def test_cold_cache_download_publishes_only_the_verified_archive(self):
        payload = b'fresh pinned compiler fixture'
        cache = self.root / 'cold-cache'
        pin = dict(url='https://example.invalid/compiler.zip', sha256=hashlib.sha256(payload).hexdigest())
        with patch.object(B.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as network:
            path = B.archive_input(pin, cache)
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(list(cache.iterdir()), [path])
            self.assertEqual(path.name, pin['sha256'] + '.zip')
            # A subsequent build must use the validated cache without downloading.
            self.assertEqual(B.archive_input(pin, cache), path)
            network.assert_called_once()

    def test_cold_cache_wrong_hash_leaves_no_published_or_partial_file(self):
        cache = self.root / 'bad-download'
        pin = dict(url='https://example.invalid/compiler.zip', sha256=hashlib.sha256(b'expected').hexdigest())
        with patch.object(B.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong bytes')):
            with self.assertRaisesRegex(ValueError, 'Downloaded.*SHA-256 mismatch'):
                B.archive_input(pin, cache)
        self.assertEqual(list(cache.iterdir()), [])

    def test_interrupted_cold_cache_stream_leaves_no_partial_file(self):
        class Interrupted(io.BytesIO):
            def read(self, count=-1):
                if self.tell():
                    raise OSError('fixture interrupted download')
                return super().read(3)
        cache = self.root / 'interrupted-download'
        pin = dict(url='https://example.invalid/compiler.zip', sha256='0' * 64)
        with patch.object(B.urllib.request, 'urlopen', return_value=Interrupted(b'partial bytes')):
            with self.assertRaisesRegex(OSError, 'interrupted download'):
                B.archive_input(pin, cache)
        self.assertEqual(list(cache.iterdir()), [])

    def test_zip_paths_cannot_escape_the_private_build(self):
        for index, name in enumerate(['../escape', '/absolute', 'C:/absolute', 'dir/../../escape', 'dir\\..\\escape']):
            with self.subTest(name=name):
                archive = self.root / f'{index}.zip'
                with zipfile.ZipFile(archive, 'w') as stream:
                    stream.writestr(name, b'untrusted')
                with self.assertRaisesRegex(ValueError, 'Unsafe path'):
                    B.extract_archive(archive, self.root / f'out-{index}')
        self.assertFalse((self.root / 'escape').exists())

    def test_changed_upstream_patch_anchor_is_rejected(self):
        source = self.root / 'upstream.rs'
        source.write_text('upstream changed')
        with self.assertRaisesRegex(ValueError, 'patch anchor changed'):
            B.replace_exact(source, 'expected', 'patched')
        self.assertEqual(source.read_text(), 'upstream changed')

    def test_upstream_runtime_defaults_and_key_test_literals_are_removed(self):
        library = self.root / 'library'
        (library / 'src').mkdir(parents=True)
        key = 'a1' * 32
        (library / 'src/lib.rs').write_text('        default_value = "' + key + '"\n')
        (library / 'src/iostore_writer.rs').write_text('''                const DEFAULT_AES_KEY: &str =
                    "''' + key + '''";
                let default_key;
                let key = if let Some(key) = self.aes_key.as_ref() { key } else { &default_key };
                let padded_len = 0;
let fixture = "''' + key + '''".parse()?;
''')
        B.remove_upstream_key_defaults(library)
        for path in (library / 'src').glob('*.rs'):
            self.assertNotIn(key, path.read_text())
        self.assertIn('require an explicit key', (library / 'src/iostore_writer.rs').read_text())

    def test_source_changed_during_copy_is_rejected_before_archive_access(self):
        source = self.root / 'live-source'
        source.mkdir()
        (source / 'program.rs').write_bytes(b'verified source')
        work = self.root / 'work'
        work.mkdir()
        original_copy = shutil.copyfile
        def concurrent_edit(src, dst):
            Path(src).write_bytes(b'changed while the build started')
            return original_copy(src, dst)
        lock = dict(sources={'program.rs': hashlib.sha256(b'verified source').hexdigest()})
        with patch.object(B, 'SOURCE', source), patch.object(B.shutil, 'copyfile', side_effect=concurrent_edit), \
             patch.object(B, 'archive_input') as download:
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                B.prepare_source(work, lock, self.root / 'cache', self.root / 'native.dll')
            download.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Portable compiler publication targets Windows')
    def test_provenance_keeps_the_original_input_lock_when_the_checkout_changes(self):
        tools = self.root / 'Tools/shaders'
        tools.mkdir(parents=True)
        (tools / 'oo2core_9_win64.dll').write_bytes(b'fixture native')
        lock = dict(schema=1, sources={}, recipe={}, upstream={}, git_dependencies={},
                    compiler={'rust_commit': 'a' * 40}, native_files={'oo2core_9_win64.dll': B.digest(tools / 'oo2core_9_win64.dll')})
        path = self.root / 'build.lock.json'
        original_lock = json.dumps(lock).encode()
        path.write_bytes(original_lock)
        def source(work, *_args):
            project = work / 'source'
            (project / 'licenses').mkdir(parents=True)
            (project / 'upstream').mkdir()
            original = tools / 'oo2core_9_win64.dll'
            shutil.copyfile(original, project / 'upstream/oo2core_9_win64.dll')
            (work / 'target/release').mkdir(parents=True)
            (work / 'target/release/retoc-rivals-cli.exe').write_bytes(b'fixture executable')
            return project
        def run(_args, _project, _env, _log):
            path.write_text('{"changed":true}')
            return 'commit-hash: ' + 'a' * 40
        with patch.object(B, 'LOCK', path), patch.object(B, 'load_shader_lock', return_value=lock), \
             patch.object(B, 'prepare_source', side_effect=source), \
             patch.object(B, 'prepare_compiler', return_value=(self.root / 'rust', self.root / 'llvm')), \
             patch.object(B, 'checked_run', side_effect=run):
            result = B.build(self.root / 'Tools', self.root / 'published', self.root / 'cache', self.root / 'build.log')
        self.assertEqual(result['build_lock_sha256'], hashlib.sha256(original_lock).hexdigest())
        self.assertNotEqual(result['build_lock_sha256'], B.digest(path))

    def test_installed_build_is_reused_only_while_lock_and_outputs_match(self):
        folder = self.root / 'shaders'
        folder.mkdir()
        (folder / 'retoc-rivals-cli.exe').write_bytes(b'fixture executable')
        lock = dict(schema=1, sources={'a': '1'}, recipe={}, upstream={}, compiler={}, git_dependencies={}, native_files={})
        lock_bytes = json.dumps(lock).encode()
        manifest = dict(tool='AtelierShader', build_lock_sha256=hashlib.sha256(lock_bytes).hexdigest(), **{
            k: v for k, v in lock.items() if k != 'schema'}, outputs={'retoc-rivals-cli.exe': B.digest(folder / 'retoc-rivals-cli.exe')})
        (folder / 'build-inputs.json').write_text(json.dumps(manifest))
        self.assertTrue(B.provenance_matches(folder, lock_bytes))
        changed_lock = json.dumps(dict(lock, sources={'a': '2'})).encode()
        self.assertFalse(B.provenance_matches(folder, changed_lock))
        (folder / 'retoc-rivals-cli.exe').write_bytes(b'tampered')
        self.assertFalse(B.provenance_matches(folder, lock_bytes))
        self.assertFalse(B.provenance_matches(self.root / 'missing', lock_bytes))

    def test_failed_build_cleanup_handles_windows_long_cargo_paths(self):
        workspace = None
        with self.assertRaisesRegex(RuntimeError, 'fixture build failure'):
            with B.build_workspace(self.root) as work:
                workspace = work
                prefix = '\\\\?\\' + str(work.resolve()) if os.name == 'nt' else str(work)
                nested = Path(prefix) / ('a' * 180) / ('b' * 120)
                nested.mkdir(parents=True)
                cached = nested / 'cached-crate.rs'
                cached.write_text('fixture')
                cached.chmod(stat.S_IREAD)
                raise RuntimeError('fixture build failure')
        self.assertFalse(workspace.exists())

    def test_existing_install_is_preserved_before_loading_compiler_inputs(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'user-file').write_bytes(b'keep')
        with patch.object(B, 'load_shader_lock') as inputs:
            with self.assertRaisesRegex(ValueError, 'Output exists|Windows x64'):
                B.build(self.root, output, self.root / 'cache', self.root / 'log')
            inputs.assert_not_called()
        self.assertEqual((output / 'user-file').read_bytes(), b'keep')

    def test_shader_key_uses_the_current_config_without_mutating_the_parent_environment(self):
        with patch.dict(os.environ, {'ATELIER_RETOC_AES_KEY': 'stale fixture'}), \
             patch.object(C, 'get_aes_key', return_value='current fixture'):
            env = C.retoc_env()
            self.assertEqual(env['ATELIER_RETOC_AES_KEY'], 'current fixture')
            self.assertEqual(os.environ['ATELIER_RETOC_AES_KEY'], 'stale fixture')
        with patch.dict(os.environ, {'ATELIER_RETOC_AES_KEY': 'stale fixture'}), patch.object(C, 'get_aes_key', return_value=''):
            self.assertNotIn('ATELIER_RETOC_AES_KEY', C.retoc_env())


if __name__ == '__main__':
    unittest.main()
