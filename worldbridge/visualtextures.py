"""Incremental texture repair: worker I/O and main-thread Blender relinking."""
import json
import re
import threading
import uuid
from pathlib import Path
from .recovery import recover


def semantic(node):
    name = (node.image.name+' '+node.label+' '+node.name).lower()
    for kind, pattern in (('normal', r'normal|(?:^|[_ .-])nrm(?:[_ .-]|$)'),
                          ('metallic', r'metallic|metalness'), ('roughness', r'roughness'),
                          ('glossiness', r'glossiness|glossmap'), ('basecolor', r'base.?colou?r|albedo|diffuse')):
        if re.search(pattern, name):
            return kind
    destinations = {link.to_socket.name for output in node.outputs for link in output.links}
    if any(link.to_node.type == 'NORMAL_MAP' for output in node.outputs for link in output.links):
        return 'normal'
    for socket, kind in (('Base Color', 'basecolor'), ('Metallic', 'metallic'), ('Roughness', 'roughness'),
                         ('Alpha', 'opacity'), ('Emission Color', 'emission'), ('Specular IOR Level', 'specular')):
        if socket in destinations:
            return kind
    return 'unknown'


def snapshot(materials, model_path='', model_url=''):
    import bpy
    bindings, requests = {}, []
    for material in materials:
        if not material.use_nodes:
            continue
        if 'worldbridge_original_nodes' not in material:
            material['worldbridge_original_nodes'] = json.dumps(dict(
                links=[(l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name) for l in material.node_tree.links],
                inputs={n.name: {s.name: str(s.default_value) for s in n.inputs if hasattr(s, 'default_value')}
                        for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'}))
        for node in material.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            image = node.image
            key = uuid.uuid4().hex
            bindings[key] = (material, node)
            reference = image.get('worldbridge_original_path', image.filepath)
            requests.append(dict(key=key, reference=reference, original_name=image.name, semantic=semantic(node),
                                 model_path=str(model_path), model_url=model_url,
                                 existing=str(Path(bpy.path.abspath(image.filepath))), packed=bool(image.packed_file)))
    return bindings, requests


def apply(bindings, row):
    import bpy
    material, node = bindings[row['key']]
    if row['status'] != 'recovered':
        return
    kind = row['semantic']
    colorspace = 'Non-Color' if kind in ('normal', 'metallic', 'roughness', 'glossiness', 'opacity', 'specular') else 'sRGB'
    image = next((i for i in bpy.data.images if i.get('worldbridge_recovery_path') == row['output']
                  and i.colorspace_settings.name == colorspace), None)
    if image is None:
        image = bpy.data.images.load(row['output'], check_existing=False)
        image.colorspace_settings.name = colorspace
        if len(image.pixels):
            _ = image.pixels[0]
        if not image.has_data:
            raise ValueError('Blender could not decode recovered image')
        image['worldbridge_recovery_path'] = row['output']
        image['worldbridge_original_path'] = row['reference']
        image['worldbridge_source_sha256'] = row['source_sha256']
    node.image = image
    row['loaded'], row['colorspace'] = bool(image.has_data), colorspace
    tree = material.node_tree
    for link in list(node.outputs['Color'].links):
        if link.to_node.type != 'BSDF_PRINCIPLED':
            continue
        target = link.to_node
        if kind == 'metallic' and link.to_socket.name in ('Specular IOR Level', 'Roughness', 'Metallic'):
            if link.to_socket.name != 'Metallic':
                row.setdefault('material_changes', []).append(link.to_socket.name+' -> Metallic (explicit image semantic)')
                tree.links.remove(link)
                tree.links.new(node.outputs['Color'], target.inputs['Metallic'])
        elif kind == 'glossiness' and link.to_socket.name == 'Roughness':
            invert = tree.nodes.new('ShaderNodeMath')
            invert.operation = 'SUBTRACT'
            invert.inputs[0].default_value = 1
            invert.label = 'WorldBridge glossiness to roughness'
            tree.links.new(node.outputs['Color'], invert.inputs[1])
            tree.links.new(invert.outputs[0], target.inputs['Roughness'])
            row.setdefault('material_changes', []).append('Roughness = 1 - explicit glossiness map')
    if kind == 'normal' and not any(l.to_node.type == 'NORMAL_MAP' for l in node.outputs['Color'].links):
        row.setdefault('warnings', []).append('Normal texture has no Normal Map connection; custom graph preserved')
    if kind == 'unknown':
        row.setdefault('warnings', []).append('Unknown semantic; original material links preserved')
    if row.get('orientation_is_assumption'):
        row.setdefault('warnings', []).append('No KTX orientation metadata; assumed S=r,T=d')


def repair_images(materials, cache, rescue_root, model_path='', model_url=''):
    bindings, requests = snapshot(materials, model_path, model_url)
    rows = recover(requests, [rescue_root, str(cache)], Path(cache)/'recovered-v05')
    for row in rows:
        try:
            apply(bindings, row)
        except Exception as exc:
            row.update(status='relink_failed', error=str(exc))
    return rows


class RepairSession:
    def __init__(self, anchors, scene, roots, cache, refresh=False):
        from .viewport import owned_objects
        from .runtime import Worker, ProgressLog
        self.scene, self.bindings, requests = scene, {}, []
        self.done, self.rows, self.applied = False, [], 0
        self.stop = threading.Event()
        self.cache = Path(cache)
        self.token = uuid.uuid4().hex[:12]
        self.report_path = self.cache / ('recovery-'+self.token+'.json')
        clones = {}
        for anchor in anchors:
            path, url = anchor.get('worldbridge_cached_asset', ''), anchor.get('worldbridge_model_url', '')
            materials = set()
            for obj in owned_objects(anchor):
                for slot in obj.material_slots:
                    if slot.material:
                        key = (slot.material, path, url)
                        if key not in clones:
                            clones[key] = slot.material.copy()
                            materials.add(clones[key])
                        slot.material = clones[key]
            if path and Path(path).is_file():
                from .materials import repair_materials
                try:
                    repair_materials(Path(path), materials)
                except Exception:
                    pass
            bindings, items = snapshot(materials, path, url)
            self.bindings.update(bindings)
            requests.extend(items)
        self.total = len(requests)
        self.worker = Worker(lambda event: recover(requests, roots, self.cache/'textures', event, refresh),
                             self.stop, ProgressLog(self.token), 'recover_local_textures')
        scene['worldbridge_recovery_status'] = 'Indexing local textures (%d uses); Cancel available' % self.total

    def cancel(self):
        self.stop.set()
        self.finish('CANCELLED')

    def finish(self, status):
        import bpy
        self.done = True
        grouped = {}
        for row in self.rows:
            key = (row.get('source_sha256') or row['reference'], row['semantic'], row['status'])
            group = grouped.setdefault(key, dict(row, uses=0))
            group['uses'] += 1
        report = dict(status=status, requested_uses=self.total, applied=self.applied, dependencies=list(grouped.values()))
        self.cache.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
        text = bpy.data.texts.new('WorldBridge Recovery '+self.token)
        text.write(json.dumps(report, indent=2))
        recovered = sum(r['status'] == 'recovered' and r.get('loaded', False) for r in self.rows)
        self.scene['worldbridge_recovery_status'] = '%s: %d/%d texture uses loaded; details in Text Editor' % (status, recovered, self.total)
        self.scene['worldbridge_recovery_report'] = str(self.report_path)

    def tick(self):
        if self.done:
            return None
        if self.scene != __import__('bpy').context.scene:
            self.cancel()
            return None
        if self.worker:
            outcome = self.worker.poll()
            if outcome is None:
                return .1
            self.worker = None
            kind, payload = outcome
            if kind == 'error':
                self.scene['worldbridge_recovery_error'] = str(payload)
                self.finish('FAILED')
                return None
            self.rows = payload
        for _ in range(2):
            if self.applied >= len(self.rows):
                self.finish('COMPLETE')
                return None
            row = self.rows[self.applied]
            try:
                apply(self.bindings, row)
            except Exception as exc:
                row.update(status='relink_failed', error=str(exc))
            self.applied += 1
        self.scene['worldbridge_recovery_status'] = 'Relinking textures: %d/%d' % (self.applied, self.total)
        return .02
