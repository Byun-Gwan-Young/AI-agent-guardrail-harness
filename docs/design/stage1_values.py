"""Stage 1 design values (C-12). Read-only; no runtime code is changed or imported for writing.

Computes, from the committed G0-8 and A-1-v3 session files only:
- metric option values (normal session, preservation, savings, detection delay)
- candidate judgement rules replayed offline (reference only, never a selection basis)
- spec linter checks rendered from the runner's own prompt code (A-1-v2 / A-1-v3 x v7 / v8)
- per-step credit figures for the pilot budget section (estimates are labelled)
Writes docs/design/stage1-values.json. Numbers in the design document come from that file.
"""
import copy
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from analyze_session import analyse
from deadlock_policy import evaluate_criteria
from experiments.issue_contract import V2, for_scenario
from experiments.run_scenario import Workspace, role_system_message, safe_path, schema_instructions
from progress_signal import calculate_progress
from progress_signal_v1 import calculate_progress as calculate_v1
from scenario_schema import load_scenario

SESSIONS = {'G0-8': 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e', 'A-1-v3': 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73'}
V3_CREDITS = 4258.13384 - 4241.70359  # user-recorded monthly_allocated.used (C-11)
PRICE = {'prompt': 0.15, 'completion': 0.60}  # USD per 1M tokens; 1 credit = $0.001 (matched in C-11)
STOP = ('deadlock', 'termination_failure')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def inputs(observation):
    return {k: copy.deepcopy(v) for k, v in observation.items() if k not in ('progress', 'criteria', 'observed_at')}


# ---------- candidate rules ----------

def streak_rule(observations, consecutive, grace):
    """deadlock-v0.2 logic with the streak length and grace as parameters (same state machine)."""
    streak, missing, declaration, out = 0, 0, None, []
    for obs in observations:
        step, state = obs['step_id'], (obs.get('progress') or {}).get('state', 'unmeasured')
        ctx = obs.get('termination_context') or {}
        disp = ctx.get('declaration', 'unknown')
        if disp == 'declared':
            if declaration is None:
                declaration, streak = ctx.get('declared_step'), 0
            elif declaration != ctx.get('declared_step'):
                disp = 'unknown'
        elif disp == 'none' and declaration is not None:
            disp = 'unknown'
        if state == 'unmeasured' or disp == 'unknown':
            missing, streak = missing + 1, 0
            out.append('unmeasured')
            continue
        missing = 0
        if state not in ('stagnant', 'oscillating') or (declaration is not None and step <= declaration):
            streak = 0
            out.append('continue')
            continue
        streak += 1
        if declaration is not None and step - declaration <= grace:
            out.append('continue')
        elif streak >= consecutive:
            out.append('deadlock' if declaration is None else 'termination_failure')
        else:
            out.append('continue')
    return out


def v1_state(events, missing, has_history):
    if not has_history:
        return 'baseline'
    if events:
        recurrent = all(e['kind'] in ('oscillation', 'reopen', 'revert') for e in events)
        return ('unmeasured' if missing else 'oscillating') if recurrent else 'progress'
    return 'unmeasured' if missing else 'stagnant'


def global_artifact_progress(observations, artifact_event_steps=None):
    """D-12 candidate: conversation metrics vs the same role (as progress-v2); artifact metrics vs the
    previous global step. First observation of each role stays baseline, as in progress-v2."""
    states, history = [], []
    for obs in observations:
        cur = inputs(obs)
        role_hist = [h for h in history if h['agent_id'] == cur['agent_id']]
        conv = calculate_v1([{**h, 'progress_source': 'conversation'} for h in role_hist],
                            {**cur, 'progress_source': 'conversation'})
        art = calculate_v1([{**h, 'progress_source': 'artifact'} for h in history],
                           {**cur, 'progress_source': 'artifact'})
        missing = [k for r in (conv, art) for k, v in r['metrics'].items() if v['status'] == 'unmeasured']
        states.append(v1_state(conv['events'] + art['events'], missing, bool(role_hist)))
        if artifact_event_steps is not None and art['events'] and role_hist:
            artifact_event_steps.append(cur['step_id'])
        history.append(cur)
    return states


