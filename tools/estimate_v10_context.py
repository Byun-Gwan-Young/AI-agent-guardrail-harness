"""Estimate v10 final-report input size from a stored v9 session without emitting reasoning text."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.step_execution import allowlisted_final_record


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def compact(value):
    return json.dumps(value, ensure_ascii=False)


def v10_record(record):
    # final_messages allowlists only assistant/tool records (they carry 'type'); the task,
    # acceptance and recent_messages facts rebuilt from user messages pass through unchanged.
    return allowlisted_final_record(record) if 'type' in record else record


def estimate(session_id):
    log_path = ROOT / 'logs' / f'{session_id}.json'
    steps_path = ROOT / 'runs' / session_id / 'steps.json'
    log, steps = load(log_path), load(steps_path)
    step_by_turn = {turn: step['step_id'] for step in steps for turn in step['llm_turns']}
    rows = []
    for turn in log['turns']:
        request = turn.get('request_body') or {}
        if 'response_format' not in request:
            continue
        messages = request.get('messages') or []
        user = next((m for m in reversed(messages)
                     if m.get('role') == 'user' and isinstance(m.get('content'), str)), None)
        try:
            old_payload = json.loads(user['content']) if user else None
        except ValueError:
            old_payload = None
        records = old_payload.get('observed_records') if isinstance(old_payload, dict) else None
        if not isinstance(records, list):
            rows.append({'step_id': step_by_turn.get(turn['turn']), 'turn': turn['turn'],
                         'status': 'unmeasured', 'reason': 'observed_records unavailable',
                         'v9_chars': None, 'v10_estimated_chars': None, 'estimated_reduction_chars': None})
            continue
        new_payload = {'observed_records': [v10_record(r) for r in records if isinstance(r, dict)]}
        old_chars = len(user['content'])
        new_chars = len(compact(new_payload))
        rows.append({'step_id': step_by_turn.get(turn['turn']), 'turn': turn['turn'], 'status': 'estimated',
                     'v9_chars': old_chars, 'v10_estimated_chars': new_chars,
                     'estimated_reduction_chars': old_chars - new_chars})
    measured = [row for row in rows if row['status'] == 'estimated']
    return {'estimate_version': 'v10-final-report-allowlist-estimate-v2',
            'session_id': session_id,
            'basis': 'stored v9 final-request user content transformed with the v10 allowlist; hypothetical, not a run',
            'inputs': {str(log_path.relative_to(ROOT)): hashlib.sha256(log_path.read_bytes()).hexdigest(),
                       str(steps_path.relative_to(ROOT)): hashlib.sha256(steps_path.read_bytes()).hexdigest()},
            'final_requests': rows,
            'summary': {'final_requests': len(rows),
                        'estimated_requests': len(measured),
                        'unmeasured_requests': len(rows) - len(measured),
                        'v9_chars': sum(row['v9_chars'] for row in measured),
                        'v10_estimated_chars': sum(row['v10_estimated_chars'] for row in measured),
                        'estimated_reduction_chars': sum(row['estimated_reduction_chars'] for row in measured)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = estimate(args.session_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
