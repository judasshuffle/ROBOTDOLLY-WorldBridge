"""Local-only provenance index and immutable texture cache. No Blender API calls."""
import csv
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.ktx', '.ktx2', '.dds', '.tga', '.bmp', '.webp', '.exr', '.hdr'}
MAX_BYTES = 128 * 1024 * 1024
HASH_REFERENCE = re.compile(r'(?:tex-)?([a-fA-F0-9]{64})(?:\.[^.]+)?$')
_indices = {}
_lock = threading.Lock()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def norm(value):
    return unquote(str(value)).replace('\\', '/').casefold()


def basename(value):
    return norm(value).rsplit('/', 1)[-1]


def bounded_read(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise ValueError('File exceeds 128 MiB recovery limit')
    return data


class Index:
    def __init__(self, roots, cancel=None):
        self.roots = tuple(Path(p).resolve() for p in roots if p and Path(p).is_dir())
        self.hashes, self.files, self.relationships, self.models = {}, [], {}, {}
        by_path = {}
        self.warnings = []
        manifests = []
        seen = set()
        for root in self.roots:
            for folder, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'node_modules') and not Path(folder, d).is_symlink()]
                for name in names:
                    if cancel and cancel.is_set():
                        raise InterruptedError('Texture indexing cancelled')
                    path = Path(folder, name)
                    key = norm(path)
                    if key in seen or path.is_symlink():
                        continue
                    seen.add(key)
                    ext = path.suffix.lower()
                    if ext == '.csv':
                        manifests.append(path)
                    elif ext in IMAGE_EXTENSIONS:
                        by_path[norm(path)] = path
                        self.files.append((path, ''))
                        match = HASH_REFERENCE.fullmatch(basename(path)) or HASH_REFERENCE.fullmatch(path.parent.name)
                        if match:
                            self.hashes.setdefault(match.group(1).lower(), []).append(path)
                    elif ext in ('.fbx', '.glb', '.gltf'):
                        self.models.setdefault(basename(path), []).append(path)
        for manifest in manifests:
            if cancel and cancel.is_set():
                raise InterruptedError('Texture indexing cancelled')
            try:
                if manifest.stat().st_size > 32*1024*1024:
                    continue
                with manifest.open(encoding='utf-8-sig', newline='') as stream:
                    for row in csv.DictReader(stream):
                        digest = row.get('SHA256', '') or row.get('sha256', '')
                        if re.fullmatch('[a-fA-F0-9]{64}', digest or ''):
                            digest = digest.lower()
                            for field in ('Source', 'LocalFile', 'path'):
                                recorded = row.get(field, '')
                                if not recorded:
                                    continue
                                paths = [recorded]
                                paths += [str(root/prefix/recorded) for root in self.roots for prefix in ('', 'originals', 'assets')]
                                for candidate in paths:
                                    if norm(candidate) in by_path:
                                        self.hashes.setdefault(digest, []).append(by_path[norm(candidate)])
                        else:
                            continue
                        model = row.get('Model', '') or row.get('ModelFile', '')
                        url = row.get('ModelOriginalUrl', '')
                        references = [row.get('TextureFile', '')]
                        try:
                            references += json.loads(row.get('References', '') or '[]')
                        except (ValueError, TypeError):
                            pass
                        for reference in references:
                            if not reference:
                                continue
                            for identity in (model, basename(model), url):
                                if identity:
                                    self.relationships.setdefault((norm(identity), basename(reference)), set()).add(digest)
            except (OSError, UnicodeError, csv.Error) as exc:
                self.warnings.append(dict(path=str(manifest), error=str(exc)))

    def match(self, reference, model_path='', model_url='', original_name=''):
        match = HASH_REFERENCE.fullmatch(basename(reference))
        if not match:
            match = next((m for part in reversed(norm(reference).split('/')[:-1]) if (m := re.fullmatch(r'([a-f0-9]{64})', part))), None)
        if match:
            digest = match.group(1).lower()
            paths = self.hashes.get(digest, [])
            for path in dict.fromkeys(paths):
                if sha(bounded_read(path)) == digest:
                    return path, digest, 'verified SHA256 reference'
            return None, digest, 'invalid hash' if paths else 'missing'
        # A real sibling/relative texture path is valid evidence. Never search globally by name.
        ref = Path(reference.replace('\\', '/'))
        candidates = []
        if model_path:
            candidate = Path(model_path).parent / ref
            try:
                if candidate.resolve().is_relative_to(Path(model_path).parent.resolve()) and candidate.is_file():
                    candidates.append(candidate)
            except (OSError, ValueError):
                pass
        try:
            if not str(reference).startswith('//') and ref.is_absolute() and ref.is_file():
                candidates.append(ref)
        except OSError:
            pass
        if candidates:
            verified = {sha(bounded_read(p)): p for p in candidates}
            if len(verified) == 1:
                digest, path = next(iter(verified.items()))
                return path, digest, 'existing source-relative path'
            return None, '', 'ambiguous'
        identities = {norm(model_url), norm(model_path), basename(model_path)}
        # URL package paths establish scope even when the cached FBX name is a URL hash.
        if model_url:
            urlpath = norm(urlsplit(model_url).path).lstrip('/')
            for name, paths in self.models.items():
                for path in paths:
                    if norm(path).endswith('/'+urlpath) or any(norm(path).endswith('/'+urlpath.split('/', n)[-1]) for n in (2, 3) if len(urlpath.split('/')) > n+1):
                        if basename(path) == basename(urlpath):
                            identities.add(basename(path))
                            identities.add(norm(path))
        digests = set()
        for identity in identities:
            for reference_name in (reference, original_name):
                digests.update(self.relationships.get((identity, basename(reference_name)), ()))
        if len(digests) == 1:
            digest = next(iter(digests))
            for path in dict.fromkeys(self.hashes.get(digest, [])):
                if sha(bounded_read(path)) == digest:
                    return path, digest, 'model-scoped manifest relationship'
            return None, digest, 'invalid manifest hash'
        return None, '', 'ambiguous' if digests else 'missing'

    def model(self, url):
        """Exact URL-cache filename or mirrored repository path; no basename-only model guesses."""
        urlpath = unquote(urlsplit(url).path).lstrip('/')
        name = sha(url.encode()) + Path(urlpath).suffix.lower()
        candidates = list(self.models.get(name, []))
        # raw.githubusercontent.com/owner/repo/branch/path -> mirrored repo/path.
        parsed = urlsplit(url)
        suffix = urlpath
        if parsed.netloc.lower() == 'raw.githubusercontent.com':
            parts = urlpath.split('/')
            if len(parts) >= 4:
                suffix = '/'.join(parts[3:])
        for path in self.models.get(basename(urlpath), []):
            if norm(path).endswith('/'+norm(suffix)):
                candidates.append(path)
        if not candidates:
            return None
        hashes = {sha(bounded_read(p)): p for p in candidates}
        return next(iter(hashes.values())) if len(hashes) == 1 else None


