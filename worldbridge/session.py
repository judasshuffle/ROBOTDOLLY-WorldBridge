"""Main-thread timer session. Workers receive only paths/dicts/events, never bpy."""
import json
from pathlib import Path
import threading
import time
import traceback
import uuid
import bpy
from .assets import download, validate_gltf
from .preparation import prepare_backup, prepare_selected, save_json
from .runtime import AssetQueue, ProgressLog, Worker
from .importer import import_backup_steps, import_model
from .viewport import after_import, owned_objects, role


def fetch_asset(task, event, cache):
    path = download(task['url'], task.get('cache', cache), cancel_event=event, force_reload=task.get('force_reload', False))
    if path.suffix in ('.glb', '.gltf'):
        validate_gltf(path)
    return path


class ImportSession:
    def __init__(self, filepath, output_dir, load_models=True, world_positions=False,
                 model_limit=4, model_filter='', downloader=None, existing_targets=None, archive_member=None, force_reload=False):
        self.scene = bpy.context.scene
        self.token = uuid.uuid4().hex[:12]
        self.log = ProgressLog(self.token)
        self.output = Path(output_dir)
        self.filepath = str(filepath)
        self.options = dict(load_models=load_models, world_positions=world_positions,
                            model_limit=model_limit, model_filter=model_filter)
        self.report = dict(status='PREPARING', phase='PREPARING', source=self.filepath,
                           entities=0, represented=0, entities_processed=0,
                           assets_downloaded=0, assets_success=0, assets_failed=0,
                           assets_skipped=0, assets_cancelled=0, warnings=[], failures=[], skipped=[])
        self.report_path = self.output / ('worldbridge-' + self.token + '.report.json')
        self.stop_event = threading.Event()
        self.steps = None
        self.collection = None
        self.assets = None
        self.done = False
        self.prepared = None
        self.current = ''
        self.downloader = downloader
        self.last_log_progress = None
        self.logged_warnings = 0
        self.completed_tasks = 0
        self.loaded_anchors = []
        self.force_reload = force_reload
        self.existing_targets = {}
        self.log.write('session_started', source=self.filepath, **self.options)
        # Capture immutable values, not the session or Blender objects, in worker.
        source, output = self.filepath, str(self.output)
        if existing_targets is None:
            function = lambda event: prepare_backup(source, output, event, archive_member=archive_member)
        else:
            snapshots = []
            for index, anchor in enumerate(sorted(set(existing_targets), key=lambda o: (o['worldbridge_sidecar'], o['worldbridge_record_index']))):
                key = str(index)
                self.existing_targets[key] = anchor
                snapshots.append(dict(target_key=key, sidecar=anchor['worldbridge_sidecar'],
                                      index=anchor['worldbridge_record_index'], id=anchor['worldbridge_entity_id'],
                                      loaded=any(role(obj) == 'MODEL' and obj.type == 'MESH' for obj in owned_objects(anchor))))
            token = self.token
            function = lambda event: prepare_selected(snapshots, output, token, model_limit, event)
        self.worker = Worker(function, self.stop_event, self.log, 'read_entity_data')
        self.publish()

    def publish(self):
        self.scene['worldbridge_progress'] = json.dumps(dict(
            status=self.report['status'], phase=self.report['phase'],
            entities=self.report['entities'], processed=self.report['entities_processed'],
            represented=self.report['represented'], downloaded=self.report['assets_downloaded'],
            success=self.report['assets_success'], failed=self.report['assets_failed'],
            skipped=self.report['assets_skipped'], cancelled=self.report['assets_cancelled'],
            current=self.current))
        self.scene['worldbridge_last_status'] = self.report['status']
        self.scene['worldbridge_last_report'] = str(self.report_path)
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def checkpoint(self):
        self.output.mkdir(parents=True, exist_ok=True)
        save_json(self.report_path, self.report)
        if self.collection:
            self.collection['worldbridge_status'] = self.report['status']
            self.collection.name = 'WorldBridge ' + self.token + ' [' + self.report['status'] + ']'
            text_name = self.collection.get('worldbridge_report_text')
            text = bpy.data.texts.get(text_name) if text_name else None
        else:
            text = getattr(self, 'text', None)
        if text is None:
            text = bpy.data.texts.new('WorldBridge Report ' + self.token)
            if self.collection:
                self.collection['worldbridge_report_text'] = text.name
        self.text = text
        text.clear()
        text.write(json.dumps(self.report, indent=2))
        self.publish()

    def finish(self, status):
        self.report['status'] = status
        self.report['phase'] = status
        self.current = ''
        self.done = True
        warning = after_import(self.scene)
        if warning:
            self.report['warnings'].append(warning)
            if status == 'COMPLETE':
                status = 'COMPLETE_WITH_WARNINGS'
                self.report['status'] = self.report['phase'] = status
        self.checkpoint()
        self.log.write('session_finished', status=status, entities=self.report['entities_processed'],
                       downloaded=self.report['assets_downloaded'], success=self.report['assets_success'],
                       failed=self.report['assets_failed'], skipped=self.report['assets_skipped'],
                       cancelled=self.report['assets_cancelled'], warnings=self.report['warnings'])

    def cancel(self, reason='User requested cancellation'):
        if self.done:
            return
        self.log.write('cancel_requested', reason=reason)
        self.stop_event.set()
        if self.assets:
            self.assets.cancel()
            self.report['assets_cancelled'] = len(self.assets.tasks) - self.completed_tasks
        if self.steps is not None:
            self.steps.close()  # Generator finalizer preserves partial scene/report.
            self.steps = None
            self.find_collection()
        self.report['warnings'].append(reason + '; completed objects and placeholders retained')
        self.finish('CANCELLED')

    def find_collection(self):
        if self.prepared:
            self.collection = next((c for c in self.scene.collection.children
                if c.get('worldbridge_report') == str(self.report_path)), None)

    def fail(self, detail):
        self.stop_event.set()
        if self.assets:
            self.assets.cancel()
        if self.steps is not None:
            self.steps.close()
            self.steps = None
        self.find_collection()
        self.report['fatal_error'] = detail
        self.log.write('session_error', traceback=detail)
        self.finish('FAILED_PARTIAL' if self.collection else 'FAILED')

    def tick(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('Blender session must run on main thread')
        if self.done:
            return None
        if bpy.context.scene != self.scene:
            self.cancel('Scene changed during import')
            return None
        try:
            self.advance()
            for warning in self.report['warnings'][self.logged_warnings:]:
                self.log.write('warning', message=warning)
            self.logged_warnings = len(self.report['warnings'])
            self.publish()
        except Exception:
            detail = traceback.format_exc()
            try:
                self.fail(detail)
            except Exception:
                # If persistence itself fails, never hide it or keep a bad timer alive.
                self.done = True
                self.report['status'] = 'FAILED'
                self.report['phase'] = 'FAILED'
                self.report['fatal_error'] = detail + '\nCleanup failure:\n' + traceback.format_exc()
                print(self.report['fatal_error'], flush=True)
                self.publish()
        return None if self.done else .05

    def advance(self):
        if self.worker:
            outcome = self.worker.poll()
            if outcome is None:
                return
            self.worker = None
            kind, payload = outcome
            if kind == 'error':
                self.fail(payload['traceback'])
                return
            self.prepared = payload
            self.token = payload['token']
            self.report = payload['report']
            self.report_path = payload['report_path']
            if payload.get('selected'):
                for task in payload['tasks']:
                    task['force_reload'] = self.force_reload
                cache = self.output / 'cache'
                downloader = self.downloader or (lambda task, event: fetch_asset(task, event, cache))
                self.assets = AssetQueue(payload['tasks'], downloader, self.log)
                self.log.write('selected_models_queued', count=len(payload['tasks']), skipped=self.report['assets_skipped'])
                self.checkpoint()
                return
            self.log.write('backup_preserved', sidecar=str(payload['sidecar']), entities=self.report['entities'])
            self.steps = import_backup_steps(self.filepath, self.output, prepared=payload,
                                            defer_models=True, **self.options)
            return
        if self.steps is not None:
            started = time.monotonic()
            # Both count and time bounds; yield every entity/transform/visual.
            for _ in range(25):
                try:
                    next(self.steps)
                except StopIteration as finished:
                    self.steps = None
                    self.collection, self.report, tasks = finished.value
                    cache = self.output / 'cache'
                    downloader = self.downloader or (lambda task, event: fetch_asset(task, event, cache))
                    self.assets = AssetQueue(tasks, downloader, self.log)
                    self.log.write('placeholders_finished', entities=self.report['entities_processed'],
                                   queued_models=len(tasks), skipped=self.report['assets_skipped'],
                                   warnings=self.report['warnings'])
                    self.report['status'] = 'LOADING_MODELS'
                    self.checkpoint()
                    return
                if time.monotonic() - started > .015:
                    break
            progress = (self.report['phase'], self.report['represented'], self.report['entities_processed'])
            if progress != self.last_log_progress:
                self.log.write('entity_progress', phase=progress[0], anchors=progress[1], processed=progress[2])
                self.last_log_progress = progress
            return
        if not self.assets:
            raise RuntimeError('Session has no active work')
        if bpy.context.mode != 'OBJECT':
            self.report['phase'] = 'WAITING_FOR_OBJECT_MODE'
            return
        action, task, payload = self.assets.step()
        if task:
            self.current = str(task.get('name') or task['url'])
        self.report['assets_downloaded'] = self.assets.downloaded
        if action == 'downloading':
            self.report['phase'] = 'DOWNLOADING'
            self.log.write('download_started', index=task['index'], url=task['url'])
        elif action == 'downloaded':
            self.report['phase'] = 'IMPORTING_NEXT_TICK'
            self.log.write('download_ready', index=task['index'], path=str(payload), url=task['url'])
            self.checkpoint()
        elif action == 'failed':
            self.completed_tasks += 1
            self.asset_failure(task, 'download', payload)
        elif action == 'import':
            self.report['phase'] = 'IMPORTING'
            self.log.write('model_import_started', index=task['index'], path=str(payload), url=task['url'])
            # No network here: this is the only synchronous per-asset Blender step.
            selected = list(bpy.context.selected_objects)
            active = bpy.context.view_layer.objects.active
            try:
                anchor, target_collection = self.target(task)
                if task.get('target_key') is not None and any(role(obj) == 'MODEL' and obj.type == 'MESH' for obj in owned_objects(anchor)):
                    self.report['assets_skipped'] += 1
                    self.report['skipped'].append(dict(index=task['index'], id=task['id'], reason='Model loaded while queued'))
                    self.checkpoint()
                    return
                placeholders = [o for o in anchor.children if o.get('worldbridge_visual')]
                import_model(payload, anchor, task['entity'], target_collection, validated=True)
                self.loaded_anchors.append(anchor)
                self.report.setdefault('texture_diagnostics', []).append(dict(index=task['index'],
                    images=json.loads(anchor.get('worldbridge_texture_diagnostics', '[]'))))
                repairs = json.loads(anchor.get('worldbridge_material_repairs', '[]'))
                if repairs:
                    self.report.setdefault('material_repairs', []).append(dict(index=task['index'], repairs=repairs))
                    self.log.write('material_repaired', index=task['index'], repairs=repairs)
                for placeholder in placeholders:
                    bpy.data.objects.remove(placeholder, do_unlink=True)
                self.report['assets_success'] += 1
                self.log.write('model_import_finished', index=task['index'], url=task['url'])
                self.checkpoint()
            except Exception as exc:
                self.asset_failure(task, 'import', dict(error=str(exc), traceback=traceback.format_exc()))
            finally:
                self.completed_tasks += 1
                for obj in bpy.context.selected_objects:
                    obj.select_set(False)
                for obj in selected:
                    try:
                        if obj.name in bpy.context.view_layer.objects:
                            obj.select_set(True)
                    except ReferenceError:
                        continue  # A replaced placeholder is expected to be gone.
                try:
                    if active and active.name in bpy.context.view_layer.objects:
                        bpy.context.view_layer.objects.active = active
                except ReferenceError:
                    bpy.context.view_layer.objects.active = None
        elif action == 'done':
            issues = self.report['warnings'] or self.report['assets_failed'] or self.report['assets_skipped']
            self.finish('COMPLETE_WITH_WARNINGS' if issues else 'COMPLETE')
            if self.loaded_anchors and getattr(self.scene, 'worldbridge_auto_recover', False):
                from .reconstruction_ui import start
                start(self.loaded_anchors, self.scene)

    def asset_failure(self, task, stage, detail):
        self.report['assets_failed'] += 1
        failure = dict(index=task['index'], id=task['id'], url=task['url'], stage=stage, **detail)
        self.report['failures'].append(failure)
        if self.collection:
            for obj in self.collection.objects:
                if obj.get('worldbridge_record_index') == task['index']:
                    obj['worldbridge_error'] = '%s: %s' % (stage, detail['error'])
        self.log.write('asset_failed', **failure)
        self.checkpoint()

    def target(self, task):
        if 'target_key' in task:
            anchor = self.existing_targets[task['target_key']]
            collection = next(c for c in anchor.users_collection if c.get('worldbridge_sidecar') == anchor['worldbridge_sidecar'])
            return anchor, collection
        return next(o for o in self.collection.objects if o.get('worldbridge_record_index') == task['index']), self.collection
