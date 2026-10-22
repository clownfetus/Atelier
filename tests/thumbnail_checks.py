"""Browser regressions for cached, queued, failed and abandoned thumbnail requests."""
from urllib.parse import parse_qs, urlparse


IMAGE = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><rect width="128" height="128" fill="#60baba"/><circle cx="64" cy="64" r="36" fill="#143c54"/></svg>'
ITEMS = [dict(type='asset', file_type='texture', game_rel=f'ThumbFixture/T_{suffix}',
              name=f'T_{suffix}', imported=suffix == 'D') for suffix in ('D', 'N', 'ORM')]


def run_thumbnail_checks(page, context, url, report, checks):
    tab = context.new_page()
    errors, requests, held = [], [], []
    state = {'mode': 'cached', 'reads': 0, 'statuses': 0}
    tab.on('pageerror', lambda error: errors.append(str(error)))

    def image(route):
        query = parse_qs(urlparse(route.request.url).query)
        game_rel = query.get('game_rel', [''])[0]
        if not game_rel.startswith('ThumbFixture/') and game_rel != skin_path:
            route.fallback()
            return
        state['reads'] += 1
        requests.append(('image', query))
        mode = state['mode']
        if mode == 'hung' or (mode == 'slow' and '_t' in query):
            held.append(route)
        elif mode in ('failed', 'queued', 'slow'):
            route.fulfill(status=404, body='Preview fixture not cached yet')
        else:
            route.fulfill(content_type='image/svg+xml', body=IMAGE)

    def status(route):
        body = route.request.post_data_json
        names = body['game_rels']
        requests.append(('status' if '/thumb_status' in route.request.url else 'prefetch', body))
        mode = state['mode']
        result = {'ok': True, 'cached': [], 'pending': [], 'failed': [], 'missing': []}
        if '/thumb_status' in route.request.url:
            state['statuses'] += 1
            if mode == 'queued':
                state['mode'] = 'cached'  # Job completes without a thumb_ready event.
                mode = 'cached'
        if mode == 'failed':
            result.update(failed=names, errors={name: 'Fixture decode failed <script>unsafe</script>' for name in names})
        elif mode in ('queued', 'hung'):
            result['pending'] = names
        else:
            result['cached'] = names
        route.fulfill(json=result)

    tab.route('**/api/thumb?*', image)
    tab.route('**/api/prefetch_thumbs', status)
    tab.route('**/api/thumb_status', status)

    def render(items=ITEMS):
        tab.evaluate("""items => {
          document.getElementById('search-input').value = '';
          allItems = items; buildGrid(items.map(_makeCard));
        }""", items)

    def ready(count):
        tab.wait_for_function("""count => {
          const images = [...document.querySelectorAll('#grid-area img[data-game-rel]')];
          return images.length === count && images.every(img => img.naturalWidth > 0 &&
            getComputedStyle(img).display !== 'none' && img.parentElement.dataset.previewState === 'ready');
        }""", arg=count)
        assert tab.locator('#grid-area .spinner:visible').count() == 0

    def texture(name, imported=False):
        return dict(type='asset', file_type='texture', game_rel=f'ThumbFixture/{name}', name=name, imported=imported)

    skin_path = 'UI/Textures/Show/Skin/img_skin_1036300'
    skin_art = dict(type='asset', file_type='texture', name='img_skin_1036300', game_rel=skin_path,
                    thumbnail='/api/catalogue/thumbnail/1036300', imported=False)
    artwork_state = {'missing': False}
    tab.route('**/api/catalogue/thumbnail/1036300*', lambda r: r.fulfill(
        status=404 if artwork_state['missing'] else 200, content_type='image/svg+xml',
        body='' if artwork_state['missing'] else IMAGE))
    tab.route('**/api/preview?*', lambda r: r.fulfill(content_type='image/svg+xml', body=IMAGE)
              if parse_qs(urlparse(r.request.url).query).get('game_rel') == [skin_path] else r.fallback())

    try:
        tab.goto(url)
        tab.wait_for_function("typeof buildGrid === 'function' && window.atelierProject?.()")
        tab.wait_for_selector('#grid-area .card')
        render()
        ready(3)
        tab.locator('#search-scope').click()
        tab.locator('#search-input').fill('T_N')
        ready(1)
        tab.locator('#search-input').fill('')
        ready(3)
        assert all(query['_project'] == ['Smoke A'] for kind, query in requests if kind == 'image')
        checks.append('Cached original and imported texture previews remain visible after search and grid rebuilds, with the originating project in image URLs')

        requests.clear()
        render([skin_art, texture('Unmatched')])
        ready(2)
        assert tab.locator('img[data-game-rel="'+skin_path+'"]').get_attribute('src') == skin_art['thumbnail']
        assert all(body.get('game_rel') != [skin_path] for kind, body in requests if kind == 'image')
        assert all(skin_path not in body.get('game_rels', []) for kind, body in requests if kind != 'image')
        assert any(body.get('game_rels') == ['ThumbFixture/Unmatched'] for kind, body in requests if kind == 'prefetch')
        tab.evaluate("path => handleSSE({game_rel:path,thumb_failed:true})", skin_path)
        ready(2)
        tab.evaluate("() => previewLibraryCard(_makeCard(allItems[0]), document.activeElement)")
        assert tab.locator('#library-preview img').get_attribute('src') == skin_art['thumbnail']
        tab.locator('#library-preview-close').click()
        checks.append('Matched skin UI portraits use catalogue artwork in the grid and Quick preview, and only unmatched textures enter the decode queue')

        tab.evaluate("""path => {
          updateImportedCard(path, {token:'skin-edited'});
          refreshEditedTexture(path, 'skin-edited', false);
        }""", skin_path)
        tab.wait_for_function("path => document.querySelector('img[data-game-rel=\"'+path+'\"]').src.includes('/api/preview?')", arg=skin_path)
        assert tab.evaluate("!allItems[0].thumbnail && !document.querySelector('#grid-area .card')._libraryCard.thumbnail")
        tab.evaluate("() => previewLibraryCard(_makeCard(allItems[0]), document.activeElement)")
        assert '/api/preview?' in tab.locator('#library-preview img').get_attribute('src')
        tab.locator('#library-preview-close').click()
        checks.append('Editing a skin UI portrait switches the visible card and Quick preview to the project image')

        artwork_state['missing'] = True
        requests.clear()
        render([{**skin_art, 'thumbnail': skin_art['thumbnail']+'?unavailable=1'}])
        tab.locator('.thumbnail-fallback-label').wait_for()
        assert not requests, 'Missing catalogue artwork unexpectedly queued texture decoding'
        artwork_state['missing'] = False
        tab.locator('#grid-area .card').click(button='right')
        tab.get_by_role('button', name='Retry preview', exact=True).click()
        ready(1)
        assert not requests, 'Retrying catalogue artwork unexpectedly queued texture decoding'
        checks.append('Unavailable cached skin artwork has a retryable fallback without starting texture extraction')

        state.update(mode='queued', statuses=0)
        render([texture('Missed_N')])
        ready(1)
        assert state['statuses'] >= 1
        checks.append('A completed thumbnail becomes visible through status recovery even when its SSE notification is missed')

        state.update(mode='failed')
        render([texture('Failed_N')])
        tab.locator('.thumbnail-fallback-label').wait_for()
        assert tab.locator('#grid-area .spinner:visible').count() == 0
        assert tab.locator('#grid-area script').count() == 0
        state['mode'] = 'cached'
        tab.locator('#grid-area .card').click(button='right')
        tab.get_by_role('button', name='Retry preview', exact=True).click()
        ready(1)
        assert any(kind == 'prefetch' and body.get('retry') for kind, body in requests)
        checks.append('Decode failures replace spinners with a clear fallback; Retry preview requests a fresh attempt and restores the image')

        state.update(mode='slow', reads=0)
        render([texture('Slow_N')])
        tab.wait_for_function("document.querySelector('#grid-area img').src.includes('_t=')")
        tab.wait_for_timeout(4400)
        assert len(held) == 1, f'Polling restarted a slow ready-image request {len(held)} times'
        held.pop().fulfill(content_type='image/svg+xml', body=IMAGE)
        ready(1)
        checks.append('Status polling does not cancel a valid slow image response every two seconds')

        # A delayed API completion must not repaint a new folder or keep a request alive.
        tab.evaluate("""() => {
          window.realThumbFetch = window.fetch;
          window.staleThumbRequests = [];
          window.fetch = (url, opts) => String(url).includes('/api/prefetch_thumbs') ?
            new Promise(resolve => staleThumbRequests.push({resolve, signal:opts.signal})) : realThumbFetch(url,opts);
        }""")
        state['mode'] = 'queued'
        render([texture('Stale_N')])
        tab.wait_for_function('staleThumbRequests.length > 0')
        render([dict(type='folder', name='Next folder', rel_path='Next')])
        assert tab.evaluate('staleThumbRequests.every(req=>req.signal.aborted)')
        tab.evaluate("""() => {
          window.fetch = realThumbFetch;
          staleThumbRequests.forEach(req=>req.resolve({json:async()=>({ok:true,cached:['ThumbFixture/Stale_N']})}));
        }""")
        tab.wait_for_timeout(100)
        assert tab.locator('#grid-area img[data-game-rel]').count() == 0
        assert tab.locator('#grid-area .card-name').inner_text() == 'Next folder'
        checks.append('Leaving a grid aborts thumbnail status requests and ignores late responses without altering the new folder')

        # Imported previews need the same bounded image-read lifecycle as original previews.
        tab.clock.install()
        state['mode'] = 'hung'
        render([texture('Hung_D', imported=True)])
        tab.wait_for_timeout(80)
        tab.clock.fast_forward(31000)
        tab.locator('.thumbnail-fallback-label').wait_for()
        assert tab.locator('#grid-area .spinner:visible').count() == 0
        for route in held:
            route.abort()
        held.clear()
        checks.append('A hung imported image request reaches a visible retryable fallback instead of spinning indefinitely')
        tab.screenshot(path=str(report / 'thumbnail-failure-fallback.png'))
        assert not errors, errors
    finally:
        tab.close()
