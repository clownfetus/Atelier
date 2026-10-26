"""Artwork identity feeds decorative motion without changing semantic interface inks."""
from io import BytesIO
from urllib.parse import urlparse

from PIL import Image


def run_context_ink_checks(context, url, report, checks):
    tab = context.new_page()
    errors = []
    held_portraits = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    red, teal, banner = '#e85d4a', '#39b8a0', '#7060e0'

    def image(colour):
        output = BytesIO()
        Image.new('RGB', (48, 48), colour).save(output, format='PNG')
        return output.getvalue()

    def catalogue(route):
        path = urlparse(route.request.url).path
        if path.endswith('/library'):
            route.fulfill(json={'heroes': [{'name': 'Late portrait', 'path': 'Characters/1046',
                                           'avatar': '/api/catalogue/hero/1046/avatar', 'skins': []}]})
        elif path.endswith('/hero/1046/avatar'):
            held_portraits.append(route)
        elif path.endswith('/icon/1000000'):
            route.fulfill(body=image(red), content_type='image/png')
        elif path.endswith('/icon/1000001'):
            route.fulfill(body=image(teal), content_type='image/png')
        elif '1000' in path:
            route.fulfill(body=image(banner), content_type='image/png')
        else:
            route.fulfill(status=404, body='No fixture art')

    tab.route('**/api/catalogue/**', catalogue)
    stored = None
    try:
        tab.goto(url)
        tab.wait_for_function("window.atelierProject?.() && window.AtelierMotion?.energy && !document.querySelector('.overlay.active')")
        stored = tab.evaluate("Object.fromEntries(['atelier.theme','atelier.motion'].map(k=>[k,localStorage.getItem(k)]))")
        tab.locator('#settings-motion').select_option('full', force=True)
        tab.evaluate("""() => {
          window.inkPanel=document.createElement('section');inkPanel.className='modal';
          inkPanel.style.cssText='position:fixed;left:260px;top:180px;width:360px;height:200px;background:var(--bg2);z-index:5000';
          inkPanel.textContent='Context pigment';document.body.append(inkPanel);
          window.semanticInks=()=>{
            const css=getComputedStyle(document.documentElement);
            return ['--acc','--text','--krackle-charge','--krackle-success','--krackle-warn','--krackle-fault'].map(k=>css.getPropertyValue(k));
          };
          window.borderInk=()=>{
            const source=inkPanel.style.getPropertyValue('--am-working-frame');
            return source && decodeURIComponent(source);
          };
          window.endInkWork=AtelierMotion.working.begin(inkPanel);
        }""")
        tab.wait_for_selector('.roster-portrait')
        tab.evaluate("AtelierRoster.show(false);AtelierContinuity.banner('Characters/1000/1000000')")
        tab.wait_for_function("AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit('#e85d4a',getComputedStyle(inkPanel).backgroundColor)")
        assert held_portraits, 'Delayed roster fixture was not requested'
        for request in held_portraits:
            request.fulfill(body=image(teal), content_type='image/png')
        tab.wait_for_function("document.querySelector('.roster-portrait img').complete")
        assert tab.evaluate("AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit('#e85d4a',getComputedStyle(inkPanel).backgroundColor)")
        checks.append('A late Home portrait cannot replace the costume pigment after leaving Home')
        for theme in ('dark', 'light'):
            tab.locator('#settings-theme').select_option(theme, force=True)
            before = tab.evaluate('semanticInks()')
            for skin, colour in [('1000000', red), ('1000001', teal)]:
                tab.evaluate("skin=>AtelierContinuity.banner('Characters/1000/'+skin)", skin)
                tab.wait_for_function("colour=>AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit(colour,getComputedStyle(inkPanel).backgroundColor)", arg=colour)
                tab.wait_for_function("borderInk()?.includes(AtelierMotion.energy.resolve(inkPanel).charge)")
                value = tab.evaluate("() => {const ink=AtelierMotion.energy.resolve(inkPanel);return {...ink,contrast:AtelierKrackleInks.contrast(ink.charge,getComputedStyle(inkPanel).backgroundColor)};}")
                assert value['source'] == 'artwork' and value['contrast'] >= 3, value
                assert tab.evaluate('semanticInks()') == before
                tab.screenshot(path=str(report / f'context-{skin}-{theme}.png'))
        checks.append('Motion and native border ink follow the actual red/teal costume icon in dark/light themes, even when the banner has a different hue; semantic controls and outcome inks remain exact')

        tab.evaluate("AtelierContinuity.banner('Characters/1000/1000000')")
        tab.wait_for_function("AtelierMotion.energy.resolve(inkPanel).source==='artwork'")
        tab.evaluate("AtelierViewportIdentity.show('1000001','1000');document.getElementById('viewport-overlay').classList.add('active')")
        tab.wait_for_function("getComputedStyle(document.getElementById('viewport-box')).getPropertyValue('--vp-skin-colour').trim()==='#39b8a0'")
        assert tab.evaluate("AtelierMotion.energy.resolve(document.getElementById('viewport-head')).source") == 'artwork'
        tab.wait_for_function("AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit('#39b8a0',getComputedStyle(inkPanel).backgroundColor)")
        tab.evaluate("AtelierViewportIdentity.clear();document.getElementById('viewport-overlay').classList.remove('active')")
        tab.wait_for_function("AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit('#e85d4a',getComputedStyle(inkPanel).backgroundColor)")
        tab.evaluate("AtelierContinuity.banner('Characters/9999/9999000')")
        tab.wait_for_function("AtelierMotion.energy.resolve(inkPanel).source==='theme'")
        tab.evaluate("AtelierContinuity.banner('')")
        tab.wait_for_function("getComputedStyle(document.documentElement).getPropertyValue('--krackle-energy').trim()===AtelierMotion.energy.resolve().charge")
        assert tab.evaluate("AtelierMotion.energy.resolve(inkPanel).charge===AtelierKrackleInks.fit(getComputedStyle(inkPanel).getPropertyValue('--acc'),getComputedStyle(inkPanel).backgroundColor)")
        checks.append('Model Studio uses its own current costume pigment and returns to library pigment on close; missing art and leaving a hero restore the selected theme colour')
        # Computed color-mix is color(srgb ...) in Chromium, and translucent layers
        # must be fitted against their visible composite rather than the top RGB alone.
        surfaces = tab.evaluate("""() => {
          const base=document.createElement('div'),middle=document.createElement('div'),leaf=document.createElement('span');
          base.style.cssText='position:fixed;width:40px;height:40px;background:#204060';
          middle.style.cssText='width:40px;height:40px;background:rgba(240,80,16,.25)';
          leaf.style.cssText='display:block;width:40px;height:40px;--roster-skin-accent:#445566;background:color(srgb .2 .8 .4 / .5)';
          base.append(middle);middle.append(leaf);document.body.append(base);
          try {
            const layered=AtelierMotion.energy.resolve(leaf).charge;
            // Known composition: (51,204,102)*.5 + ((240,80,16)*.25+(32,64,96)*.75)*.5.
            const expectedLayered=AtelierKrackleInks.fit('#445566','#448859');
            leaf.style.background='color-mix(in srgb,#000000 50%,#ffffff)';
            const mixed=AtelierMotion.energy.resolve(leaf).charge;
            const expectedMixed=AtelierKrackleInks.fit('#445566','#808080');
            return {layered,expectedLayered,mixed,expectedMixed,
              layeredContrast:AtelierKrackleInks.contrast(layered,'#448859'),
              mixedContrast:AtelierKrackleInks.contrast(mixed,'#808080')};
          } finally {base.remove();}
        }""")
        assert surfaces['layered'] == surfaces['expectedLayered'], surfaces
        assert surfaces['mixed'] == surfaces['expectedMixed'], surfaces
        assert surfaces['layeredContrast'] >= 3 and surfaces['mixedContrast'] >= 3, surfaces
        checks.append('Decorative pigment handles computed color-mix and composites nested translucent surfaces before fitting readable contrast')
        tab.evaluate('endInkWork();inkPanel.remove()')
        assert not errors, errors
    finally:
        if stored is not None:
            tab.evaluate("stored=>{for(const [key,value] of Object.entries(stored)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()
