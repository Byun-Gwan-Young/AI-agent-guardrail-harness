"""C-18-2 part 0: the C-18-1 trial sessions read again offline (DM-60, DM-62). Read-only, no external call.

Writes reports/c18-1/trial-summary.json: tools/summarize_demo_session.py for each trial session folder, the reasoning
tokens that back demo-conditions.yaml reasoning_effort: high (DM-60), the 400 that rejected medium, and every failed
tool result with its role, tool, target path and that role's writable paths (the step 4 errors). Only tool names,
paths and the runner's error summaries are printed: no model text, no reasoning content, no tool arguments other
than the path.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import summarize_demo_session  # noqa: E402

TRIAL_SESSIONS = ('DEMO-CL-normal-v1-c3a4c019c1ec48ca86b22d45340aea7b',
                  'DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a',
                  'DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1')
DEFAULT_OUTPUT = ROOT / 'reports/c18-1/trial-summary.json'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def tool_call_paths(turns):
    """call id -> path argument of every tool call in the 200 responses (the path only)."""
    paths = {}
    for t in turns:
        if t.get('status_code') != 200:
            continue
        for choice in ((t.get('response_body') or {}).get('choices') or [])[:1]:
            for call in (choice.get('message') or {}).get('tool_calls') or []:
                try:
                    arguments = json.loads(call['function']['arguments'])
                except (KeyError, TypeError, ValueError):
                    arguments = {}
                paths[call.get('id')] = arguments.get('path') if isinstance(arguments, dict) else None
    return paths


def failed_tool_results(folder):
    """Every is_error tool result: step, role, tool, target path, the role's writable paths, the runner's summary."""
    steps, log = load(folder / 'steps.json'), load(folder / 'session.json')
    writable = {a['id']: a.get('writable_paths') or [] for a in load(folder / 'conditions.json')['scenario']['agents']}
    paths = tool_call_paths(log['turns'])
    rows = []
    for s in steps:
        for e in s.get('tool_executions') or []:
            if not e.get('is_error'):
                continue
            path = paths.get(e.get('call_id'))
            rows.append({'step_id': s['step_id'], 'role': s.get('agent'), 'tool': e.get('tool'), 'path': path,
                         'role_writable_paths': writable.get(s.get('agent')),
                         'outside_writable_paths': None if path is None else path not in writable.get(s.get('agent'), []),
                         'error_summary': e.get('error_summary'),
                         'approval_refused': bool(e.get('approval_refused'))})
    return rows


def evidence(runs_root=ROOT / 'runs/demo', sessions=TRIAL_SESSIONS):
    summaries, failures = {}, {}
    for session_id in sessions:
        folder = Path(runs_root) / session_id
        summaries[session_id] = summarize_demo_session.summarize(folder)
        failures[session_id] = failed_tool_results(folder)
    effort = [{'session_id': k, 'requested': v['reasoning_effort'], 'termination_reason': v['termination_reason'],
               'turns': v['tokens']['turns'], 'completion_tokens': v['tokens']['completion'],
               'reasoning_tokens': v['tokens']['reasoning'], 'error': v['error']}
              for k, v in summaries.items()]
    return {
        'script': 'tools/c18_2_evidence.py',
        'sessions': list(sessions),
        # DM-60: medium was refused at step 1 (400); the two sessions with high carried reasoning tokens.
        'reasoning_effort_evidence': {
            'for': 'demo-conditions.yaml reasoning_effort: high (DM-60)',
            'sessions': effort,
            'high_sessions_with_reasoning_tokens': [e['session_id'] for e in effort
                                                    if e['requested'] == 'high' and e['reasoning_tokens']],
            'medium_rejected': [e['session_id'] for e in effort
                                if e['requested'] == 'medium' and e['error'] and '400' in e['error']]},
        'failed_tool_results': failures,
        'summaries': summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.relative_to(ROOT)) if args.output.is_absolute() else str(args.output),
                      'reasoning_effort_evidence': result['reasoning_effort_evidence'],
                      'failed_tool_results': result['failed_tool_results'],
                      'key_scan_clean': {k: v['key_scan']['clean'] for k, v in result['summaries'].items()}},
                     ensure_ascii=False, indent=1))
    return 0 if all(v['key_scan']['clean'] for v in result['summaries'].values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
