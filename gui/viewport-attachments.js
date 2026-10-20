import * as THREE from 'three';
import { clone as cloneSkeleton } from 'three/addons/utils/SkeletonUtils.js';

// AtelierMesh's SharpGLTF exporter swaps Y/Z but does not conjugate rotations.
// Its inverse binds cancel that discrepancy for resting vertices, so exported
// joint positions cannot be used as physical sockets. Reconstruct the physical
// reference in metres, then carry animated deformation through the exported bind.
// This is the same basis conversion used by AtelierAnimation's version 2 tracks.
export function attachmentRig(gltf) {
  const root=gltf.scene, nodes=new Map(), reference=new Map(), physical=new Map();
  root.updateMatrixWorld(true);
  const inverseRoot=root.matrixWorld.clone().invert();
  const reflected=/SharpGLTF/i.test(gltf.parser?.json?.asset?.generator || '');
  root.traverse(node=>{
    if (!node.isBone) return;
    const local=new THREE.Matrix4().compose(node.position,reflected?node.quaternion.clone().invert():node.quaternion,node.scale);
    const parent=node.parent?.isBone ? physical.get(node.parent) : inverseRoot.clone().multiply(node.parent?.matrixWorld || root.matrixWorld);
    const p=parent.clone().multiply(local), e=inverseRoot.clone().multiply(node.matrixWorld);
    physical.set(node,p); reference.set(node,e);
    if (!nodes.has(node.name)) nodes.set(node.name,{node,physical:p,exported:e,inverseExported:e.clone().invert(),inversePhysical:p.clone().invert(),
      local:{position:node.position.clone(),quaternion:node.quaternion.clone(),scale:node.scale.clone()}});
  });
  return {root,nodes,reflected};
}

export function pairedWeapon(weapon) {
  const root=cloneSkeleton(weapon.root);
  root.position.set(0,0,0);root.quaternion.identity();root.scale.set(1,1,1);
  root.traverse(node=>{const rest=weapon.rig.nodes.get(node.name)?.local;if(node.isBone && rest){node.position.copy(rest.position);node.quaternion.copy(rest.quaternion);node.scale.copy(rest.scale);}});
  return {name:weapon.name,root,rig:attachmentRig({scene:root,parser:{json:{asset:{generator:weapon.rig.reflected?'SharpGLTF':''}}}})};
}

const weaponBone=name=>!/^root$|^pelvis$|^weapon_[lr]$|^ik_/i.test(name) && /weapon|sword|gun|blade|hammer|bow|staff|dagger|shield|pistol|spear|axe/i.test(name);
const physicalWorld=joint=>joint.node.matrixWorld.clone().multiply(joint.inverseExported).multiply(joint.physical);

export function bindWeapon(weapon, body, hand='auto') {
  const source=weapon.rig,target=body.rig;
  if (!source || !target) return null;
  const shared=[...source.nodes].filter(([name])=>weaponBone(name) && target.nodes.has(name));
  const side=hand==='left' || (hand==='auto' && /(?:^|_)(?:l|left)(?:_|$)/i.test(weapon.name)) ? 'l' : 'r';
  const socket=target.nodes.get('weapon_'+side);
  // Use the actual grip, which can be a child of the weapon root. Matching a
  // sword's origin to the hand would leave its handle offset by 20 cm on Magik.
  const grip=[...source.nodes].find(([name])=>/handle|grip/i.test(name))?.[1]
    || source.nodes.get('weapon_'+side)
    || [...source.nodes].find(([name,joint])=>weaponBone(name) && !joint.node.parent?.isBone)?.[1]
    || shared[0]?.[1]
    || [...source.nodes.values()].find(joint=>!joint.node.parent?.isBone);
  if (hand==='auto' && shared.length) {
    const targetGrip=grip && target.nodes.get(grip.node.name);
    return {body,kind:'shared',side,socket:targetGrip?socket:null,targetGrip,grip,
      joints:shared.map(([name,joint])=>({source:joint,target:target.nodes.get(name)}))};
  }
  if (!socket) return null;
  return {body,kind:'socket',side,socket,grip,inverseGrip:grip?.inversePhysical || new THREE.Matrix4()};
}

export function updateWeapon(weapon, binding) {
  const root=weapon.root;
  if (!binding) return;
  binding.body.root.updateMatrixWorld(true);
  if (binding.kind==='socket') {
    const matrix=physicalWorld(binding.socket).multiply(binding.inverseGrip);
    if (root.parent) matrix.premultiply(root.parent.matrixWorld.clone().invert());
    matrix.decompose(root.position,root.quaternion,root.scale); root.updateMatrixWorld(true);
    return;
  }
  root.position.set(0,0,0);root.quaternion.identity();root.scale.set(1,1,1);root.updateMatrixWorld(true);
  const alignment=binding.socket && binding.targetGrip ? physicalWorld(binding.socket).multiply(physicalWorld(binding.targetGrip).invert()) : new THREE.Matrix4();
  // Parents precede children in the source rig, so unmapped accessory children
  // retain their local rest offsets while matched joints follow the body.
  for (const pair of binding.joints) {
    const joint=pair.source.node;
    const world=alignment.clone().multiply(physicalWorld(pair.target)).multiply(pair.source.inversePhysical).multiply(pair.source.exported);
    const local=joint.parent.matrixWorld.clone().invert().multiply(world);
    local.decompose(joint.position,joint.quaternion,joint.scale);joint.updateMatrixWorld(true);
  }
}

// Some body meshes contain a bind-pose copy of the held weapon. Replace only
// complete material sections whose vertices are weighted to that weapon's own
// articulated bones. Shared materials on skin/armour must stay visible.
export function embeddedWeaponMaterials(body, weapons) {
  const names=new Set(weapons.flatMap(weapon=>[...weapon.rig.nodes.keys()].filter(weaponBone).map(name=>name.toLowerCase())));
  const decisions=new Map();
  body.root.traverse(object=>{
    if(!object.isSkinnedMesh || !object.skeleton)return;
    const geometry=object.geometry,skin=geometry.getAttribute('skinIndex'),weights=geometry.getAttribute('skinWeight');
    if(!skin || !weights)return;
    const materials=Array.isArray(object.material)?object.material:[object.material];
    const groups=geometry.groups.length?geometry.groups:[{start:0,count:geometry.index?.count || skin.count,materialIndex:0}];
    for(const group of groups){
      const material=materials[group.materialIndex];if(!material)continue;
      const label=material.userData?.slotName || material.name;
      if(!/weapon|sword|gun|blade|hammer|bow|staff|dagger|shield|pistol|spear|axe/i.test(label))continue;
      let duplicate=group.count>0;
      for(let offset=group.start;duplicate && offset<group.start+group.count;offset++){
        const vertex=geometry.index?geometry.index.getX(offset):offset;let covered=0,total=0;
        for(let component=0;component<4;component++){
          const weight=weights.getComponent(vertex,component),index=skin.getComponent(vertex,component);
          total+=weight;if(names.has(object.skeleton.bones[index]?.name.toLowerCase()))covered+=weight;
        }
        duplicate=total>.001 && covered/total>.999;
      }
      decisions.set(material,(decisions.get(material)??true)&&duplicate);
    }
  });
  return new Set([...decisions].filter(([,duplicate])=>duplicate).map(([material])=>material));
}
