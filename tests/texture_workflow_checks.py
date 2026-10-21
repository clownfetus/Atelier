"""Browser checks for HDR file selection and the optional Blender project texture copies."""
from io import BytesIO
import json

from PIL import Image


def run_texture_workflow_checks(context, url, report, checks):
    tab = context.new_page(); errors, extracts, opened, replacements = [], [], [], []
    tab.on('pageerror', lambda error: errors.append(str(error)))
    key = 'atelier.blenderProjectTextures'; saved = None
    tab.route('**/api/blender_status', lambda route: route.fulfill(json={'ok': True}))
    def extract(route):
        extracts.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'blend': 'fixture.blend', 'textures': ['Textures/T_Body'],
                           'materials': ['Body'], 'warnings': [], 'project_textures': extracts[-1]['project_textures']})
    tab.route('**/api/mesh_blend_extract', extract)
    def open_blend(route):
        opened.append(route.request.url); route.fulfill(json={'ok': True})
    tab.route('**/api/open_blend?*', open_blend)
    def replace(route):
        replacements.append(route.request.post_data_buffer)
        route.fulfill(json={'ok': True, 'game_rel': 'Fixtures/T_Cube', 'hdr': True, 'texture_class': 'TextureCube'})
    tab.route('**/api/replace_texture', replace)
    tab.route('**/api/imported', lambda route: route.fulfill(json=[]))
    try:
        tab.goto(url); tab.wait_for_function('window.atelierProject?.()')
        saved = tab.evaluate('key=>localStorage.getItem(key)', key)
        control = tab.locator('#settings-blender-project-textures')
        assert control.is_checked() == (saved != '0')
        tab.evaluate('openPaths()')
        control.uncheck()
        field = tab.locator('.setup-field').filter(has=control)
        assert field.evaluate('node=>node.scrollWidth<=node.clientWidth')
        field.screenshot(path=str(report/'blender-project-textures-setting.png'), animations='disabled')
        tab.locator('#setup-close').click()
        tab.reload(); tab.wait_for_function('window.atelierProject?.()')
        assert not control.is_checked()
        with tab.expect_response('**/api/open_blend?*'):
            tab.evaluate("meshBlendExtract('Fixtures/SK_Body','Fixture model')")
        tab.wait_for_function('!document.querySelector("#atelier-confirm-overlay.active")')
        assert extracts[-1]['project_textures'] is False
        tab.wait_for_function('document.body.textContent.includes("Textures are packed in the Blender file")')
        assert opened
        control.evaluate("node=>{node.checked=true;node.dispatchEvent(new Event('change',{bubbles:true}));}")
        with tab.expect_response('**/api/open_blend?*'):
            tab.evaluate("meshBlendExtract('Fixtures/SK_Body','Fixture model',true)")
        assert extracts[-1]['project_textures'] is True
        checks.append('The Blender project texture preference persists across reload; off opens with packed textures and no import confirmation, while on retains project texture copies')

        tab.evaluate("replaceTextureFromFile(new File(['#?RADIANCE\\nfixture'], 'Reflection.hdr', {type:''}), 'Fixtures/T_Cube')")
        assert replacements and b'Reflection.hdr' in replacements[-1]
        assert b'#?RADIANCE' in replacements[-1]
        tab.wait_for_function('document.body.textContent.includes("HDR cubemap replaced")')
        checks.append('A Radiance file with no browser MIME type reaches texture replacement unchanged and returns HDR-specific preview feedback')

        tab.evaluate("""() => {
          matEditor={game_rel:'Fixtures/MI_Body',textures:{Reflection:'Fixtures/T_Cube'},textureClasses:{Reflection:'TextureCube'},custom:{}};
          const host=document.createElement('section');host.id='hdr-picker-fixture';
          host.style.cssText='position:fixed;inset:40px;z-index:9999;background:var(--bg2);padding:20px;overflow:auto';
          host.innerHTML=_matTexturesHtml(matEditor,new Map());document.body.append(host);
        }""")
        button = tab.locator('#hdr-picker-fixture').get_by_role('button', name='Use my HDR cubemap…')
        with tab.expect_file_chooser() as chooser:
            button.click()
        assert chooser.value.element.get_attribute('accept') == '.hdr,.dds'
        assert 'all six faces and HDR values' in tab.locator('#hdr-picker-fixture').inner_text()
        tab.screenshot(path=str(report/'hdr-material-picker.png'), animations='disabled')
        tab.evaluate("document.getElementById('hdr-picker-fixture').remove();matEditor=null")
        checks.append('TextureCube material slots offer HDR/DDS selection with an explicit six-face and HDR preview explanation')
        assert not errors, errors
    finally:
        tab.evaluate('args=>{if(args.saved===null)localStorage.removeItem(args.key);else localStorage.setItem(args.key,args.saved);}', {'key': key, 'saved': saved})
        tab.close()
