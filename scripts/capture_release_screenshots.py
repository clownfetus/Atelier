"""Capture the live, configured interface without saving edits or building/installing mods.

Start server.py with isolated ATELIER_DATA_DIR, then pass its loopback URL.
"""
import argparse,json,time,hashlib,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from release_screenshots import source_hashes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--channel',default='msedge')
    args=parser.parse_args()
    if not args.url.startswith('http://127.0.0.1:'):
        parser.error('Use the loopback server started with isolated data')
    args.output.mkdir(parents=True,exist_ok=True)
    errors=[];requests=[];files=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=args.channel,headless=True)
        context=browser.new_context(viewport={'width':1400,'height':900},device_scale_factor=1)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append(r.url) if r.method=='POST' else None)
        page.route('**/api/update_check',lambda r:r.fulfill(json={'available':False}))
        page.goto(args.url)
        page.wait_for_function("document.querySelectorAll('.roster-portrait').length>0",timeout=120000)
        page.wait_for_timeout(15000)
        def theme(value):
            page.locator('#settings-theme').select_option(value,force=True)
            page.wait_for_timeout(1200)
        def shot(name):
            page.mouse.move(1380,55)
            page.screenshot(path=str(args.output/name));files.append(name)
        for value in ['dark','light']:
            theme(value);shot('studio-'+value+'.png')
        theme('dark')
        page.evaluate("pushNav({path:'UI/Textures/HeroGallery/HeroDetail/Skin/BattleCustom'})")
        page.wait_for_function("nav.path.endsWith('/BattleCustom') && _gridStatus==='ready' && document.querySelectorAll('#grid-area .artwork-card').length>0",timeout=120000)
        page.wait_for_timeout(2000);shot('asset-library.png')
        page.evaluate("openMaterialEditor({name:'MI_1015502_Equip_01',game_rel:'Characters/1015/1015502/Materials/MI_1015502_Equip_01'})")
        page.wait_for_function("matEditor && document.querySelector('#mat-body .mat-parameter-group')",timeout=120000)
        page.wait_for_timeout(2000);shot('material-editor.png')
        page.locator('#mat-replacement summary').click()
        page.wait_for_timeout(400);shot('material-replacement.png')
        page.evaluate('closeMaterialEditor(true)')
        page.evaluate("AtelierViewport.open('1029100','Magik')")
        page.wait_for_function("document.getElementById('viewport-loading').style.display==='none' && document.querySelectorAll('.vp-mat').length>0 && !document.getElementById('viewport-poster').disabled",timeout=600000)
        page.wait_for_timeout(2500)
        if page.locator('#viewport-expand').get_attribute('aria-pressed')!='true':
            page.locator('#viewport-expand').click()
        shot('model-studio.png')
        page.locator('#viewport-showcase').click();page.wait_for_timeout(1200);shot('showcase.png')
        page.locator('#viewport-inspect').click()
        page.locator('#viewport-close').click()
        page.locator('#menu-btn').click();page.locator('#ctx-menu button',has_text='Settings').click()
        page.wait_for_function("!document.getElementById('setup-loading').classList.contains('active')")
        page.locator('#setup-overlay .setup-body').evaluate('el=>el.scrollTop=0')
        assert page.locator('#setup-aes').evaluate("el=>el.getBoundingClientRect().top >= el.closest('.setup-body').getBoundingClientRect().bottom"), 'Keep credential fields outside the captured viewport'
        page.wait_for_timeout(600);shot('appearance-settings.png')
        page.locator('#settings-blender-project-textures').scroll_into_view_if_needed()
        assert page.locator('#setup-aes').evaluate("el=>{const a=el.getBoundingClientRect(),b=el.closest('.setup-body').getBoundingClientRect();return a.bottom<=b.top||a.top>=b.bottom;}"), 'Keep credential fields outside the captured viewport'
        page.wait_for_timeout(300);shot('blender-settings.png')
        assert not errors,errors
        forbidden=[u for u in requests if any(x in u for x in ['/api/material_save','/api/material_replace','/api/material_reset','/api/export','/api/install_mod'])]
        assert not forbidden,forbidden
        browser.close()
    result={'version':(ROOT/'version').read_text().strip(),'viewport':[1400,900],'data':'Isolated configured game data; no edits saved and no mods installed','page_errors':errors,'source_files':source_hashes(ROOT),'files':[{'path':name,'sha256':hashlib.sha256((args.output/name).read_bytes()).hexdigest()} for name in files]}
    result['source_hash_format']='SHA-256; text line endings normalized to LF'
    (args.output/'screenshots.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='source_files'},indent=2))

if __name__=='__main__':main()
