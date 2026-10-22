"""Headless scheduler/Blender integration. Does NOT verify interactive UI latency."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import json
import threading
import time
import bpy
import worldbridge
from worldbridge import session as module
from worldbridge.runtime import LOG_PATH
from worldbridge.assets import DownloadCancelled

OUT = ROOT/'build'/'incremental-tests'
OUT.mkdir(exist_ok=True)
worldbridge.register()
existing = set(bpy.data.objects)
bpy.ops.mesh.primitive_cube_add()
cube = bpy.context.object
fixture = OUT/'fixture.glb'
bpy.ops.export_scene.gltf(filepath=str(fixture), export_format='GLB', use_selection=True)
bpy.data.objects.remove(cube, do_unlink=True)
bad = OUT/'broken.fbx'
bad.write_bytes(b'not an FBX')
entities = [{'id': 'box-%d'%i, 'type': 'Box'} for i in range(60)]
entities += [{'id': 'model-%d'%i, 'name': 'Model %d'%i, 'type': 'Model',
              'modelURL': 'https://example.test/%d.glb'%i} for i in range(6)]
source = OUT/'backup.json'
source.write_text(json.dumps({'Entities': entities, 'unknown': {'preserve': True}}))
source_bytes = source.read_bytes()


def advance_until(session, predicate, seconds=10):
    deadline = time.monotonic()+seconds
    ticks = 0
    while not predicate():
        assert time.monotonic() < deadline, (session.report, 'timeout')
        session.tick()
        ticks += 1
        time.sleep(.002)
    return ticks


calls = []


def fetch(task, event):
    assert threading.current_thread() is not threading.main_thread()
    calls.append(task['id'])
    if task['id'] == 'model-0':
        raise TimeoutError('intentional download failure')
    return bad if task['id'] == 'model-1' else fixture


imports = []
original_import = module.import_model


def checked_import(*args, **kwargs):
    assert threading.current_thread() is threading.main_thread()
    imports.append(str(args[0]))
    return original_import(*args, **kwargs)


module.import_model = checked_import
job = module.ImportSession(source, OUT, downloader=fetch)
ticks = advance_until(job, lambda: job.assets is not None)
assert ticks >= 8, ticks  # More than one batch is required for 66 entities.
assert job.report['entities_processed'] == 66
assert job.report['assets_skipped'] == 2
assert len(job.assets.tasks) == 4
while not job.done:
    count = len(imports)
    job.tick()
    assert len(imports)-count <= 1
    time.sleep(.002)
assert job.report['assets_failed'] == 2, job.report
assert job.report['assets_success'] == 2
assert job.report['assets_downloaded'] == 3
assert [f['stage'] for f in job.report['failures']] == ['download', 'import']
assert len(calls) == 4
anchors = {o['worldbridge_entity_id']: o for o in job.collection.objects if 'worldbridge_entity_id' in o}
assert len(anchors) == 66
for i in (0, 1, 4, 5):
    assert any(o.get('worldbridge_visual') for o in anchors['model-%d'%i].children)
for i in (2, 3):
    assert not any(o.get('worldbridge_visual') for o in anchors['model-%d'%i].children)
assert json.loads(Path(job.report['sidecar']).read_text()) == json.loads(source_bytes)
assert json.loads(job.report_path.read_text()) == job.report
assert existing.issubset(set(bpy.data.objects))
assert source.read_bytes() == source_bytes
assert 'intentional download failure' in LOG_PATH.read_text()
assert 'model_import_started' in LOG_PATH.read_text()

# Cancel part-way through entity creation: preserved partial collection and source.
partial = module.ImportSession(source, OUT, load_models=False)
advance_until(partial, lambda: partial.steps is not None)
partial.tick()
assert 0 < partial.report['represented'] < 66
partial.cancel()
assert partial.done and partial.report['status'] == 'CANCELLED'
assert partial.collection is not None
assert json.loads(partial.report_path.read_text())['status'] == 'CANCELLED'

# A blocked download cannot block ticks/cancellation or create late Blender objects.
entered, release = threading.Event(), threading.Event()


def blocked(task, event):
    entered.set()
    release.wait(5)
    if event.is_set():
        raise DownloadCancelled('test cancellation acknowledged')
    return fixture


cancelled = module.ImportSession(source, OUT, downloader=blocked)
advance_until(cancelled, lambda: cancelled.assets is not None and cancelled.assets.worker is not None)
assert entered.wait(2)
start = time.monotonic()
for _ in range(20):
    cancelled.tick()
assert time.monotonic()-start < 1
cancelled.cancel()
count = len(bpy.data.objects)
assert cancelled.report['assets_cancelled'] == 4
assert cancelled.report['status'] == 'CANCELLED'
release.set()
cancelled.assets.worker.thread.join(2)
assert not cancelled.assets.worker.thread.is_alive()
assert cancelled.tick() is None
assert len(bpy.data.objects) == count

# Placeholder-only route performs zero model requests and completes all entities.
plain = module.ImportSession(source, OUT, load_models=False, downloader=lambda *_: (_ for _ in ()).throw(AssertionError('No network expected')))
advance_until(plain, lambda: plain.done)
assert plain.report['entities_processed'] == 66
assert plain.report['assets_skipped'] == 6
assert plain.report['assets_success'] == 0

# Filter applies before limit; cancellation after download readiness never imports.
filtered = module.ImportSession(source, OUT, model_filter='model-5', downloader=lambda *_: fixture)
advance_until(filtered, lambda: filtered.assets is not None and filtered.assets.ready is not None)
assert len(filtered.assets.tasks) == 1
assert filtered.assets.tasks[0]['id'] == 'model-5'
count = len(imports)
filtered.cancel()
filtered.tick()
assert len(imports) == count

# Actual operators register/unregister the timer and expose cancellation.
from worldbridge import ui
assert bpy.ops.worldbridge.import_backup(filepath=str(source), output_dir=str(OUT), load_models=False) == {'FINISHED'}
assert bpy.app.timers.is_registered(ui.timer_tick)
assert bpy.ops.worldbridge.cancel_import() == {'FINISHED'}
assert not bpy.app.timers.is_registered(ui.timer_tick)
assert ui._SESSION.done
ui._SESSION.worker.thread.join(2)
module.import_model = original_import
worldbridge.unregister()
assert source.read_bytes() == source_bytes
print('WORLDBRIDGE_INCREMENTAL_PASS', bpy.app.version_string,
      'incremental entities, main-thread imports, off-thread downloads, failures, limit/filter, logging, cancellation, timer lifecycle')
