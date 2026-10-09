"""C-19-6 : SQL over the demo tables — the post-load check queries and the read queries of the API.

The presentation numbers are counted again in SQL from the session rows (validity, mode, variant, class, first STOP,
if-stopped ratio, tokens). `check` compares them with the aggregate JSON (C-19-1 output) and with the numbers of
reports/c19/final-report.md section 4. Nothing here writes.
"""
import hashlib
import json
import math
from pathlib import Path
import statistics

# reports/c19/final-report.md section 4 (DM-85 ①). tests/test_service_demo_db.py checks these against that text.
REPORT_SECTION4 = {
    'false_positive': 4, 'normal_success': 24, 'blocked_before_success': 2,
    'stall_detected': 8, 'stall_reached': 9, 'saving_mean_pct': 60.8,
    'block_token_saving_pct': {'DEMO-CL-stall-v1': 66.7, 'DEMO-CT-stall-v1': 59.0},
}

VALID_OBSERVE = "validity = 'valid' AND mode = 'observe'"
SQL = {
    'sessions_by_validity': "SELECT validity, COUNT(*) AS n FROM sessions GROUP BY validity ORDER BY validity",
    'sessions_by_plan_kind': "SELECT plan_kind, COUNT(*) AS n FROM sessions GROUP BY plan_kind ORDER BY plan_kind",
    'excluded_by_code': ("SELECT exclusion_code, COUNT(*) AS n FROM sessions WHERE validity = 'excluded' "
                         "GROUP BY exclusion_code ORDER BY exclusion_code"),
    'valid_by_scenario': ("SELECT scenario_id, mode, COUNT(*) AS n FROM sessions WHERE validity = 'valid' "
                          "GROUP BY scenario_id, mode ORDER BY scenario_id, mode"),
    'observe_classes': (f"SELECT class, COUNT(*) AS n FROM sessions WHERE {VALID_OBSERVE} "
                        "GROUP BY class ORDER BY class"),
    'block_sessions': "SELECT COUNT(*) FROM sessions WHERE validity = 'valid' AND mode = 'block'",
    'normal_runs': f"SELECT COUNT(*) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'normal'",
    'normal_success': f"SELECT COUNT(*) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'normal' AND class = 'success'",
    # A STOP in a successful normal-variant session (S-1) = false positive.
    'false_positive': ("SELECT session_id, task, first_stop_step, first_stop_template, steps FROM sessions "
                       f"WHERE {VALID_OBSERVE} AND variant = 'normal' AND class = 'success' "
                       "AND first_stop_step IS NOT NULL ORDER BY session_id"),
    'stall_runs': f"SELECT COUNT(*) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'stall'",
    'stall_escalated': f"SELECT COUNT(*) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'stall' AND class = 'escalated'",
    # Stall-variant sessions that reached a stall (not finished), with or without a STOP.
    'stall_reached': ("SELECT session_id, task, task_type, first_stop_step, if_stopped_token_ratio FROM sessions "
                      f"WHERE {VALID_OBSERVE} AND variant = 'stall' AND class = 'stalled' ORDER BY session_id"),
    't1_stall_stop': (f"SELECT COUNT(*) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'stall' "
                      "AND task_type = 'T1' AND first_stop_step IS NOT NULL"),
    'saving_mean': (f"SELECT AVG(if_stopped_token_ratio) FROM sessions WHERE {VALID_OBSERVE} AND variant = 'stall' "
                    "AND class = 'stalled' AND first_stop_step IS NOT NULL"),
    # Block sessions against the mean of the same scenario's valid observe sessions (DM-23).
    'block': ("SELECT b.scenario_id, COUNT(*) AS runs, "
              "SUM(CASE WHEN b.first_stop_step IS NOT NULL THEN 1 ELSE 0 END) AS with_stop, "
              "AVG(b.tokens_total) AS block_mean_tokens, "
              "(SELECT AVG(o.tokens_total) FROM sessions o WHERE o.validity = 'valid' AND o.mode = 'observe' "
              "AND o.scenario_id = b.scenario_id) AS observe_mean_tokens "
              "FROM sessions b WHERE b.validity = 'valid' AND b.mode = 'block' "
              "GROUP BY b.scenario_id ORDER BY b.scenario_id"),
    'block_classes': ("SELECT scenario_id, termination_reason, COUNT(*) AS n FROM sessions "
                      "WHERE validity = 'valid' AND mode = 'block' GROUP BY scenario_id, termination_reason "
                      "ORDER BY scenario_id, termination_reason"),
    'credits_measured_total': "SELECT SUM(credits_measured) FROM sessions WHERE validity = 'valid'",
    'judgement_ns': ("SELECT st.judgement_ns FROM steps st JOIN sessions s ON s.session_id = st.session_id "
                     "WHERE s.validity = 'valid' AND st.judgement_ns IS NOT NULL ORDER BY st.judgement_ns"),
}


