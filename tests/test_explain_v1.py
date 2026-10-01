"""C-17-1 part 2: explain-v1 STOP sentences from judgement signal values only (DM-9)."""
import json
from pathlib import Path
import string
import tempfile
import unittest
from unittest import mock

import httpx
import deadlock_policy_v03
import explain_v1
from explain_v1 import TEMPLATES, E6_DIALOGUE, UNMEASURED, explain
from proxy import create_app
from test_criteria_v03 import CONFIG, CONTEXT, artifact_obs, configured, dialogue, replay
from tools import analyze_session as tool

ROOT = Path(__file__).resolve().parents[1]
V4 = "A-1-v4-e174aafe805b4f59bb62d7c95716b8b7"
LABELS = {"planner": "기획", "developer": "개발", "reviewer": "리뷰"}


def signals(**changes):
    base = {"decision": "deadlock", "stop_step": 9, "task_kind": "artifact", "consecutive_steps": 3,
            "consecutive_states": ["stagnant"] * 3, "streak_roles": ["planner", "developer", "reviewer"],
            "declared_step": None, "test_pass_count": 7, "test_total_count": 16, "global_revert": None,
            "test_plateau_in_streak": False, "test_max_step": 1, "steps_since_test_max": 8,
            "file_state_changes_since_test_max": 0, "handoff": None, "handoff_threshold": 4, "status": None,
            "adopted_metric_selected": False, "adopted_count": None, "adopted_required": None}
    return {**base, **changes}


def stop_record(rows):
    return next(r for r in rows if r["criteria"]["decision"] in ("deadlock", "termination_failure"))


def declared(observation, step):
    return {**observation, "termination_context": {**CONTEXT, "declaration": "declared", "declared_step": step}}


class TemplateTests(unittest.TestCase):
    def test_each_template_from_signal_values(self):
        cases = {
            "E1": (signals(), "최근 3 step 동안 planner·developer·reviewer 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. "
                              "통과 테스트 7/16."),
            "E2": (signals(global_revert={"step": 6, "paths": ["src/x.py"], "revert_to_step": 4}, steps_since_test_max=6,
                           test_pass_count=12),
                   "src/x.py 가 step 4 의 내용으로 되돌아갔고, 통과 테스트는 6 step 동안 12/16 입니다."),
            "E3": (signals(test_plateau_in_streak=True, test_max_step=3, steps_since_test_max=9,
                           file_state_changes_since_test_max=5),
                   "step 3 이후 9 step 동안 파일이 5 번 바뀌었지만 통과 테스트는 7/16 에서 늘지 않았습니다."),
            "E4": (signals(task_kind="dialogue", status="triage",
                           handoff={"roles": ["refund", "shipping"], "count": 4, "at_or_above_threshold": True}),
                   "refund 과 shipping 가 문의를 서로 4 번 넘겼고 처리 상태는 'triage' 에서 바뀌지 않았습니다."),
            "E5": (signals(task_kind="dialogue", status="triage", adopted_metric_selected=True, adopted_count=2,
                           adopted_required=6),
                   "최근 3 step 동안 채택 항목이 2/6 에서 늘지 않았고 처리 상태는 'triage' 입니다."),
            "E6": (signals(decision="termination_failure", declared_step=5),
                   "step 5 에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 통과 테스트 7/16."),
            "E7": (signals(consecutive_states=["stagnant", "oscillating", "stagnant"]),
                   "최근 3 step 중 1 step 은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다."),
        }
        self.assertEqual(set(cases), set(TEMPLATES))
        for template_id, (values, text) in cases.items():
            with self.subTest(template=template_id):
                result = explain(values)
                self.assertEqual((result["template_id"], result["text"]), (template_id, text))
                self.assertEqual(result["missing_values"], [])
        dialogue_e6 = explain(signals(decision="termination_failure", declared_step=5, task_kind="dialogue",
                                      status="assigned"))
        self.assertEqual(dialogue_e6["text"], "step 5 에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. "
                                              "처리 상태는 'assigned' 입니다.")

    def test_placeholders_match_recorded_values(self):
        for template_id, template in list(TEMPLATES.items()) + [("E6", E6_DIALOGUE)]:
            fields = {f for _, f, _, _ in string.Formatter().parse(template) if f}
            kind = "dialogue" if template is E6_DIALOGUE else "artifact"
            forced = {"E1": {}, "E2": {"global_revert": {"paths": ["a"], "revert_to_step": 1}},
                      "E3": {"test_plateau_in_streak": True}, "E4": {"handoff": {"roles": ["a", "b"], "count": 9}},
                      "E5": {"adopted_metric_selected": True}, "E6": {"decision": "termination_failure"},
                      "E7": {"consecutive_states": ["oscillating"]}}[template_id]
            with self.subTest(template=template_id, kind=kind):
                result = explain(signals(task_kind=kind, **forced))
                self.assertEqual(result["template_id"], template_id)
                self.assertEqual(set(result["values"]), fields)

    def test_missing_values_are_reported_not_invented(self):
        result = explain(signals(test_pass_count=None, test_total_count=None, streak_roles=[]))
        self.assertEqual(result["text"], f"최근 3 step 동안 {UNMEASURED} 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. "
                                         f"통과 테스트 {UNMEASURED}/{UNMEASURED}.")
        self.assertEqual(result["missing_values"], ["pass", "roles", "total"])
        e5 = explain(signals(task_kind="dialogue", adopted_metric_selected=True, adopted_count=1, status="triage"))
        self.assertIn(f"1/{UNMEASURED}", e5["text"])
        self.assertEqual(e5["missing_values"], ["required"])

    def test_selection_order(self):
        handoff = {"roles": ["a", "b"], "count": 4}
        everything = signals(decision="termination_failure", global_revert={"paths": ["f"], "revert_to_step": 1},
                             test_plateau_in_streak=True, handoff=handoff, adopted_metric_selected=True,
                             consecutive_states=["oscillating"] * 3)
        order = ["E6", "E2", "E3", "E4", "E5", "E7", "E1"]
        removals = [{"decision": "deadlock"}, {"global_revert": None}, {"test_plateau_in_streak": False},
                    {"handoff": None}, {"adopted_metric_selected": False}, {"consecutive_states": ["stagnant"] * 3}]
        current = everything
        for expected, removal in zip(order, removals + [{}]):
            self.assertEqual(explain(current)["template_id"], expected)
            current = {**current, **removal}
        below = signals(handoff={"roles": ["a", "b"], "count": 3})
        self.assertEqual(explain(below)["template_id"], "E1")
        self.assertEqual(explain({**below, "handoff_threshold": 3})["template_id"], "E4")

    def test_record_rebuilds_the_same_sentence_and_labels_are_optional(self):
        record = explain(signals())
        self.assertEqual(explain(record["signals"], record["role_labels"]), record)
        labelled = explain(signals(), LABELS)
        self.assertIn("기획·개발·리뷰 모두", labelled["text"])
        self.assertEqual(explain(labelled["signals"], labelled["role_labels"]), labelled)


