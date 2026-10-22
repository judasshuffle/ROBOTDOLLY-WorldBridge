"""Viewport-only tools. Do not mutate entity transforms or render visibility."""
import math
import json
import bpy
from mathutils import Vector


def entity_anchor(obj):
    while obj is not None:
        if 'worldbridge_entity_id' in obj:
            return obj
        obj = obj.parent
    return None


def role(obj):
    if 'worldbridge_entity_id' in obj:
        return 'ANCHOR'
    stored = obj.get('worldbridge_role')
    if stored:
        return stored
    if entity_anchor(obj) is None:
        return None
    if obj.get('worldbridge_visual'):
        return 'PLACEHOLDER' if obj.display_type == 'WIRE' else 'PRIMITIVE'
    return 'MODEL'  # Also recognises imported children in saved v0.1/v0.2 scenes.


def apply_visibility(scene):
    hidden = dict(ANCHOR=not getattr(scene, 'worldbridge_show_anchors', False),
                  PLACEHOLDER=not getattr(scene, 'worldbridge_show_placeholders', True),
                  MODEL=not getattr(scene, 'worldbridge_show_models', True))
    for obj in scene.objects:
        group = role(obj)
        if group not in hidden:
            continue
        obj['worldbridge_role'] = group
        for layer in scene.view_layers:
            if obj.name in layer.objects:
                obj.hide_set(hidden[group], view_layer=layer)


def visibility_update(scene, context):
    apply_visibility(scene)


def viewports(workspace=None):
    workspace = workspace or bpy.context.workspace
    if workspace is None:
        return
    for screen in workspace.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        yield area, space


def apply_clipping(scene, workspace=None, preserve_custom=False):
    near, far = getattr(scene, 'worldbridge_clip_start', .01), getattr(scene, 'worldbridge_clip_end', 100000.0)
    if far <= near:
        raise ValueError('Clip End must be greater than Clip Start')
    state = json.loads(scene.get('worldbridge_clip_state', '{}'))
    count = 0
    for area, space in viewports(workspace):
        screen = next(screen for screen in (workspace or bpy.context.workspace).screens if area in list(screen.areas))
        key = '%s/%s/%s/%s' % ((workspace or bpy.context.workspace).name, screen.name,
                               list(screen.areas).index(area), list(area.spaces).index(space))
        current = [space.clip_start, space.clip_end]
        if preserve_custom and key in state and current != state[key]:
            continue  # Native viewport settings were edited since our last apply.
        space.clip_start = near
        space.clip_end = far
        state[key] = [space.clip_start, space.clip_end]
        area.tag_redraw()
        count += 1
    scene['worldbridge_clip_state'] = json.dumps(state)
    return count


def after_import(scene):
    # Scene properties persist in the .blend; never reset them to defaults here.
    warning = None
    try:
        apply_clipping(scene, preserve_custom=True)
    except ValueError as exc:
        warning = 'Viewport clipping unchanged: ' + str(exc)
        print('WorldBridge: ' + warning, flush=True)
    apply_visibility(scene)
    return warning


def owned_objects(anchor):
    """This entity's visuals, excluding distinct child entities."""
    pending = list(anchor.children)
    while pending:
        obj = pending.pop()
        if 'worldbridge_entity_id' in obj:
            continue
        yield obj
        pending.extend(obj.children)


def entity_bounds(anchors):
    points = []
    for anchor in anchors:
        geometry = [obj for obj in owned_objects(anchor) if obj.type == 'MESH']
        if geometry:
            for obj in geometry:
                points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
        else:
            points.append(anchor.matrix_world.translation.copy())
    if not points:
        raise ValueError('No WorldBridge entities to frame')
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low, high


def frame_entities(anchors, workspace=None):
    bpy.context.view_layer.update()
    low, high = entity_bounds(anchors)
    center, radius = (low + high) * .5, max((high - low).length * .5, .1)
    count = 0
    for area, space in viewports(workspace):
        # Conservative FOV estimate, accounting for narrow portrait viewports.
        aspect = max(.1, min(1.0, area.width / max(area.height, 1)))
        angle = math.atan(16.0 * aspect / max(space.lens, 1))
        for region in (list(space.region_quadviews) or [space.region_3d]):
            if region:
                region.view_perspective = 'PERSP'
                region.view_location = center
                region.view_distance = radius / math.sin(angle) * 1.2
                count += 1
        area.tag_redraw()
    return count


def selected_anchors(context):
    return list({anchor for obj in context.selected_objects
                 if (anchor := entity_anchor(obj)) is not None})
