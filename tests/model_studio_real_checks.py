"""Opt-in real-model checks against an independently configured development app.

Run with --url, --skin (repeatable) and --report-dir. Native work is requested
through that app's API; this script never launches a native asset tool or installs
a mod. --export writes only to the app's configured export folder.
"""
import argparse
import asyncio
import json
import io
from pathlib import Path
from playwright.async_api import async_playwright
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
HOOK=r"""
const studioPoint=joint=>new THREE.Vector3().setFromMatrixPosition(joint.node.matrixWorld.clone().multiply(joint.inverseExported).multiply(joint.physical));
window.__studio={
  ready:()=>!modelLoading&&!materialTask&&!animation.loading()&&objects.length>0,
  state:()=>({project:viewportProject,status:document.getElementById('viewport-status').textContent,animating:!!raf,
    presentation:inspection.presentationState(),
    objects:objects.map(o=>({name:o.name,kind:o.kind,visible:o.root.visible,binding:o.binding?.kind,
      position:o.root.position.toArray(),paired:!!o.paired?.root.visible,
      bounds:new THREE.Box3().setFromObject(o.root).getSize(new THREE.Vector3()).toArray(),
      grip_error:o.binding?.socket && o.binding?.grip ? new THREE.Vector3().setFromMatrixPosition(
        o.binding.grip.node.matrixWorld.clone().multiply(o.binding.grip.inverseExported).multiply(o.binding.grip.physical)).distanceTo(
        new THREE.Vector3().setFromMatrixPosition(o.binding.socket.node.matrixWorld.clone().multiply(o.binding.socket.inverseExported).multiply(o.binding.socket.physical))):null,
      paired_grip_error:o.paired?.binding?.socket && o.paired?.binding?.grip ? studioPoint(o.paired.binding.grip).distanceTo(studioPoint(o.paired.binding.socket)):null,
      anchors:o.binding?.kind==='shared' && !o.binding.socket?o.binding.joints.map(p=>({name:p.source.node.name,
        error:new THREE.Vector3().setFromMatrixPosition(p.source.node.matrixWorld.clone().multiply(p.source.inverseExported).multiply(p.source.physical)).distanceTo(
          new THREE.Vector3().setFromMatrixPosition(p.target.node.matrixWorld.clone().multiply(p.target.inverseExported).multiply(p.target.physical)))})):[],
      joints:o.binding?.joints?.map(p=>p.source.node.name)})),
    materials:Object.entries(matData).map(([key,d])=>({key,...d,map:!!matsByName[key]?.[0]?.map,
      alphaMap:!!matsByName[key]?.[0]?.alphaMap,transparent:matsByName[key]?.[0]?.transparent,
      opacity:matsByName[key]?.[0]?.opacity,visible:matsByName[key]?.[0]?.visible,replaced_copy:!!matsByName[key]?.[0]?.userData.heldDuplicate}))}),
  loading:value=>inspection.setLoading(value),
  rest:()=>{const select=document.getElementById('viewport-animation');select.value='';select.dispatchEvent(new Event('change'));},
  clearDraft:revertEdits,
  pick:key=>pickMaterial(key,false),
  reload:()=>loadMaterials(currentSkin),
  pending:()=>saving||hasPendingEdits(),
  mapPixel:key=>{const c=document.createElement('canvas');c.width=c.height=1;const x=c.getContext('2d');x.drawImage(matsByName[key][0].map.image,0,0,1,1);return [...x.getImageData(0,0,1,1).data];},
};
"""


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--skin',action='append',required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--visibility',action='store_true')
    parser.add_argument('--export',action='store_true')
    parser.add_argument('--weapons',action='store_true')
    parser.add_argument('--skip-settings',action='store_true',help='Focus a later run on weapons/exports; still capture both view modes')
    args=parser.parse_args();report=args.report_dir.resolve();report.mkdir(parents=True,exist_ok=True)
    results=[];errors=[]
    request_failures=[]
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(report/'browser-profile'),headless=True,viewport={'width':1400,'height':960})
        page=context.pages[0]
        def page_error(error):
            detail = error.stack or str(error)
            errors.append(detail)
            print('BROWSER ERROR: '+detail, flush=True)
        page.on('pageerror',page_error)
        page.on('requestfailed',lambda request:request_failures.append({'url':request.url,'failure':request.failure}))
        async def source(route):
            await route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript')
        await page.route('**/static/viewport.js',source)
        async def control(id,value,event='change'):
            await page.evaluate('([id,value,event])=>{const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event(event));}',[id,value,event])
        try:
            await page.goto(args.url,wait_until='domcontentloaded')
            await page.wait_for_function("[...document.querySelectorAll('link[rel=stylesheet][href^=\"/static/\"]')].every(link=>link.sheet)")
            await page.wait_for_function('!!window.AtelierViewport')
            active=(await (await context.request.get(args.url+'/api/projects')).json())['active'] or ''
            await page.wait_for_function('active=>window.atelierProject?.()===active',arg=active)
            # Follow the normal first-run UI before opening another modal workspace.
            await page.evaluate('''async () => {
              const notes=window.AtelierChangelog;
              if (notes && (await notes.start())?.available) await notes.show();
            }''')
            if await page.locator('#changelog-overlay.active').count():
                await page.locator('#changelog-done').click()
            headers={'X-Atelier-Project':active}
            for skin in args.skin:
                folder=report/skin;folder.mkdir(exist_ok=True)
                print('Opening real skin '+skin,flush=True)
                await control('settings-motion','full')
                await page.evaluate('skin=>{void AtelierViewport.open(skin);}',skin)
                await page.wait_for_function('window.__studio&&(!!__studio.state().presentation.scan||__studio.ready())',timeout=300000)
                scan=await page.evaluate('__studio.state().presentation')
                if scan.get('scan'):
                    await page.screenshot(path=str(folder/'loading-full.png'))
                await page.wait_for_function('__studio.ready()',timeout=900000)
                await page.evaluate('__studio.rest()')
                await page.wait_for_timeout(650)
                state=await page.evaluate('__studio.state()')
                (folder/'loaded.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
                assert not any(m.get('mapping_error') for m in state['materials']),[(m['slot_name'],m.get('mapping_error')) for m in state['materials']]
                assert not state['presentation']['scan'] and state['presentation']['scans']==0,state['presentation']
                frames=state['presentation']['scanFrames'];await page.wait_for_timeout(180)
                assert frames==await page.evaluate('__studio.state().presentation.scanFrames')
                for mode in ('inspect','showcase'):
                    await page.locator('#viewport-'+mode).click()
                    await page.screenshot(path=str(folder/(mode+'.png')))
                    if args.skip_settings:continue
                    await control('viewport-backdrop','solid')
                    await control('viewport-backdrop-color','#35594d','input')
                    assert await page.locator('.vp-showcase-backdrop').count()==0
                    assert await page.locator('#viewport-stage').evaluate("e=>getComputedStyle(e).backgroundColor")=='rgb(53, 89, 77)'
                    initial=await page.evaluate('__studio.state().presentation.grid')
                    await page.locator('#viewport-grid').evaluate('e=>e.click()')
                    assert initial!=await page.evaluate('__studio.state().presentation.grid')
                    await page.locator('#viewport-grid').evaluate('e=>e.click()')
                    for lighting in ('flat','studio','emissive'):
                        await control('viewport-lighting',lighting)
                        await page.wait_for_timeout(50)
                    await control('viewport-lighting','studio')
                    await page.locator('#viewport-bloom').evaluate('e=>e.click()')
                    await page.wait_for_function('__studio.state().presentation.targets===3')
                    assert await page.evaluate('__studio.state().presentation.targets')==3
                    await page.locator('#viewport-bloom').evaluate('e=>e.click()')
                    await page.wait_for_function('__studio.state().presentation.targets===0')
                    assert await page.evaluate('__studio.state().presentation.targets')==0
                    if mode=='showcase':
                        for id in ('viewport-wireframe','viewport-regions'):
                            assert await page.locator('#'+id).is_disabled()
                            assert 'Inspect' in await page.locator('#'+id).get_attribute('title')
                    await page.screenshot(path=str(folder/(mode+'-plain.png')))
                    await control('viewport-backdrop','gradient')
                for motion in (() if args.skip_settings else ('calm','off')):
                    await control('settings-motion',motion)
                    await page.evaluate('__studio.loading(true)');await page.wait_for_timeout(100)
                    assert await page.evaluate('__studio.state().presentation.scan') is None
                    await page.evaluate('__studio.loading(false)')
                if not args.skip_settings:
                    await control('settings-motion','full');await page.emulate_media(reduced_motion='reduce')
                    await page.evaluate('__studio.loading(true)');await page.wait_for_timeout(100)
                    assert await page.evaluate('__studio.state().presentation.scan') is None
                    await page.evaluate('__studio.loading(false)');await page.emulate_media(reduced_motion='no-preference')
                for theme in (() if args.skip_settings else ('light','dark')):
                    await control('settings-theme',theme)
                    await page.screenshot(path=str(folder/('identity-'+theme+'.png')))
                await page.evaluate("const c=document.querySelector('[data-theme-color=accent]');if(c){c.value='#ce75a8';c.dispatchEvent(new Event('input'));}")
                await page.screenshot(path=str(folder/'identity-custom.png'))
                result={'skin':skin,'objects':state['objects'],'materials':len(state['materials']),'full_scan_observed':bool(scan.get('scan')),'view_modes_verified':True,'settings_both_modes':not args.skip_settings}
                extra_items=[]
                if args.weapons:
                    weapons=[o for o in state['objects'] if o['kind']=='weapon']
                    assert weapons and any(o['visible'] for o in weapons),weapons
                    for weapon in weapons:
                        if not weapon['visible']:continue
                        assert weapon['binding'],weapon
                        assert max(weapon['bounds'])<10,weapon
                        assert all(a['error']<.001 for a in weapon['anchors']),weapon
                        if weapon.get('grip_error') is not None:assert weapon['grip_error']<.001,weapon
                    first=page.locator('.vp-weapon-hand').first
                    await page.locator('#viewport-model-menu').evaluate('e=>e.open=true')
                    await page.locator('#viewport-obj-section').evaluate('e=>e.open=true')
                    for hand in ('right','left','both','auto'):
                        await first.select_option(hand);await page.wait_for_timeout(80)
                        current=await page.evaluate('__studio.state().objects.filter(o=>o.kind==="weapon")[0]')
                        assert current['visible'],current
                        if current.get('grip_error') is not None:assert current['grip_error']<.001,current
                        if hand=='both':
                            assert current['paired'] and current['paired_grip_error']<.001,current
                            await page.screenshot(path=str(folder/'dual-weapons.png'))
                    await page.locator('#viewport-model-menu').evaluate('e=>e.open=false')
                    material=next(m for m in state['materials'] if '/Weapons/' in m.get('mesh_game_rel','') and m.get('colors'))
                    await page.evaluate('key=>__studio.pick(key)',material['key'])
                    await page.locator('#viewport-material-editor .vp-advanced').evaluate('e=>e.open=true')
                    picker=page.locator('#viewport-material-editor input[type=color]').first
                    await picker.evaluate("e=>{e.value='#357aa8';e.dispatchEvent(new Event('input'));}")
                    await page.locator('#viewport-mat-save').click()
                    await page.wait_for_function('!__studio.pending()',timeout=120000)
                    assert 'Saved recolors' in await page.locator('#viewport-status').inner_text()
                    result['weapon_colour_saved']=material['game_rel'];extra_items.append(material['game_rel'])
                    param=next((p for p,g in material.get('textures',{}).items() if g==material.get('texture_roles',{}).get('basecolor')),None)
                    if param:
                        buffer=io.BytesIO();Image.new('RGB',(64,64),(48,156,113)).save(buffer,format='PNG')
                        changed=await (await context.request.post(args.url+'/api/material_custom_texture',headers=headers,multipart={
                            'game_rel':material['game_rel'],'slot':param,'file':{'name':'Studio green.png','mimeType':'image/png','buffer':buffer.getvalue()}})).json()
                        assert changed.get('ok'),changed
                        await page.evaluate('void __studio.reload()');await page.wait_for_function('__studio.ready()',timeout=120000)
                        if not material.get('dyeable'):
                            assert (await page.evaluate('key=>__studio.mapPixel(key)',material['key']))[:3]==[48,156,113]
                        result['custom_weapon_texture']={'material':material['game_rel'],'slot':param,'file':changed['custom_textures'][param]['file']}
                    await page.screenshot(path=str(folder/'weapon-edited.png'))
                if args.visibility:
                    target=next((m for m in state['materials'] if 'Gen' in m.get('slot_name','')),None)
                    target=target or next((m for m in state['materials'] if '/Weapons/' in m.get('mesh_game_rel','')),state['materials'][0])
                    key=target['key'];eye=page.locator('.vp-section-eye[data-section='+json.dumps(key)+']')
                    result['hidden_target']={k:target[k] for k in ('mesh_game_rel','slot_name','slot_index')}
                    await eye.click();await page.wait_for_selector('#atelier-confirm')
                    assert 'in-game after' in await page.locator('#atelier-confirm-body').inner_text()
                    await page.locator('#atelier-confirm-cancel').click()
                    assert await page.evaluate('key=>__studio.state().materials.find(m=>m.key===key).visible',key)
                    await eye.click();await page.locator('#atelier-confirm-ok').click()
                    await page.wait_for_function('key=>__studio.state().materials.find(m=>m.key===key).hidden',arg=key)
                    await page.wait_for_function("document.getElementById('viewport-status').textContent.includes('saved for export')",timeout=300000)
                    await page.screenshot(path=str(folder/'hidden.png'))
                    await page.reload(wait_until='domcontentloaded');await page.wait_for_function('!!window.AtelierViewport')
                    await page.wait_for_function('active=>window.atelierProject?.()===active',arg=active)
                    await page.evaluate('skin=>{void AtelierViewport.open(skin);}',skin)
                    await page.wait_for_function('__studio.ready()',timeout=300000)
                    assert await page.evaluate('key=>__studio.state().materials.find(m=>m.key===key).hidden',key)
                    tray=await (await context.request.get(args.url+'/api/imported',headers=headers)).json()
                    row=next(r for r in tray if r['game_rel']==target['mesh_game_rel'])
                    assert 'hidden section' in row['name']
                    result['visibility_reload_and_tray']=True
                    if args.export:
                        payload={'mod_name':'Studio verification '+skin,'items':[target['mesh_game_rel'],*extra_items],'copy_to_mods':False,'background':True}
                        job=await (await context.request.post(args.url+'/api/install_mod',data=payload,headers=headers)).json()
                        if job.get('job'):
                            identifier=job['job']['id']
                            for _ in range(600):
                                job=await (await context.request.get(args.url+'/api/jobs/'+identifier,headers=headers)).json()
                                if job['job']['state'] in ('succeeded','failed','cancelled'):break
                                await asyncio.sleep(.5)
                            exported=job['job'].get('result') or job['job']
                        else:exported=job
                        (folder/'export.json').write_text(json.dumps(exported,indent=2),encoding='utf-8')
                        assert exported.get('ok') and not exported.get('skipped'),exported
                        result['export']=exported
                    eye=page.locator('.vp-section-eye[data-section='+json.dumps(key)+']');await eye.click()
                    await page.wait_for_function('key=>!__studio.state().materials.find(m=>m.key===key).hidden',arg=key)
                    await page.wait_for_function("document.getElementById('viewport-status').textContent.includes('saved for export')",timeout=60000)
                    assert await page.locator('#atelier-confirm').count()==0
                await page.evaluate('AtelierViewport.close()')
                assert not await page.evaluate('__studio.state().animating')
                assert await page.evaluate('__studio.state().presentation.scans')==0
                results.append(result);print('Verified real skin '+skin,flush=True)
        finally:
            if page and not page.is_closed():
                await page.screenshot(path=str(report/'last-state.png'))
                await page.evaluate('AtelierViewport.close()')
            (report/'results.json').write_text(json.dumps({'results':results,'page_errors':errors,'request_failures':request_failures},indent=2),encoding='utf-8')
            await context.close()
    assert not errors,errors


if __name__=='__main__':
    asyncio.run(main())
