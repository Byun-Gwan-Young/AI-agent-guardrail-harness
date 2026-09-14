import copy
import hashlib
import unittest

from progress_schema import Observation
from progress_signal import calculate_progress


def snapshot(step, *, proposal=500, issues=None, info=None, file="a", passed=1, suite="fixed-v1",
             source="both", conversation_metrics=None, artifact_metrics=None):
    return Observation.model_validate({
        "step_id": step, "llm_turns": [step], "progress_source": source,
        "progress_metric": {"conversation": conversation_metrics if conversation_metrics is not None else
                            ["proposal_value_delta", "open_issues_count", "new_info_ratio"],
                            "artifact": artifact_metrics if artifact_metrics is not None else
                            ["files_changed", "test_pass_count", "build_status"]},
        "conversation": {"source_kind": "structured", "proposal_values": {"timeout_ms": proposal},
                         "open_issue_ids": issues or [], "info_items": info or []},
        "artifact": {"file_hashes": {"code.py": hashlib.sha256(file.encode()).hexdigest()},
                     "files_scope_id": "workspace-v1", "test_pass_count": passed,
                     "test_total_count": 3, "test_suite_id": suite, "build_status": "passed"},
    }).model_dump()


class ProgressTests(unittest.TestCase):
    def test_quiet_conversation_but_file_edit_is_progress(self):
        result = calculate_progress([snapshot(1)], snapshot(2, file="b"))
        self.assertEqual(result["state"], "progress")
        self.assertFalse(result["conversation_moved"])
        self.assertTrue(result["artifact_moved"])
        self.assertTrue(result["flags"]["test_plateau"])

    def test_unchanged_files_but_issue_resolution_is_progress(self):
        result = calculate_progress([snapshot(1, issues=["issue-1"])], snapshot(2))
        self.assertEqual(result["state"], "progress")
        self.assertTrue(result["conversation_moved"])
        self.assertFalse(result["artifact_moved"])

    def test_proposal_500_800_500_is_oscillating_not_progress(self):
        result = calculate_progress([snapshot(1), snapshot(2, proposal=800)], snapshot(3))
        self.assertEqual(result["state"], "oscillating")
        self.assertEqual(result["flags"]["oscillation"], ["timeout_ms"])

    def test_closed_issue_reopened_is_oscillating_not_progress(self):
        result = calculate_progress([snapshot(1, issues=["issue-1"]), snapshot(2)],
                                    snapshot(3, issues=["issue-1"]))
        self.assertEqual(result["state"], "oscillating")
        self.assertEqual(result["flags"]["reopen"], ["issue-1"])

    def test_old_file_hash_restored_is_oscillating_not_progress(self):
        result = calculate_progress([snapshot(1), snapshot(2, file="b")], snapshot(3))
        self.assertEqual(result["state"], "oscillating")
        self.assertEqual(result["flags"]["revert"], ["code.py"])

    def test_new_information_with_oscillation_is_progress_and_keeps_flag(self):
        result = calculate_progress([snapshot(1), snapshot(2, proposal=800)],
                                    snapshot(3, info=["empty input must fail"]))
        self.assertEqual(result["state"], "progress")
        self.assertTrue(result["flags"]["oscillation"])

    def test_missing_artifact_never_becomes_stagnant(self):
        current = snapshot(2)
        current["artifact"] = None
        self.assertEqual(calculate_progress([snapshot(1)], current)["state"], "unmeasured")

    def test_all_observed_and_unchanged_is_stagnant(self):
        self.assertEqual(calculate_progress([snapshot(1)], snapshot(2))["state"], "stagnant")

    def test_changed_test_suite_cannot_establish_stagnation(self):
        current = snapshot(2, passed=3, suite="different-tests")
        result = calculate_progress([snapshot(1)], current)
        self.assertEqual(result["state"], "unmeasured")
        self.assertEqual(result["metrics"]["artifact.test_pass_count"]["status"], "unmeasured")

    def test_test_improvement_is_progress(self):
        self.assertEqual(calculate_progress([snapshot(1)], snapshot(2, passed=2))["state"], "progress")

    def test_first_is_baseline_and_inputs_are_not_modified(self):
        current = snapshot(1)
        original = copy.deepcopy(current)
        self.assertEqual(calculate_progress([], current)["state"], "baseline")
        self.assertEqual(current, original)

    def test_metric_source_selection_excludes_other_source(self):
        a, b = snapshot(1, source="conversation"), snapshot(2, source="conversation", file="b")
        self.assertEqual(calculate_progress([a], b)["state"], "stagnant")

    def test_recurring_known_change_with_unknown_source_is_unmeasured(self):
        current = snapshot(3)
        current["artifact"] = None
        result = calculate_progress([snapshot(1), snapshot(2, proposal=800)], current)
        self.assertEqual(result["state"], "unmeasured")
        self.assertEqual(result["flags"]["oscillation"], ["timeout_ms"])

    def test_issue_replacement_same_count_still_moves(self):
        result = calculate_progress([snapshot(1, issues=["issue-a"])], snapshot(2, issues=["issue-b"]))
        self.assertEqual(result["state"], "progress")
        self.assertEqual(result["metrics"]["conversation.open_issues_count"]["value"]["delta"], 0)

    def test_file_create_delete_cycle_returns_to_absence(self):
        initial = snapshot(1)
        initial["artifact"]["file_hashes"] = {}
        current = snapshot(3)
        current["artifact"]["file_hashes"] = {}
        result = calculate_progress([initial, snapshot(2)], current)
        self.assertEqual(result["state"], "oscillating")

    def test_structured_and_extracted_histories_are_not_mixed(self):
        current = snapshot(2)
        current["conversation"]["source_kind"] = "extracted"
        self.assertEqual(calculate_progress([snapshot(1)], current)["state"], "unmeasured")

    def test_unselected_source_does_not_supply_missing_baseline(self):
        current = snapshot(1, source="artifact")
        current["artifact"] = None
        self.assertEqual(calculate_progress([], current)["state"], "unmeasured")
