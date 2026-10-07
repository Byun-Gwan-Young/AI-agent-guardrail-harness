"""C-19-6 : demo records loader, SQL check queries and read-only API, offline.

PostgreSQL is replaced by an in-memory SQLite database built from service/schema.sql (same statements, type names
substituted). The API is called through FastAPI's TestClient (no socket). Tests against a real PostgreSQL are in
service/test_live_db.py and run only with GUARDRAIL_DB_URL set (separate command).
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from service import api, load_demo, queries  # noqa: E402
from service.store import (RecordError, forbidden_fields, key_hits, postgres_store, redact_url,  # noqa: E402
                           sqlite_schema, sqlite_store)

SESSION = 'DEMO-CL-stall-v1-8d760276f7cd4bd4ac01cfc94d78a808'
HEADLINE_KEYS = {  # the keys of the C-19-3 screen's headline (tools/demo_ui.py headline, branch c19-3-demo-ui)
    'observe_sessions', 'observe_classes', 'block_sessions', 'normal_runs', 'normal_success', 'false_positive',
    'false_positive_by_task', 'blocked_before_success', 'blocked_before_success_sessions', 'stall_runs',
    'stall_reached', 'stall_detected', 'stall_detected_by_task', 'missed', 'stall_escalated', 't1_stall_stop',
    'saving_mean', 'saving_by_type', 'block', 'credits_measured_total'}


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


class Rows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_demo.build_rows()
        cls.aggregate = load(load_demo.AGGREGATE)
        cls.exclusions = load(load_demo.EXCLUSIONS)
        cls.sessions = {s['session_id']: s for s in cls.rows['sessions']}

    def test_every_committed_session_folder_is_a_row(self):
        folders = {p.name for p in (ROOT / load_demo.RUNS).iterdir() if (p / 'record' / 'replay.json').is_file()}
        self.assertEqual(set(self.sessions), folders)
        replay_steps = sum(len(load(f'{load_demo.RUNS}/{s}/record/replay.json')['steps']) for s in folders)
        self.assertEqual(len(self.rows['steps']), replay_steps)

    def test_validity_follows_aggregate_and_exclusion_list(self):
        valid = {s for s, r in self.sessions.items() if r['validity'] == 'valid'}
        self.assertEqual(valid, {r['session_id'] for r in self.aggregate['session_rows']})
        excluded = {s: e['excluded'] for s, e in self.exclusions['sessions'].items() if e['excluded']}
        rows = {s: r['exclusion_code'] for s, r in self.sessions.items() if r['validity'] == 'excluded'}
        # 445ab1ba (run_interrupted, 0 step) has no record folder (DM-82 ②): the one excluded session not loaded.
        self.assertEqual({s: c for s, c in excluded.items() if s in self.sessions}, rows)
        self.assertEqual(sorted(set(excluded) - set(self.sessions)), ['DEMO-LR-stall-v1-445ab1ba6476456fbef0ab83d64e11df'])
        others = {r['plan_kind'] for r in self.sessions.values() if r['validity'] == 'not_counted'}
        self.assertEqual(others, {'trial', 'none'})

    def test_counted_sessions_carry_the_aggregate_values(self):
        for row in self.aggregate['session_rows']:
            got = self.sessions[row['session_id']]
            for key, column in (('steps', 'steps'), ('tokens', 'tokens_total'), ('class', 'class'),
                                ('first_stop_step', 'first_stop_step'), ('first_stop_template', 'first_stop_template'),
                                ('first_stop_text', 'first_stop_text'), ('stop_steps', 'stop_steps'),
                                ('credits_measured', 'credits_measured'), ('credits_estimated', 'credits_estimated'),
                                ('stall_start', 'stall_start'), ('detection_delay', 'detection_delay'),
                                ('mode', 'mode'), ('task_type', 'task_type'), ('account_label', 'account_label'),
                                ('termination_reason', 'termination_reason'), ('escalated_by', 'escalated_by')):
                self.assertEqual(got[column], row[key], (row['session_id'], key))
            if row['if_stopped']:
                self.assertEqual(got['if_stopped_token_ratio'], row['if_stopped']['token_ratio'])

    def test_scenarios_from_the_map(self):
        scenarios = {s['scenario_id']: s for s in self.rows['scenarios']}
        demo = {k: v for k, v in scenarios.items() if k.startswith('DEMO-')}
        self.assertEqual(set(demo), set(load(load_demo.FREEZE)['scenario_ids']))
        self.assertTrue(all(v['frozen'] and v['korean_name'] for v in demo.values()))
        for table in self.aggregate['scenarios']:
            self.assertEqual(demo[table['scenario_id']]['task_type'], table['task_type'])
        for sid, row in demo.items():
            if row['pair_scenario_id']:
                self.assertEqual(scenarios[row['pair_scenario_id']]['pair_scenario_id'], sid)
        self.assertIsNone(demo['DEMO-CT-N-v1']['pair_scenario_id'])
        self.assertEqual({k for k, v in scenarios.items() if v['task_type'] == 'dataset'},
                         {'A-1', 'A-1-v2', 'A-1-v3', 'A-1-v4'})

    def test_no_model_text_or_key_in_rows_and_same_rows_twice(self):
        self.assertEqual(forbidden_fields([s['facts'] for s in self.rows['steps']]), [])
        self.assertEqual(key_hits(json.dumps(self.rows, ensure_ascii=False)), [])
        self.assertEqual(load_demo.build_rows(), self.rows)


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_demo.build_rows()
        cls.store = sqlite_store(cls.rows)
        cls.addClassCleanup(cls.store.close)

    def test_sql_reproduces_aggregate_and_report_numbers(self):
        result = queries.check(self.store, load(load_demo.AGGREGATE))
        self.assertEqual([c['check'] for c in result['comparisons'] if not c['same']], [])
        self.assertTrue(result['ok'])
        self.assertEqual(result['sessions_by_validity'], {'excluded': 30, 'not_counted': 18, 'valid': 67})
        self.assertEqual(result['judgement_ms']['n'], 613)

    def test_report_constants_are_the_report_text(self):
        text = (ROOT / 'reports/c19/final-report.md').read_text(encoding='utf-8')
        section = text.split('## 4. 발표용 숫자')[1].split('\n## ')[0]
        r = queries.REPORT_SECTION4
        for phrase in (f"정상판 오탐 {r['false_positive']} 회", f"성공한 정상판 {r['normal_success']} 세션",
                       f"성공을 막았을 세션 {r['blocked_before_success']} 회", f"교착판 탐지 {r['stall_detected']} 회",
                       f"관측 {r['stall_reached']} 세션", f"평균 절감률 {r['saving_mean_pct']}%",
                       f"CL {r['block_token_saving_pct']['DEMO-CL-stall-v1']}%",
                       f"CT {r['block_token_saving_pct']['DEMO-CT-stall-v1']}%"):
            self.assertIn(phrase, section)

    def test_a_changed_row_is_reported(self):
        rows = json.loads(json.dumps(self.rows))
        first = next(s for s in rows['sessions'] if s['validity'] == 'valid' and s['variant'] == 'normal'
                     and s['class'] == 'success' and s['first_stop_step'] is None)
        first['first_stop_step'] = 1
        store = sqlite_store(rows)
        self.addCleanup(store.close)
        result = queries.check(store, load(load_demo.AGGREGATE))
        self.assertFalse(result['ok'])
        self.assertIn('report 4: false positives', [c['check'] for c in result['comparisons'] if not c['same']])

    def test_replace_all_twice_gives_the_same_tables(self):
        store = sqlite_store(self.rows)
        self.addCleanup(store.close)
        before = store.query('SELECT * FROM sessions ORDER BY session_id')
        store.replace_all(self.rows)
        self.assertEqual(store.query('SELECT * FROM sessions ORDER BY session_id'), before)
        self.assertEqual(store.scalar('SELECT COUNT(*) FROM steps'), len(self.rows['steps']))

    def test_schema_types_and_offline_substitution(self):
        lite = sqlite_schema()
        for name in ('JSONB', 'TIMESTAMPTZ', 'DOUBLE PRECISION', 'BOOLEAN'):
            self.assertNotIn(name, lite)
        self.assertNotRegex(load_demo.ROOT.joinpath('service/schema.sql').read_text(), r'SERIAL|DROP ')


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store = sqlite_store(load_demo.build_rows())
        cls.addClassCleanup(store.close)
        cls.client = TestClient(api.create_app(store))

    def test_only_read_routes(self):
        empty = sqlite_store()
        self.addCleanup(empty.close)
        methods = {m for r in api.create_app(empty).routes for m in getattr(r, 'methods', ())}
        self.assertEqual(methods, {'GET', 'HEAD'})
        self.assertEqual(self.client.post('/api/summary').status_code, 405)
        self.assertEqual(self.client.get('/docs').status_code, 200)

    def test_summary(self):
        body = self.client.get('/api/summary').json()
        self.assertEqual(set(body['headline']), HEADLINE_KEYS)
        self.assertEqual([p['value'] for p in body['presentation']][:4], [4, 2, 8, 60.8])
        self.assertEqual(body['sessions_by_validity']['valid'], 67)

    def test_sessions_filters_and_one_session(self):
        get = lambda q: self.client.get('/api/sessions' + q).json()  # noqa: E731
        self.assertEqual(get('?validity=valid')['count'], 67)
        self.assertEqual(get('?validity=valid&mode=block')['count'], 13)
        self.assertEqual(get('?validity=excluded')['count'], 30)
        self.assertEqual(get('?validity=valid&class=success&variant=normal')['count'], 24)
        self.assertEqual(get('?scenario_id=DEMO-CT-stall-v1&validity=valid&mode=observe')['count'], 5)
        one = self.client.get(f'/api/sessions/{SESSION}').json()['session']
        self.assertEqual((one['first_stop_step'], one['scenario']['korean_name']),
                         (18, '코드 버그 수정 · 서로 어긋나는 테스트 · 교착판'))
        self.assertEqual(self.client.get('/api/sessions/nope').status_code, 404)
        self.assertEqual(self.client.get('/api/sessions/nope/steps').status_code, 404)

    def test_steps_are_the_replay_steps(self):
        body = self.client.get(f'/api/sessions/{SESSION}/steps').json()
        replay = load(f'{load_demo.RUNS}/{SESSION}/record/replay.json')['steps']
        self.assertEqual([{k: v for k, v in s.items() if k != 'judgement'} for s in body['steps']], replay)
        self.assertEqual(body['steps'][17]['stop']['text'], replay[17]['stop']['text'])
        self.assertIsInstance(body['steps'][0]['judgement']['judgement_ns'], int)

    def test_scenarios(self):
        rows = {s['scenario_id']: s for s in self.client.get('/api/scenarios').json()['scenarios']}
        self.assertEqual(rows['DEMO-CL-stall-v1']['sessions']['valid'], {'block': 3, 'observe': 4})
        self.assertEqual(rows['DEMO-CL-stall-v1']['aggregate']['stalled_k_of_n'], '4 / 4')

    def test_guard_withholds_model_text_and_keys(self):
        self.assertEqual(api.guarded({'steps': [{'narrative': 'x'}]}).status_code, 500)
        self.assertEqual(api.guarded({'tokens': {'reasoning': 'some text'}}).status_code, 500)
        self.assertEqual(api.guarded({'tokens': {'reasoning': 12}}).status_code, 200)
        self.assertEqual(api.guarded({'v': 'gsk_' + 'A' * 20}).status_code, 500)
        with mock.patch.dict(os.environ, {'KMU_API_KEY': 'value-of-a-key-123'}):
            self.assertEqual(api.guarded({'v': 'x value-of-a-key-123'}).status_code, 500)

    def test_loopback_only_and_url_required(self):
        with mock.patch('uvicorn.run') as run:
            self.assertEqual(api.main(['--host', '0.0.0.0']), 2)
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(api.main([]), 2)
            run.assert_not_called()
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RecordError):
            postgres_store()
        self.assertEqual(redact_url('fail postgresql://me:secret@127.0.0.1/x'), 'fail postgresql://me:***@127.0.0.1/x')

    def test_loader_refuses_model_text(self):
        self.assertEqual(forbidden_fields({'a': [{'thought': 'x'}]}), ['$.a[].thought'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in (load_demo.AGGREGATE, load_demo.EXCLUSIONS, load_demo.CORRECTIONS, load_demo.SCENARIO_MAP,
                         load_demo.FREEZE):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / path, root / path)
            record = root / load_demo.RUNS / SESSION / 'record'
            shutil.copytree(ROOT / load_demo.RUNS / SESSION / 'record', record)
            replay = json.loads((record / 'replay.json').read_text(encoding='utf-8'))
            replay['steps'][0]['report']['narrative'] = 'model text'
            (record / 'replay.json').write_text(json.dumps(replay), encoding='utf-8')
            with self.assertRaisesRegex(RecordError, 'model text fields'):
                load_demo.build_rows(root)


if __name__ == '__main__':
    unittest.main()
