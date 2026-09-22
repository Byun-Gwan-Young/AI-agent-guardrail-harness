"""S-28: first_step_with_all_tests compares with the suite total; early STOPs stay out of the delay median."""
import json
from pathlib import Path
import unittest

from docs.design.metrics_v1_check import metrics, session_record
from tools import analyze_session as tool

ROOT = Path(__file__).resolve().parents[1]
V4 = 'A-1-v4-e174aafe805b4f59bb62d7c95716b8b7'
REPORTS = ROOT / 'reports/a-1-v4'


def failure(session_id, stop, delay, tokens=100, after=40):
    return {'session_id': session_id, 'validity': 'valid', 'normal': False, 'failure': True,
            'first_stop_step': stop, 'known_tokens': tokens, 'known_tokens_after_first_stop': after,
            'usage_missing_turns': 0, 'delay_steps': delay, 'judgement_ns': [], 'steps': 30,
            'unmeasured_steps': 0, 'needs_observation_review_steps': 0}


class FirstStepWithAllTestsTests(unittest.TestCase):
    def test_a1v4_reanalysis_equals_the_c14_output(self):
        # C-14 corrected this field in its own report only; the tool now gives the same analysis.
        fresh = json.loads(json.dumps(tool.analyse(V4), ensure_ascii=False))
        saved = json.loads((REPORTS / 'c14-analysis.json').read_text(encoding='utf-8'))
        drop = ('prompt_checks', 'secret_scan')
        self.assertEqual({k: v for k, v in fresh.items() if k not in drop},
                         {k: v for k, v in saved.items() if k not in drop})
        # 7/16 was the largest count seen; it is not the full suite.
        self.assertEqual(fresh['judgement']['tests_after'], 7)
        self.assertIsNone(fresh['counterfactual_stop']['first_step_with_all_tests'])

    def test_full_suite_is_required(self):
        step = lambda passed, total: {'acceptance': {'artifact': {'test_pass_count': passed, 'test_total_count': total}}}
        self.assertTrue(tool.all_tests_passed(step(16, 16)))
        self.assertFalse(tool.all_tests_passed(step(7, 16)))
        self.assertFalse(tool.all_tests_passed(step(7, None)))
        self.assertFalse(tool.all_tests_passed({'acceptance': {'artifact': None}}))


class EarlyStopTests(unittest.TestCase):
    def test_early_stop_is_detected_but_not_in_the_median(self):
        result = metrics([failure('a', 9, 4), failure('b', 3, -2), failure('c', None, None)])
        self.assertEqual(result['detection_rate']['numerator'], 2)
        self.assertEqual(result['detection_delay_steps_median'], {'value': 4, 'status': 'measured', 'n': 1,
                                                                  'early_stops': 1})
        # Savings still start at the actual STOP of the early-stopped session.
        self.assertEqual(result['savings_failure_basis']['numerator'], 80)

    def test_a1v4_metrics_equal_the_c14_output(self):
        record = {**session_record(V4), 'validity': 'valid'}
        result = metrics([record])
        c14 = json.loads((REPORTS / 'c14-evidence.json').read_text(encoding='utf-8'))['candidate']['metrics_v1']
        self.assertEqual(record['onset_step'], c14['onset_step'])
        self.assertEqual(result['detection_rate'], c14['detection_rate'])
        self.assertEqual(result['savings_failure_basis'], c14['savings_failure_basis'])
        self.assertEqual(result['savings_all_basis'], c14['savings_all_basis'])
        self.assertEqual(result['detection_delay_steps_median']['value'], c14['delay_steps_median'])
        self.assertEqual(result['detection_delay_steps_median']['early_stops'], c14['early_stop_count'])


if __name__ == '__main__':
    unittest.main()
