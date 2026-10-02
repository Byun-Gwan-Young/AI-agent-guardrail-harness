"""C-17-6 part 0: the C-17-5 decisions DM-49 (a particle or '입니다' after a number is attached; a particle that follows
a final consonant is chosen by the number read aloud) and DM-50 (required values choose a template, missing auxiliary
values drop their phrase, "(측정 안 됨)" only in the fallback E1)."""
from itertools import combinations
import re
import string
import unittest

import explain_v1
from explain_v1 import (E6_DIALOGUE, FALLBACK, REDUCED, REQUIRED_VALUES, SELECTION_ORDER, TEMPLATES, UNMEASURED, Slot,
                        explain, has_final_consonant)

T1_METRICS = ["conversation.status_advance", "conversation.adopted_items", "conversation.new_issue_ids"]
A1_METRICS = ["conversation.open_issues_count", "artifact.test_pass_count", "artifact.files_changed"]


def fields(template):
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def signals(**changes):
    base = {"decision": "deadlock", "stop_step": 9, "task_kind": "artifact", "consecutive_steps": 3,
            "consecutive_states": ["stagnant"] * 3, "streak_roles": ["planner", "developer", "reviewer"],
            "declared_step": None, "test_pass_count": 12, "test_total_count": 16, "global_revert": None,
            "test_plateau_in_streak": False, "test_max_step": 3, "steps_since_test_max": 6,
            "file_state_changes_since_test_max": 2, "handoff": None, "handoff_threshold": 4, "status": None,
            "adopted_metric_selected": False, "adopted_count": None, "adopted_required": None,
            "test_observed_in_session": True, "selected_metrics": A1_METRICS}
    return {**base, **changes}


# Signals that make each template's condition hold with every value of it present.
FORCED = {
    "E6": dict(decision="termination_failure", declared_step=4),
    "E6-dialogue": dict(decision="termination_failure", declared_step=4, task_kind="dialogue", status="triage"),
    "E2": dict(global_revert={"step": 9, "paths": ["src/x.py"], "revert_to_step": 1}),
    "E3": dict(test_plateau_in_streak=True),
    "E4": dict(task_kind="dialogue", status="received", handoff={"roles": ["refund", "shipping"], "count": 4}),
    "E5": dict(task_kind="dialogue", status="triage", adopted_metric_selected=True, adopted_count=1,
               adopted_required=3),
    "E7": dict(consecutive_states=["stagnant", "oscillating", "stagnant"]),
    "E1-T1": dict(task_kind="dialogue", status="received", test_observed_in_session=False, test_pass_count=None,
                  test_total_count=None, selected_metrics=T1_METRICS),
    "E1": {},
}


def without(case, name, base):
    """The signals of base with the value `name` of a template made unmeasured."""
    s = dict(base)
    if name in ("path", "k"):
        s["global_revert"] = {**s["global_revert"], {"path": "paths", "k": "revert_to_step"}[name]: None}
    elif name in ("role_a", "role_b"):
        roles = list(s["handoff"]["roles"])
        roles[0 if name == "role_a" else 1] = None
        s["handoff"] = {**s["handoff"], "roles": roles}
    elif name == "h":
        s["handoff"] = {**s["handoff"], "count": None}
    elif name == "roles":
        s["streak_roles"] = []
    elif name == "signals":
        s["selected_metrics"] = []
    elif name == "o":
        s["consecutive_states"] = None
    else:
        s[{"n": "consecutive_steps", "pass": "test_pass_count", "total": "test_total_count", "status": "status",
           "m": "steps_since_test_max", "a": "test_max_step", "c": "file_state_changes_since_test_max",
           "adopted": "adopted_count", "required": "adopted_required", "d": "declared_step"}[name]] = None
    return s


def condition_only(s):
    """The pre-DM-50 choice: the first template whose condition holds, values not looked at."""
    return next(t for t, name in SELECTION_ORDER if explain_v1.condition_holds(name, s))


