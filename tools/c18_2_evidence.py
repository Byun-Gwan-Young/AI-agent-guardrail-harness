"""C-18-2 part 0: the C-18-1 trial sessions read again offline (DM-60, DM-62). Read-only, no external call.

Writes reports/c18-1/trial-summary.json: tools/summarize_demo_session.py for each trial session folder, the reasoning
tokens that back demo-conditions.yaml reasoning_effort: high (DM-60), the 400 that rejected medium, and every failed
tool result with its role, tool, target path and that role's writable paths (the step 4 errors). Only tool names,
paths and the runner's error summaries are printed: no model text, no reasoning content, no tool arguments other
than the path.

`c18_2_evidence.py trial` (part 3) writes reports/c18-2/estimate-trial.json: the credits the C-18-2 trial plan is
expected to use, from those measured credits (an estimate).
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


# C-18-2 part 3: the C-18-1 trial sessions whose measured credits stand for a short normal run and a 30-step run.
NORMAL_REFERENCE = 'DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a'
FULL_REFERENCE = 'DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1'
# Scenarios that cannot end in success (no implementation passes their acceptance tests), so they run to max_steps.
CANNOT_SUCCEED = ('DEMO-CT-stall-v1', 'DEMO-CL-stall-v1')
TRIAL_PLAN = ROOT / 'batch_plans/demo-trial-c18-2.yaml'
DEFAULT_ESTIMATE = ROOT / 'reports/c18-2/estimate-trial.json'


def trial_estimate(summary_path=DEFAULT_OUTPUT, plan_path=TRIAL_PLAN):
    """Credits expected for the C-18-2 trial plan (an estimate): per session, from the measured credits of the C-18-1
    trial (glm-5.3-flash, high). A session that can succeed lies between the short normal run and the 30-step run;
    one that cannot succeed (and has no escalation on the artifact path) is taken as the 30-step run."""
    from tools import run_batch
    summaries = json.loads(Path(summary_path).read_text(encoding='utf-8'))['summaries']
    low = summaries[NORMAL_REFERENCE]['credits_measured']['value']
    full = summaries[FULL_REFERENCE]['credits_measured']['value']
    plan = run_batch.load_plan(plan_path)
    rows = [{'item': i.key, 'kind': '30-step (cannot succeed)' if i.scenario_id in CANNOT_SUCCEED else
             'between a short success and 30 steps',
             'low': full if i.scenario_id in CANNOT_SUCCEED else low, 'high': full} for i in plan['items']]
    return {'script': 'tools/c18_2_evidence.py trial', 'status': 'estimated', 'plan_id': plan['plan_id'],
            'plan_sha256': plan['plan_sha256'],
            'references': {'short_success': {'session_id': NORMAL_REFERENCE, 'credits_measured': low, 'steps': 6},
                           'thirty_steps': {'session_id': FULL_REFERENCE, 'credits_measured': full, 'steps': 30}},
            'sessions': rows, 'total': {'low': round(sum(r['low'] for r in rows), 5),
                                        'high': round(sum(r['high'] for r in rows), 5)},
            'limits': ['one measured session per reference (CL, T3); CT and CT-N have another task and SPEC/approval '
                       'turns, so their length and tokens differ',
                       'a session that stops early on runner_error costs less than the low value']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('evidence', 'trial'), default='evidence')
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    if args.action == 'trial':
        result = trial_estimate()
        output = args.output or DEFAULT_ESTIMATE
        output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    args.output = args.output or DEFAULT_OUTPUT
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
