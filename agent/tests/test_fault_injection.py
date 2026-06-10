"""Tier 2 / faults — automated fault-injection tests (J3 'done when').

Run with:  python -m pytest tests/ -q -m faults
(also selected by the tier-2 run: -m e2e)

Each test boots a FRESH engine + Modbus simulator (function-scoped — faults
are destructive) against the throwaway conftest databases and injects one
production failure mode:

  a. META-DB OUTAGE (C1)    — pg_terminate_backend on the engine's meta/bench
                              backends: engine survives, rows keep flowing,
                              log shows reconnect (meta AND bench self-heal).
  b. TARGET-DB OUTAGE (M11) — sustained backend kills on the target DB:
                              engine reconnects, buffered (batched) rows from
                              the outage window land after recovery (no gap).
  c. SIGTERM MID-RUN (H-ERR-2) — graceful shutdown: exit 0 within 10s, final
                              flush writes buffered rows, count stays stable.
  d. DEVICE DROP            — kill the simulator: engine alive, error CSV
                              gains read rows, target stalls; restart the sim
                              on the SAME port: rows resume.

Isolation: the engine's DB connections are tagged with application_name
('lf_engine_*' / a per-test target tag) so backend kills NEVER touch the
FastAPI app's own SQLAlchemy/psycopg2 connections (which other test modules
in the same session still rely on).

All waits are bounded polls (cf.wait_until) — never sleep-and-pray. Failure
messages append the engine log tail.
"""
from __future__ import annotations

import os
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import conftest as cf

pytestmark = [pytest.mark.e2e, pytest.mark.faults]

SIM_SCRIPT = cf.AGENT_DIR / "tools" / "modbus_simulator.py"

# application_name tags: lets the tests terminate ONLY engine backends.
APP_META = "lf_engine_meta"
APP_BENCH = "lf_engine_bench"


# ---------------------------------------------------------------------------
# Raw Modbus FC3 float32 read (simulator readiness probe)
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


