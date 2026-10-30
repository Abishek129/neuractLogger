"""Tier 1 — alerts on readings: levels, schema rules (blueprint), table
overrides / effective rules, active state + history reads, cleanup."""
from __future__ import annotations

import conftest as cf


def _setup(api):
    schema = api.create_schema("al_mfm", [
        {"key": "voltage", "type": "float32", "unit": "V"}, {"key": "current", "type": "float32", "unit": "A"}])
    target = api.create_pg_target()
    t1, t2 = api.bulk_create(schema["id"], ["al_t1", "al_t2"], target)
    return schema["id"], t1["id"], t2["id"]


def test_levels_seeded_and_crud(client):
    levels = client.get("/alerts/levels").json()["items"]
    assert [(l["id"], l["severity"]) for l in levels] == [("critical", 3), ("mild", 2), ("info", 1)]

    r = client.post("/alerts/levels", json={"name": "Warning", "severity": 2, "color": "#fa0"})
    assert r.status_code == 200, r.text
    wid = r.json()["item"]["id"]
    assert client.post("/alerts/levels", json={"name": "warning"}).status_code == 409
    r = client.put(f"/alerts/levels/{wid}", json={"name": "Warn", "severity": 4})
    assert r.status_code == 200 and r.json()["item"]["severity"] == 4
    assert client.get("/alerts/levels").json()["items"][0]["name"] == "Warn"  # most severe first
    for bad in ({"name": ""}, {"name": "X", "severity": -1}, {"name": "X", "severity": "2"}):
        assert client.post("/alerts/levels", json=bad).status_code == 400
    assert client.delete(f"/alerts/levels/{wid}").status_code == 200
    assert client.delete("/alerts/levels/nope").status_code == 404


