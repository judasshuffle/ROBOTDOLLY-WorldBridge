"""Scene reconstruction with unscaled entity anchors and separate visuals."""
import json
import traceback
import uuid
from pathlib import Path
import bpy
import bmesh
from mathutils import Matrix, Vector, Quaternion
from .parser import load_backup, plan_entities, vector, rotation, coordinates
from .assets import download, validate_gltf
from .preparation import prepare_backup, save_json
from .materials import repair_materials
from .viewport import after_import


def visual(entity, anchor, collection):
    kind = entity.get('type', 'Unknown')
    shape = entity.get('shape', kind)
    dims = vector(entity, 'dimensions', (0.1, 0.1, 0.1))
    if any(v < 0 for v in dims):
        raise ValueError('Negative dimensions')
    reg = vector(entity, 'registrationPoint', (.5, .5, .5))
    offset = coordinates(tuple((.5-r)*d for r, d in zip(reg, dims)))
    if kind == 'Light':
        data = bpy.data.lights.new(anchor.name, 'SPOT' if entity.get('isSpotlight') else 'POINT')
        data.energy = max(0, float(entity.get('intensity', 1))) * 100
        obj = bpy.data.objects.new(anchor.name + ' light', data)
        # DarkRide spotlight forward -Z maps to Blender +Y.
        obj.rotation_euler[0] = 1.57079632679
    else:
        mesh = bpy.data.meshes.new(anchor.name + ' geometry')
        bm = bmesh.new()
        if shape == 'Sphere':
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=.5)
        elif shape in ('Cylinder', 'Cone'):
            bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=.5, radius2=0 if shape == 'Cone' else .5, depth=1)
        else:
            bmesh.ops.create_cube(bm, size=1)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(anchor.name + ' visual', mesh)
        obj.scale = (dims[0], dims[2], dims[1])
        if kind not in ('Box', 'Sphere', 'Shape') or (kind == 'Shape' and shape not in ('Cube', 'Sphere', 'Cylinder', 'Cone')) or not entity.get('visible', True):
            obj.display_type = 'WIRE'
            obj.hide_render = True
        color = entity.get('color', {})
        obj.color = tuple(float(color.get(k, 180))/255 for k in ('red', 'green', 'blue')) + (1,)
    collection.objects.link(obj)
    obj.parent = anchor
    obj.location = offset
    if kind == 'Light':
        from .lighting import configure
        configure(obj, entity)
    if not entity.get('visible', True):
        obj.hide_render = True
        if kind == 'Light':
            obj.data.energy = 0
    obj['worldbridge_visual'] = True
    obj['worldbridge_role'] = 'PLACEHOLDER' if obj.display_type == 'WIRE' else 'PRIMITIVE'
    return obj


