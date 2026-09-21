import json
import unittest
import tempfile
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from autogen_agentchat.agents import AssistantAgent
from experiments.run_scenario import CallBudget
from experiments.step_execution import make_client, perform_step, tool_instructions
from artifact_hook import make_observation
from deadlock_policy import evaluate_criteria, pin_criteria
from progress_signal import calculate_progress


def success(tool=None, agent_id='planner'):
    message = {'role':'assistant','content':json.dumps({'narrative':'done',
        'open_issue_ids':[], 'info_items':[], 'completion_declared':False})}
    if tool:
        message.update(content=None, tool_calls=[{'id':'call1','type':'function','function':
                        {'name':tool,'arguments':'{"path":"ACCEPTANCE.md"}'}}])
    return httpx.Response(200,json={'id':'fake','object':'chat.completion','created':0,'model':'fake-model',
        'choices':[{'index':0,'finish_reason':'tool_calls' if tool else 'stop','message':message}],
        'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})


def unknown400(name='print_tree'):
    return httpx.Response(400,json={'error':{'message':'Tool choice is none, but model called a tool',
        'code':'tool_use_failed','failed_generation':'{"name":"%s","arguments":{}}' % name}})


def parse400():
    # Truncated generation shape observed in session A-1-67aeab11753e41169f76116f260564f5 turn 8.
    return httpx.Response(400,json={'error':{'message':'Failed to parse tool call arguments as JSON',
        'type':'invalid_request_error','code':'tool_use_failed',
        'failed_generation':'{"name": "write_file", "arguments": {"path": "SPEC.md", "content": "abc\\n"}'}})


def write_call(content='short'):
    return httpx.Response(200,json={'id':'fake','object':'chat.completion','created':0,'model':'fake-model',
        'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'w1','type':'function','function':{'name':'write_file',
                'arguments':json.dumps({'path':'SPEC.md','content':content})}}]}}],
        'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_wire_format_matches_preserved_successful_probe(self):
        self.responses = [success('read_file'),success('read_file'),success()]
        await self.step()
        evidence = Path(__file__).resolve().parents[1] / 'reports/strict-probe-3472654ecfca4274b03383123aa03131/request.json'
        probe_request = json.loads(evidence.read_text(encoding='utf-8'))
        for request in self.requests[:2]:
            self.assertNotIn('response_format',request)
            self.assertIn('tools',request)
        final = self.requests[-1]
        self.assertEqual(final['response_format'],probe_request['response_format'])
        self.assertEqual(final['reasoning_effort'],probe_request['reasoning_effort'])
        self.assertNotIn('tools',final)
        self.assertNotIn('tool_choice',final)

    async def test_early_text_also_requires_strict_confirmation(self):
        self.responses=[success(),success()]
        result=await self.step()
        self.assertTrue(result['strict_used'])
        self.assertEqual(self.budget.used,2)
        self.assertNotIn('response_format',self.requests[0])
        self.assertTrue(self.requests[1]['response_format']['json_schema']['strict'])

    async def asyncSetUp(self):
        self.budget = CallBudget(3)
        self.responses, self.requests = [], []
        def handler(request):
            self.requests.append(json.loads(request.content))
            response = self.responses.pop(0)
            response.headers['X-Guardrail-Turn'] = str(len(self.requests))
            return response
        self.client = make_client({'model':'fake-model','api_key':'fake','base_url':'http://mock/v1',
            'max_retries':0,'http_client':httpx.AsyncClient(transport=httpx.MockTransport(handler),
                event_hooks={'response':[self.budget.capture]}),
            'model_info':{'vision':False,'function_calling':True,'json_output':False,
                          'structured_output':False,'family':'unknown'}}, self.budget)
        self.written = []
        def read_file(path: str) -> str:
            """Read a synthetic test file."""
            return 'synthetic text'
        def write_file(path: str, content: str) -> str:
            """Record a synthetic write."""
            self.written.append((path, content))
            return 'written: ' + path
        self.allowed = ['read_file', 'write_file']
        self.agent = AssistantAgent('planner',model_client=self.client, tools=[read_file, write_file],
            reflect_on_tool_use=False,system_message=tool_instructions(self.allowed))

    async def asyncTearDown(self):
        await self.client.close()

    async def step(self):
        self.budget.reset()
        return await perform_step(self.agent, 'monitored_paths: [ACCEPTANCE.md]', self.budget, self.allowed)

    async def test_unknown_200_failed_step_then_next_step(self):
        self.responses = [success('print_tree'), success(), success(), success(), success()]
        first = await self.step()
        self.assertTrue(first['failed'])
        self.assertFalse(first['abort'])
        self.assertEqual(len(first['tool_errors']), 1)
        self.assertIn('해당 도구는 없다', first['feedback'])
        second = await self.step()
        self.assertFalse(second['failed'])
        self.assertEqual(len(self.requests), 5)

    async def test_two_unknown_400_same_step_abort(self):
        self.responses = [unknown400(), unknown400()]
        result = await self.step()
        self.assertTrue(result['abort'])
        self.assertEqual(len(result['tool_errors']), 2)
        self.assertEqual(self.budget.used, 2)
        self.assertEqual(self.budget.turns, [1, 2])
        self.assertIn('등록된 도구만', self.requests[1]['messages'][-1]['content'])

    async def test_one_unknown_400_can_advance(self):
        self.responses = [unknown400(), success(), success()]
        result = await self.step()
        self.assertTrue(result['failed'])
        self.assertFalse(result['abort'])

    async def test_tool_choice_auto_and_tools_on_non_final_requests(self):
        self.responses = [success('read_file'), success(), success()]
        result = await self.step()
        self.assertFalse(result['failed'])
        self.assertTrue(result['final_output'])
        self.assertEqual(len(self.requests), 3)
        for request in self.requests[:2]:
            self.assertEqual(request['tool_choice'], 'auto')
            self.assertEqual([t['function']['name'] for t in request['tools']], self.allowed)

    async def test_final_call_carries_no_tools(self):
        self.responses = [success('read_file'), success('read_file'), success()]
        result = await self.step()
        self.assertFalse(result['failed'])
        self.assertEqual(len(self.requests), 3)
        self.assertIn('tools', self.requests[1])
        final = self.requests[2]
        self.assertNotIn('tools', final)
        self.assertNotIn('tool_choice', final)
        self.assertIn('final call of this step', final['messages'][0]['content'])
        wire = json.dumps(final, ensure_ascii=False)
        self.assertNotIn('otherwise use a registered tool', wire)
        self.assertNotIn('Available tool vocabulary', wire)
        self.assertNotIn('For THIS role only these tools', wire)

    async def test_tool_then_tool_exhausts_budget_is_failed_no_final_output(self):
        # Provider rejects a registered tool generated on the tool-free final call.
        self.responses = [success('read_file'), success('read_file'), unknown400('read_file')]
        result = await self.step()
        self.assertTrue(result['failed'])
        self.assertFalse(result['abort'])
        self.assertFalse(result['final_output'])
        self.assertEqual(result['failure_reasons'], ['strict_http_400', 'no_final_output'])
        self.assertEqual(result['strict_failure'], 'strict_http_400')
        self.assertEqual(self.budget.used, 3)

    async def test_tool_result_as_last_response_is_failed_no_final_output(self):
        # Even if a provider returned tool calls on the final call, the step has no final text.
        self.responses = [success('read_file'), success('read_file'), success('read_file')]
        result = await self.step()
        self.assertTrue(result['failed'])
        self.assertEqual(result['failure_reasons'], ['strict_schema_mismatch', 'no_final_output'])
        self.assertEqual(result['text'], 'synthetic text')
        self.assertEqual(self.budget.used, 3)

    async def test_unknown_on_last_call_does_not_add_extra_call(self):
        self.responses = [success('read_file'), success('read_file'), unknown400()]
        result = await self.step()
        self.assertTrue(result['failed'])
        self.assertFalse(result['abort'])
        self.assertEqual(result['failure_reasons'], ['strict_http_400', 'no_final_output'])
        self.assertEqual(self.budget.used, 3)

    async def test_invalid_arguments_retry_once_then_succeeds(self):
        self.responses = [parse400(), write_call('SPEC part'), success()]
        result = await self.step()
        self.assertFalse(result['abort'])
        self.assertTrue(result['final_output'])
        self.assertEqual(self.written, [('SPEC.md', 'SPEC part')])
        self.assertEqual(len(self.requests), 3)
        retry = self.requests[1]
        self.assertIn('더 짧은 단위로 나눠 호출하라', retry['messages'][-1]['content'])
        self.assertEqual([t['function']['name'] for t in retry['tools']], self.allowed)
        self.assertEqual(result['tool_errors'][0]['kind'], 'invalid_tool_arguments')
        self.assertEqual(result['tool_errors'][0]['tool'], 'write_file')
        # Same policy as unknown tools: a recovered invalid response still marks the step failed.
        self.assertTrue(result['failed'])
        self.assertEqual(result['failure_reasons'], ['invalid_tool_arguments'])

    async def test_invalid_arguments_twice_aborts(self):
        self.responses = [parse400(), parse400()]
        result = await self.step()
        self.assertTrue(result['abort'])
        self.assertEqual(result['error'], 'invalid_tool_arguments_repeated_in_step')
        self.assertEqual(result['failure_reasons'], ['invalid_tool_arguments', 'aborted'])
        self.assertEqual(self.budget.used, 2)
        self.assertEqual(self.written, [])

    async def test_other_400_not_swallowed(self):
        self.responses = [httpx.Response(400,json={'error':{'message':'seed unsupported','code':'invalid_parameter'}})]
        result = await self.step()
        self.assertTrue(result['abort'])
        self.assertEqual(result['tool_errors'], [])
        self.assertEqual(len(self.requests), 1)


