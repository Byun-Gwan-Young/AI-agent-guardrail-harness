"""Exclusion rules added in C-18-8 part 1 (DM-81): search key refused, supplement plans as replacements, a second
runner_error, per-item states. Offline: synthetic session folders and proxy logs."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import demo_exclusions

PROXY_502 = "RuntimeError: InternalServerError: Error code: 502 - {'error': 'Upstream connection failed'}"
GATEWAY_504 = 'RuntimeError: InternalServerError: Error code: 504'
PLANS = ('demo-main-v1', 'demo-main-v1-lr2', 'demo-main-v1-mr2')


class C188ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs, self.logs = self.root / 'runs', self.root / 'logs'
        self.runs.mkdir()
        self.logs.mkdir()

    def session(self, session_id, item, *, plan='demo-main-v1', reason='success', error=None, rerun_of=None,
                turns=None, searches=None):
        folder = self.runs / session_id
        folder.mkdir()
        (folder / 'conditions.json').write_text(json.dumps({
            'scenario': {'scenario_id': item.split(':')[0]}, 'account_label': 'B', 'git_commit': 'c0ffee',
            'git_dirty': False, 'batch': {'plan_id': plan, 'item': item, 'lane': 2, 'rerun_of': rerun_of}}))
        (folder / 'summary.json').write_text(json.dumps({'termination_reason': reason, 'steps': 4, 'error': error}))
        if turns is not None:
            (self.logs / (session_id + '.json')).write_text(json.dumps({'turns': turns}))
        if searches is not None:
            (folder / 'search').mkdir()
            (folder / 'search' / 'records.jsonl').write_text(
                ''.join(json.dumps({'outcome': o, 'http_status': s}) + '\n' for o, s in searches))
        return session_id

    def build(self, plans=PLANS):
        return demo_exclusions.build(plans, runs_root=self.runs, logs_root=self.logs)

    def test_refused_key_excludes_and_the_supplement_replaces(self):
        self.session('MR-401', 'DEMO-MR-normal-v1:observe:3', reason='escalated', searches=[('http_error', 401)] * 4)
        self.session('MR-403', 'DEMO-MR-stall-v1:block:3', reason='escalated',
                     searches=[('ok', 200), ('http_error', 403)])
        self.session('MR-nosearch', 'DEMO-MR-stall-v1:observe:1', reason='escalated')
        self.session('MR-ok', 'DEMO-MR-normal-v1:observe:2', searches=[('ok', 200), ('http_error', 429)])
        self.session('MR-sup', 'DEMO-MR-normal-v1:observe:3', plan='demo-main-v1-mr2', searches=[('ok', 200)])
        result = self.build()
        sessions = result['sessions']
        self.assertEqual({k: v['excluded'] for k, v in sessions.items()},
                         {'MR-401': 'env_search_key_invalid', 'MR-403': 'env_search_key_invalid',
                          'MR-nosearch': None, 'MR-ok': None, 'MR-sup': None})
        self.assertEqual(sessions['MR-401']['evidence']['search_outcomes'], {'http_error:401': 4})
        self.assertEqual(sessions['MR-401']['replaced_by'], 'MR-sup')
        self.assertIsNone(sessions['MR-403']['replaced_by'])
        self.assertEqual(result['items']['DEMO-MR-normal-v1:observe:3'], {'state': 'valid', 'sessions': ['MR-sup']})
        self.assertEqual(result['items']['DEMO-MR-stall-v1:block:3'],
                         {'state': 'no_valid_session', 'sessions': ['MR-403'], 'codes': ['env_search_key_invalid']})
        self.assertEqual((result['counts']['replaced'], result['unresolved']), (1, []))

    def test_main_run_lr_is_still_search_unavailable(self):
        self.session('LR-main', 'DEMO-LR-normal-v1:observe:1', reason='escalated', searches=[('http_error', 403)])
        self.assertEqual(self.build()['sessions']['LR-main']['excluded'], 'env_search_unavailable')

    def test_second_runner_error_is_incomplete_with_its_cause(self):
        first = self.session('CL-first', 'DEMO-CL-stall-v1:observe:2', reason='runner_error', error=PROXY_502,
                             turns=[{'turn': 62, 'status_code': 502, 'upstream_ms': 120039, 'response_body': {}}])
        self.session('CL-second', 'DEMO-CL-stall-v1:observe:2', reason='runner_error', error=GATEWAY_504,
                     rerun_of=first,
                     turns=[{'turn': 76, 'status_code': 504, 'upstream_ms': 300479.4, 'response_body': {}}])
        result = self.build()
        second = result['sessions']['CL-second']
        self.assertEqual((result['sessions']['CL-first']['replaced_by'], second['excluded'], second['replaced_by']),
                         ('CL-second', 'incomplete_after_retry', None))
        self.assertEqual(second['evidence']['cause'], {'code': 'env_upstream_504', 'why': None})
        self.assertEqual(second['evidence']['failing_turn'],
                         {'turn': 76, 'status_code': 504, 'upstream_ms': 300479, 'empty_body': True})
        self.assertEqual(result['items']['DEMO-CL-stall-v1:observe:2'],
                         {'state': 'no_valid_session', 'sessions': ['CL-second'], 'codes': ['incomplete_after_retry']})
        self.assertEqual(result['counts']['by_code']['incomplete_after_retry'], 1)

    def test_a_first_504_is_not_decided(self):
        self.session('CT-504', 'DEMO-CT-stall-v1:observe:1', reason='runner_error', error=GATEWAY_504,
                     turns=[{'turn': 5, 'status_code': 504, 'upstream_ms': 300146, 'response_body': {}}])
        result = self.build()
        self.assertIsNone(result['sessions']['CT-504']['excluded'])
        self.assertEqual(result['unresolved'], [{'session_id': 'CT-504', 'why': 'failing turn status 504 (first failure)'}])

    def test_supplement_conflicts_are_unresolved(self):
        # A valid main-run session already holds the item.
        self.session('CS-ok', 'DEMO-CS-normal-v1:observe:1')
        self.session('CS-sup', 'DEMO-CS-normal-v1:observe:1', plan='demo-main-v1-mr2')
        # Two supplement sessions for one item.
        self.session('MR-401', 'DEMO-MR-stall-v1:observe:4', reason='escalated', searches=[('http_error', 401)])
        self.session('MR-sup-a', 'DEMO-MR-stall-v1:observe:4', plan='demo-main-v1-mr2')
        self.session('MR-sup-b', 'DEMO-MR-stall-v1:observe:4', plan='demo-main-v1-lr2')
        # A supplement item the main run never tried.
        self.session('LR-sup', 'DEMO-LR-stall-v1:block:3', plan='demo-main-v1-lr2', reason='user_interrupted')
        result = self.build()
        self.assertEqual([u['session_id'] for u in result['unresolved']], ['CS-sup', 'LR-sup', 'MR-sup-a', 'MR-sup-b'])
        self.assertIsNone(result['sessions']['MR-401']['replaced_by'])

    def test_a_rerun_comes_before_the_supplement(self):
        first = self.session('CT-first', 'DEMO-CT-stall-v1:block:3', reason='runner_error', error=PROXY_502,
                             turns=[{'turn': 10, 'status_code': 502, 'upstream_ms': 120039, 'response_body': {}}])
        self.session('CT-rerun', 'DEMO-CT-stall-v1:block:3', reason='guardrail_stop', rerun_of=first)
        self.session('CT-sup', 'DEMO-CT-stall-v1:block:3', plan='demo-main-v1-mr2', reason='guardrail_stop')
        result = self.build()
        self.assertEqual(result['sessions']['CT-first']['replaced_by'], 'CT-rerun')
        self.assertEqual([u['session_id'] for u in result['unresolved']], ['CT-sup'])

    def test_running_item_state(self):
        folder = self.runs / 'running'
        folder.mkdir()
        (folder / 'conditions.json').write_text(json.dumps({
            'scenario': {'scenario_id': 'DEMO-CS-stall-v1'}, 'batch': {'plan_id': 'demo-main-v1',
                                                                       'item': 'DEMO-CS-stall-v1:block:3'}}))
        self.assertEqual(self.build()['items'], {'DEMO-CS-stall-v1:block:3': {'state': 'unfinished', 'sessions': []}})


if __name__ == '__main__':
    unittest.main()
