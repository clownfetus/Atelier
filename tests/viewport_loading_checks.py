"""Slow requests must stop when their viewer or material set is replaced."""
from pathlib import Path
from viewport_inspection_checks import HOOK

ROOT = Path(__file__).resolve().parents[1]


def run_viewport_loading_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, cancelled, requests, failed = [], [], [], []
    held = []
    mode = ['materials']
    tab.on('pageerror',lambda error:errors.append(str(error)))
    tab.on('requestfailed',lambda request:failed.append(request.url))
    def observed(request):
        if request.url.endswith('/api/viewport_cancel'):
            cancelled.append(request.post_data_json['id'])
    tab.on('request',observed)
    tab.route('**/static/viewport.js',lambda route:route.fulfill(
        body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*',lambda route:route.fulfill(json=[{
        'name':'Body','game_rel':'Characters/1029/1029001/Meshes/Body'}]))
    tab.route('**/api/idle_animations?*',lambda route:route.fulfill(json={'ok':True,'animations':[]}))
    tab.route('**/api/browse_material_dirs?*',lambda route:route.fulfill(json={'dirs':[
        {'name':'1029001','materials':1,'meshes':1},{'name':'1029002','materials':1,'meshes':0}]}))
    def materials(route):
        requests.append(route.request.headers['x-atelier-preview'])
        if mode[0]=='materials': held.append(route);return
        route.fulfill(json={'ok':True,'materials':{'MI_Body':{
            'game_rel':'Characters/1029/1029001/Materials/MI_Body','colors':[{'name':'Fresh tint','rgba':[1,1,1,1]}],
            'scalars':[],'textures':{'BaseColor':'Characters/Test/SlowMap'} if mode[0]=='textures' else {}}}})
    tab.route('**/api/skin_materials',materials)
    tab.route('**/api/texture_png?*',lambda route:held.append(route))
    try:
        tab.goto(url)
        tab.wait_for_function('window.__inspection && window.atelierProject?.()')
        tab.wait_for_selector('#grid-area .card')
        def open_viewer():
            tab.evaluate("AtelierViewport.open('1029001','Cancellation fixture')")
            tab.wait_for_function("/Loading materials|Loading textures/.test(document.getElementById('viewport-status').textContent)")
        def spinners():
            return tab.locator('#viewport-status .vp-load-status').count()
        open_viewer()
        first = requests[-1]
        tab.locator('#viewport-close').click()
        assert spinners()==0
        tab.wait_for_function('!document.querySelector("#viewport-overlay.active")')
        tab.wait_for_timeout(100)
        assert first in cancelled
        checks.append('Closing a loading viewer immediately removes its inline progress and cancels its backend load')
        open_viewer()
        previous=requests[-1]
        tab.locator('#viewport-chroma').select_option('1029002',force=True)
        tab.wait_for_timeout(150)
        assert spinners()==1,spinners()
        assert previous in cancelled and requests[-1]!=previous
        tab.locator('#viewport-close').click()
        assert spinners()==0
        checks.append('Changing material skins cancels the previous request and keeps exactly one inline progress message')
        mode[0]='textures'
        open_viewer()
        tab.wait_for_function("document.getElementById('viewport-status').textContent.includes('Loading textures')")
        tab.locator('#viewport-close').click()
        assert spinners()==0
        tab.wait_for_timeout(150)
        assert any('/api/texture_png?' in url for url in failed),failed
        mode[0]='ready'
        tab.evaluate("AtelierViewport.open('1029001','Replacement model')")
        tab.wait_for_selector('.vp-mat')
        tab.wait_for_function("!/Loading materials|Loading textures/.test(document.getElementById('viewport-status').textContent)")
        tab.locator('.vp-material-select').click()
        tab.locator('.vp-advanced > summary').click()
        assert tab.locator('#viewport-material-editor .vp-color-field[data-parameter="Fresh tint"]').count()==1
        assert not errors,errors
        checks.append('Pending texture downloads abort on close; the next model opens without stale materials, spinners or page errors')
    finally:
        for route in held:
            try: route.abort()
            except Exception: pass
        tab.close()