def import_model(path, anchor, entity, collection, validated=False):
    before = set(bpy.data.objects)
    previous_materials = set(bpy.data.materials)
    try:
        if path.suffix in ('.gltf', '.glb'):
            if not validated:
                validate_gltf(path)
            result = bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            result = bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False, use_image_search=False)
        if 'FINISHED' not in result:
            raise ValueError('Blender importer cancelled')
        added = set(bpy.data.objects) - before
        bpy.context.view_layer.update()
        cameras = [obj for obj in added if obj.type == 'CAMERA']
        anchor['worldbridge_embedded_cameras'] = json.dumps([
            dict(name=obj.name, matrix=[list(row) for row in obj.matrix_world],
                 lens=obj.data.lens, clip_start=obj.data.clip_start, clip_end=obj.data.clip_end,
                 type=obj.data.type) for obj in cameras])
        if not getattr(bpy.context.scene, 'worldbridge_import_cameras', False):
            for obj in cameras:
                for child in list(obj.children):
                    matrix = child.matrix_world.copy()
                    child.parent = obj.parent
                    child.matrix_world = matrix
                added.remove(obj)
                camera_data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if camera_data.users == 0:
                    bpy.data.cameras.remove(camera_data)
        points = [obj.matrix_world @ Vector(corner) for obj in added if obj.type == 'MESH' for corner in obj.bound_box]
        if not points:
            raise ValueError('Asset contains no mesh geometry')
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        dims = vector(entity, 'dimensions', (.1, .1, .1))
        target = (dims[0], dims[2], dims[1])
        scale = Vector(tuple(target[i]/(high[i]-low[i]) if high[i]-low[i] > 1e-8 else 1 for i in range(3)))
        reg = vector(entity, 'registrationPoint', (.5, .5, .5))
        offset = Vector(coordinates(tuple((.5-r)*d for r,d in zip(reg,dims))))
        fit = Matrix.Translation(offset) @ Matrix.Diagonal((*scale, 1)) @ Matrix.Translation(-(low+high)/2)
        roots = [obj for obj in added if obj.parent not in added]
        for obj in added:
            obj['worldbridge_role'] = 'MODEL'
            if obj.type == 'LIGHT':
                obj['worldbridge_embedded_light_energy'] = obj.data.energy
                obj['worldbridge_original_energy'] = 0.0
                obj.data.energy = 0
            for old in list(obj.users_collection):
                old.objects.unlink(obj)
            collection.objects.link(obj)
            obj.hide_set(not getattr(bpy.context.scene, 'worldbridge_show_models', True))
            if obj.animation_data:
                obj.animation_data_clear()
        for obj in roots:
            world = obj.matrix_world.copy()
            obj.parent = anchor
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = fit @ world
        materials = {slot.material for obj in added for slot in obj.material_slots
                     if slot.material and slot.material not in previous_materials}
        repairs = repair_materials(path, materials)
        # Recovery is queued after the batch, avoiding synchronous scans per model.
        anchor['worldbridge_texture_diagnostics'] = '[]'
        anchor['worldbridge_material_repairs'] = json.dumps(repairs)
        anchor['worldbridge_model_loaded'] = True
        anchor['worldbridge_cached_asset'] = str(path)
        return len(added)
    except Exception:
        for obj in set(bpy.data.objects) - before:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise


