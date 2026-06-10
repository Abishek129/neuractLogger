from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
import os
import sys
import platform
import time
from threading import Timer

from ..version import VERSION
from ..permissions import require_admin
from ..redact import redact_dsn


router = APIRouter()


@router.get("/health")
def get_health():
    # Fast static liveness ping — readiness lives at /health/ready (M-OBS-1).
    return {"status": "ok", "agent": "plc-agent", "version": VERSION}


# ---------------------------------------------------------------------------
# M-OBS-1: readiness probe. Check functions are module-level so tests can
# monkeypatch each dependency individually (e.g. simulate App DB down).
# ---------------------------------------------------------------------------
def _check_app_db() -> dict:
    """Cheap SELECT 1 on the App (metadata) DB. REQUIRED for readiness."""
    try:
        from sqlalchemy import text

        from .. import appdb

        t0 = time.perf_counter()
        with appdb._engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "latencyMs": round((time.perf_counter() - t0) * 1000.0, 2)}
    except Exception as e:  # H-OBS-4: never echo a raw DSN-bearing error
        return {"ok": False, "error": redact_dsn(str(e))[:200]}


def _check_store() -> dict:
    """The in-memory Store singleton responds. REQUIRED for readiness."""
    try:
        from ..store import Store

        tables = Store.instance().list_tables()
        return {"ok": True, "tables": len(tables)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _check_redis() -> dict:
    """Redis reachability. OPTIONAL — reported but never gates readiness."""
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/3")
    try:
        import redis

        r = redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
        r.ping()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": redact_dsn(str(e))[:200]}


def _rust_engine_heartbeat() -> dict:
    """Last-seen heartbeat of the Rust engine, derived from the newest
    bench_metrics row in the App DB (the engine writes bench metrics there).
    INFO ONLY — never gates readiness (table may legitimately not exist)."""
    try:
        from sqlalchemy import text

        from .. import appdb

        with appdb._engine().connect() as conn:
            row = conn.execute(text("SELECT max(ts_utc) FROM bench_metrics")).fetchone()
        last = row[0] if row else None
        if last is None:
            return {"status": "no_data"}
        return {"status": "seen", "lastSeen": last.isoformat() if hasattr(last, "isoformat") else str(last)}
    except Exception:
        return {"status": "unknown"}


@router.get("/health/ready")
def get_readiness():
    """Readiness probe (M-OBS-1): 200 when the agent can do useful work,
    503 otherwise. Liveness stays on the static GET /health."""
    checks = {
        "app_db": _check_app_db(),
        "store": _check_store(),
        "redis": _check_redis(),
        "rust_engine": _rust_engine_heartbeat(),
    }
    ready = bool(checks["app_db"].get("ok")) and bool(checks["store"].get("ok"))
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "checks": checks},
    )


@router.get("/version")
def get_version():
    try:
        import fastapi as _fastapi
        import sqlalchemy as _sqlalchemy
        import uvicorn as _uvicorn
    except Exception:
        _fastapi = _sqlalchemy = _uvicorn = type("x", (), {"__version__": "unknown"})
    return {
        "appVersion": VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "fastapi": getattr(_fastapi, "__version__", "unknown"),
        "sqlalchemy": getattr(_sqlalchemy, "__version__", "unknown"),
        "uvicorn": getattr(_uvicorn, "__version__", "unknown"),
        "port": int(os.environ.get("AGENT_PORT", "0")) or None,
    }


@router.post("/shutdown", dependencies=[Depends(require_admin)])
def shutdown():
    # Delay exit slightly to let response flush
    Timer(0.2, lambda: os._exit(0)).start()
    return {"ok": True, "message": "shutting_down"}
