"""Portable material manifests, edited textures and physical weapon coordinates.

These checks never invoke Blender or an asset decoder. Real scene generation is
verified separately through the private app, including packed-image graph audits.
"""
import atexit
import base64
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sys
import struct
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='atelier-studio-blender-')
atexit.register(temporary.cleanup)
os.environ['ATELIER_DATA_DIR']=temporary.name
from atelier import config, jobs
from atelier.handlers import mesh, meshmat, meshport, meshstudio, meshreplace, meshedit, material, custom_texture, dye
from atelier.blender.psk_reader import source_scale,unreal_points,read_psk


def bone(name,parent=-1,translation=(0,0,0),rotation=(0,0,0,1)):
    return {'name':name,'parent':parent,'translation':translation,'rotation':rotation,'scale':(1,1,1)}


class BlenderPort(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        context=config.project_context(str(self.root/'project'));context.__enter__()
        self.addCleanup(context.__exit__,None,None,None)
        self.child='Characters/1029/1029001/Materials/MI_Child'
        self.parent='Characters/1029/1029001/Materials/MI_Parent'

    def test_blender_can_pack_cached_textures_without_adding_project_texture_edits(self):
        game_rel = 'Meshes/SK_Body'
        roots = []
        def manifest(_gr, _mesh, work_base=None, root=None):
            roots.append(root)
            target = Path(root)/'Textures/T_Body.png'; target.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (8, 8), 'red').save(target)
            return {'textures': {'Textures/T_Body': {'path': str(target)}}, 'slots': {}, 'warnings': []}
        def blender(_script, args, _tag):
            Path(args[1]).write_bytes(b'packed model')
            return 'BLEND_OK\nMATERIAL_REPORT {}'
        model = types.SimpleNamespace(lods=[{}], materials=[])
        with patch.object(meshedit._survey, 'probe', return_value={'status': 'ok', 'warnings': []}), \
             patch.object(meshedit._survey, 'verdict_text', return_value='Ready'), \
             patch.object(meshedit._mesh, 'Mesh', return_value=model), \
             patch.object(meshedit._mesh, 'export_glb', side_effect=lambda _model, _lod, path: Path(path).write_bytes(b'glb')), \
             patch.object(meshedit._meshmat, 'build_manifest', side_effect=manifest), \
             patch.object(meshedit, '_run_blender', side_effect=blender), \
             patch.object(meshedit, '_CACHE', str(self.root/'cache')):
            result = meshedit.extract_blend(game_rel, base_path='source', project_textures=False)
        self.assertFalse(result['project_textures'])
        self.assertTrue(Path(roots[0]).is_relative_to(self.root/'cache'))
        self.assertFalse(list((self.root/'project').rglob('*.png')))
        self.assertTrue(Path(result['blend']).is_file())
        self.assertTrue(json.loads(Path(result['blend']+'.mat.json').read_text())['pack_images'])

    def test_blender_texture_import_choice_requires_a_boolean(self):
        with patch.object(meshedit._survey, 'probe', return_value={'status': 'ok'}), \
             patch.object(meshedit._mesh, 'Mesh'), self.assertRaisesRegex(ValueError, 'true or false'):
            meshedit.extract_blend('Meshes/SK_Body', base_path='source', project_textures='false')

    def test_duplicate_slot_names_round_trip_as_distinct_geometry_without_changing_the_cooked_table(self):
        from test_blender_import import FakeMesh
        model = FakeMesh()
        model.lods[0]['col_off'] = None
        model.materials = [{'slot_name':'Shared', 'pkg_idx':-1}, {'slot_name':'Shared', 'pkg_idx':-2}]
        before = json.loads(json.dumps(model.materials))
        path = self.root/'duplicate-slots.glb'
        mesh.export_glb(model, 0, str(path))
        document, _ = mesh.load_glb(str(path))
        self.assertEqual([m['name'] for m in document['materials']], ['Shared', 'Shared__slot_1'])
        sections = mesh.glb_to_sections(model, 0, str(path))
        self.assertEqual([len(section['positions']) for section in sections], [16, 16])
        for section, original in zip(sections, model.lods[0]['sections']):
            start = original['base_vertex']
            np.testing.assert_allclose(section['positions'], model.pos[start:start+16], atol=1e-5)
        self.assertEqual(model.materials, before)

    def test_generated_slot_keys_cannot_collide_with_real_slot_names(self):
        names = ['Shared', 'Shared', 'Shared__slot_1', 'Shared__slot_1_']
        keys = mesh.material_slot_names([{'slot_name':name} for name in names])
        self.assertEqual(keys, ['Shared', 'Shared__slot_1__', 'Shared__slot_1', 'Shared__slot_1_'])

    def test_duplicate_slot_manifest_keeps_each_imported_material(self):
        model = types.SimpleNamespace(materials=[{'slot_name':'Shared'}, {'slot_name':'Shared'}])
        slots = [{'slot':'Shared', 'mi':mi, 'maps':[], 'parameters':{}} for mi in (self.child, self.parent)]
        with patch.object(meshmat, 'resolve_mesh_materials', return_value=slots), \
                patch.object(meshmat, 'resolve_mesh_textures', side_effect=lambda value:value), \
                patch.object(meshmat, 'extract_textures_to_project', return_value={}):
            result = meshmat.build_manifest('Meshes/SK_Body', model)
        self.assertEqual({key:value['mi'] for key,value in result['slots'].items()},
                         {'Shared':self.child, 'Shared__slot_1':self.parent})

    def test_texture_rename_preserves_inline_mips_without_interpreting_pixels_as_headers(self):
        injected=self.root/'encoded.uasset';injected.write_bytes(b'header')
        payload=b'properties'+bytes(range(256))*4+b'inline mips'
        injected.with_suffix('.uexp').write_bytes(payload+b'\xc1\x83\x2a\x9e')
        doc={'ObjectVersionUE5':'DATA_RESOURCES','NameMap':['None','T_Before'],
             'Exports':[{'ObjectName':'T_After','SerialOffset':6,'SerialSize':len(payload),
                         'PlatformData':{'Mips':[{'Data':'lost'}]},'Extras':'extra'}]}
        self.assertTrue(custom_texture._preserve_export_bytes(doc,str(injected)))
        export=doc['Exports'][0]
        self.assertEqual(export['$type'],'UAssetAPI.ExportTypes.RawExport, UAssetAPI')
        self.assertEqual(base64.b64decode(export['Data']),payload)
        self.assertEqual(export['Extras'],'')
        self.assertEqual(doc['NameMap'],['None','T_Before'])

    def test_texture_rename_rejects_partial_or_overlapping_export_ranges(self):
        injected=self.root/'encoded.uasset';injected.write_bytes(b'header')
        injected.with_suffix('.uexp').write_bytes(b'pixels'+b'\xc1\x83\x2a\x9e')
        for exports in ([{'SerialOffset':7,'SerialSize':5}],
                        [{'SerialOffset':6,'SerialSize':6},{'SerialOffset':6,'SerialSize':6}]):
            with self.assertRaisesRegex(RuntimeError,'unsupported export layout'):
                custom_texture._preserve_export_bytes({'ObjectVersionUE5':'DATA_RESOURCES','Exports':exports},str(injected))

    def test_partial_import_accepts_explicit_coverage_without_changing_legacy_rig_options(self):
        self.assertEqual(set(meshreplace.import_options()),{'keep_skeleton','keep_weights','keep_morphs'})
        self.assertTrue(meshreplace.import_options({'keep_parts':True})['keep_parts'])
        self.assertFalse(meshreplace.import_options({'keep_parts':False})['keep_parts'])
        with self.assertRaises(ValueError):meshreplace.import_options({'keep_parts':'yes'})

    def test_replacement_input_error_reaches_the_user_without_a_blender_traceback(self):
        result=types.SimpleNamespace(stdout='Blender 5.1\nTraceback (most recent call last):\nValueError: Enable Keep untouched parts\n',stderr='')
        with patch.object(meshedit,'find_blender',return_value='blender'),patch.object(jobs,'run_process',return_value=result):
            with self.assertRaisesRegex(ValueError,'^Enable Keep untouched parts$'):
                meshedit._run_blender('replacement_to_blend.py',[],'REPLACEMENT')

    def test_partial_sections_come_from_each_original_lod_even_when_absent_from_the_upload(self):
        from test_blender_import import FakeMesh
        model=FakeMesh();model.lods[0]['col_off']=None
        path=self.root/'partial.glb';mesh.export_glb(model,0,str(path))
        document,binary=mesh.load_glb(str(path));document['meshes'][0]['primitives']=document['meshes'][0]['primitives'][:1]
        model.lods.append({**model.lods[0],'layout':{'source_index':3}})
        original_positions=model.positions
        model.positions=lambda lod:original_positions(lod)*(2 if lod is model.lods[1] else 1)
        with patch.object(mesh,'load_glb',return_value=(document,binary)):
            with self.assertRaisesRegex(ValueError,'no primitive'):mesh.glb_to_sections(model,0,str(path))
            for lod in (0,1):
                sections=mesh.glb_to_sections(model,lod,str(path),preserve_parts=['Slot_1'])
                np.testing.assert_array_equal(sections[1]['positions'],model.positions(model.lods[lod])[16:32])
                np.testing.assert_array_equal(sections[1]['weight'][:,:2],np.tile([.75,.25],(16,1)))
                np.testing.assert_array_equal(sections[1]['morph_lods'],[model.lods[lod]['layout']['source_index']]*16)
            with self.assertRaisesRegex(ValueError,'slots changed'):
                mesh.glb_to_sections(model,0,str(path),preserve_parts=['Missing_slot'])

    def test_unassigned_material_faces_are_rejected_instead_of_dropped(self):
        from test_blender_import import FakeMesh
        model=FakeMesh();model.lods[0]['col_off']=None
        path=self.root/'unassigned.glb';mesh.export_glb(model,0,str(path))
        document,binary=mesh.load_glb(str(path))
        document['meshes'][0]['primitives'][0].pop('material',None)
        with patch.object(mesh,'load_glb',return_value=(document,binary)):
            with self.assertRaisesRegex(ValueError,'without an assigned material'):
                mesh.glb_to_sections(model,0,str(path))

    def test_import_repairs_known_bones_that_cannot_reach_the_target_section(self):
        from test_blender_import import FakeMesh
        model=FakeMesh(sections=1);model.lods[0]['col_off']=None
        count=len(model.pos);local=np.zeros((count,8),np.uint16);weight=np.zeros((count,8),'f4');weight[:,0]=1
        model.skin_weights=lambda lod:(local,weight)
        path=self.root/'root-weighted.glb';mesh.export_glb(model,0,str(path))
        # These destination vertices are attached only to spine. A valid global
        # root weight has no permitted ancestor in this section's fixed palette.
        model.section_bonemap=lambda section:[1]
        with self.assertRaisesRegex(ValueError,'no skin weight'):mesh.glb_to_sections(model,0,str(path))
        fitted=mesh.glb_to_sections(model,0,str(path),repair_weights=True)[0]
        np.testing.assert_array_equal(fitted['global_idx'][:,0],np.ones(count))
        np.testing.assert_array_equal(fitted['weight'][:,0],np.ones(count))
        self.assertEqual(fitted['weights_repaired'],count)

    def document(self,name,parent=None,colors=(),scalars=(),textures=None):
        path=self.root/(name+'.json')
        data={'Exports':[{'Data':[]}], 'Imports':[], 'colors':list(colors),'scalars':list(scalars),'textures':textures or {}}
        if parent:
            data['Exports'][0]['Data'].append({'Name':'Parent','Value':-1})
            data['Imports']=[{'ObjectName':os.path.basename(parent),'ClassName':'MaterialInstanceConstant','OuterIndex':-2},
                             {'ObjectName':'/Game/Marvel/'+parent}]
        path.write_text(json.dumps(data),encoding='utf-8');return str(path)

    def test_effective_parameters_keep_child_values_and_texture_ownership(self):
        child=self.document('child',self.parent,[{'name':'Tint','rgba':[1,0,0,1]}],
                            [{'name':'Metallic','value':.2}],{'BaseColor':'Textures/T_Child'})
        parent=self.document('parent',colors=[{'name':'Tint','rgba':[0,1,0,1]}],
                             scalars=[{'name':'Metallic','value':1},{'name':'Roughness','value':.5}],
                             textures={'BaseColor':'Textures/T_Parent','Normal':'Textures/T_Normal'})
        def assignments(gr):return {'BaseColor':{},'Normal':{}}
        with patch.object(material,'mat_json',side_effect=lambda gr,**kw:child if gr==self.child else parent), \
             patch.object(material,'_mat_params',side_effect=lambda d:(d['colors'],d['scalars'])), \
             patch.object(material,'_mat_textures',side_effect=lambda d:d['textures']), \
             patch.object(material,'_mat_surface',return_value={'parent':'M_Common_Body'}), \
             patch.object(custom_texture,'assignments',side_effect=assignments), \
             patch.object(custom_texture,'image_path',side_effect=lambda gr,param:gr+'/'+param+'.png'):
            result=meshmat.material_snapshot(self.child)
        self.assertEqual(result['colors'],[{'name':'Tint','rgba':[1,0,0,1]}])
        self.assertEqual({s['name']:s['value'] for s in result['scalars']},{'Metallic':.2,'Roughness':.5})
        self.assertEqual(result['textures'],{'BaseColor':'Textures/T_Child','Normal':'Textures/T_Normal'})
        self.assertEqual(result['custom_paths']['BaseColor'],self.child+'/BaseColor.png')
        self.assertEqual(result['custom_paths']['Normal'],self.parent+'/Normal.png')

    def test_fixed_four_influence_buffers_do_not_cross_vertex_boundaries(self):
        packed=bytes([1,2,3,4,100,80,50,25,5,6,7,8,255,0,0,0])
        model=types.SimpleNamespace(_blob=lambda lod:packed)
        lod={'num_verts':2,'sw_off':0,'sw_cnt':len(packed),'sw_esz':1,'max_bone_influences':4}
        indices,weights=mesh.Mesh.skin_weights(model,lod)
        np.testing.assert_array_equal(indices[:,:4],[[1,2,3,4],[5,6,7,8]])
        np.testing.assert_allclose(weights.sum(axis=1),[1,1])
        np.testing.assert_array_equal(weights[:,4:],0)
        padded=bytes([1,2,3,4,0,0,0,0,100,80,50,25,0,0,0,0])
        model._blob=lambda lod:padded;lod.update(num_verts=1,sw_cnt=16)
        np.testing.assert_allclose(mesh.Mesh.skin_weights(model,lod)[1][0,:4],[100/255,80/255,50/255,25/255])

    def test_absent_empty_and_populated_colour_buffers_keep_the_tail_aligned(self):
        buffers=(b'\0'*12+b'\1\0'+struct.pack('<4I',1,1,0,0)+struct.pack('<2I',8,1)+b'\0'*8+
                 struct.pack('<2I',4,1)+b'\0'*4+b'\1\0'+struct.pack('<6I',0,4,4,1,0,0)+
                 struct.pack('<2I',1,8)+b'\0'*8+b'\1\0'+struct.pack('<3I',0,4,0))
        for colours in (b'',b'\1\0'+struct.pack('<2I',4,0),
                        b'\1\0'+struct.pack('<4I',4,1,4,1)+b'\xff'*4):
            blob=buffers+colours+b'\0'*16
            model=types.SimpleNamespace(_blob=lambda lod:blob,_lod_blob_end=lambda i,lod:len(blob))
            lod={'pos_off':0,'num_verts':1,'layout':{'blob_end':len(blob),'sections':[]}}
            mesh.Mesh._locate_vertex_buffers(model,lod)
            self.assertEqual(lod['tail_off'],len(buffers)+len(colours))
            self.assertEqual(lod['col_off'],len(buffers)+18 if len(colours)>10 else None)
            mesh.Mesh._locate_tail(model,0,lod)
            self.assertEqual(lod['tail_prefix'],b'\0'*8)
            self.assertFalse(lod['had_morphs'])

    def test_psk_metres_and_centimetres_are_detected_from_matching_bones(self):
        data={'bones':['root','pelvis','spine','neck','head'],'bone_parents':[0,0,1,2,3],
              'bone_positions':[(0,0,0),(0,0,1),(.2,0,0),(.1,0,0),(.15,0,0)]}
        target={name:(data['bones'][parent],float(np.linalg.norm(position))) for name,parent,position in
                zip(data['bones'][1:],data['bone_parents'][1:],data['bone_positions'][1:])}
        self.assertEqual(source_scale(data,target)['scale'],1)
        data['bone_positions']=[tuple(value*100 for value in point) for point in data['bone_positions']]
        self.assertEqual(source_scale(data,target)['scale'],.01)
        self.assertEqual(source_scale(data,target,'metres')['scale'],1)
        self.assertEqual(meshreplace.import_options({'source_units':'metres'})['source_units'],'metres')
        with self.assertRaises(ValueError):meshreplace.import_options({'source_units':'feet'})

    def test_actorx_y_mirror_is_undone_before_nearest_surface_transfers(self):
        data={'points':[(0,-.09676296,1.2214154),(1,.25,2)]}
        converted=unreal_points(data,100)
        np.testing.assert_allclose(converted,[(0,9.676296,122.14154),(100,-25,200)])
        self.assertEqual(data['points'][0],(0,-.09676296,1.2214154))

    def test_inverse_bind_matrices_use_gltf_column_major_storage(self):
        from test_blender_import import FakeMesh
        model=FakeMesh(sections=1)
        model.bones=[bone('root',translation=(20,5,3),rotation=(0,0,.38268343,.92387953)),bone('spine',0,(4,7,130))]
        path=self.root/'bind-pose.glb';mesh.export_glb(model,0,str(path))
        document,binary=mesh.load_glb(str(path))
        packed=mesh.gltf_accessor(document,binary,document['skins'][0]['inverseBindMatrices'])
        matrices=packed.reshape(-1,4,4).transpose(0,2,1)
        worlds,_=mesh._bone_world_matrices(model.bones)
        np.testing.assert_allclose(np.array(worlds)@matrices,np.repeat(np.eye(4)[None],2,axis=0),atol=1e-6)

    def test_actorx_custom_normals_colours_and_secondary_uvs_are_retained(self):
        from test_mesh_replacement import fixture_psk,chunk
        path=self.root/'extended.psk'
        optional=(chunk('VTXNORMS',12,[struct.pack('<3f',0,0,1)]*3)+
            chunk('VERTEXCOLOR',4,[bytes([36,38,127,127])]*3)+
            chunk('EXTRAUVS0',8,[struct.pack('<2f',.25,.75)]*3))
        path.write_bytes(fixture_psk()+optional);data=read_psk(path)
        self.assertEqual(data['normals'],[(0,0,1)]*3)
        self.assertEqual(data['colors'],[(36,38,127,127)]*3)
        self.assertEqual(data['extra_uvs'],[[(.25,.75)]*3])
        path.write_bytes(fixture_psk()+chunk('VTXNORMS',12,[struct.pack('<3f',0,0,1)]))
        with self.assertRaisesRegex(ValueError,'custom normals'):read_psk(path)

    def test_streamed_rebuild_metadata_matches_fixed_eight_weights_and_full_precision_uvs(self):
        from atelier.handlers.meshsurvey import _read_availability
        size_offset=12;payload=bytearray(b'x'*160)
        struct.pack_into('<I',payload,size_offset,100)
        model=types.SimpleNamespace(uexp=payload)
        lod={'layout':{'size_offset':size_offset},'num_tex_coords':2,'col_off':None}
        before=bytes(payload)
        mesh.Mesh._patch_mirror(model,lod,100,200,4,6,4,5)
        # Profile count follows the fixed metadata. Give the readback an empty map.
        struct.pack_into('<I',payload,size_offset+8+65,0)
        header,end=_read_availability(payload,size_offset+8,False,len(payload))
        self.assertEqual((header['idx_stride'],header['n_indices'],header['smvb_num_verts']),(2,6,5))
        self.assertEqual((header['full_prec_uv'],header['max_bone_influences'],header['num_bones']),(1,8,40))
        self.assertEqual((header['variable_bones'],header['num_lookup_verts'],header['col_num_verts']),(0,0,0))
        self.assertEqual(bytes(payload[:size_offset]),before[:size_offset])
        self.assertEqual(bytes(payload[size_offset+4:size_offset+8]),before[size_offset+4:size_offset+8])
        self.assertEqual(bytes(payload[end:]),before[end:])

    def test_embedded_weapon_detection_requires_every_vertex_and_section(self):
        sections=[{'mat':0,'base_vertex':0,'num_verts':3},{'mat':1,'base_vertex':3,'num_verts':3}]
        weights=np.zeros((6,8));weights[:,0]=1
        indices=np.zeros((6,8),dtype=np.int32);indices[:3,0]=1
        body=types.SimpleNamespace(bones=[bone('root'),bone('Sword_Weapon_Root')],
            materials=[{'slot_name':'MI_Weapon'},{'slot_name':'MI_Body'}],lods=[{'sections':sections}],
            skin_weights=lambda lod:(indices,weights),section_bonemap=lambda section:[0,1])
        weapon=types.SimpleNamespace(bones=[bone('Sword_Weapon_Root')])
        self.assertEqual(meshstudio.embedded_weapon_slots(body,[weapon]),{0})
        sections[1]['mat']=0
        self.assertEqual(meshstudio.embedded_weapon_slots(body,[weapon]),set())

    def test_recursive_material_is_rejected_without_infinite_native_reads(self):
        child=self.document('child',self.parent);parent=self.document('parent',self.child)
        with patch.object(material,'mat_json',side_effect=lambda gr,**kw:child if gr==self.child else parent):
            with self.assertRaisesRegex(ValueError,'Recursive'):meshmat.material_snapshot(self.child)

    def test_one_failed_texture_does_not_discard_other_materials(self):
        image=self.root/'cached.png';Image.new('RGB',(32,32),'red').save(image)
        def decode(dst,base):
            if base=='bad':raise RuntimeError('unavailable texture')
            return str(image)
        with patch('atelier.handlers.texture.ensure_work_base',side_effect=lambda gr,**kw:gr), \
             patch('atelier.handlers.texture.decode_to_png',side_effect=decode), \
             patch.object(meshmat,'CACHE_3DVIEW',str(self.root/'cache')):
            result=meshmat.extract_textures_to_project(['good','bad'])
        self.assertEqual(result['bad']['status'],'failed')
        self.assertEqual(Image.open(result['good']['path']).getpixel((0,0)),(255,0,0))

    def test_standalone_texture_is_an_independent_copy_of_the_project_edit(self):
        source=Path(config.project_base('Textures/T_Edited')+'.png');source.parent.mkdir(parents=True)
        Image.new('RGB',(32,32),(17,31,49)).save(source)
        target=self.root/'portable'
        with patch('atelier.handlers.texture.ensure_work_base',side_effect=AssertionError('must preserve edit')):
            result=meshmat.extract_textures_to_project(['Textures/T_Edited'],root=str(target))
        copied=Path(result['Textures/T_Edited']['path'])
        self.assertEqual(copied.read_bytes(),source.read_bytes());self.assertFalse(os.path.samefile(copied,source))
        copied.write_bytes(b'changed');self.assertEqual(Image.open(source).getpixel((0,0)),(17,31,49))

    def test_different_custom_images_of_one_source_texture_stay_distinct(self):
        first=self.root/'red.png';second=self.root/'blue.png'
        Image.new('RGB',(32,32),'red').save(first);Image.new('RGB',(32,32),'blue').save(second)
        slots=[{'slot':'Body','mi':self.child,'maps':[{'param':'BaseColor','role':'basecolor','game_rel':'Textures/T_Shared'}],
                'parameters':{'custom_paths':{'BaseColor':str(first)}}},
               {'slot':'Weapon','mi':self.parent,'maps':[{'param':'BaseColor','role':'basecolor','game_rel':'Textures/T_Shared'}],
                'parameters':{'custom_paths':{'BaseColor':str(second)}}}]
        with patch.object(meshmat,'resolve_mesh_materials',return_value=slots), \
             patch.object(meshmat,'resolve_mesh_textures',side_effect=lambda s:s), \
             patch.object(meshmat,'extract_textures_to_project',return_value={}):
            model=types.SimpleNamespace(materials=[{'slot_name':record['slot']} for record in slots])
            result=meshmat.build_manifest('Meshes/SK_Body',model,root=str(self.root/'portable'))
        red=result['slots']['Body']['maps'][0]['path'];blue=result['slots']['Weapon']['maps'][0]['path']
        self.assertNotEqual(red,blue)
        self.assertEqual(Image.open(red).getpixel((0,0)),(255,0,0))
        self.assertEqual(Image.open(blue).getpixel((0,0)),(0,0,255))

    def test_dye_preview_uses_custom_diffuse_and_original_comparison_bypasses_it(self):
        edited=self.root/'diffuse.png';Image.new('RGB',(32,32),'red').save(edited)
        mask=Image.new('RGBA',(32,32),(0,0,0,0));vanilla=Image.new('RGB',(32,32),'blue')
        with patch.object(dye,'dye_slots',return_value=('T_Mask','T_Base')), \
             patch.object(dye,'_tex_image',side_effect=lambda gr,**kw:mask if gr=='T_Mask' else vanilla), \
             patch.object(custom_texture,'image_path',side_effect=lambda gr,slot:str(edited) if slot=='BaseColor' else None):
            result=dye.dye_preview(self.child,size=32,dye_off=True,out_path=str(self.root/'preview.png'))
            original=dye.dye_preview(self.child,size=32,dye_off=True,original=True,out_path=str(self.root/'original.png'))
        self.assertEqual(Image.open(result).getpixel((0,0)),(255,0,0))
        self.assertEqual(Image.open(original).getpixel((0,0)),(0,0,255))

    def test_shared_weapon_root_matches_physical_reference_with_grip_offset(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('SwordRoot',0,(25,-10,140))])
        weapon=types.SimpleNamespace(base='SK_Sword',bones=[bone('SwordRoot',translation=(0,0,20))])
        transform,anchor=meshport.attachment_transform(body,weapon)
        body_bones=meshport._bones(body);weapon_bones=meshport._bones(weapon)
        np.testing.assert_allclose(transform@weapon_bones[anchor],body_bones[anchor],atol=1e-10)
        # Centimetres in the cooked data become metres and the height is Y-up.
        self.assertAlmostEqual(body_bones[anchor][1,3],1.4)

    def test_left_and_right_socket_transforms_do_not_share_an_anchor(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('weapon_r',0,(-40,0,100)),bone('weapon_l',0,(40,0,100))])
        weapon=types.SimpleNamespace(base='SK_Gun',bones=[bone('root')])
        right,r=meshport.attachment_transform(body,weapon,'right');left,l=meshport.attachment_transform(body,weapon,'left')
        self.assertEqual((r,l),('weapon_r','weapon_l'))
        self.assertAlmostEqual(np.linalg.norm(right[:3,3]-left[:3,3]),.8)
        with self.assertRaisesRegex(ValueError,'No weapon_l'):
            meshport.attachment_transform(types.SimpleNamespace(bones=[bone('root')]),weapon,'left')

    def test_blade_grip_below_wrapper_keeps_its_authored_position_and_rotation(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('weapon_r',0,(-40,0,100))])
        weapon=types.SimpleNamespace(base='SK_Dagger',bones=[bone('WP_Root'),
            bone('WP_Sword',0,(2,0,0),(1,0,0,0)),bone('Sword01',1,(0,0,24))])
        transform,anchor=meshport.attachment_transform(body,weapon)
        self.assertEqual(anchor,'weapon_r')
        np.testing.assert_allclose(transform@meshport._bones(weapon)['WP_Sword'],
                                   meshport._bones(body)['weapon_r'],atol=1e-10)

    def test_cannon_suffix_and_additional_weapon_families_use_the_authored_left_grip(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('weapon_l',0,(40,0,100)),bone('weapon_r',0,(-40,0,100))])
        for family in ['Cannon','Wand','Trident','Nunchaku']:
            weapon=types.SimpleNamespace(base='SK_WP_CannonL',bones=[bone('WP_Root'),
                bone(family+'Root',0,(2,0,0),(1,0,0,0))])
            transform,anchor=meshport.attachment_transform(body,weapon)
            self.assertEqual(anchor,'weapon_l')
            np.testing.assert_allclose(transform@meshport._bones(weapon)[family+'Root'],
                                       meshport._bones(body)['weapon_l'],atol=1e-10)

    def test_explicit_alignment_precedes_a_deforming_cannon_joint(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('weapon_l',0,(40,0,100))])
        weapon=types.SimpleNamespace(base='SK_WP_CannonL',bones=[bone('Root'),bone('Align',0),
            bone('Hand_l_Cannon1',1,(2,0,0),(1,0,0,0))])
        transform,anchor=meshport.attachment_transform(body,weapon)
        self.assertEqual(anchor,'weapon_l')
        np.testing.assert_allclose(transform@meshport._bones(weapon)['Align'],
                                   meshport._bones(body)['weapon_l'],atol=1e-10)

    def test_hand_mounted_cannon_uses_wrist_instead_of_palm(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('hand_l',0,(30,0,100)),bone('weapon_l',1,(12,0,0))])
        weapon=types.SimpleNamespace(base='SK_WP_CannonL',bones=[bone('Root'),bone('Align',0),
            bone('Hand_l_Cannon1',1,(2,0,0),(1,0,0,0))])
        transform,anchor=meshport.attachment_transform(body,weapon)
        self.assertEqual(anchor,'hand_l')
        np.testing.assert_allclose(transform@meshport._bones(weapon)['Align'],
                                   meshport._bones(body)['hand_l'],atol=1e-10)

    def test_shared_sword_uses_the_handle_at_the_hand_instead_of_the_floor_origin(self):
        body=types.SimpleNamespace(bones=[bone('root'),bone('weapon_r',0,(-48,7,101)),
            bone('Sword_Weapon_Root',0),bone('Sword_WeaponHandle',2,(0,0,20))])
        weapon=types.SimpleNamespace(base='SK_Sword',bones=[bone('Sword_Weapon_Root'),bone('Sword_WeaponHandle',0,(0,0,20))])
        transform,anchor=meshport.attachment_transform(body,weapon)
        self.assertEqual(anchor,'weapon_r')
        np.testing.assert_allclose(transform@meshport._bones(weapon)['Sword_WeaponHandle'],meshport._bones(body)['weapon_r'],atol=1e-10)

    def test_export_rejects_foreign_weapons_before_native_work(self):
        with patch.object(meshport.meshstudio,'skin_meshes',return_value=[]), \
             patch.object(meshport.meshstudio,'complete_mesh_source',side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(ValueError,'belonging'):
                meshport.export('Characters/1029/1029001/Meshes/SK_Body',[{'game_rel':'Characters/1039/1039001/Weapons/SK_Hammer'}])

    def test_incomplete_material_port_keeps_the_previous_complete_scene(self):
        target=self.root/'portable/body.blend';target.parent.mkdir();target.write_bytes(b'previous complete scene')
        with patch.object(meshport,'destination',return_value=target), \
             patch.object(meshport.meshstudio,'skin_meshes',return_value=[]), \
             patch.object(meshport.meshstudio,'complete_mesh_source',return_value='fixture'), \
             patch.object(meshport.mesh,'Mesh',return_value=object()), \
             patch.object(meshport.meshedit,'extract_blend',return_value={'material_manifest_complete':False,'material_issues':['MI_Hair: missing mask']}), \
             patch.object(meshport.meshedit,'_run_blender',side_effect=AssertionError('must not assemble an incomplete port')):
            with self.assertRaisesRegex(ValueError,'missing mask'):
                meshport.export('Characters/1029/1029001/Meshes/SK_Body')
        self.assertEqual(target.read_bytes(),b'previous complete scene')

    def test_saved_geometry_uses_the_mod_export_rebuild_before_porting(self):
        gr='Characters/1029/1029001/Meshes/SK_Body'
        edited=Path(config.project_base(gr)+'.blend');edited.parent.mkdir(parents=True);edited.write_bytes(b'edited sculpt')
        with patch.object(meshport,'destination',return_value=self.root/'portable/body.blend'), \
             patch.object(meshport.meshstudio,'skin_meshes',return_value=[]), \
             patch.object(meshport.meshstudio,'complete_mesh_source',return_value='original'), \
             patch.object(meshport.mesh,'Mesh',return_value=object()), \
             patch.object(meshport.meshreplace,'is_original',return_value=False), \
             patch.object(meshport.meshedit,'stage_mesh',return_value={'uasset':'staged/body.uasset'}) as stage, \
             patch.object(meshport.meshedit,'extract_blend',return_value={'material_manifest_complete':False,'material_issues':['stop after inspection']}) as prepare:
            with self.assertRaisesRegex(ValueError,'stop after inspection'):meshport.export(gr)
        self.assertEqual(stage.call_args.kwargs['blend_path'],str(edited))
        self.assertEqual(stage.call_args.kwargs['base_path'],'original')
        self.assertEqual(prepare.call_args.kwargs['base_path'],'staged/body')

    def test_cancelled_texture_export_is_not_reported_as_a_partial_success(self):
        with patch('atelier.handlers.texture.ensure_work_base',side_effect=jobs.Cancelled('cancelled')), \
             patch.object(meshmat,'CACHE_3DVIEW',str(self.root/'empty')):
            with self.assertRaises(jobs.Cancelled):meshmat.extract_textures_to_project(['T_Uncached'])

    def test_texture_workers_keep_the_request_project_and_cancellation_context(self):
        sentinel=ContextVar('studio_test_context',default='lost');token=sentinel.set('captured')
        self.addCleanup(sentinel.reset,token)
        seen=[]
        def source(gr,**options):
            self.assertTrue(options.get('prefer_exact'))
            seen.append((config.get_import_root(),sentinel.get()));return None
        with patch('atelier.handlers.texture.ensure_work_base',side_effect=source), \
             patch.object(meshmat,'CACHE_3DVIEW',str(self.root/'empty')):
            meshmat.extract_textures_to_project(['T_A','T_B'])
        self.assertEqual([(Path(path).resolve(), context) for path, context in seen],
                         [((self.root/'project').resolve(), 'captured')]*2)


if __name__=='__main__':unittest.main()
