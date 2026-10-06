"""Aggregation with several plans and the exclusion list (C-18-7 part 3, DM-78, DM-79). Offline: the committed trial
records, and copies of one in a temporary runs root."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools import aggregate_demo, demo_exclusions

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs/demo'
CT_STALL = 'DEMO-CT-stall-v1-819eb0783b724840b9333f480a599666'
TIMEOUT_ERROR = "RuntimeError: InternalServerError: Error code: 502 - {'error': 'Upstream connection failed'}"
OLD, NEW = 'a' * 40, 'b' * 40
TRIALS = ['demo-trial-c18-2', 'demo-trial-c18-3', 'demo-trial-c18-4', 'demo-trial-c18-5']


def digest(result):
    text = json.dumps(result, ensure_ascii=False, indent=1) + '\n'
    return (hashlib.sha256(text.encode()).hexdigest(),
            hashlib.sha256(aggregate_demo.markdown(result).encode()).hexdigest())


class Unchanged(unittest.TestCase):
    """Hashes of the output before C-18-7 (same records, same code path)."""

    def test_one_plan_without_a_list_is_byte_identical(self):
        self.assertEqual(digest(aggregate_demo.aggregate(['demo-trial-c18-5'])),
                         ('6a10c6625a8b3e130b187726adb345db9b23602bd001f6e2aa5d4252e7eac8b5',
                          '7b1a358b420807f339c0f2f75d00fb518a82cb18724c21b4ce499c1437490946'))

    def test_several_plans_only_add_the_commit_counts(self):
        result = aggregate_demo.aggregate(TRIALS)
        commits = result.pop('git_commits')
        self.assertEqual(digest(result)[0], '99a426c297f03d2659f299c4224863ac74480fcf9e7db2279bc79d1cebe23f28')
        self.assertEqual(sum(commits['all'].values()), result['sessions'])
        self.assertEqual(set(commits['by_plan']), set(TRIALS))


class WithList(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs, self.logs = self.root / 'runs', self.root / 'logs'
        self.runs.mkdir()
        self.logs.mkdir()

    def copy(self, name, *, plan='demo-main-v1', repeat=1, commit=OLD, rerun_of=None, runner_error=False):
        target = self.runs / name
        shutil.copytree(RUNS / CT_STALL, target)
        conditions = json.loads((target / 'conditions.json').read_text(encoding='utf-8'))
        conditions['git_commit'] = commit
        conditions['batch'] = {**(conditions.get('batch') or {}), 'plan_id': plan, 'mode': 'observe', 'repeat': repeat,
                               'item': f'DEMO-CT-stall-v1:observe:{repeat}', 'rerun_of': rerun_of}
        (target / 'conditions.json').write_text(json.dumps(conditions), encoding='utf-8')
        if runner_error:
            summary = json.loads((target / 'summary.json').read_text(encoding='utf-8'))
            summary.update(termination_reason='runner_error', error=TIMEOUT_ERROR)
            (target / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
            (self.logs / (name + '.json')).write_text(json.dumps({'turns': [
                {'turn': 5, 'status_code': 502, 'upstream_ms': 120044.0, 'response_body': {}}]}))
        return name

    def setup_runs(self):
        failed = self.copy('DEMO-CT-stall-v1-first', runner_error=True)
        self.copy('DEMO-CT-stall-v1-rerun', commit=NEW, rerun_of=failed)
        self.copy('DEMO-CT-stall-v1-two', repeat=2)
        self.copy('DEMO-CT-stall-v1-lr2', plan='demo-main-v1-lr2', repeat=3)
        return demo_exclusions.build(['demo-main-v1', 'demo-main-v1-lr2'], runs_root=self.runs, logs_root=self.logs)

    def test_excluded_sessions_leave_and_reruns_count(self):
        listing = self.setup_runs()
        plans = ['demo-main-v1', 'demo-main-v1-lr2']
        without = aggregate_demo.aggregate(plans, runs_root=self.runs)
        self.assertEqual(without['scenarios'][0]['classes'], {'success': 0, 'stalled': 3, 'escalated': 0, 'other': 1})
        result = aggregate_demo.aggregate(plans, runs_root=self.runs, exclusion_list=listing)
        table = result['scenarios'][0]
        self.assertEqual((result['sessions'], table['observe_runs'], table['stalled_k_of_n']), (3, 3, '3 / 3'))
        self.assertEqual(table['classes']['other'], 0)
        listed = result['exclusion_list']
        self.assertEqual((listed['by_code'], listed['replaced'], listed['sessions_not_in_list']),
                         ({'env_upstream_timeout': 1}, 1, []))
        self.assertEqual(listed['sessions'], [{'session_id': 'DEMO-CT-stall-v1-first', 'scenario_id': 'DEMO-CT-stall-v1',
                                               'mode': 'observe', 'repeat': 1, 'plan_id': 'demo-main-v1',
                                               'code': 'env_upstream_timeout',
                                               'replaced_by': 'DEMO-CT-stall-v1-rerun'}])
        self.assertEqual(result['git_commits'], {'all': {NEW: 1, OLD: 2},
                                                 'by_plan': {'demo-main-v1': {NEW: 1, OLD: 1},
                                                             'demo-main-v1-lr2': {OLD: 1}}})
        self.assertEqual(result['excluded'], [])
        text = aggregate_demo.markdown(result)
        self.assertIn('뺀 세션 1 개 (사유별 : env_upstream_timeout 1), 그중 재실행으로 대체 1 개', text)
        self.assertIn('- 커밋별 세션 : demo-main-v1 aaaaaaa 1, bbbbbbb 1; demo-main-v1-lr2 aaaaaaa 1', text)

    def test_a_list_older_than_the_records_says_so(self):
        listing = self.setup_runs()
        self.copy('DEMO-CT-stall-v1-late', repeat=4)
        result = aggregate_demo.aggregate(['demo-main-v1'], runs_root=self.runs, exclusion_list=listing)
        self.assertEqual(result['exclusion_list']['sessions_not_in_list'], ['DEMO-CT-stall-v1-late'])
        self.assertIn('목록에 없는 세션 1 개', aggregate_demo.markdown(result))

    def test_only_an_exclusion_file_is_taken(self):
        with self.assertRaises(ValueError):
            aggregate_demo.aggregate(['demo-main-v1'], runs_root=self.runs, exclusion_list={'sessions': {}})


if __name__ == '__main__':
    unittest.main()
