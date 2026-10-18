"""Home sections stay separated with a full roster, Continue ribbon and every card size."""
from io import BytesIO
import time
from PIL import Image


def run_home_layout_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors = []
    tab.on('pageerror', lambda error: errors.append(error.stack or str(error)))
    raw = BytesIO()
    Image.new('RGB', (136, 136), '#7854a2').save(raw, 'PNG')
    art = '/fixture/home-card.png'
    names = ['Adam Warlock', 'Black Widow', 'Cloak & Dagger', 'Doctor Strange',
             'Gorr The God Butcher', 'Human Torch']
    heroes = [{'name': names[i % len(names)], 'path': f'Characters/{1000+i}',
               'avatar': art, 'skins': [
                   {'name': f'Costume {j} with a longer name',
                    'path': f'Characters/{1000+i}/{1000+i}{j:03}', 'icon': art}
                   for j in range(12)]} for i in range(54)]
    imported = [{'token': 'home-layout', 'name': 'T_Painted', 'file_type': 'texture',
                 'game_rel': 'Characters/1000/1000000/Textures/T_Painted',
                 'char_id': '1000', 'skin_id': '1000000', 'char_name': names[0],
                 'skin_name': 'Costume 0', 'selected': True, 'modified': time.time()}]
    tab.route('**/fixture/home-card.png', lambda route: route.fulfill(body=raw.getvalue(), content_type='image/png'))
    tab.route('**/api/catalogue/hero/**', lambda route: route.fulfill(body=raw.getvalue(), content_type='image/png'))
    tab.route('**/api/preview?*', lambda route: route.fulfill(body=raw.getvalue(), content_type='image/png'))
    tab.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': heroes}))
    tab.route('**/api/imported', lambda route: route.fulfill(json=imported))
    try:
        tab.goto(url)
        tab.wait_for_function("document.querySelectorAll('.roster-portrait').length===54 && window.atelierProject?.()")
        tab.wait_for_selector('#continue-ribbon:not([hidden])')
        for theme in ('light', 'dark'):
            tab.evaluate("theme=>document.documentElement.dataset.theme=theme", theme)
            for width, height in ((1400, 900), (1024, 768), (900, 600)):
                tab.set_viewport_size({'width': width, 'height': height})
                for size in ('128', '156', '196', '236'):
                    tab.locator('#library-size').select_option(size)
                    result = tab.evaluate("""() => {
                        const track=document.querySelector('.roster-strip'), pane=document.getElementById('explorer');
                        track.scrollTop=0;pane.scrollTop=0;
                        const rect=selector=>document.querySelector(selector).getBoundingClientRect();
                        const heroes=rect('.roster-strip'), costumes=rect('.roster-carousel'),
                          categories=rect('#grid-area'), roster=rect('#hero-roster');
                        const firstRow=[...track.children].filter(el=>Math.abs(el.getBoundingClientRect().top-track.firstElementChild.getBoundingClientRect().top)<2);
                        return {separate:heroes.bottom<=costumes.top+1 && costumes.bottom<=roster.bottom+1 && roster.bottom<=categories.top+1,
                          fullRow:firstRow.every(el=>el.getBoundingClientRect().bottom<=heroes.bottom+1),
                          scrolls:track.scrollHeight>track.clientHeight,
                          width:document.documentElement.scrollWidth<=innerWidth,
                          detail:{trackHeight:heroes.height,cardHeights:firstRow.map(el=>el.getBoundingClientRect().height)}};
                    }""")
                    if not all(result.values()):
                        tab.screenshot(path=str(report / 'home-layout-failure.png'))
                    assert all(result.values()), (theme, width, height, size, result)
                tab.locator('.roster-skin').first.scroll_into_view_if_needed()
                assert tab.locator('.roster-skin').first.is_visible()
                tab.locator('#grid-area .card').first.scroll_into_view_if_needed()
                assert tab.locator('#grid-area .card').first.is_visible()
                tab.screenshot(path=str(report / f'home-layout-{theme}-{width}.png'))
        tab.locator('.roster-toggle').click()
        assert tab.locator('.roster-content').is_hidden()
        assert not errors, errors
        checks.append('A full 54-hero Home keeps complete portrait rows, costumes and categories separated at all four card sizes in both themes; short windows scroll and Heroes still collapses')
    finally:
        tab.close()
