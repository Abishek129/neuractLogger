"""Tier 1 — Logger v2 "high" feature gaps: F1 (jobs2 GET/PATCH), F3/F4
(schema GET/rename/description), F5 (DB-managed field types + units), F7
(device address edit), F8 (saved verification), F10 (resume)."""
from __future__ import annotations

import conftest as cf


def _job_setup(api, name="hf"):
    schema = api.create_schema(f"{name}_s", [{"key": "v", "type": "float32", "unit": "V"}])
    target = api.create_pg_target()
    dev = api.create_device(f"{name}_dev", port=cf.free_port())["item"]["id"]
    tbl = api.bulk_create(schema["id"], [f"{name}_t"], target, device_id=dev)[0]["id"]
    api.migrate([tbl])
    api.bulk_apply(tbl, dev, {"v": cf.modbus_row(0)})
    return schema, tbl, dev


# ---------- F1 + F10: jobs2 ----------
def test_jobs2_get_patch_resume(api, client):
    _, tbl, _ = _job_setup(api)
    job = api.create_job("hf_job", [tbl])
    jid = job["id"]
    r = client.get(f"/jobs2/{jid}")
    assert r.status_code == 200 and r.json()["item"]["name"] == "hf_job"
    assert client.get("/jobs2/job_nope").status_code == 404

    r = client.patch(f"/jobs2/{jid}", json={"name": "hf_job2", "intervalMs": 5000, "cpuBudget": "low", "enabled": True})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert (item["name"], item["intervalMs"], item["cpuBudget"], item["enabled"]) == ("hf_job2", 5000, "low", True)
    assert client.get("/jobs2").json()["items"][0]["intervalMs"] == 5000
    for bad, code in (({"intervalMs": 10}, "INTERVAL_INVALID"), ({"type": "scheduled"}, "TYPE_INVALID"),
                      ({"tables": []}, "NO_TABLES"), ({"cpuBudget": "max"}, "CPU_BUDGET_INVALID"), ({"name": ""}, "NAME_REQUIRED")):
        r = client.patch(f"/jobs2/{jid}", json=bad)
        assert r.status_code == 400 and r.json()["detail"].startswith(code), (bad, r.text)

    # Running jobs cannot be edited (the engine reads config only at start).
    client.post(f"/jobs2/{jid}/start")
    r = client.patch(f"/jobs2/{jid}", json={"intervalMs": 2000})
    assert r.status_code == 409 and r.json()["detail"].startswith("JOB_RUNNING")
    # Resume only from paused.
    r = client.post(f"/jobs2/{jid}/resume")
    assert r.status_code == 409 and r.json()["detail"].startswith("JOB_NOT_PAUSED")
    client.post(f"/jobs2/{jid}/pause")
    assert client.patch(f"/jobs2/{jid}", json={"intervalMs": 2000}).status_code == 200  # paused: editable
    r = client.post(f"/jobs2/{jid}/resume")
    assert r.status_code == 200 and client.get(f"/jobs2/{jid}").json()["item"]["status"] == "running"
    client.post(f"/jobs2/{jid}/stop")


# ---------- F3 + F4: schemas ----------
def test_schema_get_rename_description(api, client):
    s1 = client.post("/schemas", json={"name": "LT Panel", "description": "Main LT meters",
                                       "fields": [{"key": "v", "type": "float32"}]}).json()["item"]
    s2 = api.create_schema("HT Panel", [{"key": "v", "type": "float32"}])
    r = client.get(f"/schemas/{s1['id']}")
    assert r.status_code == 200 and r.json()["item"]["description"] == "Main LT meters"
    assert client.get("/schemas/sch_nope").status_code == 404

    r = client.patch(f"/schemas/{s1['id']}", json={"name": "LT Panel v2", "description": None})
    assert r.status_code == 200 and (r.json()["item"]["name"], r.json()["item"]["description"]) == ("LT Panel v2", None)
    r = client.patch(f"/schemas/{s2['id']}", json={"name": "lt panel V2"})
    assert r.status_code == 409 and r.json()["detail"].startswith("SCHEMA_EXISTS")
    assert client.patch(f"/schemas/{s2['id']}", json={"name": "  "}).status_code == 400
    names = {s["name"] for s in client.get("/schemas").json()["items"]}
    assert {"LT Panel v2", "HT Panel"} <= names
    # Static routes still win over /schemas/{id}.
    assert "schemas" in client.get("/schemas/export").json()


