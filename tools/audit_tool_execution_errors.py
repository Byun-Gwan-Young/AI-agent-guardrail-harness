"""G0-6 offline audit: which steps of a proxy log executed a tool that returned is_error.

Read-only. A tool call belongs to a step when its id appears in a response of that step's turns.
Its is_error flag is known only where a later request of the same step carried the framework's
FunctionExecutionResultMessage (final-call observed_records). Plain role=tool messages carry no
flag, and calls whose result never reached a logged request stay unmeasured. Nothing is inferred.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LOG = 'logs/A-1-82c393c248a34286b318f344f2e181e4.json'
SUMMARY_CHARS = 300  # Same truncation as the runner's step record.


def flagged_results(request_body):
    """FunctionExecutionResult entries serialized inside the final-call observed_records."""
    found = {}
    for message in (request_body or {}).get('messages', []):
        try:
            data = json.loads(message.get('content')) if isinstance(message.get('content'), str) else None
        except ValueError:
            continue
        for record in (data or {}).get('observed_records', []) if isinstance(data, dict) else []:
            if isinstance(record, dict) and record.get('type') == 'FunctionExecutionResultMessage':
                for result in record.get('content', []):
                    found[result['call_id']] = result
    return found


def plain_results(request_body):
    return {m['tool_call_id']: m for m in (request_body or {}).get('messages', [])
            if m.get('role') == 'tool' and m.get('tool_call_id')}


def audit(log):
    turns = {t['turn']: t for t in log['turns']}
    steps = []
    for observation in log['observations']:
        step_turns = observation['llm_turns']
        calls = []
        for position, turn in enumerate(step_turns, 1):
            for choice in (turns.get(turn, {}).get('response_body') or {}).get('choices', []):
                for call in (choice.get('message') or {}).get('tool_calls') or []:
                    calls.append((position, call))
        flagged, plain = {}, {}
        for turn in step_turns:
            body = turns.get(turn, {}).get('request_body')
            flagged.update(flagged_results(body)); plain.update(plain_results(body))
        executions, unmeasured = [], []
        for position, call in calls:
            name = call['function']['name']
            if call['id'] in flagged:
                result = flagged[call['id']]
                executions.append({'llm_call_in_step': position, 'tool': name, 'call_id': call['id'],
                    'is_error': bool(result['is_error']),
                    'error_summary': str(result['content'])[:SUMMARY_CHARS] if result['is_error'] else None})
            else:
                unmeasured.append({'llm_call_in_step': position, 'tool': name, 'call_id': call['id'],
                    'is_error': None, 'status': 'unmeasured',
                    'reason': 'result sent without is_error flag' if call['id'] in plain
                              else 'result not present in any logged request of this step'})
        steps.append({'step_id': observation['step_id'], 'llm_turns': step_turns,
                      'tool_executions': executions, 'unmeasured_tool_calls': unmeasured,
                      'would_fail_with_tool_execution_error': any(e['is_error'] for e in executions)})
    return {'input': LOG, 'rule': 'G0-6: any executed tool result with is_error fails the recorded step',
            'steps': steps,
            'summary': {'steps_with_tool_execution_error': [s['step_id'] for s in steps
                                                            if s['would_fail_with_tool_execution_error']],
                        'steps_with_unmeasured_tool_results': [s['step_id'] for s in steps
                                                               if s['unmeasured_tool_calls']]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(json.loads((ROOT / LOG).read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    for step in report['steps']:
        if step['tool_executions'] or step['unmeasured_tool_calls']:
            print(json.dumps({'step_id': step['step_id'],
                'executions': [(e['tool'], e['is_error'], e['error_summary']) for e in step['tool_executions']],
                'unmeasured': [(e['tool'], e['reason']) for e in step['unmeasured_tool_calls']]}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
