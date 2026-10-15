"""CSS folder motion on real grid cards; all image/navigation requests use local fixtures."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FIXTURES = r"""() => {
  window.folderMotionClicks = [];
  // Use deliberately unclassified names: Maps and Audio now have category symbols.
  window.folderMotionItems = [
    {type:'folder', name:'Miscellaneous', rel_path:'Miscellaneous'},
    {type:'folder', name:'Unsorted Assets', rel_path:'Unsorted Assets'},
    {type:'folder', name:'Characters', rel_path:'Characters'},
    {type:'folder', name:'UI', rel_path:'UI'},
    {type:'folder', name:'Maps', rel_path:'Maps'},
    {type:'folder', name:'Audio', rel_path:'Audio'},
    {type:'folder', name:'1029', label:'Loaded hero portrait', rel_path:'Characters/1029', thumbnail:'/folder-motion/portrait.svg'},
    {type:'folder', name:'1039', label:'Failed hero portrait', rel_path:'Characters/1039', thumbnail:'/folder-motion/missing.svg'},
    {type:'folder', name:'Textures', label:'Failed category portrait', rel_path:'Textures', thumbnail:'/folder-motion/missing.svg'},
    {type:'asset', name:'Fixture material', file_type:'material', game_rel:'Fixture/MI_Body'},
    {type:'asset', name:'Failed edited texture', file_type:'texture', game_rel:'Fixture/Edited', imported:true},
    {type:'asset', name:'Failed original texture', file_type:'texture', game_rel:'Fixture/Original', imported:false}
  ];
  window.renderFolderMotionFixture = () => {
    document.getElementById('search-input').value = '';
    allItems = folderMotionItems;
    buildGrid(folderMotionItems.map(item => {
      const card = _makeCard(item);
      card.onClick = () => folderMotionClicks.push(card.label);
      return card;
    }));
  };
  renderFolderMotionFixture();
}"""


def run_folder_motion_checks(page, context, url, report, checks):
    motion_page = context.new_page()
    errors = []
    motion_page.on('pageerror', lambda error: errors.append(str(error)))
    motion_page.route('**/folder-motion/portrait.svg', lambda route: route.fulfill(
        content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#5487db"/><circle cx="32" cy="24" r="12" fill="#accbff"/></svg>'))
    motion_page.route('**/folder-motion/missing.svg', lambda route: route.fulfill(status=404, body='Fixture missing image'))
    motion_page.route('**/api/thumb?*', lambda route: route.fulfill(status=404, body='Fixture missing texture'))
    motion_page.route('**/api/prefetch_thumbs', lambda route: route.fulfill(json={
        'ok': True, 'failed': ['Fixture/Edited', 'Fixture/Original']}))

    def card(label):
        return motion_page.locator('#grid-area .card').filter(has=motion_page.locator('.card-name', has_text=label))

    def settle():
        motion_page.wait_for_function("!document.querySelector('#grid-area').getAnimations({subtree:true}).length")

    def reset_pose():
        motion_page.evaluate('document.activeElement?.blur()')
        motion_page.mouse.move(1, 1)
        settle()

    def assert_bounds():
        bounds = card('Miscellaneous').evaluate("""el => {
          const thumb=el.querySelector('.card-thumb').getBoundingClientRect();
          const svg=el.querySelector('.am-folder-flap');
          const box=svg.getBoundingClientRect(), painted=svg.getBBox();
          return {thumbWidth:thumb.width, svgWidth:box.width, svgHeight:box.height,
            paintedWidth:painted.width*box.width/svg.viewBox.baseVal.width,
            clipped:[...svg.children].some(part => { const p=part.getBoundingClientRect();
              return p.left < thumb.left-.5 || p.right > thumb.right+.5 || p.top < thumb.top-.5 || p.bottom > thumb.bottom+.5; })};
        }""")
        assert 100 <= bounds['svgWidth'] <= 104 and 100 <= bounds['svgHeight'] <= 104, bounds
        assert abs(bounds['svgWidth'] / bounds['thumbWidth'] - .76) < .01, bounds
        assert bounds['paintedWidth'] >= 88 and not bounds['clipped'], bounds

    try:
        motion_page.goto(url)
        motion_page.wait_for_function("typeof buildGrid === 'function' && window.atelierProject?.()")
        motion_page.wait_for_selector('#grid-area .card')
        motion_page.emulate_media(reduced_motion='no-preference')
        motion_page.evaluate(FIXTURES)
        motion_page.wait_for_selector('.hero-portrait.loaded')
        motion_page.wait_for_function("document.querySelectorAll('#grid-area [data-atelier-motion=folder-flap]').length === 3")
        for label in ('Miscellaneous', 'Unsorted Assets', 'Failed hero portrait'):
            assert card(label).get_attribute('data-atelier-motion') == 'folder-flap'
            assert card(label).locator('.card-thumb > svg.am-folder-flap').count() == 1
            assert card(label).locator('svg').get_attribute('aria-hidden') == 'true'
            assert card(label).locator('svg').get_attribute('focusable') == 'false'
        for label in ('Characters', 'UI', 'Maps', 'Audio', 'Loaded hero portrait', 'Failed category portrait',
                      'Fixture material', 'Failed edited texture', 'Failed original texture'):
            assert card(label).get_attribute('data-atelier-motion') is None, label
            assert card(label).locator('.am-folder-flap').count() == 0, label
        for label in ('Failed category portrait', 'Failed edited texture', 'Failed original texture'):
            card(label).locator('svg.card-icon').wait_for()
        assert card('Loaded hero portrait').locator('.hero-portrait.loaded').count() == 1
        assert motion_page.evaluate("folderMotionItems.find(item=>item.label==='Failed hero portrait').thumbnail")
        checks.append('Folder motion applies only to generic visible folders, including failed hero portraits; category and asset fallbacks stay unchanged')

        reset_pose()
        front = card('Miscellaneous').locator('.am-folder-flap-front')
        assert front.evaluate('el=>getComputedStyle(el).transform') == 'none'
        card('Miscellaneous').hover()
        settle()
        opened = front.evaluate('el=>getComputedStyle(el).transform')
        assert opened != 'none'
        card('Miscellaneous').click()
        assert motion_page.evaluate('folderMotionClicks') == ['Miscellaneous']
        motion_page.mouse.move(1, 1)
        motion_page.keyboard.press('Tab')
        card('Miscellaneous').focus()
        settle()
        assert card('Miscellaneous').evaluate('el=>el.matches(":focus-visible")')
        assert front.evaluate('el=>getComputedStyle(el).transform') == opened
        assert card('Miscellaneous').evaluate('el=>parseFloat(getComputedStyle(el).outlineWidth)') >= 2
        card('Miscellaneous').press('Enter')
        card('Miscellaneous').press('Space')
        assert motion_page.evaluate('folderMotionClicks') == ['Miscellaneous', 'Miscellaneous', 'Miscellaneous']
        card('Miscellaneous').press('Tab')
        settle()
        assert front.evaluate('el=>getComputedStyle(el).transform') == 'none'
        # The actual _makeCard handler still follows the native button click into the same folder.
        motion_page.route('**/api/browse?*', lambda route: route.fulfill(json=[]))
        motion_page.evaluate("buildGrid([_makeCard({type:'folder',name:'Navigation fixture',rel_path:'FolderMotion/Native'})])")
        card('Navigation fixture').press('Enter')
        # Loading uses #empty-state too: wait for the response's completed render before
        # installing manual fixtures, otherwise a late browse response replaces them.
        motion_page.wait_for_function("""nav.path === 'FolderMotion/Native' &&
          document.getElementById('library-count').textContent === '0 items' &&
          document.getElementById('empty-state')?.textContent.includes('Empty folder')""")
        motion_page.evaluate('renderFolderMotionFixture()')
        checks.append('Folder flap responds to pointer and retained keyboard focus without changing native click/Enter/Space navigation or focus outlines')

        for preference in ('system', 'forced'):
            reset_pose()
            if preference == 'system':
                motion_page.emulate_media(reduced_motion='reduce')
            else:
                motion_page.evaluate("document.documentElement.dataset.reducedMotion='reduce'")
            card('Miscellaneous').hover()
            assert card('Miscellaneous').locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transitionDuration') == '0s'
            assert card('Miscellaneous').locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transform') != 'none'
            assert card('Miscellaneous').locator('.am-folder-flap').evaluate('el=>el.getAnimations({subtree:true}).length') == 0
            motion_page.mouse.move(1, 1)
            assert card('Miscellaneous').locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transform') == 'none'
            if preference == 'system':
                motion_page.emulate_media(reduced_motion='no-preference')
            else:
                motion_page.evaluate('delete document.documentElement.dataset.reducedMotion')

        # A separate touch context tests CSS media gating without launching another application instance.
        touch_context = context.browser.new_context(has_touch=True, viewport={'width': 800, 'height': 600})
        try:
            touch_page = touch_context.new_page()
            markup = card('Miscellaneous').evaluate('el=>el.outerHTML')
            css = '\n'.join((ROOT / path).read_text(encoding='utf-8') for path in
                            ('gui/tokens.css', 'gui/style.css', 'gui/motion/folder-flap.css'))
            touch_page.set_content(f'<html><head><style>{css}</style></head><body>{markup}</body></html>')
            assert touch_page.evaluate("matchMedia('(pointer: coarse)').matches")
            touch_page.locator('.card').hover()
            assert touch_page.locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transform') == 'none'
            touch_page.keyboard.press('Tab')
            touch_page.locator('.card').focus()
            touch_page.wait_for_function("!document.querySelector('.card').getAnimations({subtree:true}).length")
            assert touch_page.locator('.card').evaluate('el=>el.matches(":focus-visible")')
            assert touch_page.locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transform') != 'none'
        finally:
            touch_context.close()
        checks.append('OS/forced reduced motion retains static poses; coarse pointers avoid sticky hover while keyboard focus still opens folders')

        for width, height in ((1024, 900), (1400, 900)):
            motion_page.set_viewport_size({'width': width, 'height': height})
            for theme in ('light', 'dark'):
                motion_page.locator('#settings-theme').select_option(theme, force=True)
                reset_pose()
                assert_bounds()
                category_width = card('Characters').locator('svg.card-icon').bounding_box()['width']
                assert 100 <= category_width <= 104, category_width
                card('Miscellaneous').hover()
                settle()
                assert_bounds()
                motion_page.screenshot(path=str(report / f'folder-flap-{theme}-{width}.png'), animations='disabled')
        checks.append('Folder artwork fills the existing ~102px slot without clipping or shrinking category glyphs in both desktop themes')

        reset_pose()
        card('Miscellaneous').hover()
        motion_page.evaluate("""() => {
          window.oldFolderCard=[...document.querySelectorAll('#grid-area .card')].find(el=>el.querySelector('.card-name').textContent==='Miscellaneous');
          window.oldFolderEffects=oldFolderCard.getAnimations({subtree:true});
          renderFolderMotionFixture();
        }""")
        motion_page.wait_for_function('!oldFolderCard.isConnected && oldFolderEffects.every(a=>a.playState==="idle")')
        motion_page.wait_for_function("document.querySelectorAll('#grid-area [data-atelier-motion=folder-flap]').length === 3")
        assert card('Miscellaneous').locator('.am-folder-flap').count() == 1
        for _ in range(3):
            card('Miscellaneous').hover()
            motion_page.mouse.move(1, 1)
        settle()
        assert card('Miscellaneous').locator('.am-folder-flap-front').evaluate('el=>getComputedStyle(el).transform') == 'none'
        assert card('Miscellaneous').evaluate('el=>el.getAnimations({subtree:true}).length') == 0
        checks.append('Rapid hover reversals and grid rebuilds settle cleanly without duplicated artwork or surviving transitions')
        assert not errors, errors
    finally:
        motion_page.close()
