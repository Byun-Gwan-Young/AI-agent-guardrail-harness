import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scenario_schema import load_scenario
from tools import replay_preserved_observations as tool
from tools.replay_role_progress import LegacyMismatch

ROOT = Path(__file__).resolve().parents[1]


class PreservedReplayTests(unittest.TestCase):
    def setUp(self):
        self.log = json.loads((ROOT / 'logs/A-1-82c393c248a34286b318f344f2e181e4.json').read_text())
        self.previous = json.loads((ROOT / 'reports/p0-1/replay.json').read_text())
        self.scenario = load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml')

    def test_known_recovered_reports_without_artifact_invention(self):
        before = copy.deepcopy(self.log)
        report = tool.replay(self.log, self.scenario, self.previous)
        self.assertEqual(self.log, before)
        self.assertEqual(report['summary']['conversation_restored_steps'], [5, 10, 13, 16])
        self.assertEqual(report['summary']['discarded_not_restored_steps'], [18])
        for row in report['rows']:
            obs = row['observation']
            if row['original_discarded']:
                self.assertIsNone(obs['artifact'])
                self.assertEqual(row['artifact_status'], 'unmeasured')
                for key, status in obs['collection']['metric_status'].items():
                    if key.startswith('artifact.'):
                        self.assertEqual(status, 'unmeasured')
            if row['conversation_restored']:
                self.assertIn(row['final_receipt']['source_turn'], obs['llm_turns'])
                self.assertEqual(obs['conversation']['open_issue_ids'], row['final_receipt']['value']['open_issue_ids'])
        step5 = next(r for r in report['rows'] if r['step_id'] == 5)
        self.assertIsNone(step5['observation']['conversation']['info_items'])

    def test_invalid_or_truncated_final_never_partially_restored(self):
        for content, finish in [('{"narrative":"partial"}', 'stop'), ('{}', 'length')]:
            with self.subTest(finish=finish):
                log = copy.deepcopy(self.log)
                turn = next(t for t in log['turns'] if t['turn'] == 15)
                turn['response_body']['choices'][0]['message']['content'] = content
                turn['response_body']['choices'][0]['finish_reason'] = finish
                report = tool.replay(log, self.scenario, self.previous)
                row = next(r for r in report['rows'] if r['step_id'] == 5)
                self.assertFalse(row['conversation_restored'])
                self.assertIsNone(row['observation']['conversation']['open_issue_ids'])

    def test_gates_stop_before_preservation_on_mismatch(self):
        for kind in ('original', 'previous'):
            with self.subTest(kind=kind):
                log, previous = copy.deepcopy(self.log), copy.deepcopy(self.previous)
                if kind == 'original':
                    log['observations'][-1]['progress']['state'] = 'tampered'
                else:
                    previous['rows'][-1]['new']['progress']['state'] = 'tampered'
                with patch.object(tool, 'validate_final_response') as validator:
                    with self.assertRaises(LegacyMismatch):
                        tool.replay(log, self.scenario, previous)
                    validator.assert_not_called()

    def test_saved_output_is_reproducible(self):
        saved = json.loads((ROOT / 'reports/p0-2/replay.json').read_text())
        fresh = tool.replay(self.log, self.scenario, self.previous)
        for key in fresh:
            self.assertEqual(saved[key], fresh[key])
        self.assertEqual((ROOT / 'reports/p0-2/comparison.md').read_text(), tool.markdown(saved))