def short(session_id):
    return session_id[-32:][:8]


def pct(value):
    return None if value is None else round(value * 100, 1)


def judgement_ms(store):
    values = [r['judgement_ns'] for r in store.query(SQL['judgement_ns'])]
    if not values:
        return None
    return {'n': len(values), 'p50': round(statistics.median(values) / 1e6, 2),
            'p99': round(values[math.ceil(0.99 * len(values)) - 1] / 1e6, 2)}


def headline(store):
    """The presentation numbers counted in SQL (same keys as the C-19-3 screen's headline, so the screen can switch
    from the aggregate file to this API)."""
    false_positive = store.query(SQL['false_positive'])
    before_success = [r for r in false_positive if r['first_stop_step'] < r['steps']]
    reached = store.query(SQL['stall_reached'])
    detected = [r for r in reached if r['first_stop_step'] is not None]
    by_type = {}
    for r in detected:
        by_type.setdefault(r['task_type'], []).append(r['if_stopped_token_ratio'])
    classes = {}
    for r in store.query(SQL['block_classes']):
        classes.setdefault(r['scenario_id'], {})[r['termination_reason']] = r['n']
    block = {}
    for r in store.query(SQL['block']):
        saving = None if not r['observe_mean_tokens'] else 1 - r['block_mean_tokens'] / r['observe_mean_tokens']
        block[r['scenario_id']] = {'runs': r['runs'], 'classes': classes.get(r['scenario_id'], {}),
                                   'with_stop': r['with_stop'], 'judged': r['with_stop'] > 0,
                                   'token_saving': None if saving is None else round(saving, 4)}
    tasks = sorted({r['task'] for r in reached})
    saving_mean = store.scalar(SQL['saving_mean'])
    credits = store.scalar(SQL['credits_measured_total'])
    return {
        'observe_sessions': sum(r['n'] for r in store.query(SQL['observe_classes'])),
        'observe_classes': {r['class']: r['n'] for r in store.query(SQL['observe_classes'])},
        'block_sessions': store.scalar(SQL['block_sessions']),
        'normal_runs': store.scalar(SQL['normal_runs']), 'normal_success': store.scalar(SQL['normal_success']),
        'false_positive': len(false_positive),
        'false_positive_by_task': {t: sum(1 for r in false_positive if r['task'] == t)
                                   for t in sorted({r['task'] for r in false_positive})},
        'blocked_before_success': len(before_success),
        'blocked_before_success_sessions': [[short(r['session_id']), r['first_stop_step'], r['steps']]
                                            for r in before_success],
        'stall_runs': store.scalar(SQL['stall_runs']), 'stall_reached': len(reached), 'stall_detected': len(detected),
        'stall_detected_by_task': {t: [sum(1 for r in detected if r['task'] == t),
                                       sum(1 for r in reached if r['task'] == t)] for t in tasks},
        'missed': [short(r['session_id']) for r in reached if r['first_stop_step'] is None],
        'stall_escalated': store.scalar(SQL['stall_escalated']), 't1_stall_stop': store.scalar(SQL['t1_stall_stop']),
        'saving_mean': None if saving_mean is None else round(saving_mean, 5),
        'saving_by_type': {t: round(sum(v) / len(v), 5) for t, v in sorted(by_type.items())},
        'block': block,
        'credits_measured_total': None if credits is None else round(credits, 5),
    }


def presentation(h):
    """final-report section 4 lines, each with its denominator and definition (DM-85 ①)."""
    judged = {k: v for k, v in h['block'].items() if v['judged']}
    return [
        {'label': '정상판 오탐', 'value': h['false_positive'], 'denominator': h['normal_success'],
         'definition': '성공한 정상판 관측 세션 중 STOP 이 난 세션'},
        {'label': '그중 차단 모드였다면 성공을 막았을 세션', 'value': h['blocked_before_success'],
         'denominator': h['false_positive'], 'definition': '오탐 중 첫 STOP step 이 성공 step 보다 앞선 세션'},
        {'label': '교착판 탐지', 'value': h['stall_detected'], 'denominator': h['stall_reached'],
         'definition': '교착에 닿은(미완료) 교착판 관측 세션 중 STOP 이 난 세션'},
        {'label': '평균 절감률 (%)', 'value': pct(h['saving_mean']), 'denominator': h['stall_detected'],
         'definition': '탐지된 교착판 관측 세션의 "첫 STOP 이후 토큰 / 세션 전체 토큰" 평균'},
        {'label': '차단 실측 절감 (%)', 'value': {k: pct(v['token_saving']) for k, v in judged.items()},
         'denominator': {k: v['runs'] for k, v in judged.items()},
         'definition': 'STOP 이 난 차단 세션의 평균 토큰을 같은 시나리오 관측 평균과 비교 (DM-23)'},
    ]


