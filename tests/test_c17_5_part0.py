"""C-17-5 part 0: the C-17-4 decisions DM-42 (spacing after quoted names and paths), DM-43 (E4 only with both roles
and the count), DM-44 (a self-naming handoff_to is a vocabulary violation), DM-45 (T1 success is the declarer's own
judged report), DM-46 (escalated is the one terminal status) and DM-47 (the handoff rule is named in the manifest)."""
import re
import unittest
from unittest import mock

import yaml
from pydantic import ValidationError

from tools import analyze_session
from explain_v1 import E6_DIALOGUE, TEMPLATES, UNMEASURED, explain
from scenario_schema import ScenarioV2
from t1_harness import DELIVERABLE, FIXTURE, report, run_t1

FIXED = {"turn_order": "fixed"}
LOOKUP = {1: ("lookup_order", {"order_id": "A-100"})}
LABELS = ({"refund": "환불 담당", "shipping": "배송 담당"}, {"triage": "분류", "received": "접수"})


def signals(**changes):
    return {"decision": "deadlock", "stop_step": 8, "task_kind": "dialogue", "consecutive_steps": 3,
            "consecutive_states": ["stagnant"] * 3, "streak_roles": ["refund", "shipping"], "handoff": None,
            "handoff_threshold": 4, "status": "triage", "test_observed_in_session": False,
            "selected_metrics": ["conversation.status_advance", "conversation.new_issue_ids"], **changes}


class SpacingTests(unittest.TestCase):
    """DM-42: a particle or '입니다' after a quoted status name or a path is attached; number units keep their space."""

    def test_the_three_sentences_of_the_instruction(self):
        e5 = explain(signals(adopted_metric_selected=True, adopted_count=1, adopted_required=3), *LABELS)
        self.assertEqual(e5["text"], "최근 3 step 동안 채택 항목이 1/3에서 늘지 않았고 처리 상태는 '분류'입니다.")
        e4 = explain(signals(status="received", handoff={"roles": ["refund", "shipping"], "count": 4}), *LABELS)
        self.assertEqual(e4["text"], "환불 담당과 배송 담당이 문의를 서로 4 번 넘겼고 처리 상태는 '접수'에서 바뀌지 않았습니다.")
        e2 = explain({"decision": "deadlock", "stop_step": 9, "global_revert": {"paths": ["src/x.py"], "revert_to_step": 4},
                      "steps_since_test_max": 6, "test_pass_count": 12, "test_total_count": 16})
        self.assertEqual(e2["text"], "src/x.py 파일이 step 4의 내용으로 되돌아갔고, 통과 테스트는 6 step 동안 12/16입니다.")
        e6 = explain(signals(decision="termination_failure", declared_step=4), *LABELS)
        self.assertEqual(e6["text"], "step 4에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '분류'입니다.")

    def test_no_template_leaves_a_space_after_a_quote_or_path_slot(self):
        templates = {**TEMPLATES, "E6-dialogue": E6_DIALOGUE}
        for template_id, text in templates.items():
            with self.subTest(template=template_id):
                self.assertIsNone(re.search(r"' (에서|입니다|이|가|을|를|은|는|과|와)", text))
                self.assertNotIn("{path} 가", text)
        # Every path slot reads "{path} 파일이"; number units keep their space ("{n} step", "{h} 번").
        self.assertEqual([t for t, text in templates.items() if "{path}" in text], ["E2"])
        self.assertIn("{path} 파일이 ", TEMPLATES["E2"])
        self.assertIn("{h} 번", TEMPLATES["E4"])
        self.assertIn("{n} step", TEMPLATES["E5"])


class HandoffTemplateTests(unittest.TestCase):
    """DM-43: E4 needs both role names and the round-trip count; otherwise the next template in the order."""

    def test_e4_with_both_roles_and_the_count(self):
        chosen = explain(signals(handoff={"roles": ["refund", "shipping"], "count": 4}), *LABELS)
        self.assertEqual(chosen["template_id"], "E4")
        self.assertEqual(chosen["missing_values"], [])

    def test_a_missing_role_or_count_moves_on(self):
        cases = {"no roles": {"roles": None, "count": 4}, "one role": {"roles": ["refund", None], "count": 5},
                 "no count": {"roles": ["refund", "shipping"], "count": None}, "below H": {"roles": ["a", "b"], "count": 3}}
        for name, handoff in cases.items():
            with self.subTest(case=name):
                # Next in the order with these signals: E1-T1 (no adopted metric, no oscillation, no tests).
                chosen = explain(signals(handoff=handoff), *LABELS)
                self.assertEqual(chosen["template_id"], "E1-T1")
                self.assertNotIn(f"{UNMEASURED} {UNMEASURED}", chosen["text"])
                self.assertNotIn("넘겼고", chosen["text"])
                # With the adopted metric selected the next one is E5.
                self.assertEqual(explain(signals(handoff=handoff, adopted_metric_selected=True, adopted_count=1,
                                                 adopted_required=3))["template_id"], "E5")


