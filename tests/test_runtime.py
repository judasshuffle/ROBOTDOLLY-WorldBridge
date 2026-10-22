import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from worldbridge.assets import download, DownloadCancelled
from worldbridge.runtime import AssetQueue, ProgressLog, Worker

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __init__(self, data, declared=None):
        super().__init__(data)
        self.headers = {} if declared is None else {'Content-Length': str(declared)}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT/'build')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = ProgressLog('test', self.root/'import.log')

    def poll_until(self, queue, expected):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            outcome = queue.step()
            if outcome[0] in expected:
                return outcome
            time.sleep(.001)
        self.fail('Timed out waiting for ' + str(expected))

    def test_incremental_worker_failure_and_continuation(self):
        entered, release = threading.Event(), threading.Event()
        seen = []

        def fetch(task, event):
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            seen.append(task['url'])
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test gate expired')
            if task['url'] == 'bad':
                raise TimeoutError('simulated timeout')
            return self.root/'fixture.glb'

        queue = AssetQueue([{'url': 'bad'}, {'url': 'good'}], fetch, self.log)
        self.assertEqual(queue.step()[0], 'downloading')
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        for _ in range(100):
            self.assertEqual(queue.step()[0], 'waiting')
        self.assertLess(time.monotonic()-started, .5)
        release.set()
        failure = self.poll_until(queue, {'failed'})
        self.assertIn('simulated timeout', failure[2]['traceback'])
        self.assertEqual(queue.step()[0], 'downloading')
        self.assertEqual(self.poll_until(queue, {'downloaded'})[0], 'downloaded')
        self.assertEqual(queue.step()[0], 'import')
        self.assertEqual(queue.step()[0], 'done')
        self.assertEqual(seen, ['bad', 'good'])
        self.assertEqual(queue.downloaded, 1)

    def test_cancel_does_not_join_or_schedule_more(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def fetch(task, event):
            calls.append(task['url'])
            entered.set()
            release.wait(2)
            if event.is_set():
                raise DownloadCancelled('cancelled worker')
            return 'unused'

        queue = AssetQueue([{'url': 'first'}, {'url': 'second'}], fetch, self.log)
        queue.step()
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        queue.cancel()
        self.assertEqual(queue.step()[0], 'cancelled')
        self.assertLess(time.monotonic()-started, .5)
        release.set()
        queue.worker.thread.join(2)  # Test teardown only, never the UI path.
        self.assertFalse(queue.worker.thread.is_alive())
        self.assertEqual(calls, ['first'])
        self.assertIn('cancelled worker', self.log.path.read_text())

    def test_log_is_visible_immediately_and_errors_have_traceback(self):
        self.log.write('first', count=1)
        self.assertEqual(json.loads(self.log.path.read_text())['event'], 'first')
        worker = Worker(lambda event: 1/0, threading.Event(), self.log, 'failure')
        worker.thread.join(2)
        outcome = worker.poll()
        self.assertEqual(outcome[0], 'error')
        self.assertIn('ZeroDivisionError', outcome[1]['traceback'])
        lines = [json.loads(line) for line in self.log.path.read_text().splitlines()]
        self.assertEqual(lines[-1]['event'], 'worker_error')

    def test_download_limits_cache_and_timeout(self):
        with patch('worldbridge.assets.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = Response(b'1234', 4)
            target = download('https://example.test/model.glb', self.root, limit=8)
            self.assertEqual(target.read_bytes(), b'1234')
            self.assertEqual(factory.return_value.open.call_args.kwargs['timeout'], 5)
            download('https://example.test/model.glb', self.root, limit=8)
            self.assertEqual(factory.return_value.open.call_count, 1)
            for name, declared in [('declared', 99), ('streamed', None)]:
                factory.return_value.open.return_value = Response(b'123456789', declared)
                with self.assertRaises(ValueError):
                    download('https://example.test/'+name+'.glb', self.root, limit=8)
            factory.return_value.open.side_effect = TimeoutError('read timeout')
            with self.assertRaises(TimeoutError):
                download('https://example.test/timeout.glb', self.root)
        self.assertEqual(list(self.root.glob('*.part')), [])

    def test_download_cancel_cleans_partial_file(self):
        event = threading.Event()

        class CancellingResponse(Response):
            def read1(self, size):
                event.set()
                return super().read1(size)

        with patch('worldbridge.assets.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = CancellingResponse(b'1234')
            with self.assertRaises(DownloadCancelled):
                download('https://example.test/cancel.glb', self.root, cancel_event=event)
        self.assertEqual(list(self.root.glob('*.part')), [])
        self.assertEqual(list(self.root.glob('*.glb')), [])


if __name__ == '__main__':
    unittest.main()
