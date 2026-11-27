"""Skin VFX Lab file compatibility checks against the frontend codec."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is unavailable')
class SkinVfxFrontend(unittest.TestCase):
    def test_vfx_lab_document_round_trips(self):
        script = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const {decodeSetup, encodeSetup, niagaraSystemPath, indexedNiagaraPath,
       skinVfxTarget, setupFilename, ENTRY_LIMIT, ALL_FORMS} = await import(pathToFileURL(process.argv[1]));

const system = '/Game/Marvel/VFX/Particles/Characters/1031/1031313/NS_1031313_BodyStar_01';
const mesh = '/Game/Marvel/ProjectGalacta/Meshes/1031/1031313/NightStars/SK_1031_1031313';
const fixture = {
  VFXName: 'Night stars',
  TargetHeroID: 1031,
  TargetSkinID: 1031313,
  TargetMesh: mesh + '.SK_1031_1031313',
  Entries: [
    {EntryName: 'Left shoulder', System: system + '.NS_1031313_BodyStar_01', Bone: 'clavicle_l',
     Location: 'X=-12.500 Y=0.000 Z=8.250', Rotation: 'P=20.000 Y=-45.000 R=0.000',
     Scale: 'X=1.500 Y=1.000 Z=0.750', Loop: true, Form: -1},
    {EntryName: 'Chest', System: system + '.NS_1031313_BodyStar_01', Bone: 'spine_03',
     Location: 'X=0 Y=0 Z=0', Rotation: 'P=0 Y=0 R=180', Scale: 'X=1 Y=1 Z=1', Loop: false, Form: 1},
  ],
};

const target = skinVfxTarget('Characters/1031/1031313/Meshes/SK_10311_1031313');
assert.deepEqual(target, {hero: 1031, skin: 1031313, form: 1});
assert.deepEqual(skinVfxTarget('Characters/1031/1031313/Meshes/SK_1031_1031313'), {...target, form: 0});
assert.equal(skinVfxTarget('Characters/1031/1000000/Meshes/SK_1031_1000000'), null);
assert.equal(skinVfxTarget('Characters/1031/1031313/Meshes/SM_Pedestal'), null);

const source = JSON.stringify(fixture);
const utf16 = Buffer.from('\uFEFF' + source, 'utf16le');
const edit = decodeSetup(utf16, target);
assert.equal(edit.entries[0].form, ALL_FORMS);
assert.deepEqual(edit.entries[0].location, [-12.5, 0, 8.25]);
assert.deepEqual(edit.entries[0].rotation, [20, -45, 0]);
assert.deepEqual(edit.entries[0].scale, [1.5, 1, 0.75]);
assert.equal(edit.entries[1].loop, false);
assert.equal(edit.entries[1].form, 1);
const output = JSON.parse(encodeSetup(edit));
assert.deepEqual({...output, Entries: [fixture.Entries[0], output.Entries[1]]},
                 {...fixture, Entries: [fixture.Entries[0], output.Entries[1]]});
assert.equal(output.Entries[0].Location, 'X=-12.5 Y=0 Z=8.25');
assert.equal(output.Entries[0].Rotation, 'P=20 Y=-45 R=0');
assert.equal(output.Entries[0].Scale, 'X=1.5 Y=1 Z=0.75');
assert.deepEqual(decodeSetup(new TextEncoder().encode(encodeSetup(edit)), target), edit);
assert.equal(setupFilename('Night stars'), 'GalactaVFX_Night stars.json');
assert.equal(setupFilename('Night / stars?').includes('/'), false);

assert.equal(niagaraSystemPath(system + '.20'), fixture.Entries[0].System);
assert.equal(niagaraSystemPath("NiagaraSystem'" + system + "'"), fixture.Entries[0].System);
assert.equal(niagaraSystemPath('/Game/Marvel/../NS_Effect'), '');
assert.equal(niagaraSystemPath('/Game/Marvel/VFX/Foo.Bar'), '/Game/Marvel/VFX/Foo.Bar');
assert.equal(indexedNiagaraPath({type: 'vfx', game_rel: system.replace('/Game/Marvel/', '')}), fixture.Entries[0].System);
assert.equal(indexedNiagaraPath({type: 'vfx', game_rel: 'VFX/NE_Emitter'}), '');
assert.equal(indexedNiagaraPath({type: 'mesh', game_rel: 'VFX/NS_Effect'}), '');

const withSource = (change, expected) => {
  const invalid = structuredClone(fixture);
  change(invalid);
  assert.throws(() => decodeSetup(new TextEncoder().encode(JSON.stringify(invalid)), target), expected);
};
withSource(s => { s.TargetSkinID = 1031999; }, /Open costume 1031999/);
withSource(s => { s.TargetMesh = mesh.replaceAll('1031313', '1031999'); }, /this costume/);
withSource(s => { s.Entries[0].Rotation = 'P=NaN Y=0 R=0'; }, /rotation/);
withSource(s => { s.Entries[1].EntryName = 'left shoulder'; }, /unique name/);
withSource(s => { s.Entries = Array.from({length: ENTRY_LIMIT + 1}, () => s.Entries[0]); }, /up to 16/);
withSource(s => { s.Entries = []; }, /at least one effect/);
withSource(s => { s.Entries[1].Form = -2; }, /form/);
withSource(s => { s.Entries[1].Loop = 'false'; }, /loop/);
assert.throws(() => decodeSetup(new Uint8Array([0xff, 0x00, 0xf8]), target), /valid Galacta VFX Lab JSON/);
const plain = structuredClone(edit);
plain.targetMesh = '';
plain.entries[0].location[0] = 1e-7;
assert.equal(JSON.parse(encodeSetup(plain)).TargetMesh, '');
assert.match(JSON.parse(encodeSetup(plain)).Entries[0].Location, /^X=0\.0000001 /);
plain.entries[0].location[0] = Number.POSITIVE_INFINITY;
assert.throws(() => encodeSetup(plain), /offset/);
'''
        result = subprocess.run(
            [shutil.which('node'), '--input-type=module', '-e', script, str(ROOT / 'gui/skin-vfx-data.js')],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
