"""Install warnings with small real PAK and IoStore directory indexes."""
import atexit
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
data = tempfile.TemporaryDirectory(prefix='atelier-install-conflicts-')
os.environ['ATELIER_DATA_DIR'] = data.name
from atelier import config, legacy_pak
from atelier.handlers.container_merge import serialize_dir_index
from atelier.web import routes
from fake_paks import write as write_toc


def cleanup():
    routes.shutdown(5)
    data.cleanup()


atexit.register(cleanup)


def write_pak(path, names=(), mount='../../../'):
    def fstring(text):
        encoded = text.encode('ascii') + b'\0'
        return struct.pack('<i', len(encoded)) + encoded

    directories = {}
    for name in names:
        folder, _, basename = name.rpartition('/')
        directories.setdefault(folder + '/' if folder else '', []).append(basename)
    index_prefix = fstring(mount) + struct.pack('<iQII', len(names), 0, 0, 1)
    index_names = struct.pack('<i', len(directories))
    for folder, basenames in directories.items():
        index_names += fstring(folder) + struct.pack('<i', len(basenames))
        index_names += b''.join(fstring(name) + struct.pack('<i', 0) for name in basenames)
    index = index_prefix + struct.pack('<qq20x', len(index_prefix) + 36, len(index_names))
    footer = struct.pack('<17xIiqq180x', legacy_pak.MAGIC, 11, 0, len(index))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(index + index_names + footer)
    return path


def write_iostore(base, names, mount='../../../', loose=()):
    pak = write_pak(base.with_suffix('.pak'), loose)
    toc = base.with_suffix('.utoc')
    write_toc(str(toc), serialize_dir_index(list(zip(names, range(len(names)))), mount=mount))
    data = base.with_suffix('.ucas')
    data.write_bytes(b'Fixture payload')
    return pak, toc, data


def request(path, body=None, project='A', query=''):
    env = {}
    setup_testing_defaults(env)
    payload = json.dumps(body).encode() if body is not None else b''
    env.update(REQUEST_METHOD='POST' if body is not None else 'GET', PATH_INFO=path,
               QUERY_STRING=query, CONTENT_TYPE='application/json' if body is not None else '',
               CONTENT_LENGTH=str(len(payload)), HTTP_X_ATELIER_PROJECT=project,
               **{'wsgi.input': io.BytesIO(payload)})
    status = []
    result = routes.app(env, lambda s, h, exc_info=None: status.append(s))
    try:
        raw = b''.join(result)
    finally:
        if hasattr(result, 'close'):
            result.close()
    return int(status[0].split()[0]), json.loads(raw)


