import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import random
import time
import uuid
from session_store import JsonSessionRepository, SessionStore, utc_now
from health import install_health
from experiment_config import (PHASE_HEADER, config_file, load_config, conditions, guardrail_mode, pinned_model,
                               tool_call_count, truncate_text, upstream)
from conversation_extract import extract_conversation
from observation_api import install_observations
from deadlock_policy import VERSION as CRITERIA_VERSION
from deadlock_policy_v03 import VERSION as BLOCK_CRITERIA_VERSION
from progress_schema import SessionRegistration
from pydantic import ValidationError
from explain_v1 import STOP_DECISIONS
from criteria_freeze import freeze

from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)
DEMO_PHASE = "demo"
ROOT = Path(__file__).resolve().parent
# DM-2, DM-34 for proxy logs (C-17-4): a demo-condition proxy logs only under logs/demo/ and nothing else does.
DEMO_LOG_ROOT = ROOT / "logs" / "demo"
# DM-79 (C-18-7): replies are not streamed, so a whole generation must arrive within the read limit. Read waits up to
# 600 s; connect, write and pool stay at the earlier 120 s. A read past 600 s still becomes the proxy's 502.
UPSTREAM_TIMEOUT = httpx.Timeout(120, read=600)


def demo_condition(config):
    """The proxy's demo condition is its criteria version: deadlock-v0.3 judges only demo sessions (DM-10, DM-37:
    scenario-v1 refuses v0.3; registration and block mode need v0.3). The run phase arrives only with requests."""
    return config.get("criteria_version") == BLOCK_CRITERIA_VERSION


def log_dir_for(demo, requested):
    """GUARDRAIL_LOG_DIR as given (default logs/demo/ for a demo proxy, logs for any other), checked both ways."""
    directory = Path(requested) if requested is not None else DEMO_LOG_ROOT if demo else Path("logs")
    inside_demo = directory.resolve().is_relative_to(DEMO_LOG_ROOT.resolve())
    if demo and not inside_demo:
        raise ValueError("A " + BLOCK_CRITERIA_VERSION + " (demo) proxy logs only under " + str(DEMO_LOG_ROOT)
                         + " (GUARDRAIL_LOG_DIR, DM-34)")
    if not demo and inside_demo:
        raise ValueError(str(DEMO_LOG_ROOT) + " is reserved for " + BLOCK_CRITERIA_VERSION + " (demo) proxies (DM-2)")
    return directory


def session_key(request, body):
    supplied = request.headers.get("X-Guardrail-Session")
    if supplied is not None:
        # Safe Windows filenames, including reserved device names and traversal.
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", supplied) or re.fullmatch(
            r"(?i:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])", supplied
        ):
            raise HTTPException(400, "Invalid session key: use 1-128 ASCII letters, digits, _ or -")
        return supplied
    messages = body.get("messages")
    if isinstance(messages, list) and messages and messages[0]:
        encoded = json.dumps(messages[0], sort_keys=True, ensure_ascii=False).encode()
        return "hash-" + hashlib.sha256(encoded).hexdigest()
    client = request.scope.get("client")
    if client is None:
        # Without a connection identity, don't merge unrelated requests.
        key = "temporary-" + uuid.uuid4().hex
    else:
        identity = repr((client, request.scope.get("server"))).encode()
        key = "connection-" + hashlib.sha256(identity).hexdigest()
    logger.warning("No session header or first message; using temporary connection session %s", key)
    return key


def demo_only(phase):
    """DM-32: a block-mode proxy serves only the demo phase. Anything else fails loudly instead of running as observe."""
    return JSONResponse({"error": {"type": "guardrail_block_requires_demo_phase",
                                   "code": "block_mode_requires_demo_phase",
                                   "message": "차단 프록시는 demo phase 전용입니다 (" + PHASE_HEADER + ": " + DEMO_PHASE + ")",
                                   "phase": phase}},
                        status_code=409, headers={"x-should-retry": "false"})


