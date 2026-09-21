"""D-27/D-25: the upstream is configured, recorded and key-checked; the protocol must be explicit."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import yaml

from experiment_config import DEFAULT_UPSTREAM, load_config, upstream
from experiments.issue_contract import V2, for_scenario
from experiments.observation_collection import INDEPENDENT
from experiments.step_execution import PROTOCOL_V7, PROTOCOL_V8
from proxy import create_app
from scenario_schema import load_scenario
from tools import probe_gateway as probe
import test_tool_recovery as recovery
from test_harness_facts import final, step_responses

ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = ROOT / 'guardrail.yaml'
GROQ_V02 = ROOT / 'guardrail-deadlock-v0.2.yaml'
KMU = ROOT / 'guardrail-deadlock-v0.2-kmu.yaml'
A1V3 = ROOT / 'scenarios/A-1-v3-ambiguous-task-query.yaml'
G0_8_LOG = ROOT / 'logs/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e.json'
KEY = 'kmu_test_secret_value_0123456789'


class ConfigTests(unittest.TestCase):
    def test_kmu_config_differs_only_in_criteria_and_upstream(self):
        base, kmu = load_config(BASE_CONFIG), load_config(KMU)
        self.assertEqual(upstream(base), DEFAULT_UPSTREAM)
        self.assertEqual(upstream(kmu), {'base_url': 'https://factchat.mindlogic-kr-api.com/v1/gateway',
                                         'chat_path': '/chat/completions/', 'api_key_env': 'KMU_API_KEY'})
        self.assertNotIn('upstream', base)
        for config in (base, kmu):
            config.pop('criteria_version'); config.pop('upstream', None)
        self.assertEqual(base, kmu)
        # The Groq v0.2 config keeps the Groq upstream.
        self.assertEqual(upstream(load_config(GROQ_V02)), DEFAULT_UPSTREAM)

    def test_settings_are_validated_and_hold_no_secret(self):
        for bad in ({'base_url': 'http://x.test/v1'}, {'base_url': 'https://x.test/v1/'},
                    {'base_url': 'https://x.test/v1?k=1'}, {'chat_path': 'chat'},
                    {'api_key_env': 'lower_case'}, {'api_key': 'secret'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                upstream({'upstream': bad})
        self.assertNotIn('key', yaml.safe_load(KMU.read_text(encoding='utf-8'))['upstream'])


class ProxyUpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def forward(self, config_path):
        seen = {}
        def handler(request):
            seen['url'] = str(request.url)
            seen['user_agent'] = request.headers.get('user-agent')
            return recovery.success()
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'logs', transport=httpx.MockTransport(handler),
                             config_path=config_path)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://proxy',
                                         headers={'X-Guardrail-Session': 'upstream-check',
                                                  'Authorization': 'Bearer x'}) as client:
                (await client.post('/sessions')).raise_for_status()
                response = await client.post('/v1/chat/completions',
                                             json={'model': 'm', 'messages': [{'role': 'user', 'content': 'hi'}]})
                self.assertEqual(response.status_code, 200)
                meta = (await client.get('/log')).json()['meta']
        return seen, meta

    async def test_endpoint_and_recorded_identity_come_from_the_config(self):
        seen, meta = await self.forward(KMU)
        self.assertEqual(seen['url'], 'https://factchat.mindlogic-kr-api.com/v1/gateway/chat/completions/')
        self.assertEqual(meta['upstream'], {'base_url_host': 'factchat.mindlogic-kr-api.com',
                                            'base_url': 'https://factchat.mindlogic-kr-api.com/v1/gateway',
                                            'chat_path': '/chat/completions/', 'api_key_env': 'KMU_API_KEY',
                                            'config_file': 'guardrail-deadlock-v0.2-kmu.yaml'})
        groq, groq_meta = await self.forward(GROQ_V02)
        self.assertEqual(groq['url'], 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(groq_meta['upstream']['api_key_env'], 'GROQ_API_KEY')


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'
    output_contract = V2
    runner_protocol = PROTOCOL_V8

    def scenario_transform(self, scenario):
        return load_scenario(A1V3)

    async def test_protocol_must_be_explicit_for_output_contract_v2(self):
        self.runner_protocol = None
        with self.assertRaises(ValueError):
            await self.run_offline(step_responses())

    async def test_conditions_record_protocol_key_variable_and_upstream(self):
        run = await self.run_offline(step_responses(), max_steps=1)
        self.assertEqual(run['conditions']['runner_protocol'], PROTOCOL_V8)
        self.assertEqual(run['conditions']['api_key_env'], 'GROQ_API_KEY')
        self.assertEqual(run['conditions']['upstream']['api_key_env'], 'GROQ_API_KEY')
        self.assertEqual(run['conditions']['upstream']['base_url_host'], 'api.groq.com')
        self.assertEqual(run['conditions']['reasoning_effort'],
                         {'requested': 'low', 'applied': 'unverified',
                          'sent_on': 'final tool-free call of each step only'})
        self.assertEqual(run['conditions']['final_reasoning_effort'], 'low')
        self.assertNotIn(KEY, json.dumps(run['conditions'], ensure_ascii=False))

    def test_key_variable_must_match_the_proxy_configuration(self):
        from experiments.run_scenario import ensure_key_env
        with self.assertRaises(ValueError):
            ensure_key_env({'api_key_env': 'KMU_API_KEY'}, 'GROQ_API_KEY')
        # Older sessions without the record, and a matching variable, are accepted.
        ensure_key_env(None, 'GROQ_API_KEY')
        ensure_key_env({'api_key_env': 'KMU_API_KEY'}, 'KMU_API_KEY')


class GatewayProbeTests(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(A1V3)
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def run_probe(self, variants, key=KEY, transport=None, calls=None):
        def recorder(url, api_key, body, user_agent, method='POST'):
            (calls if calls is not None else []).append({'url': url, 'method': method, 'body': body})
            if method == 'GET':
                used = 10.0 if not calls or len(calls) < 3 else 10.5
                # Shape of the real /credits/ body: usage is nested, not top-level (C-11).
                return 200, json.dumps({'monthly_allocated': {'used': used, 'limit': 5000},
                                        'total': {'used': used + 100}})
            return 200, json.dumps(transport or {})
        with patch('urllib.request.urlopen', side_effect=AssertionError('network used')):
            return probe.probe(A1V3, KMU, variants, Path(self.directory.name), 'developer', key, recorder)

    def test_request_bodies_use_runner_code_and_scenario_values(self):
        import shutil
        from experiments.run_scenario import safe_path
        workspace = Path(self.directory.name) / 'ws'
        shutil.copytree(safe_path(ROOT, self.scenario.fixture_dir), workspace,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        agent = next(a for a in self.scenario.agents if a.id == 'developer')
        bodies, contract = probe.request_bodies(self.scenario, agent, workspace,
                                                [probe.FINAL, probe.TOOLS_LOW, probe.TOOLS_HIGH])
        self.assertEqual(bodies[probe.FINAL]['response_format'], contract.response_format())
        self.assertNotIn('tools', bodies[probe.FINAL])
        low, high = bodies[probe.TOOLS_LOW], bodies[probe.TOOLS_HIGH]
        self.assertEqual(low['reasoning_effort'], 'low')
        self.assertEqual(high['reasoning_effort'], 'high')
        self.assertEqual({k: v for k, v in low.items() if k != 'reasoning_effort'},
                         {k: v for k, v in high.items() if k != 'reasoning_effort'})
        for body in bodies.values():
            self.assertEqual((body['model'], body['max_tokens']), (self.scenario.model, self.scenario.max_tokens))
        # Tool definitions equal the ones the runner actually sent for this fixture.
        log = json.loads(G0_8_LOG.read_text(encoding='utf-8'))
        sent = next(t['request_body']['tools'] for t in log['turns']
                    if (t['request_body'].get('tools') or [])
                    and {f['function']['name'] for f in t['request_body']['tools']} ==
                        {f['function']['name'] for f in low['tools']})
        self.assertEqual(low['tools'], sent)
        system = low['messages'][0]['content']
        self.assertIn('Files this role can write: src/task_query.py.', system)
        self.assertEqual(json.loads(low['messages'][1]['content'])['call_budget']['max_model_calls'],
                         self.scenario.termination.max_llm_calls_per_step)

    def test_dry_run_builds_bodies_without_sending(self):
        folder, report = self.run_probe([probe.FINAL, probe.TOOLS_LOW], key=None)
        self.assertTrue(report['dry_run'])
        self.assertEqual([r['sent'] for r in report['results']], [False, False])
        self.assertEqual(report['api_key_env'], 'KMU_API_KEY')
        self.assertEqual(report['endpoint'],
                         'https://factchat.mindlogic-kr-api.com/v1/gateway/chat/completions/')

    def test_credits_are_read_around_each_request_and_key_is_redacted(self):
        calls = []
        body = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'leaked ' + KEY,
                                                                 'reasoning_content': 'r'}}],
                'usage': {'completion_tokens': 9, 'completion_tokens_details': {'reasoning_tokens': 4}}}
        folder, report = self.run_probe([probe.FINAL], transport=body, calls=calls)
        result = report['results'][0]
        self.assertEqual([c['method'] for c in calls], ['GET', 'POST', 'GET'])
        self.assertTrue(calls[0]['url'].endswith('/credits/'))
        self.assertEqual(result['credits']['status'], 'measured')
        self.assertEqual(result['credits']['value'], 0.5)
        self.assertEqual(result['credits']['field'], 'monthly_allocated.used')
        self.assertEqual((result['http_status'], result['finish_reason']), (200, 'stop'))
        self.assertTrue(result['reasoning_content_present'])
        self.assertFalse(result['contract_valid'])
        for path in folder.iterdir():
            self.assertNotIn(KEY, path.read_text(encoding='utf-8'), path.name)

    def test_missing_used_field_is_unmeasured(self):
        monthly = lambda v: {'body': {'monthly_allocated': {'used': v}, 'total': {'used': v + 50}}}
        self.assertEqual(probe.credit_delta({'body': {}}, monthly(1))['status'], 'unmeasured')
        # A top-level used field is not the gateway's shape and is not read.
        self.assertEqual(probe.credit_delta({'body': {'used': 1}}, {'body': {'used': 3}})['status'], 'unmeasured')
        self.assertEqual(probe.credit_delta(monthly(4241.70359), monthly(4258.13384)),
                         {'value': 16.43025, 'status': 'measured', 'field': 'monthly_allocated.used',
                          'used_before': 4241.70359, 'used_after': 4258.13384})

    def test_total_used_is_the_fallback_and_fields_must_match(self):
        total = lambda v: {'body': {'total': {'used': v}}}
        self.assertEqual(probe.credit_delta(total(1), total(3))['field'], 'total.used')
        mixed = probe.credit_delta({'body': {'monthly_allocated': {'used': 1}}}, total(3))
        self.assertEqual((mixed['status'], mixed['value']), ('unmeasured', None))

    def test_reasoning_set_differs_only_in_effort_and_tools(self):
        folder, report = self.run_probe(list(probe.REASONING_SET), key=None)
        bodies = {v: json.loads((folder / (v + '.request.json')).read_text(encoding='utf-8'))
                  for v in probe.REASONING_SET}
        strip = lambda b: {k: v for k, v in b.items() if k not in ('reasoning_effort', 'tools', 'tool_choice')}
        self.assertEqual(len({json.dumps(strip(b), sort_keys=True) for b in bodies.values()}), 1)
        self.assertEqual([bodies[v]['reasoning_effort'] for v in probe.REASONING_SET], ['low', 'high', 'low', 'high'])
        self.assertNotIn('tools', bodies[probe.REASON_NO_TOOLS_LOW])
        self.assertNotIn('tools', bodies[probe.REASON_NO_TOOLS_HIGH])
        self.assertEqual(bodies[probe.REASON_TOOLS_LOW]['tools'], bodies[probe.REASON_TOOLS_HIGH]['tools'])
        self.assertEqual(bodies[probe.REASON_TOOLS_LOW]['tool_choice'], 'auto')
        self.assertIsNone(report['reasoning_comparison'])

    def test_reasoning_comparison_reports_gaps_only(self):
        usage = lambda n: {'completion_tokens_details': {'reasoning_tokens': n}}
        results = [{'variant': v, 'usage': usage(n), 'tool_calls': []}
                   for v, n in zip(probe.REASONING_SET, (100, 900, 20, 25))]
        comparison = probe.reasoning_comparison(results + [{'variant': probe.FINAL, 'usage': usage(1)}])
        self.assertEqual((comparison['high_minus_low_without_tools'], comparison['high_minus_low_with_tools']),
                         (800, 5))
        self.assertNotIn(probe.FINAL, comparison['reasoning_tokens'])
        self.assertIsNone(probe.reasoning_comparison(results[:1])['high_minus_low_without_tools'])
