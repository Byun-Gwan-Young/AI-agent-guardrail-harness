"""Explicit experiment conditions, never inferred from provider defaults."""
import hashlib
import os
from pathlib import Path
import re

import yaml

# The upstream provider is part of the experiment condition, so it is configured, never guessed.
DEFAULT_UPSTREAM = {"base_url": "https://api.groq.com/openai/v1",
                    "chat_path": "/chat/completions",
                    "api_key_env": "GROQ_API_KEY"}
# DM-7: block exists for the demo only. Without the key a configuration is observe, as every earlier one was.
GUARDRAIL_MODES = ("observe", "block")
PHASE_HEADER = "X-Guardrail-Phase"


def config_file(path=None):
    return Path(path or os.environ.get("GUARDRAIL_CONFIG", Path(__file__).with_name("guardrail.yaml")))


def upstream(config):
    """Validated upstream settings. Only the key's variable name is configured, never its value."""
    data = config.get("upstream") or {}
    if not isinstance(data, dict) or set(data) - set(DEFAULT_UPSTREAM):
        raise ValueError("upstream accepts only " + ", ".join(sorted(DEFAULT_UPSTREAM)))
    settings = {**DEFAULT_UPSTREAM, **data}
    if not str(settings["base_url"]).startswith("https://") or any(
            c in str(settings["base_url"]) for c in "?#") or str(settings["base_url"]).endswith("/"):
        raise ValueError("upstream.base_url must be an https origin with a path and no trailing slash")
    if not str(settings["chat_path"]).startswith("/"):
        raise ValueError("upstream.chat_path must start with /")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(settings["api_key_env"])):
        raise ValueError("upstream.api_key_env must be an environment variable name")
    return settings


def guardrail_mode(config):
    mode = config.get("guardrail_mode", "observe")
    if mode not in GUARDRAIL_MODES:
        raise ValueError("guardrail_mode must be one of " + ", ".join(GUARDRAIL_MODES))
    return mode


RUN_CONDITIONS_VERSION = "demo-run-conditions-v1"
RUN_CONDITION_FIELDS = {"conditions_version", "model", "reasoning_effort", "reasoning_effort_evidence"}
REASONING_EFFORTS = ("low", "medium", "high")
ROOT = Path(__file__).resolve().parent


def model_id(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(name + " must name a model ID without surrounding spaces")
    return value


def run_conditions_path(value, root=ROOT):
    """A repository-relative POSIX path to a run-conditions file (DM-57)."""
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or ".." in value.split("/"):
        raise ValueError("run_conditions must be a relative path inside the repository")
    return root / value


def load_run_conditions(value, root=ROOT):
    """DM-57: the one place that sets the demo model and reasoning effort, read by the runner (scenario-v2
    run_conditions) and by the demo proxies (their pinned model). Returns the values with the file's path and sha256."""
    path = run_conditions_path(value, root)
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != RUN_CONDITION_FIELDS:
        raise ValueError("run conditions need exactly " + ", ".join(sorted(RUN_CONDITION_FIELDS)))
    if data["conditions_version"] != RUN_CONDITIONS_VERSION:
        raise ValueError("Unsupported run conditions version")
    model_id(data["model"], "run conditions model")
    if data["reasoning_effort"] not in REASONING_EFFORTS:
        raise ValueError("run conditions reasoning_effort must be one of " + ", ".join(REASONING_EFFORTS))
    evidence = data["reasoning_effort_evidence"]
    if evidence is not None and not isinstance(evidence, str):
        raise ValueError("reasoning_effort_evidence must be a path or null")
    return {"file": value, "sha256": hashlib.sha256(raw).hexdigest(), **data}


def pinned_model(config, root=ROOT):
    """S-12 (one proxy = one condition group): the one model this proxy forwards, set when it starts, never in code.
    pinned_model names it; run_conditions takes it from a run-conditions file (the demo proxies, DM-57). None for an
    unpinned configuration (the Groq-era ones and the byte-protected v0.2 gateway one); a deadlock-v0.3 (demo)
    configuration must be pinned."""
    if "pinned_model" in config and "run_conditions" in config:
        raise ValueError("Give pinned_model or run_conditions, not both")
    if "pinned_model" in config:
        return {"name": model_id(config["pinned_model"], "pinned_model"), "source": "pinned_model"}
    if "run_conditions" in config:
        conditions = load_run_conditions(config["run_conditions"], root)
        return {"name": conditions["model"], "source": "run_conditions", "run_conditions": conditions["file"],
                "run_conditions_sha256": conditions["sha256"]}
    if config.get("criteria_version") == "deadlock-v0.3":
        raise ValueError("A deadlock-v0.3 (demo) proxy needs pinned_model or run_conditions (S-12)")
    return None


def load_config(path=None):
    path = config_file(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    truncate = data.get("log", {}).get("truncate")
    if truncate is not None and (type(truncate) is not int or truncate < 0):
        raise ValueError("log.truncate must be null or a non-negative integer")
    upstream(data)
    guardrail_mode(data)
    pinned_model(data)
    for model in data.get("models", {}).values():
        if model.get("seed_supported") is not None and type(model["seed_supported"]) is not bool:
            raise ValueError("models.*.seed_supported must be true, false or null")
    return data


def conditions(body, headers, config):
    support = config.get("models", {}).get(body.get("model"), {}).get("seed_supported")
    requested_seed = body.get("seed")
    if support is False:
        seed, seed_status, seed_note = None, "unsupported", "미지원: 설정에서 seed 미지원으로 명시"
    elif support is True:
        seed = requested_seed
        seed_status = "requested" if seed is not None else "not_set"
        seed_note = "지원 설정에 따른 요청값; 업스트림 적용·결정성 검증은 아님"
    else:
        seed, seed_status, seed_note = None, "unverified", "지원 여부 미확인"
    run_index = headers.get("X-Guardrail-Run-Index")
    buffer = headers.get("X-Guardrail-Context-Buffer-Messages")
    buffer = int(buffer) if buffer not in (None, "none") else None
    if buffer is not None and buffer < 1:
        raise ValueError("context buffer must be positive or none")
    if run_index is not None:
        run_index = int(run_index)
        if run_index < 1:
            raise ValueError("run_index must be positive")
    # The run phase is a recorded condition like the scenario ID; block mode acts only on "demo" (DM-23).
    phase = headers.get(PHASE_HEADER)
    if phase is not None and not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", phase):
        raise ValueError("phase must be a short lowercase token")
    return {
        "model": body.get("model"), "temperature": body.get("temperature"),
        "seed": seed, "seed_status": seed_status, "seed_note": seed_note,
        "requested_seed": requested_seed, "max_tokens": body.get("max_tokens"),
        "scenario_id": headers.get("X-Guardrail-Scenario"), "run_index": run_index,
        "framework_version": headers.get("X-Guardrail-Framework-Version"),
        "context_buffer_messages": buffer, "phase": phase,
    }


def tool_call_count(data, status):
    # Count returned call requests, not tools executed by the framework.
    choices = data.get("choices")
    if status != 200 or not isinstance(choices, list) or not choices:
        return None
    total = 0
    for choice in choices:
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            return None
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls):
            return None
        total += len(calls) + int(bool(message.get("function_call")))
    return total


def truncate_text(value, limit):
    text = value if isinstance(value, str) else str(value)
    return text if limit is None else text[:limit]
