"""C-17-3 part 2: session registration (DM-26, DM-29, DM-35) read by progress-v3 and explain-v1."""
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from pydantic import ValidationError

from progress_schema import SessionRegistration
from proxy import create_app
from scenario_schema import load_scenario, registration_for
from test_criteria_v03 import CONFIG as V03_CONFIG, CONTEXT
from pinned_configs import demo_model

ROOT = Path(__file__).resolve().parents[1]
DEMO_MODEL = demo_model()  # C-17-8: the demo proxies forward their pinned model only (S-12)
DIALOGUE = ROOT / "tests/fixtures/scenario-v2-dialogue.yaml"
V02_CONFIG = ROOT / "guardrail-deadlock-v0.2-kmu.yaml"
AGENTS = ["intake", "refund", "shipping"]


def registration(metrics=("status_advance", "adopted_items", "new_issue_ids")):
    value = registration_for(load_scenario(DIALOGUE))
    value["progress_metric"]["conversation"] = list(metrics)
    return value


def observation(step, metrics, status="triage", adopted=("a",), issues=("requirements",), declared=None):
    context = CONTEXT if declared is None or step < declared else {
        **CONTEXT, "declaration": "declared", "declared_step": declared}
    return {"agent_id": AGENTS[(step - 1) % 3], "step_id": step, "llm_turns": [step],
            "progress_source": "conversation", "progress_metric": {"conversation": list(metrics), "artifact": []},
            "conversation": {"source_kind": "structured", "status": status, "adopted_items": list(adopted),
                             "open_issue_ids": list(issues)},
            "artifact": None, "termination_context": context}


class RegistrationModelTests(unittest.TestCase):
    def test_scenario_registration(self):
        value = registration_for(load_scenario(DIALOGUE))
        model = SessionRegistration.model_validate(value)
        self.assertEqual(model.role_labels, {"intake": "접수", "refund": "환불 담당", "shipping": "배송 담당"})
        self.assertEqual([(s.id, s.label) for s in model.status_values],
                         [("received", "접수"), ("triage", "분류"), ("assigned", "배정"), ("resolved", "해결")])
        self.assertEqual((model.terminal_statuses[0].label, model.required_adopted_items), ("에스컬레이션", 3))
        self.assertEqual(model.model_dump(), value)
        with self.assertRaises(ValueError):
            registration_for(load_scenario(ROOT / "scenarios/A-1-v4-ambiguous-task-query.yaml"))

    def test_invalid_registrations(self):
        base = registration()
        cases = {"empty label": {"role_labels": {"intake": " "}}, "no roles": {"role_labels": {}},
                 "status repeated": {"terminal_statuses": [{"id": "triage", "label": "x"}]},
                 "status_advance without order": {"status_values": []}, "extra key": {"status_order": []},
                 "unknown metric": {"progress_metric": {"conversation": ["agreement"], "artifact": []}}}
        for name, change in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError):
                SessionRegistration.model_validate({**base, **change})


class RegistrationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())

    def client(self, config):
        app = create_app(Path(self.directory) / "logs", httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})), config_path=config)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(client.aclose)
        return client

    async def run_steps(self, metrics, inputs):
        """Register, then one chat turn and one observation per step through the real API."""
        client = self.client(V03_CONFIG)
        headers = {"X-Guardrail-Session": "t1"}
        started = await client.post("/sessions", headers=headers, json={"registration": registration(metrics)})
        self.assertEqual(started.json(), {"session_id": "t1", "registered": True})
        for raw in inputs:
            await client.post("/v1/chat/completions", json={"messages": [], "model": DEMO_MODEL}, headers=headers)
            response = await client.post("/sessions/observations", headers=headers, json=raw)
            self.assertEqual(response.status_code, 200, response.text)
        return (await client.get("/log", headers=headers)).json()

    async def test_registration_is_stored_once_and_only_for_v03(self):
        client = self.client(V03_CONFIG)
        response = await client.post("/sessions", headers={"X-Guardrail-Session": "a"}, json={"registration": registration()})
        self.assertEqual(response.status_code, 200)
        meta = (await client.get("/log", headers={"X-Guardrail-Session": "a"})).json()["meta"]
        self.assertEqual(meta["registration"], registration())
        plain = await client.post("/sessions", headers={"X-Guardrail-Session": "b"})
        self.assertEqual(plain.json(), {"session_id": "b"})
        self.assertNotIn("registration", (await client.get("/log", headers={"X-Guardrail-Session": "b"})).json()["meta"])
        for body in ({"registration": {**registration(), "role_labels": {}}}, {"other": 1}, [1]):
            with self.subTest(body=body):
                refused = await client.post("/sessions", headers={"X-Guardrail-Session": "c"}, json=body)
                self.assertEqual(refused.status_code, 422)
        legacy = self.client(V02_CONFIG)
        refused = await legacy.post("/sessions", headers={"X-Guardrail-Session": "d"}, json={"registration": registration()})
        self.assertEqual((refused.status_code, "deadlock-v0.3" in refused.text), (422, True))
        self.assertEqual((await legacy.post("/sessions", headers={"X-Guardrail-Session": "e"})).status_code, 200)

    async def test_observations_must_use_the_registered_metric_selection(self):
        client = self.client(V03_CONFIG)
        headers = {"X-Guardrail-Session": "m"}
        await client.post("/sessions", headers=headers, json={"registration": registration(["adopted_items"])})
        await client.post("/v1/chat/completions", json={"messages": [], "model": DEMO_MODEL}, headers=headers)
        other = await client.post("/sessions/observations", headers=headers,
                                  json=observation(1, ["adopted_items", "new_issue_ids"]))
        self.assertEqual(other.status_code, 422)
        self.assertIn("registration", other.text)
        same = await client.post("/sessions/observations", headers=headers, json=observation(1, ["adopted_items"]))
        self.assertEqual(same.status_code, 200)

    async def test_registered_status_order_judges_status_advance(self):
        metrics = ["status_advance", "new_issue_ids"]
        statuses = ["received", "received", "received", "triage", "assigned", "assigned"]
        log = await self.run_steps(metrics, [observation(s, metrics, status=st) for s, st in enumerate(statuses, 1)])
        self.assertEqual([o["progress"]["state"] for o in log["observations"]],
                         ["baseline"] * 3 + ["progress", "progress", "stagnant"])

    async def test_e1_t1_with_registered_korean_names(self):
        metrics = ["status_advance", "new_issue_ids"]
        log = await self.run_steps(metrics, [observation(s, metrics) for s in range(1, 7)])
        explanation = log["observations"][-1]["criteria"]["explanation"]
        self.assertEqual(explanation["template_id"], "E1-T1")
        self.assertEqual(explanation["text"], "최근 3 step 동안 접수·환불 담당·배송 담당 모두 처리 상태 변화·새 쟁점이 없습니다. "
                                              "처리 상태 '분류'.")
        self.assertEqual((explanation["missing_values"], explanation["signals"]["status"]), ([], "triage"))
        self.assertEqual(explanation["status_labels"]["triage"], "분류")

    async def test_e5_with_the_registered_required_count(self):
        metrics = ["status_advance", "adopted_items", "new_issue_ids"]
        log = await self.run_steps(metrics, [observation(s, metrics) for s in range(1, 7)])
        explanation = log["observations"][-1]["criteria"]["explanation"]
        self.assertEqual(explanation["template_id"], "E5")
        self.assertEqual(explanation["text"], "최근 3 step 동안 채택 항목이 1/3에서 늘지 않았고 처리 상태는 '분류'입니다.")
        self.assertEqual(explanation["missing_values"], [])

    async def test_e6_with_the_registered_status_name(self):
        metrics = ["status_advance", "new_issue_ids"]
        log = await self.run_steps(metrics, [observation(s, metrics, declared=4) for s in range(1, 8)])
        criteria = log["observations"][-1]["criteria"]
        self.assertEqual(criteria["decision"], "termination_failure")
        self.assertEqual(criteria["explanation"]["text"],
                         "step 4에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '분류'입니다.")

    async def test_without_registration_ids_and_unmeasured_remain(self):
        client = self.client(V03_CONFIG)
        headers = {"X-Guardrail-Session": "plain"}
        metrics = ["adopted_items", "new_issue_ids"]
        for step in range(1, 7):
            await client.post("/v1/chat/completions", json={"messages": [], "model": DEMO_MODEL}, headers=headers)
            response = await client.post("/sessions/observations", headers=headers, json=observation(step, metrics))
        explanation = response.json()["observation"]["criteria"]["explanation"]
        # DM-50: without a registration there is no required count, so E5 is not chosen (it used to write
        # "1/(측정 안 됨) 에서"); the next template, E1-T1, names the role IDs.
        self.assertEqual(explanation["text"], "최근 3 step 동안 intake·refund·shipping 모두 채택 항목·새 쟁점이 없습니다. "
                                              "처리 상태 'triage'.")
        self.assertEqual(explanation["skipped_templates"], [{"template_id": "E5", "missing_required": ["required"]}])
        self.assertEqual((explanation["role_labels"], explanation["status_labels"]), (None, None))


if __name__ == "__main__":
    unittest.main()
