"""Tier 1 — RBAC / auth matrix.

Asserts CURRENT behavior:
  * guarded POSTs without a token        -> 401
  * read-only role on write endpoints    -> 403
  * write role on write endpoints        -> 200
  * every GET needs a token              -> 401 without one

GET /schemas, /tables, /devices and /jobs2 used to be public; their routers
are now mounted behind require_safe_or_write like the rest (B4). The
neuract-admin client role counts as read + write.
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


def test_formerly_public_gets_need_a_token(no_auth, client):
    # These GETs used to be public; every read now needs a token (B4).
    for path in PUBLIC_GETS:
        r = client.get(path)
        assert r.status_code == 401, f"GET {path} expected 401, got {r.status_code}"


def test_formerly_public_gets_with_read_role(auth_role, client):
    auth_role("read")
    for path in PUBLIC_GETS:
        assert client.get(path).status_code == 200, path


def test_neuract_admin_client_role_can_write(client, monkeypatch):
    """A token whose only role is the neuract-admin client role (as in existing
    Keycloak setups, resource_access["neuract-logger"]) may read and write."""
    import conftest as cf

    claims = {"realm_access": {"roles": []}, "resource_access": {"neuract-logger": {"roles": ["neuract-admin"]}},
              "preferred_username": "contract-admin", "sub": "x"}
    monkeypatch.setattr(cf, "_claims_for_mode", lambda mode: claims)
    assert client.get("/equipment/categories").status_code == 200
    r = client.post("/equipment", json={"name": "ADMIN-W", "categoryId": "ems", "kind": "single", "typeId": "load"})
    assert r.status_code == 200, r.text


def test_storage_get_requires_token(no_auth, client):
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
