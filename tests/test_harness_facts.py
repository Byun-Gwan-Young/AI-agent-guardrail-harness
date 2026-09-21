"""G0-14 (defects 6 and 7): runner protocol v8 states the call budget and writable files as facts."""
import json
import re
from pathlib import Path
import unittest

import httpx

from experiments.observation_collection import INDEPENDENT
from experiments.issue_contract import V1, V2
from experiments.step_execution import (PROTOCOL_V7, PROTOCOL_V8, call_budget, harness_facts,
                                        with_call_budget)
from scenario_schema import load_scenario
from tools import check_harness_facts as checker
import test_tool_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]
A1V2 = ROOT / 'scenarios/A-1-v2-ambiguous-task-query.yaml'
A1V3 = ROOT / 'scenarios/A-1-v3-ambiguous-task-query.yaml'
G0_8 = 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e'
REPORT = dict(narrative='n', open_issue_ids=['requirements'], info_items=None,
              completion_declared=False, unlisted_issues=[])
# Words that would coach behaviour rather than state a fact.
ADVICE = {'should', 'must', 'avoid', 'first', 'instead', "don't", 'prefer', 'try', 'reread', 're-read'}


def final():
    body = recovery.success().json()
    body['choices'][0]['message']['content'] = json.dumps(REPORT)
    return httpx.Response(200, json=body)


def step_responses():
    # Tool round, early text answer, dedicated final call: exercises every message kind.
    return [recovery.success('read_file'), recovery.success(), final()]


