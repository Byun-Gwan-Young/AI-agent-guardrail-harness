import json
from pathlib import Path
import tempfile
import unittest
import httpx
from autogen_core.models import SystemMessage, UserMessage
from experiments.output_contract import parse_output, output_schema
from experiments.step_execution import final_messages
from experiments.probe_strict_output import probe, request_body, assess

VALUE = {'narrative':'probe','open_issue_ids':[],'info_items':[],'completion_declared':False}


class ContractTests(unittest.TestCase):
    def test_model_has_only_four_fields(self):
        schema = output_schema()
        self.assertEqual(set(schema['properties']),set(VALUE))
        self.assertEqual(set(schema['required']),set(VALUE))
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(parse_output(json.dumps(VALUE)),VALUE)
        for identifier in ('agent_id','step_id'):
            with self.assertRaises(ValueError): parse_output(json.dumps({**VALUE,identifier:'spoof'}))

    def test_unknown_values_remain_null(self):
        value = {**VALUE,'open_issue_ids':None,'info_items':None}
        self.assertEqual(parse_output(json.dumps(value)),value)

    def test_final_prompt_removes_all_work_directives(self):
        source = [SystemMessage(content='Use tools to inspect/edit. otherwise use a registered tool.'),
            UserMessage(source='user',content=json.dumps({'task':'task','step_id':1,'registered_tools':['read_file'],
                'tool_feedback':'Call replace_in_file now','acceptance':{'passed':7}})),
            UserMessage(source='user',content='otherwise use a registered tool'),
            UserMessage(source='user',content='인자가 JSON 으로 파싱되지 않았다. 나눠 호출하라.')]
        result = final_messages(source)
        text = '\n'.join(m.content for m in result)
        for forbidden in ('otherwise use', 'Use tools to inspect/edit', 'Call replace_in_file',
                          '나눠 호출하라', 'registered_tools', 'agent_id', 'step_id'):
            self.assertNotIn(forbidden,text)
        self.assertIn('No tools are available',text)
        self.assertIn('"passed": 7',text)


class ProbeTests(unittest.TestCase):
    def test_exactly_one_request_no_retry_on_429(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(429,json={'error':{'message':'rate limit'}})
        with tempfile.TemporaryDirectory() as d, httpx.Client(transport=httpx.MockTransport(handler)) as client:
            folder,result=probe(client,'fake-secret',Path(d))
            self.assertEqual(result['outcome'],'inconclusive')
            self.assertEqual(len(calls),1)
            data=json.loads((folder/'request.json').read_text())
            self.assertTrue(data['response_format']['json_schema']['strict'])
            self.assertNotIn('tools',data)
            self.assertNotIn('fake-secret',(folder/'request.json').read_text())

    def test_success_and_truncation_distinguished(self):
        body={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(VALUE)}}]}
        self.assertEqual(assess(200,body)['outcome'],'probe_passed')
        body['choices'][0]['finish_reason']='length'
        self.assertEqual(assess(200,body)['outcome'],'inconclusive')

    def test_wrong_fields_and_server_error_not_support_evidence(self):
        body={'choices':[{'finish_reason':'stop','message':{'content':'{"agent_id":"planner"}'}}]}
        self.assertEqual(assess(200,body)['outcome'],'inconclusive')
        self.assertEqual(assess(500,{'error':'server error'})['outcome'],'inconclusive')
