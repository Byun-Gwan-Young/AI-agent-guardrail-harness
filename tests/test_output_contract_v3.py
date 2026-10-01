"""C-17-3 part 1: output-contract-v3 (T1 final-report fields). output-contract-v1/v2 stay byte-identical."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

from experiments.dialogue_contract import (HANDOFF_NOT_ALLOWED, STATUS_NOT_ALLOWED, T1_FIELDS, V3,
                                           VOCABULARY_VIOLATIONS_V3, DialogueContract, for_dialogue_scenario)
from experiments.issue_contract import (ISSUE_ID_COLLISION, OPEN_ISSUE_ID_NOT_ALLOWED, V2, IssueContract,
                                        IssueContractViolation)
from progress_schema import IssueReport
from scenario_schema import load_scenario
from test_harness_facts import ADVICE

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE = ROOT / "tests/fixtures/scenario-v2-dialogue.yaml"


def report(**changes):
    value = {"narrative": "n", "open_issue_ids": ["ownership"], "info_items": None, "completion_declared": False,
             "unlisted_issues": [], "status": "triage", "handoff_to": "refund", "adopted_items": ["order:A1"],
             "deliverable": None, "spec_approved": None}
    return json.dumps({**value, **changes}, ensure_ascii=False)


class ContractV3Tests(unittest.TestCase):
    def setUp(self):
        self.contract = for_dialogue_scenario(load_scenario(DIALOGUE))
        self.v2 = IssueContract(V2, self.contract.allowed)

    def test_v1_v2_contract_files_are_byte_identical(self):
        expected = json.loads((ROOT / "tests/fixtures/c17-3-protected-files.json").read_text(encoding="utf-8"))
        for path, digest in expected.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def test_schema_is_v2_plus_the_t1_fields_all_required(self):
        v2_schema = self.v2.schema()
        schema = self.contract.schema()
        self.assertEqual({k: schema["properties"][k] for k in v2_schema["properties"]}, v2_schema["properties"])
        self.assertEqual(schema["required"], v2_schema["required"] + list(T1_FIELDS))
        self.assertEqual(set(schema["properties"]), set(schema["required"]))
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["status"],
                         {"type": "string", "enum": ["received", "triage", "assigned", "resolved", "escalated"]})
        self.assertEqual(schema["properties"]["handoff_to"]["anyOf"][0]["enum"], ["intake", "refund", "shipping"])
        self.assertEqual(schema["properties"]["deliverable"]["anyOf"], [self.contract.deliverable_schema, {"type": "null"}])
        self.assertEqual(self.contract.response_format()["json_schema"]["name"], "state_report_v3")
        self.assertTrue(self.contract.response_format()["json_schema"]["strict"])
        # Building v3 never changes the v2 schema.
        self.assertEqual(self.v2.schema(), v2_schema)
        self.assertNotIn("status", IssueContract(V2, self.contract.allowed).schema()["properties"])

    def test_valid_report_parses_with_every_field(self):
        deliverable = {"order_id": "A1", "handling_code": "R2", "owner": "refund", "customer_reply": "안내"}
        value = self.contract.parse(report(status="escalated", handoff_to=None, deliverable=deliverable,
                                           spec_approved=False))
        self.assertEqual({k: value[k] for k in T1_FIELDS},
                         {"status": "escalated", "handoff_to": None, "adopted_items": ["order:A1"],
                          "deliverable": deliverable, "spec_approved": False})
        self.assertEqual(value["open_issue_ids"], ["ownership"])
        self.assertEqual(self.contract.parse("```json\n" + report() + "\n```")["status"], "triage")

    def test_closed_list_values_outside_the_scenario_are_vocabulary_violations(self):
        for changes, code in (({"status": "closed"}, STATUS_NOT_ALLOWED), ({"handoff_to": "writer"}, HANDOFF_NOT_ALLOWED),
                              ({"open_issue_ids": ["market-share"]}, OPEN_ISSUE_ID_NOT_ALLOWED),
                              ({"unlisted_issues": ["ownership"]}, ISSUE_ID_COLLISION)):
            with self.subTest(changes=changes):
                with self.assertRaises(IssueContractViolation) as caught:
                    self.contract.parse(report(**changes))
                self.assertEqual(caught.exception.code, code)
                self.assertIn(code, VOCABULARY_VIOLATIONS_V3)

    def test_shape_errors_are_plain_contract_failures(self):
        bad = [json.dumps({k: v for k, v in json.loads(report()).items() if k != "deliverable"}),
               report(extra="x"), report(adopted_items=["a", "a"]), report(adopted_items=[""]),
               report(deliverable={"order_id": "A1"}), report(spec_approved="yes"), report(status=None),
               report(narrative=3), "[]"]
        for text in bad:
            with self.subTest(text=text[:60]):
                with self.assertRaises(ValueError) as caught:
                    self.contract.parse(text)
                self.assertNotIsInstance(caught.exception, IssueContractViolation)

    def test_instructions_add_facts_only(self):
        added = self.contract.instructions()[len(self.v2.instructions()):]
        self.assertTrue(self.contract.instructions().startswith(self.v2.instructions()))
        for fact in ('"received", "triage", "assigned", "resolved"', '["escalated"]', '"intake", "refund", "shipping"',
                     "full list of item IDs"):
            self.assertIn(fact, added)
        self.assertFalse(ADVICE & set(re.findall(r"[a-z'-]+", added.lower())))

    def test_report_and_hashes(self):
        parsed = self.contract.parse(report(unlisted_issues=["배송 사진 요청"]))
        record = self.contract.report(parsed)
        self.assertEqual(IssueReport.model_validate(record).output_contract_version, V3)
        self.assertEqual(record["allowed_issues_sha256"], self.v2.sha256)
        other = DialogueContract(self.contract.allowed, self.contract.statuses[:-1] + ("closed",), ("closed",),
                                 self.contract.agents, self.contract.deliverable_schema_json)
        self.assertNotEqual(other.contract_sha256, self.contract.contract_sha256)
        with self.assertRaises(ValueError):
            DialogueContract(self.contract.allowed, ("a", "a"), (), ("x",), self.contract.deliverable_schema_json)

    def test_only_scenario_v2_dialogue_tasks(self):
        with self.assertRaises(ValueError):
            for_dialogue_scenario(load_scenario(ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"))


if __name__ == "__main__":
    unittest.main()
