"""A-1-v4 (protocol v9) credit ESTIMATE (C-13 part 3). Read-only; every output is an estimate.

Inputs, all committed:
- A-1-v3 session (v8, low on final calls only): per-call credits from tokens x price, calls per step
- discriminator probe 2a31f5fe: measured credits of the same request at reasoning_effort low vs high
Assumption: v9 adds, on every call, the probe's high-minus-low credit difference (range of the two
probe pairs). The probe is a short arithmetic question, so real growth on the task is unknown.
Writes docs/design/budget-v9.json. Confirmation comes only from the A-1-v4 verification run.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V3 = 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73'
PROBE = ROOT / 'runs/gateway-probes/gateway-probe-2a31f5fe5a6f479187dcc2670664042d/result.json'
PRICE = {'prompt': 0.15, 'completion': 0.60}   # USD per 1M tokens; 1 credit = $0.001 (C-11 exact match)
MAX_CALLS_PER_STEP = 3
SCENARIOS = 11          # S-14
CAP_PER_SCENARIO = 20   # S-11
VERIFY_PER_SCENARIO = 2  # guideline 6 : 0.0 x 2


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def credit(prompt, completion):
    return (prompt * PRICE['prompt'] + completion * PRICE['completion']) / 1e6 * 1000


def main():
    log = load(ROOT / 'logs' / f'{V3}.json')
    steps = load(ROOT / 'runs' / V3 / 'steps.json')
    per_call = [credit(t['prompt_tokens'], t['completion_tokens']) for t in log['turns']]
    calls_per_step = len(log['turns']) / len(steps)
    probe = {r['variant']: r['credits']['value'] for r in load(PROBE)['results']}
    delta = sorted([probe['reasoning-no-tools-high'] - probe['reasoning-no-tools-low'],
                    probe['reasoning-tools-high'] - probe['reasoning-tools-low']])
    low_call = sum(per_call) / len(per_call) + delta[0]     # mean v3 call + smaller probe difference
    high_call = max(per_call) + delta[1]                     # largest v3 call + larger probe difference

    def session(n_steps):
        calls = (round(n_steps * calls_per_step), n_steps * MAX_CALLS_PER_STEP)
        return {'steps': n_steps, 'calls': list(calls),
                'credits': [round(calls[0] * low_call, 1), round(calls[1] * high_call, 1)]}

    sessions = {'like_A-1-v3_9_steps': {'steps': 9, 'calls': [len(log['turns'])] * 2,
                                        'credits': [round(len(log['turns']) * low_call, 1),
                                                    round(len(log['turns']) * high_call, 1)]},
                '18_steps': session(18), '30_steps_max': session(30)}
    s9, s30 = sessions['like_A-1-v3_9_steps']['credits'], sessions['30_steps_max']['credits']

    def dataset(normal, failure):
        # Lower: normal sessions end like A-1-v3 (9 steps, low), failures run to 30 steps (low).
        # Upper: every session runs to 30 steps at the high per-call value.
        return [round(normal * s9[0] + failure * s30[0]), round((normal + failure) * s30[1])]

    pilot_sessions = 1 + 3 * VERIFY_PER_SCENARIO   # A-1-v4 re-verification + A-1-v4, B-6, C-9 x 2 (S-15)
    report = {
        'ESTIMATE': True,
        'basis': __doc__.strip().splitlines()[0],
        'inputs': {'A-1-v3_calls': len(log['turns']), 'A-1-v3_steps': len(steps),
                   'A-1-v3_calls_per_step': round(calls_per_step, 3),
                   'A-1-v3_credit_per_call_mean': round(sum(per_call) / len(per_call), 5),
                   'A-1-v3_credit_per_call_max': round(max(per_call), 5),
                   'A-1-v3_credits_by_price_total': round(sum(per_call), 5),
                   'probe_credits': probe, 'probe_high_minus_low_per_call': [round(d, 5) for d in delta]},
        'v9_credit_per_call': [round(low_call, 5), round(high_call, 5)],
        'A-1-v4_session': sessions,
        'pilot': {'sessions': pilot_sessions,
                  'note': 'B-6 and C-9 have no measurement; the A-1-v4 per-session range is used for them',
                  'credits': [round(pilot_sessions * s9[0]), round(pilot_sessions * s30[1])]},
        'main_collection': {
            f'normal_{n}_failure_30': {'sessions': n + 30, 'credits': dataset(n, 30)} for n in (60, 93, 124)},
        'main_collection_cap': {'sessions': SCENARIOS * CAP_PER_SCENARIO,
                                'credits_upper': round(SCENARIOS * CAP_PER_SCENARIO * s30[1])},
        'verify_all_scenarios': {'sessions': SCENARIOS * VERIFY_PER_SCENARIO,
                                 'credits': [round(SCENARIOS * VERIFY_PER_SCENARIO * s9[0]),
                                             round(SCENARIOS * VERIFY_PER_SCENARIO * s30[1])]},
        'excluded': 'D-32 cross-check model: price and conditions unknown until its probe',
    }
    (ROOT / 'docs/design/budget-v9.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n',
                                                     encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
