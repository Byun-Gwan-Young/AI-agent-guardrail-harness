"""Explicit experiment conditions, never inferred from provider defaults."""
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


def load_config(path=None):
    path = config_file(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    truncate = data.get("log", {}).get("truncate")
    if truncate is not None and (type(truncate) is not int or truncate < 0):
        raise ValueError("log.truncate must be null or a non-negative integer")
    upstream(data)
    guardrail_mode(data)
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
