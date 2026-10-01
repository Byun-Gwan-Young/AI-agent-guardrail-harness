"""C-17-1 part 3: offline v0.3 recomputation tool over the existing sessions."""
import json
from pathlib import Path
import unittest

from criteria_policy import pin_criteria
from experiment_config import load_config
from tools import recompute_v03 as tool

ROOT = Path(__file__).resolve().parents[1]


class RecomputeToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = load_config(tool.CONFIG)
        cls.pin = pin_criteria(config['criteria_version'], config['criteria_parameters'])
        cls.predictions = json.loads(tool.PREDICTION.read_text(encoding='utf-8'))['sessions']

    def test_reports_prediction_match_and_v02_reproduction_without_model_text(self):
        for label, session_id in tool.SESSIONS.items():
            with self.subTest(session=label):
                report = tool.session_report(label, session_id, self.pin, self.predictions)
                self.assertTrue(report['v02_recomputed_byte_identical'])
                self.assertTrue(report['v03_matches_prediction'])
                self.assertEqual(report['steps_where_v02_v03_decision_differs'], [])
                text = json.dumps(report, ensure_ascii=False)
                for field in ('narrative', 'reasoning', 'evidence', '"reasons"'):
                    self.assertNotIn(field, text)
        normal = tool.session_report('A-1-v3', tool.SESSIONS['A-1-v3'], self.pin, self.predictions)
        self.assertEqual((normal['v03_stop_steps'], normal['first_stop_explanation']), ([], None))

    def test_first_stop_sentence_uses_role_ids_and_offers_scenario_labels(self):
        report = tool.session_report('A-1-v4', tool.SESSIONS['A-1-v4'], self.pin, self.predictions)
        first = report['first_stop_explanation']
        self.assertEqual((first['step'], first['template_id']), (9, 'E1'))
        self.assertIn('planner·developer·reviewer', first['text'])
        self.assertIn('기획·개발·리뷰', first['text_with_scenario_role_labels'])

    def test_dm28_refreeze_keeps_every_v03_decision_of_the_c17_1_report(self):
        # C-17-2: the three sessions have no T3 event, so DM-28 must not change any v0.3 state or decision.
        previous = json.loads((ROOT / 'reports/c17-1/v03-recompute.json').read_text(encoding='utf-8'))
        current = {'sessions': {label: tool.session_report(label, session_id, self.pin, self.predictions)
                                for label, session_id in tool.SESSIONS.items()}}
        for label, result in tool.compare(previous, current).items():
            with self.subTest(session=label):
                self.assertEqual((result['v03_state_changed_steps'], result['v03_decision_changed_steps']), ([], []))
                self.assertTrue(result['first_stop_text_unchanged'])
        self.assertEqual({label: s['dm28_uncounted_pass_count_event_steps'] for label, s in current['sessions'].items()},
                         {'G0-8': [15], 'A-1-v3': [6, 7], 'A-1-v4': []})
