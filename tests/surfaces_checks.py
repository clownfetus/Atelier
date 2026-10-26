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
        tab.evaluate("document.getElementById('toast-area').replaceChildren();window.replaced=[];window.oldRefresh=refreshEditedTexture;refreshEditedTexture=(...args)=>replaced.push(args);nav={path:'Texture fixture'};buildGrid([_makeCard({type:'asset',name:'T_Fixture',file_type:'texture',game_rel:'Fixture/T_Fixture',imported:true}),_makeCard({type:'asset',name:'T_Plain',file_type:'texture',game_rel:'Fixture/T_Plain'})]);")
        def replace(route):
            uploads.append((route.request.headers.get('x-atelier-project'),route.request.post_data_buffer))
            route.fulfill(json={'ok':True,'token':'fixture-token'})
        tab.route('**/api/replace_texture',replace)
        def drop(name,mime,bytes_,label='T_Fixture'):
            tab.evaluate("""([name,mime,bytes,label])=>{
              const card=[...document.querySelectorAll('#grid-area .card')].find(node=>node._libraryCard.label===label),transfer=new DataTransfer();
              transfer.items.add(new File([new Uint8Array(bytes)],name,{type:mime}));
              const over=new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer});card.dispatchEvent(over);
              window.poolRect=card.getBoundingClientRect().toJSON();window.hadPool=card.classList.contains('k-texture-pool');
              window.overPrevented=over.defaultPrevented;window.overEffect=transfer.dropEffect;
              card.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
            }""",[name,mime,list(bytes_),label])
        drop('replacement.png','image/png',png,'T_Plain');tab.wait_for_timeout(80)
        assert tab.evaluate('overPrevented') and tab.evaluate('overEffect')=='none' and not tab.evaluate('hadPool')
        assert not uploads and not tab.locator('#atelier-confirm').count()
        assert 'Edit this texture first' in tab.locator('.toast').last.inner_text()
        drop('replacement.png','image/png',png);tab.locator('#atelier-confirm-cancel').click();tab.wait_for_timeout(80)
        assert not uploads and tab.evaluate('replaced.length')==0
        for index,value in enumerate(['full','calm','off']):
            mode(value);drop('replacement.png','image/png',png)
            assert 'T_Fixture' in tab.locator('#atelier-confirm-body').inner_text()
            tab.locator('#atelier-confirm-ok').click()
            tab.wait_for_function('expected=>replaced.length===expected',arg=index+1)
            assert tab.evaluate('hadPool') and not tab.locator('.k-texture-pool').count()
        assert len(uploads)==3 and all(header=='Smoke%20A' and png in body for header,body in uploads)
        assert tab.evaluate('replaced.length')==3
        drop('unsafe.txt','text/plain',b'not an image');tab.wait_for_timeout(80)
        assert len(uploads)==3 and not tab.locator('#atelier-confirm').count()
        assert 'image file' in tab.locator('.toast.warning').last.inner_text()
        tab.evaluate('refreshEditedTexture=oldRefresh')
        checks.append('Unedited textures refuse image drops; an edited texture asks before replacing, Cancel keeps it, and confirmed drops in Full/Calm/Off upload File bytes with the originating project header and the existing refresh; non-images send no request')
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
            if value!='full':assert not tab.locator('.k-workflow-svg[data-workflow-trigger=action],.k-workflow-link').count()
            else:
                # The receiving SVG may wait for a finite native entrance before measuring its edges.
                tab.wait_for_selector('.k-workflow-svg[data-workflow-trigger=action]')
                assert tab.locator('.k-workflow-svg[data-workflow-trigger=action]').count()==1
                assert not tab.locator('.k-workflow-canvas').count()
            tab.wait_for_function("!document.querySelector('.k-workflow-svg,.k-workflow-link')")
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
        mode('full');tab.locator('button',has_text='Immediate fixture').click()
        tab.wait_for_selector('.k-workflow-svg[data-workflow-trigger=action]')
        tab.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        assert not tab.locator('.k-workflow-svg,.k-workflow-link,.k-workflow-canvas,.k-project-fall').count()
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));popButton.remove()")
        checks.append('Real results interrupt the Build drop immediately; missing Canvas/WAAPI retain usable controls and hidden documents dispose active SVG gestures and connections')
        assert tab.evaluate("Object.keys(AtelierCategoryEmblems.names).length===36")
        checks.append('Update drops stay nonblocking; primary actions fire immediately while SVG edge gestures are Full-only; all 36 category emblems are available')
        escaped=tab.evaluate("""() => {
          const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),out=[];svg.setAttribute('viewBox','0 0 24 24');document.body.append(svg);
          try{for(const cls of Object.keys(AtelierCategoryEmblems.names))for(const scale of [24,102]){
            svg.innerHTML=AtelierCategoryEmblems.markup(cls,scale);
            for(const shape of svg.querySelectorAll('.k-category-emblem-energy > *')){
              const length=shape.getTotalLength();
              for(let i=0;i<=400;i++){const p=shape.getPointAtLength(length*i/400);if(Math.min(p.x,p.y)<-.01||Math.max(p.x,p.y)>24.01){out.push([cls,scale,p.x,p.y]);break;}}
            }
          }}finally{svg.remove();}
          return out;
        }""")
        assert not escaped,escaped
        tab.evaluate("document.querySelector('[data-theme-preset=studio]').click();nav={path:'Emblem fixture'};buildGrid(['Characters','Weapons'].map(name=>_makeCard({type:'folder',name,rel_path:'Emblem fixture/'+name})))")
        assert tab.evaluate("new Set(Object.values(AtelierCategoryEmblems.inks)).size===36")
        def emblem_inks():
            return tab.evaluate("""() => [...document.querySelectorAll('#grid-area .card svg.card-icon')].map(svg=>{
              const energy=getComputedStyle(svg.querySelector('.k-category-emblem-energy > *')).fill,probe=document.createElement('i');
              const cls=Object.keys(AtelierCategoryEmblems.names).find(name=>svg.classList.contains(name));
              svg.after(probe);probe.style.color='var(--k-emblem-'+cls+')';const ink=getComputedStyle(probe).color;
              probe.style.color='var(--krackle-charge-raised)';const raised=getComputedStyle(probe).color;probe.remove();
              const against=node=>AtelierKrackleInks.contrast(energy,getComputedStyle(node).backgroundColor);
              // The card body is --bg2 and the thumb behind the emblem --bg3; each ink is fitted to both.
              return {cls,energy,ink,raised,bubbles:svg.querySelectorAll('mask .k-category-emblem-bubbles > circle').length,
                contrast:against(svg.closest('.card')),thumbContrast:against(svg.closest('.card-thumb')),
                card:getComputedStyle(svg.closest('.card')).backgroundColor,thumb:getComputedStyle(svg.closest('.card-thumb')).backgroundColor,
                mask:svg.querySelector('mask').id,masked:svg.querySelector('.k-category-emblem-energy').getAttribute('mask')};
            })""")
        energy={};thumbs={};surfaces={}
        tab.mouse.move(0,0)  # A hovered card paints --bg3; measure the resting card.
        # Theme colours can transition independently on the card and thumbnail.
        # Contrast describes the selected settled palette, not an intermediate frame.
        settled="surface=>{const card=document.querySelector('#grid-area .card'),probe=document.createElement('i');probe.style.color='var('+surface+')';card.append(probe);const color=getComputedStyle(probe).color;probe.remove();return getComputedStyle(card).backgroundColor===color;}"
        for theme in ['light','dark']:
            tab.evaluate("theme=>{const p=document.getElementById('settings-theme');p.value=theme;p.dispatchEvent(new Event('change'));}",theme)
            tab.wait_for_function(settled,arg='--bg2')
            inks=emblem_inks()
            assert len(inks)==2 and len({ink['mask'] for ink in inks})==2 and inks[0]['energy']!=inks[1]['energy'],inks
            for ink in inks:
                assert ink['energy']==ink['ink'] and ink['bubbles'],(theme,ink)
                assert ink['contrast']>=3 and ink['thumbContrast']>=3,(theme,ink)
                assert ink['masked']==f"url(#{ink['mask']})",ink
            energy[theme]=inks[0]['energy'];thumbs[theme]=round(inks[0]['thumbContrast'],2);surfaces[theme]=[inks[0]['card'],inks[0]['thumb']]
            tab.locator('#grid-area .grid').screenshot(path=str(report/f'category-emblems-app-{theme}.png'),animations='disabled')
            # Hovered, the body paints --bg3, so its edited corner takes the raised charge; the emblem keeps its ink.
            card=tab.locator('#grid-area .card').first;card.evaluate("node=>node.classList.add('imported')");card.hover()
            tab.wait_for_function(settled,arg='--bg3')
            hovered=tab.evaluate("""() => {const card=document.querySelector('#grid-area .card'),corner=getComputedStyle(card,'::after').backgroundColor;
              return {corner,contrast:AtelierKrackleInks.contrast(corner,getComputedStyle(card).backgroundColor),energy:getComputedStyle(card.querySelector('.k-category-emblem-energy > *')).fill};}""")
            card.evaluate("node=>node.classList.remove('imported')");tab.mouse.move(0,0);tab.wait_for_function(settled,arg='--bg2')
            assert hovered['corner']==inks[0]['raised'] and hovered['energy']==inks[0]['energy'] and hovered['contrast']>=3,(theme,hovered)
        assert energy['light']==energy['dark'],energy  # Studio inks read in both themes, so an emblem keeps its colour.
        (report/'category-emblem-inks.json').write_text(json.dumps({'energy':energy,'thumbContrast':thumbs},indent=2))
        print(f"Category emblem energy on card thumbs: light {thumbs['light']}:1, dark {thumbs['dark']}:1",flush=True)
        tab.evaluate("document.getElementById('grid-area').style.setProperty('--k-emblem-char-icon','#7a4cd9')")
        assert [ink['energy'] for ink in emblem_inks() if ink['cls']=='char-icon']==['rgb(122, 76, 217)']
        tab.evaluate("document.getElementById('grid-area').style.removeProperty('--k-emblem-char-icon')")
        checks.append('By default, card emblems are inlined with unique mask ids; each of the 36 categories has its own ink (3:1 on light and dark thumbs and cards, local overrides), bubbles are cut through it, a hovered card\'s edited corner takes the raised charge at 3:1 on --bg3, and all 36 silhouettes stay inside the 24-unit box')
        review=context.new_page()
        try:
            review.set_viewport_size({'width':1320,'height':1100});review.set_content((Path(__file__).resolve().parents[1]/'docs/review/wave-4b/category-emblems.html').read_text(encoding='utf-8'))
            for theme in ['light','dark']:
                review.evaluate("theme=>document.body.classList.toggle('dark',theme==='dark')",theme)
                sheet=review.evaluate("""() => {const tile=document.querySelector('article div'),cs=getComputedStyle;
                  return [cs(tile.closest('article')).backgroundColor,cs(tile).backgroundColor,cs(tile.querySelector('.k-category-emblem-energy > *')).fill];}""")
                assert sheet==[*surfaces[theme],energy[theme]],('review sheet differs from Studio cards',theme,sheet,surfaces[theme],energy[theme])
                review.screenshot(path=str(report/f'category-emblems-{theme}.png'),full_page=True)
        finally:review.close()
        checks.append('The category review sheet draws emblems on the Studio card and thumb surfaces with the same fitted ink as the app, in both themes')
        assert not errors,errors
    finally:
        if stored is not None:tab.evaluate("values=>{for(const [key,value] of Object.entries(values)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
