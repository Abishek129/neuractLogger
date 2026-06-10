"""Tier 2 — full-stack E2E: FastAPI + Modbus simulator + prebuilt Rust engine.

Run with:  python -m pytest tests/ -q -m e2e

Pieces:
  * agent/tools/modbus_simulator.py  — asyncio Modbus TCP server (FC3,
    float32 big-endian / ABCD, registers 0..19, values update at 1 Hz),
    started on a free port with --unit-ids 1.
  * agent/tests/bin/neuract-job-runner — PREBUILT working-tree Rust engine
    (intentionally NOT rebuilt here: the Rust sources are being edited by a
    parallel task; the stashed binary is the pinned test subject). It polls
    app_jobs in meta_test_e2e every JOB_POLL_MS=200 and writes acquired +
    derived values into target_test_e2e neuract.<table>.

The test drives the whole product chain and reads the data back with
psycopg2 (there is no data-read REST endpoint).
"""
from __future__ import annotations

import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

import conftest as cf

pytestmark = pytest.mark.e2e

SIM_SCRIPT = cf.AGENT_DIR / "tools" / "modbus_simulator.py"
TABLE = "e2e_full"

_LOG_DIR: Path | None = None  # set by fixtures; used in failure messages


# ---------------------------------------------------------------------------
# Raw Modbus FC3 float32 read (no pymodbus API-version dependency)
# ---------------------------------------------------------------------------
def read_float32(port: int, unit_id: int, addr: int, timeout: float = 2.0):
    req = struct.pack(">HHHBBHH", 1, 0, 6, unit_id, 3, addr, 2)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(req)
            resp = s.recv(256)
    except OSError:
        return None
    if len(resp) < 13 or resp[7] != 3:
        return None
    return struct.unpack(">f", resp[9:13])[0]


