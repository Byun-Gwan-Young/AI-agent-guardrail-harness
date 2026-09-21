"""metrics-v1 computability check (C-13 part 0). Read-only.

Applies the metrics-v1 formulas (docs/design/metrics-v1.md) to committed sessions and writes
docs/design/metrics-v1-check.json. The purpose is only to show that every formula can be computed
from log fields. G0-8 and A-1-v3 are not dataset sessions (other condition groups), and both are
normal sessions, so detection rate, primary savings and detection delay have no sample.
"""
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from analyze_session import analyse

METRICS_VERSION = 'metrics-v1'
STOP = ('deadlock', 'termination_failure')
# Validity as decided by the PM (guideline D-24, D-28). Manifests keep 'unclassified' until C-14.
VALIDITY = {'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e': ('unclassified', 'D-24'),
            'A-1-v3-4a0087756b2641f4b8f9b025c0419f73': ('valid', 'D-28')}
TARGETS = {'judgement_overhead_p99_ms': ('<=', 30.0), 'preservation': ('>=', 0.95),
           'savings_failure_basis': ('>=', 0.20), 'detection_rate': ('>=', 0.80)}


def ratio(numerator, denominator):
    if denominator == 0:
        return {'value': None, 'status': 'no_sample', 'numerator': numerator, 'denominator': 0}
    return {'value': numerator / denominator, 'status': 'measured', 'numerator': numerator, 'denominator': denominator}


def binomial_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def upper_bound(failures, n, confidence=0.95):
    """Exact one-sided upper confidence bound on a rate (Clopper-Pearson), by bisection."""
    if n == 0:
        return None
    if failures >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if binomial_cdf(failures, n, mid) > 1 - confidence else (lo, mid)
    return hi


def session_record(sid):
    a = analyse(sid)
    log = json.loads((ROOT / 'logs' / f'{sid}.json').read_text(encoding='utf-8'))
    rows = a['steps']
    turns = {t['turn']: t for t in log['turns']}
    stop = next((r['step_id'] for r in rows if r['criteria_decision'] in STOP), None)
    known = lambda ts: sum(t['tokens'] for t in ts if t.get('tokens') is not None)
    after = None
    if stop is not None:
        last = max(turns[n]['turn'] for n in rows[stop - 1]['llm_turns'])
        after = known(t for t in log['turns'] if t['turn'] > last)
    normal = a['termination']['reason'] == 'success'           # S-1 (N1)
    changes = [r['step_id'] for r in rows if r['tests_change_in_step'] or r['files_changed_in_step']]
    onset = None if normal else (max(changes) + 1 if changes else 1)   # S-4 (O1)
    roles = len({r['agent'] for r in rows})
    validity, basis = VALIDITY.get(sid, ('unclassified', None))
    return {
        'session_id': sid, 'validity': validity, 'validity_basis': basis,
        'termination_reason': a['termination']['reason'], 'normal': normal, 'failure': not normal,
        'first_stop_step': stop, 'steps': len(rows), 'roles': roles,
        'known_tokens': a['tokens']['known_total'], 'usage_missing_turns': a['tokens']['usage_missing_turns'],
        'known_tokens_after_first_stop': after,
        'onset_step': onset,
        'delay_steps': None if onset is None or stop is None else stop - onset,
        'unmeasured_steps': sum(r['criteria_decision'] == 'unmeasured' for r in rows),
        'needs_observation_review_steps': sum(bool(o['criteria'].get('needs_observation_review'))
                                              for o in log['observations']),
        'judgement_ns': [o.get('judgement_ns') for o in log['observations']],
    }


def metrics(records):
    included = [r for r in records if r['validity'] == 'valid']
    normal = [r for r in included if r['normal']]
    failure = [r for r in included if r['failure']]
    false_stops = [r for r in normal if r['first_stop_step'] is not None]
    detected = [r for r in failure if r['first_stop_step'] is not None]
    saved = sum(r['known_tokens_after_first_stop'] or 0 for r in detected)
    loss = sum(r['known_tokens_after_first_stop'] or 0 for r in false_stops)
    complete = [r for r in included if r['usage_missing_turns'] == 0]
    delays = [r['delay_steps'] for r in detected if r['delay_steps'] is not None]
    timings = [ns for r in included for ns in r['judgement_ns'] if ns is not None]
    steps = sum(r['steps'] for r in included)
    out = {
        'included_sessions': [r['session_id'] for r in included],
        'excluded_sessions': {r['session_id']: r['validity'] for r in records if r['validity'] != 'valid'},
        'normal_sessions': len(normal), 'failure_sessions': len(failure),
        # (2) preservation, S-1/S-2
        'preservation': {**ratio(len(normal) - len(false_stops), len(normal)),
                         'false_stop_rate_upper_95': upper_bound(len(false_stops), len(normal))},
        # (4) detection rate, S-17
        'detection_rate': ratio(len(detected), len(failure)),
        # (3) savings, S-18 primary and secondary, S-3 known tokens with missing turns reported
        'savings_failure_basis': ratio(saved, sum(r['known_tokens'] for r in failure)),
        'savings_all_basis': ratio(saved, sum(r['known_tokens'] for r in included)),
        'loss_tokens_normal_false_stops': loss,
        'usage_missing_turns_total': sum(r['usage_missing_turns'] for r in included),
        'sensitivity_excluding_usage_missing': {
            'savings_failure_basis': ratio(sum(r['known_tokens_after_first_stop'] or 0 for r in complete
                                               if r['failure'] and r['first_stop_step'] is not None),
                                           sum(r['known_tokens'] for r in complete if r['failure'])),
            'excluded_sessions': [r['session_id'] for r in included if r['usage_missing_turns']]},
        # detection delay, S-4/S-19 (no target)
        'detection_delay_steps_median': {'value': statistics.median(delays) if delays else None,
                                         'status': 'measured' if delays else 'no_sample', 'n': len(delays),
                                         'early_stops': sum(1 for r in detected if r['delay_steps'] is not None
                                                            and r['delay_steps'] < 0)},
        # (1) judgement overhead, S-5
        'judgement_overhead_ms': {'p50': None, 'p99': None, 'status': 'unmeasured',
                                  'reason': 'judgement_ns is not recorded yet (S-5, implemented in C-14)'}
                                 if not timings else
                                 {'p50': statistics.median(timings) / 1e6,
                                  'p99': sorted(timings)[max(0, math.ceil(0.99 * len(timings)) - 1)] / 1e6,
                                  'status': 'measured', 'n': len(timings)},
        # S-2 auxiliary, always reported
        'unmeasured_step_ratio': ratio(sum(r['unmeasured_steps'] for r in included), steps),
        'needs_observation_review_step_ratio': ratio(sum(r['needs_observation_review_steps'] for r in included), steps),
    }
    return out


def main():
    records = [session_record(sid) for sid in VALIDITY]
    report = {'metrics_version': METRICS_VERSION, 'targets_S17': TARGETS,
              'note': 'Computability check only. Not a dataset: both sessions belong to other condition groups.',
              'sessions': records,
              'metrics_valid_only': metrics(records),
              'reference_all_sessions_ignoring_validity': metrics([{**r, 'validity': 'valid'} for r in records])}
    out = ROOT / 'docs/design/metrics-v1-check.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('metrics_valid_only', 'reference_all_sessions_ignoring_validity')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
