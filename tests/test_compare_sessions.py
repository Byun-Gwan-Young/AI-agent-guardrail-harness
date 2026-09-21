"""C-11: the A-1-v3 analysis, manifest and the G0-8 comparison are reproducible from committed session files."""
import json
from pathlib import Path
import unittest

from tools import analyze_session as tool
from tools import compare_sessions as compare

ROOT = Path(__file__).resolve().parents[1]
G0_8 = 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e'
V3 = 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73'
REPORTS = ROOT / 'reports/a-1-v3'
CREDITS = (4241.70359, 4258.13384)


def saved(name):
    return json.loads((REPORTS / name).read_text(encoding='utf-8'))


def as_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


class A1V3SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = as_json(tool.analyse(V3))

    def test_analysis_and_manifest_are_reproducible(self):
        # secret_scan depends on which key variables are set in the test process; checked separately.
        without_scan = lambda a: {k: v for k, v in a.items() if k != 'secret_scan'}
        self.assertEqual(without_scan(self.analysis), without_scan(saved(f'{V3}-analysis.json')))
        manifest = saved(f'{V3}-manifest.json')
        operator_notes = [n for n in manifest['notes'] if not n.startswith('git_commit is null')]
        self.assertEqual(manifest, as_json(tool.manifest(self.analysis, 'verify', operator_notes)))
        self.assertEqual(manifest['manifest_version'], 'session-manifest-v0.2')
        self.assertEqual(manifest['condition']['reasoning_effort']['applied'], 'unverified')
        self.assertEqual(manifest['validity']['class'], 'unclassified')
        self.assertTrue(self.analysis['secret_scan']['clean'])

    def test_comparison_is_reproducible(self):
        report = saved('comparison-g0-8.json')
        self.assertEqual(as_json(compare.column(G0_8, None)), report['baseline'])
        self.assertEqual(as_json(compare.column(V3, CREDITS)), report['candidate'])
        self.assertEqual(set(report['changed_conditions']),
                         {'provider', 'model', 'runner_protocol', 'max_tokens', 'scenario_id'})


class RereadTests(unittest.TestCase):
    def call(self, call_id, path):
        return {'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path})}}]}

    def test_reread_found_only_when_result_is_already_in_the_request(self):
        first = {'request_body': {'messages': [{'role': 'user', 'content': 'task'}]},
                 'response_body': {'choices': [{'message': self.call('a', 'SPEC.md')}]}}
        second = {'request_body': {'messages': [self.call('a', 'SPEC.md'),
                                                {'role': 'tool', 'tool_call_id': 'a', 'content': 'x'}]},
                  'response_body': {'choices': [{'message': self.call('b', 'SPEC.md')}]}}
        records = {'observed_records': [{'content': [{'call_id': 'b', 'content': 'x'}]}]}
        final = {'request_body': {'messages': [{'role': 'user', 'content': json.dumps(records)}]},
                 'response_body': {'choices': [{'message': {'content': '{}'}}]}}
        rows = compare.rereads([{'step_id': 1, 'agent': 'planner', 'llm_turns': [1, 2, 3]}],
                               {1: first, 2: second, 3: final})
        self.assertEqual(rows, [{'step_id': 1, 'agent': 'planner', 'turn': 2, 'path': 'SPEC.md', 'identical': True}])


if __name__ == '__main__':
    unittest.main()
