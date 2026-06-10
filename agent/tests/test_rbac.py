"""Tier 1 — RBAC / auth matrix.

Asserts CURRENT behavior:
  * guarded POSTs without a token        -> 401
  * read-only role on write endpoints    -> 403
  * write role on write endpoints        -> 200
  * public GETs without any token        -> 200  (see note below)

NOTE (under review): GET /schemas, /tables, /devices and /jobs2 are
intentionally PUBLIC today — their routers are mounted without auth
(app.py "Public routers" / "Unprotected legacy router" comments) and only
the mutating endpoints carry per-endpoint Depends(require_logger_write).
By contrast GET /storage/targets sits behind router-level
require_safe_or_write and needs a valid token. This inconsistency is an
audit item; these tests pin the current contract so any future hardening
shows up as an explicit, reviewed test change.
"""
from __future__ import annotations

import conftest as cf


GUARDED_POSTS = [
    ("/schemas", {"name": "x", "fields": [{"key": "v", "type": "float32"}]}),
    ("/devices", {"name": "x", "protocol": "modbus", "params": {"host": "127.0.0.1"}, "port": 1, "unitId": 1}),
    ("/tables/bulk_create", {"schemaId": "nope", "names": ["t1"]}),
    ("/tables/migrate", {"ids": ["nope"]}),
    ("/jobs2", {"name": "x", "type": "continuous", "tables": ["nope"]}),
    ("/jobs2/nope/start", {}),
    ("/storage/targets", {"provider": "postgres", "conn": cf.TARGET_URL}),
    ("/mappings/nope/bulk_apply", {"rows": {}}),
]

PUBLIC_GETS = ["/schemas", "/tables", "/devices", "/jobs2"]


def test_guarded_posts_401_without_token(no_auth, client):
    for path, payload in GUARDED_POSTS:
        r = client.post(path, json=payload)
        assert r.status_code == 401, f"POST {path} expected 401, got {r.status_code}: {r.text}"


def test_guarded_posts_403_with_read_only_role(auth_role, client):
    auth_role("read")
    for path, payload in GUARDED_POSTS:
        r = client.post(path, json=payload)
        assert r.status_code == 403, f"POST {path} expected 403, got {r.status_code}: {r.text}"


def test_write_role_can_write(auth_role, client):
    auth_role("write")
    r = client.post("/schemas", json={"name": "rbac_w", "fields": [{"key": "v", "type": "float32"}]})
    assert r.status_code == 200, r.text
    r = client.post("/storage/targets", json={"provider": "postgres", "conn": cf.TARGET_URL})
    assert r.status_code == 200, r.text


def test_public_gets_200_without_token(no_auth, client):
    # Intentionally public today (under review) — see module docstring.
    for path in PUBLIC_GETS:
        r = client.get(path)
        assert r.status_code == 200, f"GET {path} expected 200 (public), got {r.status_code}"


def test_storage_get_requires_token_unlike_other_gets(no_auth, client):
    # The documented inconsistency: /storage GET is token-gated while the
    # GETs above are public.
    r = client.get("/storage/targets")
    assert r.status_code == 401


def test_roleless_token_cannot_read_safe_endpoints(auth_role, client):
    # C2 remainder FIXED: require_safe_or_write now demands logger_read (or
    # write/admin) even on SAFE methods — a merely-valid, role-less token gets
    # 403 instead of read access to every protected router (permissions.py).
    auth_role("none")
    r = client.get("/storage/targets")
    assert r.status_code == 403
    # ...and still cannot write
    r = client.post("/storage/targets", json={"provider": "postgres", "conn": cf.TARGET_URL})
    assert r.status_code == 403


def test_read_role_can_read_safe_endpoints(auth_role, client):
    # logger-read is sufficient for SAFE methods on protected routers (C2).
    auth_role("read")
    r = client.get("/storage/targets")
    assert r.status_code == 200
