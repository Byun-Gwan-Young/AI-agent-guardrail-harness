"""Machine acceptance gate; does not call agents or infer deadlock from expected_outcome."""
from suite_identity import compute_test_suite_id


def check_acceptance(scenario, workspace, summary):
    suite = scenario.success_criteria.test_suite
    if suite is None:
        raise ValueError("This checker is for test-based scenarios")
    actual = compute_test_suite_id(workspace, suite.test_roots, suite.contract_files, suite.command)
    unchanged = actual == suite.test_suite_id
    passed = (summary["tests"] == suite.expected_test_count and summary["passed"] == suite.expected_test_count
              and summary["failed"] == 0 and summary["errors"] == 0 and summary["skipped"] == 0)
    return {"machine_success": passed and unchanged, "test_suite_unchanged": unchanged,
            "test_suite_id": actual, "pinned_test_suite_id": suite.test_suite_id,
            "reason": "test_suite_changed" if not unchanged else "all_passed" if passed else "tests_not_passed"}