# ---------- F5: DB-managed field types + units ----------
def test_field_types_and_units(api, client, target_query):
    types = {t["id"]: t for t in client.get("/schemas/field_types").json()["items"]}
    assert types["real"]["encoding"] == "float32" and types["boolean"]["encoding"] == "bool16"
    assert types["float32"]["encoding"] == "float32"
    units = {u["id"] for u in client.get("/schemas/units").json()["items"]}
    assert {"V", "kW", "kWh", "%"} <= units

    # Old words are accepted (case-insensitive) and round-trip.
    r = client.post("/schemas", json={"name": "legacy", "fields": [
        {"key": "v", "type": "REAL", "unit": "V"}, {"key": "flag", "type": "boolean"},
        {"key": "s", "type": "real", "formula": "v*2"}]})
    assert r.status_code == 200, r.text
    by_key = {f["key"]: f for f in r.json()["item"]["fields"]}
    assert by_key["v"]["type"] == "real" and by_key["flag"]["type"] == "boolean"
    sid = r.json()["item"]["id"]
    assert client.patch(f"/schemas/{sid}/fields/v", json={"unit": "kV"}).status_code == 200

    for bad, code in (({"key": "x", "type": "decimal"}, "FIELD_TYPE_INVALID"), ({"key": "x", "type": "float32", "unit": "parsecs"}, "UNIT_INVALID"),
                      ({"key": "x", "type": "boolean", "formula": "v*1"}, "FIELD_TYPE_INVALID")):
        r = client.post(f"/schemas/{sid}/fields", json=bad)
        assert r.status_code == 400 and r.json()["detail"].startswith(code), (bad, r.text)

    # The mapping row gets the decoding, not the word: REAL decodes as float32.
    target = api.create_pg_target()
    dev = api.create_device("legacy_dev", port=cf.free_port())["item"]["id"]
    tbl = api.bulk_create(sid, ["legacy_t"], target, device_id=dev)[0]["id"]
    api.migrate([tbl])
    api.bulk_apply(tbl, dev, {"v": cf.modbus_row(0), "flag": cf.modbus_row(2)})
    enc = dict(target_query("SELECT field_key, encoding FROM neuract.device_mappings WHERE table_name='legacy_t' AND protocol='modbus'"))
    assert enc == {"v": "float32", "flag": "bool16"}


# ---------- F7 + F8: devices ----------
def test_device_address_edit_and_verification(api, client):
    dead = cf.free_port()
    dev = api.create_device("edit_me", port=dead, host="127.0.0.1")["item"]
    did = dev["id"]

    # quick_test keeps its result; GET /devices returns it.
    r = client.post(f"/devices/{did}/quick_test")
    v = r.json()["verification"]
    assert v["ok"] is False and v["error"] and v["at"].endswith("Z")
    listed = next(d for d in client.get("/devices").json()["items"] if d["id"] == did)
    assert listed["verification"] == v

    # Editing the address applies it, resets status and clears the verification.
    r = client.put(f"/devices/{did}", json={"params": {"host": "10.20.1.90"}, "unitId": 7})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["params"]["host"] == "10.20.1.90" and item["unitId"] == 7
    assert item["status"] == "disconnected" and item["verification"] is None
    again = next(d for d in client.get("/devices").json()["items"] if d["id"] == did)
    assert again["params"]["host"] == "10.20.1.90" and again["verification"] is None

    # Survives a reload from the DB.
    from plc_agent.api.store import Store
    Store.instance().load_from_app_db()
    assert Store.instance().get_device(did)["params"]["host"] == "10.20.1.90"

    r = client.put(f"/devices/{did}", json={"protocol": "opcua", "params": {"endpoint": "opc.tcp://10.0.0.5:4840"}})
    assert r.status_code == 200 and r.json()["item"]["protocol"] == "opcua"
    assert r.json()["item"]["params"]["endpoint"] == "opc.tcp://10.0.0.5:4840"
    for bad, code in (({"protocol": "telnet"}, "PROTOCOL_INVALID"), ({"params": "x"}, "PARAMS_INVALID")):
        r = client.put(f"/devices/{did}", json=bad)
        assert r.status_code == 400 and r.json()["detail"].startswith(code)
    assert client.put("/devices/dev_nope", json={"name": "x"}).status_code == 404
