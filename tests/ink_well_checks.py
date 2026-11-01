"""Ink-well build stage: skin palette, lifecycle and handover, using the real frontend only."""
from urllib.parse import parse_qs, urlparse

SNAPSHOT = """{project:'Smoke A', modName:'Ink fixture', copyToMods:false, modsPath:'', protected:false, skipped:0, excluded:[],
  included:[{name:'Body', game_rel:'Characters/1015/1015101/Materials/MI_1015101_Body', file_type:'material'},
            {name:'Equip', game_rel:'Characters/1015/1015101/Texture/T_1015101_Equip_01_D', file_type:'texture'},
            {name:'Other', game_rel:'Characters/1014/1014100/Textures/T_1014100_Body_D', file_type:'texture'},
            {name:'Sound', game_rel:'Audio/Sound', file_type:'audio'}]}"""

TINTS = ['#c8243a', '#e8c25a', '#3f6b2a']


def run_ink_well_checks(context, url, report, checks):
    tab = context.new_page()
    errors, asked = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))

    def palette(route):
        asked.append(parse_qs(urlparse(route.request.url).query).get('skin', []))
        route.fulfill(json={'colors': TINTS, 'sources': []})

    tab.route('**/api/diffuse_palette?**', palette)
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierExportReview && window.AtelierMotion?.inkWell && window.atelierProject?.()')
        tab.emulate_media(reduced_motion='no-preference')
        assert tab.evaluate("AtelierMotionPolicy.mode()") == 'full'

        # The review asks once for the included skins' colours (in order, deduplicated); the build
        # cooks them into a few inner bubbles.
        tab.evaluate(f"""() => {{
          window.inkSnapshot = Object.freeze({SNAPSHOT});
          AtelierExportReview.open(inkSnapshot, {{confirm(){{}}, refresh(){{}}, settings(){{}}, reveal(){{}}}});
          AtelierExportReview.checking(inkSnapshot);
        }}""")
        # The tint paths exist as soon as the palette answers; wait for their first drawn frame.
        tab.wait_for_function("[...document.querySelectorAll('.export-review-stage .am-ink-well-tint')].some(el => (el.getAttribute('d') || '').includes('M'))")
        assert asked == [['1015101', '1014100']], asked
        tints = tab.evaluate("""() => [...document.querySelectorAll('.export-review-stage .am-ink-well-tint')]
          .map(el => ({fill: getComputedStyle(el).fill, shapes: (el.getAttribute('d')||'').split('M').length - 1}))""")
        assert [t['fill'] for t in tints] == ['rgb(200, 36, 58)', 'rgb(232, 194, 90)', 'rgb(63, 107, 42)'], tints
        # Three colours ride four inner slots; a slot between lives is briefly empty.
        assert 2 <= sum(t['shapes'] for t in tints) <= 4, tints
        tab.wait_for_timeout(600)
        tab.locator('.export-review-stage').screenshot(path=str(report / 'ink-well-busy.png'))
        moving = tab.evaluate("""async () => {
          const holes = document.querySelector('.export-review-stage .am-ink-well-hole'), a = holes.getAttribute('d');
          await new Promise(r => setTimeout(r, 120));
          return {changed: holes.getAttribute('d') !== a, sleeping: document.querySelector('.export-review-stage').dataset.amSleeping};
        }""")
        assert moving == {'changed': True, 'sleeping': 'false'}, moving
        checks.append('Export build cooks in the ink-well; a few inner bubbles carry the included skins\' diffuse colours')

        # Busy after busy keeps the same well; the result performs in it at once, then settles.
        tab.evaluate("window.inkSvg = document.querySelector('.am-ink-well'); AtelierExportReview.start(inkSnapshot)")
        assert tab.evaluate("document.querySelector('.am-ink-well') === inkSvg")
        assert tab.evaluate("AtelierExportReview.staging('busy')")
        tab.evaluate("AtelierExportReview.finish(inkSnapshot, {ok:true, pak_path:'D:/Fixture/Ink.pak', applied:[], skipped:[]})")
        result = tab.evaluate("""() => ({same: document.querySelector('.am-ink-well') === inkSvg, canvas: !!document.querySelector('.export-review-stage canvas'),
          state: document.querySelector('.export-review-stage').dataset.amState, staging: AtelierExportReview.staging('success')})""")
        assert result == {'same': True, 'canvas': False, 'state': 'success', 'staging': True}, result
        tab.wait_for_function("document.querySelector('.export-review-stage').dataset.amSleeping === 'true'")
        settled = tab.evaluate("""async () => {
          const svg = document.querySelector('.am-ink-well'), d = svg.innerHTML;
          await new Promise(r => setTimeout(r, 250));
          const released = [...document.querySelectorAll('.export-review-stage path.am-ink-well-success')].map(p => (p.getAttribute('d')||'').split('M').length - 1);
          return {still: svg.innerHTML === d, released, view: svg.getAttribute('viewBox')};
        }""")
        # The clean release floats away: the settled well is back in the cooking frame, calm.
        assert settled['still'] and max(settled['released']) >= 10 and settled['view'] == '10 10 236 236', settled
        tab.locator('.export-review-stage').screenshot(path=str(report / 'ink-well-success.png'))
        checks.append('Busy-after-busy keeps the ink-well; the result performs in it immediately, then settles and stops drawing')

        # Closing releases the screen's moment; reopening the last result shows its settled pose.
        tab.keyboard.press('Escape')
        tab.locator('#export-review-overlay').wait_for(state='hidden')

        # Failure breaks into pieces that leak and pool, and success releases a clean burst; both
        # perform once and hold. Warning holds in a tense loop until hidden or reduced.
        outcomes = tab.evaluate("""async () => {
          const results = {};
          for (const name of ['warning', 'error', 'success']) {
            const host = document.createElement('div'); host.style.cssText = 'position:fixed;left:40px;top:120px;z-index:9999';
            document.body.append(host);
            const well = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-outcome'});
            await new Promise(r => setTimeout(r, 300));
            well.setState(name);
            const begun = host.dataset.amState;
            await new Promise(r => setTimeout(r, 2000));
            const count = sel => (host.querySelector(sel)?.getAttribute('d') || '').split('M').length - 1;
            const cls = {success: 'am-ink-well-success', warning: 'am-ink-well-warn', error: 'am-ink-well-fault'}[name];
            const frames = well.frames(); await new Promise(r => setTimeout(r, 200));
            results[name] = {begun, sleeping: host.dataset.amSleeping, stopped: well.frames() === frames,
              over: Math.max(...[...host.querySelectorAll('path.' + cls)].map(p => (p.getAttribute('d')||'').split('M').length - 1)),
              cracks: count('.am-ink-well-hole:last-of-type'), pieces: host.querySelectorAll('svg > use').length,
              bulge: (host.querySelector('svg > path.' + cls + ':last-of-type')?.getAttribute('d') || '').length};
            if (name === 'warning') {
              well.setReducedMotion('reduce');
              const held = well.frames(); await new Promise(r => setTimeout(r, 200));
              results[name].reducedStops = well.frames() === held && host.dataset.amSleeping === 'true';
            }
            well.destroy(); host.remove();
          }
          return results;
        }""")
        assert [outcomes[n]['begun'] for n in ('warning', 'error', 'success')] == ['warning', 'error', 'success'], outcomes
        for name in ('error', 'success'):
            assert outcomes[name]['sleeping'] == 'true' and outcomes[name]['stopped'], outcomes
        assert outcomes['warning']['sleeping'] == 'false' and not outcomes['warning']['stopped'] and outcomes['warning']['reducedStops'], outcomes
        assert outcomes['success']['over'] >= 10 and outcomes['warning']['over'] >= 10 and outcomes['error']['over'] >= 10, outcomes
        assert outcomes['error']['cracks'] >= 7 and outcomes['error']['pieces'] == 7 and outcomes['warning']['cracks'] == 0, outcomes
        assert outcomes['warning']['bulge'] > 200 and outcomes['error']['bulge'] > 200 and outcomes['success']['pieces'] == 0, outcomes
        tab.emulate_media(reduced_motion='reduce')
        reduced = tab.evaluate("""async () => {
          const host = document.createElement('div'); document.body.append(host);
          const well = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-reduced'});
          well.setState('warning');
          const frames = well.frames(); await new Promise(r => setTimeout(r, 250));
          const foam = (host.querySelector('path.am-ink-well-warn:last-of-type')?.getAttribute('d') || '').length;
          const out = {frames: well.frames() - frames, sleeping: host.dataset.amSleeping, foam};
          well.destroy(); host.remove(); return out;
        }""")
        assert reduced['frames'] == 0 and reduced['sleeping'] == 'true' and reduced['foam'] > 200, reduced
        tab.emulate_media(reduced_motion='no-preference')
        checks.append('Ink-well failure breaks and leaks, success bursts and settles calm (both hold still); warning loops until hidden or reduced, which shows its pose without frames')

        # A fixed frame keeps the artboard still through the success, so a label laid over the
        # well stays on it; the released ink spills past the SVG instead. A sparse well keeps a
        # few large bubbles and none of the small ones.
        fixed = tab.evaluate("""async () => {
          const host = document.createElement('div'); host.style.cssText = 'position:fixed;left:40px;top:120px;z-index:9999';
          document.body.append(host);
          const holes = () => (host.querySelector('.am-ink-well-hole')?.getAttribute('d') || '').split('M').length - 1;
          const full = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-dense'});
          await new Promise(r => setTimeout(r, 250));
          const dense = holes(); full.destroy();
          const well = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-fixed', fixedFrame: true, sparse: true});
          await new Promise(r => setTimeout(r, 250));
          const sparse = holes();
          well.setState('success');
          await new Promise(r => setTimeout(r, 400));
          const out = [host.dataset.amSleeping, host.querySelector('svg').getAttribute('viewBox'), sparse <= 12 && dense > 3 * sparse].join();
          well.destroy(); host.remove(); return out;
        }""")
        assert fixed == 'false,10 10 236 236,true', fixed
        checks.append('Ink-well success in a fixed frame performs without moving its artboard; a sparse well keeps only a few large bubbles')

        # Hidden documents and reduced motion stop frames; reduced motion holds one still pose.
        tab.evaluate("""() => {
          window.inkHost = document.createElement('div'); inkHost.style.cssText = 'position:fixed;left:40px;top:120px;z-index:9999';
          document.body.append(inkHost);
          window.inkWell = AtelierMotion.inkWell.mount(inkHost, {size: 160, kind: 'ink-check', palette: ['#c8243a']});
        }""")
        tab.wait_for_function('inkWell.frames() > 3')
        tab.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange'))")
        hidden = tab.evaluate("async () => { const n = inkWell.frames(); await new Promise(r => setTimeout(r, 200)); return [n, inkWell.frames(), inkHost.dataset.amSleeping]; }")
        assert hidden[0] == hidden[1] and hidden[2] == 'true', hidden
        tab.evaluate("Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange'))")
        tab.wait_for_function("inkHost.dataset.amSleeping === 'false'")
        tab.evaluate("inkWell.setReducedMotion('reduce')")
        still = tab.evaluate("async () => { const n = inkWell.frames(); await new Promise(r => setTimeout(r, 200)); return [n, inkWell.frames(), inkHost.dataset.amSleeping, inkHost.dataset.amReduced]; }")
        assert still[0] == still[1] and still[2] == 'true' and still[3] == 'true', still
        assert tab.evaluate("inkHost.querySelector('.am-ink-well-tint').getAttribute('d').length > 20"), 'still pose keeps its colours'
        tab.evaluate('inkWell.destroy(); inkWell.destroy()')
        assert tab.evaluate("inkHost.childNodes.length === 0 && !inkHost.dataset.atelierMotion")
        checks.append('Ink-well stops drawing when hidden or reduced (one still pose, colours kept) and destroys cleanly')
        assert not errors, errors
    finally:
        tab.close()
