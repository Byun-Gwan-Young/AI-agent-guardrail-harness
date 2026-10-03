"""Pre-run record for one scenario: file hash, vocabulary hash and the acceptance result on a
fresh copy of the fixture. Offline; no model or network call; the source fixture is never modified.

scenario-v1 (deadlock-v0.1 / v0.2): the record is exactly what it was before C-18-1.
scenario-v2 (deadlock-v0.3, demo track, C-18-1): the criteria are pinned with the parameters of the demo proxy
configuration (--config, default guardrail-deadlock-v0.3-kmu.yaml) and compared with the frozen record
(docs/criteria/deadlock-v0.3.json); the record adds the run-conditions file and the proxy's pinned model (DM-57), the
output contract and write_gate combination (DM-37), the session registration, and for a dialogue task the tool
settings, implementations and inputs (C-17-6). --pair compares a normal/stall pair file by file (DM-5: the two differ
only in the inducing device; the differences are listed for the PM, not judged here): the scenario values, the artifact
fixtures, and for a dialogue pair (C-18-3) the inputs_dir files and the judge files.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402

from criteria_freeze import V03, canonical_sha256, freeze  # noqa: E402
from criteria_policy import pin_criteria as pin_any  # noqa: E402
from deadlock_policy import pin_criteria  # noqa: E402
from experiment_config import load_config, load_run_conditions, pinned_model  # noqa: E402
from experiments.issue_contract import V1, V2, for_scenario  # noqa: E402
from experiments.run_scenario import Workspace, fingerprint, safe_path  # noqa: E402
from scenario_schema import SEARCH_TOOLS, load_scenario, registration_for  # noqa: E402
from suite_identity import compute_test_suite_id  # noqa: E402

DEMO_CONFIG = 'guardrail-deadlock-v0.3-kmu.yaml'
DEMO_RUN_CONDITIONS = 'demo-conditions.yaml'
FROZEN_V03 = 'docs/criteria/deadlock-v0.3.json'
# What a normal/stall pair may differ in besides the inducing device: their own names and what follows from them.
PAIR_IDENTITY_KEYS = ('scenario_id', 'fixture_dir', 'success_criteria.test_suite.test_suite_id')
# A dialogue pair (C-18-3) names its own inputs folder as well.
DIALOGUE_IDENTITY_KEYS = ('scenario_id', 'inputs_dir')


def acceptance_record(scenario):
    suite = scenario.success_criteria.test_suite
    if suite is None or not scenario.fixture_dir:
        raise ValueError('Executable artifact fixture required')
    source = safe_path(ROOT, scenario.fixture_dir)
    before = fingerprint(source)
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / 'workspace'
        shutil.copytree(source, workspace, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        result = Workspace(scenario, workspace).acceptance()
    return source, suite, before, result


def preflight(scenario_path, config_path=None):
    scenario_path = scenario_path.resolve()
    scenario = load_scenario(scenario_path)
    if scenario.schema_version == 'scenario-v2':
        return preflight_v2(scenario_path, scenario, config_path)
    source, suite, before, result = acceptance_record(scenario)
    contract = for_scenario(V2 if scenario.allowed_issues is not None else V1, scenario)
    return {'scenario_id': scenario.scenario_id,
            'scenario_path': scenario_path.relative_to(ROOT).as_posix(),
            'scenario_sha256': hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
            'criteria_version': scenario.criteria_version,
            'progress_version': pin_criteria(scenario.criteria_version)['criteria_parameters']['progress_version'],
            'output_contract_version': contract.version,
            'allowed_issues_sha256': contract.sha256,
            'allowed_issue_ids': [i.id for i in scenario.allowed_issues or []],
            'initial_issue_ids': scenario.initial_issue_ids,
            'fixture_dir': scenario.fixture_dir,
            'fixture_suite_id_matches': compute_test_suite_id(source, suite.test_roots, suite.contract_files,
                                                              suite.command) == suite.test_suite_id,
            'fixture_unchanged': fingerprint(source) == before,
            'acceptance': {'summary': result['summary'], 'gate': result['gate'], 'error': result['error']}}


def criteria_record(scenario, config_path):
    """deadlock-v0.3 pinned with the configuration's parameters, compared with the frozen record (DM-10, DM-33)."""
    path = Path(config_path) if config_path is not None else ROOT / DEMO_CONFIG
    config = load_config(path)
    if config.get('criteria_version') != scenario.criteria_version:
        raise ValueError(f'{path.name} runs {config.get("criteria_version")}, the scenario {scenario.criteria_version}')
    pin = pin_any(scenario.criteria_version, config.get('criteria_parameters'))
    frozen = json.loads((ROOT / FROZEN_V03).read_text(encoding='utf-8')) if scenario.criteria_version == V03 else None
    code = freeze(scenario.criteria_version)
    parameters = pin['criteria_parameters']
    return config, path, {
        'config_file': path.name, 'criteria_sha256': pin['criteria_sha256'],
        'parameters': {k: parameters[k] for k in ('consecutive_steps', 'grace_steps', 'missing_review_steps',
                                                  'plateau_steps', 't3_global_revert', 't1_metrics',
                                                  'handoff_record_threshold')},
        'parameter_names': {'K': 'plateau_steps', 'H': 'handoff_record_threshold (recorded only, DM-22)',
                            'N': 'consecutive_steps'},
        'frozen_record': FROZEN_V03,
        'frozen_criteria_sha256_matches': frozen is not None and frozen['criteria_sha256'] == pin['criteria_sha256'],
        'frozen_implementation_matches': frozen is not None and frozen['implementation_sha256'] ==
                                         code['implementation_sha256'],
        'frozen_templates_match': frozen is not None and frozen['explanation_templates_sha256'] ==
                                  code['explanation_templates_sha256'],
        'freeze_sha256': code['sha256']}


