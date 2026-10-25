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

    def media(value):
        tab.emulate_media(reduced_motion=value)
        # Chromium coalesces media changes inside one rendering cycle. Let the
        # previous OS setting finish dispatching before emulating its reversal.
        tab.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

    def finished():
        tab.wait_for_function("!document.querySelector('.k-workflow-svg,.k-workflow-link')")

    def formation(kind, screenshot=None):
        selector = f'.k-workflow-svg[data-workflow-kind="{kind}"]'
        tab.wait_for_selector(selector, state='attached', timeout=2500)
        tab.wait_for_function("""selector => {
            const c = document.querySelector(selector);
            return c && [...c.querySelectorAll('[data-ink]')].some(p=>Number(p.getAttribute('opacity'))>.15);
        }""", arg=selector, timeout=3500)
        assert tab.locator(selector).evaluate("c=>c.inert && c.getAttribute('aria-hidden')==='true' && getComputedStyle(c).pointerEvents==='none'")
        assert tab.locator(selector).evaluate("""c=>c.namespaceURI==='http://www.w3.org/2000/svg'
            && getComputedStyle(c).overflow==='hidden' && c.querySelectorAll('clipPath').length===2
            && !!c.querySelector('mask') && !c.querySelector('circle')""")
        if screenshot:
            tab.wait_for_timeout(200)  # Inspect the drawn seam beyond its first frame.
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
            assert tab.evaluate("""() => {
                const svg=document.querySelector('.k-workflow-svg[data-workflow-kind=hero]');
                const box=svg.getBoundingClientRect();
                const host=document.querySelector('.roster-portrait[aria-pressed=true]').getBoundingClientRect();
                return Math.abs(box.left-host.left)<1 && Math.abs(box.top-host.top)<1
                    && Math.abs(box.width-host.width)<1 && Math.abs(box.height-host.height)<1;
            }""")
            finished()
            selected.click()
            assert not tab.locator('.k-workflow-svg').count()
        checks.append('Hero selection commits immediately, draws a bounded SVG crown in both themes, and never replays for initial render or an already-selected hero')
        checks.append('Native SVG viewports match their host exactly, with rounded clipping and a protected interior')

        folder = tab.locator('#grid-area .card').first
        pin = tab.locator('.library-pin-toggle[data-library-pin-path="Characters"]')
        folder.hover(); pin.click()
        assert pin.get_attribute('aria-pressed') == 'true'
        assert tab.evaluate("nav.path === '' && AtelierLibraryPins.isPinned('Characters')")
        formation('pin', 'workflow-pin.png'); finished()
        pin.press('Space')
        assert pin.get_attribute('aria-pressed') == 'false'
        formation('unpin', 'workflow-unpin.png'); finished()
        checks.append('Pin and unpin formations follow real pointer and keyboard changes without navigating or removing library assets')

        folder.click(button='right')
        tab.wait_for_selector('#ctx-menu.active')
        formation('menu', 'workflow-menu.png')
        assert tab.locator('#ctx-menu .ctx-item').first.is_enabled()
        tab.locator('#ctx-menu .ctx-item').first.press('Escape')
        finished()
        assert not tab.locator('#ctx-menu').is_visible()
        checks.append('Context menus unfold inside their border, clear of action labels and discard it on Escape while preserving normal keyboard controls')

        tab.evaluate("_selectProject('Smoke B')")
        assert tab.locator('#project-chip-name').inner_text() == 'Smoke B'
        formation('project', 'workflow-project.png'); finished()
        tab.evaluate("_selectProject('Smoke B')")
        assert not tab.locator('.k-workflow-svg').count()
        tab.evaluate("_selectProject('Krackle missing project')")
        assert tab.locator('#project-chip-name').inner_text() == 'Smoke B'
        assert not tab.locator('.k-workflow-svg').count()
        tab.evaluate("_selectProject('Smoke A')")
        formation('project'); finished()
        checks.append('Successful project handoffs form ink under the committed project chip; reselecting and failed switches stay still and retain the active project')

        tab.locator('#grid-area .card').first.click()
        tab.wait_for_function("nav.path==='Characters' && document.getElementById('grid-area').getAttribute('aria-busy')==='false'")
        formation('navigation', 'workflow-navigation.png')
        finished()
        tab.locator('#btn-back').click()
        formation('navigation')
        assert tab.locator('html').get_attribute('data-library-direction') == 'back'
        tab.evaluate("pushNav({path:'Broken'})")
        tab.wait_for_function("document.getElementById('library-count').textContent==='Could not load assets'")
        assert not tab.locator('.k-workflow-svg').count()
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

        tab.locator('#menu-btn').click()
        tab.locator('#ctx-menu').get_by_role('button', name='Settings…', exact=True).click()
        tab.wait_for_selector('#setup-overlay.active')
        formation('panel', 'workflow-settings-panel.png')
        assert tab.locator('#settings-theme').is_enabled()
        tab.locator('#setup-close').click(); finished()
        tab.locator('#job-activity').click()
        tab.wait_for_selector('#job-overlay.active')
        formation('panel', 'workflow-activity-panel.png')
        tab.locator('#job-close').click(); finished()
        checks.append('Settings and Activity announce actual openings with compact internal corner seams; readable controls remain immediately available')
        for value in ('calm', 'off'):
            mode(value); tab.locator('#job-activity').click()
            tab.wait_for_selector('#job-overlay.active')
            tab.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            assert not tab.locator('.k-workflow-svg[data-workflow-kind=panel]').count()
            tab.locator('#job-close').click()
        mode('full')
        tab.evaluate("""() => new Promise(resolve => {
            const overlay=document.getElementById('setup-overlay');
            overlay.classList.add('active');
            requestAnimationFrame(() => {
                overlay.classList.remove('active'); requestAnimationFrame(resolve);
            });
        })""")
        assert not tab.locator('.k-workflow-svg[data-workflow-kind=panel]').count()
        assert tab.evaluate("(() => {const release=AtelierMotion.moment.claim('fixture-cancelled-panel',2);release?.();return !!release;})()")
        checks.append('Calm/Off keep panel openings static, and a fast dismissal cancels the pending entrance without retaining stage ownership')

        tab.evaluate("""() => {
            window.primaryClicks=0;
            const button=document.createElement('button');button.id='krackle-primary-fixture';
            button.className='btn primary';button.textContent='Primary action';
            button.style.cssText='position:fixed;left:400px;top:180px;z-index:150';
            button.onclick=()=>primaryClicks++;document.body.append(button);
        }""")
        tab.locator('#krackle-primary-fixture').click()
        assert tab.evaluate('primaryClicks') == 1
        formation('action', 'workflow-primary-action.png')
        tab.locator('#krackle-primary-fixture').click()
        assert tab.evaluate('primaryClicks') == 2
        assert tab.locator('.k-workflow-svg[data-workflow-kind=action]').count() == 1
        finished(); tab.locator('#krackle-primary-fixture').evaluate('button=>button.remove()')
        checks.append('Primary actions get a quick border strike without delaying clicks or stacking repeated effects')

        imported.append({'token': 'workflow', 'name': 'MI_Workflow', 'file_type': 'material',
                         'game_rel': material['game_rel'], 'selected': True})
        tab.evaluate("refreshSidebarEntry('Characters/1000/1000000/MI_Workflow','MI_Workflow','1000000')")
        tab.wait_for_selector('.sb-item .sb-thumb')
        formation('arrival', 'workflow-tray.png')
        assert tab.evaluate("""() => {
            const ink=document.querySelector('.k-workflow-svg[data-workflow-kind=arrival]').getBoundingClientRect();
            const row=document.querySelector('.sb-item').getBoundingClientRect();
            return ['left','top','width','height'].every(key=>Math.abs(ink[key]-row[key])<1);
        }"""), 'The Mod tray row frame must receive ink without covering its thumbnail'
        finished()
        checks.append('A confirmed edit lands on its actual Mod tray row frame, keeping the source and receiving ink clear of full-bleed artwork')
        tab.locator('.sb-item .sb-check').click()
        assert tab.locator('#install-btn').is_disabled()
        formation('selection', 'workflow-build-selection.png'); finished()
        tab.locator('#sel-count').click()
        assert tab.locator('#install-btn').is_enabled()
        formation('selection'); finished()
        checks.append('Individual and select-all build choices form ink around the real count, with export availability updating immediately')

        for value in ('calm', 'off'):
            mode(value)
            result = tab.evaluate("""() => {
                const host=document.querySelector('.sb-thumb'), before=host.getAnimations().length;
                const played=AtelierMotion.workflow.arrival(host);
                return {played, animated:host.getAnimations().length>before, canvas:document.querySelectorAll('.k-workflow-svg').length};
            }""")
            assert result == {'played': value == 'calm', 'animated': value == 'calm', 'canvas': 0}, result
        mode('full')
        media('reduce')
        tab.wait_for_function("document.documentElement.dataset.krackle==='off'")
        assert not tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'))")
        media('no-preference')
        tab.wait_for_function("AtelierMotionPolicy.mode()==='full' && document.documentElement.dataset.krackle==='full'")
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
            const native=document.createElementNS;
            let failed, released;
            try {
                document.createElementNS=function(ns,name,...args) {
                    if (name==='svg') throw Error('fixture SVG failure');
                    return native.call(this,ns,name,...args);
                };
                failed=AtelierMotion.workflow.navigation(document.querySelector('.library-location'));
                released=AtelierMotion.moment.claim('fixture-after-failed-svg',2); released?.();
            } finally { document.createElementNS=native; }
            return {failed,released:!!released,svgs:document.querySelectorAll('.k-workflow-svg').length};
        }""")
        assert fallback == {'failed': False, 'released': True, 'svgs': 0}, fallback
        checks.append('Failed SVG construction leaves the interface usable and releases the shared motion owner')

        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'))")
        formation('arrival')
        mode('off')
        assert not tab.locator('.k-workflow-svg').count()
        mode('full')
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));window.dispatchEvent(new Event('resize'))")
        assert not tab.locator('.k-workflow-svg').count()
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        assert not tab.locator('.k-workflow-svg').count()
        tab.evaluate("delete document.hidden")
        tab.evaluate("AtelierMotion.workflow.arrival(document.querySelector('.sb-thumb'));document.querySelector('.sb-item').remove()")
        finished()
        # Full and Calm both release effects when a new dialog takes ownership.
        for value in ('full', 'calm'):
            mode(value)
            tab.evaluate("""() => {
                window.workflowHost = document.createElement('div');
                workflowHost.style.cssText = 'position:fixed;left:20px;top:100px;width:50px;height:50px';
                document.body.append(workflowHost);
                if (!AtelierMotion.workflow.arrival(workflowHost)) throw Error('fixture did not start');
                document.getElementById('setup-overlay').classList.add('active');
            }""")
            tab.wait_for_function("!document.querySelector('.k-workflow-svg') && workflowHost.getAnimations().length===0")
            tab.evaluate("document.getElementById('setup-overlay').classList.remove('active');workflowHost.remove()")
        mode('full')
        checks.append('Opening a dialog cancels active workspace ink immediately in Full and Calm')

        # Preview the production formations from the real Settings surface. No job or project writes.
        writes = []
        tab.on('request', lambda request: writes.append(request.url)
               if request.method not in ('GET', 'HEAD', 'OPTIONS') and '/api/' in request.url else None)
        tab.evaluate("""() => {
            _pathsMode = true; _applySetupMode(); _setSetupLoading(false);
            document.getElementById('setup-overlay').classList.add('active');
        }""")
        preview = tab.get_by_role('group', name='Krackle motion preview')
        preview.get_by_role('button', name='Replay ink handoff', exact=True).click()
        tab.wait_for_selector('.k-workflow-link', state='attached', timeout=2500)
        assert tab.locator('.k-motion-sample').count() == 12
        tab.wait_for_timeout(130)
        tab.screenshot(path=str(report / 'workflow-handoff-demo.png'))
        formation('arrival'); finished()
        checks.append('Try Krackle includes an accessible connected Edit to Mod tray handoff alongside twelve local gestures')
        for _ in range(2):
            tab.locator('#setup-close').click()
            tab.evaluate("document.getElementById('setup-overlay').classList.add('active')")
            preview.get_by_role('button', name='Replay ink handoff', exact=True).click()
            tab.wait_for_selector('.k-workflow-link', state='attached', timeout=2500)
            formation('arrival'); finished()
        checks.append('Repeated immediate open-and-replay gives ownership to the handoff rather than a late panel entrance')
        for theme in ('dark', 'light'):
            tab.locator('#settings-theme').select_option(theme, force=True)
            preview.scroll_into_view_if_needed()
            for kind in ('hero', 'navigation', 'arrival', 'pin', 'unpin', 'menu', 'project', 'workspace', 'editor', 'action', 'panel', 'selection'):
                tab.locator(f'[data-motion-sample="{kind}"]').click()
                formation(kind, f'workflow-preview-{kind}-{theme}.png')
                finished()
        checks.append('Settings replays all twelve authored production gestures in both themes, without jobs or project writes')

        # Rasterize the real native SVG to verify the entire protected interior.
        tab.locator('[data-motion-sample=arrival] .k-motion-sample-art').evaluate("""host => {
            host.style.position='relative';
            const text=document.createElement('span');text.id='workflow-mask-label';text.textContent='M';
            text.style.cssText='position:absolute;left:6px;top:0;font:10px/10px sans-serif';
            host.append(text);
        }""")
        tab.locator('[data-motion-sample=arrival]').click()
        formation('arrival')
        tab.wait_for_timeout(100)
        raster = tab.evaluate("""async () => {
            const svg=document.querySelector('.k-workflow-svg[data-workflow-kind=arrival]');
            const w=Math.ceil(svg.viewBox.baseVal.width),h=Math.ceil(svg.viewBox.baseVal.height);
            const inset=Math.ceil(Number(svg.dataset.edgeBand))+2;
            const image=new Image();
            const snapshot=svg.cloneNode(true);
            for(const key of ['position','left','top']) snapshot.style.removeProperty(key);
            image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(snapshot));
            await image.decode();
            const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
            const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
            const all=ctx.getImageData(0,0,w,h).data;
            const inside=ctx.getImageData(inset,inset,w-2*inset,h-2*inset).data;
            const host=document.querySelector('[data-motion-sample=arrival] .k-motion-sample-art');
            const origin=svg.getBoundingClientRect(),regions=[];
            for(const node of host.querySelectorAll('svg,img')) regions.push(node.getBoundingClientRect());
            const range=document.createRange();range.selectNodeContents(document.getElementById('workflow-mask-label'));
            regions.push(...range.getClientRects());
            let protectedInk=0;
            for(const box of regions) {
                const x=Math.max(0,Math.ceil(box.left-origin.left)),y=Math.max(0,Math.ceil(box.top-origin.top));
                const width=Math.min(w-x,Math.floor(box.right-origin.left)-x),height=Math.min(h-y,Math.floor(box.bottom-origin.top)-y);
                if(width>0&&height>0) protectedInk+=ctx.getImageData(x,y,width,height).data.filter((v,i)=>i%4===3&&v>0).length;
            }
            return {visible:all.filter((v,i)=>i%4===3&&v>0).length, inside:inside.filter((v,i)=>i%4===3&&v>0).length,
                protectedInk,regions:regions.length,displayed:getComputedStyle(svg).display!=='none'};
        }""")
        assert raster['visible'] > 0 and raster['inside'] == 0 and raster['protectedInk'] == 0, raster
        assert raster['regions'] >= 2 and raster['displayed'], raster
        finished()
        tab.locator('#workflow-mask-label').evaluate('node=>node.remove()')
        tab.locator('[data-motion-sample=arrival] .k-motion-sample-art').evaluate("host=>host.style.removeProperty('position')")
        checks.append('Visible native SVG has edge ink, a transparent interior, and transparent full glyph/text bounds including a label touching its seam')

        # Artwork palette changes repaint the existing gesture without restarting it.
        pigment = tab.evaluate("""async () => {
            const host=document.querySelector('[data-motion-sample=hero] .k-motion-sample-art');
            const semantic=getComputedStyle(host).getPropertyValue('--krackle-charge');
            host.style.setProperty('--roster-skin-accent','#e84f8a');
            AtelierMotion.workflow.hero(host);
            const svg=document.querySelector('.k-workflow-svg');
            const first=svg.querySelector('[data-ink=charge]').getAttribute('stroke');
            host.style.setProperty('--roster-skin-accent','#57bf68');
            AtelierMotion.energy.refresh();
            await Promise.resolve();
            const expected=AtelierMotion.energy.resolve(host);
            const second=svg.querySelector('[data-ink=charge]').getAttribute('stroke');
            const result={same:svg===document.querySelector('.k-workflow-svg'),
                changed:first!==second,matched:second===expected.charge,source:svg.dataset.energySource,
                semantic:semantic===getComputedStyle(host).getPropertyValue('--krackle-charge')};
            host.style.removeProperty('--roster-skin-accent');AtelierMotion.workflow.stop();
            return result;
        }""")
        assert pigment == {'same': True, 'changed': True, 'matched': True, 'source': 'artwork', 'semantic': True}, pigment
        checks.append('Hero and skin pigment changes repaint the active gesture while semantic control colours remain unchanged')

        stable = tab.evaluate("""() => {
            const hosts=[...document.querySelectorAll('.k-motion-sample-art')].slice(0,5);
            const native=Math.random;let first,second,count;
            try {
                Math.random=()=>{throw Error('workflow must not sample random geometry');};
                AtelierMotion.workflow.hero(hosts[0]);
                first=[...document.querySelectorAll('.k-workflow-svg path')].map(p=>p.getAttribute('d')).join('|');
                AtelierMotion.workflow.stop();AtelierMotion.workflow.hero(hosts[0]);
                second=[...document.querySelectorAll('.k-workflow-svg path')].map(p=>p.getAttribute('d')).join('|');
                for(const host of hosts) AtelierMotion.workflow.arrival(host);
                count=document.querySelectorAll('.k-workflow-svg').length;
            } finally {Math.random=native;AtelierMotion.workflow.stop();}
            return {stable:!!first&&first===second,count};
        }""")
        assert stable == {'stable': True, 'count': 3}, stable
        checks.append('Authored paths replay identically without randomness and at most three effects stay active')

        linked = tab.evaluate("""async () => {
            const overlay=document.getElementById('setup-overlay');
            const source=document.createElement('div'),destination=document.createElement('div');
            source.id='workflow-source';destination.id='workflow-destination';
            source.style.cssText='position:fixed;left:320px;top:160px;width:40px;height:40px;background:var(--bg2)';
            destination.style.cssText='position:fixed;left:620px;top:210px;width:100px;height:60px;background:var(--bg2)';
            overlay.append(source,destination);
            const played=AtelierMotion.workflow.transfer(source,destination,'arrival');
            for(let i=0;i<6;i++) await new Promise(requestAnimationFrame);
            const link=document.querySelector('.k-workflow-link');
            const a=source.getBoundingClientRect(),b=destination.getBoundingClientRect();
            return {played,measured:!!link && Number(link.dataset.sourceX)===a.right-1
                && Number(link.dataset.sourceY)===a.top+a.height/2
                && Number(link.dataset.destinationX)===b.left+1
                && Number(link.dataset.destinationY)===b.top+b.height/2,
                hidden:!!link&&link.inert&&link.getAttribute('aria-hidden')==='true',
                ribbon:!!link?.querySelector('[data-flow-role=ribbon]')};
        }""")
        assert linked == {'played': True, 'measured': True, 'hidden': True, 'ribbon': True}, linked
        formation('arrival', 'workflow-connected-transfer.png')
        tab.locator('#workflow-source').evaluate('node=>node.remove()')
        finished()
        assert tab.evaluate("""() => {
            const released=AtelierMotion.moment.claim('fixture-link-cleanup',2);
            released?.();document.getElementById('workflow-destination').remove();return !!released;
        }""")
        checks.append('Connected transfers trace measured source and receiver edges; detaching the source removes the entire gesture and releases ownership')

        from ink_flow_checks import run_ink_flow_checks
        run_ink_flow_checks(tab, report, checks)

        mode('calm')
        tab.locator('[data-motion-sample=hero]').click()
        assert not tab.locator('.k-workflow-svg').count()
        assert preview.locator('.k-motion-preview-mode').inner_text() == 'Calm'
        tab.wait_for_function("!document.querySelector('[data-motion-sample=hero] .k-motion-sample-art').getAnimations().length")
        tab.locator('[data-motion-sample=menu]').click()
        assert tab.evaluate("document.querySelector('[data-motion-sample=menu] .k-motion-sample-art').getAnimations().length > 0")
        tab.evaluate("document.querySelector('.k-motion-preview').style.visibility='hidden'")
        tab.wait_for_function("!document.querySelector('[data-motion-sample=menu] .k-motion-sample-art').getAnimations().length")
        tab.evaluate("document.querySelector('.k-motion-preview').style.removeProperty('visibility')")
        for system in (False, True):
            if system:
                mode('full')
                tab.wait_for_function("document.documentElement.dataset.krackle==='full'")
                media('reduce')
            else:
                mode('off')
            tab.wait_for_function("AtelierMotionPolicy.mode()==='off' && document.querySelector('.k-motion-preview-mode').textContent==='Still'", timeout=2500)
            assert preview.locator('.k-motion-preview-mode').inner_text() == 'Still'
            assert preview.get_by_role('button').evaluate_all('(buttons)=>buttons.every(button=>button.disabled)')
            assert not tab.locator('.k-workflow-svg').count()
        media('no-preference')
        mode('full')
        tab.wait_for_function("document.documentElement.dataset.krackle==='full' && document.querySelector('.k-motion-preview-mode').textContent==='Full'")
        checks.append('Preview follows Calm, Off and OS reduced motion, with disabled replay controls for still presentation')

        # Rapid replay, dismissal, palette changes and unsupported graphics remain disposable.
        tab.locator('[data-motion-sample=hero]').scroll_into_view_if_needed()
        tab.evaluate("""() => {
            const buttons = [...document.querySelectorAll('[data-motion-sample]')].slice(0,3);
            for (let i=0; i<20; i++) buttons[i%buttons.length].click();
        }""")
        assert tab.locator('.k-workflow-svg').count() == 1
        tab.locator('#setup-close').click()
        finished()
        tab.evaluate("document.getElementById('setup-overlay').classList.add('active')")
        formation('panel'); finished()
        preview.scroll_into_view_if_needed()
        assert not tab.locator('.k-workflow-svg').count()
        tab.locator('[data-motion-sample=navigation]').click()
        formation('navigation')
        tab.locator('#settings-theme').select_option('dark', force=True)
        finished()
        # SVG gestures do not require Canvas support.
        tab.evaluate("""() => {
            const native = HTMLCanvasElement.prototype.getContext;
            try {
                HTMLCanvasElement.prototype.getContext = () => null;
                document.querySelector('[data-motion-sample=hero]').click();
            } finally { HTMLCanvasElement.prototype.getContext = native; }
        }""")
        formation('hero'); finished()
        assert tab.locator('#settings-motion').is_enabled()
        checks.append('Rapid replay owns one sample; dismissal and palette changes dispose it; SVG continues without Canvas')

        for width in (720, 360):
            tab.set_viewport_size({'width': width, 'height': 640})
            preview.scroll_into_view_if_needed()
            assert preview.evaluate("p=>p.scrollWidth<=p.clientWidth && p.getBoundingClientRect().right<=innerWidth")
            tab.screenshot(path=str(report / f'workflow-preview-{width}.png'))
        assert not writes, writes
        checks.append('Motion samples fit smaller Settings windows and never write to project or job endpoints')
        assert not errors, errors
        checks.append('Dial changes, resize, hidden documents and detached targets remove their SVG overlays and cancel pending drawing')
    finally:
        tab.close()
