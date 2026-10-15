"""Library filters, display preferences and read-only keyboard previews."""
import base64


def run_library_workflow_checks(page, context, url, report, checks):
    target = context.new_page()
    errors, imports = [], []
    target.on('pageerror', lambda error: errors.append(str(error)))
    target.on('request', lambda request: imports.append(request.url) if '/api/import_' in request.url else None)
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6mXcAAAAASUVORK5CYII=')
    target.route('**/api/thumb?*', lambda r: r.fulfill(body=png, content_type='image/png'))
    target.route('**/api/prefetch_thumbs', lambda r: r.fulfill(json={'ok': True, 'cached': r.request.post_data_json.get('game_rels', [])}))
    key = 'atelier.libraryView.v1'
    prior = None
    fixtures = [
        {'type': 'folder', 'name': 'Materials', 'rel_path': 'Characters/1015/1015502/Materials'},
        {'type': 'asset', 'name': 'Texture 10', 'file_type': 'texture', 'game_rel': 'Characters/1015/1015502/Textures/T_10', 'imported': True, 'token': 'edited-ten'},
        {'type': 'asset', 'name': 'Texture 2', 'file_type': 'texture', 'game_rel': 'Characters/1015/1015502/Textures/T_2', 'imported': False},
        {'type': 'asset', 'name': 'Red surface', 'file_type': 'material', 'game_rel': 'Characters/1015/1015502/Materials/MI_Red', 'imported': True},
        {'type': 'asset', 'name': 'Body', 'file_type': 'mesh', 'game_rel': 'Characters/1015/1015502/Meshes/Body', 'imported': False},
    ]
    fixtures = [{**item, 'rel_path': item.get('rel_path', item.get('game_rel'))} for item in fixtures]
    def seed():
        target.evaluate("""items => {
          nav={path:'Characters/1015/1015502'};
          _pathLabels={'Characters/1015':'1015 — Storm','Characters/1015/1015502':'502 — Goddess of Thunder'};
          allItems=items; document.getElementById('search-input').value='';
          AtelierLibraryTools.resetFilters(false); buildGrid(items.map(_makeCard));
        }""", fixtures)
    def names():
        return target.locator('#grid-area .card-name').all_text_contents()
    try:
        target.goto(url)
        target.wait_for_selector('#grid-area .card')
        prior = target.evaluate('key=>localStorage.getItem(key)', key)
        seed()
        search = target.locator('#search-input')
        search.fill('storm 1015502 t_2')
        assert names() == ['Texture 2'], names()
        search.fill('Materials/MI_Red')
        assert names() == ['Red surface'], names()
        search.fill('')
        target.locator('#library-type').select_option('texture')
        target.locator('#library-status').select_option('unedited')
        assert names() == ['Texture 2']
        assert target.evaluate('_shownTextures().map(i=>i.name)') == ['Texture 2']
        target.locator('#library-status').select_option('edited')
        assert names() == ['Texture 10']
        target.locator('#library-type').select_option('mesh')
        assert target.locator('#empty-state').inner_text().startswith('No matches')
        target.locator('#library-clear').click()
        assert len(names()) == 5
        checks.append('Library search matches combined names, IDs and paths; type/status filters and Edit All share the visible texture set')

        target.locator('#library-sort').select_option('name')
        assert names() == ['Materials', 'Body', 'Red surface', 'Texture 2', 'Texture 10'], names()
        target.locator('#library-sort').select_option('name-desc')
        assert names()[-2:] == ['Red surface', 'Body']
        target.locator('#library-size').select_option('196')
        assert target.locator('#grid-area .card').first.bounding_box()['width'] == 196
        target.reload(); target.wait_for_selector('#grid-area .card')
        assert target.locator('#library-size').input_value() == '196'
        assert target.locator('#library-sort').input_value() == 'name-desc'
        seed()
        for theme in ('light', 'dark'):
            target.locator('#settings-theme').select_option(theme, force=True)
            target.set_viewport_size({'width': 1024, 'height': 768})
            assert target.evaluate('document.documentElement.scrollWidth<=innerWidth')
            target.screenshot(path=str(report / f'library-workflow-{theme}.png'), animations='disabled')
        checks.append('Natural sorting and adjustable thumbnail size persist across reload; controls fit both themes at 1024px')

        target.locator('#library-sort').select_option('name')
        target.locator('#library-size').select_option('156')
        target.set_viewport_size({'width': 1400, 'height': 900})
        cards = target.locator('#grid-area button.card')
        cards.first.focus(); target.keyboard.press('ArrowRight')
        assert cards.nth(1).evaluate('el=>el===document.activeElement')
        target.keyboard.press('End')
        assert cards.last.evaluate('el=>el===document.activeElement')
        target.keyboard.press('Home')
        assert cards.first.evaluate('el=>el===document.activeElement')
        assert target.locator('#grid-area .card[tabindex="0"]').count() == 1
        texture = cards.filter(has=target.locator('.card-name', has_text='Texture 2'))
        texture.focus(); target.keyboard.press('Space')
        target.wait_for_selector('#library-preview[open]')
        assert target.locator('#library-preview-title').inner_text() == 'Texture 2'
        assert 'game_rel=Characters' in target.locator('#library-preview img').get_attribute('src')
        target.wait_for_function('document.querySelector("#library-preview img").naturalWidth > 0')
        box = target.locator('#library-preview').bounding_box()
        assert abs(box['x'] + box['width'] / 2 - 700) < 2
        assert abs(box['y'] + box['height'] / 2 - 450) < 2
        target.keyboard.press('Control+f')
        assert not search.evaluate('el=>el===document.activeElement'), 'Search must not steal dialog focus'
        target.keyboard.press('Escape')
        target.wait_for_function('!document.getElementById("library-preview").open')
        assert texture.evaluate('el=>el===document.activeElement')
        target.evaluate("window.AtelierViewport={openMesh:(...args)=>window.previewArgs=args}")
        body = cards.filter(has=target.locator('.card-name', has_text='Body'))
        body.focus(); target.keyboard.press('p')
        assert target.evaluate('previewArgs[0]') == 'Characters/1015/1015502/Meshes/Body'
        assert not imports, imports
        checks.append('Arrow/Home/End navigation uses one active card; Space previews textures without importing, P opens mesh preview, Escape restores focus')

        # Navigation must retain actual keyboard focus across async folder requests.
        target.route('**/api/browse?*', lambda r: r.fulfill(json=fixtures))
        seed()
        cards.first.focus(); target.keyboard.press('Enter')
        target.wait_for_function("nav.path.endsWith('/Materials') && _gridStatus === 'ready'")
        assert cards.first.evaluate('el=>el===document.activeElement')
        target.keyboard.press('Backspace')
        target.wait_for_function("nav.path === 'Characters/1015/1015502' && _gridStatus === 'ready'")
        assert cards.first.evaluate('el=>el===document.activeElement')
        target.unroute('**/api/browse?*')

        # A pending/failed request cannot expose the previous folder when filters change.
        target.evaluate("""() => {
          window.librarySavedApi = api;
          api = (path, options) => path.startsWith('/api/browse?')
            ? new Promise(resolve => window.finishLibraryBrowse = resolve) : librarySavedApi(path, options);
          pushNav({path:'Missing'});
        }""")
        target.locator('#library-type').select_option('texture')
        search.fill('Texture')
        assert cards.count() == 0
        assert target.locator('#library-count').inner_text() == 'Loading…'
        target.evaluate("finishLibraryBrowse({error:'Folder unavailable'})")
        target.wait_for_function("_gridStatus === 'error'")
        target.locator('#library-status').select_option('edited')
        assert cards.count() == 0
        assert target.locator('#empty-state').inner_text() == 'Folder unavailable'
        target.evaluate('api = librarySavedApi')
        checks.append('Folder entry and parent navigation preserve keyboard focus; loading/error filters cannot resurrect stale cards')
        assert not errors, errors
    finally:
        if not target.is_closed():
            target.evaluate('args=>args.raw===null?localStorage.removeItem(args.key):localStorage.setItem(args.key,args.raw)', {'key': key, 'raw': prior})
            target.close()
