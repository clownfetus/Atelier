"""Preserve evaluated replacement geometry when flattening imported objects.

Importing used to remove Mirror/Solidify/etc. without applying them. Negative
object transforms also need a winding correction after baking into mesh space.
This helper changes only the disposable imported object, never the source file.
"""
import math


def bake_geometry(obj, api=None):
    if api is None:
        import bpy as api
    transform = obj.matrix_world.copy()
    determinant = float(transform.to_3x3().determinant())
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        raise ValueError('Replacement object has a singular or invalid scale: ' + obj.name)
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    before = len(obj.data.polygons)
    baked = []
    for modifier in list(obj.modifiers):
        if modifier.type == 'ARMATURE' or not modifier.show_viewport:
            obj.modifiers.remove(modifier)
    for modifier in list(obj.modifiers):
        name = modifier.name
        try:
            with api.context.temp_override(object=obj, active_object=obj,
                                           selected_objects=[obj], selected_editable_objects=[obj]):
                outcome = api.ops.object.modifier_apply(modifier=name)
            if 'FINISHED' not in outcome:
                raise RuntimeError('Blender returned ' + str(outcome))
        except Exception as error:
            raise ValueError('Could not preserve modifier ' + repr(name) + ' on ' + repr(obj.name) +
                             '. Apply it to the source in Blender before importing; no replacement was saved. ' +
                             str(error)) from error
        baked.append(name)
    data = obj.data
    normals = {}
    if data.has_custom_normals:
        normal_matrix = transform.to_3x3().inverted().transposed()
        corner_normals = list(data.corner_normals)
        if len(corner_normals) != len(data.loops):
            raise ValueError('Custom normal data is incomplete on ' + obj.name)
        for polygon in data.polygons:
            for loop_index in polygon.loop_indices:
                key = (polygon.index, data.loops[loop_index].vertex_index)
                normal = normal_matrix @ corner_normals[loop_index].vector
                normals[key] = tuple(normal.normalized())
    obj.parent = None
    data.transform(transform, shape_keys=True)
    if determinant < 0:
        data.flip_normals()
    if normals:
        restored = [None] * len(data.loops)
        for polygon in data.polygons:
            for loop_index in polygon.loop_indices:
                restored[loop_index] = normals[(polygon.index, data.loops[loop_index].vertex_index)]
        data.normals_split_custom_set(restored)
    identity = transform.copy()
    identity.identity()
    obj.matrix_world = identity
    data.update()
    if not data.polygons:
        raise ValueError('Applying modifiers removed every face from ' + obj.name)
    for vertex in data.vertices:
        if not all(math.isfinite(float(value)) for value in vertex.co):
            raise ValueError('Replacement contains non-finite vertex coordinates: ' + obj.name)
    obj.hide_set(False)
    obj.hide_viewport = obj.hide_select = False
    return {'object': obj.name, 'input_faces': before, 'output_faces': len(data.polygons),
            'baked_modifiers': baked, 'mirrored_winding_corrected': determinant < 0}
