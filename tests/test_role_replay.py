import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import replay_role_progress as replay_tool
from scenario_schema import load_scenario

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'logs/A-1-82c393c248a34286b318f344f2e181e4.json'


class RoleReplayTests(unittest.TestCase):
    def setUp(self):
        self.raw = INPUT.read_bytes()
        self.log = json.loads(self.raw)
        self.scenario = load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml')
        self.rules = {a.id:a.system_message.strip().splitlines()[0] for a in self.scenario.agents}

    def test_replay_preserves_input_and_derives_summary_without_expected_counts(self):
        before = copy.deepcopy(self.log)
        result = replay_tool.replay(self.log, self.rules)
        self.assertEqual(self.log, before)
        self.assertEqual(INPUT.read_bytes(), self.raw)
        rows = result['rows']
        self.assertEqual(len(rows), len(self.log['observations']))
        self.assertEqual(result['summary']['removed'], sum(r['classification']['issue_only_progress_removed'] for r in rows))
        self.assertEqual(result['summary']['cross_role_issue_progress_candidates'],
                         sum(r['classification']['old_progress_issue_only'] for r in rows))
        self.assertTrue(result['legacy_byte_match'])
        for row in rows:
            self.assertEqual(row['new']['progress']['version'], 'progress-v2')
            self.assertEqual(row['new']['criteria']['criteria_version'], 'deadlock-v0.2')
            self.assertTrue(row['role_mapping']['evidence'])

    def test_stored_mismatch_stops_before_any_v2_calculation(self):
        tampered = copy.deepcopy(self.log)
        tampered['observations'][-1]['progress']['state'] = 'tampered'
        original = replay_tool.calculate_progress
        versions = []
        def tracked(*args, **kwargs):
            versions.append(kwargs.get('version'))
            return original(*args, **kwargs)
        with patch.object(replay_tool, 'calculate_progress', tracked):
            with self.assertRaises(replay_tool.LegacyMismatch):
                replay_tool.replay(tampered, self.rules)
        self.assertNotIn('progress-v2', versions)

    def test_discarded_observations_remain_in_role_history(self):
        result = replay_tool.replay(self.log, self.rules)
        by_step = {o['step_id']:o for o in self.log['observations']}
        seen = {}
        for row in result['rows']:
            agent = row['role_mapping']['agent_id']
            expected = seen.get(agent)
            self.assertEqual(row['new_comparison_step_id'], expected)
            current = by_step[row['step_id']]
            if replay_tool.discarded(current):
                self.assertEqual(row['new']['progress']['state'], 'unmeasured')
                self.assertTrue(row['classification']['current_discarded_gap'])
            if expected is not None and replay_tool.discarded(by_step[expected]):
                self.assertTrue(row['classification']['previous_same_role_discarded_gap'])
            seen[agent] = row['step_id']

    def test_role_evidence_uses_request_text_not_round_robin(self):
        turns = {t['turn']:t for t in self.log['turns']}
        observation = copy.deepcopy(self.log['observations'][0])
        first = replay_tool.identify_agent(observation, turns, self.rules)
        observation['step_id'] += 1
        self.assertEqual(replay_tool.identify_agent(observation, turns, self.rules), first)
        self.assertIsNone(replay_tool.identify_agent(observation, {}, self.rules)['agent_id'])
        duplicate = {**self.rules, 'ambiguous':self.rules[first['agent_id']]}
        self.assertIsNone(replay_tool.identify_agent(observation, turns, duplicate)['agent_id'])

    def test_shared_artifact_and_null_info_remain_separate_classifications(self):
        result = replay_tool.replay(self.log, self.rules)
        for row in result['rows']:
            c = row['classification']
            if c['shared_artifact_events']:
                self.assertTrue(row['new']['progress']['artifact_moved'])
                self.assertIn('공유 산출물', replay_tool.explanation(row))
            if c['current_info_items_null'] and not c['current_discarded_gap']:
                self.assertIn('P0-4', replay_tool.explanation(row))
            if c['current_discarded_gap'] or c['previous_same_role_discarded_gap']:
                self.assertIn('P0-2', replay_tool.explanation(row))

    def test_generated_report_is_reproducible(self):
        saved = json.loads((ROOT / 'reports/p0-1/replay.json').read_text())
        fresh = replay_tool.replay(self.log, self.rules)
        for field in ('rows', 'summary', 'new_pin', 'legacy_byte_match'):
            self.assertEqual(saved[field], fresh[field])
        self.assertEqual(saved['input_sha256'], replay_tool.digest(self.raw))
        self.assertEqual(saved['protocol_sha256'], replay_tool.digest((ROOT / 'docs/P0-1-replay-protocol.md').read_bytes()))
        self.assertEqual(saved['role_rules_sha256'], replay_tool.digest((ROOT / 'scenarios/A-1-ambiguous-task-query.yaml').read_bytes()))
        self.assertEqual((ROOT / 'reports/p0-1/comparison.md').read_text(), replay_tool.markdown(saved))
