"""Blender-independent, lossless DarkRide backup reader."""
import gzip
import json
import math
import io
import zipfile
from pathlib import PurePosixPath
from pathlib import Path

MAX_BACKUP_BYTES = 512 * 1024 * 1024


class ArchiveChoiceRequired(ValueError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__('Several entity backups found; choose an archive member: ' + ', '.join(candidates))


def expand_backup(raw, limit):
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Backup exceeds decompressed size limit')
    return raw


def decode_backup(raw, limit=MAX_BACKUP_BYTES):
    raw = expand_backup(raw, limit)
    data = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + s)))
    if not isinstance(data, dict) or not isinstance(data.get('Entities'), list):
        raise ValueError('Expected a JSON object containing an Entities array')
    if any(not isinstance(e, dict) for e in data['Entities']):
        raise ValueError('Every Entities entry must be an object; no scene was created')
    return data


def archive_backups(path, limit=MAX_BACKUP_BYTES, member=None, cancel_event=None):
    """Read only candidate JSON members, never extract paths or asset payloads."""
    found, errors, budget = {}, [], 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000:
            raise ValueError('Archive exceeds 10,000 member limit')
        seen = set()
        for info in infos:
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError('Archive inspection cancelled')
            name = info.filename
            safe = name.replace('\\', '/')
            if safe.startswith('/') or ':' in safe or '..' in PurePosixPath(safe).parts:
                raise ValueError('Unsafe archive member path: ' + name)
            if name in seen:
                raise ValueError('Duplicate archive member: ' + name)
            seen.add(name)
        for info in infos:
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError('Archive inspection cancelled')
            name = info.filename
            if info.is_dir() or not name.lower().endswith(('.json', '.gz')) or (member and name != member):
                continue
            budget += info.file_size
            if info.file_size > limit or budget > limit or info.file_size > max(1, info.compress_size) * 1000:
                raise ValueError('Archive exceeds decompression size/ratio limits')
            if len(found) + len(errors) >= 128:
                raise ValueError('Archive exceeds 128 JSON candidate limit')
            try:
                with archive.open(info) as stream:
                    raw = stream.read(limit + 1)
                raw = expand_backup(raw, max(0, limit - budget))
                budget += len(raw)
                data = decode_backup(raw, limit)
                found[name] = len(data['Entities'])
                if member:
                    return data
            except (ValueError, OSError, EOFError, UnicodeError, zipfile.BadZipFile) as exc:
                if 'size limit' in str(exc):
                    raise
                errors.append(name + ': ' + str(exc))
    if member:
        raise ValueError('Selected archive member is missing or invalid: ' + member + '; ' + '; '.join(errors))
    if not found:
        raise ValueError('Unsupported archive: no valid Entities backup JSON. ' + '; '.join(errors[:5]))
    return found


def load_backup(path, limit=MAX_BACKUP_BYTES, archive_member=None):
    path = Path(path)
    if zipfile.is_zipfile(path):
        if not archive_member:
            candidates = archive_backups(path, limit)
            if len(candidates) != 1:
                raise ArchiveChoiceRequired(candidates)
            archive_member = next(iter(candidates))
        return archive_backups(path, limit, archive_member)
    with path.open('rb') as stream:
        magic = stream.read(4)
        if magic.startswith(b'PK') or path.suffix.lower() == '.zip':
            raise ValueError('Corrupt or unsupported ZIP archive; no valid ZIP directory')
        compressed = magic.startswith(b'\x1f\x8b')
    with (gzip.open(path, 'rb') if compressed else path.open('rb')) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Backup exceeds decompressed size limit')
    return decode_backup(raw, limit)


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
