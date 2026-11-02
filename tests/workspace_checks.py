"""Workspace navigation and renderer lifetime with generated geometry and local PNGs."""
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HOOK = r"""
(() => {
  const renderers=new Set();
  let disposed=0;
  loader.loadAsync=async()=>{
    const group=new THREE.Group();
    const material=new THREE.MeshStandardMaterial();material.name='MI_Body';
    for(const [w,h,d,x,y] of [[.7,1,.35,0,1.4],[.4,.4,.4,0,2.1],[.24,.9,.26,-.2,.45],[.24,.9,.26,.2,.45],[.2,.85,.25,-.5,1.4],[.2,.85,.25,.5,1.4]]){
      const geometry=new THREE.BoxGeometry(w,h,d);geometry.addEventListener('dispose',()=>disposed++);
      const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,0);group.add(mesh);
    }
    return {scene:group};
  };
  window.__workspace={
    async settled(){await materialTask;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));},
    stats(){renderers.add(renderer);return {renderers:renderers.size,textures:renderer.info.memory.textures,
      geometries:renderer.info.memory.geometries,cached:texCache.size,disposed,animating:!!raf};},
    state:()=>({skin:meshSkin,materialSet:chromaSkin,project:viewportProject}),
  };
})();
"""


def run_workspace_checks(context, url, report, checks):
    page = context.new_page()
    errors, texture_reads = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/static/viewport.js', lambda route: route.fulfill(
        body=(ROOT / 'gui/viewport.js').read_text(encoding='utf-8') + HOOK, content_type='text/javascript'))
    png = BytesIO(); Image.new('RGB', (16, 16), (110, 136, 190)).save(png, 'PNG')
    skins = [dict(name='Original costume' if i == 0 else f'Costume {i+1}', path=f'Characters/1029/{1029001+i}') for i in range(20)]
    heroes = [dict(name='Magik', path='Characters/1029', skins=skins)]
    page.route('**/api/catalogue/library', lambda route: route.fulfill(json={'heroes': heroes}))
    page.route('**/api/catalogue/hero/**', lambda route: route.fulfill(body=png.getvalue(), content_type='image/png'))
    page.route('**/api/skin_meshes?*', lambda route: route.fulfill(json=[{
        'name': 'Body', 'game_rel': f'Characters/1029/{parse_qs(urlparse(route.request.url).query)["skin_id"][0]}/Meshes/Body'}]))
    page.route('**/api/idle_animations?*', lambda route: route.fulfill(json={'ok': True, 'animations': []}))
    page.route('**/api/browse_material_dirs?*', lambda route: route.fulfill(json={'dirs': [
        {'name': '1029001', 'materials': 1, 'meshes': 1}, {'name': '1029002', 'materials': 1, 'meshes': 0}]}))
    def materials(route):
        skin = route.request.post_data_json['skin_id']
        route.fulfill(json={'ok': True, 'materials': {'MI_Body': {
            'game_rel': f'Characters/1029/{skin}/Materials/MI_Body',
            'colors': [{'name': 'BaseTint', 'rgba': [.6, .6, .9, 1]}], 'scalars': [],
            'textures': {'BaseColor': f'Characters/1029/{skin}/Textures/T_Body'}, 'tex_ver': {}}}})
    page.route('**/api/skin_materials', materials)
    def texture(route):
        texture_reads.append(route.request.url)
        route.fulfill(body=png.getvalue(), content_type='image/png')
    page.route('**/api/texture_png?*', texture)
    # The Mod tray's edits, as /api/imported reports them; a viewport save adds the material.
    imported = []
    body_edit = {'token': 'tok-body', 'game_rel': 'Characters/1029/1029001/Materials/MI_Body', 'name': 'MI_Body',
                 'file_type': 'material', 'skin_id': '1029001', 'char_id': '1029', 'char_name': 'Magik',
                 'skin_name': 'Original costume', 'mtime': 1, 'selected': True, 'opts': {}}
    def save(route):
        if not imported: imported.append(dict(body_edit))
        route.fulfill(json={'ok': True})
    def delete(route):
        imported.clear()
        route.fulfill(json={'ok': True, 'deleted': 1})
    page.route('**/api/material_save', save)
    page.route('**/api/imported', lambda route: route.fulfill(json=imported))
    page.route('**/api/material_changes?*', lambda route: route.fulfill(json={'ok': True, 'changes': [
        {'name': 'BaseTint', 'before': '#9999e6', 'after': '#9644cc'}, {'name': 'Trim', 'before': None, 'after': '#ffffff'}]}))
    page.route('**/api/delete_imported', delete)
    try:
        page.goto(url)
        page.wait_for_selector('#proj-lead button')
        page.wait_for_function('window.__workspace && window.AtelierWorkspace')
        assert page.locator('#proj-lead h3').inner_text() == 'Smoke A'
        page.screenshot(path=str(report / 'projects-light.png'), animations='disabled')
        page.locator('#proj-lead button').click()
        page.wait_for_selector('.workspace-costume')
        page.locator('.workspace-costume').first.click()
        page.wait_for_selector('#workspace-stage #viewport-overlay.active')
        page.evaluate('__workspace.settled()')
        assert page.locator('#viewport-box').get_attribute('role') == 'region'
        assert page.locator('#viewport-box').get_attribute('aria-modal') is None
        assert page.locator('#page-library').is_visible()
        assert page.locator('#workspace-dock').is_visible()
        assert 'Save a colour change' in page.locator('#workspace-dock-status').inner_text()
        assert page.locator('#workspace-review').is_disabled()
        page.locator('.vp-material-select').first.click()
        for width, height in [(1400, 900), (1024, 768)]:
            page.set_viewport_size({'width': width, 'height': height})
            for theme in ['light', 'dark']:
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                page.screenshot(path=str(report / f'workspace-{theme}-{width}.png'), animations='disabled')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert page.locator('#viewport-mat-save').is_visible()
        page.set_viewport_size({'width': 1400, 'height': 900})
        page.locator('.vp-hex').first.fill('#9644CC')
        page.locator('.vp-hex').first.press('Tab')
        assert page.locator('#viewport-mat-save').is_enabled()
        page.locator('#page-projects').click()
        page.wait_for_selector('#atelier-confirm.active')
        page.locator('#atelier-confirm-cancel').click()
        assert page.locator('#workspace').is_visible()
        assert page.locator('#viewport-mat-save').is_enabled()
        page.locator('#viewport-mat-save').click()
        page.wait_for_function('!AtelierViewport.hasPendingEdits()')
        checks.append('Projects opens an embedded workspace; explicit Save and cancelled navigation preserve colour drafts')

        slot = page.locator('#workspace-dock-list .workspace-slot')
        slot.wait_for()
        page.wait_for_selector('.workspace-slot[data-changes="2"]')
        assert slot.locator('strong').inner_text() == 'Body'
        assert 'Magik / Original costume' in slot.inner_text()
        swatches = slot.locator('.workspace-swatch')
        assert swatches.nth(0).evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(153, 153, 230)'
        assert swatches.nth(1).evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(150, 68, 204)'
        assert slot.locator('.workspace-swatch-more').inner_text() == '+1'
        assert page.locator('#workspace-dock-count').inner_text() == '1'
        assert page.locator('#workspace-review').is_enabled()
        for theme in ['light', 'dark']:
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
            page.locator('#workspace-dock').screenshot(path=str(report / f'dock-{theme}.png'), animations='disabled')
        page.evaluate('document.documentElement.dataset.theme="light"')
        page.screenshot(path=str(report / 'workspace-with-dock-1400.png'), animations='disabled')

        page.locator('#workspace-review').click()
        page.wait_for_selector('#export-review-overlay.active')
        assert 'MI_Body' in page.locator('#export-review-overlay').inner_text()
        page.keyboard.press('Escape')
        page.wait_for_selector('#export-review-overlay.active', state='hidden')

        slot.locator('.workspace-restore').click()
        page.wait_for_selector('#atelier-confirm.active')
        with page.expect_request('**/api/skin_materials'):
            page.locator('#atelier-confirm-ok').click()
        page.wait_for_function('!document.querySelector("#workspace-dock-list .workspace-slot")')
        assert page.locator('#workspace-review').is_disabled()
        assert 'Save a colour change' in page.locator('#workspace-dock-status').inner_text()
        checks.append('Your mod dock lists saved edits with before and after colours, opens the export review, and Restore reloads the costume')

        page.locator('#viewport-model-menu > summary').click()
        page.locator('#viewport-chroma').select_option('1029002')
        page.evaluate('__workspace.settled()')
        page.locator('#viewport-model-menu > summary').click()

        page.locator('#page-projects').click()
        page.wait_for_selector('#proj-lead button')
        page.locator('#proj-lead button').click()
        page.wait_for_selector('#workspace-stage #viewport-overlay.active')
        page.evaluate('__workspace.settled()')
        assert page.evaluate('__workspace.state().skin') == '1029001'
        assert page.evaluate('__workspace.state().materialSet') == '1029002'
        page.locator('#page-library').click()
        page.wait_for_selector('#grid-area .card')
        assert not page.evaluate('__workspace.stats().animating')
        page.locator('#page-workspace').click()
        page.wait_for_selector('#workspace-stage #viewport-overlay.active')
        page.evaluate('__workspace.settled()')
        checks.append('The last costume and colour set reopen in one click; Library remains reachable and hidden stages stop rendering')

        async_switch = r"""async start=>{
          const samples=[];
          for(let i=0;i<20;i++){
            await AtelierViewport.open(String(1029001+i),'Fixture costume '+(i+1));
            await __workspace.settled();samples.push(__workspace.stats());
          }
          return samples;
        }"""
        warm = page.evaluate(async_switch, 0)
        before = len(texture_reads)
        measured = page.evaluate(async_switch, 0)
        assert len(texture_reads) == before, (before, len(texture_reads))
        assert all(s['renderers'] == 1 for s in measured), measured
        assert all(s['textures'] == warm[-1]['textures'] for s in measured), measured
        assert all(s['geometries'] == warm[-1]['geometries'] for s in measured), measured
        assert measured[-1]['disposed'] > warm[-1]['disposed']
        (report / 'skin-switch-stress.json').write_text(json.dumps({'warmup': warm, 'measured': measured, 'texture_reads': before, 'additional_reads': len(texture_reads)-before}, indent=2))
        checks.append('Twenty measured skin switches after cache warmup keep one renderer, stable live textures/geometries and zero repeated texture downloads')

        page.locator('#page-projects').click()
        page.wait_for_selector('#project-overlay.active #proj-lead button')
        page.locator('#proj-grid [data-name="Smoke B"]').click()
        page.wait_for_selector('.workspace-costume')
        assert page.locator('#workspace-stage').is_hidden()
        page.locator('#page-projects').click()
        page.wait_for_function('document.querySelector("#project-overlay.active #proj-lead h3")?.textContent === "Smoke B"')
        assert page.locator('#proj-lead h3').inner_text() == 'Smoke B'
        page.reload()
        page.wait_for_selector('#proj-lead button')
        assert page.locator('#proj-lead h3').inner_text() == 'Smoke B'
        checks.append('Opening recency survives reload, and an empty project asks for a costume instead of guessing')

        page.route('**/api/projects', lambda route: route.fulfill(json={'ok': True, 'active': '', 'projects': []}))
        page.reload()
        page.wait_for_selector('#proj-lead button')
        assert page.locator('#proj-lead button').inner_text().strip() == 'Start a recolour'
        page.screenshot(path=str(report / 'projects-empty.png'), animations='disabled')
        page.locator('#proj-lead button').click()
        page.wait_for_selector('.workspace-costume')
        page.screenshot(path=str(report / 'choose-costume.png'), animations='disabled')
        page.unroute('**/api/projects')
        page.locator('.workspace-costume').first.click()
        page.wait_for_selector('#workspace-stage #viewport-overlay.active')
        assert page.evaluate('atelierProject()') == 'Magik — Original costume'
        checks.append('Start a recolour chooses a costume before creating its automatically named project')
        assert not errors, errors
    finally:
        page.close()
