"""Actual barrel, hedge and grass FBX texture diagnostics on private local copies."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hashlib
import json
import shutil
import bpy
import worldbridge
from worldbridge.importer import import_backup, import_model
from worldbridge.viewport import owned_objects

worldbridge.register()
rescue = Path(r'C:\Projects\ROBOTDOLLY-Asset-Rescue')
out = ROOT/'build'/('v04-rescue-' + bpy.app.version_string)
out.mkdir(parents=True, exist_ok=True)
names = ['barrell-47d4f4c186d66081.fbx', 'longhedge4-b388b1c698409321.fbx', 'grassesjs-d38d41fd60f1cdc9.fbx']
entities = [{'id': name, 'type': 'Model', 'dimensions': {'x': 1, 'y': 1, 'z': 1}} for name in names]
source = out/'fixtures.json'
source.write_text(json.dumps({'Entities': entities}))
collection, _ = import_backup(source, out, load_models=False)
anchors = {o['worldbridge_entity_id']: o for o in collection.objects if 'worldbridge_entity_id' in o}
rows = []
for entity in entities:
    name = entity['id']
    original = rescue/'originals'/'s3-us-west-1.amazonaws.com'/name
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    local = out/name
    shutil.copyfile(original, local)
    anchor = anchors[name]
    import_model(local, anchor, entity, collection)
    images = {node.image for obj in owned_objects(anchor) for slot in obj.material_slots
              if slot.material and slot.material.use_nodes for node in slot.material.node_tree.nodes
              if node.type == 'TEX_IMAGE' and node.image}
    rows.append(dict(model=name, diagnostics=json.loads(anchor['worldbridge_texture_diagnostics']),
                     images=[dict(name=i.name, filepath=i.filepath, packed=bool(i.packed_file),
                                  exists=Path(bpy.path.abspath(i.filepath)).is_file()) for i in images]))
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
(out/'result.json').write_text(json.dumps(rows, indent=2))
print('RESCUE_DIAGNOSTICS', json.dumps(rows), flush=True)
worldbridge.unregister()
