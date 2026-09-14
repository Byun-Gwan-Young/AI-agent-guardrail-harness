"""Pure deterministic movement classification. Not a deadlock/success detector."""
import unicodedata

VERSION = "progress-v1"


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def calculate_progress(history, current):
    previous = history[-1] if history else None
    events, metrics, missing = [], {}, []
    flags = {"oscillation": [], "reopen": [], "revert": [], "test_plateau": False}

    def metric(name, value=None, reason=None):
        metrics[name] = {"value": value, "status": "unmeasured" if reason else "measured"}
        if reason:
            metrics[name]["reason"] = reason
            missing.append(name)

    def event(name, item, kind="new"):
        events.append({"metric": name, "item": item, "kind": kind})
        if kind in flags:
            flags[kind].append(item)

    if previous and (previous["progress_source"] != current["progress_source"]
                     or previous["progress_metric"] != current["progress_metric"]):
        return {"version": VERSION, "state": "unmeasured", "reason": "metric selection changed",
                "metrics": {}, "events": [], "flags": flags, "coverage_complete": False}

    conv = current.get("conversation") or {}
    prev_conv = (previous or {}).get("conversation") or {}
    same_kind = conv.get("source_kind") == prev_conv.get("source_kind")
    conv_history = [(h.get("conversation") or {}) for h in history
                    if (h.get("conversation") or {}).get("source_kind") == conv.get("source_kind")]
    if current["progress_source"] in ("conversation", "both"):
        for name in current["progress_metric"]["conversation"]:
            full = "conversation." + name
            field = {"proposal_value_delta": "proposal_values", "open_issues_count": "open_issue_ids",
                     "new_info_ratio": "info_items"}[name]
            now, before = conv.get(field), prev_conv.get(field)
            if now is None or before is None or not same_kind:
                metric(full, reason="missing observation/baseline or source_kind changed")
                continue
            if name == "proposal_value_delta":
                # Keys include units, e.g. timeout_ms; retain signed deltas, no invented scale.
                deltas = {}
                for key in sorted(set(now) | set(before)):
                    if key not in now:
                        # Removal is not evidence of proposal movement: it may be extraction omission.
                        continue
                    if key not in before or now[key] != before[key]:
                        seen = [h[field][key] for h in conv_history
                                if h.get(field) is not None and key in h[field]]
                        event(full, key, "oscillation" if now[key] in seen else "new")
                    deltas[key] = now[key] - before[key] if key in before else None
                if set(now) != set(before):
                    metric(full, deltas, "proposal key coverage changed")
                else:
                    metric(full, deltas)
            elif name == "open_issues_count":
                now, before = set(now), set(before)
                historical_ids = set().union(*(set(h[field]) for h in conv_history if h.get(field) is not None))
                for key in sorted(now - before):
                    event(full, key, "reopen" if key in historical_ids else "new")
                for key in sorted(before - now):
                    event(full, key, "closed")
                metric(full, {"count": len(now), "delta": len(now) - len(before)})
            else:
                items = {normalized(v) for v in now if normalized(v)}
                seen = {normalized(v) for h in conv_history for v in (h.get(field) or [])}
                novel = items - seen
                for item in sorted(novel):
                    event(full, item)
                metric(full, len(novel) / len(items) if items else 0.0)

    artifact = current.get("artifact") or {}
    old_artifact = (previous or {}).get("artifact") or {}
    if current["progress_source"] in ("artifact", "both"):
        for name in current["progress_metric"]["artifact"]:
            full = "artifact." + name
            if name == "files_changed":
                now, before = artifact.get("file_hashes"), old_artifact.get("file_hashes")
                scope = artifact.get("files_scope_id")
                if now is None or before is None or scope != old_artifact.get("files_scope_id"):
                    metric(full, reason="missing file snapshot/baseline or scope changed")
                    continue
                changed = [p for p in sorted(set(now) | set(before)) if now.get(p) != before.get(p)]
                for path in changed:
                    seen = [(h.get("artifact") or {})["file_hashes"].get(path) for h in history
                            if (h.get("artifact") or {}).get("file_hashes") is not None
                            and (h.get("artifact") or {}).get("files_scope_id") == scope]
                    event(full, path, "revert" if now.get(path) in seen else "new")
                metric(full, changed)
                if changed and comparable_tests(artifact, old_artifact):
                    flags["test_plateau"] = artifact["test_pass_count"] <= old_artifact["test_pass_count"]
            elif name == "test_pass_count":
                if not comparable_tests(artifact, old_artifact):
                    metric(full, reason="test results missing or suite/total changed")
                    continue
                delta = artifact[name] - old_artifact[name]
                if delta:
                    event(full, "tests", "improved" if delta > 0 else "regressed")
                metric(full, delta)
            else:
                now, before = artifact.get(name), old_artifact.get(name)
                if now not in ("passed", "failed") or before not in ("passed", "failed"):
                    metric(full, reason="build not observed or no baseline")
                    continue
                if now != before:
                    event(full, "build", "improved" if now == "passed" else "regressed")
                metric(full, {"before": before, "after": now})

    if not history:
        baseline_values = []
        if current["progress_source"] in ("conversation", "both"):
            fields = {"proposal_value_delta": "proposal_values", "open_issues_count": "open_issue_ids",
                      "new_info_ratio": "info_items"}
            baseline_values.extend(conv.get(fields[m]) for m in current["progress_metric"]["conversation"])
        if current["progress_source"] in ("artifact", "both"):
            baseline_values.extend(artifact.get("file_hashes" if m == "files_changed" else m)
                                   for m in current["progress_metric"]["artifact"])
        state = "baseline" if any(v is not None and v != "not_run" for v in baseline_values) else "unmeasured"
    elif events:
        # Unknown selected metrics could conceal new movement: don't assert 'all' are recurrent.
        all_recurrent = all(e["kind"] in ("oscillation", "reopen", "revert") for e in events)
        state = ("unmeasured" if missing else "oscillating") if all_recurrent else "progress"
    else:
        state = "unmeasured" if missing else "stagnant"
    return {"version": VERSION, "state": state, "metrics": metrics, "events": events,
            "flags": flags, "coverage_complete": not missing,
            "conversation_moved": any(e["metric"].startswith("conversation.") for e in events),
            "artifact_moved": any(e["metric"].startswith("artifact.") for e in events)}


def comparable_tests(a, b):
    return (a.get("test_pass_count") is not None and b.get("test_pass_count") is not None
            and a.get("test_suite_id") is not None and a.get("test_suite_id") == b.get("test_suite_id")
            and a.get("test_total_count") == b.get("test_total_count"))
