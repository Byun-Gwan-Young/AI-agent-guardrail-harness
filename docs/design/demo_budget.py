"""C-16 part 6: demo-track session count and credit range. ESTIMATE, from two measured sessions only.

Measured inputs: A-1-v3 (9 steps, success, 16.43025 credits) and A-1-v4 (30 steps, max_steps, 130.815 credits),
both user-recorded monthly_allocated.used differences, and the C-11 rate (credits = prompt x 150/1M +
completion x 600/1M), checked here against both sessions. T1 tasks (search results in context, different roles)
have no measurement; their cost is assumed to fall in the same per-session range, which is an assumption.
Output: docs/design/demo-budget.json.

C-17-8 (DM-57): --prompt-rate / --completion-rate (credits per 1M tokens) price the same measured token counts for
another model, and --output writes elsewhere (the C-16 file stays the gpt-oss record). The per-session references are
the token counts priced at the given rates; at the default rates they equal the measured credits (rate_check).
The token counts are gpt-oss sessions: another model's output length differs (DM-57: qwen wrote 5,239 tokens where
glm wrote 204), so a repriced estimate is an assumption, not a measurement. The monthly allocation check and the
observe-repeat options (DM-6) are added to the report.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_RATE, COMPLETION_RATE = 150e-6, 600e-6  # credits per token (C-11, D-27), the gpt-oss default
MONTHLY_ALLOCATION = 5000  # gateway credits per month (D-27)
MEASURED = {'A-1-v3': ('A-1-v3-4a0087756b2641f4b8f9b025c0419f73', 16.43025),
            'A-1-v4': ('A-1-v4-e174aafe805b4f59bb62d7c95716b8b7', 130.815)}
OBSERVE_RUNS, BLOCK_RUNS = 5, 3  # DM-6, DM-7
PAIRS = ['DEMO-CS', 'DEMO-MR', 'DEMO-LR', 'DEMO-CT', 'DEMO-CL']  # normal + stall each
NATURAL = ['DEMO-CT-N']  # observe only, no block runs (C-16 part 6)


def credits(prompt, completion, rates=(PROMPT_RATE, COMPLETION_RATE)):
    return round(prompt * rates[0] + completion * rates[1], 6)


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


def mixed_estimate(counts, normal, stall, blocked):
    return round(counts['observe_normal'] * normal + (counts['observe_stall'] + counts['observe_natural']) * stall
                 + counts['block_stall'] * blocked, 2)


def session_counts(observe_runs):
    counts = {'observe_normal': len(PAIRS) * observe_runs, 'observe_stall': len(PAIRS) * observe_runs,
              'observe_natural': len(NATURAL) * observe_runs, 'block_stall': len(PAIRS) * BLOCK_RUNS}
    counts['total'] = sum(counts.values())
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt-rate', type=float, default=PROMPT_RATE * 1e6, help='credits per 1M prompt tokens')
    parser.add_argument('--completion-rate', type=float, default=COMPLETION_RATE * 1e6,
                        help='credits per 1M completion tokens')
    parser.add_argument('--model-label', default='accounts/fireworks/models/gpt-oss-120b',
                        help='the model the rates are for (recorded only)')
    parser.add_argument('--used-this-month', type=float, default=None,
                        help='monthly_allocated.used read before the demo (recorded with the allocation check)')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/design/demo-budget.json')
    args = parser.parse_args(argv)
    rates = (args.prompt_rate / 1e6, args.completion_rate / 1e6)
    checks = {}
    for label, (session_id, measured) in MEASURED.items():
        tokens = session_tokens(session_id)
        checks[label] = {**tokens, 'measured_credits': measured,
                         'rate_credits': credits(tokens['prompt'], tokens['completion'], rates)}
    v4_id = MEASURED['A-1-v4'][0]
    stop = first_stop_step(v4_id)
    blocked = session_tokens(v4_id, through_step=stop)
    blocked_credits = credits(blocked['prompt'], blocked['completion'], rates)
    # The measured sessions priced at the given rates (equal to the measured credits at the default rates).
    normal, stall = checks['A-1-v3']['rate_credits'], checks['A-1-v4']['rate_credits']
    evidence = json.loads((ROOT / 'reports/a-1-v4/c14-evidence.json').read_text(encoding='utf-8'))
    wall = {'A-1-v3': evidence['baseline']['wall_seconds'], 'A-1-v4': evidence['candidate']['wall_seconds']}

    counts = session_counts(OBSERVE_RUNS)
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
            'mixed': mixed_estimate(counts, normal, stall, blocked_credits),
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
    trial_envelope = report['estimate']['c18_trial_envelope']
    report['rates'] = {'model': args.model_label, 'credits_per_1m_prompt': args.prompt_rate,
                       'credits_per_1m_completion': args.completion_rate,
                       'measured_rates': (args.prompt_rate, args.completion_rate) == (PROMPT_RATE * 1e6,
                                                                                      COMPLETION_RATE * 1e6)}
    report['allocation_check'] = {
        'monthly_allocation': MONTHLY_ALLOCATION, 'used_this_month_given': args.used_this_month,
        'mixed_plus_c18_trials': [round(report['estimate']['mixed'] + t, 2) for t in trial_envelope],
        'exceeds_allocation': [round(report['estimate']['mixed'] + t + (args.used_this_month or 0), 2) > MONTHLY_ALLOCATION
                               for t in trial_envelope],
        # DM-6: observe repeats per scenario; block runs (DM-7) and C-18 trials kept.
        'observe_runs_options': {str(r): {'sessions': session_counts(r)['total'],
                                          'mixed': mixed_estimate(session_counts(r), normal, stall, blocked_credits),
                                          'mixed_plus_c18_trials': [round(mixed_estimate(session_counts(r), normal, stall,
                                                                                         blocked_credits) + t, 2)
                                                                    for t in trial_envelope]}
                                 for r in (5, 4, 3)}}
    if not report['rates']['measured_rates']:
        report['limits'] = report['limits'] + [
            'priced at ' + args.model_label + ' rates from gpt-oss token counts: output length per model differs '
            '(DM-57), reasoning effort medium is not reflected, cached-token discounts are not subtracted']
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
