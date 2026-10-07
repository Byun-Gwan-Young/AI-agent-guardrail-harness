"""C-19-6 : SQL over the demo tables — the post-load check queries and the read queries of the API.

The presentation numbers are counted again in SQL from the session rows (validity, mode, variant, class, first STOP,
if-stopped ratio, tokens). `check` compares them with the aggregate JSON (C-19-1 output) and with the numbers of
reports/c19/final-report.md section 4. Nothing here writes.
"""
import math
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
    """Counts and presentation numbers from SQL, compared with the aggregate JSON and final-report section 4."""
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


def summary(store):
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
    where, params = [], []
    for key in SESSION_FILTERS:
        if filters.get(key) is not None:
            where.append(f'{key} = ?')
            params.append(filters[key])
    rows = store.query('SELECT * FROM sessions' + (' WHERE ' + ' AND '.join(where) if where else '')
                       + ' ORDER BY scenario_id, mode, repeat_index, session_id', params)
    return [{**r, 'short': short(r['session_id'])} for r in rows]


def session(store, session_id):
    rows = store.query('SELECT * FROM sessions WHERE session_id = ?', [session_id])
    if not rows:
        return None
    row = rows[0]
    scenario = store.query('SELECT korean_name, title, pair_scenario_id FROM scenarios WHERE scenario_id = ?',
                           [row['scenario_id']])
    return {**row, 'short': short(session_id), 'scenario': scenario[0] if scenario else None}


def steps(store, session_id):
    """The session's replay.json steps as recorded, each with its judgement values (judgements.json)."""
    rows = store.query('SELECT step_id, facts, judgement_ns, criteria_reason, consecutive_steps FROM steps '
                       'WHERE session_id = ? ORDER BY step_id', [session_id])
    return [{**r['facts'], 'judgement': {'judgement_ns': r['judgement_ns'], 'reason': r['criteria_reason'],
                                         'consecutive_steps': r['consecutive_steps']}} for r in rows]