def run_conditions_record(scenario, config):
    """DM-57: the scenario names demo-conditions.yaml, and the proxy configuration pins the model it sets."""
    if scenario.run_conditions is None:
        return {'run_conditions': None, 'points_to_demo_conditions': False,
                'reason': 'the scenario gives its own model; demo scenarios name ' + DEMO_RUN_CONDITIONS}
    conditions = load_run_conditions(scenario.run_conditions, ROOT)
    pin = pinned_model(config)
    return {'run_conditions': scenario.run_conditions,
            'points_to_demo_conditions': scenario.run_conditions == DEMO_RUN_CONDITIONS,
            'run_conditions_sha256': conditions['sha256'], 'model': conditions['model'],
            'reasoning_effort': conditions['reasoning_effort'],
            'proxy_pinned_model': pin, 'proxy_pins_the_same_model': (pin or {}).get('name') == conditions['model']}


def contract_record(scenario):
    """DM-37 / DM-16: CT reports output-contract-v3 with write_gate; CL and CT-N report output-contract-v2 without one."""
    from experiments.dialogue_contract import V3, for_artifact_scenario, for_dialogue_scenario
    gate = scenario.write_gate.model_dump() if scenario.write_gate is not None else None
    if scenario.task_kind == 'dialogue':
        contract = for_dialogue_scenario(scenario)
        return contract, {'output_contract': V3, 'write_gate': None, 'combination_ok': True,
                          'rule': 'a dialogue task reports output-contract-v3 and has no write_gate'}
    contract = for_artifact_scenario(scenario)
    combination = ('v3 with write_gate (CT)' if scenario.output_contract == V3 and gate else
                   'v2 without write_gate (CL, CT-N)' if scenario.output_contract == V2 and not gate else
                   'v3 without write_gate')
    return contract, {'output_contract': scenario.output_contract, 'write_gate': gate, 'combination': combination,
                      'combination_ok': combination != 'v3 without write_gate',
                      'rule': 'DM-37: v3 is the CT contract for spec_approved, read only by write_gate (DM-16)'}


