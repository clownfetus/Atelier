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

    # Roughness is ORM green itself; RoughnessPower (0 on most bodies, skin and hair) is kept
    # as a visible value but never scales or replaces it.
    roughness = principled(body).inputs['Roughness'].links[0].from_socket
    assert roughness.node.bl_idname == 'ShaderNodeSeparateColor', roughness.node.bl_idname
    assert roughness.identifier == roughness.node.outputs[1].identifier, roughness.name
    hair, _ = wire('MI_Fixture_Hair', {
        'colors': [], 'scalars': [{'name': 'RoughnessPower', 'value': 0.0}],
        'maps': [{'param': 'BaseColor', 'role': 'basecolor', 'path': base}], 'surface': {'blend_mode': 'BLEND_Opaque'}})
    fallback = principled(hair).inputs['Roughness'].links[0].from_socket
    assert fallback.node.type == 'VALUE' and round(fallback.default_value, 4) == .6, (fallback.node.type, fallback.default_value)
    assert node_values(hair)['Value · RoughnessPower'] == 0, node_values(hair)
    checks.append({'name': 'roughness comes from ORM green, and RoughnessPower never makes a mirror'})

    # Every material has Atelier's own Alpha first, 0 to 1, driving the surface's alpha.
    # Game effects the app's preview leaves out, and hidden sections, start at 0.
    armour, armour_report = wire('MI_Fixture_Armour', {
        'colors': [{'name': 'Fresnel Color', 'rgba': [.5, 0, 1, 1]}], 'scalars': [{'name': 'Alpha', 'value': 0.0}],
        'maps': [], 'effect_hidden': 'Disabled game effect',
        'surface': {'blend_mode': 'BLEND_TranslucentGreyTransmittance', 'two_sided': True, 'opacity': 1}})
    section, _ = wire('MI_Fixture_Section', {
        'colors': [], 'scalars': [], 'maps': [{'param': 'BaseColor', 'role': 'basecolor', 'path': base}],
        'surface': {'blend_mode': 'BLEND_Opaque'}, 'hidden': True})
    expected = {body: 1, hair: 1, armour: 0, section: 0}
    for material, start in expected.items():
        first = next(item for item in group_node(material).node_tree.interface.items_tree
                     if getattr(item, 'in_out', None) == 'INPUT')
        assert first.name == 'Alpha' and (first.min_value, first.max_value) == (0, 1), (material.name, first.name)
        assert node_values(material)['Alpha'] == start, (material.name, node_values(material))
        source = principled(material).inputs['Alpha'].links[0].from_socket
        driven = source.name == 'Alpha' and source.node.type == 'GROUP_INPUT' or any(
            link.from_socket.name == 'Alpha' and link.from_node.type == 'GROUP_INPUT'
            for link in group_node(material).node_tree.links if link.to_node == source.node)
        assert driven, (material.name, source.node.bl_idname)
    assert armour_report['effect_hidden'] == 'Disabled game effect', armour_report
    checks.append({'name': 'every material has an Alpha input; hidden effects and sections start at 0',
                   'materials': len(expected)})

report.write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string, 'checks': checks}, indent=2) + '\n')
print('ATELIER_MATERIALS_NATIVE_OK', report)
