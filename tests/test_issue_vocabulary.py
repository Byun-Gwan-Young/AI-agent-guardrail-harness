import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx

from scenario_schema import Scenario, load_scenario
from experiments.issue_contract import (IssueContract, IssueContractViolation, ISSUE_ID_COLLISION,
                                        V1, V2, PROTOCOL_V2, for_scenario)
from experiments.output_contract import output_schema, strict_response_format, parse_output
from experiments.observation_collection import INDEPENDENT, validate_final_response
from experiments.run_scenario import CallBudget
from progress_signal import calculate_progress
from artifact_hook import make_observation
from progress_schema import Observation
import test_tool_recovery as recovery

ROOT = Path(__file__).resolve().parents[1]
VOCAB = json.loads((ROOT / 'tests/fixtures/p0-3-issue-vocabulary.json').read_text())
VALUE = dict(narrative='Synthetic report', open_issue_ids=['fixture-core'],
             info_items=None, completion_declared=False, unlisted_issues=['Unexpected synthetic boundary'])


def v2_response(value=None):
    body = recovery.success().json()
    body['choices'][0]['message']['content'] = json.dumps(VALUE if value is None else value)
    return httpx.Response(200, json=body)


def fixture_scenario():
    data = load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml').model_dump()
    data.update(copy.deepcopy(VOCAB))
    data.update(scenario_id='fixture-issue-contract', task='Synthetic issue contract exercise')
    return Scenario.model_validate(data)


