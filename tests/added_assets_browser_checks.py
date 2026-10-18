"""Real Add asset dialog, multipart uploads, background jobs and saved project files."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from unittest.mock import patch

from added_asset_fixtures import AssetTool, decode_png, image_bytes, package


def run_added_asset_checks(page, context, url, report, checks):
    from atelier import added_assets as A, config as C
    from atelier.handlers import custom_texture as CT, material as M, texture as T
    from atelier.web import browse as B
    previous = C.get_active_project()
    name = 'Add assets browser'
    root = Path(C.PROJECTS_ROOT, name); root.mkdir(exist_ok=True)
    tab = context.new_page(); errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        with tempfile.TemporaryDirectory(prefix='atelier-add-browser-') as temporary, ExitStack() as stack:
            sources = {kind: package(Path(temporary, A.PREFIXES[kind] + 'Source.uasset'), kind) for kind in A.CLASSES}
            paths = {kind: 'Fixtures/' + kind.title() + 's/' + path.stem for kind, path in sources.items()}
            entries = [(gr + '.uasset',) for gr in paths.values()]
            tool = AssetTool(); ensure = T.ensure_work_base
            by_path = {paths[kind]: str(path.with_suffix('')) for kind, path in sources.items()}
            for module in (A, CT, T, M): stack.enter_context(patch.object(module, 'uat', tool))
            for module in (A, B): stack.enter_context(patch.object(module, 'ensure_index', return_value=entries))
            stack.enter_context(patch.object(T, 'decode_to_png', side_effect=decode_png))
            stack.enter_context(patch.object(T, 'ensure_work_base', side_effect=lambda gr: by_path.get(gr) or ensure(gr)))
            tab.route('**/api/browse?*', lambda route: route.continue_())
            tab.route('**/api/thumb?*', lambda route: route.fulfill(body=image_bytes(), content_type='image/png'))
            tab.route('**/api/prefetch_thumbs', lambda route: route.fulfill(json={
                'ok': True, 'cached': route.request.post_data_json['game_rels'], 'pending': [], 'failed': []}))
            tab.goto(url)
            tab.wait_for_function("window.atelierProject && !document.querySelector('.overlay.active')")
            tab.evaluate('async name => { await _selectProject(name); }', name)
            open_button = tab.locator('#add-asset-open')
            assert open_button.is_enabled() and tab.locator('#process-s-maps').is_disabled()
            bounds = [tab.locator(selector).bounding_box() for selector in ('#add-asset-open', '#process-s-maps')]
            assert abs(bounds[0]['y'] - bounds[1]['y']) < 2
            assert bounds[0]['x'] + bounds[0]['width'] <= bounds[1]['x']
            open_button.click()
            tab.locator('#add-asset-name').fill('MyPaint_D')
            tab.locator('#add-asset-files').set_input_files({'name': 'My paint.png', 'mimeType': 'image/png', 'buffer': image_bytes()})
            tab.locator('#add-asset-source').locator('..').get_by_role('button', name='Browse…', exact=True).click()
            tab.locator('.add-asset-browser-items button[data-path="Fixtures"]').click()
            tab.locator('.add-asset-browser-items button[data-path="Fixtures/Textures"]').click()
            tab.locator('.add-asset-browser-items button[data-path="' + paths['texture'] + '"]').click()
            assert tab.locator('#add-asset-source').input_value() == paths['texture']
            tab.locator('#add-asset-folder').locator('..').get_by_role('button', name='Browse…', exact=True).click()
            tab.locator('.add-asset-browser-items button[data-path="Fixtures"]').click()
            tab.locator('.add-asset-browser-items button[data-path="Fixtures/Textures"]').click()
            tab.locator('#add-asset-use-folder').click()
            assert tab.locator('#add-asset-folder').input_value() == 'Fixtures/Textures'
            tab.locator('#add-asset-folder').fill('Custom/Textures')
            assert tab.locator('#add-asset-path').inner_text() == '/Game/Marvel/Custom/Textures/T_MyPaint_D'
            tab.locator('#add-asset-submit').click()
            texture = 'Custom/Textures/T_MyPaint_D'
            tab.wait_for_function('gr => Object.values(sidebarData).some(row => row.game_rel === gr)', arg=texture)
            assert (root / (texture + '.png')).read_bytes() == image_bytes()
            assert tab.locator('#process-s-maps').is_enabled()
            checks.append('Add asset sits beside Process S maps, browses real game folders and uploads image bytes to a named project texture')

            # The exact same destination reports an error and preserves the form and saved image.
            open_button.click(); tab.locator('#add-asset-name').fill('MyPaint_D')
            tab.locator('#add-asset-files').set_input_files({'name': 'new.png', 'mimeType': 'image/png', 'buffer': image_bytes((1, 2, 3, 255))})
            tab.locator('#add-asset-source').fill(paths['texture']); tab.locator('#add-asset-folder').fill('Custom/Textures')
            tab.locator('#add-asset-submit').click()
            tab.wait_for_function("document.querySelector('#add-asset-status').textContent.includes('already exists')")
            tab.wait_for_function("!document.querySelector('#add-asset-submit').disabled")
            assert tab.locator('#add-asset-overlay').is_visible()
            assert (root / (texture + '.png')).read_bytes() == image_bytes()
            tab.keyboard.press('Escape'); assert open_button.evaluate('node => node === document.activeElement')

            open_button.click(); tab.locator('#add-asset-type').select_option('material')
            tab.locator('#add-asset-mode').select_option('game'); tab.locator('#add-asset-name').fill('MyMaterial')
            tab.locator('#add-asset-source').fill(paths['material']); tab.locator('#add-asset-folder').fill('/Game/Marvel/Custom/Materials')
            tab.locator('#add-asset-submit').click()
            material = 'Custom/Materials/MI_MyMaterial'
            tab.wait_for_function('gr => Object.values(sidebarData).some(row => row.game_rel === gr)', arg=material)
            assert (root / (material + '.json')).is_file()

            open_button.click(); tab.locator('#add-asset-type').select_option('mesh')
            tab.locator('#add-asset-name').fill('MyMesh'); tab.locator('#add-asset-folder').fill('Custom/Meshes')
            tab.locator('#add-asset-files').set_input_files([str(sources['mesh']), str(sources['mesh'].with_suffix('.uexp'))])
            assert not tab.locator('#add-asset-source').is_visible()
            tab.locator('#add-asset-submit').click()
            model = 'Custom/Meshes/SK_MyMesh'
            tab.wait_for_function('gr => Object.values(sidebarData).some(row => row.game_rel === gr)', arg=model)
            assert (root / (model + '.mesh.json')).is_file()
            assert len(tab.evaluate('Object.values(sidebarData)')) == 3
            checks.append('Game material copies and cooked mesh uploads join the Mod tray; duplicate destinations preserve existing edits')

            # Project-only folders are reachable through the library, not just the dialog.
            tab.evaluate("async () => { pushNav({path:'Custom'}); }")
            tab.wait_for_function("allItems.some(row => row.rel_path === 'Custom/Textures')")
            tab.wait_for_function("document.querySelectorAll('#grid-area .card').length === 3")
            assert tab.locator('#grid-area .card').count() == 3
            open_button.click(); tab.locator('#add-asset-name').fill('Stale'); tab.locator('#add-asset-mode').select_option('game')
            tab.locator('#add-asset-source').fill(paths['texture'])
            tab.evaluate("_activeProjectName = 'Smoke B'")
            tab.locator('#add-asset-submit').click()
            assert 'Project changed' in tab.locator('#add-asset-status').inner_text()
            assert not (root / 'Custom/T_Stale.png').exists()
            tab.evaluate('name => { _activeProjectName = name; }', name)
            tab.keyboard.press('Escape')
            checks.append('Added folders appear in the asset library and stale project dialogs refuse to write')

            for theme in ('dark', 'light'):
                tab.set_viewport_size({'width': 1024, 'height': 768})
                tab.evaluate('theme => { document.documentElement.dataset.theme = theme; }', theme)
                tab.evaluate("document.querySelectorAll('.toast').forEach(node => node.remove())")
                open_button.click(); tab.locator('#add-asset-name').fill('MyTexture')
                tab.locator('#add-asset-folder').fill('Custom/Textures')
                tab.locator('#add-asset-source').fill(paths['texture'])
                tab.wait_for_function("getComputedStyle(document.querySelector('#add-asset-overlay')).opacity === '1' && getComputedStyle(document.querySelector('.add-asset-modal')).opacity === '1'")
                tab.screenshot(path=str(report / ('add-asset-' + theme + '.png')))
                assert tab.locator('.add-asset-modal').evaluate('node => node.scrollWidth <= node.clientWidth')
                assert tab.locator('#add-asset-submit').bounding_box()['y'] < 730
                tab.keyboard.press('Escape')
            assert not errors, errors
            checks.append('Add asset supports Escape/focus return and stays within a 1024×768 window in both themes')
    finally:
        tab.close(); C.set_active_project(previous)