class NumberParticleTests(unittest.TestCase):
    """DM-49."""

    def test_the_sentences_of_the_instruction(self):
        e2 = explain(signals(**FORCED["E2"]))
        self.assertEqual(e2["text"], "src/x.py 파일이 step 1의 내용으로 되돌아갔고, 통과 테스트는 6 step 동안 12/16입니다.")
        self.assertIn("step 1의 내용으로", e2["text"])
        self.assertIn("12/16입니다", e2["text"])
        self.assertEqual(explain(signals(**FORCED["E3"]))["text"],
                         "step 3 이후 6 step 동안 파일이 2 번 바뀌었지만 통과 테스트는 12/16에서 늘지 않았습니다.")
        self.assertEqual(explain(signals(**FORCED["E5"]))["text"],
                         "최근 3 step 동안 채택 항목이 1/3에서 늘지 않았고 처리 상태는 'triage'입니다.")
        self.assertEqual(explain(signals(**FORCED["E6"]))["text"],
                         "step 4에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 통과 테스트 12/16.")

    def test_no_space_between_a_slot_and_a_particle_and_units_keep_theirs(self):
        sentences = {**TEMPLATES, "E6-dialogue": E6_DIALOGUE, **{"reduced-" + k: v for k, v in REDUCED.items()}}
        particle = r"(의|에서|에|입니다|이|가|은|는|을|를|과|와)(?=[ .,]|$)"
        for name, text in sentences.items():
            with self.subTest(sentence=name):
                self.assertIsNone(re.search(r"\} " + particle, text))
                self.assertIsNone(re.search(r"\}/\{\w+\} " + particle, text))
        # Units after a number keep their space (DM-42, DM-49): "{n} step", "{h} 번", "{c} 번".
        self.assertIn("{n} step 동안", TEMPLATES["E1"])
        self.assertIn("{h} 번 넘겼고", TEMPLATES["E4"])
        self.assertIn("{c} 번 바뀌었지만", TEMPLATES["E3"])

    def test_a_number_read_aloud_chooses_the_particle(self):
        # 영 일 이 삼 사 오 육 칠 팔 구
        self.assertEqual([d for d in "0123456789" if has_final_consonant(d)], list("013678"))
        cases = {("12/16", "이/가"): "12/16이", ("2", "이/가"): "2가", ("10", "과/와"): "10과",
                 ("5", "은/는"): "5는", ("3", "을/를"): "3을", ("agent1", "과/와"): "agent1과",
                 ("agent2", "이/가"): "agent2가"}
        for (value, pair), text in cases.items():
            with self.subTest(value=value, pair=pair):
                self.assertEqual(format(Slot(value), pair), text)
        # Hangul names and IDs keep the DM-31 rule.
        self.assertEqual(format(Slot("환불 담당"), "과/와"), "환불 담당과")
        self.assertEqual(format(Slot("refund"), "과/와"), "refund와")

    def test_a_role_id_ending_in_a_digit_in_e4(self):
        chosen = explain(signals(task_kind="dialogue", status="received",
                                 handoff={"roles": ["agent1", "agent2"], "count": 4}))
        self.assertEqual(chosen["text"], "agent1과 agent2가 문의를 서로 4 번 넘겼고 처리 상태는 'received'에서 바뀌지 않았습니다.")

    def test_only_name_and_signal_slots_take_a_variable_particle(self):
        # No template puts a final-consonant-dependent particle after a number slot today; the digit rule covers
        # the name slots (role IDs) and any later template.
        specs = {(f, s) for t in list(TEMPLATES.values()) + list(REDUCED.values()) + [E6_DIALOGUE]
                 for _, f, s, _ in string.Formatter().parse(t) if s}
        self.assertEqual(specs, {("signals", "이/가"), ("role_a", "과/와"), ("role_b", "이/가")})


