"""C-18-3 part 4: the credits the T1 trial plan (batch_plans/demo-trial-c18-3.yaml) is expected to use. An estimate,
read-only, no external call. Writes reports/c18-3/estimate-trial.json.

No dialogue (T1) session has been measured yet, so the measured C-18-1 30-step session (glm-5.3-flash, high,
reports/c18-1/trial-summary.json) is taken as the upper value of every T1 session (DM-59 trial, C-18-3 part 4). There is
no lower value: a T1 session can end at any step, by success or by an escalated report (DM-18), so the short C-18-1
normal run is shown for reference only.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.c18_2_evidence import DEFAULT_OUTPUT as C18_1_SUMMARY, FULL_REFERENCE, NORMAL_REFERENCE  # noqa: E402

TRIAL_PLAN = ROOT / 'batch_plans/demo-trial-c18-3.yaml'
DEFAULT_ESTIMATE = ROOT / 'reports/c18-3/estimate-trial.json'


def trial_estimate(summary_path=C18_1_SUMMARY, plan_path=TRIAL_PLAN):
    from tools import run_batch
    summaries = json.loads(Path(summary_path).read_text(encoding='utf-8'))['summaries']
    short = summaries[NORMAL_REFERENCE]['credits_measured']['value']
    full = summaries[FULL_REFERENCE]['credits_measured']['value']
    plan = run_batch.load_plan(plan_path)
    rows = [{'item': i.key, 'kind': 'T1 dialogue, not measured', 'low': None, 'high': full} for i in plan['items']]
    return {'script': 'tools/c18_3_evidence.py trial', 'status': 'estimated', 'plan_id': plan['plan_id'],
            'plan_sha256': plan['plan_sha256'],
            'references': {'thirty_steps': {'session_id': FULL_REFERENCE, 'credits_measured': full, 'steps': 30,
                                            'used_as': 'upper value of each T1 session'},
                           'short_success': {'session_id': NORMAL_REFERENCE, 'credits_measured': short, 'steps': 6,
                                             'used_as': 'reference only (not a lower value)'}},
            'sessions': rows, 'total': {'low': None, 'high': round(sum(r['high'] for r in rows), 5)},
            'limits': ['no T1 session is measured; the references are CL (T3) artifact sessions',
                       'a T1 step can carry search results (MR up to 6,000 and LR up to 12,000 characters per call) '
                       'that a CL step does not, so a 30-step T1 session may cost more than the upper value',
                       'a session that ends early (success, escalated, runner_error) costs less']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('trial',))
    parser.add_argument('--output', type=Path, default=DEFAULT_ESTIMATE)
    args = parser.parse_args()
    result = trial_estimate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
