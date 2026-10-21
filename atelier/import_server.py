"""Parent-owned persistent CUE4Parse imports, isolated from project edit files.

One native process retains the mounted game reader. Its inherited JSON pipes are
private to Atelier; no extra listening port or command-line encryption key exists.
Cancelling the active request drops that process before another caller can reuse
its stream. Queued callers cancel without interrupting someone else's request.
"""
import atexit
from collections import deque
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import struct
import sys
import tempfile
import threading
import time
import uuid

from atelier import config, hostos, jobs
from atelier.storage import atomic_json
from atelier.inflight import key_lock

VERSION = 1
_lock = threading.Lock()
_process_lock = threading.Lock()
_worker = None
_closing = False


class ImportError(RuntimeError):
    """The owned decoder could not complete a valid import request."""


class AssetError(ImportError):
    """A framed failure for one asset; the provider/stream remain reusable."""


def tool_path():
    return Path(config.TOOLS) / 'AtelierImport' / 'AtelierImport.exe'


def available():
    return hostos.IS_WINDOWS and tool_path().is_file()


def source_version():
    return _source()[0]


def _source():
    tool = tool_path()
    paks = Path(config.PAKS).resolve()
    key = config.get_aes_key().removeprefix('0x')
    if not key:
        raise ImportError('Configure the game encryption key before importing a model.')
    def stamp(path):
        stat = path.stat()
        return (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    containers = sorted((stamp(path) for path in paks.iterdir()
                         if path.is_file() and path.suffix.lower() in ('.utoc', '.ucas', '.pak')
                         and path.stem.lower() != '!projectgalacta_9999999_p'))
    identity = hashlib.sha256(json.dumps([VERSION, stamp(tool), stamp(Path(config.USMAP)),
        containers, hashlib.sha256(key.encode()).hexdigest()]).encode()).hexdigest()
    root = Path(config._CACHE) / 'imports' / f'v{VERSION}' / identity
    return identity, root, {'paks': str(paks), 'usmap': config.USMAP, 'aes': '0x'+key, 'cache_root': str(root)}


def _asset(game_rel):
    config.validate_game_rel(game_rel)
    from atelier.paths import pak_game_path
    return pak_game_path(game_rel)


def _target(root, kind, asset, suffix):
    config.validate_game_rel(asset)
    base = os.path.realpath(os.path.join(root, kind))
    target = os.path.realpath(os.path.join(base, asset+suffix))
    # During parallel directory creation Windows realpath can retain \\?\ on
    # only one operand. Compare ordinary drive/UNC spellings; retain the resolved
    # path for I/O and continue to reject different drives, shares and devices.
    base_key = config._path_comparison_key(base)
    target_key = config._path_comparison_key(target)
    try:
        contained = os.path.commonpath([base_key, target_key]) == base_key
    except ValueError:
        contained = False
    if not contained:
        raise ValueError('Import cache path is outside the cache.')
    return Path(target)


def _same_path(left, right):
    return (config._path_comparison_key(os.path.realpath(left))
            == config._path_comparison_key(os.path.realpath(right)))


class _Worker:
    def __init__(self, identity, initialization):
        self.identity = identity
        self.secrets = (initialization['aes'], initialization['aes'][2:])
        self.lines = queue.Queue()
        self.errors = deque(maxlen=12)
        # Bound managed memory; provider indices stay resident while transient
        # meshes/images are collected. Native allocations remain outside this cap.
        env = dict(os.environ, DOTNET_GCHeapHardLimit='60000000')
        self.process = hostos.popen_exe([str(tool_path())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', cwd=str(tool_path().parent), env=env)
        def output():
            try:
                while line := self.process.stdout.readline(4*1024*1024+1):
                    if len(line) > 4*1024*1024:
                        self.lines.put(None)
                        return
                    self.lines.put(line)
            except (OSError, ValueError):
                pass
            finally:
                self.lines.put(None)
        def errors():
            try:
                for line in self.process.stderr:
                    self.errors.append(line.strip().replace(initialization['aes'], '[redacted]')
                                       .replace(initialization['aes'][2:], '[redacted]')[-600:])
            except (OSError, ValueError):
                pass
        threading.Thread(target=output, name='import-stdout', daemon=True).start()
        threading.Thread(target=errors, name='import-stderr', daemon=True).start()
    def initialize(self, initialization):
        try:
            data = self.request('initialize', initialization)
            if data.get('protocol') != VERSION or data.get('initializations') != 1:
                raise ImportError('The import server protocol does not match this app.')
            self.pid = data['pid']
            print(f'[import] mounted game reader once (pid {data["pid"]}, {data["files"]} entries)', file=sys.stderr, flush=True)
        except BaseException:
            self.close()
            raise

    def request(self, action, values, timeout=180):
        identity = uuid.uuid4().hex
        jobs.checkpoint()
        try:
            self.process.stdin.write(json.dumps({'id': identity, 'action': action, **values})+'\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as error:
            raise ImportError('The import server stopped before accepting the request.') from error
        deadline = time.monotonic()+timeout
        while True:
            jobs.checkpoint()
            if _closing:
                raise ImportError('The import server is shutting down.')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ImportError(f'The import server did not answer within {timeout} seconds.')
            try:
                line = self.lines.get(timeout=min(.1, remaining))
            except queue.Empty:
                continue
            if line is None:
                raise ImportError('The import server exited: '+'; '.join(self.errors)[-900:])
            try:
                reply = json.loads(line)
            except (ValueError, TypeError) as error:
                raise ImportError('The import server returned an invalid response.') from error
            if not isinstance(reply, dict):
                raise ImportError('The import server returned a non-object response.')
            if reply.get('id') != identity:
                raise ImportError('The import server returned a response for a different request.')
            if not reply.get('ok'):
                message = str(reply.get('error') or 'Import failed')
                for secret in self.secrets:
                    message = message.replace(secret, '[redacted]')
                raise AssetError(message)
            data = reply.get('data')
            if not isinstance(data, dict):
                raise ImportError('The import server returned invalid data.')
            if action == 'mesh':
                print(f'[import] mesh {values.get("asset", "")}: {reply.get("elapsed_ms", 0)} ms', file=sys.stderr, flush=True)
            return data

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def _request(action, values, source=None, timeout=180):
    global _worker
    identity, root, initialization = source or _source()
    with jobs.cancellable_lock(_lock):
        if _closing:
            raise ImportError('The import server is shutting down.')
        try:
            if _worker is None or _worker.identity != identity or _worker.process.poll() is not None:
                with _process_lock:
                    if _closing:
                        raise ImportError('The import server is shutting down.')
                    if _worker:
                        _worker.close()
                    _worker = _Worker(identity, initialization)
                _worker.initialize(initialization)
            return _worker.request(action, values, timeout=timeout)
        except AssetError:
            raise
        except BaseException:
            # Even a late reply after cancellation/timeouts must never reach the
            # next request. Closing only happens while this caller owns the lock.
            with _process_lock:
                if _worker:
                    _worker.close()
                _worker = None
            raise


def mesh(game_rel):
    asset = _asset(game_rel)
    source = _source()
    target = _target(source[1], 'gltf', asset, '.glb')
    metadata = _target(source[1], 'meshes', asset, '.json')
    def valid():
        try:
            with target.open('rb') as stream:
                magic, version, length = struct.unpack('<4sII', stream.read(12))
                chunk_length, chunk_type = struct.unpack('<I4s', stream.read(8))
                return magic == b'glTF' and version == 2 and length == target.stat().st_size and chunk_type == b'JSON' and 0 < chunk_length <= length-20
        except (OSError, struct.error):
            return False
    with key_lock('native-mesh', source[0], asset):
        if not valid() or not metadata.is_file():
            reply = _request('mesh', {'asset': asset}, source)
            if not _same_path(reply.get('path', ''), target) or not valid():
                raise ImportError('The import server did not publish a valid requested mesh.')
    return str(target)


def mesh_slots(game_rel):
    if not available():
        return None
    asset = _asset(game_rel)
    metadata = _target(_source()[1], 'meshes', asset, '.json')
    if not metadata.is_file():
        return None
    data = json.loads(metadata.read_text(encoding='utf-8'))
    slots = data.get('slots')
    if data.get('version') != VERSION or data.get('asset') != asset or not isinstance(slots, list) or not slots:
        return None
    if len(slots) > 256 or any(slot.get('index') != index or not isinstance(slot.get('slot'), str)
                               for index, slot in enumerate(slots)):
        raise ImportError('The imported mesh material identities are invalid.')
    for slot in slots:
        if slot.get('mi'):
            config.validate_game_rel(slot['mi'])
    return slots


def material(game_rel):
    if not available():
        return None
    asset = _asset(game_rel)
    source = _source()
    target = _target(source[1], 'materials', asset, '.json')
    with key_lock('native-material', source[0], asset):
        if target.is_file():
            return json.loads(target.read_text(encoding='utf-8'))
        data = _request('material', {'asset': asset}, source)
        if not isinstance(data.get('colors'), list) or not isinstance(data.get('textures'), dict):
            raise ImportError('The import server returned invalid material parameters.')
        for texture in data['textures'].values():
            config.validate_game_rel(texture)
        jobs.checkpoint()
        atomic_json(str(target), data)
        return data


def texture(game_rel):
    if not available():
        return None
    asset = _asset(game_rel)
    source = _source()
    target = _target(source[1], 'textures', asset, '.png')
    with key_lock('native-texture', source[0], asset):
        if not target.is_file():
            data = _request('texture', {'asset': asset}, source)
            expected = _target(source[1], 'blocks', asset, '.bin') if data.get('encoding') == 'blocks' else target
            if not _same_path(data.get('path', ''), expected):
                raise ImportError('The import server returned an unexpected texture path.')
            if data.get('encoding') == 'blocks':
                _decode_blocks(data, expected, target)
        from PIL import Image
        try:
            with Image.open(target) as image:
                if image.format != 'PNG' or image.width > 16384 or image.height > 16384:
                    raise ImportError('The import server returned invalid texture pixels.')
                image.verify()
        except (OSError, SyntaxError) as error:
            raise ImportError('The import server did not publish a complete PNG.') from error
    return str(target)


def _decode_blocks(data, blocks, target):
    from PIL import Image
    from atelier.handlers.texture import _BPB, _dds_header
    width, height, fmt = data.get('width'), data.get('height'), data.get('format')
    if (type(width) is not int or type(height) is not int or not 0 < width <= 16384
            or not 0 < height <= 16384 or not isinstance(fmt, str) or fmt not in _BPB):
        raise ImportError('The import server returned invalid texture blocks.')
    size = max(1, (width+3)//4)*max(1, (height+3)//4)*_BPB[fmt]
    temporary = None
    try:
        if blocks.stat().st_size != size:
            raise ImportError('The import server returned incomplete texture blocks.')
        with Image.open(io.BytesIO(_dds_header(width, height, fmt, size)+blocks.read_bytes())) as image:
            image.load()
            if image.size != (width, height):
                raise ImportError('The import server returned inconsistent texture dimensions.')
            jobs.checkpoint()
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix='.texture-', suffix='.png', dir=target.parent)
            os.close(handle)
            image.save(temporary, format='PNG', compress_level=1)
        jobs.checkpoint()
        os.replace(temporary, target)
    except (OSError, ValueError, NotImplementedError) as error:
        raise ImportError('Texture blocks require the compatibility decoder.') from error
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def stats():
    return _request('stats', {})


def shutdown():
    global _worker, _closing
    with _process_lock:
        _closing = True
        if _worker:
            _worker.close()
        _worker = None


atexit.register(shutdown)
