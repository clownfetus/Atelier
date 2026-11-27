"""Editor controls and texture inspection with controlled save and image responses."""
from pathlib import Path

from PIL import Image


def _curve_history(tab):
    original = {'R': [{'time': 0, 'value': 1, 'interp': 'RCIM_Linear'}]}
    saves = []
    tab.route('**/api/curve_params?*', lambda route: route.fulfill(json={'ok': True, 'channels': original}))
    tab.route('**/api/curve_save', lambda route: saves.append(route))
    tab.route('**/api/curve_reset', lambda route: route.fulfill(json={'ok': True, 'channels': original}))
    tab.evaluate("openCurveEditor({name:'Curve fixture',game_rel:'Fixture/Curve'})")
    value = tab.locator('#curve-body input[title="value"]').first
    value.fill('2')
    tab.locator('#curve-save').click()
    tab.wait_for_function("document.getElementById('curve-status').textContent==='Saving…'")
    assert saves and saves[0].request.post_data_json['edits']['R'][0]['value'] == 2, 'Unexpected pending curve save'
    try:
        value.press('Control+z')
        assert value.input_value() == '2', 'Undo changed the curve while its save was in flight'
        value.fill('3')
    finally:
        saves.pop().fulfill(json={'ok': True})
    tab.wait_for_function("document.getElementById('curve-status').textContent.includes('Submitted edits saved')")
    tab.locator('#curve-undo').click()
    assert value.input_value() == '2', 'Undo did not return to the acknowledged save'
    assert not tab.evaluate('_curveDirty()'), 'Undo to the saved curve is still marked dirty'
    tab.locator('#curve-redo').click()
    assert value.input_value() == '3' and tab.evaluate('_curveDirty()'), 'Redo did not restore the newer change'
    tab.locator('#curve-close').click()
    tab.locator('#atelier-confirm-cancel').click()
    assert value.input_value() == '3', 'Cancel changed the curve draft'
    tab.locator('#curve-reset').click()
    tab.locator('#atelier-confirm-ok').click()
    tab.wait_for_function("document.getElementById('curve-status').textContent === 'Reset to vanilla.'")
    assert value.input_value() == '1', 'Reset did not restore the original curve'
    assert tab.locator('#curve-undo').is_disabled() and tab.locator('#curve-redo').is_disabled(), 'Reset retained old undo history'
    add_key = tab.locator('#curve-body').get_by_role('button', name='+ key', exact=True).first
    add_key.click()
    add_key.click()
    tab.locator('#curve-undo').click()
    assert tab.locator('#curve-body input[title="value"]').count() == 2, 'Separate add-key clicks coalesced'


def _material_history(tab):
    def params(value):
        return {'ok': True, 'colors': [{'name': 'Tint', 'rgba': value}], 'scalars': []}

    tab.route('**/api/material_params?*', lambda route: route.fulfill(json=params([.25, .5, .75, .5])))
    tab.route('**/api/material_original?*', lambda route: route.fulfill(json=params([1, 1, 1, 1])))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))
    tab.evaluate("openMaterialEditor({name:'Material fixture',game_rel:'Fixture/Material'})")
    tab.get_by_role('button', name='Game original', exact=True).click()
    tab.locator('#matrow0 .mat-restore').click()
    assert tab.locator('#mat-undo').is_enabled(), 'Material Use value bypassed Undo'
    tab.locator('#mat-undo').click()
    assert not tab.evaluate('materialDirtyCount()')
    assert tab.locator('#matwell0').evaluate("node => node.classList.contains('is-split')")
    tab.locator('#mat-redo').click()
    assert tab.evaluate('materialDirtyCount()') == 1


def _mpc_history(tab):
    tab.route('**/api/vfx_params?*', lambda route: route.fulfill(json={
        'ok': True, 'kind': 'mpc', 'scalars': [{'name': 'Roughness', 'value': .35}],
        'vectors': [{'name': 'Tint', 'rgba': [.25, .5, .75, 1]}],
    }))
    tab.evaluate("openVfxEditor({name:'MPC fixture',game_rel:'Fixture/MPC'})")
    value = tab.locator('#mpcsn0')
    value.fill('.75')
    assert tab.locator('#vfx-undo').is_enabled(), 'MPC scalar edits bypassed Undo'
    value.press('Control+z')
    assert value.input_value() == '0.35' and not tab.evaluate('_vfxDirty()')
    tab.locator('#vfx-redo').click()
    assert value.input_value() == '0.75' and tab.evaluate('_vfxDirty()')


