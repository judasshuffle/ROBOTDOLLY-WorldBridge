"""Conservative repair for the demonstrated Blender 2.7 FBX opacity ambiguity.

Never infer opacity from a material name or from Alpha=0 alone. glTF is left to
Blender's alphaMode implementation. FBX source and all original files stay intact.
"""
import re
from functools import lru_cache


def properties(element):
    return {p.props[0]: tuple(p.props[4:]) for child in element.elems
            if child.id == b'Properties70' for p in child.elems if p.id == b'P'}


@lru_cache(maxsize=32)
def _fbx_evidence(filepath, size, modified):
    from io_scene_fbx import parse_fbx
    tree, _version = parse_fbx.parse(filepath)
    creators, templates, materials, transparent_ids = [], [], [], set()
    pending = [tree]
    while pending:
        node = pending.pop()
        if node.id == b'Creator' and node.props:
            creators.append(node.props[0].decode('utf-8', errors='replace'))
        elif node.id == b'PropertyTemplate' and node.props == [b'FbxSurfacePhong']:
            templates.append(properties(node))
        elif node.id == b'Material' and len(node.props) >= 2:
            materials.append((node.props[0], node.props[1].split(b'\x00')[0].decode('utf-8', errors='replace'), properties(node)))
        elif node.id == b'C' and len(node.props) > 3 and node.props[3] in (b'TransparentColor', b'TransparencyFactor', b'Opacity'):
            transparent_ids.add(node.props[2])
        pending.extend(node.elems)
    legacy = any(re.search(r'Blender .* - 2\.7\d', creator) for creator in creators)
    template_opaque = any(t.get(b'Opacity') == (1.0,) and t.get(b'TransparencyFactor') == (0.0,) for t in templates)
    result = []
    for material_id, name, props in materials:
        eligible = (legacy and template_opaque and b'Opacity' not in props
                    and props.get(b'TransparencyFactor', (0.0,)) == (0.0,)
                    and props.get(b'TransparentColor') == (1.0, 1.0, 1.0)
                    and material_id not in transparent_ids)
        result.append(dict(name=name, eligible=eligible))
    return result


def fbx_evidence(path):
    stat = path.stat()
    return _fbx_evidence(str(path), stat.st_size, stat.st_mtime_ns)


def repair_materials(path, materials):
    if path.suffix.lower() != '.fbx':
        return []
    evidence = fbx_evidence(path)
    repairs = []
    for material in set(materials):
        matches = [item for item in evidence if material.name == item['name'] or
                   re.fullmatch(re.escape(item['name']) + r'\.\d{3,}', material.name)]
        # Prefer exact/longest source name; ambiguous duplicates are not repaired.
        matches.sort(key=lambda item: len(item['name']), reverse=True)
        if not matches or not matches[0]['eligible']:
            continue
        if len(matches) > 1 and len(matches[0]['name']) == len(matches[1]['name']):
            continue
        if not material.use_nodes:
            continue
        nodes = material.node_tree.nodes
        if any(node.type in ('BSDF_TRANSPARENT', 'BSDF_GLASS', 'BSDF_REFRACTION') for node in nodes):
            continue
        for node in nodes:
            if node.type != 'BSDF_PRINCIPLED':
                continue
            alpha = node.inputs.get('Alpha')
            transmission = node.inputs.get('Transmission Weight') or node.inputs.get('Transmission')
            if alpha.is_linked or alpha.default_value != 0.0:
                continue
            if transmission and (transmission.is_linked or transmission.default_value > 0):
                continue
            material['worldbridge_original_alpha'] = float(alpha.default_value)
            material['worldbridge_alpha_repair'] = 'Legacy Blender 2.7 FBX: opaque template, no explicit opacity/transparency or alpha texture'
            alpha.default_value = 1.0
            color = list(material.diffuse_color)
            color[3] = 1.0
            material.diffuse_color = color
            repairs.append(dict(material=material.name, source_material=matches[0]['name'],
                                old_alpha=0.0, new_alpha=1.0, reason=material['worldbridge_alpha_repair']))
    return repairs


def repair_existing(anchors):
    """Repair selected imported materials from local cache, copying before edits."""
    import hashlib
    import json
    import urllib.parse
    from pathlib import Path
    import bpy
    from .viewport import owned_objects, role
    from .runtime import ProgressLog
    log = ProgressLog('selected-material-repair')
    results = []
    for anchor in anchors:
        url = anchor.get('worldbridge_model_url', '')
        cached = anchor.get('worldbridge_cached_asset')
        path = Path(cached) if cached else Path(anchor['worldbridge_sidecar']).parent/'cache'/(
            hashlib.sha256(url.encode()).hexdigest() + Path(urllib.parse.urlsplit(url).path).suffix.lower())
        if path.suffix.lower() != '.fbx' or not path.is_file():
            log.write('material_repair_skipped', entity_id=anchor['worldbridge_entity_id'], reason='No cached FBX')
            continue
        slots = [slot for obj in owned_objects(anchor) if role(obj) == 'MODEL'
                 for slot in obj.material_slots if slot.material]
        repairs = []
        for original in {slot.material for slot in slots}:
            clone = original.copy()
            try:
                changes = repair_materials(path, [clone])
                if changes:
                    for slot in slots:
                        if slot.material == original:
                            slot.material = clone
                    repairs.extend(changes)
                else:
                    bpy.data.materials.remove(clone)
            except Exception:
                bpy.data.materials.remove(clone)
                raise
        anchor['worldbridge_material_repairs'] = json.dumps(repairs)
        results.extend(repairs)
        log.write('selected_material_repair', entity_id=anchor['worldbridge_entity_id'], repairs=repairs)
    return results
