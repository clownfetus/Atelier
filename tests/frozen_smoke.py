"""Exercise a built Windows executable in its real WebView2 shell, with isolated data.

Requires Playwright in the test interpreter and an installed WebView2 runtime.
Game browsing uses explicit HTTP fixtures; no game tools, exports or installs run.
The application starts hidden, uses a fresh data directory and closes after checks.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request


def wait_port(port, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Executable exited during startup: {process.returncode}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3):
                return
        except OSError:
            time.sleep(.1)
    raise TimeoutError(f'Port {port} did not open')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--debug-port', type=int, default=9338)
    parser.add_argument('--app-port', type=int, default=8778)
    parser.add_argument('--profile-source', type=Path, help='Copy an existing _webview directory to exercise an upgrade')
    parser.add_argument('--expected-theme', choices=('light', 'dark'))
    parser.add_argument('--expect-storage-canary', action='store_true', help='Require the seeded atelier.upgrade-canary preference')
    parser.add_argument('--viewer-checks', action='store_true', help='Exercise real Three.js controls, effects and capture in the packaged WebView2')
    parser.add_argument('--roster-checks', action='store_true', help='Exercise roster arrows and artwork colours in native WebView2')
    parser.add_argument('--viewer-followups',action='store_true',help='Verify texture recovery, contextual controls and model replacement in WebView2')
    parser.add_argument('--mesh', type=Path, help='Optional real decoded GLB for viewer verification')
    parser.add_argument('--idle', type=Path, help='Optional real decoded standing idle tracks')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('The frozen desktop smoke requires Windows.')
    exe = args.exe.resolve(strict=True)
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    data = report / 'isolated-data'
    data.mkdir(exist_ok=False)
    if args.profile_source:
        shutil.copytree(args.profile_source.resolve(strict=True), data / '_webview')
    for port in (args.app_port, args.debug_port):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} is in use; no running application was stopped.')
    project = data / 'assets' / 'projects' / 'Frozen smoke'
    project.mkdir(parents=True)
    (data / 'mr_config.json').write_text(json.dumps({
        'paks': str(data / 'no-game-paks'), 'tools': str(data / 'Tools'),
        'active_project': 'Frozen smoke', 'mods_folder': str(data / 'test-mods'),
    }), encoding='utf-8')
    env = os.environ.copy()
    env['ATELIER_DATA_DIR'] = str(data)
    env['ATELIER_PORT'] = str(args.app_port)
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'--remote-debugging-port={args.debug_port}'
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen([str(exe)], cwd=exe.parent, env=env, startupinfo=startup)
    stop_hiding = threading.Event()
    # pywebview can show its own window after process startup. Hide only this PID.
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def hide_window(hwnd, _):
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
        return True

    def hide_loop():
        while not stop_hiding.wait(.05):
            ctypes.windll.user32.EnumWindows(hide_window, 0)

    hider = threading.Thread(target=hide_loop, daemon=True)
    hider.start()
    result = {'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
              'checks': [], 'page_errors': [], 'fixture_scope': 'Game browsing and remote checks only'}
    try:
        wait_port(args.app_port, process)
        wait_port(args.debug_port, process)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{args.debug_port}')
            context = browser.contexts[0]
            page = context.pages[0]
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            page.wait_for_load_state('domcontentloaded')
            # Check the first navigation before reload can hide a stale cached page.
            page.wait_for_function("!!document.querySelector('.studio-brand')", timeout=15000)
            initial = page.evaluate("""() => ({
                url: location.href,
                tokens: !!document.querySelector('link[href="/static/tokens.css"]'),
                storedTheme: localStorage.getItem('atelier.theme'),
                upgradeCanary: localStorage.getItem('atelier.upgrade-canary')
            })""")
            assert '?ui=' in initial['url'] and initial['tokens'], initial
            if args.expected_theme:
                assert initial['storedTheme'] == args.expected_theme, initial
            if args.expect_storage_canary:
                assert initial['upgradeCanary'] == 'preserve-me', initial
            result['initial_navigation'] = initial
            result['existing_profile'] = bool(args.profile_source)
            result['checks'].append('First native navigation bypasses cached HTML and preserves browser preferences')
            fixture_items = [dict(type='folder', name=n, label=n, rel_path=n, count=3)
                             for n in ('Characters', 'Textures', 'Materials', 'Weapons', 'Audio', 'Maps')]
            fixtures = {
                '/api/update_check': {'available': False},
                '/api/setup_status': {'configured': True},
                '/api/prereqs': {'issues': []}, '/api/browse': fixture_items,
                '/api/index_warnings': {'failed': []},
                '/api/stale_mips': {'ok': True, 'count': 0},
                '/api/usmap_update_check': {'ok': True},
                '/api/catalogue/status': {'updating': False, 'portraits': 0},
            }
            from urllib.parse import urlparse
            def fixture(route):
                value = fixtures.get(urlparse(route.request.url).path)
                route.fulfill(json=value) if value is not None else route.continue_()
            context.route('**/api/**', fixture)
            context.route('https://**', lambda route: route.fulfill(json={}))
            page.reload()
            page.wait_for_function("window.AtelierViewport && window.atelierProject?.() === 'Frozen smoke'")
            page.wait_for_function("document.querySelectorAll('#grid-area .card').length === 6")
            page.wait_for_function("!document.querySelector('.overlay.active')")
            page.wait_for_function("document.querySelector('[data-atelier-motion=\"empty-assets\"]')?.getBoundingClientRect().width === 112")
            result['renderer'] = page.evaluate('navigator.userAgent')
            result['checks'].append('Actual frozen executable serves the interface in native WebView2')
            info = page.evaluate("""() => ({
                library: typeof AtelierLibraryTools === 'object',
                pins: typeof AtelierLibraryPins === 'object',
                exportReview: typeof AtelierExportReview === 'object',
                originalComparison: typeof materialDirtyCount === 'function',
                motions: Object.keys(AtelierMotion).sort(),
                folderMotion: !!document.querySelector('link[href$="folder-flap.css"]'),
                font: document.fonts.check('14px Roboto'),
                logo: document.querySelector('.studio-brand > img').naturalWidth,
                emptyTray: document.querySelector('[data-atelier-motion="empty-assets"]')?.getBoundingClientRect().width,
                singleMark: [...document.querySelectorAll('.studio-brand > img, .studio-brand > [data-atelier-motion="logo-entrance"]')]
                  .filter(el => getComputedStyle(el).display !== 'none').length
            })""")
            assert all(info[k] for k in ('library', 'pins', 'exportReview', 'originalComparison', 'folderMotion', 'font')), info
            assert info['motions'] == ['emptyAssets', 'exportFeedback', 'logoEntrance', 'materialSave', 'polish', 'viewportLoader'], info
            assert info['logo'] > 0 and info['emptyTray'] == 112 and info['singleMark'] == 1, info
            result['interface'] = info
            result['checks'].append('All workflow modules, six motion sets, local font and logo load from the frozen bundle')
            for theme in ('light', 'dark'):
                page.locator('#settings-theme').select_option(theme, force=True)
                assert page.evaluate('document.documentElement.dataset.theme') == theme
                page.screenshot(path=str(report / f'frozen-{theme}.png'))
            result['checks'].append('Light and dark themes render in the native shell')
            # Confirm the real frozen backend registered the new endpoint, without native tools.
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{args.app_port}/api/material_original?game_rel=../outside',timeout=10)
            except urllib.error.HTTPError as response:
                assert response.code == 400, response.code
                rejected = json.load(response)
            else:
                raise AssertionError('Invalid material path was not rejected with HTTP 400')
            assert rejected.get('ok') is False and rejected.get('error'), rejected
            result['checks'].append('Frozen Python backend includes original-material comparison and rejects traversal')
            assert not result['page_errors'], result['page_errors']
            for path in ('/', '/?ui=upgrade-check', '/static/tokens.css'):
                with urllib.request.urlopen(f'http://127.0.0.1:{args.app_port}{path}',timeout=10) as reply:
                    assert 'no-store' in reply.headers.get('Cache-Control', ''), path
            result['checks'].append('HTML and frontend assets prevent stale caching after the upgrade')
            if args.viewer_checks or args.roster_checks or args.viewer_followups:
                # WebView2 throttles animation frames in hidden native windows.
                # Show only this isolated test window, without taking focus.
                stop_hiding.set(); hider.join(timeout=2)
                @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def show_viewer(hwnd, _):
                    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==process.pid:ctypes.windll.user32.ShowWindow(hwnd,4)
                    return True
                ctypes.windll.user32.EnumWindows(show_viewer,0)
            if args.viewer_checks:
                from viewport_inspection_checks import run_viewport_inspection_checks
                source=Path(__file__).resolve().parents[1]/'gui'
                for name in ('index.html','viewport.js','viewport-inspection.js','viewport-animation.js','viewport-effects.js','viewport.css','vendor/material-symbols/symbols.js'):
                    assert (source/name).read_bytes()==(exe.parent/'_internal'/'gui'/name).read_bytes(),name
                run_viewport_inspection_checks(page,context,f'http://127.0.0.1:{args.app_port}',report,result['checks'],args.mesh,args.idle,reuse_page=True)
            if args.viewer_followups:
                from viewer_followup_checks import run_viewer_followup_checks
                run_viewer_followup_checks(page,context,f'http://127.0.0.1:{args.app_port}',report,result['checks'],reuse_page=True)
            if args.roster_checks:
                from viewport_loading_checks import run_hero_artwork_checks
                source=Path(__file__).resolve().parents[1]/'gui'
                for name in ('roster.js','roster.css','polish.js'):
                    assert (source/name).read_bytes()==(exe.parent/'_internal'/'gui'/name).read_bytes(),name
                run_hero_artwork_checks(page,context,f'http://127.0.0.1:{args.app_port}',report,result['checks'],reuse_page=True)
                result['checks'].append('Packaged roster and colour sampler match the verified source')
            browser.close()
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        stop_hiding.set()
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        (report / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    for check in result['checks']:
        print('PASS ' + check)
    print('Report:', report / 'results.json')


if __name__ == '__main__':
    main()
