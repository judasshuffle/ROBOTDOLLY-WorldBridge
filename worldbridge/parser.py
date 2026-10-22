"""Blender-independent, lossless DarkRide backup reader."""
import gzip
import json
import math
from pathlib import Path

MAX_BACKUP_BYTES = 512 * 1024 * 1024


def load_backup(path, limit=MAX_BACKUP_BYTES):
    path = Path(path)
    with path.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    with (gzip.open(path, 'rb') if compressed else path.open('rb')) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Backup exceeds decompressed size limit')
    data = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + s)))
    if not isinstance(data, dict) or not isinstance(data.get('Entities'), list):
        raise ValueError('Expected a JSON object containing an Entities array')
    if any(not isinstance(e, dict) for e in data['Entities']):
        raise ValueError('Every Entities entry must be an object; no scene was created')
    return data


def canonical_id(value):
    return str(value or '').strip('{}').lower()


def vector(entity, key, default=(0, 0, 0)):
    value = entity.get(key, {})
    result = tuple(float(value.get(k, default[i])) for i, k in enumerate('xyz'))
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Nonfinite ' + key)
    return result


def coordinates(v):
    return (v[0], -v[2], v[1])


def rotation(entity, key='rotation'):
    q = entity.get(key, {})
    values = tuple(float(q.get(k, 1 if k == 'w' else 0)) for k in 'wxyz')
    norm = math.sqrt(sum(x*x for x in values))
    if not math.isfinite(norm) or norm < 1e-12:
        raise ValueError('Invalid quaternion')
    w, x, y, z = (x/norm for x in values)
    return (w, x, -z, y)


def plan_entities(data):
    records, lookup, warnings = [], {}, []
    for index, entity in enumerate(data['Entities']):
        original = str(entity.get('id', ''))
        key = canonical_id(original)
        record_id = key or 'missing-id-%d' % index
        if not key or key in lookup:
            warnings.append('Record %d: missing or duplicate ID; preserved by record index' % index)
            record_id = 'record-%d:%s' % (index, record_id)
        record = dict(index=index, key=record_id, entity=entity, parent=None)
        records.append(record)
        if key and key not in lookup:
            lookup[key] = index
    for r in records:
        pid = canonical_id(r['entity'].get('parentID'))
        if pid and pid != '00000000-0000-0000-0000-000000000000':
            r['parent'] = lookup.get(pid)
            if r['parent'] is None:
                warnings.append('Record %d: missing parent %s; local transform shown at root' % (r['index'], pid))
    # Iterative traversal handles deep hierarchies without recursion limits.
    done = set()
    for start in range(len(records)):
        path, seen, current = [], set(), start
        while current is not None and current not in done:
            if current in seen:
                records[current]['parent'] = None
                warnings.append('Record %d: parent cycle broken' % current)
                break
            seen.add(current)
            path.append(current)
            current = records[current]['parent']
        done.update(path)
    return records, warnings
