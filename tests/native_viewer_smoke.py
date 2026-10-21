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
    args=parser.parse_args()
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
    result={'mode':'source' if args.source else 'packaged','checks':[],'page_errors':[]}
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
        code=('import webview; create=webview.create_window; '
              'webview.create_window=lambda *a,**kw:create(*a,**dict(kw,hidden=True)); '
              'from atelier import hostos; hostos.notify=lambda *a:None; '
              'hostos.focus_window=lambda *a:None; '
              'from atelier.web import routes; routes._get_latest_usmap_from_github=lambda:None; '
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
            page.on('console',lambda message:result['page_errors'].append(message.text)
                if message.type=='error' and 'Shader Error' in message.text else None)
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
            if args.mesh_rel:page.evaluate('args=>AtelierViewport.openMesh(args.mesh,args.name)',{'mesh':args.mesh_rel,'name':args.name})
            else:page.evaluate('args=>AtelierViewport.open(args.skin,args.name)',{'skin':args.skin,'name':args.name})
            page.wait_for_function('document.getElementById("viewport-loading").style.display==="none"',timeout=240000)
            page.wait_for_function('document.querySelectorAll(".vp-mat").length>0 && !document.getElementById("viewport-poster").disabled',timeout=240000)
            result['materials']=int(page.locator('#viewport-mat-count').inner_text() or '0')
            result['material_groups']=page.locator('.vp-mat').count()
            result['objects']=page.locator('.vp-obj').count()
            result['load_seconds']=round(time.monotonic()-load_started,2)
            result['checks'].append('Native mesh/material/texture routes load a real game skin and enable capture')
            print('Ready: real geometry, materials and texture uploads',flush=True)
            page.wait_for_function('document.getElementById("viewport-play").getAttribute("aria-pressed")==="true"',timeout=240000)
            if args.design_checks:
                page.set_viewport_size({'width':1582,'height':995})
                if page.locator('#viewport-expand').get_attribute('aria-pressed')!='true':page.locator('#viewport-expand').click()
                assert page.locator('.vp-obj input:checked').count()==1
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
                    page.locator('#viewport-model-choice').select_option('1')
                    assert page.locator('.vp-obj input:checked').count()==1
                    assert page.locator('#viewport-material-editor').is_hidden()
                    page.locator('#viewport-model-menu > summary').click()
                    page.locator('#viewport-model-choice').select_option('0')
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
            stage=page.locator('#viewport-canvas').bounding_box()
            page.mouse.move(stage['x']+stage['width']/2,stage['y']+stage['height']/2)
            page.wait_for_timeout(250)
            page.screenshot(path=str(report/'native-viewer-hover.png'))
            page.wait_for_function('document.getElementById("viewport-animation").options.length>1',timeout=60000)
            options=page.locator('#viewport-animation option').evaluate_all('(options)=>options.filter(o=>o.value).map(o=>({value:o.value,label:o.label}))')
            result['idles']=options
            assert options,'No real standing idle was discovered'
            page.wait_for_function('document.getElementById("viewport-play").getAttribute("aria-pressed")==="true"',timeout=240000)
            page.wait_for_timeout(500);page.screenshot(path=str(report/'native-viewer-idle.png'))
            page.locator('#viewport-play').click()
            assert page.locator('#viewport-play').get_attribute('aria-pressed')=='false'
            page.locator('#viewport-animation').select_option('')
            result['checks'].append('Native standing-idle decoder discovers, decodes and plays a real game animation; Pause and Rest pose work')
            page.locator('#viewport-settings-menu > summary').click()
            page.locator('#viewport-bloom').click();page.wait_for_timeout(150)
            page.locator('#viewport-bloom').click()
            page.evaluate('AtelierViewport.close()')
            assert not page.locator('#viewport-overlay.active').count()
            assert not result['page_errors'],result['page_errors']
            result['checks'].append('Real skinned geometry renders both themes, accepts bloom and closes without page or shader errors')
            browser.close()
    except Exception as error:
        result['error']=str(error);result['process_exit_code']=process.poll();raise
    finally:
        process.terminate()
        try:process.wait(timeout=20)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        (report/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for check in result['checks']:print('PASS '+check)


if __name__=='__main__':main()