class RequiredAuxiliaryTests(unittest.TestCase):
    """DM-50."""

    def test_table_shape(self):
        self.assertEqual(set(REQUIRED_VALUES), set(TEMPLATES))
        self.assertEqual(REQUIRED_VALUES[FALLBACK], ())
        for template_id, template in TEMPLATES.items():
            with self.subTest(template=template_id):
                slots = fields(template) | (fields(E6_DIALOGUE) if template_id == "E6" else set())
                self.assertLessEqual(set(REQUIRED_VALUES[template_id]), slots)
                auxiliary = slots - set(REQUIRED_VALUES[template_id])
                if template_id == FALLBACK or not auxiliary:
                    self.assertNotIn(template_id, REDUCED)
                else:
                    # The reduced sentence writes exactly the required values.
                    self.assertEqual(fields(REDUCED[template_id]), set(REQUIRED_VALUES[template_id]))
        self.assertEqual(set(REDUCED), {"E1-T1", "E2", "E3", "E4", "E5", "E6"})

    def test_every_template_full_with_all_values(self):
        for name, forced in FORCED.items():
            with self.subTest(template=name):
                chosen = explain(signals(**forced))
                self.assertEqual(chosen["template_id"], name.removesuffix("-dialogue"))
                self.assertEqual(chosen["form"], "fallback" if name == "E1" else "full")
                self.assertEqual((chosen["missing_values"], chosen["skipped_templates"]), ([], []))
                self.assertNotIn(UNMEASURED, chosen["text"])

    def test_no_unmeasured_outside_e1_whatever_is_missing(self):
        """Every subset of every template's values made unmeasured: "(측정 안 됨)" appears only in E1."""
        checked = 0
        for name, forced in FORCED.items():
            base = signals(**forced)
            template_id = name.removesuffix("-dialogue")
            names = sorted(explain(base)["values"])
            for size in range(len(names) + 1):
                for gone in combinations(names, size):
                    s = base
                    for value in gone:
                        s = without(name, value, s)
                    chosen = explain(s)
                    checked += 1
                    with self.subTest(template=name, missing=gone):
                        if chosen["template_id"] != FALLBACK:
                            self.assertNotIn(UNMEASURED, chosen["text"])
                            self.assertFalse(set(chosen["missing_values"]) & set(REQUIRED_VALUES[chosen["template_id"]]))
                        if chosen["template_id"] == template_id and template_id != FALLBACK:
                            self.assertEqual(chosen["form"], "reduced" if gone else "full")
                        # Rebuilt from the record, as the STOP record promises.
                        self.assertEqual(explain(chosen["signals"], chosen["role_labels"], chosen["status_labels"]),
                                         chosen)
        self.assertGreater(checked, 100)

    def test_missing_auxiliary_values_drop_the_phrase(self):
        cases = {
            "E1-T1": (dict(status=None), "최근 3 step 동안 planner·developer·reviewer 모두 처리 상태 변화·채택 항목·새 쟁점이 없습니다."),
            "E2": (dict(test_pass_count=None), "src/x.py 파일이 step 1의 내용으로 되돌아갔습니다."),
            "E3": (dict(test_total_count=None), "step 3 이후 6 step 동안 파일이 2 번 바뀌었지만 통과 테스트는 늘지 않았습니다."),
            "E4": (dict(status=None), "refund와 shipping가 문의를 서로 4 번 넘겼습니다."),
            "E5": (dict(status=None), "최근 3 step 동안 채택 항목이 1/3에서 늘지 않았습니다."),
            "E6": (dict(test_pass_count=None), "step 4에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다."),
            "E6-dialogue": (dict(status=None), "step 4에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다."),
        }
        for name, (gone, text) in cases.items():
            with self.subTest(template=name):
                chosen = explain(signals(**{**FORCED[name], **gone}))
                self.assertEqual((chosen["template_id"], chosen["form"], chosen["text"]),
                                 (name.removesuffix("-dialogue"), "reduced", text))
                self.assertTrue(chosen["missing_values"])

    def test_a_missing_required_value_moves_on_and_is_recorded(self):
        chosen = explain(signals(**{**FORCED["E5"], "adopted_required": None}))
        # Next whose condition holds: E1-T1 does not hold (tests observed), so the fallback E1.
        self.assertEqual((chosen["template_id"], chosen["skipped_templates"]),
                         ("E1", [{"template_id": "E5", "missing_required": ["required"]}]))
        chosen = explain(signals(**{**FORCED["E1-T1"], **FORCED["E5"], "test_pass_count": None,
                                    "test_total_count": None, "adopted_required": None}))
        self.assertEqual((chosen["template_id"], chosen["form"]), ("E1-T1", "full"))
        chosen = explain(signals(**{**FORCED["E6"], **FORCED["E2"], "declared_step": None}))
        self.assertEqual((chosen["template_id"], chosen["skipped_templates"]),
                         ("E2", [{"template_id": "E6", "missing_required": ["d"]}]))

    def test_e1_still_writes_unmeasured(self):
        chosen = explain(signals(test_pass_count=None, test_total_count=None, streak_roles=[]))
        self.assertEqual((chosen["template_id"], chosen["form"]), ("E1", "fallback"))
        self.assertEqual(chosen["text"], f"최근 3 step 동안 {UNMEASURED} 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. "
                                         f"통과 테스트 {UNMEASURED}/{UNMEASURED}.")

    def test_selection_changes_are_exactly_missing_required_values(self):
        """The pre-DM-50 choice (condition only) and the DM-50 choice differ only when the condition-only template
        misses a required value; the list of such changes is reported (C-17-6 part 0)."""
        changes = set()
        for name, forced in FORCED.items():
            base = signals(**forced)
            for value in sorted(explain(base)["values"]):
                s = without(name, value, base)
                before, chosen = condition_only(s), explain(s)
                if before != chosen["template_id"]:
                    self.assertEqual(chosen["skipped_templates"][0]["template_id"], before)
                    changes.add((before, value, chosen["template_id"]))
        self.assertEqual(changes, {("E6", "d", "E1"), ("E6", "n", "E1"), ("E2", "path", "E1"), ("E2", "k", "E1"),
                                   ("E3", "a", "E1"), ("E3", "m", "E1"), ("E3", "c", "E1"), ("E5", "n", "E1"),
                                   ("E5", "adopted", "E1"), ("E5", "required", "E1"), ("E7", "n", "E1"),
                                   ("E1-T1", "n", "E1"), ("E1-T1", "roles", "E1"), ("E1-T1", "signals", "E1")})

    def test_frozen_record_carries_the_tables(self):
        from tools.write_criteria_snapshot import explanation_record
        record = explanation_record()
        self.assertEqual(record["required_values"], {k: list(v) for k, v in REQUIRED_VALUES.items()})
        self.assertEqual((record["reduced_templates"], record["fallback"], record["digits_with_final_consonant"]),
                         (REDUCED, FALLBACK, "013678"))


if __name__ == "__main__":
    unittest.main()