def import_backup_steps(filepath, output_dir, load_models=True, world_positions=False,
                        prepared=None, defer_models=False, model_limit=4, model_filter=''):
    prepared = prepared or prepare_backup(filepath, output_dir)
    records, output, token, sidecar, report_path, report = (prepared[k] for k in
        ('records', 'output', 'token', 'sidecar', 'report_path', 'report'))
    warnings = report['warnings']
    tasks = []
    save_json(report_path, report)
    collection = bpy.data.collections.new('WorldBridge ' + token + ' [IN PROGRESS]')
    bpy.context.scene.collection.children.link(collection)
    collection['worldbridge_sidecar'] = str(sidecar)
    collection['worldbridge_report'] = str(report_path)
    anchors = []
    previous_selection = list(bpy.context.selected_objects)
    previous_active = bpy.context.view_layer.objects.active
    try:
        for r in records:
            e = r['entity']
            obj = bpy.data.objects.new(str(e.get('name') or e.get('type') or 'Entity'), None)
            collection.objects.link(obj)
            obj.empty_display_type = 'PLAIN_AXES'
            obj.empty_display_size = .2
            obj['worldbridge_entity_id'] = str(e.get('id', ''))
            obj['worldbridge_record_index'] = r['index']
            obj['worldbridge_record_key'] = r['key']
            obj['worldbridge_type'] = str(e.get('type', 'Unknown'))
            obj['worldbridge_parent_id'] = str(e.get('parentID', ''))
            obj['worldbridge_model_url'] = str(e.get('modelURL', ''))
            obj['worldbridge_sidecar'] = str(sidecar)
            obj['worldbridge_role'] = 'ANCHOR'
            anchors.append(obj)
            report['represented'] += 1
            yield report
        report['phase'] = 'TRANSFORMS'
        for r, obj in zip(records, anchors):
            e = r['entity']
            try:
                pk = 'localPosition' if 'localPosition' in e else 'position'
                rk = 'localRotation' if 'localRotation' in e else 'rotation'
                obj.location = coordinates(vector(e, pk))
                obj.rotation_mode = 'QUATERNION'
                obj.rotation_quaternion = Quaternion(rotation(e, rk))
                if r['parent'] is not None:
                    obj.parent = anchors[r['parent']]
                if e.get('parentJointIndex', -1) != -1:
                    warnings.append('Record %d: joint parenting approximated at entity origin' % r['index'])
            except Exception as exc:
                warnings.append('Record %d: invalid transform: %s' % (r['index'], exc))
                obj['worldbridge_error'] = str(exc)
            yield report
        if world_positions:
            # Explicit alternative for script exports that store world transforms.
            desired = {o: o.matrix_basis.copy() for o in anchors}
            pending = set(range(len(records)))
            while pending:
                for i in list(pending):
                    p = records[i]['parent']
                    if p is None or p not in pending:
                        o = anchors[i]
                        if 'localPosition' not in records[i]['entity'] and 'localRotation' not in records[i]['entity']:
                            o.matrix_basis = desired[anchors[p]].inverted_safe() @ desired[o] if p is not None else desired[o]
                        pending.remove(i)
                        yield report
        bpy.context.view_layer.update()
        report['phase'] = 'PLACEHOLDERS'
        for r, obj in zip(records, anchors):
            e = r['entity']
            try:
                placeholder = visual(e, obj, collection)
                kind = e.get('type', 'Unknown')
                if kind not in ('Box', 'Sphere', 'Light', 'Model', 'Zone') and not (kind == 'Shape' and e.get('shape') in ('Cube', 'Sphere', 'Cylinder', 'Cone')):
                    warnings.append('Record %d: %s represented approximately' % (r['index'], kind))
                if kind == 'Model':
                    if defer_models:
                        reason = ''
                        if not load_models:
                            reason = 'Model loading disabled'
                        elif not e.get('modelURL'):
                            reason = 'No model URL'
                        elif not e.get('visible', True):
                            reason = 'Invisible model'
                        elif model_filter and model_filter.casefold() not in (str(e.get('name', '')) + ' ' + str(e.get('id', ''))).casefold():
                            reason = 'Name/ID filter'
                        elif model_limit > 0 and len(tasks) >= model_limit:
                            reason = 'Safe test model limit'
                        if reason:
                            report['assets_skipped'] += 1
                            report['skipped'].append(dict(index=r['index'], id=e.get('id'), reason=reason))
                        else:
                            tasks.append(dict(index=r['index'], id=e.get('id'), name=e.get('name', ''), url=e['modelURL'], entity=e))
                    elif load_models and e.get('modelURL') and e.get('visible', True):
                        try:
                            path = download(e['modelURL'], output / 'cache')
                            import_model(path, obj, e, collection)
                            bpy.data.objects.remove(placeholder, do_unlink=True)
                            report['assets_success'] += 1
                        except Exception as exc:
                            report['assets_failed'] += 1
                            report['failures'].append(dict(index=r['index'], id=e.get('id'), url=e.get('modelURL'), error=str(exc)))
                            obj['worldbridge_error'] = str(exc)
                    else:
                        report['assets_skipped'] += 1
            except Exception as exc:
                warnings.append('Record %d: visual failed; anchor retained: %s' % (r['index'], exc))
                obj['worldbridge_error'] = str(exc)
            report['entities_processed'] += 1
            yield report
        report['status'] = 'COMPLETE_WITH_WARNINGS' if warnings or report['assets_failed'] or report['assets_skipped'] else 'COMPLETE'
        if defer_models and tasks:
            report['status'] = 'MODELS_PENDING'
        report['phase'] = report['status']
    except GeneratorExit:
        report['status'] = 'CANCELLED'
        report['phase'] = 'CANCELLED'
        raise
    except Exception:
        report['status'] = 'FAILED_PARTIAL'
        report['fatal_error'] = traceback.format_exc()
        raise
    finally:
        warning = after_import(bpy.context.scene)
        if warning:
            report['warnings'].append(warning)
            if report['status'] == 'COMPLETE':
                report['status'] = report['phase'] = 'COMPLETE_WITH_WARNINGS'
        collection.name = 'WorldBridge ' + token + ' [' + report['status'] + ']'
        collection['worldbridge_status'] = report['status']
        save_json(report_path, report)
        text = bpy.data.texts.new('WorldBridge Report ' + token)
        text.write(json.dumps(report, indent=2))
        collection['worldbridge_report_text'] = text.name
        bpy.context.scene['worldbridge_last_report'] = str(report_path)
        bpy.context.scene['worldbridge_last_status'] = report['status']
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in previous_selection:
            if obj.name in bpy.context.view_layer.objects:
                obj.select_set(True)
        if previous_active and previous_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = previous_active
    if defer_models:
        return collection, report, tasks
    return collection, report


def import_backup(filepath, output_dir, load_models=True, world_positions=False):
    """Synchronous compatibility API for scripts/tests; the UI uses timer steps."""
    steps = import_backup_steps(filepath, output_dir, load_models, world_positions)
    while True:
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value
