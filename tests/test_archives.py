import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED
from worldbridge.parser import load_backup, archive_backups, ArchiveChoiceRequired, plan_entities

RESCUE = Path(r'C:\Projects\ROBOTDOLLY-Asset-Rescue')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'world.content.zip'
        self.data = {'Entities': [{'id': 'a', 'type': 'Model', 'unknown': {'keep': True}}]}

    def archive(self, members):
        with ZipFile(self.path, 'w', ZIP_DEFLATED) as archive:
            for name, data in members:
                archive.writestr(name, data)

    def test_nested_gzip_content_and_no_extraction(self):
        self.archive([('domain/models.json.gz', gzip.compress(json.dumps(self.data).encode())),
                      ('mappings.json', '{}'), ('assets/ignore.bin', b'asset')])
        before = self.path.read_bytes()
        self.assertEqual(load_backup(self.path), self.data)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), before)

    def test_multiple_worlds_require_choice(self):
        self.archive([('one.json', json.dumps(self.data)), ('two.json', '{"Entities": []}')])
        with self.assertRaises(ArchiveChoiceRequired) as caught:
            load_backup(self.path)
        self.assertEqual(caught.exception.candidates, {'one.json': 1, 'two.json': 0})
        self.assertEqual(load_backup(self.path, archive_member='two.json'), {'Entities': []})
        with self.assertRaisesRegex(ValueError, 'missing or invalid'):
            load_backup(self.path, archive_member='absent.json')

    def test_path_traversal_and_unsupported_layout(self):
        for name in ('../outside.json', 'C:/outside.json', '/outside.json', 'a/../../b.json', '..\\outside.json'):
            self.archive([(name, json.dumps(self.data))])
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                load_backup(self.path)
        self.archive([('mappings.json', '{}'), ('a.bin', 'none')])
        with self.assertRaisesRegex(ValueError, 'no valid Entities'):
            load_backup(self.path)

    def test_limits_corruption_and_duplicate_names(self):
        self.archive([('models.json.gz', gzip.compress(json.dumps(self.data).encode()))])
        with self.assertRaisesRegex(ValueError, 'size'):
            load_backup(self.path, limit=80)
        self.archive([('models.json', '{broken')])
        with self.assertRaisesRegex(ValueError, 'Unsupported archive'):
            load_backup(self.path)
        self.archive([('models.json', '{"Entities": []}'), ('models.json', '{"Entities": []}')])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            load_backup(self.path)

    @unittest.skipUnless((RESCUE/'WorldBridge-BLENDER-TEST.json').is_file(), 'Local genuine backup unavailable')
    def test_genuine_backup_lossless_equivalence(self):
        plain = RESCUE/'WorldBridge-BLENDER-TEST.json'
        compressed = RESCUE/'TEST-EXPORT-20261022T082359'/'ROBOTDOLLY-TEST-RESTORED-ORIGINAL-GITHUB.json.gz'
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (plain, compressed)}
        a, b = load_backup(plain), load_backup(compressed)
        self.assertEqual(len(a['Entities']), 2121)
        self.assertEqual(a, b)  # All IDs, transforms, hierarchy, metadata, URLs and unknown fields.
        self.assertEqual(plan_entities(a), plan_entities(b))
        for p, digest in before.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), digest)

    @unittest.skipUnless(RESCUE.is_dir(), 'Local archive fixtures unavailable')
    def test_genuine_content_archive(self):
        folder = RESCUE/'world-export-20261021T114810Z'
        stem = 'ROBOTDOLLY-WORLD-ALL-VERIFIED-REPAIRS-TEST'
        self.assertEqual(load_backup(folder/(stem+'.content.zip')), load_backup(folder/(stem+'.json.gz')))


if __name__ == '__main__':
    unittest.main()
