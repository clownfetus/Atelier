"""Review an imported body and weapon together, including reversible visibility."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright
from model_studio_real_checks import HOOK

ROOT=Path(__file__).resolve().parents[1]


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True);parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--project',default='Dante Hood Verification');parser.add_argument('--export',action='store_true')
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    body='Characters/1066/1066001/Meshes/SK_1066_1066001'
    gun='Characters/1066/1066001/Weapons/Gun_R/Meshes/SK_WP_1066001_Gun_R'
    left_gun='Characters/1066/1066001/Weapons/Gun_L/Meshes/SK_WP_1066001_Gun_L'
    errors=[];results={};active=None;key=None
    async with async_playwright() as pw:
        context=await pw.chromium.launch_persistent_context(str(args.report_dir/'browser-profile'),headless=True,viewport={'width':1440,'height':1000})
        page=context.pages[0];page.on('pageerror',lambda error:errors.append(error.stack or str(error)))
        async def api(path,data=None):
            headers={'X-Atelier-Project':args.project}
            response=await (context.request.get(args.url+path,headers=headers,timeout=180000) if data is None else context.request.post(args.url+path,headers=headers,data=data,timeout=180000))
            return await response.json()
        async def finish(result):
            if not result.get('job'):return result
            identifier=result['job']['id']
            for _ in range(2400):
                job=(await api('/api/jobs/'+identifier))['job']
                if job['state'] in ('succeeded','failed','cancelled'):return job.get('result') or job
                await asyncio.sleep(.5)
            raise TimeoutError('Imported-model export did not finish')
        async def source(route):await route.fulfill(body=(ROOT/'gui/viewport.js').read_text(encoding='utf-8')+HOOK,content_type='text/javascript')
        await page.route('**/static/viewport.js',source)
        try:
            active=(await api('/api/projects'))['active']
            assert (await api('/api/project/select',{'name':args.project}))['ok']
            await page.goto(args.url,wait_until='domcontentloaded')
            await page.wait_for_function('!!window.AtelierViewport')
            await page.wait_for_function("[...document.querySelectorAll('link[rel=stylesheet][href^=\"/static/\"]')].every(link=>link.sheet)")
            await page.wait_for_function('name=>window.atelierProject?.()===name',arg=args.project)
            await page.evaluate('''async () => {
              const notes=window.AtelierChangelog;
              if (notes && (await notes.start())?.available) await notes.show();
            }''')
            if await page.locator('#changelog-overlay.active').count():
                await page.locator('#changelog-done').click()
            await page.evaluate('gun=>{void AtelierViewport.openMesh(gun);}',gun)
            await page.wait_for_function('window.__studio?.ready()',timeout=900000)
            await page.evaluate('__studio.rest()');await page.wait_for_timeout(500)
            state=await page.evaluate('__studio.state()');results['loaded']=state
            assert any(row['kind']=='body' and row['visible'] for row in state['objects'])
            weapon=next(row for row in state['objects'] if row['name']==gun.split('/')[-1]);assert weapon['visible'] and weapon['binding'],weapon
            if weapon['grip_error'] is not None:assert weapon['grip_error']<.001,weapon
            material=next(row for row in state['materials'] if row.get('mesh_game_rel')==gun)
            assert material['map'] and not material.get('mapping_error'),material
            assert len(material.get('texture_urls',{}))==4 and all('/material_custom_texture/preview?' in url for url in material['texture_urls'].values()),material
            left=next(row for row in state['objects'] if row['name']=='SK_WP_1066001_Gun_L')
            assert left['visible'] and left['binding'] and (left['grip_error'] is None or left['grip_error']<.001),left
            left_material=next(row for row in state['materials'] if row.get('mesh_game_rel','').endswith('/SK_WP_1066001_Gun_L'))
            assert len(left_material.get('texture_urls',{}))==4 and left_material['game_rel']!=material['game_rel'],left_material
            results['independent_left_and_right_materials']=True
            for mode in ('inspect','showcase'):
                await page.locator('#viewport-'+mode).click();await page.screenshot(path=str(args.report_dir/(mode+'.png')))
            await page.locator('#viewport-inspect').click()
            key=material['key'];eye=page.locator('.vp-section-eye[data-section='+json.dumps(key)+']')
            await eye.click();await page.locator('#atelier-confirm-cancel').click()
            assert await page.evaluate('key=>__studio.state().materials.find(row=>row.key===key).visible',key)
            await eye.click();await page.locator('#atelier-confirm-ok').click()
            await page.wait_for_function('key=>__studio.state().materials.find(row=>row.key===key).hidden',arg=key)
            await page.wait_for_function("document.getElementById('viewport-status').textContent.includes('saved for export')")
            await page.reload(wait_until='domcontentloaded');await page.wait_for_function('!!window.AtelierViewport')
            await page.evaluate('gun=>{void AtelierViewport.openMesh(gun);}',gun)
            await page.wait_for_function('__studio.ready()',timeout=900000)
            assert await page.evaluate('key=>__studio.state().materials.find(row=>row.key===key).hidden',key)
            results['visibility_persisted_on_imported_weapon']=True
            tray=await api('/api/imported');assert 'hidden section' in next(row['name'] for row in tray if row['game_rel']==gun)
            results['hidden_target']={name:material[name] for name in ('mesh_game_rel','slot_name','slot_index')}
            if args.export:
                exported=await finish(await api('/api/install_mod',{'mod_name':'Dante and guns hidden verification','items':[body,left_gun,gun],'copy_to_mods':False,'background':True}))
                results['export']=exported;assert exported.get('ok') and not exported.get('skipped'),exported
                print('PASS combined imported body, weapon, hidden sections and texture packages',flush=True)
            await page.locator('.vp-section-eye[data-section='+json.dumps(key)+']').click()
            await page.wait_for_function('key=>!__studio.state().materials.find(row=>row.key===key).hidden',arg=key)
            await page.wait_for_function("document.getElementById('viewport-status').textContent.includes('saved for export')")
            results['visibility_restored']=True;key=None
            await page.evaluate('AtelierViewport.close()')
            assert not await page.evaluate('__studio.state().animating')
            assert not errors,errors
            print('PASS imported body and gun in both modes, packed-map preview, held grip, hide/reload/restore and clean close',flush=True)
        finally:
            if key and results.get('hidden_target'):
                target=results['hidden_target'];await api('/api/mesh_visibility',{**target,'game_rel':gun,'hidden':False})
            if active:await api('/api/project/select',{'name':active})
            results['page_errors']=errors;results['skin']='1066001'
            (args.report_dir/'results.json').write_text(json.dumps({'results':[results],'page_errors':errors},indent=2),encoding='utf-8')
            await context.close()


if __name__=='__main__':asyncio.run(main())
