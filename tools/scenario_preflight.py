"""Pre-run record for one scenario: file hash, vocabulary hash and the acceptance result on a
fresh copy of the fixture. Offline; no model or network call; the source fixture is never modified."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.issue_contract import V1, V2, for_scenario
from experiments.run_scenario import Workspace, fingerprint, safe_path
from scenario_schema import load_scenario
from suite_identity import compute_test_suite_id


def preflight(scenario_path):
    scenario_path = scenario_path.resolve()
    scenario = load_scenario(scenario_path)
    suite = scenario.success_criteria.test_suite
    if suite is None or not scenario.fixture_dir:
        raise ValueError('Executable artifact fixture required')
    source = safe_path(ROOT, scenario.fixture_dir)
    before = fingerprint(source)
    contract = for_scenario(V2 if scenario.allowed_issues is not None else V1, scenario)
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / 'workspace'
        shutil.copytree(source, workspace, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        result = Workspace(scenario, workspace).acceptance()
    return {'scenario_id': scenario.scenario_id,
            'scenario_path': scenario_path.relative_to(ROOT).as_posix(),
            'scenario_sha256': hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
            'output_contract_version': contract.version,
            'allowed_issues_sha256': contract.sha256,
            'allowed_issue_ids': [i.id for i in scenario.allowed_issues or []],
            'initial_issue_ids': scenario.initial_issue_ids,
            'fixture_dir': scenario.fixture_dir,
            'fixture_suite_id_matches': compute_test_suite_id(source, suite.test_roots, suite.contract_files,
                                                              suite.command) == suite.test_suite_id,
            'fixture_unchanged': fingerprint(source) == before,
            'acceptance': {'summary': result['summary'], 'gate': result['gate'], 'error': result['error']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = preflight(args.scenario)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'acceptance'} |
                     {'acceptance': {k: v for k, v in report['acceptance']['summary'].items() if k != 'cases'}},
                     ensure_ascii=False, indent=2))
    return 0 if report['fixture_unchanged'] and report['fixture_suite_id_matches'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
