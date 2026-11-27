import * as THREE from 'three';
import { physicalWorld } from './viewport-attachments.js';

const rad = Math.PI / 180;
const fromUnreal = ([x, y, z]) => new THREE.Vector3(x, z, y).multiplyScalar(0.01);
const toUnreal = vector => [vector.x * 100, vector.z * 100, vector.y * 100];

function fromRotator([pitch, yaw, roll]) {
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-roll * rad, -pitch * rad, yaw * rad, 'ZYX'));
  return new THREE.Quaternion(-q.x, -q.z, -q.y, q.w);
}

function toRotator(q) {
  const e = new THREE.Euler().setFromQuaternion(new THREE.Quaternion(-q.x, -q.z, -q.y, q.w), 'ZYX');
  return [-e.y / rad, e.z / rad, -e.x / rad];
}

export function attachmentPoint(joint, location) {
  return fromUnreal(location).applyMatrix4(physicalWorld(joint));
}

export function mirroredPlacement(rig, bone, original) {
  const otherSide = bone.replace(/(?:^[lr]_|_[lr](?=_|$))/gi, match => (
    match.replace(/[lr]/i, side => ({l: 'r', r: 'l', L: 'R', R: 'L'})[side])
  ));
  const source = rig.nodes.get(bone);
  const targetName = [...rig.nodes.keys()].find(name => name.toLowerCase() === otherSide.toLowerCase()) || bone;
  const target = rig.nodes.get(targetName);
  const inverseRoot = rig.root.matrixWorld.clone().invert();
  const from = inverseRoot.clone().multiply(physicalWorld(source));
  const to = inverseRoot.multiply(physicalWorld(target));
  const clean = values => values.map(value => Number(value.toFixed(5)));

  // VFX Lab reflects the placement across component X and resolves it back
  // into the other socket's axes. Zero offsets and rotations stay zero.
  const point = fromUnreal(original.location).applyMatrix4(from);
  point.x *= -1;
  const location = original.location.some(Boolean)
    ? clean(toUnreal(point.applyMatrix4(to.clone().invert()))) : original.location;

  const worldRotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().extractRotation(from))
    .multiply(fromRotator(original.rotation));
  const forward = new THREE.Vector3(1, 0, 0).applyQuaternion(worldRotation);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(worldRotation);
  forward.x *= -1;
  up.x *= -1;
  const mirror = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
    forward, up, new THREE.Vector3().crossVectors(forward, up),
  ));
  const toRotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().extractRotation(to));
  const rotation = original.rotation.some(Boolean)
    ? clean(toRotator(toRotation.invert().multiply(mirror))) : original.rotation;
  return {bone: targetName, location, rotation};
}