def replay(sid):
    log = load(ROOT / 'logs' / f'{sid}.json')
    observations = log['observations']
    roles = len({o['agent_id'] for o in observations})
    # Gate: recomputing progress-v2 + deadlock-v0.2 from stored inputs must equal the stored results.
    history, recomputed = [], []
    for obs in observations:
        cur = inputs(obs)
        cur['progress'] = calculate_progress(history, cur, version='progress-v2')
        recomputed.append(evaluate_criteria(history + [cur], log['meta'])['decision'])
        history.append(cur)
    stored = [o['criteria']['decision'] for o in observations]
    grace = 2
    g_obs = [{**o, 'progress': {'state': s}} for o, s in zip(observations, global_artifact_progress(observations))]
    rules = {
        'R0 deadlock-v0.2 (3 global steps = 1 role round when roles=3)': streak_rule(observations, 3, grace),
        'R1 1 role round (N = roles x 1)': streak_rule(observations, roles * 1, grace),
        'R2 2 role rounds (N = roles x 2)': streak_rule(observations, roles * 2, grace),
        'G  global artifact comparison, N=3': streak_rule(g_obs, 3, grace),
        'G2 global artifact comparison, 2 role rounds': streak_rule(g_obs, roles * 2, grace),
    }
    return {'roles': roles, 'stored_equals_recomputed_v0.2': stored == recomputed,
            'stored_equals_param_rule_N3': stored == rules['R0 deadlock-v0.2 (3 global steps = 1 role round when roles=3)'],
            'global_artifact_states': global_artifact_progress(observations, g_art := []),
            'global_artifact_event_steps': g_art,
            'stored_states': [o['progress']['state'] for o in observations],
            'rules': {name: {'decisions': d, 'first_stop_step': next((i for i, x in enumerate(d, 1) if x in STOP), None)}
                      for name, d in rules.items()}}


# ---------- metrics ----------

def session_metrics(a, log, expected_tests):
    rows = a['steps']
    turns = {t['turn']: t for t in log['turns']}
    stop = a['first_stop_step']
    tokens_after = lambda s: None if s is None else sum(
        t['tokens'] for t in log['turns'] if t.get('tokens') is not None
        and t['turn'] > max(turns[n]['turn'] for n in rows[s - 1]['llm_turns']))
    declared = any(o['termination_context']['declaration'] == 'declared' for o in log['observations'])
    last_change = max((r['step_id'] for r in rows if r['tests_change_in_step'] or r['files_changed_in_step']), default=None)
    normal = a['termination']['reason'] == 'success'
    return {
        'termination_reason': a['termination']['reason'], 'steps': len(rows), 'llm_calls': len(log['turns']),
        'tests_after': a['judgement']['tests_after'], 'tests_total': expected_tests,
        'all_tests_pass_at_end': a['judgement']['machine_success_at_end'], 'reviewer_declared': declared,
        'normal': {'N1 all tests pass + declaration (= runner success)': a['termination']['reason'] == 'success',
                   'N2 all tests pass at end, declaration not required': a['judgement']['machine_success_at_end'],
                   'N3 pass fraction >= 0.9 at end': a['judgement']['tests_after'] / expected_tests >= 0.9},
        'first_stop_step': stop,
        'known_total': a['tokens']['known_total'], 'total_status': a['tokens']['total_status'],
        'usage_missing_turns': a['tokens']['usage_missing_turns'],
        'known_tokens_after_first_stop': tokens_after(stop),
        'unmeasured_decisions': sum(r['criteria_decision'] == 'unmeasured' for r in rows),
        'needs_observation_review_any': any(o['criteria'].get('needs_observation_review') for o in log['observations']),
        'last_artifact_or_test_change_step': last_change,
        # A normal session has no deadlock onset (3-2), so detection delay is undefined here.
        'onset_a': None if normal else (None if last_change is None else last_change + 1),
        'detection_delay': None if normal else 'failure session: see onset_a',
        'llm_calls_per_step': round(len(log['turns']) / len(rows), 3),
        'artifact_progress_steps': [r['step_id'] for r in rows if any(
            e['metric'].startswith('artifact.') for e in r['events'])],
    }


def binomial_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def normal_sessions_needed(false_stops, target=0.95, confidence=0.95):
    """Smallest n with an exact one-sided upper bound on the false-STOP rate <= 1 - target."""
    n = false_stops + 1
    while binomial_cdf(false_stops, n, 1 - target) > 1 - confidence:
        n += 1
    return n


