"""Attach runner observations without executing filesystem or test commands in the proxy."""
import logging

from fastapi import HTTPException, Request
from pydantic import ValidationError

from conversation_extract import compare_extraction
from progress_schema import Observation
from progress_signal import calculate_progress
from session_store import utc_now
from deadlock_policy import evaluate_criteria, progress_version_for

logger = logging.getLogger(__name__)


def install_observations(app, store, session_key):
    @app.post("/sessions/observations")
    async def observe(request: Request):
        if not request.headers.get("X-Guardrail-Session"):
            raise HTTPException(400, "X-Guardrail-Session is required")
        try:
            observation = Observation.model_validate(await request.json()).model_dump()
        except (ValidationError, ValueError):
            raise HTTPException(422, "Invalid observation schema") from None
        session = store.get(session_key(request, {}))
        if session is None:
            raise HTTPException(404, "Unknown session")
        async with session.lock:
            step = observation["step_id"]
            old = next((o for o in session.observations if o["step_id"] == step), None)
            if old is not None:
                original = {k: old.get(k) for k in observation}
                if original != observation:
                    raise HTTPException(409, "Conflicting observation for step_id")
                persisted = store.save(session)
                return {"observation": old, "duplicate": True, "persisted": persisted}
            if session.status == "ended":
                raise HTTPException(409, "Session is ended")
            if step != len(session.observations) + 1:
                raise HTTPException(409, "Submit steps in order, starting at 1")
            assigned = {turn for o in session.observations for turn in o["llm_turns"]}
            if any(t > len(session.turns) or t in assigned for t in observation["llm_turns"]):
                raise HTTPException(409, "Unknown or already assigned LLM turn")
            try:
                result = calculate_progress(session.observations, observation,
                                            version=progress_version_for(session.meta))
            except Exception:
                logger.warning("Progress calculation failed; observation retained", exc_info=True)
                result = {"state": "unmeasured", "reason": "progress calculation failed"}
            record = {**observation, "observed_at": utc_now(), "progress": result}
            if observation["extracted_conversation"] is not None:
                record["extraction_comparison"] = compare_extraction(
                    observation["conversation"], observation["extracted_conversation"])
            try:
                record["criteria"] = evaluate_criteria(session.observations + [record], session.meta)
            except Exception:
                logger.warning("Criteria evaluation failed; observation retained", exc_info=True)
                record["criteria"] = {"criteria_version": session.meta.get("criteria_version"),
                                      "decision": "unmeasured", "reason": "criteria evaluation failed"}
            session.observations.append(record)
            persisted = store.save(session)
            return {"observation": record, "duplicate": False, "persisted": persisted}
