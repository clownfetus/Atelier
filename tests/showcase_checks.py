"""Toon display restoration, client-only cards and opt-in audio with synthetic geometry."""
from pathlib import Path
from io import BytesIO


def run_showcase_checks(page,context,url,report,checks):
    from viewport_inspection_checks import HOOK
    from PIL import Image
    root=Path(__file__).resolve().parents[1]
    tab=context.new_page();errors=[];writes=[];stored=None
    tab.on('pageerror',lambda error:errors.append(str(error)))
    tab.on('request',lambda request:writes.append(request.url) if request.method=='POST' and any(endpoint in request.url for endpoint in ['/api/material_save','/api/project/save','/api/asset_opts','/api/replace_texture']) else None)
    source=(root/'gui/viewport.js').read_text(encoding='utf-8')+HOOK+"""
window.__showcase={
  watch(){window.__renderTypes=[];const native=renderer.render.bind(renderer);renderer.render=(s,c)=>{if(s===scene)modelRoot.traverse(o=>{if(o.isMesh)__renderTypes.push(...(Array.isArray(o.material)?o.material:[o.material]).map(m=>m.type));});return native(s,c);};
    this.refs=[];modelRoot.traverse(o=>{if(o.isMesh)this.refs.push([o,o.material]);});},
  snapshot:()=>JSON.stringify(Object.values(matsByName).flat().map(m=>m.toJSON())),
  restored(){return this.refs.every(([mesh,material])=>mesh.material===material);},
  poster:()=>inspection.cardPoster(),
  failedPoster(){const native=renderer.render;renderer.render=()=>{throw Error('Fixture renderer failure');};try{inspection.cardPoster();return false;}catch(_){return this.restored();}finally{renderer.render=native;}},
};
"""
    tab.route('**/static/viewport.js',lambda route:route.fulfill(body=source,content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*',lambda route:route.fulfill(json=[{'name':'Body fixture','game_rel':'Characters/1029/1029001/Meshes/Body'}]))
    tab.route('**/api/skin_materials',lambda route:route.fulfill(json={'ok':True,'materials':{name:{'game_rel':'Characters/1029/1029001/Materials/'+name,'colors':[{'name':'Tint','rgba':[.6,.2,.15,1]}],'scalars':[],'textures':{}} for name in ['MI_Body','MI_Hair_01','MI_Hair_02']}}))
    tab.route('**/api/browse_material_dirs?*',lambda route:route.fulfill(json={'dirs':[]}))
    tab.route('**/api/idle_animations?*',lambda route:route.fulfill(json={'ok':True,'animations':[]}))
    output=BytesIO();Image.new('RGB',(128,180),'#cb4e86').save(output,'PNG');art=output.getvalue()
    tab.route('**/api/catalogue/thumbnail/*',lambda route:route.fulfill(body=art,content_type='image/png'))
    tab.add_init_script("""(() => {
      window.__audio={created:0,started:0,suspended:0};
      class Audio {
        constructor(){__audio.created++;this.state='running';this.currentTime=0;this.sampleRate=8000;this.destination={};}
        resume(){this.state='running';return Promise.resolve();}suspend(){this.state='suspended';__audio.suspended++;return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}
        createGain(){return {gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}};}
        createOscillator(){return {frequency:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){},start(){__audio.started++;},stop(){this.onended?.();}};}
        createBuffer(){return {getChannelData:()=>new Float32Array(1120)};}createBufferSource(){return this.createOscillator();}
      }window.AudioContext=Audio;
    })()""")
    def motion(value):tab.evaluate("value=>{const p=document.getElementById('settings-motion');p.value=value;p.dispatchEvent(new Event('change'));}",value)
    try:
        tab.goto(url);tab.wait_for_selector('#grid-area .card')
        stored=tab.evaluate("Object.fromEntries(['motion','foley','theme'].map(key=>['atelier.'+key,localStorage.getItem('atelier.'+key)]))")
        tab.evaluate("AtelierViewport.open('1029001','Synthetic Showcase fixture')")
        tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none'&&document.querySelectorAll('.vp-mat').length>0")
        tab.wait_for_timeout(500);tab.evaluate('__showcase.watch();__inspection.swapMap([120,70,160])')
        baseline=tab.evaluate('__showcase.snapshot()')
        for value in ['full','calm','off']:
            motion(value);tab.locator('#viewport-showcase').click();tab.wait_for_timeout(80)
            assert tab.evaluate('__inspection.presentation().showcase')
            assert tab.evaluate("__renderTypes.includes('MeshToonMaterial')")
            assert tab.locator('.vp-showcase-backdrop').is_visible()
            tab.locator('#viewport-inspect').click();tab.wait_for_timeout(50)
            assert tab.evaluate('__showcase.restored()') and tab.evaluate('__showcase.snapshot()')==baseline
        assert not writes,writes
        checks.append('Showcase renders disposable toon materials in Full/Calm/Off, then restores the exact source material objects and serialized values without project writes')
        def setting(id,value,event='change'):
            tab.evaluate('([id,value,event])=>{const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event(event));}',[id,value,event])
        tab.locator('#viewport-inspect').click()
        inspect_grid=tab.evaluate('__inspection.presentation().grid')
        tab.locator('#viewport-showcase').click()
        showcase_grid=tab.evaluate('__inspection.presentation().grid')
        tab.locator('#viewport-grid').evaluate('e=>e.click()')
        assert tab.evaluate('__inspection.presentation().grid')!=showcase_grid
        tab.locator('#viewport-inspect').click()
        assert tab.evaluate('__inspection.presentation().grid')==inspect_grid
        tab.locator('#viewport-showcase').click()
        assert tab.evaluate('__inspection.presentation().grid')!=showcase_grid
        tab.locator('#viewport-grid').evaluate('e=>e.click()')
        for id in ('viewport-wireframe','viewport-regions','viewport-edited','viewport-original','viewport-wipe'):
            assert tab.locator('#'+id).is_disabled()
            assert 'Inspect' in tab.locator('#'+id).get_attribute('title')
        setting('viewport-backdrop','solid');setting('viewport-backdrop-color','#35594d','input')
        assert not tab.locator('.vp-showcase-backdrop').count()
        assert tab.locator('#viewport-stage').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(53, 89, 77)'
        for value in ('flat','emissive','studio'):setting('viewport-lighting',value)
        tab.locator('#viewport-bloom').evaluate('e=>e.click()');tab.wait_for_timeout(60)
        assert tab.evaluate('__inspection.presentation().targets')==3
        tab.locator('#viewport-bloom').evaluate('e=>e.click()')
        assert tab.evaluate('__inspection.presentation().targets')==0
        setting('viewport-backdrop','gradient')
        checks.append('Showcase settings preserve separate Inspect/Showcase grids, expose a solid backdrop, apply lighting and bloom, and explain disabled comparison/wireframe/dye controls')
        for theme in ['dark','light']:
            tab.evaluate("theme=>{const p=document.getElementById('settings-theme');p.value=theme;p.dispatchEvent(new Event('change'));}",theme)
            tab.locator('#viewport-showcase').click();tab.screenshot(path=str(report/f'showcase-{theme}.png'),animations='disabled')
        tab.locator('#viewport-inspect').click()
        before=tab.evaluate('__inspection.state()');tab.evaluate('window.cardPoster=__showcase.poster()');after=tab.evaluate('__inspection.state()')
        assert before['materials']==after['materials'] and tab.evaluate('__showcase.restored()')
        assert tab.evaluate('[cardPoster.width,cardPoster.height]')==[1000,1000]
        assert all(abs(a-b)<1e-10 for a,b in zip(before['position'],after['position']))
        assert tab.evaluate('__showcase.failedPoster()') and tab.evaluate('__showcase.snapshot()')==baseline
        tab.evaluate("""() => {
          const host=document.createElement('div');host.id='no-canvas-card';document.body.append(host);
          const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=()=>null;
          try{window.disposeNoCanvas=AtelierModCards.mount(host,{project:'Smoke A',modName:'Fallback',included:[{skin_id:'1029001'}]},{ok:true,applied:[],skipped:[]});}finally{HTMLCanvasElement.prototype.getContext=original;}
        }""")
        tab.wait_for_timeout(50);assert not tab.locator('#no-canvas-card .mod-card').count()
        tab.evaluate('disposeNoCanvas();document.getElementById("no-canvas-card").remove()')
        tab.evaluate("const native=Element.prototype.animate;Element.prototype.animate=()=>{throw Error('No WAAPI');};try{document.getElementById('viewport-showcase').click();document.getElementById('viewport-inspect').click();}finally{Element.prototype.animate=native;}")
        assert tab.evaluate('__audio.created')==0 and not tab.evaluate('AtelierFoley.enabled()')
        motion('full')
        tab.evaluate("const c=document.getElementById('settings-foley');c.checked=true;c.dispatchEvent(new Event('change'));document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));")
        motion('full')
        tab.evaluate("window.soundHost=document.createElement('div');soundHost.style='position:fixed;top:120px;left:350px;z-index:9999';document.body.append(soundHost);window.soundStage=AtelierMotion.krackleStage.mount(soundHost,{state:'busy',size:156});soundStage.setState('success');soundStage.setState('error')")
        assert tab.evaluate('__audio.started')==3,tab.evaluate('({audio:__audio,micro:soundHost.dataset.amMicro,sleeping:soundHost.dataset.amSleeping})')
        for value in ['calm','off']:
            motion(value);assert tab.evaluate("AtelierFoley.play('pop')") is False
        motion('full');tab.emulate_media(reduced_motion='reduce');assert tab.evaluate("AtelierFoley.play('drop')") is False
        tab.emulate_media(reduced_motion='no-preference');motion('full')
        tab.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
        assert tab.evaluate("AtelierFoley.play('splat')") is False
        tab.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));soundStage.destroy();soundHost.remove();document.getElementById('settings-foley').checked=false;document.getElementById('settings-foley').dispatchEvent(new Event('change'))")
        checks.append('Formation sounds create no audio by default; opt-in drop/pop/splat synthesis follows actual stage transitions and stays silent in Calm, Off, OS reduced motion and hidden documents')
        tab.evaluate("""() => {
          window.cardReveal=0;window.cardSnapshot={project:'Smoke A',modName:'Fixture <card>',included:[{game_rel:'Characters/1029/1029001/Textures/T_A',file_type:'texture',name:'T_A'}],excluded:[],skipped:0,copyToMods:false,protected:false};
          const callbacks={confirm(){},refresh(){},settings(){},reveal(){cardReveal++;}};
          AtelierExportReview.open(cardSnapshot,callbacks);AtelierExportReview.finish(cardSnapshot,{ok:true,applied:['tex T_A','tex T_B','mat MI_Body','combined 2 containers into one pak'],skipped:[]});
        }""")
        tab.wait_for_selector('.mod-card');tab.evaluate('AtelierViewport.close()');tab.locator('.mod-card summary').click()
        assert tab.locator('.mod-card-stats').inner_text()=='3 assets · 2 textures · 1 material',tab.locator('.mod-card-stats').text_content()
        assert tab.locator('.mod-card p',has_text='Showcase capture').count()==1
        tab.locator('.mod-card button',has_text='Open export folder').click();assert tab.evaluate('cardReveal')==1
        with tab.expect_download() as download:tab.locator('.mod-card button',has_text='Save PNG').click()
        download.value.save_as(str(report/'mod-card.png'))
        tab.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>window.copiedTypes=items[0].types}})")
        tab.locator('.mod-card button',has_text='Copy image').click();tab.wait_for_function("window.copiedTypes?.includes('image/png')")
        tab.evaluate("AtelierExportReview.finish(cardSnapshot,{ok:true,applied:['tex T_A'],skipped:['T_B failed']})")
        tab.wait_for_selector('.mod-card[data-warning=true]');assert '1 skipped' in tab.locator('.mod-card-stats').text_content()
        tab.evaluate("AtelierExportReview.finish(cardSnapshot,{ok:false,error:'Fixture build failure',applied:[],skipped:[]})")
        tab.wait_for_timeout(150);assert not tab.locator('.mod-card').count()
        checks.append('Mod cards use completed applied counts, a matching Showcase capture and local build version/date; copy/save/reveal work, warnings carry skipped counts and failed builds offer no card')
        tab.keyboard.press('Escape')
        tab.evaluate("AtelierViewport.open('1029001','Synthetic Showcase fixture')");tab.wait_for_function("document.getElementById('viewport-loading').style.display==='none'")
        assert not tab.evaluate('__inspection.presentation().showcase')
        assert not writes and not errors,(writes,errors)
        checks.append('Showcase is session presentation only: reopening returns to Inspect and captures preserve the camera and editable source materials')
    finally:
        if stored is not None:tab.evaluate("values=>{for(const [key,value] of Object.entries(values)){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,value);}}",stored)
        tab.close()
