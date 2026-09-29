"""C-16 part 5: the gateway probe sends the same requests to several models and reports them per model."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import probe_gateway as probe

ROOT = Path(__file__).resolve().parents[1]
A1V4 = ROOT / 'scenarios/A-1-v4-ambiguous-task-query.yaml'
KMU = ROOT / 'guardrail-deadlock-v0.2-kmu.yaml'
KEY = 'kmu_test_secret_value_0123456789'
GPT, CLAUDE = 'accounts/fireworks/models/gpt-oss-120b', 'claude-sonnet-5'


class ModelProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def run_probe(self, variants, models, key=KEY, reply=None, calls=None):
        used = [100.0]
        def recorder(url, api_key, body, user_agent, method='POST'):
            if calls is not None:
                calls.append({'url': url, 'method': method, 'body': body})
            if method == 'GET':
                return 200, json.dumps({'monthly_allocated': {'used': used[0]}})
            used[0] += 0.25
            return 200, json.dumps(reply(body) if reply else {})
        with patch('urllib.request.urlopen', side_effect=AssertionError('network used')):
            return probe.probe(A1V4, KMU, variants, Path(self.directory.name), 'developer', key, recorder,
                               models=models)

    def test_bodies_differ_only_by_model_and_short_has_no_tools(self):
        folder, report = self.run_probe([probe.SHORT, probe.TOOLS_HIGH], [GPT, CLAUDE], key=None)
        files = {p.name for p in folder.iterdir()}
        read = lambda m, v: json.loads((folder / (probe.model_slug(m) + '--' + v + '.request.json')).read_text())
        for variant in (probe.SHORT, probe.TOOLS_HIGH):
            a, b = read(GPT, variant), read(CLAUDE, variant)
            self.assertEqual((a['model'], b['model']), (GPT, CLAUDE))
            self.assertEqual({k: v for k, v in a.items() if k != 'model'}, {k: v for k, v in b.items() if k != 'model'})
        short = read(GPT, probe.SHORT)
        for field in ('tools', 'response_format', 'reasoning_effort'):
            self.assertNotIn(field, short)
        self.assertEqual(read(GPT, probe.TOOLS_HIGH)['reasoning_effort'], 'high')
        self.assertEqual([(r['model'], r['sent']) for r in report['results']],
                         [(GPT, False), (GPT, False), (CLAUDE, False), (CLAUDE, False)])
        self.assertIn('result.json', files)

    def test_default_call_keeps_original_names_and_no_model_summary(self):
        folder, report = self.run_probe([probe.FINAL], None, key=None)
        self.assertTrue((folder / (probe.FINAL + '.request.json')).is_file())
        self.assertNotIn('model_summary', report)
        self.assertNotIn('model', report['results'][0])

    def test_summary_reports_tokens_tool_call_and_credits_per_model(self):
        def reply(body):
            tools = 'tools' in body
            message = {'role': 'assistant', 'content': None if tools else 'OK'}
            if tools and body['model'] == GPT:
                message['tool_calls'] = [{'function': {'name': 'read_file', 'arguments': '{"path":"SPEC.md"}'}}]
            return {'choices': [{'finish_reason': 'tool_calls' if tools else 'stop', 'message': message}],
                    'usage': {'prompt_tokens': 1000 if tools else 20, 'completion_tokens': 300 if tools else 5,
                              'completion_tokens_details': {'reasoning_tokens': 200 if tools else 0}}}
        calls = []
        _, report = self.run_probe([probe.SHORT, probe.TOOLS_HIGH], [GPT, CLAUDE], reply=reply, calls=calls)
        self.assertEqual([c['method'] for c in calls[:3]], ['GET', 'POST', 'GET'])
        gpt, claude = report['model_summary'][GPT], report['model_summary'][CLAUDE]
        self.assertEqual([r['tool_call_returned'] for r in gpt['requests']], [False, True])
        self.assertEqual([r['tool_call_returned'] for r in claude['requests']], [False, False])
        self.assertEqual(gpt['requests'][1]['reasoning_tokens'], 200)
        self.assertEqual([r['credits'] for r in gpt['requests']], [0.25, 0.25])
        self.assertEqual(gpt['token_rates']['status'], 'solved_from_two_requests')

    def test_token_rates_solve_two_requests_exactly(self):
        # 0.15 / 0.60 credits per 1k tokens = 150 / 600 per 1M (the C-11 check, times 1000).
        credits = lambda p, c: p * 150e-6 + c * 600e-6
        rows = [{'usage': {'prompt_tokens': p, 'completion_tokens': c},
                 'credits': {'status': 'measured', 'value': credits(p, c)}} for p, c in ((77, 56), (2000, 300))]
        rates = probe.token_rates(rows)
        self.assertAlmostEqual(rates['credits_per_million_prompt_tokens'], 150, places=4)
        self.assertAlmostEqual(rates['credits_per_million_completion_tokens'], 600, places=4)
        self.assertEqual(probe.token_rates(rows[:1])['status'], 'unmeasured')
        proportional = [dict(rows[0]), {'usage': {'prompt_tokens': 154, 'completion_tokens': 112},
                                        'credits': {'status': 'measured', 'value': 1.0}}]
        self.assertEqual(probe.token_rates(proportional)['status'], 'unmeasured')

    def test_list_models_keeps_ids_only(self):
        def transport(url, api_key, body, user_agent, method='POST'):
            self.assertTrue(url.endswith('/models/'))
            self.assertEqual(method, 'GET')
            return 200, json.dumps({'data': [{'id': CLAUDE, 'owned_by': 'x'}, {'id': GPT}, {'name': 'no id'}]})
        self.assertEqual(probe.list_models('https://g/v1/gateway', KEY, 'ua', transport),
                         {'status': 200, 'model_ids': [GPT, CLAUDE]})
        broken = lambda *a, **k: (500, 'not json')
        self.assertEqual(probe.list_models('https://g', KEY, 'ua', broken)['model_ids'], None)


if __name__ == '__main__':
    unittest.main()
