"""Native check of the Blender material wiring, run with Blender --background --factory-startup.

Usage: blender --background --factory-startup --python tests/native_blender_materials.py -- ROOT REPORT.json
Generated material records and 8x8 images only. No game files, user projects or
installed add-ons are used. Every route into Blender (live send, portable .blend,
Edit in Blender, material bundles) builds its materials through wire_material.
"""
import json
from pathlib import Path
import sys
import tempfile

import bpy

root, report = map(Path, sys.argv[sys.argv.index('--') + 1:])
sys.path.insert(0, str(root / 'atelier/blender'))
from material_nodes import wire_material

report.parent.mkdir(parents=True, exist_ok=True)
checks = []


def rounded(value):
    return tuple(round(v, 4) for v in value) if hasattr(value, '__len__') else round(value, 4)


def group_node(material):
    return next(node for node in material.node_tree.nodes if node.type == 'GROUP')


def principled(material):
    return next(node for node in group_node(material).node_tree.nodes if node.type == 'BSDF_PRINCIPLED')


def node_values(material):
    """Values on the group node the material renders with (not the group's own defaults)."""
    return {socket.name: rounded(socket.default_value) for socket in group_node(material).inputs
            if not socket.is_linked and hasattr(socket, 'default_value')}


with tempfile.TemporaryDirectory(prefix='atelier-native-materials-', dir=report.parent) as temporary:
    work = Path(temporary)

    def png(name, rgba):
        image = bpy.data.images.new(name, 8, 8, alpha=True)
        image.pixels = list(rgba) * 64
        image.filepath_raw = str(work / (name + '.png')); image.file_format = 'PNG'; image.save()
        return image.filepath_raw

    base, orm, normal = png('T_Fixture_D', (.2, .3, .6, 1)), png('T_Fixture_ORM', (1, .6, .5, 1)), png('T_Fixture_N', (.5, .5, 1, 1))

    def wire(name, record):
        material = bpy.data.materials.new(name)
        return material, wire_material(material, record)

    body, _ = wire('MI_Fixture_Body', {
        'colors': [{'name': 'BaseTint', 'rgba': [1, 1, 1, 1]}],
        'scalars': [{'name': 'Metailic', 'value': .8}, {'name': 'NormalIntensity', 'value': 1.0},
                    {'name': 'RoughnessPower', 'value': .15}],
        'maps': [{'param': 'BaseColor', 'role': 'basecolor', 'path': base},
                 {'param': 'ORM', 'role': 'orm', 'path': orm},
                 {'param': 'Normal', 'role': 'normal', 'path': normal}],
        'surface': {'blend_mode': 'BLEND_Opaque'}})
    values = node_values(body)
    assert values['Colour · BaseTint'] == (1, 1, 1, 1), values
    assert values['Value · Metailic'] == .8 and values['Value · NormalIntensity'] == 1, values
    for item in group_node(body).node_tree.interface.items_tree:
        if getattr(item, 'in_out', None) == 'INPUT' and item.name in values:
            assert values[item.name] == rounded(item.default_value), (item.name, values[item.name])
    checks.append({'name': 'material values reach the group node, not only the group defaults',
                   'inputs': len(values)})

report.write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string, 'checks': checks}, indent=2) + '\n')
print('ATELIER_MATERIALS_NATIVE_OK', report)
