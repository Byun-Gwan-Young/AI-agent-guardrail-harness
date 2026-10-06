"""Demo aggregation (C-19-1 part 1): the sessions of a batch plan, by scenario, task type and overall, from the record
files a session commits (demo-records-v1: conditions.json, summary.json, record/demo-summary.json,
record/judgements.json, record/replay.json). No raw log is read, no model text is used. Demo sessions only, never the
dataset (DM-2): every number is "데모 세션 기준".

  aggregate_demo.py --plan demo-main-v1 --final-freeze-sha256 <sha256 of docs/criteria/demo-final-freeze.json>
                    [--plan demo-main-v1-lr2 --exclusions reports/c18-7/exclusions.json]
                    [--output-json <file>] [--output-md <file>]

Sessions: every runs/demo/<id> whose conditions.json batch.plan_id is one of --plan, and any --session named. A session
is left out of the tables and listed under excluded when
- --final-freeze-sha256 is given and its batch.final_freeze_sha256 differs (main plan, DM-33), or
- its condition group (condition-group-v1) is not the group most sessions of the same scenario and mode have.
Without --final-freeze-sha256 (trial plans) no freeze is checked and the output says so.
With --exclusions (C-18-7, DM-78, C-18-8: tools/demo_exclusions.py output, v1 or v2) a session the list marks excluded is left out first and
counted by its reason code under exclusion_list; a rerun that replaces one is an ordinary session of its plan and is
counted as such, so the per-scenario denominators are valid sessions. Sessions of the selected plans the list does not
name (a list older than the records) are listed there too. With more than one plan or with a list, git_commits gives the
number of counted sessions per commit, overall and per plan (plans may run at different commits, DM-79 ④). One plan
without a list gives the same output as before.
With --account-corrections (C-18-8, DM-81 ②: tools/demo_account_corrections.py output) accounts_corrected gives the
per-account credit totals with the stated accounts applied, next to accounts (the labels, unchanged). Without it the
output is as before.

Termination classes (DM-18, DM-46, DM-48): success; stalled = not finished (max_steps, or guardrail_stop in block
mode); escalated (by escalated_by); other (runner_error, strict_output_failures, ...).
Per scenario (observe runs): "k of n stalled" (DM-6), first STOP step and template, an explanation sentence; normal
versions: sessions with a STOP (false positive; in a success or an escalated run, DM-18); stall versions: stalled runs
with a STOP (detected). Detection delay = first STOP step - stall start, only where a stall start is defined
independently of the guardrail: artifact tasks (T2, T3), stall start = the step after the last step in which the
acceptance pass count or the workspace state changed (S-27); a negative delay is an early STOP, counted apart and
left out of the median (S-20). T1 tasks have no such signal and get none. "If stopped" savings (observe): tokens and
estimated credits of the steps after the first STOP over the session total (record/replay.json); block runs: the
difference to the mean of the same scenario's observe runs only (DM-23).
Representatives (rule in code, reason in the output): for each stall (and natural) scenario, among its observe runs
with a first STOP whose template is the scenario's most frequent first-STOP template, the run whose first STOP step is
the lower median (then the session ID); for each normal scenario, among its successful observe runs, the run whose
step count is the lower median (then the session ID).
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
DEMO_RUNS = ROOT / 'runs' / 'demo'
VERSION = 'demo-aggregate-v1'
EXCLUSION_VERSIONS = ('demo-exclusions-v1', 'demo-exclusions-v2')
TASK_TYPES = {'DEMO-CS': 'T1', 'DEMO-MR': 'T1', 'DEMO-LR': 'T1', 'DEMO-CT': 'T2', 'DEMO-CT-N': 'T2', 'DEMO-CL': 'T3'}
TYPE_LABELS = {'T1': 'T1 대화 교착', 'T2': 'T2 대화+산출물 교착', 'T3': 'T3 산출물 교착'}
STALLED = ('max_steps', 'guardrail_stop')
SCOPE = '데모 세션 기준 (데이터셋 아님, DM-2)'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def optional(path):
    return load(path) if Path(path).is_file() else None


def task_of(scenario_id):
    """(task, variant): DEMO-CT-N-v1 -> (DEMO-CT-N, natural); DEMO-CS-stall-v1 -> (DEMO-CS, stall)."""
    for variant in ('normal', 'stall'):
        marker = f'-{variant}-'
        if marker in scenario_id:
            return scenario_id.split(marker)[0], variant
    return scenario_id.rsplit('-v', 1)[0], 'natural'


def termination_class(reason):
    if reason == 'success':
        return 'success'
    if reason == 'escalated':
        return 'escalated'
    if reason in STALLED:
        return 'stalled'
    return 'other'


def stall_start(judgements, tests_before):
    """S-27 for artifact tasks: the step after the last step whose pass count or workspace state changed. None when
    the session has no artifact observation (T1)."""
    values = []
    for step in judgements['steps']:
        t3 = (step.get('progress') or {}).get('t3')
        if t3 is None:
            continue
        values.append((step['step_id'], (t3.get('test_pass_count'), t3.get('global_state_sha256'))))
    if not values:
        return None
    last, previous = None, (tests_before, None)
    for step_id, value in values:
        if value != previous:
            last = step_id
        previous = value
    return last + 1


def stop_window(judgements, step_id):
    for step in judgements['steps']:
        if step['step_id'] == step_id:
            return (step.get('criteria') or {}).get('consecutive_step_ids') or []
    return []


def session_row(folder):
    folder = Path(folder)
    conditions, summary = load(folder / 'conditions.json'), load(folder / 'summary.json')
    demo, judgements = load(folder / 'record/demo-summary.json'), load(folder / 'record/judgements.json')
    replay = optional(folder / 'record/replay.json')
    scenario_id = conditions['scenario']['scenario_id']
    task, variant = task_of(scenario_id)
    batch = conditions.get('batch') or {}
    first = demo.get('first_stop') or None
    reason = summary['termination_reason']
    klass = termination_class(reason)
    start = stall_start(judgements, summary.get('tests_passed_before')) if klass == 'stalled' else None
    first_step = first['step_id'] if first else None
    window = stop_window(judgements, first_step) if first_step else []
    vocabulary = set(summary.get('vocabulary_violation_steps') or [])
    if_stopped = (replay or {}).get('if_stopped')
    return {'session_id': folder.name, 'scenario_id': scenario_id, 'task': task, 'variant': variant,
            'task_type': TASK_TYPES.get(task), 'mode': batch.get('mode') or demo.get('guardrail_mode'),
            'repeat': batch.get('repeat'), 'plan_id': batch.get('plan_id'), 'account_label': demo.get('account_label'),
            'final_freeze_sha256': batch.get('final_freeze_sha256'), 'condition_group': demo.get('condition_group'),
            'termination_reason': reason, 'class': klass, 'escalated_by': summary.get('escalated_by'),
            'steps': summary['steps'], 'first_stop_step': first_step,
            'first_stop_template': first.get('template_id') if first else None,
            'first_stop_text': first.get('text') if first else None, 'stop_steps': demo.get('stop_steps') or [],
            'stall_start': start, 'detection_delay': None if start is None or first_step is None else first_step - start,
            'vocabulary_steps_in_first_stop_window': len(vocabulary & set(window)),
            'failed_step_reasons': dict(Counter(r for s in summary.get('failed_steps') or [] for r in s['reasons'])),
            'tokens': (demo.get('tokens') or {}).get('prompt', 0) + (demo.get('tokens') or {}).get('completion', 0),
            'credits_measured': (demo.get('credits_measured') or {}).get('value'),
            'credits_estimated': (demo.get('credits_estimated') or {}).get('value'),
            'if_stopped': None if not if_stopped else {k: if_stopped[k] for k in
                                                       ('stop_step', 'token_ratio', 'tokens_after', 'credits_after',
                                                        'credits_total')},
            'replay_recorded': replay is not None}


def select(runs_root, plans, sessions):
    found = []
    for folder in sorted(Path(runs_root).iterdir()) if Path(runs_root).is_dir() else []:
        conditions = folder / 'conditions.json'
        if not conditions.is_file() or not (folder / 'record/demo-summary.json').is_file():
            continue
        plan = (load(conditions).get('batch') or {}).get('plan_id')
        if plan in plans or folder.name in sessions:
            found.append(folder)
    return found


def exclusions(rows, freeze):
    """(kept, excluded): a different final freeze, or a condition group not the majority of its scenario and mode."""
    majority = {}
    for key in {(r['scenario_id'], r['mode']) for r in rows}:
        groups = Counter(r['condition_group'] for r in rows if (r['scenario_id'], r['mode']) == key)
        majority[key] = sorted(groups.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]
    kept, excluded = [], []
    for row in rows:
        reasons = []
        if freeze is not None and row['final_freeze_sha256'] != freeze:
            reasons.append(f"final freeze {row['final_freeze_sha256']} is not {freeze}")
        if row['condition_group'] != majority[(row['scenario_id'], row['mode'])]:
            reasons.append(f"condition group {row['condition_group']} is not the scenario's "
                           f"{majority[(row['scenario_id'], row['mode'])]}")
        (excluded if reasons else kept).append(row if not reasons else {**row, 'excluded_because': reasons})
    return kept, excluded


def mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.fmean(values), 5) if values else None


def lower_median(values):
    values = sorted(values)
    return values[(len(values) - 1) // 2] if values else None


def scenario_table(rows, scenario_id):
    observe = [r for r in rows if r['scenario_id'] == scenario_id and r['mode'] == 'observe']
    block = [r for r in rows if r['scenario_id'] == scenario_id and r['mode'] == 'block']
    sample = (observe or block)[0]
    classes = Counter(r['class'] for r in observe)
    stops = [r for r in observe if r['first_stop_step'] is not None]
    delays = [r['detection_delay'] for r in observe if r['detection_delay'] is not None]
    table = {'scenario_id': scenario_id, 'task': sample['task'], 'variant': sample['variant'],
             'task_type': sample['task_type'], 'observe_runs': len(observe),
             'classes': {k: classes.get(k, 0) for k in ('success', 'stalled', 'escalated', 'other')},
             'stalled_k_of_n': f"{classes.get('stalled', 0)} / {len(observe)}",
             'escalated_by': dict(Counter(r['escalated_by'] for r in observe if r['class'] == 'escalated')),
             'other_reasons': dict(Counter(r['termination_reason'] for r in observe if r['class'] == 'other')),
             'runs_with_stop': len(stops), 'first_stop_steps': sorted(r['first_stop_step'] for r in stops),
             'first_stop_templates': dict(Counter(r['first_stop_template'] for r in stops)),
             'explanation_example': stops[0]['first_stop_text'] if stops else None,
             'false_positive_runs': (None if sample['variant'] != 'normal' else
                                     {'success_with_stop': sum(r['class'] == 'success' and r['first_stop_step'] is not None
                                                               for r in observe),
                                      'escalated_with_stop': sum(r['class'] == 'escalated' and r['first_stop_step']
                                                                 is not None for r in observe)}),
             'detected_runs': (None if sample['variant'] == 'normal' else
                               {'stalled': classes.get('stalled', 0),
                                'stalled_with_stop': sum(r['class'] == 'stalled' and r['first_stop_step'] is not None
                                                         for r in observe)}),
             'detection_delay': {'method': ('first STOP step - stall start (S-27: step after the last change of the '
                                            'acceptance pass count or the workspace state)')
                                 if sample['task_type'] in ('T2', 'T3') else
                                 'not computed: a T1 task has no result signal independent of the guardrail',
                                 'values': sorted(delays), 'median_of_non_negative': lower_median(
                                     [d for d in delays if d >= 0]) if delays else None,
                                 'early_stops': sum(d < 0 for d in delays)},
             'if_stopped_token_ratio_mean': mean([r['if_stopped']['token_ratio'] for r in observe if r['if_stopped']]),
             'if_stopped_credits_after_sum': round(sum(r['if_stopped']['credits_after'] or 0 for r in observe
                                                       if r['if_stopped']), 5),
             'credits_measured_sum': round(sum(r['credits_measured'] or 0 for r in observe), 5),
             'credits_estimated_sum': round(sum(r['credits_estimated'] or 0 for r in observe), 5),
             'failed_step_reasons': dict(sum((Counter(r['failed_step_reasons']) for r in observe), Counter())),
             'vocabulary_steps_in_first_stop_window': sum(r['vocabulary_steps_in_first_stop_window'] for r in observe),
             'replay_missing': [r['session_id'] for r in observe if not r['replay_recorded']]}
    if block:
        base_tokens, base_credits = mean([r['tokens'] for r in observe]), mean([r['credits_estimated'] for r in observe])
        table['block'] = {
            'runs': len(block), 'classes': dict(Counter(r['termination_reason'] for r in block)),
            'mean_tokens': mean([r['tokens'] for r in block]), 'mean_credits_estimated': mean([r['credits_estimated']
                                                                                              for r in block]),
            'observe_mean_tokens': base_tokens, 'observe_mean_credits_estimated': base_credits,
            'token_saving_vs_observe': (None if not base_tokens else
                                        round(1 - mean([r['tokens'] for r in block]) / base_tokens, 4)),
            'credit_saving_vs_observe': (None if not base_credits else
                                         round(1 - mean([r['credits_estimated'] for r in block]) / base_credits, 4)),
            'basis': 'difference to the mean of the same scenario\'s observe runs only (DM-23)'}
    return table


def representatives(rows, tables):
    chosen = []
    for table in tables:
        runs = [r for r in rows if r['scenario_id'] == table['scenario_id'] and r['mode'] == 'observe']
        if table['variant'] == 'normal':
            pool = [r for r in runs if r['class'] == 'success']
            if not pool:
                continue
            target = lower_median([r['steps'] for r in pool])
            pick = sorted((r for r in pool if r['steps'] == target), key=lambda r: r['session_id'])[0]
            reason = f"정상판 성공 {len(pool)} 회 중 step 수가 아래 중앙값({target})인 세션"
        else:
            stopped = [r for r in runs if r['first_stop_template']]
            if not stopped:
                continue
            counts = Counter(r['first_stop_template'] for r in stopped)
            template = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            pool = [r for r in stopped if r['first_stop_template'] == template]
            target = lower_median([r['first_stop_step'] for r in pool])
            pick = sorted((r for r in pool if r['first_stop_step'] == target), key=lambda r: r['session_id'])[0]
            reason = (f"첫 STOP 이 난 {len(stopped)} 회 중 가장 많은 템플릿 {template}({counts[template]} 회) 가운데 "
                      f"첫 STOP step 이 아래 중앙값({target})인 세션")
        chosen.append({'scenario_id': table['scenario_id'], 'task_type': TYPE_LABELS.get(table['task_type'], '-'),
                       'role': {'normal': '정상판', 'stall': '교착판', 'natural': '자연 발생 비교군'}[table['variant']],
                       'session_id': pick['session_id'], 'first_stop_step': pick['first_stop_step'],
                       'template_id': pick['first_stop_template'], 'reason': reason})
    return chosen


def type_summary(rows, task_type):
    observe = [r for r in rows if r['task_type'] == task_type and r['mode'] == 'observe']
    normal = [r for r in observe if r['variant'] == 'normal']
    stall = [r for r in observe if r['variant'] == 'stall']
    detected = [r for r in stall if r['class'] == 'stalled' and r['first_stop_step'] is not None]
    return {'task_type': task_type, 'label': TYPE_LABELS[task_type], 'observe_runs': len(observe),
            'normal_runs': len(normal), 'normal_success': sum(r['class'] == 'success' for r in normal),
            'normal_with_stop': sum(r['first_stop_step'] is not None for r in normal),
            'normal_false_positive': sum(r['first_stop_step'] is not None and r['class'] in ('success', 'escalated')
                                         for r in normal),
            'stall_runs': len(stall), 'stall_stalled': sum(r['class'] == 'stalled' for r in stall),
            'stall_escalated': sum(r['class'] == 'escalated' for r in stall), 'stall_detected': len(detected),
            'if_stopped_token_ratio_mean_detected': mean([r['if_stopped']['token_ratio'] for r in detected
                                                         if r['if_stopped']])}


def listed_exclusions(rows, listing):
    """(rows the list leaves in, summary of what it took out). listing is a demo-exclusions-v1 or -v2 document (v2,
    C-18-8: more reason codes, and supplement sessions as replacements)."""
    if listing.get('exclusions_version') not in EXCLUSION_VERSIONS:
        raise ValueError('--exclusions takes a demo-exclusions-v1 or -v2 file (tools/demo_exclusions.py)')
    named = listing.get('sessions') or {}
    marked = {k: v for k, v in named.items() if v.get('excluded')}
    out = [r for r in rows if r['session_id'] in marked]
    summary = {'exclusions_version': listing['exclusions_version'], 'plans': listing.get('plans'),
               'by_code': dict(sorted(Counter(marked[r['session_id']]['excluded'] for r in out).items())),
               'sessions': [{'session_id': r['session_id'], 'scenario_id': r['scenario_id'], 'mode': r['mode'],
                             'repeat': r['repeat'], 'plan_id': r['plan_id'],
                             'code': marked[r['session_id']]['excluded'],
                             'replaced_by': marked[r['session_id']].get('replaced_by')} for r in out],
               'replaced': sum(1 for r in out if marked[r['session_id']].get('replaced_by')),
               'sessions_not_in_list': sorted(r['session_id'] for r in rows if r['session_id'] not in named),
               'items_without_valid_session': listing.get('items_without_valid_session') or [],
               'unresolved': listing.get('unresolved') or [], 'unfinished': listing.get('unfinished') or []}
    return [r for r in rows if r['session_id'] not in marked], summary


def by_key(mapping):
    return dict(sorted(mapping.items(), key=lambda kv: str(kv[0])))


def commit_counts(rows, commits):
    by_plan = {}
    for row in rows:
        plan = by_plan.setdefault(row['plan_id'], Counter())
        plan[commits.get(row['session_id'])] += 1
    return {'all': by_key(sum(by_plan.values(), Counter())),
            'by_plan': by_key({plan: by_key(counts) for plan, counts in by_plan.items()})}


def account_totals(rows, account_of):
    accounts = {}
    for row in rows:
        entry = accounts.setdefault(account_of(row) or '(없음)', {'sessions': 0, 'credits_measured': 0.0})
        entry['sessions'] += 1
        entry['credits_measured'] = round(entry['credits_measured'] + (row['credits_measured'] or 0), 5)
    return accounts


def corrected_accounts(rows, corrections):
    """Per-account totals with a demo-account-corrections-v1 file applied (the labels stay in accounts)."""
    if corrections.get('account_corrections_version') != 'demo-account-corrections-v1':
        raise ValueError('--account-corrections takes a demo-account-corrections-v1 file '
                         '(tools/demo_account_corrections.py)')
    actual = {s['session_id']: s['actual'] for s in corrections.get('sessions') or []}
    counted = [r for r in rows if r['session_id'] in actual]
    return {'source': corrections.get('source'), 'sessions_in_file': len(actual), 'sessions_counted': len(counted),
            'sessions_relabelled': sum(1 for r in counted if r['account_label'] != actual[r['session_id']]),
            'accounts': account_totals(rows, lambda r: actual.get(r['session_id'], r['account_label']))}


def aggregate(plans, *, freeze=None, sessions=(), runs_root=DEMO_RUNS, exclusion_list=None, account_corrections=None):
    folders = select(runs_root, set(plans), set(sessions))
    rows = [session_row(f) for f in folders]
    listed = None
    if exclusion_list is not None:
        rows, listed = listed_exclusions(rows, exclusion_list)
    kept, excluded = exclusions(rows, freeze)
    scenario_ids = sorted({r['scenario_id'] for r in kept})
    tables = [scenario_table(kept, s) for s in scenario_ids]
    types = [type_summary(kept, t) for t in ('T1', 'T2', 'T3') if any(r['task_type'] == t for r in kept)]
    accounts = account_totals(kept, lambda r: r['account_label'])
    observe = [r for r in kept if r['mode'] == 'observe']
    detected = [r for r in observe if r['variant'] == 'stall' and r['class'] == 'stalled' and r['first_stop_step']]
    headline = {'scope': SCOPE,
                'normal_runs_with_stop': sum(r['variant'] == 'normal' and r['first_stop_step'] is not None
                                             for r in observe),
                'normal_runs': sum(r['variant'] == 'normal' for r in observe),
                # S-1 / DM-18: a STOP is a false positive in a successful or an escalated normal run only.
                'normal_false_positive_runs': sum(r['variant'] == 'normal' and r['first_stop_step'] is not None
                                                  and r['class'] in ('success', 'escalated') for r in observe),
                'stall_runs_stalled': sum(r['variant'] == 'stall' and r['class'] == 'stalled' for r in observe),
                'stall_runs_detected': len(detected),
                'stall_runs_escalated': sum(r['variant'] == 'stall' and r['class'] == 'escalated' for r in observe),
                'stall_runs': sum(r['variant'] == 'stall' for r in observe),
                'if_stopped_token_ratio_mean_detected': mean([r['if_stopped']['token_ratio'] for r in detected
                                                             if r['if_stopped']]),
                'credits_measured_total': round(sum(r['credits_measured'] or 0 for r in kept), 5)}
    result = {'aggregate_version': VERSION, 'scope': SCOPE, 'plans': sorted(plans), 'named_sessions': sorted(sessions),
              'final_freeze_sha256': freeze,
              'freeze_check': 'applied' if freeze else 'not applied (no --final-freeze-sha256: trial plans)',
              'sessions': len(kept), 'excluded': excluded, 'headline': headline, 'types': types,
              'scenarios': tables, 'accounts': accounts, 'representatives': representatives(kept, tables),
              'session_rows': kept}
    if listed is not None:
        result['exclusion_list'] = listed
    if account_corrections is not None:
        result['accounts_corrected'] = corrected_accounts(kept, account_corrections)
    if listed is not None or len(set(plans)) > 1:
        commits = {f.name: (load(f / 'conditions.json').get('git_commit')) for f in folders}
        result['git_commits'] = commit_counts(kept, commits)
    return result


def markdown(result):
    h = result['headline']
    lines = [f"# 데모 집계 — {', '.join(result['plans'])}", '', f"- 범위 : {result['scope']}",
             f"- 세션 {result['sessions']} 개, 제외 {len(result['excluded'])} 개, 최종 동결 검사 : {result['freeze_check']}",
             *listed_lines(result),
             f"- 정상판 STOP : {h['normal_runs_with_stop']} / {h['normal_runs']} 회, 그중 성공·에스컬레이션 세션의 STOP (오탐) "
             f"{h['normal_false_positive_runs']} 회",
             f"- 교착판 : 미완료 {h['stall_runs_stalled']} / {h['stall_runs']} 회, 그중 STOP {h['stall_runs_detected']} 회, "
             f"에스컬레이션 {h['stall_runs_escalated']} 회",
             f"- 탐지된 교착판의 \"STOP 에서 멈췄다면\" 아낄 토큰 비율 평균 : {fmt_ratio(h['if_stopped_token_ratio_mean_detected'])}",
             f"- 실측 크레딧 합 : {h['credits_measured_total']}", '', '## 유형별', '',
             '| 유형 | 관측 | 정상판 성공 | 정상판 STOP (오탐) | 교착판 미완료 | 교착판 STOP | 교착판 에스컬레이션 | 아낄 토큰 비율 |',
             '|---|---|---|---|---|---|---|---|']
    for t in result['types']:
        lines.append(f"| {t['label']} | {t['observe_runs']} | {t['normal_success']} / {t['normal_runs']} | "
                     f"{t['normal_with_stop']} ({t['normal_false_positive']}) | {t['stall_stalled']} / {t['stall_runs']} | {t['stall_detected']} | "
                     f"{t['stall_escalated']} | {fmt_ratio(t['if_stopped_token_ratio_mean_detected'])} |")
    lines += ['', '## 시나리오별 (관측)', '',
              '| 시나리오 | 성공 | 미완료 (k/n) | 에스컬레이션 | 기타 | STOP 세션 | 첫 STOP step | 템플릿 | 탐지 지연 | 아낄 토큰 비율 | 크레딧 실측 |',
              '|---|---|---|---|---|---|---|---|---|---|---|']
    for s in result['scenarios']:
        c = s['classes']
        escalated = ', '.join(f'{k} {v}' for k, v in s['escalated_by'].items()) or '0'
        delay = s['detection_delay']['values'] if s['task_type'] in ('T2', 'T3') else '—'
        lines.append(f"| {s['scenario_id']} | {c['success']} | {s['stalled_k_of_n']} | {escalated} | {c['other']} | "
                     f"{s['runs_with_stop']} | {s['first_stop_steps']} | {s['first_stop_templates']} | {delay} | "
                     f"{fmt_ratio(s['if_stopped_token_ratio_mean'])} | {s['credits_measured_sum']} |")
    blocks = [s for s in result['scenarios'] if s.get('block')]
    if blocks:
        lines += ['', '## 차단 (관측 평균 대비, DM-23)', '', '| 시나리오 | 차단 회수 | 종료 | 토큰 절감 | 크레딧 절감 |',
                  '|---|---|---|---|---|']
        for s in blocks:
            b = s['block']
            lines.append(f"| {s['scenario_id']} | {b['runs']} | {b['classes']} | {fmt_ratio(b['token_saving_vs_observe'])} | "
                         f"{fmt_ratio(b['credit_saving_vs_observe'])} |")
    lines += ['', '## 원인 설명 문장 예', '']
    lines += [f"- {s['scenario_id']} : {s['explanation_example']}" for s in result['scenarios'] if s['explanation_example']]
    lines += ['', '## 대표 세션', '', '| 시나리오 | 구분 | 세션 | 선정 근거 |', '|---|---|---|---|']
    lines += [f"| {r['scenario_id']} | {r['role']} | {r['session_id']} | {r['reason']} |" for r in result['representatives']]
    lines += ['', '## 계정별 실측 크레딧', '']
    lines += [f"- {k} : {v['sessions']} 세션, {v['credits_measured']}" for k, v in sorted(result['accounts'].items())]
    corrected = result.get('accounts_corrected')
    if corrected is not None:
        lines += ['', f"## 계정별 실측 크레딧 — 보정 표 적용 ({corrected['source']})", '',
                  f"- 보정 표 세션 {corrected['sessions_in_file']} 개 중 집계에 든 {corrected['sessions_counted']} 개, "
                  f"그중 계정이 이름표와 다른 {corrected['sessions_relabelled']} 개를 실제 계정으로 셈"]
        lines += [f"- {k} : {v['sessions']} 세션, {v['credits_measured']}"
                  for k, v in sorted(corrected['accounts'].items())]
    if result['excluded']:
        lines += ['', '## 제외한 세션', '']
        lines += [f"- {r['session_id']} : {'; '.join(r['excluded_because'])}" for r in result['excluded']]
    return '\n'.join(lines) + '\n'


def listed_lines(result):
    """Header lines for the exclusion list and the commits (none for one plan without a list)."""
    lines = []
    listed = result.get('exclusion_list')
    if listed is not None:
        codes = ', '.join(f'{k} {v}' for k, v in listed['by_code'].items()) or '0'
        by = '재실행으로' if listed['exclusions_version'] == 'demo-exclusions-v1' else '재실행·보충 세션으로'
        lines.append(f"- 제외·대체 목록 ({listed['exclusions_version']}) 으로 뺀 세션 {len(listed['sessions'])} 개 "
                     f"(사유별 : {codes}), 그중 {by} 대체 {listed['replaced']} 개. 분모는 유효 세션 수")
        if listed['items_without_valid_session']:
            lines.append(f"- 유효 세션이 없는 항목 {len(listed['items_without_valid_session'])} 개 : "
                         + ', '.join(listed['items_without_valid_session']))
        if listed['sessions_not_in_list']:
            lines.append(f"- 목록에 없는 세션 {len(listed['sessions_not_in_list'])} 개 (목록을 다시 만들 것) : "
                         + ', '.join(listed['sessions_not_in_list']))
    commits = result.get('git_commits')
    if commits is not None:
        lines.append('- 커밋별 세션 : ' + '; '.join(
            f"{plan} " + ', '.join(f'{str(c)[:7]} {n}' for c, n in counts.items())
            for plan, counts in commits['by_plan'].items()))
    return lines


def fmt_ratio(value):
    return '—' if value is None else f'{100 * value:.1f}%'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', action='append', default=[])
    parser.add_argument('--session', action='append', default=[], help='a session folder name to include as well')
    parser.add_argument('--final-freeze-sha256')
    parser.add_argument('--exclusions', type=Path, help='a demo-exclusions-v1 or -v2 file (tools/demo_exclusions.py)')
    parser.add_argument('--account-corrections', type=Path,
                        help='a demo-account-corrections-v1 file (tools/demo_account_corrections.py)')
    parser.add_argument('--runs-root', type=Path, default=DEMO_RUNS)
    parser.add_argument('--output-json', type=Path)
    parser.add_argument('--output-md', type=Path)
    args = parser.parse_args()
    if not args.plan and not args.session:
        parser.error('name --plan or --session')
    listing = json.loads(args.exclusions.read_text(encoding='utf-8')) if args.exclusions else None
    corrections = (json.loads(args.account_corrections.read_text(encoding='utf-8'))
                   if args.account_corrections else None)
    result = aggregate(args.plan, freeze=args.final_freeze_sha256, sessions=args.session, runs_root=args.runs_root,
                       exclusion_list=listing, account_corrections=corrections)
    text = json.dumps(result, ensure_ascii=False, indent=1) + '\n'
    for path, content in ((args.output_json, text), (args.output_md, markdown(result))):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
    print(markdown(result), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
