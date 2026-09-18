import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from pydantic import ValidationError

from experiments.observation_collection import (DEFAULT_POLICY, INDEPENDENT, LEGACY, PROTOCOLS,
    validate_final_response, select_sources, collection_metadata, unavailable)
from experiments.output_contract import strict_response_format
from experiments.run_scenario import CallBudget, deliver
from artifact_hook import make_observation
from progress_schema import Observation
from proxy import create_app
from test_role_progress import obs
import test_tool_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]
VALUE = dict(narrative='recovered report',open_issue_ids=[],info_items=None,completion_declared=False)


def response(value=None, finish='stop'):
    data = recovery.success().json()
    data['choices'][0]['finish_reason'] = finish
    data['choices'][0]['message']['content'] = json.dumps(VALUE if value is None else value)
    return httpx.Response(200,json=data)


def evidence(value=None):
    return dict(request={'response_format':strict_response_format()},response=response(value).json(),
                status_code=200,turn=7,step_turns=[6,7])


class FinalEvidenceTests(unittest.TestCase):
    def test_valid_report_keeps_null_and_linked_source(self):
        r = validate_final_response(**evidence())
        self.assertEqual(r['status'],'valid'); self.assertEqual(r['source_turn'],7)
        self.assertIsNone(r['value']['info_items'])

    def test_missing_or_wrong_step_link_cannot_recover(self):
        for turn in (None,0,8,True):
            e=evidence(); e['turn']=turn
            self.assertEqual(validate_final_response(**e)['status'],'unmeasured')

    def test_requires_final_request_http_stop_and_no_tool_output(self):
        for kind in ('work_call','http400','http429','length','tool','content_type','multiple_choices'):
            e=evidence()
            if kind=='work_call': e['request']={}
            if kind.startswith('http'): e['status_code']=int(kind[4:])
            if kind=='length': e['response']['choices'][0]['finish_reason']='length'
            if kind=='tool': e['response']['choices'][0]['message']['tool_calls']=[{'id':'x'}]
            if kind=='content_type': e['response']['choices'][0]['message']['content']=None
            if kind=='multiple_choices': e['response']['choices'].append(e['response']['choices'][0])
            with self.subTest(kind=kind):
                self.assertNotEqual(validate_final_response(**e)['status'],'valid')
                self.assertIsNone(validate_final_response(**e)['value'])

    def test_no_partial_parsing_for_invalid_json_fields_types_or_duplicate_ids(self):
        for content in ('{"narrative":',json.dumps({'narrative':'only'}),
                        json.dumps({**VALUE,'completion_declared':'false'}),
                        json.dumps({**VALUE,'open_issue_ids':['x','x']}),json.dumps({**VALUE,'agent_id':'spoof'})):
            e=evidence(); e['response']['choices'][0]['message']['content']=content
            self.assertEqual(validate_final_response(**e)['status'],'invalid')
            self.assertIsNone(validate_final_response(**e)['value'])

    def test_independent_artifact_even_when_no_report_legacy_still_discards(self):
        artifact={'file_hashes':None,'test_pass_count':3,'build_status':None}
        for policy in (LEGACY,INDEPENDENT):
            parsed, kept=select_sources(policy,failed=True,legacy_parsed=None,
                                        final_report=unavailable('429'),artifact=artifact)
            self.assertIsNone(parsed)
            self.assertEqual(kept,artifact if policy==INDEPENDENT else None)

    def test_source_coverage_marks_missing_values_unmeasured_without_filling(self):
        a={'file_hashes':{},'test_pass_count':None,'build_status':'not_run'}
        m=collection_metadata(INDEPENDENT,unavailable('missing'),None,a,'both',
            {'conversation':['open_issues_count','new_info_ratio'],'artifact':['files_changed','test_pass_count','build_status']})
        self.assertEqual(m['measurement_status'],'partial')
        self.assertEqual(m['metric_status']['artifact.test_pass_count'],'unmeasured')
        self.assertEqual(m['metric_status']['artifact.files_changed'],'measured')
        self.assertIsNone(a['test_pass_count'])

    def test_protected_calculators_model_contract_and_original_reports_unchanged(self):
        hashes=json.loads((ROOT/'tests/fixtures/p0-2-protected-files.json').read_text())
        for path,expected in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),expected,path)

    def test_default_policy_and_protocol_are_new(self):
        self.assertEqual(DEFAULT_POLICY,INDEPENDENT)
        self.assertNotEqual(PROTOCOLS[INDEPENDENT],PROTOCOLS[LEGACY])


class BudgetEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_and_reset_do_not_reuse_previous_step_report(self):
        b=CallBudget(3); b.consume()
        req=httpx.Request('POST','http://mock',json={'response_format':strict_response_format()})
        r=httpx.Response(200,json=response().json(),request=req,headers={'X-Guardrail-Turn':'1'})
        await b.capture(r); b.confirm_final_report(json.dumps(VALUE))
        self.assertEqual(b.observation_report()['status'],'valid')
        b.reset(); self.assertIsNone(b.observation_report()['value'])
        b.consume(); self.assertIsNone(b.observation_report()['value'])


class IndependentRunnerTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'

    async def test_recovered_unknown_tool_keeps_failed_and_observation_only_narrative(self):
        r=await self.run_offline([recovery.unknown400(),recovery.success(),response(),recovery.success(),recovery.success()])
        first=r['steps'][0]; o=first['observation']
        self.assertEqual(first['step_status'],'failed'); self.assertEqual(first['failure_reasons'],['unknown_tool'])
        self.assertEqual(o['conversation']['open_issue_ids'],[]); self.assertIsNone(o['conversation']['info_items'])
        self.assertIsNotNone(o['artifact']); self.assertEqual(o['termination_context']['declaration'],'none')
        self.assertEqual(o['collection']['source_turn'],first['llm_turns'][-1])
        self.assertEqual(first['observed_final_report']['narrative'],VALUE['narrative'])
        incoming=json.loads(r['upstream_requests'][3]['messages'][-1]['content'])
        self.assertEqual(incoming['recent_messages'],[{'agent':'planner','narrative':'[구조화 출력 없음]'}])
        self.assertEqual(r['conditions']['collection_policy'],INDEPENDENT)
        self.assertEqual(r['conditions']['runner_protocol'],PROTOCOLS[INDEPENDENT])
        for req in r['upstream_requests']:
            self.assertNotIn('agent_id',json.dumps(req['messages']))

    async def test_recovered_argument_error_keeps_original_failure_and_calls(self):
        r=await self.run_offline([recovery.success('read_file'),recovery.parse400(),response(),recovery.success(),recovery.success()])
        s=r['steps'][0]
        self.assertEqual(s['failure_reasons'],['invalid_tool_arguments'])
        self.assertEqual(s['llm_calls'],len(s['llm_turns']))
        self.assertEqual(s['collection']['final_output_status'],'valid')
        self.assertEqual(s['observation']['agent_id'],s['agent'])

    async def test_429_has_no_report_but_keeps_actual_artifact_and_abort(self):
        async def no_wait(delay): pass
        self.proxy_sleep=no_wait
        r=await self.run_offline(lambda request:httpx.Response(429,json={'error':{'message':'limit'}}))
        s=r['steps'][0]
        self.assertEqual(r['summary']['termination_reason'],'runner_error')
        self.assertIn('aborted',s['failure_reasons']); self.assertEqual(s['step_status'],'failed')
        self.assertIsNone(s['observed_final_report']); self.assertIsNotNone(s['observation']['artifact'])
        self.assertEqual(s['observation']['termination_context']['declaration'],'unknown')
        self.assertEqual(s['observation']['criteria']['decision'],'unmeasured')

    async def test_failed_final_call_never_promotes_stale_early_valid_text(self):
        r=await self.run_offline([response(),httpx.Response(400,json={'error':{'message':'strict rejected'}}),
                                 recovery.success(),recovery.success()])
        s=r['steps'][0]
        self.assertIsNone(s['observed_final_report']); self.assertEqual(s['collection']['final_output_status'],'unmeasured')
        self.assertIsNone(s['observation']['conversation']['open_issue_ids'])
        self.assertIsNotNone(s['observation']['artifact'])
        self.assertFalse(s['final_output'])

    async def test_invalid_or_truncated_final_output_preserves_only_artifact(self):
        for final in (response({'narrative':'partial'}),response(finish='length')):
            r=await self.run_offline([recovery.success('read_file'),recovery.success('read_file'),final,
                                     recovery.success(),recovery.success()])
            s=r['steps'][0]
            self.assertIsNone(s['observed_final_report'])
            self.assertEqual(s['collection']['final_output_status'],'invalid')
            self.assertIn('strict_schema_mismatch',s['failure_reasons'])
            self.assertIsNotNone(s['observation']['artifact'])

    async def test_failed_artifact_collection_does_not_erase_valid_conversation(self):
        def missing(result):
            result['artifact']=None; result['error']='synthetic collection failure'; return result
        self.acceptance_transform=missing
        r=await self.run_offline([recovery.unknown400(),recovery.success(),response(),recovery.success(),recovery.success()])
        s=r['steps'][0]; o=s['observation']
        self.assertIsNotNone(s['observed_final_report']); self.assertIsNone(o['artifact'])
        self.assertEqual(o['collection']['metric_status']['artifact.files_changed'],'unmeasured')

    async def test_repeated_tool_errors_preserve_abort_without_inventing_final(self):
        r=await self.run_offline([recovery.unknown400(),recovery.unknown400()])
        s=r['steps'][0]
        self.assertIn('aborted',s['failure_reasons']); self.assertIsNone(s['observed_final_report'])
        self.assertEqual(r['summary']['termination_reason'],'runner_error')

    async def test_recovered_reviewer_declaration_is_observation_only(self):
        self.machine_success=True
        responses=[recovery.success(),recovery.success(),recovery.success(),recovery.success(),
                   recovery.unknown400(),recovery.success(),response({**VALUE,'completion_declared':True}),
                   recovery.success(),recovery.success(),recovery.success(),recovery.success()]
        r=await self.run_offline(responses,max_steps=5)
        reviewer=next(s for s in r['steps'] if s['agent']=='reviewer')
        self.assertEqual(reviewer['step_status'],'failed')
        self.assertEqual(reviewer['observation']['termination_context']['declaration'],'declared')
        self.assertEqual(r['summary']['termination_reason'],'max_steps')
        self.assertEqual(r['steps'][-1]['observation']['termination_context']['declared_step'],reviewer['step_id'])

    async def test_same_role_next_step_compares_to_preserved_failed_step(self):
        r=await self.run_offline([recovery.unknown400(),recovery.success(),response(),
            recovery.success(),recovery.success(),recovery.success(),recovery.success(),recovery.success(),recovery.success()],max_steps=4)
        first,last=r['steps'][0],r['steps'][-1]
        self.assertEqual(last['observation']['progress']['comparison_step_id'],first['step_id'])
        self.assertEqual(last['observation']['progress']['version'],'progress-v2')


class CollectionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_duplicate_submission_and_restart_preserve_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=root/'config.yaml'; config.write_text('criteria_version: deadlock-v0.2\n')
            transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]}))
            app=create_app(root/'logs',transport,config_path=config)
            headers={'X-Guardrail-Session':'source'}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://mock') as c:
                await c.post('/v1/chat/completions',json={'messages':[]},headers=headers)
                receipt=validate_final_response(**{**evidence(), 'turn':1,'step_turns':[1]})
                artifact=obs(1)['artifact']; metrics={'conversation':['open_issues_count','new_info_ratio'],'artifact':['files_changed']}
                metadata=collection_metadata(INDEPENDENT,receipt,VALUE,artifact,'both',metrics)
                body=make_observation(step_id=1,agent_id='A',llm_turns=[1],text=VALUE['narrative'],
                    progress_source='both',progress_metric=metrics,artifact=artifact,
                    structured={k:VALUE[k] for k in ('open_issue_ids','info_items')},collection=metadata)
                first=await deliver(c,'source',body); duplicate=await deliver(c,'source',body)
                self.assertTrue(duplicate['duplicate']); self.assertEqual(first['observation'],duplicate['observation'])
                self.assertEqual(len(app.state.store.get('source').observations),1)
            new=create_app(root/'logs',transport,config_path=config)
            self.assertEqual(new.state.store.get('source').observations[0],first['observation'])
            body['collection']['source_turn']=2
            with self.assertRaises(ValidationError): Observation.model_validate(body)
