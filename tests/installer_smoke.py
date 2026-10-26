"""Run installer checks only on a deliberately configured disposable hosted runner.

Local execution is disabled after a host BSOD during smoke-test preparation.
This restriction is a safety measure, not a repair of the underlying BSOD.
An existing Atelier registration is never renamed, replaced, or restored.
Failed fixtures are left for disposal with the runner, not automatically cleaned.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import time
import traceback
import urllib.request
import winreg

UNINSTALL = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
APP_KEY = '{2E25ABE9-E3D5-4ABA-9E50-725BA75185AF}_is1'


def admit_disposable_runner(report):
    # Operational guard against accidental host execution, not VM attestation.
    required = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'RUNNER_OS': 'Windows', 'ATELIER_DISPOSABLE_INSTALLER_TEST': '1'}
    if os.name != 'nt' or any(os.environ.get(key) != value for key, value in required.items()):
        raise RuntimeError('Local installer smoke testing is disabled after a BSOD. '
                           'Only a deliberately configured GitHub-hosted Windows disposable runner is allowed; '
                           'the underlying crash investigation is separate.')
    runner_temp_value = os.environ.get('RUNNER_TEMP')
    if not runner_temp_value:
        raise RuntimeError('RUNNER_TEMP is required for disposable installer tests')
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    if report == runner_temp or not report.is_relative_to(runner_temp):
        raise RuntimeError('Installer test report must be a new directory beneath RUNNER_TEMP')
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, UNINSTALL + '\\' + APP_KEY, 0, winreg.KEY_READ | view):
                    pass
            except FileNotFoundError:
                continue
            raise RuntimeError('Refusing installer tests: an Atelier uninstall registration already exists')


def initialize_native_api():
    global USER32, KERNEL32, CALLBACK
    USER32 = ctypes.windll.user32
    KERNEL32 = ctypes.WinDLL('kernel32', use_last_error=True)
    KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    KERNEL32.OpenProcess.restype = wintypes.HANDLE
    KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    KERNEL32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    USER32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    USER32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def registration(name=APP_KEY):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL + '\\' + name) as key:
            return {winreg.EnumValue(key, i)[0]: winreg.EnumValue(key, i)[1:] for i in range(winreg.QueryInfoKey(key)[1])}
    except FileNotFoundError:
        return None


def process_path(pid):
    handle = KERNEL32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        length = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(length.value)
        if not KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return None
        return Path(buffer.value)
    finally:
        KERNEL32.CloseHandle(handle)


def alive(pid):
    handle = KERNEL32.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return KERNEL32.WaitForSingleObject(handle, 0) == 258
    finally:
        KERNEL32.CloseHandle(handle)


def wait_for(predicate, message, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.1)
    raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--previous-installer', type=Path, required=True)
    parser.add_argument('--previous-sha256', required=True)
    parser.add_argument('--payload-manifest', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--app-port', type=int, default=8767)
    parser.add_argument('--debug-port', type=int, default=9354)
    args = parser.parse_args()
    report = args.report_dir.resolve()
    admit_disposable_runner(report)
    if not __debug__:
        raise RuntimeError('Installer verification must not run with Python optimization enabled')
    report.mkdir(parents=True, exist_ok=False)
    result = {'ok': False, 'checks': [], 'page_errors': [], 'steps': [],
              'page_error_scope': 'Errors observed after each pageerror listener attaches; early startup errors may precede attachment',
              'fixture_scope': 'Synthetic data and naturally created previous-version WebView profile; no imported user cache'}

    def journal(stage, **details):
        entry = {'time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 'stage': stage, **details}
        with (report / 'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(entry), flush=True)

    journal('admitted', report=str(report))
    try:
        execute_checks(args, report, result, journal)
    except BaseException as exc:
        result['error'] = str(exc)
        result['traceback'] = traceback.format_exc()
        journal('error', error=str(exc), traceback=result['traceback'])
        raise
    finally:
        # Failure never triggers an uninstall; dispose of the whole runner.
        with (report / 'results.json').open('w', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps(result, indent=2))


def execute_checks(args, report, result, journal):
    journal('preparation-start')
    from playwright.sync_api import sync_playwright
    initialize_native_api()
    installer = args.installer.resolve(strict=True)
    previous = args.previous_installer.resolve(strict=True)
    payload = json.loads(args.payload_manifest.read_text(encoding='utf-8'))
    result['installer_sha256'] = digest(installer)
    result['previous_installer_sha256'] = digest(previous)
    if result['installer_sha256'] != payload['installer_sha256'].lower():
        raise RuntimeError('Installer does not match the payload manifest')
    if result['previous_installer_sha256'] != args.previous_sha256.lower():
        raise RuntimeError('Previous installer does not match the required SHA-256')
    manifest_files = payload['files']
    if not isinstance(manifest_files, list) or not manifest_files:
        raise RuntimeError('Payload manifest must contain files')
    seen = set()
    for item in manifest_files:
        name = item['path']
        relative = PurePosixPath(name)
        if (not name or relative.is_absolute() or '..' in relative.parts or
                '\\' in name or ':' in name or '\x00' in name or relative.as_posix() != name or
                name.casefold() in seen):
            raise RuntimeError(f'Unsafe or duplicate payload path: {name!r}')
        checksum = item['sha256']
        if len(checksum) != 64 or any(char not in '0123456789abcdefABCDEF' for char in checksum):
            raise RuntimeError(f'Invalid payload SHA-256: {name}')
        seen.add(name.casefold())
    result['payload_files_expected'] = len(manifest_files)
    for port in (args.app_port, args.debug_port):
        with socket.socket() as sock:
            # A refused connection can time out under the runner firewall.
            # An exclusive bind directly proves that this local port is free.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as exc:
                raise RuntimeError(f'Port {port} is unavailable: {exc}') from exc
    # Hosted Windows jobs run elevated. Recent WebView2 versions intentionally
    # ignore WEBVIEW2_* environment overrides for elevated hosts, but honor this
    # application-specific machine policy. This is configured ONLY after the
    # disposable-runner gate; the entire VM (including this policy) is discarded.
    debug_policy = r'Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments'
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, debug_policy, 0, winreg.KEY_SET_VALUE | view) as key:
            winreg.SetValueEx(key, 'Atelier.exe', 0, winreg.REG_SZ, f'--remote-debugging-port={args.debug_port}')
    journal('fixture-debug-policy-configured', executable='Atelier.exe', port=args.debug_port)
    env = dict(os.environ, ATELIER_PORT=str(args.app_port), PYTHONUTF8='1',
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={args.debug_port}',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='localhost,127.0.0.1')
    env.pop('ATELIER_DATA_DIR', None)
    env.pop('ATELIER_DEBUG', None)
    journal('preparation-complete', installer_sha256=result['installer_sha256'],
            previous_installer_sha256=result['previous_installer_sha256'], payload_files=len(manifest_files))
    owned_pids = set()

    def fixture_window_pids(target):
        found = set()
        executable = (target / 'Atelier.exe').resolve(strict=True)

        @CALLBACK
        def inspect_pid(hwnd, unused):
            pid = wintypes.DWORD()
            USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            path = process_path(pid.value)
            if path and path.resolve() == executable:
                found.add(pid.value)
            return True

        if not USER32.EnumWindows(inspect_pid, 0):
            raise RuntimeError('Could not enumerate fixture application windows')
        if not found:
            raise RuntimeError('No native fixture application window found')
        journal('fixture-window-pids', target=str(target), pids=sorted(found))
        return found

    def verify_shortcuts(target, label, installed=True):
        # Read-only shortcut inspection. This subprocess runs only after VM admission.
        script = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$paths = @(
  (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Atelier.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Atelier\Atelier.lnk')
)
$items = @($paths | ForEach-Object {
  $present = Test-Path -LiteralPath $_ -PathType Leaf
  $destination = if ($present) { $shell.CreateShortcut($_).TargetPath } else { $null }
  [pscustomobject]@{ path = $_; exists = $present; target = $destination }
})
ConvertTo-Json -InputObject $items -Compress
"""
        journal('shortcut-inspection-start', step=label)
        # PowerShell 7 is already initialized by the hosted workflow. Avoid a
        # second, cold Windows PowerShell/.NET Framework startup during launch.
        inspected = subprocess.run(['pwsh.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                   capture_output=True, text=True, timeout=60, check=True)
        shortcuts = json.loads(inspected.stdout)
        if len(shortcuts) != 2:
            raise RuntimeError('Expected desktop and Start Menu shortcut inspection')
        for shortcut in shortcuts:
            if shortcut['exists'] != installed:
                raise AssertionError('Unexpected shortcut presence: ' + shortcut['path'])
            if installed and Path(shortcut['target']).resolve() != (target / 'Atelier.exe').resolve():
                raise AssertionError('Shortcut points to the wrong executable: ' + shortcut['path'])
        result.setdefault('shortcut_checks', []).append({'step': label, 'installed': installed, 'shortcuts': shortcuts})
        journal('shortcuts-verified', step=label, installed=installed)

    @CALLBACK
    def inspect_window(hwnd, action):
        pid = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = process_path(pid.value)
        if path and path.name.lower() == 'atelier.exe' and path.is_relative_to(report):
            owned_pids.add(pid.value)
            title = ctypes.create_unicode_buffer(256)
            USER32.GetWindowTextW(hwnd, title, 256)
            if title.value == 'Atelier':
                USER32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True

    def run_program(exe, arguments, label):
        exe = Path(exe).resolve(strict=True)
        if exe not in (installer, previous) and not exe.is_relative_to(report):
            raise RuntimeError('Refusing to run a non-fixture uninstaller')
        journal(label + '-start', executable=str(exe), arguments=arguments)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(exe), *arguments], env=env, startupinfo=startup)
        journal(label + '-spawned', pid=process.pid)
        deadline = time.monotonic() + 180
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError(f'{label} exceeded 180 seconds; process {process.pid}; dispose of the runner')
            time.sleep(.2)
        result['steps'].append({'step': label, 'exit_code': process.returncode})
        journal(label + '-exited', exit_code=process.returncode)
        if process.returncode != 0:
            raise RuntimeError(f'{label} failed: {process.returncode}')
        print('PASS ' + label, flush=True)

    def install(exe, target, label, explicit_directory=True):
        target = target.resolve()
        if not target.is_relative_to(report) or target == report:
            raise RuntimeError('Refusing an install target outside the fixture directory')
        entry = registration()
        if explicit_directory and entry is not None:
            raise RuntimeError('Refusing clean install over an existing registration')
        if not explicit_directory and (not entry or Path(entry['InstallLocation'][0]).resolve() != target):
            raise RuntimeError('Refusing upgrade of a non-fixture registration')
        arguments = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NORESTARTAPPLICATIONS',
                     '/CLOSEAPPLICATIONS', '/NOFORCECLOSEAPPLICATIONS', '/LOGCLOSEAPPLICATIONS',
                     '/TASKS=desktopicon', '/SP-', '/LOG=' + str(report / (label + '.log'))]
        if explicit_directory:
            arguments.append('/DIR=' + str(target))
        run_program(exe, arguments, label)
        entry = registration()
        if not entry or Path(entry['InstallLocation'][0]).resolve() != target:
            raise RuntimeError('Installer registered an unexpected target')
        assert (target / 'unins000.exe').is_file()
        verify_shortcuts(target, label)

    def verify_payload(target, preserve_seed=False):
        checked = 0
        expected = len(manifest_files)
        for item in manifest_files:
            if preserve_seed and item['path'] == 'Tools/MarvelRivalsCharacterIDs.md':
                expected -= 1
                continue
            path = (target / item['path']).resolve(strict=True)
            if not path.is_relative_to(target.resolve()):
                raise RuntimeError('Payload path escaped the installation directory')
            assert digest(path) == item['sha256'].lower(), item['path']
            checked += 1
        assert checked == expected
        journal('payload-verified', target=str(target), files=checked, preserved_seed=preserve_seed)
        return checked

    def close_apps():
        journal('fixture-close-start')
        USER32.EnumWindows(inspect_window, 1)
        wait_for(lambda: all(not alive(pid) for pid in tuple(owned_pids)), 'Fixture application did not close cleanly', timeout=45)
        journal('fixture-close-complete')

    def uninstall(target, label):
        close_apps()
        entry = registration()
        if not entry or Path(entry['InstallLocation'][0]).resolve() != target.resolve():
            raise RuntimeError('Refusing uninstall of a non-fixture registration')
        run_program(target / 'unins000.exe', ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                            '/LOG=' + str(report / (label + '.log'))], label)
        wait_for(lambda: registration() is None and not (target / 'Atelier.exe').exists(), 'Fixture uninstall did not finish')
        remaining = [item['path'] for item in manifest_files
                     if item['path'] != 'Tools/MarvelRivalsCharacterIDs.md' and (target / item['path']).exists()]
        assert not remaining, 'Uninstall retained program payload: ' + ', '.join(remaining)
        verify_shortcuts(target, label, installed=False)
        journal('uninstalled-payload-verified', step=label, removed_files=len(manifest_files) - sum(
            item['path'] == 'Tools/MarvelRivalsCharacterIDs.md' for item in manifest_files))

    def connect(pw):
        journal('native-connect-start')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoints = [f'http://127.0.0.1:{args.debug_port}', f'http://localhost:{args.debug_port}']
        connected = None
        last_errors = {}
        def debug_ready():
            nonlocal connected
            for endpoint in endpoints:
                try:
                    with opener.open(endpoint + '/json/version', timeout=2) as response:
                        version = json.load(response)
                    if not version.get('webSocketDebuggerUrl'):
                        raise ValueError('DevTools response omitted its WebSocket endpoint')
                    connected = version['webSocketDebuggerUrl']
                    journal('native-debug-ready', endpoint=endpoint, browser=version.get('Browser'))
                    return True
                except (OSError, ValueError) as exc:
                    last_errors[endpoint] = repr(exc)
            return False
        try:
            wait_for(debug_ready, 'Native WebView debugging endpoint did not become available', timeout=60)
        except AssertionError:
            journal('native-debug-unavailable', errors=last_errors)
            raise
        browser = pw.chromium.connect_over_cdp(connected)
        context = browser.contexts[0]
        # The debugging socket can precede WebView2's first page. Waiting here
        # also pumps Playwright's page-created event on slower hosted runners.
        page = context.pages[0] if context.pages else context.wait_for_event('page', timeout=60000)
        page.wait_for_load_state('domcontentloaded')
        journal('native-connect-complete', url=page.url)
        return browser, page

    try:
        if registration() is not None:
            raise RuntimeError('Atelier registration appeared after admission; refusing installer launch')
        with sync_playwright() as pw:
            fresh = report / 'Fresh install with spaces'
            assert not fresh.exists()
            install(installer, fresh, 'clean-install')
            result['clean_payload_files_verified'] = verify_payload(fresh)
            browser, page = connect(pw)
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            page.wait_for_selector('#setup-overlay.active')
            page.wait_for_selector('#setup-loading.active', state='hidden', timeout=60000)
            assert page.locator('#setup-path').is_editable(), 'Initial configuration never became usable'
            first = page.evaluate("""() => ({url: location.href, tokens: !!document.querySelector('link[href="/static/tokens.css"]'),
                font: getComputedStyle(document.body).fontFamily, setup: !!document.querySelector('#setup-overlay.active'),
                setup_ready: !document.querySelector('#setup-loading.active')})""")
            assert '?ui=' in first['url'] and first['tokens'] and 'Roboto' in first['font'] and first['setup'], first
            page.screenshot(path=str(report / 'clean-first-launch.png'))
            result['clean_first_launch'] = first
            journal('clean-first-launch-verified', **first)
            result['checks'].append('Clean install registers the selected directory and opens the styled first-time setup')
            uninstall(fresh, 'clean-uninstall')
            browser.close()

            upgrade = report / 'Upgrade install with spaces'
            install(previous, upgrade, 'previous-version-install')
            browser, page = connect(pw)
            page.wait_for_selector('#setup-overlay.active')
            result['previous_first_launch'] = page.evaluate("""() => ({url: location.href,
                tokens: !!document.querySelector('link[href="/static/tokens.css"]'),
                studioBrand: !!document.querySelector('.studio-brand')})""")
            journal('previous-first-launch-observed', **result['previous_first_launch'])
            close_apps()
            browser.close()
            project = upgrade / 'assets/projects/Upgrade project'
            project.mkdir(parents=True, exist_ok=True)
            protected = {
                'assets/projects/Upgrade project/keep.fixture': b'original project content',
                'assets/exported/keep.pak': b'original exported content',
                '_cache/keep.fixture': b'original cached content',
                'Tools/AES_KEY.txt': b'0' * 64,
                'Tools/Mappings/keep.usmap': b'original mapping content',
                'Tools/MarvelRivalsCharacterIDs.md': b'original user-edited character seed',
                'Tools/shaders/user-added.fixture': b'original extra shader file',
            }
            config = {'paks': str(upgrade / 'no-game-paks'), 'aes_key': '0' * 64,
                      'usmap': str(upgrade / 'Tools/Mappings/keep.usmap'), 'active_project': 'Upgrade project',
                      'mods_folder': str(upgrade / 'test-mods'), 'upgrade_canary': 'preserve-me'}
            protected['mr_config.json'] = json.dumps(config).encode()
            for name, content in protected.items():
                path = upgrade / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            stale = ('_internal/obsolete-fixture.dll', 'Tools/AtelierMesh/obsolete.fixture', 'Tools/retoc-rivals-cli/retired.fixture')
            for name in stale:
                path = upgrade / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'obsolete installed payload')
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            old_app = subprocess.Popen([str(upgrade / 'Atelier.exe')], cwd=upgrade, env=env, startupinfo=startup)
            browser, page = connect(pw)
            page.wait_for_selector('#topbar')
            page.evaluate("localStorage.setItem('atelier.theme', 'dark'); localStorage.setItem('atelier.upgrade-canary', 'preserve-me')")
            time.sleep(2)
            result['checks'].append('Previous installed version creates its own native browser profile and synthetic preferences')
            journal('previous-version-ready-for-upgrade', pid=old_app.pid, url=page.url)
            # Leave the old window running: Restart Manager must close it safely.
            install(installer, upgrade, 'running-app-upgrade', explicit_directory=False)
            assert not alive(old_app.pid), 'Installer did not close the previous application'
            browser.close()
            result['upgrade_payload_files_verified'] = verify_payload(upgrade, preserve_seed=True)
            assert all(not (upgrade / name).exists() for name in stale), 'Stale installer-owned payload survived'
            for name, content in protected.items():
                assert (upgrade / name).read_bytes() == content, 'Upgrade changed user data: ' + name
            browser, page = connect(pw)
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            page.wait_for_function("!!document.querySelector('.studio-brand')")
            initial = page.evaluate("""() => ({url: location.href, theme: localStorage.getItem('atelier.theme'),
                canary: localStorage.getItem('atelier.upgrade-canary'), tokens: !!document.querySelector('link[href="/static/tokens.css"]')})""")
            assert '?ui=' in initial['url'] and initial['tokens'] and initial['theme'] == 'dark' and initial['canary'] == 'preserve-me', initial
            result['upgrade_first_launch'] = initial
            journal('upgrade-first-launch-verified', **initial)
            context = browser.contexts[0]
            fixtures = {'/api/setup_status': {'configured': True}, '/api/prereqs': {'issues': []},
                        '/api/update_check': {'available': False}, '/api/index_warnings': {'failed': []},
                        '/api/stale_mips': {'ok': True, 'count': 0}, '/api/usmap_update_check': {'ok': True},
                        '/api/catalogue/status': {'updating': False, 'portraits': 0},
                        '/api/browse': [dict(type='folder', name=n, label=n, rel_path=n, count=3) for n in ('Characters', 'Textures', 'Materials', 'Maps')]}
            from urllib.parse import urlparse
            def fixture(route):
                value = fixtures.get(urlparse(route.request.url).path)
                route.fulfill(json=value) if value is not None else route.continue_()
            context.route('**/api/**', fixture)
            context.route('https://**', lambda route: route.fulfill(json={}))
            # The UI assertions below are the gate; Windows 2022's WebView2 can hold the full
            # load event past 30 s after an upgrade, so don't also wait for every subresource.
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("document.querySelectorAll('#grid-area .card').length === 4 && document.documentElement.dataset.theme === 'dark'")
            # Historical manifests can still exercise installers from before this feature.
            has_changelog = (upgrade / '_internal/gui/changelog.js').is_file()
            if has_changelog:
                expected_version = (upgrade / '_internal/version').read_text().strip()
                page.wait_for_selector('#changelog-overlay.active')
                assert page.locator('#changelog-version').inner_text() == 'Atelier ' + expected_version
                assert page.locator('.changelog-release h3').first.inner_text() == expected_version
                page.screenshot(path=str(report / 'upgrade-changelog.png'))
                with page.expect_response('**/api/changelog/acknowledge') as acknowledged:
                    page.locator('#changelog-done').click()
                assert acknowledged.value.ok
                page.wait_for_selector('#changelog-overlay.active', state='hidden')
                saved_config = json.loads((upgrade / 'mr_config.json').read_text())
                assert saved_config == dict(config, changelog_version=expected_version), saved_config
                protected['mr_config.json'] = (upgrade / 'mr_config.json').read_bytes()
                result['checks'].append('Installed upgrade shows bundled release notes and acknowledgement preserves every existing setting')
            page.screenshot(path=str(report / 'upgraded-interface.png'))
            assert not result['page_errors'], result['page_errors']
            result['checks'].append('Running-app upgrade detects its previous directory, replaces all payload, removes stale owned files and preserves user files/preferences')

            # Reinstall the exact same candidate over its running fixture.
            before_reinstall_pids = fixture_window_pids(upgrade)
            install(installer, upgrade, 'same-version-reinstall', explicit_directory=False)
            wait_for(lambda: all(not alive(pid) for pid in before_reinstall_pids),
                     'Same-version reinstall did not close its previous native window')
            browser.close()
            result['reinstall_payload_files_verified'] = verify_payload(upgrade, preserve_seed=True)
            for name, content in protected.items():
                assert (upgrade / name).read_bytes() == content, 'Reinstall changed user data: ' + name
            browser, page = connect(pw)
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            page.wait_for_function("!!document.querySelector('.studio-brand')")
            after_reinstall_pids = fixture_window_pids(upgrade)
            assert before_reinstall_pids.isdisjoint(after_reinstall_pids), 'Reinstall reused the old application process'
            result['reinstall_processes'] = {'before': sorted(before_reinstall_pids), 'after': sorted(after_reinstall_pids)}
            repeated = page.evaluate("""() => ({url: location.href, theme: localStorage.getItem('atelier.theme'),
                canary: localStorage.getItem('atelier.upgrade-canary'), tokens: !!document.querySelector('link[href="/static/tokens.css"]')})""")
            assert '?ui=' in repeated['url'] and repeated['tokens'] and repeated['theme'] == 'dark' and repeated['canary'] == 'preserve-me', repeated
            result['reinstall_first_launch'] = repeated
            if has_changelog:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.app_port}/api/changelog', timeout=10) as response:
                    notes = json.load(response)
                assert not notes['available'] and notes['version'] == expected_version, notes
                result['checks'].append('Reinstall retains the acknowledged changelog version without another update popup')
            journal('same-version-first-launch-verified', **repeated)
            page.screenshot(path=str(report / 'reinstalled-first-launch.png'))
            assert not result['page_errors'], result['page_errors']
            result['checks'].append('Same-version reinstall preserves synthetic user files and browser preferences')
            patch_canary = upgrade / '_internal/gui/later-patch-canary.js'
            patch_canary.write_text('// Added after installation by an app patch', encoding='utf-8')
            uninstall(upgrade, 'upgrade-uninstall')
            assert not patch_canary.exists(), 'Uninstall left an application file introduced by a patch'
            browser.close()
            for name, content in protected.items():
                assert (upgrade / name).read_bytes() == content, 'Uninstall removed user data: ' + name
            result['checks'].append('Uninstall removes program files and registration while retaining user data')
        result['installer_sha256_after'] = digest(installer)
        result['previous_installer_sha256_after'] = digest(previous)
        assert result['installer_sha256_after'] == result['installer_sha256']
        assert result['previous_installer_sha256_after'] == result['previous_installer_sha256']
        result['ok'] = True
        journal('all-checks-passed', installer_sha256=result['installer_sha256_after'])
    except Exception as exc:
        result['error'] = str(exc)
        raise


if __name__ == '__main__':
    main()