# ---------- spec linter demo ----------

FACT_MARKERS = {'call_limit': 'model calls for this role', 'writable_files': 'Files this role can write:'}


def lint(scenario_path, facts):
    scenario = load_scenario(scenario_path)
    contract = for_scenario(V2, scenario)
    fields = set(contract.schema()['properties'])
    allowed = {i.id for i in scenario.allowed_issues}
    result = {'scenario': scenario.scenario_id, 'protocol': 'v8' if facts else 'v7', 'roles': {}}
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / 'ws'
        shutil.copytree(safe_path(ROOT, scenario.fixture_dir), ws, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for agent in scenario.agents:
            names = [f.__name__ for f in Workspace(scenario, ws).tools(agent)]
            text = role_system_message(agent, names, scenario, schema_instructions(contract), facts=facts)
            # contract-shaped tokens named in the role's own instruction that the contract lacks
            own = agent.system_message
            for path in scenario.monitored_paths + [p for a in scenario.agents for p in a.writable_paths]:
                own = own.replace(path, ' ')
            named = set(re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', own))
            known = fields | set(names) | {'agent_id', 'step_id'}
            result['roles'][agent.id] = {
                'L1 call budget stated': FACT_MARKERS['call_limit'] in text,
                'L2 writable files stated': FACT_MARKERS['writable_files'] in text,
                'L3 instruction names fields missing from contract': sorted(named - known),
                'L3b instruction asks for a reason with null (no reason field)': bool(re.search(r'null\s*과\s*이유|null and (a )?reason', agent.system_message))}
    result['L4 initial_issue_ids subset of allowed'] = set(scenario.initial_issue_ids) <= allowed
    result['L4b every allowed id has a definition'] = all(i.definition.strip() for i in scenario.allowed_issues)
    result['L5 identifiers explicit'] = {'model': bool(scenario.model), 'criteria_version': bool(scenario.criteria_version),
                                         'max_tokens': scenario.max_tokens is not None,
                                         'temperature': scenario.temperature is not None,
                                         'expected_outcome_unknown': scenario.expected_outcome == 'unknown'}
    return result


# ---------- credits ----------

def credit(prompt, completion):
    return (prompt * PRICE['prompt'] + completion * PRICE['completion']) / 1e6 * 1000


def credits_by_step(sid):
    log = load(ROOT / 'logs' / f'{sid}.json')
    steps = load(ROOT / 'runs' / sid / 'steps.json')
    turns = {t['turn']: t for t in log['turns']}
    out = []
    for s in steps:
        p = sum(turns[n].get('prompt_tokens') or 0 for n in s['llm_turns'])
        c = sum(turns[n].get('completion_tokens') or 0 for n in s['llm_turns'])
        out.append({'step_id': s['step_id'], 'agent': s['agent'], 'calls': len(s['llm_turns']),
                    'prompt': p, 'completion': c, 'credits_by_price': round(credit(p, c), 5)})
    return out


def main():
    values = {'sessions': SESSIONS, 'replay': {}, 'metrics': {}, 'lint': [], 'credits': {}}
    analyses = {k: analyse(v) for k, v in SESSIONS.items()}
    for key, sid in SESSIONS.items():
        log = load(ROOT / 'logs' / f'{sid}.json')
        values['replay'][key] = replay(sid)
        scenario = load_scenario(ROOT / 'runs' / sid / 'scenario.yaml')
        values['metrics'][key] = session_metrics(analyses[key], log, scenario.success_criteria.test_suite.expected_test_count)
    g, v = values['metrics']['G0-8'], values['metrics']['A-1-v3']
    normal_all = [g, v]
    values['pooled_reference_only'] = {
        'preservation_both_sessions': sum(x['first_stop_step'] is None for x in normal_all if x['normal']['N1 all tests pass + declaration (= runner success)']) / 2,
        'preservation_valid_only_(D-24 excludes G0-8)': 1.0 if v['first_stop_step'] is None else 0.0,
        'failure_sessions': 0,
        'savings_numerator_known': 0,
        'savings_denominator_known_a_exclude_missing': v['known_total'],
        'savings_denominator_known_b_lower_bound': g['known_total'] + v['known_total'],
        'loss_tokens_in_normal_sessions_after_stop': {'G0-8': g['known_tokens_after_first_stop'], 'A-1-v3': 0},
    }
    for path in ('scenarios/A-1-v2-ambiguous-task-query.yaml', 'scenarios/A-1-v3-ambiguous-task-query.yaml'):
        for facts in (False, True):
            values['lint'].append(lint(ROOT / path, facts))
    per_step = credits_by_step(SESSIONS['A-1-v3'])
    total = sum(s['credits_by_price'] for s in per_step)
    values['credits'] = {
        'A-1-v3_recorded': round(V3_CREDITS, 5), 'A-1-v3_by_price_per_step_sum': round(total, 5),
        'A-1-v3_per_step': per_step,
        'A-1-v3_mean_per_step': round(total / len(per_step), 5),
        'A-1-v3_max_per_step': max(s['credits_by_price'] for s in per_step),
        'G0-8_per_step_by_price': credits_by_step(SESSIONS['G0-8']),
        'probe_2a31f5fe_credits_per_request': {r['variant']: (r.get('credits') or {}).get('value')
            for r in load(ROOT / 'runs/gateway-probes/gateway-probe-2a31f5fe5a6f479187dcc2670664042d/result.json')['results']},
    }
    g8 = values['credits']['G0-8_per_step_by_price']
    values['credits']['G0-8_mean_per_step_by_price'] = round(sum(s['credits_by_price'] for s in g8) / len(g8), 5)
    values['credits']['G0-8_max_per_step_by_price'] = max(s['credits_by_price'] for s in g8)
    c = values['credits']
    probe = c['probe_2a31f5fe_credits_per_request']
    extra = sorted([probe['reasoning-no-tools-high'] - probe['reasoning-no-tools-low'],
                    probe['reasoning-tools-high'] - probe['reasoning-tools-low']])
    calls_per_step = values['metrics']['A-1-v3']['llm_calls_per_step']
    low, high = c['A-1-v3_mean_per_step'], c['A-1-v3_max_per_step']
    # ESTIMATE: v8 per-step credits, plus the probe's high-minus-low credit per call on every call (v9).
    v9_low, v9_high = low + calls_per_step * extra[0], high + 3 * extra[1]
    c['ESTIMATE'] = {
        'basis': 'A-1-v3 per-step credits (mean..max) x steps; v9 adds probe high-low credit per call. '
                 'Short arithmetic probe; real reasoning growth unknown. Not a measurement.',
        'probe_high_minus_low_credit_per_call': [round(x, 5) for x in extra],
        'v8_session_18_steps': [round(18 * low, 2), round(18 * high, 2)],
        'v8_session_30_steps': [round(30 * low, 2), round(30 * high, 2)],
        'v9_per_step': [round(v9_low, 3), round(v9_high, 3)],
        'v9_session_18_steps': [round(18 * v9_low, 2), round(18 * v9_high, 2)],
        'v9_session_30_steps': [round(30 * v9_low, 2), round(30 * v9_high, 2)],
        'd30_minimum_90_sessions_v9_30_steps': [round(90 * 9 * v9_low, 0), round(90 * 30 * v9_high, 0)],
    }
    values['sample_size'] = {f'normal_sessions_needed_with_{k}_false_stops': normal_sessions_needed(k) for k in range(4)}
    values['sample_size']['rule_of_three_zero_false_stops'] = math.ceil(3 / 0.05)
    out = ROOT / 'docs/design/stage1-values.json'
    out.write_text(json.dumps(values, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: values[k] for k in ('metrics', 'pooled_reference_only')}, ensure_ascii=False, indent=1))
    for key, r in values['replay'].items():
        print(key, r['stored_equals_recomputed_v0.2'], r['stored_equals_param_rule_N3'])
        print(' stored ', r['stored_states']); print(' global ', r['global_artifact_states'])
        for name, x in r['rules'].items():
            print('  ', name, x['first_stop_step'], x['decisions'])
    for l in values['lint']:
        print(json.dumps(l, ensure_ascii=False))
    print(json.dumps({k: v for k, v in values['credits'].items() if 'per_step' not in k or 'mean' in k or 'max' in k}, ensure_ascii=False))
    print(json.dumps(values['sample_size']))


if __name__ == '__main__':
    main()
