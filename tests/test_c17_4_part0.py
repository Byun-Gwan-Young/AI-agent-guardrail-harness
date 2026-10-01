"""C-17-4 part 0: particles after name slots (DM-36) and the demo proxy log directory (DM-34 for proxy logs)."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import httpx
import explain_v1
import proxy
from explain_v1 import PARTICLES, TEMPLATES, E6_DIALOGUE, UNMEASURED, Slot, explain
from proxy import create_app, log_dir_for
from test_criteria_v03 import CONFIG as V03_CONFIG, V02_KMU, configured, dialogue, replay, t1_registration

ROOT = Path(__file__).resolve().parents[1]
BLOCK_CONFIG = ROOT / "guardrail-deadlock-v0.3-kmu-block.yaml"
HANDOFF = {"roles": ["refund", "shipping"], "count": 4, "at_or_above_threshold": True}


def e4(**changes):
    return {"decision": "deadlock", "stop_step": 8, "task_kind": "dialogue", "consecutive_steps": 3,
            "consecutive_states": ["stagnant"] * 3, "streak_roles": ["refund", "shipping"], "handoff": HANDOFF,
            "handoff_threshold": 4, "status": "triage", **changes}


class ParticleTests(unittest.TestCase):
    """DM-36: the DM-31 final-consonant rule picks the particle after every role or status name slot."""

    def test_registered_names_with_a_final_consonant(self):
        text = explain(e4(), {"refund": "환불 담당", "shipping": "배송 담당"}, {"triage": "분류"})["text"]
        self.assertEqual(text, "환불 담당과 배송 담당이 문의를 서로 4 번 넘겼고 처리 상태는 '분류' 에서 바뀌지 않았습니다.")

    def test_names_without_a_final_consonant(self):
        text = explain(e4(), {"refund": "검토자", "shipping": "작성자"})["text"]
        self.assertTrue(text.startswith("검토자와 작성자가 문의를 서로 4 번 넘겼고"), text)

    def test_mixed_names_choose_per_name(self):
        self.assertTrue(explain(e4(), {"refund": "검토자", "shipping": "배송 담당"})["text"]
                        .startswith("검토자와 배송 담당이 "))
        self.assertTrue(explain(e4(), {"refund": "환불 담당", "shipping": "작성자"})["text"]
                        .startswith("환불 담당과 작성자가 "))

    def test_role_ids_without_registration_take_the_dm31_form(self):
        # An ID has no Hangul final consonant, as in DM-31's signal phrases.
        self.assertTrue(explain(e4())["text"].startswith("refund와 shipping가 문의를 서로 4 번"))

    def test_registered_session_sentence_from_the_stop_record(self):
        agents = ["refund", "shipping"] * 3
        inputs = [dialogue(s, agent=a, handoff=agents[s]) for s, a in enumerate(agents[:5], 1)]
        labelled = t1_registration(role_labels={"refund": "환불 담당", "shipping": "배송 담당", "planner": "기획",
                                                "developer": "개발", "reviewer": "검토", "intake": "접수"},
                                   status_labels={"received": "접수"})
        explanation = replay(inputs, configured(), labelled)[-1]["criteria"]["explanation"]
        self.assertEqual(explanation["template_id"], "E4")
        self.assertEqual(explanation["text"], "환불 담당과 배송 담당이 문의를 서로 5 번 넘겼고 처리 상태는 '접수' 에서 "
                                              "바뀌지 않았습니다.")
        # The record still rebuilds the same sentence.
        rebuilt = explain(explanation["signals"], explanation["role_labels"], explanation["status_labels"])
        self.assertEqual(rebuilt["text"], explanation["text"])
        # Values keep the names without particles.
        self.assertEqual((explanation["values"]["role_a"], explanation["values"]["role_b"]), ("환불 담당", "배송 담당"))
        # Without a T1 registration status_advance is unmeasured (no STOP), so the ID fallback is shown with a
        # registration that names no label for these two roles.
        unnamed = replay(inputs, configured(), t1_registration(role_labels={"intake": "접수"}))
        self.assertTrue(unnamed[-1]["criteria"]["explanation"]["text"].startswith("refund와 shipping가 "))

    def test_every_pair_and_the_unmeasured_value(self):
        cases = {("배송 담당", "과/와"): "배송 담당과", ("검토자", "과/와"): "검토자와", ("배송 담당", "이/가"): "배송 담당이",
                 ("검토자", "이/가"): "검토자가", ("배송 담당", "은/는"): "배송 담당은", ("검토자", "은/는"): "검토자는",
                 ("배송 담당", "을/를"): "배송 담당을", ("검토자", "을/를"): "검토자를", ("refund", "을/를"): "refund를",
                 ("12", "이/가"): "12가"}
        for (name, spec), expected in cases.items():
            with self.subTest(name=name, spec=spec):
                self.assertEqual(format(Slot(name), spec), expected)
                self.assertEqual(("{x:" + spec + "}").format_map({"x": Slot(name)}), expected)
        # DM-31 wrote "(측정 안 됨)" with no particle; the same here.
        self.assertEqual(format(Slot(UNMEASURED), "과/와"), UNMEASURED)
        self.assertEqual(explain(e4(handoff={"roles": None, "count": 4}))["text"],
                         f"{UNMEASURED} {UNMEASURED} 문의를 서로 4 번 넘겼고 처리 상태는 'triage' 에서 바뀌지 않았습니다.")
        self.assertEqual(format(Slot("배송 담당"), ""), "배송 담당")
        with self.assertRaises(ValueError):
            format(Slot("배송 담당"), "의/의")

    def test_templates_attach_every_particle_after_a_name_slot(self):
        """The slots followed by a 과/와, 이/가, 은/는 or 을/를 particle, listed: only E4's two role names carry a
        particle spec; E1/E1-T1 {signals} also uses it (DM-31). E2's "{path} 가" is a file path, not a name slot."""
        templates = {**TEMPLATES, "E6-dialogue": E6_DIALOGUE}
        specs = sorted((t, slot, spec) for t, text in templates.items()
                       for slot, spec in re.findall(r"\{(\w+):([^}]+)\}", text))
        self.assertEqual(specs, [("E1", "signals", "이/가"), ("E1-T1", "signals", "이/가"),
                                 ("E4", "role_a", "과/와"), ("E4", "role_b", "이/가")])
        self.assertTrue(all(spec in PARTICLES for _, _, spec in specs))
        loose = sorted((t, slot, particle) for t, text in templates.items()
                       for slot, particle in re.findall(r"\{(\w+)\} (과|와|이|가|은|는|을|를) ", text))
        self.assertEqual(loose, [("E2", "path", "가")])

    def test_signal_sentences_are_unchanged_by_the_particle_spec(self):
        # DM-31 sentences, as written by the previous render_subject.
        base = {"decision": "deadlock", "stop_step": 6, "consecutive_steps": 3, "streak_roles": ["planner"],
                "test_pass_count": 7, "test_total_count": 16}
        self.assertEqual(explain({**base, "selected_metrics": ["artifact.files_changed"]})["text"],
                         "최근 3 step 동안 planner 모두 산출물 변경이 없습니다. 통과 테스트 7/16.")
        self.assertEqual(explain({**base, "selected_metrics": ["conversation.new_info_ratio"]})["text"],
                         "최근 3 step 동안 planner 모두 새 정보가 없습니다. 통과 테스트 7/16.")
        self.assertEqual(explain({**base, "selected_metrics": []})["text"],
                         f"최근 3 step 동안 planner 모두 {UNMEASURED} 없습니다. 통과 테스트 7/16.")

    def test_frozen_record_lists_the_particles(self):
        from tools.write_criteria_snapshot import explanation_record
        self.assertEqual(explanation_record()["particles"], list(explain_v1.PARTICLES))


