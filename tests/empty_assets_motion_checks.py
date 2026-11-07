"""The Mod tray's empty state: a still glyph, only for a project confirmed empty. API results are fixtures."""

GLYPH = '#sidebar-list .sidebar-empty > .empty-state-glyph'
STILL = """async selector => {
  const svg = document.querySelector(selector + ' svg'), first = svg.innerHTML;
  for (let i = 0; i < 10; i++) {
    await new Promise(resolve => setTimeout(resolve, 50));
    if (svg.innerHTML !== first || svg.getAnimations().length) return false;
  }
  return true;
}"""


def run_empty_assets_motion_checks(page, context, url, report, checks):
    empty_page = context.new_page()
    errors = []
    empty_page.on('pageerror', lambda error: errors.append(str(error)))
    fixture = {'data': [], 'fail': False}
    empty_page.route('**/api/imported', lambda route: route.fulfill(
        status=500 if fixture['fail'] else 200,
        json={'ok': False, 'error': 'Fixture imported read failure'} if fixture['fail'] else fixture['data']))
    glyphs = empty_page.locator(GLYPH)
    try:
        empty_page.goto(url)
        empty_page.wait_for_function('window.AtelierEmptyAssetsUI && window.AtelierEmptyGlyph && window.atelierProject?.()')
        empty_page.wait_for_selector('#grid-area .card')
        empty_page.emulate_media(reduced_motion='no-preference')
        empty_page.evaluate("() => { _applyActiveProject('Empty motion Alpha'); sidebarData={}; renderSidebar(); }")
        assert glyphs.count() == 0
        empty_page.evaluate('loadSidebar()')
        empty_page.wait_for_selector(GLYPH)
        assert glyphs.get_attribute('data-glyph-state') == 'info'
        assert glyphs.get_attribute('data-glyph-tier') == 'inline'
        assert glyphs.get_attribute('aria-hidden') == 'true'
        assert empty_page.evaluate(STILL, GLYPH)
        empty_page.evaluate('renderSidebar(); renderSidebar()')
        assert glyphs.count() == 1
        assert empty_page.evaluate(STILL, GLYPH)
        checks.append('A confirmed empty project shows the three pieces at rest, and they stay still through repeat renders')

        fixture['data'] = [{'token': 'empty-fixture', 'name': 'MI_Fixture', 'game_rel': 'Fixture/MI_Fixture',
                            'file_type': 'material', 'selected': True}]
        empty_page.evaluate('loadSidebar()')
        assert empty_page.locator('#sidebar-list .sb-item').count() == 1
        assert glyphs.count() == 0
        empty_page.locator('#search-scope').click()
        empty_page.locator('#search-input').fill('unmatched-asset')
        assert 'No Mod tray assets match the search.' in empty_page.locator('#sidebar-list').inner_text()
        assert empty_page.locator('#sidebar-list .empty-state-glyph').count() == 0
        empty_page.locator('#search-input').fill('')
        fixture['data'] = []
        empty_page.evaluate('loadSidebar()')
        assert glyphs.count() == 1
        empty_page.evaluate("_applyActiveProject('Empty motion Beta'); sidebarData={}; renderSidebar()")
        assert glyphs.count() == 0
        empty_page.evaluate('loadSidebar()')
        assert glyphs.count() == 1
        fixture['fail'] = True
        empty_page.evaluate('async()=>{try{await loadSidebar();}catch{} renderSidebar();}')
        assert glyphs.count() == 0
        fixture['fail'] = False
        empty_page.evaluate('loadSidebar()')
        assert glyphs.count() == 1
        checks.append('Only a genuinely empty project gets the glyph: filtered results, pending switches and failed reads do not')

        empty_page.set_viewport_size({'width': 1400, 'height': 900})
        for theme in ('dark', 'light'):
            empty_page.locator('#settings-theme').select_option(theme, force=True)
            box = glyphs.bounding_box()
            assert box['width'] == 130 and box['height'] == 64
            assert empty_page.locator('.sidebar-empty > svg').is_hidden()
            halo, surface = empty_page.evaluate("""selector => [
              getComputedStyle(document.querySelector(selector)).getPropertyValue('--glyph-halo').trim(),
              getComputedStyle(document.documentElement).getPropertyValue('--bg2').trim()]""", GLYPH)
            assert halo == surface, (theme, halo, surface)
            assert empty_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert empty_page.locator('#install-btn').is_visible()
            assert empty_page.evaluate(STILL, GLYPH)
            empty_page.screenshot(path=str(report / f'empty-assets-{theme}.png'), animations='disabled')
        checks.append("The glyph keeps its size and the tray's halo in both themes, and a theme change doesn't move it")

        empty_page.evaluate("""() => {
          const original = AtelierMotion.glyph;
          AtelierMotion.glyph = {...original, mount() { throw Error('Fixture mount failure'); }};
          renderSidebar();
          AtelierMotion.glyph = original;
          if (document.querySelector('#sidebar-list .empty-state-glyph')) throw Error('Failed mount left a host');
          const fallback = document.querySelector('.sidebar-empty > svg');
          if (!fallback || getComputedStyle(fallback).display === 'none') throw Error('Fallback not restored');
          renderSidebar();
        }""")
        assert glyphs.count() == 1
        empty_page.evaluate('AtelierEmptyAssetsUI.dispose()')
        assert glyphs.count() == 0
        assert empty_page.locator('.sidebar-empty > svg').is_visible()
        assert not errors, errors
        checks.append("The icon comes back when the glyph can't mount or leaves, with no stray host")
    finally:
        empty_page.close()