# ---------------------------------------------------------------------------
# Process handles
# ---------------------------------------------------------------------------
class SimHandle:
    """Modbus simulator that can be killed and restarted on the SAME port."""

    def __init__(self, log_dir: Path):
        self.port = cf.free_port()
        self.log_dir = log_dir
        self.proc: subprocess.Popen | None = None
        self._logf = None
        self._n = 0

    def start(self) -> None:
        self._n += 1
        self._logf = open(self.log_dir / f"modbus_sim_{self._n}.log", "wb")
        self.proc = subprocess.Popen(
            [sys.executable, str(SIM_SCRIPT), "--port", str(self.port), "--unit-ids", "1"],
            stdout=self._logf,
            stderr=subprocess.STDOUT,
        )

        def _ready():
            if self.proc.poll() is not None:
                raise RuntimeError(f"modbus simulator died (rc={self.proc.returncode})")
            v = read_float32(self.port, 1, 0, timeout=0.5)
            return v is not None and 150.0 < v < 320.0

        cf.wait_until(_ready, timeout=20, interval=0.25, desc="modbus simulator registers live")

    def kill(self) -> None:
        """Hard-kill (the DEVICE DROP fault)."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self._logf:
            self._logf.close()
            self._logf = None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self._logf:
            self._logf.close()
            self._logf = None


class EngineHandle:
    def __init__(self, proc: subprocess.Popen, log_path: Path, work_dir: Path):
        self.proc = proc
        self.log_path = log_path
        self.work_dir = work_dir  # error CSV lands here (RUST_BENCH_LOG_DIR)

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(errors="replace")
        except OSError:
            return ""

    def log_tail(self, n: int = 3000) -> str:
        return self.log_text()[-n:]

    def alive(self) -> bool:
        return self.proc.poll() is None

    def error_csv_text(self) -> str:
        p = self.work_dir / "error_log_rust.csv"
        try:
            return p.read_text(errors="replace")
        except OSError:
            return ""


def _fail(msg: str, eng: EngineHandle):
    raise AssertionError(f"{msg}\n--- engine log tail ---\n{eng.log_tail()}")


# ---------------------------------------------------------------------------
# Fixtures (function-scoped: every fault test gets a fresh engine + sim)
# ---------------------------------------------------------------------------
@pytest.fixture
def sim(tmp_path):
    h = SimHandle(tmp_path)
    h.start()
    yield h
    h.stop()


@pytest.fixture
def engine(client, tmp_path):
    """Fresh engine per test, DB connections tagged with application_name."""
    if not cf.RUST_BINARY.exists():
        pytest.skip(f"prebuilt engine missing: {cf.RUST_BINARY}")
    env = {
        **os.environ,
        "APP_DB_URL": f"{cf.META_URL}?application_name={APP_META}",
        "BENCH_DB_URL": f"{cf.META_URL}?application_name={APP_BENCH}",
        "JOB_POLL_MS": "200",
        "JOB_BENCH_WINDOW_SEC": "1",
        "RUST_LOG": "info",
        "RUST_BENCH_LOG_DIR": str(tmp_path),  # error CSV in the test's dir
        "API_BASE_URL": "http://127.0.0.1:1",  # dead port: notifications no-op
    }
    log_path = tmp_path / "rust_engine.log"
    logf = open(log_path, "wb")
    proc = subprocess.Popen(
        [str(cf.RUST_BINARY)],
        env=env,
        cwd=str(tmp_path),
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    handle = EngineHandle(proc, log_path, tmp_path)

    def _ready():
        if proc.poll() is not None:
            raise RuntimeError(
                f"engine exited at startup (rc={proc.returncode}):\n{handle.log_tail()}"
            )
        # Both startup connections present => supervisor loop is running.
        rows = cf.pg_query(
            cf.META_DB,
            "SELECT count(DISTINCT application_name) FROM pg_stat_activity "
            "WHERE application_name IN (%s, %s)",
            (APP_META, APP_BENCH),
        )
        return rows[0][0] == 2

    try:
        cf.wait_until(_ready, timeout=20, interval=0.25, desc="engine startup (meta+bench connected)")
        yield handle
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        logf.close()


# ---------------------------------------------------------------------------
# Shared setup: schema -> target -> device -> table -> mapping -> running job
# ---------------------------------------------------------------------------
def _kill_backends(app_names: list, datname: str) -> int:
    """Terminate ONLY the tagged backends; returns number killed."""
    rows = cf.pg_query(
        cf.META_DB,
        "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
        "WHERE datname = %s AND application_name = ANY(%s) "
        "AND pid <> pg_backend_pid()",
        (datname, app_names),
    )
    return rows[0][0]


def _count(table: str) -> int:
    return cf.pg_query(cf.TARGET_DB, f"SELECT count(*) FROM neuract.{table}")[0][0]


def _start_flowing(api, client, sim: SimHandle, table: str, target_app: str,
                   batching: dict | None = None, interval_ms: int = 250) -> str:
    """Full chain up to a running job; returns the job id."""
    schema = api.create_schema(
        f"sch_{table}",
        [
            {"key": "voltage", "type": "float32"},
            {"key": "current", "type": "float32"},
        ],
    )
    # Per-test application_name on the target conn so backend kills are scoped.
    target_conn = f"{cf.TARGET_URL}?application_name={target_app}"
    target_id = api.create_pg_target(conn=target_conn)
    dev = api.create_device(f"dev_{table}", port=sim.port, unit_id=1)
    device_id = dev["item"]["id"]
    table_id = api.bulk_create(schema["id"], [table], target_id, device_id=device_id)[0]["id"]
    api.migrate([table_id])
    assert cf.pg_table_exists(cf.TARGET_DB, f"neuract.{table}")
    api.bulk_apply(table_id, device_id,
                   rows={"voltage": cf.modbus_row(0), "current": cf.modbus_row(2)})
    payload = {"name": f"job_{table}", "type": "continuous",
               "tables": [table_id], "intervalMs": interval_ms}
    if batching:
        payload["batching"] = batching
    r = client.post("/jobs2", json=payload)
    assert r.status_code == 200, f"POST /jobs2 -> {r.status_code}: {r.text}"
    job_id = r.json()["item"]["id"]
    r = client.post(f"/jobs2/{job_id}/start")
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    return job_id


def _wait_rows(table: str, n: int, eng: EngineHandle, timeout: float = 30):
    try:
        cf.wait_until(lambda: _count(table) >= n, timeout=timeout,
                      interval=0.3, desc=f">={n} rows in {table}")
    except TimeoutError as e:
        if not eng.alive():
            _fail(f"engine died (rc={eng.proc.returncode}) while waiting for rows: {e}", eng)
        _fail(str(e), eng)


def _wait_log(eng: EngineHandle, needle: str, timeout: float = 30):
    try:
        cf.wait_until(lambda: needle in eng.log_text(), timeout=timeout,
                      interval=0.3, desc=f"engine log contains {needle!r}")
    except TimeoutError as e:
        _fail(str(e), eng)


# ---------------------------------------------------------------------------
# a. META-DB OUTAGE (C1) — engine survives, jobs keep flowing, reconnect logged
# ---------------------------------------------------------------------------
@pytest.mark.timeout(150)
def test_meta_db_outage_engine_survives_and_reconnects(api, client, sim, engine):
    table = f"flt_meta_{uuid.uuid4().hex[:6]}"
    _start_flowing(api, client, sim, table, target_app=f"lf_tgt_{table}")
    _wait_rows(table, 3, engine)

    killed = _kill_backends([APP_META, APP_BENCH], cf.META_DB)
    assert killed >= 1, "no engine meta/bench backends found to terminate"

    # Engine process must survive the outage (C1: it used to die here).
    assert engine.alive(), "engine process died after meta-DB backend kill"

    # The job must never stop: rows CONTINUE flowing into the target.
    c_after_kill = _count(table)
    _wait_rows(table, c_after_kill + 3, engine)

    # Self-healing is visible in the log: supervisor reconnects the meta DB...
    _wait_log(engine, "metadata db reconnected")
    # ...and the job's report loop reconnects the bench-metrics DB (the new
    # bench self-heal: previously every window logged 'bench db write failed'
    # forever after an outage).
    _wait_log(engine, "bench metrics db reconnected")

    # Still alive and still flowing at the end.
    assert engine.alive(), "engine died after reconnect"
    c_now = _count(table)
    _wait_rows(table, c_now + 2, engine)


# ---------------------------------------------------------------------------
# b. TARGET-DB OUTAGE (M11) — reconnect; batched rows from the outage window
#    are flushed after recovery (no gap-induced loss beyond the cap).
# ---------------------------------------------------------------------------
@pytest.mark.timeout(150)
def test_target_db_outage_rows_resume_without_gap(api, client, sim, engine):
    table = f"flt_tgt_{uuid.uuid4().hex[:6]}"
    target_app = f"lf_tgt_{table}"
    # Batching ON: rows read during the outage buffer in-process (M11) and
    # must land after the target DB is reachable again.
    _start_flowing(api, client, sim, table, target_app=target_app,
                   batching={"count": 2, "ms": 500})
    _wait_rows(table, 3, engine)

    # Sustained outage (~3s): keep terminating the engine's target backends
    # so its reconnect attempts during the window also fail.
    outage_start = datetime.now(timezone.utc)
    deadline = time.time() + 3.0
    killed_total = 0
    while time.time() < deadline:
        killed_total += _kill_backends([target_app], cf.TARGET_DB)
        time.sleep(0.3)
    outage_end = datetime.now(timezone.utc)
    assert killed_total >= 1, "no engine target-DB backends found to terminate"
    assert engine.alive(), "engine died during target-DB outage"

    # Reconnect must be logged and rows must resume (count monotonically grows).
    _wait_log(engine, "target db reconnected", timeout=45)
    c_after = _count(table)
    _wait_rows(table, c_after + 4, engine, timeout=45)

    # NO GAP: reads continued during the outage; their buffered rows (stamped
    # at read time, H-DBC-1) must have been flushed after recovery. Look for
    # rows whose timestamp falls INSIDE the kill window (with margin for the
    # first kill landing mid-flush).
    lo = (outage_start + timedelta(seconds=0.8)).isoformat()
    hi = (outage_end - timedelta(seconds=0.5)).isoformat()

    def _outage_rows():
        return cf.pg_query(
            cf.TARGET_DB,
            f"SELECT count(*) FROM neuract.{table} "
            "WHERE timestamp_utc::timestamptz BETWEEN %s::timestamptz AND %s::timestamptz",
            (lo, hi),
        )[0][0]

    try:
        cf.wait_until(lambda: _outage_rows() >= 1, timeout=30, interval=0.5,
                      desc="buffered outage-window rows flushed (M11 no-gap)")
    except TimeoutError as e:
        _fail(f"rows read during the outage window were lost: {e}", engine)
    assert engine.alive(), "engine died after target-DB recovery"


# ---------------------------------------------------------------------------
# c. SIGTERM MID-RUN (H-ERR-2) — exit 0 <=10s, buffered rows flushed, stable
# ---------------------------------------------------------------------------
@pytest.mark.timeout(150)
def test_sigterm_graceful_shutdown_flushes_buffers(api, client, sim, engine):
    table = f"flt_term_{uuid.uuid4().hex[:6]}"
    # count=100000, ms=0 => no flush trigger ever fires during the test, so
    # ALL acquired rows sit in the in-process batch buffer. Only the SIGTERM
    # drain path can write them — making the flush assertion deterministic.
    _start_flowing(api, client, sim, table, target_app=f"lf_tgt_{table}",
                   batching={"count": 100000, "ms": 0})

    # 'Rows flowing' gate: the engine reports buffered rows in its log.
    def _buffered_rows() -> int:
        import re
        hits = re.findall(r"\[BATCH_STATUS\] buffered=(\d+)", engine.log_text())
        return int(hits[-1]) if hits else 0

    try:
        cf.wait_until(lambda: _buffered_rows() >= 3, timeout=30, interval=0.3,
                      desc=">=3 rows buffered in engine")
    except TimeoutError as e:
        _fail(str(e), engine)

    c_pre = _count(table)  # nothing flushed yet (buffer-only)

    engine.proc.send_signal(signal.SIGTERM)
    try:
        rc = engine.proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _fail("engine did not exit within 10s of SIGTERM", engine)
    assert rc == 0, f"engine exited rc={rc} (expected 0)\n{engine.log_tail()}"

    # Final flush wrote the buffered rows BEFORE exiting.
    c_post = _count(table)
    assert c_post > c_pre, (
        f"buffered rows were not flushed on SIGTERM: {c_pre} -> {c_post}\n"
        f"{engine.log_tail()}"
    )
    assert "graceful shutdown complete" in engine.log_text(), engine.log_tail()

    # No partial garbage / nothing arrives after exit: count is stable.
    time.sleep(2.0)
    c_post2 = _count(table)
    assert c_post2 == c_post, f"row count changed after engine exit: {c_post} -> {c_post2}"

    # Every flushed row is complete (both mapped fields present).
    nulls = cf.pg_query(
        cf.TARGET_DB,
        f"SELECT count(*) FROM neuract.{table} WHERE voltage IS NULL OR current IS NULL",
    )[0][0]
    assert nulls == 0, f"{nulls} partial row(s) written during shutdown"


# ---------------------------------------------------------------------------
# d. DEVICE DROP — sim killed: engine alive, error CSV grows, target stalls;
#    sim restarted on the SAME port: rows resume.
# ---------------------------------------------------------------------------
@pytest.mark.timeout(150)
def test_device_drop_and_recovery(api, client, sim, engine):
    table = f"flt_dev_{uuid.uuid4().hex[:6]}"
    _start_flowing(api, client, sim, table, target_app=f"lf_tgt_{table}")
    _wait_rows(table, 3, engine)

    csv_len_before = len(engine.error_csv_text())
    sim.kill()

    # Engine must survive and record read errors in the error CSV (cwd logs).
    def _read_errors_logged():
        new = engine.error_csv_text()[csv_len_before:]
        return any((",read," in line) for line in new.splitlines())

    try:
        cf.wait_until(_read_errors_logged, timeout=30, interval=0.5,
                      desc="read-error rows appended to error CSV")
    except TimeoutError as e:
        _fail(str(e), engine)
    assert engine.alive(), "engine died after device drop"

    # Target stops growing: two consecutive samples 1s apart must be equal.
    def _stalled():
        a = _count(table)
        time.sleep(1.0)
        return a if _count(table) == a else None

    try:
        stalled_at = cf.wait_until(_stalled, timeout=30, interval=0.2,
                                   desc="target row count stalls after device drop")
    except TimeoutError as e:
        _fail(str(e), engine)

    # Restart the simulator on the SAME port — acquisition must self-heal.
    sim.start()
    try:
        cf.wait_until(lambda: _count(table) > stalled_at, timeout=15, interval=0.3,
                      desc="rows resume within ~10s of device recovery")
    except TimeoutError as e:
        _fail(f"rows did not resume after simulator restart: {e}", engine)
    assert engine.alive(), "engine died after device recovery"
