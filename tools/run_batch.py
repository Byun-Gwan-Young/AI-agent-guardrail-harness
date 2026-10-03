"""Batch runner for demo sessions (C-18-2, DM-63). No model call of its own: it starts experiments/run_scenario.py
once per plan item, in this window, with this window's keys.

A plan file (batch_plans/*.yaml, demo-batch-plan-v1) lists every session: scenario, mode (observe / block) and repeat
number. One window runs one lane (--lane k --lanes n), one session at a time, in plan order. Items with
one_at_a_time (DM-52 ④: academic_search, LR) all go to the last lane, which runs nothing else; the other items are
dealt round-robin to the other lanes. With one lane, that lane runs everything.

Before each session the target proxy's GET /conditions must match the plan item: guardrail mode, criteria version,
the deadlock-v0.3 freeze of this checkout, and the pinned model with the run-conditions file it came from. A mismatch
stops the lane. Observe and block proxies listen on their own ports (--observe-proxy, --block-proxy).

Resume: an item counts as done when a session folder under runs/demo/ carries this plan ID and item in its
conditions.json (batch) and ended other than runner_error. Done items are skipped, so a lane stopped and started
again runs nothing twice. A runner_error or interrupted item is not run again unless --rerun-failed is given (the new
run records rerun_of). Two runner_errors in a row stop the lane.

After each session tools/summarize_demo_session.py runs here (key scan with this window's keys) and one JSON line goes
to runs/demo-batches/<plan id>/lane-<k>-of-<n>.jsonl; the runner's output goes to the .log beside it. A key found by
the scan stops the lane. Key values are never printed or written; only the PM's --account-label is recorded.

  run_batch.py run --plan batch_plans/demo-trial-c18-2.yaml --lane 1 --lanes 3 --account-label A
  run_batch.py status --plan batch_plans/demo-trial-c18-2.yaml --lanes 3
"""
import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import criteria_freeze  # noqa: E402
from experiment_config import load_run_conditions  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402

PLAN_VERSION = 'demo-batch-plan-v1'
PLAN_KEYS = {'plan_version', 'plan_id', 'description', 'items'}
ITEM_KEYS = {'scenario', 'mode', 'repeats', 'one_at_a_time'}
MODES = ('observe', 'block')
ID_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-')
DEMO_RUNS = ROOT / 'runs' / 'demo'
RECORDS_ROOT = ROOT / 'runs' / 'demo-batches'
DEFAULT_PROXIES = {'observe': 'http://127.0.0.1:8000', 'block': 'http://127.0.0.1:8001'}
RUNNER_ERROR = 'runner_error'
STOP_AFTER_RUNNER_ERRORS = 2
KMU_KEY, SEARCH_KEY = 'KMU_API_KEY', 'TAVILY_API_KEY'
PROTOCOL_V10 = 'tool-capable-step-v10-final-report-allowlist'
INDEPENDENT = 'independent-sources-v1'
DIALOGUE_CONTRACT = 'output-contract-v3'


@dataclass(frozen=True)
class Item:
    scenario: str
    scenario_id: str
    mode: str
    repeat: int
    one_at_a_time: bool

    @property
    def key(self):
        return f'{self.scenario_id}:{self.mode}:{self.repeat}'


def now():
    return datetime.now(timezone.utc).isoformat()


def load_plan(path):
    """The plan's sessions in order. Checked: version, keys, modes, repeat numbers, no item twice."""
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or set(data) - PLAN_KEYS or data.get('plan_version') != PLAN_VERSION:
        raise ValueError('A plan is a mapping with plan_version ' + PLAN_VERSION + ', plan_id, items')
    plan_id = data.get('plan_id')
    if not isinstance(plan_id, str) or not plan_id or set(plan_id) - ID_CHARS:
        raise ValueError('plan_id takes letters, digits, _ . -')
    items = []
    for entry in data.get('items') or []:
        if not isinstance(entry, dict) or set(entry) - ITEM_KEYS or not {'scenario', 'mode', 'repeats'} <= set(entry):
            raise ValueError('A plan item has scenario, mode, repeats and optionally one_at_a_time')
        scenario = entry['scenario']
        relative = Path(scenario)
        if relative.is_absolute() or relative.parts[:1] != ('scenarios',) or relative.suffix != '.yaml' \
                or '..' in relative.parts:
            raise ValueError('scenario must be a scenarios/<ID>.yaml path: ' + str(scenario))
        if entry['mode'] not in MODES:
            raise ValueError('mode must be observe or block: ' + str(entry['mode']))
        repeats = entry['repeats']
        if not isinstance(repeats, list) or not repeats or len(set(repeats)) != len(repeats) \
                or any(type(r) is not int or r < 1 for r in repeats):
            raise ValueError('repeats must be distinct positive integers: ' + scenario)
        exclusive = entry.get('one_at_a_time', False)
        if type(exclusive) is not bool:
            raise ValueError('one_at_a_time must be true or false')
        items += [Item(relative.as_posix(), relative.stem, entry['mode'], r, exclusive) for r in repeats]
    keys = [i.key for i in items]
    if not items or len(set(keys)) != len(keys):
        raise ValueError('A plan lists at least one session and each scenario, mode and repeat once')
    return {'plan_id': plan_id, 'plan_sha256': hashlib.sha256(raw).hexdigest(), 'path': str(path), 'items': items}


