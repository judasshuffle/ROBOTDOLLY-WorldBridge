"""Local-only headless integration; never downloads or changes rescue fixtures."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hashlib
import json
import time
import bpy
import worldbridge
from worldbridge import ui, viewport
from worldbridge.parser import load_backup
from worldbridge.importer import import_backup, import_model
from worldbridge.session import ImportSession
from worldbridge.textures import repair_images

OUT = ROOT/'build'/('v04-' + bpy.app.version_string.replace(' ', '-'))
OUT.mkdir(parents=True, exist_ok=True)
RESCUE = Path(r'C:\Projects\ROBOTDOLLY-Asset-Rescue')
PLAIN = RESCUE/'WorldBridge-BLENDER-TEST.json'
GZIP = RESCUE/'TEST-EXPORT-20261022T082359'/'ROBOTDOLLY-TEST-RESTORED-ORIGINAL-GITHUB.json.gz'
worldbridge.register()
scene = bpy.context.scene
originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (PLAIN, GZIP)}


def snapshot(collection):
    bpy.context.view_layer.update()
    return {o['worldbridge_record_index']: dict(id=o['worldbridge_entity_id'],
            parent=o.parent.get('worldbridge_record_index') if o.parent else None,
            matrix=[list(row) for row in o.matrix_world], url=o['worldbridge_model_url'])
            for o in collection.objects if 'worldbridge_entity_id' in o}


def clear_collection(collection):
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


first, report = import_backup(PLAIN, OUT, load_models=False)
a = snapshot(first)
assert len(a) == 2121
assert sum(o.type == 'LIGHT' for o in first.objects) == 225
assert not any(o.type == 'CAMERA' for o in first.objects)
clear_collection(first)
second, report = import_backup(GZIP, OUT, load_models=False)
assert snapshot(second) == a
assert load_backup(report['sidecar']) == load_backup(PLAIN)
clear_collection(second)

# Exercise the registered WorldBridge ZIP import operator (not add-on install).
archive = RESCUE/'world-export-20261021T114810Z'/'ROBOTDOLLY-WORLD-ALL-VERIFIED-REPAIRS-TEST.content.zip'
assert bpy.ops.worldbridge.import_backup(filepath=str(archive), output_dir=str(OUT), load_models=False) == {'FINISHED'}
deadline = time.monotonic() + 60
while not ui._SESSION.done:
    assert time.monotonic() < deadline
    ui._SESSION.tick()
    time.sleep(.001)
assert ui._SESSION.report['represented'] == 2121, ui._SESSION.report
assert ui._SESSION.report['archive_member'] == 'models.json.gz'
clear_collection(ui._SESSION.collection)
ui.stop_session('test cleanup')
assert '*.zip' in bpy.ops.worldbridge.import_backup.get_rna_type().properties['filter_glob'].default

# Spatial selection at three elevations, including a parented model.
data = {'Entities': [
    {'id': 'parent', 'type': 'Box', 'position': {'x': 10}},
    {'id': 'low', 'parentID': 'parent', 'type': 'Model', 'position': {'x': 1},
     'dimensions': {'x': 4, 'y': 4, 'z': 4}, 'modelURL': 'https://example.test/shared.fbx'},
    {'id': 'high', 'type': 'Model', 'position': {'x': 11, 'y': 20}, 'modelURL': 'https://example.test/shared.fbx'},
    {'id': 'lamp', 'type': 'Light', 'position': {'x': 11}, 'intensity': 3},
    {'id': 'outside-lamp', 'type': 'Light', 'position': {'x': 50}, 'intensity': 2}]}
source = OUT/'selection.json'
source.write_text(json.dumps(data))
collection, _ = import_backup(source, OUT, load_models=False)
anchors = {o['worldbridge_entity_id']: o for o in collection.objects if 'worldbridge_entity_id' in o}
assert anchors['low'].parent == anchors['parent']
bpy.ops.worldbridge.create_region()
region = scene.worldbridge_region
region.location = (11, 0, 0)
region.scale = (1, 1, 1)
assert anchors['low'] in viewport.region_anchors(bpy.context)
assert anchors['high'] not in viewport.region_anchors(bpy.context)
region.location.x = 13
assert anchors['low'] not in viewport.region_anchors(bpy.context)
scene.worldbridge_region_bounds = True
assert anchors['low'] in viewport.region_anchors(bpy.context)
region.scale.z = 0
try:
    viewport.region_anchors(bpy.context)
    raise AssertionError('Zero region accepted')
except ValueError:
    pass
region.scale.z = 1
region.location.x = 11
scene.worldbridge_region_bounds = False
bpy.context.view_layer.update()
scene.worldbridge_lights_region_only = True
viewport.apply_lighting(scene)
lamp = next(o for o in anchors['lamp'].children if o.type == 'LIGHT')
outside = next(o for o in anchors['outside-lamp'].children if o.type == 'LIGHT')
lamp_power = lamp['worldbridge_original_energy']
outside_power = outside['worldbridge_original_energy']
assert abs(lamp.data.energy-lamp_power)<1e-5 and outside.data.energy == 0
scene.worldbridge_show_lights = False
assert not lamp.hide_get() and abs(lamp.data.energy-lamp_power)<1e-5
scene.worldbridge_enable_lights = False
assert lamp.data.energy == 0
scene.worldbridge_enable_lights = True
scene.worldbridge_lights_region_only = False
assert abs(lamp.data.energy-lamp_power)<1e-5 and abs(outside.data.energy-outside_power)<1e-5
scene.worldbridge_show_lights = True

# Build a tiny FBX containing mesh, camera and light, then import via the queue.
for o in bpy.context.selected_objects:
    o.select_set(False)
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
bpy.ops.object.camera_add()
camera = bpy.context.object
bpy.ops.object.light_add(type='POINT')
light = bpy.context.object
for o in (cube, camera, light):
    o.select_set(True)
fixture = OUT/'embedded.fbx'
bpy.ops.export_scene.fbx(filepath=str(fixture), use_selection=True, bake_anim=False)
for o in (cube, camera, light):
    bpy.data.objects.remove(o, do_unlink=True)
calls = []
def fetch(task, event):
    calls.append(task['id'])
    return fixture
job = ImportSession('', OUT, existing_targets=[anchors['low']], model_limit=0, downloader=fetch)
deadline = time.monotonic() + 30
while not job.done:
    assert time.monotonic() < deadline
    job.tick()
    time.sleep(.001)
assert job.report['assets_success'] == 1, job.report
assert calls == ['low']
assert not any(o.type == 'CAMERA' for o in viewport.owned_objects(anchors['low']))
assert len(json.loads(anchors['low']['worldbridge_embedded_cameras'])) == 1
assert anchors['low'].parent == anchors['parent']
owned = list(viewport.owned_objects(anchors['low']))
assert any(o.type == 'LIGHT' for o in owned)
model = next(o for o in owned if o.type == 'MESH')
for o in bpy.context.selected_objects:
    o.select_set(False)
model.select_set(True)
assert viewport.selected_anchors(bpy.context) == [anchors['low']]
again = ImportSession('', OUT, existing_targets=[anchors['low']], model_limit=0, downloader=fetch)
while not again.done:
    again.tick()
    time.sleep(.001)
assert calls == ['low'] and again.report['assets_skipped'] == 1

# Read actual rescue resources, copying only recovered image bytes to test cache.
texture_results = []
for filename in ('hedgedif.jpg', 'judgrass.png', 'definitely-missing-barrel.png'):
    material = bpy.data.materials.new('Rescue ' + filename)
    material.use_nodes = True
    node = material.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = bpy.data.images.new(filename, 1, 1)
    node.image.filepath = 'Z:/missing/' + filename
    result = repair_images([material], OUT/'cache', str(RESCUE))
    assert result
    texture_results += result
assert texture_results[0]['status'] == 'missing', texture_results  # v0.5 requires provenance, not a basename guess.
assert texture_results[1]['status'] == 'missing', texture_results
for p, digest in originals.items():
    assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
result = dict(blender=bpy.app.version_string, genuine_entities=2121,
              genuine_lights=225, genuine_cameras=0, equivalent_transforms=True,
              spatial_selection=True, duplicate_prevention=True, camera_suppression=True,
              light_controls=True, textures=texture_results, source_hashes={str(p): h for p,h in originals.items()})
(OUT/'result.json').write_text(json.dumps(result, indent=2))
worldbridge.unregister()
print('V04_HEADLESS_PASS', json.dumps(result), flush=True)
