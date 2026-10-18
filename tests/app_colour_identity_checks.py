"""Check Home/library decoration in installed Chromium against an isolated dev server.

Game artwork is read from the server's private catalogue. Failure/race cases use
labelled image and sidebar fixtures, without saving assets or changing projects.
Run with --base-url <private server> --report-dir <private report directory>.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


def png(colour, size=(96, 96), costume=False):
    image = Image.new('RGBA', size, colour)
    if costume:
        ImageDraw.Draw(image).rectangle((28, 12, 67, 83), fill='#df2454')
    output = BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


RED = '#df2454'
BLUE = '#247be0'
PURPLE = '#7141ba'
GREEN = '#30ad70'
IMAGES = {
    '/api/catalogue/hero/1046/avatar': png(PURPLE),
    '/api/catalogue/hero/1046/story': png('#51575e', (344, 120)),
    '/api/catalogue/hero/1058/avatar': png(BLUE),
    '/api/catalogue/hero/1058/story': png(BLUE, (344, 120)),
    '/api/catalogue/icon/1046102': png('#b1947e', costume=True),
    '/api/catalogue/thumbnail/1046102': png('#ad927e'),
    '/api/catalogue/banner/1046102': png('#c53e6d', (848, 192)),
    '/api/catalogue/icon/1046103': png(BLUE),
    '/api/catalogue/thumbnail/1046103': png(BLUE),
    '/api/catalogue/thumbnail/1046104': png(GREEN),
    '/api/catalogue/icon/1046105': png((0, 0, 0, 0)),
    '/api/catalogue/thumbnail/1046105': png(BLUE),
    '/api/catalogue/thumbnail/1046106': png(RED),
    '/api/catalogue/icon/1058100': png(BLUE),
    '/api/catalogue/thumbnail/1058100': png(BLUE),
    '/colour-grey': png('#888888'),
}


def heroes_fixture():
    def skin(sid, name, **extra):
        return dict(name=name, path=f'Characters/{sid[:4]}/{sid}',
                    icon=f'/api/catalogue/icon/{sid}',
                    thumbnail=f'/api/catalogue/thumbnail/{sid}', **extra)
    return [
        dict(name='Fixture purple hero', path='Characters/1046',
             avatar='/api/catalogue/hero/1046/avatar', skins=[
                 skin('1046102', 'Fixture red costume', banner='/api/catalogue/banner/1046102'),
                 skin('1046103', 'Fixture blue costume', banner='/api/catalogue/banner/1046103'),
                 skin('1046104', 'Fixture missing icon'),
                 skin('1046105', 'Fixture transparent icon'),
                 skin('1046106', 'Fixture hero fallback', hero_fallback=True),
             ]),
        dict(name='Fixture blue hero', path='Characters/1058',
             avatar='/api/catalogue/hero/1058/avatar', skins=[skin('1058100', 'Fixture blue identity')]),
        dict(name='Fixture absent artwork', path='Characters/1099',
             avatar='/api/catalogue/hero/1099/avatar', skins=[skin('1099100', 'Fixture absent costume')]),
    ]


def rgb(colour):
    return 'rgb(%d, %d, %d)' % tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def wait_decoration(page, kind, colour):
    page.wait_for_function("""([kind, expected]) => {
      const root=document.querySelector(kind==='banner'?'#library-hero':kind==='continue'?'#continue-ribbon':'.roster-skin');
      if(!root)return false;
      if(kind==='banner')return root.classList.contains('has-art-colour')&&getComputedStyle(root,'::before').backgroundColor===expected;
      if(kind==='continue')return getComputedStyle(root).boxShadow.includes(expected);
      const icon=root.querySelector('.roster-skin-icon');
      return icon ? getComputedStyle(icon).boxShadow.includes(expected) : getComputedStyle(root,'::before').backgroundColor===expected;
    }""", arg=[kind, rgb(colour)])


def sample(page, url):
    return page.evaluate("""url=>new Promise(resolve=>{
      const image=new Image();image.onload=()=>resolve({accent:AtelierPolish.accent(image),sample:AtelierPolish.sample(image),palette:AtelierPolish.samplePalette(image)});
      image.onerror=()=>resolve(null);image.src=url;
    })""", url)


def nav(page, path):
    page.evaluate('path=>pushNav({path})', path)
    page.wait_for_function("path=>nav.path===path&&document.getElementById('grid-area').getAttribute('aria-busy')==='false'", arg=path)


def recent(page, sid, *, project=None, with_ids=True):
    path = f'Characters/{sid[:4]}/{sid}' if len(sid) == 7 else f'Characters/{sid}'
    item = dict(game_rel=path + '/Materials/MI_ColourFixture',
                name='Recent edit fixture', file_type='material', modified=time.time(),
                char_name='Fixture hero', skin_name='Fixture costume')
    if with_ids:
        item.update(char_id=sid[:4])
        if len(sid) == 7:
            item['skin_id'] = sid
    page.evaluate('([item,project])=>AtelierRoster.update([item],project||atelierProject())', [item, project])


def controls(page):
    return page.evaluate("""()=>{
      const selectors=['#hero-roster .roster-skin','#hero-roster .roster-open','.roster-filters .btn',
        '#continue-ribbon .btn','#search-input','#search-scope','#settings-theme','#toggle-copy + .switch-track'];
      const properties=['backgroundColor','color','borderTopColor','accentColor','outlineColor'];
      return {roles:Object.fromEntries(['--acc','--bg','--bg2','--bg3','--text','--border',
        '--md-sys-color-primary','--md-sys-color-on-primary'].map(key=>[key,getComputedStyle(document.documentElement).getPropertyValue(key)])),
        controls:Object.fromEntries(selectors.map(selector=>{const el=document.querySelector(selector),style=el&&getComputedStyle(el);
          return [selector,style&&Object.fromEntries(properties.map(key=>[key,style[key]]))];}))};
    }""")


def boot(browser, url, errors, mode='dark', custom=False, fixture=None):
    context = browser.new_context(viewport={'width': 1400, 'height': 900}, reduced_motion='reduce')
    context.route('https://**', lambda route: route.abort())
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    prefs = {'version': 2, 'preset': 'custom', 'saved': [], 'custom': {
        'dark': dict(background='#18271e', surface='#304b38', foreground='#f2f9ef', accent='#da9bf2'),
        'light': dict(background='#f7f3e8', surface='#e6dccc', foreground='#32291e', accent='#704d8b'),
    }}
    page.add_init_script("localStorage.setItem('atelier.theme',%s);localStorage.setItem('atelier.motion','off');localStorage.setItem('atelier.adaptiveAccent','0');%s" % (
        json.dumps(mode), "localStorage.setItem('atelier.appearance',%s);" % json.dumps(json.dumps(prefs)) if custom else ''))
    page.route('**/api/update_check', lambda route: route.fulfill(json={'available': False}))
    page.route('**/api/usmap_update_check', lambda route: route.fulfill(json={'ok': True}))
    page.route('**/api/catalogue/status', lambda route: route.fulfill(json={'updating': False, 'portraits': 803}))
    if fixture:
        page.route('**/api/setup_status', lambda route: route.fulfill(json={'configured': True}))
        page.route('**/api/prereqs', lambda route: route.fulfill(json={'issues': []}))
        page.route('**/api/changelog', lambda route: route.fulfill(json={'available': False, 'releases': []}))
        page.route('**/api/catalogue/**', fixture)
        page.route('**/colour-grey', fixture)
        page.route('**/api/imported', lambda route: route.fulfill(json=[]))
        page.route('**/api/jobs', lambda route: route.fulfill(json={'jobs': []}))
        page.route('**/api/browse?*', lambda route: route.fulfill(json=[dict(
            type='folder', name='Characters', label='Characters', rel_path='Characters', count=3)]))
    page.goto(url)
    page.wait_for_selector('.roster-portrait')
    page.wait_for_function("window.AtelierPolish&&window.AtelierContinuity&&window.atelierProject?.()&&!document.querySelector('.overlay.active')")
    return context, page


def real_artwork(browser, args, report, results, errors):
    context, page = boot(browser, args.base_url, errors)
    try:
        library = page.request.get(args.base_url + '/api/catalogue/library').json()['heroes']
        hero = next(h for h in library if any('nurse' in s['name'].lower() for s in h['skins']))
        nurse = next(s for s in hero['skins'] if 'nurse' in s['name'].lower())
        sid = nurse['path'].split('/')[-1]
        colour = sample(page, nurse['icon'])
        assert colour and colour['accent'], colour
        r, g, b = [int(colour['accent'][i:i+2], 16) for i in (1, 3, 5)]
        assert r > g * 1.5 and r > b * 1.5, ('Nurse-Pool should read red rather than blonde/brown', colour)
        page.locator('.roster-portrait').filter(has=page.locator('strong', has_text=hero['name'])).click()
        tile = page.get_by_role('button', name=nurse['name'], exact=True)
        tile.scroll_into_view_if_needed()
        page.wait_for_function("([name,expected])=>{const icon=[...document.querySelectorAll('.roster-skin')].find(n=>n.getAttribute('aria-label')===name)?.querySelector('img');return icon&&getComputedStyle(icon).boxShadow.includes(expected);}", arg=[nurse['name'], rgb(colour['accent'])])
        recent(page, sid)
        wait_decoration(page, 'continue', colour['accent'])
        page.get_by_role('button', name=nurse['name'], exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(report / 'real-nurse-pool-home.png'), animations='disabled')
        nav(page, nurse['path'])
        wait_decoration(page, 'banner', colour['accent'])
        page.wait_for_selector('#library-hero.has-art')
        page.screenshot(path=str(report / 'real-nurse-pool-library.png'), animations='disabled')
        nurse_banner = page.locator('.library-hero-art').get_attribute('src')
        nav(page, 'Characters/1046')
        hero_colour = sample(page, '/api/catalogue/hero/1046/avatar')['accent']
        wait_decoration(page, 'banner', hero_colour)
        assert page.locator('.library-hero-art').get_attribute('src') == '/api/catalogue/hero/1046/story'
        nav(page, 'Characters/1046/1046102')
        king = sample(page, '/api/catalogue/icon/1046102')['accent']
        wait_decoration(page, 'banner', king)
        page.wait_for_selector('#library-hero.has-art')
        king_banner = page.locator('.library-hero-art').get_attribute('src')
        for mode in ['light', 'dark']:
            page.locator('#settings-theme').select_option(mode, force=True)
            page.screenshot(path=str(report / f'real-king-in-white-{mode}.png'), animations='disabled')
        results.append(dict(check='Real cached Nurse-Pool is red on Home, Continue and library; real Adam Warlock and King in White folders use matching artwork',
                            nurse_id=sid, nurse_picker=colour, nurse_banner=nurse_banner, king_colour=king, king_banner=king_banner))
    finally:
        context.close()


def synthetic(browser, args, report, results, errors, mode, custom):
    heroes = heroes_fixture()
    images = dict(IMAGES)
    held = []

    def fixtures(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        if path == '/api/catalogue/library':
            route.fulfill(json={'heroes': heroes})
        elif path == '/api/catalogue/status':
            route.fulfill(json={'updating': False, 'portraits': 3})
        elif 'hold=' in parsed.query:
            held.append(route)
        elif path == '/api/catalogue/banner/1046102' and 'fresh=1' in parsed.query:
            route.fulfill(body=png(BLUE, (848, 192)), content_type='image/png')
        elif path in images:
            route.fulfill(body=images[path], content_type='image/png')
        else:
            route.fulfill(status=404, body='Artwork absent in explicit test fixture')

    context, page = boot(browser, args.base_url, errors, mode, custom, fixtures)
    label = ('custom-' if custom else '') + mode
    try:
        red = sample(page, '/api/catalogue/icon/1046102')['accent']
        r, g, b = [int(red[i:i+2], 16) for i in (1, 3, 5)]
        assert r > g * 2 and r > b * 1.5, red
        wait_decoration(page, 'skin', red)
        recent(page, '1046102')
        wait_decoration(page, 'continue', red)
        before = controls(page)
        page.get_by_role('button', name='Fixture blue hero', exact=True).click()
        wait_decoration(page, 'skin', BLUE)
        recent(page, '1058100')
        wait_decoration(page, 'continue', BLUE)
        assert controls(page) == before, ('Artwork recoloured a themed control', label, before, controls(page))
        page.screenshot(path=str(report / f'fixture-home-{label}.png'), animations='disabled')
        nav(page, 'Characters/1046')
        wait_decoration(page, 'banner', PURPLE)
        assert controls(page)['roles'] == before['roles']
        nav(page, 'Characters/1046/1046102')
        wait_decoration(page, 'banner', red)
        page.wait_for_selector('#library-hero.has-nameplate.has-art')
        nameplate = urlparse(page.locator('.library-hero-art').get_attribute('src'))
        assert nameplate.path == '/api/catalogue/banner/1046102'
        assert parse_qs(nameplate.query).get('sharp') == ['1']
        assert controls(page)['roles'] == before['roles']
        page.screenshot(path=str(report / f'fixture-nameplate-{label}.png'), animations='disabled')
        for sid, expected in [('1046103', BLUE), ('1046104', GREEN), ('1046105', BLUE), ('1046106', PURPLE)]:
            nav(page, 'Characters/1046/' + sid)
            wait_decoration(page, 'banner', expected)
            if sid == '1046103':
                page.wait_for_function("document.querySelector('.library-hero-art')?.getAttribute('src')==='/api/catalogue/hero/1046/story'")
                assert not page.locator('#library-hero').evaluate("el=>el.classList.contains('has-nameplate')")
        page.evaluate("()=>AtelierContinuity.banner('Characters/1046/1046999',{}, {'Characters/1046/1046999':{heroFallback:true,thumbnail:'/api/catalogue/thumbnail/1046102'}})")
        wait_decoration(page, 'banner', PURPLE)
        page.evaluate("()=>['Characters/1046/1046102','Characters/1058/1058100','Characters/1046/1046103'].forEach(path=>pushNav({path}))")
        page.wait_for_function("nav.path==='Characters/1046/1046103'&&document.getElementById('grid-area').getAttribute('aria-busy')==='false'")
        wait_decoration(page, 'banner', BLUE)
        nav(page, 'Characters/1099/1099100')
        page.wait_for_function("!document.querySelector('.library-hero-art')")
        assert page.locator('#library-hero').evaluate("el=>!el.classList.contains('has-art-colour')&&getComputedStyle(el,'::before').opacity==='0'")
        assert controls(page)['roles'] == before['roles']
        page.screenshot(path=str(report / f'fixture-missing-art-{label}.png'), animations='disabled')
        nav(page, '')
        recent(page, '1046102', with_ids=False)
        wait_decoration(page, 'continue', red)
        recent(page, '1099100')
        page.wait_for_timeout(150)
        assert page.locator('#continue-ribbon').evaluate("el=>getComputedStyle(el).boxShadow==='none'")
        results.append(dict(check='Costume/hero accents match through rapid folder navigation; buttons, inputs, toggles and palette roles stay unchanged; missing/transparent icons, hero fallbacks and failed nameplates work; IDs can come from the edit path', palette=label))

        if label != 'dark':
            return
        contract = page.evaluate("""async()=>{
          const unloaded=AtelierPolish.accent(new Image()),transparent=await new Promise(resolve=>{const im=new Image();im.onload=()=>resolve(AtelierPolish.accent(im));im.src='/api/catalogue/icon/1046105';});
          const im=await new Promise(resolve=>{const im=new Image();im.onload=()=>resolve(im);im.src='/colour-grey';});
          const grey=AtelierPolish.accent(im),getContext=HTMLCanvasElement.prototype.getContext;let inaccessible;
          try{HTMLCanvasElement.prototype.getContext=()=>{throw new DOMException('Sampling blocked','SecurityError');};inaccessible=AtelierPolish.accent(im);}finally{HTMLCanvasElement.prototype.getContext=getContext;}
          let detail;const receive=e=>detail=e.detail;window.addEventListener('atelier:artwork',receive,{once:true});AtelierPolish.artwork(im);
          return {unloaded,transparent,inaccessible,grey,sample:AtelierPolish.sample(im),exports:Object.keys(AtelierPolish),detail};
        }""")
        assert all(contract[key] is None for key in ['unloaded', 'transparent', 'inaccessible']), contract
        assert contract['grey'] == contract['sample'] == '#808080', contract
        assert contract['detail'] == {'accent': '#808080', 'colors': ['#808080']}, contract
        assert all(name in contract['exports'] for name in ['sample', 'samplePalette', 'accent', 'artwork', 'count', 'fly', 'exported', 'empty', 'leave']), contract

        # The path returns to A with different art while A's old requests are pending.
        page.evaluate("""()=>{
          window.__colourEvents=[];window.addEventListener('atelier:artwork',e=>__colourEvents.push(e.detail));
          AtelierContinuity.banner('Characters/1046/1046102',{}, {'Characters/1046/1046102':{icon:'/api/catalogue/icon/1046102?hold=old',banner:'/api/catalogue/banner/1046102?hold=old'}});
        }""")
        for _ in range(60):
            if len(held) >= 2:
                break
            page.wait_for_timeout(25)
        assert len(held) == 2, len(held)
        page.evaluate("""()=>{
          AtelierContinuity.banner('Characters/1058',{},{});
          AtelierContinuity.banner('Characters/1046/1046102',{}, {'Characters/1046/1046102':{icon:'/api/catalogue/icon/1058100?fresh=1',banner:'/api/catalogue/banner/1046102?fresh=1'}});
        }""")
        wait_decoration(page, 'banner', BLUE)
        page.wait_for_selector('#library-hero.has-art')
        events = page.evaluate('__colourEvents.length')
        for route in held:
            route.fulfill(body=images[urlparse(route.request.url).path], content_type='image/png')
        held.clear()
        page.wait_for_timeout(150)
        wait_decoration(page, 'banner', BLUE)
        assert page.evaluate('__colourEvents.length') == events
        assert 'fresh=1' in page.locator('.library-hero-art').get_attribute('src')

        page.get_by_role('button', name='Fixture purple hero', exact=True).click()
        heroes[0]['skins'][0]['icon'] = '/api/catalogue/icon/1046102?hold=continue'
        page.evaluate("window.dispatchEvent(new CustomEvent('atelier:catalogue-updated'))")
        page.wait_for_function("document.querySelector('.roster-skin img')?.getAttribute('src').includes('hold=continue')")
        recent(page, '1046102')
        for _ in range(60):
            if held:
                break
            page.wait_for_timeout(25)
        assert held
        recent(page, '1058100')
        wait_decoration(page, 'continue', BLUE)
        for route in held:
            route.fulfill(body=images[urlparse(route.request.url).path], content_type='image/png')
        held.clear()
        page.wait_for_timeout(150)
        wait_decoration(page, 'continue', BLUE)
        recent(page, '1046', project='Fixture project with hero-only edit')
        wait_decoration(page, 'continue', PURPLE)
        page.evaluate('AtelierRoster.show(false,()=>{})')
        assert page.locator('#continue-ribbon').is_hidden()
        page.evaluate('AtelierRoster.show(true,()=>{})')
        recent(page, '1099100', project='Fixture recovery')
        images['/api/catalogue/icon/1099100'] = png(GREEN)
        page.evaluate("window.dispatchEvent(new CustomEvent('atelier:catalogue-updated'))")
        wait_decoration(page, 'continue', GREEN)
        results.append(dict(check='Synchronous picker/API payload preserved; grey/unloaded/transparent/blocked sampling is safe; stale A-B-A artwork and old Continue callbacks cannot repaint; hero-only edits and recovered artwork work', picker_contract=contract))
    except Exception:
        page.screenshot(path=str(report / f'failure-{label}.png'), animations='disabled')
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--fixtures-only', action='store_true')
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in ['127.0.0.1', 'localhost'], 'Use a private local dev server'
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    results, errors = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                if not args.fixtures_only:
                    real_artwork(browser, args, report, results, errors)
                for custom in [False, True]:
                    for mode in ['dark', 'light']:
                        synthetic(browser, args, report, results, errors, mode, custom)
            finally:
                browser.close()
        assert not errors, errors
    finally:
        (report / 'results.json').write_text(json.dumps({'checks': results, 'page_errors': errors}, indent=2), encoding='utf-8')
    for check in results:
        print('PASS ' + check['check'] + (' (' + check['palette'] + ')' if 'palette' in check else ''))


if __name__ == '__main__':
    main()
