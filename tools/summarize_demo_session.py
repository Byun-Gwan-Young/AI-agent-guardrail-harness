"""Short summary of one demo session folder for the PM to paste back (C-18-1 part 3). Offline, read-only.

Input: a runner folder runs/demo/<session id>/ (conditions.json, steps.json, summary.json and session.json, the runner's
copy of the proxy log). Prints JSON: how the session ended, the first STOP with its rule and explanation sentence,
tokens (input, cached input, output, reasoning), credits measured (/credits/ difference, experiments/gateway_usage.py)
and estimated (tokens x price, tools/gateway_prices.py), tool calls per model response, refused and failed tool
results, strict output failures, and the condition group with model and reasoning effort. No model text and no
reasoning content is printed; the scan for keys over the folder is reported (D-11 patterns, and the KMU_API_KEY and
TAVILY_API_KEY values when they are set where this runs).
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.dialogue_contract import VOCABULARY_VIOLATIONS_V3 as VOCABULARY_VIOLATIONS  # noqa: E402
from tools import gateway_prices  # noqa: E402
from tools.analyze_session import SECRET_PATTERNS, SEARCH_SECRET_PATTERNS, condition_group  # noqa: E402

STOP_DECISIONS = ('deadlock', 'termination_failure')
KEY_ENVS = ('KMU_API_KEY', 'TAVILY_API_KEY')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def first_stop(observations):
    for o in observations:
        criteria = o.get('criteria') or {}
        if criteria.get('decision') in STOP_DECISIONS:
            explanation = criteria.get('explanation') or {}
            return {'step_id': o['step_id'], 'criteria_version': criteria.get('criteria_version'),
                    'decision': criteria.get('decision'), 'reason': criteria.get('reason'),
                    'template_id': explanation.get('template_id'), 'text': explanation.get('text')}
    return None


def tool_calls_per_response(turns):
    """How many tool calls each 200 response carried: {count: responses}."""
    counts = Counter()
    for t in turns:
        if t.get('status_code') != 200:
            continue
        for choice in ((t.get('response_body') or {}).get('choices') or [])[:1]:
            counts[len((choice.get('message') or {}).get('tool_calls') or [])] += 1
    return {str(k): counts[k] for k in sorted(counts)}


def tool_results(steps):
    executions = [e for s in steps for e in s.get('tool_executions') or []]
    refused = [e for e in executions if e.get('approval_refused')]
    failed = [e for e in executions if e.get('is_error') and not e.get('approval_refused')]
    return {'executed': len(executions), 'refused_before_approval': len(refused), 'error_results': len(failed),
            'error_results_by_tool': dict(Counter(e.get('name') for e in failed)),
            'invalid_tool_calls': sum(len(s.get('tool_errors') or []) for s in steps)}


def strict_failures(steps):
    kinds = [s.get('strict_failure') for s in steps if s.get('strict_failure')]
    return {'format_failures': sum(k not in VOCABULARY_VIOLATIONS for k in kinds),
            'vocabulary_violations': sum(k in VOCABULARY_VIOLATIONS for k in kinds),
            'by_kind': dict(Counter(kinds)),
            'failed_steps': [{'step_id': s['step_id'], 'reasons': s.get('failure_reasons')} for s in steps
                             if s.get('step_status') == 'failed']}


def key_scan(folder):
    values = {env: os.environ[env] for env in KEY_ENVS if os.environ.get(env)}
    patterns = {**SECRET_PATTERNS, **SEARCH_SECRET_PATTERNS}
    hits = {}
    files = [p for p in sorted(folder.rglob('*')) if p.is_file()]
    for path in files:
        text = path.read_text(encoding='utf-8', errors='replace')
        found = [name for name, pattern in patterns.items() if pattern.search(text)]
        found += ['env:' + env for env, value in values.items() if value in text]
        if found:
            hits[path.relative_to(folder).as_posix()] = found
    return {'files_scanned': len(files), 'key_values_checked': sorted(values), 'hits': hits, 'clean': not hits}


def summarize(folder):
    folder = Path(folder).resolve()
    conditions, steps = load(folder / 'conditions.json'), load(folder / 'steps.json')
    summary, log = load(folder / 'summary.json'), load(folder / 'session.json')
    meta, turns = log['meta'], log['turns']
    termination = conditions['scenario']['termination']
    group = condition_group({'condition': {'max_steps': termination['max_steps'],
                                           'max_llm_calls_per_step': termination['max_llm_calls_per_step']}},
                            conditions, meta)
    passed = [s['acceptance']['summary']['passed'] for s in steps if s.get('acceptance')]
    return {
        'session_id': summary['session_id'], 'scenario_id': conditions['scenario']['scenario_id'],
        'termination_reason': summary['termination_reason'], 'steps': summary['steps'],
        'error': summary.get('error'),
        'tests_passed': {'before': summary.get('tests_passed_before'), 'after': summary.get('tests_passed_after'),
                         'max': max(passed) if passed else None},
        'first_stop': first_stop(log['observations']),
        'stop_steps': [o['step_id'] for o in log['observations']
                       if (o.get('criteria') or {}).get('decision') in STOP_DECISIONS],
        'tokens': gateway_prices.usage_totals(turns),
        'credits_measured': {k: (summary.get('gateway_usage') or {}).get(k)
                             for k in ('status', 'value', 'field', 'reason', 'exact_only_if_alone')}
                            | {'read_at': [((summary.get('gateway_usage') or {}).get(k) or {}).get('read_at')
                                           for k in ('before', 'after')]},
        'credits_estimated': {k: v for k, v in gateway_prices.estimate(meta.get('model'), turns).items()
                              if k in ('status', 'value', 'cached_price', 'reason')},
        'tool_calls_per_response': tool_calls_per_response(turns),
        'tool_results': tool_results(steps),
        'strict_output': strict_failures(steps),
        'condition_group': group['id'], 'condition_group_missing_fields': group['missing_fields'],
        'model': meta.get('model'), 'reasoning_effort': (conditions.get('reasoning_effort') or {}).get('requested'),
        'phase': conditions.get('phase'), 'guardrail_mode': meta.get('guardrail_mode'),
        'session_times': {'started_at': meta.get('started_at'), 'ended_at': meta.get('ended_at')},
        'key_scan': key_scan(folder)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='runs/demo/<session id>')
    args = parser.parse_args()
    result = summarize(args.folder)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result['key_scan']['clean'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