def dialogue_record(scenario):
    """C-17-6 pre-run facts of a dialogue task that hold without the environment (no key presence is recorded)."""
    from experiments import cs_tools, dialogue_tools, search_tools
    used = sorted({t for a in scenario.agents for t in a.tools})
    inputs_dir = safe_path(ROOT, scenario.inputs_dir)
    return {'tools_used': used, 'tools_without_implementation': dialogue_tools.missing_implementations(scenario),
            'key_environment_variables': sorted({search_tools.KEY_ENVS[t] for t in used if t in search_tools.KEY_ENVS}),
            'inputs_dir': scenario.inputs_dir, 'inputs_dir_exists': inputs_dir.is_dir(),
            'input_problems': {t: cs_tools.input_problems(t, inputs_dir) for t in used if t in cs_tools.TOOLS},
            'judge': scenario.judge, 'judge_exists': safe_path(ROOT, scenario.judge).is_file(),
            'tool_settings': {t: getattr(scenario.tool_settings, t).model_dump() for t in SEARCH_TOOLS
                              if scenario.tool_settings is not None and getattr(scenario.tool_settings, t)}}


def preflight_v2(scenario_path, scenario, config_path):
    config, _, criteria = criteria_record(scenario, config_path)
    contract, combination = contract_record(scenario)
    registration = registration_for(scenario)
    record = {'scenario_id': scenario.scenario_id, 'schema_version': scenario.schema_version,
              'task_kind': scenario.task_kind,
              'scenario_path': scenario_path.relative_to(ROOT).as_posix(),
              'scenario_sha256': hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
              'criteria_version': scenario.criteria_version,
              'progress_version': config['criteria_parameters']['progress_version'],
              'criteria': criteria,
              'run_conditions': run_conditions_record(scenario, config),
              'output_contract_version': contract.version,
              'contract': combination,
              'allowed_issues_sha256': contract.sha256,
              'allowed_issue_ids': [i.id for i in scenario.allowed_issues],
              'initial_issue_ids': scenario.initial_issue_ids,
              'registration_sha256': canonical_sha256(registration),
              'role_labels': registration['role_labels'],
              'writable_paths': {a.id: a.writable_paths for a in scenario.agents},
              'tools': {a.id: list(a.tools) for a in scenario.agents}}
    if scenario.task_kind == 'dialogue':
        return {**record, 'dialogue': dialogue_record(scenario)}
    source, suite, before, result = acceptance_record(scenario)
    return {**record, 'fixture_dir': scenario.fixture_dir,
            'monitored_paths_present': {p: (source / p).is_file() for p in scenario.monitored_paths},
            'fixture_suite_id_matches': compute_test_suite_id(source, suite.test_roots, suite.contract_files,
                                                              suite.command) == suite.test_suite_id,
            'fixture_unchanged': fingerprint(source) == before,
            'acceptance': {'summary': result['summary'], 'gate': result['gate'], 'error': result['error']}}


def checks_passed(report):
    if report.get('schema_version') != 'scenario-v2':
        return report['fixture_unchanged'] and report['fixture_suite_id_matches']
    criteria, conditions = report['criteria'], report['run_conditions']
    ok = (criteria['frozen_criteria_sha256_matches'] and criteria['frozen_implementation_matches']
          and criteria['frozen_templates_match'] and conditions['points_to_demo_conditions']
          and conditions.get('proxy_pins_the_same_model', False) and report['contract']['combination_ok'])
    if report['task_kind'] == 'dialogue':
        d = report['dialogue']
        return ok and not d['tools_without_implementation'] and d['inputs_dir_exists'] and d['judge_exists']
    return (ok and report['fixture_unchanged'] and report['fixture_suite_id_matches']
            and all(report['monitored_paths_present'].values()))


def leaves(value, prefix=''):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(leaves(item, prefix + key + '.'))
        return out
    return {prefix[:-1]: value}


def fixture_files(root):
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def unified(a_text, b_text, a_name, b_name):
    return ''.join(difflib.unified_diff(a_text.splitlines(keepends=True), b_text.splitlines(keepends=True),
                                        a_name, b_name))


