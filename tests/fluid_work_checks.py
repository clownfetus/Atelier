"""Real configuration requests and connected fluid feedback, using offline fixtures."""
from io import BytesIO
from time import monotonic

from PIL import Image, ImageChops


def _ink_components(png, background=(20, 22, 27)):
    """Measure actual raster continuity; masks may punch holes without splitting the ink."""
    image = Image.open(BytesIO(png)).convert('RGB')
    pixels = image.load()
    active = {(x, y) for y in range(image.height) for x in range(image.width)
              if max(abs(pixels[x, y][c] - background[c]) for c in range(3)) >= 28}
    count, largest = len(active), 0
    while active:
        pending = [active.pop()]
        size = 0
        while pending:
            x, y = pending.pop()
            size += 1
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
                point = (x + dx, y + dy)
                if point in active:
                    active.remove(point)
                    pending.append(point)
        largest = max(largest, size)
    return image, count, largest


def run_fluid_work_checks(context, url, report, checks):
    tab = context.new_page()
    errors, pending = [], []
    stored = None
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/AES.json', lambda route: route.fulfill(json={'mainKey': 'F' * 64}))
    tab.route('**/api/download_usmap', lambda route: route.fulfill(json={'ok': True, 'path': 'Fixture/current.usmap'}))
    for endpoint in ('validate_paks', 'validate_usmap', 'validate_mods_folder', 'validate_blender'):
        tab.route('**/api/' + endpoint + '?*', lambda route: route.fulfill(json={'status': 'ok'}))
    tab.route('**/api/content_mounts', lambda route: route.fulfill(json={'mounts': []}))

    def option(identifier, value):
        tab.evaluate("([id,value])=>{const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('change'));}", [identifier, value])

    def request():
        tab.evaluate("() => { window.fluidOpening = openPaths(); }")
        deadline = monotonic() + 5
        while not pending and monotonic() < deadline:
            tab.wait_for_timeout(10)
        assert pending, 'Configuration discovery never reached the held request'
        held = pending.pop(0)
        tab.wait_for_selector('#setup-loading[aria-busy="true"] .am-config-art')
        return held

    def respond(held, outcome='success', path='Fixture/Paks'):
        held.fulfill(json={'configured': True, 'paks_prefill': path if outcome == 'success' else '',
                           'error': 'Fixture discovery failed' if outcome == 'error' else None})
        tab.wait_for_function("outcome=>document.querySelector('#setup-overlay .modal').dataset.amWorkingOutcome===outcome", arg=outcome)
        assert tab.locator('#setup-loading').get_attribute('aria-busy') == 'false'
        tab.wait_for_function("!document.querySelector('#setup-overlay .modal').classList.contains('am-working-border')")
        tab.evaluate('fluidOpening')

    def close():
        # Exercise the app's cancellation handler without waiting for network completion.
        tab.locator('#setup-close').evaluate('el=>el.click()')
        tab.wait_for_function("!document.getElementById('setup-overlay').classList.contains('active')")

    try:
        tab.goto(url)
        tab.wait_for_function("window.atelierProject?.() && window.AtelierMotion?.configDiscovery && !document.querySelector('.overlay.active')")
        tab.wait_for_selector('#grid-area .card')
        stored = tab.evaluate("Object.fromEntries(['atelier.theme','atelier.motion'].map(key=>[key,localStorage.getItem(key)]))")
        tab.emulate_media(reduced_motion='no-preference')
        option('settings-motion', 'full')
        # Bootstrap completes normally; hold only explicit Settings discovery below.
        tab.route('**/api/setup_status', lambda route: pending.append(route))
        held = request()
        tab.wait_for_selector('#setup-overlay .am-working-border')
        tab.evaluate(r"""() => {
          window.fluidPanel=document.querySelector('#setup-overlay .modal');
          window.fluidOutcomes=[];
          window.fluidObserver=new MutationObserver(records=>{
            for(const record of records) if(record.attributeName==='data-am-working-outcome') {
              const value=fluidPanel.dataset.amWorkingOutcome;if(value)fluidOutcomes.push(value);
            }
          });
          fluidObserver.observe(fluidPanel,{attributes:true});
          window.fluidBorder=()=>{
            const uri=fluidPanel.style.getPropertyValue('--am-working-frame');
            return new DOMParser().parseFromString(decodeURIComponent(uri.slice(uri.indexOf(',')+1,uri.lastIndexOf('"'))),'image/svg+xml');
          };
          window.fluidLayout=()=>{
            const host=document.querySelector('.am-config-art'),svg=host.querySelector('.am-config-conduits');
            const panel=fluidPanel.getBoundingClientRect(),style=getComputedStyle(fluidPanel),art=host.getBoundingClientRect();
            const label=document.querySelector('#setup-loading > span:not(.am-config-art)').getBoundingClientRect();
            const paths=[...svg.querySelectorAll('.am-config-edge-channel')];
            return {source:+svg.dataset.sourceX,destination:+svg.dataset.destinationX,
              left:panel.left+parseFloat(style.borderLeftWidth)/2,right:panel.right-parseFloat(style.borderRightWidth)/2,
              labelTop:label.top,artBottom:art.bottom,paths:paths.map(p=>p.getTotalLength()),
              scanner:!!host.querySelector('.am-config-scanner'),receiver:!!host.querySelector('.am-config-receiver'),
              status:document.getElementById('setup-loading').textContent.trim()};
          };
        }""")
        for theme, pigment in [('dark', '#df6249'), ('light', '#269f8f')]:
            option('settings-theme', theme)
            tab.evaluate("pigment=>window.dispatchEvent(new CustomEvent('atelier:artwork',{detail:{accent:pigment,colors:[pigment]}}))", pigment)
            tab.wait_for_function("document.querySelector('.am-config-art').style.getPropertyValue('--krackle-energy')===AtelierMotion.energy.resolve(document.getElementById('setup-loading')).charge")
            geometry = tab.evaluate('fluidLayout()')
            assert abs(geometry['source'] - geometry['left']) <= 1 and abs(geometry['destination'] - geometry['right']) <= 1, geometry
            assert geometry['labelTop'] >= geometry['artBottom'] and min(geometry['paths']) > 12, geometry
            assert geometry['scanner'] and geometry['receiver'] and 'configuration' in geometry['status'].lower(), geometry
            roles = tab.evaluate("[...fluidBorder().querySelectorAll('[data-role]')].map(n=>n.getAttribute('data-role'))")
            assert all(role in roles for role in ('source', 'channel', 'ribbon', 'receiver')), roles
            tab.locator('#setup-overlay .modal').screenshot(path=str(report / ('fluid-config-' + theme + '.png')))
        # Geometry follows the real panel; it is not a fixed-size decoration floating above it.
        tab.evaluate("fluidPanel.style.width='480px'")
        tab.wait_for_function("Math.abs(fluidLayout().destination-fluidLayout().right)<1")
        geometry = tab.evaluate('fluidLayout()')
        assert abs(geometry['source'] - geometry['left']) <= 1, geometry
        tab.evaluate("fluidPanel.style.width=''")
        tab.emulate_media(reduced_motion='reduce')
        tab.wait_for_function("document.querySelector('.am-config-art').dataset.amConfigRunning==='false'")
        assert tab.locator('.am-config-art').evaluate('el=>el.getAnimations({subtree:true}).length') == 0
        tab.emulate_media(reduced_motion='no-preference')
        tab.wait_for_function("document.querySelector('.am-config-art').dataset.amConfigRunning==='true'")
        tab.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
        tab.wait_for_function("document.querySelector('.am-config-art').dataset.amConfigRunning==='false'")
        assert tab.locator('.am-config-art').evaluate('el=>el.getAnimations({subtree:true}).length') == 0
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        tab.wait_for_function("document.querySelector('.am-config-art').dataset.amConfigRunning==='true'")
        respond(held)
        assert tab.evaluate("fluidOutcomes.includes('success')")
        assert tab.locator('#setup-path').input_value() == 'Fixture/Paks'
        assert tab.locator('.am-config-art').count() == 0
        checks.append('Held real configuration discovery joins both native panel edges to scanner/channel/receiver, follows resize and theme, keeps its label clear, respects reduced/hidden, and finishes once with finite cleanup')
        close()

        old = request()
        close()
        current = request()
        tab.evaluate('fluidOutcomes.length=0')
        old.fulfill(json={'configured': True, 'paks_prefill': 'Fixture/Stale'})
        tab.wait_for_timeout(100)
        assert tab.locator('#setup-loading').get_attribute('aria-busy') == 'true'
        assert not tab.evaluate('fluidOutcomes.length'), 'A stale response finished the new operation'
        assert tab.locator('#setup-path').input_value() != 'Fixture/Stale'
        respond(current, path='Fixture/Current')
        assert tab.locator('#setup-path').input_value() == 'Fixture/Current'
        close()
        for outcome in ('warning', 'error'):
            held = request()
            tab.evaluate('fluidOutcomes.length=0')
            respond(held, outcome)
            assert not tab.evaluate("fluidOutcomes.includes('success')"), outcome
            assert tab.evaluate('fluidOutcomes'), outcome
            close()
        checks.append('Closing/reopening configuration fences late responses; missing paths warn and failures error without a false successful finish')

        option('settings-theme', 'dark')
        tab.evaluate("""() => {
          window.fluidFixture=document.createElement('div');
          fluidFixture.style.cssText='position:fixed;left:40px;top:140px;display:flex;gap:28px;align-items:center;padding:20px;background:#14161b;z-index:9999';
          window.fluidSave=document.createElement('span');fluidSave.style.setProperty('--am-material-save-size','44px');
          window.fluidViewport=document.createElement('span');fluidViewport.style.setProperty('--am-viewport-loader-size','112px');
          fluidFixture.append(fluidSave,fluidViewport);document.body.append(fluidFixture);
          window.fluidSaveMotion=AtelierMotion.materialSave.mount(fluidSave,{state:'saving'});
          window.fluidViewportMotion=AtelierMotion.viewportLoader.mount(fluidViewport,{state:'loading'});
          window.fluidPause=time=>{for(const host of [fluidSave,fluidViewport])for(const a of host.getAnimations({subtree:true})){a.pause();a.currentTime=time;}};
        }""")
        tab.wait_for_function("fluidViewport.getAnimations({subtree:true}).some(a=>a.effect.getTiming().iterations===Infinity)")
        assert tab.evaluate('fluidSave.getBoundingClientRect().width') == 44
        assert tab.evaluate('fluidViewport.getBoundingClientRect().width') == 112
        contract = tab.evaluate("""() => {
          const save=fluidSave.querySelector('.am-material-save-fluid'),viewport=fluidViewport.querySelector('.am-viewport-loader-fluid');
          const connected=(root,prefix)=>{
            const path=root.querySelector('.'+prefix+'conduit'),source=root.querySelector('.'+prefix+'source').getBBox(),receiver=root.querySelector('.'+prefix+'receiver').getBBox();
            const a=path.getPointAtLength(0),b=path.getPointAtLength(path.getTotalLength());
            const inside=(p,r)=>p.x>=r.x-1&&p.x<=r.x+r.width+1&&p.y>=r.y-1&&p.y<=r.y+r.height+1;
            return inside(a,source)&&inside(b,receiver)&&parseFloat(getComputedStyle(path).strokeWidth)>=3.8;
          };
          return {save:connected(save,'am-material-save-'),viewport:connected(viewport,'am-viewport-loader-'),
            masks:fluidSave.querySelectorAll('mask').length+fluidViewport.querySelectorAll('mask').length,
            looseHidden:[...fluidViewport.querySelectorAll('.am-viewport-loader-loose')].every(n=>getComputedStyle(n).display==='none')};
        }""")
        assert contract['save'] and contract['viewport'] and contract['masks'] == 2 and contract['looseHidden'], contract
        captures = {}
        for phase in (260, 700):
            tab.evaluate('fluidPause', phase)
            for name, selector in [('save', '.am-material-save-svg'), ('viewport', '.am-viewport-loader-svg')]:
                png = tab.locator(selector).last.screenshot()
                image, ink, largest = _ink_components(png)
                assert ink > image.width * image.height * .08 and largest >= ink * .88, (name, phase, ink, largest)
                image.save(report / f'fluid-{name}-{phase}.png')
                captures[name, phase] = image
        for name in ('save', 'viewport'):
            assert ImageChops.difference(captures[name, 260], captures[name, 700]).getbbox(), name + ' has no travelling fluid'
        tab.evaluate("fluidSaveMotion.setState('success');fluidViewportMotion.setState('ready')")
        tab.wait_for_function('!fluidSave.getAnimations({subtree:true}).length && !fluidViewport.getAnimations({subtree:true}).length')
        for name, selector in [('save', '.am-material-save-svg'), ('viewport', '.am-viewport-loader-svg')]:
            done = Image.open(BytesIO(tab.locator(selector).last.screenshot())).convert('RGB')
            done.save(report / f'fluid-{name}-done.png')
            assert ImageChops.difference(captures[name, 700], done).getbbox(), name + ' did not change to its completed pose'
        tab.evaluate('fluidSaveMotion.destroy();fluidViewportMotion.destroy();fluidFixture.remove();fluidObserver.disconnect()')
        checks.append('44px save and 112px viewport feedback render one bold connected masked fluid body at controlled phases, travel on the shared beat, and settle into distinct completed poses')
        assert not errors, errors
    finally:
        if stored is not None:
            tab.evaluate("stored=>{for(const [key,value] of Object.entries(stored)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()