def get_index(roots, cancel=None, refresh=False):
    key = tuple(str(Path(p).resolve()) for p in roots if p)
    with _lock:
        if refresh or key not in _indices:
            _indices[key] = Index(key, cancel)
        return _indices[key]


def convert(source, digest, semantic, cache):
    from .ktx import MAGIC, FORMATS, parse, decode, png_bytes
    data = bounded_read(source)
    if sha(data) != digest:
        raise ValueError('Source hash changed since indexing')
    details = {}
    if data.startswith(MAGIC):
        info = parse(data)
        tag = 'normal' if semantic == 'normal' else 'data'
        output = Path(cache) / (digest+'-ktx1-v1-'+tag+'.png')
        receipt = output.with_suffix('.json')
        if output.is_file() and receipt.is_file():
            old = json.loads(receipt.read_text())
            if sha(bounded_read(output)) == old['output_sha256']:
                return dict(old, cached=True)
        pixels, details = decode(info, normal=semantic == 'normal')
        encoded = png_bytes(pixels, FORMATS[info['format']][3] and semantic not in ('normal', 'metallic', 'roughness', 'glossiness', 'opacity'))
        details['pixel_sha256'] = sha(pixels.tobytes())
        extension = '.png'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        encoded, extension = data, '.png'
        details['format'] = 'PNG'
    elif data.startswith(b'\xff\xd8\xff'):
        encoded, extension = data, '.jpg'
        details['format'] = 'JPEG'
    else:
        raise ValueError('Unsupported image signature '+data[:12].hex()+'; source extension '+Path(source).suffix)
    if not data.startswith(MAGIC):
        output = Path(cache) / (digest+extension)
        receipt = output.with_suffix(output.suffix+'.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise ValueError('Cache integrity mismatch: '+str(output))
    else:
        with output.open('xb') as stream:
            stream.write(encoded)
    result = dict(source=str(source), source_sha256=digest, output=str(output), output_sha256=sha(encoded), semantic=semantic, **details)
    if not receipt.exists():
        with receipt.open('x') as stream:
            json.dump(result, stream, indent=2)
    return result


def recover(requests, roots, cache, cancel=None, refresh=False):
    index = get_index(roots, cancel, refresh)
    results = []
    for item in requests:
        if cancel and cancel.is_set():
            break
        row = dict(item)
        try:
            source, digest, evidence = index.match(item['reference'], item.get('model_path', ''), item.get('model_url', ''), item.get('original_name', ''))
            row.update(status=evidence, evidence=evidence)
            if source:
                row.update(convert(source, digest, item.get('semantic', ''), cache), status='recovered')
        except Exception as exc:
            row.update(status='unsupported_or_invalid', error=str(exc))
        results.append(row)
    return results
