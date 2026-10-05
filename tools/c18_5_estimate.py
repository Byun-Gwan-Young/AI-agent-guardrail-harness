"""Credits the C-18-5 MR retest plan (batch_plans/demo-trial-c18-5.yaml) is expected to use (DM-72). An estimate.

For each plan item: the measured credits of the same scenario's session in the C-18-4 retest (demo-trial-c18-4, the
last run before the partial-report change), and as the high value the longest measured session of any committed MR
trial (a 30-step max_steps run). Read-only: committed record files only (conditions.json, record/demo-summary.json).

  venv/bin/python -B tools/c18_5_estimate.py --output reports/c18-5/estimate-retest.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import demo_records, run_batch  # noqa: E402

PLAN = ROOT / 'batch_plans/demo-trial-c18-5.yaml'
BEFORE = 'demo-trial-c18-4'


def measured(folder):
    summary = json.loads((folder / 'record/demo-summary.json').read_text(encoding='utf-8'))
    return {'scenario_id': summary['scenario_id'], 'session_id': summary['session_id'], 'steps': summary['steps'],
            'termination_reason': summary['termination_reason'],
            'credits_measured': summary['credits_measured']['value']}


def estimate(plan_path=PLAN, runs_root=ROOT / 'runs/demo'):
    plan = run_batch.load_plan(plan_path)
    before = {m['scenario_id']: m for m in map(measured, demo_records.plan_sessions(BEFORE, runs_root))}
    mr = [measured(f.parent.parent) for f in sorted(runs_root.glob('DEMO-MR-*/record/demo-summary.json'))]
    high = max(mr, key=lambda m: m['credits_measured'])
    rows = []
    for item in plan['items']:
        scenario_id = item.key.split(':')[0]
        rows.append({'item': item.key, 'c18_4_retest': before[scenario_id], 'high': high['credits_measured']})
    return {'script': 'tools/c18_5_estimate.py', 'status': 'estimated', 'plan_id': plan['plan_id'],
            'plan_sha256': hashlib.sha256(Path(plan_path).read_bytes()).hexdigest(),
            'upper_reference': high, 'sessions': rows,
            'total': {'c18_4_retest_sum': round(sum(r['c18_4_retest']['credits_measured'] for r in rows), 5),
                      'high': round(sum(r['high'] for r in rows), 5)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output')
    args = parser.parse_args()
    text = json.dumps(estimate(), ensure_ascii=False, indent=1) + '\n'
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