class Runner(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'
    output_contract = V2
    scenario_path = A1V3

    def scenario_transform(self, scenario):
        return load_scenario(self.scenario_path)

    async def run_protocol(self, protocol, steps=3):
        self.runner_protocol = protocol
        return await self.run_offline([r for _ in range(steps) for r in step_responses()], max_steps=steps)


class FactTextTests(unittest.TestCase):
    def test_values_come_from_arguments_and_contain_no_advice(self):
        self.assertIn('Files this role can write: a.md, b.py.', harness_facts(['a.md', 'b.py'], 5))
        self.assertIn('at most 5 model calls', harness_facts(['a.md'], 5))
        self.assertIn('Files this role can write: none.', harness_facts([], 3))
        self.assertEqual(call_budget(2, 4), {'model_call': 2, 'max_model_calls': 4,
                                             'remaining_after_this_call': 2, 'last_call_has_no_tools': True})
        for text in (harness_facts(['x'], 3), with_call_budget('', 2, 3), json.dumps(call_budget(2, 3))):
            self.assertFalse(ADVICE & set(re.findall(r"[a-z'-]+", text.lower())), text)

    def test_json_context_gets_a_field_and_text_gets_a_sentence(self):
        context = json.dumps({'task': 't', 'recent_messages': []}, ensure_ascii=False)
        data = json.loads(with_call_budget(context, 1, 3))
        self.assertEqual(data.pop('call_budget'), call_budget(1, 3))
        self.assertEqual(json.dumps(data, ensure_ascii=False), context)
        self.assertEqual(with_call_budget('Continue.', 2, 3),
                         'Continue. Model call 2 of at most 3 in this step; 1 call(s) remain after this one, '
                         'and the last call of the step has no tools.')


class V8SnapshotTests(Runner):
    async def test_v8_differs_from_v7_only_by_the_fact_sentences(self):
        v7, v8 = await self.run_protocol(PROTOCOL_V7), await self.run_protocol(PROTOCOL_V8)
        self.assertEqual(len(v7['upstream_requests']), len(v8['upstream_requests']))
        kinds = set()
        scenario = load_scenario(A1V3)
        writable = {a.id: a.writable_paths for a in scenario.agents}
        limit = scenario.termination.max_llm_calls_per_step
        for old, new in zip(v7['upstream_requests'], v8['upstream_requests']):
            self.assertEqual({k: v for k, v in old.items() if k != 'messages'},
                             {k: v for k, v in new.items() if k != 'messages'})
            self.assertEqual(new['max_tokens'], scenario.max_tokens)
            if 'response_format' in new:
                self.assertEqual(old['messages'], new['messages']); kinds.add('final'); continue
            for a, b in zip(old['messages'], new['messages']):
                if a == b:
                    continue
                if a['role'] == 'system':
                    facts = [harness_facts(writable[r], limit) for r in writable]
                    used = [f for f in facts if f in b['content']]
                    self.assertEqual(len(used), 1)
                    self.assertEqual(b['content'].replace(used[0], '', 1), a['content'])
                    kinds.add('system')
                    continue
                try:
                    old_ctx, new_ctx = json.loads(a['content']), json.loads(b['content'])
                except (TypeError, ValueError):
                    self.assertTrue(b['content'].startswith(a['content']))
                    self.assertRegex(b['content'][len(a['content']):],
                                     r'^ ?Model call \d of at most %d in this step; \d call\(s\) remain' % limit)
                    kinds.add('continuation')
                    continue
                budget = new_ctx.pop('call_budget')
                self.assertEqual(new_ctx, old_ctx)
                self.assertEqual((budget['model_call'], budget['max_model_calls']), (1, limit))
                kinds.add('context')
        self.assertEqual(kinds, {'final', 'system', 'context', 'continuation'})
        self.assertEqual(v7['conditions']['runner_protocol'], PROTOCOL_V7)
        self.assertEqual(v8['conditions']['runner_protocol'], PROTOCOL_V8)
        self.assertIn('harness_facts_policy', v8['conditions'])
        self.assertNotIn('harness_facts_policy', v7['conditions'])
        for run in (v7, v8):
            self.assertIn('verified final report', run['conditions']['recent_messages_policy'])
        # Observations and judgements are unaffected by the prompt facts.
        self.assertEqual([s['observation']['progress']['state'] for s in v7['steps']],
                         [s['observation']['progress']['state'] for s in v8['steps']])

    async def test_each_role_gets_its_own_writable_list(self):
        run = await self.run_protocol(PROTOCOL_V8)
        scenario = load_scenario(A1V3)
        systems = {r['messages'][0]['content'] for r in run['upstream_requests'] if 'response_format' not in r}
        for agent in scenario.agents:
            fact = harness_facts(agent.writable_paths, scenario.termination.max_llm_calls_per_step)
            self.assertEqual(sum(fact in s for s in systems), 1, agent.id)

    async def test_values_follow_the_scenario_not_constants(self):
        def transform(scenario):
            loaded = load_scenario(A1V3)
            data = loaded.model_dump()
            data['termination']['max_llm_calls_per_step'] = 4
            data['agents'][2]['writable_paths'] = ['SPEC.md']
            data['agents'][2]['permissions'] = ['read_files', 'write_files', 'run_tests']
            return type(loaded).model_validate(data)
        self.scenario_transform = transform
        self.runner_protocol = PROTOCOL_V8
        run = await self.run_offline(step_responses() * 3, max_steps=3)
        prompt = json.dumps([r['messages'] for r in run['upstream_requests']], ensure_ascii=False)
        self.assertIn('at most 4 model calls', prompt)
        self.assertIn('Model call 2 of at most 4', prompt)
        self.assertNotIn('Files this role can write: none.', prompt)


class ProtocolSelectionTests(Runner):
    async def test_v1_contract_rejects_protocol_and_unknown_protocol_is_rejected(self):
        self.output_contract = V1
        self.scenario_path = ROOT / 'scenarios/A-1-ambiguous-task-query.yaml'
        self.collection_policy = 'legacy-failed-step-v1'
        self.criteria_version = 'deadlock-v0.1'
        self.runner_protocol = PROTOCOL_V8
        with self.assertRaises(ValueError):
            await self.run_offline(step_responses())
        self.output_contract, self.scenario_path = V2, A1V3
        self.collection_policy, self.criteria_version = INDEPENDENT, 'deadlock-v0.2'
        self.runner_protocol = 'tool-capable-step-v9-unknown'
        with self.assertRaises(ValueError):
            await self.run_offline(step_responses())


class V7ReproducesG08Tests(Runner):
    scenario_path = A1V2

    async def test_v7_system_messages_equal_the_ones_sent_in_g0_8(self):
        log = json.loads((ROOT / 'logs' / f'{G0_8}.json').read_text(encoding='utf-8'))
        sent = {t['request_body']['messages'][0]['content'] for t in log['turns']
                if 'response_format' not in t['request_body']}
        run = await self.run_protocol(PROTOCOL_V7)
        built = {r['messages'][0]['content'] for r in run['upstream_requests'] if 'response_format' not in r}
        self.assertEqual(built, sent)


class A1V3ScenarioTests(unittest.TestCase):
    def test_only_identity_and_max_tokens_differ_from_a1v2(self):
        old, new = load_scenario(A1V2).model_dump(), load_scenario(A1V3).model_dump()
        self.assertEqual((new.pop('scenario_id'), old.pop('scenario_id')), ('A-1-v3', 'A-1-v2'))
        self.assertEqual((new.pop('max_tokens'), old.pop('max_tokens')), (2400, 1200))
        # D-27: A-1-v3 runs on the gateway's Fireworks model; A-1-v2 (G0-8) stays on the Groq id.
        self.assertEqual((new.pop('model'), old.pop('model')),
                         ('accounts/fireworks/models/gpt-oss-120b', 'openai/gpt-oss-120b'))
        self.assertEqual(new, old)

    def test_preflight_record_is_reproducible(self):
        from tools.scenario_preflight import preflight
        saved = json.loads((ROOT / 'reports/a-1-v3/preflight-kmu.json').read_text(encoding='utf-8'))
        self.assertEqual(preflight(A1V3), saved)
        # The pre-provider-switch record is kept, not overwritten.
        older = json.loads((ROOT / 'reports/a-1-v3/preflight.json').read_text(encoding='utf-8'))
        self.assertNotEqual(older['scenario_sha256'], saved['scenario_sha256'])
        self.assertEqual(older['acceptance'], saved['acceptance'])


class G08CheckTests(unittest.TestCase):
    def test_saved_check_is_reproducible_and_shows_missing_facts(self):
        report = json.loads(json.dumps(checker.check(G0_8), ensure_ascii=False))
        saved = json.loads((ROOT / 'reports/a-1-v3/g0-8-harness-facts.json').read_text(encoding='utf-8'))
        self.assertEqual(report, saved)
        self.assertEqual(report['summary']['non_final_calls_with_budget_fact'], 0)
        self.assertEqual(sorted(report['summary']['roles_missing_writable_fact']), sorted(report['roles']))
