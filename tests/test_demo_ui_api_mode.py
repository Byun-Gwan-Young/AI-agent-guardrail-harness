"""C-19-7 part 1 : the demo screen's query API mode (tools/demo_ui.py build --api), offline.

The API answers come from the C-19-6 query API (service/api.py) on the in-memory SQLite stand-in of the same rows
(FastAPI TestClient, no socket). The page's own mapping script (demo_ui.API_MAP) runs in node against those answers,
and every value the dashboard cards, the session table and the session steps draw must equal the values the page
carries in the file (demo_ui.collect). A failed or missing API rejects, so the page keeps the file records. Without
--api the page still has no request code (tests/test_demo_ui.py); with --api the request code runs only over http(s).
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from service import api, load_demo
from service.store import sqlite_store
from tools import demo_ui

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'reports' / 'c19' / 'aggregate-main.json'
NODE = shutil.which('node')
SESSION_KEYS = ('id', 'short', 'scenario', 'task', 'task_name', 'variant', 'type', 'mode', 'class', 'termination',
                'escalated_by', 'escalated_by_label', 'steps', 'max_steps', 'tokens', 'credits', 'first_stop', 'template',
                'stop_text', 'stop_steps', 'blocked_step', 'if_stopped', 'account', 'plan')
LOADED_KEYS = ('name', 'title', 'step_rows', 'replay')
DASHBOARD_KEYS = ('observe_sessions', 'observe_classes', 'block_sessions', 'normal_success', 'false_positive',
                  'false_positive_by_task', 'blocked_before_success', 'stall_reached', 'stall_detected', 'saving_mean')

RUN = r"""
const fs=require('fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));
%s
const R=input.responses;
const fake=async u=>{if(input.reject)throw new Error('connection refused');
 return {ok:Object.prototype.hasOwnProperty.call(R,u),status:Object.prototype.hasOwnProperty.call(R,u)?200:404,json:async()=>R[u]};};
(async()=>{try{const X=await apiLoad(fake,input.task_names);
  if(input.steps)for(const s of X.sessions)await apiSessionSteps(fake,s);
  for(const s of X.sessions){delete s.roles;delete s.loaded;}
  process.stdout.write(JSON.stringify({ok:true,X}));}
 catch(e){process.stdout.write(JSON.stringify({ok:false,error:String(e.message)}));}})();
"""


def run_node(responses, *, steps=True, reject=False):
    payload = {'responses': responses, 'task_names': demo_ui.TASK_NAMES, 'steps': steps, 'reject': reject}
    out = subprocess.run([NODE, '-e', RUN % demo_ui.API_MAP], input=json.dumps(payload), capture_output=True,
                         text=True, timeout=120, check=True)
    return json.loads(out.stdout)


class Fixture:
    data = responses = None

    @classmethod
    def get(cls):
        if cls.data is None:
            cls.data = demo_ui.collect(demo_ui.load(MAIN), runs_root=ROOT / 'runs' / 'demo')
            store = sqlite_store(load_demo.build_rows())
            try:
                client = TestClient(api.create_app(store))
                responses = {}
                for url in ('/api/summary', '/api/sessions?validity=valid'):
                    responses[url] = client.get(url).json()
                for row in responses['/api/sessions?validity=valid']['sessions']:
                    for url in (f"/api/sessions/{row['session_id']}", f"/api/sessions/{row['session_id']}/steps"):
                        responses[url] = client.get(url).json()
                cls.responses = responses
            finally:
                store.close()
        return cls.data, cls.responses


@unittest.skipUnless(NODE, 'node is not on PATH')
class ApiModeSameNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.responses = Fixture.get()
        cls.result = run_node(cls.responses)

    def test_api_mode_loads(self):
        self.assertTrue(self.result['ok'], self.result.get('error'))

    def test_dashboard_cards_same_numbers(self):
        api_h, file_h = self.result['X']['headline'], self.data['headline']
        for key in DASHBOARD_KEYS:
            self.assertEqual(api_h[key], file_h[key], key)
        self.assertEqual(self.result['X']['judgement_ms'], self.data['judgement_ms'])

    def test_session_table_same_rows_same_order(self):
        api_s, file_s = self.result['X']['sessions'], self.data['sessions']
        self.assertEqual([s['id'] for s in api_s], [s['id'] for s in file_s])
        for a, f in zip(api_s, file_s):
            for key in SESSION_KEYS:
                self.assertEqual(a[key], f[key], (f['id'], key))

    def test_session_steps_same_values(self):
        by_id = {s['id']: s for s in self.data['sessions']}
        for a in self.result['X']['sessions']:
            f = by_id[a['id']]
            for key in LOADED_KEYS:
                self.assertEqual(a[key], f[key], (f['id'], key))

    def test_failed_api_rejects_so_the_file_records_stay(self):
        self.assertFalse(run_node(self.responses, steps=False, reject=True)['ok'])
        missing = {k: v for k, v in self.responses.items() if k != '/api/summary'}
        self.assertIn('/api/summary', run_node(missing, steps=False)['error'])
        empty = dict(self.responses, **{'/api/sessions?validity=valid': {'count': 0, 'sessions': []}})
        self.assertFalse(run_node(empty, steps=False)['ok'])


class ApiModePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, _ = Fixture.get()
        cls.file_page = demo_ui.page(data)
        cls.api_page = demo_ui.page(data, api=True)

    def test_file_page_has_no_api_code_and_says_file(self):
        self.assertNotIn('apiLoad', self.file_page)
        self.assertNotIn('fetch(', self.file_page)
        self.assertIn('<span id="data-src">데이터 : 파일에 담긴 기록</span>', self.file_page)

    def test_api_page_requests_only_its_own_server_over_http(self):
        self.assertIn(demo_ui.API_MAP, self.api_page)
        self.assertIn("if(/^https?:$/.test(location.protocol)){", self.api_page)
        urls = set(__import__('re').findall(r"apiJson\(fetchFn,'([^']+)'", demo_ui.API_MAP))
        self.assertEqual(urls, {'/api/summary', '/api/sessions?validity=valid', '/api/sessions/'})
        self.assertNotRegex(demo_ui.API_MAP + demo_ui.API_SCRIPT, r'https?://')
        self.assertIn("데이터 : DB (조회 API)", demo_ui.API_SCRIPT)
        self.assertIn("SRC=FILE_SRC", demo_ui.API_SCRIPT)

    def test_live_monitor_menu_unchanged(self):
        # The server has no live server : the menu says so (the live script is only in the page demo_live serves).
        self.assertIn('실시간 서버가 꺼져 있습니다. 기록 재생을 쓰세요.', self.api_page)
        self.assertNotIn('lvTick', self.api_page)


if __name__ == '__main__':
    unittest.main()
