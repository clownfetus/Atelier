"""Ink-well lifecycle, using the real frontend only. Nothing mounts it now; it goes with Krackle."""

def run_ink_well_checks(context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierMotion?.inkWell && window.atelierProject?.()')
        tab.emulate_media(reduced_motion='no-preference')
        assert tab.evaluate("AtelierMotionPolicy.mode()") == 'full'

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
        checks.append('Ink-well failure breaks and leaks, success bursts and settles calm (both hold still); warning loops until hidden or reduced, which shows its pose without frames')

        # A fixed frame keeps the artboard still through the success, so a label laid over the
        # well stays on it; the released ink spills past the SVG instead. A sparse well keeps a
        # few large bubbles and none of the small ones. Sample actual drawn frames:
        # a delayed timer can observe the correctly completed outcome instead.
        fixed = tab.evaluate("""async () => {
          const host = document.createElement('div'); host.style.cssText = 'position:fixed;left:40px;top:120px;z-index:9999';
          document.body.append(host);
          const state = () => ({sleeping: host.dataset.amSleeping, reduced: host.dataset.amReduced,
            micro: host.dataset.amMicro, motion: AtelierMotionPolicy.mode(), hidden: document.hidden});
          const drawn = (well, count) => new Promise((resolve, reject) => {
            const target = well.frames() + count;
            let raf = 0;
            const timeout = setTimeout(() => {
              cancelAnimationFrame(raf);
              reject(Error('Ink-well stopped before the sampled frame: ' + JSON.stringify(state())));
            }, 5000);
            const sample = () => {
              if (well.frames() >= target) { clearTimeout(timeout); resolve(); }
              else raf = requestAnimationFrame(sample);
            };
            raf = requestAnimationFrame(sample);
          });
          const holes = () => (host.querySelector('.am-ink-well-hole')?.getAttribute('d') || '').split('M').length - 1;
          let full, well;
          try {
            full = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-dense'});
            await drawn(full, 12);
            const dense = holes(); full.destroy();
            well = AtelierMotion.inkWell.mount(host, {size: 160, kind: 'ink-fixed', fixedFrame: true, sparse: true});
            await drawn(well, 12);
            const sparse = holes();
            well.setState('success');
            await drawn(well, 12);
            return {...state(), view: host.querySelector('svg').getAttribute('viewBox'), sparse, dense};
          } finally {
            full?.destroy(); well?.destroy(); host.remove();
          }
        }""")
        assert fixed['sleeping'] == 'false' and fixed['view'] == '10 10 236 236', fixed
        assert fixed['sparse'] <= 12 and fixed['dense'] > 3 * fixed['sparse'], fixed
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

        # Keep the OS override last: Chromium can apply the preference before its
        # media-change callback, leaving the rendered policy stale on a fast reset.
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
        checks.append('OS reduced motion mounts the ink-well in its still warning pose without drawing animation frames')
        assert not errors, errors
    finally:
        tab.close()