def check(store, aggregate):
    """Counts and presentation numbers compared with aggregate JSON and final-report section 4."""
    if _unified_schema(store):
        return _check_unified(store, aggregate)
    h = headline(store)
    validity = {r['validity']: r['n'] for r in store.query(SQL['sessions_by_validity'])}
    by_code = {r['exclusion_code']: r['n'] for r in store.query(SQL['excluded_by_code'])}
    by_scenario = {}
    for r in store.query(SQL['valid_by_scenario']):
        by_scenario.setdefault(r['scenario_id'], {})[r['mode']] = r['n']
    agg_head = aggregate['headline']
    agg_scenarios = {}
    for t in aggregate['scenarios']:
        agg_scenarios[t['scenario_id']] = {'observe': t['observe_runs']} | (
            {'block': t['block']['runs']} if t.get('block') else {})
    agg_block = {t['scenario_id']: t['block']['token_saving_vs_observe'] for t in aggregate['scenarios']
                 if t.get('block') and h['block'].get(t['scenario_id'], {}).get('judged')}
    sql_block = {k: v['token_saving'] for k, v in h['block'].items() if v['judged']}
    comparisons = [
        ('valid sessions = aggregate sessions', validity.get('valid'), aggregate['sessions']),
        ('excluded by code = aggregate exclusion_list.by_code', by_code, aggregate['exclusion_list']['by_code']),
        ('valid by scenario and mode = aggregate scenario tables', by_scenario, agg_scenarios),
        ('normal runs', h['normal_runs'], agg_head['normal_runs']),
        ('false positives (aggregate)', h['false_positive'], agg_head['normal_false_positive_runs']),
        ('stall runs', h['stall_runs'], agg_head['stall_runs']),
        ('stall reached (aggregate)', h['stall_reached'], agg_head['stall_runs_stalled']),
        ('stall detected (aggregate)', h['stall_detected'], agg_head['stall_runs_detected']),
        ('stall escalated', h['stall_escalated'], agg_head['stall_runs_escalated']),
        ('saving mean (aggregate)', h['saving_mean'], agg_head['if_stopped_token_ratio_mean_detected']),
        ('block token saving (aggregate, judged scenarios)', sql_block, agg_block),
        ('credits measured total', h['credits_measured_total'], agg_head['credits_measured_total']),
        ('report 4: false positives', h['false_positive'], REPORT_SECTION4['false_positive']),
        ('report 4: successful normal sessions', h['normal_success'], REPORT_SECTION4['normal_success']),
        ('report 4: blocked before success', h['blocked_before_success'], REPORT_SECTION4['blocked_before_success']),
        ('report 4: stall detected', h['stall_detected'], REPORT_SECTION4['stall_detected']),
        ('report 4: stall reached', h['stall_reached'], REPORT_SECTION4['stall_reached']),
        ('report 4: saving mean %', pct(h['saving_mean']), REPORT_SECTION4['saving_mean_pct']),
        ('report 4: block token saving %', {k: pct(v) for k, v in sql_block.items()},
         REPORT_SECTION4['block_token_saving_pct']),
    ]
    results = [{'check': name, 'sql': got, 'expected': want, 'same': got == want} for name, got, want in comparisons]
    return {
        'ok': all(r['same'] for r in results),
        'sessions_by_validity': validity,
        'sessions_by_plan_kind': {r['plan_kind']: r['n'] for r in store.query(SQL['sessions_by_plan_kind'])},
        'excluded_by_code': by_code, 'valid_by_scenario': by_scenario, 'headline': h,
        'presentation': presentation(h), 'judgement_ms': judgement_ms(store), 'comparisons': results,
    }


# -- API reads ---------------------------------------------------------------------------------------------------
SESSION_FILTERS = ('scenario_id', 'task', 'task_type', 'variant', 'mode', 'validity', 'plan_id', 'plan_kind', 'class')
ROOT = Path(__file__).resolve().parents[1]


def _json_obj(value):
    """psycopg JSONB(dict/list)와 문자열 JSON을 같은 방식으로 다룬다."""
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


