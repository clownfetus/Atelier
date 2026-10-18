"""Everywhere search, roster filters, real edit recency and costume entry points."""
from io import BytesIO
import time
from urllib.parse import parse_qs,urlparse


def run_find_checks(page,context,url,report,checks):
    from PIL import Image
    output=BytesIO();Image.new('RGB',(100,120),'#7954bf').save(output,'PNG');art=output.getvalue()
    tab=context.new_page();errors=[];held=[];tab.on('pageerror',lambda error:errors.append(str(error)))
    heroes=[{'name':'Fixture Magik','path':'Characters/1029','avatar':'/find-art','skins':[{'name':'Amethyst','path':'Characters/1029/1029001','thumbnail':'/find-art'}]},
            {'name':'Fixture Venom','path':'Characters/1035','avatar':'/find-art','skins':[{'name':'No mesh','path':'Characters/1035/1035001','thumbnail':'/find-art'}]}]
    imported=[{'token':'find-curve','game_rel':'Characters/1029/1029001/Curve_Test','name':'Curve_Test','file_type':'curve','selected':True,
               'char_id':'1029','skin_id':'1029001','char_name':'Fixture Magik','skin_name':'Amethyst','modified':time.time()-7200}]
    folders=[{'type':'folder','name':name,'label':name,'rel_path':name} for name in ['Textures','Materials','VFX','Meshes','UI','Audio','Maps','Characters','Misc','Other']]
    asset={'type':'asset','name':'T_Cafe','file_type':'texture','game_rel':'Characters/1029/1029001/Textures/T_Cafe','rel_path':'Characters/1029/1029001/Textures/T_Cafe'}
    tab.route('**/find-art',lambda route:route.fulfill(body=art,content_type='image/png'))
    tab.route('**/api/catalogue/library',lambda route:route.fulfill(json={'heroes':heroes}))
    tab.route('**/api/imported',lambda route:route.fulfill(json=imported))
    tab.route('**/api/browse?*',lambda route:route.fulfill(json=[asset] if parse_qs(urlparse(route.request.url).query).get('path',[''])[0].endswith('/Textures') else folders))
    def search(route):
        q=parse_qs(urlparse(route.request.url).query).get('q',[''])[0]
        if q=='slow':held.append(route);return
        rows=[] if q=='missing' else [{'name':'T_Cafe','game_rel':asset['game_rel'],'type':'texture','parent':'Characters/1029/1029001/Textures'}]
        route.fulfill(json={'heroes':[],'skins':[],'folders':[],'assets':rows,'totals':{'heroes':0,'skins':0,'folders':0,'assets':len(rows)}})
    tab.route('**/api/search?*',search)
    tab.route('**/api/skin_meshes?*',lambda route:route.fulfill(json=[] if '1035001' in route.request.url else [{'name':'Body','game_rel':'Characters/1029/1029001/Meshes/SK_Body'}]))
    try:
        tab.goto(url);tab.wait_for_function("document.querySelectorAll('.roster-portrait').length===2 && window.AtelierViewport")
        tab.evaluate("() => {window.studioOpens=[];AtelierViewport.open=async (...args)=>studioOpens.push(args);window.continued=[];openCurveEditor=async item=>continued.push(item.game_rel);}")
        assert tab.locator('#search-scope').inner_text()=='Everywhere'
        assert tab.locator('#continue-ribbon').is_visible();assert '2 h ago' in tab.locator('#continue-ribbon').inner_text()
        tab.locator('#continue-ribbon button').click();assert tab.evaluate('continued')==[imported[0]['game_rel']]
        tab.evaluate("AtelierRoster.rememberEditor('Characters/1029/1029001/Curve_Test','studio','Smoke A');sidebarData['find-curve'].skin_id='';renderSidebar()")
        tab.locator('#continue-ribbon button').click();assert len(tab.evaluate('continued'))==2
        tab.evaluate("sidebarData['find-curve'].skin_id='1029001';renderSidebar()")
        tab.get_by_role('button',name='Edited',exact=True).click()
        assert tab.locator('.roster-portrait').count()==1
        assert '1 edit' in tab.locator('.roster-counts').inner_text()
        tab.get_by_role('button',name='All',exact=True).click()
        tab.locator('.roster-portrait').nth(1).click();tab.get_by_role('button',name='Recently opened',exact=True).click()
        assert tab.locator('.roster-portrait').count()==1;assert 'Venom' in tab.locator('.roster-portrait').inner_text()
        tab.reload();tab.wait_for_selector('.roster-portrait')
        tab.get_by_role('button',name='Recently opened',exact=True).click();assert tab.locator('.roster-portrait').count()==1
        tab.evaluate("_applyActiveProject('Smoke B');sidebarData={};renderSidebar()")
        tab.get_by_role('button',name='Recently opened',exact=True).click();assert tab.locator('.roster-portrait').count()==0
        assert tab.locator('#continue-ribbon').is_hidden()
        tab.evaluate("_applyActiveProject('Smoke A');loadSidebar()")
        tab.wait_for_function("document.querySelectorAll('.roster-portrait').length===2")
        tab.get_by_role('button',name='All',exact=True).click();tab.locator('.roster-portrait').first.focus();tab.keyboard.press('ArrowRight')
        assert tab.locator('.roster-portrait').nth(1).evaluate('el=>el===document.activeElement')
        assert tab.locator('#grid-area .card').count()==8
        tab.locator('.home-category-more').click();assert tab.locator('#grid-area .card').count()==10
        checks.append('Home leads with hero costume/edit counts, per-project recent/edited filters, keyboard movement, category chips and a Continue ribbon from actual edit time')
        tab.evaluate("() => {window.studioOpens=[];AtelierViewport.open=async (...args)=>studioOpens.push(args);}")
        tab.locator('.roster-portrait').first.click();tab.locator('.roster-skin').click()
        tab.wait_for_function('studioOpens.length===1');assert tab.evaluate('studioOpens[0][0]')=='1029001'
        tab.locator('.roster-portrait').nth(1).click();tab.locator('.roster-skin').click()
        tab.wait_for_function("nav.path==='Characters/1035/1035001'")
        tab.wait_for_function("document.getElementById('toast-area').textContent.includes('No meshes')")
        checks.append('A costume opens Model Studio directly and the no-mesh case opens its folder with an explanation')
        field=tab.locator('#search-input');field.fill('cafe')
        tab.wait_for_selector('#search-results .search-result')
        before=tab.locator('#grid-area .card').count()
        assert before==10 # Everywhere does not filter the current folder.
        field.press('ArrowDown');field.press('Enter')
        tab.wait_for_function("nav.path==='Characters/1029/1029001/Textures'")
        tab.wait_for_function("document.activeElement.dataset.libraryPath==='Characters/1029/1029001/Textures/T_Cafe'")
        field.fill('missing');tab.wait_for_function("document.querySelector('#search-results')?.textContent.includes('No results')")
        field.press('Escape');assert tab.locator('#search-results').is_hidden();assert field.evaluate('el=>el===document.activeElement')
        field.fill('slow');tab.wait_for_timeout(200);assert held
        field.fill('cafe');tab.wait_for_selector('#search-results .search-result')
        try:held.pop().fulfill(json={'heroes':[],'skins':[],'folders':[],'assets':[],'totals':{}})
        except Exception:pass # An aborted route can no longer be fulfilled.
        assert tab.locator('#search-results .search-result').count()==1
        field.press('Escape');tab.locator('#search-scope').click();field.fill('missing')
        assert tab.locator('#grid-area .card').count()==0;assert tab.locator('#search-results').is_hidden()
        field.fill('cafe');assert tab.locator('#grid-area .card').count()==1
        checks.append('Everywhere supports debounced keyboard navigation and asset focus, rejects stale responses, and This folder keeps local filtering')
        tab.evaluate("pushNav({path:''})");tab.wait_for_selector('.roster-portrait')
        tab.locator('#search-scope').click()
        tab.evaluate('_homeCategoriesExpanded=false;buildGrid(allItems.map(_makeCard))')
        for theme in ('dark','light'):
            tab.locator('#settings-theme').select_option(theme,force=True)
            tab.screenshot(path=str(report/f'find-home-{theme}.png'),animations='disabled')
        imported.clear();tab.evaluate('loadSidebar()');tab.wait_for_function("document.getElementById('continue-ribbon').hidden")
        tab.route('**/api/catalogue/library',lambda route:route.abort())
        tab.reload();tab.wait_for_selector('#grid-area .card')
        tab.wait_for_function("document.getElementById('hero-roster').textContent.includes('Catalogue unavailable')")
        assert tab.locator('#grid-area .card').count()>=1
        assert not errors,errors
        checks.append('Empty projects hide Continue and an offline catalogue keeps the folder library usable')
    finally:tab.close()
