"""Verify the source or packaged viewer against real game data in an isolated directory.

Reads game files and native tools; never imports, saves, exports or installs a mod.
Use a dedicated data directory with a configured project and test-mods destination.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    launch=parser.add_mutually_exclusive_group(required=True)
    launch.add_argument('--exe',type=Path,help='Packaged Atelier executable')
    launch.add_argument('--source',action='store_true',help='Launch this checkout in a hidden native WebView2 window')
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--skin',default='1029100')
    parser.add_argument('--mesh-rel',help='Open a specific mesh instead of the default character preview')
    parser.add_argument('--name',default='Native model verification')
    parser.add_argument('--app-port',type=int,default=8889)
    parser.add_argument('--debug-port',type=int,default=9449)
    parser.add_argument('--design-checks',action='store_true',help='Check the contextual Model Studio and capture visual QA states')
    parser.add_argument('--deferred-body-rel',help='Verify this alternate body stays unloaded initially, then switches exclusively')
    parser.add_argument('--expected-weapon-rel',help='Require this held weapon on the initial selected body')
    parser.add_argument('--viewport-script',type=Path,help='Optional saved viewer script for a before/after performance comparison')
    parser.add_argument('--import-server-checks',action='store_true',help='Source-only probe for persistent reader reuse and process shutdown')
    args=parser.parse_args()
    if args.import_server_checks and not args.source:
        parser.error('--import-server-checks requires the source launcher')
    data=args.data_root.resolve(strict=True)
    root=Path(__file__).resolve().parents[1]
    exe=args.exe.resolve(strict=True) if args.exe else None
    config=json.loads((data/'mr_config.json').read_text(encoding='utf-8'))
    if data==(exe.parent if exe else root) or not (data/'test-mods').is_dir() or Path(config.get('mods_folder','')).resolve()!=data/'test-mods':
        raise SystemExit('Use isolated data with its own test-mods directory.')
    for port in (args.app_port,args.debug_port):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',port))==0:raise SystemExit(f'Port {port} is already in use.')
    report=args.report_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    result={'mode':'source' if args.source else 'packaged','checks':[],'page_errors':[],'asset_errors':[]}
    if exe:
        with exe.open('rb') as stream:
            result['exe_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
    else:
        result['source_root']=str(root)
    env=dict(os.environ,ATELIER_DATA_DIR=str(data),ATELIER_PORT=str(args.app_port),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={args.debug_port}')
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=4
    if args.source:
        # Keep testing hooks in the launcher rather than in the shipped application.
        probe=('from atelier import import_server; routes.app.get("/api/_native_import_stats")(import_server.stats); ' if args.import_server_checks else '')
        code=('import webview; create=webview.create_window; '
              'webview.create_window=lambda *a,**kw:create(*a,**dict(kw,hidden=True)); '
              'from atelier import hostos; hostos.notify=lambda *a:None; '
              'hostos.focus_window=lambda *a:None; '
              'from atelier.web import routes; routes._get_latest_usmap_from_github=lambda:None; '+probe+
              'import window; raise SystemExit(window.main())')
        command=[sys.executable,'-u','-B','-c',code]
    else:
        command=[str(exe)]
    process=subprocess.Popen(command,cwd=root if args.source else exe.parent,env=env,startupinfo=startup)
    try:
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Viewer exited during launch')
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',args.debug_port))==0:break
            time.sleep(.2)
        else:raise TimeoutError('WebView2 debugging endpoint did not start')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{args.debug_port}')
            context=browser.contexts[0];page=context.pages[0]
            page.on('pageerror',lambda error:result['page_errors'].append(str(error)))
            def asset_response(response):
                from urllib.parse import urlsplit
                path=urlsplit(response.url).path
                if path=='/api/idle_animation':
                    try:
                        payload=response.json()
                        if payload.get('ok'):return
                        message=payload.get('error','Native idle decoding failed')
                    except Exception:message='Idle response body unavailable'
                    result['asset_errors'].append(dict(url=response.url,status=response.status,error=message))
                elif response.status>=400 and path in ('/api/model_gltf','/api/skin_materials','/api/texture_png','/api/dye_texture'):
                    try:message=response.text()[:1200]
                    except Exception:message='Response body unavailable'
                    result['asset_errors'].append(dict(url=response.url,status=response.status,error=message))
            page.on('response',asset_response)
            def wait_for_idle():
                deadline=time.monotonic()+240
                while page.locator('#viewport-play').get_attribute('aria-pressed')!='true':
                    assert not result['asset_errors'],result['asset_errors']
                    if time.monotonic()>=deadline:raise TimeoutError('Real standing idle did not start')
                    page.wait_for_timeout(150)
            page.on('console',lambda message:result['page_errors'].append(message.text)
                if message.type=='error' and 'Shader Error' in message.text else None)
            if args.viewport_script:
                context.route('**/static/viewport.js',lambda route:route.fulfill(
                    body=args.viewport_script.read_text(encoding='utf-8'),content_type='text/javascript'))
            def fixture(value):
                return lambda route:route.fulfill(json=value)
            for endpoint,payload in {'update_check':{'available':False},'usmap_update_check':{'ok':True},
                'catalogue/status':{'updating':False,'portraits':0},'catalogue/library':{'heroes':[]}}.items():
                context.route(f'**/api/{endpoint}',fixture(payload))
            context.route('https://**',lambda route:route.fulfill(json={}))
            page.reload();page.wait_for_function('window.AtelierViewport && window.atelierProject?.()',timeout=120000)
            page.wait_for_function('!document.querySelector(".overlay.active") || document.querySelector("#changelog-overlay.active")',timeout=120000)
            if page.locator('#changelog-done').is_visible():
                page.locator('#changelog-done').click()
            page.wait_for_function('!document.querySelector(".overlay.active")',timeout=120000)
            print(f'Ready: configured {result["mode"]} application; loading the real game skin',flush=True)
            load_started=time.monotonic()
            requests={}
            result['requests']=[]
            def started(request):
                from urllib.parse import urlsplit
                route=urlsplit(request.url)
                if route.path in ('/api/model_gltf','/api/skin_materials','/api/texture_png','/api/dye_texture'):
                    record={'route':route.path,'query':route.query,'started_seconds':round(time.monotonic()-load_started,3)}
                    requests[request]=record;result['requests'].append(record)
            def finished(request):
                if request in requests:
                    requests[request]['finished_seconds']=round(time.monotonic()-load_started,3)
            page.on('request',started);page.on('requestfinished',finished)
            page.on('requestfailed',lambda request:finished(request))
            if args.mesh_rel:page.evaluate('args=>{void AtelierViewport.openMesh(args.mesh,args.name)}',{'mesh':args.mesh_rel,'name':args.name})
            else:page.evaluate('args=>{void AtelierViewport.open(args.skin,args.name)}',{'skin':args.skin,'name':args.name})
            page.wait_for_function('document.getElementById("viewport-loading").style.display==="none"',timeout=240000)
            result['first_model_seconds']=round(time.monotonic()-load_started,2)
            page.wait_for_function('document.querySelectorAll(".vp-mat").length>0 && !document.getElementById("viewport-poster").disabled',timeout=240000)
            result['materials']=int(page.locator('#viewport-mat-count').inner_text() or '0')
            result['material_groups']=page.locator('.vp-mat').count()
            result['objects']=page.locator('.vp-obj').count()
            result['load_seconds']=round(time.monotonic()-load_started,2)
            if args.import_server_checks:
                result['import_server_first']=page.evaluate('()=>fetch("/api/_native_import_stats").then(r=>r.json())')
                assert result['import_server_first']['initializations']==1
                assert result['import_server_first']['requests']>3
            result['checks'].append('Native mesh/material/texture routes load a real game skin and enable capture')
            print('Ready: real geometry, materials and texture uploads',flush=True)
            def checked_bodies():
                return page.locator('.vp-obj').evaluate_all('rows=>rows.filter(row=>!row.querySelector("label span").textContent.startsWith("Weapon · ") && row.querySelector("input").checked).length')
            if args.deferred_body_rel:
                from urllib.parse import parse_qs
                result['initial_parts']=page.locator('.vp-obj').evaluate_all('rows=>rows.map(row=>({name:row.querySelector("label span").textContent,visible:row.querySelector("input").checked}))')
                initial_meshes=[parse_qs(record['query']).get('game_rel',[''])[0]
                                for record in result['requests'] if record['route']=='/api/model_gltf']
                result['initial_mesh_requests']=initial_meshes
                assert checked_bodies()==1,'A second body was automatically displayed'
                assert args.deferred_body_rel not in initial_meshes,'An alternate body was auto-loaded as equipment'
                if args.expected_weapon_rel:
                    assert args.expected_weapon_rel in initial_meshes,'The alternate body prevented the held weapon from loading'
                    weapon=args.expected_weapon_rel.rsplit('/',1)[-1]
                    assert any(part['visible'] and part['name']=='Weapon · '+weapon for part in result['initial_parts'])
                result['checks'].append('One body opens without decoding the alternate human form, and the real held weapon remains equipped')
            wait_for_idle()
            if args.design_checks:
                page.set_viewport_size({'width':1582,'height':995})
                if page.locator('#viewport-expand').get_attribute('aria-pressed')!='true':page.locator('#viewport-expand').click()
                assert checked_bodies()==1
                assert page.locator('#viewport-material-editor').is_hidden()
                assert not page.locator('#viewport-box .vp-menu[open]').count()
                assert result['materials']>=8,'The transformed rig lost its material mappings'
            for theme in ('dark','light'):
                page.locator('#settings-theme').select_option(theme,force=True)
                page.wait_for_timeout(250)
                page.screenshot(path=str(report/f'native-viewer-{theme}.png'))
            if args.design_checks:
                body=page.locator('.vp-material-select').filter(has_text='Body')
                (body.first if body.count() else page.locator('.vp-material-select').first).click()
                assert page.locator('#viewport-material-editor').is_visible()
                assert not page.locator('.vp-advanced').evaluate('el=>el.open')
                page.mouse.move(1,1);page.wait_for_timeout(500)
                page.screenshot(path=str(report/'studio-light-editing.png'))
                picker=page.locator('#viewport-material-editor input[type=color]').first
                if picker.count():
                    picker.fill('#70459B');page.wait_for_timeout(200)
                    assert page.locator('#viewport-material-editor .vp-hex').first.input_value()=='#70459B'
                    assert not page.locator('#viewport-mat-save').is_disabled()
                    page.screenshot(path=str(report/'studio-light-draft.png'))
                    page.locator('.vp-revert-material').click()
                page.locator('.vp-advanced > summary').click()
                assert page.locator('.vp-material-edit').is_visible()
                page.screenshot(path=str(report/'studio-light-advanced.png'))
                page.locator('.vp-advanced > summary').click()
                page.locator('#viewport-model-menu > summary').click()
                page.screenshot(path=str(report/'studio-model-menu.png'))
                if page.locator('.vp-obj').count()>1:
                    lazy_started=time.monotonic()
                    page.locator('#viewport-model-choice').select_option('1')
                    page.wait_for_function('document.getElementById("viewport-model-choice").value==="1" && !document.getElementById("viewport-model-choice").disabled',timeout=240000)
                    result['second_model_seconds']=round(time.monotonic()-lazy_started,2)
                    assert checked_bodies()==1
                    assert page.locator('#viewport-material-editor').is_hidden()
                    page.locator('#viewport-model-menu > summary').click()
                    page.locator('#viewport-model-choice').select_option('0')
                    page.wait_for_function('document.getElementById("viewport-model-choice").value==="0" && !document.getElementById("viewport-model-choice").disabled',timeout=240000)
                else:page.keyboard.press('Escape')
                page.locator('#viewport-settings-menu > summary').click()
                page.screenshot(path=str(report/'studio-view-settings.png'))
                page.keyboard.press('Escape')
                assert page.locator('#viewport-overlay').is_visible()
                result['checks'].append('Native Model Studio shows one mesh, reveals only selected material controls, opens advanced and settings on demand, and switches meshes without stale selection')
                page.locator('#viewport-original').click()
                page.wait_for_function('document.getElementById("viewport-original").getAttribute("aria-pressed")==="true"',timeout=240000)
                page.locator('#viewport-wipe').click()
                page.wait_for_function('document.getElementById("viewport-wipe").getAttribute("aria-pressed")==="true"',timeout=240000)
                page.screenshot(path=str(report/'studio-real-comparison.png'))
                page.locator('#viewport-edited').click()
                result['checks'].append('Original and side-by-side comparison load real game materials for both forms, including unchanged unmatched slots')
            if args.deferred_body_rel:
                choices=page.locator('#viewport-model-choice option').evaluate_all('options=>options.map(option=>({value:option.value,label:option.label}))')
                name=args.deferred_body_rel.rsplit('/',1)[-1]
                alternate=next(option['value'] for option in choices if name in option['label'])
                original=page.locator('#viewport-model-choice').input_value()
                def choose_form(value):
                    if not page.locator('#viewport-model-menu').evaluate('el=>el.open'):
                        page.locator('#viewport-model-menu > summary').click()
                    page.locator('#viewport-model-choice').select_option(value)
                    page.wait_for_function('value=>document.getElementById("viewport-model-choice").value===value && !document.getElementById("viewport-model-choice").disabled && !document.getElementById("viewport-poster").disabled',arg=value,timeout=240000)
                    assert checked_bodies()==1,'Switching a form left overlapping bodies visible'
                choose_form(alternate)
                result['alternate_body_parts']=page.locator('.vp-obj').evaluate_all('rows=>rows.map(row=>({name:row.querySelector("label span").textContent,visible:row.querySelector("input").checked}))')
                assert any(part['name']==name and part['visible'] for part in result['alternate_body_parts'])
                page.screenshot(path=str(report/'alternate-body-selected.png'))
                choose_form(original)
                page.screenshot(path=str(report/'single-body-restored.png'))
                result['checks'].append('The human transformation remains selectable as a body form; switching and restoring show exactly one body')
            stage=page.locator('#viewport-canvas').bounding_box()
            page.mouse.move(stage['x']+stage['width']/2,stage['y']+stage['height']/2)
            page.wait_for_timeout(250)
            page.screenshot(path=str(report/'native-viewer-hover.png'))
            page.wait_for_function('document.getElementById("viewport-animation").options.length>1',timeout=60000)
            options=page.locator('#viewport-animation option').evaluate_all('(options)=>options.filter(o=>o.value).map(o=>({value:o.value,label:o.label}))')
            result['idles']=options
            assert options,'No real standing idle was discovered'
            wait_for_idle()
            page.wait_for_timeout(500);page.screenshot(path=str(report/'native-viewer-idle.png'))
            page.locator('#viewport-play').click()
            assert page.locator('#viewport-play').get_attribute('aria-pressed')=='false'
            page.locator('#viewport-animation').select_option('')
            result['checks'].append('Native standing-idle decoder discovers, decodes and plays a real game animation; Pause and Rest pose work')
            page.locator('#viewport-settings-menu > summary').click()
            page.locator('#viewport-bloom').click();page.wait_for_timeout(150)
            page.locator('#viewport-bloom').click()
            if args.import_server_checks:
                stats=page.evaluate('()=>fetch("/api/_native_import_stats").then(r=>r.json())')
                result['import_server_final']=stats
                assert stats['pid']==result['import_server_first']['pid'],'Reader restarted during successful imports'
                assert stats['initializations']==1
                result['checks'].append('One persistent native game reader serves geometry, material and image imports')
            page.evaluate('AtelierViewport.close()')
            assert not page.locator('#viewport-overlay.active').count()
            assert not result['page_errors'],result['page_errors']
            assert not result['asset_errors'],result['asset_errors']
            result['checks'].append('Real skinned geometry renders both themes, accepts bloom and closes without page or shader errors')
            browser.close()
    except Exception as error:
        result['error']=str(error);result['process_exit_code']=process.poll();raise
    finally:
        process.terminate()
        try:process.wait(timeout=20)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if args.import_server_checks and result.get('import_server_final'):
            import ctypes
            from ctypes import wintypes
            ctypes.windll.kernel32.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            ctypes.windll.kernel32.OpenProcess.restype=wintypes.HANDLE
            ctypes.windll.kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
            pid=result['import_server_final']['pid']
            exited=False
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
                if not handle:
                    exited=True;break
                ctypes.windll.kernel32.CloseHandle(handle);time.sleep(.1)
            result['import_process_exited']=exited
            if not exited:
                result['error']='Persistent import process did not exit with its parent'
        (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if args.import_server_checks:assert result.get('import_process_exited'),'Persistent child was left running'
    for check in result['checks']:print('PASS '+check)


if __name__=='__main__':main()
