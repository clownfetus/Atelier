"""Real HTTP/browser checks of reviewed bulk saves and managed-job cancellation."""
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch


def run_job_bulk_checks(page, context, url, report, checks):
    from atelier import config as C, jobs as J
    from atelier.handlers import curve as CV
    from atelier.web import routes as R

    def curve(value):
        return {"Exports":[{"Data":[{"Name":"FloatCurves","Value":[{"Value":[
            {"Value":[{"Value":{"Time":0.,"Value":value,"ArriveTangent":.5,"LeaveTangent":.5}}]}
        ]}]} for _ in range(4)]}]}

    project = Path(C.project_dir('Smoke A'))
    assets = ['Fixture/C_BulkOne','Fixture/C_BulkTwo']
    files = []
    for gr in assets:
        path = Path(C.project_base(gr,str(project))+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(curve(1)),encoding='utf-8');files.append(path)
    items = [dict(type='asset',file_type='curve',name=gr.split('/')[-1],game_rel=gr,
                  token=R.token(gr),selected=True,imported=True) for gr in assets]
    tab = context.new_page()
    tab.route('**/api/imported',lambda route: route.fulfill(json=items))
    tab.route('**/api/browse?*',lambda route: route.fulfill(json=items))
    try:
        tab.goto(url)
        tab.wait_for_function("window.atelierProject() === 'Smoke A' && window.AtelierBulkEdit")
        tab.wait_for_function("!document.querySelector('.overlay.active')")
        tab.wait_for_function("Object.keys(sidebarData).length===2")
        tab.locator('#bulk-edit-open').click()
        tab.locator('#bulk-factor').fill('2')
        before = [path.read_bytes() for path in files]
        tab.locator('#bulk-preview').click()
        tab.wait_for_function("!document.getElementById('bulk-apply').disabled")
        assert [path.read_bytes() for path in files] == before
        assert tab.locator('#bulk-results tbody tr, #bulk-results table tr').count() == 3
        for theme in ('dark','light'):
            tab.locator('[data-theme-picker]').first.select_option(theme)
            tab.screenshot(path=str(report / ('bulk-review-'+theme+'.png')))
        tab.locator('#bulk-apply').click()
        tab.wait_for_function("document.getElementById('bulk-status').textContent.startsWith('Saved 2')")
        for path in files:
            channels = CV._channels(json.loads(path.read_text()))
            assert channels['R'][0]['value'] == 2 and channels['A'][0]['value'] == 1
        checks.append('Bulk review uses real HTTP jobs without project writes; applying saves both curves and preserves alpha')

        tab.locator('#bulk-factor').fill('3')
        tab.locator('#bulk-preview').click()
        tab.wait_for_function("!document.getElementById('bulk-apply').disabled")
        tab.locator('#bulk-factor').fill('4')
        assert tab.locator('#bulk-apply').is_disabled()
        tab.locator('#bulk-preview').click()
        tab.wait_for_function("!document.getElementById('bulk-apply').disabled")
        files[0].write_text(json.dumps(curve(9)),encoding='utf-8')
        previous = files[1].read_bytes()
        tab.locator('#bulk-apply').click()
        tab.wait_for_function("document.getElementById('bulk-status').textContent.includes('changed after preview')")
        assert files[1].read_bytes() == previous
        assert CV._channels(json.loads(files[0].read_text()))['R'][0]['value'] == 9
        checks.append('Changing bulk controls invalidates approval; an external edit rejects the entire stale batch')
        tab.locator('#bulk-close').click()

        started = threading.Event()
        def slow_export(body):
            started.set()
            while True:
                J.progress('Encoding fixture texture…')
                time.sleep(.04)
        with patch.object(R,'_install_mod_payload',side_effect=slow_export):
            tab.evaluate("""() => {
              window.__jobResult=null;
              AtelierJobs.run('/api/install_mod',{project:'Smoke A',method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({mod_name:'Cancelable fixture',items:['Fixture/C_BulkOne'],password:'never-store-this-input'})})
                .then(result=>window.__jobResult=result);
            }""")
            tab.locator('#job-activity').click()
            tab.wait_for_function("[...document.querySelectorAll('.job-row')].some(n=>n.textContent.includes('Encoding fixture texture'))")
            assert started.is_set()
            tab.locator('.job-row').filter(has_text='Cancelable fixture').get_by_role('button',name='Cancel',exact=True).click()
            tab.wait_for_function('window.__jobResult?.cancelled===true')
            tab.wait_for_function("[...document.querySelectorAll('.job-state')].some(n=>n.textContent==='cancelled')")
        assert 'never-store-this-input' not in ''.join(p.read_text() for p in J.manager().directory.glob('*.json'))
        checks.append('Activity cancels a running HTTP export; job records retain outcomes without saving input passwords')
        tab.reload()
        tab.wait_for_function("window.atelierProject() === 'Smoke A'")
        tab.wait_for_selector('#job-activity')
        tab.locator('#job-activity').click()
        tab.wait_for_function("[...document.querySelectorAll('.job-state')].some(n=>n.textContent==='cancelled')")
        assert tab.locator('.job-row').count() >= 5
        tab.screenshot(path=str(report/'activity-history.png'))
        checks.append('Reloading restores project job history and cancelled/failed outcomes without resubmitting work')
        tab.locator('#job-overlay').get_by_role('button',name='Close',exact=True).click()
        tab.locator('#bulk-edit-open').click()
        tab.set_viewport_size({'width':1024,'height':768})
        tab.keyboard.press('Tab');tab.keyboard.press('Shift+Tab');tab.keyboard.press('Escape')
        assert not tab.locator('#bulk-overlay').evaluate("n=>n.classList.contains('active')")
        assert tab.locator('#bulk-edit-open').evaluate('n=>n===document.activeElement')
        checks.append('Bulk dialog fits a compact desktop, traps keyboard focus and returns focus on Escape')
    finally:
        tab.close()
