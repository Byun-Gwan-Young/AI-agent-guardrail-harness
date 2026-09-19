"""Offline check of one session log: were the call budget and writable files stated to the model?

Read-only (C-9 part 4). For every role it reports whether the system message actually sent
contained the v8 harness facts, and the sentence v8 would have added. For every non-final call
it shows the per-call budget fact v8 would have attached. The session is not re-judged.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.step_execution import call_budget, harness_facts
from scenario_schema import load_scenario

FACT_MARKERS = {'writable_files': 'Files this role can write:', 'call_limit': 'model calls for this role',
                'per_call_budget': 'call_budget', 'per_call_budget_text': 'call(s) remain after this one'}


def check(session_id):
    log = json.loads((ROOT / 'logs' / f'{session_id}.json').read_text(encoding='utf-8'))
    steps = json.loads((ROOT / 'runs' / session_id / 'steps.json').read_text(encoding='utf-8'))
    scenario = load_scenario(ROOT / 'runs' / session_id / 'scenario.yaml')
    limit = scenario.termination.max_llm_calls_per_step
    agents = {a.id: a for a in scenario.agents}
    turns = {t['turn']: t for t in log['turns']}
    roles, calls = {}, []
    for step in steps:
        for position, turn in enumerate(step['llm_turns'], 1):
            body = turns[turn]['request_body']
            system = body['messages'][0]['content']
            sent = json.dumps(body['messages'], ensure_ascii=False)
            final = 'response_format' in body
            roles.setdefault(step['agent'], {
                'system_message_has': {k: v in system for k, v in FACT_MARKERS.items()
                                       if k in ('writable_files', 'call_limit')},
                'writable_paths_in_scenario': agents[step['agent']].writable_paths,
                'v8_would_add_to_system_message': harness_facts(agents[step['agent']].writable_paths, limit)})
            calls.append({'step_id': step['step_id'], 'agent': step['agent'], 'turn': turn, 'call_in_step': position,
                          'final_call': final,
                          'request_has_budget_fact': any(v in sent for k, v in FACT_MARKERS.items()
                                                         if k.startswith('per_call')),
                          'v8_would_attach': None if final else call_budget(position, limit)})
    return {'session_id': session_id, 'runner_protocol': json.loads(
                (ROOT / 'runs' / session_id / 'conditions.json').read_text(encoding='utf-8')).get('runner_protocol'),
            'max_llm_calls_per_step': limit, 'roles': roles, 'calls': calls,
            'summary': {'roles_missing_writable_fact': sorted(r for r, v in roles.items()
                                                             if not v['system_message_has']['writable_files']),
                        'roles_missing_call_limit_fact': sorted(r for r, v in roles.items()
                                                               if not v['system_message_has']['call_limit']),
                        'non_final_calls': sum(not c['final_call'] for c in calls),
                        'non_final_calls_with_budget_fact': sum(not c['final_call'] and c['request_has_budget_fact']
                                                                for c in calls)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = check(args.session_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('runner_protocol', 'max_llm_calls_per_step', 'summary')}, ensure_ascii=False))
    for role, value in report['roles'].items():
        print(role, json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
