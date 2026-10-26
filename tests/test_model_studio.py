"""Slot provenance, texture semantics and reversible all-LOD section exports.

The byte-buffer fixture uses the real index patcher and file writer. Native
decoding and the cooked-container parser are checked separately on real models.
"""
import atexit
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='atelier-model-studio-')
atexit.register(temporary.cleanup)
os.environ['ATELIER_DATA_DIR'] = temporary.name
from atelier import config, project_meta, project_trash
from atelier.handlers import material, mesh, meshmat, meshstudio, meshvisibility, meshreplace, meshedit
from atelier.web import browse


class BufferMesh:
    """Labelled synthetic layout, real Mesh byte editing and persistence methods."""
    _blob = mesh.Mesh._blob
    degenerate_triangles = mesh.Mesh.degenerate_triangles
    save = mesh.Mesh.save

    def __init__(self, base):
        self.base = base
        self.uasset = bytearray(Path(base + '.uasset').read_bytes())
        self.uexp = bytearray(Path(base + '.uexp').read_bytes())
        self.ubulk = bytearray(Path(base + '.ubulk').read_bytes())
        layout = json.loads(self.uasset)
        self.materials = layout['materials']
        self.lods = layout['lods']
        self._layout = [{'blob': lod['buf']} for lod in self.lods]


def fixture(base):
    base.parent.mkdir(parents=True, exist_ok=True)
    # The same slot occurs in TWO sections in each LOD. The old helper's next()
    # silently edited just the first section; a second visible island survived.
    lods = []
    for i in range(3):
        lods.append({'buf': 'ubulk' if i < 2 else 'uexp', 'idx_stride': 2,
                     'idx_off': i*64 if i < 2 else 0,
                     'sections': [{'mat': 0, 'base_index': 0, 'num_tris': 1, 'base_vertex': 0},
                                  {'mat': 0, 'base_index': 3, 'num_tris': 1, 'base_vertex': 3},
                                  {'mat': 1, 'base_index': 6, 'num_tris': 1, 'base_vertex': 6}]})
    doc = {'materials': [{'slot_name': 'MI_Body'}, {'slot_name': 'MI_Hair'}], 'lods': lods}
    Path(str(base)+'.uasset').write_bytes(json.dumps(doc).encode())
    data = struct.pack('<9H', *range(9)) + b'opaque vertices, weights and morphs'.ljust(46,b'!')
    Path(str(base)+'.uexp').write_bytes(data)
    Path(str(base)+'.ubulk').write_bytes(data*2)


