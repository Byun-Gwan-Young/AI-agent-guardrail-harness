import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_hook import capture_artifact, make_observation
from conversation_extract import compare_extraction, extract_conversation


class CollectorTests(unittest.TestCase):
    def test_same_filename_with_new_content_has_new_hash_and_revert_restores_hash(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "module.py"
            path.write_text("first", encoding="utf-8")
            a = capture_artifact(root, ["module.py"])
            path.write_text("second", encoding="utf-8")
            b = capture_artifact(root, ["module.py"])
            path.write_text("first", encoding="utf-8")
            c = capture_artifact(root, ["module.py"])
            self.assertEqual(a["files_scope_id"], b["files_scope_id"])
            self.assertNotEqual(a["file_hashes"], b["file_hashes"])
            self.assertEqual(a["file_hashes"], c["file_hashes"])

    def test_junit_counts_fail_error_skip_and_preserves_suite_identity(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "result.xml").write_text(
                '<testsuite><testcase/><testcase><failure/></testcase>'
                '<testcase><error/></testcase><testcase><skipped/></testcase></testsuite>', encoding="utf-8")
            result = capture_artifact(root, ["module.py"], junit_path="result.xml", test_suite_id="fixed-v1")
            self.assertEqual(result["test_pass_count"], 1)
            self.assertEqual(result["test_total_count"], 4)
            self.assertEqual(result["test_suite_id"], "fixed-v1")
            self.assertEqual(result["file_hashes"], {})

    def test_bad_test_report_and_file_read_failure_are_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "module.py"
            path.write_text("x", encoding="utf-8")
            with patch.object(Path, "read_bytes", side_effect=PermissionError("test")):
                result = capture_artifact(root, ["module.py"], junit_path="missing.xml", test_suite_id="fixed-v1")
            self.assertIsNone(result["file_hashes"])
            self.assertIsNone(result["test_pass_count"])
            self.assertIn("file_hashes", result["reasons"])

    def test_capture_rejects_paths_outside_explicit_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                capture_artifact(root, ["../private.txt"])

    def test_rule_extraction_evidence_and_unknown_text(self):
        result = extract_conversation("timeout: 500 ms. RAM: 32 GB. issue-1 open\n새 정보: 빈 입력 거부")
        self.assertEqual(result["source_kind"], "extracted")
        self.assertEqual(result["proposal_values"], {"timeout_ms": 500, "ram_gb": 32})
        self.assertEqual(result["open_issue_ids"], ["issue-1"])
        self.assertTrue(result["evidence"])
        unknown = extract_conversation("좋습니다. 더 검토하겠습니다.")
        self.assertIsNone(unknown["proposal_values"])
        self.assertIsNone(unknown["open_issue_ids"])
        self.assertIsNone(unknown["info_items"])

    def test_ambiguous_proposals_are_not_invented(self):
        result = extract_conversation("timeout: 500 ms or timeout: 800 ms")
        self.assertIsNone(result["proposal_values"])
        self.assertIn("ambiguous", result["reasons"]["timeout_ms"])

    def test_issue_parser_retains_other_known_issues_when_one_closes(self):
        prior = extract_conversation("issue-1 open; issue-2 open")
        now = extract_conversation("issue-1 resolved", prior)
        self.assertEqual(now["open_issue_ids"], ["issue-2"])

    def test_structured_reference_never_enters_extractor_input(self):
        payload = make_observation(step_id=1, llm_turns=[1], text="timeout: 500 ms",
            progress_source="conversation", progress_metric={"conversation": ["proposal_value_delta"]},
            structured={"proposal_values": {"timeout_ms": 999}})
        self.assertEqual(payload["conversation"]["proposal_values"]["timeout_ms"], 999)
        self.assertEqual(payload["extracted_conversation"]["proposal_values"]["timeout_ms"], 500)
        result = compare_extraction(payload["conversation"], payload["extracted_conversation"])
        self.assertFalse(result["proposal_values"]["match"])
        self.assertEqual(result["open_issue_ids"]["status"], "unmeasured")
