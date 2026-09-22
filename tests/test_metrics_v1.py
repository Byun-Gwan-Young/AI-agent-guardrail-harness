import unittest

from docs.design.metrics_v1_check import metrics


def record(session_id, timings):
    return {'session_id': session_id, 'validity': 'valid', 'normal': True, 'failure': False,
            'first_stop_step': None, 'known_tokens_after_first_stop': None,
            'known_tokens': 1, 'usage_missing_turns': 0, 'delay_steps': None,
            'judgement_ns': timings, 'steps': len(timings), 'unmeasured_steps': 0,
            'needs_observation_review_steps': 0}


class MetricsTimingTests(unittest.TestCase):
    def test_p50_and_nearest_rank_p99_read_judgement_ns(self):
        result = metrics([record('a', [1_000_000, 3_000_000, 9_000_000])])
        self.assertEqual(result['judgement_overhead_ms'],
                         {'p50': 3.0, 'p99': 9.0, 'status': 'measured', 'n': 3})
