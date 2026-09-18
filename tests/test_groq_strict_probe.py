import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from scenario_schema import Scenario, load_scenario
from experiments.issue_contract import ISSUE_ID_COLLISION, V2, for_scenario
from experiments.observation_collection import INDEPENDENT
from experiments.step_execution import final_instruction
from tools import probe_groq_strict as probe
import test_tool_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(probe.DEFAULT_SCENARIO)
CONTRACT = for_scenario(V2, SCENARIO)
KEY = 'gsk_test_secret_value_0123456789'
GOOD = dict(narrative='probe', open_issue_ids=['requirements'], info_items=[], completion_declared=False,
            unlisted_issues=[])


def reply(value=GOOD, finish='stop', status=200):
    body = {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant', 'content': json.dumps(value)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
    return lambda url, key, request: (status, json.dumps(body))


class RequestBodyTests(unittest.TestCase):
    def test_base_request_matches_contract_and_final_prompt(self):
        body = probe.request_body(SCENARIO, CONTRACT)
        self.assertEqual(body['response_format'], CONTRACT.response_format())
        self.assertEqual(body['messages'][0], {'role': 'system', 'content': final_instruction(CONTRACT)})
        self.assertEqual((body['model'], body['temperature'], body['max_tokens'], body['reasoning_effort']),
                         (SCENARIO.model, SCENARIO.temperature, SCENARIO.max_tokens, 'low'))
        self.assertNotIn('enum', json.dumps(body['response_format']))
        self.assertNotIn('tools', body)

    def test_enum_variant_only_adds_allowed_ids(self):
        base = probe.request_body(SCENARIO, CONTRACT)['response_format']
        enum = probe.request_body(SCENARIO, CONTRACT, probe.ENUM)['response_format']
        schema = enum['json_schema']['schema']
        array = next(a for a in schema['properties']['open_issue_ids']['anyOf'] if a.get('type') == 'array')
        self.assertEqual(array['items'].pop('enum'), [i.id for i in SCENARIO.allowed_issues])
        self.assertEqual(enum, base)

    def test_no_length_variant_only_drops_length_keywords(self):
        base = probe.request_body(SCENARIO, CONTRACT)['response_format']
        stripped = probe.request_body(SCENARIO, CONTRACT, probe.NO_LENGTH)['response_format']
        text = json.dumps(stripped)
        self.assertNotIn('minLength', text); self.assertNotIn('maxLength', text)
        self.assertIn('maxLength', json.dumps(base))
        self.assertEqual(stripped, probe.strip_lengths(base))


class RunnerParityTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'
    output_contract = V2

    def scenario_transform(self, scenario):
        return load_scenario(probe.DEFAULT_SCENARIO)

    async def test_probe_matches_runner_final_request_for_a1_v2(self):
        value = json.dumps(GOOD)
        def upstream(request):
            response = recovery.success().json()
            response['choices'][0]['message']['content'] = value
            return httpx.Response(200, json=response)
        r = await self.run_offline(upstream, max_steps=1)
        final = [q for q in r['upstream_requests'] if 'response_format' in q][-1]
        body = probe.request_body(SCENARIO, CONTRACT)
        self.assertEqual(final['response_format'], body['response_format'])
        self.assertEqual(final['messages'][0]['content'], body['messages'][0]['content'])
        self.assertEqual(sorted(k for k in final if k != 'messages'), sorted(k for k in body if k != 'messages'))
        self.assertEqual(final['reasoning_effort'], body['reasoning_effort'])
        self.assertEqual(final['max_tokens'], body['max_tokens'])


class ProbeRunTests(unittest.TestCase):
    def run_probe(self, variants, key=KEY, transport=None):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        def forbidden(*a, **kw):
            raise AssertionError('network used')
        with patch('urllib.request.urlopen', forbidden):
            folder, report = probe.probe(probe.DEFAULT_SCENARIO, variants, Path(directory.name), key,
                                         transport or forbidden)
        return folder, report

    def test_dry_run_builds_bodies_without_sending(self):
        folder, report = self.run_probe([probe.BASE, probe.ENUM, probe.NO_LENGTH], key=None)
        self.assertTrue(report['dry_run'])
        self.assertEqual([r['sent'] for r in report['results']], [False] * 3)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([v + '.request.json' for v in (probe.BASE, probe.ENUM, probe.NO_LENGTH)] + ['result.json']))

    def test_reports_status_finish_contract_and_usage_without_leaking_key(self):
        leaky = lambda url, key, request: (401, json.dumps({'error': {'message': 'bad key ' + key}}))
        cases = [(reply(), True, None, 'stop'),
                 (reply({**GOOD, 'unlisted_issues': ['requirements']}), False, ISSUE_ID_COLLISION, 'stop'),
                 (reply(finish='length'), False, None, 'length')]
        for transport, valid, code, finish in cases:
            with self.subTest(code=code, finish=finish):
                folder, report = self.run_probe([probe.BASE], transport=transport)
                result = report['results'][0]
                self.assertEqual((result['http_status'], result['finish_reason'], result['contract_valid']),
                                 (200, finish, valid))
                self.assertEqual(result['usage']['total_tokens'], 15)
                if code:
                    self.assertEqual(result['contract_violation'], code)
        folder, report = self.run_probe([probe.BASE], transport=leaky)
        result = report['results'][0]
        self.assertEqual(result['http_status'], 401)
        self.assertFalse(result['contract_valid'])
        for path in folder.iterdir():
            self.assertNotIn(KEY, path.read_text(encoding='utf-8'), path.name)

    def test_default_cli_sends_only_base_variant_and_requires_key_unless_dry_run(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        with patch('sys.argv', ['probe', '--dry-run', '--output-root', directory.name]), \
                patch('builtins.print'):
            self.assertEqual(probe.main(), 0)
        folder = next(Path(directory.name).iterdir())
        self.assertEqual(json.loads((folder / 'result.json').read_text())['results'],
                         [{'variant': probe.BASE, 'sent': False}])
        with patch('sys.argv', ['probe']), patch.dict('os.environ', {}, clear=True), \
                patch('sys.stderr'), self.assertRaises(SystemExit):
            probe.main()
