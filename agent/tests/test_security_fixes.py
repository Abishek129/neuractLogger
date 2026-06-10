"""Tier 1 — regression tests for the auth/security/API-reliability fix round.

Findings covered (ids from FINDINGS_VERIFIED.md):
  C5      — boot autostart must use jobs2 (status-mark only), never the
            legacy routers.jobs thread spawner (double-write with Rust)
  C2      — require_safe_or_write now needs logger_read on SAFE methods;
            /auth/register is admin-only (401/403 paths)
  C3/SEC-4— every /ai route carries auth; skills/import traversal hardened
  C6/SEC-3— mutating endpoints sweep (devices delete, protocol_types)
  M13     — exact issuer allowlist + optional KC_REQUIRED_AZP enforcement
  M14     — LOGGER_CORS_ORIGINS exact-origin allowlist
  M16     — bulk_import: probes opt-in via testConnections, set-based dedupe
  H-ERR-1 — jobs2 OPC UA client cache dropped on read failure
  M-OBS-4 — /shutdown admin-guarded (and never actually exits under test)
  (extra) — PUT /storage/targets/{tid} persists to the App DB
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

import conftest as cf


# ---------------------------------------------------------------------------
# C5 — boot autostart marks via jobs2; never spawns Python job threads
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_c5_boot_autostart_marks_via_jobs2_and_spawns_no_threads(
    api, client, meta_query, tmp_path
):
    """Full chain: enabled job exists -> fresh app boots WITH autostart ON in a
    subprocess -> job is marked running (jobs2 path) but the legacy
    routers.jobs thread spawner is never called and _job_threads stays empty.
    """
    # Build a startable job (schema -> target -> device -> table -> mapping).
    schema = api.create_schema(
        "c5_schema", [{"key": "v1", "type": "float32"}]
    )
    target_id = api.create_pg_target()
    dev = api.create_device("c5_dev", port=cf.free_port())
    device_id = dev["item"]["id"]
    tables = api.bulk_create(schema["id"], ["c5_table"], target_id, device_id=device_id)
    table_id = tables[0]["id"]
    api.migrate([table_id])
    api.bulk_apply(table_id, device_id, {"v1": cf.modbus_row(0)})
    r = client.post(
        "/jobs2",
        json={
            "name": "c5_job",
            "type": "continuous",
            "tables": [table_id],
            "intervalMs": 1000,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["item"]["id"]
    rows = meta_query("SELECT status FROM app_jobs WHERE id=%s", (job_id,))
    assert rows and rows[0][0] == "stopped"

    script = tmp_path / "boot_probe.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {str(cf.AGENT_DIR)!r})

            import plc_agent.api.routers.jobs as legacy_jobs
            import plc_agent.api.routers.jobs2 as jobs2

            calls = {{"legacy": 0, "jobs2": 0}}
            _legacy_orig = legacy_jobs.start_enabled_jobs_on_boot
            def _legacy_spy():
                calls["legacy"] += 1
                return _legacy_orig()
            legacy_jobs.start_enabled_jobs_on_boot = _legacy_spy
            _jobs2_orig = jobs2.start_enabled_jobs_on_boot
            def _jobs2_spy():
                calls["jobs2"] += 1
                return _jobs2_orig()
            jobs2.start_enabled_jobs_on_boot = _jobs2_spy

            # create_app() runs at import time; boot autostart is ENABLED here
            from plc_agent.api.app import app  # noqa: F401

            assert calls["legacy"] == 0, (
                "C5 REGRESSION: legacy routers.jobs.start_enabled_jobs_on_boot "
                "was called %d time(s) at boot" % calls["legacy"]
            )
            assert calls["jobs2"] == 1, (
                "jobs2.start_enabled_jobs_on_boot expected exactly once, got %d"
                % calls["jobs2"]
            )
            assert not legacy_jobs._job_threads, (
                "C5 REGRESSION: Python acquisition threads spawned at boot: %r"
                % list(legacy_jobs._job_threads)
            )
            print("C5_BOOT_OK")
            """
        )
    )
    env = dict(os.environ)
    env.pop("LOGGER_DISABLE_BOOT_JOBS", None)  # autostart ON in the subprocess
    env["LOGGER_ENABLE_AI"] = "0"
    env["APP_DB_URL"] = cf.META_URL
    env["KC_URL"] = "http://127.0.0.1:1"
    env["KC_ADMIN_CLIENT_SECRET"] = ""
    env["REDIS_URL"] = "redis://127.0.0.1:1/0"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(cf.AGENT_DIR),
    )
    assert proc.returncode == 0, (
        f"boot probe failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "C5_BOOT_OK" in proc.stdout

    # jobs2.start_enabled_jobs_on_boot marked the enabled job running.
    rows = meta_query("SELECT status FROM app_jobs WHERE id=%s", (job_id,))
    assert rows and rows[0][0] == "running", rows


# ---------------------------------------------------------------------------
# C2 — register admin-only; safe reads need logger_read
# ---------------------------------------------------------------------------
def test_c2_register_403_for_non_admin(auth_role, client):
    auth_role("write")  # read+write but NOT admin
    r = client.post(
        "/auth/register",
        json={"username": "x", "email": "x@example.invalid", "password": "p"},
    )
    assert r.status_code == 403, r.text


def test_c2_safe_methods_need_logger_read_across_protected_routers(auth_role, client):
    auth_role("none")  # valid token, zero roles
    for path in ("/storage/targets", "/jobs", "/networking/gateways", "/system/summary"):
        r = client.get(path)
        assert r.status_code == 403, f"GET {path} expected 403, got {r.status_code}"
    auth_role("read")
    for path in ("/storage/targets", "/jobs", "/networking/gateways", "/system/summary"):
        r = client.get(path)
        assert r.status_code == 200, f"GET {path} expected 200, got {r.status_code}"


# ---------------------------------------------------------------------------
# C6/SEC-3 — endpoint sweep guards
# ---------------------------------------------------------------------------
def test_sec3_device_delete_requires_write_role(auth_role, client):
    auth_role("read")
    r = client.delete("/devices/dev_does_not_exist")
    assert r.status_code == 403, r.text


def test_sec3_protocol_types_mutations_guarded(no_auth, client):
    assert client.post("/protocol_types", json={"type": "x"}).status_code == 401
    assert client.delete("/protocol_types/x").status_code == 401
    # the read stays public (pinned contract)
    assert client.get("/protocol_types").status_code == 200


def test_sec3_protocol_types_mutations_403_read_only(auth_role, client):
    auth_role("read")
    assert client.post("/protocol_types", json={"type": "x"}).status_code == 403
    assert client.delete("/protocol_types/x").status_code == 403


# ---------------------------------------------------------------------------
# M13 — issuer allowlist + optional azp enforcement
# ---------------------------------------------------------------------------
def test_m13_issuer_exact_match_against_allowlist(monkeypatch):
    from plc_agent.api import security

    monkeypatch.setattr(
        security, "KEYCLOAK_ALLOWED_ISSUERS", ["http://kc.local/realms/desktop"]
    )
    security.validate_issuer("http://kc.local/realms/desktop")  # exact -> ok
    # Same realm suffix but unknown host MUST now be rejected (was accepted
    # by the old endswith-only check).
    with pytest.raises(pyjwt.InvalidIssuerError):
        security.validate_issuer("http://evil.example/realms/desktop")


def test_m13_empty_allowlist_falls_back_to_realm_suffix(monkeypatch):
    from plc_agent.api import security

    monkeypatch.setattr(security, "KEYCLOAK_ALLOWED_ISSUERS", [])
    suffix_ok = f"http://anyhost/realms/{security.KEYCLOAK_REALM}"
    security.validate_issuer(suffix_ok)
    with pytest.raises(pyjwt.InvalidIssuerError):
        security.validate_issuer("http://anyhost/realms/other_realm")


def test_m13_azp_enforcement_off_by_default(monkeypatch):
    from plc_agent.api import security

    monkeypatch.delenv("KC_REQUIRED_AZP", raising=False)
    security.validate_azp({"azp": "anything"})  # no-op when unset


def test_m13_azp_enforcement_when_configured(monkeypatch):
    from plc_agent.api import security

    monkeypatch.setenv("KC_REQUIRED_AZP", "neuract-logger-ui, other-client")
    security.validate_azp({"azp": "neuract-logger-ui"})
    security.validate_azp({"azp": "nope", "aud": ["x", "other-client"]})
    security.validate_azp({"aud": "other-client"})
    with pytest.raises(pyjwt.InvalidAudienceError):
        security.validate_azp({"azp": "rogue", "aud": "account"})


# ---------------------------------------------------------------------------
# M14 — CORS allowlist via LOGGER_CORS_ORIGINS
# ---------------------------------------------------------------------------
def test_m14_cors_env_allowlist_disables_permissive_regex(monkeypatch):
    from plc_agent.api import app as app_module

    monkeypatch.setenv(
        "LOGGER_CORS_ORIGINS", "https://ops.example.com, http://10.0.0.5:5173"
    )
    origins, regex = app_module._cors_config()
    assert origins == ["https://ops.example.com", "http://10.0.0.5:5173"]
    assert regex is None  # no LAN/loopback/app-scheme wildcard


def test_m14_cors_default_keeps_compat_behavior(monkeypatch):
    from plc_agent.api import app as app_module

    monkeypatch.delenv("LOGGER_CORS_ORIGINS", raising=False)
    origins, regex = app_module._cors_config()
    assert "http://localhost:5173" in origins
    assert regex is not None and "tauri" in regex


# ---------------------------------------------------------------------------
# C3 — every /ai route carries an auth dependency (static assertion)
# ---------------------------------------------------------------------------
def _flat_dependency_calls(dependant):
    calls = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            calls.add(sub.call)
        calls |= _flat_dependency_calls(sub)
    return calls


# Endpoints that must demand logger_write, not just a valid token.
_AI_WRITE_PATHS = {
    "/ai/skills/import",
    "/ai/raw_read",
    "/ai/sessions/{session_id}/approve",
    "/ai/sessions/{session_id}/apply",
    "/ai/predictions/temporal/{device_id}/retrain",
    "/ai/anomaly/retrain/{model}",
    "/ai/anomaly/training-data/{model}/import",
    "/ai/marketplace/import",
    "/ai/marketplace/publish",
    "/ai/skills/{skill_id}",  # DELETE
}


def test_c3_every_ai_route_requires_auth():
    # Direct router import — does NOT mount AI into the app (flag stays off).
    from plc_agent.api.ai.router import router as ai_router
    from plc_agent.api.permissions import (
        get_claims,
        require_admin,
        require_logger_read,
        require_logger_write,
    )

    auth_deps = {get_claims, require_admin, require_logger_read, require_logger_write}
    api_routes = [r for r in ai_router.routes if isinstance(r, APIRoute)]
    assert len(api_routes) >= 30  # sanity: the surface is really there

    unguarded = []
    for route in api_routes:
        calls = _flat_dependency_calls(route.dependant)
        if not (calls & auth_deps):
            unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert not unguarded, f"/ai routes without auth dependency: {unguarded}"


def test_c3_destructive_ai_routes_require_logger_write():
    from plc_agent.api.ai.router import router as ai_router
    from plc_agent.api.permissions import require_logger_write

    missing = []
    seen = set()
    for route in ai_router.routes:
        if not isinstance(route, APIRoute) or route.path not in _AI_WRITE_PATHS:
            continue
        if route.path == "/ai/skills/{skill_id}" and "DELETE" not in route.methods:
            continue  # GET variant only needs a valid token
        seen.add(route.path)
        if require_logger_write not in _flat_dependency_calls(route.dependant):
            missing.append(f"{sorted(route.methods)} {route.path}")
    assert not missing, f"destructive /ai routes without logger_write: {missing}"
    assert seen == _AI_WRITE_PATHS, f"sweep drift — paths not found: {_AI_WRITE_PATHS - seen}"


# ---------------------------------------------------------------------------
# SEC-4 — skills import path traversal
# ---------------------------------------------------------------------------
def test_sec4_skills_import_traversal_contained(tmp_path, monkeypatch):
    from plc_agent.api.ai import router as ai_router_module

    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(ai_router_module, "_SKILLS_DIR", skills_dir)

    body = {
        "skills": [
            {
                "name": "good_skill",
                "files": {
                    "SKILL.md": "legit",
                    "../../escape.md": "traversal",
                    "/etc/abs_path.md": "absolute",
                    "..\\win_escape.md": "windows",
                    "payload.py": "import os",  # extension not whitelisted
                },
            },
            {"name": "../outside", "files": {"a.md": "x"}},  # bad name -> skipped
            {"name": "bad/slash", "files": {"a.md": "x"}},  # bad name -> skipped
        ]
    }
    res = ai_router_module.import_skills(body)
    assert res["imported"] == 1

    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    # every written file is INSIDE skills/good_skill, basenames only,
    # whitelisted extensions only
    assert written == [
        "skills/good_skill/SKILL.md",
        "skills/good_skill/abs_path.md",
        "skills/good_skill/escape.md",
        "skills/good_skill/win_escape.md",
    ], written
    assert not (tmp_path / "escape.md").exists()
    assert (skills_dir / "good_skill" / "SKILL.md").read_text() == "legit"


def test_sec4_skill_id_traversal_rejected(tmp_path, monkeypatch):
    from plc_agent.api.ai import router as ai_router_module

    monkeypatch.setattr(ai_router_module, "_SKILLS_DIR", tmp_path / "skills")
    for bad in ("../sibling", "..", "a/b", "a\\b"):
        with pytest.raises(HTTPException) as exc:
            ai_router_module.delete_skill(bad)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            ai_router_module.get_skill(bad)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# H-ERR-1 — jobs2 OPC UA cache dropped on read failure
# ---------------------------------------------------------------------------
def test_herr1_opcua_client_dropped_on_read_failure(client):
    from plc_agent.api.routers import jobs2
    from plc_agent.api.store import Store

    store = Store.instance()
    endpoint = "opc.tcp://h-err-1.invalid:4840"
    dev = store.add_device(
        {"name": "herr1_dev", "protocol": "opcua", "params": {"endpoint": endpoint}}
    )
    table_id = "tbl_herr1"
    store._mappings[table_id] = {
        "deviceId": dev["id"],
        "rows": {"f1": {"protocol": "opcua", "address": "ns=2;i=2"}},
    }

    class DeadClient:
        def get_node(self, nid):
            raise RuntimeError("BadSessionIdInvalid")

    with jobs2._opcua_lock:
        jobs2._opcua_clients[endpoint] = DeadClient()
    try:
        values = jobs2._read_mapping_values(table_id)
        assert values == {"f1": None}
        # H-ERR-1: the dead cached client must be evicted so the next call
        # reconnects instead of returning None forever.
        with jobs2._opcua_lock:
            assert endpoint not in jobs2._opcua_clients, (
                "dead OPC UA client still cached after read failure"
            )
    finally:
        jobs2._drop_opcua_client(endpoint)
        store._mappings.pop(table_id, None)


# ---------------------------------------------------------------------------
# Storage target update persistence (E2E extra observation)
# ---------------------------------------------------------------------------
def test_storage_target_update_persists_across_reload(api, client):
    from plc_agent.api.store import Store

    tid = api.create_pg_target(default=False)
    r = client.put(f"/storage/targets/{tid}", json={"lastMsg": "persist-me", "status": "ok"})
    assert r.status_code == 200, r.text

    Store.instance().load_from_app_db()  # simulate restart
    cur = Store.instance().get_db_target(tid)
    assert cur is not None
    # NOTE: load_from_app_db hydrates the DB column name (last_msg) while the
    # live dict uses lastMsg — pre-existing store.py naming quirk, not part of
    # this fix; accept either spelling.
    assert (cur.get("lastMsg") or cur.get("last_msg")) == "persist-me"
    assert cur.get("status") == "ok"


# ---------------------------------------------------------------------------
# M16 — bulk import: probes opt-in, dedupe via dict
# ---------------------------------------------------------------------------
def test_m16_bulk_import_skips_probe_by_default(client, monkeypatch):
    from plc_agent.api.store import Store

    store = Store.instance()
    calls = []

    def fake_probe(proto, params, **extra):
        calls.append((proto, extra))
        return False, None, "DEAD_HOST"

    monkeypatch.setattr(store, "test_device_params", fake_probe)
    payload = {
        "devices": [
            {"name": "m16_a", "ip": "10.9.9.1", "port": 502, "unit": 1},
            {"name": "m16_a", "ip": "10.9.9.1", "port": 502, "unit": 1},  # dup row
            {"name": "m16_b", "ip": "10.9.9.2", "port": 502, "unit": 2},
        ]
    }
    r = client.post("/bulk_import/devices", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert calls == [], "live connection probe ran despite testConnections=false"
    assert body["summary"]["created_devices"] == 2
    assert body["summary"]["skipped"] == 1  # in-payload duplicate deduped
    created = [row for row in body["results"] if row["status"] == "created"]
    # response shape unchanged: probe keys present, just null without probes
    for row in created:
        assert row["connected"] is None
        assert row["latencyMs"] is None
        assert row["connectionError"] is None
    # device not marked degraded by a probe that never ran
    dev = next(d for d in store.list_devices() if d["name"] == "m16_a")
    assert dev.get("status") != "degraded"


def test_m16_bulk_import_probe_opt_in(client, monkeypatch):
    from plc_agent.api.store import Store

    store = Store.instance()
    calls = []

    def fake_probe(proto, params, **extra):
        calls.append(proto)
        return False, None, "DEAD_HOST"

    monkeypatch.setattr(store, "test_device_params", fake_probe)
    payload = {
        "testConnections": True,
        "devices": [{"name": "m16_c", "ip": "10.9.9.3", "port": 502, "unit": 1}],
    }
    r = client.post("/bulk_import/devices", json=payload)
    assert r.status_code == 200, r.text
    assert calls == ["modbus"]
    row = r.json()["results"][0]
    assert row["connected"] is False
    assert row["connectionError"] == "DEAD_HOST"
    dev = next(d for d in store.list_devices() if d["name"] == "m16_c")
    assert dev.get("status") == "degraded"


# ---------------------------------------------------------------------------
# M-OBS-4 — /shutdown admin guard (never actually exits under test)
# ---------------------------------------------------------------------------
def test_mobs4_shutdown_401_anonymous(no_auth, client):
    r = client.post("/shutdown")
    assert r.status_code == 401, r.text


def test_mobs4_shutdown_403_non_admin(auth_role, client):
    auth_role("write")  # read+write, no neuract-admin
    r = client.post("/shutdown")
    assert r.status_code == 403, r.text


def test_mobs4_shutdown_admin_schedules_exit(client, monkeypatch):
    from plc_agent.api.routers import health as health_module

    scheduled = []

    class FakeTimer:
        def __init__(self, delay, fn):
            scheduled.append((delay, fn))

        def start(self):  # never run fn -> os._exit never fires in tests
            pass

    monkeypatch.setattr(health_module, "Timer", FakeTimer)
    r = client.post("/shutdown")  # default fixture mode is admin
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert len(scheduled) == 1 and scheduled[0][0] == 0.2
