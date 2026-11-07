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
          const scripts = ['working-panels', 'workflow-krackle', 'workflow-surfaces', 'texture-reconstruction', 'krackle-context'];
          const styles = ['working-panels', 'workflow-krackle', 'texture-reconstruction', 'folder-flap'];
          return {
            api: [AtelierMotion.working, AtelierMotion.workflow, AtelierMotion.energy, window.AtelierTextureReconstruction].filter(Boolean).length,
            scripts: scripts.filter(name => document.querySelector(`script[src$="/${name}.js"]`)),
            styles: styles.filter(name => document.querySelector(`link[href$="/${name}.css"]`)),
            pigment: getComputedStyle(document.documentElement).getPropertyValue('--krackle-energy').trim(),
          };
        }""")
        assert gone == {'api': 0, 'scripts': [], 'styles': [], 'pigment': ''}, gone
        checks.append('Working panels, workflow gestures, ink transfers, halftone reconstruction, the folder flap and contextual pigments no longer load')

        # A row arriving in the Mod tray fades and rises for 200 ms, and no ink is drawn across the screen.
        arrival = tab.evaluate("""async () => {
          sidebarData = {m: {token: 'm', game_rel: 'Fixture/MI_Fixture', name: 'Material fixture', file_type: 'material', selected: true}};
          renderSidebar();
          AtelierPolish.fly('Fixture/MI_Fixture');
          await new Promise(requestAnimationFrame);
          await new Promise(requestAnimationFrame);
          const row = document.querySelector('.sb-item[data-game-rel="Fixture/MI_Fixture"]');
          const motion = row.getAnimations()[0];
          const frames = motion?.effect.getKeyframes() || [];
          return {duration: motion?.effect.getTiming().duration, first: frames[0]?.opacity, added: document.querySelectorAll('.k-workflow-svg,.k-workflow-link,.k-workflow-canvas').length};
        }""")
        assert arrival['added'] == 0, arrival
        if tab.evaluate('!AtelierMotionPolicy.query().matches'):
            assert arrival['duration'] == 200 and arrival['first'] == '0', arrival
        checks.append('A row arrives in the Mod tray with a plain 200 ms fade and rise')

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
