from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
target = root / 'ROBOTDOLLY-WorldBridge-v0.5.zip'
with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
    for path in sorted((root / 'worldbridge').glob('*.py')):
        archive.write(path, path.relative_to(root))
    for name in ('THIRD_PARTY_NOTICES.md', 'LICENSE-STATUS.md', 'docs/V0.5-STATUS.md'):
        archive.write(root/name, 'worldbridge/'+Path(name).name)
with ZipFile(target) as archive:
    assert archive.testzip() is None
    assert 'worldbridge/__init__.py' in archive.namelist()
print(target, target.stat().st_size, 'bytes; ZIP integrity OK')
