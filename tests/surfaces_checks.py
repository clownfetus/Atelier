"""Wave 4b: real UI entry points, byte uploads, policy gates and frame costs."""
import json
from pathlib import Path
from io import BytesIO


def run_surfaces_checks(page,context,url,report,checks):
    from PIL import Image
    tab=context.new_page();errors=[];tab.on('pageerror',lambda error:errors.append(str(error)))
    stored=None;uploads=[]
    output=BytesIO();Image.new('RGB',(8,8),'#3b70b8').save(output,'PNG');png=output.getvalue()
    def mode(value):
        tab.evaluate("value=>{const c=document.getElementById('settings-motion');c.value=value;c.dispatchEvent(new Event('change'));}",value)
    try:
        tab.goto(url);tab.wait_for_selector('#grid-area .card')
        stored=tab.evaluate("Object.fromEntries(['motion','theme','appearance'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        assert tab.evaluate("document.fonts.load('650 24px \"Bricolage Grotesque\"').then(f=>f.length>0)")
        assert tab.locator('#explorer').evaluate('el=>getComputedStyle(el).borderRadius')=='6px'
        assert 'Mod tray' in tab.locator('#sidebar-header').inner_text()
        assert 'Build mod' in tab.locator('#install-btn').inner_text()
        tab.evaluate("document.getElementById('toast-area').replaceChildren();toast('Caption fixture','success',60000);for(let i=0;i<4;i++)toast('Caption fixture','success',60000)")
        assert tab.locator('.toast-repeat').inner_text()=='×5'
        assert tab.locator('.toast-repeat').evaluate("n=>getComputedStyle(n).fontSize")=='0px'
        tab.evaluate("toast('Caption fixture','success',60000)")
        assert tab.locator('.toast-repeat-number').inner_text()=='×6'
        for theme in ['dark','light']:
            tab.evaluate("theme=>{const p=document.getElementById('settings-theme');p.value=theme;p.dispatchEvent(new Event('change'));}",theme)
            assert tab.locator('.toast').evaluate("n=>[getComputedStyle(n).backgroundColor,getComputedStyle(n).color]")==['rgb(238, 229, 207)','rgb(18, 18, 22)']
            tab.screenshot(path=str(report/f'surfaces-caption-{theme}.png'),animations='disabled')
        checks.append('Local Latin display lettering loads; panels use 6px roles; Mod tray captions keep Ink text on Paper and repeats use five bubbles then a number')
        tab.evaluate("document.getElementById('toast-area').replaceChildren();window.replaced=[];window.oldRefresh=refreshEditedTexture;refreshEditedTexture=(...args)=>replaced.push(args);nav={path:'Texture fixture'};buildGrid([_makeCard({type:'asset',name:'T_Fixture',file_type:'texture',game_rel:'Fixture/T_Fixture'})]);")
        def replace(route):
            uploads.append((route.request.headers.get('x-atelier-project'),route.request.post_data_buffer))
            route.fulfill(json={'ok':True,'token':'fixture-token'})
        tab.route('**/api/replace_texture',replace)
        def drop(name,mime,bytes_):
            tab.evaluate("""([name,mime,bytes])=>{
              const card=document.querySelector('#grid-area .card'),transfer=new DataTransfer();
              transfer.items.add(new File([new Uint8Array(bytes)],name,{type:mime}));
              card.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));
              window.poolRect=card.getBoundingClientRect().toJSON();window.hadPool=card.classList.contains('k-texture-pool');
              card.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
            }""",[name,mime,list(bytes_)])
        for index,value in enumerate(['full','calm','off']):
            mode(value);drop('replacement.png','image/png',png)
            tab.wait_for_function('expected=>replaced.length===expected',arg=index+1)
            assert tab.evaluate('hadPool') and not tab.locator('.k-texture-pool').count()
        assert len(uploads)==3 and all(header=='Smoke%20A' and png in body for header,body in uploads)
        assert tab.evaluate('replaced.length')==3
        drop('unsafe.txt','text/plain',b'not an image');tab.wait_for_timeout(80)
        assert len(uploads)==3 and 'image file' in tab.locator('.toast.warning').last.inner_text()
        tab.evaluate('refreshEditedTexture=oldRefresh')
        checks.append('Image drops in Full/Calm/Off upload File bytes with the originating project header and use the existing refresh; non-images send no request')
        tab.evaluate("_renderProjectPicker([],false);document.getElementById('project-overlay').classList.add('active')")
        for value in ['full','calm','off']:
            mode(value);tab.locator('.k-project-drop:not(.k-project-fall)').click();tab.wait_for_selector('#proj-name-overlay.active')
            assert tab.locator('#proj-name-input').input_value()==''
            tab.locator('#proj-name-cancel').click()
        tab.evaluate("document.getElementById('project-overlay').classList.remove('active')")
        checks.append('The hanging No projects drop opens the original New Project dialog immediately in all dial modes')
        mode('full')
        tab.evaluate("""async()=>{
          await document.querySelector('.studio-brand > img').decode();
          const splash=document.createElement('div');splash.id='startup-splash';splash.style='position:fixed;top:80px;left:300px;z-index:1000;background:var(--bg2)';splash.innerHTML='<img><span>Reading containers</span><progress id="startup-progress" max="10" value="2"></progress>';document.body.append(splash);
          AtelierSurfaces.startupProgress({total:10,current:2});
        }""")
        tab.wait_for_function("document.querySelector('.k-startup-stage')?.dataset.amSleeping==='false'")
        assert tab.locator('#startup-splash').get_attribute('data-launch')=='true'
        tab.evaluate('AtelierSurfaces.startupProgress({total:10,current:7})')
        assert '7 of 10' in tab.locator('.k-startup-stage').get_attribute('aria-label')
        mode('calm');assert not tab.locator('.k-startup-stage').is_visible()
        tab.evaluate("AtelierSurfaces.startupDone();document.getElementById('startup-splash').remove()")
        mode('full')
        tab.evaluate("window.perfHost=document.createElement('div');perfHost.style='position:fixed;top:100px;left:300px;z-index:1000';document.body.append(perfHost);window.perfStage=AtelierMotion.krackleStage.mount(perfHost,{state:'busy',size:224})")
        tab.wait_for_timeout(1800)
        perf=tab.evaluate('perfStage.perf()');(report/'krackle-frame-perf.json').write_text(json.dumps(perf,indent=2))
        assert perf['samples']>=10 and perf['medianMs']<8,perf
        print(f"Krackle frame CPU median: {perf['medianMs']:.2f} ms ({perf['samples']} samples; filter={perf['filter']})",flush=True)
        for value in ['calm','off']:
            mode(value);tab.wait_for_function("perfHost.dataset.amSleeping==='true'")
            frames=tab.evaluate('perfStage.frames()');tab.wait_for_timeout(120);assert frames==tab.evaluate('perfStage.frames()')
        mode('full');tab.emulate_media(reduced_motion='reduce');tab.wait_for_timeout(100)
        assert tab.evaluate('AtelierMotionPolicy.tier()')==0
        tab.evaluate('perfStage.destroy();perfHost.remove()');tab.emulate_media(reduced_motion='no-preference')
        mode('full')
        fallback=tab.evaluate("""() => {
          const nativeRAF=requestAnimationFrame,nativeCancel=cancelAnimationFrame;let next;
          window.requestAnimationFrame=fn=>{next=fn;return 987654;};window.cancelAnimationFrame=()=>{};
          const host=document.createElement('div');document.body.append(host);let stage;
          try{stage=AtelierMotion.krackleStage.mount(host,{state:'busy',size:156});let now=100;
            for(let i=0;i<30;i++){const fn=next;now+=i<10?8:40;fn(now);}return stage.perf();
          }finally{stage?.destroy();host.remove();window.requestAnimationFrame=nativeRAF;window.cancelAnimationFrame=nativeCancel;}
        }""")
        assert fallback['filter'] is False,fallback
        checks.append('Launch energy follows real progress; particle batches stay below 8ms median CPU, sleep in Calm/Off and disable merging when real frame intervals exceed the measured refresh baseline')
        mode('full')
        tab.evaluate("window.openedDrop=0;AtelierSurfaces.updateDrop('fixture',()=>openedDrop++)")
        tab.locator('.k-update-drop').click();assert tab.evaluate('openedDrop')==1
        tab.evaluate("window.actionCount=0;window.popButton=document.createElement('button');popButton.className='btn primary';popButton.textContent='Immediate fixture';popButton.style='position:fixed;top:80px;left:300px;z-index:1000';popButton.onclick=()=>actionCount++;document.body.append(popButton)")
        for value in ['full','calm','off']:
            mode(value);tab.locator('button',has_text='Immediate fixture').click();assert tab.evaluate('actionCount')==['full','calm','off'].index(value)+1
            if value!='full':assert not tab.locator('.k-button-pop').count()
            tab.wait_for_timeout(230)
        tab.evaluate('popButton.remove()')
        tab.evaluate("""() => {
          window.buildDone=beginExportFeedback(atelierProject());
          const host=document.getElementById('install-btn-motion-host');
          if(host.dataset.amState!=='busy')throw Error('Build did not charge');
          buildDone('warning');if(host.dataset.amState!=='warning')throw Error('Result did not interrupt the drop');
          const splash=document.createElement('div');splash.id='startup-splash';splash.innerHTML='<progress id="startup-progress" max="10" value="2"></progress>';document.body.append(splash);
          const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=()=>null;
          try{AtelierSurfaces.startupProgress({total:10,current:2});if(splash.querySelector('canvas'))throw Error('Canvas fallback lost');}finally{HTMLCanvasElement.prototype.getContext=original;AtelierSurfaces.startupDone();splash.remove();}
          const animate=Element.prototype.animate;Element.prototype.animate=()=>{throw Error('No WAAPI fixture');};
          try{AtelierSurfaces.updateDrop('fallback',()=>window.fallbackOpened=true);}finally{Element.prototype.animate=animate;}
        }""")
        tab.locator('.k-update-drop').click();assert tab.evaluate('fallbackOpened')
        tab.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        assert not tab.locator('.k-button-pop,.k-project-fall').count()
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        checks.append('Real results interrupt the Build drop immediately; missing Canvas/WAAPI retain usable controls and hidden documents dispose transient bubbles')
        assert tab.evaluate("!AtelierCategoryEmblems.enabled()&&Object.keys(AtelierCategoryEmblems.names).length===36")
        checks.append('Update drops stay nonblocking; primary actions fire immediately while bubbles are Full-only; the 36 category candidates remain disabled pending D4 review')
        review=context.new_page()
        try:
            review.set_viewport_size({'width':1320,'height':1100});review.set_content((Path(__file__).resolve().parents[1]/'docs/review/wave-4b/category-emblems.html').read_text(encoding='utf-8'))
            for theme in ['light','dark']:
                review.evaluate("theme=>document.body.classList.toggle('dark',theme==='dark')",theme);review.screenshot(path=str(report/f'category-emblems-{theme}.png'),full_page=True)
        finally:review.close()
        assert not errors,errors
    finally:
        if stored is not None:tab.evaluate("values=>{for(const [key,value] of Object.entries(values)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