def lane_items(plan, lane, lanes):
    """The items of one lane, in plan order (see module docstring)."""
    if type(lanes) is not int or type(lane) is not int or not 1 <= lane <= lanes:
        raise ValueError('--lane must be between 1 and --lanes')
    items = plan['items']
    if lanes == 1:
        return list(items)
    exclusive = [i for i in items if i.one_at_a_time]
    others = [i for i in items if not i.one_at_a_time]
    if exclusive:
        if lane == lanes:
            return exclusive
        general = lanes - 1
    else:
        general = lanes
    return [i for n, i in enumerate(others) if n % general == lane - 1]


def plan_sessions(plan, runs_root=DEMO_RUNS):
    """item key -> the session folders made for it under this plan ID, oldest first."""
    found = {}
    for conditions_path in sorted(Path(runs_root).glob('*/conditions.json')):
        try:
            conditions = json.loads(conditions_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        batch = conditions.get('batch') or {}
        if batch.get('plan_id') != plan['plan_id']:
            continue
        folder = conditions_path.parent
        summary_path = folder / 'summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else None
        found.setdefault(batch.get('item'), []).append({
            'session_id': folder.name, 'started': conditions_path.stat().st_mtime,
            'termination_reason': (summary or {}).get('termination_reason'), 'finished': summary is not None})
    for sessions in found.values():
        sessions.sort(key=lambda s: s['started'])
    return found


def item_state(sessions):
    """done (a session that ended other than runner_error), failed (its last session ended in runner_error),
    interrupted (its last session has no summary), or pending (none)."""
    if not sessions:
        return 'pending'
    if any(s['finished'] and s['termination_reason'] != RUNNER_ERROR for s in sessions):
        return 'done'
    return 'failed' if sessions[-1]['finished'] else 'interrupted'


def proxy_conditions(url):
    import httpx
    response = httpx.get(url.rstrip('/') + '/conditions', timeout=10)
    response.raise_for_status()
    return response.json()


def proxy_problems(item, scenario, observed, root=ROOT):
    """Why this proxy must not take this item ([] when it may)."""
    problems = []
    if observed.get('guardrail_mode') != item.mode:
        problems.append(f"proxy mode {observed.get('guardrail_mode')}, plan item {item.mode}")
    if observed.get('criteria_version') != scenario.criteria_version:
        problems.append(f"proxy criteria {observed.get('criteria_version')}, scenario {scenario.criteria_version}")
    frozen = criteria_freeze.freeze(scenario.criteria_version, root)
    if frozen is not None and observed.get('criteria_freeze_sha256') != frozen['sha256']:
        problems.append('proxy deadlock-v0.3 freeze differs from this checkout (restart the proxy)')
    pin = observed.get('pinned_model') or {}
    run_conditions = getattr(scenario, 'run_conditions', None)
    if run_conditions is None:
        problems.append('scenario has no run_conditions (not a demo scenario)')
    else:
        expected = load_run_conditions(run_conditions, root)
        if pin.get('name') != expected['model']:
            problems.append(f"proxy model {pin.get('name')}, {run_conditions} {expected['model']}")
        if pin.get('run_conditions_sha256') != expected['sha256']:
            problems.append(run_conditions + ' changed since the proxy started (restart the proxy)')
    return problems


def required_keys(scenario):
    tools = {t for agent in scenario.agents for t in agent.tools}
    return [KMU_KEY] + ([SEARCH_KEY] if 'web_search' in tools else [])


def command(item, scenario, proxy_url, plan, lane, lanes, account_label, rerun_of=None):
    contract = DIALOGUE_CONTRACT if scenario.task_kind == 'dialogue' else scenario.output_contract
    batch = {'plan_id': plan['plan_id'], 'plan_sha256': plan['plan_sha256'], 'item': item.key, 'mode': item.mode,
             'repeat': item.repeat, 'lane': lane, 'lanes': lanes, 'rerun_of': rerun_of}
    args = [sys.executable, 'experiments/run_scenario.py', item.scenario, '--phase', 'demo',
            '--runner-protocol', PROTOCOL_V10, '--output-contract', contract, '--collection-policy', INDEPENDENT,
            '--api-key-env', KMU_KEY, '--proxy-url', proxy_url, '--run-index', str(item.repeat),
            '--batch-item', json.dumps(batch, ensure_ascii=False, sort_keys=True)]
    return args + (['--account-label', account_label] if account_label else [])


def run_subprocess(args, log):
    """Start one session; its output goes to the lane log. Returns (exit code, session ID or None)."""
    session_id = None
    with subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          encoding='utf-8', errors='replace') as process:
        for line in process.stdout:
            log.write(line)
            log.flush()
            if line.startswith('session_id:') and session_id is None:
                session_id = line.split()[1]
                print('  started', session_id, flush=True)
    return process.returncode, session_id


