"""C-19-1 part 2: tools/replay_demo.py. extract builds record/replay.json from a raw run folder with the structured
facts only (no narrative, info_items, deliverable values or tool output), per-step tokens and credits that add up to
the session's estimate, the "if stopped" amount after the first STOP, and the blocked step of a block run; render
makes one self-contained page (inline data, no external resource, script-safe JSON); index lists the representatives.
The committed trial replay records match their sessions' token totals. Offline."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import aggregate_demo, gateway_prices, replay_demo  # noqa: E402

SECRET_TEXT = "모델 서술 비밀 문장 </script><script>alert(1)</script>"


def turn(n, prompt, completion, cached=0, tokens=True):
    return {"turn": n, "tokens": prompt + completion if tokens else None, "prompt_tokens": prompt,
            "completion_tokens": completion,
            "response_body": {"usage": {"prompt_tokens_details": {"cached_tokens": cached},
                                        "completion_tokens_details": {"reasoning_tokens": 5}}},
            "request_body": {"messages": [{"content": SECRET_TEXT}]}}


def report(status, handoff=None, adopted=0, deliverable=None):
    return {"narrative": SECRET_TEXT, "info_items": [SECRET_TEXT], "open_issue_ids": ["ownership"], "status": status,
            "handoff_to": handoff, "adopted_items": [f"a{i}" for i in range(adopted)], "deliverable": deliverable,
            "completion_declared": False, "spec_approved": None}


def observation(step, state, decision="continue", explanation=None):
    criteria = {"decision": decision}
    if explanation:
        criteria["explanation"] = {"template_id": "E4", "text": explanation}
    return {"step_id": step, "progress": {"state": state, "flags": {"revert": []}}, "criteria": criteria}


def make_run(root, mode="observe", blocked=False):
    folder = Path(root) / "DEMO-CS-stall-v1-abc"
    folder.mkdir()
    steps = [{"step_id": 1, "agent": "intake", "llm_turns": [1], "step_status": "completed", "failure_reasons": [],
              "observed_final_report": report("triage", "refund"),
              "tool_executions": [{"tool": "read_policy", "is_error": False, "result": SECRET_TEXT}]},
             {"step_id": 2, "agent": "refund", "llm_turns": [2, 3], "step_status": "completed", "failure_reasons": [],
              "observed_final_report": report("assigned", "shipping", deliverable={"customer_reply": SECRET_TEXT}),
              "tool_executions": [{"tool": "lookup_order", "is_error": True}],
              "completion_claim": {"accepted": False, "reasons": ["not_declarer"],
                                   "gate": {"missing": ["owner_confirmation"]}}},
             {"step_id": 3, "agent": "shipping", "llm_turns": [4], "step_status": "blocked" if blocked else "completed",
              "failure_reasons": [], "observed_final_report": None if blocked else report("assigned", "refund"),
              "tool_executions": []}]
    files = {
        "conditions.json": {"scenario": {"scenario_id": "DEMO-CS-stall-v1", "title": "CS",
                                         "termination": {"max_steps": 30}},
                            "task_kind": "dialogue", "batch": {"plan_id": "demo-main-v1", "mode": mode},
                            "registration": {"role_labels": {"intake": "접수", "refund": "환불 담당",
                                                              "shipping": "배송 담당"},
                                             "status_values": [{"id": "triage", "label": "분류"},
                                                               {"id": "assigned", "label": "배정"}],
                                             "terminal_statuses": [{"id": "escalated", "label": "에스컬레이션"}]}},
        "steps.json": steps,
        "summary.json": {"session_id": folder.name, "termination_reason": "guardrail_stop" if blocked else "max_steps",
                         "steps": 3},
        "session.json": {"meta": {"model": "glm-5.3-flash", "guardrail_mode": mode},
                         "turns": [turn(1, 1000, 100), turn(2, 2000, 200, cached=1000), turn(3, 2500, 50),
                                   turn(4, 3000, 300)],
                         "observations": [observation(1, "baseline"), observation(2, "stagnant", "deadlock",
                                                                                  "환불 담당과 배송 담당이 문의를 서로 넘겼습니다."),
                                          observation(3, "stagnant")]}}
    for name, value in files.items():
        (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return folder


class Extract(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_facts_only_and_no_model_text(self):
        replay = replay_demo.extract(make_run(self.root))
        text = json.dumps(replay, ensure_ascii=False)
        self.assertNotIn("모델 서술", text)
        first, second = replay["steps"][0], replay["steps"][1]
        self.assertEqual((first["role"], first["report"]["status_label"], first["report"]["handoff_to"]),
                         ("접수", "분류", "refund"))
        self.assertTrue(second["report"]["deliverable_reported"])
        self.assertEqual(second["tools"], [{"tool": "lookup_order", "is_error": True}])
        self.assertEqual(second["completion_claim"], {"accepted": False, "reasons": ["not_declarer"],
                                                      "missing": ["owner_confirmation"]})
        self.assertEqual((second["state_label"], second["stop"]["template_id"]), ("정체", "E4"))

    def test_tokens_credits_and_if_stopped(self):
        replay = replay_demo.extract(make_run(self.root))
        self.assertEqual([s["cumulative_tokens"] for s in replay["steps"]], [1100, 5850, 9150])
        whole = gateway_prices.estimate("glm-5.3-flash", [turn(1, 1000, 100), turn(2, 2000, 200, cached=1000),
                                                          turn(3, 2500, 50), turn(4, 3000, 300)])["value"]
        self.assertAlmostEqual(replay["steps"][-1]["cumulative_credits"], whole, places=5)
        self.assertEqual(replay["if_stopped"]["stop_step"], 2)
        self.assertEqual((replay["if_stopped"]["tokens_after"], replay["if_stopped"]["token_ratio"]),
                         (3300, round(3300 / 9150, 4)))

    def test_a_block_run_marks_the_refused_step(self):
        replay = replay_demo.extract(make_run(self.root, mode="block", blocked=True))
        self.assertEqual((replay["blocked_step"], replay["steps"][2]["blocked"], replay["steps"][2]["report"]),
                         (3, True, None))

    def test_a_missing_usage_leaves_credits_unknown(self):
        folder = make_run(self.root)
        log = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        log["turns"][1]["tokens"] = None
        (folder / "session.json").write_text(json.dumps(log), encoding="utf-8")
        replay = replay_demo.extract(folder)
        self.assertEqual(replay["steps"][1]["usage_missing_turns"], 1)
        self.assertIsNone(replay["steps"][1]["cumulative_credits"])
        self.assertIsNone(replay["steps"][2]["cumulative_credits"])


class Pages(unittest.TestCase):
    def test_one_self_contained_page(self):
        with tempfile.TemporaryDirectory() as directory:
            replay = replay_demo.extract(make_run(directory))
        replay["title"] = "</script><b>x</b>"
        html = replay_demo.page(replay, {"credits_measured": {"value": 1.5}})
        self.assertNotRegex(html, r'(src|href)="https?://')
        self.assertNotIn("@import", html)
        data = re.search(r'<script type="application/json" id="replay-data">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(data.replace("<\\/", "</"))["session_id"], replay["session_id"])
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("1.5 (실측)", html)
        self.assertIn("데모 세션 기준", html)

    def test_index_lists_the_representatives_with_links(self):
        result = aggregate_demo.aggregate(["demo-trial-c18-2"])
        page = replay_demo.index_page(result, {r["session_id"]: r["session_id"] + ".html"
                                              for r in result["representatives"]})
        for row in result["representatives"]:
            self.assertIn(f'href="{row["session_id"]}.html"', page)
        self.assertIn("T2 대화+산출물 교착", page)


class CommittedTrials(unittest.TestCase):
    def test_each_trial_replay_adds_up_to_its_summary(self):
        records = sorted((ROOT / "runs/demo").glob("*/record/replay.json"))
        self.assertEqual(len(records), 12)
        for path in records:
            replay = json.loads(path.read_text(encoding="utf-8"))
            summary = json.loads((path.parent / "demo-summary.json").read_text(encoding="utf-8"))
            tokens = summary["tokens"]["prompt"] + summary["tokens"]["completion"]
            self.assertEqual(sum(s["tokens"]["prompt"] + s["tokens"]["completion"] for s in replay["steps"]), tokens)
            self.assertEqual(replay["first_stop_step"], (summary.get("first_stop") or {}).get("step_id"))


if __name__ == "__main__":
    unittest.main()
