"""Blender add-on: staged Atelier scenes import on Blender's MAIN thread.

No server, arbitrary-script execution, network calls or game file writes.
Install this directory as a Blender extension, enable it, and leave Blender open.
"""
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
import shutil

import bpy
from mathutils import Matrix
from .tracking import strip_tracking, restore_tracking
from .material_nodes import wire_material
from .safety import PROTOCOL, identity, validate_request

bl_info = {
    'name': 'Atelier Live Bridge', 'author': 'Atelier contributors',
    'version': (0, 1, 0), 'blender': (4, 2, 0), 'category': 'Import-Export',
    'description': 'Receive staged GLB models and their material parameters from Atelier',
}

_RUNNING = False
_SESSION = None


def bridge_root():
    if os.name == 'nt':
        parent = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    else:
        parent = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
    return parent / 'Atelier' / 'BlenderBridge'


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    stage.write_text(json.dumps(value), encoding='utf-8')
    os.replace(stage, path)


def _wire_materials(created, path, staging):
    """Use Atelier's existing typed material renderer, with confined image inputs."""
    material_data = json.loads(Path(path).read_text(encoding='utf-8'))
    slots = material_data.get('slots', {})
    errors, images = [], []
    for obj in created:
        if obj.type != 'MESH':
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            name = material.name
            original_name = name.rsplit('.', 1)[0] if name.rsplit('.', 1)[-1].isdigit() else name
            row = slots.get(name) or slots.get(original_name)
            if row is None:
                errors.append(name + ': no matching material manifest entry')
                continue
            allowed_maps = []
            for tex in row.get('maps', []):
                filename = tex.get('path')
                if not filename or not Path(filename).is_file() or not Path(filename).resolve().is_relative_to(staging):
                    errors.append(f"{name}: unavailable texture {tex.get('param')}")
                    continue
                allowed_maps.append(tex)
            before_images = set(bpy.data.images)
            try:
                wire_material(material, {**row, 'maps': allowed_maps})
            except Exception as error:
                errors.append(name + ': material graph could not be built: ' + str(error))
                continue
            images.extend(set(bpy.data.images) - before_images)
    return errors, images


def receive(request, root):
    parts = validate_request(request, root, _SESSION)
    before = set(bpy.data.objects)
    added = []
    created_collections = []
    warning = []
    source_staging = (root / 'staging' / request['job']).resolve()
    rotation = Matrix.Rotation(1.5707963267948966, 4, 'X')
    try:
        for idx, part in enumerate(parts):
            # glTF import operates on the current Blender scene, no headless restart.
            prepared_path, tracking = strip_tracking(part['glb'])
            try:
                bpy.ops.import_scene.gltf(filepath=prepared_path)
            finally:
                if prepared_path != part['glb']:
                    Path(prepared_path).unlink(missing_ok=True)
            created = set(bpy.data.objects) - before
            fresh = list(created - set(added))
            if tracking is not None:
                for obj in fresh:
                    if obj.type == 'MESH':restore_tracking(obj.data, tracking)
            if not fresh or not any(obj.type == 'MESH' for obj in fresh):
                raise RuntimeError('Imported GLB contained no usable mesh')
            collection = bpy.data.collections.new(str(part.get('name') or 'Atelier part')[:100])
            created_collections.append(collection)
            bpy.context.scene.collection.children.link(collection)
            for obj in fresh:
                for old_collection in list(obj.users_collection): old_collection.objects.unlink(obj)
                collection.objects.link(obj)
                obj['atelier_game_rel'] = part.get('game_rel', '')
            matrix = rotation @ Matrix(part['transform']) @ rotation.inverted()
            for obj in fresh:
                if obj.parent is None: obj.matrix_world = matrix @ obj.matrix_world
            issues, images = _wire_materials(fresh, part['materials'], source_staging)
            warning.extend(issues)
            for image in images:
                if not image.packed_file:
                    image.pack()  # images survive deletion of temporary staging files
            added.extend(fresh)
        for obj in added:
            obj.select_set(False)
        for obj in added:
            if obj.type == 'MESH':obj.select_set(True)
        mesh_count = sum(obj.type == 'MESH' for obj in added)
        return {'meshes': mesh_count, 'warnings': warning[:24],
                'note': 'Imported into the open Blender scene. Save the Blender file to keep your edits.'}
    except Exception:
        # Roll back only objects added by this request; existing user scene remains.
        for obj in set(bpy.data.objects) - before:
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection in created_collections:
            bpy.data.collections.remove(collection)
        raise


def tick():
    if not _RUNNING:
        return None
    root = bridge_root()
    try:
        # Only the advertised session accepts jobs. Another enabled Blender
        # waits while that session is active; requests are bound to its identity.
        try:
            active = json.loads((root / 'receiver.json').read_text())
        except (OSError, ValueError):
            active = {}
        if active.get('receiver') != _SESSION and abs(time.time() - active.get('time', 0)) < 8:
            return .5
        _atomic_json(root / 'receiver.json', {'protocol': PROTOCOL, 'time': time.time(),
                                              'receiver': _SESSION, 'blender': bpy.app.version_string})
        for path in sorted((root / 'requests').glob('*.json'))[:1]:
            if not identity(path.stem):
                continue
            # Atomic claim: two open Blender instances must not import the same request.
            claimed = path.with_suffix('.processing')
            try:
                os.replace(path, claimed)
            except FileNotFoundError:
                continue
            try:
                request = json.loads(claimed.read_text(encoding='utf-8'))
                if request.get('job') != path.stem:
                    raise ValueError('Request filename and job identity differ')
                result = receive(request, root)
                receipt = {'protocol': PROTOCOL, 'job': request['job'], 'receiver': _SESSION, 'ok': True, **result}
            except Exception as error:
                receipt = {'protocol': PROTOCOL, 'job': path.stem, 'receiver': _SESSION, 'ok': False,
                           'error': str(error)}
                print('[Atelier Live Bridge]', error, file=sys.stderr)
            _atomic_json(root / 'receipts' / (path.stem + '.json'), receipt)
            claimed.unlink(missing_ok=True)
            stage = root / 'staging' / path.stem
            if stage.exists() and stage.resolve().parent == (root.resolve() / 'staging'):
                shutil.rmtree(stage)
    except Exception as error:
        print('[Atelier Live Bridge] poll error:', error, file=sys.stderr)
    return .5


def register():
    global _RUNNING, _SESSION
    _SESSION = uuid.uuid4().hex
    _RUNNING = True
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.5, persistent=True)


def unregister():
    global _RUNNING
    _RUNNING = False
    if bpy.app.timers.is_registered(tick): bpy.app.timers.unregister(tick)
    try:
        path = bridge_root() / 'receiver.json'
        if json.loads(path.read_text()).get('receiver') == _SESSION:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
