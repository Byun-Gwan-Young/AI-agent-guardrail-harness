"""C-17-7: several tool calls in one model response, offline. Confirmation only (D-32): no runner behaviour changes.

gpt-oss returned one tool call per response in every recorded session; in the 2026-09-29 gateway probe Claude
Sonnet 5, Claude Haiku 4.5 and gpt-5.5 each returned three (reports/c17-7/evidence.json). These tests pin what the
runner does today with such a response on the artifact path, so a change before the cross-check (D-32) is visible.
"""
import json
from pathlib import Path

import httpx

from experiments.step_execution import PROTOCOL_V10
import test_harness_facts as facts
import test_tool_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]
A1V4 = ROOT / 'scenarios/A-1-v4-ambiguous-task-query.yaml'
PATHS = ('SPEC.md', 'ACCEPTANCE.md', 'missing.md')


def three_reads():
    message = {'role': 'assistant', 'content': None,
               'tool_calls': [{'id': 'call%d' % i, 'type': 'function',
                               'function': {'name': 'read_file', 'arguments': json.dumps({'path': p})}}
                              for i, p in enumerate(PATHS)]}
    return httpx.Response(200, json={'id': 'fake', 'object': 'chat.completion', 'created': 0, 'model': 'fake-model',
                                     'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': message}],
                                     'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


class MultiToolCallTests(facts.Runner):
    scenario_path = A1V4
    runner_protocol = PROTOCOL_V10

    async def test_one_response_with_three_calls_is_one_model_call_and_three_executions(self):
        run = await self.run_offline([three_reads(), recovery.success(), facts.final()], max_steps=1)
        step = run['steps'][0]
        # The tool round costs one model call of the step budget, however many calls it carries.
        self.assertEqual((run['code'], step['llm_calls']), (0, 3))
        self.assertTrue(step['final_output'])
        executions = step['tool_executions']
        self.assertEqual([(e['tool'], e['llm_call_in_step']) for e in executions], [('read_file', 1)] * 3)
        # A failing call among them is recorded as a tool error and fails the step (G0-6), as for a single call;
        # the other calls of the response still ran.
        self.assertEqual([e['is_error'] for e in executions], [False, False, True])
        self.assertEqual((step['step_status'], step['failure_reasons'], step['tool_errors']),
                         ('failed', ['tool_execution_error'], []))
        # All three results go back to the model in the next request, in the response's call order.
        follow_up = run['upstream_requests'][1]['messages']
        results = [m for m in follow_up if m['role'] == 'tool']
        self.assertEqual([m['tool_call_id'] for m in results], ['call0', 'call1', 'call2'])
        # The proxy counts the calls of the response; parallel_tool_calls is never sent.
        self.assertEqual(run['session']['turns'][0]['tool_calls'], 3)
        self.assertTrue(all('parallel_tool_calls' not in r for r in run['upstream_requests']))