def _terminate(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _log_tail(name: str, n: int = 2500) -> str:
    if _LOG_DIR is None:
        return "<no log dir>"
    p = _LOG_DIR / name
    try:
        return p.read_text(errors="replace")[-n:]
    except OSError:
        return f"<missing {p}>"


# ---------------------------------------------------------------------------
# Session fixtures: simulator + Rust engine
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _log_dir(tmp_path_factory) -> Path:
    global _LOG_DIR
    _LOG_DIR = tmp_path_factory.mktemp("e2e_logs")
    return _LOG_DIR


@pytest.fixture(scope="session")
def modbus_sim(_log_dir):
    """Start the in-repo Modbus simulator and wait until registers are live.

    The simulator's update loop only populates registers after its first
    1-second tick — reading plausible voltage at register 0 gates readiness
    so the engine never samples the initial all-zero registers.
    """
    port = cf.free_port()
    logf = open(_log_dir / "modbus_sim.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, str(SIM_SCRIPT), "--port", str(port), "--unit-ids", "1"],
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    try:
        def _ready():
            if proc.poll() is not None:
                raise RuntimeError(
                    f"modbus simulator died (rc={proc.returncode}):\n{_log_tail('modbus_sim.log')}"
                )
            v = read_float32(port, 1, 0, timeout=0.5)
            return v is not None and 150.0 < v < 320.0

        cf.wait_until(_ready, timeout=15, interval=0.25, desc="modbus simulator registers live")
        yield port
    finally:
        _terminate(proc, "modbus_sim")
        logf.close()


@pytest.fixture(scope="session")
def rust_engine(_databases, client, _log_dir):
    """Start the PREBUILT engine binary against the test meta DB.

    Depends on ``client`` so the app has already run appdb.init() (the engine
    expects the app_* tables). Readiness probe: the engine creates the
    bench_metrics table in BENCH_DB_URL (=meta_test_e2e) during startup.
    """
    assert cf.RUST_BINARY.exists(), f"prebuilt engine missing: {cf.RUST_BINARY}"
    env = {
        **os.environ,
        "APP_DB_URL": cf.META_URL,
        "BENCH_DB_URL": cf.META_URL,  # isolates bench_metrics into the test DB
        "JOB_POLL_MS": "200",
        "RUST_LOG": "info",
        # trigger-notification target; dead port keeps continuous jobs hermetic
        "API_BASE_URL": "http://127.0.0.1:1",
    }
    logf = open(_log_dir / "rust_engine.log", "wb")
    proc = subprocess.Popen(
        [str(cf.RUST_BINARY)],
        env=env,
        cwd=str(_log_dir),  # engine drops error CSVs/logs in cwd — keep them in tmp
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    try:
        def _ready():
            if proc.poll() is not None:
                raise RuntimeError(
                    f"rust engine exited at startup (rc={proc.returncode}):\n{_log_tail('rust_engine.log')}"
                )
            return cf.pg_table_exists(cf.META_DB, "public.bench_metrics")

        cf.wait_until(_ready, timeout=20, interval=0.25, desc="rust engine startup (bench_metrics)")
        yield proc
    finally:
        _terminate(proc, "rust_engine")
        logf.close()


# ---------------------------------------------------------------------------
# The full-stack test
# ---------------------------------------------------------------------------
@pytest.mark.timeout(120)
def test_full_chain_acquires_and_derives(api, client, modbus_sim, rust_engine, target_query):
    sim_port = modbus_sim

    # 1. schema: three float32 device fields + one derived field computed by
    #    the Rust engine from the same read.
    schema = api.create_schema(
        "e2e_mfm",
        [
            {"key": "voltage", "type": "float32"},   # sim reg 0  (~230 V)
            {"key": "current", "type": "float32"},   # sim reg 2
            {"key": "power", "type": "float32"},     # sim reg 12
            {"key": "s_check", "type": "float64", "formula": "voltage*current"},
        ],
    )

    # 2. postgres target + default
    target_id = api.create_pg_target()

    # 3. device pointing at the live simulator (probe should succeed)
    dev_resp = api.create_device("e2e_dev", port=sim_port, unit_id=1)
    assert dev_resp["item"]["id"], dev_resp
    device_id = dev_resp["item"]["id"]
    assert dev_resp["success"] is True, f"device probe failed against live sim: {dev_resp}"

    # 4. table + migrate
    table_id = api.bulk_create(schema["id"], [TABLE], target_id, device_id=device_id)[0]["id"]
    api.migrate([table_id])
    assert cf.pg_table_exists(cf.TARGET_DB, f"neuract.{TABLE}")

    # 5. manual modbus mapping rows (derived row was auto-written by migrate)
    api.bulk_apply(
        table_id,
        device_id,
        rows={
            "voltage": cf.modbus_row(0),
            "current": cf.modbus_row(2),
            "power": cf.modbus_row(12),
        },
    )

    # 6. job + start
    job = api.create_job("e2e_job", [table_id], interval_ms=250)
    job_id = job["id"]
    r = client.post(f"/jobs2/{job_id}/start")
    assert r.status_code == 200 and r.json()["success"] is True

    # 7. poll the target DB until the engine has written >= 3 complete rows
    def _rows():
        got = target_query(
            f"SELECT voltage, current, power, s_check FROM neuract.{TABLE} "
            "WHERE voltage IS NOT NULL"
        )
        return got if len(got) >= 3 else None

    try:
        rows = cf.wait_until(_rows, timeout=20, interval=0.4, desc=">=3 acquired rows")
    except TimeoutError as e:
        if rust_engine.poll() is not None:
            raise AssertionError(
                f"rust engine died mid-test (rc={rust_engine.returncode}):\n{_log_tail('rust_engine.log')}"
            ) from e
        raise AssertionError(f"{e}\n--- engine log tail ---\n{_log_tail('rust_engine.log')}") from e

    # 8. plausibility + derived-correctness assertions (per row)
    for voltage, current, power, s_check in rows:
        assert 200.0 <= voltage <= 260.0, f"voltage out of range: {voltage}"
        assert s_check is not None, "derived column is NULL (engine failed to evaluate)"
        expected = voltage * current
        tol = max(1e-3 * abs(expected), 1e-6)
        assert abs(s_check - expected) <= tol, (
            f"derived mismatch: s_check={s_check} vs voltage*current={expected} "
            f"(v={voltage}, i={current})"
        )

    # 9. stop -> row count plateaus
    r = client.post(f"/jobs2/{job_id}/stop")
    assert r.status_code == 200
    # engine notices the stop within JOB_POLL_MS (200ms); allow one in-flight
    # interval (250ms) plus generous slack before sampling.
    time.sleep(2.0)
    count_sql = f"SELECT count(*) FROM neuract.{TABLE}"
    c1 = target_query(count_sql)[0][0]
    time.sleep(1.5)
    c2 = target_query(count_sql)[0][0]
    assert c2 == c1, f"rows kept arriving after stop: {c1} -> {c2}"
    assert c1 >= 3
