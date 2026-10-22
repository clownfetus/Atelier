"""Generated-geometry native probe, run with Blender --background --factory-startup.

Usage: blender --background --factory-startup --python tests/native_blender_bridge.py -- ROOT REPORT.json
No game files, user projects or installed add-ons are used.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import zipfile

import bpy
import bmesh
from mathutils import Matrix

root, report = map(Path, sys.argv[sys.argv.index('--') + 1:])
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'atelier/blender'))
from import_geometry import bake_geometry
from atelier.blender_extension import archive_bytes

report.parent.mkdir(parents=True, exist_ok=True)
checks = []
with tempfile.TemporaryDirectory(prefix='atelier-native-bridge-', dir=report.parent) as temporary:
    work = Path(temporary)
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.name = 'Generated geometry fixture'
    cube.matrix_world = Matrix.Diagonal((-1.0, 1.5, 2.0, 1.0))
    bevel = cube.modifiers.new('Preserved bevel', 'BEVEL'); bevel.width = .15
    bpy.context.view_layer.update()
    evaluated = cube.evaluated_get(bpy.context.evaluated_depsgraph_get())
    expected_faces = len(evaluated.data.polygons)
    expected_vertices = sorted(tuple(round(v, 5) for v in cube.matrix_world @ point.co) for point in evaluated.data.vertices)
    result = bake_geometry(cube)
    assert result['baked_modifiers'] == ['Preserved bevel']
    assert result['mirrored_winding_corrected'] and result['output_faces'] == expected_faces > 6
    assert sorted(tuple(round(v, 5) for v in point.co) for point in cube.data.vertices) == expected_vertices
    bm = bmesh.new(); bm.from_mesh(cube.data)
    assert bm.calc_volume(signed=True) > 0; bm.free()
    checks.append({'name': 'visible bevel geometry and mirrored outward winding retained', 'faces': expected_faces})
    cube.matrix_world = Matrix.Diagonal((0.0, 1.0, 1.0, 1.0))
    try: bake_geometry(cube)
    except ValueError: pass
    else: raise AssertionError('Singular scale was accepted')
    cube.matrix_world = Matrix.Identity(4)
    checks.append({'name': 'singular replacement scale rejected'})

    package = work/'extension'; package.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive_bytes(root))) as archive: archive.extractall(package)
    spec = importlib.util.spec_from_file_location('atelier_bridge_fixture', package/'__init__.py', submodule_search_locations=[str(package)])
    addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
    spool = work/'spool'; spool.mkdir()
    addon.bridge_root = lambda: spool
    addon._RUNNING = True; addon._SESSION = 'a'*32
    job='b'*32; stage=spool/'staging'/job; stage.mkdir(parents=True)
    bpy.ops.object.select_all(action='DESELECT'); cube.select_set(True); bpy.context.view_layer.objects.active=cube
    bpy.ops.export_scene.gltf(filepath=str(stage/'model.glb'),export_format='GLB',use_selection=True)
    (stage/'materials.json').write_text(json.dumps({'slots':{}}))
    request={'protocol':addon.PROTOCOL,'job':job,'receiver':addon._SESSION,'expires':time.time()+120,
             'parts':[{'glb':str(stage/'model.glb'),'materials':str(stage/'materials.json'),
                       'name':'Received fixture','transform':[list(row) for row in Matrix.Identity(4)]}]}
    addon._atomic_json(spool/'requests'/(job+'.json'),request)
    before=set(bpy.data.objects);addon.tick()
    receipt=json.loads((spool/'receipts'/(job+'.json')).read_text())
    assert receipt['ok'] and receipt['meshes']==1 and receipt['receiver']==addon._SESSION,receipt
    assert cube in bpy.data.objects.values() and len(set(bpy.data.objects)-before)==1
    assert not stage.exists()
    checks.append({'name':'packaged extension imports staged GLB into existing scene and acknowledges', 'meshes':receipt['meshes']})
    destination=work/'result.blend';bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    bpy.ops.wm.open_mainfile(filepath=str(destination))
    assert len([obj for obj in bpy.data.objects if obj.type=='MESH'])==2
    checks.append({'name':'saved and reopened Blender scene preserves original and received meshes'})
report.write_text(json.dumps({'ok':True,'blender':bpy.app.version_string,'checks':checks},indent=2)+'\n')
print('ATELIER_BRIDGE_NATIVE_OK',report)
