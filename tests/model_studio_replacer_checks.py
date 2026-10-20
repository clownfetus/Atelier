"""Exercise weapon replacement destinations in a private running app.

The UI upload is intercepted to prove that a weapon cannot accidentally replace
the body. --native additionally imports the real original weapon through the
app in a separate verification project, then builds an export without installing.
"""
import argparse
import asyncio
import json
import struct
from pathlib import Path
from urllib.parse import unquote
from playwright.async_api import async_playwright


def partial_model(data):
    size,kind=struct.unpack_from('<II',data,12)
    assert kind==0x4e4f534a
    document=json.loads(data[20:20+size]);assert len(document['meshes'])==1
    primitives=document['meshes'][0]['primitives'];assert len(primitives)>1
    document['meshes'][0]['primitives']=[primitives[0]]
    encoded=json.dumps(document).encode();encoded+=b' '*(-len(encoded)%4)
    remainder=data[20+size:]
    return struct.pack('<5I',0x46546c67,2,20+len(encoded)+len(remainder),len(encoded),kind)+encoded+remainder


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--report-dir',required=True,type=Path)
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--weapon-zip',type=Path)
    parser.add_argument('--partial-skin',default='1066001',help='Skin from the reported missing-material-slot failure')
    args=parser.parse_args();report=args.report_dir.resolve();report.mkdir(parents=True,exist_ok=True)
    results={};errors=[];uploads=[];release=asyncio.Event()
    async with async_playwright() as pw:
        context=await pw.chromium.launch_persistent_context(str(report/'browser-profile'),headless=True,viewport={'width':1400,'height':960})
        page=context.pages[0];page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            projects=await (await context.request.get(args.url+'/api/projects')).json();active=projects['active']
            headers={'X-Atelier-Project':active}
            meshes=await (await context.request.get(args.url+'/api/skin_meshes?skin_id=1029001',headers=headers)).json()
            body=next(row for row in meshes if row['kind']=='body');weapon=next(row for row in meshes if row['kind']=='weapon')
            await page.goto(args.url,wait_until='domcontentloaded')
            await page.wait_for_function('window.AtelierMeshEdit && window.atelierProject?.()')
            await page.wait_for_function('active=>atelierProject()===active',arg=active)
            await page.wait_for_function("[...document.querySelectorAll('link[rel=stylesheet][href^=\"/static/\"]')].every(link=>link.sheet)")
            await page.evaluate('target=>AtelierMeshEdit.open(target)',body)
            await page.wait_for_selector('#mesh-edit-weapons .mesh-edit-target')
            assert await page.locator('#mesh-edit-weapons .mesh-edit-target').count()==len([row for row in meshes if row['kind']=='weapon'])
            assert await page.locator('.mesh-edit-target[aria-pressed=true]').get_attribute('data-mesh')==body['game_rel']
            await page.locator('#mesh-edit-weapons .mesh-edit-target').first.click()
            assert await page.locator('.mesh-edit-path').inner_text()==weapon['game_rel']
            assert 'weapon' in await page.locator('#mesh-replace-choose').inner_text()
            assert await page.locator('.mesh-edit-target[aria-pressed=true]').count()==1
            assert await page.locator('.mesh-import-options input:checked').count()==3
            assert await page.locator('#mesh-import-keep_parts').is_checked()
            assert 'custom physics are not created' in await page.locator('.mesh-edit-rig-help').inner_text()
            button=await page.locator('#mesh-replace-choose').bounding_box()
            assert button and button['y']+button['height']<=960,button
            await page.screenshot(path=str(report/'weapon-destination.png'))
            entered=asyncio.Event()
            async def replacement(route):
                uploads.append({'body':route.request.post_data_buffer.decode('latin1'),'project':unquote(route.request.headers.get('x-atelier-project',''))})
                entered.set();await release.wait()
                await route.fulfill(json={'ok':True,'validation':{'lods':4,'retained_weight_vertices':50,'transferred_weight_vertices':0}})
            await page.route('**/api/mesh_replace',replacement)
            await page.locator('#mesh-import-keep_morphs').uncheck()
            await page.locator('#mesh-edit-overlay input[type=file]').set_input_files({'name':'replacement.glb','mimeType':'model/gltf-binary','buffer':b'UI routing fixture'})
            await asyncio.wait_for(entered.wait(),20)
            assert await page.locator('.mesh-edit-target:enabled').count()==0
            assert await page.locator('#mesh-replace-choose').is_disabled()
            release.set()
            await page.wait_for_function("document.getElementById('mesh-edit-status').textContent.includes('Model saved')")
            assert weapon['game_rel'] in uploads[0]['body'] and body['game_rel'] not in uploads[0]['body']
            assert '"keep_skeleton":true' in uploads[0]['body'] and '"keep_morphs":false' in uploads[0]['body']
            assert uploads[0]['project']==active
            await page.unroute('**/api/mesh_replace',replacement)
            results['weapon_destination']={'body':body['game_rel'],'weapon':weapon['game_rel'],'busy_switching_prevented':True,'project_scoped':True}
            await page.get_by_role('button',name='Close',exact=True).last.click()
            await page.evaluate("AtelierMeshEdit.open({name:'Magus',game_rel:'Characters/1046/1046500/Meshes/SK_1046_1046500'})")
            await page.wait_for_function("document.querySelector('.mesh-edit-weapon-status').textContent.includes('No separate weapon')")
            assert await page.locator('#mesh-edit-weapons button').count()==0
            assert await page.locator('#mesh-replace-choose').is_enabled()
            results['no_weapon_state']=True
            await page.get_by_role('button',name='Close',exact=True).last.click()
            async def unavailable(route):await route.fulfill(status=503,json={'error':'fixture unavailable'})
            await page.route('**/api/skin_meshes?*',unavailable)
            await page.evaluate('target=>AtelierMeshEdit.open(target)',body)
            await page.wait_for_function("document.querySelector('.mesh-edit-weapon-status').textContent.includes('could not be loaded')")
            assert await page.locator('.mesh-edit-path').inner_text()==body['game_rel']
            assert await page.locator('#mesh-replace-choose').is_enabled()
            await page.unroute('**/api/skin_meshes?*',unavailable)
            await page.get_by_role('button',name='Close',exact=True).last.click()
            results['discovery_failure_preserves_selected_destination']=True
            if args.weapon_zip:
                hood={'name':'The Hood default','game_rel':'Characters/1066/1066001/Meshes/SK_1066_1066001'}
                left='Characters/1066/1066001/Weapons/Gun_L/Meshes/SK_WP_1066001_Gun_L'
                await page.evaluate('target=>AtelierMeshEdit.open(target)',hood)
                await page.locator('button[data-mesh="'+left+'"]').click()
                assert await page.locator('#mesh-import-fit_weapon').is_checked()
                assert '.zip' in await page.locator('#mesh-edit-overlay input[type=file]').get_attribute('accept')
                await page.locator('.mesh-import-details').first.evaluate('e=>e.open=true')
                await page.locator('#mesh-import-scale').fill('1.1')
                await page.locator('#mesh-import-rotate_z').fill('90')
                await page.locator('.mesh-import-details').last.evaluate('e=>e.open=true')
                await page.locator('#mesh-import-normal_encoding').select_option('unity_ag')
                await page.screenshot(path=str(report/'left-gun-bundle-options.png'))
                entered.clear();release.clear();await page.route('**/api/mesh_replace',replacement)
                await page.locator('#mesh-edit-overlay input[type=file]').set_input_files(str(args.weapon_zip))
                await asyncio.wait_for(entered.wait(),20)
                assert left in uploads[-1]['body'] and args.weapon_zip.name in uploads[-1]['body']
                assert '"scale":1.1' in uploads[-1]['body'] and '"rotate_z":90' in uploads[-1]['body']
                assert '"normal_encoding":"unity_ag"' in uploads[-1]['body'] and '"fit_weapon":true' in uploads[-1]['body']
                release.set();await page.wait_for_function("document.getElementById('mesh-edit-status').textContent.includes('Model saved')")
                await page.unroute('**/api/mesh_replace',replacement)
                results['zip_bundle_upload']={'target':left,'archive':args.weapon_zip.name,'numeric_and_channel_options':True}
                await page.get_by_role('button',name='Close',exact=True).last.click()
            if args.native:
                name='Model Studio Import Verification'
                if not any(row['name']==name for row in projects['projects']):
                    created=await (await context.request.post(args.url+'/api/project/create',data={'name':name},headers=headers)).json()
                    assert created.get('ok'),created
                    await context.request.post(args.url+'/api/project/select',data={'name':active})
                native_headers={'X-Atelier-Project':name}
                model=await context.request.get(args.url+'/api/model_gltf',params={'game_rel':weapon['game_rel']},headers=native_headers,timeout=300000)
                assert model.ok,await model.text()
                data=await model.body();(report/'original-weapon.glb').write_bytes(data)
                async def finish(response):
                    result=await response.json()
                    if not result.get('job'):return result
                    identifier=result['job']['id']
                    for _ in range(1200):
                        current=await (await context.request.get(args.url+'/api/jobs/'+identifier,headers=native_headers)).json()
                        if current['job']['state'] in ('succeeded','failed','cancelled'):
                            return current['job'].get('result') or current['job']
                        await asyncio.sleep(.5)
                    raise TimeoutError('Native replacement verification did not finish')
                imported=await finish(await context.request.post(args.url+'/api/mesh_replace',headers=native_headers,multipart={
                    'game_rel':weapon['game_rel'],'options':json.dumps({'keep_skeleton':True,'keep_weights':True,'keep_morphs':True}),
                    'files':{'name':'Original weapon.glb','mimeType':'model/gltf-binary','buffer':data}}))
                (report/'native-import.json').write_text(json.dumps(imported,indent=2),encoding='utf-8')
                assert imported.get('ok'),imported
                assert imported['validation']['lods']==4,imported
                assert imported['validation']['skeleton_preserved'] and imported['validation']['rig_bones']>0,imported
                partial_meshes=await (await context.request.get(args.url+'/api/skin_meshes?skin_id='+args.partial_skin,headers=native_headers)).json()
                partial_target=next(row['game_rel'] for row in partial_meshes if row['kind']=='body')
                original=await context.request.get(args.url+'/api/model_gltf',params={'game_rel':partial_target},headers=native_headers,timeout=300000)
                assert original.ok
                partial=partial_model(await original.body());(report/'partial-body.glb').write_bytes(partial)
                partial_import=await finish(await context.request.post(args.url+'/api/mesh_replace',headers=native_headers,multipart={
                    'game_rel':partial_target,'options':json.dumps({'keep_skeleton':True,'keep_weights':False,'keep_morphs':True,'keep_parts':True}),
                    'files':{'name':'Partial body.glb','mimeType':'model/gltf-binary','buffer':partial}}))
                (report/'native-partial-import.json').write_text(json.dumps(partial_import,indent=2),encoding='utf-8')
                assert partial_import.get('ok'),partial_import
                info=partial_import['validation']
                assert info['skeleton_preserved'] and info['lods']==4 and len(info['preserved_parts'])>1,info
                assert info['transferred_weight_vertices']>0 and info['retained_weight_vertices']==0,info
                exported=await finish(await context.request.post(args.url+'/api/install_mod',headers=native_headers,data={
                    'mod_name':'Imported weapon verification','items':[weapon['game_rel'],partial_target],'copy_to_mods':False,'background':True}))
                (report/'native-export.json').write_text(json.dumps(exported,indent=2),encoding='utf-8')
                assert exported.get('ok') and not exported.get('skipped'),exported
                results['native_import']=imported;results['native_partial_import']=partial_import;results['native_export']=exported
                results['physics']='Existing game physics assets; no new simulation or collision fitting'
            assert not errors,errors
            print('PASS weapon destinations, upload routing, busy controls, empty and failed discovery'+(' and real imported-weapon export' if args.native else ''),flush=True)
        finally:
            release.set()
            results['page_errors']=errors
            (report/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            await context.close()


if __name__=='__main__':asyncio.run(main())
