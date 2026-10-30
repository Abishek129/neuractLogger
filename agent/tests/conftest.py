"""Pytest harness for the LoggerFast agent API (J1 E2E suite).

CRITICAL ORDERING
-----------------
``plc_agent.api.app`` runs ``create_app()`` at MODULE IMPORT time (app.py:219),
which immediately initializes the App DB (appdb.init), loads the Store
singleton, and starts daemon threads. All environment variables MUST therefore
be set before the first ``from plc_agent.api.app import app`` anywhere in the
test process — that is why the os.environ block below lives at conftest module
level (conftest is imported before any test module).

DB ISOLATION
------------
One meta DB per pytest process (appdb._ENGINE / Store._inst /
tables._engine_cache are process-global; never re-point APP_DB_URL mid-run).
The session creates/drops two throwaway PostgreSQL databases:

  * meta_test_e2e   — App (metadata) DB, also used as the Rust BENCH_DB_URL
  * target_test_e2e — user/target DB (neuract schema, physical tables)

NEVER point these names at production DBs (meta_data_version1,
target_version1, loggerfast_metrics are off-limits).

AUTH
----
There is no auth bypass in the product. Tests install
``app.dependency_overrides[permissions.get_claims]`` with a role-parametrized
fake-claims factory (see ``_AUTH`` / ``auth_role`` / ``no_auth``). Clearing
the override restores real 401 behavior on guarded endpoints.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

import psycopg2
import pytest

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]  # was hardcoded to one machine's checkout
AGENT_DIR = REPO_ROOT / "agent"
TESTS_DIR = AGENT_DIR / "tests"
RUST_BINARY = TESTS_DIR / "bin" / "neuract-job-runner"

# LOGGERFAST_TEST_DB_SUFFIX lets concurrent pytest runs (e.g. parallel CI lanes
# or multiple agents) use disjoint throwaway databases.
_DB_SUFFIX = os.environ.get("LOGGERFAST_TEST_DB_SUFFIX", "e2e")
META_DB = f"meta_test_{_DB_SUFFIX}"
TARGET_DB = f"target_test_{_DB_SUFFIX}"
PG_KW = dict(user="postgres", host="localhost")
META_URL = f"postgresql://postgres@localhost/{META_DB}"
TARGET_URL = f"postgresql://postgres@localhost/{TARGET_DB}"

# ---------------------------------------------------------------------------
# Environment BEFORE any app import (see module docstring).
# agent/.env is loaded by app.py with override=False, so values set here win.
# KC/REDIS point at dead ports so external calls fail fast and are swallowed.
# ---------------------------------------------------------------------------
os.environ["APP_DB_URL"] = META_URL
os.environ["LOGGER_DISABLE_BOOT_JOBS"] = "1"
os.environ["LOGGER_ENABLE_AI"] = "0"
# app.py loads agent/.env (load_dotenv never overrides set vars): keep auth ON
# under test even if a local demo .env disables it.
os.environ["LOGGER_AUTH_DISABLED"] = "0"
os.environ["KC_URL"] = "http://127.0.0.1:1"
os.environ["KC_ADMIN_CLIENT_SECRET"] = ""
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"

if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Safe to import AFTER the env block above (fastapi itself reads no app env;
# the plc_agent app module is only imported lazily inside the client fixture).
from fastapi import Request  # noqa: E402


# ---------------------------------------------------------------------------
# Raw psycopg2 helpers (no SQLAlchemy: keeps readback independent of the app)
# ---------------------------------------------------------------------------
def _admin_conn():
    conn = psycopg2.connect(dbname="postgres", **PG_KW)
    conn.autocommit = True
    return conn


def _db_conn(dbname: str):
    conn = psycopg2.connect(dbname=dbname, **PG_KW)
    conn.autocommit = True
    return conn


def pg_query(dbname: str, sql: str, params=None):
    """Run one statement against a throwaway test DB; return rows (or None)."""
    conn = _db_conn(dbname)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description:
                return cur.fetchall()
            return None
    finally:
        conn.close()


def pg_table_exists(dbname: str, qualified: str) -> bool:
    rows = pg_query(dbname, "SELECT to_regclass(%s)", (qualified,))
    return bool(rows and rows[0][0] is not None)


def free_port() -> int:
    """An OS-assigned free TCP port (closed again => connection-refused port)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _recreate_databases() -> None:
    conn = _admin_conn()
    try:
        with conn.cursor() as cur:
            for db in (META_DB, TARGET_DB):
                # PG 13+: FORCE severs lingering pooled connections.
                cur.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
                cur.execute(f'CREATE DATABASE "{db}"')
    finally:
        conn.close()


