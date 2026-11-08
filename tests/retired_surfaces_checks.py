"""The surfaces motion v2 retired stay gone, and what replaced them is plain."""


def run_retired_surfaces_checks(context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierPolish && window.AtelierMotion?.glyph && window.atelierProject?.()')
        tab.wait_for_selector('#grid-area .card')

        gone = tab.evaluate("""() => {
          const scripts = ['working-panels', 'workflow-surfaces', 'texture-reconstruction'];
          const styles = ['working-panels', 'texture-reconstruction', 'folder-flap'];
          return {
            api: [AtelierMotion.working, AtelierMotion.workflow, AtelierMotion.energy, window.AtelierTextureReconstruction].filter(Boolean).length,
            scripts: scripts.filter(name => document.querySelector(`script[src$="/${name}.js"]`)),
            styles: styles.filter(name => document.querySelector(`link[href$="/${name}.css"]`)),
            lattice: [getComputedStyle(document.documentElement).getPropertyValue('--screen-dot').trim(),
              [...document.styleSheets].flatMap(sheet => { try { return [...sheet.cssRules]; } catch (_) { return []; } }).some(rule => rule.selectorText?.includes('.k-screen'))],
          };
        }""")
        assert gone == {'api': 0, 'scripts': [], 'styles': [], 'lattice': ['', False]}, gone
        checks.append('Working panels, workflow gestures, ink transfers, halftone reconstruction, the folder flap, contextual pigments and the dot lattice no longer load')

        # A row arriving in the Mod tray clicks in like a glyph piece (P4b.6): the slot opens, the thumbnail
        # travels in, snaps 3 px past its well and settles, and the text wipes in. A re-save only re-seats.
        # Nothing fades, and no ink is drawn across the screen.
        arrival = tab.evaluate("""async () => {
          sidebarData = {m: {token: 'm', game_rel: 'Fixture/MI_Fixture', name: 'Material fixture', file_type: 'material', selected: true}};
          const take = async () => {
            renderSidebar();
            AtelierPolish.fly('Fixture/MI_Fixture');
            await new Promise(requestAnimationFrame);
            await new Promise(requestAnimationFrame);
            const row = document.querySelector('.sb-item[data-game-rel="Fixture/MI_Fixture"]');
            const all = row.getAnimations({subtree: true}), thumb = row.querySelector('.sb-thumb').getAnimations()[0];
            const frames = thumb?.effect.getKeyframes() || [];
            const out = {count: all.length, duration: thumb?.effect.getTiming().duration,
              opacity: all.some(a => a.effect.getKeyframes().some(f => 'opacity' in f)),
              moves: frames.map(f => f.transform), slot: row.getAnimations().some(a => a.effect.getKeyframes().some(f => f.height === '0px')),
              wipes: all.filter(a => a.effect.getKeyframes().some(f => f.clipPath)).length};
            all.forEach(a => a.finish()); await new Promise(requestAnimationFrame);
            out.overflow = row.style.overflow; return out;
          };
          const fresh = await take();
          sidebarData.m = {...sidebarData.m, name: 'Material fixture, saved again'};
          const again = await take();
          return {fresh, again, added: document.querySelectorAll('.k-workflow-svg,.k-workflow-link,.k-workflow-canvas').length};
        }""")
        assert arrival['added'] == 0, arrival
        if tab.evaluate('!AtelierMotionPolicy.query().matches'):
            fresh, again = arrival['fresh'], arrival['again']
            assert not fresh['opacity'] and not again['opacity'], arrival
            assert fresh['duration'] == 830 and fresh['slot'] and fresh['wipes'] == 3, arrival
            assert fresh['moves'][:2] == ['translateX(-120px)', 'translateX(-12px)'] and 'translateX(3px)' in fresh['moves'], arrival
            assert again['duration'] == 380 and not again['slot'] and again['wipes'] == 0 and again['moves'][0] == 'none', arrival
            assert fresh['overflow'] == '' and again['overflow'] == '', arrival
        checks.append('A row arriving in the Mod tray clicks in like a glyph piece and a re-save re-seats, with no fade')

        # A changed texture fades over the old one and leaves nothing behind.
        swap = tab.evaluate("""async () => {
          const pixel = colour => {
            const canvas = document.createElement('canvas'); canvas.width = canvas.height = 8;
            const paint = canvas.getContext('2d'); paint.fillStyle = colour; paint.fillRect(0, 0, 8, 8);
            return canvas.toDataURL();
          };
          const box = document.createElement('div'); box.style.cssText = 'position:fixed;left:0;top:0;width:40px;height:40px;z-index:9999';
          const image = document.createElement('img'); image.dataset.token = 'fixture'; image.src = pixel('#112233');
          box.append(image); document.body.append(box);
          await image.decode();
          AtelierPolish.swapImage(image, pixel('#445566'));
          const during = box.querySelectorAll('.image-swap').length;
          const copy = box.querySelector('.image-swap');
          const carriesData = !!copy && [...copy.attributes].some(attribute => attribute.name.startsWith('data-'));
          await new Promise(resolve => setTimeout(resolve, 400));
          const after = box.querySelectorAll('.image-swap').length, source = image.src;
          box.remove();
          return {during, carriesData, after, swapped: source === pixel('#445566')};
        }""")
        assert swap['swapped'] and swap['after'] == 0 and not swap['carriesData'], swap
        checks.append('A changed texture cross-fades and leaves no copy of itself behind')

        # The selection count is the number alone, with no bubble beside it.
        bubble = tab.evaluate("getComputedStyle(document.getElementById('sel-count'), '::before').content")
        assert bubble in ('none', 'normal'), bubble
        checks.append('The selection count is the number alone')

        # The edited corner is a plain triangle, with no bubbles cut into it.
        corners = tab.evaluate("""() => ['sb-item', 'card imported'].map(cls => {
          const el = document.createElement('div'); el.className = cls; el.style.position = 'relative'; document.body.append(el);
          const after = getComputedStyle(el, '::after'), result = {mask: after.maskImage || after.webkitMaskImage || 'none', clip: after.clipPath};
          el.remove(); return result;
        })""")
        assert all(c['mask'] == 'none' and c['clip'].startswith('polygon') for c in corners), corners
        checks.append('The edited corner is a plain triangle with no bubbles')

        # The plain folder stands still.
        folder = tab.evaluate("""() => {
          const card = document.createElement('button'); card.className = 'card'; card.type = 'button';
          const icon = renderCardIcon({type: 'folder', iconCls: 'folder-icon'}, card);
          card.append(icon); document.body.append(card);
          const result = {motion: card.dataset.atelierMotion || '', pieces: icon.querySelectorAll('g').length, colour: getComputedStyle(icon).color, tag: icon.tagName.toLowerCase()};
          card.remove();
          return result;
        }""")
        assert folder['motion'] == '' and folder['pieces'] == 0 and folder['tag'] == 'svg' and folder['colour'], folder
        checks.append('The plain folder is a still icon in its category colour')
        assert not errors, errors
    finally:
        tab.close()
