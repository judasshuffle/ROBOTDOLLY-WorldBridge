"""Compare v0.2 placeholders against preserved v0.1 on the local domain backup."""
import sys
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from zipfile import ZipFile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from worldbridge.session import ImportSession

source = ROOT/'test-backup'/'models.json.gz'
if not source.exists():
    raise RuntimeError('Optional real-domain test requires test-backup/models.json.gz')
original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
baseline_root = ROOT/'build'/'v01-comparison-source'
with ZipFile(ROOT/'build'/'worldbridge-v0.1-source-backup.zip') as archive:
    for name in archive.namelist():
        if name.startswith('worldbridge/') and name.endswith('.py'):
            target = baseline_root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
spec = importlib.util.spec_from_file_location('worldbridge_v01', baseline_root/'worldbridge'/'__init__.py',
                                            submodule_search_locations=[str(baseline_root/'worldbridge')])
package = importlib.util.module_from_spec(spec)
sys.modules['worldbridge_v01'] = package
spec.loader.exec_module(package)
from worldbridge_v01.importer import import_backup


def snapshot(collection):
    bpy.context.view_layer.update()
    result = {}
    for obj in collection.objects:
        if 'worldbridge_record_index' in obj:
            result[obj['worldbridge_record_index']] = dict(
                id=obj['worldbridge_entity_id'],
                parent=obj.parent.get('worldbridge_record_index') if obj.parent else None,
                matrix=[x for row in obj.matrix_world for x in row],
                visuals=[[x for row in child.matrix_world for x in row]
                         for child in obj.children if child.get('worldbridge_visual')])
    return result


baseline, old_report = import_backup(source, ROOT/'build'/'real-v01-output', False)
expected = snapshot(baseline)
job = ImportSession(source, ROOT/'build'/'real-v02-output', load_models=False)
deadline = time.monotonic()+120
ticks = 0
while not job.done:
    assert time.monotonic() < deadline, 'real backup timed out'
    job.tick()
    ticks += 1
    time.sleep(.001)
actual = snapshot(job.collection)
assert actual == expected, 'v0.2 differs from v0.1 placeholder hierarchy or transforms'
assert job.report['entities_processed'] == old_report['represented'] == 2121
assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
assert json.loads(Path(job.report['sidecar']).read_text(encoding='utf-8')) == json.loads(Path(old_report['sidecar']).read_text(encoding='utf-8'))
print('WORLDBRIDGE_REAL_BACKUP_PASS', bpy.app.version_string,
      '2121 entities; v0.1/v0.2 hierarchy, anchor and visual matrices identical; sidecar identical; source unchanged;', ticks, 'ticks')