def _drop_databases() -> None:
    conn = _admin_conn()
    try:
        with conn.cursor() as cur:
            for db in (META_DB, TARGET_DB):
                cur.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
    finally:
        conn.close()


# app_* state tables truncated between tests. app_protocol_types is
# intentionally EXCLUDED: it is seeded only by appdb.init() and the Store
# needs it to validate device protocols (truncating it would 400 every
# device-create with PROTOCOL_INVALID).
_TRUNCATE_TABLES = [
    "app_jobs",
    "app_job_runs",
    "app_device_tables",
    "app_devices",
    "app_gateways",
    "app_schemas",
    "app_schema_fields",
    "app_db_targets",
    "app_meta",
    "app_notifications",
    # Equipment data. app_equipment_category is seed data (like
    # app_protocol_types) and is deliberately NOT truncated; the built-in
    # types are re-seeded per test (clean_state) after truncation.
    "app_bus_meter",
    "app_alert_event",
    "app_alert_state",
    "app_table_alert",
    "app_schema_alert",
    "app_bus_equipment",
    "app_bus_type",
    "app_bus",
    "app_equipment",
    "app_equipment_type",
    "app_equipment_zone",
]


def _truncate_meta_tables() -> None:
    conn = _db_conn(META_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
            existing = {r[0] for r in cur.fetchall()}
            todo = [t for t in _TRUNCATE_TABLES if t in existing]
            if todo:
                cur.execute(
                    "TRUNCATE TABLE " + ", ".join(todo) + " CASCADE"
                )
    finally:
        conn.close()


def _drop_target_neuract_schema() -> None:
    conn = _db_conn(TARGET_DB)
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS neuract CASCADE")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auth override: role-parametrized fake-claims factory
# ---------------------------------------------------------------------------
# Modes: "admin" (read+write+neuract-admin), "write" (read+write),
#        "read" (logger-read only), "none" (valid token, zero roles).
_AUTH = {"mode": "admin"}


def _claims_for_mode(mode: str) -> dict:
    realm_roles = []
    resource_access = {}
    if mode in ("read", "write", "admin"):
        realm_roles.append("logger-read")
    if mode in ("write", "admin"):
        realm_roles.append("logger-write")
    if mode == "admin":
        # neuract-admin is a Keycloak *client* role => resource_access
        resource_access = {"neuract_owner": {"roles": ["neuract-admin"]}}
    return {
        "realm_access": {"roles": realm_roles},
        "resource_access": resource_access,
        "preferred_username": f"pytest-{mode}",
        "sub": "00000000-0000-4000-8000-0000000e2e01",
    }


async def _override_get_claims(request: Request) -> dict:
    """Drop-in replacement for permissions.get_claims (installed via
    app.dependency_overrides). The ``request: Request`` annotation is
    REQUIRED — without it FastAPI treats the parameter as a query param and
    every guarded route 422s. Mirrors the real dependency's side effect of
    stashing claims on request.state.auth (jobs2.start_job reads it)."""
    claims = _claims_for_mode(_AUTH["mode"])
    request.state.auth = claims
    return claims


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _databases():
    _recreate_databases()
    yield
    _drop_databases()


@pytest.fixture(scope="session")
def client(_databases):
    """Import the app (env already set above) and yield an authed TestClient.

    The default override grants admin+write+read; individual tests downgrade
    via ``auth_role`` or remove the override entirely via ``no_auth``.
    """
    from fastapi.testclient import TestClient

    from plc_agent.api import permissions
    from plc_agent.api.app import app

    app.dependency_overrides[permissions.get_claims] = _override_get_claims
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(permissions.get_claims, None)


@pytest.fixture(autouse=True)
def clean_state(client):
    """Reset DB + in-memory state BEFORE each test.

    Truncate app_* tables, drop the target neuract schema, then resync the
    singleton Store from the now-empty App DB. (Store.load_from_app_db now
    resets the _mappings cache itself — finding 9a from the test build — so
    the previous explicit ``store._mappings = {}`` workaround was removed.)
    """
    from plc_agent.api.store import Store

    _AUTH["mode"] = "admin"
    from plc_agent.api import appdb

    _truncate_meta_tables()
    appdb.seed_equipment_types()
    _drop_target_neuract_schema()
    Store.instance().load_from_app_db()
    yield


@pytest.fixture
def auth_role(client):
    """Switch the fake-claims role for the current test: auth_role('read')."""

    def _set(mode: str) -> None:
        assert mode in ("admin", "write", "read", "none")
        _AUTH["mode"] = mode

    yield _set
    _AUTH["mode"] = "admin"


@pytest.fixture
def no_auth(client):
    """Remove the get_claims override so guarded endpoints return real 401s."""
    from plc_agent.api import permissions
    from plc_agent.api.app import app

    saved = app.dependency_overrides.pop(permissions.get_claims, None)
    yield
    if saved is not None:
        app.dependency_overrides[permissions.get_claims] = saved


# ---------------------------------------------------------------------------
# Readback fixtures (no data-read REST endpoint exists; psycopg2 is the way)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def meta_query():
    return lambda sql, params=None: pg_query(META_DB, sql, params)


@pytest.fixture(scope="session")
def target_query():
    return lambda sql, params=None: pg_query(TARGET_DB, sql, params)


# ---------------------------------------------------------------------------
# Thin API helper shared by tier-1 and tier-2 tests
# ---------------------------------------------------------------------------
def modbus_row(address) -> dict:
    return {"protocol": "modbus", "address": str(address)}


class ApiHelper:
    def __init__(self, client):
        self.c = client

    def create_schema(self, name: str, fields: list) -> dict:
        r = self.c.post("/schemas", json={"name": name, "fields": fields})
        assert r.status_code == 200, f"POST /schemas -> {r.status_code}: {r.text}"
        return r.json()["item"]

    def create_pg_target(self, conn: str = TARGET_URL, default: bool = True) -> str:
        r = self.c.post("/storage/targets", json={"provider": "postgres", "conn": conn})
        assert r.status_code == 200, f"POST /storage/targets -> {r.status_code}: {r.text}"
        tid = r.json()["item"]["id"]
        if default:
            r2 = self.c.post("/storage/targets/default", json={"id": tid})
            assert r2.status_code == 200, f"set default -> {r2.status_code}: {r2.text}"
        return tid

    def create_device(self, name: str, port: int, unit_id: int = 1, host: str = "127.0.0.1") -> dict:
        """Returns the full response body: {'success': bool, 'item': ..., 'error': ...}.
        NOTE: device create runs a LIVE connection probe; against a dead port
        the response has success=False / status degraded but the device IS
        created."""
        r = self.c.post(
            "/devices",
            json={
                "name": name,
                "protocol": "modbus",
                "params": {"host": host},
                "port": port,
                "unitId": unit_id,
            },
        )
        assert r.status_code == 200, f"POST /devices -> {r.status_code}: {r.text}"
        return r.json()

    def bulk_create(self, schema_id: str, names: list, db_target_id: str, device_id=None) -> list:
        payload = {"schemaId": schema_id, "names": names, "dbTargetId": db_target_id}
        if device_id:
            payload["deviceId"] = device_id
        r = self.c.post("/tables/bulk_create", json=payload)
        assert r.status_code == 200, f"POST /tables/bulk_create -> {r.status_code}: {r.text}"
        return r.json()["items"]

    def migrate(self, ids: list) -> dict:
        # NOTE: the payload key is "ids" — GETTING_STARTED.md's "tableIds" is wrong (E2E3).
        r = self.c.post("/tables/migrate", json={"ids": ids})
        assert r.status_code == 200, f"POST /tables/migrate -> {r.status_code}: {r.text}"
        return r.json()

    def bulk_apply(self, table_id: str, device_id: str, rows: dict) -> dict:
        r = self.c.post(
            f"/mappings/{table_id}/bulk_apply",
            json={"deviceId": device_id, "rows": rows},
        )
        assert r.status_code == 200, f"POST /mappings/{table_id}/bulk_apply -> {r.status_code}: {r.text}"
        return r.json()

    def create_job(self, name: str, tables: list, interval_ms: int = 1000, jtype: str = "continuous") -> dict:
        r = self.c.post(
            "/jobs2",
            json={"name": name, "type": jtype, "tables": tables, "intervalMs": interval_ms},
        )
        assert r.status_code == 200, f"POST /jobs2 -> {r.status_code}: {r.text}"
        return r.json()["item"]

    def create_equipment(self, name: str, type_id: str, kind: str = None, category: str = "ems", **extra) -> dict:
        """An element of a seeded type; kind defaults to distribution for panels, else single."""
        kind = kind or ("distribution" if type_id in ("ht_panel", "lt_panel") else "single")
        body = {"name": name, "categoryId": category, "kind": kind, "typeId": type_id, **extra}
        r = self.c.post("/equipment", json=body)
        assert r.status_code == 200, f"POST /equipment -> {r.status_code}: {r.text}"
        return r.json()["item"]


@pytest.fixture
def api(client):
    return ApiHelper(client)


def wait_until(predicate, timeout: float, interval: float = 0.25, desc: str = "condition"):
    """Poll ``predicate`` until truthy; return its value. Raise on timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout}s waiting for {desc} (last={last!r})")
