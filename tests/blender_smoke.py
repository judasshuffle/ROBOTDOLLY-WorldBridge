import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import gzip
import json
import math
import worldbridge
from worldbridge.importer import import_backup, import_model
from mathutils import Vector

worldbridge.register()
original = set(bpy.data.objects)
data = {'Version': 1, 'Entities': [
    {'id': 'parent', 'name': 'Parent', 'type': 'Box', 'position': {'x': 10}, 'dimensions': {'x': 4, 'y': 6, 'z': 8}, 'rotation': {'w': math.sqrt(.5), 'y': math.sqrt(.5)}, 'registrationPoint': {'x': 0, 'y': 0, 'z': 0}},
    {'id': 'child', 'type': 'Sphere', 'parentID': 'parent', 'position': {'x': 2}, 'dimensions': {'x': 1, 'y': 1, 'z': 1}},
    {'id': 'bad-model', 'type': 'Model', 'modelURL': 'atp:/missing.fbx'},
    {'id': 'zone', 'type': 'Zone'},
    {'id': 'light', 'type': 'Light'},
    {'id': 'unknown', 'type': 'NewUnknownType', 'script': 'NEVER EXECUTE'},
    {'id': 'broken', 'type': 'Box', 'position': {'x': 'bad'}},
    {'id': 'orphan', 'type': 'Box', 'parentID': 'absent'},
]}
source = ROOT/'build'/'smoke.json.gz'
source.write_bytes(gzip.compress(json.dumps(data).encode()))
before = source.read_bytes()
collection, report = import_backup(source, ROOT/'build'/'smoke-output', True)
bpy.context.view_layer.update()
anchors = {o['worldbridge_entity_id']: o for o in collection.objects if 'worldbridge_entity_id' in o}
assert len(anchors) == 8
assert anchors['child'].parent == anchors['parent']
assert (anchors['child'].matrix_world.translation - Vector((10, 2, 0))).length < 1e-5, anchors['child'].matrix_world
parent_visual = next(o for o in anchors['parent'].children if o.get('worldbridge_visual'))
assert (parent_visual.location - Vector((2, -4, 3))).length < 1e-5
assert all(abs(v-1) < 1e-6 for v in anchors['parent'].scale)
assert report['assets_failed'] == 1
assert report['status'] == 'COMPLETE_WITH_WARNINGS'
assert json.loads(Path(report['sidecar']).read_text()) == data
assert source.read_bytes() == before
assert original.issubset(set(bpy.data.objects))
# Exercise built-in importers using locally generated assets, no network.
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
for suffix in ('glb', 'gltf', 'fbx'):
    path = ROOT/'build'/('fixture.'+suffix)
    if suffix == 'fbx':
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, bake_anim=False)
    elif suffix == 'glb':
        bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True)
    else:
        import struct, base64
        raw = (ROOT/'build'/'fixture.glb').read_bytes()
        length = struct.unpack('<I', raw[12:16])[0]
        doc = json.loads(raw[20:20+length])
        binary = raw[28+length:]
        doc['buffers'][0]['uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode()
        path.write_text(json.dumps(doc))
    count = import_model(path, anchors['bad-model'], {'dimensions': {'x': 2, 'y': 4, 'z': 6}}, collection)
    assert count > 0
    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
bpy.data.objects.remove(cube, do_unlink=True)
worldbridge.unregister()
print('WORLDBRIDGE_SMOKE_PASS', bpy.app.version_string, json.dumps(report))
