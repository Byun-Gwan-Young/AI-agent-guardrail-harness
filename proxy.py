import asyncio
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
from experiment_config import config_file, load_config, conditions, tool_call_count, truncate_text, upstream
from conversation_extract import extract_conversation
from observation_api import install_observations
from deadlock_policy import VERSION as CRITERIA_VERSION

from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


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


def create_app(log_dir=None, transport=None, sleep=asyncio.sleep, repository=None,
               config_path=None, clock=time.monotonic, jitter=random.uniform,
               judgement_clock_ns=time.perf_counter_ns):
    config = load_config(config_path)
    settings = upstream(config)
    endpoint = settings["base_url"] + settings["chat_path"]
    # Identifiers only: the key itself is never read here, only forwarded from the caller.
    identity = {"base_url_host": urlsplit(settings["base_url"]).netloc,
                "base_url": settings["base_url"], "chat_path": settings["chat_path"],
                "api_key_env": settings["api_key_env"], "config_file": config_file(config_path).name}
    app = FastAPI()
    store = SessionStore(repository if repository is not None else JsonSessionRepository(
        log_dir or os.environ.get("GUARDRAIL_LOG_DIR", "logs")
    ), criteria_version=config.get("criteria_version", CRITERIA_VERSION), upstream=identity)
    app.state.store = store
    app.state.upstream = identity
    install_health(app, store, clock, config.get("policy_version"))
    install_observations(app, store, session_key, judgement_clock_ns)

    @app.post("/sessions")
    async def start_session(request: Request):
        if not request.headers.get("X-Guardrail-Session"):
            raise HTTPException(400, "X-Guardrail-Session is required")
        session = store.start(session_key(request, {}))
        return {"session_id": session.session_id}

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
        session = store.get_or_start(session_key(request, body))
        async with session.lock:
            if session.status == "ended":
                raise HTTPException(409, "Session is closed; use a new key")
            if not session.turns:
                session.meta.update(params)
                session.meta["conditions_mixed"] = False
            elif any(session.meta.get(k) != v for k, v in params.items()):
                session.meta["conditions_mixed"] = True
            t0 = clock()
            upstream_ms, retry_wait_ms = 0.0, 0.0
            retry_delays_ms = []
            try:
                async with httpx.AsyncClient(timeout=120, transport=transport) as client:
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
