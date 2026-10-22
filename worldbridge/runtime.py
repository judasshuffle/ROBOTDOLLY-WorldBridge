"""Pure Python worker coordination. This module never imports or calls bpy."""
import datetime
import json
from pathlib import Path
import queue
import threading
import traceback

LOG_PATH = Path(r'C:\Projects\ROBOTDOLLY-WorldBridge\build\worldbridge-import.log')
_LOG_LOCK = threading.Lock()


class ProgressLog:
    def __init__(self, session, path=LOG_PATH):
        self.session = session
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event, **details):
        entry = dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     session=self.session, thread=threading.current_thread().name,
                     event=event, **details)
        with _LOG_LOCK, self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            stream.flush()


class Worker:
    """One daemon I/O worker with a nonblocking result mailbox; no joins on UI."""
    def __init__(self, function, cancel_event, log, label):
        self.results = queue.Queue(maxsize=1)

        def run():
            try:
                log.write('worker_started', task=label)
                result = function(cancel_event)
                log.write('worker_finished', task=label, cancelled=cancel_event.is_set())
                self.results.put(('ok', result))
            except Exception as exc:
                detail = dict(error=str(exc), traceback=traceback.format_exc())
                # Even logging failures reach the main thread via the mailbox.
                try:
                    log.write('worker_error', task=label, **detail)
                except Exception as log_exc:
                    detail['logging_error'] = str(log_exc)
                self.results.put(('error', detail))

        self.thread = threading.Thread(target=run, name='WorldBridge-IO', daemon=True)
        self.thread.start()

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None


class AssetQueue:
    """Download sequentially in a worker; return one main-thread action per tick.

    Tasks are JSON-compatible dictionaries. Blender objects stay in the session.
    An accepted download is staged for a *later* tick, so the UI can redraw the
    IMPORTING state and the flushed log records exactly which file may stall.
    """
    def __init__(self, tasks, downloader, log):
        self.tasks = list(tasks)
        self.downloader = downloader
        self.log = log
        self.cancel_event = threading.Event()
        self.worker = None
        self.current = None
        self.ready = None
        self.index = 0
        self.downloaded = 0
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()
        self.ready = None
        self.log.write('downloads_cancel_requested', outstanding=len(self.tasks)-self.index + bool(self.current))

    def step(self):
        if self.cancelled:
            return ('cancelled', None, None)
        if self.ready is not None:
            path = self.ready
            self.ready = None
            task = self.current
            self.current = None
            return ('import', task, path)
        if self.worker:
            outcome = self.worker.poll()
            if outcome is None:
                return ('waiting', self.current, None)
            self.worker = None
            kind, payload = outcome
            if kind == 'error':
                task = self.current
                self.current = None
                return ('failed', task, payload)
            self.downloaded += 1
            self.ready = payload
            return ('downloaded', self.current, payload)
        if self.index == len(self.tasks):
            return ('done', None, None)
        self.current = self.tasks[self.index]
        self.index += 1
        task = self.current
        self.worker = Worker(lambda event: self.downloader(task, event), self.cancel_event,
                             self.log, task.get('url', 'model'))
        return ('downloading', task, None)
