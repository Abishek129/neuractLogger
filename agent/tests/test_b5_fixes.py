"""Tier 1 — B5 fixes from the Logger v2 asks (A5).

* DELETE /mappings/{tableId}/{fieldKey} persists (the row used to come back
  from the user DB on the next table load);
* POST /mappings/{tableId}/import refuses a body without rows and replaces
  only with an explicit "mode": "replace" (an unknown body used to wipe);
* migrate failures are 4xx/500 MIGRATE_FAILED; 404 only for an unknown table.
"""
from __future__ import annotations

import conftest as cf


def _table(api):
    schema = api.create_schema("b5_mfm", [
        {"key": "v", "type": "float32"}, {"key": "i", "type": "float32"}, {"key": "p", "type": "float32"},
        {"key": "s", "type": "float64", "formula": "v*i"},
    ])
    target = api.create_pg_target()
    dev = api.create_device("b5_dev", port=cf.free_port())["item"]["id"]
    table = api.bulk_create(schema["id"], ["b5_table"], target, device_id=dev)[0]
    api.migrate([table["id"]])
    rows = {k: cf.modbus_row(n) for k, n in (("v", 0), ("i", 2), ("p", 4))}
    api.bulk_apply(table["id"], dev, rows)
    return table["id"], dev


def _keys(target_query):
    return sorted(r[0] for r in target_query(
        "SELECT field_key FROM neuract.device_mappings WHERE table_name='b5_table'"))


def test_row_delete_persists(api, client, target_query):
    tid, _ = _table(api)
    assert _keys(target_query) == ["i", "p", "s", "v"]
    r = client.delete(f"/mappings/{tid}/p")
    assert r.status_code == 200, r.text
    assert _keys(target_query) == ["i", "s", "v"]
    client.get("/tables")  # re-hydrates mappings from the user DB
    rows = client.get(f"/mappings/{tid}").json()["item"]["rows"]
    assert "p" not in rows and "v" in rows
    # Derived rows are engine-owned.
    r = client.delete(f"/mappings/{tid}/s")
    assert r.status_code == 400 and r.json()["detail"].startswith("DERIVED_ROW")
    assert "s" in _keys(target_query)


def test_import_never_wipes_by_accident(api, client, target_query):
    tid, dev = _table(api)
    for bad in ({"mappings": [{"field_key": "v"}]}, {}, {"rows": [1]}):
        r = client.post(f"/mappings/{tid}/import", json=bad)
        assert r.status_code == 400 and r.json()["detail"].startswith("ROWS_REQUIRED"), r.text
    assert _keys(target_query) == ["i", "p", "s", "v"]
    r = client.post(f"/mappings/{tid}/import", json={"rows": {}, "mode": "wipe"})
    assert r.status_code == 400 and r.json()["detail"].startswith("MODE_INVALID")

    # Default = merge: other rows stay.
    r = client.post(f"/mappings/{tid}/import", json={"rows": {"v": cf.modbus_row(10)}})
    assert r.status_code == 200 and r.json()["mode"] == "merge"
    assert _keys(target_query) == ["i", "p", "s", "v"]
    addr = target_query("SELECT address FROM neuract.device_mappings WHERE table_name='b5_table' AND field_key='v'")
    assert addr[0][0] == "10"

    # Explicit replace drops the non-derived rows not sent (derived kept).
    r = client.post(f"/mappings/{tid}/import", json={"rows": {"v": cf.modbus_row(0)}, "mode": "replace", "deviceId": dev})
    assert r.status_code == 200 and r.json()["mode"] == "replace"
    assert _keys(target_query) == ["s", "v"]


def test_migrate_status_codes(api, client, monkeypatch):
    r = client.post("/tables/tbl_nope/migrate")
    assert r.status_code == 404 and r.json()["detail"] == "TABLE_NOT_FOUND"

    tid, _ = _table(api)
    from plc_agent.api.routers import tables as tables_router

    def boom(*a, **k):
        raise RuntimeError("target unreachable")

    monkeypatch.setattr(tables_router, "_migrate_one", boom)
    r = client.post(f"/tables/{tid}/migrate")
    assert r.status_code == 500 and r.json()["detail"] == "MIGRATE_FAILED: target unreachable"

    from fastapi import HTTPException

    def refused(*a, **k):
        raise HTTPException(status_code=409, detail="TABLE_HAS_RUNNING_JOBS")

    monkeypatch.setattr(tables_router, "_migrate_one", refused)
    r = client.post(f"/tables/{tid}/migrate")
    assert r.status_code == 409 and r.json()["detail"] == "MIGRATE_FAILED: TABLE_HAS_RUNNING_JOBS"


def test_save_repairs_old_mapping_table_without_encoding(api, client, target_query):
    """A v1-era neuract.device_mappings has no encoding column: every save used
    to fail silently (200, nothing stored). The column is now added on use."""
    schema = api.create_schema("b5_old", [{"key": "v", "type": "float32"}])
    target = api.create_pg_target()
    dev = api.create_device("b5_old_dev", port=cf.free_port())["item"]["id"]
    tid = api.bulk_create(schema["id"], ["b5_old_t"], target, device_id=dev)[0]["id"]
    target_query("CREATE SCHEMA IF NOT EXISTS neuract")
    target_query("DROP TABLE IF EXISTS neuract.device_mappings")
    target_query(
        "CREATE TABLE neuract.device_mappings (table_name TEXT NOT NULL, field_key TEXT NOT NULL, protocol TEXT,"
        " address TEXT, data_type TEXT, scale REAL, deadband REAL, device_id TEXT, PRIMARY KEY (table_name, field_key))"
    )
    body = {"mappings": [{"field_key": "v", "protocol": "modbus", "address": "40001", "data_type": "float", "scale": 1}],
            "deviceId": dev}
    try:
        r = client.post(f"/tables/{tid}/mappings/bulk", json=body)
        assert r.status_code == 200, r.text
        assert client.get(f"/mappings/{tid}").json()["item"]["rows"]["v"]["address"] == "40001"
        assert target_query("SELECT encoding FROM neuract.device_mappings WHERE table_name='b5_old_t'") == [("float32",)]
    finally:
        target_query("DROP TABLE neuract.device_mappings")


def test_failed_mapping_save_is_an_error_not_200(api, client, target_query):
    schema = api.create_schema("b5_bad", [{"key": "v", "type": "float32"}])
    target = api.create_pg_target()
    dev = api.create_device("b5_bad_dev", port=cf.free_port())["item"]["id"]
    tid = api.bulk_create(schema["id"], ["b5_bad_t"], target, device_id=dev)[0]["id"]
    target_query("CREATE SCHEMA IF NOT EXISTS neuract")
    target_query("DROP TABLE IF EXISTS neuract.device_mappings")
    # address is NOT NULL here, so a row without one cannot be stored.
    target_query(
        "CREATE TABLE neuract.device_mappings (table_name TEXT NOT NULL, field_key TEXT NOT NULL, protocol TEXT,"
        " address TEXT NOT NULL, data_type TEXT, scale REAL, deadband REAL, device_id TEXT, encoding TEXT,"
        " PRIMARY KEY (table_name, field_key))"
    )
    try:
        r = client.post(f"/mappings/{tid}/import", json={"rows": {"v": {"protocol": "modbus", "address": None}}, "deviceId": dev})
        assert r.status_code == 500 and r.json()["detail"].startswith("MAPPING_SAVE_FAILED: v"), r.text
    finally:
        target_query("DROP TABLE neuract.device_mappings")
