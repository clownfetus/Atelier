"""Library filters, display preferences and read-only keyboard previews."""
import base64
from urllib.parse import parse_qs, urlsplit


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
    def seed(items=fixtures, path='Characters/1015/1015502'):
        target.evaluate("""({items, path}) => {
          if(window.AtelierSearch?.scope()==='everywhere')document.getElementById('search-scope').click();
          nav={path};
          _pathLabels={'Characters/1015':'1015 — Storm','Characters/1015/1015502':'502 — Goddess of Thunder'};
          allItems=items; document.getElementById('search-input').value='';
          AtelierLibraryTools.resetFilters(false); buildGrid(items.map(_makeCard));
        }""", {'items': items, 'path': path})
    def names():
        return target.locator('#grid-area .card-name').all_text_contents()
    try:
        target.goto(url)
        target.wait_for_selector('#grid-area .card')
        prior = target.evaluate('key=>localStorage.getItem(key)', key)
        sort = target.locator('#library-sort')
        sort.select_option('recommended')
        coloured = ['VFX', 'Icons', 'Meshes', 'Characters', 'UI', 'Materials', 'Textures']
        for path, other in (('', ['Weapons', 'Maps']), ('Test folder', ['Maps', 'Weapons'])):
            prefix = f'{path}/' if path else ''
            mixed = [{'type': 'folder', 'name': name, 'rel_path': prefix + name}
                     for name in ['Maps', 'Weapons', *coloured]]
            texture_path = prefix + 'Detail'
            mixed.append({'type': 'asset', 'name': 'Detail', 'file_type': 'texture',
                          'game_rel': texture_path, 'rel_path': texture_path})
            seed(mixed, path)
            expected = coloured + other + ['Detail']
            assert names() == expected, names()
            target.evaluate("path => updateImportedCard(path, {token: 'priority-check'})", texture_path)
            assert names() == expected, names()
        sort.select_option('name')
        assert names() == sorted(['Maps', 'Weapons', *coloured]) + ['Detail'], names()
        sort.select_option('recommended')
        checks.append('Recommended puts coloured folder icons first on Home and inside folders, including after import; Name A–Z sorts by name')

        seed()
        assert target.locator('#library-clear').is_hidden()
        search = target.locator('#search-input')
        search.fill('storm 1015502 t_2')
        assert target.locator('#library-clear').is_visible()
        assert names() == ['Texture 2'], names()
        search.fill('Materials/MI_Red')
        assert names() == ['Red surface'], names()
        target.locator('#library-clear').focus()
        target.keyboard.press('Enter')
        assert search.input_value() == '' and search.evaluate('e=>e===document.activeElement')
        search.fill('')
        assert target.locator('#library-clear').is_hidden()
        target.locator('#library-type').select_option('texture')
        target.locator('#library-status').select_option('unedited')
        assert names() == ['Texture 2']
        assert target.evaluate('_shownTextures().map(i=>i.name)') == ['Texture 2']
        target.locator('#library-status').select_option('edited')
        assert names() == ['Texture 10']
        target.locator('#library-type').select_option('mesh')
        assert target.locator('#empty-state').inner_text().startswith('No matches')
        target.locator('#library-clear').focus()
        target.keyboard.press('Enter')
        assert len(names()) == 5
        assert target.locator('#library-clear').is_hidden()
        assert target.locator('#library-type').input_value() == 'all'
        assert target.locator('#library-status').input_value() == 'all'
        assert target.locator('#library-type').evaluate('e=>e===document.activeElement')
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
        toolbar = target.locator('.library-controls')
        field_widths = 'fields => fields.map(field => field.offsetWidth)'
        widths = toolbar.locator('select').evaluate_all(field_widths)
        target.locator('#library-type').select_option('material')
        target.locator('#library-status').select_option('edited')
        active_widths = toolbar.locator('select').evaluate_all(field_widths)
        assert active_widths == widths, (widths, active_widths)
        assert target.locator('#library-clear').is_visible() and target.locator('#bulk-material-open').is_visible()
        for theme in ('light', 'dark'):
            target.locator('#settings-theme').select_option(theme, force=True)
            target.set_viewport_size({'width': 1024, 'height': 768})
            assert target.evaluate('document.documentElement.scrollWidth<=innerWidth')
            for tray_width in (260, 500):
                target.evaluate("width => document.getElementById('sidebar').style.width = width + 'px'", tray_width)
                layout = toolbar.evaluate("""bar => {
                  const box = bar.getBoundingClientRect();
                  const [type, status, sort, size] = [...bar.querySelectorAll('select')].map(field => field.getBoundingClientRect());
                  const view = bar.querySelector('.library-view-group');
                  return {fits: [...bar.querySelectorAll('select, button, .library-scope')].every(field => {
                            const rect = field.getBoundingClientRect();
                            return rect.left >= box.left && rect.right <= box.right + 1;
                          }), aligned: type.top === status.top && sort.top === size.top &&
                                       [status, sort, size].every(rect => rect.height === type.height),
                          stacked: sort.top > type.top,
                          divider: getComputedStyle(view, '::before').content !== 'none'};
                }""")
                assert layout == {'fits': True, 'aligned': True, 'stacked': tray_width == 500,
                                  'divider': tray_width == 260}, (theme, tray_width, layout)
                if tray_width == 260:
                    target.screenshot(path=str(report / f'library-workflow-{theme}.png'), animations='disabled')
        target.evaluate("document.getElementById('sidebar').style.width = ''")
        target.set_viewport_size({'width': 540, 'height': 768})
        assert search.bounding_box()['width'] >= 100
        menu = target.locator('#menu-btn').bounding_box()
        assert menu['x'] + menu['width'] <= 540
        assert target.locator('#sel-count-value').evaluate("""count => {
          AtelierPolish.count(count, 10);
          const [first, second] = count.querySelectorAll('.rolling-digit');
          const gap = second.getBoundingClientRect().left - first.getBoundingClientRect().right;
          updateInstallBtn();
          return Math.abs(gap) < .5 && getComputedStyle(count).overflow === 'hidden';
        }""")
        checks.append('Library dropdowns keep their widths and alignment in both themes, the toolbar wraps beside a wide Mod tray, and narrow search and tray counts remain readable')

        seed()
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
        preview = target.locator('#library-preview')
        preview.evaluate('dialog => Promise.allSettled(dialog.getAnimations().map(animation => animation.finished))')
        box = preview.bounding_box()
        assert abs(box['x'] + box['width'] / 2 - 700) < 2, box
        assert abs(box['y'] + box['height'] / 2 - 450) < 2, box
        target.keyboard.press('Control+f')
        assert not search.evaluate('el=>el===document.activeElement'), 'Search must not steal dialog focus'
        target.keyboard.press('Escape')
        preview.wait_for(state='hidden')
        assert texture.evaluate('el=>el===document.activeElement')
        target.evaluate("window.AtelierViewport={openMesh:(...args)=>window.previewArgs=args}")
        body = cards.filter(has=target.locator('.card-name', has_text='Body'))
        body.focus(); target.keyboard.press('p')
        assert target.evaluate('previewArgs[0]') == 'Characters/1015/1015502/Meshes/Body'
        assert not imports, imports
        checks.append('Arrow/Home/End navigation uses one active card; Space previews textures without importing, P opens mesh preview, Escape restores focus')

        texture_path = fixtures[2]['game_rel']
        launches = []
        def import_texture(route):
            body = route.request.post_data_json
            assert body['game_rel'] == texture_path
            route.fulfill(json={'ok':True, 'imported':{'game_rel':texture_path, 'token':'texture-2',
                          'name':'Texture 2', 'file_type':'texture', 'selected':True}})
        def open_image(route):
            launches.append(parse_qs(urlsplit(route.request.url).query)['game_rel'][0])
            route.fulfill(json={'ok':True})
        target.route('**/api/import_texture', import_texture)
        target.route('**/api/open_with?*', open_image)
        target.route('**/api/preview?*', lambda r: r.fulfill(body=png, content_type='image/png'))
        texture.click()
        target.wait_for_function('_editsInFlight.size===0 && !!document.querySelector(".card.imported[data-library-path$=T_2]")')
        assert not launches and preview.is_hidden()
        texture.click()
        target.wait_for_selector('#library-preview[open]')
        assert '/api/preview?' in target.locator('#library-preview img').get_attribute('src') and not launches
        target.keyboard.press('Escape')
        preview.wait_for(state='hidden')
        menu = target.get_by_role('button', name='Open in default image app')
        for item in (texture, target.locator('#sidebar-list .sb-item[data-token="texture-2"]')):
            item.click(button='right')
            with target.expect_response('**/api/open_with?*'):
                menu.click()
        assert launches == [texture_path,texture_path] and len(imports) == 1
        assert not target.locator('#toggle-import-open').count()
        checks.append('Texture clicks import or preview inside Atelier. Only the Library or Mod tray context menu opens the system image app')

        explorer_path = 'Characters/1015/1015502/Textures/T_Explorer'
        target.evaluate("""path => {
          allItems.push({type:'asset', name:'Explorer texture', file_type:'texture', game_rel:path, rel_path:path});
          buildGrid(allItems.map(_makeCard));
        }""", explorer_path)
        revealed = []

        def prepare_for_explorer(route):
            assert route.request.post_data_json['game_rel'] == explorer_path
            route.fulfill(json={'ok': True, 'imported': {'game_rel': explorer_path, 'token': 'explorer',
                          'name': 'Explorer texture', 'file_type': 'texture', 'selected': True}})

        def reveal_texture(route):
            revealed.append(parse_qs(urlsplit(route.request.url).query)['game_rel'][0])
            assert len(imports) == 2
            route.fulfill(json={'ok': True})

        target.route('**/api/import_texture', prepare_for_explorer)
        target.route('**/api/open_explorer?*', reveal_texture)
        for item in (cards.filter(has_text='Explorer texture'), target.locator('.sb-item[data-token="explorer"]')):
            item.click(button='right')
            with target.expect_response('**/api/open_explorer?*'):
                target.get_by_role('button', name='Open in Explorer').click()
        assert revealed == [explorer_path, explorer_path]
        checks.append('Explorer prepares a project texture on first use and reveals the same asset from the Mod tray without reimporting')

        # Navigation must retain actual keyboard focus across async folder requests.
        target.route('**/api/browse?*', lambda r: r.fulfill(json=fixtures))
        seed()
        target.evaluate('renderGrid()')
        target.evaluate('AtelierViewport.open = id => window.inspectedCostume = id')
        target.locator('#library-hero').get_by_role('button', name='Inspect in 3D').click()
        assert target.evaluate('inspectedCostume') == '1015502'
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
        assert target.locator('#grid-area .library-loading[role=status]').inner_text() == 'Loading assets…'
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
