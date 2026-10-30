from __future__ import annotations

import os
from dotenv import load_dotenv
# Load .env from agent/ directory (contains APP_DB_URL, REDIS_URL, etc.)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from typing import Optional

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
from .routers import protocol_types as protocol_types_router
from .routers import bulk_import as bulk_import_router
from .routers import equipment as equipment_router
from .routers import alerts as alerts_router
from fastapi import Depends
from .permissions import require_logger_write, require_safe_or_write
from .store import Store
from ..metrics import metrics as METRICS


def _flag(name: str, default: bool = False) -> bool:
    """Read a boolean feature flag from the environment."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# L12: boot-path status/warnings go through structured logging (not print)
# so subsystem failures land in agent.log with tracebacks.
boot_log = logging.getLogger("plc_agent.boot")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default


def _log_rotation_config() -> tuple[int, int]:
    """Resolve log-rotation caps as (max_bytes, backup_count) — H-OBS-3.

    Env names match the Rust engine (log_max_bytes()/log_max_backups() in
    agent/rust_jobs/src/main.rs): LOGGER_LOG_MAX_MB (default 50 MB/file) and
    LOGGER_LOG_BACKUPS (default 5). Replaces the old 500 MB x 999-backup
    config that allowed ~unbounded disk growth.
    """
    max_mb = max(1, _env_int("LOGGER_LOG_MAX_MB", 50))
    backups = max(1, _env_int("LOGGER_LOG_BACKUPS", 5))
    return max_mb * 1024 * 1024, backups


def _cors_config() -> tuple[list[str], Optional[str]]:
    """Resolve the CORS allowlist (M14).

    When LOGGER_CORS_ORIGINS is set (comma-separated exact origins) only those
    origins are allowed and the permissive LAN/loopback/app-scheme regex is
    disabled. When unset, the historical dev-friendly allowlist is kept for
    compatibility.
    """
    raw = os.environ.get("LOGGER_CORS_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins, None
    allow_origins = [
        os.environ.get("CORS_ORIGIN", "http://127.0.0.1:5173"),
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://127.0.0.1:9847",
        "http://localhost:9847",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://100.90.185.31:5173",
        "http://100.90.185.31:5175",
        "http://100.90.185.31:5180",
        "http://100.90.185.31:8081",
        "http://100.90.185.31:9847",
        # Naidupet: Logger V2 production (9848) and dev (3170), from plant
        # PCs (LAN) and over Tailscale. localhost / 127.0.0.1 match the regex.
        "http://10.60.200.10:9848",
        "http://100.65.86.37:9848",
        "http://10.60.200.10:3170",
        "http://100.65.86.37:3170",
    ]
    allow_origin_regex = r"^(https?://tauri\.localhost(:\d+)?|(app|tauri)://.*|https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|100\.90\.185\.31)(:\d+)?)$"
    return allow_origins, allow_origin_regex


def create_app() -> FastAPI:
    app = FastAPI(title="Neuract Logger Agent", version=VERSION)
    # Feature flags. The AI pipeline is a COMING-SOON integration: its code ships
    # in the repo but is excluded from the production runtime unless explicitly
    # enabled via LOGGER_ENABLE_AI=1.
    ai_enabled = _flag("LOGGER_ENABLE_AI", default=False)
    # Minimal logging config (respects UVICORN_LOG where applicable)
    try:
        if not logging.getLogger().handlers:
            lvl = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
            logging.basicConfig(level=getattr(logging, lvl, logging.INFO))
        # File logs under ProgramData
        try:
            log_dir = Path(__file__).resolve().parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            # H-OBS-3: bounded rotation, env-tunable (LOGGER_LOG_MAX_MB /
            # LOGGER_LOG_BACKUPS — same knobs as the Rust engine).
            max_bytes, backup_count = _log_rotation_config()
            fh = RotatingFileHandler(
                log_dir / "agent.log", encoding="utf-8",
                maxBytes=max_bytes,
                backupCount=backup_count,
            )
            fh.setLevel(getattr(logging, os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(), logging.INFO))
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            fh.setFormatter(fmt)
            logging.getLogger().addHandler(fh)
        except Exception as _e:
            boot_log.warning("File logging setup warning: %s", _e)
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
        boot_log.info(
            "Tech Stack Verified: %s",
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
        boot_log.warning("Tech Stack Verification warning: %s", _e)

    # CORS for local dev (Desktop app or browser hitting localhost)
    # Allow local dev + packaged app (Tauri schemes send non-http origins)
    # M14: production deployments should set LOGGER_CORS_ORIGINS to an exact
    # comma-separated origin allowlist (see GETTING_STARTED.md section 2).
    allow_origins, allow_origin_regex = _cors_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Public routers (no auth — matches Django AllowAny)
    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(protocol_types_router.router)
    app.include_router(bulk_import_router.router)
    # Protected routers (Keycloak JWT + role-based). schemas, tables, devices
    # and jobs2 used to allow GETs without a token (their writes were already
    # guarded per endpoint); every read now needs logger-read as well.
    _protected = [
        schemas.router,
        tables_router.router,
        devices_router.router,
        jobs2.router,
        jobs.router,
        networking.router,
        storage.router,
        mappings_router.router,
        system_router.router,
        db_metrics_router.router,
        reports_router.router,
        debug_router.router,
        equipment_router.router,
        alerts_router.router,
    ]
    for r in _protected:
        app.include_router(r, dependencies=[Depends(require_safe_or_write)])
    # Notification routers (auth handled inside each endpoint/websocket)
    app.include_router(notifications_router.router)
    app.include_router(ws_notifications_router.router)
    # AI Agent (Hermes + Qwen) — COMING SOON, excluded from production unless
    # LOGGER_ENABLE_AI=1. Code stays in the repo; it is simply not wired in.
    if ai_enabled:
        from .ai.router import router as ai_router
        app.include_router(ai_router)
        # AI Chat UI — served as static files
        from pathlib import Path as _Path
        _ui_dir = _Path(__file__).resolve().parent / "ai" / "ui"
        if _ui_dir.exists():
            from fastapi.staticfiles import StaticFiles
            app.mount("/ai/ui", StaticFiles(directory=str(_ui_dir), html=True), name="ai-ui")
        boot_log.info("AI pipeline ENABLED (LOGGER_ENABLE_AI=1)")
    else:
        boot_log.info("AI pipeline disabled (set LOGGER_ENABLE_AI=1 to enable)")
    from .permissions import auth_disabled
    if auth_disabled():
        boot_log.warning(
            "AUTH DISABLED (LOGGER_AUTH_DISABLED=1): every request is treated as an admin. "
            "Local demo only; never use in production."
        )
    # Align DPAPI scope: rekey secrets under current context (machine scope for service)
    try:
        from .appdb import rekey_all_device_params as _rekey
        changed = _rekey()
        if changed:
            boot_log.info("DPAPI rekey: updated %s device secret(s)", changed)
    except Exception as _e:
        boot_log.exception("DPAPI rekey warning: %s", _e)
    # Load persisted App Local DB state
    try:
        Store.instance().load_from_app_db()
        try:
            tables = Store.instance().list_tables()
            bound = len([t for t in tables if t.get("deviceId")])
            boot_log.info("App DB load: tables=%s device_bound=%s", len(tables), bound)
        except Exception:
            pass
    except Exception as _e:
        boot_log.exception("App DB load warning: %s", _e)
    # Start device auto-reconnect loop
    try:
        Store.instance().start_device_reconnector()
    except Exception as _e:
        boot_log.exception("Device reconnector warning: %s", _e)

    # Start system metrics sampler
    try:
        METRICS.system.start()
    except Exception as _e:
        boot_log.exception("System metrics sampler warning: %s", _e)
    # Start enabled jobs on boot (idempotent). Set LOGGER_DISABLE_BOOT_JOBS=1 to
    # suppress — required for tests, and the operator switch to avoid the Python
    # writer double-writing when the Rust job-runner is the acquisition engine.
    # C5: boot autostart must only MARK enabled jobs running (jobs2) — job
    # execution belongs to the Rust engine. The legacy routers.jobs version
    # spawns Python acquisition threads that double-write alongside Rust.
    if not _flag("LOGGER_DISABLE_BOOT_JOBS", default=False):
        try:
            jobs2.start_enabled_jobs_on_boot()
        except Exception as _e:
            boot_log.exception("Start enabled jobs warning: %s", _e)
    else:
        boot_log.info("Boot job autostart disabled (LOGGER_DISABLE_BOOT_JOBS=1)")
    # Start prediction monitor (Layer 3) — part of the AI pipeline, gated off by default.
    if ai_enabled:
        try:
            from .ai.prediction.background import start_prediction_monitor
            start_prediction_monitor()
        except Exception as _e:
            boot_log.exception("Prediction monitor warning: %s", _e)
    return app


# Exposed for `uvicorn agent.plc_agent.api.app:app`
app = create_app()