def _unified_schema(store):
    """새 storage 스키마인지 한 번만 확인한다. SQLite 오프라인 테스트는 기존 service 스키마를 그대로 쓴다."""
    cached = getattr(store, '_guardrail_unified_schema', None)
    if cached is not None:
        return cached
    if store.dialect != 'postgres':
        store._guardrail_unified_schema = False
        return False
    rows = store.query("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = current_schema() AND table_name = 'sessions'")
    columns = {r['column_name'] for r in rows}
    result = {'id', 'guardrail_mode', 'session_data', 'source'}.issubset(columns)
    store._guardrail_unified_schema = result
    return result


def _plan_kind(plan_id):
    if not plan_id:
        return 'none'
    if plan_id.startswith('demo-main-'):
        return 'main'
    if plan_id.startswith('demo-trial-'):
        return 'trial'
    return 'other'


def _task_of(scenario_id):
    for task in ('DEMO-CT-N', 'DEMO-CL', 'DEMO-CT', 'DEMO-CS', 'DEMO-MR', 'DEMO-LR'):
        if scenario_id.startswith(task + '-'):
            return task
    return scenario_id


def _variant_of(scenario_id):
    if not scenario_id.startswith('DEMO-'):
        return 'dataset'
    if '-normal-' in scenario_id:
        return 'normal'
    if '-stall-' in scenario_id:
        return 'stall'
    return 'natural'




def _task_type_map():
    from service import load_demo
    return {r['scenario_id']: r['task_type'] for r in load_demo.scenario_rows(load_demo.ROOT, {})}


def _credits_value(value, *, measured=False):
    value = _json_obj(value)
    if not isinstance(value, dict):
        return None
    if measured and value.get('status') != 'measured':
        return None
    return value.get('value')


def _reasoning_effort_value(value):
    """Legacy API exposed only the requested effort string, not the evidence object."""
    if isinstance(value, dict):
        return value.get('requested')
    return value


def _unified_rows(store):
    """통합 storage 세션을 기존 service API가 사용하던 세션 행 모양으로 변환한다."""
    rows = store.query(
        "SELECT s.*, sc.scenario_key, sc.name AS scenario_title, sc.task_kind, sc.config AS scenario_config "
        "FROM sessions s JOIN scenarios sc ON sc.id = s.scenario_id "
        "WHERE s.source = 'demo-record' ORDER BY s.id"
    )
    task_types = _task_type_map()
    result = []
    for r in rows:
        data = _json_obj(r.get('session_data'))
        aggregate = _json_obj(data.get('aggregate'))
        batch = _json_obj(data.get('batch'))
        tokens = _json_obj(data.get('tokens'))
        execution = _json_obj(r.get('execution_config'))
        if_stopped = _json_obj(data.get('if_stopped'))
        replay_steps = data.get('replay_steps') or []
        scenario_id = r['scenario_key']
        first_stop = next((x.get('stop') or {} for x in replay_steps if x.get('stop')), {})
        stop_steps = aggregate.get('stop_steps')
        if stop_steps is None:
            stop_steps = [x.get('step_id') for x in replay_steps if x.get('stop')]
        role_labels = _json_obj(data.get('role_labels'))
        if not isinstance(role_labels, dict) or not role_labels:
            role_labels = {}
            for step in replay_steps:
                if step.get('agent') and step.get('role'):
                    role_labels.setdefault(step['agent'], step['role'])
        prompt = tokens.get('prompt')
        completion = tokens.get('completion')
        result.append({
            'session_id': r['id'], 'scenario_id': scenario_id,
            'task': aggregate.get('task') or _task_of(scenario_id),
            'task_type': aggregate.get('task_type') or task_types.get(scenario_id) or r.get('task_kind'),
            'variant': aggregate.get('variant') or _variant_of(scenario_id),
            'mode': r.get('guardrail_mode'), 'plan_id': batch.get('plan_id'),
            'plan_kind': _plan_kind(batch.get('plan_id')), 'batch_item': batch.get('item'),
            'lane': batch.get('lane'), 'repeat_index': batch.get('repeat'), 'rerun_of': r.get('rerun_of'),
            'account_label': data.get('account_label'), 'account_corrected': data.get('account_corrected'),
            'git_commit': execution.get('git_commit'), 'git_dirty': execution.get('git_dirty'),
            'condition_group': data.get('condition_group'), 'final_freeze_sha256': batch.get('final_freeze_sha256'),
            'model': r.get('model'),
            'reasoning_effort': _reasoning_effort_value(execution.get('reasoning_effort')),
            'termination_reason': r.get('termination_reason'), 'class': aggregate.get('class'),
            'escalated_by': aggregate.get('escalated_by') if aggregate.get('escalated_by') is not None else data.get('escalated_by'),
            'role_labels': role_labels,
            'steps': aggregate.get('steps', r.get('steps_reached')), 'max_steps': execution.get('max_steps'),
            'tokens_prompt': prompt, 'tokens_cached_prompt': tokens.get('cached_prompt'),
            'tokens_completion': completion, 'tokens_reasoning': tokens.get('reasoning'),
            'tokens_total': r.get('total_tokens') if r.get('total_tokens') is not None else (
                None if prompt is None or completion is None else prompt + completion),
            'usage_missing_turns': tokens.get('usage_missing_turns'),
            'credits_measured': _credits_value(data.get('credits_measured'), measured=True),
            'credits_estimated': _credits_value(data.get('credits_estimated')),
            'first_stop_step': r.get('first_stop_step'),
            'first_stop_template': aggregate.get('first_stop_template') or first_stop.get('template_id'),
            'first_stop_text': aggregate.get('first_stop_text') or first_stop.get('text'),
            'stop_steps': stop_steps or [], 'blocked_step': data.get('blocked_step'),
            'if_stopped_token_ratio': if_stopped.get('token_ratio'),
            'if_stopped_tokens_after': if_stopped.get('tokens_after'),
            'if_stopped_credits_after': if_stopped.get('credits_after'),
            'stall_start': aggregate.get('stall_start'), 'detection_delay': aggregate.get('detection_delay'),
            'validity': r.get('validity'), 'exclusion_code': r.get('exclusion_code'),
            'replaced_by': r.get('replaced_by'), 'counted': bool(data.get('counted')),
            'started_at': r.get('started_at'), 'ended_at': r.get('ended_at'),
            # 내부 변환용. API로 내보낼 때 제거한다.
            '_replay_steps': replay_steps, '_scenario_title': r.get('scenario_title'),
        })
    return result


