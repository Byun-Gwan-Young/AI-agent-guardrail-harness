"""C-17-7 part 3 evidence, from files only (no network, no model reasoning text is read or written).

1. Gateway probe 2026-09-29 (gateway-probe-9d2b2053…): per model and request, HTTP status and the error message read
   with probe_gateway.error_text (the probe itself kept null for the gateway's {"detail": ...} bodies), and which
   request fields were sent. Records why the gpt-6 tool requests got HTTP 400; nothing is re-sent.
2. D-11 secret scan of that probe folder before it is committed (patterns, plus the key's value when set here).
3. Several tool calls in one model response: per proxy log, 200 responses by tool-call count, requests that set
   parallel_tool_calls, and per runner step record, model calls that executed more than one tool.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_session import secret_scan
from tools.probe_gateway import error_text

PROBE = ROOT / 'runs/gateway-probes/gateway-probe-9d2b2053fa2d41e982e3352bf1adacc7'
SESSIONS = ('A-1-v2-b51f67df2fb9402ba15fccb35c3db53e', 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73',
            'A-1-v4-e174aafe805b4f59bb62d7c95716b8b7')
REQUEST_FIELDS = ('tools', 'tool_choice', 'reasoning_effort', 'response_format', 'parallel_tool_calls')
# The upstream message is embedded as text in the gateway's message; only its 'param' value is pulled out.
PARAM = re.compile(r"'param':\s*'([^']*)'")


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def probe_requests(folder):
    result = load(folder / 'result.json')
    rows = []
    for item in result['results']:
        name = ''.join(c if c.isalnum() or c in '.-' else '_' for c in item['model']) + '--' + item['variant']
        request = load(folder / (name + '.request.json'))
        response_path = folder / (name + '.response.json')
        response = load(response_path) if response_path.is_file() else None
        message = error_text(response) if isinstance(response, dict) else None
        param = PARAM.search(message or '')
        rows.append({'model': item['model'], 'variant': item['variant'], 'http_status': item.get('http_status'),
                     'error_message_in_result': item.get('error_message'),
                     'error_message_from_response': message,
                     'error_param': param.group(1) if param else None,
                     'sent_fields': {k: (request[k] if k in ('reasoning_effort', 'tool_choice', 'parallel_tool_calls')
                                         else len(request[k])) for k in REQUEST_FIELDS if k in request},
                     'tool_calls_returned': len(((response or {}).get('choices') or [{}])[0].get('message', {})
                                                .get('tool_calls') or []) if item.get('http_status') == 200 else None})
    return {'folder': folder.relative_to(ROOT).as_posix(), 'created_at': result['created_at'],
            'scenario_id': result['scenario_id'], 'models': result['models'], 'requests': rows,
            'http_400': [r for r in rows if r['http_status'] == 400],
            'retried': False, 'retry_note': 'C-17-7: the 400 requests are recorded, not re-sent'}


def log_tool_calls(session_id):
    log = load(ROOT / 'logs' / (session_id + '.json'))
    counts, parallel = Counter(), Counter()
    for turn in log['turns']:
        body = turn.get('request_body') or {}
        if 'parallel_tool_calls' in body:
            parallel[json.dumps(body['parallel_tool_calls'])] += 1
        if turn.get('status_code') != 200:
            continue
        message = ((turn.get('response_body') or {}).get('choices') or [{}])[0].get('message') or {}
        counts[len(message.get('tool_calls') or [])] += 1
    steps = load(ROOT / 'runs' / session_id / 'steps.json')
    per_call = Counter((s['step_id'], e['llm_call_in_step']) for s in steps for e in s.get('tool_executions') or [])
    return {'session_id': session_id, 'turns': len(log['turns']),
            'responses_200_by_tool_call_count': {str(k): counts[k] for k in sorted(counts)},
            'responses_with_more_than_one_tool_call': sum(v for k, v in counts.items() if k > 1),
            'requests_setting_parallel_tool_calls': dict(parallel),
            'runner_calls_with_more_than_one_execution': sorted([list(k) for k, v in per_call.items() if v > 1])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = {'probe_9d2b2053': probe_requests(PROBE),
                'probe_9d2b2053_secret_scan': secret_scan([PROBE], {'KMU_API_KEY'}),
                'multi_tool_calls': [log_tool_calls(s) for s in SESSIONS]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'http_400': [(r['model'], r['variant'], r['error_param']) for r in
                                   evidence['probe_9d2b2053']['http_400']],
                      'secret_scan_clean': evidence['probe_9d2b2053_secret_scan']['clean'],
                      'multi_tool_calls': {m['session_id']: m['responses_with_more_than_one_tool_call']
                                           for m in evidence['multi_tool_calls']}}, ensure_ascii=False, indent=1))
    return 0 if evidence['probe_9d2b2053_secret_scan']['clean'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