class Scan(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=data.name)
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.mods = self.root / 'mods'
        self.src = self.root / 'exported'

    def scan(self, sources):
        from atelier.install_conflicts import scan
        return scan(sources, self.mods)

    def test_cross_format_matches_keep_export_spelling_and_collapse_package_companions(self):
        target = write_pak(self.src / 'My Mod.pak', ['Marvel/MI_Body.uasset', 'Marvel/MI_Body.uexp'],
                           mount='../../../Marvel/Content/')
        write_iostore(self.mods / 'Skins' / 'Existing', ['marvel/mi_body.ubulk'], mount='//GAME/./')
        result = self.scan([target])
        self.assertEqual(result['conflicts'], [{
            'mod': 'Skins/Existing.pak', 'paths': ['../../../Marvel/Content/Marvel/MI_Body.uasset'],
        }])
        self.assertEqual(result['unreadable'], [])

    def test_disabled_and_replaced_bundles_are_excluded_but_nested_names_are_distinct(self):
        entries = ['Marvel/Content/Marvel/T_Body.uasset']
        target = write_iostore(self.src / 'New', entries, loose=['patched_files', 'chunknames'])
        write_iostore(self.mods / 'New', entries)
        write_iostore(self.mods / 'Nested' / 'New', entries)
        for index, suffix in enumerate(('.bak_repak', '.PAK_DISABLED', '.pak.disabled')):
            pak, _, _ = write_iostore(self.mods / f'Disabled {index}', entries)
            pak.rename(pak.with_suffix(suffix))
        write_pak(self.mods / 'Metadata only.pak', ['PATCHED_FILES', 'CHUNKNAMES'])
        result = self.scan(target)
        self.assertEqual([item['mod'] for item in result['conflicts']], ['Nested/New.pak'])
        self.assertEqual(result['unreadable'], [])

    def test_loose_files_in_a_pak_companion_are_checked_even_when_the_toc_is_unreadable(self):
        target = write_pak(self.src / 'New.pak', ['Marvel/Content/Marvel/Audio/Voice.wem'])
        _, toc, _ = write_iostore(self.mods / 'Hybrid', ['Content/Unused.uasset'],
                                  loose=['Game/Marvel/Audio/voice.WEM'])
        toc.write_bytes(b'Invalid toc')
        result = self.scan([target])
        self.assertEqual([item['mod'] for item in result['conflicts']], ['Hybrid.pak'])
        self.assertEqual([item['file'] for item in result['unreadable']], ['Hybrid.utoc'])

    def test_plugin_and_game_mounts_keep_their_own_packages(self):
        target = write_pak(self.src / 'New.pak', ['Marvel/Plugins/MarvelGAS/Content/UI/T_A.uasset'])
        write_pak(self.mods / 'Game mount.pak', ['Marvel/Content/UI/T_A.uasset'])
        write_iostore(self.mods / 'Plugin mount', ['UI/T_A.uasset'], mount='/MarvelGAS/')
        self.assertEqual([item['mod'] for item in self.scan([target])['conflicts']], ['Plugin mount.pak'])

    def test_truncated_iostore_table_cannot_be_reported_as_an_empty_read(self):
        target = write_pak(self.src / 'New.pak', ['Marvel/Content/Marvel/T_Body.uasset'])
        toc = self.mods / 'Truncated.utoc'
        self.mods.mkdir()
        write_toc(str(toc), b'')
        corrupt = bytearray(toc.read_bytes())
        struct.pack_into('<I', corrupt, 36, 5)  # advertised compression-method table is absent
        toc.write_bytes(corrupt)
        self.assertEqual([item['file'] for item in self.scan([target])['unreadable']], ['Truncated.utoc'])

    def test_reader_loads_the_configured_tools_key_on_a_cold_import(self):
        tools = self.root / 'Tools'
        tools.mkdir()
        (tools / 'AES_KEY.txt').write_text('ab' * 32, encoding='ascii')
        env = dict(os.environ, ATELIER_DATA_DIR=str(self.root))
        env.pop('MR_TOOLS', None)
        check = subprocess.run([sys.executable, '-B', '-c',
                                'from atelier import install_conflicts; import io_lib; '
                                'assert io_lib.AES_KEY == b"\\xab" * 32'],
                               env=env, cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(check.returncode, 0, check.stderr)


class Install(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=data.name)
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.export = self.root / 'exported'
        self.mods = self.root / 'mods'
        self.current_mods = self.mods
        self.projects = self.root / 'projects'
        for project in ('A', 'B'):
            (self.projects / project).mkdir(parents=True)
        settings = patch.multiple(routes, ASSETS_MODS=str(self.export), PROJECTS_ROOT=str(self.projects),
                                  get_mods_folder=lambda: str(self.current_mods))
        settings.start()
        self.addCleanup(settings.stop)
        context = patch.object(config, 'PROJECTS_ROOT', str(self.projects))
        context.start()
        self.addCleanup(context.stop)
        self.entries = ['Marvel/Content/Marvel/MI_Chest.uasset']
        self.files = write_iostore(self.export / 'Demo_9999999_P', self.entries)
        build = patch.object(routes, 'build_mod', return_value={
            'ok': True, 'pak': str(self.files[0]), 'artifacts': list(map(str, self.files)),
            'applied': ['Chest material'], 'skipped': ['Skipped fixture edit'],
        })
        self.build = build.start()
        self.addCleanup(build.stop)

    def build_request(self, **extra):
        return request('/api/install_mod', {'mod_name': 'Demo', 'items': ['Characters/MI_Chest'],
                                            'copy_to_mods': True, **extra})[1]

    def decide(self, token, install=True, project='A', **extra):
        return request('/api/install_mod/confirm', {'token': token, 'install': install, **extra}, project)[1]

    def pending_result(self):
        write_pak(self.mods / 'Other.pak', self.entries)
        result = self.build_request()
        self.assertTrue(result['ok'], result)
        self.assertFalse((self.mods / self.files[0].name).exists())
        self.assertEqual(result['install_warning']['conflicts'][0]['mod'], 'Other.pak')
        return result

    def test_accept_resumes_the_built_export_in_the_owning_project_and_consumes_the_token(self):
        result = self.pending_result()
        token = result['install_token']
        self.assertFalse(self.decide(token, project='B')['ok'])
        self.assertFalse((self.mods / self.files[0].name).exists())
        installed = self.decide(token, artifacts=['other.pak'], destination='Unconfigured')
        self.assertTrue(installed['ok'], installed)
        self.assertEqual(installed['applied'], ['Chest material'])
        self.assertEqual(installed['skipped'], ['Skipped fixture edit'])
        for source in self.files:
            self.assertEqual((self.mods / source.name).read_bytes(), source.read_bytes())
        self.assertFalse(self.decide(token)['ok'])
        self.build.assert_called_once()

    def test_keep_export_only_disarms_the_pending_install(self):
        result = self.pending_result()
        self.assertTrue(self.decide(result['install_token'], install=False)['ok'])
        self.assertFalse(self.decide(result['install_token'])['ok'])
        self.assertFalse((self.mods / self.files[0].name).exists())
        self.assertTrue(all(source.exists() for source in self.files))
        self.build.assert_called_once()

    def test_concurrent_approvals_publish_once(self):
        token = self.pending_result()['install_token']
        ready = Barrier(2, timeout=5)

        def approve():
            ready.wait()
            return self.decide(token)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = [pool.submit(approve) for _ in range(2)]
            results = [reply.result(timeout=15) for reply in replies]
        self.assertEqual(sum(bool(result.get('installed_dir')) for result in results), 1)
        self.assertEqual(sum(result['ok'] for result in results), 1)
        self.build.assert_called_once()

    def test_a_new_conflicting_mod_requires_updated_confirmation(self):
        result = self.pending_result()
        write_pak(self.mods / 'Added while waiting.pak', self.entries)
        rescanned = self.decide(result['install_token'])
        self.assertTrue(rescanned['ok'], rescanned)
        self.assertNotEqual(rescanned['install_token'], result['install_token'])
        self.assertEqual([m['mod'] for m in rescanned['install_warning']['conflicts']],
                         ['Added while waiting.pak', 'Other.pak'])
        self.assertFalse((self.mods / self.files[0].name).exists())
        self.assertIn('installed_dir', self.decide(rescanned['install_token']))
        self.build.assert_called_once()

    def test_pending_install_cannot_use_changed_destination_or_export_files(self):
        for changed in ('mods folder', 'export files'):
            with self.subTest(changed=changed):
                result = self.pending_result()
                if changed == 'mods folder':
                    self.current_mods = self.root / 'New folder'
                else:
                    self.files[2].write_bytes(b'Replaced file after review')
                response = self.decide(result['install_token'])
                self.assertFalse(response['ok'])
                self.assertFalse((self.current_mods / self.files[0].name).exists())
                self.current_mods = self.mods

    def test_unreadable_bundles_require_consent_and_export_only_never_copies(self):
        self.mods.mkdir()
        (self.mods / 'Unreadable.pak').write_bytes(b'Broken pak')
        result = self.build_request(copy_to_mods=False)
        self.assertNotIn('install_token', result)
        result = self.build_request()
        self.assertEqual(result['install_warning']['unreadable'][0]['file'], 'Unreadable.pak')
        self.assertFalse((self.mods / self.files[0].name).exists())

    def test_an_approved_filename_replacement_does_not_raise_an_overlap_warning(self):
        write_iostore(self.mods / 'Demo_9999999_P', self.entries)
        _, preflight = request('/api/check_mod_conflict', query='mod_name=Demo&copy_to_mods=1')
        self.assertTrue(preflight['default'])
        self.assertTrue(preflight['mods'])
        result = self.build_request(replacement_check=preflight['replacement_check'])
        self.assertTrue(result['ok'], result)
        self.assertIn('installed_dir', result)
        self.assertNotIn('install_token', result)

    def test_a_filename_collision_appearing_after_preflight_also_requires_consent(self):
        _, preflight = request('/api/check_mod_conflict', query='mod_name=Demo&copy_to_mods=1')
        self.assertFalse(preflight['mods'])
        write_iostore(self.mods / 'Demo_9999999_P', self.entries)
        result = self.build_request()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['install_warning']['replacements'], sorted(p.name for p in self.files))
        self.assertEqual(result['install_warning']['conflicts'], [])

    def test_an_existing_replacement_changed_while_waiting_requires_new_consent(self):
        original = write_iostore(self.mods / 'Demo_9999999_P', self.entries)
        result = self.build_request()
        original[2].write_bytes(b'Another installed revision')
        refreshed = self.decide(result['install_token'])
        self.assertNotEqual(refreshed['install_token'], result['install_token'])
        self.assertEqual(original[2].read_bytes(), b'Another installed revision')
        self.assertEqual(refreshed['install_warning']['replacements'], result['install_warning']['replacements'])
        self.assertIn('installed_dir', self.decide(refreshed['install_token']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