class SelfHandoffTests(unittest.IsolatedAsyncioTestCase):
    """DM-44: handoff_to naming the reporting role is a vocabulary violation; the other fields stay valid."""

    async def test_router_counts_it_leaves_it_unobserved_and_falls_back(self):
        reports = [report("triage", handoff="intake"), report("assigned", handoff="intake"), report("assigned")]
        run = await run_t1(reports, max_steps=3, tests=self)
        steps, summary = run["steps"], run["summary"]
        self.assertEqual([s["agent"] for s in steps], ["intake", "refund", "intake"])
        self.assertEqual([s["vocabulary_violation"] for s in steps], ["handoff_to_self", None, None])
        self.assertEqual((summary["vocabulary_violations_total"], summary["vocabulary_violation_steps"]), (1, [1]))
        # The report is still the step's report: completed, not a strict failure, shared and observed without the value.
        self.assertEqual((steps[0]["step_status"], steps[0]["consecutive_strict_failures"],
                          steps[0]["shared_narrative_source"], steps[0]["route"]["fallback_reason"]),
                         ("completed", 0, "parsed", "self_handoff"))
        first = run["session"]["observations"][0]["conversation"]
        self.assertNotIn("handoff_to", first)
        self.assertEqual(first["status"], "triage")
        self.assertEqual(steps[0]["observed_final_report"]["handoff_to"], "intake")
        # A handoff to another role is observed as before.
        self.assertEqual(run["session"]["observations"][1]["conversation"]["handoff_to"], "intake")

    async def test_fixed_order_counts_it_too(self):
        run = await run_t1([report("triage", handoff="intake"), report("triage", handoff="intake")], max_steps=2,
                           scenario_changes=FIXED, tests=self)
        self.assertEqual([s["vocabulary_violation"] for s in run["steps"]], ["handoff_to_self", None])
        self.assertEqual([s["agent"] for s in run["steps"]], ["intake", "refund"])
        self.assertNotIn("handoff_to", run["session"]["observations"][0]["conversation"])
        self.assertEqual(run["session"]["observations"][1]["conversation"]["handoff_to"], "intake")

    async def test_it_does_not_feed_the_strict_failure_stop(self):
        reports = [report("triage", handoff="intake"), "not json", report("triage", handoff="shipping"), "not json",
                   report("triage")]
        run = await run_t1(reports, max_steps=5, scenario_changes=FIXED, tests=self)
        self.assertEqual([s["consecutive_strict_failures"] for s in run["steps"]], [0, 1, 0, 1, 0])
        self.assertEqual([s["vocabulary_violation"] for s in run["steps"]],
                         ["handoff_to_self", None, "handoff_to_self", None, None])
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    """DM-45: success only on the declarer's own report in the completion status that passes the judge."""

    async def test_the_declarers_report_succeeds(self):
        reports = [report("triage"), report("triage"), report("assigned"),
                   report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=FIXED, tests=self)
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 4))
        self.assertEqual(run["steps"][3]["completion_claim"]["accepted"], True)
        self.assertEqual(run["steps"][3]["completion_claim"]["gate"],
                         {"machine_success": True, "result": "resolved", "missing": []})

    async def test_a_failed_declaration_is_recorded_and_the_run_goes_on(self):
        # Intake declares at step 1 without a lookup (judge unfinished), then again at step 4 after the lookup.
        reports = [report("resolved", deliverable=DELIVERABLE, declared=True, issues=()), report("triage"),
                   report("triage"), report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools={2: ("lookup_order", {"order_id": "A-100"})}, scenario_changes=FIXED,
                           tests=self)
        first = run["steps"][0]["completion_claim"]
        self.assertEqual((first["accepted"], first["reasons"], first["gate"]["missing"]),
                         (False, ["judge_unfinished"], ["order_id_not_looked_up"]))
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 4))

    async def test_a_non_declarer_completion_status_is_recorded_only(self):
        # Refund (router target) reports the completion status with a passing deliverable: no success.
        reports = [report("triage", handoff="refund"), report("resolved", deliverable=DELIVERABLE, declared=True,
                                                              issues=(), handoff="intake"),
                   report("resolved", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, max_steps=3, tests=self)
        claims = run["summary"]["completion_claims"]
        self.assertEqual([(c["step_id"], c["agent"], c["accepted"], c["reasons"]) for c in claims],
                         [(2, "refund", False, ["not_declarer"]), (3, "intake", True, [])])
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 3))
        # The status itself is observed as the shared state whoever reports it.
        self.assertEqual(run["session"]["observations"][1]["conversation"]["status"], "resolved")

    async def test_the_declarer_must_also_be_in_the_completion_status(self):
        reports = [report("assigned", deliverable=DELIVERABLE, declared=True, issues=())]
        run = await run_t1(reports, tools=LOOKUP, max_steps=1, scenario_changes=FIXED, tests=self)
        claim = run["steps"][0]["completion_claim"]
        self.assertEqual((claim["accepted"], claim["reasons"]), (False, ["status_not_completion"]))
        self.assertEqual(run["summary"]["termination_reason"], "max_steps")

    async def test_without_a_required_declaration_it_is_still_the_declarers_report(self):
        changes = {**FIXED, "termination": {**yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["termination"],
                                            "require_completion_declaration": False}}
        reports = [report("triage"), report("resolved", deliverable=DELIVERABLE, issues=()),
                   report("resolved", deliverable=DELIVERABLE, issues=()),
                   report("resolved", deliverable=DELIVERABLE, issues=())]
        run = await run_t1(reports, tools=LOOKUP, scenario_changes=changes, max_steps=4, tests=self)
        self.assertEqual([(c["agent"], c["accepted"]) for c in run["summary"]["completion_claims"]],
                         [("refund", False), ("shipping", False), ("intake", True)])
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["steps"]), ("success", 4))

    async def test_any_roles_escalated_report_ends_the_run(self):
        # Decision recorded in docs/decisions/016 (C-17-5): escalation is not a judged final answer.
        run = await run_t1([report("triage"), report("escalated")], scenario_changes=FIXED, max_steps=3, tests=self)
        self.assertEqual((run["summary"]["termination_reason"], run["summary"]["escalated_by"], run["summary"]["steps"]),
                         ("escalated", "refund", 2))
        self.assertEqual(run["summary"]["completion_claims"], [])


