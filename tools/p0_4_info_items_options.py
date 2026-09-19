"""P0-4 offline analysis: replay saved P0-2 observations of the A-1 log under info_items options.

Read-only. Options: current, A (contract requires a list), B (calculation reads null as []),
C (new_info_ratio not selected; D-22). progress-v2 / deadlock-v0.2 code is used unchanged; options
only transform the input observations. Output is a script result, not a run reproduction.
"""
import argparse
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from progress_signal import calculate_progress
from deadlock_policy import evaluate_criteria

LOG = 'logs/A-1-82c393c248a34286b318f344f2e181e4.json'
REPLAY = 'reports/p0-2/replay.json'
OPTIONS = ('current', 'A_contract_requires_list', 'B_calc_null_as_empty', 'C_drop_new_info_ratio_metric')


def analyse(log, replay):
    pin, rows = replay['pin'], replay['rows']

    def kind(v):
        return 'null' if v is None else 'empty' if v == [] else 'nonempty'

    # 1. info_items in valid final outputs, by role
    dist = {}
    for name, items in (
        ('p0_2_valid_final_receipts', [(r['agent_id'], r['final_receipt']['value']['info_items'])
                                       for r in rows if r['final_receipt']['status'] == 'valid']),
        ('original_stored_structured', [(r['agent_id'], o['conversation']['info_items'])
            for r, o in zip(rows, log['observations'])
            if (o.get('conversation') or {}).get('source_kind') == 'structured'
            and 'output' not in (o['conversation'].get('reasons') or {})])):
        c = defaultdict(Counter)
        for role, v in items:
            c[role][kind(v)] += 1
        dist[name] = {role: dict(c[role]) for role in sorted(c)} | {'total_steps': len(items)}

    def discard(obs):
        conv = obs['conversation']
        conv.update(proposal_values=None, open_issue_ids=None, info_items=None,
                    reasons={'output': 'invalid or missing structured output'})

    def option(name):
        obs = [copy.deepcopy(r['observation']) for r in rows]
        violations = []
        for r, o in zip(rows, obs):
            o.pop('progress', None); o.pop('criteria', None)
            valid = r['final_receipt']['status'] == 'valid'
            if name == 'A_contract_requires_list' and valid and r['final_receipt']['value']['info_items'] is None:
                violations.append(r['step_id']); discard(o)
            if name == 'B_calc_null_as_empty' and valid and o['conversation']['info_items'] is None:
                o['conversation']['info_items'] = []
            if name == 'C_drop_new_info_ratio_metric':
                o['progress_metric'] = {**o['progress_metric'],
                    'conversation': [m for m in o['progress_metric']['conversation'] if m != 'new_info_ratio']}
        history, steps = [], []
        for o in obs:
            o['progress'] = calculate_progress(history, o, version='progress-v2')
            history.append(o)
            crit = evaluate_criteria(history, pin)
            p = o['progress']
            missing = sorted(k for k, v in p.get('metrics', {}).items() if v['status'] == 'unmeasured')
            steps.append({'step': o['step_id'], 'agent': o['agent_id'], 'state': p['state'],
                          'missing': missing, 'decision': crit['decision']})
        # Existing strict-stop rule: two consecutive strict-failed steps (type errors are format errors).
        stop, streak = None, 0
        for r in rows:
            failed = r['step_id'] in violations or r['final_receipt']['status'] != 'valid'
            streak = streak + 1 if failed else 0
            if streak >= 2 and stop is None:
                stop = r['step_id']
        compared = [s for s in steps if s['state'] != 'baseline']
        return {'option': name, 'contract_violation_steps': violations,
                'first_strict_stop_step_under_existing_rule': stop,
                'new_info_ratio_measured_steps': [s['step'] for s in steps if 'conversation.new_info_ratio' not in s['missing']
                                                  and s['state'] != 'baseline'] if name != 'C_drop_new_info_ratio_metric' else 'not selected',
                'states': dict(Counter(s['state'] for s in steps)),
                'unmeasured_due_to_missing_metric': [s['step'] for s in compared if s['state'] == 'unmeasured' and s['missing']],
                'unmeasured_where_only_info_missing': [s['step'] for s in compared if s['state'] == 'unmeasured'
                                                      and s['missing'] == ['conversation.new_info_ratio']],
                'progress_despite_missing_metric_G0_5': [s['step'] for s in compared if s['state'] == 'progress' and s['missing']],
                'stagnant_or_oscillating_steps': [s['step'] for s in compared if s['state'] in ('stagnant', 'oscillating')],
                'criteria_decisions': [s['decision'] for s in steps],
                'per_step': [{k: s[k] for k in ('step', 'agent', 'state', 'missing')} for s in steps]}

    options = [option(n) for n in OPTIONS]
    same = [s['state'] for s in options[0]['per_step']] == [r['p0_2']['progress']['state'] for r in rows]
    return {'inputs': {'log': LOG, 'replay': REPLAY}, 'info_items_distribution': dist,
            'current_matches_saved_p0_2_states': same, 'options': options}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyse(json.loads((ROOT / LOG).read_text(encoding='utf-8')),
                     json.loads((ROOT / REPLAY).read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for o in report['options']:
        print(json.dumps({k: v for k, v in o.items() if k not in ('per_step', 'criteria_decisions')}, ensure_ascii=False))
    return 0 if report['current_matches_saved_p0_2_states'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