def _texture_inspector(tab):
    from atelier import config

    asset = 'Fixture/Texture'
    edited = Image.new('RGBA', (512, 1024), (0, 255, 0, 255))
    edited.paste((215, 62, 17, 0), (0, 768, 512, 1024))
    original = Image.new('RGBA', (512, 1024), (255, 0, 0, 255))
    for image, directory in [(edited, config.project_dir('Smoke A')), (original, config.CACHE_3DVIEW)]:
        path = Path(config.project_base(asset, directory) + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, 'PNG')

    tab.evaluate("asset=>previewLibraryCard({type:'asset',file_type:'texture',imported:true,label:'Texture fixture',game_rel:asset})", asset)
    dialog = tab.locator('#library-preview')
    dialog.get_by_role('button', name='Wipe').click()
    wipe = dialog.get_by_role('slider', name='Original and edited split')
    wipe.evaluate("el=>{el.value=25;el.dispatchEvent(new Event('input',{bubbles:true}));}")
    width = wipe.bounding_box()['width']
    assert width < 300, f'Wipe width {width} is not aligned with the portrait texture'
    picture = wipe.bounding_box()
    tab.mouse.move(picture['x'] + width * .1, picture['y'] + picture['height'] * .5)
    dialog.locator('#library-preview-pixel').get_by_text('#FF0000', exact=False).wait_for()
    tab.mouse.move(picture['x'] + width * .9, picture['y'] + picture['height'] * .5)
    dialog.locator('#library-preview-pixel').get_by_text('#00FF00', exact=False).wait_for()
    dialog.get_by_role('button', name='200%').click()
    assert wipe.bounding_box()['width'] == 1024
    stage = dialog.locator('.library-preview-stage')
    assert stage.evaluate('el => {el.scrollLeft=100;el.scrollTop=100;return el.scrollLeft>0 && el.scrollTop>0;}')
    dialog.get_by_role('button', name='Edited', exact=True).click()
    dialog.get_by_role('button', name='Fit', exact=True).click()
    dialog.get_by_role('button', name='R', exact=True).click()
    canvas = dialog.locator('#library-preview-canvas')
    canvas.wait_for()
    assert canvas.evaluate("el => [...el.getContext('2d').getImageData(30,900,1,1).data]") == [215, 215, 215, 255]
    picture = canvas.bounding_box()
    tab.mouse.move(picture['x'] + picture['width'] * .2, picture['y'] + picture['height'] * .9)
    assert '#D73E11 · A 0' in dialog.locator('#library-preview-pixel').inner_text()


def _project_palette(tab):
    tab.route('**/api/project/palette', lambda route: route.fulfill(
        status=500, json={'ok': False, 'error': 'Write failed'}) if route.request.method == 'POST'
        else route.fulfill(json={'ok': True, 'palette': ['#00aabb']}))
    tab.route('**/api/material_params?*', lambda route: route.fulfill(json={
        'ok': True, 'colors': [{'name': 'Tint', 'rgba': [1, 1, 1, 1]}], 'scalars': [],
    }))
    tab.route('**/api/dye_info?*', lambda route: route.fulfill(json={'dyeable': False}))
    tab.evaluate("openMaterialEditor({name:'Material fixture',game_rel:'Fixture/Palette'})")
    palette = tab.locator('#mat-project-palette')
    palette.get_by_role('button', name='Apply colour #00AABB').wait_for()
    with tab.expect_response(lambda response: response.request.method == 'POST' and '/api/project/palette' in response.url):
        palette.get_by_role('button', name='Save colour', exact=False).click()
    assert palette.get_by_role('button', name='Apply colour #FFFFFF').count() == 0, 'A failed palette write appeared saved'
    assert palette.get_by_role('button', name='Apply colour #00AABB').is_visible()


def run_editor_improvements_checks(context, url, checks):
    failures = []
    for scenario, description in (
        (_curve_history, 'Curve history tracks the latest save, protects in-flight saves and clears on reset'),
        (_material_history, 'Applying a material reference value can be undone and redone'),
        (_mpc_history, 'MPC parameters support undo and redo'),
        (_texture_inspector, 'Texture wipe aligns with the image, samples either side and supports scrollable 200% zoom'),
        (_project_palette, 'A failed project palette write does not claim to save a colour'),
    ):
        tab = context.new_page()
        errors = []
        tab.on('pageerror', lambda error: errors.append(str(error)))
        try:
            tab.goto(url)
            tab.wait_for_function("window.atelierProject?.()==='Smoke A'")
            scenario(tab)
            assert not errors, errors
            checks.append(description)
        except AssertionError as error:
            failures.append(f'{scenario.__name__}: {error}')
        finally:
            tab.close()
    assert not failures, '\n' + '\n'.join(failures)