def test_schema_rules_blueprint(api, client):
    sid, _, _ = _setup(api)
    r = client.post(f"/schemas/{sid}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 250})
    assert r.status_code == 200, r.text
    rule = r.json()["item"]
    assert (rule["alertName"], rule["op"], rule["threshold"], rule["unit"]) == ("Critical", ">", 250.0, "V")
    client.post(f"/schemas/{sid}/alerts", json={"fieldKey": "voltage", "alertId": "mild", "op": ">", "threshold": 240})

    for bad, code in (({"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 1}, 409),
                      ({"fieldKey": "nope", "alertId": "mild", "op": ">", "threshold": 1}, 400),
                      ({"fieldKey": "current", "alertId": "mild", "op": "~", "threshold": 1}, 400),
                      ({"fieldKey": "current", "alertId": "mild", "op": ">", "threshold": "1"}, 400),
                      ({"fieldKey": "current", "alertId": "ghost", "op": ">", "threshold": 1}, 404)):
        assert client.post(f"/schemas/{sid}/alerts", json=bad).status_code == code, bad

    items = client.get(f"/schemas/{sid}/alerts").json()["items"]
    assert [(i["alertId"], i["threshold"]) for i in items] == [("critical", 250.0), ("mild", 240.0)]
    r = client.put(f"/schemas/{sid}/alerts/{rule['id']}", json={"threshold": 255, "op": ">="})
    assert r.status_code == 200 and (r.json()["item"]["op"], r.json()["item"]["threshold"]) == (">=", 255.0)
    assert client.put(f"/schemas/{sid}/alerts/{rule['id']}", json={"alertId": "mild"}).status_code == 400
    # A level used by a rule cannot be deleted.
    r = client.delete("/alerts/levels/critical")
    assert r.status_code == 409 and r.json()["detail"].startswith("ALERT_LEVEL_IN_USE")


def test_table_inherits_and_overrides(api, client):
    sid, t1, t2 = _setup(api)
    client.post(f"/schemas/{sid}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 250})
    client.post(f"/schemas/{sid}/alerts", json={"fieldKey": "voltage", "alertId": "mild", "op": ">", "threshold": 240})

    eff = client.get(f"/tables/{t1}/alerts").json()["items"]
    assert [(e["alertId"], e["threshold"], e["source"]) for e in eff] == [("critical", 250.0, "schema"), ("mild", 240.0, "schema")]

    # Override critical's threshold on t1 only; disable mild on t1; add a table-only rule.
    r = client.put(f"/tables/{t1}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "threshold": 260})
    assert r.status_code == 200, r.text
    client.put(f"/tables/{t1}/alerts", json={"fieldKey": "voltage", "alertId": "mild", "enabled": False})
    r = client.put(f"/tables/{t1}/alerts", json={"fieldKey": "current", "alertId": "info", "op": "<", "threshold": 0.5})
    eff = {(e["fieldKey"], e["alertId"]): e for e in r.json()["items"]}
    assert (eff[("voltage", "critical")]["threshold"], eff[("voltage", "critical")]["op"], eff[("voltage", "critical")]["source"]) == (260.0, ">", "overridden")
    assert eff[("voltage", "mild")]["source"] == "disabled" and eff[("voltage", "mild")]["enabled"] is False
    assert eff[("current", "info")]["source"] == "table"
    # t2 still inherits the blueprint unchanged.
    assert [e["source"] for e in client.get(f"/tables/{t2}/alerts").json()["items"]] == ["schema", "schema"]
    # A schema change flows to tables that did not override it.
    rid = next(i["id"] for i in client.get(f"/schemas/{sid}/alerts").json()["items"] if i["alertId"] == "mild")
    client.put(f"/schemas/{sid}/alerts/{rid}", json={"threshold": 245})
    assert next(e for e in client.get(f"/tables/{t2}/alerts").json()["items"] if e["alertId"] == "mild")["threshold"] == 245.0

    # A table-only rule needs op + threshold; unknown field refused.
    r = client.put(f"/tables/{t1}/alerts", json={"fieldKey": "current", "alertId": "mild"})
    assert r.status_code == 400 and r.json()["detail"].startswith("RULE_REQUIRED")
    assert client.put(f"/tables/{t1}/alerts", json={"fieldKey": "nope", "alertId": "mild", "op": ">", "threshold": 1}).status_code == 400

    # Removing the override falls back to the schema rule.
    oid = eff[("voltage", "critical")]["overrideId"]
    r = client.delete(f"/tables/{t1}/alerts/{oid}")
    crit = next(e for e in r.json()["items"] if e["alertId"] == "critical")
    assert (crit["threshold"], crit["source"]) == (250.0, "schema")


def test_active_and_events_reads_and_cleanup(api, client, meta_query):
    sid, t1, _ = _setup(api)
    client.post(f"/schemas/{sid}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 250})
    client.put(f"/tables/{t1}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "threshold": 260})
    # What the engine writes on a state change:
    meta_query("INSERT INTO app_alert_state (table_id, field_key, alert_id, value, since) VALUES (%s,'voltage','critical',265,'2026-10-25T10:00:00Z')", (t1,))
    meta_query("INSERT INTO app_alert_event (id, table_id, field_key, from_alert_id, to_alert_id, value, op, threshold, job_id, at) "
               "VALUES ('ae_1', %s, 'voltage', NULL, 'critical', 265, '>', 260, 'job_x', '2026-10-25T10:00:00Z')", (t1,))
    act = client.get("/alerts/active").json()["items"]
    assert act == [{"tableId": t1, "tableName": "al_t1", "fieldKey": "voltage", "alertId": "critical", "alertName": "Critical",
                    "severity": 3, "color": "#b42318", "value": 265.0, "since": "2026-10-25T10:00:00Z"}]
    ev = client.get("/alerts/events", params={"tableId": t1}).json()["items"]
    assert ev[0]["to"] == {"alertId": "critical", "alertName": "Critical"} and ev[0]["from"] is None and ev[0]["threshold"] == 260.0

    # Deleting the field removes its rules, overrides and active states.
    client.delete(f"/schemas/{sid}/fields/voltage")
    assert client.get(f"/schemas/{sid}/alerts").json()["items"] == []
    assert client.get("/alerts/active").json()["items"] == []
    assert meta_query("SELECT COUNT(*) FROM app_table_alert")[0][0] == 0
    assert len(client.get("/alerts/events").json()["items"]) == 1  # history kept


def test_alerts_need_token(no_auth, client):
    assert client.get("/alerts/levels").status_code == 401