def _public_session(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def _headline_from_rows(rows):
    valid_observe = [r for r in rows if r['validity'] == 'valid' and r['mode'] == 'observe']
    false_positive = [r for r in valid_observe if r['variant'] == 'normal' and r['class'] == 'success'
                      and r['first_stop_step'] is not None]
    before_success = [r for r in false_positive if r['steps'] is not None and r['first_stop_step'] < r['steps']]
    reached = [r for r in valid_observe if r['variant'] == 'stall' and r['class'] == 'stalled']
    detected = [r for r in reached if r['first_stop_step'] is not None]
    by_type = {}
    for r in detected:
        if r['if_stopped_token_ratio'] is not None:
            by_type.setdefault(r['task_type'], []).append(r['if_stopped_token_ratio'])
    valid_block = [r for r in rows if r['validity'] == 'valid' and r['mode'] == 'block']
    block = {}
    for scenario_id in sorted({r['scenario_id'] for r in valid_block}):
        bs = [r for r in valid_block if r['scenario_id'] == scenario_id]
        os = [r for r in rows if r['validity'] == 'valid' and r['mode'] == 'observe'
              and r['scenario_id'] == scenario_id and r['tokens_total'] is not None]
        bt = [r['tokens_total'] for r in bs if r['tokens_total'] is not None]
        block_mean = sum(bt) / len(bt) if bt else None
        observe_mean = sum(r['tokens_total'] for r in os) / len(os) if os else None
        saving = None if block_mean is None or not observe_mean else 1 - block_mean / observe_mean
        classes = {}
        for r in bs:
            classes[r['termination_reason']] = classes.get(r['termination_reason'], 0) + 1
        with_stop = sum(1 for r in bs if r['first_stop_step'] is not None)
        block[scenario_id] = {'runs': len(bs), 'classes': classes, 'with_stop': with_stop,
                              'judged': with_stop > 0,
                              'token_saving': None if saving is None else round(saving, 4)}
    tasks = sorted({r['task'] for r in reached})
    saving_values = [r['if_stopped_token_ratio'] for r in detected if r['if_stopped_token_ratio'] is not None]
    credits = [r['credits_measured'] for r in rows if r['validity'] == 'valid' and r['credits_measured'] is not None]
    classes = {}
    for r in valid_observe:
        classes[r['class']] = classes.get(r['class'], 0) + 1
    return {
        'observe_sessions': len(valid_observe), 'observe_classes': classes, 'block_sessions': len(valid_block),
        'normal_runs': sum(1 for r in valid_observe if r['variant'] == 'normal'),
        'normal_success': sum(1 for r in valid_observe if r['variant'] == 'normal' and r['class'] == 'success'),
        'false_positive': len(false_positive),
        'false_positive_by_task': {t: sum(1 for r in false_positive if r['task'] == t)
                                   for t in sorted({r['task'] for r in false_positive})},
        'blocked_before_success': len(before_success),
        'blocked_before_success_sessions': [[short(r['session_id']), r['first_stop_step'], r['steps']]
                                            for r in before_success],
        'stall_runs': sum(1 for r in valid_observe if r['variant'] == 'stall'),
        'stall_reached': len(reached), 'stall_detected': len(detected),
        'stall_detected_by_task': {t: [sum(1 for r in detected if r['task'] == t),
                                       sum(1 for r in reached if r['task'] == t)] for t in tasks},
        'missed': [short(r['session_id']) for r in reached if r['first_stop_step'] is None],
        'stall_escalated': sum(1 for r in valid_observe if r['variant'] == 'stall' and r['class'] == 'escalated'),
        't1_stall_stop': sum(1 for r in valid_observe if r['variant'] == 'stall' and r['task_type'] == 'T1'
                             and r['first_stop_step'] is not None),
        'saving_mean': None if not saving_values else round(sum(saving_values) / len(saving_values), 5),
        'saving_by_type': {t: round(sum(v) / len(v), 5) for t, v in sorted(by_type.items())},
        'block': block, 'credits_measured_total': None if not credits else round(sum(credits), 5),
    }


def _unified_judgement_ms(store):
    values = [r['judgement_ns'] for r in store.query(
        "SELECT j.judgement_ns FROM judgements j JOIN sessions s ON s.id = j.session_id "
        "WHERE s.source = 'demo-record' AND s.validity = 'valid' AND j.judgement_ns IS NOT NULL "
        "ORDER BY j.judgement_ns")]
    if not values:
        return None
    return {'n': len(values), 'p50': round(statistics.median(values) / 1e6, 2),
            'p99': round(values[math.ceil(0.99 * len(values)) - 1] / 1e6, 2)}


def _check_unified(store, aggregate):
    """Same verification contract as ``check`` but counted from unified Storage rows."""
    rows = _unified_rows(store)
    h = _headline_from_rows(rows)

    validity = {}
    by_code = {}
    by_plan_kind = {}
    by_scenario = {}
    for row in rows:
        validity[row['validity']] = validity.get(row['validity'], 0) + 1
        by_plan_kind[row['plan_kind']] = by_plan_kind.get(row['plan_kind'], 0) + 1
        if row['validity'] == 'excluded' and row['exclusion_code']:
            by_code[row['exclusion_code']] = by_code.get(row['exclusion_code'], 0) + 1
        if row['validity'] == 'valid':
            by_scenario.setdefault(row['scenario_id'], {})[row['mode']] = \
                by_scenario.setdefault(row['scenario_id'], {}).get(row['mode'], 0) + 1

    agg_head = aggregate['headline']
    agg_scenarios = {}
    for table in aggregate['scenarios']:
        agg_scenarios[table['scenario_id']] = {'observe': table['observe_runs']} | (
            {'block': table['block']['runs']} if table.get('block') else {})
    agg_block = {table['scenario_id']: table['block']['token_saving_vs_observe']
                 for table in aggregate['scenarios']
                 if table.get('block') and h['block'].get(table['scenario_id'], {}).get('judged')}
    sql_block = {key: value['token_saving'] for key, value in h['block'].items() if value['judged']}

    comparisons = [
        ('valid sessions = aggregate sessions', validity.get('valid'), aggregate['sessions']),
        ('excluded by code = aggregate exclusion_list.by_code', by_code, aggregate['exclusion_list']['by_code']),
        ('valid by scenario and mode = aggregate scenario tables', by_scenario, agg_scenarios),
        ('normal runs', h['normal_runs'], agg_head['normal_runs']),
        ('false positives (aggregate)', h['false_positive'], agg_head['normal_false_positive_runs']),
        ('stall runs', h['stall_runs'], agg_head['stall_runs']),
        ('stall reached (aggregate)', h['stall_reached'], agg_head['stall_runs_stalled']),
        ('stall detected (aggregate)', h['stall_detected'], agg_head['stall_runs_detected']),
        ('stall escalated', h['stall_escalated'], agg_head['stall_runs_escalated']),
        ('saving mean (aggregate)', h['saving_mean'], agg_head['if_stopped_token_ratio_mean_detected']),
        ('block token saving (aggregate, judged scenarios)', sql_block, agg_block),
        ('credits measured total', h['credits_measured_total'], agg_head['credits_measured_total']),
        ('report 4: false positives', h['false_positive'], REPORT_SECTION4['false_positive']),
        ('report 4: successful normal sessions', h['normal_success'], REPORT_SECTION4['normal_success']),
        ('report 4: blocked before success', h['blocked_before_success'], REPORT_SECTION4['blocked_before_success']),
        ('report 4: stall detected', h['stall_detected'], REPORT_SECTION4['stall_detected']),
        ('report 4: stall reached', h['stall_reached'], REPORT_SECTION4['stall_reached']),
        ('report 4: saving mean %', pct(h['saving_mean']), REPORT_SECTION4['saving_mean_pct']),
        ('report 4: block token saving %', {key: pct(value) for key, value in sql_block.items()},
         REPORT_SECTION4['block_token_saving_pct']),
    ]
    results = [{'check': name, 'sql': got, 'expected': want, 'same': got == want}
               for name, got, want in comparisons]
    return {
        'ok': all(item['same'] for item in results),
        'sessions_by_validity': validity,
        'sessions_by_plan_kind': by_plan_kind,
        'excluded_by_code': by_code,
        'valid_by_scenario': by_scenario,
        'headline': h,
        'presentation': presentation(h),
        'judgement_ms': _unified_judgement_ms(store),
        'comparisons': results,
    }


def _aggregate_file():
    """화면 호환용 aggregate 표/범위 메타데이터. 수치 headline 자체는 DB 세션에서 다시 계산한다."""
    from service import load_demo
    path = load_demo.ROOT / load_demo.AGGREGATE
    return load_demo.load_json(path), path


def _scenario_metadata(store):
    """기존 demo 화면 메타데이터를 demo-record 경계 안에서만 읽는다.

    사용자/live 프로젝트가 같은 scenario_key를 가져도 발표용 demo title을
    덮어쓰면 안 된다. 세션 수와 headline도 이미 demo-record만 보므로 title
    lookup 역시 같은 source 경계를 사용한다.
    """
    from service import load_demo
    titles = {r['scenario_key']: r['name'] for r in store.query(
        "SELECT sc.scenario_key, sc.name "
        "FROM scenarios sc "
        "WHERE EXISTS ("
        "  SELECT 1 FROM sessions s "
        "  WHERE s.scenario_id = sc.id AND s.source = 'demo-record'"
        ") "
        "ORDER BY sc.id")}
    return load_demo.scenario_rows(load_demo.ROOT, titles)


def _summary_unified(store):
    rows = _unified_rows(store)
    h = _headline_from_rows(rows)
    aggregate, path = _aggregate_file()
    validity = {}
    by_code = {}
    for r in rows:
        validity[r['validity']] = validity.get(r['validity'], 0) + 1
        if r['validity'] == 'excluded' and r['exclusion_code']:
            by_code[r['exclusion_code']] = by_code.get(r['exclusion_code'], 0) + 1
    return {
        'scope': aggregate.get('scope'),
        'note': '데모 세션 기준 · 유도한 교착 · 시나리오당 관측 5 회 · 단일 모델 (DM-2·DM-5)',
        'aggregates': [{
            'aggregate_id': '+'.join(aggregate.get('plans') or []),
            'aggregate_version': aggregate.get('aggregate_version'), 'plans': aggregate.get('plans') or [],
            'scope': aggregate.get('scope'), 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'loaded_at': None,
        }],
        'sessions_by_validity': validity, 'excluded_by_code': by_code,
        'headline': h, 'presentation': presentation(h), 'judgement_ms': _unified_judgement_ms(store),
    }


def _scenarios_unified(store):
    session_rows = _unified_rows(store)
    counts = {}
    for r in session_rows:
        counts.setdefault(r['scenario_id'], {}).setdefault(r['validity'], {})[r['mode']] = \
            counts.setdefault(r['scenario_id'], {}).setdefault(r['validity'], {}).get(r['mode'], 0) + 1
    aggregate, _ = _aggregate_file()
    tables = {r['scenario_id']: r for r in aggregate.get('scenarios') or []}
    result = [{**r, 'sessions': counts.get(r['scenario_id'], {}), 'aggregate': tables.get(r['scenario_id'])}
              for r in _scenario_metadata(store)]
    return sorted(result, key=lambda r: r['scenario_id'])


def _sessions_unified(store, filters):
    rows = _unified_rows(store)
    for key in SESSION_FILTERS:
        value = filters.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows.sort(key=lambda r: (r.get('scenario_id') or '', r.get('mode') or '',
                             r.get('repeat_index') is None, r.get('repeat_index') or 0, r['session_id']))
    return [{**_public_session(r), 'short': short(r['session_id'])} for r in rows]


def _session_unified(store, session_id):
    rows = [r for r in _unified_rows(store) if r['session_id'] == session_id]
    if not rows:
        return None
    row = rows[0]
    meta = {r['scenario_id']: r for r in _scenario_metadata(store)}.get(row['scenario_id'])
    scenario = None if meta is None else {k: meta.get(k) for k in ('korean_name', 'title', 'pair_scenario_id')}
    return {**_public_session(row), 'short': short(session_id), 'scenario': scenario}


def _steps_unified(store, session_id):
    rows = [r for r in _unified_rows(store) if r['session_id'] == session_id]
    if not rows:
        return []
    judgements = {r['step']: r for r in store.query(
        'SELECT step, judgement_ns, reason, stagnant_run FROM judgements WHERE session_id = ? ORDER BY step',
        [session_id])}
    result = []
    for fact in rows[0]['_replay_steps']:
        j = judgements.get(fact.get('step_id')) or {}
        result.append({**fact, 'judgement': {'judgement_ns': j.get('judgement_ns'), 'reason': j.get('reason'),
                                             'consecutive_steps': j.get('stagnant_run')}})
    return result


def summary(store):
    if _unified_schema(store):
        return _summary_unified(store)
    aggregate = store.query('SELECT aggregate_id, aggregate_version, plans, scope, input_sha256, loaded_at '
                            'FROM aggregates ORDER BY aggregate_id')
    h = headline(store)
    return {
        'scope': aggregate[0]['scope'] if aggregate else None,
        'note': '데모 세션 기준 · 유도한 교착 · 시나리오당 관측 5 회 · 단일 모델 (DM-2·DM-5)',
        'aggregates': aggregate,
        'sessions_by_validity': {r['validity']: r['n'] for r in store.query(SQL['sessions_by_validity'])},
        'excluded_by_code': {r['exclusion_code']: r['n'] for r in store.query(SQL['excluded_by_code'])},
        'headline': h, 'presentation': presentation(h), 'judgement_ms': judgement_ms(store),
    }


def scenarios(store):
    if _unified_schema(store):
        return _scenarios_unified(store)
    rows = store.query('SELECT * FROM scenarios ORDER BY scenario_id')
    counts = {}
    for r in store.query('SELECT scenario_id, validity, mode, COUNT(*) AS n FROM sessions '
                         'GROUP BY scenario_id, validity, mode'):
        counts.setdefault(r['scenario_id'], {}).setdefault(r['validity'], {})[r['mode']] = r['n']
    tables = {}
    for r in store.query('SELECT body FROM aggregates ORDER BY aggregate_id'):
        for t in r['body'].get('scenarios') or []:
            tables.setdefault(t['scenario_id'], t)
    return [{**r, 'sessions': counts.get(r['scenario_id'], {}), 'aggregate': tables.get(r['scenario_id'])}
            for r in rows]


def sessions(store, filters):
    if _unified_schema(store):
        return _sessions_unified(store, filters)
    where, params = [], []
    for key in SESSION_FILTERS:
        if filters.get(key) is not None:
            where.append(f'{key} = ?')
            params.append(filters[key])
    rows = store.query('SELECT * FROM sessions' + (' WHERE ' + ' AND '.join(where) if where else '')
                       + ' ORDER BY scenario_id, mode, repeat_index, session_id', params)
    return [{**r, 'short': short(r['session_id'])} for r in rows]


def session(store, session_id):
    if _unified_schema(store):
        return _session_unified(store, session_id)
    rows = store.query('SELECT * FROM sessions WHERE session_id = ?', [session_id])
    if not rows:
        return None
    row = rows[0]
    scenario = store.query('SELECT korean_name, title, pair_scenario_id FROM scenarios WHERE scenario_id = ?',
                           [row['scenario_id']])
    return {**row, 'short': short(session_id), 'scenario': scenario[0] if scenario else None}


def steps(store, session_id):
    """The session's replay.json steps as recorded, each with its judgement values (judgements.json)."""
    if _unified_schema(store):
        return _steps_unified(store, session_id)
    rows = store.query('SELECT step_id, facts, judgement_ns, criteria_reason, consecutive_steps FROM steps '
                       'WHERE session_id = ? ORDER BY step_id', [session_id])
    return [{**r['facts'], 'judgement': {'judgement_ns': r['judgement_ns'], 'reason': r['criteria_reason'],
                                         'consecutive_steps': r['consecutive_steps']}} for r in rows]
