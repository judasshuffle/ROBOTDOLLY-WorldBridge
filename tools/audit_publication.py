"""Audit the Git index and the preserved release ZIP without reading private data."""
import hashlib
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {'.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md',
             'LICENSE-STATUS.md', 'THIRD_PARTY_NOTICES.md', 'build_zip.py'}
SUFFIXES = {'worldbridge': {'.py'}, 'tests': {'.py'}, 'docs': {'.md'}, 'tools': {'.py', '.ps1'}}
PATTERNS = [
    rb'gh[pousr]_[A-Za-z0-9]{20,}',
    rb'github_pat_[A-Za-z0-9_]{20,}',
    rb'AKIA[A-Z0-9]{16}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'[A-Za-z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo)\.com',
    rb'C:[\\/]+Users[\\/]+[A-Za-z0-9_. -]+[\\/]',
]


def scan(name, content):
    for pattern in PATTERNS:
        if re.search(pattern, content):
            # Do not print possible credentials or personal data.
            raise ValueError('Potential sensitive content requires review: ' + name)
    content.decode('utf-8-sig')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--working-tree', action='store_true', help='Review candidates only; does not certify the Git index')
    args = parser.parse_args()
    command = ['git', 'ls-files', '-z']
    if args.working_tree:
        command += ['--cached', '--others', '--exclude-standard']
    files = subprocess.check_output(command, cwd=ROOT).decode().split('\0')
    files = [name for name in files if name]
    if not files:
        raise ValueError('Nothing is staged/tracked; stage the reviewed public files first')
    manifest = {}
    for name in files:
        path = PurePosixPath(name)
        allowed = name in TOP_LEVEL or (len(path.parts) == 2 and path.parts[0] in SUFFIXES
                                       and path.suffix in SUFFIXES[path.parts[0]])
        if not allowed:
            raise ValueError('Not in public-source allowlist: ' + name)
        content = (ROOT/name).read_bytes() if args.working_tree else subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        scan(name, content)
        manifest[name] = dict(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    release = ROOT/'ROBOTDOLLY-WorldBridge-v0.3.zip'
    with ZipFile(release) as archive:
        if archive.testzip() is not None:
            raise ValueError('Release ZIP failed integrity check')
        expected = {'worldbridge/' + path.name for path in (ROOT/'worldbridge').glob('*.py')}
        if set(archive.namelist()) != expected:
            raise ValueError('Release ZIP contains unexpected or missing files')
        for name in archive.namelist():
            content = archive.read(name)
            scan(name, content)
            if content != (ROOT/name).read_bytes():
                raise ValueError('Preserved release differs from working source: ' + name)
    result = dict(status='PASS', scope='working-tree candidates' if args.working_tree else 'Git index', files=manifest, release=release.name,
                  release_sha256=hashlib.sha256(release.read_bytes()).hexdigest(),
                  notes='Allowlist, credential-pattern, personal-path/email and ZIP-content checks; not a proof of absence of all secrets.')
    (ROOT/'build').mkdir(exist_ok=True)
    (ROOT/'build'/'publication-audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS:', result['scope'], len(files), 'public files; source-only release ZIP; no flagged sensitive patterns')
    print('Release SHA-256:', result['release_sha256'])


if __name__ == '__main__':
    main()
