"""C-18-3 part 0: the demo record rule (DM-64 ⑤). Which files of a demo session are committed, the record/ files made
from a session (no model text), the size limits, staging exactly the commit files, the index of this checkout, and the
raw-file backup outside the repository with its key scan. Offline (local git only)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import demo_records  # noqa: E402

MODEL_TEXT = "model-report-text-that-must-not-be-recorded"
C18_1 = ("DEMO-CL-normal-v1-c3a4c019c1ec48ca86b22d45340aea7b", "DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a",
         "DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1")


def observation(step, decision="continue", explanation=None):
    return {"step_id": step, "agent_id": "planner", "observed_at": "t", "judgement_ns": 1000 + step,
            "collection": {"final_output_status": "valid", "measurement_status": "measured", "metric_status": {}},
            "conversation": {"evidence": [MODEL_TEXT], "open_issue_ids": ["x"]},
            "extracted_conversation": {"evidence": [MODEL_TEXT]},
            "termination_context": {"evidence": [MODEL_TEXT]},
            "progress": {"version": "progress-v3", "state": "stagnant", "events": [], "flags": [], "pass_count": 3},
            "criteria": {"criteria_version": "deadlock-v0.3", "decision": decision, "explanation": explanation}}


def make_session(root, name="DEMO-X-normal-v1-0001", extra=None, log=True):
    folder = Path(root) / "runs" / "demo" / name
    (folder / "workspace").mkdir(parents=True)
    (folder / "observations").mkdir()
    stop = {"template_id": "E1", "text": "최근 3 step 동안 변화가 없습니다.", "values": {"n": 3}}
    session = {"session_id": name, "meta": {"criteria_version": "deadlock-v0.3", "criteria_sha256": "c",
                                            "criteria_freeze": {"sha256": "f"}, "guardrail_mode": "observe",
                                            "termination_reason": "max_steps"},
               "turns": [{"request_body": {"messages": [{"content": MODEL_TEXT}]}}],
               "observations": [observation(1), observation(2, "deadlock", stop)]}
    files = {"conditions.json": {"session_id": name}, "summary.json": {"steps": 2}, "scenario.yaml": "x: 1\n",
             "registered-tools.json": [], "prompt-trend.json": [], "session.json": session,
             "steps.json": [{"final": MODEL_TEXT}], "observations/1.ack.json": {}, "workspace/a.py": "print()\n",
             **(extra or {})}
    for relative, value in files.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        (folder / relative).write_text(text, encoding="utf-8")
    if log:
        logs = Path(root) / "logs" / "demo"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / (name + ".json")).write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    return folder


def fake_manifest(folder):
    return {"manifest_version": "session-manifest-v0.7", "session_id": folder.name, "condition": {"phase": "demo"}}


def fake_summary(folder):
    return {"session_id": folder.name, "key_scan": {"clean": True}}


class RecordFiles(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ))
        for env in demo_records.KEY_ENVS:
            os.environ.pop(env, None)

    def test_record_writes_the_three_record_files_without_model_text(self):
        folder = make_session(self.root)
        result = demo_records.record(folder, manifest=fake_manifest, summary=fake_summary)
        self.assertEqual(result["written"], ["record/manifest.json", "record/demo-summary.json", "record/judgements.json"])
        judgements = json.loads((folder / "record/judgements.json").read_text(encoding="utf-8"))
        self.assertEqual((judgements["first_stop_step"], judgements["stop_steps"]), (2, [2]))
        self.assertEqual(judgements["steps"][1]["criteria"]["explanation"]["text"], "최근 3 step 동안 변화가 없습니다.")
        self.assertEqual([s["judgement_ns"] for s in judgements["steps"]], [1001, 1002])
        for name in ("judgements.json", "manifest.json", "demo-summary.json"):
            self.assertNotIn(MODEL_TEXT, (folder / "record" / name).read_text(encoding="utf-8"))

    def test_a_key_in_the_folder_writes_nothing(self):
        folder = make_session(self.root, extra={"steps.json": '"Bearer abcdefghijklmnop"'})
        with self.assertRaisesRegex(ValueError, "key scan found .*steps.json"):
            demo_records.record(folder, manifest=fake_manifest, summary=fake_summary)
        self.assertFalse((folder / "record").exists())

    def test_the_key_value_set_here_is_scanned(self):
        os.environ["TAVILY_API_KEY"] = "plain-value-0123456789"
        folder = make_session(self.root, extra={"search.txt": "plain-value-0123456789"})
        with self.assertRaisesRegex(ValueError, "key scan"):
            demo_records.record(folder, manifest=fake_manifest, summary=fake_summary)

    def test_a_manifest_that_is_not_demo_is_refused(self):
        folder = make_session(self.root)
        with self.assertRaisesRegex(ValueError, "phase is not demo"):
            demo_records.record(folder, manifest=lambda f: {"condition": {"phase": "measure"}}, summary=fake_summary)

    def test_size_limits_and_required_files(self):
        folder = make_session(self.root)
        self.assertEqual(demo_records.check_session(folder)["problems"],
                         [f"{folder.name}/record/{n}: missing" for n in ("manifest.json", "demo-summary.json",
                                                                         "judgements.json")])
        demo_records.record(folder, manifest=fake_manifest, summary=fake_summary)
        self.assertEqual(demo_records.check_session(folder)["problems"], [])
        (folder / "summary.json").write_text("x" * (demo_records.MAX_FILE_BYTES + 1))
        self.assertEqual(demo_records.check_session(folder)["problems"],
                         [f"{folder.name}/summary.json: {demo_records.MAX_FILE_BYTES + 1} bytes > "
                          f"{demo_records.MAX_FILE_BYTES}"])
        with mock.patch.object(demo_records, "MAX_SESSION_BYTES", 100):
            self.assertTrue(demo_records.check_session(folder)["problems"][-1].endswith("bytes > 100"))

    def test_the_rule_lists_no_raw_file(self):
        for raw in ("session.json", "steps.json", "tool-dispatch.json"):
            self.assertNotIn(raw, demo_records.COMMIT_FILES)
        self.assertFalse(any(name.startswith(("workspace/", "search/", "observations/"))
                             for name in demo_records.COMMIT_FILES))


class Staging(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ))
        for env in demo_records.KEY_ENVS:
            os.environ.pop(env, None)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / ".gitignore").write_text("runs/\nlogs/\n")

    def tracked(self):
        return sorted(demo_records.git("ls-files", root=self.root).split())

    def test_stage_adds_exactly_the_commit_files_of_an_ignored_folder(self):
        folder = make_session(self.root)
        demo_records.record(folder, manifest=fake_manifest, summary=fake_summary)
        demo_records.stage([folder], root=self.root)
        prefix = "runs/demo/" + folder.name + "/"
        self.assertEqual(self.tracked(), sorted(prefix + n for n in demo_records.COMMIT_FILES))
        self.assertTrue(demo_records.check_index(self.root)["ok"])

    def test_stage_refuses_a_session_without_its_record(self):
        folder = make_session(self.root)
        with self.assertRaisesRegex(ValueError, "not staged: .*record/manifest.json: missing"):
            demo_records.stage([folder], root=self.root)
        self.assertEqual(self.tracked(), [])

    def test_check_index_names_raw_files_and_proxy_logs(self):
        folder = make_session(self.root)
        demo_records.git("add", "-f", "runs/demo/" + folder.name + "/session.json",
                         "logs/demo/" + folder.name + ".json", root=self.root)
        problems = demo_records.check_index(self.root)["problems"]
        self.assertEqual(problems, [f"logs/demo/{folder.name}.json: proxy logs stay local (backup)",
                                    f"runs/demo/{folder.name}/session.json: not a commit file of demo-records-v1"])


class Backup(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.outside = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ))
        for env in demo_records.KEY_ENVS:
            os.environ.pop(env, None)

    def backup(self, folders, output):
        return demo_records.backup(folders, output, logs_root=self.root / "logs" / "demo", root=self.root)

    def test_one_archive_with_folders_proxy_logs_and_their_hashes(self):
        a, b = make_session(self.root, "DEMO-X-normal-v1-0001"), make_session(self.root, "DEMO-X-stall-v1-0002", log=False)
        result = self.backup([a, b], self.outside / "demo-raw.tar.gz")
        self.assertEqual((result["sessions"], result["proxy_logs_missing"]), ([a.name, b.name], [b.name]))
        with tarfile.open(result["output"]) as archive:
            names = archive.getnames()
            listing = json.load(archive.extractfile("backup-files.json"))
        self.assertIn(f"runs/demo/{a.name}/session.json", names)
        self.assertIn(f"runs/demo/{a.name}/workspace/a.py", names)
        self.assertIn(f"logs/demo/{a.name}.json", names)
        self.assertNotIn(f"logs/demo/{b.name}.json", names)
        self.assertEqual(sorted(f["path"] for f in listing["files"]), sorted(n for n in names if n != "backup-files.json"))
        self.assertTrue(listing["key_scan"]["clean"])

    def test_inside_the_repository_or_over_an_existing_file_is_refused(self):
        folder = make_session(self.root)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            self.backup([folder], self.root / "backup.tar.gz")
        existing = self.outside / "old.tar.gz"
        existing.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            self.backup([folder], existing)

    def test_a_key_in_a_raw_file_writes_no_backup(self):
        folder = make_session(self.root, extra={"workspace/b.txt": "gsk_abcdefghijklmnop"})
        output = self.outside / "demo-raw.tar.gz"
        with self.assertRaisesRegex(ValueError, "key scan found"):
            self.backup([folder], output)
        self.assertFalse(output.exists())


class ThisCheckout(unittest.TestCase):
    def test_the_index_keeps_the_rule(self):
        result = demo_records.check_index()
        self.assertEqual(result["problems"], [])
        tracked = demo_records.git("ls-files", "--", "logs/demo").split()
        self.assertEqual(tracked, [])

    def test_raw_demo_files_are_ignored(self):
        for path in ("runs/demo/X/session.json", "runs/demo/X/workspace/a.py", "logs/demo/X.json"):
            subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, check=True)

    def test_the_c18_1_trial_sessions_keep_their_records(self):
        tracked = set(demo_records.git("ls-files", "--", "runs/demo").split())
        for session in C18_1:
            for name in demo_records.REQUIRED_FILES:
                self.assertIn(f"runs/demo/{session}/{name}", tracked)
        stall = json.loads(demo_records.git("show", f":runs/demo/{C18_1[2]}/record/judgements.json"))
        stop = stall["steps"][stall["stop_steps"][0] - 1]["criteria"]["explanation"]
        self.assertEqual((stall["first_stop_step"], stop["template_id"]), (15, "E6"))
        self.assertEqual(stop["text"], "step 12에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 통과 테스트 14/15.")


if __name__ == "__main__":
    unittest.main()