class VocabularyTests(unittest.TestCase):
    def test_valid_subset_including_equal_and_empty(self):
        data = fixture_scenario().model_dump()
        for initial in ([], ['fixture-core'], ['fixture-core', 'fixture-edge']):
            self.assertEqual(Scenario.model_validate({**data, 'initial_issue_ids':initial}).initial_issue_ids, initial)

    def test_rejects_duplicate_empty_or_unknown_initial_ids(self):
        data = fixture_scenario().model_dump()
        for initial in (['fixture-core','fixture-core'], [''], [' '], ['outside'], [' fixture-core']):
            with self.subTest(initial=initial), self.assertRaises(ValueError):
                Scenario.model_validate({**data, 'initial_issue_ids':initial})

    def test_rejects_empty_duplicate_whitespace_ids_and_multiline_definitions(self):
        data = fixture_scenario().model_dump()
        invalid = [dict(id='',definition='x'), dict(id=' ',definition='x'),
                   dict(id='bad id',definition='x'), dict(id='fixture-edge',definition=''),
                   dict(id='fixture-edge',definition='x\ny')]
        for issue in invalid:
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                Scenario.model_validate({**data, 'allowed_issues':[data['allowed_issues'][0], issue]})
        with self.assertRaises(ValueError):
            Scenario.model_validate({**data,'allowed_issues':[data['allowed_issues'][0]] * 2})

    def test_original_a1_assets_and_previous_replay_unchanged(self):
        hashes = json.loads((ROOT / 'tests/fixtures/p0-3-protected-files.json').read_text())
        for path, digest in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)
        self.assertIsNone(load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml').allowed_issues)


class VersionedContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = for_scenario(V2, fixture_scenario())

    def test_legacy_schema_format_and_parser_are_unchanged(self):
        c = IssueContract(V1)
        self.assertEqual(c.schema(), output_schema())
        self.assertEqual(c.response_format(), strict_response_format())
        value = {k:v for k,v in VALUE.items() if k != 'unlisted_issues'}
        self.assertEqual(c.parse(json.dumps(value)), parse_output(json.dumps(value)))
        self.assertIsNone(c.sha256)

    def test_local_membership_exact_no_normalization_or_partial_output(self):
        for ids in (['outside'], ['fixture-core', 'outside'], ['FIXTURE-CORE'],
                    [' fixture-core'], ['fixture-core','fixture-core'], ['']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.contract.parse(json.dumps({**VALUE,'open_issue_ids':ids}))
        self.assertEqual(self.contract.parse(json.dumps(VALUE)), VALUE)

    def test_null_empty_and_info_items_meaning_preserved(self):
        for unknown in (None, []):
            value = {**VALUE,'unlisted_issues':unknown,'info_items':unknown,'open_issue_ids':unknown}
            self.assertEqual(self.contract.parse(json.dumps(value)), value)
        with self.assertRaises(ValueError):
            self.contract.parse(json.dumps({**VALUE,'info_items':'not a list'}))

    def test_new_field_required_short_and_no_agent_metadata(self):
        for value in ({k:v for k,v in VALUE.items() if k != 'unlisted_issues'},
                      {**VALUE,'unlisted_issues':['']}, {**VALUE,'unlisted_issues':[' ']},
                      {**VALUE,'unlisted_issues':['a\nb']}, {**VALUE,'unlisted_issues':['x'*241]},
                      {**VALUE,'agent_id':'spoof'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.contract.parse(json.dumps(value))

    def test_duplicate_unlisted_issues_rejected_exactly(self):
        with self.assertRaises(ValueError):
            self.contract.parse(json.dumps({**VALUE,'unlisted_issues':['Same text','Same text']}))
        # No normalization: case or spacing differences are distinct entries.
        value = {**VALUE,'unlisted_issues':['Same text','same text']}
        self.assertEqual(self.contract.parse(json.dumps(value)), value)

    def test_collision_rejects_whole_output_with_distinct_code_and_no_normalization(self):
        for unlisted in (['fixture-core'], ['Other issue','fixture-edge']):
            with self.subTest(unlisted=unlisted), self.assertRaises(IssueContractViolation) as ctx:
                self.contract.parse(json.dumps({**VALUE,'unlisted_issues':unlisted}))
            self.assertEqual(ctx.exception.code, ISSUE_ID_COLLISION)
        for other in (['outside'], ['fixture-core','fixture-core'], ['']):
            with self.subTest(open=other):
                try:
                    self.contract.parse(json.dumps({**VALUE,'open_issue_ids':other}))
                except IssueContractViolation:
                    self.fail('only the collision rule uses the collision code')
                except ValueError:
                    pass
        for near in (['FIXTURE-CORE'], [' fixture-core'], ['fixture-core ']):
            value = {**VALUE,'unlisted_issues':near}
            self.assertEqual(self.contract.parse(json.dumps(value)), value)

    def test_prompt_states_ids_definitions_and_collision_rule(self):
        text = self.contract.instructions()
        for issue in VOCAB['allowed_issues']:
            self.assertIn(issue['id'], text); self.assertIn(issue['definition'], text)
        self.assertIn('exactly equals an allowed ID', text)
        self.assertEqual(IssueContract(V1).instructions(), '')

    def test_provider_strict_shape_has_no_vocabulary_enum(self):
        fmt = self.contract.response_format()
        self.assertTrue(fmt['json_schema']['strict'])
        schema = fmt['json_schema']['schema']
        self.assertNotIn('enum', json.dumps(schema))
        self.assertNotIn('agent_id', json.dumps(schema))
        self.assertIn('unlisted_issues', schema['required'])

    def test_hash_includes_definitions_is_order_independent_without_normalization(self):
        reverse = IssueContract(V2, tuple(reversed(self.contract.allowed)))
        self.assertEqual(reverse.sha256, self.contract.sha256)
        changed = IssueContract(V2, (('fixture-core','Different definition'),))
        self.assertNotEqual(changed.sha256, self.contract.sha256)
        changed_case = IssueContract(V2, tuple((i.upper(),d) for i,d in self.contract.allowed))
        self.assertNotEqual(changed_case.sha256, self.contract.sha256)

    def test_no_vocabulary_fails_preflight_and_empty_vocabulary_is_explicit(self):
        old = load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml')
        with self.assertRaises(ValueError): for_scenario(V2, old)
        self.assertEqual(for_scenario(V1, old).version, V1)
        c = IssueContract(V2, ())
        self.assertEqual(c.parse(json.dumps({**VALUE,'open_issue_ids':[]}))['open_issue_ids'], [])

    def test_p0_2_receipt_uses_same_local_contract(self):
        args = dict(request={'response_format':self.contract.response_format()}, status_code=200,
                    turn=2,step_turns=[1,2],contract=self.contract)
        valid = validate_final_response(response=v2_response().json(), **args)
        self.assertEqual(valid['value'], VALUE)
        bad = validate_final_response(response=v2_response({**VALUE,'open_issue_ids':['outside']}).json(), **args)
        self.assertEqual(bad['status'], 'invalid'); self.assertIsNone(bad['value'])
        self.assertEqual(bad['reason'], 'final output contract violation')
        clash = validate_final_response(response=v2_response({**VALUE,'unlisted_issues':['fixture-core']}).json(), **args)
        self.assertEqual(clash['status'], 'invalid'); self.assertIsNone(clash['value'])
        self.assertEqual(clash['reason'], 'final output contract violation: ' + ISSUE_ID_COLLISION)

    def test_unlisted_text_recorded_without_progress_effect(self):
        from test_role_progress import obs
        previous = obs(1); current = obs(2)
        result = calculate_progress([previous], current, version='progress-v2')
        current['issue_report'] = self.contract.report(VALUE)
        self.assertEqual(calculate_progress([previous], current, version='progress-v2'), result)
        current['issue_report']['unlisted_issues'] = ['Completely different novel issue']
        self.assertEqual(calculate_progress([previous], current, version='progress-v2'), result)
        validated = Observation.model_validate(current).model_dump()
        self.assertEqual(validated['issue_report'], current['issue_report'])


class IssueRunnerTests(unittest.IsolatedAsyncioTestCase):
    run_offline = recovery.RunnerIntegrationTests.run_offline
    collection_policy = INDEPENDENT
    criteria_version = 'deadlock-v0.2'
    output_contract = V2

    def scenario_transform(self, scenario):
        data = scenario.model_dump(); data.update(copy.deepcopy(VOCAB))
        return Scenario.model_validate(data)

    async def test_all_roles_receive_definitions_and_only_local_enum_validation(self):
        r = await self.run_offline(lambda request:v2_response(), max_steps=3)
        c = for_scenario(V2, fixture_scenario())
        self.assertEqual(r['conditions']['runner_protocol'], PROTOCOL_V2)
        self.assertEqual(r['conditions']['output_contract_version'], V2)
        self.assertEqual(r['conditions']['allowed_issues_sha256'], c.sha256)
        self.assertEqual(r['conditions']['strict_support'], 'unverified')
        for step in r['steps']:
            self.assertEqual(step['step_status'], 'completed')
            self.assertEqual(step['observation']['issue_report'], c.report(VALUE))
            self.assertEqual(step['observation']['progress']['version'], 'progress-v2')
        for req in r['upstream_requests']:
            prompt = json.dumps(req['messages'])
            for issue in VOCAB['allowed_issues']:
                self.assertIn(issue['definition'], prompt); self.assertIn(issue['id'], prompt)
            self.assertNotIn('agent_id', prompt)
            if 'response_format' in req:
                self.assertNotIn('enum', json.dumps(req['response_format']))

    async def test_invalid_id_discards_whole_conversation_preserves_artifact_and_failure(self):
        invalid = {**VALUE,'open_issue_ids':['fixture-core','outside']}
        r = await self.run_offline([recovery.success(),v2_response(invalid),recovery.success(),v2_response()])
        s = r['steps'][0]; o = s['observation']
        self.assertEqual(s['step_status'],'failed')
        self.assertIn('strict_schema_mismatch',s['failure_reasons'])
        self.assertIsNone(s['observed_final_report'])
        self.assertIsNone(o['conversation']['open_issue_ids'])
        self.assertIsNone(o['issue_report']['unlisted_issues'])
        self.assertIsNotNone(o['artifact'])
        self.assertEqual(r['steps'][1]['step_status'],'completed')

    async def test_recovered_final_keeps_unlisted_evidence_but_still_failed(self):
        r = await self.run_offline([recovery.unknown400(),recovery.success(),v2_response(),
                                   recovery.success(),v2_response()])
        s = r['steps'][0]
        self.assertEqual(s['step_status'],'failed')
        self.assertEqual(s['failure_reasons'],['unknown_tool'])
        self.assertEqual(s['observation']['issue_report']['unlisted_issues'],VALUE['unlisted_issues'])
        self.assertIsNotNone(s['observation']['artifact'])
        incoming = json.loads(r['upstream_requests'][3]['messages'][-1]['content'])
        self.assertEqual(incoming['recent_messages'][0]['narrative'],'[구조화 출력 없음]')

    async def test_collision_fails_step_with_distinct_reason_and_keeps_artifact(self):
        clash = {**VALUE,'unlisted_issues':['fixture-edge']}
        r = await self.run_offline([recovery.success(),v2_response(clash),recovery.success(),v2_response()])
        s = r['steps'][0]; o = s['observation']
        self.assertEqual(s['step_status'],'failed')
        self.assertEqual(s['strict_failure'], ISSUE_ID_COLLISION)
        self.assertIn(ISSUE_ID_COLLISION, s['failure_reasons'])
        self.assertNotIn('strict_schema_mismatch', s['failure_reasons'])
        self.assertIsNone(s['observed_final_report'])
        self.assertEqual(s['collection']['final_output_reason'], 'final output contract violation: ' + ISSUE_ID_COLLISION)
        self.assertIsNone(o['conversation']['open_issue_ids'])
        self.assertIsNone(o['issue_report']['unlisted_issues'])
        self.assertIsNotNone(o['artifact'])
        self.assertEqual(r['steps'][1]['step_status'],'completed')

    async def test_each_role_applies_same_validation(self):
        # Alternate so the two-consecutive strict-failure stop never triggers.
        invalid = {**VALUE,'open_issue_ids':['outside']}
        pattern = [invalid, VALUE, invalid, VALUE, invalid]
        r = await self.run_offline([x for v in pattern for x in (recovery.success(), v2_response(v))], max_steps=5)
        failed = {s['agent'] for s in r['steps'] if s['step_status'] == 'failed'}
        self.assertEqual(failed, {'planner','developer','reviewer'})
        for s, v in zip(r['steps'], pattern):
            self.assertEqual(s['step_status'], 'failed' if v is invalid else 'completed')
            self.assertEqual(s['observed_final_report'] is None, v is invalid)

    async def test_v2_with_legacy_collection_policy_refused_before_run(self):
        self.collection_policy = 'legacy-failed-step-v1'
        with self.assertRaises(ValueError):
            await self.run_offline(lambda request:v2_response())
