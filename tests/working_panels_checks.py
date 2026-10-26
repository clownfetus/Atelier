"""Real delayed requests and activity-edge lifecycle, using offline browser fixtures."""
from time import monotonic
from io import BytesIO


def run_working_panels_checks(context, url, report, checks):
    tab = context.new_page()
    errors, pending = [], []
    stored = None
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/api/material_params?*', lambda route: pending.append(route))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))
    tab.route('**/api/material_save', lambda route: pending.append(route))
    for kind in ('curve', 'world', 'text'):
        tab.route(f'**/api/{kind}_params?*', lambda route: pending.append(route))
        tab.route(f'**/api/{kind}_save', lambda route: pending.append(route))

    def held():
        deadline = monotonic() + 5
        while not pending and monotonic() < deadline:
            tab.wait_for_timeout(10)
        assert pending, 'The real operation never reached its request'
        return pending.pop(0)

    def mode(value):
        tab.evaluate("value=>{const el=document.getElementById('settings-motion');el.value=value;el.dispatchEvent(new Event('change'));}", value)

    try:
        tab.goto(url)
        tab.wait_for_selector('#grid-area .card')
        tab.wait_for_function('window.AtelierMotion?.working && window.atelierProject?.()')
        stored = tab.evaluate("Object.fromEntries(['motion','theme','appearance'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        mode('full')
        tab.evaluate("() => { window.openingWork=openMaterialEditor({name:'Activity fixture',game_rel:'Fixture/MI_Activity'}); }")
        request = held()
        frame = tab.locator('#material-overlay .am-working-border')
        frame.wait_for()
        tab.evaluate(r"""() => {
          window.readWorkingSVG=el=>{
            const uri=getComputedStyle(el).getPropertyValue('--am-working-frame').match(/^url\("data:image\/svg\+xml,(.*)"\)$/)[1];
            return new DOMParser().parseFromString(decodeURIComponent(uri),'image/svg+xml');
          };
        }""")
        assert frame.evaluate("""el=>{
          const svg=readWorkingSVG(el);
          return ['source','channel','ribbon','receiver'].every(role=>svg.querySelector(`[data-role="${role}"]`)) &&
            svg.querySelectorAll('animate').length > 0;
        }""")
        assert frame.evaluate("el=>getComputedStyle(el).borderTopColor") == 'rgba(0, 0, 0, 0)'
        assert frame.locator('svg.am-working-border, .am-working-dot').count() == 0
        request.fulfill(json={'ok': True, 'colors': [{'name': 'Tint', 'rgba': [.25, .5, .75, 1]}], 'scalars': []})
        tab.evaluate('openingWork')
        tab.wait_for_selector('#mathx0')
        tab.wait_for_function("document.querySelector('#material-overlay .modal').dataset.amWorkingOutcome==='success'")
        tab.locator('#material-overlay .am-working-border').wait_for(state='detached')
        checks.append('Real material loading feeds a connected SVG source/channel/receiver in the native border, then catches the confirmed response before settling')

        tab.evaluate("() => {matEditor.colors[0].rgba=[.8,.2,.1,1];renderMatEditor();window.savingWork=saveMaterial();}")
        request = held()
        tab.locator('#material-overlay .am-working-save').wait_for()
        assert tab.locator('#mat-status').inner_text() == 'Saving…'
        assert tab.locator('#material-overlay .am-working-save .am-material-save-svg').bounding_box()['width'] == 44
        tab.locator('#material-overlay .am-working-dock').wait_for()
        assert tab.locator('#material-overlay .am-working-dock').evaluate("""svg=>{
          const path=svg.querySelector('[data-role=channel]'),matrix=svg.getScreenCTM();
          const start=path.getPointAtLength(0).matrixTransform(matrix),end=path.getPointAtLength(path.getTotalLength()).matrixTransform(matrix);
          const icon=svg.parentElement.querySelector('.am-material-save-svg').getBoundingClientRect();
          const button=document.getElementById('mat-save').getBoundingClientRect();
          return start.x>=icon.left&&start.x<=icon.right&&start.y>=icon.top&&start.y<=icon.bottom&&
            Math.abs(end.y-button.bottom)<2&&end.x>=button.left&&end.x<=button.right;
        }""")
        for theme in ('dark', 'light'):
            tab.evaluate("theme=>{const el=document.getElementById('settings-theme');el.value=theme;el.dispatchEvent(new Event('change'));}", theme)
            tab.screenshot(path=str(report / f'working-save-{theme}.png'))
        request.fulfill(json={'ok': False, 'error': 'Fixture save failure'})
        tab.evaluate('savingWork')
        tab.wait_for_function("document.querySelector('#material-overlay .modal').dataset.amWorkingOutcome==='error'")
        tab.locator('#material-overlay .am-working-border').wait_for(state='detached')
        assert tab.locator('#material-overlay .am-working-save').count() == 0
        assert 'Fixture save failure' in tab.locator('#mat-status').inner_text()
        assert tab.locator('.am-material-save-toast .am-material-save-svg').evaluate('el=>getComputedStyle(el).width') == '40px'
        tab.evaluate('() => {window.retryWork=saveMaterial()}')
        request = held()
        request.fulfill(json={'ok': True, 'inten_saved': True})
        tab.evaluate('retryWork')
        tab.locator('#material-overlay.active').wait_for(state='detached')
        tab.wait_for_function("document.getElementById('sidebar').dataset.amWorkingOutcome==='success'")
        assert tab.evaluate("""() => {
          const panel=document.getElementById('sidebar'), header=document.getElementById('sidebar-header');
          const svg=readWorkingSVG(panel), receiver=svg.querySelector('[data-role=receiver]'), source=svg.querySelector('[data-role=source]');
          const box=panel.getBoundingClientRect(), anchor=header.getBoundingClientRect();
          const x=(anchor.left+anchor.width/2-box.left)*panel.offsetWidth/box.width;
          const y=parseFloat(getComputedStyle(panel).borderTopWidth)/2;
          const rx=+receiver.dataset.x, ry=+receiver.dataset.y;
          return Math.abs(rx-x)<=1 && Math.abs(ry-y)<=1 &&
            Math.hypot(rx-(+source.dataset.x),ry-(+source.dataset.y))>24;
        }"""), 'The receipt did not meet the measured mod-tray header on its native border'
        tab.screenshot(path=str(report / 'working-save-tray-receipt.png'))
        tab.locator('#sidebar.am-working-border').wait_for(state='detached')
        checks.append('A failed save keeps its draft and error; a successful retry sends one finite catch into the actual mod-tray border after the editor closes')

        editors = (
            ('curve', 'Curve', {
                'ok': True, 'channels': {'R': [{'time': 0, 'value': .2, 'interp': 'RCIM_Linear'},
                                              {'time': 1, 'value': .8, 'interp': 'RCIM_Linear'}]},
                'stops': [],
            }, '#curve-body input[title="value"]', '0.4', '0.7'),
            ('world', 'World', {
                'ok': True, 'lights': [{'idx': 0, 'name': 'Fixture light', 'cls': 'PointLightComponent',
                                       'intensity': 1, 'color': [255, 255, 255]}],
                'components': [], 'edits': {},
            }, '#world-body input[data-lidx="0"][data-lk="intensity"]', '2', '3'),
            ('text', 'Text', {
                'ok': True, 'entries': [{'key': 'Greeting', 'value': 'Original'}], 'edits': {},
            }, '#text-body input[data-tkey="Greeting"]', 'Submitted wording', 'Newer wording'),
        )
        for kind, title, payload, input_selector, submitted_value, newer_value in editors:
            item = {'name': f'{title} request fixture', 'game_rel': f'Fixture/{title}_SameFile'}
            tab.evaluate("""({title,item}) => {
              window.oldEditorOpening=window['open'+title+'Editor'](item);
            }""", {'title': title, 'item': item})
            old_request = held()
            tab.locator(f'#{kind}-overlay .am-working-border').wait_for()
            tab.evaluate("title=>window['close'+title+'Editor'](true)", title)
            tab.evaluate("""({title,item}) => {
              window.currentEditorOpening=window['open'+title+'Editor'](item);
            }""", {'title': title, 'item': item})
            current_request = held()
            current_frame = tab.locator(f'#{kind}-overlay .modal')
            old_request.fulfill(json={'ok': False, 'error': f'Stale {title} failure'})
            tab.evaluate('oldEditorOpening')
            assert f'Stale {title} failure' not in tab.locator(f'#{kind}-body').inner_text()
            assert current_frame.evaluate("el=>el.classList.contains('am-working-border') && el.dataset.amWorkingPhase==='working' && !el.dataset.amWorkingOutcome"), f'Stale {kind} response settled the newer request'
            current_request.fulfill(json=payload)
            tab.evaluate('currentEditorOpening')
            control = tab.locator(input_selector).first
            control.wait_for()
            tab.wait_for_function("kind=>document.querySelector('#'+kind+'-overlay .modal').dataset.amWorkingOutcome==='success'", arg=kind)
            assert tab.evaluate("kind=>({curve:curveEditor,world:worldEditor,text:textEditor})[kind].game_rel", kind) == item['game_rel']
            tab.locator(f'#{kind}-overlay .am-working-border').wait_for(state='detached')
            checks.append(f'Reopening the same {kind} file ignores the older request and reserves completion for the current load')

            control.fill(submitted_value)
            tab.locator(f'#{kind}-save').click()
            save_request = held()
            submitted = save_request.request.post_data_json
            assert submitted['game_rel'] == item['game_rel']
            if kind == 'curve':
                assert submitted['edits']['R'][0]['value'] == float(submitted_value)
            elif kind == 'world':
                assert submitted['edits']['lights']['0']['intensity'] == float(submitted_value)
            else:
                assert submitted['edits']['Greeting'] == submitted_value
            control.fill(newer_value)
            save_request.fulfill(json={'ok': True})
            tab.wait_for_function("kind=>document.querySelector('#'+kind+'-overlay .modal').dataset.amWorkingOutcome==='warning'", arg=kind)
            assert tab.locator(f'#{kind}-overlay').evaluate("el=>el.classList.contains('active')"), f'The {kind} editor closed over a newer draft'
            assert tab.locator(input_selector).first.input_value() == newer_value
            if kind == 'curve':
                assert tab.evaluate("curveEditor.channels.R[0].value===.7 && !!curveEditor.dirty.R && _curveDirty()")
            else:
                assert tab.evaluate("""({kind,submitted})=>{
                  const editor=kind==='world'?worldEditor:textEditor;
                  return JSON.stringify(JSON.parse(editor.baseline))===JSON.stringify(submitted.edits) &&
                    (kind==='world'?_worldDirty():_textDirty());
                }""", {'kind': kind, 'submitted': submitted}), f'The {kind} baseline swallowed edits made after submission'
            tab.screenshot(path=str(report / f'working-{kind}-newer-draft.png'))
            tab.locator(f'#{kind}-overlay .am-working-border').wait_for(state='detached')
            tab.evaluate("title=>window['close'+title+'Editor'](true)", title)
            checks.append(f'A held {kind} save retains the submitted snapshot and newer draft, with a partial warning catch instead of full success')

        tab.evaluate("""() => {
          window.workPanel=document.createElement('section');workPanel.className='modal';
          workPanel.id='working-fixture';workPanel.style.cssText='position:fixed;top:180px;left:260px;width:360px;height:190px;z-index:5000;background:var(--bg2)';
          workPanel.style.backgroundImage='linear-gradient(135deg,rgba(80,100,130,.12),rgba(140,110,80,.06))';
          workPanel.textContent='Concurrent work fixture';document.body.append(workPanel);
          window.nativeWorkingBackground=getComputedStyle(workPanel).backgroundImage;
        }""")
        from PIL import Image, ImageChops
        native = Image.open(BytesIO(tab.locator('#working-fixture').screenshot()))
        native.save(report / 'border-native.png')
        tab.evaluate("""() => {
          window.endFirst=AtelierMotion.working.begin(workPanel);
          window.endSecond=AtelierMotion.working.begin(workPanel);
        }""")
        border = tab.locator('#working-fixture.am-working-border')
        border.wait_for()
        tab.evaluate("window.edgeSource=workPanel.style.getPropertyValue('--am-working-frame');endFirst();endFirst();")
        assert border.count() == 1
        tab.evaluate("workPanel.append(document.createElement('span'))")
        assert tab.evaluate("workPanel.style.getPropertyValue('--am-working-frame')===edgeSource")
        first = Image.open(BytesIO(border.screenshot()))
        first.save(report / 'border-active.png')
        interior_change = ImageChops.difference(native, first).convert('RGB').crop((8, 8, first.width - 8, first.height - 8))
        interior_change.save(report / 'border-interior-difference.png')
        # Chromium may round gradient compositing by two channel levels when a
        # second background layer is added. The original gradient parameters stay exact.
        assert max(high for low, high in interior_change.getextrema()) <= 2
        assert tab.evaluate("getComputedStyle(workPanel).backgroundImage.endsWith(nativeWorkingBackground)")
        tab.wait_for_timeout(360)
        second = Image.open(BytesIO(border.screenshot()))
        difference = ImageChops.difference(first, second).convert('RGB')
        assert difference.getbbox(), 'The SVG border did not animate'
        # The entire panel interior stays identical; only its actual border paint changes.
        assert difference.crop((8, 8, first.width - 8, first.height - 8)).getbbox() is None
        assert not tab.evaluate('workPanel.getAnimations({subtree:true}).length'), 'Border created a separate WAAPI animation'
        for value in ('calm', 'off'):
            mode(value)
            border.wait_for(state='detached')
            assert tab.evaluate("!workPanel.style.getPropertyValue('--am-working-frame') && getComputedStyle(workPanel).borderTopColor!=='rgba(0, 0, 0, 0)'")
            assert tab.evaluate("getComputedStyle(workPanel).backgroundImage===nativeWorkingBackground")
        mode('full')
        border.wait_for()
        tab.emulate_media(reduced_motion='reduce')
        border.wait_for(state='detached')
        tab.emulate_media(reduced_motion='no-preference')
        border.wait_for()
        tab.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
        border.wait_for(state='detached')
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        border.wait_for()
        tab.evaluate("workPanel.hidden=true")
        border.wait_for(state='detached')
        tab.evaluate("workPanel.hidden=false")
        border.wait_for()
        tab.evaluate("window.oldEdgeSource=workPanel.style.getPropertyValue('--am-working-frame');workPanel.style.width='460px';workPanel.style.borderRadius='18px 9px 24px 5px / 12px 18px 8px 5px';workPanel.style.borderWidth='3px 1px 2px 4px'")
        tab.wait_for_function("workPanel.style.getPropertyValue('--am-working-frame')!==oldEdgeSource")
        assert tab.evaluate("readWorkingSVG(workPanel).documentElement.getAttribute('viewBox')===`0 0 ${workPanel.offsetWidth} ${workPanel.offsetHeight}`")
        tab.evaluate("""async () => {
          const svg=readWorkingSVG(workPanel), image=new Image();
          image.src='data:image/svg+xml,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));await image.decode();
          const canvas=document.createElement('canvas');canvas.width=workPanel.offsetWidth;canvas.height=workPanel.offsetHeight;
          const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
          if(ctx.getImageData(28,28,canvas.width-56,canvas.height-56).data.some((v,i)=>i%4===3 && v))throw Error('SVG paints inside the panel content');
          if(!ctx.getImageData(28,0,canvas.width-56,3).data.some((v,i)=>i%4===3 && v))throw Error('SVG does not paint the native top border');
        }""")
        tab.evaluate("endSecond()")
        border.wait_for(state='detached')
        assert tab.locator('#working-fixture .am-working-save').count() == 0
        checks.append('SVG border motion preserves its shared clock, leaves interior pixels unchanged and restores the native border for Calm/Off, reduced motion and hidden panels')

        tab.evaluate("""() => {
          window.firstResult=AtelierMotion.working.begin(workPanel);
          window.secondResult=AtelierMotion.working.begin(workPanel);
          firstResult('success');
        }""")
        border.wait_for()
        assert not tab.evaluate('workPanel.dataset.amWorkingOutcome'), 'An early lease reported completion while other work remained'
        tab.evaluate("secondResult('success');secondResult('error')")
        tab.wait_for_function("workPanel.dataset.amWorkingOutcome==='success'")
        border.wait_for(state='detached')
        tab.evaluate("""() => {
          window.currentWork=true;
          window.staleResult=AtelierMotion.working.begin(workPanel,{current:()=>currentWork});
        }""")
        border.wait_for()
        tab.evaluate("currentWork=false;staleResult('success')")
        border.wait_for(state='detached')
        assert not tab.evaluate('workPanel.dataset.amWorkingOutcome')
        tab.evaluate("""() => {
          window.hiddenResult=AtelierMotion.working.begin(workPanel);
          Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
          document.dispatchEvent(new Event('visibilitychange'));hiddenResult('success');
        }""")
        border.wait_for(state='detached')
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        tab.wait_for_timeout(80)
        assert border.count() == 0, 'A result completed in the background replayed on return'
        checks.append('Concurrent work completes only after its last lease; completion is idempotent and stale or hidden results never replay a success')

        tab.evaluate("""() => {
          workPanel.setAttribute('aria-busy','true');
          window.cover=document.createElement('div');cover.className='overlay active';cover.style.zIndex='99999';
          cover.innerHTML='<section class="modal" aria-busy="true">Foreground operation</section>';document.body.append(cover);
        }""")
        tab.locator('.overlay.active .am-working-border').wait_for()
        assert border.count() == 0
        tab.evaluate('cover.remove()')
        border.wait_for()
        tab.evaluate("workPanel.remove()")
        tab.wait_for_function("!workPanel.classList.contains('am-working-border') && !workPanel.style.getPropertyValue('--am-working-frame')")
        tab.evaluate("""() => {
          window.originalSVGAnimate=window.SVGAnimateElement;
          window.SVGAnimateElement=undefined;
          document.body.append(workPanel);window.endFallback=AtelierMotion.working.begin(workPanel);
        }""")
        tab.wait_for_timeout(100)
        assert border.count() == 0
        tab.evaluate("window.SVGAnimateElement=originalSVGAnimate;endFallback();workPanel.remove()")
        checks.append('Only the foreground border animates; asymmetric corners and border widths remain exact, with safe removal and unavailable-SVG fallback')
        assert not errors, errors
    finally:
        if stored is not None:
            tab.evaluate("stored=>{for(const [key,value] of Object.entries(stored)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}", stored)
        tab.unroute_all(behavior='ignoreErrors')
        tab.close()
