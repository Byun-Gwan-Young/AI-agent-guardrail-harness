from fastapi import APIRouter, Depends, HTTPException, Path, Query
from backend.db import db_connection
from backend.auth.dependencies import get_current_user
from backend.repositories.projects import project_exists
from backend.repositories.sessions import fetch_session_detail, fetch_sessions
from backend.schemas import SessionDetailResponse, SessionListResponse


router = APIRouter(prefix="/api/projects", tags=["sessions"])


def validate_list_params(
    project_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=2**63 - 1),
):
    return project_id, limit, offset


def validate_detail_params(
    project_id: int = Path(..., ge=1),
    session_id: str = Path(..., min_length=1, max_length=200),
):
    return project_id, session_id


@router.get("/{project_id}/sessions", response_model=SessionListResponse)
def list_sessions(params=Depends(validate_list_params), user=Depends(get_current_user)):
    project_id, limit, offset = params
    with db_connection() as conn:
        if not project_exists(conn, project_id, user["id"]):
            raise HTTPException(status_code=404, detail="Project not found")
        return fetch_sessions(conn, project_id, limit, offset, user["id"])


@router.get(
    "/{project_id}/sessions/{session_id}",
    response_model=SessionDetailResponse,
)
def get_session_detail(params=Depends(validate_detail_params), user=Depends(get_current_user)):
    project_id, session_id = params
    with db_connection() as conn:
        if not project_exists(conn, project_id, user["id"]):
            raise HTTPException(status_code=404, detail="Project not found")
        session = fetch_session_detail(conn, project_id, session_id, user["id"])
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found in this project",
        )
    return session
