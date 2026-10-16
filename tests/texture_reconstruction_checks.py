"""Edited textures reconstruct only after their real preview loads, with bounded cleanup."""
import io
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw


def texture_image(color):
    image = Image.new('RGBA', (160, 96), color)
    draw = ImageDraw.Draw(image)
    for x in range(8, 150, 24):
        draw.rectangle((x, 8, x + 14, 35), fill='#182b40')
        draw.rectangle((x, 64, x + 14, 88), fill='#b3c7dc')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def run_texture_reconstruction_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, requests, held, replacements = [], [], [], []
    state = {'hold': False, 'color': '#397aaa', 'fail': False}
    items = [dict(type='asset', file_type='texture', game_rel=f'Reconstruction/T_{name}_D',
                  name=f'T_{name}_D', token=f'reconstruction-{name}', imported=True, selected=True)
             for name in ('Body', 'Other')]

    def preview(route):
        query = parse_qs(urlparse(route.request.url).query)
        if not query.get('game_rel', [''])[0].startswith('Reconstruction/'):
            route.fallback()
            return
        requests.append(query)
        if state['hold'] and '_t' in query:
            held.append(route)
        elif state['fail'] and '_t' in query:
            route.fulfill(status=404, body='Fixture preview unavailable')
        else:
            route.fulfill(body=texture_image(state['color']), content_type='image/png')

    def replace(route):
        replacements.append(route.request.headers.get('x-atelier-project'))
        route.fulfill(json={'ok': True, 'token': items[0]['token'], 'game_rel': items[0]['game_rel']})

    def seed():
        tab.evaluate("""items => {
          document.getElementById('search-input').value = '';
          allItems = items; buildGrid(items.map(_makeCard));
          sidebarData = Object.fromEntries(items.map(item => [item.token, item]));
          renderSidebar();
        }""", items)
        tab.wait_for_function("""() => {
          const images = [...document.querySelectorAll('#grid-area img, #sidebar-list img')];
          return images.length === 4 && images.every(img => img.complete && img.naturalWidth === 160);
        }""")

    def edited():
        tab.evaluate("item => handleSSE({file_changed:true, game_rel:item.game_rel, token:item.token})", items[0])

    def settled():
        tab.wait_for_function("!document.querySelector('.texture-reconstruction')")

    try:
        tab.on('pageerror', lambda error: errors.append(str(error)))
        tab.route('**/api/thumb?*', preview)
        tab.route('**/api/preview?*', preview)
        tab.route('**/api/prefetch_thumbs', lambda route: route.fulfill(json={
            'ok': True, 'cached': [item['game_rel'] for item in items], 'pending': [], 'failed': []}))
        tab.route('**/api/replace_texture', replace)
        tab.emulate_media(reduced_motion='no-preference')
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card')
        tab.wait_for_function("!document.querySelector('.overlay.active')")
        tab.evaluate("_activeProjectName = 'Smoke A'")
        seed()
        assert tab.locator('.texture-reconstruction').count() == 0
        checks.append('Initial texture browsing and sidebar rendering remain still')

        # Hold the real replacement image: the effect must not stand in for loading.
        state['hold'] = True
        edited()
        tab.wait_for_function("document.querySelector('#grid-area img').src.includes('/api/preview?')")
        tab.wait_for_timeout(80)
        assert 1 <= len(held) <= 2, len(held)  # The browser may coalesce identical preview URLs.
        assert tab.locator('.texture-reconstruction').count() == 0
        for route in held:
            route.fulfill(body=texture_image('#b3537a'), content_type='image/png')
        held.clear()
        tab.wait_for_function("document.querySelectorAll('.texture-reconstruction').length === 2")
        assert tab.locator('.texture-reconstruction[data-swap-mode=wipe]').count() == 2
        assert tab.locator('#grid-area .card:nth-child(2) .texture-reconstruction').count() == 0
        assert tab.locator('#sidebar-list .sb-item:nth-child(2) .texture-reconstruction').count() == 0
        assert all(query['_project'] == ['Smoke A'] for query in requests if '_t' in query)
        tab.wait_for_timeout(160)
        tab.screenshot(path=str(report / 'texture-reconstruction-mid-animation.png'))
        settled()
        # Check the displayed pixels and contain fit after the animation has released its layers.
        assert tab.evaluate("""() => {
          const img = document.querySelector('#grid-area img');
          const canvas = document.createElement('canvas'); canvas.width = 1; canvas.height = 1;
          const ctx = canvas.getContext('2d'); ctx.drawImage(img, 80, 48, 1, 1, 0, 0, 1, 1);
          return [...ctx.getImageData(0,0,1,1).data];
        }""") == [179, 83, 122, 255]
        tab.screenshot(path=str(report / 'texture-reconstruction-settled.png'))
        checks.append('An external texture save reconstructs only the matching grid/sidebar previews after load, then shows the exact updated pixels')

        state.update(hold=False, color='#4f9873')
        tab.evaluate("item => { _ctxFileTarget = item.game_rel; }", items[0])
        tab.locator('#ctx-file-input').set_input_files({
            'name': 'replacement.png', 'mimeType': 'image/png', 'buffer': texture_image(state['color'])})
        tab.wait_for_function("document.querySelectorAll('.texture-reconstruction').length === 2")
        assert replacements == ['Smoke%20A'], replacements
        settled()
        checks.append('Replace Texture triggers the same effect for both previews using the originating project')

        # Repeated saves replace their previous effects rather than stacking canvases.
        edited()
        tab.wait_for_function("document.querySelectorAll('.texture-reconstruction').length === 2")
        edited()
        tab.wait_for_timeout(70)
        assert tab.locator('.texture-reconstruction').count() <= 2
        tab.emulate_media(reduced_motion='reduce')
        settled()
        edited()
        tab.wait_for_timeout(100)
        assert tab.locator('.texture-reconstruction').count() == 0
        assert tab.locator('.texture-reconstructing').count() == 0
        tab.emulate_media(reduced_motion='no-preference')
        assert tab.locator('.texture-reconstruction').count() == 0
        checks.append('Rapid saves replace in-flight effects; enabling reduced motion settles immediately and does not replay')

        # Failure and optional-controller/canvas loss retain the existing preview behavior.
        state['fail'] = True
        edited()
        tab.wait_for_timeout(100)
        assert tab.locator('.texture-reconstruction').count() == 0
        state['fail'] = False
        tab.evaluate("""() => {
          window.__reconstruction = window.AtelierTextureReconstruction;
          window.AtelierTextureReconstruction = undefined;
        }""")
        edited()
        tab.wait_for_timeout(100)
        assert tab.locator('#grid-area img').first.evaluate('(img) => img.naturalWidth') == 160
        assert tab.locator('.texture-reconstruction').count() == 0
        tab.evaluate("window.AtelierTextureReconstruction = window.__reconstruction")
        tab.evaluate("""() => {
          window.__getContext = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = () => null;
        }""")
        edited()
        tab.wait_for_timeout(100)
        assert tab.locator('.texture-reconstruction').count() == 0
        tab.evaluate('() => { HTMLCanvasElement.prototype.getContext = window.__getContext; }')
        checks.append('Failed image reads, absent motion controller and unavailable canvas keep usable static previews')

        # Discard pending effects when the owning project/grid is replaced.
        state['hold'] = True
        edited()
        tab.wait_for_timeout(80)
        assert 1 <= len(held) <= 2
        state['hold'] = False
        tab.evaluate("_activeProjectName = 'Smoke B'")
        seed()
        for route in held:
            try:
                route.fulfill(body=texture_image('#aa2244'), content_type='image/png')
            except Exception:
                pass  # Navigation may already have cancelled the old browser image request.
        held.clear()
        assert tab.locator('.texture-reconstruction').count() == 0
        edited()
        tab.wait_for_function("document.querySelectorAll('.texture-reconstruction').length === 2")
        tab.evaluate("""() => {
          allItems = []; buildGrid([]); sidebarData = {}; renderSidebar();
        }""")
        assert tab.locator('.texture-reconstruction').count() == 0
        checks.append('Project changes and grid/sidebar replacement dispose pending and running reconstruction layers')

        # Bulk saves have a fixed canvas budget, and hiding the page releases every effect.
        more = [dict(items[0], game_rel=f'Reconstruction/T_Bulk_{i}', name=f'T_Bulk_{i}',
                     token=f'reconstruction-bulk-{i}') for i in range(6)]
        tab.evaluate("""items => {
          allItems = items; buildGrid(items.map(_makeCard));
          sidebarData = Object.fromEntries(items.map(item => [item.token, item])); renderSidebar();
        }""", more)
        tab.wait_for_function("""() => [...document.querySelectorAll('#grid-area img, #sidebar-list img')]
          .every(img => img.complete && img.naturalWidth === 160)""")
        tab.evaluate("items => items.forEach(item => refreshEditedTexture(item.game_rel, item.token))", more)
        tab.wait_for_function("document.querySelectorAll('.texture-reconstruction').length === 4")
        assert tab.locator('.texture-reconstruction').count() == 4
        tab.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true, value:true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        assert tab.locator('.texture-reconstruction').count() == 0
        tab.evaluate("""() => {
          delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
        }""")
        tab.wait_for_timeout(80)
        assert tab.locator('.texture-reconstruction').count() == 0
        checks.append('Bulk updates cap reconstruction at four canvases; hidden pages release effects and do not replay')
        assert not errors, errors
    finally:
        tab.close()
