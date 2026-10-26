"""Real editor/HTTP persistence and lifecycle checks with explicit native LUT fixtures."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from motionboard_fixtures import ASSET, details, bindings


def run_motionboard_checks(page, context, url, report, checks):
    from atelier import config as C
    from atelier.handlers import vfx as V
    project=Path(C.project_dir('Smoke A'))
    original=project.parent/'motionboard-original'/'NS_Motionboard'
    original.parent.mkdir(exist_ok=True); original.with_suffix('.uasset').write_bytes(b'fixture cooked package')
    native=details(); saves=[]
    tab=context.new_page(); errors=[]
    tab.on('pageerror',lambda error: errors.append(str(error)))
    tab.add_init_script("""const mbClear=CanvasRenderingContext2D.prototype.clearRect;
      window.__mbDraws=0;CanvasRenderingContext2D.prototype.clearRect=function(...args){
      if(this.canvas.id==='mb-canvas')window.__mbDraws++;return mbClear.apply(this,args);};""")
    item={'game_rel':ASSET,'name':'Motionboard fixture','file_type':'vfx'}
    tab.route('**/api/vfx_save',lambda route:(saves.append(route.request.post_data_json),route.continue_())[-1])
    def scrub(value):
        tab.locator('#mb-scrub').evaluate('(node,value)=>{node.value=value;node.dispatchEvent(new Event("input",{bubbles:true}));}',str(value))
    def open_editor():
        tab.evaluate('(item)=>openVfxEditor(item)',item)
        tab.wait_for_selector('#vfx-overlay.has-motionboard .mb-track')
    def select_opacity(point=3):
        tab.locator('.mb-track[data-track-key="3"] .mb-track-select').click()
        tab.locator('#mb-point').fill(str(point));tab.locator('#mb-point').press('Tab')

    try:
        with patch.object(V,'_ensure_extracted',return_value=str(original)), \
                patch.object(V,'_vfx_labels',side_effect=lambda *_args,**_kwargs:copy.deepcopy(bindings())), \
                patch.object(V,'uat',side_effect=lambda args:SimpleNamespace(returncode=0,stdout=json.dumps(native),stderr='')):
            tab.goto(url);tab.wait_for_function("window.atelierProject?.()==='Smoke A' && window.AtelierMotionboard")
            tab.evaluate('(item)=>{_openAfterImport=false;handleAssetClick(item);}',item)
            tab.wait_for_selector('#vfx-overlay.has-motionboard .mb-track')
            assert tab.locator('.mb-track').count()==6
            assert not Path(C.project_base(ASSET,str(project))+'.json').exists()
            assert tab.locator('#mb-map-color').input_value()=='1,2'
            assert tab.locator('#mb-map-opacity').input_value()=='3'
            assert tab.locator('#mb-map-scale').input_value()=='4'
            assert tab.locator('#mb-map-rate').input_value()=='5'
            assert tab.locator('#mb-map-emission').input_value()=='6'
            assert not tab.evaluate('_vfxDirty()')
            checks.append('Clicking an unimported VFX opens its editor with auto-open disabled; the real API supplies six LUT tracks and read-only opening creates no project edit')

            before=tab.evaluate('_vfxSnapshot(vfxEditor)')
            row=tab.locator('.mb-track[data-track-key="7"]')
            row.get_by_role('button',name='Move up',exact=False).click()
            row.get_by_role('button',name='Hide graph',exact=False).click()
            assert 'mb-track-hidden' in row.get_attribute('class')
            row.get_by_role('button',name='Isolate',exact=False).click()
            assert tab.locator('.mb-track:visible').count()==1
            tab.locator('#mb-show-all').click()
            tab.locator('#mb-track-filter').select_option('scalar');assert tab.locator('.mb-track:visible').count()==2
            tab.locator('#mb-show-all').click()
            assert tab.evaluate('_vfxSnapshot(vfxEditor)')==before
            checks.append('Hide, isolate, category filtering and track reordering change only local presentation; original LUT order, values and dirty state stay intact')

            scrub(.5)
            assert '.500' in tab.locator('#mb-clock').inner_text()
            assert all(tab.locator('.mb-playhead').nth(i).evaluate("node=>getComputedStyle(node).left !== '0px'") for i in range(6))
            tab.locator('#mb-duration').fill('.2');tab.locator('#mb-duration').press('Tab')
            tab.locator('#mb-loop').uncheck();scrub(.9);tab.locator('#mb-play').click()
            tab.wait_for_function("document.getElementById('mb-play').getAttribute('aria-pressed')==='false' && Number(document.getElementById('mb-scrub').value)===1")
            tab.locator('#mb-back').click();assert .91<float(tab.locator('#mb-scrub').input_value())<.92
            tab.locator('#mb-forward').click();assert float(tab.locator('#mb-scrub').input_value())==1
            tab.locator('#mb-loop').check();scrub(.98);tab.locator('#mb-speed').select_option('2');tab.locator('#mb-play').click()
            tab.wait_for_function("Number(document.getElementById('mb-scrub').value)<.7 && document.getElementById('mb-play').getAttribute('aria-pressed')==='true'")
            tab.locator('#mb-play').click();tab.locator('#mb-duration').fill('2');tab.locator('#mb-duration').press('Tab')
            checks.append('One normalized playhead scrubs every track; non-looping playback stops at the endpoint, frame stepping uses the chosen preview duration and looping/speed controls remain local')

            select_opacity()
            svg=tab.locator('.mb-track[data-track-key="3"] svg')
            point=svg.locator('[data-mb-point="2"]');bounds=point.bounding_box()
            tab.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2)
            tab.mouse.down();tab.mouse.move(bounds['x']+bounds['width']/2,bounds['y']-10,steps=3);tab.mouse.up()
            assert tab.evaluate('vfxEditor.groups[1].stops[2][0]')!=.5
            tab.locator('#mb-value').fill('.375')
            tab.locator('summary').filter(has_text='Gradient & numeric controls').click()
            legacy=tab.locator('[data-vfx-group="1"] input[data-vfx-stop="2"]')
            assert float(legacy.input_value())==.375
            legacy.fill('.25');assert float(tab.locator('#mb-value').input_value())==.25
            tab.locator('#mb-reset-point').click();assert tab.evaluate('vfxEditor.groups[1].stops[2][0]')==.5
            assert not tab.evaluate('_vfxDirty()')
            tab.locator('#mb-value').fill('.125')
            checks.append('Dragging a real scalar point, precise value entry and existing gradient/numeric inputs edit the same LUT stops; restoring one point returns exactly to its saved value')

            scrub(.5)
            tab.get_by_role('button',name='Original',exact=True).click()
            assert tab.locator('#mb-value').is_disabled()
            assert tab.evaluate('vfxEditor.groups[1].original_samples[2][0]')==.5
            tab.get_by_role('button',name='Compare',exact=True).click()
            assert tab.locator('.mb-reference-line').count()>0
            tab.mouse.move(5,5);tab.wait_for_function("!document.querySelector('.toast')")
            for theme in ('dark','light'):
                tab.locator('#settings-theme').select_option(theme,force=True)
                tab.screenshot(path=str(report/('motionboard-'+theme+'.png')))
            tab.set_viewport_size({'width':1024,'height':768})
            canvas=tab.locator('#mb-canvas').bounding_box();timeline=tab.locator('.mb-timeline-panel').bounding_box()
            assert canvas['width']>400 and canvas['height']>100 and timeline['height']>180
            assert tab.locator('#vfx-save').is_visible()
            tab.screenshot(path=str(report/'motionboard-compact.png'))
            tab.set_viewport_size({'width':1400,'height':900})
            tab.locator('#vfx-close').click();tab.wait_for_selector('#atelier-confirm.active')
            tab.locator('#atelier-confirm-cancel').click()
            assert tab.locator('#vfx-overlay').evaluate("n=>n.classList.contains('active')")
            assert tab.evaluate('_blockExportForDrafts()')
            assert 'unsaved VFX' in tab.locator('#vfx-status').inner_text()
            checks.append('Pristine samples support read-only Original and synchronized comparison; both themes and compact desktops retain the preview/timeline/save controls, and unsaved edits block close and export')

            tab.locator('#vfx-save').click();tab.wait_for_function('vfxEditor===null')
            saved=json.loads(Path(C.project_base(ASSET,str(project))+'.json').read_text())
            assert len(saved['vfx_edits'])==1 and saved['vfx_edits'][0]['export_indices']==[3]
            assert saved['vfx_edits'][0]['stops'][2][0]==.125
            assert set(saved['vfx_edits'][0])=={'export_indices','stops','sample_count','channels'}
            open_editor();select_opacity();assert float(tab.locator('#mb-value').input_value())==.125
            assert tab.evaluate('vfxEditor.groups[1].original_samples[2][0]')==.5
            tab.locator('#mb-original-track').click();assert tab.evaluate('_vfxDirty()')
            tab.locator('#vfx-save').click();tab.wait_for_function('vfxEditor===null')
            assert json.loads(Path(C.project_base(ASSET,str(project))+'.json').read_text())['vfx_edits']==[]
            checks.append('HTTP save persists only changed exports in the existing four-field sidecar format; reopening retains edits and the game reference, and restoring a track removes its saved LUT override')

            open_editor();select_opacity();tab.locator('#mb-value').fill('.25')
            tab.unroute('**/api/vfx_save')
            tab.route('**/api/vfx_save',lambda route:route.fulfill(json={'ok':False,'error':'Fixture save failure'}))
            tab.locator('#vfx-save').click();tab.wait_for_function("document.getElementById('vfx-status').textContent.includes('Fixture save failure')")
            assert float(tab.locator('#mb-value').input_value())==.25 and tab.evaluate('_vfxDirty()')
            tab.unroute('**/api/vfx_save');held=[]
            tab.route('**/api/vfx_save',lambda route:held.append(route))
            tab.locator('#vfx-save').click();tab.wait_for_function("document.getElementById('vfx-status').textContent==='Saving…'")
            tab.locator('#mb-value').fill('.75');assert held
            held.pop().continue_()
            tab.wait_for_function("document.getElementById('vfx-status').textContent.includes('newer changes remain unsaved')")
            assert float(tab.locator('#mb-value').input_value())==.75 and tab.evaluate('_vfxDirty()')
            tab.locator('#mb-reset-point').click();assert float(tab.locator('#mb-value').input_value())==.25
            assert not tab.evaluate('_vfxDirty()')
            checks.append('Failed saves retain the timeline draft; a save completing after another edit advances only the submitted baseline and keeps the newer point unsaved')

            tab.locator('#mb-original-track').click()
            tab.locator('#vfx-save').click();tab.wait_for_function("document.getElementById('vfx-status').textContent==='Saving…'")
            tab.locator('#mb-value').fill('.75');assert held
            held.pop().continue_()
            tab.wait_for_function("document.getElementById('vfx-status').textContent.includes('newer changes remain unsaved')")
            tab.locator('#mb-reset-point').click()
            assert float(tab.locator('#mb-value').input_value())==.5 and not tab.evaluate('_vfxDirty()')
            assert json.loads(Path(C.project_base(ASSET,str(project))+'.json').read_text())['vfx_edits']==[]
            assert not tab.evaluate('AtelierMotionboardData.modified(vfxEditor.groups[1])')
            checks.append('A game-original reset saved during a newer edit clears only its submitted restore intent; restoring that newer point leaves the track clean and its native LUT unmodified')

            tab.locator('#mb-play').click()
            tab.wait_for_function('__mbDraws>4')
            tab.locator('#bulk-edit-open').click();tab.wait_for_selector('#bulk-overlay.active')
            tab.wait_for_timeout(120);frozen=tab.evaluate('__mbDraws')
            tab.wait_for_timeout(180);assert tab.evaluate('__mbDraws')==frozen
            tab.locator('#bulk-close').click();tab.wait_for_function('count=>__mbDraws>count+2',arg=frozen)
            tab.locator('#mb-play').click();tab.locator('#vfx-close').click();tab.wait_for_function('vfxEditor===null')
            frozen=tab.evaluate('__mbDraws');tab.wait_for_timeout(180);assert tab.evaluate('__mbDraws')==frozen
            checks.append('Opening bulk editing suspends preview rendering and playback time; closing it resumes, and leaving VFX disposes the canvas renderer and stops animation frames')
            assert not errors,errors
    except BaseException:
        tab.screenshot(path=str(report/'motionboard-failure.png'))
        print('Motionboard status:',tab.locator('#vfx-status').inner_text(),flush=True)
        print('Motionboard errors:',errors,flush=True)
        raise
    finally:
        tab.close()
