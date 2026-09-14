"""Local health snapshot; never probes the upstream."""
import logging

logger = logging.getLogger(__name__)


def install_health(app, store, clock, policy_version=None):
    started = clock()
    app.state.upstream_health = {"reachable": None, "checked_at": None}

    @app.get("/healthz")
    async def healthz():
        try:
            active = store.active_count()
            status = "ok"
        except Exception:
            logger.warning("Cannot count active sessions", exc_info=True)
            active, status = None, "degraded"
        cached = app.state.upstream_health
        return {
            "status": status,
            "uptime": max(0.0, clock() - started),
            "active_sessions": active,
            "upstream_reachable": cached["reachable"],
            "upstream_checked_at": cached["checked_at"],
            "policy_version": policy_version,
        }
