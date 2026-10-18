"""Model Studio export controls against real HTTP jobs and a labelled worker fixture."""
from pathlib import Path
import threading
from unittest.mock import patch
from urllib.parse import unquote

from viewport_inspection_checks import HOOK

ROOT = Path(__file__).resolve().parents[1]


def run_model_studio_export_browser_checks(page, context, url, report, checks):
    from atelier import jobs as J
    from atelier.handlers import meshport

    tab = context.new_page()
    errors, calls, opens, headers = [], [], [], []
    release = threading.Event()
    failure = [False]
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.on('request', lambda request: headers.append(unquote(request.headers.get('x-atelier-project', '')))
           if request.url.endswith('/api/model_blender_export') else None)
    tab.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK,
        content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*', lambda route: route.fulfill(json=[
        {'name': name + ' fixture', 'kind': 'body', 'game_rel': 'Characters/1029/1029001/Meshes/' + name}
        for name in ('Body', 'Cape')]))
    tab.route('**/api/skin_materials', lambda route: route.fulfill(json={'ok': True, 'materials': {}}))
    tab.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok': True, 'animations': []}))
    tab.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs': []}))
    tab.route('**/api/model_blender_open', lambda route: (
        opens.append((route.request.post_data_json, unquote(route.request.headers['x-atelier-project']))),
        route.fulfill(json={'ok': True}))[-1])

    def worker(game_rel, weapons):
        calls.append({'game_rel': game_rel, 'weapons': weapons})
        J.progress('Packing fixture textures', current_count=2, total=4)
        assert release.wait(60), 'Browser did not release the fixture worker'
        if failure[0]:
            raise ValueError('Fixture texture could not be packed')
        return {'ok': True, 'meshes': 1, 'materials': 3, 'textures': 4, 'warnings': []}

    def models():
        if not tab.locator('#viewport-model-menu').evaluate('el=>el.open'):
            tab.locator('#viewport-model-menu > summary').click()

    try:
        tab.goto(url)
        tab.wait_for_function("window.__inspection && window.atelierProject?.() === 'Smoke A'")
        tab.wait_for_function("!document.querySelector('.overlay.active')")
        tab.evaluate("AtelierViewport.open('1029001', 'Blender export fixture — synthetic geometry')")
        tab.wait_for_function("document.getElementById('viewport-loading').style.display === 'none'")
        models()
        button = tab.locator('#viewport-blender-btn')
        assert button.is_enabled()
        tab.locator('#viewport-model-choice').select_option('all')
        models(); button.click()
        assert 'Choose one body form' in tab.locator('#viewport-status').inner_text()
        assert not calls
        tab.locator('#viewport-model-choice').select_option('0')
        models()
        tab.locator('#viewport-obj-section').evaluate('el=>el.open=true')
        tab.locator('.vp-obj input[type=checkbox]').first.uncheck()
        models()
        button.click()
        assert 'Show one body form' in tab.locator('#viewport-status').inner_text()
        assert not calls
        tab.locator('.vp-obj input[type=checkbox]').first.check()
        tab.locator('#viewport-obj-section').evaluate('el=>el.open=false')
        with patch.object(meshport, 'export', side_effect=worker):
            button.click()
            tab.wait_for_function("document.getElementById('job-activity').getAttribute('aria-label').includes('1 running')")
            assert button.is_disabled()
            assert 'Preparing model, materials and textures' in tab.locator('#viewport-status').inner_text()
            assert calls == [{'game_rel': 'Characters/1029/1029001/Meshes/Body', 'weapons': []}]
            for theme in ('light', 'dark'):
                tab.locator('#settings-theme').select_option(theme, force=True)
                tab.screenshot(path=str(report / ('model-blender-preparing-' + theme + '.png')))
            release.set()
            tab.wait_for_selector('#viewport-status button')
            assert button.is_enabled()
            assert '1 meshes · 3 materials · 4 packed textures' in tab.locator('#viewport-status').inner_text()
            for theme in ('light', 'dark'):
                tab.locator('#settings-theme').select_option(theme, force=True)
                for width, height in ((1024, 768), (1400, 900)):
                    tab.set_viewport_size({'width': width, 'height': height})
                    tab.get_by_role('button', name='Open in Blender', exact=True).click(trial=True)
                    assert tab.locator('#viewport-box').evaluate('el=>el.scrollWidth===el.clientWidth')
                    tab.screenshot(path=str(report / f'model-blender-complete-{theme}-{width}.png'))
            tab.get_by_role('button', name='Open in Blender', exact=True).click()
            tab.wait_for_timeout(100)
            assert opens == [({'game_rel': calls[0]['game_rel']}, 'Smoke A')]
            tab.screenshot(path=str(report / 'model-blender-complete.png'))
            failure[0] = True
            models()
            button.click()
            tab.wait_for_function("document.getElementById('viewport-status').textContent.includes('Fixture texture could not be packed')")
            assert button.is_enabled() and not tab.locator('#viewport-status button').count()
            failure[0] = False
            models()
            button.click()
            tab.wait_for_selector('#viewport-status button')
            assert button.is_enabled() and len(calls) == 3
        assert headers == ['Smoke A'] * 3, headers
        tab.evaluate('AtelierViewport.close()')
        tab.locator('#job-activity').click()
        tab.wait_for_function("document.querySelectorAll('.job-row').length>=3")
        assert tab.locator('.job-row').filter(has_text='Export model to Blender').count() == 3
        assert 'Fixture texture could not be packed' in tab.locator('#job-overlay').inner_text()
        tab.screenshot(path=str(report / 'model-blender-activity.png'))
        assert not errors, errors
        checks.append('Model Studio exports the selected body through project-scoped jobs, blocks hidden/multiple bodies and duplicate clicks, reports packed counts, keeps Open in Blender clickable in both themes and desktop sizes, and recovers from worker failure; Activity retains the outcomes')
    except Exception:
        tab.screenshot(path=str(report / 'model-blender-failure.png'))
        raise
    finally:
        release.set()
        tab.close()
