"""C-17-7 part 2: the gateway probe's closed-list strict variants (DM-20) and its reading of gateway error bodies.

--with-v3-strict sends a dialogue task's final output-contract-v3 request with the closed lists as enums
(provider_strict) and without them (after_receipt). The two bodies are the ones the dialogue runner sends and differ
only in the enums. Error bodies in the gateway's {"detail": {...}} shape keep their message (the 2026-09-29 probe
recorded null for its two HTTP 400s). Offline: every transport is a fake.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from t1_harness import FIXTURE, report, run_t1
from tools import probe_gateway as probe

ROOT = Path(__file__).resolve().parents[1]
A1V4 = ROOT / 'scenarios/A-1-v4-ambiguous-task-query.yaml'
KMU = ROOT / 'guardrail-deadlock-v0.2-kmu.yaml'
KEY = 'kmu_test_secret_value_0123456789'
STATUSES = ['received', 'triage', 'assigned', 'resolved', 'escalated']
# The shape of the gateway's HTTP 400 body in runs/gateway-probes/gateway-probe-9d2b2053…/gpt-6-sol--…response.json.
GATEWAY_400 = {'detail': {'code': 400, 'message': 'invalid_request_error - [400] Error code: 400 - '
                                                 "{'error': {'message': \"Function tools with reasoning_effort are "
                                                 "not supported for gpt-6-sol in /v1/chat/completions.\"}}"}}


def contains_enum(value):
    if isinstance(value, dict):
        return 'enum' in value or any(contains_enum(v) for v in value.values())
    return isinstance(value, list) and any(contains_enum(v) for v in value)


class ErrorTextTests(unittest.TestCase):
    def test_both_error_shapes_keep_their_message(self):
        self.assertEqual(probe.error_text({'error': {'message': 'bad schema'}}), 'bad schema')
        self.assertTrue(probe.error_text(GATEWAY_400).startswith('invalid_request_error - [400]'))
        self.assertEqual(probe.error_text({'detail': 'Not Found'}), 'Not Found')
        self.assertEqual(probe.error_text({'error': 'plain'}), 'plain')
        self.assertIsNone(probe.error_text({'choices': []}))

    def test_assess_records_the_gateway_message_of_a_400(self):
        result = probe.assess(None, probe.TOOLS_HIGH, 400, GATEWAY_400)
        self.assertEqual(result['http_status'], 400)
        self.assertIn('Function tools with reasoning_effort are not supported for gpt-6-sol', result['error_message'])


class StrictVariantTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def run_probe(self, scenario=FIXTURE, variants=(probe.V3_STRICT_NO_ENUMS, probe.V3_STRICT_ENUMS), key=KEY,
                  reply=None, models=None):
        used = [10.0]
        def recorder(url, api_key, body, user_agent, method='POST'):
            if method == 'GET':
                return 200, json.dumps({'monthly_allocated': {'used': used[0]}})
            used[0] += 0.5
            status, value = reply(body) if reply else (200, {})
            return status, json.dumps(value)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network used')):
            return probe.probe(scenario, KMU, list(variants), Path(self.directory.name), 'developer', key, recorder,
                               models=models)

    def bodies(self, folder, prefix=''):
        read = lambda v: json.loads((folder / (prefix + v + '.request.json')).read_text(encoding='utf-8'))
        return read(probe.V3_STRICT_NO_ENUMS), read(probe.V3_STRICT_ENUMS)

    def test_bodies_differ_only_in_the_enums(self):
        folder, result = self.run_probe(key=None)
        plain, strict = self.bodies(folder)
        properties = strict['response_format']['json_schema']['schema']['properties']
        self.assertEqual(properties['status']['enum'], STATUSES)
        self.assertEqual(properties['handoff_to']['anyOf'][0]['enum'], ['intake', 'refund', 'shipping'])
        self.assertFalse(contains_enum(plain['response_format']))
        self.assertEqual({k: v for k, v in plain.items() if k != 'response_format'},
                         {k: v for k, v in strict.items() if k != 'response_format'})
        self.assertTrue(strict['response_format']['json_schema']['strict'])
        self.assertEqual((plain['reasoning_effort'], plain['model'], 'tools' in plain),
                         ('high', 'accounts/fireworks/models/gpt-oss-120b', False))
        self.assertEqual((result['output_contract_version'], result['runner_protocol'], result['role']),
                         ('output-contract-v3', 'tool-capable-step-v10-final-report-allowlist', None))
        self.assertTrue(result['dry_run'])

    async def test_bodies_match_the_dialogue_runner_final_request(self):
        folder, _ = self.run_probe(key=None)
        probed = dict(zip(('after_receipt', 'provider_strict'), self.bodies(folder)))
        for mode, body in probed.items():
            with self.subTest(mode=mode):
                run = await run_t1([report('triage')], max_steps=1, closed_list_check=mode, tests=self)
                final = next(r for r in run['requests'] if 'response_format' in r)
                for field in ('model', 'temperature', 'max_tokens', 'reasoning_effort', 'response_format'):
                    self.assertEqual(body[field], final[field], field)
                self.assertEqual(body['messages'][0], final['messages'][0])
                self.assertEqual(json.loads(body['messages'][1]['content'])['observed_records'][0]['task'],
                                 json.loads(final['messages'][1]['content'])['observed_records'][0]['task'])

    def test_replies_are_checked_with_the_full_contract_in_both_modes(self):
        def reply(body):
            strict = contains_enum(body['response_format'])
            content = report('triage' if strict else 'closed')  # 'closed' is outside the status list
            return 200, {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                                                                           'content': json.dumps(content)}}],
                         'usage': {'prompt_tokens': 900, 'completion_tokens': 120,
                                   'completion_tokens_details': {'reasoning_tokens': 80}}}
        _, result = self.run_probe(reply=reply)
        rows = {r['variant']: r for r in result['results']}
        self.assertTrue(rows[probe.V3_STRICT_ENUMS]['contract_valid'])
        self.assertFalse(rows[probe.V3_STRICT_NO_ENUMS]['contract_valid'])
        self.assertIsNotNone(rows[probe.V3_STRICT_NO_ENUMS]['contract_violation'])
        comparison = result['closed_list_comparison']['by_model']
        self.assertEqual((comparison['provider_strict']['contract_valid'], comparison['after_receipt']['contract_valid'],
                          comparison['provider_strict']['http_status']), (True, False, 200))
        self.assertEqual([r['credits']['value'] for r in result['results']], [0.5, 0.5])

    def test_a_refused_schema_keeps_the_provider_message(self):
        def reply(body):
            if contains_enum(body['response_format']):
                return 400, {'error': {'message': 'enum is not supported in strict mode'}}
            return 200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(report('triage'))}}]}
        _, result = self.run_probe(reply=reply)
        comparison = result['closed_list_comparison']['by_model']
        self.assertEqual((comparison['provider_strict']['http_status'], comparison['provider_strict']['error_message']),
                         (400, 'enum is not supported in strict mode'))
        self.assertEqual((comparison['after_receipt']['http_status'], comparison['after_receipt']['contract_valid']),
                         (200, True))

    def test_models_are_compared_per_model(self):
        folder, result = self.run_probe(key=None, models=['m-one', 'm-two'])
        plain, strict = self.bodies(folder, 'm-two--')
        self.assertEqual((plain['model'], strict['model']), ('m-two', 'm-two'))
        self.assertEqual([(r['model'], r['variant']) for r in result['results']],
                         [('m-one', probe.V3_STRICT_NO_ENUMS), ('m-one', probe.V3_STRICT_ENUMS),
                          ('m-two', probe.V3_STRICT_NO_ENUMS), ('m-two', probe.V3_STRICT_ENUMS)])

    def test_variants_and_scenarios_are_not_mixed(self):
        with self.assertRaisesRegex(ValueError, 'dialogue task'):
            self.run_probe(scenario=A1V4, key=None)
        with self.assertRaisesRegex(ValueError, 'only the v3 strict variants'):
            self.run_probe(variants=(probe.FINAL,), key=None)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])


class CommandLineTests(unittest.TestCase):
    def main(self, *argv):
        with patch.object(sys, 'argv', ['probe_gateway.py', *argv]), \
                patch('urllib.request.urlopen', side_effect=AssertionError('network used')), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            return probe.main(), out.getvalue()

    def test_dry_run_writes_the_two_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _ = self.main('--scenario', str(FIXTURE), '--with-v3-strict', '--dry-run', '--output-root', directory)
            folder = next(Path(directory).iterdir())
            self.assertEqual(code, 0)
            self.assertEqual(sorted(p.name for p in folder.iterdir()),
                             sorted([probe.V3_STRICT_ENUMS + '.request.json', probe.V3_STRICT_NO_ENUMS + '.request.json',
                                     'result.json']))

    def test_refused_combinations(self):
        for argv in (('--scenario', str(A1V4), '--with-v3-strict', '--dry-run'),
                     ('--scenario', str(FIXTURE), '--with-v3-strict', '--with-tools-high', '--dry-run')):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                self.main(*argv)
            self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
