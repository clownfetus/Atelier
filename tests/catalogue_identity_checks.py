"""Identity artwork, HiDPI fallbacks, theme ownership and custom package location UI."""
from io import BytesIO
import time
from PIL import Image


def run_catalogue_identity_checks(context, url, report, checks):
    tab = context.new_page()
    errors, writes, delayed = [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    art = BytesIO(); Image.new('RGBA', (848,192), (30,80,210,220)).save(art, 'PNG')
    image = art.getvalue()
    hero = {'name': 'Magik', 'path': 'Characters/1029', 'thumbnail': '/api/catalogue/thumbnail/1029',
            'banner': '/api/catalogue/banner/1029',
            'skins': [{'name': 'Amethyst Armor', 'path': 'Characters/1029/1029100',
                       'icon': '/api/catalogue/icon/1029100', 'banner': '/api/catalogue/banner/1029100',
                       'badge': '/api/catalogue/badge/1029100'}]}
    material = 'Characters/1029/1029100/Materials/MI_Body'
    custom = {'BaseColor': {'name': 'T_Paint', 'file': '0123456789abcdef0123.png',
                           'source': 'paint.png', 'size': [1024,1024], 'folder': 'Atelier/Custom/fixture',
                           'game_rel': 'Atelier/Custom/fixture/T_Paint'}}
    imported = [{'token': 'paint', 'name': 'MI_Body', 'game_rel': material, 'file_type': 'material',
                 'char_id': '1029', 'char_name': 'Magik', 'skin_id': '1029100', 'skin_name': 'Amethyst Armor',
                 'modified': time.time(), 'selected': True},
                {'token': 'excluded', 'name': 'MI_Thor', 'game_rel': 'Characters/1035/1035001/MI_Thor',
                 'file_type': 'material', 'char_id': '1035', 'char_name': 'Thor', 'selected': False}]
    tab.route('**/api/catalogue/library', lambda r: r.fulfill(json={'heroes': [hero]}))
    hero_plate = [True]
    def artwork(route):
        from urllib.parse import urlsplit
        if urlsplit(route.request.url).path == '/api/catalogue/banner/1029' and not hero_plate[0]:
            route.fulfill(status=404)
            return
        if 'missing=1' in route.request.url or '/1035/lord' in route.request.url:
            route.fulfill(status=404)
        else:
            route.fulfill(body=image, content_type='image/png')
    tab.route('**/api/catalogue/hero/**', artwork)
    for kind in ('banner','badge','icon','thumbnail'):
        tab.route('**/api/catalogue/'+kind+'/*', artwork)
    tab.route('**/api/imported', lambda r: r.fulfill(json=imported))
    tab.route('**/api/browse?*', lambda r: r.fulfill(json=[{'type': 'folder', 'name': 'Materials',
        'rel_path': 'Characters/1029/1029100/Materials', 'label': 'Materials'}]))
    tab.route('**/api/material_params?*', lambda r: r.fulfill(json={'ok': True, 'colors': [], 'scalars': [],
        'textures': {'BaseColor': 'Characters/1029/1029100/Textures/T_Game'},
        'texture_classes': {'BaseColor': 'Texture2D'}, 'custom_textures': custom}))
    tab.route('**/api/dye_info?*', lambda r: r.fulfill(json={'dyeable': False}))
    def location(route):
        body = route.request.post_data_json
        writes.append((body, route.request.headers.get('x-atelier-project')))
        if body['name'] == 'Delayed':
            delayed.append(route)
        elif '..' in body['folder']:
            route.fulfill(json={'ok': False, 'error': 'invalid asset path'})
        else:
            folder = body['folder'].removeprefix('/Game/Marvel/')
            name = body['name'] if body['name'].startswith('T_') else 'T_'+body['name']
            custom['BaseColor'].update(name=name, folder=folder, game_rel=folder+'/'+name)
            route.fulfill(json={'ok': True, 'custom_textures': custom})
    tab.route('**/api/material_custom_texture/location', location)
    stored = None
    try:
        tab.goto(url); tab.wait_for_function('window.AtelierCatalogueArt && window.atelierProject?.()')
        pixel_ratio = tab.evaluate('devicePixelRatio')
        sharp = '?sharp=1'
        stored = tab.evaluate("Object.fromEntries(['homePins.v1','motion'].map(k=>['atelier.'+k,localStorage.getItem('atelier.'+k)]))")
        tab.wait_for_selector('#mod-tray-heroes .hero-chip-art')
        assert tab.locator('#mod-tray-heroes').inner_text() == 'Magik'
        assert tab.locator('#mod-tray-heroes img').get_attribute('src') == '/api/catalogue/hero/1029/lord'
        tab.wait_for_selector('#continue-ribbon p .hero-chip-art')
        assert tab.locator('#continue-ribbon > img').get_attribute('src') == '/api/catalogue/badge/1029100'
        tab.evaluate("pushNav({path:'Characters/1029/1029100'})")
        tab.wait_for_selector('#library-hero.has-art.has-nameplate')
        assert tab.locator('#library-hero .nameplate').get_attribute('src') == '/api/catalogue/banner/1029100'+sharp
        assert tab.locator('#breadcrumbs img').get_attribute('src') == '/api/catalogue/hero/1029/lord'
        tab.evaluate("AtelierLibraryPins.toggle({type:'folder',rel_path:'Characters/1029/1029100/Materials',label:'Paint materials'})")
        tab.evaluate("pushNav({path:''})")
        tab.wait_for_selector('.library-pin-open .hero-chip-art')
        assert tab.locator('.library-pin-open .hero-chip-art').first.get_attribute('src') == '/api/catalogue/hero/1029/lord'
        tab.evaluate("pushNav({path:'Characters/1029/1029100'})")
        tab.wait_for_selector('#library-hero.has-nameplate')
        tab.screenshot(path=str(report/'skin-nameplate-hidpi.png'), animations='disabled')
        tab.evaluate("AtelierContinuity.banner('Characters/1029/1029100',{}, {'Characters/1029/1029100':{banner:'/api/catalogue/banner/1029100?missing=1'}})")
        tab.wait_for_function("document.querySelector('#library-hero.has-art.has-nameplate img.library-hero-art')?.getAttribute('src')==='/api/catalogue/banner/1029?sharp=1'")
        tab.evaluate("document.body.append(AtelierCatalogueArt.heroChip('1035'))")
        tab.wait_for_selector('body > .hero-chip-art[src="/api/catalogue/hero/1035/avatar"]')
        assert tab.evaluate("AtelierCatalogueArt.heroId('Characters/1029/1035001')") is None
        checks.append(f'At DPR {pixel_ratio:g}, wide nameplates request sharpening; missing costume plates use the hero nameplate, missing Lord portraits use avatars, and hero chips cover breadcrumbs, pins, selected Mod tray heroes and Continue')

        empty = BytesIO(); Image.new('RGBA', (2,2), (0,0,0,0)).save(empty, 'PNG')
        tab.route('**/api/catalogue/icon/1029002', lambda r: r.fulfill(body=empty.getvalue(), content_type='image/png'))
        tab.route('**/api/catalogue/icon/1029101', lambda r: r.fulfill(status=404))
        control_colour = tab.locator('#viewport-mat-save').evaluate('e=>getComputedStyle(e).backgroundColor')
        tab.evaluate("AtelierViewportIdentity.show('1029101')")
        tab.wait_for_function("document.getElementById('viewport-skin-icon').getAttribute('src')==='/api/catalogue/badge/1029101'&&!document.getElementById('viewport-skin-icon').hidden")
        assert tab.locator('#viewport-skin-card img').get_attribute('src') == '/api/catalogue/banner/1029101'+sharp
        tab.evaluate("""() => {
          const icon=document.getElementById('viewport-skin-icon');
          const art=document.querySelector('#viewport-skin-card img');
          window.oldIdentityCallbacks=[icon.onload,icon.onerror,art.onload,art.onerror];
          AtelierViewportIdentity.show('1029002');
        }""")
        tab.wait_for_function("document.getElementById('viewport-skin-icon').complete&&!document.getElementById('viewport-skin-card').hidden&&document.getElementById('viewport-box').classList.contains('has-skin-colour')")
        assert tab.evaluate("AtelierPolish.accent(document.getElementById('viewport-skin-icon'))") is None
        identity = tab.evaluate("""() => ({
          icon:document.getElementById('viewport-skin-icon').getAttribute('src'),
          art:document.querySelector('#viewport-skin-card img').getAttribute('src'),
          colour:document.getElementById('viewport-box').style.getPropertyValue('--vp-skin-colour')
        })""")
        tab.evaluate('oldIdentityCallbacks.forEach(callback=>callback?.())')
        assert tab.evaluate("document.getElementById('viewport-skin-icon').getAttribute('src')") == identity['icon']
        assert tab.evaluate("document.querySelector('#viewport-skin-card img').getAttribute('src')") == identity['art']
        assert tab.evaluate("document.getElementById('viewport-box').style.getPropertyValue('--vp-skin-colour')") == identity['colour']
        assert tab.locator('#viewport-mat-save').evaluate('e=>getComputedStyle(e).backgroundColor') == control_colour
        tab.evaluate("""() => {
          const icon=document.getElementById('viewport-skin-icon');
          window.closedIdentityCallbacks=[icon.onload,icon.onerror];
          AtelierViewportIdentity.clear(); closedIdentityCallbacks.forEach(callback=>callback?.());
        }""")
        assert tab.evaluate("document.getElementById('viewport-skin-icon').hidden&&!document.getElementById('viewport-skin-icon').hasAttribute('src')&&!document.getElementById('viewport-box').classList.contains('has-skin-colour')")
        checks.append('Model Studio keeps badge and HiDPI banner fallbacks, samples banner colour when the icon is transparent, ignores stale loads after switching or closing, and leaves control colours unchanged')

        tab.evaluate('gr=>openMaterialEditor({game_rel:gr,name:"Body"})', material)
        tab.wait_for_selector('#mattex-name-0', state='attached')
        tab.locator('.mat-texture-location summary').click()
        tab.locator('#mattex-folder-0').fill('../escape')
        tab.locator('.mat-texture-location .btn').click()
        tab.wait_for_function("document.getElementById('mat-status').textContent.includes('invalid asset path')")
        assert tab.locator('#mattex-folder-0').input_value() == '../escape'
        tab.locator('#mattex-name-0').fill('t_Chosen')
        tab.locator('#mattex-folder-0').fill('/Game/Marvel/')
        assert tab.locator('#mattex-path-0').inner_text() == '/Game/Marvel/T_Chosen'
        tab.locator('#mattex-name-0').fill('Chosen')
        tab.locator('#mattex-folder-0').fill('/Game/Marvel/MyMod/Textures')
        assert tab.locator('#mattex-path-0').inner_text() == '/Game/Marvel/MyMod/Textures/T_Chosen'
        tab.locator('.mat-texture-location .btn').click()
        tab.wait_for_function("matEditor.custom.BaseColor.game_rel==='MyMod/Textures/T_Chosen'")
        assert all(header == 'Smoke%20A' for _,header in writes)
        tab.locator('.mat-texture-location summary').click()
        tab.screenshot(path=str(report/'custom-texture-location.png'), animations='disabled')
        tab.locator('#mattex-name-0').fill('Delayed')
        tab.locator('.mat-texture-location .btn').click()
        tab.wait_for_function("document.querySelector('.mat-texture-location .btn').disabled")
        tab.evaluate("window.previousTextureEditor=matEditor;matEditor={...matEditor,game_rel:'Other/MI_Body',custom:{}}")
        delayed[0].fulfill(json={'ok': True, 'custom_textures': {'BaseColor': {'name': 'T_Delayed'}}})
        tab.wait_for_timeout(80)
        assert tab.evaluate('Object.keys(matEditor.custom).length') == 0
        tab.evaluate('matEditor=previousTextureEditor;closeMaterialEditor(true)')
        checks.append('Custom texture location fields preview the exact package, retain rejected input, save with the originating project, and ignore a response after another editor opens')

        tab.evaluate("""() => {
          const host=document.createElement('div');host.id='identity-mod-card';document.body.append(host);
          window.identityCardDispose=AtelierModCards.mount(host,{project:'Smoke A',modName:'Identity fixture',included:[{game_rel:'Characters/1029/1029100/Materials/MI_Body'}]},
            {ok:true,applied:['mat MI_Body'],skipped:[]});
        }""")
        tab.wait_for_selector('#identity-mod-card canvas[data-hero-badge="1029"]', state='attached')
        tab.evaluate('identityCardDispose();document.getElementById("identity-mod-card").remove()')
        checks.append('Completed single-hero Mod cards include that hero’s verified KO emblem; missing optional images never block editing')

        # The first response can precede the CPU worker. The same visible image must upgrade
        # after completion, without navigating or rebuilding the rest of the library.
        for kind, dimensions in (('story', (344,120)), ('hero-nameplate', (848,192)), ('nameplate', (848,192))):
            hero_plate[0] = kind != 'story'
            ready = [False]
            requests = []
            original = BytesIO(); Image.new('RGB', dimensions, '#b64050').save(original, 'PNG')
            enlarged = BytesIO(); Image.new('RGB', tuple(n*4 for n in dimensions), '#b64050').save(enlarged, 'PNG')
            path = '/api/catalogue/hero/1029/story' if kind == 'story' else '/api/catalogue/banner/' + ('1029' if kind == 'hero-nameplate' else '1029100')
            def delayed_banner(route):
                requests.append((route.request.method, route.request.url))
                route.fulfill(body=enlarged.getvalue() if ready[0] else original.getvalue(), content_type='image/png',
                              headers={'X-Atelier-Upscale': 'ready' if ready[0] else 'pending', 'Cache-Control':'no-cache'})
            tab.route('**'+path+'*', delayed_banner)
            tab.evaluate("kind=>AtelierContinuity.banner(kind==='nameplate'?'Characters/1029/1029100':'Characters/1029')", kind)
            tab.wait_for_function("width=>document.querySelector('.library-hero-art')?.naturalWidth===width", arg=dimensions[0])
            ready[0] = True
            tab.wait_for_function("width=>document.querySelector('.library-hero-art')?.naturalWidth===width*4", arg=dimensions[0])
            assert any(method == 'HEAD' for method,_ in requests), requests
            assert any('upscale=4' in request for _,request in requests), requests
            assert tab.locator('#library-hero').evaluate("""host=>{
              const box=host.getBoundingClientRect(), image=host.querySelector('.library-hero-art').getBoundingClientRect();
              const parent=host.parentElement.getBoundingClientRect();
              return Math.abs(box.left-parent.left-1)<1 && Math.abs(box.right-parent.right+1)<1 &&
                image.left>=box.left && image.left<box.left+box.width*.3 && image.right>=box.right-1 &&
                Math.abs(image.bottom-box.bottom)<1 && getComputedStyle(host).marginBottom==='0px';
            }""")
            box = tab.locator('#library-hero').bounding_box()
            screenshot = Image.open(BytesIO(tab.screenshot(scale='css'))).convert('RGB')
            pixel = screenshot.getpixel((round(box['x']+box['width']*.8), round(box['y']+box['height']*.5)))
            assert all(abs(a-b)<=3 for a,b in zip(pixel,(182,64,80))), pixel
            tab.screenshot(path=str(report/(kind+'-upscaled-edge-to-edge.png')), animations='disabled')
        checks.append('Visible stories, hero nameplates and costume nameplates upgrade to 4× without navigation; the strip has no outer gaps and right-side artwork keeps its original colour and contrast')
        assert not errors, errors
    except Exception:
        print('Identity failure:', tab.evaluate("() => [...document.querySelectorAll('#viewport-skin-icon,#viewport-skin-card img')].map(i=>({src:i.getAttribute('src'),hidden:i.hidden,complete:i.complete,width:i.naturalWidth}))"), errors, flush=True)
        tab.screenshot(path=str(report/'catalogue-identity-failure.png'), animations='disabled')
        raise
    finally:
        if stored is not None:
            tab.evaluate("saved=>{for(const [key,value] of Object.entries(saved)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.close()
