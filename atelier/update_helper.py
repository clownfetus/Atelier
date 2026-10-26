"""Standalone process: wait for Atelier, update, restart and roll back a bad boot."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from atelier import update_protocol as protocol
from atelier.updates import clean_environment


def prune_backups(data_root, current):
    root = (Path(data_root) / '_updates').resolve()
    current = Path(current).resolve()
    for folder in root.iterdir():
        if folder == current or not re.fullmatch('[a-f0-9]{32}', folder.name) or folder.is_symlink() or folder.is_junction():
            continue
        # The updater owns only completed transaction folders below this root.
        if not folder.is_dir() or not folder.resolve().is_relative_to(root):
            continue
        try:
            journal = json.loads((folder / 'transaction/journal.json').read_bytes())
        except (OSError, ValueError):
            continue
        if journal.get('state') in {'committed', 'rolled_back'}:
            shutil.rmtree(folder)


def wait_for_exit(pid, timeout=24 * 60 * 60):
    deadline = time.monotonic() + timeout
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: process already exited
                return
            raise OSError('Cannot wait for Atelier to close.')
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError('Atelier is still finishing work. Update was not applied.')
        finally:
            kernel.CloseHandle(handle)
    else:
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.2)
        raise TimeoutError('Atelier is still finishing work. Update was not applied.')


def launch(command, request, healthy=False):
    env = clean_environment()
    env['ATELIER_DATA_DIR'] = request['data_root']
    if healthy:
        env.update(ATELIER_UPDATE_TOKEN=request['token'],
                   ATELIER_UPDATE_ACK=str(Path(request['folder']) / 'healthy.json'))
    options = {'env': env, 'cwd': str(Path(command[0]).parent), 'close_fds': True}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    else:
        options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def healthy(process, request, timeout=120):
    marker = Path(request['folder']) / 'healthy.json'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = json.loads(marker.read_bytes())
            if data == {'version': request['version'], 'token': request['token']}:
                return True
        except (OSError, ValueError):
            pass
        if process.poll() is not None:
            return False
        time.sleep(.25)
    return False


def stop_application(process):
    if os.name == 'nt':
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        return
    # Extract-and-run AppImages can have a wrapper and a child application.
    # launch() creates their own session, so stop that entire group before rollback.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)


@contextmanager
def update_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run(request_path, recover=False, parent_pid=None):
    request = json.loads(Path(request_path).read_bytes())
    with update_lock(Path(request['data_root']) / '_updates/install.lock'):
        return _run(request_path, recover, parent_pid)


def _run(request_path, recover=False, parent_pid=None):
    request_path = Path(request_path).resolve(strict=True)
    request = json.loads(request_path.read_bytes())
    folder = request_path.parent
    if Path(request['folder']).resolve() != folder:
        raise ValueError('Updater request folder does not match.')
    pending = Path(request['data_root']) / '_updates' / 'pending.json'
    transaction = folder / 'transaction'
    journal = transaction / 'journal.json'
    command = [str(Path(request['installation']) / 'Atelier.exe')] if request['platform'] == 'windows-x64' else [request['image'], '--appimage-extract-and-run']
    wait_for_exit(parent_pid or request['parent_pid'])
    if recover:
        if journal.is_file():
            if request['platform'] == 'windows-x64':
                protocol.rollback_windows(transaction)
            elif json.loads(journal.read_bytes())['state'] != 'committed' and (transaction / 'previous.AppImage').is_file():
                os.replace(transaction / 'previous.AppImage', request['image'])
        pending.unlink(missing_ok=True)
        launch(command, request)
        return
    atomic_pending = {'request': str(request_path)}
    committed = False
    try:
        keys = json.loads((Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'update_keys.json').read_bytes())
        feed = protocol.verify_feed(request['envelope'], keys)
        target = feed['platforms'][request['platform']]
        descriptor = request['descriptor']
        if feed['version'] != request['version'] or descriptor not in [target['full'], *target.get('patches', [])]:
            raise ValueError('Update request is not in the signed release.')
        package = Path(request['package'])
        if package.stat().st_size != descriptor['bytes'] or protocol.digest(package) != descriptor['sha256']:
            raise ValueError('Staged update package was modified.')
        if request['platform'] == 'windows-x64':
            # Recheck the base after all application work has drained.
            staging = folder / 'apply-payload'
            plan = protocol.stage_windows(request['installation'], package, staging, request['kind'])
            if plan['target']['version'] != feed['version'] or plan['target']['source_commit'] != feed['source_commit']:
                raise ValueError('Package version or source differs from its signed release.')
            protocol.atomic_json(pending, atomic_pending)
            protocol.apply_windows(request['installation'], staging, plan, transaction)
        else:
            image = Path(request['image'])
            if image.is_symlink() or not image.is_file() or not os.access(image.parent, os.W_OK):
                raise ValueError('The AppImage location is not writable.')
            with package.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    raise ValueError('The update is not an AppImage.')
            transaction.mkdir()
            shutil.copy2(image, transaction / 'previous.AppImage')
            protocol.atomic_json(journal, {'state': 'applying'})
            protocol.atomic_json(pending, atomic_pending)
            protocol._replace_file(package, image)
            image.chmod(0o755)
        process = launch(command, request, healthy=True)
        data = json.loads(journal.read_bytes())
        data['process_pid'] = process.pid
        protocol.atomic_json(journal, data)
        if not healthy(process, request):
            stop_application(process)
            raise RuntimeError('The updated application did not finish starting; restored the previous version.')
        data = json.loads(journal.read_bytes())
        data['state'] = 'committed'
        protocol.atomic_json(journal, data)
        committed = True
        pending.unlink(missing_ok=True)
        # Retain the backup and receipt, but avoid retaining two expanded payloads.
        for name in ('payload', 'apply-payload'):
            shutil.rmtree(folder / name, ignore_errors=True)
        package.unlink(missing_ok=True)
        prune_backups(request['data_root'], folder)
    except BaseException:
        if committed:
            # Cleanup must never roll back or relaunch an already healthy app.
            return
        if journal.is_file():
            if request['platform'] == 'windows-x64':
                protocol.rollback_windows(transaction)
            elif (transaction / 'previous.AppImage').is_file():
                protocol._replace_file(transaction / 'previous.AppImage', Path(request['image']))
        pending.unlink(missing_ok=True)
        launch(command, request)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--request', type=Path)
    group.add_argument('--recover', type=Path)
    parser.add_argument('--parent-pid', type=int)
    args = parser.parse_args()
    path = args.request or args.recover
    try:
        run(path, recover=bool(args.recover), parent_pid=args.parent_pid)
    except Exception as error:
        protocol.atomic_json(path.parent / 'error.json', {'error': str(error)})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
