"""Account label correction file of the demo main run reruns (C-18-8 part 2, DM-81 ②). The reruns were started from
windows that held another account's key than the lane's label; the key is not in any record, so the actual account is
the PM's statement, given here as --lane-account. Which sessions it applies to is a rule, not a hand pick:

  demo_account_corrections.py --plan demo-main-v1 --git-commit <rerun commit>
                              --lane-account 1=C --lane-account 2=A --lane-account 3=B
                              --source "PM 진술 (DM-81 ②)" [--output reports/c18-8/account-corrections.json]

Sessions: every runs/demo/<id> whose conditions.json batch.plan_id is --plan, git_commit is --git-commit (the reruns ran
at the commit after the proxy fix, the main run before it, DM-79 ④) and batch.lane is one of the --lane-account lanes.
Each gets its label (conditions.json account_label) and the stated account. tools/aggregate_demo.py
--account-corrections adds per-account credit totals with these applied next to the label totals.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEMO_RUNS = ROOT / 'runs' / 'demo'
VERSION = 'demo-account-corrections-v1'


def lane_accounts(pairs):
    accounts = {}
    for pair in pairs:
        lane, _, account = pair.partition('=')
        if not lane.isdigit() or not account:
            raise ValueError(f'--lane-account takes <lane>=<account>, not {pair!r}')
        accounts[int(lane)] = account
    return accounts


def build(plan, git_commit, accounts, source, *, runs_root=DEMO_RUNS):
    sessions = []
    for folder in sorted(Path(runs_root).iterdir()) if Path(runs_root).is_dir() else []:
        path = folder / 'conditions.json'
        if not path.is_file():
            continue
        conditions = json.loads(path.read_text(encoding='utf-8'))
        batch = conditions.get('batch') or {}
        if (batch.get('plan_id') != plan or conditions.get('git_commit') != git_commit
                or batch.get('lane') not in accounts):
            continue
        sessions.append({'session_id': folder.name, 'item': batch.get('item'), 'lane': batch['lane'],
                         'rerun_of': batch.get('rerun_of'), 'label': conditions.get('account_label'),
                         'actual': accounts[batch['lane']]})
    return {'account_corrections_version': VERSION, 'plan_id': plan, 'git_commit': git_commit,
            'lane_accounts': {str(k): v for k, v in sorted(accounts.items())}, 'source': source,
            'sessions': sessions}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--git-commit', required=True)
    parser.add_argument('--lane-account', action='append', required=True)
    parser.add_argument('--source', required=True, help='where the actual accounts come from (no key is recorded)')
    parser.add_argument('--runs-root', type=Path, default=DEMO_RUNS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = build(args.plan, args.git_commit, lane_accounts(args.lane_account), args.source, runs_root=args.runs_root)
    text = json.dumps(result, ensure_ascii=False, indent=1) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if result['sessions'] else 1


if __name__ == '__main__':
    sys.exit(main())