class TerminalStatusTests(unittest.IsolatedAsyncioTestCase):
    """DM-46: one completion status (the last ordered status) and escalated; the terminal_status ending is gone."""

    def test_schema_allows_escalated_only(self):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual([s.id for s in ScenarioV2.model_validate(data).terminal_statuses], ["escalated"])
        for name, terminal in {"none": [], "other": [{"id": "withdrawn", "label": "철회"}],
                               "two": [{"id": "escalated", "label": "e"}, {"id": "withdrawn", "label": "w"}]}.items():
            with self.subTest(case=name), self.assertRaisesRegex(ValidationError, "DM-46"):
                ScenarioV2.model_validate({**data, "terminal_statuses": terminal})

    async def test_summary_has_no_terminal_status_reason_or_field(self):
        run = await run_t1([report("escalated")], scenario_changes=FIXED, max_steps=1, tests=self)
        self.assertNotIn("terminal_status", run["summary"])
        self.assertEqual(run["summary"]["termination_reason"], "escalated")


class ManifestTests(unittest.IsolatedAsyncioTestCase):
    """DM-47 and the manifest v0.6 fields that DM-44..46 changed."""

    async def test_manifest_names_the_handoff_rule_and_records_claims(self):
        reports = [report("triage", handoff="intake"), report("escalated")]
        run = await run_t1(reports, max_steps=2, scenario_changes=FIXED, tests=self)
        self.assertEqual((run["conditions"]["recent_messages_rule"], run["summary"]["recent_messages_rule"]),
                         ("t1-handoff-v1", "t1-handoff-v1"))
        with mock.patch.object(analyze_session, "ROOT", run["root"]):
            manifest = analyze_session.manifest(analyze_session.analyse(run["session_id"]), "measure", [])
        # C-18-2: the runner records the account label and batch item (None here), so the manifest is v0.7 (v0.6 + run.account_label, run.batch).
        self.assertEqual(manifest["manifest_version"], "session-manifest-v0.7")
        self.assertEqual(manifest["task"]["recent_messages_rule"], "t1-handoff-v1")
        self.assertEqual((manifest["run"]["termination_reason"], manifest["run"]["escalated_by"]), ("escalated", "refund"))
        self.assertNotIn("terminal_status", manifest["run"])
        self.assertEqual((manifest["vocabulary_violations"]["total"], manifest["vocabulary_violations"]["steps"]), (1, [1]))
        self.assertEqual(manifest["judgement"]["completion_claims"], [])


if __name__ == "__main__":
    unittest.main()
