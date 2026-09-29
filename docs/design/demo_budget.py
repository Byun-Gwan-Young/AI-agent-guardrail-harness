"""C-16 part 6: demo-track session count and credit range. ESTIMATE, from two measured sessions only.

Measured inputs: A-1-v3 (9 steps, success, 16.43025 credits) and A-1-v4 (30 steps, max_steps, 130.815 credits),
both user-recorded monthly_allocated.used differences, and the C-11 rate (credits = prompt x 150/1M +
completion x 600/1M), checked here against both sessions. T1 tasks (search results in context, different roles)
have no measurement; their cost is assumed to fall in the same per-session range, which is an assumption.
Output: docs/design/demo-budget.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_RATE, COMPLETION_RATE = 150e-6, 600e-6  # credits per token (C-11, D-27)
MEASURED = {'A-1-v3': ('A-1-v3-4a0087756b2641f4b8f9b025c0419f73', 16.43025),
            'A-1-v4': ('A-1-v4-e174aafe805b4f59bb62d7c95716b8b7', 130.815)}
OBSERVE_RUNS, BLOCK_RUNS = 5, 3  # DM-6, DM-7
PAIRS = ['DEMO-CS', 'DEMO-MR', 'DEMO-LR', 'DEMO-CT', 'DEMO-CL']  # normal + stall each
NATURAL = ['DEMO-CT-N']  # observe only, no block runs (C-16 part 6)


def credits(prompt, completion):
    return round(prompt * PROMPT_RATE + completion * COMPLETION_RATE, 6)


def session_tokens(session_id, through_step=None):
    log = json.loads((ROOT / 'logs' / (session_id + '.json')).read_text(encoding='utf-8'))
    steps = json.loads((ROOT / 'runs' / session_id / 'steps.json').read_text(encoding='utf-8'))
    last = None if through_step is None else max(t for s in steps if s['step_id'] <= through_step for t in s['llm_turns'])
    turns = [t for t in log['turns'] if last is None or t['turn'] <= last]
    missing = sum(t.get('prompt_tokens') is None or t.get('completion_tokens') is None for t in turns)
    return {'turns': len(turns), 'usage_missing_turns': missing,
            'prompt': sum(t.get('prompt_tokens') or 0 for t in turns),
            'completion': sum(t.get('completion_tokens') or 0 for t in turns)}


def first_stop_step(session_id):
    log = json.loads((ROOT / 'logs' / (session_id + '.json')).read_text(encoding='utf-8'))
    return next((o['step_id'] for o in log['observations']
                 if (o.get('criteria') or {}).get('decision') in ('deadlock', 'termination_failure')), None)


def main():
    checks = {}
    for label, (session_id, measured) in MEASURED.items():
        tokens = session_tokens(session_id)
        checks[label] = {**tokens, 'measured_credits': measured,
                         'rate_credits': credits(tokens['prompt'], tokens['completion'])}
    v4_id = MEASURED['A-1-v4'][0]
    stop = first_stop_step(v4_id)
    blocked = session_tokens(v4_id, through_step=stop)
    blocked_credits = credits(blocked['prompt'], blocked['completion'])
    normal, stall = MEASURED['A-1-v3'][1], MEASURED['A-1-v4'][1]
    evidence = json.loads((ROOT / 'reports/a-1-v4/c14-evidence.json').read_text(encoding='utf-8'))
    wall = {'A-1-v3': evidence['baseline']['wall_seconds'], 'A-1-v4': evidence['candidate']['wall_seconds']}

    counts = {'observe_normal': len(PAIRS) * OBSERVE_RUNS, 'observe_stall': len(PAIRS) * OBSERVE_RUNS,
              'observe_natural': len(NATURAL) * OBSERVE_RUNS, 'block_stall': len(PAIRS) * BLOCK_RUNS}
    counts['total'] = sum(counts.values())
    trial = len(PAIRS) * 2 + len(NATURAL)  # C-18: one PM trial run per scenario
    report = {
        'script': 'docs/design/demo_budget.py', 'status': 'ESTIMATE',
        'rate_check': checks,
        'blocked_session_reference': {'session': v4_id, 'first_stop_step': stop, **blocked,
                                      'credits': blocked_credits,
                                      'note': 'A-1-v4 consumption through its first STOP step, as if the next request were blocked'},
        'session_counts': counts, 'c18_trial_sessions': trial,
        'per_session_reference_credits': {'normal_like_A-1-v3': normal, 'stall_like_A-1-v4': stall,
                                          'blocked_like_A-1-v4_to_stop': blocked_credits},
        'estimate': {
            'mixed': round(counts['observe_normal'] * normal + (counts['observe_stall'] + counts['observe_natural']) * stall
                           + counts['block_stall'] * blocked_credits, 2),
            'envelope_all_like_A-1-v3': round(counts['total'] * normal, 2),
            'envelope_all_like_A-1-v4': round(counts['total'] * stall, 2),
            'c18_trial_envelope': [round(trial * normal, 2), round(trial * stall, 2)]},
        'wall_time': {'measured_seconds': wall, 'source': 'reports/a-1-v4/c14-evidence.json',
                      'sequential_hours_envelope': [round(counts['total'] * wall['A-1-v3'] / 3600, 2),
                                                    round(counts['total'] * wall['A-1-v4'] / 3600, 2)],
                      # S-12 starts at 3 concurrent sessions; plain division, ignores 429 and uneven lengths.
                      'parallel_3_hours_envelope': [round(counts['total'] * wall['A-1-v3'] / 3600 / 3, 2),
                                                    round(counts['total'] * wall['A-1-v4'] / 3600 / 3, 2)]},
        'limits': ['A-1-v3 ran on protocol v8 (reasoning high not on every call); a v10 normal session is likely larger, unmeasured',
                   'T1 tasks (CS/MR/LR) have no measured session; search results enlarge prompts, unmeasured',
                   'mixed assumes every normal-variant session looks like A-1-v3 and every stall/natural like A-1-v4',
                   'two sessions are points, not a population range']}
    out = ROOT / 'docs/design/demo-budget.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
