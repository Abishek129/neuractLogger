"""Tier 2 — OPC UA jobs through the real Rust engine, like the Modbus chain.

Run with:  python -m pytest tests/test_opcua_e2e.py -q -m e2e
(needs agent/tests/bin/neuract-job-runner built from the working tree)

  * agent/tools/opcua_simulator.py — OPC UA server with ns=2;s=Voltage_L1
    (Double ~230), Current_L1 (Float ~10), Counter (Int32, +1/s).
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import conftest as cf
from test_fullstack_e2e import _log_dir, rust_engine, _log_tail, _terminate  # noqa: F401 (fixtures)

pytestmark = pytest.mark.e2e

SIM_SCRIPT = cf.AGENT_DIR / "tools" / "opcua_simulator.py"
ROWS = {
    "voltage": {"protocol": "opcua", "address": "ns=2;s=Voltage_L1"},
    "current": {"protocol": "opcua", "address": "ns=2;s=Current_L1"},
    "counter": {"protocol": "opcua", "address": "ns=2;s=Counter"},
}


def _endpoint(port: int) -> str:
    return f"opc.tcp://127.0.0.1:{port}/neuract/sim/"


def _sim_ready(port: int) -> bool:
    try:
        from opcua import Client
        c = Client(_endpoint(port), timeout=1)
        c.connect()
        try:
            return c.get_node("ns=2;s=Counter").get_value() >= 1
        finally:
            c.disconnect()
    except Exception:
        return False


class Sim:
    def __init__(self, log_dir):
        self.port = cf.free_port()
        self.log_dir = log_dir
        self.proc = None

    def start(self):
        logf = open(self.log_dir / f"opcua_sim_{self.port}.log", "ab")
        self.proc = subprocess.Popen([sys.executable, str(SIM_SCRIPT), "--port", str(self.port)],
                                     stdout=logf, stderr=subprocess.STDOUT)
        cf.wait_until(lambda: _sim_ready(self.port), timeout=20, interval=0.3, desc="opcua simulator live")

    def stop(self):
        if self.proc:
            _terminate(self.proc, "opcua_sim")


@pytest.fixture
def opcua_sim(_log_dir):
    sim = Sim(_log_dir)
    sim.start()
    yield sim
    sim.stop()


def _schema(api, name):
    return api.create_schema(name, [
        {"key": "voltage", "type": "float64", "unit": "V"},
        {"key": "current", "type": "float32", "unit": "A"},
        {"key": "counter", "type": "int32"},
    ])


def _run(api, client, schema_id, table, device_id):
    target = api.create_pg_target()
    tid = api.bulk_create(schema_id, [table], target, device_id=device_id)[0]["id"]
    api.migrate([tid])
    api.bulk_apply(tid, device_id, ROWS)
    job = api.create_job(f"{table}_job", [tid], interval_ms=250)
    r = client.post(f"/jobs2/{job['id']}/start")
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    return job["id"]


def _wait_rows(target_query, table, n, rust_engine, after_counter=None):
    sql = f"SELECT voltage, current, counter FROM neuract.{table} WHERE voltage IS NOT NULL"
    if after_counter is not None:
        sql += f" AND counter > {int(after_counter)}"

    def _rows():
        got = target_query(sql)
        return got if len(got) >= n else None

    try:
        return cf.wait_until(_rows, timeout=25, interval=0.4, desc=f">={n} rows in {table}")
    except TimeoutError as e:
        raise AssertionError(f"{e}\n--- engine log tail ---\n{_log_tail('rust_engine.log', 4000)}") from e


def _check(rows):
    for v, i, c in rows:
        assert 220.0 <= v <= 240.0, v
        assert 8.0 <= i <= 12.0, i
        assert c is not None and c >= 1, c


@pytest.mark.timeout(120)
def test_opcua_device_with_endpoint_logs(api, client, opcua_sim, rust_engine, target_query):
    r = client.post("/devices", json={"name": "opc_ep", "protocol": "opcua",
                                      "params": {"endpoint": _endpoint(opcua_sim.port)}})
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    dev = r.json()["item"]["id"]
    job = _run(api, client, _schema(api, "opc_ep_s")["id"], "opc_ep_t", dev)
    _check(_wait_rows(target_query, "opc_ep_t", 3, rust_engine))
    client.post(f"/jobs2/{job}/stop")


@pytest.mark.timeout(120)
def test_opcua_device_from_bulk_import_logs(api, client, opcua_sim, rust_engine, target_query):
    # Bulk import keeps the endpoint on the gateway (host opc.tcp://ip:port), not in params.
    r = client.post("/bulk_import/devices", json={"devices": [
        {"name": "opc_bulk", "ip": "127.0.0.1", "port": opcua_sim.port, "protocol": "opcua"}]})
    res = r.json()["results"][0]
    assert res["status"] == "created", res
    job = _run(api, client, _schema(api, "opc_bulk_s")["id"], "opc_bulk_t", res["device"]["id"])
    _check(_wait_rows(target_query, "opc_bulk_t", 3, rust_engine))
    client.post(f"/jobs2/{job}/stop")


@pytest.mark.timeout(150)
def test_opcua_job_recovers_after_server_restart(api, client, opcua_sim, rust_engine, target_query):
    r = client.post("/devices", json={"name": "opc_rc", "protocol": "opcua",
                                      "params": {"endpoint": _endpoint(opcua_sim.port)}})
    dev = r.json()["item"]["id"]
    job = _run(api, client, _schema(api, "opc_rc_s")["id"], "opc_rc_t", dev)
    _wait_rows(target_query, "opc_rc_t", 2, rust_engine)

    opcua_sim.stop()
    opcua_sim.start()  # same port; the counter restarts from 1
    # Rows written after the restart carry the new server's small counter values,
    # so look for rows newer than the restart instead.
    before = target_query("SELECT count(*) FROM neuract.opc_rc_t")[0][0]

    def _more():
        return target_query("SELECT count(*) FROM neuract.opc_rc_t")[0][0] >= before + 3 or None

    try:
        cf.wait_until(_more, timeout=40, interval=0.5, desc="rows resume after OPC UA server restart")
    except TimeoutError as e:
        raise AssertionError(f"{e}\n--- engine log tail ---\n{_log_tail('rust_engine.log', 4000)}") from e
    client.post(f"/jobs2/{job}/stop")
