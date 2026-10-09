"""Demo screen (C-19-3, DM-76): one static HTML file built from the committed demo records.

  build --aggregate <aggregate.json> --output <demo.html> [--runs-root runs/demo] [--api]

Inputs are only what C-19-1 already wrote and the repository already holds: the aggregate JSON (tools/aggregate_demo.py),
each counted session's record/replay.json, record/manifest.json (start time) and record/judgements.json (judgement_ns),
the batch plan files (item count), the final freeze record (content hash), the scenario pair difference
(tools/scenario_preflight.py pair_diff), the Korean scenario names of scenarios/README.md, and the proxy code and
configuration for the system page (header name, routes, criteria parameters, model). Nothing else is read: no raw
session log, narrative, deliverable value, tool output or model reasoning (C-19-1 rule). The page has its style,
script and data inline and makes no request; it opens with a double click.

A trial aggregate (plan IDs demo-trial-*) gets the "시험 세션 — 본 실행 결과 아님" band and source line; a main aggregate
(demo-main-*) gets the main source line. Features that do not exist (project sign-up, guardrail keys, warn mode, false
positive report, policy and integration settings) are shown disabled with "구현 전" (DM-76 ④⑤).

The "실시간 모니터" menu (C-19-4) works only when tools/demo_live.py serves this page (page(..., live=True) adds the
polling script); the file opened with a double click has no request code and says the live server is off.

Query API mode (C-19-7, build --api, the page the server's Caddy serves): when the page is served over http(s) and
/api/summary of the same server answers, the dashboard cards, the session table and each session's steps come from
the query API (service/api.py, the database); otherwise (file, no answer, wrong shape) the page keeps the records in
the file. The source line says which ("데이터 : DB (조회 API)" / "데이터 : 파일에 담긴 기록"). Without --api the
page has no request code, as before.
Offline; no model call.
"""
import argparse
from datetime import datetime, timedelta, timezone
import html
import json
import math
from pathlib import Path
import re
import statistics
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import scenario_preflight  # noqa: E402

UI_VERSION = 'demo-ui-v1'
TASKS = ('DEMO-CL', 'DEMO-CT', 'DEMO-CS', 'DEMO-MR', 'DEMO-LR')
TASK_NAMES = {'DEMO-CL': '코드 버그 수정', 'DEMO-CT': '승인 절차 코딩', 'DEMO-CT-N': 'A-1 코딩 사본',
              'DEMO-CS': '고객 지원', 'DEMO-MR': '시장 조사', 'DEMO-LR': '논문 조사'}
VARIANT_NAMES = {'normal': '정상판', 'stall': '교착판', 'natural': '비교군'}
CLASS_NAMES = {'success': '성공', 'stalled': '교착', 'escalated': '에스컬레이션', 'other': '기타'}
PLANNED = (
    ('project', '프로젝트 만들기', '가입하고 프로젝트를 만드는 화면. 지금은 프록시를 로컬에서 직접 띄운다.'),
    ('key', '가드레일 키 발급', '프로젝트별 가드레일 키. 지금은 세션 헤더 하나만 받는다.'),
    ('warn', '경고 모드', 'STOP 을 알리기만 하고 요청은 그대로 보내는 모드. 지금은 관측·차단(데모 한정)만 있다.'),
    ('report', '오탐 신고', '사용자가 STOP 을 오탐으로 표시하는 버튼. 지금은 오탐을 기록으로만 센다.'),
    ('policy', '정책 설정', '판정 규칙·파라미터를 화면에서 고르는 기능. 지금은 동결된 설정 파일 하나 (deadlock-v0.3).'),
    ('integration', '연동 설정', '에이전트 프레임워크 연동 마법사. 지금은 base_url 과 세션 헤더를 직접 바꾼다.'),
)
KST = timezone(timedelta(hours=9))


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def optional(path):
    path = Path(path)
    return load(path) if path.is_file() else None


def task_of(scenario_id):
    for task in ('DEMO-CT-N',) + TASKS:
        if scenario_id.startswith(task + '-'):
            return task
    return scenario_id


def variant_of(scenario_id):
    return 'normal' if '-normal-' in scenario_id else 'stall' if '-stall-' in scenario_id else 'natural'


def data_kind(plans):
    """main when every plan is a main plan (demo-main-*), trial when every plan is a trial plan (demo-trial-*)."""
    if plans and all(p.startswith('demo-main-') for p in plans):
        return 'main'
    if plans and all(p.startswith('demo-trial-') for p in plans):
        return 'trial'
    return 'mixed'