class FailureObservationTests(unittest.TestCase):
    def test_failed_step_abstains_instead_of_stagnant(self):
        observation = make_observation(step_id=1,llm_turns=[1,2],text='', progress_source='both',
            progress_metric={'conversation':['open_issues_count'], 'artifact':['files_changed']},
            structured={'open_issue_ids':None,'info_items':None},artifact=None,
            termination_context={'declaration':'unknown','source_kind':'scenario_rule','evidence':'tool failure'})
        observation['progress'] = calculate_progress([], observation)
        self.assertEqual(evaluate_criteria([observation], pin_criteria())['decision'], 'unmeasured')


class RunnerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_consecutive_strict_failed_steps_saved_then_stop(self):
        bad = httpx.Response(400,json={'error':{'message':'strict rejected'}})
        mismatch = success()
        body=mismatch.json()
        body['choices'][0]['message']['content']='{"narrative":"missing other fields"}'
        result=await self.run_offline([success('read_file'),success('read_file'),bad,
            success('read_file'),success('read_file'),httpx.Response(200,json=body)],max_steps=3)
        self.assertEqual(result['code'],1)
        self.assertEqual(len(result['steps']),2)
        self.assertEqual(result['summary']['termination_reason'],'strict_output_failures')
        self.assertEqual([s['consecutive_strict_failures'] for s in result['steps']],[1,2])
        self.assertEqual([s['strict_failure'] for s in result['steps']],['strict_http_400','strict_schema_mismatch'])
        for step in result['steps']:
            self.assertEqual(step['step_status'],'failed')
            self.assertEqual(step['observation']['criteria']['decision'],'unmeasured')
            self.assertIn(str(step['step_id'])+'.ack.json',result['pending'])
        self.assertEqual(result['session']['status'],'ended')

    async def test_success_between_strict_failures_resets_streak(self):
        bad=lambda:httpx.Response(400,json={'error':{'message':'strict rejected'}})
        result=await self.run_offline([success('read_file'),success('read_file'),bad(),
            success(),success(),success('read_file'),success('read_file'),bad()],max_steps=3)
        self.assertEqual(result['code'],0)
        self.assertEqual([s['consecutive_strict_failures'] for s in result['steps']],[1,0,1])
        self.assertEqual(result['summary']['termination_reason'],'max_steps')

    async def test_invalid_final_json_is_failed_and_never_shared_as_narrative(self):
        for content in ('def source_code(): return 1', '', '{"agent_id":"planner"}'):
            with self.subTest(content=content):
                response = success()
                body = response.json()
                body['choices'][0]['message']['content'] = content
                run = await self.run_offline([success('read_file'), success('read_file'),
                    httpx.Response(200, json=body), success(agent_id='developer'), success(agent_id='developer')])
                first = run['steps'][0]
                self.assertEqual(first['step_status'], 'failed')
                self.assertEqual(first['measurement_status'], 'unmeasured')
                self.assertEqual(first['failure_reasons'], ['strict_schema_mismatch','no_final_output'])
                self.assertFalse(first['final_output'])
                self.assertEqual(first['observation']['criteria']['decision'], 'unmeasured')
                self.assertIsNone(first['observation']['artifact'])
                context = json.loads(run['upstream_requests'][3]['messages'][-1]['content'])
                self.assertEqual(context['recent_messages'], [{'agent':'planner','narrative':'[구조화 출력 없음]'}])
                self.assertEqual(run['steps'][1]['step_status'], 'completed')

    async def run_offline(self, responses, max_steps=2):
        """Run the real runner against an in-memory proxy and fake upstream. Returns run folder files."""
        import experiments.run_scenario as runner
        from scenario_schema import load_scenario
        from proxy import create_app
        from artifact_hook import capture_artifact
        project = Path(__file__).resolve().parents[1]
        scenario_path = project / 'scenarios/A-1-ambiguous-task-query.yaml'
        scenario = load_scenario(scenario_path).model_copy(deep=True)
        if hasattr(self, 'scenario_transform'):
            # Revalidated before the harness overrides below, which bypass validation.
            scenario = self.scenario_transform(scenario)
        # Synthetic harness only; production YAML and fixture remain untouched.
        scenario.termination.max_steps = max_steps
        scenario.model = 'fake-model'
        if hasattr(self, 'criteria_version'):
            scenario.criteria_version = self.criteria_version
        upstream_requests = []
        def upstream_handler(request):
            upstream_requests.append(json.loads(request.content))
            return responses(request) if callable(responses) else responses.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.yaml'; config.write_text(
                'criteria_version: ' + scenario.criteria_version if hasattr(self, 'criteria_version') else '{}')
            upstream = httpx.MockTransport(upstream_handler)
            extra = {'sleep': self.proxy_sleep} if hasattr(self, 'proxy_sleep') else {}
            app = create_app(root / 'logs', transport=upstream, config_path=config, **extra)
            real_client = httpx.AsyncClient
            class OfflineClient(real_client):
                def __init__(self, *a, **kw):
                    if 'transport' not in kw:
                        kw['transport'] = httpx.ASGITransport(app=app)
                    super().__init__(*a, **kw)
            def acceptance(work):
                artifact = capture_artifact(work.root, scenario.monitored_paths,
                    test_suite_id=scenario.success_criteria.test_suite.test_suite_id)
                artifact.update(test_pass_count=7,test_total_count=16)
                result = {'summary':{'passed':7,'tests':16},
                          'gate':{'machine_success':getattr(self, 'machine_success', False)},
                          'artifact':artifact,'error':None}
                return self.acceptance_transform(result) if hasattr(self, 'acceptance_transform') else result
            args = SimpleNamespace(scenario=scenario_path,run_index=1,temperature=0.0,
                output_root=root/'runs',no_context_buffer=False,context_buffer_messages=12,
                seed_probe=None,proxy_url='http://mock',
                collection_policy=getattr(self, 'collection_policy', 'legacy-failed-step-v1'))
            args.output_contract = getattr(self, 'output_contract', 'output-contract-v1')
            # Existing v2 tests pin v7 explicitly; v8 tests set runner_protocol themselves.
            args.runner_protocol = getattr(self, 'runner_protocol',
                'tool-capable-step-v7-issue-ids' if args.output_contract == 'output-contract-v2' else None)
            args.api_key_env = getattr(self, 'api_key_env', 'GROQ_API_KEY')
            with patch.object(runner,'ROOT',project), patch.object(runner,'load_scenario',return_value=scenario), \
                    patch.object(runner.Workspace,'acceptance',acceptance), \
                    patch('httpx.AsyncClient',OfflineClient), patch.dict('os.environ',{'GROQ_API_KEY':'fake'}), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = await runner.run(args)
            out = next((root/'runs').iterdir())
            read = lambda name: json.loads((out/name).read_text(encoding='utf-8'))
            files = {'code': code, 'steps': read('steps.json'), 'summary': read('summary.json'),
                     'session': read('session.json'), 'conditions': read('conditions.json'),
                     'registered': read('registered-tools.json'), 'upstream_requests': upstream_requests,
                     'pending': {p.name for p in (out/'observations').iterdir()}}
        return files

    async def test_failure_persisted_and_next_step_runs_offline(self):
        run = await self.run_offline([unknown400(), success(), success(),
                                     success(agent_id='developer'), success(agent_id='developer')])
        self.assertEqual(run['code'],0)
        steps = run['steps']
        self.assertEqual(len(steps),2)
        self.assertEqual(steps[0]['step_status'],'failed')
        self.assertEqual(steps[0]['failure_reasons'],['unknown_tool'])
        self.assertEqual(steps[0]['observation']['criteria']['decision'],'unmeasured')
        self.assertEqual(steps[1]['step_status'],'completed')
        self.assertEqual(steps[0]['agent'], 'planner')
        self.assertEqual(steps[1]['agent'], 'developer')
        self.assertIn('1.pending.json', run['pending'])
        self.assertIn('1.ack.json', run['pending'])
        session = run['session']
        self.assertEqual(session['status'],'ended')
        self.assertEqual(len(session['turns']),5)
        self.assertTrue(all(t['request_body']['tool_choice']=='auto' for t in session['turns'] if 'tools' in t['request_body']))
        self.assertEqual(run['conditions']['runner_protocol'], 'tool-capable-step-v5-strict')
        self.assertEqual(run['conditions']['scenario']['scenario_revision'], 4)
        self.assertEqual(run['registered']['developer'], ['read_file','write_file','replace_in_file','run_tests'])

    async def test_no_final_output_step_is_failed_unmeasured_and_hidden_from_other_roles(self):
        # planner: read, read, then a registered tool generated on the tool-free final call.
        responses = [success('read_file'), success('read_file'), unknown400('read_file'),
                     success(agent_id='developer'), success(agent_id='developer')]
        run = await self.run_offline(responses)
        self.assertEqual(run['code'],0)
        first, second = run['steps']
        self.assertEqual(first['step_status'],'failed')
        self.assertEqual(first['measurement_status'],'unmeasured')
        self.assertFalse(first['final_output'])
        self.assertEqual(first['failure_reasons'],['strict_http_400','no_final_output'])
        self.assertEqual(first['llm_calls'],3)
        observation = first['observation']
        self.assertIsNone(observation['artifact'])
        self.assertIsNone(observation['conversation']['open_issue_ids'])
        self.assertEqual(observation['progress']['state'],'unmeasured')
        self.assertEqual(observation['criteria']['decision'],'unmeasured')
        self.assertEqual(run['summary']['failed_steps'],[{'step_id':1,'reasons':['strict_http_400','no_final_output']}])
        self.assertEqual(second['step_status'],'completed')
        # Final call of the planner step reached upstream without tools.
        planner_requests = run['upstream_requests'][:3]
        self.assertIn('tools', planner_requests[1])
        self.assertNotIn('tools', planner_requests[2])
        self.assertNotIn('tool_choice', planner_requests[2])
        # The developer sees a placeholder, never the ACCEPTANCE.md text the planner read.
        acceptance_text = (Path(__file__).resolve().parents[1] /
                           'scenario_assets/A-1/ACCEPTANCE.md').read_text(encoding='utf-8')
        developer_context = json.loads(run['upstream_requests'][3]['messages'][-1]['content'])
        self.assertEqual(developer_context['recent_messages'],
                         [{'agent':'planner','narrative':'[구조화 출력 없음]'}])
        probe = 'NFKC 정규화 후 casefold한다'
        self.assertIn(probe, acceptance_text)
        self.assertIn(probe, json.dumps(run['upstream_requests'][2], ensure_ascii=False))
        self.assertNotIn(probe, json.dumps(run['upstream_requests'][3], ensure_ascii=False))

    async def test_recent_messages_carry_parsed_narrative_only(self):
        run = await self.run_offline([success(), success(), success(agent_id='developer'),success(agent_id='developer')])
        developer_context = json.loads(run['upstream_requests'][2]['messages'][-1]['content'])
        self.assertEqual(developer_context['recent_messages'], [{'agent':'planner','narrative':'done'}])
