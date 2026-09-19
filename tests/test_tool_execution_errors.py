"""G0-6: executed tool errors are recorded and fail the recorded step without changing control flow."""
import copy
import json
from pathlib import Path
import unittest

import httpx

from experiments.observation_collection import INDEPENDENT
from experiments.issue_contract import V2
from scenario_schema import Scenario
import test_tool_recovery as recovery
from test_issue_vocabulary import VOCAB, v2_response
from tools import audit_tool_execution_errors as audit

ROOT = Path(__file__).resolve().parents[1]


def tool_call(name, arguments, call_id='t1'):
    return httpx.Response(200, json={'id': 'fake', 'object': 'chat.completion', 'created': 0, 'model': 'fake-model',
        'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': call_id, 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


def final(declared=False):
    body = recovery.success().json()
    body['choices'][0]['message']['content'] = json.dumps({'narrative': 'reported', 'open_issue_ids': [],
        'info_items': [], 'completion_declared': declared})
    return httpx.Response(200, json=body)


UNAUTHORIZED = tool_call('write_file', {'path': 'src/task_query.py', 'content': 'x'})
MISSING_READ = tool_call('read_file', {'path': 'missing.md'})


def with_tool(call, last):
    # A tool round, then an early text answer, then the dedicated strict final call.
    return [call, recovery.success(), last]


def plain(last=None):
    return [recovery.success(), last or recovery.success()]


def recent_messages_after(requests, step_count):
    for request in requests:
        try:
            context = json.loads(request['messages'][-1]['content'])
        except (TypeError, ValueError):
            continue
        if isinstance(context, dict) and len(context.get('recent_messages') or []) >= step_count:
            return context['recent_messages']


class LegacyPathTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline

    async def test_unauthorized_edit_fails_recorded_step_but_output_flow_is_unchanged(self):
        r = await self.run_offline(with_tool(UNAUTHORIZED, final()) + plain())
        first, second = r['steps']
        self.assertEqual(first['step_status'], 'failed')
        self.assertEqual(first['failure_reasons'], ['tool_execution_error'])
        self.assertEqual(first['tool_executions'], [{'llm_call_in_step': 1, 'tool': 'write_file', 'call_id': 't1',
            'is_error': True, 'error_summary': 'Role is not authorized to edit this file'}])
        # Output validity is independent of the tool error: the narrative is still shared and observed.
        self.assertEqual(first['measurement_status'], 'observed')
        self.assertEqual(first['observation']['conversation']['open_issue_ids'], [])
        self.assertIsNotNone(first['observation']['artifact'])
        self.assertEqual(recent_messages_after(r['upstream_requests'], 1)[0]['narrative'], 'reported')
        # Same call count and no extra retry or abort.
        self.assertEqual((first['llm_calls'], first['strict_failure'], first['call_error']), (3, None, None))
        self.assertEqual(second['step_status'], 'completed')
        self.assertEqual(second['tool_executions'], [])
        self.assertEqual(r['summary']['failed_steps'], [{'step_id': 1, 'reasons': ['tool_execution_error']}])

    async def test_success_termination_still_happens_on_a_step_with_a_tool_error(self):
        self.machine_success = True
        r = await self.run_offline(plain() + plain() + with_tool(MISSING_READ, final(declared=True)), max_steps=5)
        self.assertEqual(r['summary']['termination_reason'], 'success')
        self.assertEqual(len(r['steps']), 3)
        last = r['steps'][-1]
        self.assertEqual((last['agent'], last['step_status'], last['failure_reasons']),
                         ('reviewer', 'failed', ['tool_execution_error']))
        self.assertTrue(last['tool_executions'][0]['is_error'])
        self.assertIn('missing.md', last['tool_executions'][0]['error_summary'])

    async def test_successful_tool_is_recorded_without_failing(self):
        r = await self.run_offline(with_tool(recovery.success('read_file'), final()) + plain())
        first = r['steps'][0]
        self.assertEqual(first['step_status'], 'completed')
        self.assertEqual(first['failure_reasons'], [])
        self.assertEqual([(e['tool'], e['is_error'], e['error_summary']) for e in first['tool_executions']],
                         [('read_file', False, None)])


class IndependentV2PathTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'
    output_contract = V2

    def scenario_transform(self, scenario):
        data = scenario.model_dump(); data.update(copy.deepcopy(VOCAB))
        return Scenario.model_validate(data)

    async def test_tool_error_keeps_both_observation_sources(self):
        r = await self.run_offline([UNAUTHORIZED, v2_response(), v2_response(), v2_response(), v2_response()])
        first = r['steps'][0]
        self.assertEqual(first['step_status'], 'failed')
        self.assertEqual(first['failure_reasons'], ['tool_execution_error'])
        self.assertEqual(first['collection']['final_output_status'], 'valid')
        self.assertIsNotNone(first['observed_final_report'])
        self.assertEqual(first['observation']['conversation']['open_issue_ids'], ['fixture-core'])
        self.assertIsNotNone(first['observation']['artifact'])
        self.assertEqual((first['consecutive_strict_failures'], first['vocabulary_violation']), (0, None))


class OfflineAuditTests(unittest.TestCase):
    def test_saved_audit_is_reproducible(self):
        log = json.loads((ROOT / audit.LOG).read_text(encoding='utf-8'))
        report = audit.audit(log)
        saved = json.loads((ROOT / 'reports/g0-6/tool-execution-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(report, saved)
        step7 = next(s for s in report['steps'] if s['step_id'] == 7)
        self.assertTrue(step7['would_fail_with_tool_execution_error'])
        self.assertIn('Role is not authorized to edit this file',
                      [e['error_summary'] for e in step7['tool_executions'] if e['is_error']])
