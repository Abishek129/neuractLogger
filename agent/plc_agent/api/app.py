from __future__ import annotations

import os
from fastapi import FastAPI
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from .version import VERSION
from .routers import health, schemas, jobs, networking, storage
from .routers import system as system_router
from .routers import db_metrics as db_metrics_router
from .routers import reports as reports_router
from .routers import auth as auth_router
from .routers import tables as tables_router
from .routers import mappings as mappings_router
from .routers import devices as devices_router
from .security import auth_middleware, get_or_create_token
from .store import Store
from ..metrics import metrics as METRICS


def create_app() -> FastAPI:
    app = FastAPI(title="PLC Logger Agent", version=VERSION)
    # Minimal logging config (respects UVICORN_LOG where applicable)
    try:
        if not logging.getLogger().handlers:
            lvl = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
            logging.basicConfig(level=getattr(logging, lvl, logging.INFO))
        # File logs under ProgramData
        try:
            base = os.environ.get("ProgramData") or os.getcwd()
            log_dir = Path(base) / "PLCLogger" / "agent" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(log_dir / "agent.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
            fh.setLevel(getattr(logging, os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(), logging.INFO))
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            fh.setFormatter(fmt)
            logging.getLogger().addHandler(fh)
        except Exception as _e:
            print("File logging setup warning:", _e)
    except Exception:
        pass
    # Register token auth middleware
    app.middleware("http")(auth_middleware())
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
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=r"^(app|tauri)://.*$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(schemas.router)
    app.include_router(jobs.router)
    app.include_router(networking.router)
    app.include_router(storage.router)
    app.include_router(devices_router.router)
    app.include_router(tables_router.router)
    app.include_router(mappings_router.router)
    app.include_router(system_router.router)
    app.include_router(db_metrics_router.router)
    app.include_router(reports_router.router)
    # Ensure token exists early
    get_or_create_token()
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
