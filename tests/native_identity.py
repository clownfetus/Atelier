"""Read-only browser audit of real game ID folders and cached catalogue artwork."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import threading
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UI = 'UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    os.environ['ATELIER_DATA_DIR'] = str(args.data_dir.resolve())
    report = args.report_dir.resolve(); report.mkdir(parents=True, exist_ok=False)
    from atelier import config, index, catalogue as module
    from atelier.identity import resolve_ids
    from atelier.web import routes as R, browse
    from atelier.web.app import _ThreadingWSGIServer
    from playwright.sync_api import sync_playwright
    Path(config.PROJECTS_ROOT, 'Identity QA').mkdir(parents=True, exist_ok=True)
    config.set_active_project('Identity QA')
    module.catalogue.start_update = lambda: None
    module.fetch = lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('Offline audit'))
    R._get_latest_usmap_from_github = lambda: None
    browse._fetch_attempted = True
    catalogue = module.catalogue
    items = browse.browse_dispatch(UI)
    skins = [item for item in items if re.fullmatch(r'\d{7}', item['name'])]
    assert len(items) == 64 and len(skins) == 63
    assert all(item.get('display_name') and item['display_name'] != item['name'] and item.get('char_name') for item in skins)
    folders = set()
    for path, *_ in index.ensure_index():
        parts = path.split('/')[:-1]
        for offset, part in enumerate(parts):
            if re.search('[0-9]{4}', part): folders.add('/'.join(parts[:offset+1]))
    entries = catalogue.data.get('entries', {})
    contexts = {path: resolve_ids(path, entries) for path in sorted(folders)}
    contexts = {path: identity for path, identity in contexts.items() if identity}
    class Quiet(WSGIRequestHandler):
        def log_message(self, *_args): pass
    server = make_server('127.0.0.1', 0, R.app, _ThreadingWSGIServer, Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1400,'height':900})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/update_check', lambda route: route.fulfill(json={'available':False}))
            page.route('**/api/download_usmap', lambda route: route.fulfill(json={'ok':True}))
            page.route('**/api/usmap_update_check', lambda route: route.fulfill(json={'ok':True}))
            page.goto(url)
            page.wait_for_function('window.atelierProject?.()&&AtelierCatalogueArt.describe("'+UI+'/1014502")?.skin')
            actual = page.evaluate('paths=>paths.map(path=>AtelierCatalogueArt.resolveIds(path))', list(contexts))
            mismatches = [path for (path, expected), found in zip(contexts.items(), actual) if expected != found]
            assert not mismatches, mismatches[:10]
            page.evaluate('path=>pushNav({path})', UI)
            page.wait_for_function('path=>nav.path===path&&_gridStatus==="ready"', arg=UI)
            assert page.locator('#grid-area button.card').count() == 64
            for card in page.locator('#grid-area .artwork-card').all():
                card.scroll_into_view_if_needed()
            page.locator('#grid-area').evaluate('element=>element.scrollTop=0')
            sizes = page.locator('#library-size option').evaluate_all('options=>options.map(option=>option.value)')
            for width, height in ((1400,900),(1024,768)):
                page.set_viewport_size({'width':width,'height':height})
                size = '156' if width == 1400 else min(sizes, key=lambda value:int(value))
                page.locator('#library-size').select_option(size)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(report/f'battlecustom-{width}.png'), animations='disabled')
            loaded = page.locator('.hero-portrait.loaded').count()
            assert not errors, errors
            result = {'ok': True, 'skin_folders': len(skins), 'common_folders': 1,
                      'game_folder_contexts': len(contexts), 'browser_python_mismatches': mismatches,
                      'loaded_portraits': loaded, 'page_errors': errors,
                      'skins': [{'id': item['name'], 'character':item['char_name'], 'skin':item['display_name']} for item in skins]}
            (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps({key:value for key,value in result.items() if key!='skins'}),flush=True)
            browser.close()
    finally:
        server.shutdown(); server.server_close(); R.shutdown(5)


if __name__ == '__main__': main()
