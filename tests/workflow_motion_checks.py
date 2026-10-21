"""Everyday Krackle: actual selection/navigation/editor/import UI, isolated API fixtures."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def run_workflow_motion_checks(context, url, report, checks):
    tab = context.new_page()
    tab.set_viewport_size({'width': 1400, 'height': 900})
    errors = []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    art = (Path(__file__).resolve().parents[1] / 'gui/brand/atelier-mark.png').read_bytes()
    heroes = [{'name': name, 'path': f'Characters/{1000+i}', 'avatar': '/fixture/workflow.png',
               'skins': [{'name': 'Fixture costume', 'path': f'Characters/{1000+i}/{1000+i}000'}]}
              for i, name in enumerate(('Fixture hero A', 'Fixture hero B'))]
    imported = []
    material = {'type': 'asset', 'file_type': 'material', 'name': 'MI_Workflow',
                'game_rel': 'Characters/1000/1000000/MI_Workflow', 'imported': True}
    folders = {'': [{'type': 'folder', 'name': 'Characters', 'rel_path': 'Characters'}],
               'Characters': [material]}
    tab.route('**/fixture/workflow.png', lambda route: route.fulfill(body=art, content_type='image/png'))
    tab.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': heroes}))
    tab.route('**/api/catalogue/hero/**', lambda route: route.fulfill(status=404, body='Fixture: no banner'))
    tab.route('**/api/imported', lambda route: route.fulfill(json=imported))
    tab.route('**/api/browse?*', lambda route: route.fulfill(json=folders.get(
        parse_qs(urlparse(route.request.url).query).get('path', [''])[0], {'error': 'Fixture read failed'})))
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={
        'ok': True, 'colors': [{'name': 'Tint', 'rgba': [.2, .5, .8, 1]}], 'scalars': [],
        'original': {'colors': [{'name': 'Tint', 'rgba': [.2, .5, .8, 1]}], 'scalars': []}}))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))

    def mode(value):
        tab.locator('#settings-motion').select_option(value, force=True)

    def finished():
        tab.wait_for_function("!document.querySelector('.k-workflow-canvas')")

    def formation(kind, screenshot=None):
        selector = f'.k-workflow-canvas[data-workflow-kind="{kind}"]'
        tab.wait_for_selector(selector, state='attached', timeout=2500)
        tab.wait_for_function("""selector => {
            const c = document.querySelector(selector);
            return c && c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((v,i)=>i%4===3&&v>0);
        }""", arg=selector)
        assert tab.locator(selector).evaluate("c=>c.inert && c.getAttribute('aria-hidden')==='true' && getComputedStyle(c).pointerEvents==='none'")
        if screenshot:
            tab.screenshot(path=str(report / screenshot))

    try:
        tab.goto(url)
        tab.wait_for_function("document.querySelectorAll('.roster-portrait').length===2 && window.atelierProject?.()")
        tab.wait_for_function("!document.querySelector('.overlay.active')")
        mode('full')
        for theme in ('dark', 'light'):
            tab.locator('#settings-theme').select_option(theme, force=True)
            label = tab.locator('.roster-portrait[aria-pressed=false]').first.get_attribute('aria-label')
            selected = tab.get_by_role('button', name=label, exact=True)
            selected.click()
            assert selected.get_attribute('aria-pressed') == 'true'
            formation('hero', f'workflow-hero-{theme}.png')
            finished()
            selected.click()
            assert not tab.locator('.k-workflow-canvas').count()
        checks.append('Hero selection commits immediately, punches real energy bubbles in both themes, and never replays for initial render or an already-selected hero')

        tab.locator('#grid-area .card').first.click()
        tab.wait_for_function("nav.path==='Characters' && document.getElementById('grid-area').getAttribute('aria-busy')==='false'")
        formation('navigation', 'workflow-navigation.png')
        finished()
        tab.locator('#btn-back').click()
        formation('navigation')
        assert tab.locator('html').get_attribute('data-library-direction') == 'back'
        tab.evaluate("pushNav({path:'Broken'})")
        tab.wait_for_function("document.getElementById('library-count').textContent==='Could not load assets'")
        assert not tab.locator('.k-workflow-canvas').count()
        tab.evaluate("pushNav({path:'Characters'})")
        formation('navigation'); finished()
        checks.append('Successful forward/back folder navigation gets an ink wake after the content commits; a new failed navigation cancels the previous effect and keeps its error state without an arrival')

        tab.evaluate("openMaterialEditor({name:'MI_Workflow',game_rel:'Characters/1000/1000000/MI_Workflow'})")
        tab.wait_for_selector('#matsw0')
        formation('editor', 'workflow-editor.png')
        finished()
        assert tab.locator('#mat-save').is_enabled()
        tab.evaluate('closeMaterialEditor(true)')
        tab.wait_for_function("!document.querySelector('.overlay.active')")
        checks.append('Opening the real material editor forms ink along its header edge while its controls and colour values remain available')

        imported.append({'token': 'workflow', 'name': 'MI_Workflow', 'file_type': 'material',
                         'game_rel': material['game_rel'], 'selected': True})
        tab.evaluate("refreshSidebarEntry('Characters/1000/1000000/MI_Workflow','MI_Workflow','1000000')")
        tab.wait_for_selector('.sb-item .sb-thumb')
        formation('arrival', 'workflow-tray.png'); finished()
        checks.append('A confirmed edited asset lands in the actual Mod tray thumbnail with an ink catch, reusing the existing import/save presentation path')

        for value in ('calm', 'off'):
            mode(value)
            result = tab.evaluate("""() => {
                const host=document.querySelector('.sb-thumb'), before=host.getAnimations().length;
                const played=AtelierMotion.workflow.arrival(host);
                return {played, animated:host.getAnimations().length>before, canvas:document.querySelectorAll('.k-workflow-canvas').length};
            }""")
            assert result == {'played': value == 'calm', 'animated': value == 'calm', 'canvas': 0}, result
        mode('full')
        tab.emulate_media(reduced_motion='reduce')
        assert not tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'))")
        tab.emulate_media(reduced_motion='no-preference')
        tab.wait_for_function("AtelierMotionPolicy.mode()==='full'")
        checks.append('Calm uses only a brief inset pulse, Off has no effect, and OS reduced motion takes precedence over Full')

        ownership = tab.evaluate("""() => {
            const release=AtelierMotion.moment.claim('fixture-busy-stage',2);
            try { return {held:!!release, played:AtelierMotion.workflow.navigation(document.querySelector('.library-location')),mode:AtelierMotionPolicy.mode()}; }
            finally { release?.(); }
        }""")
        assert ownership == {'held': True, 'played': False, 'mode': 'full'}, ownership
        tab.evaluate("openMaterialEditor({name:'MI_Workflow',game_rel:'Characters/1000/1000000/MI_Workflow'})")
        tab.wait_for_selector('#matsw0'); finished()
        assert not tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'))")
        tab.evaluate('closeMaterialEditor(true)')
        checks.append('Import/export stage ownership suppresses wide workflow formations; background tray effects never float over an active editor or dialog')

        fallback = tab.evaluate("""() => {
            const native=HTMLCanvasElement.prototype.getContext;
            let nullResult, throwResult, released;
            try {
                HTMLCanvasElement.prototype.getContext=function(...args){return this.classList.contains('k-workflow-canvas')?null:native.apply(this,args);};
                nullResult=AtelierMotion.workflow.navigation(document.querySelector('.library-location'));
                HTMLCanvasElement.prototype.getContext=function(...args){return this.classList.contains('k-workflow-canvas')?{scale(){throw Error('fixture canvas failure');}}:native.apply(this,args);};
                throwResult=AtelierMotion.workflow.navigation(document.querySelector('.library-location'));
                released=AtelierMotion.moment.claim('fixture-after-failed-canvas',2); released?.();
            } finally { HTMLCanvasElement.prototype.getContext=native; }
            return {nullResult,throwResult,released:!!released,canvases:document.querySelectorAll('.k-workflow-canvas').length};
        }""")
        assert fallback == {'nullResult': False, 'throwResult': False, 'released': True, 'canvases': 0}, fallback
        checks.append('Missing or throwing Canvas support leaves the interface usable and releases the shared motion owner')

        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'))")
        formation('arrival')
        mode('off')
        assert not tab.locator('.k-workflow-canvas').count()
        mode('full')
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));window.dispatchEvent(new Event('resize'))")
        assert not tab.locator('.k-workflow-canvas').count()
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        assert not tab.locator('.k-workflow-canvas').count()
        tab.evaluate("delete document.hidden")
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));document.querySelector('.sb-item').remove()")
        finished()
        assert not errors, errors
        checks.append('Dial changes, resize, hidden documents and detached targets remove their canvases and cancel pending drawing')
    finally:
        tab.close()
