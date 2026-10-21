"""Read-only regression check against an isolated app with real Blade assets.

Run the configured backend first, then pass --url and --report-dir. This does
not save material edits, install mods, or close another application window.
"""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MESH = 'Characters/1044/1044001/Meshes/SK_1044_1044001_Lobby'
HOOK = r"""
window.__bladePreview = {
  ready:()=>!modelLoading&&!materialTask&&!animation.loading()&&objects.some(o=>o.loaded),
  face:()=>{
    const body=objects.find(o=>o.kind!=='weapon'&&o.root.visible),joint=body.rig.nodes.get('head');
    const point=new THREE.Vector3().setFromMatrixPosition(joint.node.matrixWorld.clone().multiply(joint.inverseExported).multiply(joint.physical));
    const direction=camera.position.clone().sub(controls.target).normalize();
    controls.target.copy(point);camera.position.copy(point).addScaledVector(direction,.65);controls.update();
  },
  inspect:()=>{
    modelRoot.updateMatrixWorld(true);
    const physical=joint=>joint.node.matrixWorld.clone().multiply(joint.inverseExported).multiply(joint.physical);
    const weapon=objects.find(o=>o.kind==='weapon'&&o.root.visible),binding=weapon?.binding;
    const socket=binding?.socket&&physical(binding.socket),grip=binding?.grip&&physical(binding.grip);
    const tip=new THREE.Vector3();let tipVertices=0;
    weapon?.root.traverse(mesh=>{
      if(!mesh.isSkinnedMesh)return;
      mesh.skeleton.update();
      const indices=mesh.geometry.getAttribute('skinIndex'),weights=mesh.geometry.getAttribute('skinWeight');
      const positions=mesh.geometry.getAttribute('position');
      for(let vertex=0;vertex<positions.count;vertex++){
        let covered=0;
        for(let component=0;component<4;component++)
          if(/^Sword0[45](?:_|$)/i.test(mesh.skeleton.bones[indices.getComponent(vertex,component)]?.name||''))
            covered+=weights.getComponent(vertex,component);
        if(covered>.99){
          const point=new THREE.Vector3().fromBufferAttribute(positions,vertex);
          mesh.applyBoneTransform(vertex,point);tip.add(point.applyMatrix4(mesh.matrixWorld));tipVertices++;
        }
      }
    });
    const origin=grip&&new THREE.Vector3().setFromMatrixPosition(grip);
    const direction=socket&&new THREE.Vector3(0,1,0).transformDirection(socket);
    const blade=tipVertices&&tip.divideScalar(tipVertices).sub(origin).normalize();
    return {materials:Object.entries(matData).map(([key,info])=>({key,...info,
        mapped:!!matsByName[key]?.[0]?.map,masked:!!matsByName[key]?.[0]?.alphaMap,
        emission:matsByName[key]?.[0]?.emissiveIntensity})),
      weapon:weapon&&{name:weapon.name,grip:binding?.grip?.node.name,tip_vertices:tipVertices,
        direction_dot:blade&&blade.dot(direction),grip_error:grip&&socket&&origin.distanceTo(new THREE.Vector3().setFromMatrixPosition(socket))},
      playing:document.getElementById('viewport-play').getAttribute('aria-pressed')==='true'};
  }
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    result = {'checks': [], 'page_errors': [], 'asset_errors': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1400, 'height': 960})
        page = context.new_page()
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
        def response_received(response):
            if response.status >= 400 and any(endpoint in response.url for endpoint in
                    ('/api/model_gltf?', '/api/skin_materials', '/api/texture_png?')):
                result['asset_errors'].append({'url': response.url, 'status': response.status})
        page.on('response', response_received)
        page.route('**/static/viewport.js', lambda route: route.fulfill(
            body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK,
            content_type='text/javascript'))
        try:
            setup = context.request.get(args.url + '/api/setup_status').json()
            assert setup.get('configured'), 'Use a fully configured isolated development instance'
            assert Path(setup.get('mods_prefill', '')).name == 'test-mods', 'Use an isolated test-mods destination'
            print('Opening the configured app and real Blade lobby mesh', flush=True)
            page.goto(args.url, wait_until='domcontentloaded')
            page.wait_for_function('window.AtelierViewport && window.atelierProject?.()', timeout=120000)
            page.locator('#settings-theme').select_option('dark', force=True)
            if page.locator('#changelog-done').is_visible():
                page.locator('#changelog-done').click()
            started = time.monotonic()
            page.evaluate('(mesh)=>{void AtelierViewport.openMesh(mesh,"Blade","1044001")}', MESH)
            page.wait_for_function('__bladePreview.ready()', timeout=240000)
            print('Real geometry, materials, textures and standing idle are ready', flush=True)
            page.wait_for_timeout(350)
            result['load_seconds'] = round(time.monotonic() - started, 2)
            state = result['idle'] = page.evaluate('__bladePreview.inspect()')
            page.screenshot(path=str(report / 'blade-idle.png'))
            hair = [m for m in state['materials'] if m.get('game_rel', '').endswith('MI_1044001_Hair_02')]
            assert len(hair) == 1, 'The shared hair/eyebrow material is missing or duplicated'
            assert hair[0]['mapped'] and hair[0]['masked'], 'Hair needs its diffuse and opacity textures'
            assert not hair[0].get('mapping_error') and len(hair[0].get('shared_slots', [])) == 2
            assert 'slot_index' not in hair[0], 'A merged material must not target an arbitrary cooked section'
            hair_cards = next(m for m in state['materials'] if m.get('game_rel', '').endswith('MI_1044001_Hair_01'))
            assert hair_cards['mapped'] and hair_cards['masked'], 'Both hair materials need their real textures'
            body = next(m for m in state['materials'] if m.get('game_rel', '').endswith('MI_1044001_Body'))
            assert body['emission'] == 0, 'An unused tattoo mask must stay non-emissive'
            result['checks'].append('Real tattoo strength stays zero; shared hair and eyebrows receive both textures without guessing a section')
            assert state['playing'], 'The real standing idle did not start'
            for pose in ('idle', 'rest'):
                if pose == 'rest':
                    page.locator('#viewport-animation').select_option('')
                    page.wait_for_timeout(150)
                    state = result['rest'] = page.evaluate('__bladePreview.inspect()')
                    page.screenshot(path=str(report / 'blade-rest.png'))
                weapon = state['weapon']
                assert weapon['grip'] == 'WP_Sword', weapon
                assert weapon['grip_error'] < 1e-5, weapon
                assert weapon['tip_vertices'] > 0 and weapon['direction_dot'] > .9, weapon
            result['checks'].append('Rendered blade vertices point along the hand socket in both real idle and rest poses; the authored grip stays in the hand')
            page.evaluate('__bladePreview.face()')
            page.wait_for_timeout(150)
            page.screenshot(path=str(report / 'blade-hair-eyebrows.png'))
            page.locator('#viewport-original').click()
            page.wait_for_function('document.getElementById("viewport-original").getAttribute("aria-pressed")==="true"')
            page.wait_for_timeout(300)
            page.screenshot(path=str(report / 'blade-original.png'))
            assert not result['page_errors'], result['page_errors']
            assert not result['asset_errors'], result['asset_errors']
            result['checks'].append('Original-material comparison renders without page or asset errors')
        except Exception as error:
            result['error'] = str(error)
            page.screenshot(path=str(report / 'failure.png'))
            raise
        finally:
            (report / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            browser.close()
    print(f'PASS {len(result["checks"])} real Blade preview checks')


if __name__ == '__main__':
    main()
