"""Backup parsing and preservation; safe to call from an I/O worker."""
import json
import uuid
from pathlib import Path
from .parser import load_backup, plan_entities
from .assets import check_cancel


def save_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def prepare_backup(filepath, output_dir, cancel_event=None):
    check_cancel(cancel_event)
    data = load_backup(filepath)
    records, warnings = plan_entities(data)
    check_cancel(cancel_event)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    sidecar = output / ('worldbridge-' + token + '.source.json')
    report_path = output / ('worldbridge-' + token + '.report.json')
    save_json(sidecar, data)
    report = dict(status='IN_PROGRESS', phase='ANCHORS', source=str(Path(filepath).resolve()),
                  sidecar=str(sidecar), entities=len(records), represented=0, entities_processed=0,
                  assets_downloaded=0, assets_success=0, assets_failed=0, assets_skipped=0,
                  assets_cancelled=0, warnings=warnings, failures=[], skipped=[])
    check_cancel(cancel_event)
    return dict(records=records, output=output, token=token, sidecar=sidecar,
                report_path=report_path, report=report)


def prepare_selected(targets, output_dir, token, limit, cancel_event=None):
    """Read original sidecars on the worker; never serialize edited transforms."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = dict(status='LOADING_MODELS', phase='MODELS_PENDING', source='Existing selected entities',
                  entities=len(targets), represented=len(targets), entities_processed=len(targets),
                  assets_downloaded=0, assets_success=0, assets_failed=0, assets_skipped=0,
                  assets_cancelled=0, warnings=[], failures=[], skipped=[])
    documents, tasks = {}, []
    for target in targets:
        check_cancel(cancel_event)
        path = target['sidecar']
        if path not in documents:
            documents[path] = load_backup(path)
        entity = documents[path]['Entities'][target['index']]
        if str(entity.get('id', '')) != target['id']:
            raise ValueError('Sidecar record/ID mismatch for ' + target['id'])
        reason = ''
        if entity.get('type') != 'Model':
            reason = 'Not a model entity'
        elif target['loaded']:
            reason = 'Model already loaded'
        elif not entity.get('visible', True) or not entity.get('modelURL'):
            reason = 'Invisible model or missing URL'
        elif limit > 0 and len(tasks) >= limit:
            reason = 'Safe test model limit'
        if reason:
            report['assets_skipped'] += 1
            report['skipped'].append(dict(index=target['index'], id=target['id'], reason=reason))
        else:
            tasks.append(dict(index=target['index'], id=target['id'], name=entity.get('name', ''),
                              url=entity['modelURL'], entity=entity, target_key=target['target_key'],
                              cache=str(Path(path).parent/'cache')))
    report['sidecars'] = sorted(documents)
    return dict(selected=True, tasks=tasks, output=output, token=token, report=report,
                report_path=output / ('worldbridge-' + token + '.report.json'))
