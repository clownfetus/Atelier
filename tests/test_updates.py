"""Real update archives, signatures, preservation, failure recovery and handoff."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as P
from atelier import update_helper as H
from atelier import updates as U
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class UpdateFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atelier-update-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / 'installed'
        self.new = self.root / 'new'
        for folder, number, code in [(self.install, '1.1.3', b'old code'), (self.new, '1.1.4', b'new code')]:
            self.write(folder, 'Atelier.exe', code)
            self.write(folder, '_internal/version', number.encode())
            self.write(folder, '_internal/gui/app.js', code)
            self.write(folder, '_internal/python312.dll', b'stable runtime')
            self.write(folder, 'Tools/AtelierMesh/native.dll', b'stable native tool')
            self.write(folder, P.SEED, b'original seed')
        self.write(self.install, '_internal/gui/retired.js', b'removed in update')
        self.base = P.make_inventory(self.install, '1.1.3', 'a' * 40)
        self.target = P.make_inventory(self.new, '1.1.4', 'b' * 40)
        self.canaries = {'assets/projects/My project/keep.txt': b'project', 'mr_config.json': b'configuration',
                         '_webview/preferences': b'theme', 'Tools/Mappings/current.usmap': b'mapping',
                         'Tools/AES_KEY.txt': b'private key', 'Tools/shaders/custom-note.txt': b'custom tool note',
                         P.SEED: b'user updated seed'}
        for name, data in self.canaries.items():
            self.write(self.install, name, data)
        self.package = self.root / 'patch.zip'
        self.patch_record = P.make_patch(self.new, self.base, self.package)
        self.full = self.root / 'full.zip'
        with zipfile.ZipFile(self.full, 'w') as archive:
            for path in self.new.rglob('*'):
                if path.is_file():
                    archive.write(path, 'Atelier/' + path.relative_to(self.new).as_posix())
        self.private = Ed25519PrivateKey.generate()
        self.secret = base64.b64encode(self.private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.keys = {'fixture': base64.b64encode(public).decode()}
        self.feed = {'schema': 1, 'version': '1.1.4', 'source_commit': 'b' * 40,
                     'platforms': {'windows-x64': {'full': P.file_record(self.full), 'patches': [self.patch_record], 'runtime_id': self.target['runtime_id']},
                                   'linux-x64': {'full': P.file_record(self.full), 'patches': []}}}
        self.envelope = P.sign_feed(self.feed, self.secret, 'fixture')

    def write(self, root, name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def preserved(self):
        for name, data in self.canaries.items():
            self.assertEqual((self.install / name).read_bytes(), data, name)

    def stage(self, kind='patch'):
        return P.stage_windows(self.install, self.package if kind == 'patch' else self.full, self.root / 'stage', kind)

    def rewrite_zip(self, change):
        with zipfile.ZipFile(self.package) as archive:
            files = {entry.filename: archive.read(entry) for entry in archive.infolist()}
        change(files)
        with zipfile.ZipFile(self.package, 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)


class PackageTests(UpdateFixtures):
    def test_patch_contains_only_changed_application_files(self):
        with zipfile.ZipFile(self.package) as archive:
            self.assertEqual(set(archive.namelist()), {'patch.json', 'payload/Atelier.exe',
                             'payload/_internal/version', 'payload/_internal/gui/app.js'})

    def test_update_and_rollback_preserve_every_user_location(self):
        plan = self.stage()
        P.apply_windows(self.install, self.root / 'stage', plan, self.root / 'transaction')
        P.verify_files(self.install, self.target['files'])
        self.assertFalse((self.install / '_internal/gui/retired.js').exists())
        self.preserved()
        P.rollback_windows(self.root / 'transaction')
        P.verify_files(self.install, self.base['files'])
        self.assertEqual(P.load_inventory(self.install), self.base)
        self.preserved()

    def test_full_package_repairs_modified_runtime_without_touching_user_data(self):
        (self.install / '_internal/python312.dll').write_bytes(b'modified')
        plan = self.stage('full')
        P.apply_windows(self.install, self.root / 'stage', plan, self.root / 'transaction')
        P.verify_files(self.install, self.target['files'])
        self.preserved()

    def test_changed_base_rejects_delta_before_mutation(self):
        (self.install / 'Atelier.exe').write_bytes(b'locally changed')
        with self.assertRaisesRegex(ValueError, 'differs from its release'):
            self.stage()
        self.assertFalse((self.root / 'stage').exists())
        self.preserved()

    def test_wrong_base_inventory_rejected(self):
        data = P.load_inventory(self.install)
        data['source_commit'] = 'c' * 40
        P.atomic_json(self.install / P.INVENTORY, data)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.stage()

    def test_corrupted_patch_file_never_reaches_installation(self):
        self.rewrite_zip(lambda files: files.update({'payload/Atelier.exe': b'bad code'}))
        with self.assertRaises(ValueError):
            self.stage()
        P.verify_files(self.install, self.base['files'])

    def test_archive_traversal_rejected_without_writing_outside_stage(self):
        self.rewrite_zip(lambda files: files.update({'../escaped.txt': b'bad'}))
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse((self.root / 'escaped.txt').exists())
        self.assertFalse((self.root / 'stage').exists())

    def test_unexpected_archive_member_rejected(self):
        self.rewrite_zip(lambda files: files.update({'payload/mr_config.json': b'overwrite settings'}))
        with self.assertRaisesRegex(ValueError, 'Unexpected file'):
            self.stage()

    def test_duplicate_case_insensitive_archive_member_rejected(self):
        self.rewrite_zip(lambda files: files.update({'payload/ATELIER.exe': b'duplicate'}))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.stage()

    def test_forged_removal_of_user_data_rejected(self):
        def mutate(files):
            metadata = json.loads(files['patch.json'])
            metadata['removed'].append('mr_config.json')
            files['patch.json'] = P.canonical(metadata)
        self.rewrite_zip(mutate)
        with self.assertRaisesRegex(ValueError, 'operations differ'):
            self.stage()
        self.preserved()

    def test_inventory_cannot_claim_user_data(self):
        data = copy.deepcopy(self.target)
        data['files'].append({'path': 'assets/projects/keep.txt', 'bytes': 0, 'sha256': 'a' * 64})
        with self.assertRaisesRegex(ValueError, 'Invalid or duplicate'):
            P.validate_inventory(data)

    def test_inventory_rejects_duplicate_paths_and_file_directory_collisions(self):
        data = copy.deepcopy(self.target)
        row = data['files'][0].copy()
        row['path'] = row['path'].upper()
        data['files'].append(row)
        with self.assertRaises(ValueError):
            P.validate_inventory(data)
        data = copy.deepcopy(self.target)
        data['files'].append({'path': '_internal/gui', 'bytes': 0, 'sha256': 'a' * 64})
        with self.assertRaisesRegex(ValueError, 'collision'):
            P.validate_inventory(data)

    def test_reserved_absolute_and_windows_stream_paths_rejected(self):
        for name in ('/absolute', '../outside', '_internal/../../outside', 'C:/Windows/a',
                     '_internal/a:stream', '_internal/CON.txt', '_internal/trailing.', '_internal\\a', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                P.relative_name(name)

    def test_linked_destination_rejected(self):
        path = self.install / '_internal/gui'
        shutil.rmtree(path)
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            path.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks needs developer mode on this Windows runner.')
        with self.assertRaisesRegex(ValueError, 'links'):
            self.stage('full')
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_file_replace_restores_previous_version(self):
        plan = self.stage()
        original = P._replace_file
        count = 0
        def fail_once(source, target):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('simulated write failure')
            return original(source, target)
        with patch.object(P, '_replace_file', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'write failure'):
                P.apply_windows(self.install, self.root / 'stage', plan, self.root / 'transaction')
        P.verify_files(self.install, self.base['files'])
        self.preserved()

    def test_inventory_generation_rejects_accidentally_packaged_config(self):
        self.write(self.new, 'mr_config.json', b'private settings')
        with self.assertRaisesRegex(ValueError, 'Unmanaged data'):
            P.make_inventory(self.new, '1.1.4', 'b' * 40)

    def test_patch_generation_refuses_same_version(self):
        with self.assertRaisesRegex(ValueError, 'increase'):
            P.make_patch(self.new, self.target, self.root / 'same.zip')

    def test_runtime_changes_require_installer_instead_of_patching_recovery_dependencies(self):
        (self.new / '_internal/python312.dll').write_bytes(b'new interpreter')
        P.make_inventory(self.new, '1.1.4', 'b' * 40)
        with self.assertRaisesRegex(ValueError, 'runtime requires the installer'):
            P.make_patch(self.new, self.base, self.root / 'runtime.zip')


class SignatureTests(UpdateFixtures):
    def test_publisher_and_client_verify_the_same_signed_feed(self):
        self.assertEqual(P.verify_feed(self.envelope, self.keys), self.feed)

    def test_modified_signed_metadata_is_rejected(self):
        self.envelope['signed']['version'] = '1.1.5'
        with self.assertRaisesRegex(ValueError, 'signature'):
            P.verify_feed(self.envelope, self.keys)

    def test_unknown_key_and_invalid_signature_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            P.verify_feed(self.envelope, {})
        self.envelope['signature'] = 'invalid signature'
        with self.assertRaisesRegex(ValueError, 'signature'):
            P.verify_feed(self.envelope, self.keys)


class ClientTests(UpdateFixtures):
    def client(self, **kwargs):
        return U.UpdateClient(self.install, self.install / '_internal/version', self.root / 'data',
                              windows=True, keys=self.keys, **kwargs)

    def offer(self, client):
        rows = [P.file_record(self.full), self.patch_record,
                {'name': P.FEED, 'bytes': len(P.canonical(self.envelope)), 'sha256': 'f' * 64}]
        assets = {row['name']: {'name': row['name'], 'size': row['bytes'],
                  'browser_download_url': f'https://github.com/clownfetus/Atelier/releases/download/v1.1.4/{row["name"]}'} for row in rows}
        client.offer = {'version': '1.1.4', 'tag': 'v1.1.4', 'platform': 'windows-x64',
                        'target': self.feed['platforms']['windows-x64'], 'envelope': self.envelope,
                        'assets': assets}
        return assets

    def download(self, client):
        def copy_download(row, folder):
            source = self.package if row['name'] == self.package.name else self.full
            target = folder / row['name']
            shutil.copy2(source, target)
            return target
        with patch.object(client, '_download', side_effect=copy_download):
            client.download()

    def test_download_stages_patch_without_changing_running_app(self):
        client = self.client()
        self.offer(client)
        self.download(client)
        self.assertEqual(client.state, 'ready', client.error)
        self.assertEqual(client.request['kind'], 'patch')
        P.verify_files(self.install, self.base['files'])

    def test_modified_base_selects_full_update(self):
        client = self.client()
        self.offer(client)
        (self.install / '_internal/python312.dll').write_bytes(b'locally changed')
        self.download(client)
        self.assertEqual(client.state, 'ready', client.error)
        self.assertEqual(client.request['kind'], 'full')

    def test_corrupt_delta_falls_back_to_full_update(self):
        client = self.client()
        self.offer(client)
        self.package.write_bytes(b'corrupt zip')
        self.download(client)
        self.assertEqual(client.state, 'ready', client.error)
        self.assertEqual(client.request['kind'], 'full')

    def test_unofficial_and_non_https_downloads_rejected(self):
        for url in ('http://github.com/clownfetus/Atelier/releases/download/v1/a',
                    'https://github.com.evil.test/clownfetus/Atelier/releases/download/v1/a',
                    'https://github.com/another/Atelier/releases/download/v1/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                U.release_url(url)

    def test_corrupt_or_truncated_download_is_removed(self):
        client = self.client()
        self.offer(client)
        folder = self.root / 'download'
        folder.mkdir()
        with patch.object(U.urllib.request, 'urlopen', return_value=io.BytesIO(b'incomplete')):
            with self.assertRaisesRegex(ValueError, 'integrity'):
                client._download(P.file_record(self.full), folder)
        self.assertEqual(list(folder.iterdir()), [])

    def test_source_checkout_never_offers_to_replace_source_or_python(self):
        client = self.client()
        assets = self.offer(client)
        release = {'tag_name': 'v1.1.4', 'assets': list(assets.values())}
        with patch.object(U, 'read_json', return_value=release), patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(client.check(), {'available': True, 'tag': 'v1.1.4', 'manual': True})

    def test_signature_failure_does_not_silently_launch_an_installer(self):
        client = self.client()
        assets = self.offer(client)
        envelope = copy.deepcopy(self.envelope)
        envelope['signed']['version'] = '1.1.5'
        with patch.object(U, 'read_json', side_effect=[{'tag_name': 'v1.1.4', 'assets': list(assets.values())}, envelope]), \
             patch.object(sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(ValueError, 'signature'):
                client.check()

    def test_full_fallback_works_when_skipping_a_release(self):
        client = self.client()
        self.offer(client)
        client.offer['target']['patches'][0]['from_version'] = '1.1.2'
        self.download(client)
        self.assertEqual(client.request['kind'], 'full')

    def test_apply_requires_finished_download(self):
        with self.assertRaisesRegex(ValueError, 'not finished'):
            self.client().apply()

    def test_verified_download_survives_closing_and_reopening_the_app(self):
        client = self.client()
        assets = self.offer(client)
        self.download(client)
        reopened = self.client()
        with patch.object(U, 'read_json', side_effect=[{'tag_name': 'v1.1.4', 'assets': list(assets.values())}, self.envelope]), \
             patch.object(sys, 'frozen', True, create=True):
            self.assertTrue(reopened.check()['ready'])
        self.assertEqual(reopened.request['package'], client.request['package'])

    def test_saved_download_cannot_target_another_installation(self):
        client = self.client()
        self.offer(client)
        self.download(client)
        request = client.request.copy()
        request['installation'] = str(self.root / 'another-application')
        P.atomic_json(client.data_root / '_updates/ready.json', request)
        self.assertFalse(client._restore_ready())


class HelperTests(UpdateFixtures):
    def request(self):
        folder = self.root / 'data/_updates/fixture'
        folder.mkdir(parents=True)
        self.write(self.root, 'keys/update_keys.json', P.canonical(self.keys))
        package = folder / self.package.name
        shutil.copy2(self.package, package)
        request = {'kind': 'patch', 'package': str(package), 'descriptor': self.patch_record,
                   'envelope': self.envelope, 'platform': 'windows-x64', 'version': '1.1.4',
                   'installation': str(self.install), 'folder': str(folder), 'parent_pid': 999999,
                   'token': 'fixture-token', 'data_root': str(self.root / 'data')}
        path = folder / 'request.json'
        P.atomic_json(path, request)
        return path, request

    def run_helper(self, successful):
        path, request = self.request()
        process = Mock(pid=123456)
        process.poll.return_value = None
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch', return_value=process), \
             patch.object(H, 'healthy', return_value=successful), \
             patch.object(sys, '_MEIPASS', str(self.root / 'keys'), create=True):
            if successful:
                H.run(path)
            else:
                with self.assertRaisesRegex(RuntimeError, 'restored the previous'):
                    H.run(path)
                process.terminate.assert_called_once()
        return path, request

    def test_helper_commits_only_after_new_application_is_healthy(self):
        path, request = self.run_helper(True)
        P.verify_files(self.install, self.target['files'])
        self.assertEqual(json.loads((path.parent / 'transaction/journal.json').read_bytes())['state'], 'committed')
        self.assertFalse((self.root / 'data/_updates/pending.json').exists())
        self.preserved()

    def test_failed_startup_restores_old_files_and_inventory(self):
        self.run_helper(False)
        P.verify_files(self.install, self.base['files'])
        self.assertEqual(P.load_inventory(self.install), self.base)
        self.preserved()

    def test_helper_rechecks_download_digest_before_any_change(self):
        path, request = self.request()
        Path(request['package']).write_bytes(b'modified after download')
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch') as restart, patch.object(sys, '_MEIPASS', str(self.root / 'keys'), create=True):
            with self.assertRaisesRegex(ValueError, 'modified'):
                H.run(path)
        restart.assert_called_once()
        P.verify_files(self.install, self.base['files'])

    def test_backup_cleanup_only_removes_finished_owned_transactions(self):
        path, request = self.request()
        old = self.root / 'data/_updates' / ('a' * 32)
        P.atomic_json(old / 'transaction/journal.json', {'state': 'committed'})
        incomplete = self.root / 'data/_updates' / ('b' * 32)
        P.atomic_json(incomplete / 'transaction/journal.json', {'state': 'applying'})
        custom = self.root / 'data/_updates/user-files/keep.txt'
        custom.parent.mkdir()
        custom.write_text('preserve')
        H.prune_backups(request['data_root'], path.parent)
        self.assertFalse(old.exists())
        self.assertTrue(incomplete.exists())
        self.assertEqual(custom.read_text(), 'preserve')
        self.assertTrue(path.exists())


    def test_interrupted_transaction_can_be_recovered(self):
        path, request = self.request()
        plan = self.stage()
        P.apply_windows(self.install, self.root / 'stage', plan, path.parent / 'transaction')
        P.atomic_json(self.root / 'data/_updates/pending.json', {'request': str(path)})
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch') as launch:
            H.run(path, recover=True)
        launch.assert_called_once()
        P.verify_files(self.install, self.base['files'])
        self.preserved()

    def test_acknowledgement_binds_version_and_request_token(self):
        ack = self.root / 'ack.json'
        with patch.dict(os.environ, {'ATELIER_UPDATE_TOKEN': 'unique-token', 'ATELIER_UPDATE_ACK': str(ack)}):
            U.acknowledge_startup(self.new / '_internal/version')
        self.assertEqual(json.loads(ack.read_bytes()), {'token': 'unique-token', 'version': '1.1.4'})
        process = Mock()
        process.poll.return_value = 1
        request = {'folder': str(self.root), 'version': '1.1.4', 'token': 'different-token'}
        ack.rename(self.root / 'healthy.json')
        self.assertFalse(H.healthy(process, request))


class LinuxHelperTests(UpdateFixtures):
    def linux_request(self):
        folder = self.root / 'data/_updates' / ('f' * 32)
        folder.mkdir(parents=True)
        image = self.write(self.root, 'Atelier.AppImage', b'\x7fELF old AppImage')
        package = self.write(folder, 'Atelier-1.1.4.AppImage', b'\x7fELF new AppImage')
        feed = copy.deepcopy(self.feed)
        feed['platforms']['linux-x64']['full'] = P.file_record(package)
        envelope = P.sign_feed(feed, self.secret, 'fixture')
        self.write(self.root, 'keys/update_keys.json', P.canonical(self.keys))
        request = {'kind': 'full', 'package': str(package), 'descriptor': P.file_record(package),
                   'envelope': envelope, 'platform': 'linux-x64', 'version': '1.1.4',
                   'installation': str(self.install), 'folder': str(folder), 'parent_pid': 999999,
                   'token': 'linux-token', 'data_root': str(self.root / 'data'), 'image': str(image)}
        path = folder / 'request.json'
        P.atomic_json(path, request)
        return path, request

    def test_appimage_update_installs_and_keeps_user_files(self):
        path, request = self.linux_request()
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch', return_value=Mock(pid=123456)), patch.object(H, 'healthy', return_value=True), \
             patch.object(sys, '_MEIPASS', str(self.root / 'keys'), create=True):
            H.run(path)
        self.assertEqual(Path(request['image']).read_bytes(), b'\x7fELF new AppImage')
        self.assertFalse((self.root / 'data/_updates/pending.json').exists())
        self.preserved()

    def test_failed_appimage_startup_restores_previous_image(self):
        path, request = self.linux_request()
        process = Mock(pid=123456)
        process.poll.return_value = 1
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch', return_value=process), patch.object(H, 'healthy', return_value=False), \
             patch.object(sys, '_MEIPASS', str(self.root / 'keys'), create=True):
            with self.assertRaisesRegex(RuntimeError, 'restored the previous'):
                H.run(path)
        self.assertEqual(Path(request['image']).read_bytes(), b'\x7fELF old AppImage')
        self.preserved()

    def test_recovering_committed_appimage_transaction_keeps_new_version(self):
        path, request = self.linux_request()
        transaction = path.parent / 'transaction'
        self.write(transaction, 'previous.AppImage', b'\x7fELF previous')
        P.atomic_json(transaction / 'journal.json', {'state': 'committed'})
        Path(request['image']).write_bytes(b'\x7fELF committed version')
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch'):
            H.run(path, recover=True)
        self.assertEqual(Path(request['image']).read_bytes(), b'\x7fELF committed version')

    def test_cleanup_failure_does_not_roll_back_or_start_a_second_healthy_app(self):
        path, request = self.linux_request()
        with patch.object(H, 'wait_for_exit'), patch.object(H, 'launch', return_value=Mock(pid=123456)) as launch, \
             patch.object(H, 'healthy', return_value=True), patch.object(H, 'prune_backups', side_effect=OSError('busy backup file')), \
             patch.object(sys, '_MEIPASS', str(self.root / 'keys'), create=True):
            H.run(path)
        launch.assert_called_once()
        self.assertEqual(Path(request['image']).read_bytes(), b'\x7fELF new AppImage')



if __name__ == '__main__':
    unittest.main()
