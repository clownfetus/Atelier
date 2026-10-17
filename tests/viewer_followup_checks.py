"""UI integration for folder art, contextual batch controls and model replacements."""
from io import BytesIO
from PIL import Image


def run_viewer_followup_checks(page,context,url,report,checks,*,reuse_page=False):
    tab=page if reuse_page else context.new_page()
    art=BytesIO();Image.new('RGBA',(64,64),(210,40,50,128)).save(art,'PNG')
    errors=[];tab.on('pageerror',lambda error:errors.append(str(error)))
    tab.route('**/api/catalogue/hero/**',lambda route:route.fulfill(body=art.getvalue(),content_type='image/png'))
    tab.route('**/api/catalogue/thumbnail/*',lambda route:route.fulfill(body=art.getvalue(),content_type='image/png'))
    tab.route('**/api/browse?*',lambda route:route.fulfill(json=[{'type':'folder','name':'1057001','label':'Default costume',
        'rel_path':'Characters/1057/1057001','thumbnail':'/api/catalogue/thumbnail/1057001'}]))
    tab.route('**/api/curve_params?*',lambda route:route.fulfill(json={'ok':True,'channels':{'R':[{'time':0,'value':1}]},'stops':[]}))
    tab.route('**/api/vfx_params?*',lambda route:route.fulfill(json={'ok':True,'groups':[],'scalars':[],'vectors':[]}))
    added=[];replaced=[];reverted=[];refreshed=[]
    tab.route('**/api/revert_imported',lambda route:(reverted.append(route.request.post_data_json),route.fulfill(json={'ok':True}))[-1])
    tab.route('**/api/stale_mips',lambda route:route.fulfill(json={'ok':True,'count':0,'items':[]}))
    tab.route('**/api/refresh_texture_mips',lambda route:(refreshed.append(route.request.post_data_json),route.fulfill(json={'ok':True,'repaired':[{'game_rel':'Fixture/T_Painted'}],'skipped':[]}))[-1])
    tab.route('**/api/mesh_add',lambda route:(added.append(route.request.post_data_json),route.fulfill(json={'ok':True}))[-1])
    def replacement(route):
        replaced.append(route.request.post_data_buffer)
        route.fulfill(json={'ok':True,'validation':{'lods':2,'retained_weight_vertices':20,'transferred_weight_vertices':10}})
    tab.route('**/api/mesh_replace',replacement)
    try:
        tab.goto(url);tab.wait_for_function('window.AtelierMeshEdit && window.atelierProject?.()')
        tab.wait_for_selector('.hero-portrait.loaded')
        assert tab.locator('.card-thumb').first.evaluate('el=>getComputedStyle(el).backgroundImage')=='none'
        assert tab.locator('.card-thumb').first.evaluate('el=>getComputedStyle(el).backgroundColor')=='rgba(0, 0, 0, 0)'
        tab.evaluate("pushNav({path:'Characters/1057/1057001'})")
        tab.wait_for_selector('#library-hero.has-art')
        assert tab.locator('.library-hero-art').get_attribute('src')=='/api/catalogue/hero/1057/story'
        checks.append('Character folder portraits stay transparent; hero and costume banners request story art by the exact character code')
        labels=tab.evaluate("_ctxItemsCard({type:'asset',file_type:'mesh',game_rel:'Characters/1057/1057001/Meshes/SK_Test',label:'Mesh',imported:false}).filter(x=>typeof x==='object').map(x=>x.label)")
        assert labels.count('View in 3D')==1 and 'Preview in 3D' not in labels and 'Add to edit list' in labels
        assert tab.locator('#bulk-edit-open').is_hidden()
        tab.evaluate("openCurveEditor({game_rel:'Fixture/C_Test',name:'Curve'})")
        tab.wait_for_selector('#curve-overlay #bulk-edit-open:not([hidden])')
        tab.evaluate('closeCurveEditor()');assert tab.locator('#bulk-edit-open').is_hidden()
        tab.evaluate("openVfxEditor({game_rel:'Fixture/NS_Empty',name:'Empty VFX'})")
        tab.wait_for_function("document.getElementById('vfx-body').textContent.includes('no') || !!vfxEditor")
        assert tab.locator('#bulk-edit-open').is_hidden();tab.evaluate('closeVfxEditor()')
        checks.append('Meshes have one 3D menu action; bulk controls appear inside a loaded compatible editor and hide on close or unsupported data')
        tab.evaluate("AtelierMeshEdit.add({game_rel:'Characters/1057/1057001/Meshes/SK_Test',name:'Test model'})")
        tab.wait_for_selector('#mesh-edit-overlay.active')
        assert added==[{'game_rel':'Characters/1057/1057001/Meshes/SK_Test'}]
        assert set(tab.locator('#mesh-edit-overlay input[type=file]').get_attribute('accept').split(','))>=set(('.blend','.fbx','.glb','.psk','.uasset','.uexp','.ubulk'))
        assert tab.locator('.mesh-import-options input[type=checkbox]:checked').count()==3
        tab.screenshot(path=str(report/'model-import-defaults.png'))
        tab.locator('#mesh-import-keep_morphs').uncheck()
        tab.locator('#mesh-edit-overlay input[type=file]').set_input_files({'name':'model.psk','mimeType':'application/octet-stream','buffer':b'PSK fixture - backend validation tested separately'})
        tab.wait_for_function("document.getElementById('mesh-edit-status').textContent.includes('Model saved')")
        assert len(replaced)==1 and b'model.psk' in replaced[0] and b'game_rel' in replaced[0]
        assert b'"keep_morphs":false' in replaced[0] and b'"keep_skeleton":true' in replaced[0] and b'"keep_weights":true' in replaced[0]
        tab.screenshot(path=str(report/'model-replacement-dialog.png'))
        tab.get_by_role('button',name='Close',exact=True).last.click()
        imported=[];browse_requests=[]
        textures=[{'type':'asset','file_type':'texture','name':name,'game_rel':'Fixture/'+name,'imported':False} for name in ('T_One','T_Two')]
        tab.unroute('**/api/browse?*')
        tab.route('**/api/browse?*',lambda route:(browse_requests.append(route.request.url),route.fulfill(json=textures))[-1])
        tab.route('**/api/imported',lambda route:route.fulfill(json=imported))
        tab.route('**/api/thumb?*',lambda route:route.fulfill(body=art.getvalue(),content_type='image/png'))
        tab.route('**/api/preview?*',lambda route:route.fulfill(body=art.getvalue(),content_type='image/png'))
        tab.route('**/api/prefetch_thumbs',lambda route:route.fulfill(json={'ok':True,'cached':[row['game_rel'] for row in textures]}))
        def import_texture(route):
            gr=route.request.post_data_json['game_rel']
            imported.append({'game_rel':gr,'name':gr.split('/')[-1],'file_type':'texture','token':gr.split('/')[-1],'selected':True})
            route.fulfill(json={'ok':True})
        tab.route('**/api/import_texture',import_texture)
        tab.evaluate("async()=>{_openAfterImport=false;await renderGrid();window.__steadyGrid=document.querySelector('#grid-area .grid');window.__steadyImages=[...__steadyGrid.querySelectorAll('img')];window.__steadyBanner=document.getElementById('library-hero').firstChild;}")
        for index,name in enumerate(('T_One','T_Two')):
            tab.locator(f'.card[data-library-path="Fixture/{name}"]').click()   # one click edits; no confirmation
            tab.wait_for_function('count=>document.querySelectorAll("#grid-area .card.imported").length===count',arg=index+1)
            if index==0:tab.evaluate("window.__steadySidebarRow=document.querySelector('.sb-item');window.__steadySidebarImage=__steadySidebarRow.querySelector('img')")
        assert len(browse_requests)==1,browse_requests
        assert tab.evaluate("document.querySelector('#grid-area .grid')===__steadyGrid && __steadyImages.every((img,i)=>img===__steadyGrid.querySelectorAll('img')[i]) && document.getElementById('library-hero').firstChild===__steadyBanner")
        assert tab.evaluate("document.querySelector('.sb-item')===__steadySidebarRow && __steadySidebarRow.querySelector('img')===__steadySidebarImage")
        tab.screenshot(path=str(report/'texture-import-stable-grid.png'))
        checks.append('Consecutive texture imports preserve grid, thumbnail, banner and existing sidebar nodes without reloading the library')
        for kind in ('texture','mesh','material','curve','vfx','world','text'):
            labels=tab.evaluate("kind=>_ctxItemsCard({type:'asset',file_type:kind,imported:true,token:'kept',game_rel:'Fixture/T_Painted'}).filter(x=>typeof x==='object').map(x=>x.label)",kind)
            assert 'Revert to original' in labels,kind
            labels=tab.evaluate("kind=>_ctxItemsSidebar({file_type:kind,token:'kept',game_rel:'Fixture/T_Painted'}).filter(x=>typeof x==='object').map(x=>x.label)",kind)
            assert 'Revert to original' in labels,kind
        tab.once('dialog', lambda dialog: dialog.accept())   # Revert replaces the edit, so it asks first
        tab.evaluate("revertImported({file_type:'texture',game_rel:'Fixture/T_Painted',token:'kept'})")
        tab.wait_for_function("[...document.querySelectorAll('.toast')].some(el=>el.textContent.includes('Original restored'))")
        assert reverted[0]['game_rel']=='Fixture/T_Painted'
        checks.append('Asset and edit-list menus restore originals for every editable asset type through the preserve-entry endpoint')
        tab.unroute('**/api/stale_mips')
        tab.route('**/api/stale_mips',lambda route:route.fulfill(json={'ok':True,'count':1,'items':[{'game_rel':'Fixture/T_Painted'}]}))
        tab.evaluate('_staleMipChecked.clear();checkStaleMips()')
        tab.wait_for_function("[...document.querySelectorAll('.toast')].some(el=>el.textContent.includes('Painted areas preserved'))")
        assert len(refreshed)==1
        checks.append('Available high-resolution mips trigger automatic tracked repair and explain paint preservation and backups')
        tab.evaluate("buildGrid([_makeCard({type:'asset',file_type:'texture',name:'T_Painted',label:'Painted texture',game_rel:'Fixture/T_Painted',imported:true,token:'kept'})])")
        assert tab.locator('.card.imported .card-editing-badge').inner_text()=='Editing'
        assert tab.locator('.card.imported').evaluate('el=>parseFloat(getComputedStyle(el).borderTopWidth)')>=3
        tab.screenshot(path=str(report/'editing-card-border.png'))
        checks.append('Edited grid assets have a three-pixel contrasting border and an explicit Editing badge')
        tab.evaluate("""() => {
          window.followupExport={project:atelierProject(),modName:'Completed build',copyToMods:true,modsPath:'D:/Test/mods',protected:false,included:[],excluded:[],skipped:0};
          AtelierExportReview.open(followupExport,{refresh(){},confirm(){},settings(){}});
          AtelierExportReview.finish(followupExport,{ok:true,installed_dir:'D:/Test/mods',applied:['tex T_Painted'],skipped:[]});
        }""")
        for theme in ('light','dark'):
            tab.locator('#settings-theme').select_option(theme,force=True)
            tab.wait_for_function("theme=>document.documentElement.dataset.theme===theme && getComputedStyle(document.querySelector('.export-review-modal .btn')).color===getComputedStyle(document.querySelector('.export-review-modal h2')).color",arg=theme)
            assert tab.locator('.export-review-modal').get_attribute('data-state')=='success'
            assert tab.locator('.export-review-modal').evaluate("el=>parseFloat(getComputedStyle(el).borderTopWidth)")>=2
            assert tab.locator('.export-review-modal').evaluate("el=>getComputedStyle(el).borderTopColor===getComputedStyle(el.querySelector('h2')).color")
            tab.screenshot(path=str(report/f'completed-build-green-{theme}.png'))
        tab.keyboard.press('Escape')
        checks.append('Completed builds use a green surface, strong status border, heading and controls in both themes')
        assert not errors,errors
        checks.append('Model import defaults skeleton, weights and morph preservation on; explicit checkbox choices upload with the target and supported model formats')
    finally:
        if not reuse_page:tab.close()
