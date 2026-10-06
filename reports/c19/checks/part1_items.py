"""C-19-2 part 1, DM-83 ②③④ and the credit/lane totals. Reads committed record files (record/judgements.json,
record/replay.json, demo-summary) and conditions.json; structured fields only (no narrative, no reasoning)."""
import json, statistics, math, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
agg = json.loads((ROOT / 'reports/c19/aggregate-main.json').read_text())
rows = agg['session_rows']
out = {}


def rec(sid, name):
    return json.loads((ROOT / 'runs/demo' / sid / 'record' / name).read_text())


# ② false positives: normal-version observe runs with a STOP
fp = []
for r in rows:
    if r['variant'] != 'normal' or r['mode'] != 'observe' or r['first_stop_step'] is None:
        continue
    rp = rec(r['session_id'], 'replay.json')
    success_step = r['steps'] if r['class'] == 'success' else None
    fs = r['first_stop_step']
    window = None
    j = rec(r['session_id'], 'judgements.json')
    for st in j['steps']:
        if st['step_id'] == fs:
            window = (st.get('criteria') or {}).get('consecutive_step_ids')
    wsteps = [s for s in rp['steps'] if window and s['step_id'] in window]
    fp.append({'session': r['session_id'], 'scenario': r['scenario_id'], 'class': r['class'], 'steps': r['steps'],
               'first_stop': fs, 'template': r['first_stop_template'], 'text': r['first_stop_text'],
               'success_step': success_step,
               'block_would_cut_before_success': (success_step is not None and fs < success_step),
               'steps_after_stop_until_end': r['steps'] - fs,
               'if_stopped_token_ratio': (r['if_stopped'] or {}).get('token_ratio'),
               'window': window,
               'window_facts': [{'step': s['step_id'], 'role': s['role'], 'tests': s['tests'],
                                 'changed_paths': s['changed_paths'], 'state': s['state'],
                                 'spec_approved': s['report'].get('spec_approved'),
                                 'open_issues': len(s['report'].get('open_issue_ids') or []),
                                 'status': s['report'].get('status'), 'adopted': s['report'].get('adopted_items'),
                                 'completion_declared': s['report'].get('completion_declared'),
                                 'tools': dict(Counter(f"{t['tool']}{'!' if t['is_error'] else ''}" for t in s['tools'])),
                                 'step_status': s['step_status'], 'failure_reasons': s['failure_reasons']}
                                for s in wsteps]})
    # first approval step / first edit step of CT normal (structured)
    if r['scenario_id'].startswith('DEMO-CT'):
        appr = next((s['step_id'] for s in rp['steps'] if s['report'].get('spec_approved')), None)
        edits = [s['step_id'] for s in rp['steps'] if s['changed_paths']]
        tests = [(s['step_id'], (s['tests'] or {}).get('passed')) for s in rp['steps']]
        fp[-1]['ct_first_spec_approved_step'] = appr
        fp[-1]['ct_steps_with_file_change'] = edits
        fp[-1]['ct_first_step_all_tests'] = next((k for k, v in tests if v is not None and v == 16), None)
out['false_positive_detail'] = fp
out['fp_summary'] = {
    'normal_runs_with_stop': len(fp),
    'false_positive_runs (success or escalated)': sum(f['class'] in ('success', 'escalated') for f in fp),
    'of_which_block_would_cut_before_success': sum(f['block_would_cut_before_success'] for f in fp),
    'max_steps_runs_with_stop': sum(f['class'] == 'stalled' for f in fp)}

# CT normal runs without STOP: approval and edits, for comparison
ctn = []
for r in rows:
    if r['scenario_id'] == 'DEMO-CT-normal-v1':
        rp = rec(r['session_id'], 'replay.json')
        ctn.append({'session': r['session_id'][-32:][:8], 'steps': r['steps'], 'first_stop': r['first_stop_step'],
                    'first_spec_approved': next((s['step_id'] for s in rp['steps'] if s['report'].get('spec_approved')), None),
                    'file_change_steps': [s['step_id'] for s in rp['steps'] if s['changed_paths']],
                    'write_refusals': sum(1 for s in rp['steps'] if 'write_refused_before_approval' in s['failure_reasons'])})
out['ct_normal_runs'] = ctn

# ③ misses: stall-version observe runs that stalled without a STOP
miss = []
for r in rows:
    if r['variant'] == 'stall' and r['mode'] == 'observe' and r['class'] == 'stalled' and r['first_stop_step'] is None:
        j = rec(r['session_id'], 'judgements.json')
        last = []
        for st in j['steps'][-12:]:
            pr, cr, col = st.get('progress') or {}, st.get('criteria') or {}, st.get('collection') or {}
            t3 = pr.get('t3') or {}
            last.append({'step': st['step_id'], 'agent': st.get('agent_id'), 'state': pr.get('state'),
                         'events': pr.get('events'), 'conv_moved': pr.get('conversation_moved'),
                         'art_moved': pr.get('artifact_moved'), 'measurement': col.get('measurement_status'),
                         'final_output': col.get('final_output_status'),
                         'tests': t3.get('test_pass_count'), 'test_max': t3.get('test_max'),
                         'changed_paths': t3.get('changed_paths'), 'revert': t3.get('global_revert'),
                         'plateau_steps': t3.get('plateau_steps'), 'test_plateau': t3.get('test_plateau'),
                         'decision': cr.get('decision'), 'consecutive_states': cr.get('consecutive_states'),
                         'unmeasured_steps': cr.get('unmeasured_steps')})
        allsteps = j['steps']
        states = Counter((s.get('progress') or {}).get('state') for s in allsteps)
        meas = Counter((s.get('collection') or {}).get('measurement_status') for s in allsteps)
        decisions = Counter((s.get('criteria') or {}).get('decision') for s in allsteps)
        miss.append({'session': r['session_id'], 'steps': r['steps'], 'stall_start': r['stall_start'],
                     'failed_step_reasons': r['failed_step_reasons'], 'state_counts': dict(states),
                     'measurement_counts': dict(meas), 'decision_counts': dict(decisions),
                     'state_sequence': ''.join({'progress': 'P', 'stagnant': 'S', 'oscillating': 'O', 'baseline': 'B',
                                                'unmeasured': 'U'}.get((s.get('progress') or {}).get('state'), '?')
                                               for s in allsteps),
                     'last_12': last})
