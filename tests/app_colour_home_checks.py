"""Home card-size consistency and the saved Heroes startup preference in Chromium."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from app_colour_identity_checks import IMAGES, boot, heroes_fixture, nav, png


def run(browser, args, report, errors, mode, custom):
    heroes = heroes_fixture()

    def artwork(route):
        path = urlparse(route.request.url).path
        if path == '/api/catalogue/library':
            route.fulfill(json={'heroes': heroes})
        elif path == '/api/catalogue/status':
            route.fulfill(json={'updating': False})
        elif path in IMAGES:
            route.fulfill(body=IMAGES[path], content_type='image/png')
        else:
            route.fulfill(status=404)

    context, page = boot(browser, args.base_url, errors, mode, custom, artwork)
    label = ('custom-' if custom else '') + mode
    try:
        folders = [dict(type='folder', name='Folder '+str(i), label='Folder '+str(i),
                        rel_path='Folder '+str(i), count=2) for i in range(12)]
        assets = [dict(type='file', file_type=kind, name=name, game_rel='Fixture/'+name,
                       rel_path='Fixture/'+name) for kind, name in [('mesh', 'SM_MediaPlate'), ('texture', 'T_MediaPlate')]]

        def browse(route):
            path = parse_qs(urlparse(route.request.url).query).get('path', [''])[0]
            route.fulfill(json=folders + assets if not path else folders[:2])

        page.route('**/api/browse?*', browse)
        page.route('**/api/thumb?*', lambda route: route.fulfill(body=png('#777777'), content_type='image/png'))
        page.route('**/api/prefetch_thumbs', lambda route: route.fulfill(json={'ok': True, 'ready': [], 'pending': []}))
        page.route('**/api/thumb_status', lambda route: route.fulfill(json={'ok': True, 'ready': [], 'pending': []}))
        page.reload()
        toggle = page.get_by_role('button', name='Heroes', exact=True)
        page.wait_for_selector('#grid-area .card')
        assert toggle.get_attribute('aria-expanded') == 'true'
        assert page.locator('#settings-home-heroes').is_checked()
        assert page.locator('#grid-area .card').count() == 10  # Eight folders and both assets.
        more = page.locator('.home-category-more')
        assert more.inner_text() == '+4 more folders'
        more.click()
        assert page.locator('#grid-area .card').count() == 14
        toggle.click()
        assert page.locator('.roster-content').is_hidden()
        closed_space = page.locator('#grid-area').evaluate('el=>el.clientHeight')

        for width, height in [(1024, 768), (1400, 900)]:
            page.set_viewport_size({'width': width, 'height': height})
            for size in [128, 156, 196, 236]:
                page.locator('#library-size').select_option(str(size))
                boxes = page.locator('#grid-area .card').evaluate_all("""nodes=>nodes.map(el=>{
                  const card=el.getBoundingClientRect(),thumb=el.querySelector('.card-thumb').getBoundingClientRect();
                  return {width:card.width,height:card.height,thumbWidth:thumb.width,thumbHeight:thumb.height};
                })""")
                assert len(boxes) == 14
                assert all(abs(box['width'] - size) < 1 for box in boxes), (label, size, boxes)
                assert max(box['height'] for box in boxes) - min(box['height'] for box in boxes) < 1, boxes
                assert all(abs(box['thumbWidth'] - box['thumbHeight']) < 1 and box['thumbHeight'] > 60 for box in boxes), boxes
                assert page.evaluate('document.documentElement.scrollWidth===innerWidth')
                if size == 128:
                    page.screenshot(path=str(report / f'home-collapsed-{label}-{width}.png'), animations='disabled')

        nav(page, 'Fixture folder')
        nav(page, '')
        assert toggle.get_attribute('aria-expanded') == 'false'
        page.reload()
        page.wait_for_selector('.roster-portrait')
        assert toggle.get_attribute('aria-expanded') == 'true'  # Manual collapse does not change the startup choice.
        assert page.locator('#grid-area').evaluate('el=>el.clientHeight') < closed_space

        page.evaluate('openPaths()')
        setting = page.get_by_role('checkbox', name='Open Heroes on Home by default', exact=True)
        setting.uncheck()
        page.locator('#setup-cancel').click()
        assert page.evaluate("localStorage.getItem('atelier.homeHeroesOpen')") == '0'
        assert toggle.get_attribute('aria-expanded') == 'false'
        page.reload()
        page.wait_for_selector('#grid-area .card')
        assert toggle.get_attribute('aria-expanded') == 'false'
        assert not page.locator('#settings-home-heroes').is_checked()
        toggle.focus()
        page.keyboard.press('Enter')
        assert toggle.get_attribute('aria-expanded') == 'true'
        assert page.evaluate("localStorage.getItem('atelier.homeHeroesOpen')") == '0'
        page.reload()
        page.wait_for_selector('#grid-area .card')
        assert toggle.get_attribute('aria-expanded') == 'false'

        other = context.new_page()
        other.goto(args.base_url + '/static/roster.css')
        other.evaluate("localStorage.setItem('atelier.homeHeroesOpen','1')")
        page.wait_for_function("document.querySelector('.roster-toggle').getAttribute('aria-expanded')==='true'")
        assert page.locator('#settings-home-heroes').is_checked()
        other.evaluate("localStorage.setItem('atelier.homeHeroesOpen','0')")
        page.wait_for_function("document.querySelector('.roster-toggle').getAttribute('aria-expanded')==='false'")
        other.close()

        page.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': []}))
        page.reload()
        page.wait_for_selector('#grid-area .card')
        assert toggle.get_attribute('aria-expanded') == 'false'
        toggle.click()
        assert page.get_by_text('Catalogue unavailable', exact=True).is_visible()
        if label == 'dark':
            page.add_init_script("""(()=>{
              const get=Storage.prototype.getItem,set=Storage.prototype.setItem;
              Storage.prototype.getItem=function(key){if(key==='atelier.homeHeroesOpen')throw new DOMException('Blocked','SecurityError');return get.call(this,key);};
              Storage.prototype.setItem=function(key,value){if(key==='atelier.homeHeroesOpen')throw new DOMException('Blocked','SecurityError');return set.call(this,key,value);};
            })();""")
            page.reload()
            page.wait_for_selector('#grid-area .card')
            assert toggle.get_attribute('aria-expanded') == 'true'
            page.evaluate("()=>{const el=document.getElementById('settings-home-heroes');el.checked=false;el.dispatchEvent(new Event('change'));}")
            assert toggle.get_attribute('aria-expanded') == 'false'
        return {'palette': label, 'check': 'Folders and assets share all four card sizes at both desktop widths; the Heroes preference persists, keyboard expansion works, tabs synchronize, and missing catalogue/storage remain usable'}
    except Exception:
        page.screenshot(path=str(report / f'failure-{label}.png'), animations='disabled')
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in ['127.0.0.1', 'localhost']
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for custom in [False, True]:
                    for mode in ['dark', 'light']:
                        checks.append(run(browser, args, report, errors, mode, custom))
            finally:
                browser.close()
        assert not errors, errors
    finally:
        (report/'results.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, indent=2), encoding='utf-8')
    for check in checks:
        print('PASS '+check['palette']+': '+check['check'])


if __name__ == '__main__':
    main()