def korean_names(root):
    """scenario ID -> the Korean name of scenarios/README.md (the map of C-19-5); missing IDs get no name."""
    names = {}
    readme = Path(root) / 'scenarios' / 'README.md'
    if readme.is_file():
        for line in readme.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\| \[`([^`]+)`\]\([^)]*\) \| ([^|]+) \|', line)
            if m:
                names[m.group(1)] = m.group(2).strip()
    return names


def issue_definitions(root, scenario_ids):
    """scenario ID -> {issue ID: one-line definition} from the scenario's allowed_issues (the agents' closed list)."""
    out = {}
    for scenario_id in sorted(set(scenario_ids)):
        path = Path(root) / 'scenarios' / f'{scenario_id}.yaml'
        if path.is_file():
            allowed = yaml.safe_load(path.read_text(encoding='utf-8')).get('allowed_issues') or []
            out[scenario_id] = {i['id']: i.get('definition') for i in allowed if isinstance(i, dict) and i.get('id')}
    return out


def plan_items(root, plan_id):
    for path in sorted((Path(root) / 'batch_plans').glob('*.yaml')):
        plan = yaml.safe_load(path.read_text(encoding='utf-8'))
        if plan.get('plan_id') == plan_id:
            return sum(len(item.get('repeats') or []) for item in plan.get('items') or [])
    return None


def freeze_content_hash(root, record_sha256):
    """The content hash of docs/criteria/demo-final-freeze.json when that file is the record the sessions name."""
    import hashlib
    path = Path(root) / 'docs' / 'criteria' / 'demo-final-freeze.json'
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record_sha256:
        return None
    return load(path).get('sha256')


def slim_step(step, role_labels):
    """The per-step values the screen shows; every field comes from replay.json (no narrative, no reasoning)."""
    report = step.get('report') or {}
    claim = step.get('completion_claim')
    tools = step.get('tools') or []
    tokens = step.get('tokens') or {}
    return {
        'n': step['step_id'], 'agent': step.get('agent'), 'role': step.get('role'), 'state': step.get('state'),
        'label': step.get('state_label'),
        'stop': None if not step.get('stop') else {'t': step['stop'].get('template_id'), 'text': step['stop'].get('text')},
        'blocked': bool(step.get('blocked')), 'status': step.get('step_status'),
        'fail': step.get('failure_reasons') or [],
        'tests': None if not step.get('tests') else [step['tests']['passed'], step['tests']['total']],
        'report': None if not step.get('report') else {
            'status': report.get('status_label') or report.get('status'),
            'handoff': role_labels.get(report.get('handoff_to'), report.get('handoff_to')),
            'adopted': report.get('adopted_items'), 'issues': len(report.get('open_issue_ids') or []),
            'issue_ids': list(report.get('open_issue_ids') or []),
            'spec': report.get('spec_approved'), 'declared': bool(report.get('completion_declared')),
            'deliverable': bool(report.get('deliverable_reported'))},
        'claim': None if claim is None else bool(claim.get('accepted')),
        'tools': len(tools), 'tool_errors': sum(1 for t in tools if t.get('is_error')),
        'changed': len(step.get('changed_paths') or []), 'paths': list(step.get('changed_paths') or []),
        'tok': (tokens.get('prompt') or 0) + (tokens.get('completion') or 0),
        'cum': step.get('cumulative_tokens'), 'cumc': step.get('cumulative_credits'),
    }


def session_entry(row, record, names):
    replay = optional(record / 'replay.json')
    manifest = optional(record / 'manifest.json') or {}
    started = ((manifest.get('run') or {}).get('started_at'))
    roles = (replay or {}).get('role_labels') or {}
    if_stopped = row.get('if_stopped') or (replay or {}).get('if_stopped')
    return {
        'id': row['session_id'], 'short': row['session_id'][-32:][:8], 'scenario': row['scenario_id'],
        'name': names.get(row['scenario_id']), 'title': (replay or {}).get('title'),
        'task': row['task'], 'task_name': TASK_NAMES.get(row['task'], row['task']),
        'variant': variant_of(row['scenario_id']), 'type': row['task_type'], 'mode': row['mode'],
        'class': row['class'], 'termination': row['termination_reason'], 'escalated_by': row.get('escalated_by'),
        'escalated_by_label': roles.get(row.get('escalated_by'), row.get('escalated_by')),
        'steps': row['steps'], 'max_steps': (replay or {}).get('max_steps'), 'tokens': row.get('tokens'),
        'credits': row.get('credits_measured') if row.get('credits_measured') is not None else row.get('credits_estimated'),
        'first_stop': row.get('first_stop_step'), 'template': row.get('first_stop_template'),
        'stop_text': row.get('first_stop_text'), 'stop_steps': row.get('stop_steps') or [],
        'blocked_step': (replay or {}).get('blocked_step'),
        'if_stopped': None if not if_stopped else {'ratio': if_stopped.get('token_ratio'),
                                                   'tokens_after': if_stopped.get('tokens_after')},
        'started_at': started, 'account': row.get('account_label'), 'plan': row.get('plan_id'),
        'replay': replay is not None,
        'step_rows': [] if replay is None else [slim_step(s, roles) for s in replay['steps']],
    }


def judgement_ms(rows, runs_root):
    """Rule judgement time over every counted session's steps (S-5 judgement_ns), as C-19-2 reported it."""
    values = []
    for row in rows:
        judgements = optional(Path(runs_root) / row['session_id'] / 'record' / 'judgements.json')
        for step in (judgements or {}).get('steps') or []:
            if step.get('judgement_ns') is not None:
                values.append(step['judgement_ns'])
    if not values:
        return None
    values.sort()
    return {'n': len(values), 'p50': round(statistics.median(values) / 1e6, 2),
            'p99': round(values[math.ceil(0.99 * len(values)) - 1] / 1e6, 2)}


def headline(aggregate, rows):
    """The presentation numbers (final report section 4) computed from the aggregate's rows."""
    observe = [r for r in rows if r['mode'] == 'observe']
    normal_success = [r for r in observe if variant_of(r['scenario_id']) == 'normal' and r['class'] == 'success']
    false_positive = [r for r in normal_success if r['first_stop_step'] is not None]
    # A STOP before the success step: a block-mode proxy would have refused the requests that led to the success.
    before_success = [r for r in false_positive if r['first_stop_step'] < r['steps']]
    stall = [r for r in observe if variant_of(r['scenario_id']) == 'stall']
    reached = [r for r in stall if r['class'] == 'stalled']
    detected = [r for r in reached if r['first_stop_step'] is not None]
    ratios = [r['if_stopped']['token_ratio'] for r in detected if r.get('if_stopped')]
    block = {}
    for table in aggregate['scenarios']:
        if not table.get('block'):
            continue
        sessions = [r for r in rows if r['mode'] == 'block' and r['scenario_id'] == table['scenario_id']]
        block[table['scenario_id']] = {
            'runs': table['block']['runs'], 'classes': table['block']['classes'],
            'with_stop': sum(1 for r in sessions if r['first_stop_step'] is not None),
            'token_saving': table['block']['token_saving_vs_observe'],
            'credit_saving': table['block']['credit_saving_vs_observe'],
            'observe_estimate': table.get('if_stopped_token_ratio_mean'),
            'judged': any(r['first_stop_step'] is not None for r in sessions)}
    classes = {}
    for r in observe:
        classes[r['class']] = classes.get(r['class'], 0) + 1
    return {
        'observe_sessions': len(observe), 'observe_classes': classes,
        'block_sessions': sum(1 for r in rows if r['mode'] == 'block'),
        'normal_runs': aggregate['headline']['normal_runs'], 'normal_success': len(normal_success),
        'false_positive': len(false_positive),
        'false_positive_by_task': {t: sum(1 for r in false_positive if r['task'] == t) for t in TASKS
                                   if any(r['task'] == t for r in false_positive)},
        'blocked_before_success': len(before_success),
        'blocked_before_success_sessions': [[r['session_id'][-32:][:8], r['first_stop_step'], r['steps']]
                                            for r in before_success],
        'stall_runs': len(stall), 'stall_reached': len(reached), 'stall_detected': len(detected),
        'stall_detected_by_task': {t: [sum(1 for r in detected if r['task'] == t), sum(1 for r in reached if r['task'] == t)]
                                   for t in TASKS if any(r['task'] == t for r in reached)},
        'missed': [r['session_id'][-32:][:8] for r in reached if r['first_stop_step'] is None],
        'stall_escalated': sum(1 for r in stall if r['class'] == 'escalated'),
        't1_stall_stop': sum(1 for r in stall if r['task_type'] == 'T1' and r['first_stop_step'] is not None),
        'saving_mean': None if not ratios else round(sum(ratios) / len(ratios), 5),
        'saving_by_type': {t['task_type']: t['if_stopped_token_ratio_mean_detected'] for t in aggregate['types']
                           if t.get('if_stopped_token_ratio_mean_detected') is not None},
        'block': block,
        'credits_measured_total': aggregate['headline'].get('credits_measured_total'),
    }


def changed_lines(diff):
    return [line for line in diff.splitlines() if line[:1] in '+-' and not line.startswith(('+++', '---'))
            and line[1:].strip()]


def pair_lines(root, task):
    """The line(s) the stall version changes (DM-5): the task text, else the non-test fixture files, else the tests."""
    a, b = (Path(root) / 'scenarios' / f'{task}-{v}-v1.yaml' for v in ('normal', 'stall'))
    if not a.is_file() or not b.is_file():
        return None
    pair = scenario_preflight.pair_diff(a, b)
    a_task, b_task = (yaml.safe_load(p.read_text(encoding='utf-8')).get('task') or '' for p in (a, b))
    lines = []
    if a_task != b_task:
        lines += [{'where': '과제 문장', 'line': l} for l in changed_lines(scenario_preflight.unified(a_task, b_task, 'a', 'b'))]
    files = pair['fixture_files_differing']
    plain = [f for f in files if not f['path'].startswith('tests/')] or files
    if not lines:
        for f in plain:
            lines += [{'where': f['path'], 'line': l} for l in changed_lines(f.get('diff', ''))]
    return {'lines': lines, 'files': [f['path'] for f in files],
            'scenario_keys': pair['scenario_values_differing_beyond_identity'],
            'judge_same': None if pair['judge_files'] is None else pair['judge_files']['same_file']}


def proxy_facts(root):
    """Names and values the system page shows, read from the proxy code and the demo configuration."""
    root = Path(root)
    proxy = (root / 'proxy.py').read_text(encoding='utf-8')
    observation = (root / 'observation_api.py').read_text(encoding='utf-8')
    config = yaml.safe_load((root / 'guardrail-deadlock-v0.3-kmu.yaml').read_text(encoding='utf-8'))
    block_config = yaml.safe_load((root / 'guardrail-deadlock-v0.3-kmu-block.yaml').read_text(encoding='utf-8'))
    conditions = yaml.safe_load((root / config['run_conditions']).read_text(encoding='utf-8'))
    params = config['criteria_parameters']
    ports = {}
    commands = root / 'reports' / 'c18-6' / 'pm-commands.md'
    if commands.is_file():
        for m in re.finditer(r'GUARDRAIL_CONFIG=(\S+) .*?--port (\d+)', commands.read_text(encoding='utf-8')):
            ports[m.group(1)] = int(m.group(2))
    host = re.match(r'https?://([^/]+)', config['upstream']['base_url'])
    return {
        'session_header': re.search(r'headers\.get\("(X-Guardrail-[A-Za-z]+)"\)', proxy).group(1),
        'turn_header': re.search(r'"(X-Guardrail-Turn)"', proxy).group(1),
        'chat_route': re.search(r'@app\.post\("(/v1/chat/[a-z]+)"\)', proxy).group(1),
        'session_route': re.search(r'@app\.post\("(/sessions)"\)', proxy).group(1),
        'observation_route': re.search(r'@app\.post\("([^"]+)"\)', observation).group(1),
        'block_status': 403 if 'status_code=403' in proxy else None,
        'criteria_version': params['criteria_version'], 'progress_version': params['progress_version'],
        'explanation_version': params['explanation_version'], 'n': params['consecutive_steps'],
        'k': params['plateau_steps'], 't1_metrics': params['t1_metrics'],
        'mode_observe': config.get('guardrail_mode', 'observe'), 'mode_block': block_config.get('guardrail_mode'),
        'model': conditions['model'], 'reasoning_effort': conditions['reasoning_effort'],
        'upstream_host': host.group(1) if host else None,
        'port_observe': ports.get('guardrail-deadlock-v0.3-kmu.yaml'),
        'port_block': ports.get('guardrail-deadlock-v0.3-kmu-block.yaml'),
    }


def example_observation(session, runs_root, root=ROOT):
    """A runner observation for one step of a real session, checked against the proxy's Observation schema."""
    if not session or not session['step_rows']:
        return None
    record = Path(runs_root) / session['id'] / 'record'
    replay = optional(record / 'replay.json') or {}
    step = next((s for s in replay.get('steps') or [] if s.get('stop')), None) or (replay.get('steps') or [None])[0]
    if step is None:
        return None
    registration = ((optional(record / 'manifest.json') or {}).get('registration') or {}).get('value') or {}
    scenario = yaml.safe_load((Path(root) / 'scenarios' / f"{session['scenario']}.yaml").read_text(encoding='utf-8'))
    suite = (((scenario.get('success_criteria') or {}).get('test_suite')) or {}).get('test_suite_id')
    body = {'step_id': step['step_id'], 'agent_id': step['agent'], 'llm_turns': [1, 2],
            'progress_source': registration.get('progress_source'),
            'progress_metric': registration.get('progress_metric'),
            'conversation': None if step.get('report') is None else {
                'source_kind': 'structured', 'open_issue_ids': step['report'].get('open_issue_ids') or []},
            'artifact': None if not step.get('tests') else {
                'test_pass_count': step['tests']['passed'], 'test_total_count': step['tests']['total'],
                'test_suite_id': suite}}
    body = {k: v for k, v in body.items() if v is not None}
    step = {'n': step['step_id']}
    try:
        from progress_schema import Observation
        Observation.model_validate(body)
        checked = True
    except Exception:  # noqa: BLE001 - shown as unchecked, never hidden
        checked = False
    return {'body': body, 'schema_checked': checked, 'session': session['short'], 'step': step['n']}


def collect(aggregate, *, runs_root, root=ROOT):
    rows = aggregate['session_rows']
    names = korean_names(root)
    sessions = [session_entry(r, Path(runs_root) / r['session_id'] / 'record', names) for r in rows]
    sessions.sort(key=lambda s: s['started_at'] or '', reverse=True)
    kind = data_kind(aggregate.get('plans') or [])
    starts = sorted(s['started_at'] for s in sessions if s['started_at'])
    days = sorted({datetime.fromisoformat(t).astimezone(KST).strftime('%-m/%-d') for t in starts},
                  key=lambda d: tuple(int(x) for x in d.split('/')))
    span = '' if not days else days[0] if len(days) == 1 else f'{days[0]}~{days[-1]}'
    content = freeze_content_hash(root, aggregate.get('final_freeze_sha256'))
    if kind == 'main':
        items = plan_items(root, aggregate['plans'][0])
        source = (f"본 실행 항목 {items} 개 중 유효 {len(rows)} 세션 ({span}), 최종 동결 "
                  f"{(content or aggregate.get('final_freeze_sha256') or '')[:8]}…")
    else:
        source = f"시험 세션 {len(rows)} 개 ({span}) — 본 실행 결과 아님"
    representative = {r['scenario_id'] + ':' + r['role']: r['session_id'] for r in aggregate.get('representatives', [])}
    stall_rep = next((s for s in sessions for r in aggregate.get('representatives', [])
                      if r['session_id'] == s['id'] and s['first_stop'] and s['task'] == 'DEMO-CT'), None) or \
        next((s for s in sessions if s['first_stop'] and s['variant'] == 'stall'), None)
    scenarios = [{k: t.get(k) for k in ('scenario_id', 'task', 'variant', 'task_type', 'observe_runs', 'classes',
                                        'stalled_k_of_n', 'escalated_by', 'runs_with_stop', 'first_stop_steps',
                                        'first_stop_templates', 'false_positive_runs', 'detected_runs',
                                        'if_stopped_token_ratio_mean', 'credits_measured_sum', 'block')}
                 | {'detection_delay': (t.get('detection_delay') or {}).get('values'),
                    'name': names.get(t['scenario_id'])}
                 for t in aggregate['scenarios']]
    return {
        'ui_version': UI_VERSION, 'kind': kind, 'plans': aggregate.get('plans'), 'source': source,
        'scope': aggregate.get('scope'), 'freeze_record_sha256': aggregate.get('final_freeze_sha256'),
        'freeze_content_sha256': content, 'headline': headline(aggregate, rows),
        'judgement_ms': judgement_ms(rows, runs_root), 'types': aggregate['types'], 'scenarios': scenarios,
        'representatives': representative, 'sessions': sessions,
        'pairs': {task: pair_lines(root, task) for task in TASKS},
        'system': proxy_facts(root), 'example': example_observation(stall_rep, runs_root, root),
        'guide_session': stall_rep['id'] if stall_rep else None,
        'issue_defs': issue_definitions(root, [s['scenario'] for s in sessions] + [
            f'{t}-{v}-v1' for t in TASKS for v in ('normal', 'stall')] + ['DEMO-CT-N-v1']),
        'task_names': TASK_NAMES, 'planned': [{'id': i, 'name': n, 'plan': p} for i, n, p in PLANNED],
    }


STYLE = """
:root{--bg:#f4efe6;--card:#fff;--fg:#26231e;--muted:#7a7468;--line:#e3dccf;--side:#1f1d1a;--sidefg:#e9e4da;
--prog:#a9cdee;--base:#dde9f4;--stag:#f0a048;--stop:#5b2a12;--after:#d8d4cc;--unm:#f6f3ee;--block:#9b1c1c;
--orange:#d9741c;--navy:#1f3a68;--ok:#2f7d4a;--warn:#fbeee0}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
.app{display:flex;min-height:100vh}
aside{width:208px;flex:none;background:var(--side);color:var(--sidefg);display:flex;flex-direction:column;padding:16px 12px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:18px}.brand svg{width:40px;height:40px;border-radius:8px;flex:none}
.brand b{font-size:15px;letter-spacing:.2px}
nav button{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;background:none;border:0;color:var(--sidefg);
font:inherit;padding:8px 10px;border-radius:6px;cursor:pointer;margin:1px 0}
nav button.on{background:#3a3631}nav button:disabled{color:#837d72;cursor:default}
nav .sep{border-top:1px solid #3a3631;margin:10px 0}
.badge{font-size:11px;border:1px solid currentColor;border-radius:9px;padding:0 6px;white-space:nowrap}
.proj{margin-top:auto;font-size:12px;color:#a59f93}
main{flex:1;min-width:0;padding:16px 22px 28px;display:flex;flex-direction:column;gap:12px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px}
.top h1{font-size:19px;margin:0}.mode{background:#fff;border:1px solid var(--line);border-radius:14px;padding:3px 12px;font-size:13px}
.band{background:#7a1f1f;color:#fff;border-radius:8px;padding:10px 14px;font-size:16px;font-weight:700}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.kpi .v{font-size:26px;font-weight:700;line-height:1.2}.kpi .l{color:var(--muted);font-size:12px}.kpi .d{font-size:12px;margin-top:4px}
.kpi.pending{border:2px dashed var(--line);background:transparent}
.orange{color:var(--orange)}.navy{color:var(--navy)}.muted{color:var(--muted)}
.grid2{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:12px;align-items:start}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}tbody tr{cursor:pointer}tbody tr:hover{background:#faf6ef}
.scroll{max-height:330px;overflow:auto}
.pill{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;white-space:nowrap}
.p-stop{background:var(--stop);color:#fff}.p-go{background:#e7f1e9;color:var(--ok)}.p-block{background:var(--block);color:#fff}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.filters select{font:inherit;font-size:12px;padding:2px 4px}
.alert{border-left:4px solid var(--stop);background:#fbf4ee;border-radius:6px;padding:8px 10px;margin-bottom:8px;font-size:13px}
.alert b{display:block}.alert button,.linkbtn{background:none;border:0;color:var(--navy);padding:0;font:inherit;cursor:pointer;text-decoration:underline}
.alerts{max-height:440px;overflow:auto}
.foot{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:6px;margin-top:auto}
.tl{display:grid;gap:2px;margin:6px 0}.tl div{height:26px;border-radius:3px;font-size:10px;display:flex;align-items:center;justify-content:center;color:#3a352d;cursor:pointer}
.c-progress{background:var(--prog)}.c-baseline{background:var(--base)}.c-stagnant,.c-oscillating{background:var(--stag)}
.c-oscillating{background:repeating-linear-gradient(45deg,var(--stag),var(--stag) 4px,#c9782a 4px,#c9782a 8px)}
.c-unmeasured{background:var(--unm);border:1px dashed #b8b0a2}.c-stop{background:var(--stop)!important;color:#fff!important}
.c-after{background:var(--after)!important;color:#6d675d}.c-blocked{background:var(--block)!important;color:#fff!important}
.c-empty{background:transparent;border:1px solid var(--line)}.c-cur{outline:2px solid var(--navy);outline-offset:1px}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:14px;height:12px;border-radius:2px;vertical-align:-2px;margin-right:4px}
.replay{display:inline-block;background:var(--navy);color:#fff;border-radius:10px;padding:0 8px;font-size:12px}
.controls{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.controls button,.btn{font:inherit;font-size:13px;padding:3px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0}dt{color:var(--muted)}dd{margin:0}
.stopbox{background:#f4e9e2;border-left:4px solid var(--stop);border-radius:4px;padding:8px 10px;margin:6px 0}
.blockbox{background:#f8e3e3;border-left:4px solid var(--block);border-radius:4px;padding:8px 10px;margin:6px 0}
.induced{display:inline-block;background:var(--warn);color:#8a4b12;border:1px solid #e8c49b;border-radius:10px;padding:0 8px;font-size:12px}
code,pre{font-family:ui-monospace,Menlo,monospace;font-size:12px}pre{max-height:230px;background:#f7f3ec;border:1px solid var(--line);border-radius:8px;padding:8px 10px;overflow:auto;margin:6px 0}
.gray{color:#9a9488}.diffline{font-family:ui-monospace,Menlo,monospace;font-size:13px;padding:2px 6px;border-radius:4px;margin:2px 0}
.dl-plus{background:#e6f2e8}.dl-minus{background:#f6e3e3}
.guide{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:center;margin-bottom:12px}
.guide>*{min-width:0}.guide pre{max-width:100%;overflow-x:auto}
.detail{border-top:1px solid var(--line);margin-top:8px;padding-top:8px}.detail h4{margin:0 0 4px;font-size:13px}
.detail .basis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.detail .basis>div{background:#faf7f1;border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:0}
.chip{display:inline-block;border-radius:8px;padding:0 6px;margin:1px 2px;font-size:12px;font-family:ui-monospace,Menlo,monospace}
.chip-minus{background:#f6e3e3}.chip-plus{background:#e6f2e8}.chip-same{background:#efe9de}
.caution{color:var(--muted);font-size:12px;margin-top:6px}.none{color:#9a9488}
.c-live{background:repeating-linear-gradient(90deg,#fff,#fff 4px,#e9e2d4 4px,#e9e2d4 8px)!important;border:1px dashed var(--navy)}
.livebadge{display:inline-flex;align-items:center;gap:6px;background:#7a1f1f;color:#fff;border-radius:10px;padding:0 10px;font-size:12px}
.livebadge i{width:8px;height:8px;border-radius:50%;background:#ff8a80;display:inline-block}
.gnum{font-size:44px;font-weight:800;color:#cfc5b3;line-height:1}.gtitle{font-size:17px;font-weight:700;margin:4px 0}
.planned{border:2px dashed #c9bfae;border-radius:12px;padding:12px;color:var(--muted);background:#faf7f1}
.planned .tag{display:inline-block;background:#e9e2d4;color:#6d675d;border-radius:8px;padding:0 8px;font-size:12px;margin-bottom:6px}
button[disabled]{opacity:.55;cursor:not-allowed}
.flow{width:100%;height:auto}.flow text{font-size:13px;fill:#26231e}.flow .s{font-size:11px;fill:#7a7468}
.hide{display:none!important}
section.page{display:flex;flex-direction:column;gap:12px}
"""


SCRIPT = r"""
const D=JSON.parse(document.getElementById('demo-data').textContent);
const $=s=>document.querySelector(s),esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const compact=o=>JSON.stringify(o,null,1).replace(/\[\s+([^\[\]{}]*?)\s+\]/g,(m,a)=>'['+a.replace(/\s*\n\s*/g,' ')+']');
const pct=v=>v===null||v===undefined?'—':(100*v).toFixed(1)+'%';
const byId={};D.sessions.forEach(s=>byId[s.id]=s);
/* data source of the dashboard and session pages : the records in this file, or the query API (C-19-7, page built with --api) */
const FILE_SRC={api:false,headline:D.headline,judgement_ms:D.judgement_ms,sessions:D.sessions,byId:byId};let SRC=FILE_SRC,beforeOpen=null;
const VAR={normal:'정상판',stall:'교착판',natural:'비교군'};
function scName(s){return esc(s.task_name)+' · '+VAR[s.variant];}
function pill(s){if(s.mode==='block'&&s.blocked_step)return '<span class="pill p-block">차단 · step '+s.blocked_step+'</span>';
 if(s.first_stop)return '<span class="pill p-stop">STOP · step '+s.first_stop+'</span>';return '<span class="pill p-go">계속 진행</span>';}
function result(s){if(s.class==='success')return s.first_stop&&s.variant==='normal'?'성공 (오탐)':'성공';
 if(s.class==='stalled')return s.mode==='block'?'교착 (차단으로 끝)':'교착 ('+esc(s.termination)+')';
 if(s.class==='escalated')return '에스컬레이션'+(s.escalated_by_label?' ('+esc(s.escalated_by_label)+')':'');return '기타 ('+esc(s.termination)+')';}
/* ---------- navigation ---------- */
const PAGES=['dashboard','session','compare','stats','system','guide','live'];
function go(p,arg){if(!PAGES.includes(p))p='dashboard';PAGES.forEach(x=>{$('#pg-'+x).classList.toggle('hide',x!==p);const b=$('#nav-'+x);if(b)b.classList.toggle('on',x===p)});
 if(p==='session'&&arg)openSession(arg);if(location.hash!=='#'+p)history.replaceState(null,'','#'+p);window.scrollTo(0,0);}
document.querySelectorAll('nav button[data-page]').forEach(b=>b.onclick=()=>go(b.dataset.page));
document.querySelectorAll('nav button[data-planned]').forEach(b=>b.onclick=()=>{});
/* ---------- timeline ---------- */
function cellsOf(s){const n=Math.max(s.max_steps||s.steps,s.steps),out=[];
 for(let k=1;k<=n;k++){const r=s.step_rows.find(x=>x.n===k);let c='c-empty',t='';
  if(r){c='c-'+(r.state||'unmeasured');t='step '+k+' · '+(r.role||'')+' · '+(r.label||'-');
   if(s.mode!=='block'&&s.first_stop&&k>s.first_stop){c+=' c-after';}
   if(r.stop&&k===s.first_stop){c+=' c-stop';}
   if(r.blocked){c+=' c-blocked';t+=' · 403 차단';}}
  out.push({k,c,t,r});}return out;}
function timeline(s,host,cur,onpick){const cells=cellsOf(s);host.style.gridTemplateColumns='repeat('+cells.length+',1fr)';
 host.innerHTML=cells.map(x=>'<div class="'+x.c+(cur===x.k?' c-cur':'')+'" title="'+esc(x.t)+'" data-k="'+x.k+'">'+(x.r&&x.r.blocked?'403':(x.k===s.first_stop?'STOP':x.k))+'</div>').join('');
 if(onpick)host.querySelectorAll('div[data-k]').forEach(d=>d.onclick=()=>onpick(+d.dataset.k));}
function legend(s){const after=s&&s.if_stopped&&s.mode!=='block'?' (토큰 '+pct(s.if_stopped.ratio)+')':'';
 return '<div class="legend"><span><i class="c-progress"></i>진전</span><span><i class="c-baseline"></i>기준 (비교 전)</span><span><i class="c-stagnant"></i>제자리 (정체·되돌림)</span><span><i class="c-unmeasured"></i>측정 안 됨</span><span><i class="c-stop"></i>STOP</span><span><i class="c-after"></i>멈췄다면 안 썼을 구간'+after+'</span><span><i class="c-blocked"></i>403 차단</span></div>';}
/* ---------- dashboard ---------- */
function dashboard(){const H=SRC.headline,c=H.observe_classes;
 const fpTasks=Object.entries(H.false_positive_by_task).map(([t,v])=>esc(D.task_names[t]||t)+' '+v).join(' · ');
 const j=SRC.judgement_ms;
 $('#kpis').innerHTML=
 '<div class="card kpi"><div class="l">관측한 세션</div><div class="v">'+H.observe_sessions+'</div><div class="d">성공 '+(c.success||0)+' · 교착 '+(c.stalled||0)+' · 에스컬레이션 '+(c.escalated||0)+' · 기타 '+(c.other||0)+'</div><div class="d muted">차단 세션 '+H.block_sessions+' 따로</div></div>'+
 '<div class="card kpi"><div class="l">교착 판정 STOP (교착판)</div><div class="v orange">'+H.stall_detected+' <span style="font-size:15px">/ '+H.stall_reached+'</span></div><div class="d">교착에 닿은 교착판 관측 중 STOP</div><div class="d">정상판 오탐 <b>'+H.false_positive+'</b> / '+H.normal_success+' ('+fpTasks+'), 그중 차단이었다면 성공을 막았을 <b>'+H.blocked_before_success+'</b></div></div>'+
 '<div class="card kpi"><div class="l">멈췄다면 아꼈을 토큰</div><div class="v navy">'+pct(H.saving_mean)+'</div><div class="d">탐지된 교착판 관측 '+H.stall_detected+' 세션의 "첫 STOP 이후 토큰 / 전체" 평균</div></div>'+
 (j?'<div class="card kpi"><div class="l">판정 지연 p99 (규칙 판정)</div><div class="v">'+j.p99+' ms</div><div class="d">'+j.n+' step · p50 '+j.p50+' ms · 네트워크·LLM 제외 (S-5)</div></div>'
   :'<div class="card kpi pending"><div class="l">판정 지연 p99</div><div class="v muted">[측정 예정]</div><div class="d">기록에 측정값 없음</div></div>');
 const f={type:$('#f-type').value,variant:$('#f-var').value,mode:$('#f-mode').value};
 const rows=SRC.sessions.filter(s=>(!f.type||s.type===f.type)&&(!f.variant||s.variant===f.variant)&&(!f.mode||s.mode===f.mode));
 $('#recent').innerHTML=rows.map(s=>'<tr data-id="'+s.id+'"><td><code>'+s.short+'</code></td><td>'+scName(s)+' <span class="muted">'+s.type+'</span></td><td>'+s.steps+'</td><td>'+(s.tokens||0).toLocaleString()+'</td><td>'+pill(s)+'</td><td>'+result(s)+'</td></tr>').join('');
 $('#recent-n').textContent=rows.length+' 세션';
 document.querySelectorAll('#recent tr').forEach(r=>r.onclick=()=>go('session',r.dataset.id));
 /* stall-version STOPs first, then the normal-version false positives; by first STOP step inside each group */
 const stops=SRC.sessions.filter(s=>s.first_stop&&s.stop_text).map((s,k)=>[s,k])
  .sort((a,b)=>((a[0].variant==='normal')-(b[0].variant==='normal'))||(a[0].first_stop-b[0].first_stop)||(a[1]-b[1])).map(x=>x[0]);
 $('#alerts').innerHTML=stops.map(s=>'<div class="alert"><b>교착 의심 — '+esc(s.task_name)+' '+VAR[s.variant]+(s.class==='success'?' <span class="muted">(성공 세션 · 오탐)</span>':'')+'</b>step '+s.first_stop+' · '+esc(s.template)+' · '+(s.mode==='block'?'차단':'관측')+'<div>'+esc(s.stop_text)+'</div><button data-id="'+s.id+'">세션 보기</button></div>').join('');
 document.querySelectorAll('#alerts button').forEach(b=>b.onclick=()=>go('session',b.dataset.id));}
['#f-type','#f-var','#f-mode'].forEach(id=>$(id).onchange=dashboard);
/* ---------- session ---------- */
let S=null,cur=1,timer=null;
function facts(r){const o=[];if(r.report){const p=r.report;if(p.status)o.push(['처리 상태',p.status]);if(p.handoff)o.push(['다음 담당',p.handoff]);
  o.push(['채택 항목',p.adopted]);o.push(['열린 쟁점 수',p.issues]);if(p.spec!==null&&p.spec!==undefined)o.push(['SPEC 승인',p.spec?'승인':'미승인']);
  if(p.declared)o.push(['완료 선언','예']);if(p.deliverable)o.push(['결과물','보고함']);}else o.push(['최종 보고','없음']);
 if(r.claim!==null)o.push(['완료 주장',r.claim?'판정 통과':'판정 거절']);if(r.tests)o.push(['통과 테스트',r.tests[0]+'/'+r.tests[1]]);
 if(r.changed)o.push(['바뀐 파일 수',r.changed]);o.push(['도구 호출',r.tools+(r.tool_errors?' (오류 '+r.tool_errors+')':'')]);
 if(r.fail.length)o.push(['실패 사유',r.fail.join(', ')]);o.push(['step 토큰',r.tok.toLocaleString()]);return o;}
function chart(s){const W=1000,H=120,P=34,rs=s.step_rows,n=rs.length;if(!n)return '';const max=Math.max(1,...rs.map(r=>r.cum||0));
 const x=k=>P+(W-2*P)*(n<2?0:k/(n-1)),y=v=>H-22-(H-36)*v/max;let p='';rs.forEach((r,k)=>p+=(k?'L':'M')+x(k).toFixed(1)+' '+y(r.cum||0).toFixed(1));
 let g='<svg viewBox="0 0 '+W+' '+H+'" class="flow" role="img" aria-label="누적 토큰"><line x1="'+P+'" y1="'+(H-22)+'" x2="'+(W-P)+'" y2="'+(H-22)+'" stroke="#e3dccf"/><path d="'+p+'" fill="none" stroke="#1f3a68" stroke-width="2"/>';
 if(s.first_stop){const k=rs.findIndex(r=>r.n===s.first_stop);if(k>=0)g+='<line x1="'+x(k)+'" y1="8" x2="'+x(k)+'" y2="'+(H-22)+'" stroke="#5b2a12" stroke-dasharray="4 3"/><text class="s" x="'+(x(k)+4)+'" y="18">STOP</text>';}
 const k=rs.findIndex(r=>r.n===cur);if(k>=0)g+='<line x1="'+x(k)+'" y1="8" x2="'+x(k)+'" y2="'+(H-22)+'" stroke="#26231e"/>';
 g+='<text class="s" x="'+P+'" y="'+(H-6)+'">step 1</text><text class="s" x="'+(W-P-70)+'" y="'+(H-6)+'">step '+rs[n-1].n+'</text><text class="s" x="'+P+'" y="12">누적 토큰 '+max.toLocaleString()+'</text></svg>';return g;}
function sessionOptions(){$('#s-pick').innerHTML=SRC.sessions.map(s=>'<option value="'+s.id+'">'+s.short+' · '+esc(s.task_name)+' '+VAR[s.variant]+' · '+(s.mode==='block'?'차단':'관측')+'</option>').join('');
 $('#s-pick').onchange=e=>openSession(e.target.value);}
function openSession(id){S=SRC.byId[id]||SRC.sessions[0];cur=1;stop();$('#s-pick').value=S.id;if(beforeOpen&&beforeOpen(S))return;renderSession();}
function renderSession(){const s=S;if(!s)return;
 $('#s-alert').innerHTML=s.first_stop?'<div class="alert"><b>교착 의심 — '+esc(s.task_name)+' '+VAR[s.variant]+' · step '+s.first_stop+' ('+esc(s.template)+')</b>'+esc(s.stop_text)+'</div>':'<div class="card muted">이 세션에는 STOP 이 없다.</div>';
 $('#s-head').innerHTML='<b>'+esc(s.name||s.scenario)+'</b><div class="muted">'+esc(s.title)+' · 세션 '+esc(s.id)+' · '+(s.mode==='block'?'차단 (block)':'관측 (observe)')+' · 결과 '+result(s)+' · '+s.steps+' / '+(s.max_steps||'-')+' step · 토큰 '+(s.tokens||0).toLocaleString()+' · 크레딧 '+(s.credits??'—')+'</div>';
 timeline(s,$('#s-tl'),cur,k=>{cur=k;renderSession();});$('#s-legend').innerHTML=legend(s);
 $('#s-step').innerHTML=stepHtml(s,s.step_rows.find(x=>x.n===cur));$('#s-chart').innerHTML=chart(s);$('#s-pos').textContent='step '+cur+' / '+s.step_rows.length;}
function stepHtml(s,r){if(!r)return '';
 let h='<h3 style="margin:0">step '+r.n+' · '+esc(r.role)+' <span class="muted">판정 : '+esc(r.label||'-')+'</span></h3>';
 if(r.stop)h+='<div class="stopbox"><b>STOP ('+esc(r.stop.t)+')</b> '+esc(r.stop.text)+'</div>';
 if(r.blocked)h+='<div class="blockbox"><b>403 차단</b> STOP 뒤 이 step 의 요청을 프록시가 업스트림에 보내지 않고 돌려보냈다.</div>';
 if(s.mode!=='block'&&s.if_stopped&&r.n===s.first_stop)h+='<div class="card">여기서 멈췄다면 뒤의 '+s.if_stopped.tokens_after.toLocaleString()+' 토큰 ('+pct(s.if_stopped.ratio)+')을 쓰지 않았다.</div>';
 h+='<dl>'+facts(r).map(([a,b])=>'<dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd>').join('')+'<dt>누적 토큰</dt><dd>'+(r.cum||0).toLocaleString()+(r.cumc!==null&&r.cumc!==undefined?' · '+r.cumc+' 크레딧 (추정)':'')+'</dd></dl>';
 return h+detailPanel(s,r);}
/* ---------- step detail (DM-87) : replay.json values only; a value the record lacks is "관측값 없음", never 0 ---------- */
const NONE='<span class="none">관측값 없음</span>';
function chips(list,cls,s){return list.length?list.map(id=>{const d=(D.issue_defs[s.scenario]||{})[id];return '<span class="chip '+cls+'" title="'+esc(d||'')+'">'+esc(id)+'</span>'}).join(''):'<span class="none">없음</span>';}
function prevSame(s,r){const i=s.step_rows.findIndex(x=>x.n===r.n);for(let k=i-1;k>=0;k--){const p=s.step_rows[k];if(p.agent===r.agent)return p;}return null;}
function detailPanel(s,r){let h='<div class="detail"><h4>step 상세</h4>';
 const p=prevSame(s,r);
 h+='<div><b>미해결 쟁점</b> <span class="muted">— 같은 역할의 이전 step 대비</span><div>';
 if(!r.report)h+=NONE+' <span class="muted">(이 step 에 검증된 최종 보고가 없다)</span>';
 else if(!p)h+='<span class="muted">비교 기준 없음 — 이 역할의 첫 step</span> · 지금 목록 '+chips(r.report.issue_ids,'chip-same',s);
 else if(!p.report)h+='<span class="muted">비교 기준 step '+p.n+' 에 검증된 보고가 없음</span> · 지금 목록 '+chips(r.report.issue_ids,'chip-same',s);
 else{const a=p.report.issue_ids,b=r.report.issue_ids;
  h+='<span class="muted">step '+p.n+' → step '+r.n+'</span><dl><dt>빠짐</dt><dd>'+chips(a.filter(x=>!b.includes(x)),'chip-minus',s)+'</dd><dt>추가</dt><dd>'+chips(b.filter(x=>!a.includes(x)),'chip-plus',s)+'</dd><dt>지금 목록</dt><dd>'+chips(b,'chip-same',s)+'</dd></dl>';}
 h+='</div></div><div style="margin-top:6px"><b>파일 변화</b><div class="basis">';
 if(s.type==='T1')h+='<div><b>직전 step 대비</b><div>'+NONE+' <span class="muted">(파일 산출물이 없는 대화 과제)</span></div></div><div><b>판정 입력 (같은 역할 이전 step 대비)</b><div>'+NONE+'</div></div>';
 else{const first=s.step_rows.findIndex(x=>x.n===r.n)===0;
  h+='<div><b>직전 step 대비</b><div>'+(first?'<span class="muted">비교 기준 없음 (첫 step)</span>':(r.tests===null?NONE+' <span class="muted">(이 step 의 인수 판정 기록 없음)</span>':(r.paths.length?r.paths.map(x=>'<code>'+esc(x)+'</code>').join(', '):'바뀐 파일 없음')))+'</div></div>';
  h+='<div><b>판정 입력 (같은 역할 이전 step 대비)</b><div>'+NONE+' <span class="muted">(재생 기록에 이 기준의 파일 목록이 없다)</span></div></div>';}
 h+='</div></div><div class="caution">목록에서 빠졌다는 사실만으로 해결이 증명되지는 않습니다.<br>교착 판정은 자동 규칙의 결과입니다.</div></div>';
 return h;}
function stop(){if(timer){clearInterval(timer);timer=null;$('#s-play').textContent='▶ 자동 재생';}}
$('#s-prev').onclick=()=>{stop();cur=Math.max(1,cur-1);renderSession()};$('#s-next').onclick=()=>{stop();cur=Math.min(S.step_rows.length,cur+1);renderSession()};
$('#s-tostop').onclick=()=>{stop();if(S.first_stop){cur=S.first_stop;renderSession()}};
$('#s-play').onclick=()=>{if(timer){stop();return}if(cur>=S.step_rows.length)cur=0;$('#s-play').textContent='⏸ 멈춤';
 timer=setInterval(()=>{if(cur>=S.step_rows.length){stop();return}cur++;renderSession()},900);};
/* ---------- compare ---------- */
function compare(){const t=$('#c-task').value,P=D.pairs[t];
 const pick=(v,sel)=>{const list=D.sessions.filter(s=>s.task===t&&s.variant===v&&s.mode==='observe');
  sel.innerHTML=list.map(s=>'<option value="'+s.id+'">'+s.short+' · '+result(s)+'</option>').join('');
  const rep=D.representatives[t+'-'+v+'-v1:'+(v==='normal'?'정상판':'교착판')];if(rep&&list.some(s=>s.id===rep))sel.value=rep;return list.length;};
 if($('#c-task').dataset.last!==t){pick('normal',$('#c-a'));pick('stall',$('#c-b'));$('#c-task').dataset.last=t;}
 [['#c-a','#c-ta','#c-ia'],['#c-b','#c-tb','#c-ib']].forEach(([sel,tl,info])=>{const s=byId[$(sel).value];if(!s){$(tl).innerHTML='';$(info).textContent='세션 없음';return}
  timeline(s,$(tl),null,null);$(info).innerHTML=result(s)+' · '+s.steps+' step'+(s.first_stop?' · 첫 STOP step '+s.first_stop+' ('+esc(s.template)+')':' · STOP 없음')+(s.if_stopped&&s.variant==='stall'?' · 멈췄다면 아꼈을 토큰 '+pct(s.if_stopped.ratio):'');});
 $('#c-legend').innerHTML=legend(null);
 $('#c-diff').innerHTML=!P?'짝 없음':P.lines.map(l=>'<div class="diffline '+(l.line[0]==='+'?'dl-plus':'dl-minus')+'">'+esc(l.line[0]==='+'?'교착판 +':'정상판 −')+' '+esc(l.line.slice(1))+' <span class="muted">('+esc(l.where)+')</span></div>').join('')+
  '<div class="muted" style="font-size:12px;margin-top:4px">짝 차이 전체 (scenario_preflight --pair) : 파일 '+(P.files.length?P.files.map(esc).join(', '):'없음')+' · 시나리오 값 '+(P.scenario_keys.length?P.scenario_keys.map(esc).join(', '):'신원 값뿐')+(P.judge_same===false?' · 판정 함수 파일 다름':'')+'</div>';}
['#c-task','#c-a','#c-b'].forEach(id=>$(id).onchange=compare);
/* ---------- stats ---------- */
function stats(){const tm=t=>Object.entries(t||{}).map(([k,v])=>k+' '+v).join(' · ')||'—';
 $('#st-sc').innerHTML=D.scenarios.map(x=>{const fp=x.false_positive_runs,det=x.detected_runs;
  return '<tr><td>'+esc(x.name||x.scenario_id)+'</td><td>'+x.task_type+'</td><td>'+x.observe_runs+'</td><td>'+(x.variant==='stall'?esc(x.stalled_k_of_n):'—')+'</td><td>'+x.classes.success+' · '+x.classes.stalled+' · '+x.classes.escalated+' · '+x.classes.other+'</td>'+
  '<td>'+x.runs_with_stop+'</td><td>'+(x.first_stop_steps.length?x.first_stop_steps.join(', '):'—')+'</td><td>'+tm(x.first_stop_templates)+'</td>'+
  '<td>'+(fp?'<b>'+fp.success_with_stop+'</b>':'—')+'</td><td>'+(det?det.stalled_with_stop+' / '+det.stalled:'—')+'</td>'+
  '<td>'+(x.variant==='stall'&&det&&det.stalled_with_stop?pct(x.if_stopped_token_ratio_mean):(x.variant==='normal'&&x.if_stopped_token_ratio_mean!==null?'<span class="gray">'+pct(x.if_stopped_token_ratio_mean)+' = 오탐 비용</span>':'—'))+'</td><td>'+(x.credits_measured_sum??'—')+'</td></tr>';}).join('');
 $('#st-block').innerHTML=Object.entries(D.headline.block).map(([id,b])=>{const sc=D.scenarios.find(x=>x.scenario_id===id);
  return '<tr class="'+(b.judged?'':'gray')+'"><td>'+esc(sc&&sc.name||id)+'</td><td>'+b.runs+'</td><td>'+tm(b.classes)+'</td><td>'+b.with_stop+'</td><td>'+pct(b.token_saving)+'</td><td>'+pct(b.credit_saving)+'</td><td>'+(b.judged?pct(b.observe_estimate):'—')+'</td><td>'+(b.judged?'판정기 효과':'판정 없음 — 실행 간 차이')+'</td></tr>';}).join('');
 $('#st-types').innerHTML=D.types.map(t=>'<tr><td>'+esc(t.label)+'</td><td>'+t.observe_runs+'</td><td>'+t.normal_success+' / '+t.normal_runs+'</td><td>'+t.normal_with_stop+' ('+t.normal_false_positive+')</td><td>'+t.stall_stalled+' / '+t.stall_runs+'</td><td>'+t.stall_detected+'</td><td>'+t.stall_escalated+'</td><td>'+pct(t.if_stopped_token_ratio_mean_detected)+'</td></tr>').join('');}
/* ---------- system ---------- */
function system(){const y=D.system;
 $('#sys-facts').innerHTML='<dl><dt>판정 규칙</dt><dd>'+esc(y.criteria_version)+' ('+esc(y.progress_version)+', 원인 설명 '+esc(y.explanation_version)+') — 규칙 기반만</dd><dt>정체 연속 N</dt><dd>'+y.n+' step</dd><dt>통과 수 정체 K</dt><dd>'+y.k+' step (역할 3 × 2 바퀴)</dd><dt>T1 진전 신호</dt><dd>'+y.t1_metrics.map(esc).join(', ')+'</dd><dt>모델</dt><dd>'+esc(y.model)+' · 추론 강도 '+esc(y.reasoning_effort)+' (데모 조건, 원래 LLM 쪽)</dd><dt>업스트림</dt><dd>'+esc(y.upstream_host)+'</dd><dt>프록시</dt><dd>관측 127.0.0.1:'+y.port_observe+' · 차단 127.0.0.1:'+y.port_block+' (데모 한정)</dd></dl>';
 $('#sys-ex').textContent=D.example?compact(D.example.body):'';$('#sys-ex-note').textContent=D.example?('대표 세션 '+D.example.session+' step '+D.example.step+' 값으로 만든 예시 (llm_turns 는 자리값). 프록시의 관측 스키마 검사 : '+(D.example.schema_checked?'통과':'확인 안 됨')):'';}
/* ---------- guide ---------- */
function guide(){const s=byId[D.guide_session];if(!s)return;timeline(s,$('#g-tl'),null,null);$('#g-alert').innerHTML='<b>교착 의심 — '+esc(s.task_name)+' '+VAR[s.variant]+' · step '+s.first_stop+'</b>'+esc(s.stop_text);}
/* ---------- planned ---------- */
document.querySelectorAll('[data-planned]').forEach(b=>{b.addEventListener('click',()=>{const p=D.planned.find(x=>x.id===b.dataset.planned);const n=$('#planned-note');if(p&&n){n.textContent=p.name+' — 구현 전 : '+p.plan;n.classList.remove('hide');}});});
sessionOptions();dashboard();stats();system();guide();compare();openSession(D.guide_session||D.sessions[0].id);
const h=location.hash.slice(1);go(PAGES.includes(h)?h:'dashboard');
"""


def svg_inline(root):
    path = Path(root) / 'docs' / 'assets' / 'logo.svg'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<\?xml[^>]*\?>', '', text)
    return re.sub(r'<!--.*?-->', '', text, flags=re.S).strip()


def flow_svg(system):
    s = {k: html.escape(str(v)) for k, v in system.items() if not isinstance(v, list)}
    return f"""<svg class="flow" viewBox="0 0 960 300" role="img" aria-label="시스템 구조">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#7a7468"/></marker></defs>
<rect x="20" y="40" width="230" height="150" rx="12" fill="#fff" stroke="#e3dccf"/>
<text x="40" y="70" font-weight="700">내 에이전트들</text><text class="s" x="40" y="94">기획 · 개발 · 검토 (또는 접수·담당)</text>
<text class="s" x="40" y="114">+ 실행기 (테스트 실행, 결과 수집)</text><text class="s" x="40" y="160">base_url → 가드레일</text><text class="s" x="40" y="178">헤더 {s['session_header']}</text>
<rect x="360" y="30" width="250" height="170" rx="12" fill="#1f1d1a"/>
<text x="380" y="62" fill="#fff" font-weight="700" style="fill:#fff">가드레일 프록시</text>
<text class="s" x="380" y="86" style="fill:#d8d2c6">{s['chat_route']} 중계</text>
<text class="s" x="380" y="106" style="fill:#d8d2c6">{s['observation_route']} 관측 받기</text>
<text class="s" x="380" y="126" style="fill:#d8d2c6">판정 {s['criteria_version']} → 계속 / STOP</text>
<text class="s" x="380" y="146" style="fill:#d8d2c6">STOP 원인 문장 {s['explanation_version']}</text>
<text class="s" x="380" y="166" style="fill:#d8d2c6">차단 모드 : 다음 요청 {s['block_status']}</text>
<rect x="720" y="40" width="220" height="150" rx="12" fill="#fff" stroke="#e3dccf"/>
<text x="740" y="70" font-weight="700">원래 LLM</text><text class="s" x="740" y="94">{s['model']}</text><text class="s" x="740" y="114">{s['upstream_host']}</text>
<line x1="250" y1="90" x2="356" y2="90" stroke="#7a7468" marker-end="url(#ar)"/><text class="s" x="262" y="82">① 에이전트 차례 (요청)</text>
<line x1="610" y1="90" x2="716" y2="90" stroke="#7a7468" marker-end="url(#ar)"/><text class="s" x="622" y="82">그대로 전달</text>
<line x1="716" y1="140" x2="614" y2="140" stroke="#7a7468" marker-end="url(#ar)"/><text class="s" x="630" y="158">응답</text>
<line x1="356" y1="140" x2="254" y2="140" stroke="#7a7468" marker-end="url(#ar)"/><text class="s" x="262" y="158">응답 (또는 {s['block_status']})</text>
<line x1="135" y1="190" x2="135" y2="250" stroke="#7a7468"/><line x1="135" y1="250" x2="480" y2="250" stroke="#7a7468"/>
<line x1="480" y1="250" x2="480" y2="204" stroke="#7a7468" marker-end="url(#ar)"/>
<text class="s" x="150" y="228">② 테스트 실행 (실행기)</text><text class="s" x="150" y="270">③ 결과 보내기 : POST {s['observation_route']}</text>
<text class="s" x="496" y="230">④ 판정 : 계속 / STOP (+ 원인 문장)</text>
</svg>"""


LIVE_SCRIPT = r"""
/* ---------- live monitor (only in the page tools/demo_live.py serves; a file has none of this) ---------- */
const LIVE_POLL_MS=2500;let LV=null,lvCur=null,lvFollow=true,lvBusy=false;
const LVS={running:'진행 중',ended:'끝'};
async function lvGet(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
function lvTime(iso){return iso?new Date(iso).toLocaleTimeString('ko-KR',{hour12:false}):'—';}
function lvState(s){const l=s.live;if(l.status==='ended')return '끝 · '+result(s);
 const idle=l.idle_seconds>=600?' <span class="muted">('+Math.round(l.idle_seconds/60)+' 분 변화 없음)</span>':'';
 return '진행 중 · step '+(l.in_progress?l.in_progress.step:s.steps+1)+' 진행'+idle;}
function lvList(L){$('#lv-list').innerHTML=L.sessions.map(s=>'<tr data-id="'+s.id+'" class="'+(s.id===(LV&&LV.id)?'sel':'')+'"><td><code>'+s.short+'</code></td><td>'+esc(s.task_name)+' · '+VAR[s.variant]+'</td><td>'+(s.mode==='block'?'차단':'관측')+'</td><td>'+(s.live.lane?esc(s.live.lane+'/'+s.live.lanes):'—')+(s.account?' · '+esc(s.account):'')+'</td><td>'+s.steps+' / '+(s.max_steps||'-')+'</td><td>'+(s.first_stop?'<span class="pill p-stop">STOP · step '+s.first_stop+'</span>':(s.blocked_step?'<span class="pill p-block">403 · step '+s.blocked_step+'</span>':'—'))+'</td><td>'+lvState(s)+'</td></tr>').join('')||'<tr><td colspan="7" class="muted">세션 폴더가 없다</td></tr>';
 document.querySelectorAll('#lv-list tr[data-id]').forEach(r=>r.onclick=()=>{lvCur=null;lvFollow=true;lvOpen(r.dataset.id);});}
function lvRender(){const s=LV;if(!s){$('#lv-detail').classList.add('hide');return}$('#lv-detail').classList.remove('hide');
 $('#lv-alert').innerHTML=s.first_stop?'<div class="alert"><b>교착 의심 — '+esc(s.task_name)+' '+VAR[s.variant]+' · step '+s.first_stop+' ('+esc(s.template)+')'+(s.mode==='block'?' · 차단':'')+'</b>'+esc(s.stop_text)+'</div>':'<div class="card muted">아직 STOP 이 없다.</div>';
 $('#lv-head').innerHTML='<b>'+esc(s.name||s.scenario)+'</b><div class="muted">세션 '+esc(s.id)+' · '+(s.mode==='block'?'차단 (block)':'관측 (observe)')+' · '+lvState(s)+' · 토큰 '+(s.tokens||0).toLocaleString()+(s.credits!==null?' · '+s.credits+' 크레딧 (추정)':'')+' · 마지막 변화 '+lvTime(s.live.updated_at)+'</div>';
 timeline(s,$('#lv-tl'),lvFollow?null:lvCur,k=>{if(s.step_rows.some(x=>x.n===k)){lvCur=k;lvFollow=false;lvRender();}});
 const ip=s.live.in_progress;if(ip){const d=$('#lv-tl').querySelector('div[data-k="'+ip.step+'"]');if(d){d.classList.add('c-live');d.textContent=ip.blocked_requests?'403':'…';d.title='step '+ip.step+' 진행 중 · LLM 호출 '+ip.llm_calls+' 회';}}
 $('#lv-legend').innerHTML=legend(s)+(ip?'<div class="legend"><span><i class="c-live"></i>진행 중 step</span></div>':'');
 const r=lvFollow?s.step_rows[s.step_rows.length-1]:s.step_rows.find(x=>x.n===lvCur);
 $('#lv-step').innerHTML=r?stepHtml(s,r):'<span class="muted">아직 끝난 step 이 없다.</span>';
 $('#lv-follow').disabled=lvFollow;}
async function lvOpen(id){const X=await lvGet('/api/live/sessions/'+encodeURIComponent(id));LV=X.session;lvRender();}
async function lvTick(){if($('#pg-live').classList.contains('hide')||lvBusy)return;lvBusy=true;
 try{const L=await lvGet('/api/live/sessions');lvList(L);
  const want=(LV&&L.sessions.some(s=>s.id===LV.id))?LV.id:((L.sessions.find(s=>s.live.status==='running')||L.sessions[0]||{}).id);
  if(want)await lvOpen(want);$('#lv-updated').textContent='마지막 갱신 '+lvTime(L.now);$('#lv-err').classList.add('hide');}
 catch(e){$('#lv-err').textContent='실시간 서버 응답 없음 ('+e.message+'). 기록 재생(세션 메뉴)을 쓰세요.';$('#lv-err').classList.remove('hide');}
 finally{lvBusy=false;}}
$('#lv-off').classList.add('hide');$('#lv-on').classList.remove('hide');
$('#lv-follow').onclick=()=>{lvFollow=true;lvCur=null;lvRender();};
document.querySelectorAll('nav button[data-page]').forEach(b=>b.addEventListener('click',()=>setTimeout(lvTick,0)));
setInterval(lvTick,LIVE_POLL_MS);lvTick();
"""


# C-19-7 : the query API's rows -> the values the screen draws. Pure functions (no DOM) so a test can run them in node
# against fake API responses and compare with the records in the file (slim_step and session_entry above, same values).
API_MAP = r"""
const API_TIMEOUT_MS=8000;
const hasOwn=(o,k)=>k!==null&&k!==undefined&&Object.prototype.hasOwnProperty.call(o||{},k);
const filled=v=>v!==null&&v!==undefined&&!(typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===0)&&v!==''&&v!==false&&v!==0&&!(Array.isArray(v)&&v.length===0);
async function apiJson(fetchFn,u){const c=typeof AbortController!=='undefined'?new AbortController():null;const t=c?setTimeout(()=>c.abort(),API_TIMEOUT_MS):null;
 try{const r=await fetchFn(u,{cache:'no-store',credentials:'same-origin',signal:c?c.signal:undefined});if(!r.ok)throw new Error(u+' HTTP '+r.status);return await r.json();}
 finally{if(t)clearTimeout(t);}}
function apiStep(f,roles){const rp=filled(f.report)?f.report:null,claim=f.completion_claim,tools=f.tools||[],tk=f.tokens||{};
 return {n:f.step_id,agent:f.agent??null,role:f.role??null,state:f.state??null,label:f.state_label??null,
  stop:filled(f.stop)?{t:f.stop.template_id??null,text:f.stop.text??null}:null,blocked:!!f.blocked,status:f.step_status??null,
  fail:f.failure_reasons||[],tests:filled(f.tests)?[f.tests.passed,f.tests.total]:null,
  report:!rp?null:{status:(rp.status_label||rp.status)??null,handoff:hasOwn(roles,rp.handoff_to)?roles[rp.handoff_to]:(rp.handoff_to??null),
   adopted:rp.adopted_items??null,issues:(rp.open_issue_ids||[]).length,issue_ids:[...(rp.open_issue_ids||[])],
   spec:rp.spec_approved??null,declared:!!rp.completion_declared,deliverable:!!rp.deliverable_reported},
  claim:claim===null||claim===undefined?null:!!claim.accepted,tools:tools.length,tool_errors:tools.filter(x=>x.is_error).length,
  changed:(f.changed_paths||[]).length,paths:[...(f.changed_paths||[])],tok:(tk.prompt||0)+(tk.completion||0),
  cum:f.cumulative_tokens??null,cumc:f.cumulative_credits??null};}
function apiSession(r,taskNames){const roles=r.role_labels||{},eb=r.escalated_by??null;
 const ifs=r.if_stopped_token_ratio==null&&r.if_stopped_tokens_after==null?null:{ratio:r.if_stopped_token_ratio??null,tokens_after:r.if_stopped_tokens_after??null};
 return {id:r.session_id,short:String(r.session_id).slice(-32).slice(0,8),scenario:r.scenario_id,name:null,title:null,
  task:r.task,task_name:taskNames[r.task]||r.task,variant:r.variant,type:r.task_type,mode:r.mode,class:r.class,
  termination:r.termination_reason??null,escalated_by:eb,escalated_by_label:hasOwn(roles,eb)?roles[eb]:eb,
  steps:r.steps,max_steps:r.max_steps??null,tokens:r.tokens_total??null,
  credits:r.credits_measured!==null&&r.credits_measured!==undefined?r.credits_measured:(r.credits_estimated??null),
  first_stop:r.first_stop_step??null,template:r.first_stop_template??null,stop_text:r.first_stop_text??null,stop_steps:r.stop_steps||[],
  blocked_step:r.blocked_step??null,if_stopped:ifs,started_at:r.started_at??null,account:r.account_label??null,plan:r.plan_id??null,
  replay:false,step_rows:[],roles:roles,loaded:false};}
/* the counted sessions (validity valid), newest first, and the headline the dashboard cards read */
async function apiLoad(fetchFn,taskNames){const S=await apiJson(fetchFn,'/api/summary');
 if(!S||typeof S.headline!=='object'||S.headline===null)throw new Error('/api/summary : headline 없음');
 const L=await apiJson(fetchFn,'/api/sessions?validity=valid');
 if(!L||!Array.isArray(L.sessions)||!L.sessions.length||L.count!==L.sessions.length)throw new Error('/api/sessions : 세션 없음');
 const t=x=>{const v=Date.parse(x.started_at||'');return isNaN(v)?-Infinity:v;};
 const sessions=L.sessions.map(r=>apiSession(r,taskNames)).map((s,k)=>[s,k]).sort((a,b)=>(t(b[0])-t(a[0]))||(a[1]-b[1])).map(x=>x[0]);
 return {headline:S.headline,judgement_ms:S.judgement_ms??null,sessions};}
/* one session's name, title and steps (replay.json values as the database holds them) */
async function apiSessionSteps(fetchFn,s){const id=encodeURIComponent(s.id);
 const [one,st]=await Promise.all([apiJson(fetchFn,'/api/sessions/'+id),apiJson(fetchFn,'/api/sessions/'+id+'/steps')]);
 if(!one||!one.session||!st||!Array.isArray(st.steps))throw new Error('/api/sessions/'+s.id+' : 응답 모양 다름');
 const sc=one.session.scenario||{};s.name=sc.korean_name??null;s.title=sc.title??null;
 s.step_rows=st.steps.map(f=>apiStep(f,s.roles));s.replay=st.steps.length>0;s.loaded=true;return s;}
"""

# The page glue : only in the page built with --api, and only when that page is served over http(s). A file opened
# with a double click, a missing API or a wrong answer keeps (or puts back) the records in the file; nothing is faked.
API_SCRIPT = r"""
/* ---------- query API mode (C-19-7) ---------- */
const SRC_FILE_TEXT='데이터 : 파일에 담긴 기록';
const SRC_API_TEXT='데이터 : DB (조회 API) — 대시보드 카드 · 세션 표 · 세션 step. 비교 · 통계 · 시스템 구조 · 사용 가이드는 파일에 담긴 기록';
function setSrc(t){const e=$('#data-src');if(e)e.textContent=t;}
function apiRefresh(keep){sessionOptions();dashboard();openSession(SRC.byId[keep]?keep:(SRC.byId[D.guide_session]?D.guide_session:SRC.sessions[0].id));}
function apiFallback(e){const keep=S&&S.id;SRC=FILE_SRC;beforeOpen=null;setSrc(SRC_FILE_TEXT+' (조회 API 응답 없음 : '+String(e&&e.message||e)+')');apiRefresh(keep);}
function apiBeforeOpen(s){if(s.loaded)return false;
 $('#s-alert').innerHTML='';$('#s-head').innerHTML='<span class="muted">세션 '+esc(s.short)+' 의 step 을 조회 API 에서 읽는 중…</span>';
 $('#s-tl').innerHTML='';$('#s-step').innerHTML='';$('#s-chart').innerHTML='';
 apiSessionSteps(fetch.bind(window),s).then(()=>{if(S===s)renderSession();}).catch(apiFallback);return true;}
function apiUse(X){const keep=S&&S.id,byid={};X.sessions.forEach(s=>byid[s.id]=s);
 SRC={api:true,headline:X.headline,judgement_ms:X.judgement_ms,sessions:X.sessions,byId:byid};beforeOpen=apiBeforeOpen;setSrc(SRC_API_TEXT);apiRefresh(keep);}
if(/^https?:$/.test(location.protocol)){setSrc(SRC_FILE_TEXT+' (조회 API 확인 중)');apiLoad(fetch.bind(window),D.task_names).then(apiUse).catch(apiFallback);}
"""


def page(data, root=ROOT, live=False, api=False):
    trial = data['kind'] != 'main'
    planned_nav = ''.join(
        f'<button data-planned="{p["id"]}" disabled title="구현 전">{html.escape(p["name"])} <span class="badge">구현 전</span></button>'
        for p in data['planned'] if p['id'] in ('live', 'policy', 'integration'))
    planned_box = lambda pid, extra='': (
        f'<div class="planned" data-planned-box="{pid}"><span class="tag">구현 전</span><div>'
        f'{html.escape(next(p["plan"] for p in data["planned"] if p["id"] == pid))}</div>{extra}</div>')
    task_options = ''.join(f'<option value="{t}">{html.escape(TASK_NAMES[t])} ({t[5:]})</option>' for t in TASKS)
    sysd = data['system']
    base = f"http://127.0.0.1:{sysd['port_observe']}/v1"
    band = ('<div class="band">시험 세션 (시나리오당 1~2 회) — 본 실행 결과 아님</div>' if trial else '')
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    H = data['headline']
    limits = [
        f"판정은 규칙 기반 {html.escape(sysd['criteria_version'])} 뿐이다. 모델 기반 판정(Cross-encoder)은 없다.",
        f"오탐 {H['false_positive']} / 성공한 정상판 {H['normal_success']} — CT 정상판 E1 (승인 전 구간에 3 step 창이 걸림), "
        f"MR 정상판 E6 (T1 진전 신호가 칸 내용·출처 변화를 보지 않음, DM-75). 차단 모드였다면 성공을 막았을 세션 {H['blocked_before_success']}.",
        f"미탐 {len(H['missed'])} (CL 교착판 {', '.join(H['missed'])} : 판정 불가 step 이 정체 연속을 끊음).",
        f"T1(대화) 교착판 STOP {H['t1_stall_stop']} : CS 는 교착에 닿지 않았고 MR·LR 은 먼저 에스컬레이션했다. 잡은 것은 T2·T3 교착이다.",
        "데모 세션 기준 · 유도한 교착 · 시나리오당 관측 5 회 · 단일 모델. 데이터셋 지표가 아니다.",
    ]
    nexts = ['모델 기반 판정 (Cross-encoder) — 계획', '복구 개입 (STOP 뒤 되살리기) — 계획 (DM-8)', '경고 모드 — 계획',
             'v0.4 후보 : 판정 불가 step 건너뛰기 · 승인 대기 구간 · T1 칸 내용 변화 (데이터셋으로 평가)']
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-guardrail 데모</title><style>{STYLE}</style></head>
<body><div class="app">
<aside><div class="brand">{svg_inline(root)}<b>agent-guardrail</b></div>
<nav>
<button id="nav-dashboard" data-page="dashboard">대시보드</button>
<button id="nav-session" data-page="session">세션</button>
<button id="nav-compare" data-page="compare">비교</button>
<button id="nav-stats" data-page="stats">통계</button>
<button id="nav-system" data-page="system">시스템 구조</button>
<button id="nav-guide" data-page="guide">사용 가이드</button>
<button id="nav-live" data-page="live">실시간 모니터</button>
<div class="sep"></div>{planned_nav}
</nav>
<div class="proj">프로젝트 : 캡스톤 데모</div></aside>
<main>
<div class="top"><h1 id="title">agent-guardrail — 데모</h1><span class="mode">모드 : 관측 (observe) · 차단 (block) 세션은 따로 표시</span></div>
{band}
<div id="planned-note" class="planned hide"></div>

<section class="page" id="pg-dashboard">
<div class="cards" id="kpis"></div>
<div class="grid2">
<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><b>최근 세션</b><span class="muted" id="recent-n"></span></div>
<div class="filters"><select id="f-type"><option value="">유형 전체</option><option>T1</option><option>T2</option><option>T3</option></select>
<select id="f-var"><option value="">정상·교착 전체</option><option value="normal">정상판</option><option value="stall">교착판</option><option value="natural">비교군</option></select>
<select id="f-mode"><option value="">관측·차단 전체</option><option value="observe">관측</option><option value="block">차단</option></select></div>
<div class="scroll"><table><thead><tr><th>세션</th><th>시나리오</th><th>step</th><th>토큰</th><th>가드레일 판정</th><th>결과</th></tr></thead><tbody id="recent"></tbody></table></div></div>
<div><div class="card"><b>알림</b><div class="alerts" id="alerts" style="margin-top:6px"></div></div>
<div class="card" style="margin-top:10px"><b>관측 모드 안내</b><div class="muted" style="font-size:13px">관측 모드에서는 STOP 이 나도 세션을 끝까지 돌리고 "여기서 멈췄다면" 을 기록한다. 차단 모드(데모 한정)는 STOP 다음 요청을 {sysd['block_status']} 으로 돌려보낸다.</div></div></div>
</div>
<div class="card"><b>한계와 다음 단계</b><ul style="margin:6px 0 0 18px;padding:0">{''.join('<li>' + l + '</li>' for l in limits)}</ul>
<div class="muted" style="margin-top:6px">다음 단계 (계획, 화면에서 동작하지 않음) : {' · '.join(html.escape(n) for n in nexts)}</div></div>
</section>

<section class="page hide" id="pg-session">
<div class="controls"><select id="s-pick"></select><span class="replay">기록 재생</span></div>
<div id="s-alert"></div>
<div class="card"><div id="s-head"></div><div class="tl" id="s-tl"></div><div id="s-legend"></div>
<div class="controls" style="margin-top:6px"><button id="s-prev">◀ 이전</button><button id="s-play">▶ 자동 재생</button><button id="s-next">다음 ▶</button><button id="s-tostop">첫 STOP 으로</button><span class="muted" id="s-pos"></span>
<button disabled data-planned="report" title="구현 전">오탐 신고 <span class="badge">구현 전</span></button></div>
<div id="s-chart" style="margin-top:6px"></div></div>
<div class="card" id="s-step"></div>
<div class="muted" style="font-size:12px">판정 상태·STOP 원인 문장은 프록시 판정 기록, 사실 요약은 최종 보고의 구조화 필드·도구 호출 이름·테스트 결과다. 모델의 서술·추론은 넣지 않았다.</div>
</section>

<section class="page hide" id="pg-compare">
<div class="controls"><select id="c-task">{task_options}</select><span class="induced">유도한 교착 (DM-5)</span></div>
<div class="card"><b>정상판</b> <select id="c-a"></select> <span class="muted" id="c-ia"></span><div class="tl" id="c-ta"></div>
<b>교착판</b> <select id="c-b"></select> <span class="muted" id="c-ib"></span><div class="tl" id="c-tb"></div><div id="c-legend"></div></div>
<div class="card"><b>교착판에서 바뀐 한 줄</b><div id="c-diff" style="margin-top:6px"></div></div>
</section>

<section class="page hide" id="pg-stats">
<div class="card"><b>시나리오별 (관측)</b> <span class="muted">— 데모 세션 기준 · 분모는 유효 세션 수</span>
<table><thead><tr><th>시나리오</th><th>유형</th><th>n</th><th>n 회 중 교착 k 회</th><th>성공·교착·에스컬·기타</th><th>STOP 세션</th><th>첫 STOP step</th><th>템플릿</th><th>오탐 (성공+STOP)</th><th>탐지 (STOP / 교착)</th><th>멈췄다면 아꼈을 토큰</th><th>실측 크레딧</th></tr></thead><tbody id="st-sc"></tbody></table></div>
<div class="card"><b>유형별</b><table><thead><tr><th>유형</th><th>관측</th><th>정상판 성공</th><th>정상판 STOP (오탐)</th><th>교착판 교착</th><th>교착판 STOP</th><th>에스컬레이션</th><th>탐지된 교착판 아낄 토큰</th></tr></thead><tbody id="st-types"></tbody></table></div>
<div class="card"><b>차단 세션 (같은 시나리오 관측 평균 대비 실제 차이, DM-23)</b> <span class="muted">— STOP 이 난 시나리오만 판정기 효과</span>
<table><thead><tr><th>시나리오</th><th>차단 회수</th><th>끝</th><th>STOP</th><th>토큰 절감</th><th>크레딧 절감</th><th>같은 시나리오 관측 추정</th><th>구분</th></tr></thead><tbody id="st-block"></tbody></table></div>
</section>

<section class="page hide" id="pg-system">
<div class="card">{flow_svg(sysd)}</div>
<div class="grid2"><div class="card"><b>적용</b><div style="font-size:13px">에이전트 쪽은 <code>base_url</code> 과 세션 헤더(<code>{html.escape(sysd['session_header'])}</code>, 없으면 400)를 바꾸고, 판정 입력은 실행기가 <code>POST {html.escape(sysd['observation_route'])}</code> 로 보낸다.</div>
<pre>client = OpenAI(base_url="{base}", api_key=...,
                default_headers={{"{html.escape(sysd['session_header'])}": session_id}})</pre>
<b>관측 본문 예</b> <span class="muted" id="sys-ex-note" style="font-size:12px"></span><pre id="sys-ex"></pre></div>
<div class="card" id="sys-facts"></div></div>
</section>

<section class="page hide" id="pg-guide">
<div class="guide"><div><div class="gnum">1</div><div class="gtitle">프로젝트 만들기</div><div class="muted">가입하고 프로젝트를 만든다.</div></div>{planned_box('project', '<button disabled data-planned="project">프로젝트 만들기</button>')}</div>
<div class="guide"><div><div class="gnum">2</div><div class="gtitle">가드레일 키 발급</div><div class="muted">프로젝트별 키를 받는다.</div></div>{planned_box('key', '<button disabled data-planned="key">키 발급</button>')}</div>
<div class="guide"><div><div class="gnum">3</div><div class="gtitle">base_url 을 가드레일로 바꾸기</div><div class="muted">에이전트 코드는 그대로 두고, 모델 호출 주소와 세션 헤더만 바꾼다 (데모 관측 프록시).</div></div>
<div class="card"><pre>base_url = "{base}"
headers  = {{"{html.escape(sysd['session_header'])}": session_id}}</pre></div></div>
<div class="guide"><div><div class="gnum">4</div><div class="gtitle">차례가 끝날 때 결과 보내기</div><div class="muted">실행기가 step 마다 테스트 결과·파일 상태·보고 필드를 관측으로 보낸다.</div></div>
<div class="card"><code>POST {html.escape(sysd['observation_route'])}</code><pre id="g-ex"></pre></div></div>
<div class="guide"><div><div class="gnum">5</div><div class="gtitle">알림과 타임라인</div><div class="muted">STOP 이 나면 원인 문장이 알림으로 뜨고, 타임라인에 멈췄다면 안 썼을 구간이 보인다 (실제 세션).</div></div>
<div class="card"><div class="alert" id="g-alert"></div><div class="tl" id="g-tl"></div></div></div>
<div class="guide"><div><div class="gnum">6</div><div class="gtitle">모드와 오탐 신고</div><div class="muted">관측 ✓ · 차단 ✓ (데모 한정, 127.0.0.1:{sysd['port_block']}) · 경고 — 구현 전</div></div>
<div class="card"><div class="controls"><button class="btn" disabled>관측 ✓</button><button class="btn" disabled>차단 ✓ (데모)</button><button class="btn" disabled data-planned="warn">경고 <span class="badge">구현 전</span></button></div>
<div style="margin-top:8px">{planned_box('report', '<button disabled data-planned="report">오탐 신고</button>')}</div><div style="margin-top:8px">{planned_box('warn')}</div></div></div>
</section>

<section class="page hide" id="pg-live">
<div id="lv-off" class="card"><b>실시간 서버가 꺼져 있습니다. 기록 재생을 쓰세요.</b>
<div class="muted" style="margin-top:6px">이 화면은 파일로 열려 있어 진행 중 세션을 읽지 않는다 (요청 코드가 없다). 실시간 보기는 읽기 전용 로컬 서버로 연다 : <code>venv/bin/python -B tools/demo_live.py serve</code> → <code>http://127.0.0.1:8010/#live</code></div>
<div style="margin-top:8px"><button class="btn" onclick="go('session')">기록 재생 (세션)으로</button></div></div>
<div id="lv-on" class="hide" style="display:flex;flex-direction:column;gap:12px">
<div class="controls"><span class="livebadge"><i></i>실시간</span><span class="muted" id="lv-updated">마지막 갱신 —</span><span class="muted">· 2.5 초마다 기록 파일을 다시 읽는다</span></div>
<div id="lv-err" class="alert hide"></div>
<div class="card"><b>최근에 바뀐 세션</b> <span class="muted">— 세션 폴더의 기록 파일이 바뀐 순서</span>
<div class="scroll" style="max-height:220px"><table><thead><tr><th>세션</th><th>시나리오</th><th>모드</th><th>레인·계정</th><th>step</th><th>판정</th><th>상태</th></tr></thead><tbody id="lv-list"></tbody></table></div></div>
<div id="lv-detail" class="hide" style="display:flex;flex-direction:column;gap:12px">
<div id="lv-alert"></div>
<div class="card"><div id="lv-head"></div><div class="tl" id="lv-tl"></div><div id="lv-legend"></div>
<div class="controls" style="margin-top:6px"><button id="lv-follow" class="btn">최신 step 따라가기</button><span class="muted">칸을 누르면 그 step 을 본다</span></div></div>
<div class="card" id="lv-step"></div>
<div class="muted" style="font-size:12px">세션이 쓰는 기록 파일(실행기의 steps.json, 프록시 세션 로그)을 읽기만 한다. 구조화 값만 보이고 모델의 서술·추론은 넣지 않았다. 판정 상태·STOP 원인 문장은 프록시 판정 기록이다.</div>
</div></div>
</section>

<div class="foot" id="source">데이터 출처 : {html.escape(data['source'])} · {html.escape(data.get('scope') or '')} · 화면 {UI_VERSION}{' · 실시간 모니터 (127.0.0.1)' if live else ''} · <span id="data-src">데이터 : 파일에 담긴 기록</span></div>
</main></div>
<script type="application/json" id="demo-data">{payload}</script>
<script>{SCRIPT}
document.getElementById('g-ex').textContent=D.example?compact(D.example.body):'';</script>
{('<script>' + LIVE_SCRIPT + '</script>') if live else ''}
{('<script>' + API_MAP + API_SCRIPT + '</script>') if api else ''}
</body></html>
"""


def build(aggregate_path, output, runs_root=ROOT / 'runs' / 'demo', root=ROOT, api=False):
    data = collect(load(aggregate_path), runs_root=runs_root, root=root)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page(data, root, api=api), encoding='utf-8')
    missing = [s['id'] for s in data['sessions'] if not s['replay']]
    return {'output': str(output), 'kind': data['kind'], 'api': api, 'sessions': len(data['sessions']),
            'replay_missing': missing, 'bytes': output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    one = sub.add_parser('build')
    one.add_argument('--aggregate', type=Path, required=True)
    one.add_argument('--output', type=Path, required=True)
    one.add_argument('--runs-root', type=Path, default=ROOT / 'runs' / 'demo')
    one.add_argument('--api', action='store_true',
                     help='add the query API mode (C-19-7): served over http(s), the page reads /api/* of its own server')
    args = parser.parse_args()
    result = build(args.aggregate, args.output, args.runs_root, api=args.api)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['replay_missing'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