class DemoProxyLogTests(unittest.TestCase):
    """A deadlock-v0.3 (demo) proxy logs only under logs/demo/; any other proxy never logs there."""

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.demo_root = self.directory / "logs" / "demo"
        self.enterContext(mock.patch.object(proxy, "DEMO_LOG_ROOT", self.demo_root))
        environment = {k: v for k, v in os.environ.items() if k != "GUARDRAIL_LOG_DIR"}
        self.enterContext(mock.patch.dict(os.environ, environment, clear=True))

    def test_demo_condition_is_the_v03_criteria_version(self):
        self.assertTrue(proxy.demo_condition(proxy.load_config(V03_CONFIG)))
        self.assertTrue(proxy.demo_condition(proxy.load_config(BLOCK_CONFIG)))
        self.assertFalse(proxy.demo_condition(proxy.load_config(V02_KMU)))
        self.assertFalse(proxy.demo_condition(proxy.load_config(ROOT / "guardrail.yaml")))

    def test_defaults_and_allowed_directories(self):
        self.assertEqual(log_dir_for(True, None), self.demo_root)
        self.assertEqual(log_dir_for(True, str(self.demo_root / "cs")), self.demo_root / "cs")
        self.assertEqual(log_dir_for(False, None), Path("logs"))
        self.assertEqual(log_dir_for(False, str(self.directory / "other")), self.directory / "other")

    def test_both_directions_fail(self):
        with self.assertRaisesRegex(ValueError, "DM-34"):
            log_dir_for(True, str(self.directory / "logs"))
        with self.assertRaisesRegex(ValueError, "DM-34"):
            log_dir_for(True, str(self.directory / "elsewhere"))
        with self.assertRaisesRegex(ValueError, "reserved"):
            log_dir_for(False, str(self.demo_root / "x"))
        with self.assertRaisesRegex(ValueError, "reserved"):
            log_dir_for(False, str(self.demo_root))

    def test_started_proxy_checks_the_environment_before_serving(self):
        for config in (V03_CONFIG, BLOCK_CONFIG):
            with self.subTest(config=config.name):
                with mock.patch.dict(os.environ, {"GUARDRAIL_LOG_DIR": str(self.directory / "logs")}), \
                        self.assertRaisesRegex(ValueError, "DM-34"):
                    create_app(config_path=config)
                self.assertEqual(create_app(config_path=config).state.store.repository.directory, self.demo_root)
        with mock.patch.dict(os.environ, {"GUARDRAIL_LOG_DIR": str(self.demo_root)}), \
                self.assertRaisesRegex(ValueError, "reserved"):
            create_app(config_path=V02_KMU)
        with mock.patch.dict(os.environ, {"GUARDRAIL_LOG_DIR": str(self.directory / "logs")}):
            self.assertEqual(create_app(config_path=V02_KMU).state.store.repository.directory, self.directory / "logs")

    def test_demo_session_file_lands_under_logs_demo(self):
        import asyncio

        async def start():
            app = create_app(config_path=V03_CONFIG)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/sessions", headers={"X-Guardrail-Session": "demo-log"})
                self.assertEqual(response.status_code, 200)
        asyncio.run(start())
        self.assertTrue((self.demo_root / "demo-log.json").is_file())
        self.assertFalse((self.directory / "logs" / "demo-log.json").exists())


if __name__ == "__main__":
    unittest.main()
