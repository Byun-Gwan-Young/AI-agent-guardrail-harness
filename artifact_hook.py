"""Runner-side observation helpers. No commands or network calls run implicitly."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from conversation_extract import extract_conversation
from progress_schema import Artifact, Conversation, Observation


def capture_artifact(workspace, monitored_paths, *, junit_path=None, test_suite_id=None,
                     build_status=None):
    root = Path(workspace).resolve(strict=True)
    paths = sorted(set(monitored_paths))
    reasons, hashes = {}, {}
    # Fixed explicit file scope; missing files are absent, so create/delete/revert can be compared.
    for relative in paths:
        candidate = Path(relative)
        target = (root / candidate).resolve()
        if candidate.is_absolute() or ".." in candidate.parts or not target.is_relative_to(root):
            raise ValueError("Monitored path must stay within the approved workspace")
        key = candidate.as_posix()
        try:
            import stat
            mode = target.stat().st_mode
            if stat.S_ISREG(mode):
                hashes[key] = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                raise ValueError("Monitored paths must be files, not directories")
        except FileNotFoundError:
            pass
        except OSError:
            reasons["file_hashes"] = "file read failed; snapshot incomplete"
    scope = hashlib.sha256(json.dumps({"root": str(root), "paths": paths}, ensure_ascii=False).encode()).hexdigest()
    passed = total = None
    if junit_path is not None:
        if not test_suite_id:
            raise ValueError("Pass a suite identity derived from fixed test definitions/configuration")
        report = (root / junit_path).resolve()
        if not report.is_relative_to(root):
            raise ValueError("Test report must stay within the workspace")
        try:
            tree = ET.parse(report)
            cases = list(tree.iter("testcase"))
            if not cases:
                raise ValueError("No test cases in report")
            total = len(cases)
            passed = sum(not any(c.find(tag) is not None for tag in ("failure", "error", "skipped"))
                         for c in cases)
        except (OSError, ET.ParseError, ValueError):
            reasons["test_pass_count"] = "test report missing, invalid or contains no test cases"
    else:
        reasons["test_pass_count"] = "tests not observed"
    if build_status in (None, "not_run"):
        reasons["build_status"] = "build not observed"
    return Artifact(file_hashes=None if "file_hashes" in reasons else hashes,
                    files_scope_id=scope, test_pass_count=passed, test_total_count=total,
                    test_suite_id=test_suite_id, build_status=build_status, reasons=reasons).model_dump()


def make_observation(*, step_id, llm_turns, text, progress_source, progress_metric,
                     artifact=None, structured=None, previous_extracted=None, termination_context=None,
                     agent_id=None, collection=None):
    extracted = extract_conversation(text, previous_extracted)
    # Only text is passed to B, independently of A's reference record.
    primary = (Conversation(source_kind="structured", **structured).model_dump()
               if structured is not None else extracted)
    return Observation(step_id=step_id, collection=collection, agent_id=agent_id, llm_turns=llm_turns, progress_source=progress_source,
                       progress_metric=progress_metric, conversation=primary, artifact=artifact,
                       extracted_conversation=extracted if structured is not None else None,
                       termination_context=termination_context).model_dump()


async def submit_observation(client, session_id, observation):
    """Explicit caller-owned local proxy client; propagate failure for runner retry/reporting."""
    response = await client.post("/sessions/observations", json=observation,
                                 headers={"X-Guardrail-Session": session_id})
    response.raise_for_status()
    return response.json()
