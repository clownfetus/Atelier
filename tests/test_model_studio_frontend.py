"""Run real three.js matrix and surface regressions without a browser or decoder."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'),'Node is unavailable')
class Frontend(unittest.TestCase):
    def test_automatic_equipment_stays_with_its_body_form(self):
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function weaponMatchesBody('),end=source.indexOf('async function loadAutomaticWeapons',start);
const weapon={},banner={},hulk={},flat={},shared={};
const objects=[weapon,banner,hulk,flat,shared];
const meshMeta=[
 {game_rel:'Characters/1011/1011001/Weapons/10110/HandGun/Meshes/SK_HandGun'},
 {game_rel:'Characters/1011/1011001/Meshes/10110/SK_10110_1011001'},
 {game_rel:'Characters/1011/1011001/Meshes/10111/SK_10111_1011001'},
 {game_rel:'Characters/1011/1011001/Meshes/SK_10110_1011001'},
 {game_rel:'Characters/1011/1011001/Weapons/Shared/Meshes/SK_Weapon'}];
const environment={objects,meshMeta};vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
assert.equal(environment.weaponMatchesBody(weapon,banner),true);
assert.equal(environment.weaponMatchesBody(weapon,hulk),false,'Banner equipment must not attach to Hulk automatically');
assert.equal(environment.weaponMatchesBody(weapon,flat),true,'Flat mesh layouts retain the authored body identifier');
assert.equal(environment.weaponMatchesBody(shared,hulk),true,'A shared weapon remains available on ordinary rigs');
console.log('PASS body-form automatic equipment identity');
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'gui/viewport.js')],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_material_group_follows_body_classification_instead_of_its_folder(self):
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function materialGroup(name)'),end=source.indexOf('function filterMaterials()',start);
const caption='Characters/1022/1022504/Weapons/Caption/Meshes/SK_WP_1022504_Caption';
const shield='Characters/1022/1022504/Weapons/Shield/Meshes/SK_WP_1022504_Shield';
const environment={materialLabel:name=>name,matData:{Body:{mesh_game_rel:caption},Shield:{mesh_game_rel:shield}},
  meshMeta:[{game_rel:caption},{game_rel:shield}],objects:[{kind:'body'},{kind:'weapon'}]};
vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
assert.equal(environment.materialGroup('Body'),'Body');
assert.equal(environment.materialGroup('Shield'),'Weapon · Shield');
assert.equal(environment.materialGroup('Unmapped'),'Unmapped');
console.log('PASS body-form materials are not mislabelled as held weapons');
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'gui/viewport.js')],
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_global_base_tint_precedes_effect_colours(self):
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function pickBaseIdx(colors)');
const end=source.indexOf('// The emissive glow',start);
assert.ok(start>=0 && end>start);
const environment={};vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
const choose=names=>environment.pickBaseIdx(names.map(name=>({name})));
assert.equal(choose(['BaseTint','VenousGrowthBaseColor','VenousGrowthColor']),0);
assert.equal(choose(['VenousGrowthBaseColor','BaseTint']),1,'Order must not select the effect tint');
assert.equal(choose(['EmissiveColor','BaseColor','RimColor']),1);
assert.equal(choose(['FabricTint','SkinColor']),1,'Retain descriptive base-colour fallback');
assert.equal(choose(['EmissiveColor','FresnelTint']),-1,'Do not tint the whole surface from lighting colours');
console.log('PASS canonical base tint and effect colour selection');
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'gui/viewport.js')],
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_optional_ability_mesh_needs_explicit_selection(self):
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('function syncAttachments()');
const end=source.indexOf('// One row per top-level mesh',start);
assert.ok(start>=0 && end>start);
const body={kind:'body',loaded:true,root:{visible:true}};
const ability={kind:'weapon',loaded:true,autoEquip:false,root:{visible:false}};
const sword={kind:'weapon',loaded:true,root:{visible:false}};
const pending={kind:'weapon',loaded:false,enabled:true,root:{visible:false}};
const environment={objects:[body,ability,sword,pending],matsByName:{},embeddedWeaponMaterials:()=>[],weaponMatchesBody:()=>true,
 bindWeapon:(_weapon,body)=>({side:'r',body}),updateWeapon:()=>{}};
vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
environment.syncAttachments();
assert.equal(ability.root.visible,false,'An optional ability rig must not obscure the body on open');
assert.equal(sword.root.visible,true,'An ordinary held weapon still equips automatically');
assert.equal(pending.root.visible,false,'An unloaded attachment must not reserve a hand or access an absent rig');
ability.enabled=true;environment.syncAttachments();
assert.equal(ability.root.visible,true,'Explicit selection must make the optional effect available');
assert.equal(sword.root.visible,false,'An explicitly selected rig reserves its hand');
ability.enabled=false;environment.syncAttachments();
assert.equal(ability.root.visible,false);assert.equal(sword.root.visible,true);
body.root.visible=false;environment.syncAttachments();
assert.equal(ability.root.visible,false);assert.equal(sword.root.visible,false);
console.log('PASS optional ability selection and ordinary held weapon defaults');
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'gui/viewport.js')],
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_display_copy_rebuilds_when_late_maps_change_shader_variant(self):
        with tempfile.TemporaryDirectory(prefix='atelier-studio-three-') as folder:
            folder=Path(folder)
            vendor=(ROOT/'gui/vendor/three').as_uri()
            loader=folder/'loader.mjs'
            loader.write_text("export async function resolve(name,context,next){if(name==='three')return {url:"+json.dumps(vendor+'/three.module.min.js')+",shortCircuit:true};return next(name,context);}",encoding='utf-8')
            script=folder/'checks.mjs'
            script.write_text(r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from 'three';
const source=fs.readFileSync(process.argv[2],'utf8');
const start=source.indexOf('const variantSlots='),end=source.indexOf('// Showcase honours View settings',start);
assert.ok(start>=0 && end>start);
const displayMaterial=new Function('THREE','originals','overlays','variants','toonGradient','effects',
  "let lighting='studio',regions=false,wireframe=false;"+source.slice(start,end)+';return displayMaterial;')(
  THREE,new Map(),new Map(),new Map(),null,{tint:()=>{}});
// Venom's parts carry a white emissive colour masked by a black emissive texture that loads late.
const part=new THREE.MeshStandardMaterial();part.emissive.set(0xffffff);part.emissiveIntensity=1.2;
let shown=displayMaterial(part,false,false);const compiled=shown.version;
assert.equal(displayMaterial(part,false,false).version,compiled,'An unchanged part keeps its compiled shader');
part.emissiveMap=new THREE.Texture();part.needsUpdate=true;
shown=displayMaterial(part,false,false);
assert.equal(shown.emissiveMap,part.emissiveMap);
assert.ok(shown.version>compiled,'A late emissive mask must rebuild the Inspect display shader');
const masked=shown.version;part.side=THREE.DoubleSide;
assert.ok(displayMaterial(part,false,false).version>masked,'Side selects a shader variant');
const card=new THREE.MeshStandardMaterial();let toon=displayMaterial(card,false,true,true);const toonCompiled=toon.version;
card.normalMap=new THREE.Texture();toon=displayMaterial(card,false,true,true);
assert.equal(toon.normalMap,card.normalMap);assert.ok(toon.version>toonCompiled,'The Showcase copy follows the same rule');
console.log('PASS display copies rebuild for late maps and surface variants');
''',encoding='utf-8')
            result=subprocess.run([shutil.which('node'),'--no-warnings','--experimental-loader',loader.as_uri(),str(script),str(ROOT/'gui/viewport-inspection.js')],
                                  capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_blender_export_requires_one_visible_body_and_uses_visible_weapons(self):
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const start=source.indexOf('async function editInBlender()');
const end=source.indexOf('// Sidebar shows',start);
assert.ok(start>=0 && end>start);
const objects=[
 {kind:'body',root:{visible:false}},
 {kind:'body',root:{visible:false}},
 {kind:'weapon',root:{visible:true},hand:'both'},
 {kind:'weapon',root:{visible:false},hand:'left'},
];
const meshMeta=['HiddenBody','SelectedBody','VisibleWeapon','HiddenWeapon'].map(name=>({game_rel:'Fixture/'+name}));
const requests=[],notes=[];
const environment={objects,meshMeta,generation:1,viewportProject:'Originating project',
 canLeave:async()=>true,note:(message)=>notes.push(message),refreshBlenderBtn:()=>{},$:()=>({disabled:false}),
 window:{AtelierJobs:{run:async(path,request)=>{
  requests.push({path,project:request.project,payload:JSON.parse(request.body)});
  return {ok:false,error:'Fixture stops before any native export'};
 }}}};
vm.createContext(environment);vm.runInContext(source.slice(start,end),environment);
(async()=>{
 await environment.editInBlender();
 assert.equal(requests.length,0,'A weapon-only or empty view must not export an invisible body');
 assert.ok(notes.at(-1).includes('Show one body form'));
 objects[0].root.visible=objects[1].root.visible=true;
 await environment.editInBlender();
 assert.equal(requests.length,0,'Multiple body forms must be resolved before export');
 assert.ok(notes.at(-1).includes('Choose one body form'));
 objects[0].root.visible=false;
 await environment.editInBlender();
 assert.deepEqual(requests,[{path:'/api/model_blender_export',project:'Originating project',payload:{
  game_rel:'Fixture/SelectedBody',weapons:[{game_rel:'Fixture/VisibleWeapon',hand:'both'}]}}]);
 environment.canLeave=async()=>false;
 await environment.editInBlender();
 assert.equal(requests.length,1,'Declining the pending-edits confirmation must not export');
 console.log('PASS Blender export selection, visible held weapons and pending-edit cancellation');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'gui/viewport.js')],
                              capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

    def test_physical_sockets_shared_bones_dual_clones_and_surface_modes(self):
        with tempfile.TemporaryDirectory(prefix='atelier-studio-three-') as folder:
            folder=Path(folder)
            vendor=(ROOT/'gui/vendor/three').as_uri()
            loader=folder/'loader.mjs'
            loader.write_text("export async function resolve(name,context,next){if(name==='three')return {url:"+json.dumps(vendor+'/three.module.min.js')+",shortCircuit:true};if(name.startsWith('three/addons/'))return {url:"+json.dumps(vendor+'/jsm/')+"+name.slice(13),shortCircuit:true};return next(name,context);}",encoding='utf-8')
            script=folder/'checks.mjs'
            source=r'''
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {attachmentRig,bindWeapon,updateWeapon,pairedWeapon,embeddedWeaponMaterials,weaponSide} from 'ATTACHMENT';
import {applySurface,textureRoles,emissiveColorIndex,applyEmissive} from 'SURFACE';
const near=(actual,expected)=>assert.ok(actual.distanceTo(new THREE.Vector3(...expected))<1e-8,`${actual.toArray()} != ${expected}`);
function rig(name,reflected=true){
 const scene=new THREE.Group(),root=new THREE.Bone(),socket=new THREE.Bone();root.name='root';socket.name=name;
 root.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),Math.PI/2);socket.position.set(1,0,0);
 scene.add(root);root.add(socket);scene.updateMatrixWorld(true);
 return {root:scene,rig:attachmentRig({scene,parser:{json:{asset:{generator:reflected?'SharpGLTF 1':'Atelier Python'}}}}),socket};
}
const body=rig('weapon_r'),weapon=rig('grip');
assert.equal(weaponSide('SK_WP_CannonL'),'l');assert.equal(weaponSide('SK_WP_CannonR'),'r');
assert.equal(weaponSide('SK_WP_LauncherL'),'l');assert.equal(weaponSide('SK_WP_Stick_L_Anim'),'l');
assert.equal(weaponSide('SK_WP_Railgun'),'r');assert.equal(weaponSide('SK_WP_CannonL','right'),'r');
// SharpGLTF's visible bind is upright even though raw joint positions are reflected.
near(new THREE.Vector3().setFromMatrixPosition(body.socket.matrixWorld),[0,1,0]);
near(new THREE.Vector3().setFromMatrixPosition(body.rig.nodes.get('weapon_r').physical),[0,-1,0]);
near(new THREE.Vector3().setFromMatrixPosition(rig('weapon_r',false).rig.nodes.get('weapon_r').physical),[0,1,0]);
const rootOnly=new THREE.Group(),grip=new THREE.Bone();grip.name='root';grip.position.set(.25,0,0);rootOnly.add(grip);
const held={root:rootOnly,rig:attachmentRig({scene:rootOnly}),name:'SK_Gun'};
let binding=bindWeapon(held,body,'right');assert.equal(binding.kind,'socket');updateWeapon(held,binding);
near(new THREE.Vector3(.25,0,0).applyMatrix4(held.root.matrixWorld),[0,-1,0]);
// A world translation of an animated exported rig carries the physical socket by that same delta.
body.root.position.set(0,2,0);updateWeapon(held,binding);
near(new THREE.Vector3(.25,0,0).applyMatrix4(held.root.matrixWorld),[0,1,0]);
assert.equal(bindWeapon(held,body,'left'),null);
for(const name of ['CannonRoot','WandRoot','TridentRoot','NunchakuRoot']){
 const familyRoot=new THREE.Group(),wrapper=new THREE.Bone(),joint=new THREE.Bone();
 wrapper.name='WP_Root';joint.name=name;joint.position.set(.1,0,0);familyRoot.add(wrapper);wrapper.add(joint);
 const family={name:'SK_'+name,root:familyRoot,rig:attachmentRig({scene:familyRoot})};
 assert.equal(bindWeapon(family,body,'right').grip.node,joint,`${name} must not attach its generic wrapper`);
}
const alignedRoot=new THREE.Group(),align=new THREE.Bone(),cannon=new THREE.Bone();
align.name='Align';cannon.name='Hand_l_Cannon1';cannon.quaternion.setFromAxisAngle(new THREE.Vector3(1,0,0),Math.PI);
alignedRoot.add(align);align.add(cannon);
const aligned={name:'SK_CannonL',root:alignedRoot,rig:attachmentRig({scene:alignedRoot})};
assert.equal(bindWeapon(aligned,body,'right').grip.node,align,'An authored alignment node takes precedence over a deforming cannon joint');
const wrist=new THREE.Bone();wrist.name='hand_r';wrist.position.set(.2,0,0);body.root.children[0].add(wrist);
body.rig=attachmentRig({scene:body.root,parser:{json:{asset:{generator:'SharpGLTF'}}}});
const wristBinding=bindWeapon(aligned,body,'right');
assert.equal(wristBinding.socket.node,wrist,'A hand-mounted cannon uses the wrist rather than the palm weapon socket');
// A wrapper root is not necessarily the authored grip. An inverted blade
// joint below it must align to the socket instead of retaining the half-turn.
const wrapped=new THREE.Group(),wrapper=new THREE.Bone(),blade=new THREE.Bone();
wrapper.name='WP_Root';blade.name='WP_Sword';blade.position.set(.02,0,0);
blade.quaternion.setFromAxisAngle(new THREE.Vector3(1,0,0),Math.PI);
wrapped.add(wrapper);wrapper.add(blade);
const dagger={name:'SK_Dagger',root:wrapped,rig:attachmentRig({scene:wrapped})};
const daggerBinding=bindWeapon(dagger,body,'right');
assert.equal(daggerBinding.grip.node,blade,'The articulated blade is the grip below the wrapper');
updateWeapon(dagger,daggerBinding);
const bladePhysical=blade.matrixWorld.clone().multiply(daggerBinding.grip.inverseExported).multiply(daggerBinding.grip.physical);
const socketPhysical=body.rig.nodes.get('weapon_r').node.matrixWorld.clone()
 .multiply(body.rig.nodes.get('weapon_r').inverseExported).multiply(body.rig.nodes.get('weapon_r').physical);
assert.ok(bladePhysical.elements.every((value,i)=>Math.abs(value-socketPhysical.elements[i])<1e-8),
 'Grip position and orientation must both match the socket');
const sharedBody=rig('SwordRoot'),sharedWeapon=rig('SwordRoot');
binding=bindWeapon(sharedWeapon,sharedBody);assert.equal(binding.kind,'shared');
sharedBody.root.position.set(3,0,0);updateWeapon(sharedWeapon,binding);
near(new THREE.Vector3().setFromMatrixPosition(sharedWeapon.socket.matrixWorld),[3,1,0]);
const handSocket=new THREE.Bone();handSocket.name='weapon_r';handSocket.position.set(-2,0,0);
sharedBody.root.children[0].add(handSocket);
sharedBody.rig=attachmentRig({scene:sharedBody.root,parser:{json:{asset:{generator:'SharpGLTF'}}}});
binding=bindWeapon(sharedWeapon,sharedBody);updateWeapon(sharedWeapon,binding);
// Matching sword bones must still put the physical grip in the actual hand.
const sourceGrip=sharedWeapon.rig.nodes.get('SwordRoot');
const gripWorld=sourceGrip.node.matrixWorld.clone().multiply(sourceGrip.inverseExported).multiply(sourceGrip.physical);
const targetSocket=sharedBody.rig.nodes.get('weapon_r');
const socketWorld=targetSocket.node.matrixWorld.clone().multiply(targetSocket.inverseExported).multiply(targetSocket.physical);
assert.ok(new THREE.Vector3().setFromMatrixPosition(gripWorld).distanceTo(new THREE.Vector3().setFromMatrixPosition(socketWorld))<1e-8);
const twin=pairedWeapon(sharedWeapon);assert.notEqual(twin.rig.nodes.get('SwordRoot').node,sharedWeapon.socket);
assert.equal(twin.rig.nodes.size,sharedWeapon.rig.nodes.size);
near(twin.rig.nodes.get('SwordRoot').node.position,[1,0,0]);
// Changing attachment modes must not apply a socket transform on top of the
// pose already written by shared-rig alignment.
for(const hand of ['right','auto','right']){
 binding=bindWeapon(sharedWeapon,sharedBody,hand);updateWeapon(sharedWeapon,binding);
 const actual=sourceGrip.node.matrixWorld.clone().multiply(sourceGrip.inverseExported).multiply(sourceGrip.physical);
 assert.ok(new THREE.Vector3().setFromMatrixPosition(actual).distanceTo(new THREE.Vector3().setFromMatrixPosition(socketWorld))<1e-8);
}
const material=new THREE.MeshStandardMaterial();
applySurface(material,{surface:{blend_mode:'BLEND_Translucent',opacity:.8,two_sided:true}});
assert.equal(material.transparent,true);assert.equal(material.opacity,.8);assert.equal(material.side,THREE.DoubleSide);assert.equal(material.depthWrite,false);
applySurface(material,{surface:{blend_mode:'BLEND_Masked',opacity:1,mask_clip:.2}});
assert.equal(material.alphaTest,.2);assert.equal(material.transparent,false);
assert.deepEqual(textureRoles({textures:{DiffuseMap:'gem',OpacityMask:'hair'}}),{basecolor:'gem',opacity:'hair'});
const skin={colors:[{name:'BaseGlowColor',rgba:[1,1,1,0]},{name:'EmissiveColor',rgba:[1,.02,.02,0]}],
 scalars:[{name:'GlowStrength',value:8},{name:'EmissiveStrength',value:0}]};
assert.equal(emissiveColorIndex(skin.colors),1,'A separate white base glow must not tint the emissive mask');
assert.equal(emissiveColorIndex(null),-1);
material.emissiveMap=new THREE.Texture();applyEmissive(material,skin);
assert.equal(material.emissiveIntensity,0,'Disabled tattoos must not glow');
assert.deepEqual(material.emissive.toArray(),[1,.02,.02]);
skin.scalars[1].value=.038;applyEmissive(material,skin);
assert.equal(material.emissiveIntensity,.038,'Small authored emission must not be raised to a brightness floor');
skin.scalars[1].value=9;applyEmissive(material,skin,[.1,.2,.3]);
assert.equal(material.emissiveIntensity,9);assert.deepEqual(material.emissive.toArray(),[.1,.2,.3]);
skin.scalars[1].value=-1;applyEmissive(material,skin);assert.equal(material.emissiveIntensity,0);
material.emissiveMap=null;applyEmissive(material,skin);
assert.deepEqual(material.emissive.toArray(),[0,0,0],'Removing an emissive map must clear its previous glow');
const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(new Array(18).fill(0),3));
geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([1,0,0,0,1,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],4));
geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],4));
geometry.setIndex([0,1,2,3,4,5]);geometry.addGroup(0,3,0);geometry.addGroup(3,3,1);
const swordMat=new THREE.MeshStandardMaterial(),armourMat=new THREE.MeshStandardMaterial();swordMat.name='MI_Weapon';armourMat.name='MI_WeaponTrim';
const embedded=new THREE.SkinnedMesh(geometry,[swordMat,armourMat]);embedded.skeleton=new THREE.Skeleton([sharedBody.rig.nodes.get('root').node,sharedBody.rig.nodes.get('SwordRoot').node]);
sharedBody.root.add(embedded);
assert.deepEqual([...embeddedWeaponMaterials(sharedBody,[sharedWeapon])],[swordMat]);
geometry.groups[1].materialIndex=0;assert.equal(embeddedWeaponMaterials(sharedBody,[sharedWeapon]).size,0);
console.log('PASS physical reference, animated socket, shared rig, independent dual clone, translucent and masked materials');
'''
            source=source.replace('ATTACHMENT',(ROOT/'gui/viewport-attachments.js').as_uri()).replace('SURFACE',(ROOT/'gui/viewport-materials.js').as_uri())
            script.write_text(source,encoding='utf-8')
            result=subprocess.run([shutil.which('node'),'--no-warnings','--experimental-loader',loader.as_uri(),str(script)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


if __name__=='__main__':unittest.main()
