import copy
import unittest

from deadlock_policy import evaluate_criteria, pin_criteria
from progress_signal import calculate_progress
from test_progress_signal import snapshot


def sequence(inputs, declared=None, context_known=True):
    observations = []
    for observation in inputs:
        observation = copy.deepcopy(observation)
        step = observation["step_id"]
        context = {"declaration": "none", "source_kind": "scenario_rule", "evidence": "test fixture"}
        if declared is not None and step >= declared:
            context.update(declaration="declared", declared_step=declared)
        if not context_known:
            context["declaration"] = "unknown"
        observation["termination_context"] = context
        observation["progress"] = calculate_progress(observations, observation)
        observations.append(observation)
    return observations


class CriteriaTests(unittest.TestCase):
    def test_three_stagnant_steps_detect_on_fourth_including_baseline(self):
        rows = sequence([snapshot(i) for i in range(1, 5)])
        self.assertEqual(evaluate_criteria(rows[:3], pin_criteria())["decision"], "continue")
        result = evaluate_criteria(rows, pin_criteria())
        self.assertEqual(result["decision"], "deadlock")
        self.assertEqual(result["first_deadlock_step"], 4)

    def test_oscillations_count_but_keep_original_states(self):
        rows = sequence([snapshot(i, proposal=value) for i, value in enumerate([500, 800, 500, 800, 500], 1)])
        result = evaluate_criteria(rows, pin_criteria())
        self.assertEqual(result["first_deadlock_step"], 5)
        self.assertEqual(result["consecutive_states"], ["oscillating"] * 3)

    def test_legitimate_reverification_with_issue_closure_is_not_deadlock(self):
        rows = sequence([snapshot(1, issues=["a", "b"]), snapshot(2, issues=["a", "b"]),
                         snapshot(3, issues=["a"]), snapshot(4, issues=["a"]), snapshot(5)])
        result = evaluate_criteria(rows, pin_criteria())
        self.assertIsNone(result["first_deadlock_step"])
        self.assertEqual(rows[2]["progress"]["state"], "progress")

    def test_quiet_file_work_and_test_plateau_is_not_deadlock(self):
        rows = sequence([snapshot(i, file=str(i)) for i in range(1, 8)])
        result = evaluate_criteria(rows, pin_criteria())
        self.assertIsNone(result["first_deadlock_step"])
        self.assertTrue(rows[-1]["progress"]["flags"]["test_plateau"])

    def test_two_confirmation_steps_after_agreement_are_allowed(self):
        rows = sequence([snapshot(i) for i in range(1, 4)], declared=1)
        result = evaluate_criteria(rows, pin_criteria())
        self.assertEqual(result["decision"], "continue")
        self.assertIsNone(result["first_deadlock_step"])
        self.assertIsNone(result["first_termination_failure_step"])

    def test_third_nonprogress_after_declaration_is_termination_failure(self):
        rows = sequence([snapshot(i) for i in range(1, 5)], declared=1)
        result = evaluate_criteria(rows, pin_criteria())
        self.assertEqual(result["decision"], "termination_failure")
        self.assertEqual(result["first_termination_failure_step"], 4)
        self.assertIsNone(result["first_deadlock_step"])

    def test_missing_resets_streak_and_never_times_out_as_deadlock(self):
        inputs = [snapshot(i) for i in range(1, 10)]
        for row in inputs[3:]:
            row["artifact"] = None
        result = evaluate_criteria(sequence(inputs), pin_criteria())
        self.assertEqual(result["decision"], "unmeasured")
        self.assertTrue(result["needs_observation_review"])
        self.assertIsNone(result["first_deadlock_step"])
        self.assertEqual(result["consecutive_steps"], 0)

    def test_unknown_declaration_is_not_assumed_absent(self):
        result = evaluate_criteria(sequence([snapshot(i) for i in range(1, 8)], context_known=False), pin_criteria())
        self.assertEqual(result["decision"], "unmeasured")
        self.assertIsNone(result["first_deadlock_step"])

    def test_missing_gap_cannot_bridge_two_stagnant_runs(self):
        rows = sequence([snapshot(i) for i in range(1, 8)])
        rows[3]["progress"]["state"] = "unmeasured"
        self.assertEqual(evaluate_criteria(rows[:6], pin_criteria())["decision"], "continue")
        self.assertEqual(evaluate_criteria(rows, pin_criteria())["first_deadlock_step"], 7)

    def test_criteria_hash_mismatch_and_unversioned_data_are_withheld(self):
        rows = sequence([snapshot(i) for i in range(1, 5)])
        pin = pin_criteria()
        pin["criteria_parameters"]["consecutive_steps"] = 2
        self.assertEqual(evaluate_criteria(rows, pin)["decision"], "unmeasured")
        self.assertEqual(evaluate_criteria(rows, {})["decision"], "unmeasured")

    def test_regressed_event_is_not_independent_deadlock_signal(self):
        rows = sequence([snapshot(1, passed=3), snapshot(2, passed=2), snapshot(3, passed=1), snapshot(4, passed=0)])
        result = evaluate_criteria(rows, pin_criteria())
        self.assertIsNone(result["first_deadlock_step"])
        self.assertTrue(any(e["kind"] == "regressed" for e in rows[-1]["progress"]["events"]))
