"""Real browser coverage of identity labels outside the Characters hierarchy."""
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from PIL import Image

UI = 'UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom'


def run_shared_identity_checks(context, url, report, checks):
    tab = context.new_page()
    errors, writes = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD')
           and urlparse(request.url).path != '/api/prefetch_thumbs' else None)
    tab.route('**/api/prefetch_thumbs', lambda route: route.fulfill(json={'ok': True}))
    hero = {'name': 'Magik', 'path': 'Characters/1029', 'thumbnail': '/api/catalogue/thumbnail/1029',
            'skins': [{'name': 'Infernal Idol', 'path': 'Characters/1029/1029304',
                       'thumbnail': '/api/catalogue/thumbnail/1029304',
                       'icon': '/api/catalogue/icon/1029304'}]}
    image = BytesIO(); Image.new('RGB', (64, 80), (120, 40, 180)).save(image, 'PNG')
    tab.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': [hero]}))
    tab.route('**/api/catalogue/thumbnail/*', lambda route: route.fulfill(body=image.getvalue(), content_type='image/png'))
    tab.route('**/api/catalogue/icon/*', lambda route: route.fulfill(body=image.getvalue(), content_type='image/png'))
    tab.route('**/api/catalogue/hero/**', lambda route: route.fulfill(body=image.getvalue(), content_type='image/png'))
    tab.route('**/api/thumb?*', lambda route: route.fulfill(body=image.getvalue(), content_type='image/png'))

    def folders(path):
        return [{'type': 'folder', 'name': '1029304', 'rel_path': path+'/1029304',
                 'label': '1029304 — Magik — Infernal Idol', 'display_name': 'Infernal Idol',
                 'context_label': 'Magik', 'thumbnail': '/api/catalogue/thumbnail/1029304'},
                {'type': 'folder', 'name': '1029999', 'rel_path': path+'/1029999',
                 'label': '1029999 — Magik — Skin 999', 'display_name': 'Skin 999',
                 'context_label': 'Magik', 'thumbnail': '/api/catalogue/thumbnail/1029', 'hero_fallback': True},
                {'type': 'folder', 'name': 'Com', 'label': 'Com', 'rel_path': path+'/Com'}]

    def items(path):
        if path.endswith('/1029304'):
            return [{'type': 'asset', 'name': 'T_Icon', 'game_rel': path+'/T_Icon',
                     'rel_path': path+'/T_Icon', 'file_type': 'texture'}]
        if path:
            return folders(path)
        return [{'type': 'folder', 'name': 'UI', 'label': 'UI', 'rel_path': 'UI'}]

    def browse(route):
        path = parse_qs(urlparse(route.request.url).query).get('path', [''])[0]
        route.fulfill(json=items(path))

    def picker(route):
        path = parse_qs(urlparse(route.request.url).query).get('path', [''])[0]
        route.fulfill(json={'ok': True, 'path': path, 'items': items(path)})

    tab.route('**/api/browse?*', browse)
    tab.route('**/api/assets/browse?*', picker)
    tab.route('**/api/search?*', lambda route: route.fulfill(json={
        'heroes': [], 'skins': [], 'folders': [{**folders(UI)[0], 'path': UI+'/1029304'}], 'assets': [],
        'totals': {'heroes': 0, 'skins': 0, 'folders': 1, 'assets': 0}, 'building': False}))

    def navigate(path):
        tab.evaluate('path=>pushNav({path})', path)
        tab.wait_for_function('path=>nav.path===path&&_gridStatus==="ready"', arg=path)

    saved_pins = None
    try:
        tab.goto(url)
        tab.wait_for_function('AtelierCatalogueArt.describe("'+UI+'/1029304")?.skin?.name==="Infernal Idol"')
        saved_pins = tab.evaluate('localStorage.getItem("atelier.homePins.v1")')
        for root in (UI, 'Marvel_LQ/'+UI, 'Plugins/MarvelGAS/UI', 'VFX/Materials/Characters/1029'):
            navigate(root)
            card = tab.locator('#grid-area button.card').first
            assert card.locator('.card-name').inner_text() == 'Infernal Idol'
            assert card.locator('.card-context').inner_text() == 'Magik'
            assert card.get_attribute('title').endswith(root+'/1029304')
            card.locator('img.hero-portrait').wait_for()
            assert tab.locator('#grid-area button.card').nth(1).get_attribute('title').endswith('Hero portrait (skin artwork unavailable)')
            assert tab.locator('#grid-area button.card').nth(2).locator('img').count() == 0
        checks.append('Skin folders use names, character context and artwork in UI, low-quality, plugin and VFX branches; unknown costumes and common folders stay explicit')

        navigate(UI)
        if tab.locator('#search-scope').inner_text() != 'This folder':
            tab.locator('#search-scope').click()
        tab.locator('#search-input').fill('infernal')
        assert tab.locator('#grid-area button.card').count() == 1
        tab.locator('#search-input').fill('1029304')
        assert tab.locator('#grid-area button.card').count() == 1
        tab.locator('#search-input').fill('')
        tab.locator('#grid-area button.card').first.press('Enter')
        tab.wait_for_function('nav.path.endsWith("/1029304")&&_gridStatus==="ready"')
        assert tab.locator('#breadcrumbs .crumb.active').inner_text() == 'Infernal Idol'
        assert tab.locator('#breadcrumbs .crumb.active').get_attribute('title').endswith(UI+'/1029304')
        assert tab.locator('#library-hero h2').inner_text() == 'Magik'
        assert 'Infernal Idol' in tab.locator('#library-hero p').inner_text()
        assert tab.locator('#view3d-fab').evaluate('node=>!node.classList.contains("show")')
        checks.append('Name and ID filters agree; keyboard navigation, breadcrumbs and banners retain the original UI location without enabling character-only editing actions')

        tab.evaluate('path=>AtelierLibraryPins.toggle({type:"folder",rel_path:path})', UI+'/1029304')
        navigate('')
        tab.wait_for_selector('.library-pin-open .hero-chip-art')
        assert 'Magik — Infernal Idol' in tab.locator('.library-pin-open').inner_text()
        tab.reload()
        tab.wait_for_function('AtelierCatalogueArt.describe("'+UI+'/1029304")?.skin?.name==="Infernal Idol"')
        assert 'Magik — Infernal Idol' in tab.locator('.library-pin-open').inner_text()
        tab.locator('.library-pin-open').press('Enter')
        tab.wait_for_function('nav.path.endsWith("/1029304")&&_gridStatus==="ready"')
        checks.append('Saved pins acquire readable character/skin labels and hero artwork across reload and keep their exact destination')

        tab.locator('#add-asset-open').click()
        tab.locator('#add-asset-source').fill(UI+'/T_Template')
        tab.locator('#add-asset-source').locator('..').get_by_role('button', name='Browse…', exact=True).click()
        row = tab.locator('.add-asset-browser-items button').first
        assert 'Magik — Infernal Idol' in row.inner_text()
        assert row.locator('img').count() == 1
        row.click()
        tab.wait_for_function('document.querySelector(".add-asset-browser-path").textContent.includes("Magik — Infernal Idol")')
        assert 'Magik — Infernal Idol' in tab.locator('.add-asset-browser-path').inner_text()
        assert tab.locator('.add-asset-browser-path').get_attribute('title').endswith(UI+'/1029304')
        tab.locator('.add-asset-browser-items button[data-path="'+UI+'/1029304/T_Icon"]').click()
        assert tab.locator('#add-asset-source').input_value() == UI+'/1029304/T_Icon'
        tab.locator('#add-asset-overlay').get_by_role('button', name='Cancel', exact=True).click()
        checks.append('Custom asset template picking shows identity artwork and names while selecting the unchanged game asset path')

        if tab.locator('#search-scope').inner_text() != 'Everywhere':
            tab.locator('#search-scope').click()
        tab.locator('#search-input').fill('infernal')
        result = tab.locator('#search-results .search-result')
        result.wait_for()
        assert 'Infernal Idol' in result.locator('strong').inner_text()
        assert result.locator('img').count() == 1
        assert 'Magik — Infernal Idol' in result.locator(':scope > span').inner_text()
        assert result.get_attribute('title') == UI+'/1029304'
        result.click()
        tab.wait_for_function('nav.path.endsWith("/1029304")&&_gridStatus==="ready"')
        checks.append('Global folder search shows skin names and artwork with a readable path; selecting a result preserves its numeric game path')
        navigate(UI)
        for width, height in ((1400, 900), (1024, 768)):
            tab.set_viewport_size({'width': width, 'height': height})
            assert tab.evaluate('document.documentElement.scrollWidth<=innerWidth')
            tab.screenshot(path=str(report/f'shared-identities-{width}.png'), animations='disabled')
        assert not errors, errors
        assert not writes, writes
        checks.append('Identity browsing fits desktop and compact widths without script errors or project writes')
    except Exception:
        tab.screenshot(path=str(report/'shared-identity-failure.png'), animations='disabled')
        raise
    finally:
        tab.evaluate('value=>{if(value===null)localStorage.removeItem("atelier.homePins.v1");else localStorage.setItem("atelier.homePins.v1",value);}', saved_pins)
        tab.close()
