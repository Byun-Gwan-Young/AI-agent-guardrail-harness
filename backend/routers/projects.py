from fastapi import APIRouter, Depends
from psycopg import Connection

from backend.db import get_db
from backend.auth.dependencies import get_current_user
from backend.repositories.projects import fetch_projects
from backend.schemas import ProjectResponse


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(user=Depends(get_current_user), conn: Connection = Depends(get_db)):
    return fetch_projects(conn, user["id"])
