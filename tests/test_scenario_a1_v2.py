import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

import httpx
import yaml

from scenario_schema import load_scenario
from experiments.issue_contract import V2, for_scenario
from tools.scenario_preflight import preflight
from experiment_config import load_config
from proxy import create_app

ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / 'scenarios/A-1-ambiguous-task-query.yaml'
V2_PATH = ROOT / 'scenarios/A-1-v2-ambiguous-task-query.yaml'
PROCESS = {'requirements', 'acceptance-review'}


class A1V2ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.old, self.new = load_scenario(V1_PATH), load_scenario(V2_PATH)

    def test_only_identity_vocabulary_and_criteria_differ_from_a1(self):
        old, new = self.old.model_dump(), self.new.model_dump()
        self.assertEqual(new.pop('scenario_id'), 'A-1-v2')
        self.assertIsNotNone(new.pop('allowed_issues'))
        # D-18: A-1-v2 runs under deadlock-v0.2 / progress-v2; A-1 stays on v0.1.
        self.assertEqual((new.pop('criteria_version'), old.pop('criteria_version')),
                         ('deadlock-v0.2', 'deadlock-v0.1'))
        old.pop('scenario_id'); self.assertIsNone(old.pop('allowed_issues'))
        self.assertEqual(new, old)
        self.assertEqual(self.new.expected_outcome, 'unknown')

    def test_one_id_per_numbered_acceptance_item_plus_two_process_issues(self):
        acceptance = (ROOT / self.new.fixture_dir / 'ACCEPTANCE.md').read_text(encoding='utf-8')
        items = [int(m.group(1)) for m in re.finditer(r'^(\d+)\. ', acceptance, re.M)]
        ids = [i.id for i in self.new.allowed_issues]
        functional = [i for i in self.new.allowed_issues if i.id not in PROCESS]
        self.assertTrue(PROCESS <= set(ids))
        self.assertEqual(len(functional), len(items))
        for n in items:
            owners = [i.id for i in functional if i.definition.startswith(f'인수 조건 {n} ')]
            self.assertEqual(len(owners), 1, n)
        self.assertLessEqual(set(self.new.initial_issue_ids), set(ids))
        self.assertEqual(self.new.initial_issue_ids, self.old.initial_issue_ids)

    def test_every_id_has_evidence_comment_citing_readable_files(self):
        text = V2_PATH.read_text(encoding='utf-8')
        readable = {p.relative_to(ROOT / self.new.fixture_dir).as_posix()
                    for p in (ROOT / self.new.fixture_dir).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        for issue in self.new.allowed_issues:
            match = re.search(r'#\s*근거:\s*(.+)\n\s*- id: ' + re.escape(issue.id) + r'\n', text)
            self.assertIsNotNone(match, issue.id)
            cited = re.findall(r'([\w/]+\.(?:md|py)):', match.group(1))
            self.assertTrue(cited and set(cited) <= readable, (issue.id, cited))

    def test_v2_contract_builds_and_v1_scenario_still_refuses_v2(self):
        self.assertRegex(for_scenario(V2, self.new).sha256, r'^[0-9a-f]{64}$')
        with self.assertRaises(ValueError):
            for_scenario(V2, self.old)


class PreflightTests(unittest.TestCase):
    def test_preflight_is_offline_reproducible_and_leaves_fixture_unchanged(self):
        report = preflight(V2_PATH)
        scenario = load_scenario(V2_PATH)
        self.assertEqual(report['scenario_sha256'], hashlib.sha256(V2_PATH.read_bytes()).hexdigest())
        self.assertTrue(report['fixture_unchanged'])
        self.assertTrue(report['fixture_suite_id_matches'])
        self.assertEqual(report['acceptance']['summary']['tests'],
                         scenario.success_criteria.test_suite.expected_test_count)
        self.assertIsNone(report['acceptance']['error'])
        self.assertEqual((report['criteria_version'], report['progress_version']), ('deadlock-v0.2', 'progress-v2'))
        saved = json.loads((ROOT / 'reports/p0-3/A-1-v2-preflight-deadlock-v0.2.json').read_text(encoding='utf-8'))
        self.assertEqual(report, saved)
        # The earlier v0.1 preflight is kept as a historical record, not overwritten.
        old = json.loads((ROOT / 'reports/p0-3/A-1-v2-preflight.json').read_text(encoding='utf-8'))
        self.assertNotEqual(old['scenario_sha256'], report['scenario_sha256'])
        self.assertEqual(old['acceptance'], report['acceptance'])


V02_CONFIG = ROOT / 'guardrail-deadlock-v0.2.yaml'


class ProxyCriteriaConfigTests(unittest.IsolatedAsyncioTestCase):
    async def pinned(self, config_path):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'logs', config_path=config_path)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://proxy',
                                         headers={'X-Guardrail-Session': 'criteria-check'}) as client:
                (await client.post('/sessions')).raise_for_status()
                return (await client.get('/log')).json()['meta']

    def test_v02_config_differs_from_default_only_in_criteria_version(self):
        default, v02 = load_config(ROOT / 'guardrail.yaml'), load_config(V02_CONFIG)
        self.assertEqual((default.pop('criteria_version'), v02.pop('criteria_version')),
                         ('deadlock-v0.1', 'deadlock-v0.2'))
        self.assertEqual(default, v02)
        self.assertEqual(yaml.safe_load((ROOT / 'guardrail.yaml').read_text(encoding='utf-8'))['criteria_version'],
                         'deadlock-v0.1')

    async def test_runner_version_check_matches_only_with_explicit_config(self):
        a1, a1v2 = load_scenario(V1_PATH), load_scenario(V2_PATH)
        default = await self.pinned(ROOT / 'guardrail.yaml')
        explicit = await self.pinned(V02_CONFIG)
        # Same comparison as run_scenario: proxy meta criteria_version == scenario.criteria_version.
        self.assertEqual(default['criteria_version'], a1.criteria_version)
        self.assertNotEqual(default['criteria_version'], a1v2.criteria_version)
        self.assertEqual(explicit['criteria_version'], a1v2.criteria_version)
        self.assertEqual(explicit['criteria_parameters']['progress_version'], 'progress-v2')
        self.assertEqual(default['criteria_parameters']['progress_version'], 'progress-v1')
