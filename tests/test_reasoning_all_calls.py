"""D-29: runner protocol v9 sends the scenario's reasoning_effort on every model call; A-1-v4."""
import json
import unittest

from pydantic import ValidationError

from experiments.step_execution import PROTOCOL_V8, PROTOCOL_V9
from scenario_schema import load_scenario
from test_harness_facts import A1V3, ROOT, Runner

A1V4 = ROOT / 'scenarios/A-1-v4-ambiguous-task-query.yaml'


def without_reasoning(path):
    """The same scenario with the v9-only fields removed, so it can run under v8."""
    loaded = load_scenario(path)
    data = loaded.model_dump()
    data.update(reasoning_effort=None, reasoning_effort_evidence=None)
    return type(loaded).model_validate(data)


class V9SnapshotTests(Runner):
    scenario_path = A1V4

    async def test_v9_differs_from_v8_only_by_reasoning_effort_on_every_call(self):
        v9 = await self.run_protocol(PROTOCOL_V9)
        self.scenario_transform = lambda scenario: without_reasoning(A1V4)
        v8 = await self.run_protocol(PROTOCOL_V8)
        scenario = load_scenario(A1V4)
        self.assertEqual(len(v8['upstream_requests']), len(v9['upstream_requests']))
        finals = 0
        for old, new in zip(v8['upstream_requests'], v9['upstream_requests']):
            self.assertEqual(new['reasoning_effort'], scenario.reasoning_effort)
            finals += 'response_format' in new
            # v8 sends its fixed low value on the tool-free final call only.
            self.assertEqual(old.get('reasoning_effort'), 'low' if 'response_format' in old else None)
            strip = lambda body: {k: v for k, v in body.items() if k != 'reasoning_effort'}
            self.assertEqual(strip(old), strip(new))
            self.assertEqual(new['max_tokens'], 16384)
        self.assertTrue(finals and finals < len(v9['upstream_requests']))
        self.assertEqual(v9['conditions']['runner_protocol'], PROTOCOL_V9)
        self.assertEqual(v9['conditions']['reasoning_effort'],
                         {'requested': 'high', 'sent_on': 'all_calls', 'applied': 'probe_indicated',
                          'evidence': scenario.reasoning_effort_evidence})
        self.assertEqual(v9['conditions']['final_reasoning_effort'], 'high')
        self.assertIn('harness_facts_policy', v9['conditions'])
        self.assertEqual(v8['conditions']['reasoning_effort']['sent_on'], 'final tool-free call of each step only')
        self.assertEqual([s['observation']['progress']['state'] for s in v8['steps']],
                         [s['observation']['progress']['state'] for s in v9['steps']])

    async def test_value_comes_from_the_scenario(self):
        def medium(scenario):
            loaded = load_scenario(A1V4)
            return type(loaded).model_validate({**loaded.model_dump(), 'reasoning_effort': 'medium'})
        self.scenario_transform = medium
        run = await self.run_protocol(PROTOCOL_V9, steps=1)
        self.assertEqual({r['reasoning_effort'] for r in run['upstream_requests']}, {'medium'})

    async def test_without_evidence_applied_stays_unverified(self):
        def no_evidence(scenario):
            loaded = load_scenario(A1V4)
            return type(loaded).model_validate({**loaded.model_dump(), 'reasoning_effort_evidence': None})
        self.scenario_transform = no_evidence
        run = await self.run_protocol(PROTOCOL_V9, steps=1)
        self.assertEqual(run['conditions']['reasoning_effort']['applied'], 'unverified')


class V9SelectionTests(Runner):
    async def test_protocol_and_scenario_setting_must_match(self):
        # v9 with a scenario that sets no reasoning_effort.
        self.scenario_path = A1V3
        with self.assertRaisesRegex(ValueError, 'requires scenario reasoning_effort'):
            await self.run_protocol(PROTOCOL_V9, steps=1)
        # A-1-v4 under v8 would silently drop its reasoning_effort.
        self.scenario_path = A1V4
        with self.assertRaisesRegex(ValueError, 'requires scenario reasoning_effort'):
            await self.run_protocol(PROTOCOL_V8, steps=1)

    async def test_missing_evidence_file_is_rejected(self):
        def missing(scenario):
            loaded = load_scenario(A1V4)
            return type(loaded).model_validate({**loaded.model_dump(),
                                                'reasoning_effort_evidence': 'runs/gateway-probes/none.json'})
        self.scenario_transform = missing
        with self.assertRaisesRegex(ValueError, 'evidence file not found'):
            await self.run_protocol(PROTOCOL_V9, steps=1)


class A1V4ScenarioTests(unittest.TestCase):
    def test_only_the_d29_d31_fields_differ_from_a1v3(self):
        old, new = load_scenario(A1V3).model_dump(), load_scenario(A1V4).model_dump()
        self.assertEqual((new.pop('scenario_id'), old.pop('scenario_id')), ('A-1-v4', 'A-1-v3'))
        self.assertEqual((new.pop('max_tokens'), old.pop('max_tokens')), (16384, 2400))
        self.assertEqual((new.pop('reasoning_effort'), old.pop('reasoning_effort')), ('high', None))
        evidence = new.pop('reasoning_effort_evidence')
        self.assertIsNone(old.pop('reasoning_effort_evidence'))
        self.assertTrue((ROOT / evidence).is_file())
        comparison = json.loads((ROOT / evidence).read_text(encoding='utf-8'))['reasoning_comparison']
        self.assertGreater(comparison['high_minus_low_with_tools'], 0)
        self.assertEqual((new['termination'].pop('max_steps'), old['termination'].pop('max_steps')), (30, 18))
        self.assertEqual(new, old)

    def test_preflight_record_is_reproducible(self):
        from tools.scenario_preflight import preflight
        saved = json.loads((ROOT / 'reports/a-1-v4/preflight.json').read_text(encoding='utf-8'))
        self.assertEqual(preflight(A1V4), saved)
        v3 = json.loads((ROOT / 'reports/a-1-v3/preflight-kmu.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['acceptance'], v3['acceptance'])
        self.assertEqual(saved['allowed_issues_sha256'], v3['allowed_issues_sha256'])

    def test_evidence_requires_a_value(self):
        data = load_scenario(A1V4).model_dump()
        data['reasoning_effort'] = None
        with self.assertRaises(ValidationError):
            type(load_scenario(A1V4)).model_validate(data)


if __name__ == '__main__':
    unittest.main()
