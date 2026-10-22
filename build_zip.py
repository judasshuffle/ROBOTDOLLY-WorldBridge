from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
target = root / 'ROBOTDOLLY-WorldBridge-v0.3.zip'
with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
    for path in sorted((root / 'worldbridge').glob('*.py')):
        archive.write(path, path.relative_to(root))
with ZipFile(target) as archive:
    assert archive.testzip() is None
    assert 'worldbridge/__init__.py' in archive.namelist()
print(target, target.stat().st_size, 'bytes; ZIP integrity OK')
