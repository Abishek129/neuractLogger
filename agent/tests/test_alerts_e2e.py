"""Tier 2 — alerts through the real Rust engine + Modbus simulator.

Run with:  python -m pytest tests/test_alerts_e2e.py -q -m e2e
(needs agent/tests/bin/neuract-job-runner built from the working tree)
"""
from __future__ import annotations

import pytest

import conftest as cf
from test_fullstack_e2e import _log_dir, modbus_sim, rust_engine, _log_tail  # noqa: F401 (fixtures)

pytestmark = pytest.mark.e2e


def _state(meta_query, table_id):
    return meta_query("SELECT alert_id, value FROM app_alert_state WHERE table_id=%s AND field_key='voltage'", (table_id,))


def _events(meta_query, table_id):
    return meta_query(
        "SELECT from_alert_id, to_alert_id, op, threshold FROM app_alert_event WHERE table_id=%s ORDER BY at, id", (table_id,)
    )


@pytest.mark.timeout(120)
def test_alert_raised_and_cleared_by_engine(api, client, modbus_sim, rust_engine, meta_query):
    schema = api.create_schema("al_e2e", [{"key": "voltage", "type": "float32", "unit": "V"},
                                          {"key": "current", "type": "float32", "unit": "A"}])
    target = api.create_pg_target()
    dev = api.create_device("al_e2e_dev", port=modbus_sim, unit_id=1)["item"]["id"]
    tid = api.bulk_create(schema["id"], ["al_e2e_t"], target, device_id=dev)[0]["id"]
    api.migrate([tid])
    api.bulk_apply(tid, dev, {"voltage": cf.modbus_row(0), "current": cf.modbus_row(2)})

    # Simulator voltage is ~230 V: Critical > 100 and Mild > 50 both match -> worst (Critical) wins.
    client.post(f"/schemas/{schema['id']}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 100})
    client.post(f"/schemas/{schema['id']}/alerts", json={"fieldKey": "voltage", "alertId": "mild", "op": ">", "threshold": 50})

    job = api.create_job("al_e2e_job", [tid], interval_ms=200)
    assert client.post(f"/jobs2/{job['id']}/start").status_code == 200
    cf.wait_until(lambda: _state(meta_query, tid), timeout=20, desc="alert state raised\n" + _log_tail("rust_engine.log"))
    st = _state(meta_query, tid)[0]
    assert st[0] == "critical" and 150 < st[1] < 320
    # One event only, however many reads happened (state-change semantics).
    cf.wait_until(lambda: len(_events(meta_query, tid)) >= 1, timeout=5, desc="alert event")
    import time
    time.sleep(1.5)
    assert _events(meta_query, tid) == [(None, "critical", ">", 100.0)]
    assert client.get("/alerts/active", params={"tableId": tid}).json()["items"][0]["alertName"] == "Critical"

    # Override on this table: thresholds above any reading. Rules load at job
    # start, so restart the job; the seeded Critical state then clears.
    client.post(f"/jobs2/{job['id']}/stop")
    cf.wait_until(lambda: True, timeout=1)
    time.sleep(1.0)
    client.put(f"/tables/{tid}/alerts", json={"fieldKey": "voltage", "alertId": "critical", "threshold": 1000})
    client.put(f"/tables/{tid}/alerts", json={"fieldKey": "voltage", "alertId": "mild", "threshold": 1000})
    client.post(f"/jobs2/{job['id']}/start")
    cf.wait_until(lambda: not _state(meta_query, tid), timeout=20, desc="alert state cleared\n" + _log_tail("rust_engine.log"))
    time.sleep(1.0)
    ev = _events(meta_query, tid)
    assert ev == [(None, "critical", ">", 100.0), ("critical", None, None, None)], ev
    client.post(f"/jobs2/{job['id']}/stop")
