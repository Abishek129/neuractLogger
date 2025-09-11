from fastapi import APIRouter
import os
import sys
import platform
from threading import Timer

from ..version import VERSION


router = APIRouter()


@router.get("/health")
def get_health():
    return {"status": "ok", "agent": "plc-agent", "version": VERSION}


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


@router.post("/shutdown")
def shutdown():
    # Delay exit slightly to let response flush
    Timer(0.2, lambda: os._exit(0)).start()
    return {"ok": True, "message": "shutting_down"}
