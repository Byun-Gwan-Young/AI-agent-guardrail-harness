"""C-19-3 : the demo screen (tools/demo_ui.py) built from the committed demo records (offline, read-only).

Checked : the page makes no request (no external src/href/url()/fetch, every http(s) text is a namespace or the local
proxy address), carries no narrative/reasoning field, shows the aggregate's numbers and the final report's section 4
presentation numbers, switches the trial band and source line by plan ID, keeps every "구현 전" feature disabled and
marked, reads the system page names from the proxy code, and finds the changed line of each normal/stall pair.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools import aggregate_demo, demo_ui

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'reports' / 'c19' / 'aggregate-main.json'
REPORT = ROOT / 'reports' / 'c19' / 'final-report.md'
TRIAL_PLANS = ['demo-trial-c18-2', 'demo-trial-c18-3', 'demo-trial-c18-4', 'demo-trial-c18-5']
FORBIDDEN_KEYS = ('narrative', 'reasoning', 'thought', 'info_items', 'reasoning_content')


def page_data(text):
    m = re.search(r'<script type="application/json" id="demo-data">(.*?)</script>', text, re.S)
    return json.loads(m.group(1).replace('<\\/', '</'))


def keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys(v)


class Built:
    main = trial = None

    @classmethod
    def get(cls):
        if cls.main is None:
            aggregate = demo_ui.load(MAIN)
            data = demo_ui.collect(aggregate, runs_root=ROOT / 'runs' / 'demo')
            cls.main = (aggregate, data, demo_ui.page(data))
            trial = aggregate_demo.aggregate(TRIAL_PLANS, runs_root=ROOT / 'runs' / 'demo')
            tdata = demo_ui.collect(trial, runs_root=ROOT / 'runs' / 'demo')
            cls.trial = (trial, tdata, demo_ui.page(tdata))
        return cls.main, cls.trial


class DemoUiTest(unittest.TestCase):
    def setUp(self):
        (self.aggregate, self.data, self.html), (self.t_aggregate, self.t_data, self.t_html) = Built.get()

    def test_no_request_in_page(self):
        for text in (self.html, self.t_html):
            self.assertNotRegex(text, r'(?i)<(script|img|iframe|link)[^>]+(src|href)\s*=\s*["\']?https?:')
            self.assertNotRegex(text, r'(?i)url\(\s*["\']?https?:|@import|fetch\(|XMLHttpRequest|import\(|<link ')
            for url in re.findall(r'https?://[^\s"\'<>)]+', text):
                local = url.startswith('http://127.0.0.1:')
                namespace = url in ('http://www.w3.org/2000/svg', 'http://c2pa.org/manifest')
                self.assertTrue(local or namespace, url)

    def test_no_narrative_or_reasoning_in_data(self):
        found = {k for k in keys(self.data) if k in FORBIDDEN_KEYS}
        self.assertEqual(found, set())
        self.assertEqual(page_data(self.html)['headline'], json.loads(json.dumps(self.data['headline'])))

    def test_numbers_match_aggregate(self):
        h, agg = self.data['headline'], self.aggregate['headline']
        self.assertEqual(h['false_positive'], agg['normal_false_positive_runs'])
        self.assertEqual(h['stall_reached'], agg['stall_runs_stalled'])
        self.assertEqual(h['stall_detected'], agg['stall_runs_detected'])
        self.assertEqual(h['stall_escalated'], agg['stall_runs_escalated'])
        self.assertAlmostEqual(h['saving_mean'], agg['if_stopped_token_ratio_mean_detected'], places=4)
        self.assertEqual(len(self.data['sessions']), self.aggregate['sessions'])
        by_id = {t['scenario_id']: t for t in self.aggregate['scenarios']}
        for row in self.data['scenarios']:
            self.assertEqual(row['stalled_k_of_n'], by_id[row['scenario_id']]['stalled_k_of_n'])
            self.assertEqual(row['first_stop_steps'], by_id[row['scenario_id']]['first_stop_steps'])
        for scenario_id, block in h['block'].items():
            self.assertEqual(block['token_saving'], by_id[scenario_id]['block']['token_saving_vs_observe'])

    def test_numbers_match_final_report_presentation_section(self):
        text = REPORT.read_text(encoding='utf-8')
        section = text.split('## 4. 발표용 숫자', 1)[1].split('\n## ', 1)[0]
        h = self.data['headline']
        fp = re.search(r'정상판 오탐 (\d+) 회\*\* — 성공한 정상판 (\d+) 세션', section)
        self.assertEqual((h['false_positive'], h['normal_success']), tuple(map(int, fp.groups())))
        blocked = re.search(r'차단 모드였다면 성공을 막았을 세션 (\d+) 회', section)
        self.assertEqual(h['blocked_before_success'], int(blocked.group(1)))
        detected = re.search(r'교착판 탐지 (\d+) 회\*\* — 교착에 닿은\(미완료\) 교착판 관측 (\d+) 세션', section)
        self.assertEqual((h['stall_detected'], h['stall_reached']), tuple(map(int, detected.groups())))
        saving = re.search(r'평균 절감률 ([\d.]+)%', section)
        self.assertEqual(f"{100 * h['saving_mean']:.1f}", saving.group(1))
        block = re.search(r'차단 실측 절감 CL ([\d.]+)% · CT ([\d.]+)%', section)
        self.assertEqual(f"{100 * h['block']['DEMO-CL-stall-v1']['token_saving']:.1f}", block.group(1))
        self.assertEqual(f"{100 * h['block']['DEMO-CT-stall-v1']['token_saving']:.1f}", block.group(2))
        judged = {k for k, b in h['block'].items() if b['judged']}
        self.assertEqual(judged, {'DEMO-CL-stall-v1', 'DEMO-CT-stall-v1'})

    def test_trial_band_and_source_line(self):
        band = '시험 세션 (시나리오당 1~2 회) — 본 실행 결과 아님'
        self.assertEqual(self.t_data['kind'], 'trial')
        self.assertIn(band, self.t_html)
        self.assertIn('본 실행 결과 아님', self.t_data['source'])
        self.assertEqual(self.data['kind'], 'main')
        self.assertNotIn(band, self.html)
        self.assertNotIn('시험 세션', self.data['source'])
        self.assertRegex(self.data['source'], r'^본 실행 항목 70 개 중 유효 67 세션 \(\d+/\d+~\d+/\d+\), 최종 동결 6a7bf8dc…$')
        self.assertEqual(demo_ui.data_kind(['demo-main-v1', 'demo-trial-c18-2']), 'mixed')

    def test_planned_features_disabled_and_marked(self):
        for pid in ('project', 'key', 'warn', 'report', 'live', 'policy', 'integration'):
            tags = re.findall(r'<button[^>]*data-planned="%s"[^>]*>' % pid, self.html)
            boxes = re.findall(r'data-planned-box="%s"' % pid, self.html)
            self.assertTrue(tags or boxes, pid)
            for tag in tags:
                self.assertIn('disabled', tag, pid)
        name_of = {p['id']: p['name'] for p in self.data['planned']}
        for pid in ('live', 'policy', 'integration'):
            self.assertRegex(self.html, r'data-planned="%s" disabled title="구현 전">%s <span class="badge">구현 전'
                             % (pid, re.escape(name_of[pid])))
        self.assertNotRegex(self.html, r'<button(?![^>]*disabled)[^>]*data-planned=')

    def test_system_names_from_code(self):
        system = self.data['system']
        self.assertEqual(system['session_header'], 'X-Guardrail-Session')
        self.assertEqual(system['observation_route'], '/sessions/observations')
        self.assertEqual(system['chat_route'], '/v1/chat/completions')
        self.assertEqual(system['block_status'], 403)
        self.assertEqual((system['criteria_version'], system['k']), ('deadlock-v0.3', 6))
        self.assertTrue(self.data['example']['schema_checked'])

    def test_pair_changed_lines(self):
        pairs = self.data['pairs']
        self.assertIn('배송 사고는 배송 담당 소관이다', ' '.join(l['line'] for l in pairs['DEMO-CS']['lines']))
        self.assertTrue(any('1h30' in l['line'] for l in pairs['DEMO-CL']['lines']))
        self.assertTrue(all(l['where'] == '과제 문장' for l in pairs['DEMO-MR']['lines']))
        self.assertTrue(any('QuorvexBench' in l['line'] for l in pairs['DEMO-LR']['lines']))
        self.assertEqual([l['where'] for l in pairs['DEMO-CT']['lines']], ['ACCEPTANCE.md'])

    def test_build_writes_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = demo_ui.build(MAIN, Path(tmp) / 'demo.html')
            self.assertEqual(result['replay_missing'], [])
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['demo.html'])


if __name__ == '__main__':
    unittest.main()
