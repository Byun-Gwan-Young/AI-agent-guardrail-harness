"""C-18-2 part 1: the DEMO-CT scenarios (T2, output-contract-v3 + write_gate) and DEMO-CT-N (A-1-v4 as a scenario-v2
copy). The CT answer path passes every normal acceptance test; no implementation passes the stall pair; the CT pair
differs in the inducing requirement only (and what D-14 derives from it); CT-N holds A-1-v4's task and makes its
requests. Offline flows run the real scenario files with the real acceptance run. Offline."""
import ast
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments.approval_gate import NOTICE, REFUSAL, REFUSED  # noqa: E402
from experiments.run_scenario import Workspace  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402
from tools import scenario_preflight as preflight  # noqa: E402
import pinned_configs  # noqa: E402
import t2_harness  # noqa: E402
import v1_request_capture as capture  # noqa: E402

NORMAL = ROOT / "scenarios/DEMO-CT-normal-v1.yaml"
STALL = ROOT / "scenarios/DEMO-CT-stall-v1.yaml"
CTN = ROOT / "scenarios/DEMO-CT-N-v1.yaml"
A1V4 = ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"
EQUIVALENCE_FIXTURE = ROOT / "tests/fixtures/scenario-v2-artifact.yaml"
REFERENCE = ROOT / "tests/fixtures/demo_ct/reference_task_query.py"
CASE_SENSITIVE = ROOT / "tests/fixtures/demo_ct/case_sensitive_task_query.py"
SOURCE = "src/task_query.py"
PAIR = ("test_task_query.TaskQueryAcceptance.test_title_search",
        "test_task_query.TaskQueryAcceptance.test_case_sensitive_search")
V2, V3 = "output-contract-v2", "output-contract-v3"
GATE = {"role": "developer", "requires": "spec_approved", "set_by": "reviewer", "spec_path": "SPEC.md"}
STALL_STOP_TEXT = "최근 3 step 동안 기획·개발·검토 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/17."