def pair_diff(a_path, b_path):
    """A normal/stall pair compared file by file: the scenario files (parsed values and text) and the fixtures."""
    a_path, b_path = Path(a_path).resolve(), Path(b_path).resolve()
    a_data, b_data = (yaml.safe_load(p.read_text(encoding='utf-8')) for p in (a_path, b_path))
    a_leaves, b_leaves = leaves(a_data), leaves(b_data)
    keys = sorted(k for k in set(a_leaves) | set(b_leaves) if a_leaves.get(k) != b_leaves.get(k))
    a_scenario, b_scenario = load_scenario(a_path), load_scenario(b_path)
    files = []
    # The artifact fixtures, or the inputs of a dialogue pair (C-18-3); a shared folder has no difference.
    for field in ('fixture_dir', 'inputs_dir'):
        a_dir, b_dir = getattr(a_scenario, field, None), getattr(b_scenario, field, None)
        if not a_dir or not b_dir:
            continue
        a_files, b_files = fixture_files(safe_path(ROOT, a_dir)), fixture_files(safe_path(ROOT, b_dir))
        for name in sorted(set(a_files) | set(b_files)):
            if name not in b_files or name not in a_files:
                files.append({'path': name, 'status': 'only_in_' + ('a' if name in a_files else 'b')})
            elif a_files[name].read_bytes() != b_files[name].read_bytes():
                files.append({'path': name, 'status': 'different',
                              'diff': unified(a_files[name].read_text(encoding='utf-8'),
                                              b_files[name].read_text(encoding='utf-8'),
                                              a_dir + '/' + name, b_dir + '/' + name)})
    judges = None
    if getattr(a_scenario, 'judge', None) and getattr(b_scenario, 'judge', None):
        a_judge, b_judge = (safe_path(ROOT, s.judge).read_text(encoding='utf-8') for s in (a_scenario, b_scenario))
        judges = {'a': a_scenario.judge, 'b': b_scenario.judge, 'same_file': a_scenario.judge == b_scenario.judge,
                  'diff': unified(a_judge, b_judge, a_scenario.judge, b_scenario.judge)}
    identity = DIALOGUE_IDENTITY_KEYS if a_scenario.schema_version == 'scenario-v2' and \
        a_scenario.task_kind == 'dialogue' else PAIR_IDENTITY_KEYS
    beyond = [k for k in keys if k not in identity]
    rel = lambda p: p.relative_to(ROOT).as_posix()
    return {'a': rel(a_path), 'b': rel(b_path),
            'scenario_values_differing': {k: [a_leaves.get(k), b_leaves.get(k)] for k in keys},
            'scenario_values_differing_beyond_identity': beyond,
            'identity_keys': list(identity),
            'scenario_text_diff': unified(a_path.read_text(encoding='utf-8'), b_path.read_text(encoding='utf-8'),
                                          rel(a_path), rel(b_path)),
            'fixture_files_differing': files,
            'judge_files': judges,
            'one_fixture_file_and_identity_only': not beyond and len(files) == 1 and files[0]['status'] == 'different'
                                                  and (judges is None or judges['same_file'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=None,
                        help='scenario-v2: proxy configuration with the criteria parameters (default ' + DEMO_CONFIG + ')')
    parser.add_argument('--pair', type=Path, default=None,
                        help='scenario-v2: the other scenario of a normal/stall pair, compared file by file')
    args = parser.parse_args()
    report = preflight(args.scenario, args.config)
    if args.pair is not None:
        report['pair'] = pair_diff(args.scenario, args.pair)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    shown = {k: v for k, v in report.items() if k not in ('acceptance', 'pair')}
    if 'acceptance' in report:
        shown['acceptance'] = {k: v for k, v in report['acceptance']['summary'].items() if k != 'cases'}
    if 'pair' in report:
        shown['pair'] = {k: report['pair'][k] for k in ('scenario_values_differing_beyond_identity',
                                                        'one_fixture_file_and_identity_only')}
        shown['pair']['fixture_files_differing'] = [f['path'] for f in report['pair']['fixture_files_differing']]
        if report['pair']['judge_files'] is not None:
            shown['pair']['judge_files'] = {k: report['pair']['judge_files'][k] for k in ('a', 'b', 'same_file')}
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if checks_passed(report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
