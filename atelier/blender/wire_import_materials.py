"""Connect a validated uploaded material bundle to its saved replacement scene."""
import json
import os
import sys

import bpy

sys.path.insert(0,os.path.dirname(__file__))
from material_nodes import wire_material

scene,manifest=sys.argv[sys.argv.index('--')+1:][:2]
with open(manifest,encoding='utf-8') as stream:slots=json.load(stream)['slots']
bpy.ops.wm.open_mainfile(filepath=scene,load_ui=False,use_scripts=False)
mesh=bpy.data.objects.get('SkeletalMesh')
if not mesh:raise ValueError('The replacement scene has no skeletal mesh')
reports=[];paths={}
for material in mesh.data.materials:
    if material and material.name in slots:
        record=slots[material.name];reports.append(wire_material(material,record))
        paths.update({os.path.normcase(os.path.abspath(mp['path'])):mp['final_path'] for mp in record['maps']})
for image in bpy.data.images:
    key=os.path.normcase(os.path.abspath(bpy.path.abspath(image.filepath)))
    if key in paths:image.filepath_raw=paths[key]
bpy.ops.wm.save_as_mainfile(filepath=scene)
print('IMPORT_MATERIALS_OK '+json.dumps(reports))
