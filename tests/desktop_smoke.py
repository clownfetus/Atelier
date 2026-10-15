"""Launch a hidden native WebView2 window against the real local backend, then close it.

Requires ATELIER_DATA_DIR. Updates and thumbnail prefetch are suppressed in this smoke only.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
from wsgiref.simple_server import make_server, WSGIRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if not os.environ.get('ATELIER_DATA_DIR'):
        raise SystemExit('Set ATELIER_DATA_DIR to isolated development data.')
    print('Loading native desktop dependencies...', flush=True)
    from atelier import config as C
    from atelier.web import routes as R
    from atelier.web.app import _ThreadingWSGIServer
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
        if env['PATH_INFO'] in stubs:
            data = json.dumps(stubs[env['PATH_INFO']]).encode()
            respond('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(data)))])
            return [data]
        return R.app(env, respond)

    server = make_server('127.0.0.1', 0, app, _ThreadingWSGIServer, Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = webview.create_window('Atelier development smoke',
        f'http://127.0.0.1:{server.server_port}', hidden=True, width=1400, height=900)
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
                  const picker = document.querySelector('#topbar [data-theme-picker]');
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
                  document.querySelector('#grid-area .grid').appendChild(card);
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
                    card.remove();
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
    print('PASS native WebView2: real asset browser, project, symbols, font, logo, themes and viewport module loaded')
    print('Report:', report)


if __name__ == '__main__':
    main()
