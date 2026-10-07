"""C-19-6 (DM-89) : load the committed demo records into PostgreSQL and check them with SQL.

  rows   [--output rows.json]          build the table rows from the files only (no database) and print counts
  schema                               apply service/schema.sql to GUARDRAIL_DB_URL
  load                                 replace the demo rows in GUARDRAIL_DB_URL in one transaction
  check  [--offline] [--output x.json] run the check queries (service/queries.py) on GUARDRAIL_DB_URL, or with
                                       --offline on an in-memory SQLite copy of the same rows; exit 1 on a mismatch

Inputs are the small committed files only (C-19-6) : reports/c19/aggregate-main.json, reports/c18-8/exclusions.json,
reports/c18-8/account-corrections.json, each runs/demo/<session>/record/{demo-summary,manifest,judgements,replay}.json,
the batch plans the aggregate names, scenarios/README.md (Korean names) and docs/criteria/demo-final-freeze.json.
Large session logs and logs/ are never opened. Values are copied as recorded (STOP sentences and judgement values are
not recomputed); a value that is not in the records stays NULL. The database URL is read from GUARDRAIL_DB_URL only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402

from service import queries  # noqa: E402
from service.store import (DB_NAME, RecordError, database_name, forbidden_fields, key_hits,  # noqa: E402
                           postgres_store, redact_url, sqlite_store)

LOADER_VERSION = 'demo-db-load-v1'
AGGREGATE = 'reports/c19/aggregate-main.json'
EXCLUSIONS = 'reports/c18-8/exclusions.json'
CORRECTIONS = 'reports/c18-8/account-corrections.json'
SCENARIO_MAP = 'scenarios/README.md'
FREEZE = 'docs/criteria/demo-final-freeze.json'
RUNS = 'runs/demo'
RECORD_FILES = ('demo-summary.json', 'manifest.json', 'judgements.json', 'replay.json')
TASKS = ('DEMO-CT-N', 'DEMO-CL', 'DEMO-CT', 'DEMO-CS', 'DEMO-MR', 'DEMO-LR')
DEMO_ROW = re.compile(r'^\| \[`([^`]+)`\]\([^)]*\) \| ([^|]+) \| ([^|]+) \|')
DATASET_ROW = re.compile(r'^\| `([^`]+)` \| \[`[^`]+`\]\([^)]*\) \| ([^|]+) \|')
DATASET_TASK = re.compile(r'과제는 모두 같습니다 : \*\*([^*]+)\*\*')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def task_of(scenario_id):
    for task in TASKS:
        if scenario_id.startswith(task + '-'):
            return task
    return scenario_id


def variant_of(scenario_id):
    if not scenario_id.startswith('DEMO-'):
        return 'dataset'
    return 'normal' if '-normal-' in scenario_id else 'stall' if '-stall-' in scenario_id else 'natural'


def plan_kind(plan_id):
    if not plan_id:
        return 'none'
    return 'main' if plan_id.startswith('demo-main-') else 'trial' if plan_id.startswith('demo-trial-') else 'other'


def scenario_rows(root, titles):
    """scenarios/README.md demo and dataset tables -> scenario rows (Korean name, type, pair, status, frozen)."""
    text = (root / SCENARIO_MAP).read_text(encoding='utf-8')
    frozen = set(load_json(root / FREEZE)['scenario_ids'])
    dataset_task = DATASET_TASK.search(text)
    rows = []
    for line in text.splitlines():
        demo, dataset = DEMO_ROW.match(line), DATASET_ROW.match(line)
        if demo:
            sid, name, kind = demo.group(1), demo.group(2).strip(), demo.group(3).strip()
            rows.append({'scenario_id': sid, 'korean_name': name, 'task': task_of(sid), 'task_type': kind.split()[0],
                         'variant': variant_of(sid), 'status': '데모 최종 동결' if sid in frozen else None})
        elif dataset:
            sid = dataset.group(1)
            rows.append({'scenario_id': sid, 'korean_name': dataset_task.group(1) if dataset_task else None,
                         'task': 'A-1', 'task_type': 'dataset', 'variant': 'dataset', 'status': dataset.group(2).strip()})
    by_task = {}
    for row in rows:
        by_task.setdefault(row['task'], []).append(row)
    for row in rows:
        pair = [r['scenario_id'] for r in by_task[row['task']] if row['variant'] in ('normal', 'stall')
                and r['variant'] == ('stall' if row['variant'] == 'normal' else 'normal')]
        row.update({'pair_scenario_id': pair[0] if pair else None, 'frozen': row['scenario_id'] in frozen,
                    'title': titles.get(row['scenario_id'])})
    return rows


def step_row(session_id, step, judgement):
    tokens = step.get('tokens') or {}
    tests = step.get('tests') or {}
    criteria = (judgement or {}).get('criteria') or {}
    stop = step.get('stop') or {}
    prompt, completion = tokens.get('prompt'), tokens.get('completion')
    return {
        'session_id': session_id, 'step_id': step['step_id'], 'agent': step.get('agent'), 'role': step.get('role'),
        'step_status': step.get('step_status'), 'failure_reasons': step.get('failure_reasons') or [],
        'state': step.get('state'), 'state_label': step.get('state_label'), 'decision': step.get('decision'),
        'criteria_reason': criteria.get('reason'), 'consecutive_steps': criteria.get('consecutive_steps'),
        'stop_template': stop.get('template_id'), 'stop_text': stop.get('text'), 'blocked': bool(step.get('blocked')),
        'tests_passed': tests.get('passed'), 'tests_total': tests.get('total'),
        'changed_paths': step.get('changed_paths') or [],
        'tokens_prompt': prompt, 'tokens_cached_prompt': tokens.get('cached_prompt'), 'tokens_completion': completion,
        'tokens_reasoning': tokens.get('reasoning'),
        'step_tokens': None if prompt is None or completion is None else prompt + completion,
        'cumulative_tokens': step.get('cumulative_tokens'), 'credits_estimated': step.get('credits_estimated'),
        'cumulative_credits': step.get('cumulative_credits'), 'judgement_ns': (judgement or {}).get('judgement_ns'),
        'facts': step,
    }


def session_rows(root, aggregate, exclusions, corrections):
    """Every committed demo session folder -> one session row and its step rows."""
    counted = {r['session_id']: r for r in aggregate['session_rows']}
    excluded = exclusions['sessions']
    actual = {c['session_id']: c['actual'] for c in corrections['sessions']}
    sessions, steps, titles, inputs = [], [], {}, {}
    for folder in sorted(p for p in (root / RUNS).iterdir() if (p / 'record' / 'replay.json').is_file()):
        record = folder / 'record'
        files = {name: record / name for name in RECORD_FILES}
        missing = [n for n, p in files.items() if not p.is_file()]
        if missing:
            raise RecordError(f'{folder.name}: missing record files {missing}')
        summary, manifest, judgements, replay = (load_json(files[n]) for n in RECORD_FILES)
        for name, path in files.items():
            inputs[str(path.relative_to(root))] = sha256(path)
        sid = replay['session_id']
        if sid != folder.name or summary['session_id'] != sid or judgements['session_id'] != sid:
            raise RecordError(f'{folder.name}: session IDs in the record files differ')
        bad = forbidden_fields(replay['steps'])
        if bad:
            raise RecordError(f'{sid}: replay steps carry model text fields {bad[:3]}')
        scenario_id = replay['scenario_id']
        titles.setdefault(scenario_id, replay.get('title'))
        batch = replay.get('batch') or {}
        row, entry = counted.get(sid), excluded.get(sid)
        if row is not None:
            validity = 'valid'
        elif entry is not None and entry.get('excluded'):
            validity = 'excluded'
        else:
            validity = 'not_counted'
        if row is not None and entry is not None and entry.get('excluded'):
            raise RecordError(f'{sid}: counted by the aggregate and excluded by {EXCLUSIONS}')
        first = summary.get('first_stop') or {}
        tokens = summary.get('tokens') or {}
        if_stopped = replay.get('if_stopped') or {}
        measured = summary.get('credits_measured') or {}
        estimated = summary.get('credits_estimated') or {}
        times = summary.get('session_times') or {}
        code = manifest.get('code') or {}
        prompt, completion = tokens.get('prompt'), tokens.get('completion')
        sessions.append({
            'session_id': sid, 'scenario_id': scenario_id, 'task': task_of(scenario_id),
            'task_type': (row or {}).get('task_type'), 'variant': variant_of(scenario_id),
            'mode': replay.get('guardrail_mode'), 'plan_id': batch.get('plan_id'),
            'plan_kind': plan_kind(batch.get('plan_id')), 'batch_item': batch.get('item'), 'lane': batch.get('lane'),
            'repeat_index': batch.get('repeat'), 'rerun_of': batch.get('rerun_of'),
            'account_label': summary.get('account_label'),
            'account_corrected': actual.get(sid, summary.get('account_label')),
            'git_commit': code.get('git_commit'), 'git_dirty': code.get('git_dirty'),
            'condition_group': summary.get('condition_group'),
            'final_freeze_sha256': batch.get('final_freeze_sha256'), 'model': summary.get('model'),
            'reasoning_effort': summary.get('reasoning_effort'), 'termination_reason': replay.get('termination_reason'),
            'class': (row or {}).get('class'), 'escalated_by': replay.get('escalated_by'),
            'role_labels': replay.get('role_labels'),
            'steps': replay.get('steps_reached'), 'max_steps': replay.get('max_steps'),
            'tokens_prompt': prompt, 'tokens_cached_prompt': tokens.get('cached_prompt'),
            'tokens_completion': completion, 'tokens_reasoning': tokens.get('reasoning'),
            'tokens_total': None if prompt is None or completion is None else prompt + completion,
            'usage_missing_turns': tokens.get('usage_missing_turns'),
            'credits_measured': measured.get('value') if measured.get('status') == 'measured' else None,
            'credits_estimated': estimated.get('value'),
            'first_stop_step': first.get('step_id'), 'first_stop_template': first.get('template_id'),
            'first_stop_text': first.get('text'), 'stop_steps': replay.get('stop_steps') or [],
            'blocked_step': replay.get('blocked_step'),
            'if_stopped_token_ratio': if_stopped.get('token_ratio'),
            'if_stopped_tokens_after': if_stopped.get('tokens_after'),
            'if_stopped_credits_after': if_stopped.get('credits_after'),
            'stall_start': (row or {}).get('stall_start'), 'detection_delay': (row or {}).get('detection_delay'),
            'validity': validity, 'exclusion_code': (entry or {}).get('excluded'),
            'replaced_by': (entry or {}).get('replaced_by'), 'counted': row is not None,
            'started_at': times.get('started_at'), 'ended_at': times.get('ended_at'),
        })
        by_step = {j['step_id']: j for j in judgements.get('steps') or []}
        steps += [step_row(sid, s, by_step.get(s['step_id'])) for s in replay['steps']]
    missing = sorted(set(counted) - {s['session_id'] for s in sessions})
    if missing:
        raise RecordError(f'aggregate sessions without a record folder: {missing[:3]}')
    return sessions, steps, titles, inputs


def build_rows(root=ROOT, *, loaded_at=None):
    """All table rows from the committed files. Pure (no database); the same files give the same rows."""
    root = Path(root)
    aggregate, exclusions = load_json(root / AGGREGATE), load_json(root / EXCLUSIONS)
    corrections = load_json(root / CORRECTIONS)
    sessions, steps, titles, record_inputs = session_rows(root, aggregate, exclusions, corrections)
    scenarios = scenario_rows(root, titles)
    types = {s['scenario_id']: s['task_type'] for s in scenarios}
    unknown = sorted({s['scenario_id'] for s in sessions} - set(types))
    if unknown:
        raise RecordError(f'sessions of scenarios missing from {SCENARIO_MAP}: {unknown}')
    for session in sessions:
        session['task_type'] = session['task_type'] or types[session['scenario_id']]
    plans = {}
    for path in sorted((root / 'batch_plans').glob('*.yaml')):
        plan_id = (yaml.safe_load(path.read_text(encoding='utf-8')) or {}).get('plan_id')
        if plan_id in aggregate['plans']:
            plans[str(path.relative_to(root))] = sha256(path)
    inputs = {p: sha256(root / p) for p in (AGGREGATE, EXCLUSIONS, CORRECTIONS, SCENARIO_MAP, FREEZE)}
    inputs.update(plans)
    inputs['runs/demo/*/record/*.json'] = hashlib.sha256(
        json.dumps(record_inputs, sort_keys=True).encode()).hexdigest()
    rows = {
        'scenarios': scenarios, 'sessions': sessions, 'steps': steps,
        'aggregates': [{'aggregate_id': '+'.join(aggregate['plans']),
                        'aggregate_version': aggregate.get('aggregate_version'), 'plans': aggregate['plans'],
                        'scope': aggregate.get('scope'), 'input_sha256': inputs[AGGREGATE], 'inputs': inputs,
                        'loaded_at': loaded_at or '1970-01-01T00:00:00+00:00', 'body': aggregate}],
    }
    text = json.dumps(rows, ensure_ascii=False)
    hits = key_hits(text)
    if hits:
        raise RecordError(f'key patterns in the rows: {hits}')
    return rows


def row_counts(rows):
    sessions = rows['sessions']
    count = lambda key: {v: sum(1 for s in sessions if s[key] == v)  # noqa: E731
                         for v in sorted({s[key] for s in sessions}, key=lambda x: (x is None, str(x)))}
    return {'loader_version': LOADER_VERSION, 'tables': {t: len(r) for t, r in rows.items()},
            'sessions_by_validity': count('validity'), 'sessions_by_plan_kind': count('plan_kind'),
            'excluded_by_code': {k: v for k, v in count('exclusion_code').items() if k}}


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    rows_cmd = sub.add_parser('rows')
    rows_cmd.add_argument('--output', type=Path)
    sub.add_parser('schema')
    load_cmd = sub.add_parser('load')
    load_cmd.add_argument('--expect-db', default=DB_NAME)
    check_cmd = sub.add_parser('check')
    check_cmd.add_argument('--offline', action='store_true')
    check_cmd.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'rows':
            rows = build_rows()
            report = row_counts(rows)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        elif args.command == 'schema':
            store = postgres_store(read_only=False)
            store.apply_schema()
            report = {'schema': 'applied', 'database': database_name(store)}
        elif args.command == 'load':
            store = postgres_store(read_only=False)
            name = database_name(store)
            if name != args.expect_db:
                raise RecordError(f'connected to database {name!r}, expected {args.expect_db!r}; nothing written')
            rows = build_rows(loaded_at=now())
            store.replace_all(rows)
            report = {'loaded': row_counts(rows), 'database': name}
        else:
            if args.offline:
                store, where = sqlite_store(build_rows()), 'sqlite-in-memory (offline stand-in, same SQL)'
            else:
                store = postgres_store()
                where = 'postgresql:' + database_name(store)
            report = {'database': where, **queries.check(store, load_json(ROOT / AGGREGATE))}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    except RecordError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
    except Exception as error:  # database errors: never echo a URL password
        print(json.dumps({'error': type(error).__name__ + ': ' + redact_url(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report.get('ok') is False else 0


if __name__ == '__main__':
    sys.exit(main())