def short_summary(folder, summarize):
    """One lane-record line from the summary tool (no model text)."""
    s = summarize(folder)
    first = s.get('first_stop') or {}
    return {'session_id': s['session_id'], 'termination_reason': s['termination_reason'], 'steps': s['steps'],
            'tests_passed': s['tests_passed'], 'first_stop_step': first.get('step_id'),
            'first_stop_template': first.get('template_id'),
            'credits_measured': (s.get('credits_measured') or {}).get('value'),
            'credits_estimated': (s.get('credits_estimated') or {}).get('value'),
            'condition_group': s.get('condition_group'), 'model': s.get('model'),
            'account_label': s.get('account_label'),
            'key_scan_clean': s['key_scan']['clean'], 'key_values_checked': s['key_scan']['key_values_checked']}


def default_summarize(folder):
    from tools.summarize_demo_session import summarize
    return summarize(folder)


def run_lane(plan, lane, lanes, *, proxies=None, account_label=None, rerun_failed=False, runner=run_subprocess,
             get=proxy_conditions, summarize=default_summarize, runs_root=DEMO_RUNS, records_root=RECORDS_ROOT,
             environ=None, root=ROOT, out=print):
    """Runs one lane to its end or to a stop. Returns what happened (also written to the lane record)."""
    proxies = {**DEFAULT_PROXIES, **(proxies or {})}
    environ = os.environ if environ is None else environ
    items = lane_items(plan, lane, lanes)
    folder = Path(records_root) / plan['plan_id']
    folder.mkdir(parents=True, exist_ok=True)
    name = f'lane-{lane}-of-{lanes}'
    record_path, log_path = folder / (name + '.jsonl'), folder / (name + '.log')
    result = {'plan_id': plan['plan_id'], 'lane': lane, 'lanes': lanes, 'ran': [], 'skipped': [], 'stopped': None}

    def write(entry):
        with record_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': now(), 'plan_id': plan['plan_id'], 'plan_sha256': plan['plan_sha256'],
                                     'lane': lane, 'lanes': lanes, **entry}, ensure_ascii=False) + '\n')

    def stop(reason):
        result['stopped'] = reason
        write({'event': 'lane_stopped', 'reason': reason})
        out(f'lane {lane}/{lanes} stopped: {reason}')
        return result

    scenarios = {}
    for item in items:
        path = Path(root) / item.scenario
        if not path.is_file():
            return stop(f'{item.scenario} not found')
        scenario = scenarios.setdefault(item.scenario, load_scenario(path))
        if scenario.scenario_id != item.scenario_id:
            return stop(f'{item.scenario} holds scenario_id {scenario.scenario_id}')
        if item.one_at_a_time != any('academic_search' in a.tools for a in scenario.agents):
            return stop(f'{item.scenario}: one_at_a_time must be set exactly for academic_search (LR) scenarios')
    missing = sorted({k for s in scenarios.values() for k in required_keys(s) if not environ.get(k)})
    if missing:
        return stop('not set in this window: ' + ', '.join(missing))
    write({'event': 'lane_started', 'items': [i.key for i in items], 'account_label': account_label})
    out(f'lane {lane}/{lanes}: {len(items)} items, plan {plan["plan_id"]}')
    errors_in_row = 0
    for item in items:
        sessions = plan_sessions(plan, runs_root).get(item.key, [])
        state = item_state(sessions)
        if state == 'done' or (state in ('failed', 'interrupted') and not rerun_failed):
            result['skipped'].append({'item': item.key, 'state': state})
            out(f'  skip {item.key} ({state})')
            continue
        scenario = scenarios[item.scenario]
        url = proxies[item.mode]
        try:
            problems = proxy_problems(item, scenario, get(url), root)
        except Exception as error:  # the proxy is down or answers something else
            problems = [f'cannot read {url}/conditions: {type(error).__name__}']
        if problems:
            return stop(f'{item.key}: ' + '; '.join(problems))
        rerun_of = sessions[-1]['session_id'] if sessions else None
        out(f'  run {item.key} -> {url}')
        with log_path.open('a', encoding='utf-8') as log:
            log.write(f'=== {now()} {item.key}\n')
            code, session_id = runner(command(item, scenario, url, plan, lane, lanes, account_label, rerun_of), log)
        session_folder = Path(runs_root) / session_id if session_id else None
        finished = session_folder is not None and (session_folder / 'summary.json').exists()
        termination = (json.loads((session_folder / 'summary.json').read_text(encoding='utf-8'))
                       ['termination_reason'] if finished else RUNNER_ERROR)
        entry = {'event': 'session', 'item': item.key, 'rerun_of': rerun_of, 'exit_code': code,
                 'session_id': session_id, 'termination_reason': termination}
        if finished:
            try:
                entry['summary'] = short_summary(session_folder, summarize)
            except Exception as error:  # a summary failure is recorded; it does not hide the session
                entry['summary_error'] = type(error).__name__ + ': ' + str(error)[:200]
        write(entry)
        result['ran'].append(entry)
        out(f'  done {item.key}: {termination}' + (f" ({entry['summary']['credits_measured']} credits)"
                                                    if 'summary' in entry else ''))
        if 'summary' in entry and not entry['summary']['key_scan_clean']:
            return stop(f'{item.key}: the key scan found a key in {session_id}; do not commit that folder')
        errors_in_row = errors_in_row + 1 if termination == RUNNER_ERROR else 0
        if errors_in_row >= STOP_AFTER_RUNNER_ERRORS:
            return stop(f'{STOP_AFTER_RUNNER_ERRORS} runner_error in a row (last {item.key}, {session_id}); '
                        'see ' + log_path.name)
    write({'event': 'lane_finished'})
    out(f'lane {lane}/{lanes} finished')
    return result


