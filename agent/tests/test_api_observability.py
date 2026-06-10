"""Tier 1 — API-consistency + Python-observability fix round.

Findings covered (ids from FINDINGS_VERIFIED.md):
  H-API-3 — single-resource business failures no longer return HTTP 200 with
            success:false: jobs2/jobs backfill -> 500 BACKFILL_WRITE_FAILED
            (no raw exception leak), mappings preview_sample stub -> 501.
  M-API-1 — status-code consistency: PATCH /tables/{id} unknown schemaId is
            now 404 (was the lone 400 for a not-found condition).
  M-OBS-1 — GET /health/ready real readiness probe (App DB SELECT 1 + Store;
            Redis reported but optional; Rust heartbeat info-only);
            GET /health stays a fast static liveness ping.
  H-OBS-3 — agent.log rotation env-tunable: LOGGER_LOG_MAX_MB (default 50),
            LOGGER_LOG_BACKUPS (default 5) — parity with the Rust engine.
  H-OBS-4 — redact_dsn() masks password components in logged conn strings.
  L12     — boot path uses logging (plc_agent.boot), no print() calls.
  J6/C3   — LOGGER_ENABLE_AI flag contract locked BOTH ways at app level
            (subprocess boots: flag=1 mounts /ai, unset does not).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import conftest as cf


# ---------------------------------------------------------------------------
# H-OBS-4 — redact_dsn unit tests
# ---------------------------------------------------------------------------
def test_redact_dsn_masks_url_password():
    from plc_agent.api.redact import redact_dsn

    assert (
        redact_dsn("postgresql://user:s3cr3t@db.example:5432/target_db")
        == "postgresql://user:***@db.example:5432/target_db"
    )
    # empty password still masked, host/db stay visible
    assert redact_dsn("postgresql://user:@h/db") == "postgresql://user:***@h/db"


def test_redact_dsn_no_password_unchanged():
    from plc_agent.api.redact import redact_dsn

    assert (
        redact_dsn("postgresql://postgres@localhost/target_version1")
        == "postgresql://postgres@localhost/target_version1"
    )
    # host:port after the '@' must never be mistaken for user:pass
    assert redact_dsn("postgresql://u@h:5432/db") == "postgresql://u@h:5432/db"


def test_redact_dsn_sqlite_and_garbage_unchanged():
    from plc_agent.api.redact import redact_dsn

    assert redact_dsn("sqlite:///C:/data/app.db") == "sqlite:///C:/data/app.db"
    assert redact_dsn("not a dsn at all") == "not a dsn at all"
    assert redact_dsn("") == ""


def test_redact_dsn_keyword_form_and_non_string():
    from plc_agent.api.redact import redact_dsn

    assert (
        redact_dsn("host=h dbname=d password=s3cr3t user=u")
        == "host=h dbname=d password=*** user=u"
    )
    # non-string input (e.g. sqlalchemy URL object) is str()-ed, not crashed on
    assert redact_dsn(None) == "None"
    assert redact_dsn(123) == "123"


# ---------------------------------------------------------------------------
# H-API-3 — backfill failures are 500 + standard envelope, no str(e) leak
# ---------------------------------------------------------------------------
def _build_startable_job(api, client, name_prefix: str):
    schema = api.create_schema(f"{name_prefix}_schema", [{"key": "v1", "type": "float32"}])
    target_id = api.create_pg_target()
    dev = api.create_device(f"{name_prefix}_dev", port=cf.free_port())
    device_id = dev["item"]["id"]
    table_id = api.bulk_create(schema["id"], [f"{name_prefix}_table"], target_id, device_id=device_id)[0]["id"]
    api.migrate([table_id])
    api.bulk_apply(table_id, device_id, {"v1": cf.modbus_row(0)})
    job = api.create_job(f"{name_prefix}_job", [table_id], interval_ms=1000)
    return job["id"]


def test_hapi3_jobs2_backfill_failure_is_500_without_leak(api, client, monkeypatch):
    from plc_agent.api.routers import jobs2 as jobs2_module

    job_id = _build_startable_job(api, client, "bf2")

    def boom(table_id):
        raise RuntimeError("SECRET-INTERNAL-DETAIL-xyzzy")

    monkeypatch.setattr(jobs2_module, "_read_mapping_values", boom)
    r = client.post(f"/jobs2/{job_id}/backfill")
    # H-API-3: was HTTP 200 + {"success": false, "message": str(e)}
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert detail["success"] is False
    assert detail["error"] == "BACKFILL_WRITE_FAILED"
    assert detail["wrote"] == 0
    assert "SECRET-INTERNAL-DETAIL-xyzzy" not in r.text  # no raw exception leak


def test_hapi3_legacy_jobs_backfill_failure_is_500_without_leak(api, client, monkeypatch):
    from plc_agent.api.routers import jobs as jobs_module

    job_id = _build_startable_job(api, client, "bf1")

    def boom(table_id, job_id=None):
        raise RuntimeError("SECRET-INTERNAL-DETAIL-xyzzy")

    monkeypatch.setattr(jobs_module, "_read_mapping_values", boom)
    r = client.post(f"/jobs/{job_id}/backfill")
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert detail["success"] is False
    assert detail["error"] == "BACKFILL_WRITE_FAILED"
    assert "SECRET-INTERNAL-DETAIL-xyzzy" not in r.text


def test_hapi3_jobs2_backfill_unknown_job_still_404(client):
    r = client.post("/jobs2/job_ghost/backfill")
    assert r.status_code == 404
    assert r.json()["detail"] == "JOB_NOT_FOUND"


def test_hapi3_preview_sample_stub_is_501(api, client):
    schema = api.create_schema("prev_schema", [{"key": "v", "type": "float32"}])
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["prev_table"], target_id)[0]["id"]
    r = client.post(f"/mappings/{table_id}/preview_sample", json={})
    # H-API-3/M-API-1: was HTTP 200 + success:false PREVIEW_NOT_IMPLEMENTED
    assert r.status_code == 501, r.text
    detail = r.json()["detail"]
    assert detail["success"] is False
    assert detail["error"] == "PREVIEW_NOT_IMPLEMENTED"
    # unknown table keeps its 404
    assert client.post("/mappings/tbl_ghost/preview_sample", json={}).status_code == 404


# ---------------------------------------------------------------------------
# H-API-3 (pinned, unchanged contracts)
# ---------------------------------------------------------------------------
def test_hapi3_device_create_partial_success_contract_kept(api):
    """POST /devices stays 200 + success:false when only the live probe fails:
    the resource IS created (partial success), so a 4xx would mislead clients
    (H-API-3 severity note). Pinned here on purpose."""
    resp = api.create_device("hapi3_dev", port=cf.free_port())
    assert resp["success"] is False
    assert resp["item"]["id"]  # created despite failed probe


def test_hapi3_quick_test_probe_result_contract_kept(api, client):
    """POST /devices/{id}/quick_test stays 200: 'the test ran, the result was
    negative' is a probe outcome, not a request failure (H-API-3)."""
    dev = api.create_device("hapi3_qt_dev", port=cf.free_port())
    r = client.post(f"/devices/{dev['item']['id']}/quick_test")
    assert r.status_code == 200
    assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# M-API-1 — PATCH /tables/{id} unknown schemaId: 400 -> 404
