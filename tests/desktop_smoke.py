"""Launch a hidden native WebView2 window against the real local backend, then close it.

Requires ATELIER_DATA_DIR. Updates and thumbnail prefetch are suppressed in this smoke only.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from wsgiref.simple_server import make_server, WSGIRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', action='store_true', help='Use synthetic folders in isolated data; no game install required')
    parser.add_argument('--interactions', action='store_true', help='Exercise real WebView2 mouse/keyboard input through CDP and capture screenshots')
    args = parser.parse_args()
    if not os.environ.get('ATELIER_DATA_DIR'):
        raise SystemExit('Set ATELIER_DATA_DIR to isolated development data.')
    if args.interactions:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            debug_port = listener.getsockname()[1]
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'--remote-debugging-port={debug_port}'
    print('Loading native desktop dependencies...', flush=True)
    from atelier import config as C
    from atelier.web import routes as R
    from atelier.web.app import _ThreadingWSGIServer
    if args.fixtures:
        R._get_latest_usmap_from_github = lambda: None
        Path(C.project_dir('Desktop fixture')).mkdir(parents=True, exist_ok=True)
        C.set_active_project('Desktop fixture')
    import webview
    print('Starting native WebView2...', flush=True)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *_args):
            pass

    def app(env, respond):
        stubs = {'/api/update_check': {'available': False},
                 '/api/download_usmap': {'ok': True, 'path': C.USMAP},
                 '/api/prefetch_thumbs': {'ok': True},
                 '/api/usmap_update_check': {'ok': True}}
        stubs['/api/catalogue/status'] = {'updating': False, 'portraits': 803}
        if args.fixtures: stubs['/api/catalogue/library'] = {'heroes': []}
        if args.fixtures:
            stubs.update({
                '/api/setup_status': {'configured': True}, '/api/prereqs': {'issues': []},
                '/api/index_warnings': {'failed': []}, '/api/stale_mips': {'ok': True, 'count': 0},
                '/api/browse': [dict(type='folder', name=name, label=name, rel_path=name, count=3)
                                for name in ('Characters', 'UI', 'VFX', 'Maps')],
            })
        if env['PATH_INFO'] in stubs:
            data = json.dumps(stubs[env['PATH_INFO']]).encode()
            respond('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(data)))])
            return [data]
        return R.app(env, respond)

    server = make_server('127.0.0.1', 0, app, _ThreadingWSGIServer, Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from atelier.window_theme import WindowTheme
    native_appearance = WindowTheme(C.DATA_ROOT)
    window = webview.create_window('Atelier development smoke',
        f'http://127.0.0.1:{server.server_port}', hidden=True, width=1400, height=900,
        background_color=native_appearance._background(), js_api=native_appearance)
    native_appearance._attach(window)
    result = {}

    def verify():
        try:
            deadline = time.monotonic() + 60
            data = {}
            while time.monotonic() < deadline:
                data = window.evaluate_js("""({
                  title: document.title,
                  cards: document.querySelectorAll('#grid-area .card').length,
                  viewport: typeof window.AtelierViewport === 'object',
                  project: window.atelierProject?.(),
                  items: typeof allItems === 'undefined' ? 0 : allItems.length,
                  status: document.querySelector('.overlay.active')?.id || '',
                  icons: document.querySelectorAll('svg.lucide').length,
                  font: document.fonts.check('14px Roboto'),
                  logo: document.querySelector('.studio-brand img')?.naturalWidth || 0,
                  renderer: navigator.userAgent
                })""")
                if data and data.get('items') and data.get('viewport') and data.get('project') and data.get('icons'):
                    result.update(data)
                    break
                time.sleep(0.2)
            if not result:
                result.update(error='Interface did not become ready within 60 seconds', last_state=data)
            else:
                themes = window.evaluate_js("""(() => {
                  const picker = document.querySelector('#settings-theme');
                  return ['light', 'dark', 'system'].map(value => {
                    picker.value = value; picker.dispatchEvent(new Event('change'));
                    return {preference:value, theme:document.documentElement.dataset.theme,
                      settings:document.getElementById('settings-theme').value};
                  });
                })()""")
                assert result['font'] and result['logo'] > 0, result
                assert all(t['settings'] == t['preference'] for t in themes), themes
                assert [t['theme'] for t in themes[:2]] == ['light', 'dark'], themes
                result['themes'] = themes
                appearance = window.evaluate_js("""(() => {
                  const picker = document.querySelector('#settings-theme');
                  const rows = [];
                  for (const mode of ['light', 'dark']) {
                    picker.value=mode; picker.dispatchEvent(new Event('change'));
                    for (const preset of ['studio','darcula','repak']) {
                      document.querySelector('[data-theme-preset="'+preset+'"]').click();
                      const select = document.querySelector('#settings-theme'), option=select.options[0];
                      const probe=document.createElement('span');
                      probe.style.color=CSS.supports('appearance','base-select') && option.matches(':checked')
                        ? 'var(--md-sys-color-on-secondary-container)' : 'var(--text)';
                      document.body.append(probe); const expected=getComputedStyle(probe).color; probe.remove();
                      rows.push({mode, preset, theme:document.documentElement.dataset.theme,
                        palette:document.documentElement.dataset.palette,
                        scheme:getComputedStyle(select).colorScheme,
                        text:getComputedStyle(select).color, option:getComputedStyle(option).color, expected,
                        optionBackground:getComputedStyle(option).backgroundColor,
                        brand:getComputedStyle(document.querySelector('.studio-brand')).color});
                    }
                  }
                  document.querySelector('[data-theme-color="background"]').value='#080808';
                  document.querySelector('[data-theme-color="background"]').dispatchEvent(new Event('input'));
                  const customBackground=getComputedStyle(document.body).backgroundColor;
                  const name=document.getElementById('theme-palette-name');
                  name.value='Desktop custom'; name.dispatchEvent(new Event('input'));
                  document.getElementById('theme-palette-save').click();
                  const saved=document.querySelector('[data-saved-palette]');
                  const savedPalette=!!saved && saved.getAttribute('aria-pressed')==='true';
                  document.getElementById('theme-palette-delete').click();
                  document.querySelector('[data-theme-preset="studio"]').click();
                  return {rows, customBackground,
                    savedPalette, enhancedPicker:CSS.supports('appearance','base-select'),
                    nativeColors:[...document.querySelectorAll('[data-theme-color]')].every(el=>el.type==='color' && typeof el.showPicker==='function'),
                    menuLast:document.querySelector('#topbar > :last-child').id==='menu-btn',
                    headerPickers:document.querySelectorAll('#topbar [data-theme-picker]').length};
                })()""")
                assert appearance['nativeColors'] and appearance['menuLast'] and appearance['savedPalette'] and appearance['headerPickers'] == 0, appearance
                assert appearance['customBackground'] == 'rgb(8, 8, 8)', appearance
                assert all(row['theme'] == row['mode'] and row['palette'] == row['preset']
                           and row['scheme'] == row['mode'] and row['expected'] == row['option']
                           and row['optionBackground'] != 'rgba(0, 0, 0, 0)'
                           and row['brand'] == ('rgb(0, 0, 0)' if row['mode'] == 'light' else 'rgb(255, 255, 255)')
                           for row in appearance['rows']), appearance
                result['appearance'] = appearance
                motion = window.evaluate_js("""(() => {
                  const host = document.createElement('span'); document.body.append(host);
                  const instance = AtelierMotion.exportFeedback.mount(host, {state:'busy', reducedMotion:'reduce'});
                  const busy = host.dataset.amState;
                  instance.setState('success');
                  const success = host.dataset.amState;
                  const opacity = getComputedStyle(host.querySelector('.am-export-feedback-outcome-success')).opacity;
                  const animations = host.getAnimations({subtree:true}).length;
                  instance.destroy(); instance.destroy();
                  const clean = !host.querySelector('svg') && !host.dataset.amState;
                  host.remove(); return {busy, success, opacity, animations, clean};
                })()""")
                assert motion == {'busy': 'busy', 'success': 'success', 'opacity': '1',
                                  'animations': 0, 'clean': True}, motion
                result['export_motion'] = motion
                loader_motion = window.evaluate_js("""(() => {
                  const host = document.createElement('span'); document.body.append(host);
                  const instance = AtelierMotion.viewportLoader.mount(host, {state:'loading', reducedMotion:'reduce'});
                  const width = host.getBoundingClientRect().width;
                  const states = ['loading', 'empty', 'error', 'ready'].map(state => {
                    instance.setState(state);
                    return {state:host.dataset.amState, animations:host.getAnimations({subtree:true}).length};
                  });
                  instance.destroy(); instance.destroy();
                  const clean = !host.querySelector('svg') && !host.dataset.amState;
                  host.remove(); return {width, states, clean};
                })()""")
                assert loader_motion['width'] == 72 and loader_motion['clean'], loader_motion
                assert [s['state'] for s in loader_motion['states']] == ['loading', 'empty', 'error', 'ready'], loader_motion
                assert all(s['animations'] == 0 for s in loader_motion['states']), loader_motion
                result['viewport_motion'] = loader_motion
                folder_motion = window.evaluate_js("""(() => {
                  // Root categories can all have dedicated symbols. Exercise the real
                  // generic-folder renderer without rebuilding the grid or changing navigation.
                  const item = _makeCard({type:'folder', name:'Miscellaneous', rel_path:'NativeSmoke/Miscellaneous'});
                  const card = document.createElement('button');
                  card.className = 'card'; card.type = 'button';
                  card.dataset.amReduced = 'true';
                  const thumb = document.createElement('div'); thumb.className = 'card-thumb';
                  thumb.appendChild(renderCardIcon(item, card));
                  const name = document.createElement('div'); name.className = 'card-name';
                  name.textContent = item.label;
                  card.append(thumb, name);
                  const fullSize = document.createElement('div'); fullSize.className='grid'; fullSize.style.setProperty('--card-w','156px');
                  fullSize.append(card); document.body.append(fullSize);
                  try {
                    const svg = card.querySelector('.am-folder-flap');
                    const front = svg.querySelector('.am-folder-flap-front');
                    // Hidden WebView2 cannot receive keyboard focus; browser smoke covers it.
                    return {width:svg.getBoundingClientRect().width,
                      hidden:svg.getAttribute('aria-hidden'),
                      transform:getComputedStyle(front).transform,
                      transition:getComputedStyle(front).transitionDuration,
                      animations:svg.getAnimations({subtree:true}).length};
                  } finally {
                    fullSize.remove();
                  }
                })()""")
                assert 101 <= folder_motion['width'] <= 103, folder_motion
                assert folder_motion['hidden'] == 'true' and folder_motion['transform'] == 'none', folder_motion
                assert folder_motion['transition'] == '0s' and folder_motion['animations'] == 0, folder_motion
                result['folder_motion'] = folder_motion
                material_motion = window.evaluate_js("""(() => {
                  const host = document.createElement('span'); document.body.append(host);
                  const instance = AtelierMotion.materialSave.mount(host, {state:'saving', reducedMotion:'reduce'});
                  const width = host.getBoundingClientRect().width;
                  const states = ['saving', 'success', 'warning', 'error'].map(state => {
                    instance.setState(state);
                    const visible = state === 'saving' ? '.am-material-save-saving-ring' : '.am-material-save-outcome-' + state;
                    return {state:host.dataset.amState, opacity:getComputedStyle(host.querySelector(visible)).opacity,
                      animations:host.getAnimations({subtree:true}).length};
                  });
                  instance.destroy(); instance.destroy();
                  const clean = !host.querySelector('svg') && !host.dataset.amState;
                  host.remove(); return {width, states, clean};
                })()""")
                assert material_motion['width'] == 24 and material_motion['clean'], material_motion
                assert [s['state'] for s in material_motion['states']] == ['saving', 'success', 'warning', 'error'], material_motion
                assert all(float(s['opacity']) > .9 and s['animations'] == 0 for s in material_motion['states']), material_motion
                result['material_save_motion'] = material_motion
                # Hidden desktop startup may intentionally skip the logo entrance.
                # Exercise the component independently, preserving the real fallback.
                window.evaluate_js("""(() => {
                  const host = document.createElement('span'); document.body.append(host);
                  const original = document.querySelector('.studio-brand > img');
                  const instance = AtelierMotion.logoEntrance.mount(host, {
                    state:'entering', reducedMotion:'reduce', logoSrc:original.currentSrc || original.src
                  });
                  window.__desktopLogoMotion = {host, instance, ready:false, error:''};
                  instance.ready.then(() => {window.__desktopLogoMotion.ready=true;},
                    error => {window.__desktopLogoMotion.error=String(error);});
                })()""")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    readiness = window.evaluate_js("({ready:__desktopLogoMotion.ready,error:__desktopLogoMotion.error})")
                    if readiness['ready'] or readiness['error']:
                        break
                    time.sleep(0.05)
                assert readiness['ready'] and not readiness['error'], readiness
                logo_motion = window.evaluate_js("""(() => {
                  const {host, instance} = window.__desktopLogoMotion;
                  const brand = document.querySelector('.studio-brand');
                  const marks = [...brand.querySelectorAll(':scope > img, :scope > [data-atelier-motion="logo-entrance"]')]
                    .filter(el => getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0);
                  const visibleWidth = marks[0]?.getBoundingClientRect().width;
                  const result = {width:host.getBoundingClientRect().width, state:host.dataset.amState,
                    opacity:getComputedStyle(host.querySelector('.am-logo-entrance-stage')).opacity,
                    animations:host.getAnimations({subtree:true}).length,
                    ready:host.dataset.amReady, visibleMarks:marks.length, visibleWidth,
                    startupAPI:typeof AtelierLogoEntranceUI.destroy === 'function'};
                  instance.destroy(); instance.destroy(); instance.replay();
                  result.clean = !host.querySelector('svg') && !host.dataset.amState;
                  host.remove(); delete window.__desktopLogoMotion; return result;
                })()""")
                assert logo_motion == {'width': 32, 'state': 'settled', 'opacity': '1',
                                       'animations': 0, 'ready': 'true', 'visibleMarks': 1,
                                       'visibleWidth': 32, 'startupAPI': True, 'clean': True}, logo_motion
                result['logo_entrance'] = logo_motion
                empty_motion = window.evaluate_js("""(() => {
                  const host = document.createElement('div'); document.body.append(host);
                  const instance = AtelierMotion.emptyAssets.mount(host, {state:'entering', reducedMotion:'reduce'});
                  instance.replay(); instance.setState('settled');
                  const result = {width:host.getBoundingClientRect().width, state:host.dataset.amState,
                    hidden:host.querySelector('svg').getAttribute('aria-hidden'),
                    animations:host.getAnimations({subtree:true}).length,
                    sidebarAPI:typeof AtelierEmptyAssetsUI.confirmed === 'function'};
                  instance.destroy(); instance.destroy(); instance.replay();
                  result.clean = !host.querySelector('svg') && !host.dataset.amState;
                  host.remove(); return result;
                })()""")
                assert empty_motion == {'width': 112, 'state': 'settled', 'hidden': 'true',
                                        'animations': 0, 'sidebarAPI': True, 'clean': True}, empty_motion
                result['empty_assets_motion'] = empty_motion
                polish = window.evaluate_js("""(() => {
                  const motion=document.getElementById('settings-motion');motion.value='off';motion.dispatchEvent(new Event('change'));
                  const density=document.getElementById('settings-density');density.value='compact';density.dispatchEvent(new Event('change'));
                  const operation=toastSpinner('Native packing fixture');operation.resolve('Native complete','success',4000);
                  const same=operation.isConnected && operation.dataset.operationState==='success';operation.remove();
                  toast('Native repeat fixture','info');toast('Native repeat fixture','info');
                  const repeated=document.querySelector('.toast-repeat')?.textContent==='×2';
                  document.getElementById('toast-area').replaceChildren();
                  const host=document.createElement('div');document.body.append(host);
                  const instance=AtelierMotion.polish.mount(host,{frames:[{opacity:0},{opacity:1}],state:'playing'});
                  const staticMotion=host.getAnimations().length===0;instance.destroy();instance.destroy();host.remove();
                  AtelierPolish.importStart([{name:'A',game_rel:'A'},{name:'B',game_rel:'B'}]);
                  AtelierPolish.importProgress({game_rel:'A',ok:true});AtelierPolish.importProgress({game_rel:'B',ok:false});
                  const segments=document.querySelectorAll('#import-segments [data-state=done]').length===1 && document.querySelectorAll('#import-segments [data-state=failed]').length===1;
                  const palette=document.querySelector('[data-theme-preset=blueprint]');palette.click();
                  const newPalette=document.documentElement.dataset.palette==='blueprint';
                  document.querySelector('[data-theme-preset=studio]').click();
                  const theme=document.getElementById('settings-theme');theme.value='dark';theme.dispatchEvent(new Event('change'));
                  return {same,repeated,staticMotion,segments,newPalette,compact:document.documentElement.dataset.density==='compact',
                    continuity:typeof AtelierContinuity.closeEditor==='function',roster:typeof AtelierRoster.show==='function',
                    logoReplay:document.querySelector('.studio-brand').getAttribute('role')==='button'};
                })()""")
                assert all(polish.values()), polish
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    saved=json.loads(native_appearance._path.read_text(encoding='utf-8')) if native_appearance._path.exists() else {}
                    if saved.get('preference')=='dark' and saved.get('dark')=='#17191d': break
                    time.sleep(.05)
                assert saved.get('preference')=='dark', saved
                import ctypes
                from ctypes import wintypes
                hwnd=int(window.native.Handle.ToInt64())
                get_attribute=ctypes.windll.dwmapi.DwmGetWindowAttribute
                get_attribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
                dark=ctypes.c_int(); caption=ctypes.c_int()
                assert get_attribute(hwnd,20,ctypes.byref(dark),4)==0 and dark.value==1
                caption_supported=get_attribute(hwnd,35,ctypes.byref(caption),4)==0
                if caption_supported:
                    assert caption.value==0x1d1917, hex(caption.value)
                result['polish']={**polish,'native_dark':dark.value,'caption_supported':caption_supported,'caption_color':caption.value if caption_supported else None,'launch_background':WindowTheme(C.DATA_ROOT)._background()}
                if args.interactions:
                    # WebView2 suspends screenshot frames while its native window
                    # is hidden. Show this isolated fixture window for CDP capture.
                    window.show()
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as pw:
                        browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}')
                        context = browser.contexts[0]
                        context.route('https://**', lambda route: route.fulfill(json={}))
                        page = next(p for p in context.pages if p.url.startswith('http://127.0.0.1:'))
                        page_errors = []
                        page.on('pageerror', lambda error: page_errors.append(str(error)))
                        page.evaluate('openPaths()')
                        page.wait_for_function('!document.getElementById("setup-loading").classList.contains("active")')
                        picker = page.locator('#settings-theme')
                        picker.select_option('light')
                        picker.click()
                        page.screenshot(path=str(Path(C.DATA_ROOT) / 'desktop-dropdown-light.png'), animations='disabled')
                        page.keyboard.press('ArrowDown'); page.keyboard.press('Enter')
                        assert picker.input_value() == 'dark'
                        picker.click(); page.keyboard.press('Escape')
                        assert picker.input_value() == 'dark'
                        page.locator('[data-theme-preset="repak"]').click()
                        page.locator('[data-theme-color="background"]').fill('#080808')
                        page.locator('#theme-palette-name').fill('Desktop saved palette')
                        page.locator('#theme-palette-save').click()
                        selected = page.locator('html').get_attribute('data-palette')
                        assert selected.startswith('palette-')
                        page.reload()
                        page.wait_for_selector('#grid-area .card')
                        assert page.locator('html').get_attribute('data-palette') == selected
                        assert page.locator('html').get_attribute('data-theme') == 'dark'
                        page.evaluate('openPaths()')
                        page.wait_for_function('!document.getElementById("setup-loading").classList.contains("active")')
                        assert page.locator('[data-saved-palette]', has_text='Desktop saved palette').is_visible()
                        for mode in ('light', 'dark'):
                            picker.select_option(mode)
                            page.screenshot(path=str(Path(C.DATA_ROOT) / f'desktop-settings-{mode}.png'), animations='disabled')
                        page.locator('#setup-close').click()
                        page.screenshot(path=str(Path(C.DATA_ROOT) / 'desktop-workspace-dark.png'), animations='disabled')
                        assert not page_errors, page_errors
                        from viewport_inspection_checks import run_viewport_inspection_checks
                        viewer_checks=[]
                        run_viewport_inspection_checks(page,context,f'http://127.0.0.1:{server.server_port}',Path(C.DATA_ROOT),viewer_checks,reuse_page=True)
                        result['viewer_checks']=viewer_checks
                        result['interactions'] = ['WebView2 mouse opens the styled dropdown',
                            'ArrowDown/Enter select Dark; Escape preserves the choice',
                            'native color input and named palette survive WebView2 reload',
                            'light/dark Settings and workspace screenshots captured with no page errors']
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            print('Desktop result:', result, flush=True)
            window.destroy()

    try:
        webview.start(verify, gui='edgechromium', private_mode=False,
                      storage_path=str(Path(C.DATA_ROOT) / 'desktop-smoke-profile'))
    finally:
        server.shutdown()
        server.server_close()
        R._observer.stop()
        R._observer.join()
    report = Path(C.DATA_ROOT) / 'desktop-smoke.json'
    report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert 'error' not in result, result
    print('PASS native WebView2: browser, project, symbols, font, monochrome logo, palettes, dropdown roles and viewport module loaded'
          + (' (synthetic folder fixtures)' if args.fixtures else ' (real assets)'))
    print('Report:', report)


if __name__ == '__main__':
    main()
