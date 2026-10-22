"""Bounded HTTP(S) downloads. Only entity modelURL is fetched."""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_ASSET_BYTES = 128 * 1024 * 1024
HTTP_TIMEOUT = 5
DOWNLOAD_DEADLINE = 60


class DownloadCancelled(Exception):
    """Cooperative cancellation; never a silent asset failure."""


def check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled('Download cancelled')


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme not in ('http', 'https'):
            raise ValueError('Non-HTTP redirect rejected')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, cache, limit=MAX_ASSET_BYTES, cancel_event=None):
    check_cancel(cancel_event)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('Only HTTP(S) model URLs are supported')
    suffix = Path(parts.path).suffix.lower()
    if suffix not in ('.fbx', '.gltf', '.glb'):
        raise ValueError('Unsupported model extension: ' + suffix)
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (hashlib.sha256(url.encode()).hexdigest() + suffix)
    if target.is_file() and 0 < target.stat().st_size <= limit:
        return target
    temporary = target.with_suffix(suffix + '.' + uuid.uuid4().hex + '.part')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'ROBOTDOLLY-WorldBridge/0.2'})
        started = time.monotonic()
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=HTTP_TIMEOUT) as response, temporary.open('wb') as output:
            if int(response.headers.get('Content-Length', 0)) > limit:
                raise ValueError('Asset exceeds size limit')
            count = 0
            while True:
                check_cancel(cancel_event)
                if time.monotonic() - started > DOWNLOAD_DEADLINE:
                    raise TimeoutError('Total download deadline exceeded')
                # read1 returns after one socket read, permitting cancellation/deadline
                # checks even when a server trickles a large response slowly.
                chunk = response.read1(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > limit or time.monotonic() - started > DOWNLOAD_DEADLINE:
                    raise ValueError('Asset size or total download time limit exceeded')
                output.write(chunk)
        if not count:
            raise ValueError('Empty asset')
        check_cancel(cancel_event)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def validate_gltf(path):
    """External dependencies are intentionally unsupported in this prototype."""
    import struct
    if path.suffix == '.gltf':
        document = json.loads(path.read_text(encoding='utf-8'))
    else:
        with path.open('rb') as stream:
            header = stream.read(20)
            if len(header) != 20 or header[:4] != b'glTF' or header[16:20] != b'JSON':
                raise ValueError('Invalid GLB header')
            length = struct.unpack('<I', header[12:16])[0]
            if length > MAX_ASSET_BYTES:
                raise ValueError('GLB JSON too large')
            document = json.loads(stream.read(length))
    for item in document.get('buffers', []) + document.get('images', []):
        uri = item.get('uri', '')
        if uri and not uri.startswith('data:'):
            raise ValueError('External glTF dependencies unsupported; use self-contained GLB')