out['misses'] = miss

# ④ negative detection delays: last result change per step
neg = []
for r in rows:
    if r['mode'] == 'observe' and r['detection_delay'] is not None:
        j = rec(r['session_id'], 'judgements.json')
        changes = []
        prev = (json.loads((ROOT / 'runs/demo' / r['session_id'] / 'summary.json').read_text()).get('tests_passed_before'), None)
        for st in j['steps']:
            t3 = (st.get('progress') or {}).get('t3')
            if t3 is None:
                continue
            v = (t3.get('test_pass_count'), t3.get('global_state_sha256'))
            if v != prev:
                changes.append({'step': st['step_id'], 'tests': v[0], 'state_changed': v[1] != prev[1],
                                'tests_changed': v[0] != prev[0]})
            prev = v
        neg.append({'session': r['session_id'][-32:][:8], 'scenario': r['scenario_id'], 'first_stop': r['first_stop_step'],
                    'stall_start': r['stall_start'], 'delay': r['detection_delay'],
                    'late_progress': r['detection_delay'] < 0,
                    'change_steps_after_first_stop': [c for c in changes if c['step'] >= r['first_stop_step']]})
out['delays'] = neg

# ⑤ block vs observe (from the aggregate tables, with STOP presence in the block runs)
blk = []
for s in agg['scenarios']:
    if s.get('block'):
        b = s['block']
        bruns = [r for r in rows if r['scenario_id'] == s['scenario_id'] and r['mode'] == 'block']
        blk.append({'scenario': s['scenario_id'], 'runs': b['runs'], 'ends': b['classes'],
                    'block_runs_with_stop': sum(r['first_stop_step'] is not None for r in bruns),
                    'stop_steps': [r['first_stop_step'] for r in bruns],
                    'token_saving': b['token_saving_vs_observe'], 'credit_saving': b['credit_saving_vs_observe'],
                    'observe_if_stopped_ratio_mean': s['if_stopped_token_ratio_mean'],
                    'mean_tokens_block': b['mean_tokens'], 'mean_tokens_observe': b['observe_mean_tokens']})
out['block'] = blk

# credits: per lane, estimate vs measured
lane = defaultdict(lambda: {'sessions': 0, 'measured': 0.0, 'estimated': 0.0})
for r in rows:
    c = json.loads((ROOT / 'runs/demo' / r['session_id'] / 'conditions.json').read_text())['batch']
    k = f"{r['plan_id']} lane {c['lane']}/{c['lanes']}"
    lane[k]['sessions'] += 1
    lane[k]['measured'] = round(lane[k]['measured'] + (r['credits_measured'] or 0), 5)
    lane[k]['estimated'] = round(lane[k]['estimated'] + (r['credits_estimated'] or 0), 5)
out['credits_by_lane'] = dict(sorted(lane.items()))
out['credits_counted'] = {'measured': round(sum(r['credits_measured'] or 0 for r in rows), 5),
                          'estimated_token_x_price': round(sum(r['credits_estimated'] or 0 for r in rows), 5),
                          'sessions_measured_ne_estimated': sum(1 for r in rows if r['credits_measured'] is not None and
                                                                abs(r['credits_measured'] - r['credits_estimated']) > 1e-5)}
# termination of escalated by role, failed step reasons (all counted rows)
out['escalated_by_scenario_mode'] = {f"{k[0]}:{k[1]}": dict(v) for k, v in sorted(
    {(r['scenario_id'], r['mode']): Counter() for r in rows}.items())}
for r in rows:
    if r['class'] == 'escalated':
        out['escalated_by_scenario_mode'][f"{r['scenario_id']}:{r['mode']}"][r['escalated_by']] = \
            out['escalated_by_scenario_mode'][f"{r['scenario_id']}:{r['mode']}"].get(r['escalated_by'], 0) + 1
out['escalated_by_scenario_mode'] = {k: v for k, v in out['escalated_by_scenario_mode'].items() if v}
out['escalated_runs_with_stop'] = sum(1 for r in rows if r['class'] == 'escalated' and r['first_stop_step'] is not None)
out['failed_step_reasons_all'] = dict(sum((Counter(r['failed_step_reasons']) for r in rows), Counter()))
out['vocab_steps_in_first_stop_windows'] = sum(r['vocabulary_steps_in_first_stop_window'] for r in rows)
# judgement_ns over all counted sessions
ns = []
for r in rows:
    for st in rec(r['session_id'], 'judgements.json')['steps']:
        if st.get('judgement_ns') is not None:
            ns.append(st['judgement_ns'])
ns.sort()
out['judgement_ms'] = {'n': len(ns), 'p50': statistics.median(ns) / 1e6, 'p99': ns[math.ceil(0.99 * len(ns)) - 1] / 1e6,
                       'max': ns[-1] / 1e6}
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in out.items() if k not in ('false_positive_detail', 'misses')}, ensure_ascii=False, indent=1))
