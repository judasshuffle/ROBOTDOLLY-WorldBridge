from pathlib import Path
import json
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty, FloatVectorProperty
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper
from .session import ImportSession
from . import viewport

_SESSION = None


def timer_tick():
    return _SESSION.tick() if _SESSION and not _SESSION.done else None


def stop_session(reason):
    if _SESSION and not _SESSION.done:
        _SESSION.cancel(reason)
    if bpy.app.timers.is_registered(timer_tick):
        bpy.app.timers.unregister(timer_tick)


@persistent
def before_load(_):
    stop_session('Blender file changed')


def initialize_viewport():
    if _SESSION and not _SESSION.done:
        return None  # The running import applies settings when its scene is ready.
    scene = bpy.context.scene
    if any('worldbridge_entity_id' in obj for obj in scene.objects):
        viewport.after_import(scene)
    return None


@persistent
def after_load(_):
    initialize_viewport()


class WORLDBRIDGE_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = 'worldbridge.import_backup'
    bl_label = 'Import DarkRide Backup'
    filename_ext = '.json.gz'
    filter_glob: StringProperty(default='*.json;*.json.gz;*.gz', options={'HIDDEN'})
    load_models: BoolProperty(name='Download HTTP(S) models', default=True)
    model_limit: IntProperty(name='Maximum models (0 = all)', default=4, min=0,
                            description='Safe test mode: all entities get placeholders; only first N matching models load')
    model_filter: StringProperty(name='Model name or ID contains', default='',
                                 description='Optional case-insensitive name/ID substring, applied before model limit')
    world_positions: BoolProperty(name='Script export: world-space transforms', default=False, description='Leave OFF for domain models.json.gz backups')
    output_dir: StringProperty(name='Sidecar / cache directory', subtype='DIR_PATH', default='C:\\Projects\\ROBOTDOLLY-WorldBridge\\imports')

    def execute(self, context):
        global _SESSION
        if _SESSION and not _SESSION.done:
            self.report({'ERROR'}, 'An import is already running; cancel it first')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, 'Switch to Object Mode before importing')
            return {'CANCELLED'}
        try:
            _SESSION = ImportSession(self.filepath, bpy.path.abspath(self.output_dir), self.load_models,
                                     self.world_positions, self.model_limit, self.model_filter)
            bpy.app.timers.register(timer_tick, first_interval=.05)
            self.report({'INFO'}, 'Import started. Progress and Cancel Import are in WorldBridge sidebar.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, 'Import failed: %s. Check WorldBridge report if a collection was created.' % exc)
            return {'CANCELLED'}


class WORLDBRIDGE_OT_cancel(bpy.types.Operator):
    bl_idname = 'worldbridge.cancel_import'
    bl_label = 'Cancel Import'

    @classmethod
    def poll(cls, context):
        return _SESSION is not None and not _SESSION.done

    def execute(self, context):
        stop_session('User requested cancellation')
        self.report({'INFO'}, 'Cancelled. Completed objects/placeholders retained; in-flight download will stop at its next I/O check.')
        return {'FINISHED'}


class WORLDBRIDGE_OT_clip(bpy.types.Operator):
    bl_idname = 'worldbridge.apply_clipping'
    bl_label = 'Apply to All Viewports'

    def execute(self, context):
        try:
            count = viewport.apply_clipping(context.scene, context.workspace)
            self.report({'INFO'}, 'Applied clipping to %d viewport(s)' % count)
            return {'FINISHED'}
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_OT_frame(bpy.types.Operator):
    bl_idname = 'worldbridge.frame_entities'
    bl_label = 'Frame WorldBridge Entities'
    selected_only: BoolProperty(default=False)

    def execute(self, context):
        anchors = viewport.selected_anchors(context) if self.selected_only else [
            obj for obj in context.scene.objects if 'worldbridge_entity_id' in obj]
        try:
            viewport.frame_entities(anchors, context.workspace)
            return {'FINISHED'}
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_OT_load_selected(bpy.types.Operator):
    bl_idname = 'worldbridge.load_selected_models'
    bl_label = 'Load Selected Models'
    use_region: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and (_SESSION is None or _SESSION.done)

    def execute(self, context):
        global _SESSION
        try:
            if self.use_region:
                low, high = context.scene.worldbridge_region_min, context.scene.worldbridge_region_max
                if any(low[i] > high[i] for i in range(3)):
                    raise ValueError('Region minimum must not exceed maximum')
                context.view_layer.update()
                anchors = [obj for obj in context.scene.objects if 'worldbridge_entity_id' in obj and
                           all(low[i] <= obj.matrix_world.translation[i] <= high[i] for i in range(3))]
            else:
                anchors = viewport.selected_anchors(context)
            if not anchors:
                raise ValueError('No WorldBridge entities selected or inside region')
            _SESSION = ImportSession('', r'C:\Projects\ROBOTDOLLY-WorldBridge\imports',
                                     model_limit=context.scene.worldbridge_selection_limit, existing_targets=anchors)
            bpy.app.timers.register(timer_tick, first_interval=.05)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_OT_repair_materials(bpy.types.Operator):
    bl_idname = 'worldbridge.repair_selected_materials'
    bl_label = 'Repair Selected Cached FBX Materials'

    @classmethod
    def poll(cls, context):
        return _SESSION is None or _SESSION.done

    def execute(self, context):
        from .materials import repair_existing
        try:
            anchors = viewport.selected_anchors(context)
            if not anchors:
                raise ValueError('Select a WorldBridge model or its entity anchor')
            repairs = repair_existing(anchors)
            self.report({'INFO'}, 'Repaired %d proven legacy opaque material(s); other alpha settings preserved' % len(repairs))
            return {'FINISHED'}
        except Exception as exc:
            import traceback
            from .runtime import ProgressLog
            ProgressLog('selected-material-repair').write('repair_error', traceback=traceback.format_exc())
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = 'ROBOTDOLLY WorldBridge v0.3'
    bl_idname = 'WORLDBRIDGE_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'WorldBridge'

    def draw(self, context):
        row = self.layout.row()
        row.enabled = _SESSION is None or _SESSION.done
        row.operator('worldbridge.import_backup', icon='IMPORT')
        if _SESSION and not _SESSION.done:
            self.layout.operator('worldbridge.cancel_import', icon='CANCEL')
        self.layout.label(text=context.scene.get('worldbridge_last_status', 'Ready'))
        progress = json.loads(context.scene.get('worldbridge_progress', '{}'))
        if progress:
            self.layout.label(text='Phase: ' + progress['phase'])
            self.layout.label(text='Entities: %d / %d (%d anchors)' % (progress['processed'], progress['entities'], progress['represented']))
            self.layout.label(text='Downloaded / cached: %d' % progress['downloaded'])
            self.layout.label(text='Imported: %d  Failed: %d' % (progress['success'], progress['failed']))
            self.layout.label(text='Skipped: %d  Cancelled: %d' % (progress['skipped'], progress['cancelled']))
            if progress['current']:
                self.layout.label(text='Current: ' + progress['current'][:90])
        self.layout.label(text='Reports: Text Editor > WorldBridge Report')
        box = self.layout.box()
        box.label(text='Viewport Clipping')
        box.prop(context.scene, 'worldbridge_clip_start', text='Clip Start')
        box.prop(context.scene, 'worldbridge_clip_end', text='Clip End')
        box.operator('worldbridge.apply_clipping')
        box = self.layout.box()
        box.label(text='Visibility (viewport only)')
        box.prop(context.scene, 'worldbridge_show_anchors', text='Show Entity Anchors')
        box.prop(context.scene, 'worldbridge_show_placeholders', text='Show Placeholder Geometry')
        box.prop(context.scene, 'worldbridge_show_models', text='Show Imported Models')
        box.operator('worldbridge.frame_entities', text='Frame Entire World').selected_only = False
        box.operator('worldbridge.frame_entities', text='Frame Selected Entity').selected_only = True
        box = self.layout.box()
        box.label(text='Load Existing Entities (no duplicates)')
        box.prop(context.scene, 'worldbridge_selection_limit', text='Model Limit')
        box.operator('worldbridge.load_selected_models')
        box.operator('worldbridge.repair_selected_materials')
        box.prop(context.scene, 'worldbridge_region_min', text='Region Min')
        box.prop(context.scene, 'worldbridge_region_max', text='Region Max')
        box.operator('worldbridge.load_selected_models', text='Load Models in Region').use_region = True
        obj = context.active_object
        if obj and 'worldbridge_entity_id' in obj:
            self.layout.label(text='ID: ' + obj['worldbridge_entity_id'])
            self.layout.label(text='Type: ' + obj['worldbridge_type'])


CLASSES = (WORLDBRIDGE_OT_import, WORLDBRIDGE_OT_cancel, WORLDBRIDGE_OT_clip, WORLDBRIDGE_OT_frame,
           WORLDBRIDGE_OT_load_selected, WORLDBRIDGE_OT_repair_materials, WORLDBRIDGE_PT_panel)


def register():
    bpy.types.Scene.worldbridge_clip_start = FloatProperty(name='Clip Start', default=.01, min=.0001, max=99999, unit='LENGTH')
    bpy.types.Scene.worldbridge_clip_end = FloatProperty(name='Clip End', default=100000, min=.001, max=1000000, unit='LENGTH')
    bpy.types.Scene.worldbridge_show_anchors = BoolProperty(default=False, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_show_placeholders = BoolProperty(default=True, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_show_models = BoolProperty(default=True, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_selection_limit = IntProperty(default=4, min=1, max=10000)
    bpy.types.Scene.worldbridge_region_min = FloatVectorProperty(default=(-10, -10, -10), subtype='XYZ', unit='LENGTH')
    bpy.types.Scene.worldbridge_region_max = FloatVectorProperty(default=(10, 10, 10), subtype='XYZ', unit='LENGTH')
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(before_load)
    bpy.app.handlers.load_post.append(after_load)
    bpy.app.timers.register(initialize_viewport, first_interval=.1)


def unregister():
    stop_session('WorldBridge add-on disabled')
    if before_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(before_load)
    if after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(after_load)
    if bpy.app.timers.is_registered(initialize_viewport):
        bpy.app.timers.unregister(initialize_viewport)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in ('clip_start', 'clip_end', 'show_anchors', 'show_placeholders', 'show_models', 'selection_limit', 'region_min', 'region_max'):
        delattr(bpy.types.Scene, 'worldbridge_' + name)
