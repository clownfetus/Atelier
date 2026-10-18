"""Measured outcome inks, presentation-policy migration and one large moment."""


def run_inks_dial_checks(page,context,url,report,checks):
    tab=context.new_page();errors=[];tab.on('pageerror',lambda error:errors.append(str(error)))
    stored=None
    def motion(value):
        tab.evaluate("value=>{const control=document.getElementById('settings-motion');control.value=value;control.dispatchEvent(new Event('change'));}",value)
    try:
        tab.goto(url);tab.wait_for_selector('#grid-area .card')
        stored=tab.evaluate("Object.fromEntries(['motion','adaptiveAccent','theme','appearance'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        for previous,expected in [('system','full'),('reduce','off')]:
            tab.evaluate("value=>localStorage.setItem('atelier.motion',value)",previous);tab.reload();tab.wait_for_selector('#grid-area .card')
            assert tab.evaluate("[localStorage.getItem('atelier.motion'),document.documentElement.dataset.krackle]")==[expected,expected]
        checks.append('Motion migrates system to Full and reduce to Off, preserving the legacy data-motion contract')
        for mode in ['dark','light']:
            tab.evaluate("mode=>{const picker=document.getElementById('settings-theme');picker.value=mode;picker.dispatchEvent(new Event('change'));}",mode)
            for preset in ['studio','darcula','repak','contrast','blueprint','comic']:
                tab.evaluate("preset=>document.querySelector('[data-theme-preset='+preset+']').click()",preset)
                result=tab.evaluate("""() => {
                  const root=document.documentElement,cs=getComputedStyle(root),K=AtelierKrackleInks;
                  const expected=K.defaults(cs.getPropertyValue('--bg2').trim());
                  return {surface:root.dataset.krackleSurface,expected:K.surfaceKind(cs.getPropertyValue('--bg2').trim()),
                    ok:['success','warn','fault','success-hole'].every(key=>cs.getPropertyValue('--krackle-'+key).trim()===expected[key==='success-hole'?'successHole':key])};
                }""")
                assert result['ok'] and result['surface']==result['expected'],(mode,preset,result)
            tab.evaluate("""mode=>{
              document.querySelector('[data-theme-preset=custom]').click();
              for(const [key,value] of Object.entries({background:mode==='dark'?'#101021':'#fef2eb',surface:mode==='dark'?'#252545':'#f2dddd'})){
                const control=document.querySelector('[data-theme-color='+key+']');control.value=value;control.dispatchEvent(new Event('input'));
              }
            }""",mode)
            assert tab.locator('html').get_attribute('data-krackle-surface')==mode
        checks.append('Fixed outcome inks follow measured surfaces on all six presets in both themes and custom dark/light palettes')
        tab.evaluate("""() => {
          document.querySelector('[data-theme-preset=studio]').click();
          const hero=document.getElementById('library-hero');hero.hidden=false;
          const control=document.getElementById('settings-adaptive-accent');control.checked=true;control.dispatchEvent(new Event('change'));
          window.dispatchEvent(new CustomEvent('atelier:artwork',{detail:{accent:'#ff5c9a',colors:['#ff5c9a','#2a9fd6']}}));
        }""")
        assert tab.locator('#krackle-accent-status').inner_text()=='SHIFTED'
        assert tab.evaluate("""() => {
          const host=document.getElementById('viewport-loading-motion-host'),cs=getComputedStyle(host);
          return host.dataset.krackleSurface==='dark'&&AtelierKrackleInks.contrast(cs.getPropertyValue('--krackle-charge'),'#14161b')>=3;
        }""")
        tab.evaluate("document.getElementById('library-hero').hidden=true;window.dispatchEvent(new Event('atelier:preferences'))")
        assert tab.locator('#krackle-accent-status').get_attribute('hidden') is not None
        assert tab.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--krackle-charge').trim()")=='#2693c6'
        checks.append('Adaptive inks are guarded only in hero/skin context; SHIFTED is visible and the dark model-loader surface keeps readable inks')
        motion('full')
        result=tab.evaluate("""() => {
          const arbiter=AtelierMotion.moment,a=arbiter.claim('fixture',2),b=arbiter.claim('fixture-second',2);
          a?.();const c=arbiter.claim('fixture-event',3);c?.();const d=arbiter.claim('fixture-event',3);
          return [!!a,b===null,!!c,d===null];
        }""")
        assert result==[True]*4,result
        tab.evaluate("""() => {
          const root=document.createElement('div');root.id='ink-stage-fixture';root.style='position:fixed;top:80px;left:320px;z-index:1000;display:flex;background:var(--bg2)';document.body.append(root);
          window.inkStages=[1,2].map(()=>{const host=document.createElement('div');root.append(host);return AtelierMotion.krackleStage.mount(host,{state:'busy',size:156});});
        }""")
        tab.wait_for_function("document.querySelectorAll('#ink-stage-fixture [data-am-micro=true]').length===1")
        tab.wait_for_timeout(150)
        for value,tier in [('calm',1),('off',0)]:
            motion(value)
            assert tab.evaluate('AtelierMotionPolicy.tier()')==tier
            tab.wait_for_function("[...document.querySelectorAll('#ink-stage-fixture [data-atelier-motion=krackle-stage]')].every(n=>n.dataset.amSleeping==='true')")
            frames=tab.evaluate('inkStages.map(s=>s.frames())');tab.wait_for_timeout(180)
            assert tab.evaluate('inkStages.map(s=>s.frames())')==frames
        tab.evaluate("inkStages.forEach(s=>s.destroy());document.getElementById('ink-stage-fixture').remove()")
        motion('full');tab.bring_to_front();tab.emulate_media(reduced_motion='reduce')
        tab.wait_for_timeout(100)
        state=tab.evaluate("[AtelierMotionPolicy.mode(),AtelierMotionPolicy.tier(),document.documentElement.dataset.motion]")
        assert state==['off',0,'reduce'],(state,errors)
        assert 'System reduced motion' in tab.locator('#settings-motion + [data-motion-note]').inner_text()
        tab.emulate_media(reduced_motion='no-preference')
        checks.append('The arbiter refuses simultaneous large stages, shows a micro fallback, and permits each Tier 3 event only once per session')
        checks.append('Calm and Off stop particle drawing; OS reduced motion forces Off and is explained beside the dial')
        for mode in ['dark','light']:
            tab.evaluate("mode=>{const p=document.getElementById('settings-theme');p.value=mode;p.dispatchEvent(new Event('change'));document.querySelector('[data-theme-preset=studio]').click();_pathsMode=true;_applySetupMode();_setSetupLoading(false);document.getElementById('setup-overlay').classList.add('active');}",mode)
            tab.locator('#settings-motion').scroll_into_view_if_needed()
            tab.screenshot(path=str(report/f'inks-dial-{mode}.png'),animations='disabled')
        assert not errors,errors
    finally:
        if stored is not None:
            tab.evaluate("values=>{for(const [key,value] of Object.entries(values)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
