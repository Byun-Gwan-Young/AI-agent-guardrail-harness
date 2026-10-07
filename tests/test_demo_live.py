"""C-19-4 : the live monitor (tools/demo_live.py), a read-only local server over the files a running demo session writes.

Checked with function calls and the in-process test client (no socket): a session grown one step at a time in a temp
folder shows one more step per write, the STOP step carries its explanation sentence, the end is seen from
summary.json, the rows equal the replay extraction of the same files, the server writes no file, responses hold no
narrative/reasoning field or key pattern (a response that would is refused), session IDs cannot leave the runs root,
the server binds 127.0.0.1 only, and the live script exists only in the served page (the file has no request code).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tools import demo_live, demo_ui, replay_demo

SID = 'DEMO-CT-stall-v1-0123456789abcdef0123456789abcdef'
STOP_TEXT = '최근 3 step 동안 기획·개발·검토 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/17.'


def conditions():
    return {'scenario': {'scenario_id': 'DEMO-CT-stall-v1', 'title': '시험 과제', 'termination': {'max_steps': 30}},
            'registration': {'role_labels': {'planner': '기획', 'developer': '개발', 'reviewer': '검토'}},
            'batch': {'plan_id': 'demo-live-test', 'lane': 1, 'lanes': 2, 'mode': 'observe', 'repeat': 1},
            'account_label': 'A', 'task_kind': 'artifact', 'guardrail_mode': 'observe'}


def step(n):
    agent = ('planner', 'developer', 'reviewer')[(n - 1) % 3]
    return {'step_id': n, 'agent': agent, 'llm_turns': [2 * n - 1, 2 * n], 'step_status': 'completed',
            'narrative': 'SECRET-NARRATIVE', 'failure_reasons': [],
            'observed_final_report': {'narrative': 'SECRET-NARRATIVE', 'open_issue_ids': ['requirements'],
                                      'info_items': ['x'], 'completion_declared': False, 'status': None},
            'acceptance': {'summary': {'passed': 7, 'tests': 17}}, 'tool_executions': [{'tool': 'read_file'}]}


def turn(t):
    return {'turn': t, 'status_code': 200, 'prompt_tokens': 1000, 'completion_tokens': 100, 'tokens': 1100,
            'in': 'raw input line', 'out': 'raw output line', 'response_body': {'usage': {}},
            'request_body': {'messages': [{'content': 'Bearer abcdefghijklmnop'}]}}


def observation(n):
    stop = n >= 3
    return {'step_id': n, 'progress': {'state': 'baseline' if n == 1 else 'stagnant'},
            'criteria': {'decision': 'deadlock' if stop else 'continue',
                         'explanation': {'template_id': 'E1', 'text': STOP_TEXT} if stop else None}}


class Session:
    def __init__(self, base):
        self.runs, self.logs = Path(base) / 'runs' / 'demo', Path(base) / 'logs' / 'demo'
        self.folder = self.runs / SID
        self.folder.mkdir(parents=True)
        self.logs.mkdir(parents=True)
        (self.folder / 'conditions.json').write_text(json.dumps(conditions(), ensure_ascii=False), encoding='utf-8')

    def log(self, k, status='active'):
        return {'session_id': SID, 'status': status, 'meta': {'model': 'glm-5.3-flash', 'guardrail_mode': 'observe'},
                'turns': [turn(t) for t in range(1, 2 * k + 1)], 'observations': [observation(n) for n in range(1, k + 1)]}

    def grow(self, k):
        (self.folder / 'steps.json').write_text(json.dumps([step(n) for n in range(1, k + 1)]), encoding='utf-8')
        (self.logs / f'{SID}.json').write_text(json.dumps(self.log(k), ensure_ascii=False), encoding='utf-8')

    def end(self, k):
        (self.folder / 'summary.json').write_text(json.dumps({'session_id': SID, 'termination_reason': 'max_steps',
                                                              'steps': k}), encoding='utf-8')
        (self.logs / f'{SID}.json').write_text(json.dumps(self.log(k, 'ended'), ensure_ascii=False), encoding='utf-8')
        (self.folder / 'session.json').write_text(json.dumps(self.log(k, 'ended'), ensure_ascii=False), encoding='utf-8')


def snapshot(base):
    return sorted((p.relative_to(base).as_posix(), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(base).rglob('*'))


class DemoLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.s = Session(self.base)
        self.client = TestClient(demo_live.create_app(runs_root=self.s.runs, logs_root=self.s.logs, page='<html></html>'))

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.json()

    def test_grows_one_step_per_write_and_stop_carries_sentence(self):
        seen = []
        for k in range(1, 6):
            self.s.grow(k)
            before = snapshot(self.base)
            view = self.get(f'/api/live/sessions/{SID}')['session']
            listing = self.get('/api/live/sessions')['sessions']
            self.assertEqual(snapshot(self.base), before, 'the server wrote a file')
            seen.append((len(view['step_rows']), view['first_stop'], view['live']['status']))
            self.assertEqual([s['id'] for s in listing], [SID])
            self.assertEqual(listing[0]['steps'], k)
            self.assertEqual(view['live']['in_progress']['step'], k + 1)
            if k >= 3:
                self.assertEqual(view['step_rows'][2]['stop'], {'t': 'E1', 'text': STOP_TEXT})
                self.assertEqual(view['stop_text'], STOP_TEXT)
        self.assertEqual(seen, [(1, None, 'running'), (2, None, 'running'), (3, 3, 'running'), (4, 3, 'running'),
                                (5, 3, 'running')])
        self.s.end(5)
        view = self.get(f'/api/live/sessions/{SID}')['session']
        self.assertEqual((view['live']['status'], view['class'], view['termination']), ('ended', 'stalled', 'max_steps'))
        self.assertIsNone(view['live']['in_progress'])
        self.assertEqual((view['mode'], view['account'], view['live']['lane'], view['type']), ('observe', 'A', 1, 'T2'))

    def test_rows_equal_the_replay_extraction(self):
        self.s.grow(4)
        self.s.end(4)
        view = self.get(f'/api/live/sessions/{SID}')['session']
        replay = replay_demo.extract(self.s.folder)
        self.assertEqual(view['step_rows'], json.loads(json.dumps(
            [demo_ui.slim_step(r, replay['role_labels']) for r in replay['steps']], ensure_ascii=False)))
        self.assertEqual(view['first_stop'], replay['first_stop_step'])

    def test_no_narrative_reasoning_raw_line_or_key_in_responses(self):
        self.s.grow(4)
        texts = json.dumps(self.get('/api/live/sessions')) + json.dumps(self.get(f'/api/live/sessions/{SID}'))
        for needle in ('SECRET-NARRATIVE', 'raw input line', 'raw output line', 'Bearer ', '"narrative"',
                       '"info_items"', '"reasoning'):
            self.assertNotIn(needle, texts)

    def test_response_with_a_key_or_forbidden_field_is_refused(self):
        self.assertRaises(demo_live.Unsafe, demo_live.checked, {'a': 'gsk_' + 'A' * 20})
        self.assertRaises(demo_live.Unsafe, demo_live.checked, {'a': 'tvly-' + 'b' * 20})
        self.assertRaises(demo_live.Unsafe, demo_live.checked, {'rows': [{'narrative': 'x'}]})
        with mock.patch.dict(os.environ, {'KMU_API_KEY': 'plain-key-value-123'}):
            self.assertRaises(demo_live.Unsafe, demo_live.checked, {'a': 'x plain-key-value-123 y'})
        self.s.grow(2)
        with mock.patch.object(demo_live, 'list_item', lambda v: {'id': v['id'], 'leak': 'gsk_' + 'Z' * 20}):
            response = self.client.get('/api/live/sessions')
        self.assertEqual((response.status_code, response.content), (500, b''))

    def test_session_id_stays_under_the_runs_root(self):
        self.s.grow(1)
        for bad in ('..', '..%2F..%2Fetc', '.hidden', 'x' * 200, 'no-such-session'):
            self.assertEqual(self.client.get('/api/live/sessions/' + bad).status_code, 404, bad)

    def test_session_without_proxy_log_yet(self):
        view = self.get(f'/api/live/sessions/{SID}')['session']
        self.assertEqual((view['step_rows'], view['live']['status'], view['live']['in_progress']['step']), ([], 'running', 1))

    def test_binds_loopback_only(self):
        calls = []
        demo_live.serve(8010, runner=lambda app, **kw: calls.append(kw), runs_root=self.s.runs, logs_root=self.s.logs,
                        page='<html></html>')
        self.assertEqual(calls, [{'host': '127.0.0.1', 'port': 8010, 'log_level': 'warning'}])
        self.assertEqual(demo_live.HOST, '127.0.0.1')
        source = Path(demo_live.__file__).read_text(encoding='utf-8')
        self.assertNotIn('0.0.0.0', source)
        self.assertNotIn("'--host'", source)

    def test_live_script_only_in_the_served_page(self):
        aggregate = demo_ui.load(demo_ui.ROOT / 'reports' / 'c19' / 'aggregate-main.json')
        data = demo_ui.collect(aggregate, runs_root=demo_ui.ROOT / 'runs' / 'demo')
        static, served = demo_ui.page(data), demo_ui.page(data, live=True)
        self.assertNotIn('fetch(', static)
        self.assertIn('실시간 서버가 꺼져 있습니다. 기록 재생을 쓰세요.', static)
        self.assertIn("fetch(u,{cache:'no-store'})", served)
        self.assertIn('/api/live/sessions', served)
        for text in (static, served):
            self.assertIn('<button id="nav-live" data-page="live">실시간 모니터</button>', text)
            self.assertNotRegex(text, r'data-planned="live"')
        page = TestClient(demo_live.create_app(runs_root=self.s.runs, logs_root=self.s.logs)).get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/api/live/sessions', page.text)


if __name__ == '__main__':
    unittest.main()
