"""Account label correction (C-18-8 part 2, DM-81 ②): the selection rule, and aggregate_demo's corrected totals next to
the unchanged label totals. Offline: synthetic conditions files and the committed trial records."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import aggregate_demo, demo_account_corrections

TRIAL = 'demo-trial-c18-5'
RERUN, MAIN = 'b' * 40, 'a' * 40


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.runs = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def session(self, name, *, plan='demo-main-v1', commit=RERUN, lane=1, label='A'):
        (self.runs / name).mkdir()
        (self.runs / name / 'conditions.json').write_text(json.dumps({
            'account_label': label, 'git_commit': commit,
            'batch': {'plan_id': plan, 'lane': lane, 'item': f'X:observe:{lane}', 'rerun_of': None}}))

    def test_rule_picks_plan_commit_and_lane(self):
        self.session('rerun-1', lane=1, label='A')
        self.session('rerun-3', lane=3, label='C')
        self.session('main-1', commit=MAIN, lane=1)
        self.session('lane-4', lane=4, label='D')
        self.session('other-plan', plan='demo-main-v1-mr2', lane=1)
        result = demo_account_corrections.build('demo-main-v1', RERUN, {1: 'C', 3: 'B'}, 'PM', runs_root=self.runs)
        self.assertEqual([(s['session_id'], s['label'], s['actual']) for s in result['sessions']],
                         [('rerun-1', 'A', 'C'), ('rerun-3', 'C', 'B')])
        self.assertEqual((result['account_corrections_version'], result['lane_accounts'], result['source']),
                         ('demo-account-corrections-v1', {'1': 'C', '3': 'B'}, 'PM'))

    def test_lane_account_pairs(self):
        self.assertEqual(demo_account_corrections.lane_accounts(['1=C', '2=A']), {1: 'C', 2: 'A'})
        with self.assertRaises(ValueError):
            demo_account_corrections.lane_accounts(['C'])


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.plain = aggregate_demo.aggregate([TRIAL])
        self.rows = self.plain['session_rows']

    def corrections(self, actual):
        return {'account_corrections_version': 'demo-account-corrections-v1', 'source': 'PM 진술 (시험)',
                'sessions': [{'session_id': r['session_id'], 'actual': actual} for r in self.rows[:1]]}

    def test_corrected_totals_sit_next_to_the_labels(self):
        result = aggregate_demo.aggregate([TRIAL], account_corrections=self.corrections('Z'))
        self.assertEqual(result['accounts'], self.plain['accounts'])
        corrected = result.pop('accounts_corrected')
        self.assertEqual(result, self.plain)
        moved = self.rows[0]
        self.assertEqual(corrected['accounts']['Z'], {'sessions': 1, 'credits_measured': moved['credits_measured']})
        self.assertEqual((corrected['sessions_in_file'], corrected['sessions_counted'], corrected['sessions_relabelled']),
                         (1, 1, 1))
        self.assertEqual(sum(v['sessions'] for v in corrected['accounts'].values()), result['sessions'])
        self.assertAlmostEqual(sum(v['credits_measured'] for v in corrected['accounts'].values()),
                               sum(v['credits_measured'] for v in result['accounts'].values()), places=4)

    def test_markdown_adds_one_section(self):
        result = aggregate_demo.aggregate([TRIAL], account_corrections=self.corrections('Z'))
        text, plain = aggregate_demo.markdown(result), aggregate_demo.markdown(self.plain)
        self.assertTrue(text.startswith(plain))
        self.assertIn('## 계정별 실측 크레딧 — 보정 표 적용 (PM 진술 (시험))', text)

    def test_same_account_is_not_relabelled(self):
        label = self.rows[0]['account_label']
        corrected = aggregate_demo.aggregate([TRIAL], account_corrections=self.corrections(label))['accounts_corrected']
        self.assertEqual((corrected['sessions_relabelled'], corrected['accounts']), (0, self.plain['accounts']))

    def test_only_a_corrections_file_is_taken(self):
        with self.assertRaises(ValueError):
            aggregate_demo.aggregate([TRIAL], account_corrections={'sessions': []})


if __name__ == '__main__':
    unittest.main()
