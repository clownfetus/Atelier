"""Exercise the Skin VFX authoring and Galacta JSON hand-off in Model Studio."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKIN = '1031313'
MESHES = [
    {'game_rel': f'Characters/1031/{SKIN}/Meshes/SK_1031{form}_{SKIN}', 'name': f'Fixture form {form}', 'kind': 'body'}
    for form in (0, 1)
]
EFFECT = f'VFX/Particles/Characters/1031/{SKIN}/NS_{SKIN}_BodyStar_01'

# Draw a small rig in the actual viewer. Only asset retrieval is substituted.
RIG = r'''
loader.loadAsync = async url => {
  const root = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({color:0x52748e,roughness:.8});
  material.name = 'MI_Fixture';
  const add = (geometry,x,y,z) => {
    const mesh = new THREE.Mesh(geometry,material);
    mesh.position.set(x,y,z);
    root.add(mesh);
  };
  add(new THREE.BoxGeometry(.75,1.15,.45),0,1.55,0);
  add(new THREE.SphereGeometry(.28,24,16),0,2.37,0);
  for(const side of [-1,1]) {
    add(new THREE.CapsuleGeometry(.12,.68,6,12),side*.55,1.58,0);
    add(new THREE.CapsuleGeometry(.16,.70,6,12),side*.22,.48,0);
  }
  if (!url.includes('SK_Standalone')) {
    for(const [name,x,y] of [['root',0,0],['clavicle_l',-.3,1.9],['clavicle_r',.3,1.9],['head',0,2.37]]) {
      const bone = new THREE.Bone(); bone.name = name; bone.position.set(x,y,0); root.add(bone);
    }
  }
  return {scene:root,animations:[]};
};
'''


def run_skin_vfx_checks(context, url, report, checks):
    tab = context.new_page()
    tab.set_viewport_size({'width': 1100, 'height': 770})
    errors, searches = [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    tab.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + RIG, content_type='text/javascript'))
    tab.route('**/api/skin_meshes?*', lambda route: route.fulfill(json=MESHES))
    tab.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok': True, 'animations': []}))
    tab.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs': []}))
    tab.route('**/api/skin_materials', lambda route: route.fulfill(json={'ok': True, 'materials': {}}))

    def search(route):
        searches.append(parse_qs(urlsplit(route.request.url).query)['q'][0])
        route.fulfill(json={'assets': [
            {'name': 'Emitter fixture', 'game_rel': 'VFX/NE_Fixture', 'type': 'vfx'},
            {'name': 'Body star', 'game_rel': EFFECT, 'type': 'vfx'},
        ]})
    tab.route('**/api/search?*', search)

    try:
        tab.goto(url)
        tab.wait_for_function('window.AtelierViewport && window.atelierProject?.()')
        tab.evaluate("AtelierViewport.openMesh('Meshes/SK_Standalone','Standalone preview')")
        tab.wait_for_function("document.getElementById('viewport-canvas').getAttribute('aria-busy') === 'false'")
        toggle = tab.locator('#viewport-skin-vfx-toggle')
        assert toggle.is_hidden(), 'The integration only applies to character costumes.'
        tab.evaluate('AtelierViewport.close()')

        tab.evaluate("skin => AtelierViewport.open(skin,'Skin VFX verification fixture')", SKIN)
        toggle.wait_for()
        toggle.click()
        panel = tab.locator('#viewport-skin-vfx-panel')
        panel.wait_for()
        assert panel.locator('#skin-vfx-placement').is_hidden()
        assert panel.get_by_role('button', name='Export setup').is_disabled()
        panel.get_by_label('Setup name').fill('Night stars')
        panel.get_by_role('button', name='Add effect').click()
        assert not panel.locator('#skin-vfx-placement').evaluate('(el) => el.open')
        assert not panel.locator('#skin-vfx-mesh-options').evaluate('(el) => el.open')
        panel.get_by_label('Effect name').fill('Left shoulder')
        panel.get_by_label('Niagara system', exact=True).fill('star')
        panel.get_by_role('button', name='Body star').click()
        assert searches == ['ns_ star'], searches
        assert panel.get_by_role('button', name='Emitter fixture').count() == 0
        panel.get_by_label('Target bone').fill('clavicle_l')
        guide = tab.locator('#skin-vfx-guide')
        guide.wait_for()
        assert panel.get_by_role('button', name='Export setup').is_enabled()
        assert panel.locator('.skin-vfx-editor').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        active_bounds = panel.locator('#skin-vfx-placement summary').bounding_box()
        footer_bounds = panel.locator('.skin-vfx-footer').bounding_box()
        assert active_bounds['y'] + active_bounds['height'] <= footer_bounds['y'], (active_bounds, footer_bounds)
        assert panel.get_by_label('Niagara system', exact=True).input_value() == EFFECT.split('/')[-1]
        tab.screenshot(path=str(report / 'skin-vfx-model-studio.png'))
        panel.screenshot(path=str(report / 'skin-vfx-panel.png'))
        checks.append('Skin VFX appears for rigged costumes with the placement settings collapsed and no horizontal overflow')

        panel.locator('#skin-vfx-placement summary').click()
        marker = guide.locator('.skin-vfx-guide-point')
        previous_left = marker.evaluate('(el) => el.style.left')
        panel.get_by_label('Offset (cm) X', exact=True).fill('12.5')
        tab.wait_for_function(
            "before => document.querySelector('.skin-vfx-guide-point').style.left !== before", arg=previous_left)
        panel.get_by_label('Rotation (°) Yaw').fill('-45')
        panel.get_by_label('Scale Z', exact=True).fill('0.75')
        panel.get_by_label('Loop effect').check()
        panel.get_by_label('Apply to').select_option('1')
        guide.wait_for(state='hidden')
        assert 'Form 1' in panel.locator('#skin-vfx-preview-note').inner_text()

        tab.locator('#viewport-model-menu > summary').click()
        tab.locator('#viewport-model-choice').select_option(label='Mesh 2 · Fixture form 1')
        guide.wait_for()
        panel.get_by_role('button', name='Duplicate effect').click()
        assert panel.get_by_label('Effect name').input_value() == 'Left shoulder copy'
        panel.get_by_role('button', name='Mirror placement').click()
        assert panel.get_by_label('Target bone').input_value() == 'clavicle_r'

        export = panel.get_by_role('button', name='Export setup')
        tab.evaluate("""() => {
          window.showSaveFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
        }""")
        export.click()
        assert export.is_enabled()
        assert panel.get_by_label('Effect name').input_value() == 'Left shoulder copy'
        assert not panel.locator('.skin-vfx-handoff').evaluate('(el) => el.open')

        tab.evaluate('window.showSaveFilePicker = undefined')
        with tab.expect_download() as pending:
            export.click()
        download = pending.value
        assert download.suggested_filename == 'GalactaVFX_Night stars.json'
        contents = Path(download.path()).read_bytes()
        payload = json.loads(contents)
        assert (payload['TargetHeroID'], payload['TargetSkinID'], payload['TargetMesh']) == (1031, int(SKIN), '')
        assert payload['Entries'][0] == {
            'EntryName': 'Left shoulder', 'System': '/Game/Marvel/' + EFFECT + '.' + EFFECT.split('/')[-1],
            'Bone': 'clavicle_l', 'Location': 'X=12.5 Y=0 Z=0', 'Rotation': 'P=0 Y=-45 R=0',
            'Scale': 'X=1 Y=1 Z=0.75', 'Loop': True, 'Form': 1,
        }, payload
        assert payload['Entries'][1]['Location'] == 'X=-12.5 Y=0 Z=0'
        assert payload['Entries'][1]['Rotation'] == 'P=0 Y=-135 R=0'
        checks.append('Effect search, bone placement, form switching, duplication and mirroring produce the expected Galacta VFX Lab JSON')

        upload = panel.locator('#skin-vfx-file')
        wrong_skin = json.dumps(dict(payload, TargetSkinID=1031314)).encode('utf-8')
        upload.set_input_files({'name': 'wrong-skin.json', 'mimeType': 'application/json', 'buffer': wrong_skin})
        tab.wait_for_function("document.getElementById('skin-vfx-status').textContent.includes('1031314')")
        assert panel.get_by_label('Setup name').input_value() == 'Night stars'
        upload.set_input_files({'name': download.suggested_filename, 'mimeType': 'application/json', 'buffer': contents})
        tab.wait_for_function("document.getElementById('skin-vfx-status').textContent === 'Setup opened.'")
        assert panel.get_by_label('Target bone').input_value() == 'clavicle_l'
        assert not panel.locator('#skin-vfx-placement').evaluate('(el) => el.open')

        tab.keyboard.press('Escape')
        panel.wait_for(state='hidden')
        assert tab.locator('#viewport-overlay.active').count() == 1
        toggle.click()
        assert panel.get_by_label('Setup name').input_value() == 'Night stars'
        checks.append('Imported setups stay scoped to their costume, and closing the inspector preserves the open draft')

        tab.evaluate('AtelierWorkspace.present()')
        toggle.wait_for()
        assert tab.locator('#workspace #viewport-uv-toggle').is_hidden()
        assert panel.get_by_label('Setup name').input_value() == 'Night stars'
        assert not errors, errors
        checks.append('The embedded Workspace exposes Skin VFX and preserves the open setup')
    finally:
        tab.close()
