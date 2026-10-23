"""Source-based light approximation; original entity JSON is never changed."""
import json
import math


def parameters(entity):
    intensity = max(0, float(entity.get('intensity', 1)))
    radius = float(entity.get('falloffRadius', .1))
    radius = radius if radius > 0 else .1
    color = tuple(max(0, min(1, float(entity.get('color', {}).get(k, 255))/255)) for k in ('red','green','blue'))
    dimensions = entity.get('dimensions', {})
    maximum = max(float(dimensions.get(k, 1)) for k in ('x','y','z'))/2
    cutoff = max(0, min(maximum, radius*(math.sqrt(intensity*max(color)/.001)-2)))
    # DarkRide I/(1+d/r)^2 tends to I*r^2/d^2. Blender isotropic power P gives P/(4*pi*d^2).
    distance = max(.001, cutoff/2)
    power = 4*math.pi*intensity*(distance*radius/(distance+radius))**2
    if not all(math.isfinite(v) for v in (power, radius, cutoff, *color)):
        raise ValueError('Non-finite light parameter')
    return dict(power=power if entity.get('visible', True) else 0, radius=radius, cutoff=cutoff, color=color,
                spot=bool(entity.get('isSpotlight')), angle=math.radians(max(.5,min(89.9,float(entity.get('cutoff',90)))))*2,
                exponent=max(0,float(entity.get('exponent',0))), shadows=bool(entity.get('canCastShadow',True)))


def configure(obj, entity):
    p = parameters(entity)
    data = obj.data
    data.type = 'SPOT' if p['spot'] else 'POINT'
    data.color, data.energy = p['color'], p['power']
    data.shadow_soft_size = .05  # Falloff radius is attenuation, not an emitter sphere size.
    data.use_shadow = p['shadows']
    data.use_custom_distance = True
    data.cutoff_distance = max(.001,p['cutoff'])
    if p['spot']:
        data.spot_size = p['angle']
        # Blender's edge blend cannot reproduce cos(theta)^exponent exactly.
        data.spot_blend = 1-1/(1+p['exponent'])
    obj.location = (0,0,0)
    obj.rotation_euler = (math.pi/2,0,0)
    obj.scale = (1,1,1)
    obj['worldbridge_original_energy'] = p['power']
    obj['worldbridge_source_light'] = json.dumps(entity)
    obj['worldbridge_light_translation'] = json.dumps(dict(**p, policy='radiometric match at half source cutoff radius v1',
        warnings=['DarkRide intensity has no declared SI unit; radiometric scale assumed',
                  'Near-field attenuation and spot exponent approximated; EEVEE range is not Cycles cutoff']))
    return p


def repair_scene(scene):
    from pathlib import Path
    from .viewport import entity_anchor, apply_lighting
    sidecars, rows = {}, []
    for obj in scene.objects:
        if obj.type != 'LIGHT':
            continue
        anchor = entity_anchor(obj)
        if anchor is None:
            continue
        if anchor.get('worldbridge_type') != 'Light':
            if 'worldbridge_embedded_light_energy' not in obj:
                obj['worldbridge_embedded_light_energy'] = obj.data.energy
            obj.data.energy = 0
            obj['worldbridge_original_energy'] = 0
            rows.append(dict(name=obj.name, status='embedded model light disabled; source retained'))
            continue
        try:
            path = anchor['worldbridge_sidecar']
            if path not in sidecars:
                document = json.loads(Path(path).read_text(encoding='utf8'))
                sidecars[path] = document.get('Entities', document.get('entities', []))
            entity = sidecars[path][anchor['worldbridge_record_index']]
            rows.append(dict(id=anchor['worldbridge_entity_id'], status='translated', **configure(obj,entity)))
        except Exception as exc:
            rows.append(dict(name=obj.name, status='warning', error=str(exc)))
    scene['worldbridge_light_report'] = json.dumps(rows)
    apply_lighting(scene)
    return rows
