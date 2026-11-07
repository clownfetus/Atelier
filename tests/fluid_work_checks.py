"""Real configuration requests drive the setup-status feedback, using offline fixtures."""
from time import monotonic

LOADING = '#setup-loading[aria-busy="true"] .am-config-art[data-glyph-state="busy"][data-glyph-tier="inline"]'


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
        tab.wait_for_selector(LOADING)
        return held

    def respond(held, outcome='success', path='Fixture/Paks'):
        held.fulfill(json={'configured': True, 'paks_prefill': path if outcome == 'success' else '',
                           'error': 'Fixture discovery failed' if outcome == 'error' else None})
        tab.wait_for_function("outcome=>fluidOutcomes.includes(outcome)", arg=outcome)
        assert tab.locator('#setup-loading').get_attribute('aria-busy') == 'false'
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
        # Every outcome the app hands the feedback is recorded, in order.
        tab.evaluate("""() => {
          window.fluidOutcomes = [];
          const original = AtelierMotion.configDiscovery.begin;
          AtelierMotion.configDiscovery = {begin(target) {
            const finish = original(target);
            const watched = outcome => { fluidOutcomes.push(outcome); return finish(outcome); };
            watched.dispose = finish.dispose;
            return watched;
          }};
        }""")
        # Bootstrap completes normally; hold only explicit Settings discovery below.
        tab.route('**/api/setup_status', lambda route: pending.append(route))
        held = request()
        tab.locator('#setup-overlay .modal').screenshot(path=str(report / 'setup-status-busy.png'))
        respond(held)
        assert tab.locator('#setup-path').input_value() == 'Fixture/Paks'
        # The cover lifts with the result, and the glyph goes with it.
        tab.wait_for_function("!document.querySelector('.am-config-art') && !document.querySelector('#setup-loading.am-config-discovery-active')")
        checks.append('Held real configuration discovery shows the working glyph while the request runs and finishes once with success')
        close()

        old = request()
        close()
        current = request()
        tab.evaluate('fluidOutcomes.length=0')
        old.fulfill(json={'configured': True, 'paks_prefill': 'Fixture/Stale'})
        tab.wait_for_timeout(100)
        assert tab.locator('#setup-loading').get_attribute('aria-busy') == 'true'
        assert not tab.evaluate("fluidOutcomes.filter(outcome => outcome !== 'cancel').length"), 'A stale response finished the new operation'
        assert tab.locator('#setup-path').input_value() != 'Fixture/Stale'
        respond(current, path='Fixture/Current')
        assert tab.locator('#setup-path').input_value() == 'Fixture/Current'
        close()
        for outcome in ('warning', 'error'):
            held = request()
            tab.evaluate('fluidOutcomes.length=0')
            respond(held, outcome)
            assert not tab.evaluate("fluidOutcomes.includes('success')"), outcome
            close()
        checks.append('Closing/reopening configuration fences late responses; missing paths warn and failures error without a false successful finish')
        assert not errors, errors
    finally:
        if stored is not None:
            tab.evaluate("stored=>{for(const [key,value] of Object.entries(stored)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()
