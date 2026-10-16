"""Confirmed empty-project illustration and finite SVG lifecycle; API results are fixtures."""
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def run_empty_assets_motion_checks(page, context, url, report, checks):
    empty_page = context.new_page()
    errors = []
    empty_page.on('pageerror', lambda error: errors.append(str(error)))
    fixture = {'data': [], 'fail': False}
    empty_page.route('**/api/imported', lambda route: route.fulfill(
        status=500 if fixture['fail'] else 200,
        json={'ok': False, 'error': 'Fixture imported read failure'} if fixture['fail'] else fixture['data']))
    try:
        empty_page.goto(url)
        empty_page.wait_for_function('window.AtelierEmptyAssetsUI && window.AtelierMotion?.emptyAssets && window.atelierProject?.()')
        empty_page.wait_for_selector('#grid-area .card')
        empty_page.emulate_media(reduced_motion='no-preference')
        empty_page.evaluate("""() => {
          window.emptyMounts=[]; window.emptyDestroyed=[];
          window.originalEmptyMount=AtelierMotion.emptyAssets.mount;
          AtelierMotion.emptyAssets.mount=(host, options)=>{
            emptyMounts.push(options.state);
            const handle=originalEmptyMount(host,options), destroy=handle.destroy;
            handle.destroy=()=>{emptyDestroyed.push(host.isConnected); destroy();};
            return handle;
          };
          _applyActiveProject('Empty motion Alpha'); sidebarData={}; renderSidebar();
        }""")
        assert empty_page.locator('#sidebar-list [data-atelier-motion="empty-assets"]').count() == 0
        empty_page.evaluate('loadSidebar()')
        assert empty_page.evaluate('emptyMounts.at(-1)') == 'entering'
        empty_page.wait_for_function("document.querySelector('#sidebar-list [data-atelier-motion=empty-assets]')?.dataset.amState==='settled'")
        empty_page.evaluate('renderSidebar(); renderSidebar()')
        assert empty_page.evaluate('emptyMounts.slice(-2)') == ['settled', 'settled']
        assert empty_page.evaluate('emptyDestroyed.every(Boolean)')
        assert empty_page.evaluate("!document.querySelector('#sidebar-list').getAnimations({subtree:true}).length")
        checks.append('Empty tray enters once after a confirmed empty response, then stays static on repeat renders; owned effects are disposed before DOM replacement')

        fixture['data'] = [{'token': 'empty-fixture', 'name': 'MI_Fixture', 'game_rel': 'Fixture/MI_Fixture',
                            'file_type': 'material', 'selected': True}]
        empty_page.evaluate('loadSidebar()')
        assert empty_page.locator('#sidebar-list .sb-item').count() == 1
        assert empty_page.locator('#sidebar-list [data-atelier-motion="empty-assets"]').count() == 0
        empty_page.locator('#search-input').fill('unmatched-asset')
        assert 'No edited assets match the search.' in empty_page.locator('#sidebar-list').inner_text()
        assert empty_page.locator('#sidebar-list .am-empty-assets-svg').count() == 0
        empty_page.locator('#search-input').fill('')
        fixture['data'] = []
        empty_page.evaluate('loadSidebar()')
        assert empty_page.evaluate('emptyMounts.at(-1)') == 'entering'
        empty_page.evaluate("_applyActiveProject('Empty motion Beta'); sidebarData={}; renderSidebar()")
        assert empty_page.locator('#sidebar-list .am-empty-assets-svg').count() == 0
        empty_page.evaluate('loadSidebar()')
        assert empty_page.evaluate('emptyMounts.at(-1)') == 'entering'
        empty_page.evaluate("_applyActiveProject('Empty motion Alpha'); sidebarData={}; renderSidebar()")
        assert empty_page.locator('#sidebar-list .am-empty-assets-svg').count() == 0
        empty_page.evaluate('loadSidebar()')
        assert empty_page.evaluate('emptyMounts.at(-1)') == 'settled'
        fixture['fail'] = True
        empty_page.evaluate('async()=>{try{await loadSidebar();}catch{} renderSidebar();}')
        assert empty_page.locator('#sidebar-list .am-empty-assets-svg').count() == 0
        fixture['fail'] = False
        empty_page.evaluate('loadSidebar()')
        assert empty_page.evaluate('emptyMounts.at(-1)') == 'settled'
        checks.append('Only genuine empty projects get the illustration: filtered results, pending switches and errors do not; confirmed nonempty-to-empty transitions replay once and returning to a seen project does not')

        before_themes = empty_page.evaluate('emptyMounts.length')
        empty_page.set_viewport_size({'width': 1400, 'height': 900})
        for theme in ('dark', 'light'):
            empty_page.locator('#settings-theme').select_option(theme, force=True)
            svg = empty_page.locator('#sidebar-list .am-empty-assets-svg')
            box = svg.bounding_box()
            assert box['width'] == 112 and box['height'] == 112
            assert svg.get_attribute('aria-hidden') == 'true'
            assert svg.get_attribute('focusable') == 'false'
            bounds = svg.evaluate('el=>{const b=el.getBBox();return {x:b.x,y:b.y,width:b.width,height:b.height}}')
            assert 90 <= bounds['width'] <= 104
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 112
            assert empty_page.locator('.sidebar-empty > .am-empty-assets-fallback-hidden').is_hidden()
            assert empty_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert empty_page.locator('#install-btn').is_visible()
            empty_page.screenshot(path=str(report / f'empty-assets-{theme}.png'), animations='disabled')
        assert empty_page.evaluate('emptyMounts.length') == before_themes
        paths = [element.attrib['d'] for element in ET.parse(ROOT / 'gui/motion/empty-assets.svg').iter('{http://www.w3.org/2000/svg}path')]
        assert empty_page.locator('#sidebar-list .am-empty-assets-svg path').evaluate_all('els=>els.map(el=>el.getAttribute("d"))') == paths
        checks.append('Empty tray retains a 112px host and 96px painted width in both themes, matches its editable SVG, stays decorative and does not replay on theme changes')

        empty_page.evaluate("""() => {
          window.emptyHost=document.createElement('div');
          emptyHost.style.cssText='position:fixed;left:20px;top:160px;z-index:9999'; document.body.append(emptyHost);
          window.emptyHandle=originalEmptyMount(emptyHost,{state:'entering'});
          window.emptyEffects=emptyHost.getAnimations({subtree:true});
          // Krackle entrance: the tray stamps, guides fade and each loose bubble drops in, all finite.
          if(emptyEffects.length<5 || emptyEffects.some(effect=>effect.effect.getTiming().iterations===Infinity))
            throw Error('Expected finite entrance effects for the tray, guides and bubbles');
          emptyHandle.setState('entering');
          if(!emptyEffects.every(effect=>emptyHost.getAnimations({subtree:true}).includes(effect))) throw Error('Repeated entrance restarted');
          emptyHandle.setState('settled');
          if(emptyHost.getAnimations({subtree:true}).length) throw Error('Settling left effects');
          emptyHandle.replay();
          window.replacedEmptyHandle=emptyHandle;
          emptyHandle=originalEmptyMount(emptyHost,{state:'settled'});
          replacedEmptyHandle.destroy(); replacedEmptyHandle.setState('entering');
          if(emptyHost.querySelectorAll('svg').length!==1 || emptyHost.dataset.amState!=='settled') throw Error('Replacement affected by old instance');
          for(const state of ['constructor','toString','unknown']) {
            let rejected=false; try{emptyHandle.setState(state);}catch{rejected=true;}
            if(!rejected) throw Error('Invalid state accepted');
          }
          const unrelated=document.createElement('div'); unrelated.innerHTML='<span>Keep me</span>'; document.body.append(unrelated);
          let rejected=false; try{originalEmptyMount(unrelated);}catch{rejected=true;}
          if(!rejected || unrelated.textContent!=='Keep me') throw Error('Unrelated content changed');
          unrelated.remove();
          emptyHandle.replay();
        }""")
        empty_page.emulate_media(reduced_motion='reduce')
        empty_page.wait_for_function("emptyHost.dataset.amState==='settled'")
        assert empty_page.evaluate('emptyHost.getAnimations({subtree:true}).length') == 0
        empty_page.evaluate("emptyHandle.setReducedMotion('system'); emptyHandle.replay()")
        assert empty_page.evaluate('emptyHost.dataset.amState') == 'settled'
        empty_page.emulate_media(reduced_motion='no-preference')
        empty_page.evaluate("""() => {
          emptyHandle.setReducedMotion('reduce'); emptyHandle.replay();
          if(emptyHost.dataset.amState!=='settled') throw Error('Forced reduce ignored');
          emptyHandle.setReducedMotion('system'); emptyHost.style.left='-500px'; emptyHandle.replay();
          if(emptyHost.dataset.amState!=='settled') throw Error('Offscreen entrance played');
          emptyHost.style.left='20px';
          Object.defineProperty(document,'hidden',{configurable:true,value:true}); emptyHandle.replay();
          if(emptyHost.dataset.amState!=='settled') throw Error('Hidden entrance played');
          delete document.hidden;
          emptyHandle.replay(); emptyHost.style.left='-500px';
        }""")
        empty_page.wait_for_function("emptyHost.dataset.amState==='settled'")
        empty_page.evaluate("""() => {
          emptyHost.style.left='20px'; emptyHandle.destroy(); emptyHandle.destroy(); emptyHandle.replay();
          if(emptyHost.childNodes.length || emptyHost.hasAttribute('data-atelier-motion')) throw Error('Destroy left owned DOM');
          const animate=Element.prototype.animate;
          Element.prototype.animate=undefined;
          emptyHandle=originalEmptyMount(emptyHost,{state:'entering'});
          if(emptyHost.dataset.amState!=='settled' || !emptyHost.querySelector('svg')) throw Error('Missing WAAPI did not settle');
          emptyHandle.destroy();
          let count=0;
          Element.prototype.animate=function(...args){if(++count===3) throw Error('Fixture partial WAAPI failure');return animate.apply(this,args);};
          emptyHandle=originalEmptyMount(emptyHost,{state:'entering'});
          Element.prototype.animate=animate;
          if(emptyHost.dataset.amState!=='settled' || emptyHost.getAnimations({subtree:true}).length) throw Error('Partial animation failure leaked');
          emptyHandle.destroy(); emptyHost.remove();
          AtelierMotion.emptyAssets.mount=()=>{throw Error('Fixture mount failure');}; renderSidebar();
          if(document.querySelector('#sidebar-list .am-empty-assets-host')) throw Error('Failed mount left empty host');
          const fallback=document.querySelector('.sidebar-empty > svg');
          if(!fallback || getComputedStyle(fallback).display==='none') throw Error('Fallback not restored');
          AtelierMotion.emptyAssets.mount=originalEmptyMount; renderSidebar();
        }""")
        assert not errors, errors
        checks.append('Empty SVG handles interruption, duplicate mount, reduced motion, hidden/offscreen state, unavailable/partial WAAPI and mount failure without orphan effects or lost fallback')
    finally:
        empty_page.close()