class StopRecordTests(unittest.TestCase):
    def test_t2_unchanged_session_gives_e1(self):
        rows = replay([artifact_obs(s, {"code.py": "same"}) for s in range(1, 7)], configured())
        record = rows[5]["criteria"]
        self.assertEqual(record["explanation"]["template_id"], "E1")
        self.assertEqual(record["explanation"]["values"],
                         {"n": 3, "roles": ["planner", "developer", "reviewer"], "pass": 7, "total": 16})
        self.assertTrue(all("explanation" not in r["criteria"] for r in rows[:5]))

    def test_t3_global_revert_in_streak_gives_e2(self):
        contents = ["s0", "s0", "s0", "s1", "s2", "s1", "s1", "s1"]
        rows = replay([artifact_obs(s, {"code.py": c}) for s, c in enumerate(contents, 1)], configured())
        record = stop_record(rows)
        self.assertEqual(record["criteria"]["first_deadlock_step"], 8)
        self.assertEqual(record["criteria"]["explanation"]["text"],
                         "code.py 가 step 4 의 내용으로 되돌아갔고, 통과 테스트는 7 step 동안 7/16 입니다.")

    def test_t3_plateau_gives_e3(self):
        rows = replay([artifact_obs(s, {"code.py": f"v{s}"}) for s in range(1, 11)], configured())
        self.assertEqual(rows[-1]["criteria"]["explanation"]["text"],
                         "step 1 이후 9 step 동안 파일이 9 번 바뀌었지만 통과 테스트는 7/16 에서 늘지 않았습니다.")

    def test_t1_handoff_gives_e4_and_adopted_stagnation_gives_e5(self):
        agents = ["refund", "shipping"] * 3
        rows = replay([dialogue(s, agent=a, handoff=agents[s]) for s, a in enumerate(agents[:5], 1)], configured())
        self.assertEqual(rows[-1]["criteria"]["explanation"]["text"],
                         "refund 과 shipping 가 문의를 서로 5 번 넘겼고 처리 상태는 'received' 에서 바뀌지 않았습니다.")
        rows = replay([dialogue(s, status="triage", adopted=["a"]) for s in range(1, 7)], configured())
        explanation = rows[-1]["criteria"]["explanation"]
        self.assertEqual(explanation["text"],
                         f"최근 3 step 동안 채택 항목이 1/{UNMEASURED} 에서 늘지 않았고 처리 상태는 'triage' 입니다.")
        self.assertEqual(explanation["missing_values"], ["required"])

    def test_termination_failure_gives_e6_in_both_forms(self):
        inputs = [artifact_obs(s, {"code.py": "same"}) for s in range(1, 8)]
        inputs = inputs[:3] + [declared(o, 4) for o in inputs[3:]]
        rows = replay(inputs, configured())
        self.assertEqual(rows[-1]["criteria"]["decision"], "termination_failure")
        self.assertEqual(rows[-1]["criteria"]["explanation"]["text"],
                         "step 4 에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 통과 테스트 7/16.")
        talk = [dialogue(s) for s in range(1, 8)]
        rows = replay(talk[:3] + [declared(o, 4) for o in talk[3:]], configured())
        self.assertEqual(rows[-1]["criteria"]["explanation"]["text"],
                         "step 4 에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 'received' 입니다.")

    def test_oscillation_in_streak_gives_e7(self):
        issues = [["a", "b"], ["a"], ["a"], ["a"], ["a"], ["a"], ["a", "b"]]
        rows = replay([artifact_obs(s, {"code.py": "same"}, issues=i) for s, i in enumerate(issues, 1)], configured())
        self.assertEqual(rows[-1]["criteria"]["consecutive_states"], ["stagnant", "stagnant", "oscillating"])
        self.assertEqual(rows[-1]["criteria"]["explanation"]["text"],
                         "최근 3 step 중 1 step 은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다.")

    def test_dialogue_without_tests_reports_them_unmeasured(self):
        rows = replay([dialogue(s, metrics=["status_advance", "new_issue_ids"]) for s in range(1, 7)], configured())
        explanation = rows[-1]["criteria"]["explanation"]
        self.assertEqual(explanation["template_id"], "E1")
        self.assertEqual(explanation["missing_values"], ["pass", "total"])

    def test_model_text_never_reaches_the_sentence(self):
        marker = "MODEL-TEXT-MARKER"
        inputs = []
        for step in range(1, 7):
            o = artifact_obs(step, {"code.py": "same"})
            o["conversation"]["reasons"] = {"open_issue_ids": marker}
            o["conversation"]["evidence"] = [{"narrative": marker}]
            o["artifact"]["reasons"] = {"build_status": marker}
            inputs.append(o)
        explanation = replay(inputs, configured())[-1]["criteria"]["explanation"]
        self.assertNotIn(marker, json.dumps(explanation, ensure_ascii=False))

    def test_explanation_failure_keeps_the_decision(self):
        rows = replay([artifact_obs(s, {"code.py": "same"}) for s in range(1, 6)], configured())
        sixth = artifact_obs(6, {"code.py": "same"})
        from progress_signal_v3 import calculate_progress
        record = {**sixth, "progress": calculate_progress(rows, sixth, configured()["criteria_parameters"])}
        with mock.patch.object(deadlock_policy_v03, "explain", side_effect=RuntimeError("boom")):
            result = deadlock_policy_v03.evaluate_criteria(rows + [record], configured())
        self.assertEqual(result["decision"], "deadlock")
        self.assertEqual(result["explanation"],
                         {"explanation_version": "explain-v1", "status": "failed", "reason": "RuntimeError"})


