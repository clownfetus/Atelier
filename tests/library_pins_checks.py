"""Home folder shortcuts: real navigation/controls, isolated browser storage and local tree fixtures."""
import json
from urllib.parse import parse_qs, urlparse


KEY = 'atelier.homePins.v1'
TREE = {
    '': [('Characters', 'Characters'), ('UI', 'UI'), ('Maps', 'Maps')],
    'Characters': [('Magik', 'Characters/1029')],
    'Characters/1029': [('Magik costume', 'Characters/1029/1029100')],
    'Characters/1029/1029100': [('Magik materials', 'Characters/1029/1029100/Materials')],
    'Characters/1029/1029100/Materials': [('Body', 'Characters/1029/1029100/Materials/Body')],
    'Maps': [('Arena', 'Maps/Arena')],
    'UI': [('Icons', 'UI/Icons')],
}


def run_library_pins_checks(page, context, url, report, checks):
    pins_page = context.new_page()
    errors, writes = [], []
    pins_page.on('pageerror', lambda error: errors.append(str(error)))
    pins_page.on('request', lambda request: writes.append(request.url) if request.method != 'GET' else None)

    def browse_fixture(route):
        path = parse_qs(urlparse(route.request.url).query).get('path', [''])[0]
        route.fulfill(json=[{'type': 'folder', 'name': target.split('/')[-1], 'label': label,
                             'rel_path': target, 'count': 1} for label, target in TREE.get(path, [])])

    pins_page.route('**/api/browse?*', browse_fixture)
    prior = None

    def folder(label, target=pins_page):
        return target.locator('#grid-area button.card').filter(has=target.locator('.card-name', has_text=label))

    def toggle_for(label, target=pins_page):
        return folder(label, target).locator('..').locator('.library-pin-toggle')

    def wait_path(path, target=pins_page):
        target.wait_for_function("path=>nav.path===path && document.getElementById('library-count').textContent!=='Loading…'", arg=path)

    def home(target=pins_page):
        target.evaluate("pushNav({path:''})")
        wait_path('', target)

    def pin_folder(label):
        folder(label).hover()
        toggle_for(label).click()

    def assert_map_pin():
        glyph = pins_page.locator('.library-pin-open[title="Maps"] svg')
        assert glyph.get_attribute('data-lucide') == 'folder-map'
        assert 'map-folder-icon' in glyph.get_attribute('class')
        assert glyph.bounding_box()['width'] == 18
        assert glyph.evaluate("""el=>el.querySelector('path').getAttribute('d') ===
          AtelierSymbolPaths['folder-map'].body.match(/d="([^"]+)"/)[1]""")
        assert pins_page.evaluate('AtelierLibraryPins.list().find(pin=>pin.path==="Maps").iconCls') == 'map-folder-icon'

    try:
        pins_page.goto(url)
        pins_page.wait_for_function('window.AtelierLibraryPins && window.atelierProject?.()')
        pins_page.wait_for_selector('#grid-area .card')
        prior = pins_page.evaluate('key=>localStorage.getItem(key)', KEY)
        pins_page.evaluate('() => AtelierLibraryPins.list().forEach(pin=>AtelierLibraryPins.remove(pin.path))')
        initial_count = pins_page.locator('#library-count').inner_text()
        assert pins_page.locator('button button').count() == 0
        pin_folder('Maps')
        assert pins_page.evaluate('nav.path') == ''
        assert toggle_for('Maps').get_attribute('aria-pressed') == 'true'
        assert pins_page.locator('.library-pins .library-pin-open').count() == 1
        assert_map_pin()
        assert pins_page.locator('#library-count').inner_text() == initial_count
        folder('UI').click(button='right')
        pins_page.locator('#ctx-menu').get_by_role('button', name='Pin to home', exact=True).click()
        assert toggle_for('UI').get_attribute('aria-pressed') == 'true'
        folder('UI').click(button='right')
        pins_page.locator('#ctx-menu').get_by_role('button', name='Unpin from home', exact=True).click()
        assert toggle_for('UI').get_attribute('aria-pressed') == 'false'
        # Category folders have the same option; pinning does not replace their normal tile.
        pin_folder('Characters')
        assert folder('Characters').count() == 1
        folder('Characters').press('Enter')
        wait_path('Characters')
        assert pins_page.locator('.library-pins').is_hidden()
        folder('Magik').press('Enter')
        wait_path('Characters/1029')
        folder('Magik costume').press('Enter')
        wait_path('Characters/1029/1029100')
        pin_folder('Magik materials')
        paths = pins_page.evaluate('AtelierLibraryPins.list().map(pin=>pin.path)')
        assert paths == ['Maps', 'Characters', 'Characters/1029/1029100/Materials'], paths
        checks.append('Any folder can be pinned independently of navigation, including nested/category folders; native card buttons stay intact')

        pins_page.reload()
        wait_path('')
        assert pins_page.locator('.library-pins .library-pin-open').count() == 3
        assert_map_pin()
        nested = pins_page.locator('.library-pin-open').filter(has_text='Magik materials')
        nested.focus()
        nested.press('Enter')
        wait_path('Characters/1029/1029100/Materials')
        assert pins_page.locator('.library-pins').is_hidden()
        assert folder('Body').count() == 1
        home()
        pins_page.locator('#search-scope').click()
        pins_page.locator('#search-input').fill('Magik')
        assert pins_page.locator('.library-pin-open').count() == 1
        assert 'Magik materials' in pins_page.locator('.library-pin-open').inner_text()
        pins_page.locator('#search-input').fill('')
        # Pin toggles are keyboard controls beside the navigation button.
        toggle_for('Maps').focus()
        toggle_for('Maps').press('Space')
        assert toggle_for('Maps').get_attribute('aria-pressed') == 'false'
        assert pins_page.evaluate('nav.path') == ''
        pins_page.locator('.library-pin-chip').filter(has_text='Magik materials').locator('.library-pin-remove').click()
        assert not pins_page.evaluate("AtelierLibraryPins.isPinned('Characters/1029/1029100/Materials')")
        assert pins_page.evaluate('document.activeElement.classList.contains("library-pin-open")')
        pins_page.locator('.library-pin-remove').click()
        assert pins_page.locator('.library-pins').is_hidden()
        assert pins_page.evaluate('document.activeElement.matches("#grid-area button.card")')
        assert folder('Characters').count() == 1
        checks.append('Pins persist across reload, navigate by keyboard, filter on home, and unpin without removing folders or losing focus')

        forged = {'version': 1, 'pins': [
            {'path': 'Characters\\1029//', 'label': '<img src=x onerror="window.pinInjected=true">', 'iconCls': 'bad" onclick="evil'},
            {'path': 'Characters/1029', 'label': 'Duplicate'}, {'path': 'Maps', 'label': 'Maps', 'iconCls': 'folder-icon'},
            *({'path': value, 'label': 'Invalid'} for value in ('../Escape', '/absolute', 'C:\\temp',
                '\\\\server\\folder', 'https://example.com', 'Characters/%2e%2e/Escape',
                'Characters/%2fEscape', 'Characters/\u0000bad')),
            {'path': 99}, None, {'type': 'asset', 'path': 'Fixture/Asset'}]}
        pins_page.evaluate('(args)=>localStorage.setItem(args.key,args.raw)', {'key': KEY, 'raw': json.dumps(forged)})
        pins_page.reload()
        wait_path('')
        assert pins_page.evaluate('AtelierLibraryPins.list().map(pin=>pin.path)') == ['Characters/1029', 'Maps']
        # Existing v1 shortcuts acquire current category artwork without a storage migration.
        assert_map_pin()
        assert pins_page.evaluate('key=>JSON.parse(localStorage.getItem(key)).version', KEY) == 1
        assert pins_page.locator('.library-pins img').count() == 0
        assert pins_page.locator('.library-pin-open').first.inner_text().startswith('<img src=x')
        assert not pins_page.evaluate('Boolean(window.pinInjected)')
        assert not pins_page.evaluate("AtelierLibraryPins.toggle({type:'asset',rel_path:'Fixture/Asset'})")
        pins_page.evaluate('key=>localStorage.setItem(key,"{broken JSON")', KEY)
        pins_page.reload()
        wait_path('')
        assert pins_page.evaluate('AtelierLibraryPins.list()') == []
        assert pins_page.locator('.library-pins').is_hidden()
        checks.append('Existing v1 generic Maps pins gain current artwork; stored paths normalize/deduplicate safely, forged labels stay inert and corrupt storage does not block launch')

        secondary = context.new_page()
        secondary.on('pageerror', lambda error: errors.append(str(error)))
        secondary.route('**/api/browse?*', browse_fixture)
        try:
            secondary.goto(url)
            secondary.wait_for_function('window.AtelierLibraryPins && window.atelierProject?.()')
            secondary.evaluate("AtelierLibraryPins.toggle({type:'folder',rel_path:'Maps',label:'Maps',iconCls:'folder-icon'})")
            pins_page.wait_for_function("AtelierLibraryPins.isPinned('Maps')")
            assert toggle_for('Maps').get_attribute('aria-pressed') == 'true'
            assert pins_page.locator('.library-pin-open').count() == 1
            pin_folder('Maps')
            secondary.wait_for_function("!AtelierLibraryPins.isPinned('Maps')")
            assert secondary.locator('.library-pins').is_hidden()
        finally:
            secondary.close()
        blocked = context.new_page()
        blocked.on('pageerror', lambda error: errors.append(str(error)))
        blocked.route('**/api/browse?*', browse_fixture)
        blocked.add_init_script("Storage.prototype.getItem=()=>{throw Error('Fixture blocked storage')}; Storage.prototype.setItem=()=>{throw Error('Fixture blocked storage')};")
        try:
            blocked.goto(url)
            blocked.wait_for_selector('#grid-area .card')
            folder('Maps', blocked).hover()
            toggle_for('Maps', blocked).click()
            assert blocked.evaluate("AtelierLibraryPins.isPinned('Maps')")
            folder('Maps', blocked).press('Enter')
            wait_path('Maps', blocked)
            home(blocked)
            assert blocked.locator('.library-pin-open').count() == 1
            blocked.locator('.library-pin-remove').click()
            assert blocked.evaluate('AtelierLibraryPins.list()') == []
        finally:
            blocked.close()
        checks.append('Pin changes synchronize between windows; blocked storage still supports pinning/navigation/unpinning for the session')

        pins_page.evaluate("""() => {
          AtelierLibraryPins.toggle({type:'folder',rel_path:'Maps',label:'Maps',iconCls:'folder-icon'});
          AtelierLibraryPins.toggle({type:'folder',rel_path:'Characters',label:'Characters',iconCls:'char-icon'});
          AtelierLibraryPins.toggle({type:'folder',rel_path:'Characters/1029/1029100/Materials',label:'Magik materials',iconCls:'material-folder-icon'});
        }""")
        for width, height in ((1024, 768), (1400, 900)):
            pins_page.set_viewport_size({'width': width, 'height': height})
            for theme in ('light', 'dark'):
                pins_page.locator('#settings-theme').select_option(theme, force=True)
                assert pins_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert pins_page.locator('.library-pin-open').count() == 3
                # Home uses the selected card size, including its pinned folder cards.
                size=int(pins_page.locator('#library-size').input_value())
                cards=pins_page.locator('#grid-area .card').evaluate_all(
                    "nodes=>nodes.map(node=>node.getBoundingClientRect().toJSON())")
                assert cards and all(abs(card['width']-size)<1 and card['height']>size for card in cards),cards
                thumb=folder('Maps').locator('.card-thumb').bounding_box()
                assert abs(thumb['width']-thumb['height'])<1 and thumb['width']>60,thumb
                assert pins_page.locator('#install-btn').is_visible()
                pins_page.screenshot(path=str(report / f'library-pins-{theme}-{width}.png'), animations='disabled')
        assert not errors, errors
        assert not writes, writes
        checks.append('Pinned home links and consistently sized folder cards fit both themes and desktop sizes without blocking export or issuing backend writes')
    finally:
        if not pins_page.is_closed():
            pins_page.evaluate('(args)=>args.raw===null ? localStorage.removeItem(args.key) : localStorage.setItem(args.key,args.raw)', {'key': KEY, 'raw': prior})
        pins_page.close()
