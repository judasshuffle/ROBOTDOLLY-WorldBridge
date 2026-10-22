import gzip
import json
from pathlib import Path
import tempfile
import unittest
from worldbridge.parser import load_backup, plan_entities, coordinates, rotation
from worldbridge.assets import download, validate_gltf

ROOT = Path(__file__).resolve().parents[1]


class ParserTests(unittest.TestCase):
    def test_plain_gzip_and_preservation(self):
        data = {'Version': 100, 'Entities': [{'id': 'a', 'userData': '{secret}', 'unknown': [1, 2]}]}
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            for name in ('a.json', 'a.json.gz', 'a.gz'):
                p = Path(directory)/name
                raw = json.dumps(data).encode()
                p.write_bytes(gzip.compress(raw) if name.endswith('gz') else raw)
                before = p.read_bytes()
                self.assertEqual(load_backup(p), data)
                self.assertEqual(p.read_bytes(), before)
                with self.assertRaises(ValueError):
                    load_backup(p, limit=2)

    def test_invalid_root_and_entries(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            p = Path(directory)/'a.json'
            for data in ({}, [], {'Entities': [None]}):
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_backup(p)

    def test_cycles_duplicates_missing(self):
        records, warnings = plan_entities({'Entities': [{'id': '{A}', 'parentID': 'b'}, {'id': 'b', 'parentID': 'a'}, {'id': 'a'}, {}, {'id': 'c', 'parentID': 'absent'}]})
        self.assertEqual(len(records), 5)
        self.assertEqual(len(warnings), 4)
        self.assertIsNone(records[0]['parent'])
        self.assertEqual(records[1]['parent'], 0)

    def test_deep_hierarchy(self):
        records, warnings = plan_entities({'Entities': [{'id': str(i), 'parentID': str(i+1)} for i in range(5000)]})
        self.assertEqual(len(records), 5000)
        self.assertEqual(len(warnings), 1)

    def test_coordinates_rotation(self):
        self.assertEqual(coordinates((1, 2, 3)), (1, -3, 2))
        self.assertEqual(rotation({'rotation': {'w': 2}}), (1, 0, 0, 0))
        with self.assertRaises(ValueError):
            rotation({'rotation': {'w': 0}})

    def test_asset_scheme_and_dependencies(self):
        with self.assertRaises(ValueError):
            download('file:///etc/model.glb', ROOT / 'build')
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            p = Path(directory)/'model.gltf'
            p.write_text(json.dumps({'buffers': [{'uri': '../secret'}]}))
            with self.assertRaises(ValueError):
                validate_gltf(p)


if __name__ == '__main__':
    unittest.main()
