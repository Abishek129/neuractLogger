from __future__ import annotations

import os
from fastapi import FastAPI
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from .version import VERSION
from .routers import health, schemas, jobs, jobs2, networking, storage
from .routers import system as system_router
from .routers import db_metrics as db_metrics_router
from .routers import reports as reports_router
from .routers import debug as debug_router
from .routers import auth as auth_router
from .routers import tables as tables_router
from .routers import mappings as mappings_router
from .routers import devices as devices_router
from .routers import notifications as notifications_router
from .routers import ws_notifications as ws_notifications_router
from fastapi import Depends
from .permissions import require_safe_or_write
from .store import Store
from ..metrics import metrics as METRICS


def create_app() -> FastAPI:
    app = FastAPI(title="Neuract Logger Agent", version=VERSION)
    # Minimal logging config (respects UVICORN_LOG where applicable)
    try:
        if not logging.getLogger().handlers:
            lvl = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
            logging.basicConfig(level=getattr(logging, lvl, logging.INFO))
        # File logs under ProgramData
        try:
            log_dir = Path(__file__).resolve().parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
            fh.setLevel(getattr(logging, os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(), logging.INFO))
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            fh.setFormatter(fmt)
            logging.getLogger().addHandler(fh)
        except Exception as _e:
            print("File logging setup warning:", _e)
    except Exception:
        pass
    # Auth is handled via per-router Depends (Keycloak JWT)
    # Tech stack verification note
    try:
        import sys, platform
        import fastapi as _fastapi
        import sqlalchemy as _sqlalchemy
        import uvicorn as _uvicorn
        import apscheduler as _aps
        try:
            import opcua as _opcua  # type: ignore
            opcua_ver = getattr(_opcua, "__version__", "installed")
        except Exception:
            opcua_ver = "missing"
        print(
            "Tech Stack Verified:",
            {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "fastapi": getattr(_fastapi, "__version__", "unknown"),
                "sqlalchemy": getattr(_sqlalchemy, "__version__", "unknown"),
                "uvicorn": getattr(_uvicorn, "__version__", "unknown"),
                "apscheduler": getattr(_aps, "__version__", "unknown"),
                "opcua": opcua_ver,
            },
        )
    except Exception as _e:
        print("Tech Stack Verification warning:", _e)

    # CORS for local dev (Desktop app or browser hitting localhost)
    # Allow local dev + packaged app (Tauri schemes send non-http origins)
    allow_origins = [
        os.environ.get("CORS_ORIGIN", "http://127.0.0.1:5173"),
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=r"^(https?://tauri\.localhost(:\d+)?|(app|tauri)://.*)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Public routers (no auth — matches Django AllowAny)
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(schemas.router)
    app.include_router(tables_router.router)
    app.include_router(devices_router.router)
    # Unprotected legacy router
    app.include_router(jobs2.router)
    # Protected routers (Keycloak JWT + role-based: IsNeuractAdminForUnsafeMethods)
    _protected = [
        jobs.router,
        networking.router,
        storage.router,
        mappings_router.router,
        system_router.router,
        db_metrics_router.router,
        reports_router.router,
        debug_router.router,
    ]
    for r in _protected:
        app.include_router(r, dependencies=[Depends(require_safe_or_write)])
    # Notification routers (auth handled inside each endpoint/websocket)
    app.include_router(notifications_router.router)
    app.include_router(ws_notifications_router.router)
    # Align DPAPI scope: rekey secrets under current context (machine scope for service)
    try:
        from .appdb import rekey_all_device_params as _rekey
        changed = _rekey()
        if changed:
            print(f"DPAPI rekey: updated {changed} device secret(s)")
    except Exception as _e:
        print("DPAPI rekey warning:", _e)
    # Load persisted App Local DB state
    try:
        Store.instance().load_from_app_db()
        try:
            tables = Store.instance().list_tables()
            bound = len([t for t in tables if t.get("deviceId")])
            print(f"App DB load: tables={len(tables)} device_bound={bound}")
        except Exception:
            pass
    except Exception as _e:
        print("App DB load warning:", _e)
    # Start device auto-reconnect loop
    try:
        Store.instance().start_device_reconnector()
    except Exception as _e:
        print("Device reconnector warning:", _e)

    # Start system metrics sampler
    try:
        METRICS.system.start()
    except Exception as _e:
        print("System metrics sampler warning:", _e)
    # Start enabled jobs on boot (idempotent)
    try:
        from .routers import jobs as _jobs
        _jobs.start_enabled_jobs_on_boot()
    except Exception as _e:
        print("Start enabled jobs warning:", _e)
    return app


# Exposed for `uvicorn agent.plc_agent.api.app:app`
app = create_app()


