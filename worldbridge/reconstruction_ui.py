import bpy
from pathlib import Path
from bpy.props import StringProperty, FloatProperty, BoolProperty, EnumProperty
from . import viewport

SESSION = None


def tick():
    return SESSION.tick() if SESSION and not SESSION.done else None


def start(anchors, scene):
    global SESSION
    from .visualtextures import RepairSession
    if SESSION and not SESSION.done:
        raise ValueError('Texture recovery already running')
    roots = [scene.worldbridge_rescue_root]+scene.worldbridge_asset_roots.split(';')
    roots.extend(str(Path(a['worldbridge_sidecar']).parent/'cache') for a in anchors if a.get('worldbridge_sidecar'))
    SESSION = RepairSession(anchors, scene, list(dict.fromkeys(roots)), bpy.path.abspath(scene.worldbridge_recovery_cache), scene.worldbridge_rescan)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=.1)
    return SESSION


@bpy.app.handlers.persistent
def stop(*args):
    if SESSION and not SESSION.done:
        SESSION.cancel()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)


class WB_OT_reconstruct(bpy.types.Operator):
    bl_idname = 'worldbridge.reconstruct_textures'
    bl_label = 'Recover Textures and Materials'
    scope: EnumProperty(items=[('SELECTED','Selected Objects',''), ('COLLECTION','Active Collection',''),
                               ('REGION','Selected Area',''), ('ALL','Entire Imported Scene','')], default='SELECTED')

    @classmethod
    def poll(cls, context):
        from .ui import _SESSION
        return (SESSION is None or SESSION.done) and (_SESSION is None or _SESSION.done)

    def execute(self, context):
        try:
            if self.scope == 'SELECTED':
                anchors = viewport.selected_anchors(context)
            elif self.scope == 'REGION':
                anchors = viewport.region_anchors(context)
            else:
                objects = context.collection.all_objects if self.scope == 'COLLECTION' else context.scene.objects
                anchors = list({a for o in objects if (a := viewport.entity_anchor(o)) is not None})
            if not anchors:
                raise ValueError('No imported WorldBridge objects in this scope')
            start(anchors, context.scene)
            self.report({'INFO'}, 'Local recovery started; progress and cancellation below')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WB_OT_cancel_recovery(bpy.types.Operator):
    bl_idname = 'worldbridge.cancel_recovery'
    bl_label = 'Cancel Texture Recovery'

    def execute(self, context):
        stop()
        return {'FINISHED'}


class WB_OT_camera(bpy.types.Operator):
    bl_idname = 'worldbridge.reference_camera'
    bl_label = 'Create Camera and Surrounding Area'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .reference import create_camera
        scene = context.scene
        try:
            create_camera(scene, scene.worldbridge_location, scene.worldbridge_fov, scene.worldbridge_eye_height,
                          scene.worldbridge_camera_distance, scene.worldbridge_area_radius)
            self.report({'INFO'}, 'Camera ready. Load Selected Area (Region) to load nearby models.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WB_PT_reconstruction(bpy.types.Panel):
    bl_label = 'Visual Reconstruction'
    bl_idname = 'WB_PT_reconstruction'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'WorldBridge'

    def draw(self, context):
        scene = context.scene
        box = self.layout.box()
        for name in ('location', 'fov', 'eye_height', 'camera_distance', 'area_radius'):
            box.prop(scene, 'worldbridge_'+name)
        box.operator('worldbridge.reference_camera')
        box.operator('worldbridge.load_selected_models', text='Load Surrounding Area').use_region = True
        box = self.layout.box()
        box.prop(scene, 'worldbridge_auto_recover')
        box.prop(scene, 'worldbridge_rescue_root')
        box.prop(scene, 'worldbridge_asset_roots')
        box.prop(scene, 'worldbridge_recovery_cache')
        box.prop(scene, 'worldbridge_rescan')
        for scope, label in [('SELECTED','Repair Selected'), ('COLLECTION','Repair Active Collection'),
                             ('REGION','Repair Selected Area'), ('ALL','Repair Imported Scene')]:
            box.operator('worldbridge.reconstruct_textures', text=label).scope = scope
        if SESSION and not SESSION.done:
            box.operator('worldbridge.cancel_recovery')
        box.label(text=scene.get('worldbridge_recovery_status', 'Ready')[:110])


CLASSES = (WB_OT_reconstruct, WB_OT_cancel_recovery, WB_OT_camera, WB_PT_reconstruction)
PROPS = dict(location=StringProperty(name='DarkRide location', default='hifi://domain/0,0,0/0,0,0,1'),
             fov=FloatProperty(name='Horizontal FOV (degrees)', default=70, min=10, max=150),
             eye_height=FloatProperty(name='Eye height offset', default=1.6, min=-10, max=10),
             camera_distance=FloatProperty(name='Third-person distance', default=0, min=0, max=100),
             area_radius=FloatProperty(name='Area half-size (metres)', default=35, min=.1, max=1000),
             asset_roots=StringProperty(name='Additional local roots (; separated)', default=''),
             recovery_cache=StringProperty(name='Recovery output', subtype='DIR_PATH', default=str(Path.home()/'WorldBridge'/'v05-recovery')),
             rescan=BoolProperty(name='Rescan local files', default=False),
             auto_recover=BoolProperty(name='Recover textures after area import', default=True))


def register():
    for name, prop in PROPS.items():
        setattr(bpy.types.Scene, 'worldbridge_'+name, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(stop)


def unregister():
    stop()
    if stop in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(stop)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in PROPS:
        delattr(bpy.types.Scene, 'worldbridge_'+name)
