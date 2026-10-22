"""Verify a real Linux release AppImage in an isolated GTK/WebKit desktop.

Run under Xvfb, a session D-Bus and a window manager. Tests never use game data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def wait_for(check, process, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'AppImage exited early: {process.returncode}')
        try:
            value = check()
            if value:
                return value
        except Exception as exc:
            last = exc
        time.sleep(0.5)
    raise RuntimeError(f'Timed out waiting for the frozen app: {last}')


def accessible_names():
    import pyatspi
    names = []

    def visit(node, depth=0):
        if depth > 25:
            return
        if node.name:
            names.append(node.name)
        for child in node:
            visit(child, depth + 1)

    visit(pyatspi.Registry.getDesktop(0))
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appimage', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--previous-appimage', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'linux' or not os.environ.get('DISPLAY'):
        parser.error('Requires a Linux desktop session')
    appimage, source, report = args.appimage.resolve(), args.source.resolve(), args.report_dir.resolve()
    if report.exists():
        parser.error('Use a fresh report directory')
    report.mkdir(parents=True)
    previous = args.previous_appimage.resolve(strict=True)
    inputs = json.loads((source / 'tests/fixtures/installer' / f'release-{(source / "version").read_text().strip()}-inputs.json').read_text())
    if sha256(previous) != inputs['linux_seed_sha256']:
        parser.error('Previous AppImage does not match the pinned upgrade baseline')
    result = {'appimage_sha256': sha256(appimage), 'previous_appimage_sha256': sha256(previous), 'checks': [], 'platform': sys.platform}
    version = (source / 'version').read_text().strip()
    process = None
    try:
        extract = report / 'extracted'
        extract.mkdir()
        subprocess.run([str(appimage), '--appimage-extract'], cwd=extract, check=True,
                       stdout=subprocess.DEVNULL, timeout=120)
        payload = extract / 'squashfs-root/usr/Atelier'
        sys.path.insert(0, str(source))
        from atelier.blender_extension import archive_bytes
        assert (payload / '_internal/extensions/Atelier-Live-Bridge.zip').read_bytes() == archive_bytes(source)
        result['checks'].append({'name': 'bundled Blender extension matches exact source and provenance'})
        sys.path.insert(0, str(source / 'scripts'))
        from stage_tools import audit, validate_tools
        # Build-time staging audits the raw payload before release licenses are added.
        validate_tools(payload / 'Tools', 'linux')
        if (payload / '_internal/version').read_text().strip() != version:
            raise RuntimeError('Wrong packaged version')
        matches = {}
        for folder in ('gui', 'atelier/blender', 'atelier/models'):
            for original in sorted((source / folder).rglob('*')):
                if not original.is_file() or '__pycache__' in original.parts or original.suffix == '.pyc':
                    continue
                relative = original.relative_to(source)
                frozen = payload / '_internal' / relative
                if not frozen.is_file() or sha256(frozen) != sha256(original):
                    raise RuntimeError(f'Packaged file differs from release source: {relative}')
                matches[relative.as_posix()] = sha256(frozen)
        (report / 'source-hashes.json').write_text(json.dumps(matches, indent=2))
        result['checks'].append({'name': 'payload audit and exact source files', 'files': len(matches)})
        # Linux intentionally omits DXC and disables shader editing. Check the
        # native retoc commands used by text extraction and repatching instead.
        for tool, required in (('UAssetTool', ('extract',)), ('shaders/retoc-rivals-cli', ('pack', 'unpack'))):
            completed = subprocess.run([str(payload / 'Tools' / tool), '--help'], cwd=payload / 'Tools',
                                       capture_output=True, text=True, timeout=60)
            (report / (Path(tool).name + '-help.txt')).write_text(completed.stdout + completed.stderr)
            if completed.returncode or not all(word in completed.stdout + completed.stderr for word in required):
                raise RuntimeError(f'Native tool failed to launch: {tool}: {completed.stdout} {completed.stderr}')
        for command in ('pack', 'unpack'):
            completed = subprocess.run([str(payload / 'Tools/shaders/retoc-rivals-cli'), command, '--help'],
                                       capture_output=True, text=True, timeout=30)
            (report / f'retoc-{command}-help.txt').write_text(completed.stdout + completed.stderr)
            if completed.returncode or '--game-paks-dir' not in completed.stdout + completed.stderr:
                raise RuntimeError(f'Native retoc lacks the Rivals {command} interface')
        result['checks'].append({'name': 'native UAssetTool and Rivals retoc launch'})
        previous_extract = report / 'previous-extracted'
        previous_extract.mkdir()
        subprocess.run([str(previous), '--appimage-extract'], cwd=previous_extract, check=True,
                       stdout=subprocess.DEVNULL, timeout=120)
        previous_payload = previous_extract / 'squashfs-root/usr/Atelier'
        previous_version = (previous_payload / '_internal/version').read_text().strip()
        result['previous_version'] = previous_version
        data = report / 'user-data'
        with socket.socket() as port_probe:
            port_probe.bind(('127.0.0.1', 0))
            port = port_probe.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, ATELIER_HOME=str(data), ATELIER_DATA_DIR=str(data),
                   ATELIER_PORT=str(port), WEBKIT_DISABLE_DMABUF_RENDERER='1',
                   LIBGL_ALWAYS_SOFTWARE='1', NO_AT_BRIDGE='0')
        for launch, image, expected_payload, expected_version in (
                ('previous-launch', previous, previous_payload, previous_version),
                ('upgrade-and-preservation', appimage, payload, version),
                ('same-version-relaunch', appimage, payload, version)):
            with (report / f'{launch}.log').open('w') as log:
                process = subprocess.Popen([str(image), '--appimage-extract-and-run'], env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                setup = wait_for(lambda: json.load(urllib.request.urlopen(base + '/api/setup_status', timeout=2)), process)
                if setup['configured']:
                    raise RuntimeError('Smoke fixture unexpectedly configured a real game')
                title = ('Find the game' if tuple(map(int, expected_version.split('.'))) >= (1, 0, 0)
                         else 'Initial Configuration')
                wait_for(lambda: any(title in name for name in accessible_names()), process)
                if launch != 'previous-launch':
                    prereqs = json.load(urllib.request.urlopen(base + '/api/prereqs', timeout=10))
                    if any(item['level'] == 'error' and ('UAssetTool' in item['message'] or 'Wine not found' in item['message']) for item in prereqs['issues']):
                        raise RuntimeError('Packaged Linux native core tool failed prerequisite recognition')
                names = accessible_names()
                (report / f'{launch}-accessibility.json').write_text(json.dumps(names, indent=2))
                if not any(title in name for name in names):
                    raise RuntimeError('WebKit setup form did not initialize')
                with urllib.request.urlopen(base + '/static/app.js', timeout=5) as response:
                    if hashlib.sha256(response.read()).hexdigest() != sha256(expected_payload / '_internal/gui/app.js'):
                        raise RuntimeError('Frozen backend served different frontend code')
                subprocess.run(['scrot', str(report / f'{launch}.png')], check=True)
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name', '^Atelier$'], text=True).splitlines()[-1]
                subprocess.run(['xdotool', 'windowactivate', '--sync', window, 'key', 'alt+F4'], check=True)
                code = process.wait(timeout=45)
                process = None
                if code:
                    raise RuntimeError(f'Frozen app did not close cleanly: {code}')
            if (data / '.staged').read_text().strip() != expected_version:
                raise RuntimeError('AppRun did not stage the release version')
            if sha256(data / 'Atelier') != sha256(expected_payload / 'Atelier'):
                raise RuntimeError('AppRun staged the wrong executable')
            if sha256(data / 'Tools/UAssetTool') != sha256(expected_payload / 'Tools/UAssetTool'):
                raise RuntimeError('AppRun did not refresh the native tool')
            result['checks'].append({'name': launch + ': real GTK/WebKit setup, frontend, graceful close'})
            if launch == 'previous-launch':
                (data / 'Tools/user-note.txt').write_text('preserve this user file')
                fixture = data / 'assets/projects/SmokeProject/readme.txt'
                fixture.parent.mkdir(parents=True)
                fixture.write_text('preserve this project')
                config = data / 'mr_config.json'
                saved = json.loads(config.read_text()) if config.exists() else {}
                saved['release_upgrade_canary'] = 'preserve existing settings'
                config.write_text(json.dumps(saved))
                # The actual old AppImage populated this directory and WebKit profile.
                # Corrupt a bundled tool to prove the upgrade really refreshes it.
                (data / 'Tools/UAssetTool').write_bytes(b'obsolete runtime tool')
            else:
                if (data / 'Tools/user-note.txt').read_text() != 'preserve this user file' or fixture.read_text() != 'preserve this project':
                    raise RuntimeError('AppRun replaced user data during refresh')
                if json.loads((data / 'mr_config.json').read_text()).get('release_upgrade_canary') != 'preserve existing settings':
                    raise RuntimeError('Upgrade lost existing configuration fields')
        result['checks'].append({'name': 'packaged native UAssetTool satisfies asset-operation prerequisites without its Windows executable'})
        result['checks'].append({'name': 'actual previous-version upgrade and relaunch preserve user tools, projects and configuration'})
        result['ok'] = True
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        result.update(ok=False, error=str(exc))
        subprocess.run(['scrot', str(report / 'failure.png')], check=False)
        raise
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        (report / 'results.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