class ManifestTests(unittest.TestCase):
    def test_v04_copies_the_first_stop_record(self):
        analysis = json.loads(json.dumps(tool.analyse(V4), ensure_ascii=False))
        log = json.loads((ROOT / "logs" / f"{V4}.json").read_text(encoding="utf-8"))
        fields = set(log["observations"][0]) - {"progress", "criteria", "observed_at", "extraction_comparison"}
        rows = replay([{k: v for k, v in o.items() if k in fields} for o in log["observations"]], configured())
        base = tool.base_manifest(analysis, "measure", [])
        conditions = json.loads((ROOT / "runs" / V4 / "conditions.json").read_text(encoding="utf-8"))
        m = tool.v04_fields(tool.v03_fields(base, analysis, conditions, rows), rows)
        self.assertEqual(m["manifest_version"], "session-manifest-v0.4")
        first = m["guardrail"]["first_stop_explanation"]
        self.assertEqual(first, {"step_id": 9, **rows[8]["criteria"]["explanation"]})
        self.assertEqual(explain(first["signals"], first["role_labels"])["text"], first["text"])
        self.assertIsNone(tool.v04_fields(tool.v03_fields(tool.base_manifest(analysis, "measure", []), analysis,
                                                          conditions, rows[:5]), rows[:5])
                          ["guardrail"]["first_stop_explanation"])


class ExplanationApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_record_with_sentence_is_persisted(self):
        def upstream(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / "logs"
            app = create_app(logs, httpx.MockTransport(upstream), config_path=CONFIG)
            headers = {"X-Guardrail-Session": "explain"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                for step in range(1, 7):
                    await c.post("/v1/chat/completions", json={"messages": []}, headers=headers)
                    response = await c.post("/sessions/observations", headers=headers,
                                            json=artifact_obs(step, {"code.py": "same"}))
            criteria = response.json()["observation"]["criteria"]
            self.assertEqual(criteria["decision"], "deadlock")
            stored = json.loads((logs / "explain.json").read_text(encoding="utf-8"))["observations"][-1]["criteria"]
            self.assertEqual(stored["explanation"], criteria["explanation"])
            self.assertEqual(stored["explanation"]["template_id"], "E1")
