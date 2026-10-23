from pathlib import Path
import json
import zipfile
import tempfile
import threading
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty, FloatVectorProperty, EnumProperty, PointerProperty
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper
from .session import ImportSession
from . import viewport

_SESSION = None
DEFAULT_OUTPUT = str(Path(r'C:\Projects\ROBOTDOLLY-WorldBridge\imports')
                     if Path(r'C:\Projects\ROBOTDOLLY-WorldBridge').is_dir()
                     else Path.home() / 'WorldBridge' / 'imports')
_INSPECTING = False
_ARCHIVE_ITEMS = [('NONE', 'No archive selected', '')]


def file_type_update(self, context):
    self.filter_glob = {'ALL': '*.json;*.json.gz;*.gz;*.zip', 'JSON': '*.json',
                        'GZIP': '*.gz', 'ZIP': '*.zip'}[self.file_type]
    if context.space_data and context.space_data.type == 'FILE_BROWSER':
        context.space_data.params.filter_glob = self.filter_glob


def archive_items(self, context):
    # Blender may pass OperatorProperties rather than the Python Operator here.
    # Keep returned strings alive at module scope for the dynamic enum's lifetime.
    return _ARCHIVE_ITEMS


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
    filter_glob: StringProperty(default='*.json;*.json.gz;*.gz;*.zip', options={'HIDDEN'})
    file_type: EnumProperty(name='File type', items=[('ALL', 'All Supported Files', ''),
        ('JSON', 'JSON (*.json)', ''), ('GZIP', 'Compressed JSON (*.json.gz, *.gz)', ''),
        ('ZIP', 'World archives (*.zip, *.content.zip)', '')], default='ALL', update=file_type_update)
    archive_member: EnumProperty(name='World JSON', items=archive_items)
    load_models: BoolProperty(name='Download HTTP(S) models', default=False)
    model_limit: IntProperty(name='Maximum models (0 = all)', default=4, min=0,
                            description='Safe test mode: all entities get placeholders; only first N matching models load')
    model_filter: StringProperty(name='Model name or ID contains', default='',
                                 description='Optional case-insensitive name/ID substring, applied before model limit')
    world_positions: BoolProperty(name='Script export: world-space transforms', default=False, description='Leave OFF for domain models.json.gz backups')
    output_dir: StringProperty(name='Sidecar / cache directory', subtype='DIR_PATH', default=DEFAULT_OUTPUT)

    def set_candidates(self, candidates):
        global _ARCHIVE_ITEMS
        self._archive_items = [(name, '%s (%d entities)' % (name, count), name)
                               for name, count in candidates.items()]
        _ARCHIVE_ITEMS = self._archive_items
        self._archive_path = self.filepath
        self.archive_member = self._archive_items[0][0]

    def open_choice(self):
        global _ARCHIVE_ITEMS
        _ARCHIVE_ITEMS = self._archive_items
        bpy.ops.worldbridge.choose_archive('INVOKE_DEFAULT', filepath=self.filepath,
            output_dir=self.output_dir, load_models=self.load_models,
            world_positions=self.world_positions, model_limit=self.model_limit, model_filter=self.model_filter)
        return {'FINISHED'}

    def modal(self, context, event):
        global _INSPECTING
        if event.type == 'ESC':
            self._scan_stop.set()
            context.window_manager.event_timer_remove(self._scan_timer)
            _INSPECTING = False
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        outcome = self._scan_worker.poll()
        if outcome is None:
            return {'PASS_THROUGH'}
        context.window_manager.event_timer_remove(self._scan_timer)
        _INSPECTING = False
        kind, payload = outcome
        if kind == 'error':
            self.report({'ERROR'}, payload['error'])
            return {'CANCELLED'}
        self.set_candidates(payload)
        if len(payload) > 1:
            return self.open_choice()
        return self.execute(context)

    def draw(self, context):
        if getattr(self, '_archive_items', None):
            self.layout.label(text='Choose the world to import from this archive')
            self.layout.prop(self, 'archive_member')
        else:
            for name in ('file_type', 'load_models', 'model_limit', 'model_filter', 'world_positions', 'output_dir'):
                self.layout.prop(self, name)

    def execute(self, context):
        global _SESSION, _INSPECTING
        if _INSPECTING:
            self.report({'ERROR'}, 'Archive inspection is running; press Esc to cancel it')
            return {'CANCELLED'}
        if _SESSION and not _SESSION.done:
            self.report({'ERROR'}, 'An import is already running; cancel it first')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            self.report({'ERROR'}, 'Switch to Object Mode before importing')
            return {'CANCELLED'}
        try:
            member = None
            if zipfile.is_zipfile(self.filepath):
                if getattr(self, '_archive_path', None) != self.filepath:
                    from .parser import archive_backups
                    if not bpy.app.background:
                        from .runtime import Worker, ProgressLog
                        source = self.filepath
                        self._scan_stop = threading.Event()
                        self._scan_worker = Worker(lambda event: archive_backups(source, cancel_event=event),
                                                   self._scan_stop, ProgressLog('archive-inspection'), 'inspect_archive')
                        self._scan_timer = context.window_manager.event_timer_add(.1, window=context.window)
                        context.window_manager.modal_handler_add(self)
                        _INSPECTING = True
                        self.report({'INFO'}, 'Inspecting archive; press Esc to cancel. No assets are extracted.')
                        return {'RUNNING_MODAL'}
                    candidates = archive_backups(self.filepath)
                    self.set_candidates(candidates)
                    if len(candidates) > 1:
                        if bpy.app.background:
                            raise ValueError('Multiple worlds in archive; use load_backup(..., archive_member=...) in headless scripts')
                        return self.open_choice()
                member = self.archive_member
            _SESSION = ImportSession(self.filepath, bpy.path.abspath(self.output_dir), self.load_models,
                                     self.world_positions, self.model_limit, self.model_filter, archive_member=member)
            bpy.app.timers.register(timer_tick, first_interval=.05)
            self.report({'INFO'}, 'Import started. Progress and Cancel Import are in WorldBridge sidebar.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, 'Import failed: %s. Check WorldBridge report if a collection was created.' % exc)
            return {'CANCELLED'}


class WORLDBRIDGE_OT_archive_choice(bpy.types.Operator):
    bl_idname = 'worldbridge.choose_archive'
    bl_label = 'Choose World Backup in Archive'
    filepath: StringProperty()
    output_dir: StringProperty()
    archive_member: EnumProperty(name='World JSON', items=archive_items)
    load_models: BoolProperty(default=False)
    world_positions: BoolProperty(default=False)
    model_limit: IntProperty(default=4)
    model_filter: StringProperty()

    def invoke(self, context, event):
        self.archive_member = _ARCHIVE_ITEMS[0][0]
        return context.window_manager.invoke_props_dialog(self, width=650)

    def draw(self, context):
        self.layout.label(text='Several valid entity backups found. Choose one:')
        self.layout.prop(self, 'archive_member')

    def execute(self, context):
        global _SESSION
        if (_SESSION and not _SESSION.done) or context.mode != 'OBJECT':
            self.report({'ERROR'}, 'Finish the active import and switch to Object Mode first')
            return {'CANCELLED'}
        try:
            _SESSION = ImportSession(self.filepath, bpy.path.abspath(self.output_dir), self.load_models,
                self.world_positions, self.model_limit, self.model_filter, archive_member=self.archive_member)
            bpy.app.timers.register(timer_tick, first_interval=.05)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
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
    bl_label = 'Load Selected Area'
    use_region: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and (_SESSION is None or _SESSION.done)

    def invoke(self, context, event):
        try:
            from .preparation import prepare_selected
            self._anchors = viewport.region_anchors(context) if self.use_region else viewport.selected_anchors(context)
            if not self._anchors:
                raise ValueError('No WorldBridge entities selected or inside region')
            self._anchors.sort(key=lambda o: (o['worldbridge_sidecar'], o['worldbridge_record_index']))
            snapshots = [dict(target_key=str(i), sidecar=o['worldbridge_sidecar'],
                              index=o['worldbridge_record_index'], id=o['worldbridge_entity_id'],
                              loaded=any(viewport.role(c) == 'MODEL' and c.type == 'MESH'
                                         for c in viewport.owned_objects(o))) for i, o in enumerate(self._anchors)]
            with tempfile.TemporaryDirectory(prefix='worldbridge-preview-') as directory:
                result = prepare_selected(snapshots, directory, 'preview', context.scene.worldbridge_selection_limit)
            self._preview = (len(self._anchors), len(result['tasks']),
                             len({t['url'] for t in result['tasks']}), result['report']['assets_skipped'],
                             result['report']['selected_cached_assets'], result['report']['selected_downloadable_assets'])
            return context.window_manager.invoke_props_dialog(self, width=440)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def draw(self, context):
        entities, models, assets, skipped, cached, downloadable = self._preview
        self.layout.label(text='%d selected entities; %d model instances to load' % (entities, models))
        self.layout.label(text='%d unique model URLs; %d skipped (loaded, non-model or limit)' % (assets, skipped))
        self.layout.label(text='%d cached assets; %d require download' % (cached, downloadable))
        if context.scene.worldbridge_refresh_cache:
            self.layout.label(text='Refresh enabled: cached assets will be downloaded again.')
        self.layout.label(text='Region: ' + ('conservative bounds intersection' if context.scene.worldbridge_region_bounds else 'entity origins'))
        self.layout.label(text='Confirm to download and import these models.')

    def execute(self, context):
        global _SESSION
        try:
            if getattr(self, '_anchors', None) is not None:
                anchors = self._anchors
            elif self.use_region:
                anchors = viewport.region_anchors(context)
            else:
                anchors = viewport.selected_anchors(context)
            if not anchors:
                raise ValueError('No WorldBridge entities selected or inside region')
            _SESSION = ImportSession('', DEFAULT_OUTPUT,
                                     model_limit=context.scene.worldbridge_selection_limit, existing_targets=anchors,
                                     force_reload=context.scene.worldbridge_refresh_cache)
            bpy.app.timers.register(timer_tick, first_interval=.05)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_OT_region(bpy.types.Operator):
    bl_idname = 'worldbridge.create_region'
    bl_label = 'Create / Select Area Region'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        region = context.scene.worldbridge_region
        if region is None or region.name not in context.scene.objects:
            region = bpy.data.objects.new('WorldBridge Selection Region', None)
            context.scene.collection.objects.link(region)
            region.empty_display_type = 'CUBE'
            region.empty_display_size = 1
            region.location = context.scene.cursor.location
            region.scale = (10, 10, 10)
            region.show_in_front = True
            region['worldbridge_role'] = 'REGION'
            context.scene.worldbridge_region = region
        for obj in context.selected_objects:
            obj.select_set(False)
        region.hide_set(False)
        region.select_set(True)
        context.view_layer.objects.active = region
        self.report({'INFO'}, 'Move (G), scale (S), or rotate (R) the region; use X/Y/Z to adjust each axis')
        return {'FINISHED'}


class WORLDBRIDGE_OT_lights(bpy.types.Operator):
    bl_idname = 'worldbridge.apply_lights'
    bl_label = 'Apply Light Region Now'

    def execute(self, context):
        context.view_layer.update()
        viewport.apply_lighting(context.scene)
        return {'FINISHED'}


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


class WORLDBRIDGE_OT_repair_textures(bpy.types.Operator):
    bl_idname = 'worldbridge.repair_selected_textures'
    bl_label = 'Recover Selected Missing Textures'

    @classmethod
    def poll(cls, context):
        return _SESSION is None or _SESSION.done

    def execute(self, context):
        from .textures import repair_images
        results = []
        try:
            anchors = viewport.selected_anchors(context)
            if not anchors:
                raise ValueError('Select a WorldBridge model or placeholder')
            for anchor in anchors:
                materials = {s.material for obj in viewport.owned_objects(anchor)
                             for s in obj.material_slots if s.material}
                diagnostics = repair_images(materials, Path(anchor['worldbridge_sidecar']).parent/'cache',
                                            context.scene.worldbridge_rescue_root)
                anchor['worldbridge_texture_diagnostics'] = json.dumps(diagnostics)
                results.extend(diagnostics)
            text = bpy.data.texts.new('WorldBridge Texture Recovery')
            text.write(json.dumps(results, indent=2))
            recovered = sum(r['status'] == 'recovered' for r in results)
            self.report({'INFO'}, '%d images recovered; %d unresolved. Details in Text Editor.' % (recovered, len(results)-recovered))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WORLDBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = 'ROBOTDOLLY WorldBridge v0.5'
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
        if _SESSION and _SESSION.report.get('fatal_error'):
            self.layout.label(text=_SESSION.report['fatal_error'].strip().splitlines()[-1][:160], icon='ERROR')
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
        box.prop(context.scene, 'worldbridge_import_cameras', text='Keep Embedded Model Cameras')
        box.prop(context.scene, 'worldbridge_show_cameras', text='Show WorldBridge Cameras')
        box.prop(context.scene, 'worldbridge_show_lights', text='Show Light Gizmos / Extras')
        box.prop(context.scene, 'worldbridge_enable_lights', text='Enable Light Contribution')
        box.prop(context.scene, 'worldbridge_lights_region_only', text='Enable Lights Only Inside Region')
        box.operator('worldbridge.apply_lights')
        box.operator('worldbridge.frame_entities', text='Frame Entire World').selected_only = False
        box.operator('worldbridge.frame_entities', text='Frame Selected Entity').selected_only = True
        box = self.layout.box()
        box.label(text='Load Existing Entities (no duplicates)')
        box.prop(context.scene, 'worldbridge_selection_limit', text='Model Limit')
        box.prop(context.scene, 'worldbridge_refresh_cache', text='Refresh Cache for Retry')
        box.operator('worldbridge.load_selected_models')
        box.operator('worldbridge.repair_selected_materials')
        box.operator('worldbridge.reconstruct_textures')
        box.prop(context.scene, 'worldbridge_rescue_root', text='Read-only Texture Rescue')
        box.operator('worldbridge.create_region')
        box.prop(context.scene, 'worldbridge_region_bounds', text='Intersect Entity Bounds')
        box.label(text='Move G / Scale S / Rotate R; X, Y, Z constrain')
        box.operator('worldbridge.load_selected_models', text='Load Selected Area (Region)').use_region = True
        obj = context.active_object
        if obj and 'worldbridge_entity_id' in obj:
            self.layout.label(text='ID: ' + obj['worldbridge_entity_id'])
            self.layout.label(text='Type: ' + obj['worldbridge_type'])


CLASSES = (WORLDBRIDGE_OT_import, WORLDBRIDGE_OT_archive_choice, WORLDBRIDGE_OT_cancel, WORLDBRIDGE_OT_clip, WORLDBRIDGE_OT_frame,
           WORLDBRIDGE_OT_load_selected, WORLDBRIDGE_OT_region, WORLDBRIDGE_OT_lights, WORLDBRIDGE_OT_repair_materials,
           WORLDBRIDGE_OT_repair_textures, WORLDBRIDGE_PT_panel)


def register():
    bpy.types.Scene.worldbridge_refresh_cache = BoolProperty(default=False, description='Re-download selected unloaded models; completed instances are still skipped')
    bpy.types.Scene.worldbridge_rescue_root = StringProperty(subtype='DIR_PATH', default=r'C:\Projects\ROBOTDOLLY-Asset-Rescue')
    bpy.types.Scene.worldbridge_clip_start = FloatProperty(name='Clip Start', default=.01, min=.0001, max=99999, unit='LENGTH')
    bpy.types.Scene.worldbridge_clip_end = FloatProperty(name='Clip End', default=100000, min=.001, max=1000000, unit='LENGTH')
    bpy.types.Scene.worldbridge_show_anchors = BoolProperty(default=False, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_show_placeholders = BoolProperty(default=True, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_show_models = BoolProperty(default=True, update=viewport.visibility_update)
    bpy.types.Scene.worldbridge_selection_limit = IntProperty(default=0, min=0, max=10000, description='0 loads all eligible selected models')
    bpy.types.Scene.worldbridge_region = PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.worldbridge_region_bounds = BoolProperty(default=False)
    bpy.types.Scene.worldbridge_import_cameras = BoolProperty(default=False)
    bpy.types.Scene.worldbridge_show_cameras = BoolProperty(default=False, update=viewport.lighting_update)
    bpy.types.Scene.worldbridge_show_lights = BoolProperty(default=True, update=viewport.lighting_update)
    bpy.types.Scene.worldbridge_enable_lights = BoolProperty(default=True, update=viewport.lighting_update)
    bpy.types.Scene.worldbridge_lights_region_only = BoolProperty(default=False, update=viewport.lighting_update)
    bpy.types.Scene.worldbridge_region_min = FloatVectorProperty(default=(-10, -10, -10), subtype='XYZ', unit='LENGTH')
    bpy.types.Scene.worldbridge_region_max = FloatVectorProperty(default=(10, 10, 10), subtype='XYZ', unit='LENGTH')
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(before_load)
    bpy.app.handlers.load_post.append(after_load)
    bpy.app.timers.register(initialize_viewport, first_interval=.1)


def unregister():
    del bpy.types.Scene.worldbridge_refresh_cache
    del bpy.types.Scene.worldbridge_rescue_root
    stop_session('WorldBridge add-on disabled')
    if before_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(before_load)
    if after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(after_load)
    if bpy.app.timers.is_registered(initialize_viewport):
        bpy.app.timers.unregister(initialize_viewport)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in ('clip_start', 'clip_end', 'show_anchors', 'show_placeholders', 'show_models', 'selection_limit', 'region_min', 'region_max', 'region', 'region_bounds', 'import_cameras', 'show_cameras', 'show_lights', 'enable_lights', 'lights_region_only'):
        delattr(bpy.types.Scene, 'worldbridge_' + name)
