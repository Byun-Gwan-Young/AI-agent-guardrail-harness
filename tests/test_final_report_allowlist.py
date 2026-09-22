import json
import unittest

from experiments.step_execution import PROTOCOL_V9, PROTOCOL_V10, allowlisted_final_record
from test_harness_facts import Runner
from test_reasoning_all_calls import A1V4
from test_tool_recovery import success


def with_thought(response, text):
    body = response.json()
    body['choices'][0]['message']['reasoning_content'] = text
    return type(response)(200, json=body)


class V10SnapshotTests(Runner):
    scenario_path = A1V4

    async def test_v10_differs_from_v9_only_by_final_request_thought(self):
        responses = lambda: [with_thought(success(), 'synthetic thought'), success()]
        self.runner_protocol = PROTOCOL_V9
        v9 = await self.run_offline(responses(), max_steps=1)
        self.runner_protocol = PROTOCOL_V10
        v10 = await self.run_offline(responses(), max_steps=1)
        self.assertEqual(len(v9['upstream_requests']), len(v10['upstream_requests']))
        self.assertEqual(v9['upstream_requests'][0], v10['upstream_requests'][0])
        old_final = v9['upstream_requests'][1]
        new_final = v10['upstream_requests'][1]
        self.assertEqual({k: v for k, v in old_final.items() if k != 'messages'},
                         {k: v for k, v in new_final.items() if k != 'messages'})
        old_payload = json.loads(old_final['messages'][-1]['content'])
        new_payload = json.loads(new_final['messages'][-1]['content'])
        old_record = old_payload['observed_records'][0]
        self.assertEqual(new_payload['observed_records'][0],
                         {k: v for k, v in old_record.items() if k != 'thought'})
        self.assertNotIn('synthetic thought', new_final['messages'][-1]['content'])
        self.assertEqual(v10['conditions']['runner_protocol'], PROTOCOL_V10)
        self.assertEqual(v9['conditions']['runner_protocol'], PROTOCOL_V9)


class AllowlistUnitTests(unittest.TestCase):
    def test_keeps_only_approved_tool_evidence(self):
        assistant = {'type': 'AssistantMessage', 'source': 'role', 'thought': 'hidden',
                     'content': [{'id': 'call-1', 'name': 'read_file', 'arguments': '{"path":"a"}',
                                  'future_sdk_field': 'hidden'}]}
        result = {'type': 'FunctionExecutionResultMessage', 'metadata': {'hidden': 'value'},
                  'content': [{'call_id': 'call-1', 'name': 'read_file', 'content': 'file body',
                               'is_error': False, 'future_sdk_field': 'hidden'}]}
        self.assertEqual(allowlisted_final_record(assistant), {
            'source': 'role', 'type': 'AssistantMessage',
            'content': [{'name': 'read_file', 'arguments': '{"path":"a"}'}]})
        self.assertEqual(allowlisted_final_record(result), {
            'type': 'FunctionExecutionResultMessage',
            'content': [{'name': 'read_file', 'content': 'file body'}]})
