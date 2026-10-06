"""Exclusion and replacement list (C-18-7 part 1, DM-78, DM-79). Offline: synthetic session folders and proxy logs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import demo_exclusions

PROXY_502 = "RuntimeError: InternalServerError: Error code: 502 - {'error': 'Upstream connection failed'}"
UPSTREAM_502 = 'RuntimeError: InternalServerError: 502 Bad Gateway'


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs, self.logs = self.root / 'runs', self.root / 'logs'
        self.runs.mkdir()
        self.logs.mkdir()

    def session(self, session_id, item, *, plan='demo-main-v1', reason='success', error=None, rerun_of=None,
                turns=None, searches=None, log_in_folder=False, summary=True):
        folder = self.runs / session_id
        folder.mkdir()
        scenario_id = item.split(':')[0]
        (folder / 'conditions.json').write_text(json.dumps({
            'scenario': {'scenario_id': scenario_id}, 'account_label': 'A', 'git_commit': 'c0ffee', 'git_dirty': False,
            'batch': {'plan_id': plan, 'item': item, 'lane': 1, 'rerun_of': rerun_of}}))
        if summary:
            (folder / 'summary.json').write_text(json.dumps({'termination_reason': reason, 'steps': 3, 'error': error}))
        if turns is not None:
            target = folder / 'session.json' if log_in_folder else self.logs / (session_id + '.json')
            target.write_text(json.dumps({'turns': turns}))
        if searches is not None:
            (folder / 'search').mkdir()
            (folder / 'search' / 'records.jsonl').write_text(
                ''.join(json.dumps({'outcome': o, 'http_status': s}) + '\n' for o, s in searches))
        return session_id

    def build(self, plans=('demo-main-v1', 'demo-main-v1-lr2')):
        return demo_exclusions.build(plans, runs_root=self.runs, logs_root=self.logs)

    def test_rules(self):
        ok = {'turn': 1, 'status_code': 200, 'upstream_ms': 15000.0, 'response_body': {'choices': []}}
        self.session('CT-timeout', 'DEMO-CT-stall-v1:observe:1', reason='runner_error', error=PROXY_502,
                     turns=[ok, {'turn': 2, 'status_code': 502, 'upstream_ms': 120043.2, 'response_body': {}}])
        self.session('MR-502', 'DEMO-MR-normal-v1:observe:5', reason='runner_error', error=UPSTREAM_502,
                     turns=[ok, {'turn': 2, 'status_code': 502, 'upstream_ms': 42289.0, 'response_body': {}}],
                     log_in_folder=True)
        self.session('LR-main', 'DEMO-LR-normal-v1:observe:1', reason='escalated',
                     searches=[('http_error', 429), ('timeout', None)])
        self.session('LR-main-nosearch', 'DEMO-LR-normal-v1:observe:5', reason='escalated', searches=[])
        self.session('LR-supplement', 'DEMO-LR-normal-v1:observe:1', plan='demo-main-v1-lr2',
                     searches=[('ok', 200), ('ok', 200)])
        self.session('LR-cut', 'DEMO-LR-stall-v1:block:3', plan='demo-main-v1-lr2', reason='user_interrupted')
        self.session('CL-fine', 'DEMO-CL-normal-v1:observe:2', reason='success')
        self.session('trial', 'DEMO-CL-normal-v1:observe:1', plan='demo-trial-c18-2', reason='runner_error')
        result = self.build()
        codes = {k: v['excluded'] for k, v in result['sessions'].items()}
        self.assertEqual(codes, {'CT-timeout': 'env_upstream_timeout', 'MR-502': 'env_upstream_502',
                                 'LR-main': 'env_search_unavailable', 'LR-main-nosearch': 'env_search_unavailable',
                                 'LR-supplement': None, 'LR-cut': 'run_interrupted', 'CL-fine': None})
        self.assertEqual(result['sessions']['CT-timeout']['evidence']['failing_turn'],
                         {'turn': 2, 'status_code': 502, 'upstream_ms': 120043, 'empty_body': True})
        self.assertEqual(result['sessions']['LR-main']['evidence']['search_outcomes'],
                         {'http_error:429': 1, 'timeout:None': 1})
        self.assertEqual(result['sessions']['LR-main-nosearch']['notes'], ['no_search_attempt'])
        self.assertEqual(result['counts']['by_code'], {'env_search_unavailable': 2, 'env_upstream_timeout': 1,
                                                       'env_upstream_502': 1, 'run_interrupted': 1})
        # The supplement's LR item stands in for the excluded main-run one; the others have no valid session yet.
        self.assertEqual(result['items_without_valid_session'],
                         ['DEMO-CT-stall-v1:observe:1', 'DEMO-LR-normal-v1:observe:5', 'DEMO-LR-stall-v1:block:3',
                          'DEMO-MR-normal-v1:observe:5'])
        self.assertEqual(result['git_commits'], {'c0ffee dirty=False': 7})

    def test_rerun_replaces_and_counts_as_the_item(self):
        failed = self.session('CT-timeout', 'DEMO-CT-stall-v1:observe:1', reason='runner_error', error=PROXY_502,
                              turns=[{'turn': 1, 'status_code': 502, 'upstream_ms': 120040, 'response_body': {}}])
        self.session('CT-rerun', 'DEMO-CT-stall-v1:observe:1', reason='max_steps', rerun_of=failed)
        result = self.build()
        self.assertEqual(result['sessions']['CT-timeout']['replaced_by'], 'CT-rerun')
        self.assertEqual(result['sessions']['CT-timeout']['excluded'], 'env_upstream_timeout')
        self.assertIsNone(result['sessions']['CT-rerun']['excluded'])
        self.assertEqual((result['counts']['replaced'], result['items_without_valid_session']), (1, []))

    def test_a_failed_rerun_is_excluded_and_the_item_stays_open(self):
        failed = self.session('first', 'DEMO-CT-stall-v1:observe:1', reason='runner_error', error=PROXY_502,
                              turns=[{'turn': 1, 'status_code': 502, 'upstream_ms': 120040, 'response_body': {}}])
        self.session('second', 'DEMO-CT-stall-v1:observe:1', reason='runner_error', error=PROXY_502, rerun_of=failed,
                     turns=[{'turn': 1, 'status_code': 502, 'upstream_ms': 600020, 'response_body': {}}])
        result = self.build()
        self.assertEqual([result['sessions'][s]['excluded'] for s in ('first', 'second')],
                         ['env_upstream_timeout', 'env_upstream_timeout'])
        self.assertEqual(result['items_without_valid_session'], ['DEMO-CT-stall-v1:observe:1'])

    def test_unmatched_runner_error_is_unresolved_not_excluded(self):
        self.session('short', 'DEMO-CL-normal-v1:observe:1', reason='runner_error', error=PROXY_502,
                     turns=[{'turn': 1, 'status_code': 502, 'upstream_ms': 800, 'response_body': {}}])
        self.session('nolog', 'DEMO-CL-normal-v1:observe:2', reason='runner_error', error=UPSTREAM_502)
        self.session('other', 'DEMO-CL-normal-v1:observe:3', reason='runner_error', error='RuntimeError: 500',
                     turns=[{'turn': 1, 'status_code': 500, 'upstream_ms': 900, 'response_body': {'error': 'x'}}])
        result = self.build()
        self.assertEqual([result['sessions'][s]['excluded'] for s in ('short', 'nolog', 'other')], [None] * 3)
        self.assertEqual([u['session_id'] for u in result['unresolved']], ['nolog', 'other', 'short'])
        out = self.root / 'out.json'
        argv = ['demo_exclusions.py', '--plan', 'demo-main-v1', '--runs-root', str(self.runs), '--logs-root',
                str(self.logs), '--output', str(out)]
        with mock.patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(demo_exclusions.main(), 1)
        self.assertEqual(json.loads(out.read_text())['counts']['unresolved'], 3)

    def test_running_session_is_left_undecided(self):
        self.session('running', 'DEMO-CS-stall-v1:block:3', summary=False)
        result = self.build()
        self.assertEqual(([u['session_id'] for u in result['unfinished']], result['sessions']), (['running'], {}))
        self.assertEqual(result['items_without_valid_session'], ['DEMO-CS-stall-v1:block:3'])

    def test_block_refusals_are_not_failures(self):
        self.session('blocked', 'DEMO-CT-stall-v1:block:1', reason='guardrail_stop',
                     turns=[{'turn': 1, 'status_code': 200, 'upstream_ms': 1, 'response_body': {}},
                            {'turn': 2, 'status_code': 403, 'upstream_ms': 0, 'response_body': {'error': {}}}])
        self.assertIsNone(self.build()['sessions']['blocked']['excluded'])

    def test_same_records_same_output(self):
        self.session('CL-fine', 'DEMO-CL-normal-v1:observe:2')
        self.assertEqual(json.dumps(self.build()), json.dumps(self.build()))


if __name__ == '__main__':
    unittest.main()