def other_model(pin, requested):
    """S-12: a pinned proxy forwards one model only. Another model is refused before anything goes upstream or a
    session starts, like DM-32: running it here would put a session of another condition group in this proxy's logs."""
    return JSONResponse({"error": {"type": "guardrail_model_not_pinned", "code": "model_differs_from_pinned_model",
                                   "message": "이 프록시는 모델 " + pin["name"] + " 전용입니다 (S-12, 프록시 1 개 = 조건군 1 개). "
                                              "요청 모델 : " + str(requested),
                                   "pinned_model": pin["name"], "requested_model": requested}},
                        status_code=409, headers={"x-should-retry": "false"})


def blocking_stop(session, params):
    """DM-7, DM-23: the first STOP record of a block-mode session, for a request that declares the demo phase.

    A block-mode request without the demo phase never gets here (DM-32). The STOP comes from the same judgement
    as observe mode.
    """
    if session.meta.get("guardrail_mode") != "block" or params.get("phase") != DEMO_PHASE:
        return None
    return next((o for o in session.observations
                 if (o.get("criteria") or {}).get("decision") in STOP_DECISIONS), None)


def stop_error(session, stop):
    criteria = stop["criteria"]
    explanation = criteria.get("explanation") or {}
    # DM-9: the sentence of the STOP record itself, copied and never rebuilt, so body, log and manifest match.
    return {"error": {"type": "guardrail_stop", "code": "guardrail_stop",
                      "message": explanation.get("text") or "guardrail_stop",
                      "stop_step": stop["step_id"], "decision": criteria["decision"],
                      "criteria_version": criteria.get("criteria_version"),
                      "criteria_sha256": criteria.get("criteria_sha256"),
                      "explanation_version": explanation.get("explanation_version"),
                      "template_id": explanation.get("template_id"), "session_id": session.session_id}}


