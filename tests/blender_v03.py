"""Headless v0.3 regression: viewport, real cached materials, targeted loading."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import copy
import gzip
import hashlib
import json
import shutil
import struct
import time
import threading
import urllib.parse
from unittest.mock import patch
import bpy
import worldbridge
from worldbridge import viewport, ui
from worldbridge.session import ImportSession
from worldbridge.materials import repair_materials, repair_existing
from mathutils import Vector

OUT = ROOT/'build'/'v03-tests'
OUT.mkdir(exist_ok=True)
worldbridge.register()
scene = bpy.context.scene
camera = scene.camera
camera_clip = (camera.data.clip_start, camera.data.clip_end)
areas = list(bpy.context.screen.areas)
extra = next(a for a in areas if a.type != 'VIEW_3D')
extra.type = 'VIEW_3D'
assert viewport.apply_clipping(scene) >= 2
for _, space in viewport.viewports():
    assert abs(space.clip_start-.01) < 1e-6 and space.clip_end == 100000
scene.worldbridge_clip_start = .1
scene.worldbridge_clip_end = 25000
viewport.after_import(scene)
assert all(s.clip_end == 25000 for _, s in viewport.viewports())
first = next(viewport.viewports())[1]
first.clip_end = 12345
viewport.after_import(scene)
assert first.clip_end == 12345  # Native viewport edit survives another import.
viewport.apply_clipping(scene)
assert first.clip_end == 25000  # Explicit Apply intentionally synchronises.
assert (camera.data.clip_start, camera.data.clip_end) == camera_clip

backup = ROOT/'test-backup'/'models.json.gz'
backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
entities = json.load(gzip.open(backup, 'rt', encoding='utf-8'))['Entities']
chosen, originals = [], {}
for filename in ('crate1.fbx', 'GLASSFRONTCUPBOARD4.fbx'):
    e = next(e for e in entities if e.get('modelURL', '').endswith('/'+filename))
    cache_name = hashlib.sha256(e['modelURL'].encode()).hexdigest()+'.fbx'
    cache = ROOT/'imports'/'cache'/cache_name
    assert cache.is_file(), cache
    originals[cache] = hashlib.sha256(cache.read_bytes()).hexdigest()
    (OUT/'cache').mkdir(exist_ok=True)
    shutil.copyfile(cache, OUT/'cache'/cache_name)
    chosen.append(copy.deepcopy(e))

def principled(material):
    return next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')

# Demonstrate the unmodified native importer bug before WorldBridge repair.
before = set(bpy.data.objects)
before_mats = set(bpy.data.materials)
crate_path = next(iter(originals))
bpy.ops.import_scene.fbx(filepath=str(crate_path), use_anim=False, use_image_search=False)
raw_materials = set(bpy.data.materials)-before_mats
assert raw_materials and all(principled(m).inputs['Alpha'].default_value == 0 for m in raw_materials)
for obj in set(bpy.data.objects)-before:
    bpy.data.objects.remove(obj, do_unlink=True)

# Deliberate alpha wiring / transmission must veto the legacy repair.
candidate = next(iter(raw_materials))
image = candidate.node_tree.nodes.new('ShaderNodeTexImage')
alpha = principled(candidate).inputs['Alpha']
link = candidate.node_tree.links.new(image.outputs['Alpha'], alpha)
assert repair_materials(crate_path, [candidate]) == []
assert alpha.is_linked and alpha.default_value == 0
candidate.node_tree.links.remove(link)
principled(candidate).inputs['Transmission Weight'].default_value = .5
assert repair_materials(crate_path, [candidate]) == []
assert alpha.default_value == 0

for i, e in enumerate(chosen):
    e.update(id='test-%d'%i, name='Test %d'%i, parentID='', position={'x': i*10, 'y': 0, 'z': 0},
             rotation={'w': 1, 'x': 0, 'y': 0, 'z': 0})
third = copy.deepcopy(chosen[0])
third.update(id='test-2', name='Region crate', position={'x': 100, 'y': 0, 'z': 0})
chosen.append(third)
source = OUT/'selected.json'
source.write_text(json.dumps({'Entities': chosen}), encoding='utf-8')

def complete(job):
    deadline = time.monotonic()+45
    while not job.done:
        assert time.monotonic() < deadline, job.report
        job.tick()
        time.sleep(.001)
    assert job.report['status'] not in ('FAILED', 'FAILED_PARTIAL'), job.report

plain = ImportSession(source, OUT, load_models=False)
complete(plain)
anchors = sorted([o for o in plain.collection.objects if 'worldbridge_entity_id' in o], key=lambda o:o['worldbridge_record_index'])
bpy.context.view_layer.update()
snapshots = {o: o.matrix_world.copy() for o in anchors}
sidecar = Path(plain.report['sidecar'])
sidecar_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()
assert all(o.hide_get() for o in anchors)
for anchor in anchors:
    anchor.hide_set(False)
ui.initialize_viewport()  # Saved v0.2 scenes receive visibility settings too.
assert all(o.hide_get() for o in anchors)
assert all(not next(iter(o.children)).hide_get() for o in anchors)
scene.worldbridge_show_placeholders = False
assert all(next(iter(o.children)).hide_get() for o in anchors)
scene.worldbridge_show_anchors = True
assert all(not o.hide_get() for o in anchors)
scene.worldbridge_show_placeholders = True

# The default downloader must use the real pre-populated cache, with no HTTP.
with patch('worldbridge.assets.urllib.request.build_opener', side_effect=AssertionError('Unexpected network request')):
    selected = ImportSession('', OUT, existing_targets=anchors[:2], model_limit=4)
    complete(selected)
assert selected.report['assets_success'] == 2, selected.report
assert selected.report['assets_failed'] == 0
assert len(selected.report['material_repairs']) == 2
crate_mats = {s.material for o in viewport.owned_objects(anchors[0]) for s in o.material_slots if s.material}
assert crate_mats and all(principled(m).inputs['Alpha'].default_value == 1 for m in crate_mats)
assert any(principled(m).inputs['Base Color'].is_linked for m in crate_mats)
cupboard_mats = {s.material for o in viewport.owned_objects(anchors[1]) for s in o.material_slots if s.material}
glass = next(m for m in cupboard_mats if m.name.startswith('newgla'))
wood = next(m for m in cupboard_mats if m.name.startswith('newwood'))
assert principled(glass).inputs['Alpha'].is_linked
assert principled(glass).inputs['Alpha'].default_value == 0
assert principled(wood).inputs['Alpha'].default_value == 1

# Existing imported models can be repaired without changing shared originals.
# Remove v0.3 tags to exercise an existing v0.2 scene's parent/sidecar discovery.
for obj in viewport.owned_objects(anchors[0]):
    del obj['worldbridge_role']
del anchors[0]['worldbridge_cached_asset']
del anchors[0]['worldbridge_model_loaded']
for m in crate_mats:
    principled(m).inputs['Alpha'].default_value = 0
assert repair_existing([anchors[0]])
assert all(principled(s.material).inputs['Alpha'].default_value == 1
           for o in viewport.owned_objects(anchors[0]) for s in o.material_slots if s.material)
assert all(principled(m).inputs['Alpha'].default_value == 0 for m in crate_mats)

scene.worldbridge_show_models = False
models = [o for a in anchors[:2] for o in viewport.owned_objects(a)]
assert all(o.hide_get() for o in models)
scene.worldbridge_show_anchors = False
scene.worldbridge_show_models = True
assert all(not o.hide_get() for o in models)
assert all(o.visible_get() for o in models if o.type == 'MESH')
assert all(o.hide_get() for o in anchors)
for anchor, matrix in snapshots.items():
    assert anchor.matrix_world == matrix
bpy.context.view_layer.update()
low, high = viewport.entity_bounds(anchors)
assert viewport.frame_entities(anchors) >= 2
assert (first.region_3d.view_location-(low+high)*.5).length < 1e-4
assert viewport.frame_entities([anchors[0]]) >= 2
assert (camera.data.clip_start, camera.data.clip_end) == camera_clip

count = len(bpy.data.objects)
repeated = ImportSession('', OUT, existing_targets=anchors[:2])
complete(repeated)
assert repeated.report['assets_success'] == 0 and repeated.report['assets_skipped'] == 2
assert len(bpy.data.objects) == count

# Targeted loading retains cooperative cancellation while a download is pending.
from worldbridge.assets import DownloadCancelled
entered, release = threading.Event(), threading.Event()
def delayed(task, event):
    entered.set()
    release.wait(5)
    if event.is_set():
        raise DownloadCancelled('Targeted loading cancelled')
    return crate_path
cancelled = ImportSession('', OUT, existing_targets=[anchors[2]], downloader=delayed)
deadline = time.monotonic()+10
while not entered.is_set():
    assert time.monotonic() < deadline
    cancelled.tick()
    time.sleep(.001)
cancelled.cancel()
release.set()
cancelled.assets.worker.thread.join(2)
assert cancelled.report['status'] == 'CANCELLED' and cancelled.report['assets_cancelled'] == 1
assert any(obj.get('worldbridge_visual') for obj in anchors[2].children)

# Exercise selected-entity and spatial-region UI routes without re-importing a world.
for o in bpy.context.selected_objects:
    o.select_set(False)
mesh = next(o for o in viewport.owned_objects(anchors[0]) if o.type == 'MESH')
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
assert viewport.selected_anchors(bpy.context) == [anchors[0]]
assert bpy.ops.worldbridge.load_selected_models() == {'FINISHED'}
complete(ui._SESSION)
assert ui._SESSION.report['assets_skipped'] == 1
ui.stop_session('Test timer cleanup')
scene.worldbridge_region_min = (99, -1, -1)
scene.worldbridge_region_max = (101, 1, 1)
with patch('worldbridge.assets.urllib.request.build_opener', side_effect=AssertionError('Unexpected network request')):
    assert bpy.ops.worldbridge.load_selected_models(use_region=True) == {'FINISHED'}
    complete(ui._SESSION)
assert ui._SESSION.report['assets_success'] == 1
assert ui._SESSION.report['entities'] == 1
ui.stop_session('Test timer cleanup')
assert len([o for o in plain.collection.objects if 'worldbridge_entity_id' in o]) == 3
assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == sidecar_hash
assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash
for p, digest in originals.items():
    assert hashlib.sha256(p.read_bytes()).hexdigest() == digest

# glTF OPAQUE/BLEND/MASK are left to native metadata interpretation.
fixture = ROOT/'build'/'fixture.glb'
raw = fixture.read_bytes()
length = struct.unpack('<I', raw[12:16])[0]
doc = json.loads(raw[20:20+length])
binary_chunk = raw[20+length:]
doc['materials'] = [{'name':'AlphaMode-'+mode, 'alphaMode':mode,
                     'pbrMetallicRoughness':{'baseColorFactor':[1,1,1,alpha]}}
                    for mode,alpha in [('OPAQUE',0),('BLEND',.25),('MASK',.4)]]
original_mesh = copy.deepcopy(doc['meshes'][0])
doc['meshes'] = [copy.deepcopy(original_mesh) for _ in range(3)]
for i, model in enumerate(doc['meshes']):
    for primitive in model['primitives']: primitive['material'] = i
doc['nodes'] = [{'mesh':i} for i in range(3)]
doc['scenes'] = [{'nodes':[0,1,2]}]
doc['scene'] = 0
encoded = json.dumps(doc).encode()
encoded += b' ' * ((-len(encoded))%4)
chunk = struct.pack('<I4s',len(encoded),b'JSON') + encoded
path = OUT/'alpha-modes.glb'
path.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(chunk)+len(binary_chunk)) + chunk + binary_chunk)
from worldbridge.importer import import_model
before_mats = set(bpy.data.materials)
import_model(path, anchors[2], chosen[2], plain.collection)
for material in set(bpy.data.materials)-before_mats:
    alpha = principled(material).inputs['Alpha'].default_value
    # MASK .4 is below the default .5 cutoff and should remain fully cut out.
    expected = 1 if material.name.startswith('AlphaMode-OPAQUE') else .25 if material.name.startswith('AlphaMode-BLEND') else 0
    assert abs(alpha-expected) < 1e-5, (material.name,alpha)
worldbridge.unregister()
assert not bpy.app.timers.is_registered(ui.initialize_viewport)
print('WORLDBRIDGE_V03_PASS', bpy.app.version_string,
      'multi-viewport clipping + user overrides, camera unchanged, reversible visibility, framing, real cached crate/wood repair, glass and alpha links preserved, GLB alpha modes, selected/cache/region loading, duplicate prevention, source preservation')
