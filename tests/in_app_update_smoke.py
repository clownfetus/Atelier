"""Exercise the signed updater with real frozen processes on disposable CI runners."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atelier import update_protocol as P


def stop(pid):
    if os.name == 'nt':
        import ctypes
        user = ctypes.windll.user32
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def close(hwnd, _):
            owner = ctypes.c_ulong()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                user.PostMessageW(hwnd, 0x0010, 0, 0)
            return True
        user.EnumWindows(close, 0)
    else:
        os.killpg(pid, signal.SIGTERM)


def wait_server(port, process, marker, token):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Frozen application exited before its window loaded.')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/update_ready', timeout=1) as response:
                json.load(response)
            if marker.is_file() and json.loads(marker.read_bytes()).get('token') == token:
                return
        except (OSError, ValueError):
            pass
        time.sleep(.3)
    raise TimeoutError('Frozen application did not start.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or os.environ.get('ATELIER_DISPOSABLE_UPDATE_TEST') != '1':
        raise RuntimeError('Run this process-upgrade check only on an explicitly configured disposable hosted runner.')
    report = args.report_dir.resolve()
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    if report == runner_temp or not report.is_relative_to(runner_temp):
        raise ValueError('Update smoke reports must be below RUNNER_TEMP.')
    report.mkdir(parents=True, exist_ok=False)
    release = args.release.resolve(strict=True)
    feed = P.verify_feed(json.loads((release / P.FEED).read_bytes()), json.loads((ROOT / 'update_keys.json').read_bytes()))
    host = 'windows-x64' if os.name == 'nt' else 'linux-x64'
    descriptor = feed['platforms'][host]['full']
    package = release / descriptor['name']
    if package.stat().st_size != descriptor['bytes'] or P.digest(package) != descriptor['sha256']:
        raise ValueError('Release payload differs from its signed metadata.')
    data = report / 'data'
    folder = data / '_updates' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    canary = data / 'assets/projects/Updater canary/keep.txt'
    canary.parent.mkdir(parents=True)
    canary.write_text('preserve this project', encoding='utf-8')
    (data / 'mr_config.json').write_text(json.dumps({'active_project': 'Updater canary', 'update_canary': 'keep this setting'}), encoding='utf-8')
    if os.name == 'nt':
        with zipfile.ZipFile(package) as archive:
            P._members(archive)
            archive.extractall(report / 'baseline')
        installation = report / 'baseline/Atelier'
        current = list(P.version(feed['version']))
        if current[2]:
            current[2] -= 1
        elif current[1]:
            current[1] -= 1
        else:
            current[0] = max(0, current[0] - 1)
        baseline_version = '.'.join(map(str, current))
        (installation / '_internal/version').write_text(baseline_version, encoding='utf-8')
        P.make_inventory(installation, baseline_version, feed['source_commit'])
        helper_source = installation / '_internal/updates/AtelierUpdater.exe'
        executable = installation / 'Atelier.exe'
        image = None
    else:
        package.chmod(0o755)
        subprocess.run([str(package), '--appimage-extract'], cwd=report, check=True, stdout=subprocess.DEVNULL)
        helper_source = report / 'squashfs-root/usr/Atelier/_internal/updates/AtelierUpdater'
        image = report / 'Atelier.AppImage'
        shutil.copy2(package, image)
        image.chmod(0o755)
        installation, executable = data, image
    helper = folder / helper_source.name
    shutil.copy2(helper_source, helper)
    helper.chmod(0o755)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, ATELIER_DATA_DIR=str(data), ATELIER_HOME=str(data), ATELIER_PORT=str(port), PYINSTALLER_RESET_ENVIRONMENT='1')
    baseline_marker, baseline_token = report / 'baseline-ready.json', uuid.uuid4().hex
    old_env = env | {'ATELIER_UPDATE_TOKEN': baseline_token, 'ATELIER_UPDATE_ACK': str(baseline_marker)}
    options = {'env': old_env, 'cwd': str(executable.parent)}
    if os.name != 'nt':
        options['start_new_session'] = True
    old = subprocess.Popen([str(executable)] + ([] if os.name == 'nt' else ['--appimage-extract-and-run']), **options)
    new_pid = None
    try:
        wait_server(port, old, baseline_marker, baseline_token)
        request = {'kind': 'full', 'package': str(package), 'descriptor': descriptor,
                   'envelope': json.loads((release / P.FEED).read_bytes()), 'platform': host,
                   'version': feed['version'], 'installation': str(installation), 'image': str(image) if image else None,
                   'folder': str(folder), 'parent_pid': old.pid, 'token': uuid.uuid4().hex, 'data_root': str(data)}
        P.atomic_json(folder / 'request.json', request)
        update = subprocess.Popen([str(helper), '--request', str(folder / 'request.json')], env=env)
        stop(old.pid)
        old.wait(timeout=60)
        if update.wait(timeout=180) != 0:
            error = json.loads((folder / 'error.json').read_bytes())
            raise RuntimeError('Standalone updater failed: ' + error['error'])
        journal = json.loads((folder / 'transaction/journal.json').read_bytes())
        new_pid = journal.get('process_pid')
        if journal['state'] != 'committed' or not new_pid:
            raise ValueError('Standalone update was not committed.')
        if canary.read_text() != 'preserve this project' or json.loads((data / 'mr_config.json').read_bytes()).get('update_canary') != 'keep this setting':
            raise ValueError('The updater changed project/configuration canaries.')
        if json.loads((folder / 'healthy.json').read_bytes()) != {'version': feed['version'], 'token': request['token']}:
            raise ValueError('The real frontend did not acknowledge the new version.')
        P.atomic_json(report / 'results.json', {'ok': True, 'platform': host, 'version': feed['version'],
                      'source_commit': feed['source_commit'], 'package_sha256': descriptor['sha256'],
                      'baseline': 'current payload with older version metadata' if os.name == 'nt' else 'current AppImage',
                      'checks': ['real frozen parent exits', 'signed full package applied by standalone helper',
                                 'restarted native frontend acknowledges update', 'project and setting canaries preserved']})
    finally:
        if old.poll() is None:
            stop(old.pid)
            old.wait(timeout=30)
        if new_pid:
            try:
                stop(new_pid)
            except ProcessLookupError:
                pass


if __name__ == '__main__':
    main()
