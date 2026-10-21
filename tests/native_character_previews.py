"""Read-only material and weapon audit of real installed character models.

Requires a configured isolated app with its own test-mods destination. Defaults
to every playable character in the bundled catalogue. --skin narrows a rerun.
Reports are checkpointed after each character; nothing is saved to projects.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOOK = r"""
const auditPhysical=joint=>joint.node.matrixWorld.clone().multiply(joint.inverseExported).multiply(joint.physical);
window.__characterAudit={
  ready:()=>!modelLoading&&!materialTask&&!animation.loading(),
  rest:()=>{const select=document.getElementById('viewport-animation');select.value='';select.dispatchEvent(new Event('change'));},
  parts:()=>objects.map((object,index)=>({index,name:object.name,kind:object.kind,auto:object.autoEquip,
    loaded:!!object.loaded,visible:object.root.visible,game_rel:meshMeta[index].game_rel,error:object.loadError})),
  choose:async index=>{
    const selected=objects[index];
    await changeObjects([selected],()=>{
      if(selected.kind==='weapon'){
        for(const object of objects)if(object.kind==='weapon')object.enabled=object===selected;
      }else{
        for(const object of objects){
          if(object.kind==='weapon')delete object.enabled;
          else object.root.visible=object===selected&&!!object.loaded;
        }
      }
    },{automatic:selected.kind!=='weapon'});
  },
  face:()=>{
    const body=objects.find(object=>object.kind!=='weapon'&&object.root.visible);
    const joint=body?.rig&&[...body.rig.nodes.values()].find(joint=>/^head$/i.test(joint.node.name));
    if(!joint)return false;
    const point=new THREE.Vector3().setFromMatrixPosition(auditPhysical(joint));
    const direction=camera.position.clone().sub(controls.target).normalize();
    controls.target.copy(point);camera.position.copy(point).addScaledVector(direction,.65);controls.update();return true;
  },
  frame:frameCamera,
  state:()=>{
    modelRoot.updateMatrixWorld(true);
    const active=new Set(objects.flatMap((object,index)=>object.root.visible?[meshMeta[index].game_rel]:[]));
    return {status:document.getElementById('viewport-status').textContent,
      playing:document.getElementById('viewport-play').getAttribute('aria-pressed')==='true',
      idle_count:document.getElementById('viewport-animation').options.length-1,
      objects:objects.map((object,index)=>{
        const binding=object.binding,grip=binding?.grip&&auditPhysical(binding.grip),socket=binding?.socket&&auditPhysical(binding.socket);
        const anchors=binding?.kind==='shared'&&!binding.socket?binding.joints.map(pair=>({name:pair.source.node.name,
          error:new THREE.Vector3().setFromMatrixPosition(auditPhysical(pair.source)).distanceTo(new THREE.Vector3().setFromMatrixPosition(auditPhysical(pair.target)))})):[];
        return {index,name:object.name,kind:object.kind,auto:object.autoEquip,visible:object.root.visible,loaded:!!object.loaded,
          game_rel:meshMeta[index].game_rel,error:object.loadError,binding:binding?.kind,side:binding?.side,grip:binding?.grip?.node.name,
          grip_error:grip&&socket?new THREE.Vector3().setFromMatrixPosition(grip).distanceTo(new THREE.Vector3().setFromMatrixPosition(socket)):null,
          grip_rotation_error:grip&&socket?new THREE.Quaternion().setFromRotationMatrix(grip).normalize().angleTo(new THREE.Quaternion().setFromRotationMatrix(socket).normalize()):null,
          anchors,bones:object.kind==='weapon'&&object.loaded?[...object.rig.nodes.keys()]:undefined,
          bounds:object.loaded?new THREE.Box3().setFromObject(object.root).getSize(new THREE.Vector3()).toArray():null};
      }),
      materials:Object.entries(matData).filter(([,info])=>active.has(info.mesh_game_rel)).map(([key,info])=>{
        const material=matsByName[key]?.[0];
        return {key,...info,map:!!material?.map,emissiveMap:!!material?.emissiveMap,alphaMap:!!material?.alphaMap,
          tint:material?.color?.toArray(),emissive:material?.emissive?.toArray(),intensity:material?.emissiveIntensity,visible:material?.visible,
          transparent:material?.transparent,opacity:material?.opacity,alphaTest:material?.alphaTest};
      })};
  }
};
"""


def issues(state):
    found = []
    bodies = [part for part in state['objects'] if part['kind'] != 'weapon' and part['visible']]
    if len(bodies) != 1:
        found.append(f'Visible body count is {len(bodies)}')
    if not state['materials']:
        found.append('No material bindings loaded')
    for material in state['materials']:
        name = material['slot_name']
        for field in ('mapping_error', 'material_error'):
            if material.get(field):
                found.append(f'{name}: {material[field]}')
        roles = material.get('texture_roles', {})
        textures = material.get('textures', {})
        if textures.get('IrisBaseColor') and textures.get('ScleraBaseColor') and not textures.get('BaseColor'):
            if not material.get('eye_preview') or not material.get('map'):
                found.append(f'{name}: iris and sclera colour layers were not applied')
            if material.get('tint') != [1, 1, 1]:
                found.append(f'{name}: eye colour layers received a second overall tint')
        surface = material.get('surface', {})
        if surface.get('opacity_source') and material.get('opacity') != surface.get('opacity'):
            found.append(f'{name}: inherited opacity was not applied')
        if surface.get('preview_omitted') and material.get('opacity') != 0:
            found.append(f'{name}: unsupported or disabled effect is visible')
        for role, actual in [('basecolor', 'map'), ('opacity', 'alphaMap'), ('emissive', 'emissiveMap')]:
            if roles.get(role) and not material[actual]:
                found.append(f'{name}: {role} texture was not applied')
        strength = next((scalar['value'] for scalar in material.get('scalars', [])
                         if ''.join(c for c in scalar['name'].lower() if c.isalnum()) == 'emissivestrength'), None)
        if strength == 0 and material.get('intensity', 0) != 0:
            found.append(f'{name}: disabled emission is visible')
        if material.get('shared_slots') and 'slot_index' in material:
            found.append(f'{name}: merged material guesses an individual section')
    for part in state['objects']:
        if part['kind'] != 'weapon' or not part['visible']:
            continue
        if not part.get('binding'):
            found.append(f'{part["name"]}: visible weapon has no binding')
        if part.get('grip_error') is not None and part['grip_error'] > .001:
            found.append(f'{part["name"]}: grip misses its socket by {part["grip_error"]:.4f} m')
        if part.get('grip_rotation_error') is not None and part['grip_rotation_error'] > .002:
            found.append(f'{part["name"]}: grip rotation differs from its socket by {part["grip_rotation_error"]:.4f} radians')
        if any(anchor['error'] > .001 for anchor in part.get('anchors', [])):
            found.append(f'{part["name"]}: shared weapon rig is misaligned')
        if part.get('bounds') and max(part['bounds']) > 12:
            found.append(f'{part["name"]}: weapon bounds exceed 12 metres')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--skin', action='append')
    parser.add_argument('--all-parts', action='store_true', help='Also select every additional body and ordinary weapon')
    parser.add_argument('--timeout', type=int, default=150000)
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    entries = json.loads((ROOT / 'gui/catalogue.json').read_text(encoding='utf-8'))['entries']
    skins = args.skin or sorted(key + '001' for key, value in entries.items()
                               if value.get('kind') == 'hero' and key.isdigit() and int(key) < 2000)
    sources = ['gui/viewport.js', 'gui/viewport-attachments.js', 'gui/viewport-inspection.js',
               'atelier/handlers/meshstudio.py', 'atelier/handlers/material_preview.py',
               'atelier/handlers/material.py', 'atelier/handlers/meshport.py', 'atelier/import_server.py',
               'atelier/web/routes.py', 'atelier/storage.py', 'tools-src/AtelierImport/Program.cs',
               'tools-src/native-tools.lock.json', 'tests/native_character_previews.py']
    results = {'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
               'all_parts': args.all_parts, 'characters': [], 'unavailable': [], 'page_errors': [], 'asset_errors': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1240, 'height': 900})
        setup = context.request.get(args.url + '/api/setup_status').json()
        assert setup.get('configured') and Path(setup.get('mods_prefill', '')).name == 'test-mods'
        available = []
        for skin in skins:
            parts = context.request.get(args.url + '/api/skin_meshes?skin_id=' + skin).json()
            if any(part['kind'] != 'weapon' for part in parts):
                available.append(skin)
            else:
                results['unavailable'].append({'skin': skin, 'reason': 'No installed body mesh'})
        skins = available
        page = None
        def prepare_page():
            nonlocal page
            if page:
                page.close()
            page = context.new_page()
            page.on('pageerror', lambda error: results['page_errors'].append(str(error)))
            def response_received(response):
                if response.status >= 400 and any(endpoint in response.url for endpoint in
                        ('/api/model_gltf?', '/api/skin_materials', '/api/texture_png?', '/api/eye_texture?', '/api/eye_preview')):
                    results['asset_errors'].append({'url': response.url, 'status': response.status})
            page.on('response', response_received)
            page.route('**/static/viewport.js', lambda route: route.fulfill(
                body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK, content_type='text/javascript'))
            page.goto(args.url, wait_until='domcontentloaded')
            page.wait_for_function('window.AtelierViewport && window.atelierProject?.()', timeout=120000)
            page.locator('#settings-theme').select_option('dark', force=True)
            if page.locator('#changelog-done').is_visible():
                page.locator('#changelog-done').click()
        try:
            for index, skin in enumerate(skins):
                if index % 5 == 0:
                    prepare_page()
                name = entries.get(skin[:4], {}).get('name', skin)
                record = {'skin': skin, 'name': name, 'stages': [], 'issues': []}
                folder = report / skin
                folder.mkdir()
                started = time.monotonic()
                def capture(label):
                    page.wait_for_function('__characterAudit.ready()', timeout=args.timeout)
                    page.wait_for_timeout(120)
                    state = page.evaluate('__characterAudit.state()')
                    problems = issues(state)
                    record['stages'].append({'label': label, 'state': state, 'issues': problems})
                    record['issues'].extend(f'{label}: {problem}' for problem in problems)
                    page.screenshot(path=str(folder / (label + '.png')))
                    return state
                try:
                    print(f'{index + 1}/{len(skins)} Opening {name} ({skin})', flush=True)
                    page.evaluate('skin=>{void AtelierViewport.open(skin)}', skin)
                    initial = capture('default-idle')
                    page.evaluate('__characterAudit.rest()')
                    capture('default-rest')
                    if page.evaluate('__characterAudit.face()'):
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(folder / 'face.png'))
                    page.evaluate('__characterAudit.frame()')
                    if args.all_parts:
                        extra_weapons = [part for part in initial['objects'] if part['kind'] == 'weapon'
                                         and part.get('auto') is not False and not part['visible']]
                        extra_bodies = [part for part in initial['objects'] if part['kind'] != 'weapon' and not part['visible']]
                        for part in extra_weapons + extra_bodies:
                            page.evaluate('index=>{void __characterAudit.choose(index)}', part['index'])
                            state = capture(f'part-{part["index"]}-idle')
                            selected = state['objects'][part['index']]
                            if not selected['visible']:
                                record['issues'].append(f'{part["name"]}: selectable part did not become visible: {selected.get("error")}')
                            page.evaluate('__characterAudit.rest()')
                            capture(f'part-{part["index"]}-rest')
                except Exception as error:
                    record['error'] = str(error)
                    record['issues'].append(str(error))
                    if not page.is_closed():
                        page.screenshot(path=str(folder / 'failure.png'))
                finally:
                    record['seconds'] = round(time.monotonic() - started, 2)
                    (folder / 'results.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
                    results['characters'].append(record)
                    (report / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                    print(f'  {name}: {len(record["stages"])} views, {len(record["issues"])} findings, {record["seconds"]} s', flush=True)
                    if not page.is_closed():
                        page.evaluate('void AtelierViewport.close()')
        finally:
            browser.close()
    print(f'Completed {len(results["characters"])} characters; review {report / "results.json"}', flush=True)
    return int(bool(results['page_errors'] or results['asset_errors'] or
                    any(character['issues'] for character in results['characters'])))


if __name__ == '__main__':
    raise SystemExit(main())
