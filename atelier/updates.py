"""Signed GitHub releases, staged downloads and explicit restart to install."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import uuid
import zipfile

from atelier import update_protocol as protocol

REPOSITORY = 'clownfetus/Atelier'
RELEASE_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_METADATA = 4 * 1024 * 1024
MAX_DOWNLOAD = 8 * 1024 * 1024 * 1024


def release_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment or not parsed.path.startswith(f'/{REPOSITORY}/releases/download/'):
        raise ValueError('Update download is not an official Atelier release.')
    return url


def read_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Atelier-Updater'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise ValueError('Update metadata is too large.')
    return json.loads(raw)


def clean_environment():
    env = dict(os.environ)
    bundle = str(getattr(sys, '_MEIPASS', '')).rstrip('/\\')
    if bundle:
        for name in ('PATH', 'GI_TYPELIB_PATH', 'GIO_MODULE_DIR', 'GSETTINGS_SCHEMA_DIR',
                     'GDK_PIXBUF_MODULE_FILE', 'GDK_PIXBUF_MODULEDIR', 'GTK_DATA_PREFIX',
                     'GTK_EXE_PREFIX', 'GTK_PATH', 'XDG_DATA_DIRS'):
            kept = [entry for entry in env.get(name, '').split(os.pathsep) if entry and
                    entry != bundle and not entry.startswith((bundle + '/', bundle + '\\'))]
            if kept:
                env[name] = os.pathsep.join(kept)
            else:
                env.pop(name, None)
    for name in list(env):
        if name.startswith('_PYI_') or name in {'APPDIR', 'APPIMAGE', 'APPIMAGE_EXTRACT_AND_RUN',
                                               'ATELIER_UPDATE_ACK', 'ATELIER_UPDATE_TOKEN'}:
            env.pop(name, None)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    original = env.pop('LD_LIBRARY_PATH_ORIG', None)
    if original is None:
        env.pop('LD_LIBRARY_PATH', None)
    else:
        env['LD_LIBRARY_PATH'] = original
    return env


def detached(command, **kwargs):
    options = {'close_fds': True, 'env': clean_environment()}
    options.update(kwargs)
    if os.name == 'nt':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        # A frozen app's DLL search directory is inherited by child processes.
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(command, **options)
        finally:
            if getattr(sys, 'frozen', False):
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
    options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def acknowledge_startup(version_file):
    """Called by the usable frontend, not merely by a listening HTTP socket."""
    token, ack = os.environ.get('ATELIER_UPDATE_TOKEN'), os.environ.get('ATELIER_UPDATE_ACK')
    if token and ack:
        protocol.atomic_json(Path(ack), {'token': token, 'version': Path(version_file).read_text().strip()})


class UpdateClient:
    def __init__(self, installation, version_file, data_root, windows=None, image=None, keys=None):
        self.installation = Path(installation).absolute()
        self.version_file = Path(version_file)
        self.data_root = Path(data_root).absolute()
        self.windows = os.name == 'nt' if windows is None else windows
        self.image = Path(image or os.environ['APPIMAGE']).absolute() if image or os.environ.get('APPIMAGE') else None
        self.keys = keys
        self.lock = threading.Lock()
        self.state = 'idle'
        self.error = ''
        self.progress = {'pct': 0, 'bytes': 0, 'total': 0}
        self.offer = None
        self.request = None

    def _keys(self):
        if self.keys is not None:
            return self.keys
        path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'update_keys.json'
        return json.loads(path.read_bytes())

    def check(self):
        with self.lock:
            if self.state in {'downloading', 'ready', 'applying'} and self.offer:
                return {'available': True, 'tag': self.offer['tag'], 'ready': self.state == 'ready',
                        'patch': bool(self.offer.get('target'))}
            return self._check()

    def _check(self):
        current = self.version_file.read_text(encoding='utf-8').strip()
        protocol.version(current)
        release = read_json(RELEASE_API)
        tag = release.get('tag_name', '')
        remote = tag.removeprefix('v')
        if release.get('draft') or release.get('prerelease') or protocol.version(remote) <= protocol.version(current):
            return {'available': False}
        assets = {asset['name']: asset for asset in release.get('assets', [])}
        page = f'https://github.com/{REPOSITORY}/releases/tag/{urllib.parse.quote(tag, safe="")}'
        self.offer = {'tag': tag, 'release_url': page, 'assets': assets, 'version': remote}
        # Source checkouts must never replace their Python installation or source.
        frozen = getattr(sys, 'frozen', False)
        supported = platform.machine().lower() in {'amd64', 'x86_64'}
        native = frozen and supported and (self.windows or self.image is not None)
        if not self.windows and native:
            native = self.image.is_file() and not self.image.is_symlink() and os.access(self.image.parent, os.W_OK)
        if protocol.FEED in assets and native:
            envelope = read_json(release_url(assets[protocol.FEED]['browser_download_url']))
            feed = protocol.verify_feed(envelope, self._keys())
            if feed['version'] != remote:
                raise ValueError('Update feed and release tag disagree.')
            target_platform = 'windows-x64' if self.windows else 'linux-x64'
            target = feed.get('platforms', {}).get(target_platform)
            if not target:
                return {'available': True, 'tag': tag, 'manual': True}
            self.offer.update(envelope=envelope, target=target, platform=target_platform)
            if self.windows:
                try:
                    installed = protocol.load_inventory(self.installation)
                    if installed['version'] != current:
                        raise ValueError('Installation metadata differs from running version.')
                except (OSError, ValueError, KeyError):
                    if target.get('installer'):
                        self.offer['installer_descriptor'] = target['installer']
                    return self._legacy_offer(assets, tag)
                if installed.get('runtime_id') != target.get('runtime_id'):
                    self.offer['installer_descriptor'] = target['installer']
                    return self._legacy_offer(assets, tag)
            result = {'available': True, 'tag': tag, 'patch': True}
            if self._restore_ready():
                result['ready'] = True
            return result
        if self.windows and native:
            return self._legacy_offer(assets, tag)
        return {'available': True, 'tag': tag, 'manual': True}

    def _legacy_offer(self, assets, tag):
        installer = assets.get('AtelierSetup.exe')
        if installer:
            self.offer['installer'] = installer
            result = {'available': True, 'tag': tag, 'installer': True}
            if self._restore_ready():
                result['ready'] = True
            return result
        return {'available': True, 'tag': tag, 'manual': True}

    def _restore_ready(self):
        try:
            path = self.data_root / '_updates/ready.json'
            request = json.loads(path.read_bytes())
            package = Path(request['package'])
            descriptor = request['descriptor']
            target = self.offer.get('target', {})
            if request.get('envelope') != self.offer.get('envelope') or request['version'] != self.offer['version'] or not package.resolve().is_relative_to(path.parent.resolve()):
                return False
            if Path(request['installation']).resolve() != self.installation.resolve() or request.get('image') != (str(self.image) if self.image else None):
                return False
            if request['kind'] == 'installer':
                asset = self.offer['installer']
                expected = self.offer.get('installer_descriptor') or {
                    'name': asset['name'], 'bytes': asset['size'], 'sha256': (asset.get('digest') or '').removeprefix('sha256:')}
                candidates = [expected]
            else:
                candidates = [target['full'], *target.get('patches', [])]
            if descriptor not in candidates or package.stat().st_size != descriptor['bytes'] or protocol.digest(package) != descriptor['sha256']:
                return False
            if request['kind'] == 'patch':
                protocol.verify_files(self.installation, protocol.load_inventory(self.installation)['files'])
            self.request, self.state = request, 'ready'
            return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False

    def _descriptor(self, row):
        name = protocol.relative_name(row.get('name'))
        if '/' in name or type(row.get('bytes')) is not int or not 0 < row['bytes'] <= MAX_DOWNLOAD or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256'))):
            raise ValueError('Invalid update package descriptor.')
        asset = self.offer['assets'].get(name)
        if not asset or asset.get('size') != row['bytes']:
            raise ValueError('Update package is missing or has a different size.')
        return release_url(asset['browser_download_url'])

    def _download(self, row, folder):
        url = self._descriptor(row)
        path = folder / row['name']
        partial = path.with_name(path.name + '.partial')
        self.progress = {'pct': 0, 'bytes': 0, 'total': row['bytes']}
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Atelier-Updater'})
            with urllib.request.urlopen(request, timeout=60) as source, partial.open('xb') as output:
                count = 0
                while chunk := source.read(1024 * 1024):
                    count += len(chunk)
                    if count > row['bytes']:
                        raise ValueError('Update download exceeds its expected size.')
                    output.write(chunk)
                    self.progress = {'pct': int(count * 100 / row['bytes']), 'bytes': count, 'total': row['bytes']}
            if count != row['bytes'] or protocol.digest(partial) != row['sha256']:
                raise ValueError('Update download failed its integrity check.')
            os.replace(partial, path)
        finally:
            partial.unlink(missing_ok=True)
        return path

    def start_download(self):
        with self.lock:
            if self.state in {'downloading', 'ready', 'applying'}:
                return
            if not self.offer or not (self.offer.get('target') or self.offer.get('installer')):
                raise ValueError('Check for an update first.')
            self.state, self.error = 'downloading', ''
        threading.Thread(target=self.download, name='atelier-update-download', daemon=True).start()

    def download(self):
        try:
            folder = self.data_root / '_updates' / uuid.uuid4().hex
            folder.mkdir(parents=True, exist_ok=False)
            if 'installer' in self.offer:
                asset = self.offer['installer']
                asset_digest = asset.get('digest', '')
                if not self.offer.get('installer_descriptor') and not asset_digest.startswith('sha256:'):
                    raise ValueError('This installer has no GitHub integrity digest. Open its release page to update.')
                row = self.offer.get('installer_descriptor') or {'name': asset['name'], 'bytes': asset['size'], 'sha256': asset_digest[7:]}
                package = self._download(row, folder)
                self.request = {'kind': 'installer', 'package': str(package), 'descriptor': row}
            else:
                target = self.offer['target']
                selected, kind = target['full'], 'full'
                if self.windows:
                    installed = protocol.load_inventory(self.installation)
                    for patch in target.get('patches', []):
                        if patch.get('from_version') == installed['version'] and patch['bytes'] < selected['bytes']:
                            try:
                                protocol.verify_files(self.installation, installed['files'])
                            except (OSError, ValueError):
                                break
                            selected, kind = patch, 'patch'
                            break
                installer_fallback = False
                try:
                    package = self._download(selected, folder)
                    if self.windows:
                        protocol.stage_windows(self.installation, package, folder / 'payload', kind)
                except protocol.InstallerRequired:
                    installer_fallback = True
                except (OSError, ValueError, zipfile.BadZipFile):
                    if kind != 'patch':
                        raise
                    # A rejected delta must still be able to update from the full package.
                    shutil.rmtree(folder / 'payload', ignore_errors=True)
                    selected, kind = target['full'], 'full'
                    package = self._download(selected, folder)
                    try:
                        protocol.stage_windows(self.installation, package, folder / 'payload', kind)
                    except protocol.InstallerRequired:
                        installer_fallback = True
                if installer_fallback:
                    selected = target['installer']
                    package = self._download(selected, folder)
                    self.request = {'kind': 'installer', 'package': str(package), 'descriptor': selected}
                else:
                    self.request = {'kind': kind, 'package': str(package), 'descriptor': selected,
                                    'envelope': self.offer['envelope'], 'platform': self.offer['platform'],
                                    'installation': str(self.installation), 'image': str(self.image) if self.image else None,
                                    'version': self.offer['version']}
                shutil.rmtree(folder / 'payload', ignore_errors=True)
            self.request['folder'] = str(folder)
            self.request.update(version=self.offer['version'], installation=str(self.installation),
                                image=str(self.image) if self.image else None,
                                envelope=self.offer.get('envelope'))
            protocol.atomic_json(self.data_root / '_updates/ready.json', self.request)
            with self.lock:
                self.state = 'ready'
        except Exception as error:
            print('[update] ' + str(error))
            with self.lock:
                self.state, self.error = 'error', str(error)

    def apply(self):
        with self.lock:
            if self.state != 'ready' or not self.request:
                raise ValueError('The update has not finished downloading.')
            if self.request['kind'] == 'installer':
                descriptor = self.request['descriptor']
                if protocol.digest(self.request['package']) != descriptor['sha256']:
                    raise ValueError('The staged installer changed after downloading.')
                detached([self.request['package'], '/SILENT'])
            else:
                folder = Path(self.request['folder'])
                helper_name = 'AtelierUpdater.exe' if self.windows else 'AtelierUpdater'
                source = Path(sys._MEIPASS) / 'updates' / helper_name
                helper = folder / helper_name
                shutil.copy2(source, helper)
                helper.chmod(0o700)
                request = self.request | {'parent_pid': os.getpid(), 'token': uuid.uuid4().hex,
                                          'data_root': str(self.data_root)}
                protocol.atomic_json(folder / 'request.json', request)
                detached([str(helper), '--request', str(folder / 'request.json')])
            (self.data_root / '_updates/ready.json').unlink(missing_ok=True)
            self.state = 'applying'


def recover_interrupted(installation, data_root):
    """Start the preserved helper before loading application modules after a power loss."""
    pending = Path(data_root) / '_updates' / 'pending.json'
    if not pending.is_file() or os.environ.get('ATELIER_UPDATE_TOKEN'):
        return False
    data = json.loads(pending.read_bytes())
    request = Path(data['request'])
    if not request.resolve().is_relative_to(pending.parent.resolve()):
        raise ValueError('Invalid interrupted-update location.')
    helper = request.parent / ('AtelierUpdater.exe' if os.name == 'nt' else 'AtelierUpdater')
    detached([str(helper), '--recover', str(request), '--parent-pid', str(os.getpid())])
    return True
