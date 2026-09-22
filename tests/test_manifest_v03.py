"""S-8/S-1/S-23: session-manifest-v0.3 for sessions whose runner recorded the Git state."""
import copy
import json
from pathlib import Path
import unittest

from tools import analyze_session as tool

ROOT = Path(__file__).resolve().parents[1]
V4 = 'A-1-v4-e174aafe805b4f59bb62d7c95716b8b7'


class ManifestV03Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = json.loads(json.dumps(tool.analyse(V4), ensure_ascii=False))
        cls.conditions = json.loads((ROOT / 'runs' / V4 / 'conditions.json').read_text(encoding='utf-8'))
        cls.observations = json.loads((ROOT / 'logs' / f'{V4}.json').read_text(encoding='utf-8'))['observations']

    def build(self, conditions, observations):
        base = tool.base_manifest(self.analysis, 'measure', ['operator note'])
        return tool.v03_fields(base, self.analysis, conditions, observations)

    def test_fields_follow_s1_s8_s23(self):
        conditions = {**self.conditions, 'git_commit': 'abc123', 'git_dirty': False,
                      'git_state_status': 'measured', 'dataset_run': True}
        observations = [{**o, 'judgement_ns': 1_000_000 * (i + 1)} for i, o in enumerate(self.observations)]
        m = self.build(conditions, observations)
        self.assertEqual(m['manifest_version'], 'session-manifest-v0.3')
        self.assertNotIn('version', m['scenario'])
        self.assertEqual((m['code']['git_commit'], m['code']['git_dirty'], m['code']['metrics_version']),
                         ('abc123', False, 'metrics-v1'))
        self.assertTrue(m['condition']['dataset_run'])
        self.assertEqual(m['condition']['runner_protocol'], self.conditions['runner_protocol'])
        # S-1: this session reached max_steps with 7/16 tests, so it is not normal.
        self.assertEqual(self.analysis['termination']['reason'], 'max_steps')
        self.assertFalse(m['judgement']['normal_session'])
        self.assertEqual(m['judgement_time']['n'], len(observations))
        self.assertEqual(m['judgement_time']['p50_ms'], (len(observations) + 1) / 2)
        self.assertEqual(m['judgement_time']['p99_ms'], float(len(observations)))
        self.assertEqual(m['credits']['status'], 'measured')
        self.assertEqual(m['replay']['status'], 'unmeasured')
        self.assertTrue(m['validity']['evidence']['isolation_ok'])
        self.assertEqual(m['validity']['class'], 'unclassified')
        self.assertEqual(m['notes'], ['operator note'])

    def test_credits_match_the_user_recorded_gateway_usage(self):
        # C-14 input: monthly_allocated.used 4260.62669 -> 4391.44169 for this session.
        m = self.build({**self.conditions, 'git_state_status': 'unmeasured', 'git_commit': None,
                        'git_dirty': None}, self.observations)
        self.assertAlmostEqual(m['credits']['value'], round(4391.44169 - 4260.62669, 5), places=5)
        self.assertTrue(any(n.startswith('git_commit is null') for n in m['notes']))

    def test_missing_judgement_time_is_unmeasured_not_zero(self):
        m = self.build({**self.conditions, 'git_state_status': 'measured', 'git_commit': 'x', 'git_dirty': False},
                       copy.deepcopy(self.observations))
        self.assertEqual(m['judgement_time']['status'], 'unmeasured')
        self.assertIsNone(m['judgement_time']['p99_ms'])

    def test_sessions_without_git_state_keep_their_manifest_version(self):
        self.assertNotIn('git_state_status', self.conditions)
        self.assertEqual(tool.manifest(self.analysis, 'verify', [])['manifest_version'], 'session-manifest-v0.2')


if __name__ == '__main__':
    unittest.main()