def status(plan, lanes, runs_root=DEMO_RUNS):
    """Plan against session folders, lane by lane: done, failed, interrupted, pending, and how sessions ended."""
    found = plan_sessions(plan, runs_root)
    report = {'plan_id': plan['plan_id'], 'plan_sha256': plan['plan_sha256'], 'lanes': {}, 'total': Counter()}
    for lane in range(1, lanes + 1):
        rows = {'done': [], 'failed': [], 'interrupted': [], 'pending': []}
        endings = Counter()
        for item in lane_items(plan, lane, lanes):
            sessions = found.get(item.key, [])
            rows[item_state(sessions)].append(item.key)
            for s in sessions:
                endings[s['termination_reason'] or 'unfinished'] += 1
        counts = {k: len(v) for k, v in rows.items()}
        report['lanes'][lane] = {'planned': sum(counts.values()), **counts, 'endings': dict(endings),
                                 'failed_items': rows['failed'], 'interrupted_items': rows['interrupted'],
                                 'pending_items': rows['pending']}
        report['total'].update({'planned': sum(counts.values()), **counts})
    report['total'] = dict(report['total'])
    unknown = sorted(k for k in found if k not in {i.key for i in plan['items']})
    report['sessions_with_unknown_items'] = unknown
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('run', help='run one lane in this window')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--lane', type=int, required=True)
    run.add_argument('--lanes', type=int, required=True)
    run.add_argument('--account-label', default=None, help='the PM label of the account whose key this window holds')
    run.add_argument('--observe-proxy', default=DEFAULT_PROXIES['observe'])
    run.add_argument('--block-proxy', default=DEFAULT_PROXIES['block'])
    run.add_argument('--rerun-failed', action='store_true',
                     help='run failed or interrupted items of this lane again (recorded as rerun_of)')
    show = sub.add_parser('status', help='plan against finished sessions, lane by lane')
    show.add_argument('--plan', type=Path, required=True)
    show.add_argument('--lanes', type=int, required=True)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if args.action == 'status':
        print(json.dumps(status(plan, args.lanes), ensure_ascii=False, indent=1))
        return 0
    result = run_lane(plan, args.lane, args.lanes, account_label=args.account_label, rerun_failed=args.rerun_failed,
                      proxies={'observe': args.observe_proxy, 'block': args.block_proxy})
    return 1 if result['stopped'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
