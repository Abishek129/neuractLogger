"""Tier 1 — full happy-path workflow chain at API level (no Rust engine).

schema (regular + derived formula field) -> postgres storage target (+default)
-> device (live probe against a dead port => degraded but created)
-> tables bulk_create -> migrate {"ids": [...]} (physical table + auto derived
mapping rows in target DB) -> mappings bulk_apply (derived keys silently
stripped) -> jobs2 create + start (status flips to running; nothing executes
without the Rust engine) -> stop -> delete.
"""
from __future__ import annotations

import conftest as cf


SCHEMA_FIELDS = [
    {"key": "voltage", "type": "float32"},
    {"key": "current", "type": "float32"},
    {"key": "power", "type": "float32"},
    # Derived field: evaluated by the Rust engine from the same read
    {"key": "s_check", "type": "float64", "formula": "voltage*current"},
]


def test_full_workflow_chain(api, client, meta_query, target_query):
    # ---- 1. schema with regular + derived fields --------------------------
    schema = api.create_schema("wf_mfm", SCHEMA_FIELDS)
    schema_id = schema["id"]
    by_key = {f["key"]: f for f in schema["fields"]}
    assert by_key["s_check"]["formula"] == "voltage*current"
    assert by_key["s_check"].get("eval_order") == 0  # only derived field => first

    # ---- 2. storage target (postgres) + default ---------------------------
    target_id = api.create_pg_target()
    r = client.get("/storage/targets")
    assert r.status_code == 200
    assert r.json()["defaultId"] == target_id

    # ---- 3. device — live probe against a dead port -----------------------
    dead_port = cf.free_port()
    dev_resp = api.create_device("wf_dev", port=dead_port, unit_id=1)
    # The create endpoint probes the device live; with nothing listening it
    # reports failure BUT still persists the device.
    assert dev_resp["success"] is False
    device_id = dev_resp["item"]["id"]
    assert dev_resp["item"]["status"] in ("degraded", "reconnecting")
    r = client.get("/devices")
    assert any(d["id"] == device_id for d in r.json()["items"])

    # ---- 4. tables bulk_create --------------------------------------------
    items = api.bulk_create(schema_id, ["wf_table_1"], target_id, device_id=device_id)
    assert len(items) == 1
    table_id = items[0]["id"]
    assert items[0]["status"] == "not_migrated"

    # ---- 5. migrate {"ids": [...]} -----------------------------------------
    res = api.migrate([table_id])
    assert res["items"][0]["status"] in ("created", "updated")

    # physical table exists in target DB with all schema columns
    assert cf.pg_table_exists(cf.TARGET_DB, "neuract.wf_table_1")
    cols = {
        r[0]
        for r in target_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='neuract' AND table_name='wf_table_1'"
        )
    }
    assert {"timestamp_utc", "voltage", "current", "power", "s_check"} <= cols

    # derived formula auto-populated into neuract.device_mappings
    rows = target_query(
        "SELECT protocol, address, scale FROM neuract.device_mappings "
        "WHERE table_name=%s AND field_key=%s",
        ("wf_table_1", "s_check"),
    )
    assert rows, "migrate did not write the derived mapping row"
    proto, address, scale = rows[0]
    assert proto == "derived"
    assert address == "voltage*current"
    assert scale == 0.0  # scale column reused for eval_order

    # table status flipped in meta DB
    status = meta_query(
        "SELECT status FROM app_device_tables WHERE id=%s", (table_id,)
    )[0][0]
    assert status == "migrated"

    # ---- 6. mappings bulk_apply — derived keys silently stripped ----------
    apply_resp = api.bulk_apply(
        table_id,
        device_id,
        rows={
            "voltage": cf.modbus_row(0),
            "current": cf.modbus_row(2),
            "power": cf.modbus_row(12),
            # Manual attempt to map the derived field MUST be ignored:
            "s_check": cf.modbus_row(99),
        },
    )
    applied_rows = apply_resp["item"]["rows"]
    assert "s_check" not in applied_rows, "derived key was not stripped from manual rows"
    assert set(applied_rows) == {"voltage", "current", "power"}
    # ... and the derived row in the target DB is untouched
    rows = target_query(
        "SELECT protocol, address FROM neuract.device_mappings "
        "WHERE table_name=%s AND field_key=%s",
        ("wf_table_1", "s_check"),
    )
    assert rows[0] == ("derived", "voltage*current")
    # the three manual modbus rows landed
    n_modbus = target_query(
        "SELECT count(*) FROM neuract.device_mappings "
        "WHERE table_name=%s AND protocol='modbus'",
        ("wf_table_1",),
    )[0][0]
    assert n_modbus == 3

    # ---- 7. jobs2 create + start (status only; no execution in tier 1) ----
    job = api.create_job("wf_job", [table_id], interval_ms=1000)
    job_id = job["id"]
    assert job["status"] == "stopped"

    r = client.post(f"/jobs2/{job_id}/start")
    assert r.status_code == 200 and r.json()["success"] is True
    # status flipped in memory and in the meta DB (the Rust engine polls this)
    jobs = {j["id"]: j for j in client.get("/jobs2").json()["items"]}
    assert jobs[job_id]["status"] == "running"
    assert meta_query("SELECT status FROM app_jobs WHERE id=%s", (job_id,))[0][0] == "running"

    # No engine in tier 1 => nothing may be written to the physical table
    assert target_query("SELECT count(*) FROM neuract.wf_table_1")[0][0] == 0

    # ---- 8. stop -> delete --------------------------------------------------
    r = client.post(f"/jobs2/{job_id}/stop")
    assert r.status_code == 200
    assert meta_query("SELECT status FROM app_jobs WHERE id=%s", (job_id,))[0][0] == "stopped"

    r = client.delete(f"/jobs2/{job_id}")
    assert r.status_code == 200 and r.json()["success"] is True
    assert all(j["id"] != job_id for j in client.get("/jobs2").json()["items"])
    assert meta_query("SELECT count(*) FROM app_jobs WHERE id=%s", (job_id,))[0][0] == 0


def test_bulk_create_pattern_expansion(api):
    schema = api.create_schema("wf_pat", [{"key": "v", "type": "float32"}])
    target_id = api.create_pg_target()
    items = api.bulk_create(schema["id"], ["mfm_{1..3}"], target_id)
    assert [t["name"] for t in items] == ["mfm_1", "mfm_2", "mfm_3"]