class Studio(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        context = config.project_context(str(self.root/'project')); context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.gr = 'Characters/1029/1029001/Meshes/SK_Body'
        mapping = patch('atelier.handlers.mesh_lods.load_material_maps', return_value=[])
        mapping.start(); self.addCleanup(mapping.stop)
        self.slots = [{'index': 0, 'slot': 'MI_Body', 'mi': 'Characters/1029/1029001/Materials/MI_Body', 'via': 'imports'},
                      {'index': 1, 'slot': 'MI_Hair', 'mi': 'Characters/1029/1029001/Materials/MI_Hair', 'via': 'imports'}]

    def test_visibility_uses_the_lower_lod_material_map_instead_of_its_raw_section_index(self):
        source, target = self.root/'original/SK_Body', self.root/'stage/SK_Body'
        fixture(source); fixture(target)
        with patch.object(mesh, 'Mesh', side_effect=BufferMesh), \
                patch('atelier.handlers.texture.find_extracted', return_value=str(source)), \
                patch('atelier.handlers.mesh_lods.load_material_maps', return_value=[[], [], [1,0]]):
            meshvisibility.apply_to_staged(self.gr, str(target)+'.uasset',
                                          sections=[{'slot_index':0, 'slot_name':'MI_Body'}])
        before, after = BufferMesh(str(source)), BufferMesh(str(target))
        for index, lod in enumerate(after.lods):
            values = struct.unpack_from('<9H', after._blob(lod), lod['idx_off'])
            expected = (0,0,0,3,3,3,6,7,8) if index < 2 else (0,1,2,3,4,5,6,6,6)
            self.assertEqual(values, expected)
        self.assertEqual(before.uasset, after.uasset)

    def test_small_skeletal_name_table_requires_class_and_export_identity(self):
        names = ['lambert1', 'Root', 'SK_Tiny', '/Script/Engine', 'Class',
                 'SkeletalMesh', 'Default__SkeletalMesh', 'Skeleton']
        data = b'header\xff' + b''.join(struct.pack('<i', len(name) + 1) + name.encode() + b'\0' + bytes(4)
                                      for name in names) + b'\xfftrailer'
        self.assertEqual(mesh.skeletal_name_table(data, 'SK_Tiny'), (7, names))
        with self.assertRaisesRegex(ValueError, 'identify this skeletal mesh'):
            mesh.skeletal_name_table(data, 'SK_Other')
        with self.assertRaisesRegex(ValueError, 'identify this skeletal mesh'):
            mesh.skeletal_name_table(data.replace(b'SkeletalMesh', b'StaticObject'), 'SK_Tiny')

    def test_discovery_separates_held_weapons_from_bodies_and_props(self):
        paths = ['Meshes/SK_Body', 'Weapons/Sword/Meshes/SK_Sword', 'Weapons/Guns/Meshes/SK_Gun_L',
                 'Weapons/Guns/Meshes/SK_Gun_R', 'Weapons/MVP/Bullet/Meshes/SK_Bullet',
                 'Weapons/Emote/Meshes/SK_Flag', 'Weapons/Demon/Meshes/SK_Summon', 'Slots/Accessories/Meshes/SK_Badge',
                 'Weapons/Sword/Meshes/SK_Sword_Skeleton',
                 'Weapons/Sword/Meshes/SK_Sword_PhysicsAsset', 'Meshes/SK_Body_Lobby',
                 'Meshes/SK_Body_PA', 'Meshes/SK_Body_FPP', 'Weapons/FPPhands/Meshes/SK_Hands',
                 'Weapons/Guns/Meshes/SK_Gun_FPP', 'Weapons/Guns/Meshes/SK_Gun_1P']
        entries = [('Characters/1029/1029001/'+p+'.uasset', '') for p in paths]
        with patch('atelier.paths.skin_entries', return_value=entries):
            result = meshstudio.skin_meshes('1029001')
        self.assertEqual([r['kind'] for r in result], ['body', 'weapon', 'weapon', 'weapon'])
        self.assertTrue(any(r['name']=='SK_Gun_L' for r in result))
        self.assertEqual(meshstudio.skin_meshes('../skin'), [])

    def test_skin_with_no_weapon_is_valid(self):
        with patch('atelier.paths.skin_entries', return_value=[('Characters/1029/1029001/Meshes/SK_Body.uasset','')]):
            self.assertEqual([r['kind'] for r in meshstudio.skin_meshes('1029001')], ['body'])

    def test_helpers_outside_weapons_do_not_replace_the_body(self):
        base = 'Characters/1042/1042001/'
        paths = ['Cues/104251/SM_SplineCables_RopeM2', 'Emote/Horn/Meshes/SK_Horn',
                 'Animations/HeroDetails/Weapon/SK_Dragon', 'Slot/Accessories/Meshes/SK_Badge',
                 '1042_Girl/Meshes/SK_1042_Girl_1042001', 'Meshes/SK_1042_1042001']
        with patch('atelier.paths.skin_entries', return_value=[(base + p + '.uasset', '') for p in paths]):
            rows = meshstudio.skin_meshes('1042001')
        self.assertEqual([row['name'] for row in rows], ['SK_1042_1042001', 'SK_1042_Girl_1042001'])

    def test_ability_props_static_duplicates_and_control_rigs_do_not_auto_equip(self):
        prefix='Characters/1027/1027001/'
        props=['SK_WP_IronWoodenWall','SK_WP_GiantArm_L','SK_WP_SporeBomb',
               'SK_WP_HandGun_Container','SK_WP_FloatingGun','SK_WP_SpiderTentacles',
               'SK_WP_Phoenix','SK_WP_Monster','SK_WP_SpearTie','SM_WP_Pistol']
        held=['SK_WP_CannonL','SK_WP_CannonR','SK_WP_DesertEagle_L','SK_WP_Trident','SK_WP_Wand','SK_WP_Nunchaku_R']
        paths=[prefix+'Weapons/Parts/'+name+'.uasset' for name in props+held]
        paths += [prefix+'Meshes/SK_Body.uasset',prefix+'Meshes/SK_Body_OnGroot_CtrlRig.uasset',prefix+'Meshes/SK_Body_FA.uasset']
        with patch('atelier.paths.skin_entries',return_value=[(path,'') for path in paths]):
            rows=meshstudio.skin_meshes('1027001')
        self.assertEqual({row['name'] for row in rows if row.get('auto_equip')},set(held))
        self.assertTrue(set(props).issubset({row['name'] for row in rows}))
        self.assertFalse(any('CtrlRig' in row['name'] for row in rows))
        self.assertFalse(any(row['name'].endswith('_FA') for row in rows))

    def test_capwolf_human_transformation_is_a_body_form_not_held_equipment(self):
        base='Characters/1022/1022504/'
        paths=['Meshes/SK_1022_1022504', 'Weapons/Caption/Meshes/SK_WP_1022504_Caption',
               'Weapons/Shield/Meshes/SK_WP_1022504_Shield']
        with patch('atelier.paths.skin_entries',return_value=[(base+p+'.uasset','') for p in paths]):
            rows=meshstudio.skin_meshes('1022504')
        by_name={row['name']:row for row in rows}
        human=by_name['SK_WP_1022504_Caption']
        self.assertEqual(human['kind'],'body')
        self.assertNotIn('auto_equip',human)
        self.assertEqual([row['name'] for row in rows if row['kind']=='weapon'],['SK_WP_1022504_Shield'])
        self.assertTrue(by_name['SK_WP_1022504_Shield']['auto_equip'])

    def test_ability_meshes_remain_selectable_without_automatic_equipping(self):
        names = ['SK_WP_1035001_DevouringSymbiote', 'SK_WP_1035001_DevouringSymbiote_Hand',
                 'SK_WP_1035001_Head', 'SK_EQPT_1035001_Plane', 'SK_WP_1036001_Plane02',
                 'SK_WP_1035001_SpikedTentacles', 'SK_WP_1035001_Sword', 'SK_WP_1035001_Gun_L']
        entries = [('Characters/1035/1035001/Weapons/Parts/' + name + '.uasset', '') for name in names]
        with patch('atelier.paths.skin_entries', return_value=entries):
            rows = meshstudio.skin_meshes('1035001')
        self.assertEqual({row['name'] for row in rows}, set(names))
        self.assertEqual({row['name'] for row in rows if row['auto_equip']}, set(names[-2:]))

    def test_import_reference_beats_a_real_but_wrong_same_named_material(self):
        model=type('Model', (), {'materials':[{'slot_name':'MI_Body_01','pkg_idx':-1}]})()
        document={'Imports':[{'OuterIndex':-2,'ObjectName':'MI_Body'}, {'ObjectName':'/Game/Marvel/Characters/1029/1029001/Materials/MI_Body'}]}
        with patch.object(meshmat,'_mesh_json',return_value=document), patch.object(meshmat,'_index_candidates',return_value=['wrong/Lobby/MI_Body_01']):
            result=meshmat.resolve_mesh_materials(self.gr,model,'fixture')
        self.assertEqual(result[0]['mi'],'Characters/1029/1029001/Materials/MI_Body')
        self.assertEqual(result[0]['via'],'imports')

    def test_preview_maps_actual_material_name_back_to_different_slot_label(self):
        slots=[{**self.slots[0],'slot':'MI_Body_01'}]
        with patch.object(meshstudio,'cooked_slots',return_value=slots):
            out=meshstudio.preview_bindings(self.gr,[{'key':'body::0','name':'MI_Body','material_index':0}])
        self.assertEqual(out[0]['slot_name'],'MI_Body_01');self.assertEqual(out[0]['slot_index'],0)

    def test_preview_batches_validated_mesh_sources_before_resolving_slots(self):
        from atelier.handlers import texture
        calls=[]
        meshes=[{'game_rel':self.gr,'slots':[{'key':'body::0','name':'MI_Body'}]},
                {'game_rel':self.gr+'_Other','slots':[{'key':'other::0','name':'MI_Body'}]}]
        def resolve(gr, requested):
            calls.append(('slots',gr))
            return [{'key':requested[0]['key'],'slot_name':'MI_Body','game_rel':self.slots[0]['mi']}]
        with patch.object(texture,'prefetch_exact',side_effect=lambda paths:calls.append(('prefetch',paths))), \
             patch('atelier.paths.skin_entries',return_value=[]), patch.object(meshstudio,'preview_bindings',side_effect=resolve):
            result=list(meshstudio.material_bindings('1029001',meshes))
        self.assertEqual(calls[0],('prefetch',[self.gr,self.gr+'_Other']))
        self.assertEqual(len(result),2)

    def test_preview_rejects_invalid_batch_before_extraction(self):
        from atelier.handlers import texture
        for meshes in ([{'game_rel':'../outside'}], ['invalid'],
                       [{'game_rel':self.gr,'slots':[{'key':'body::0','name':None}]}]):
            with self.subTest(meshes=meshes), patch.object(texture,'prefetch_exact') as extract:
                with self.assertRaises(ValueError):
                    list(meshstudio.material_bindings('1029001',meshes))
                extract.assert_not_called()

    def test_ambiguous_slot_is_never_guessed_from_a_partial_gltf(self):
        slots=[self.slots[0],{**self.slots[0],'index':1}]
        with patch.object(meshstudio,'cooked_slots',return_value=slots):
            out=meshstudio.preview_bindings(self.gr,[{'key':'body::0','name':'MI_Body','material_index':0}])
        self.assertNotIn('slot_index',out[0])
        self.assertEqual(out[0]['game_rel'],self.slots[0]['mi'])
        self.assertEqual(len(out[0]['shared_slots']),2)

    def test_shared_hair_material_resolves_without_guessing_an_outline_section(self):
        material='Characters/1029/1029001/Materials/MI_Hair'
        slots=[{'index':3,'slot':'MI_HairCards','mi':material,'via':'imports'},
               {'index':11,'slot':'MI_Outlines','mi':material,'via':'imports'}]
        with patch.object(meshstudio,'cooked_slots',return_value=slots):
            out=meshstudio.preview_bindings(self.gr,[{'key':'body::3','name':'MI_Hair','material_index':3}])
        self.assertEqual(out[0]['game_rel'],material)
        self.assertNotIn('mapping_error',out[0]);self.assertNotIn('slot_index',out[0])
        self.assertEqual(out[0]['shared_slots'],[{'slot_index':3,'slot_name':'MI_HairCards'},
                                              {'slot_index':11,'slot_name':'MI_Outlines'}])

    def test_same_material_basename_in_different_packages_stays_ambiguous(self):
        slots=[self.slots[0],{**self.slots[0],'index':1,'mi':'Characters/Other/Materials/MI_Body'}]
        with patch.object(meshstudio,'cooked_slots',return_value=slots):
            out=meshstudio.preview_bindings(self.gr,[{'key':'body::0','name':'MI_Body','material_index':0}])
        self.assertIn('mapping_error',out[0]);self.assertNotIn('game_rel',out[0])

    def test_complete_ordered_duplicate_slots_keep_individual_visibility_targets(self):
        slots=[self.slots[0],{**self.slots[0],'index':1}]
        requested=[{'key':f'body::{i}','name':'MI_Body','material_index':i} for i in range(2)]
        with patch.object(meshstudio,'cooked_slots',return_value=slots):
            out=meshstudio.preview_bindings(self.gr,requested)
        self.assertEqual([row['slot_index'] for row in out],[0,1])

    def test_texture_aliases_are_canonical_and_masks_are_not_albedo(self):
        for name in ('DiffuseMap','Base Color Map','albedo'):
            self.assertEqual(meshmat.texture_role(name),'basecolor')
        self.assertEqual(meshmat.texture_role('OpacityMask'),'opacity')
        self.assertEqual(meshmat.texture_role('DyeingTexture'),'dye')

    def test_translucent_surface_preserves_opacity_sidedness_and_parent(self):
        doc={'Exports':[{'Data':[{'Name':'Parent','Value':-1},
            {'Name':'BasePropertyOverrides','Value':[{'Name':'BlendMode','Value':'BLEND_TranslucentGreyTransmittance'},
              {'Name':'TwoSided','Value':True},{'Name':'OpacityMaskClipValue','Value':'+0'}]}]}],
             'Imports':[{'ObjectName':'M_Common_Translucent'}]}
        with patch.object(material,'_mat_params',return_value=([],[{'name':'OpacityMultiplier','value':.8}])):
            surface=material._mat_surface(doc)
        self.assertEqual(surface['opacity'],.8);self.assertTrue(surface['two_sided'])
        self.assertEqual(surface['mask_clip'],0);self.assertIn('Translucent',surface['blend_mode'])

    def toggle(self, hidden):
        with patch.object(meshstudio,'cooked_slots',return_value=self.slots), patch.object(meshstudio,'complete_mesh_source',return_value='fixture'):
            return meshvisibility.set_hidden(self.gr,0,'MI_Body',hidden)

    def test_visibility_persists_and_is_an_ordinary_reversible_project_asset(self):
        self.toggle(True);self.toggle(True)
        self.assertEqual(len(meshvisibility.hidden_sections(self.gr)),1)
        rows=browse.all_imported();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['file_type'],'mesh')
        self.assertTrue(meshreplace.is_original(self.gr))
        root=config.get_import_root();removed=project_trash.remove(root,[self.gr])
        self.assertEqual(meshvisibility.hidden_sections(self.gr),[])
        project_trash.restore(root,removed['entry'])
        self.assertEqual(len(meshvisibility.hidden_sections(self.gr)),1)
        self.toggle(False)
        self.assertNotIn('hidden_sections',project_meta.get_asset_opts(root,self.gr))
        self.assertEqual(browse.all_imported(),[])

    def test_unhide_preserves_an_existing_mesh_edit_entry_and_other_options(self):
        meshreplace.add(self.gr)
        project_meta.set_asset_opts(config.get_import_root(),self.gr,{'test_option':True})
        self.toggle(True);self.toggle(False)
        self.assertEqual(len(browse.all_imported()),1)
        self.assertTrue(project_meta.get_asset_opts(config.get_import_root(),self.gr)['test_option'])

    def test_changed_slot_or_missing_bulk_cannot_be_saved_as_export_ready(self):
        with patch.object(meshstudio,'cooked_slots',return_value=self.slots):
            with self.assertRaises(ValueError):meshvisibility.set_hidden(self.gr,0,'MI_Old',False)
        with patch.object(meshstudio,'complete_mesh_source',side_effect=ValueError('missing streamed LODs')):
            with self.assertRaises(ValueError):meshvisibility.set_hidden(self.gr,0,'MI_Body',True)
        self.assertEqual(browse.all_imported(),[])

    def test_stage_hides_every_matching_section_in_every_lod_and_keeps_other_bytes(self):
        source=self.root/'original/SK_Body';fixture(source)
        before={ext:Path(str(source)+ext).read_bytes() for ext in ('.uasset','.uexp','.ubulk')}
        self.toggle(True)
        stage=self.root/'export'
        with patch.object(meshedit,'_resolve_base',return_value=str(source)), \
             patch('atelier.paths.pak_game_path',return_value='Marvel/Content/Marvel/'+self.gr), \
             patch.object(mesh,'Mesh',BufferMesh),patch('atelier.handlers.texture.find_extracted',return_value=str(source)):
            info=meshedit.stage_mesh(self.gr,str(stage))
        self.assertEqual(info['visibility'],[{'lod':i,'sections':2} for i in range(3)])
        result=BufferMesh(info['uasset'][:-7])
        for lod in result.lods:
            data=result._blob(lod)
            indices=struct.unpack_from('<9H',data,lod['idx_off'])
            self.assertEqual(indices,(0,0,0,3,3,3,6,7,8))
            self.assertEqual(bytes(data[lod['idx_off']+18:lod['idx_off']+64]),before['.uexp'][18:64])
        self.assertEqual(bytes(result.uasset),before['.uasset'])
        for ext,data in before.items():self.assertEqual(Path(str(source)+ext).read_bytes(),data)
        # Unhide and restage from pristine input, proving no accumulated destructive edit.
        self.toggle(False);meshreplace.add(self.gr)
        with patch.object(meshedit,'_resolve_base',return_value=str(source)), \
             patch('atelier.paths.pak_game_path',return_value='Marvel/Content/Marvel/'+self.gr):
            restored=meshedit.stage_mesh(self.gr,str(self.root/'restored'))
        for ext,data in before.items():self.assertEqual(Path(restored['uasset'][:-7]+ext).read_bytes(),data)

    def test_stage_rejects_partial_lods_without_mutating_files(self):
        source=self.root/'original/SK_Body';fixture(source)
        before=Path(str(source)+'.uexp').read_bytes()
        class Missing(BufferMesh):
            def __init__(self,base):
                super().__init__(base);self._layout.append({'blob':'missing'})
        with patch.object(mesh,'Mesh',Missing),patch('atelier.handlers.texture.find_extracted',return_value='other'):
            with self.assertRaisesRegex(ValueError,'every cooked LOD'):
                meshvisibility.apply_to_staged(self.gr,str(source)+'.uasset',[{'slot_index':0,'slot_name':'MI_Body'}])
        self.assertEqual(Path(str(source)+'.uexp').read_bytes(),before)

    def test_legacy_helper_handles_multiple_sections_for_the_same_slot(self):
        base=self.root/'fixture/SK_Body';fixture(base);model=BufferMesh(str(base))
        self.assertEqual(mesh.set_material_triangles(model,0,0),[0]*6)


if __name__=='__main__':
    unittest.main()
