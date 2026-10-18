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
import {attachmentRig,bindWeapon,updateWeapon,pairedWeapon,embeddedWeaponMaterials} from 'ATTACHMENT';
import {applySurface,textureRoles} from 'SURFACE';
const near=(actual,expected)=>assert.ok(actual.distanceTo(new THREE.Vector3(...expected))<1e-8,`${actual.toArray()} != ${expected}`);
function rig(name,reflected=true){
 const scene=new THREE.Group(),root=new THREE.Bone(),socket=new THREE.Bone();root.name='root';socket.name=name;
 root.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),Math.PI/2);socket.position.set(1,0,0);
 scene.add(root);root.add(socket);scene.updateMatrixWorld(true);
 return {root:scene,rig:attachmentRig({scene,parser:{json:{asset:{generator:reflected?'SharpGLTF 1':'Atelier Python'}}}}),socket};
}
const body=rig('weapon_r'),weapon=rig('grip');
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