def run_hero_artwork_checks(page, context, url, report, checks, *, reuse_page=False):
    from io import BytesIO
    from PIL import Image
    image=BytesIO();Image.new('RGBA',(64,64),(30,130,200,200)).save(image,'PNG')
    tab=page if reuse_page else context.new_page()
    heroes=[{'name':name,'path':'Characters/'+cid,'avatar':'/api/catalogue/hero/'+cid+'/avatar',
             'logo':'/api/catalogue/hero/'+cid+'/logo','thumbnail':'/api/catalogue/thumbnail/'+cid,
             'skins':[{'name':skin,'path':'Characters/'+cid+'/'+cid+'100','thumbnail':'/api/catalogue/thumbnail/'+cid+'100'}]}
            for cid,name,skin in [('1029','Magik','Amethyst Armor'),('1035','Venom','Space Knight')]]
    tab.route('**/api/catalogue/library',lambda route:route.fulfill(json={'heroes':heroes}))
    tab.route('**/api/catalogue/hero/**',lambda route:route.fulfill(body=image.getvalue(),content_type='image/png'))
    def portrait(route):
        raw=BytesIO();colour=(210,40,50,255) if '1029' in route.request.url else (30,130,200,255)
        Image.new('RGBA',(32,32),colour).save(raw,'PNG');route.fulfill(body=raw.getvalue(),content_type='image/png')
    tab.route('**/api/catalogue/thumbnail/*',portrait)
    tab.route('**/static/viewport.js',lambda route:route.fulfill(
        body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*',lambda route:route.fulfill(json=[{
        'name':'Body','game_rel':'Characters/1029/1029001/Meshes/Body'}]))
    tab.route('**/api/skin_materials',lambda route:route.fulfill(json={'ok':True,'materials':{}}))
    tab.route('**/api/idle_animations?*',lambda route:route.fulfill(json={'ok':True,'animations':[]}))
    tab.route('**/api/browse_material_dirs?*',lambda route:route.fulfill(json={'dirs':[]}))
    try:
        tab.goto(url)
        tab.wait_for_function('window.__inspection && window.atelierProject?.()')
        tab.wait_for_selector('.roster-portrait img')
        assert tab.locator('.roster-portrait img').count()==2
        assert all('/api/catalogue/hero/' in img.get_attribute('src') and img.get_attribute('src').endswith('/avatar')
                   for img in tab.locator('.roster-portrait img').all())
        assert tab.locator('.roster-skins img').count()==0
        assert tab.locator('.roster-skins').get_by_text('Amethyst Armor',exact=True).count()==1
        tab.locator('.roster-portrait').nth(1).click()
        assert tab.locator('.roster-skins').get_by_text('Space Knight',exact=True).count()==1
        tab.wait_for_selector('.roster-skin[data-artwork-colour]')
        blue=tab.locator('.roster-skin').evaluate('el=>getComputedStyle(el).backgroundColor')
        tab.locator('.roster-portrait').first.click();tab.wait_for_selector('.roster-skin[data-artwork-colour]')
        red=tab.locator('.roster-skin').evaluate('el=>getComputedStyle(el).backgroundColor')
        assert blue!=red
        for theme in ('dark','light'):
            tab.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            tab.wait_for_timeout(50)
            assert tab.locator('.roster-skin').evaluate(r"""el=>{
              const s=getComputedStyle(el),rgb=x=>x.match(/[\d.]+/g).slice(0,3).map(Number);
              const lum=c=>c.map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0);
              const a=lum(rgb(s.color)),b=lum(rgb(s.backgroundColor));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5;
            }""")
        checks.append('Skin name backgrounds sample their own portrait colours and retain readable text in light and dark themes')
        tab.locator('.roster-portrait').nth(1).click()
        tab.evaluate("window.dispatchEvent(new CustomEvent('atelier:catalogue-updated'))")
        tab.wait_for_timeout(100)
        assert tab.locator('.roster-skins').get_by_text('Space Knight',exact=True).count()==1
        tab.evaluate("AtelierViewport.open('1029001','Hero emblem fixture')")
        tab.wait_for_function("document.querySelector('#viewport-hero-logo').naturalWidth>0 && !document.querySelector('#viewport-hero-logo').hidden")
        assert tab.locator('#viewport-hero-logo').get_attribute('src').endswith('/1029/logo')
        checks.append('Roster uses square hero avatars and text-only skin names; artwork refresh preserves selection and the viewer shows the matching hero logo')
        tab.evaluate('AtelierViewport.close()')
        # The inherited Home grid fills the available height. Create actual
        # overflow before testing keyboard scrolling, including on a large monitor.
        tab.set_viewport_size({'width':1024,'height':768})
        for i in range(20):heroes.append({'name':f'Hero {i}','path':f'Characters/{1100+i}','avatar':'/api/catalogue/hero/1029/avatar','skins':[]})
        tab.evaluate("window.dispatchEvent(new CustomEvent('atelier:catalogue-updated'))")
        tab.wait_for_function('document.querySelectorAll(".roster-portrait").length===22')
        tab.wait_for_function('(()=>{const track=document.querySelector(".roster-strip");return track.scrollHeight>track.clientHeight;})()')
        tab.emulate_media(reduced_motion='reduce')
        tab.locator('.roster-portrait').first.focus();tab.keyboard.press('ArrowRight')
        assert tab.locator('.roster-portrait').nth(1).evaluate('el=>el===document.activeElement')
        tab.keyboard.press('End')
        assert tab.locator('.roster-portrait').last.evaluate('el=>el===document.activeElement')
        tab.wait_for_function('document.querySelector(".roster-strip").scrollTop>0')
        tab.keyboard.press('Home')
        assert tab.locator('.roster-portrait').first.evaluate('el=>el===document.activeElement')
        tab.wait_for_function('document.querySelector(".roster-strip").scrollTop===0')
        assert tab.locator('.roster-portrait').first.evaluate('el=>{const card=el.getBoundingClientRect(),track=el.closest(".roster-strip").getBoundingClientRect();return card.top>=track.top && card.bottom<=track.bottom;}')
        tab.screenshot(path=str(report/'roster-wall-keyboard.png'))
        assert tab.locator('#hero-roster').evaluate('el=>el.scrollWidth<=el.clientWidth')
        checks.append('Roster wall arrows and Home/End move focus across heroes, scroll vertically under reduced motion and fit compact windows')
        heroes[1]['skins'].extend({'name':f'Costume {i}', 'path':f'Characters/1035/1035{i:03}',
                                  'thumbnail':'/api/catalogue/thumbnail/1035100'} for i in range(20))
        tab.evaluate("window.dispatchEvent(new CustomEvent('atelier:catalogue-updated'))")
        tab.wait_for_function('document.querySelectorAll(".roster-skin").length===21')
        tab.get_by_role('button',name='Next skins',exact=True).click()
        tab.wait_for_function('document.querySelector(".roster-skins").scrollLeft>0')
        tab.wait_for_function("""!document.querySelector('button[aria-label="Previous skins"]').disabled""")
        tab.get_by_role('button',name='Previous skins',exact=True).click()
        tab.wait_for_function('document.querySelector(".roster-skins").scrollLeft===0')
        checks.append('Skin side arrows browse an overflowing costume list without changing the selected hero')
    finally:
        if not reuse_page: tab.close()
