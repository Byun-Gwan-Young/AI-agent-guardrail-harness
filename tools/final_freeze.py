"""Final freeze of the demo (C-18-3 part 3, DM-33): one record of everything the main run depends on, made once before
C-19 and checked before every main-run session.

The record (docs/criteria/demo-final-freeze.json, demo-final-freeze-v1) holds:
- the deadlock-v0.3 freeze of this checkout (implementation files and explanation templates, criteria_freeze.freeze)
  and the criteria parameter hash of each demo proxy configuration (observe and block)
- the sha256 of every file the main run reads: the v0.3 implementation files and frozen records, the two demo proxy
  configurations, demo-conditions.yaml, the main plan (batch_plans/demo-main-v1.yaml), and for each of its scenarios
  (11) the scenario file, its judge and every file of its fixture_dir or inputs_dir
- the commit it was made at, and sha256 = one hash over all of the above except the time and the commit

  create   PM, after the T1 trial is confirmed: refuses when a record exists or when a covered file differs from HEAD
           (uncommitted or untracked), so the record names committed content
  check    the record against the files now; exit 1 on any difference or without a record

tools/run_batch.py runs a plan with requires_final_freeze (the main plan) only while check passes, and hands the record
file's sha256 to each session (conditions.json batch.final_freeze_sha256, manifest run.batch). Offline; no model call.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import criteria_freeze  # noqa: E402
from criteria_policy import pin_criteria  # noqa: E402
from experiment_config import load_config  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402

VERSION = 'demo-final-freeze-v1'
RECORD = 'docs/criteria/demo-final-freeze.json'
MAIN_PLAN = 'batch_plans/demo-main-v1.yaml'
RUN_CONDITIONS = 'demo-conditions.yaml'
PROXY_CONFIGS = ('guardrail-deadlock-v0.3-kmu.yaml', 'guardrail-deadlock-v0.3-kmu-block.yaml')
FROZEN_RECORDS = ('docs/criteria/deadlock-v0.3.json', criteria_freeze.EXPLANATION_RECORD)
SCENARIOS = 11  # DM-59: CL, CT, CS, MR, LR normal and stall + CT-N


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def folder_files(root, relative):
    folder = Path(root) / relative
    return sorted(p.relative_to(root).as_posix() for p in folder.rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')


def plan_scenarios(root, plan=MAIN_PLAN):
    from tools.run_batch import load_plan
    return sorted({item.scenario for item in load_plan(Path(root) / plan)['items']})


def covered_paths(root, plan=MAIN_PLAN):
    """Every file the record hashes, and the scenario IDs of the plan."""
    paths = set(criteria_freeze.V03_IMPLEMENTATION) | set(FROZEN_RECORDS) | set(PROXY_CONFIGS) | {RUN_CONDITIONS, plan}
    scenario_ids = []
    for relative in plan_scenarios(root, plan):
        scenario = load_scenario(Path(root) / relative)
        scenario_ids.append(scenario.scenario_id)
        paths.add(relative)
        for folder in (getattr(scenario, 'fixture_dir', None), getattr(scenario, 'inputs_dir', None)):
            if folder:
                paths.update(folder_files(root, folder))
        if getattr(scenario, 'judge', None):
            paths.add(scenario.judge)
    return sorted(paths), sorted(scenario_ids)


def content(root=ROOT, plan=MAIN_PLAN):
    """What the record freezes (no time, no commit), with its sha256."""
    paths, scenario_ids = covered_paths(root, plan)
    criteria = {}
    for name in PROXY_CONFIGS:
        config = load_config(Path(root) / name)
        criteria[name] = {'criteria_version': config['criteria_version'], 'guardrail_mode': config.get('guardrail_mode'),
                          'criteria_sha256': pin_criteria(config['criteria_version'],
                                                          config.get('criteria_parameters'))['criteria_sha256']}
    values = {'freeze_version': VERSION, 'plan': plan, 'scenario_ids': scenario_ids,
              'criteria_freeze': criteria_freeze.freeze(criteria_freeze.V03, Path(root)),
              'proxy_criteria': criteria, 'files': {p: sha256_file(Path(root) / p) for p in paths}}
    return {**values, 'sha256': criteria_freeze.canonical_sha256(values)}


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True).stdout


def create(root=ROOT, record=RECORD, plan=MAIN_PLAN, now=None):
    root = Path(root)
    path = root / record
    if path.exists():
        raise ValueError(f'{record} exists: the final freeze is made once (DM-33); a new freeze is a PM decision')
    values = content(root, plan)
    if len(values['scenario_ids']) != SCENARIOS:
        raise ValueError(f'{plan} names {len(values["scenario_ids"])} scenarios, not {SCENARIOS}')
    changed = [line[3:] for line in git(root, 'status', '--porcelain', '--untracked-files=all', '--',
                                        *values['files']).splitlines()]
    if changed:
        raise ValueError('commit these files before the final freeze: ' + ', '.join(changed))
    data = {**values, 'created_at': (now or datetime.now(timezone.utc)).isoformat(),
            'git_commit': git(root, 'rev-parse', 'HEAD').strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return {'record': record, 'record_file_sha256': sha256_file(path), 'sha256': data['sha256'],
            'scenarios': len(data['scenario_ids']), 'files': len(data['files']), 'git_commit': data['git_commit']}


def check(root=ROOT, record=RECORD):
    """{ok, record_file_sha256, sha256, differences}. Differences are what changed since the record."""
    root = Path(root)
    path = root / record
    if not path.is_file():
        return {'ok': False, 'record': record, 'record_file_sha256': None, 'sha256': None,
                'differences': [f'no final freeze record ({record}); the PM makes it with create (DM-33)']}
    frozen = json.loads(path.read_text(encoding='utf-8'))
    differences = []
    try:
        now = content(root, frozen.get('plan', MAIN_PLAN))
    except (OSError, ValueError) as error:
        now = None
        differences.append('cannot read the frozen files: ' + str(error)[:300])
    if now is not None:
        for name in sorted(set(frozen['files']) | set(now['files'])):
            if name not in now['files']:
                differences.append(f'{name}: no longer read by the plan or missing')
            elif name not in frozen['files']:
                differences.append(f'{name}: not in the record')
            elif frozen['files'][name] != now['files'][name]:
                differences.append(f'{name}: changed')
        for key in ('freeze_version', 'scenario_ids', 'criteria_freeze', 'proxy_criteria'):
            if frozen.get(key) != now[key]:
                differences.append(f'{key}: changed')
        if not differences and frozen.get('sha256') != now['sha256']:
            differences.append('sha256: the record does not match its own content')
    return {'ok': not differences, 'record': record, 'record_file_sha256': sha256_file(path),
            'sha256': frozen.get('sha256'), 'git_commit': frozen.get('git_commit'), 'differences': differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('create', 'check'))
    args = parser.parse_args()
    try:
        result = create() if args.action == 'create' else check()
    except ValueError as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if args.action == 'create' or result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