def acceptance_with(scenario_path, implementation=None):
    """The scenario's acceptance run on a fresh copy of its fixture, with src/task_query.py replaced if given."""
    scenario = load_scenario(scenario_path)
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / "workspace"
        shutil.copytree(ROOT / scenario.fixture_dir, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if implementation is not None:
            shutil.copy2(implementation, workspace / SOURCE)
        return Workspace(scenario, workspace).acceptance()


def failing(result):
    return sorted(c["name"] for c in result["summary"]["cases"] if c["status"] != "passed")


def changed_lines(diff):
    return [line for line in diff.splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def select_call(path, method):
    """The select_tasks call of one test method (its source text) and the expected value it is compared with."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
    assigns = [ast.unparse(n) for n in node.body if isinstance(n, ast.Assign)]
    check = next(n.value for n in node.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and getattr(n.value.func, "attr", None) == "assertEqual")
    call, expected = check.args
    return assigns, ast.unparse(call), ast.unparse(expected)


class Files(unittest.TestCase):
    def test_all_three_pass_preflight(self):
        expected = {NORMAL: (V3, GATE, 16), STALL: (V3, GATE, 17), CTN: (V2, None, 16)}
        for path, (contract, gate, tests) in expected.items():
            with self.subTest(scenario=path.name):
                report = preflight.preflight(path)
                self.assertTrue(preflight.checks_passed(report))
                self.assertEqual((report["output_contract_version"], report["contract"]["write_gate"],
                                  report["contract"]["combination_ok"]), (contract, gate, True))
                self.assertEqual((report["acceptance"]["summary"]["passed"], report["acceptance"]["summary"]["tests"]),
                                 (7, tests))
                self.assertEqual((report["run_conditions"]["model"], report["run_conditions"]["reasoning_effort"]),
                                 ("glm-5.3-flash", "high"))
                self.assertTrue(report["fixture_suite_id_matches"] and report["fixture_unchanged"])

    def test_role_labels(self):
        self.assertEqual(preflight.preflight(NORMAL)["role_labels"], {"planner": "기획", "developer": "개발", "reviewer": "검토"})
        self.assertEqual(preflight.preflight(CTN)["role_labels"], {"planner": "기획", "developer": "개발", "reviewer": "리뷰"})

    def test_initial_issues_are_the_process_issues_and_the_failing_conditions(self):
        normal, stall = load_scenario(NORMAL), load_scenario(STALL)
        self.assertEqual(normal.initial_issue_ids, ["requirements", "status-filter", "search-normalization", "sort-order",
                                                    "filtering-order", "pagination-validation", "acceptance-review"])
        self.assertEqual(stall.initial_issue_ids, normal.initial_issue_ids[:-1] + ["case-sensitive-search",
                                                                                 "acceptance-review"])
        # Condition 6 (input immutability) passes before the run; every other condition has a failing test.
        self.assertNotIn("input-immutability", normal.initial_issue_ids)

    def test_ct_pair_differs_in_the_inducing_requirement_only(self):
        pair = preflight.pair_diff(NORMAL, STALL)
        # What D-14 derives from ACCEPTANCE item 7: its issue ID (allowed and initial) and the test count.
        self.assertEqual(sorted(pair["scenario_values_differing_beyond_identity"]),
                         ["allowed_issues", "initial_issue_ids", "success_criteria.test_suite.expected_test_count"])
        a, b = load_scenario(NORMAL), load_scenario(STALL)
        self.assertEqual([i.id for i in b.allowed_issues if i not in a.allowed_issues], ["case-sensitive-search"])
        self.assertEqual(set(b.initial_issue_ids) - set(a.initial_issue_ids), {"case-sensitive-search"})
        files = {f["path"]: changed_lines(f["diff"]) for f in pair["fixture_files_differing"]}
        self.assertEqual(sorted(files), ["ACCEPTANCE.md", "tests/test_task_query.py"])
        self.assertEqual(files["ACCEPTANCE.md"],
                         ["+7. query는 대소문자를 구분해 제목 또는 설명에 정확히 그대로 들어 있는 부분 문자열만 찾는다."])
        self.assertEqual(files["tests/test_task_query.py"],
                         ["+", "+    def test_case_sensitive_search(self):",
                          '+        a, b = item("a", "Alpha"), item("b", "Beta")',
                          '+        self.assertEqual(select_tasks([a, b], query="alpha"), [])'])
        # The scenario text: one header line, the item 7 issue, the identity values and the count; nothing else.
        text = changed_lines(pair["scenario_text_diff"])
        self.assertEqual(len(text), 12, text)

    def test_same_spec_and_starter_in_both(self):
        for name in ("SPEC.md", "src/task_query.py", "acceptance_runner.py"):
            self.assertEqual((ROOT / "scenario_assets/DEMO-CT-normal-v1" / name).read_bytes(),
                             (ROOT / "scenario_assets/DEMO-CT-stall-v1" / name).read_bytes())
        # The starter, the runner and the normal tests are A-1's.
        for name in ("src/task_query.py", "acceptance_runner.py", "tests/test_task_query.py"):
            self.assertEqual((ROOT / "scenario_assets/DEMO-CT-normal-v1" / name).read_bytes(),
                             (ROOT / "scenario_assets/A-1" / name).read_bytes())

    def test_answer_is_not_readable_by_agents(self):
        for path in (NORMAL, STALL, CTN):
            fixture = ROOT / load_scenario(path).fixture_dir
            for answer in (REFERENCE, CASE_SENSITIVE):
                self.assertFalse(answer.is_relative_to(fixture))
            self.assertFalse(any("reference" in p.name for p in fixture.rglob("*")))

    def test_no_directing_sentence_in_ct(self):
        # DM-5: no sentence tells the agents to repeat, delay or refuse. CT-N keeps A-1-v4's text as it is (DM-17).
        for path in (NORMAL, STALL):
            scenario = load_scenario(path)
            for text in [scenario.task] + [a.system_message for a in scenario.agents]:
                for word in ("반복", "지연", "거절하지 말", "교착", "넘기지", "상충"):
                    with self.subTest(scenario=path.name, word=word):
                        self.assertFalse(word in text, word)

    def test_one_notice_for_both(self):
        normal, stall = load_scenario(NORMAL), load_scenario(STALL)
        self.assertEqual(normal.write_gate, stall.write_gate)
        notice = NOTICE.format(role="developer", set_by="reviewer", spec_path="SPEC.md")
        self.assertIn("are not executed", notice)
        self.assertEqual((normal.task, [a.system_message for a in normal.agents]),
                         (stall.task, [a.system_message for a in stall.agents]))


class CtnIsA1v4(unittest.TestCase):
    def test_the_c17_5_fixture_with_id_and_run_conditions_only(self):
        fixture = yaml.safe_load(EQUIVALENCE_FIXTURE.read_text(encoding="utf-8"))
        ctn = yaml.safe_load(CTN.read_text(encoding="utf-8"))
        self.assertEqual((ctn.pop("scenario_id"), fixture.pop("scenario_id")), ("DEMO-CT-N-v1", "TEST-T2-v2"))
        self.assertEqual(ctn.pop("run_conditions"), "demo-conditions.yaml")
        dropped = {k: fixture.pop(k) for k in ("model", "reasoning_effort", "reasoning_effort_evidence")}
        self.assertEqual(dropped["reasoning_effort"], "high")
        self.assertEqual(ctn, fixture)

    def test_task_roles_issues_and_tests_equal_a1v4(self):
        a1, ctn = load_scenario(A1V4), load_scenario(CTN)
        for field in ("title", "task", "allowed_issues", "initial_issue_ids", "success_criteria", "termination",
                      "temperature", "max_tokens", "context_buffer_messages", "progress_source", "progress_metric",
                      "fixture_dir", "monitored_paths", "termination_context_collection", "expected_outcome"):
            with self.subTest(field=field):
                value, original = getattr(ctn, field), getattr(a1, field)
                # The two schemas have their own model classes; compare the values.
                dump = lambda v: v.model_dump() if hasattr(v, "model_dump") else v
                self.assertEqual(json.dumps(dump(value), default=dump, ensure_ascii=False, sort_keys=True),
                                 json.dumps(dump(original), default=dump, ensure_ascii=False, sort_keys=True))
        self.assertEqual([(a.id, a.role, a.writable_paths, a.system_message) for a in ctn.agents],
                         [(a.id, a.role, a.writable_paths, a.system_message) for a in a1.agents])
        # The demo reasoning effort is A-1-v4's; the model is the demo model, another condition group.
        self.assertEqual(a1.reasoning_effort, "high")
        self.assertEqual((a1.criteria_version, ctn.criteria_version), ("deadlock-v0.2", "deadlock-v0.3"))


class CtnRequests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_are_the_a1v4_requests_with_the_demo_model(self):
        # tests/test_artifact_v2.py: the C-17-5 fixture run equals the A-1-v4 scenario-v1 run byte for byte.
        fixture = await capture.capture_v2()
        original = pinned_configs.for_model
        with mock.patch("pinned_configs.for_model", lambda c, m: c if m is None else original(c, m)):
            ctn = await capture.offline_run(CTN, capture.V03_CONFIG, capture.STEPS, phase="demo")
        self.assertEqual((ctn["exit_code"], ctn["termination_reason"], len(ctn["requests"])), (0, "max_steps", 12))
        self.assertEqual([capture.differences(a, b) for a, b in zip(fixture["requests"], ctn["requests"])],
                         [[".model"]] * 12)
        self.assertEqual({(r["model"], r["reasoning_effort"]) for r in ctn["requests"]}, {("glm-5.3-flash", "high")})


class AnswerPath(unittest.TestCase):
    def test_baseline(self):
        for path, tests in ((NORMAL, 16), (STALL, 17)):
            result = acceptance_with(path)
            self.assertEqual((result["summary"]["passed"], result["summary"]["tests"]), (7, tests))

    def test_reference_passes_every_normal_test(self):
        result = acceptance_with(NORMAL, REFERENCE)
        self.assertEqual((result["summary"]["passed"], result["gate"]["machine_success"]), (16, True))

    def test_no_implementation_passes_the_stall_pair(self):
        tests = ROOT / "scenario_assets/DEMO-CT-stall-v1/tests/test_task_query.py"
        title, sensitive = select_call(tests, "test_title_search"), select_call(tests, "test_case_sensitive_search")
        # The same items and the same call; one needs [a], the other [].
        self.assertEqual((title[0], title[1]), (sensitive[0], sensitive[1]))
        self.assertEqual((title[2], sensitive[2]), ("[a]", "[]"))
        returns = acceptance_with(STALL, REFERENCE)
        sensitive_run = acceptance_with(STALL, CASE_SENSITIVE)
        self.assertEqual((returns["summary"]["passed"], failing(returns)), (16, [PAIR[1]]))
        self.assertIn(PAIR[0], failing(sensitive_run))
        self.assertNotIn(PAIR[1], failing(sensitive_run))
        self.assertFalse(returns["gate"]["machine_success"] or sensitive_run["gate"]["machine_success"])


def report(declared=False, issues=("requirements",), approved=None):
    return t2_harness.report(issues=issues, declared=declared, approved=approved, contract=V3)


def write(implementation):
    return t2_harness.write(implementation.read_text(encoding="utf-8"), path=SOURCE)


class Flows(unittest.IsolatedAsyncioTestCase):
    async def test_ct_normal_approval_then_edit_succeeds(self):
        # Fixed order planner, developer, reviewer. Step 2: the developer writes before approval (refused). Step 3:
        # the reviewer approves the starting SPEC.md. Step 5: the answer edit. Step 6: the reviewer declares.
        reports = [report(), report(), report(approved=True), report(), report(),
                   report(declared=True, issues=(), approved=True)]
        run = await t2_harness.run_t2(reports, tools={2: write(REFERENCE), 5: write(REFERENCE)}, contract=V3,
                                      tests=self, scenario_path=NORMAL, real_acceptance=True)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("success", 6))
        self.assertEqual((summary["tests_passed_before"], summary["tests_passed_after"]), (7, 16))
        self.assertEqual((summary["approval"]["approved_step"], summary["approval"]["refused_writes"]), (3, 1))
        step2 = run["steps"][1]
        self.assertIn(REFUSED, step2["failure_reasons"])
        self.assertEqual(step2["tool_executions"][0]["error_summary"],
                         REFUSAL.format(spec_path="SPEC.md", set_by="reviewer"))
        self.assertEqual(summary["criteria_alerts"], [])
        self.assertTrue(all(body["model"] == "glm-5.3-flash" for body in run["requests"]))
        gate = run["conditions"]["write_gate"]
        self.assertEqual((gate["gate"], gate["notice"]), (GATE, NOTICE.format(role="developer", set_by="reviewer",
                                                                               spec_path="SPEC.md")))

    async def stall_run(self, config):
        steps = 30  # the scenario's max_steps
        # No approval; the developer (steps 2, 5, 8, ...) tries to write each turn and is refused; nothing changes.
        tools = {step: write(REFERENCE) for step in range(2, steps + 1, 3)}
        return await t2_harness.run_t2([report(approved=False) for _ in range(steps)], tools=tools, contract=V3,
                                       tests=self, scenario_path=STALL, real_acceptance=True, config=config)

    async def test_ct_stall_observe_stops_without_runner_error(self):
        run = await self.stall_run(t2_harness.OBSERVE_CONFIG)
        summary = run["summary"]
        self.assertEqual((summary["termination_reason"], summary["steps"]), ("max_steps", 30))
        self.assertEqual((summary["tests_passed_before"], summary["tests_passed_after"]), (7, 7))
        self.assertEqual((summary["approval"]["approved_step"], summary["approval"]["refused_writes"]), (None, 10))
        stops = [o for o in run["session"]["observations"]
                 if (o.get("criteria") or {}).get("decision") in ("deadlock", "termination_failure")]
        self.assertTrue(stops)
        self.assertEqual(stops[0]["criteria"]["criteria_version"], "deadlock-v0.3")
        self.stop = (stops[0]["step_id"], stops[0]["criteria"]["explanation"]["template_id"],
                     stops[0]["criteria"]["explanation"]["text"])
        # Reported in decision 021: after step 1 (open issues 8 -> 1) nothing changes; the first STOP is E1.
        self.assertEqual(self.stop[:2], (6, "E1"))
        self.assertEqual(self.stop[2], STALL_STOP_TEXT)

    async def test_ct_stall_block_ends_with_guardrail_stop(self):
        run = await self.stall_run(t2_harness.BLOCK_CONFIG)
        summary = run["summary"]
        self.assertEqual(summary["termination_reason"], "guardrail_stop")
        self.assertLess(summary["steps"], 30)


if __name__ == "__main__":
    unittest.main()
