"""The committed G0-8 session analysis is reproducible from the committed session files."""
import json
from pathlib import Path
import unittest

from tools import analyze_session as tool

ROOT = Path(__file__).resolve().parents[1]
SESSION = 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e'


class SessionAnalysisTests(unittest.TestCase):
    def setUp(self):
        # Compare in the saved JSON form (string keys, lists).
        self.analysis = json.loads(json.dumps(tool.analyse(SESSION), ensure_ascii=False))

    def test_saved_analysis_and_manifest_are_reproducible(self):
        saved = json.loads((ROOT / 'reports/g0-8' / f'{SESSION}-analysis.json').read_text(encoding='utf-8'))
        self.assertEqual(self.analysis, saved)
        manifest = json.loads((ROOT / 'reports/g0-8' / f'{SESSION}-manifest.json').read_text(encoding='utf-8'))
        rebuilt = json.loads(json.dumps(tool.manifest(self.analysis, 'verify', manifest['notes'][:-1]), ensure_ascii=False))
        self.assertEqual(manifest, rebuilt)
        self.assertEqual(manifest['validity']['class'], 'unclassified')

    def test_internal_consistency(self):
        a = self.analysis
        self.assertTrue(a['secret_scan']['clean'])
        self.assertTrue(a['isolation']['every_turn_linked_once'])
        # total follows the usage-missing rule rather than a partial sum.
        self.assertEqual(a['tokens']['total'] is None, a['tokens']['usage_missing_turns'] > 0)
        stop = a['first_stop_step']
        decisions = [r['criteria_decision'] for r in a['steps']]
        self.assertEqual(stop, next((r['step_id'] for r in a['steps'] if r['criteria_decision'] in tool.STOP_DECISIONS), None))
        if stop is not None:
            self.assertIn(decisions[stop - 1], tool.STOP_DECISIONS)
            after = a['counterfactual_stop']['known_tokens_after_stop']
            self.assertLessEqual(after, a['tokens']['known_total'])
