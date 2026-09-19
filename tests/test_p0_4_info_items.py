"""P0-4 option C (D-22): info_items is recorded but never judged for A-1-v2."""
import copy
import json
from pathlib import Path
import unittest

from scenario_schema import load_scenario
from progress_signal import calculate_progress
from deadlock_policy import evaluate_criteria, pin_criteria
from experiments.observation_collection import collection_metadata
from progress_schema import Observation
from tools import p0_4_info_items_options as analysis

ROOT = Path(__file__).resolve().parents[1]
A1 = load_scenario(ROOT / 'scenarios/A-1-ambiguous-task-query.yaml')
A1V2 = load_scenario(ROOT / 'scenarios/A-1-v2-ambiguous-task-query.yaml')
METRIC = A1V2.progress_metric.model_dump()
DECLARATION = {'declaration': 'none', 'source_kind': 'scenario_rule',
               'evidence': 'valid structured output; no reviewer declaration'}


def observation(step, agent, info, issues=('requirements',)):
    artifact = {'file_hashes': {'src/task_query.py': 'a' * 64}, 'files_scope_id': 'b' * 64,
                'test_pass_count': 7, 'test_total_count': 16, 'test_suite_id': 'sha256:' + 'c' * 64,
                'build_status': None, 'reasons': {'build_status': 'build not observed'}}
    return Observation.model_validate({
        'step_id': step, 'agent_id': agent, 'llm_turns': [step], 'progress_source': A1V2.progress_source,
        'progress_metric': METRIC, 'artifact': artifact, 'termination_context': DECLARATION,
        'conversation': {'source_kind': 'structured', 'open_issue_ids': list(issues), 'info_items': info}}
    ).model_dump()


def judged(info_by_step):
    history, results = [], []
    for step, info in enumerate(info_by_step, 1):
        current = observation(step, ('planner', 'developer', 'reviewer')[(step - 1) % 3], info)
        current['progress'] = calculate_progress(history, current, version='progress-v2')
        history.append(current)
        results.append((current['progress'], evaluate_criteria(history, pin_criteria('deadlock-v0.2'))))
    return results


class OptionCSelectionTests(unittest.TestCase):
    def test_a1v2_selects_open_issues_only_and_a1_is_unchanged(self):
        self.assertEqual(METRIC['conversation'], ['open_issues_count'])
        self.assertEqual(METRIC['artifact'], ['test_pass_count', 'files_changed'])
        self.assertEqual(A1.progress_metric.conversation, ['open_issues_count', 'new_info_ratio'])

    def test_recorded_info_items_never_change_progress_or_criteria(self):
        # null, empty, repeated and always-novel reports must all be judged identically.
        variants = [[None] * 9, [[]] * 9, [['same fact']] * 9,
                    [['novel fact %d' % i] for i in range(9)], [None, [], ['x'], None, ['y'], [], None, ['z'], []]]
        results = [judged(v) for v in variants]
        for other in results[1:]:
            self.assertEqual(other, results[0])
        states = [p['state'] for p, _ in results[0]]
        self.assertEqual(states[:3], ['baseline'] * 3)
        self.assertEqual(set(states[3:]), {'stagnant'})
        self.assertTrue(all('conversation.new_info_ratio' not in p['metrics'] for p, _ in results[0]))
        self.assertEqual(results[0][-1][1]['decision'], 'deadlock')

    def test_info_items_still_recorded_and_coverage_ignores_it(self):
        current = observation(1, 'developer', None)
        self.assertIsNone(current['conversation']['info_items'])
        self.assertEqual(observation(1, 'developer', ['kept'])['conversation']['info_items'], ['kept'])
        metadata = collection_metadata('independent-sources-v1', {'status': 'valid', 'reason': None, 'source_turn': 1},
            {'open_issue_ids': ['requirements'], 'info_items': None}, current['artifact'],
            A1V2.progress_source, METRIC)
        self.assertNotIn('conversation.new_info_ratio', metadata['metric_status'])
        self.assertEqual(metadata['measurement_status'], 'observed')


class RolePromptTests(unittest.TestCase):
    def test_unknown_means_null_without_reason_for_all_three_roles(self):
        for agent in A1V2.agents:
            with self.subTest(agent=agent.id):
                self.assertNotIn('null과 이유', agent.system_message)
                self.assertIn('null', agent.system_message)
                self.assertIn('없으면 빈 목록', agent.system_message)

    def test_only_the_prescribed_prompt_edits_differ_from_a1(self):
        edits = {'planner': [('상태를 모르면 null과 이유를 제공한다.', '상태를 모르면 null을 제공한다.')],
                 'developer': [('모르는 값은 null과 이유를 기록한다.', '모르는 값은 null로 기록한다.')],
                 'reviewer': [('completion_declared를 제공한다.\n',
                               'completion_declared를 제공한다.\n'
                               'info_items는 이번 작업의 새 사실이며 없으면 빈 목록이다. 모르는 값은 null로 기록한다.\n')]}
        old = {a.id: a for a in A1.agents}
        for agent in A1V2.agents:
            text = old[agent.id].system_message
            for before, after in edits[agent.id]:
                self.assertEqual(text.count(before), 1, (agent.id, before))
                text = text.replace(before, after)
            self.assertEqual(agent.system_message, text, agent.id)
            self.assertEqual(agent.model_dump(exclude={'system_message'}),
                             old[agent.id].model_dump(exclude={'system_message'}))


class AnalysisToolTests(unittest.TestCase):
    def test_saved_report_is_reproducible_and_current_matches_p0_2(self):
        report = analysis.analyse(json.loads((ROOT / analysis.LOG).read_text(encoding='utf-8')),
                                  json.loads((ROOT / analysis.REPLAY).read_text(encoding='utf-8')))
        saved = json.loads((ROOT / 'reports/p0-4/info-items-options.json').read_text(encoding='utf-8'))
        self.assertEqual(report, saved)
        self.assertTrue(report['current_matches_saved_p0_2_states'])
        option_c = next(o for o in report['options'] if o['option'] == 'C_drop_new_info_ratio_metric')
        self.assertEqual(option_c['contract_violation_steps'], [])
        self.assertEqual(option_c['unmeasured_where_only_info_missing'], [])

    def test_analysis_does_not_mutate_inputs(self):
        log = json.loads((ROOT / analysis.LOG).read_text(encoding='utf-8'))
        replay = json.loads((ROOT / analysis.REPLAY).read_text(encoding='utf-8'))
        before = copy.deepcopy((log, replay))
        analysis.analyse(log, replay)
        self.assertEqual((log, replay), before)