def create_app(log_dir=None, transport=None, sleep=asyncio.sleep, repository=None,
               config_path=None, clock=time.monotonic, jitter=random.uniform,
               judgement_clock_ns=time.perf_counter_ns):
    config = load_config(config_path)
    mode = guardrail_mode(config)
    if mode == "block" and config.get("criteria_version") != BLOCK_CRITERIA_VERSION:
        # Block is a demo device (DM-7); the dataset criteria versions never run with it.
        raise ValueError("guardrail_mode block requires criteria_version " + BLOCK_CRITERIA_VERSION)
    settings = upstream(config)
    pin = pinned_model(config)
    endpoint = settings["base_url"] + settings["chat_path"]
    # Identifiers only: the key itself is never read here, only forwarded from the caller.
    identity = {"base_url_host": urlsplit(settings["base_url"]).netloc,
                "base_url": settings["base_url"], "chat_path": settings["chat_path"],
                "api_key_env": settings["api_key_env"], "config_file": config_file(config_path).name}
    app = FastAPI()
    if repository is None and log_dir is None:
        # The started proxy (uvicorn proxy:app) reads its log directory only here; checked before it serves anything.
        log_dir = log_dir_for(demo_condition(config), os.environ.get("GUARDRAIL_LOG_DIR"))
    store = SessionStore(repository if repository is not None else JsonSessionRepository(log_dir),
        criteria_version=config.get("criteria_version", CRITERIA_VERSION), upstream=identity,
        criteria_parameters=config.get("criteria_parameters"), guardrail_mode=mode, pinned_model=pin,
        criteria_freeze=freeze(config.get("criteria_version", CRITERIA_VERSION)))
    app.state.store = store
    app.state.upstream = identity
    app.state.pinned_model = pin
    install_health(app, store, clock, config.get("policy_version"))
    install_observations(app, store, session_key, judgement_clock_ns)

    @app.post("/sessions")
    async def start_session(request: Request):
        if not request.headers.get("X-Guardrail-Session"):
            raise HTTPException(400, "X-Guardrail-Session is required")
        if mode == "block" and request.headers.get(PHASE_HEADER) != DEMO_PHASE:
            return demo_only(request.headers.get(PHASE_HEADER))
        registration = None
        if await request.body():
            # DM-26, DM-29, DM-35: optional scenario display settings, registered once with the session.
            try:
                payload = await request.json()
                if not isinstance(payload, dict) or set(payload) - {"registration"}:
                    raise ValueError("body accepts only registration")
                if payload.get("registration") is not None:
                    registration = SessionRegistration.model_validate(payload["registration"]).model_dump()
            except (ValidationError, ValueError):
                raise HTTPException(422, "Invalid session registration") from None
            if registration is not None and store.criteria_pin["criteria_version"] != BLOCK_CRITERIA_VERSION:
                raise HTTPException(422, "Session registration requires deadlock-v0.3")
        session = store.start(session_key(request, {}), registration)
        return {"session_id": session.session_id, **({"registered": True} if registration is not None else {})}

    @app.post("/sessions/end")
    async def end_session(request: Request):
        if not request.headers.get("X-Guardrail-Session"):
            raise HTTPException(400, "X-Guardrail-Session is required")
        payload = await request.json() if await request.body() else {}
        reason = payload.get("termination_reason")
        if reason is not None and not isinstance(reason, str):
            raise HTTPException(400, "termination_reason must be a string or null")
        key = session_key(request, {})
        session = store.get(key)
        if session is None:
            raise HTTPException(404, "Unknown session")
        async with session.lock:
            store.end(session, reason)
        return {"session_id": key, "status": "ended"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        try:
            params = conditions(body, request.headers, config)
        except (ValueError, TypeError):
            raise HTTPException(400, "Invalid experiment metadata") from None
        upstream_body = dict(body)
        if params["seed_status"] == "unsupported":
            upstream_body.pop("seed", None)
        key = session_key(request, body)
        existing = store.get(key)
        # The session's own recorded mode, or this proxy's mode for a session that does not exist yet.
        session_mode = existing.meta.get("guardrail_mode") if existing is not None else mode
        if session_mode == "block" and params["phase"] != DEMO_PHASE:
            return demo_only(params["phase"])
        if pin is not None and body.get("model") != pin["name"]:
            return other_model(pin, body.get("model"))
        session = store.get_or_start(key)
        async with session.lock:
            if session.status == "ended":
                raise HTTPException(409, "Session is closed; use a new key")
            if not session.turns:
                session.meta.update(params)
                session.meta["conditions_mixed"] = False
            elif any(session.meta.get(k) != v for k, v in params.items()):
                session.meta["conditions_mixed"] = True
            t0 = clock()
            stop = blocking_stop(session, params)
            if stop is not None:
                # Nothing goes upstream. The refusal is a logged turn so the runner can link it to its step.
                error = stop_error(session, stop)
                turn = len(session.turns) + 1
                block = session.meta.get("guardrail_block")
                if block is None:
                    block = session.meta["guardrail_block"] = {
                        "stop_step": stop["step_id"], "decision": error["error"]["decision"],
                        "criteria_version": error["error"]["criteria_version"],
                        "criteria_sha256": error["error"]["criteria_sha256"],
                        "explanation": copy.deepcopy(stop["criteria"].get("explanation")),
                        # Observations arrive after each step, so the refused request belongs to the next step.
                        "blocked_at_step": len(session.observations) + 1, "first_blocked_turn": turn,
                        "refused_requests": 0}
                block["refused_requests"] += 1
                messages = body.get("messages") or []
                session.turns.append({
                    "turn": turn, "forwarded": False, "blocked": True,
                    "upstream_ms": 0.0, "retry_wait_ms": 0.0, "total_ms": (clock() - t0) * 1000,
                    "retry_delays_ms": [], "retry_count": 0, "request_params": params, "request_body": body,
                    "upstream_request_body": None, "response_body": error,
                    "seed_audit": {"requested_seed": body.get("seed"), "forwarded_seed": None, "forwarded": False,
                                   "response_status": 403, "request_succeeded": False, "model_applied_seed": None,
                                   "note": "Refused by guardrail block mode; nothing was sent upstream"},
                    "conversation_extracted": None, "tool_calls": None, "status_code": 403,
                    "in": truncate_text(messages[-1].get("content", "") if messages else "",
                                        config.get("log", {}).get("truncate")),
                    "out": "", "empty": None,
                    # Not forwarded, so the provider consumed nothing for this request.
                    "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0,
                })
                store.save(session)
                return JSONResponse(error, status_code=403,
                                    headers={"X-Guardrail-Session": session.session_id, "X-Guardrail-Turn": str(turn),
                                             "x-should-retry": "false"})
            upstream_ms, retry_wait_ms = 0.0, 0.0
            retry_delays_ms = []
            try:
                async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, transport=transport) as client:
                    for attempt in range(7):  # Initial attempt + at most six retries.
                        call_started = clock()
                        try:
                            r = await client.post(
                                endpoint, json=upstream_body,
                                headers={"Authorization": request.headers.get("authorization", "")},
                            )
                        finally:
                            upstream_ms += (clock() - call_started) * 1000
                        app.state.upstream_health = {"reachable": True, "checked_at": utc_now()}
                        if r.status_code != 429 or attempt == 6:
                            break
                        ceiling = min(60.0, 2.0 ** attempt)
                        delay = ceiling / 2 + jitter(0.0, ceiling / 2)
                        retry_delays_ms.append(delay * 1000)
                        wait_started = clock()
                        await sleep(delay)
                        retry_wait_ms += (clock() - wait_started) * 1000
                status = r.status_code
                content = r.content
                media_type = r.headers.get("content-type", "application/json")
                try:
                    data = r.json()
                except ValueError:
                    data = {}
            except httpx.RequestError:
                app.state.upstream_health = {"reachable": False, "checked_at": utc_now()}
                status, data = 502, {}
                content = b'{"error":"Upstream connection failed"}'
                media_type = "application/json"

            if not isinstance(data, dict):
                data = {}
            choices = data.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            reply = message.get("content") or ""
            usage = data.get("usage") or {}
            messages = body.get("messages") or []
            last_in = messages[-1].get("content", "") if messages else ""
            # Read only original utterance, before optional log truncation. Never request agent JSON.
            extracted = None
            if status == 200:
                try:
                    prior = next((t["conversation_extracted"] for t in reversed(session.turns)
                                  if (t.get("conversation_extracted") or {}).get("open_issue_ids") is not None), None)
                    extracted = extract_conversation(str(reply), prior)
                except Exception:
                    logger.warning("Conversation extraction failed; forwarding response", exc_info=True)
            session.turns.append({
                "turn": len(session.turns) + 1,
                "upstream_ms": upstream_ms,
                "retry_wait_ms": retry_wait_ms,
                "total_ms": (clock() - t0) * 1000,
                "retry_delays_ms": retry_delays_ms,
                "retry_count": len(retry_delays_ms),
                "request_params": params,
                "request_body": body,
                "upstream_request_body": upstream_body,
                "response_body": data,
                "seed_audit": {
                    "requested_seed": body.get("seed"),
                    "forwarded_seed": upstream_body.get("seed"),
                    "forwarded": "seed" in upstream_body,
                    "response_status": status,
                    "request_succeeded": status == 200,
                    "model_applied_seed": None,
                    "note": "Forwarded body and HTTP outcome only; success does not prove seed was applied",
                },
                "conversation_extracted": extracted,
                "tool_calls": tool_call_count(data, status),
                "status_code": status,
                "in": truncate_text(last_in, config.get("log", {}).get("truncate")),
                "out": truncate_text(reply, config.get("log", {}).get("truncate")),
                "empty": reply.strip() == "" if status == 200 else None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "tokens": usage.get("total_tokens"),
            })
            store.save(session)
            return Response(content=content, status_code=status, media_type=media_type,
                            headers={"X-Guardrail-Session": session.session_id,
                                     "X-Guardrail-Turn": str(len(session.turns))})

    @app.get("/conditions")
    async def get_conditions():
        # C-18-2 (DM-63): what this proxy judges and forwards, read by the batch runner before each session. Local
        # values only; never calls the upstream and holds no key.
        return {"criteria_version": store.criteria_pin["criteria_version"],
                "criteria_sha256": store.criteria_pin.get("criteria_sha256"),
                "criteria_freeze_sha256": (store.criteria_freeze or {}).get("sha256"),
                "guardrail_mode": mode, "pinned_model": pin, "config_file": identity["config_file"],
                "upstream_host": identity["base_url_host"]}

    @app.get("/log")
    async def get_log(request: Request):
        if not request.headers.get("X-Guardrail-Session"):
            raise HTTPException(400, "X-Guardrail-Session is required")
        session = store.get(session_key(request, {}))
        if session is None:
            raise HTTPException(404, "Unknown session")
        return JSONResponse(session.record())

    return app


app = create_app()
