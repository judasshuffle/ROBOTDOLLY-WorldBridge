import json
from pathlib import Path
import tempfile
import threading
import unittest
from worldbridge.preparation import prepare_selected
from worldbridge.assets import DownloadCancelled

ROOT = Path(__file__).resolve().parents[1]


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT/'build')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root/'source.json'
        self.source.write_text(json.dumps({'Entities': [
            {'id':str(i), 'type':'Model', 'modelURL':'https://example.test/%d.glb'%i}
            for i in range(4)]}))
        self.targets = [dict(target_key=str(i), sidecar=str(self.source), index=i, id=str(i), loaded=i==0)
                        for i in range(4)]

    def test_limit_loaded_skip_cache_and_no_source_mutation(self):
        before = self.source.read_bytes()
        result = prepare_selected(self.targets, self.root, 'test', 2)
        self.assertEqual([task['id'] for task in result['tasks']], ['1','2'])
        self.assertEqual(result['report']['assets_skipped'], 2)
        self.assertEqual(result['tasks'][0]['cache'], str(self.root/'cache'))
        self.assertEqual(self.source.read_bytes(), before)

    def test_record_identity_mismatch_is_not_silently_loaded(self):
        self.targets[0]['id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            prepare_selected(self.targets, self.root, 'test', 4)

    def test_cancel_before_read(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(DownloadCancelled):
            prepare_selected(self.targets, self.root, 'test', 4, event)


if __name__ == '__main__':
    unittest.main()
