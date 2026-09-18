import hashlib
import json
from pathlib import Path
import re
import unittest

from scenario_schema import load_scenario
from experiments.issue_contract import V2, for_scenario
from tools.scenario_preflight import preflight

ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / 'scenarios/A-1-ambiguous-task-query.yaml'
V2_PATH = ROOT / 'scenarios/A-1-v2-ambiguous-task-query.yaml'
PROCESS = {'requirements', 'acceptance-review'}


class A1V2ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.old, self.new = load_scenario(V1_PATH), load_scenario(V2_PATH)

    def test_only_identity_and_vocabulary_differ_from_a1(self):
        old, new = self.old.model_dump(), self.new.model_dump()
        self.assertEqual(new.pop('scenario_id'), 'A-1-v2')
        self.assertIsNotNone(new.pop('allowed_issues'))
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
        saved = json.loads((ROOT / 'reports/p0-3/A-1-v2-preflight.json').read_text(encoding='utf-8'))
        self.assertEqual(report, saved)
