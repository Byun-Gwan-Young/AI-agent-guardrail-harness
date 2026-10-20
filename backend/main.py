from fastapi import Depends, FastAPI
from psycopg import Connection

from backend.db import get_db
from backend.routers.sessions import router
from backend.routers.projects import router as projects_router
from backend.routers.auth import router as auth_router


app = FastAPI(title="Agent Guardrail Backend", version="0.1.0")
app.include_router(router)
app.include_router(projects_router)
app.include_router(auth_router)


@app.get("/healthz", tags=["health"])
def health_check(conn: Connection = Depends(get_db)):
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return {"status": "ok", "database": "ok"}