# ---------------------------------------------------------------------------
def test_mapi1_patch_table_unknown_schema_is_404(api, client):
    schema = api.create_schema("mapi1_schema", [{"key": "v", "type": "float32"}])
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["mapi1_table"], target_id)[0]["id"]
    r = client.patch(f"/tables/{table_id}", json={"schemaId": "sch_ghost"})
    # M-API-1: was 400 — the lone not-found returned as 400 among 404 siblings.
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "SCHEMA_NOT_FOUND"


# ---------------------------------------------------------------------------
# M-OBS-1 — /health/ready readiness probe; /health stays static liveness
# ---------------------------------------------------------------------------
def test_mobs1_health_liveness_static(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["agent"] == "plc-agent"
    assert "checks" not in body  # liveness stays cheap/static


def test_mobs1_ready_200_with_dependency_report(client):
    r = client.get("/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is True
    checks = body["checks"]
    assert checks["app_db"]["ok"] is True
    assert checks["store"]["ok"] is True
    # Harness points REDIS_URL at a dead port: redis is DOWN yet readiness
    # holds — redis is reported but optional (M-OBS-1 contract).
    assert checks["redis"]["ok"] is False
    # Rust heartbeat is info-only; bench_metrics doesn't exist in the test
    # meta DB, so it reports a status without failing readiness.
    assert checks["rust_engine"]["status"] in ("unknown", "no_data", "seen")


def test_mobs1_ready_503_when_app_db_down(client, monkeypatch):
    from plc_agent.api.routers import health as health_module

    monkeypatch.setattr(
        health_module,
        "_check_app_db",
        lambda: {"ok": False, "error": "simulated outage"},
    )
    r = client.get("/health/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["ready"] is False
    assert body["checks"]["app_db"]["ok"] is False
    # other checks still reported for diagnosis
    assert body["checks"]["store"]["ok"] is True


def test_mobs1_redis_failure_alone_never_gates_readiness(client, monkeypatch):
    from plc_agent.api.routers import health as health_module

    monkeypatch.setattr(
        health_module, "_check_redis", lambda: {"ok": False, "error": "down"}
    )
    monkeypatch.setattr(
        health_module, "_rust_engine_heartbeat", lambda: {"status": "unknown"}
    )
    r = client.get("/health/ready")
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is True


# ---------------------------------------------------------------------------
# H-OBS-3 — env-tunable log rotation (parity with Rust LOGGER_LOG_* knobs)
# ---------------------------------------------------------------------------
def test_hobs3_log_rotation_defaults(monkeypatch):
    from plc_agent.api import app as app_module

    monkeypatch.delenv("LOGGER_LOG_MAX_MB", raising=False)
    monkeypatch.delenv("LOGGER_LOG_BACKUPS", raising=False)
    max_bytes, backups = app_module._log_rotation_config()
    assert max_bytes == 50 * 1024 * 1024  # was 500 MB
    assert backups == 5  # was 999 ("keep all")


def test_hobs3_log_rotation_env_override_and_garbage(monkeypatch):
    from plc_agent.api import app as app_module

    monkeypatch.setenv("LOGGER_LOG_MAX_MB", "10")
    monkeypatch.setenv("LOGGER_LOG_BACKUPS", "3")
    assert app_module._log_rotation_config() == (10 * 1024 * 1024, 3)
    # garbage falls back to defaults; zero clamps to the 1/1 floor (same
    # .max(1) semantics as the Rust engine)
    monkeypatch.setenv("LOGGER_LOG_MAX_MB", "not-a-number")
    monkeypatch.setenv("LOGGER_LOG_BACKUPS", "0")
    max_bytes, backups = app_module._log_rotation_config()
    assert max_bytes == 50 * 1024 * 1024
    assert backups == 1


# ---------------------------------------------------------------------------
# L12 — boot path logs via plc_agent.boot, no print() left in app.py
# ---------------------------------------------------------------------------
def test_l12_no_print_in_boot_path():
    from plc_agent.api import app as app_module

    src = Path(app_module.__file__).read_text(encoding="utf-8")
    assert "print(" not in src, "L12 regression: print() back in app.py boot path"
    assert 'logging.getLogger("plc_agent.boot")' in src


# ---------------------------------------------------------------------------
# J6 — LOGGER_ENABLE_AI app-level contract, locked BOTH ways via subprocess
# boots against a scratch sqlite App DB (pattern from test_c5).
# ---------------------------------------------------------------------------
def _ai_probe_script(expect_mounted: bool) -> str:
    return textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(cf.AGENT_DIR)!r})
        from fastapi.routing import APIRoute

        from plc_agent.api.app import app

        route_paths = {{r.path for r in app.routes if isinstance(r, APIRoute)}}
        mount_paths = {{getattr(r, "path", "") for r in app.routes}}
        ai_routes = sorted(p for p in route_paths if p.startswith("/ai"))
        if {expect_mounted!r}:
            assert "/ai/sessions/{{session_id}}/chat" in ai_routes, ai_routes
            assert len(ai_routes) >= 30, "AI surface unexpectedly small: %r" % ai_routes
            print("AI_ROUTES_MOUNTED")
        else:
            assert not ai_routes, "AI routes mounted with flag OFF: %r" % ai_routes
            assert not any(p.startswith("/ai") for p in mount_paths), mount_paths
            print("AI_ROUTES_ABSENT")
        """
    )


def _boot_subprocess(tmp_path, script_body: str, *, ai_flag: str | None):
    script = tmp_path / "ai_flag_probe.py"
    script.write_text(script_body)
    env = dict(os.environ)
    # Scratch sqlite App DB — never the harness Postgres DBs, never prod.
    env["APP_DB_URL"] = f"sqlite:///{tmp_path / 'ai_probe_app.db'}"
    env["LOGGER_DISABLE_BOOT_JOBS"] = "1"
    env["KC_URL"] = "http://127.0.0.1:1"
    env["KC_ADMIN_CLIENT_SECRET"] = ""
    env["REDIS_URL"] = "redis://127.0.0.1:1/0"
    if ai_flag is None:
        env.pop("LOGGER_ENABLE_AI", None)  # truly unset -> default applies
    else:
        env["LOGGER_ENABLE_AI"] = ai_flag
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(cf.AGENT_DIR),
    )


@pytest.mark.slow
def test_j6_ai_routes_mounted_when_flag_enabled(tmp_path):
    proc = _boot_subprocess(tmp_path, _ai_probe_script(True), ai_flag="1")
    assert proc.returncode == 0, (
        f"AI-enabled boot failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "AI_ROUTES_MOUNTED" in proc.stdout


@pytest.mark.slow
def test_j6_ai_routes_absent_when_flag_unset(tmp_path):
    proc = _boot_subprocess(tmp_path, _ai_probe_script(False), ai_flag=None)
    assert proc.returncode == 0, (
        f"default boot failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "AI_ROUTES_ABSENT" in proc.stdout
