from __future__ import annotations

import struct
import threading
import time
import logging
from collections import deque
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text

from ..store import Store
from ...metrics import metrics as METRICS


router = APIRouter(prefix="/jobs")

_job_threads: Dict[str, threading.Thread] = {}
_job_stops: Dict[str, threading.Event] = {}
log = logging.getLogger(__name__)
_thread_local = threading.local()


def _db_engine_for_table(table_id: str):
    store = Store.instance()
    t = store.get_table(table_id)
    if not t:
        raise RuntimeError("TABLE_NOT_FOUND")
    target_id = t.get("dbTargetId") or store.get_default_db_target()
    url = "sqlite:///mydatabase.db"
    if target_id:
        target = store.get_db_target(target_id)
        if target:
            provider = (target.get("provider") or "").lower()
            if provider == "sqlite":
                conn = target.get("conn") or ":memory:"
                url = f"sqlite:///{conn}" if not str(conn).startswith("sqlite:") else conn
            elif provider in ("postgresql", "postgres", "mssql", "sqlserver", "mysql"):
                conn = target.get("conn") or ""
                if conn:
                    url = conn
    cache = getattr(_thread_local, "engine_cache", None)
    if cache is None:
        cache = {}
        _thread_local.engine_cache = cache
    eng = cache.get(url)
    if eng is None:
        eng = create_engine(url)
        cache[url] = eng
    return eng


# --- NEURACT physical ident helpers (mirror tables router) ---
NEURACT_SCHEMA = "neuract"
NEURACT_PREFIX = "neuract__"


def _dialect_name(engine) -> str:
    try:
        return getattr(engine.dialect, "name", "") or ""
    except Exception:
        return ""


def _uses_schema(engine) -> bool:
    name = _dialect_name(engine)
    return name in ("postgresql", "psycopg2", "mssql", "sqlserver")


def _physical_ident(engine, logical_name: str) -> Dict[str, str]:
    if _uses_schema(engine):
        return {"schema": NEURACT_SCHEMA, "name": logical_name, "qualified": f"{NEURACT_SCHEMA}.{logical_name}"}
    name = f"{NEURACT_PREFIX}{logical_name}"
    return {"schema": None, "name": name, "qualified": name}


def _read_mapping_values(table_id: str) -> Dict[str, Any]:
    store = Store.instance()
    mapping = store.get_mapping(table_id)
    device_id = mapping.get("deviceId")
    rows = mapping.get("rows") or {}
    if not device_id:
        raise RuntimeError("DEVICE_NOT_BOUND")
    dev = store.get_device(device_id)
    if not dev:
        raise RuntimeError("DEVICE_NOT_FOUND")
    proto = (dev.get("protocol") or "").lower()
    params = dev.get("params") or {}
    values: Dict[str, Any] = {}
    if proto == "opcua":
        try:
            import opcua  # type: ignore
            _ = opcua
        except Exception as e:
            raise RuntimeError(f"OPCUA_PKG_MISSING: {e}")
        endpoint = params.get("endpoint") or "opc.tcp://127.0.0.1:4840/freeopcua/server/"
        # Some servers advertise 0.0.0.0 which is not connectable; replace with loopback
        if isinstance(endpoint, str) and "0.0.0.0" in endpoint:
            safe_ep = endpoint.replace("0.0.0.0", "127.0.0.1")
            log.info("OPC UA endpoint normalized from %s to %s", endpoint, safe_ep)
            endpoint = safe_ep
        try:
            client = _get_opcua_client(endpoint)
            for field, spec in rows.items():
                if (spec.get("protocol") or "").lower() != "opcua":
                    continue
                nid = spec.get("address") or spec.get("nodeId")
                if not nid:
                    continue
                try:
                    key = (endpoint, str(nid))
                    with _opcua_lock:
                        node = _opcua_nodes.get(key)
                    if node is None:
                        node = client.get_node(nid)
                        with _opcua_lock:
                            _opcua_nodes[key] = node
                    val = node.get_value()
                    # Apply scale if present
                    sc = spec.get("scale")
                    try:
                        if sc is not None and isinstance(val, (int, float)):
                            val = float(val) * float(sc)
                    except Exception:
                        pass
                    values[field] = val
                except Exception as e:
                    log.warning("OPC UA read failed field=%s node=%s err=%s", field, nid, e)
                    values[field] = None
        except Exception as e:
            log.error("OPC UA connect/read failed endpoint=%s err=%s", endpoint, e)
            _drop_opcua_client(endpoint)
            raise
    elif proto == "modbus":
        host = (params.get("host") or params.get("ip") or "").strip()
        port = int(params.get("port", 502))
        if not host:
            raise RuntimeError("MODBUS_HOST_MISSING")
        try:
            client = _get_modbus_client(host, port)
            for field, spec in rows.items():
                if (spec.get("protocol") or "").lower() != "modbus":
                    continue
                addr_raw = spec.get("address")
                if addr_raw is None or addr_raw == "":
                    continue
                try:
                    address = int(addr_raw)
                    encoding = (spec.get("encoding") or "float32").lower()
                    unit_id = int(spec.get("unitId") or 1)
                    reg_count = _ENCODING_MAP.get(encoding, (1, ">H"))[0]
                    rr = client.read_holding_registers(address=address, count=reg_count, device_id=unit_id)
                    if hasattr(rr, "isError") and rr.isError():
                        log.warning("Modbus read error field=%s addr=%s unit=%s err=%s", field, address, unit_id, rr)
                        values[field] = None
                        continue
                    val = _decode_registers(rr.registers, encoding)
                    # Apply scale if present
                    sc = spec.get("scale")
                    try:
                        if sc is not None and isinstance(val, (int, float)):
                            val = float(val) * float(sc)
                    except Exception:
                        pass
                    values[field] = val
                except Exception as e:
                    log.warning("Modbus read failed field=%s addr=%s err=%s", field, addr_raw, e)
                    values[field] = None
        except Exception as e:
            log.error("Modbus connect/read failed host=%s port=%s err=%s", host, port, e)
            _drop_modbus_client(host, port)
            raise
    else:
        raise RuntimeError("PROTOCOL_NOT_SUPPORTED")
    return values


# --- Trigger evaluation helpers ---
def _eval_op(val: Optional[float], prev: Optional[float], op: str, threshold: Optional[float], *, deadband: float = 0.0) -> bool:
    try:
        if op == "change":
            if val is None or prev is None:
                return False
            return abs(float(val) - float(prev)) > float(deadband or 0.0)
        if op in (">", ">=", "<", "<=", "==", "!="):
            if val is None or threshold is None:
                return False
            v = float(val); t = float(threshold)
            if op == ">":
                return v > t
            if op == ">=":
                return v >= t
            if op == "<":
                return v < t
            if op == "<=":
                return v <= t
            if op == "==":
                return v == t
            if op == "!=":
                return v != t
        if op == "rising":
            if val is None or prev is None or threshold is None:
                return False
            return float(prev) <= float(threshold) and float(val) > float(threshold)
        if op == "falling":
            if val is None or prev is None or threshold is None:
                return False
            return float(prev) >= float(threshold) and float(val) < float(threshold)
    except Exception:
        return False
    return False


_job_last_values: Dict[str, Dict[str, Dict[str, Any]]] = {}
_job_cooldowns: Dict[str, Dict[str, float]] = {}
_opcua_clients: Dict[str, Any] = {}
_opcua_nodes: Dict[Tuple[str, str], Any] = {}
_opcua_lock = threading.RLock()
_thread_cpu_cache: Dict[int, float] = {}
_thread_cpu_cache_ts = 0.0
_thread_cpu_cache_lock = threading.Lock()
_process_stats_cache: Optional[Tuple[float, float]] = None
_process_stats_ts = 0.0
_process_stats_lock = threading.Lock()
_bench_csv_lock = threading.Lock()


def _get_opcua_client(endpoint: str):
    with _opcua_lock:
        client = _opcua_clients.get(endpoint)
    if client:
        return client
    from opcua import Client  # type: ignore
    client = Client(endpoint)
    client.connect()
    with _opcua_lock:
        _opcua_clients[endpoint] = client
    return client


def _drop_opcua_client(endpoint: str) -> None:
    with _opcua_lock:
        client = _opcua_clients.pop(endpoint, None)
        if client:
            for key in list(_opcua_nodes.keys()):
                if key[0] == endpoint:
                    _opcua_nodes.pop(key, None)
    if client:
        try:
            client.disconnect()
        except Exception:
            pass


# --- Modbus client cache & helpers ---
_modbus_clients: Dict[str, Any] = {}
_modbus_lock = threading.RLock()


def _get_modbus_client(host: str, port: int):
    key = f"{host}:{port}"
    with _modbus_lock:
        client = _modbus_clients.get(key)
    if client and client.connected:
        return client
    from pymodbus.client import ModbusTcpClient  # type: ignore
    client = ModbusTcpClient(host=host, port=port)
    if not client.connect():
        raise RuntimeError(f"MODBUS_CONNECT_FAILED: {key}")
    with _modbus_lock:
        _modbus_clients[key] = client
    return client


def _drop_modbus_client(host: str, port: int) -> None:
    key = f"{host}:{port}"
    with _modbus_lock:
        client = _modbus_clients.pop(key, None)
    if client:
        try:
            client.close()
        except Exception:
            pass


# Encoding → (register count, struct format)
_ENCODING_MAP = {
    "float32": (2, ">f"),
    "float": (2, ">f"),
    "uint16": (1, ">H"),
    "int16": (1, ">h"),
    "uint32": (2, ">I"),
    "int32": (2, ">i"),
    "float64": (4, ">d"),
    "uint64": (4, ">Q"),
    "int64": (4, ">q"),
}


def _decode_registers(regs: list, encoding: str):
    """Decode raw Modbus registers into a Python value."""
    enc = (encoding or "float32").lower()
    info = _ENCODING_MAP.get(enc)
    if not info:
        # Fallback: single register as int
        return regs[0] if regs else None
    count, fmt = info
    if len(regs) < count:
        return None
    # Pack registers as big-endian 16-bit words, then unpack
    raw = b"".join(r.to_bytes(2, "big") for r in regs[:count])
    return struct.unpack(fmt, raw)[0]


def _percentile_ms(samples: List[float], pct: float) -> Optional[float]:
    if not samples:
        return None
    s = sorted(samples)
    if len(s) == 1:
        return s[0]
    idx = int((pct / 100.0) * (len(s) - 1))
    return s[idx]


def _get_thread_cpu_time_sec(thread_id: int) -> Optional[float]:
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    now = time.perf_counter()
    with _thread_cpu_cache_lock:
        global _thread_cpu_cache_ts
        if (now - _thread_cpu_cache_ts) > 1.0 or not _thread_cpu_cache:
            try:
                proc = psutil.Process()
                _thread_cpu_cache = {t.id: float(t.user_time + t.system_time) for t in proc.threads()}
                _thread_cpu_cache_ts = now
            except Exception:
                return None
        return _thread_cpu_cache.get(thread_id)


def _get_process_stats() -> Optional[Tuple[float, float]]:
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    now = time.perf_counter()
    with _process_stats_lock:
        global _process_stats_ts, _process_stats_cache
        if (now - _process_stats_ts) > 1.0 or _process_stats_cache is None:
            try:
                proc = psutil.Process()
                cpu_pct = float(proc.cpu_percent(interval=None))
                rss_mb = float(proc.memory_info().rss) / (1024.0 * 1024.0)
                _process_stats_cache = (cpu_pct, rss_mb)
                _process_stats_ts = now
            except Exception:
                return None
        return _process_stats_cache


def _append_bench_csv(row: Dict[str, Any]) -> None:
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    primary = log_dir / "bench_metrics.csv"
    pending = log_dir / "bench_metrics_pending.csv"
    header = [
        "ts_utc",
        "job_id",
        "window_secs",
        "reads_per_sec",
        "writes_per_sec",
        "read_avg_ms",
        "write_avg_ms",
        "loop_p95_ms",
        "overrun_pct",
        "cpu_time_ms",
        "proc_cpu_pct",
        "proc_rss_mb",
        "read_err",
        "write_err",
    ]

    def _write_row(path: Path) -> None:
        needs_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if needs_header:
                writer.writeheader()
            writer.writerow(row)

    def _drain_pending() -> None:
        if not pending.exists():
            return
        try:
            lines = pending.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        if not lines:
            try:
                pending.unlink()
            except Exception:
                pass
            return
        if lines and lines[0].split(",")[0] == header[0]:
            lines = lines[1:]
        if not lines:
            try:
                pending.unlink()
            except Exception:
                pass
            return
        with primary.open("a", encoding="utf-8", newline="") as f:
            for line in lines:
                f.write(line + "\n")
        try:
            pending.unlink()
        except Exception:
            pass

    with _bench_csv_lock:
        try:
            _write_row(primary)
            _drain_pending()
        except Exception as e:
            try:
                _write_row(pending)
            except Exception:
                pass
            try:
                log.warning("Bench CSV write failed (%s); wrote to %s", e, pending.name)
            except Exception:
                pass


def _run_job_loop(job_id: str):
    store = Store.instance()
    job = store.get_job(job_id)
    if not job:
        return
    interval = max(0.1, (job.get("intervalMs") or 1000) / 1000.0)
    stop_event = _job_stops[job_id]
    jtype = (job.get("type") or "continuous").lower()
    if jtype == "triggered":
        jtype = "trigger"
    # Prepare state containers
    _job_last_values.setdefault(job_id, {})
    _job_cooldowns.setdefault(job_id, {})
    log.info(
        "Job %s started type=%s intervalMs=%s tables=%s",
        job_id,
        jtype,
        int(interval * 1000),
        ",".join(job.get("tables") or []),
    )
    # begin run in metrics
    try:
        METRICS.get_job(job_id).start_run()
    except Exception:
        pass
    # Lightweight benchmark counters (per reporting window)
    report_every = 2.0
    last_report = time.perf_counter()
    win_reads_ok = 0
    win_reads_err = 0
    win_writes_ok = 0
    win_writes_err = 0
    win_read_ms_sum = 0.0
    win_write_ms_sum = 0.0
    win_loops = 0
    win_overruns = 0
    loop_samples_ms = deque(maxlen=1000)
    thread_id = threading.get_native_id()
    last_cpu_time = _get_thread_cpu_time_sec(thread_id)
    while not stop_event.is_set():
        t_start = time.perf_counter()
        if jtype == "continuous":
            for tbl_id in job.get("tables") or []:
                # Read values
                try:
                    t0 = time.perf_counter()
                    vals = _read_mapping_values(tbl_id)
                    win_read_ms_sum += (time.perf_counter() - t0) * 1000.0
                    win_reads_ok += 1
                    METRICS.get_job(job_id).record_read((time.perf_counter() - t0) * 1000.0, ok=True)
                except Exception as e:
                    log.warning("Job %s read failed for table %s: %s", job_id, tbl_id, e)
                    win_reads_err += 1
                    try:
                        METRICS.get_job(job_id).record_read((time.perf_counter() - t_start) * 1000.0, ok=False)
                        METRICS.get_job(job_id).record_error("READ_ERROR", str(e))
                    except Exception:
                        pass
                    continue
                # Write values
                try:
                    engine = _db_engine_for_table(tbl_id)
                    table = Store.instance().get_table(tbl_id)
                    logical = table.get("name") if table else None
                    if not logical:
                        continue
                    ident = _physical_ident(engine, logical)
                    cols = ["timestamp_utc"] + list(vals.keys())
                    placeholders = ",".join([":ts"] + [f":{k}" for k in vals.keys()])
                    params = {"ts": _now_ist_iso(), **vals}
                    col_list = ",".join(cols)
                    sql = f"INSERT INTO {ident['qualified']} ({col_list}) VALUES ({placeholders})"
                    t1 = time.perf_counter()
                    with engine.begin() as conn:
                        conn.execute(text(sql), params)
                    win_write_ms_sum += (time.perf_counter() - t1) * 1000.0
                    win_writes_ok += 1
                    try:
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t1) * 1000.0, ok=True, rows=1, table_id=tbl_id, target_id=target_id)
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("Job %s write failed for table %s: %s", job_id, tbl_id, e)
                    win_writes_err += 1
                    try:
                        table = Store.instance().get_table(tbl_id)
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t_start) * 1000.0, ok=False, rows=0, table_id=tbl_id, target_id=target_id)
                        METRICS.get_job(job_id).record_error("WRITE_ERROR", str(e))
                    except Exception:
                        pass
        else:
            # Trigger jobs: evaluate conditions; when true, log one row of all mapped columns
            triggers = job.get("triggers") or []
            # Group triggers by table id
            by_tbl: Dict[str, List[Dict[str, Any]]] = {}
            for tr in triggers:
                tid = tr.get("tableId") or (job.get("tables") or [None])[0]
                if not tid:
                    continue
                by_tbl.setdefault(tid, []).append(tr)
            for tbl_id, tlist in by_tbl.items():
                try:
                    t0 = time.perf_counter()
                    vals = _read_mapping_values(tbl_id)
                    win_read_ms_sum += (time.perf_counter() - t0) * 1000.0
                    win_reads_ok += 1
                    METRICS.get_job(job_id).record_read((time.perf_counter() - t0) * 1000.0, ok=True)
                except Exception as e:
                    log.warning("Trigger job %s read failed for table %s: %s", job_id, tbl_id, e)
                    win_reads_err += 1
                    try:
                        METRICS.get_job(job_id).record_read((time.perf_counter() - t_start) * 1000.0, ok=False)
                        METRICS.get_job(job_id).record_error("READ_ERROR", str(e))
                    except Exception:
                        pass
                    continue
                try:
                    lv = _job_last_values[job_id].setdefault(tbl_id, {})
                    should_fire = False
                    for tr in tlist:
                        fkey = tr.get("field") or tr.get("fieldKey")
                        op = (tr.get("op") or "change").lower()
                        threshold = tr.get("value")
                        deadband = float(tr.get("deadband") or 0.0)
                        v = vals.get(fkey)
                        pv = lv.get(fkey)
                        fired = _eval_op(v, pv, op, threshold, deadband=deadband)
                        if fired:
                            should_fire = True
                            break
                    METRICS.get_job(job_id).record_trigger_eval(fired=should_fire, suppressed=False)
                    # Update last values for edge/change detection
                    for k, v in vals.items():
                        lv[k] = v
                    if not should_fire:
                        continue
                    # Cooldown per table
                    cd_ms =  float((tlist[0].get("cooldownMs") if tlist else 0) or 0)
                    now = time.perf_counter()
                    last_t = _job_cooldowns[job_id].get(tbl_id) or 0.0
                    if cd_ms > 0 and (now - last_t) < (cd_ms/1000.0):
                        METRICS.get_job(job_id).record_trigger_eval(fired=False, suppressed=True)
                        continue
                    _job_cooldowns[job_id][tbl_id] = now
                    # Write one coherent row
                    engine = _db_engine_for_table(tbl_id)
                    table = Store.instance().get_table(tbl_id)
                    logical = table.get("name") if table else None
                    if not logical:
                        continue
                    ident = _physical_ident(engine, logical)
                    cols = ["timestamp_utc"] + list(vals.keys())
                    placeholders = ",".join([":ts"] + [f":{k}" for k in vals.keys()])
                    params = {"ts": datetime.now(timezone.utc).isoformat(), **vals}
                    col_list = ",".join(cols)
                    sql = f"INSERT INTO {ident['qualified']} ({col_list}) VALUES ({placeholders})"
                    t1 = time.perf_counter()
                    with engine.begin() as conn:
                        conn.execute(text(sql), params)
                    win_write_ms_sum += (time.perf_counter() - t1) * 1000.0
                    win_writes_ok += 1
                    try:
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t1) * 1000.0, ok=True, rows=1, table_id=tbl_id, target_id=target_id)
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("Trigger job %s write failed for table %s: %s", job_id, tbl_id, e)
                    win_writes_err += 1
                    try:
                        table = Store.instance().get_table(tbl_id)
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t_start) * 1000.0, ok=False, rows=0, table_id=tbl_id, target_id=target_id)
                        METRICS.get_job(job_id).record_error("WRITE_ERROR", str(e))
                    except Exception:
                        pass
        # sleep remaining time
        dt = time.perf_counter() - t_start
        win_loops += 1
        if dt > interval:
            win_overruns += 1
        loop_samples_ms.append(dt * 1000.0)
        now = time.perf_counter()
        if (now - last_report) >= report_every:
            elapsed = now - last_report
            reads_per_sec = win_reads_ok / elapsed if elapsed > 0 else 0.0
            writes_per_sec = win_writes_ok / elapsed if elapsed > 0 else 0.0
            p95 = _percentile_ms(list(loop_samples_ms), 95.0)
            overrun_pct = (win_overruns / win_loops * 100.0) if win_loops else 0.0
            read_avg_ms = (win_read_ms_sum / win_reads_ok) if win_reads_ok else 0.0
            write_avg_ms = (win_write_ms_sum / win_writes_ok) if win_writes_ok else 0.0
            p95_txt = f"{p95:.2f}" if p95 is not None else "na"
            cpu_time_now = _get_thread_cpu_time_sec(thread_id)
            cpu_time_ms = None
            if cpu_time_now is not None and last_cpu_time is not None:
                cpu_time_ms = max(0.0, (cpu_time_now - last_cpu_time) * 1000.0)
            proc_stats = _get_process_stats()
            proc_cpu = proc_stats[0] if proc_stats else None
            proc_rss = proc_stats[1] if proc_stats else None
            log.info(
                "Job %s bench window=%.1fs reads/s=%.1f writes/s=%.1f read_avg_ms=%.2f write_avg_ms=%.2f loop_p95_ms=%s overrun_pct=%.1f cpu_time_ms=%s proc_cpu_pct=%s proc_rss_mb=%s read_err=%s write_err=%s",
                job_id,
                elapsed,
                reads_per_sec,
                writes_per_sec,
                read_avg_ms,
                write_avg_ms,
                p95_txt,
                overrun_pct,
                f"{cpu_time_ms:.2f}" if cpu_time_ms is not None else "na",
                f"{proc_cpu:.1f}" if proc_cpu is not None else "na",
                f"{proc_rss:.1f}" if proc_rss is not None else "na",
                win_reads_err,
                win_writes_err,
            )
            try:
                _append_bench_csv({
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "job_id": job_id,
                    "window_secs": f"{elapsed:.1f}",
                    "reads_per_sec": f"{reads_per_sec:.1f}",
                    "writes_per_sec": f"{writes_per_sec:.1f}",
                    "read_avg_ms": f"{read_avg_ms:.2f}",
                    "write_avg_ms": f"{write_avg_ms:.2f}",
                    "loop_p95_ms": p95_txt,
                    "overrun_pct": f"{overrun_pct:.1f}",
                    "cpu_time_ms": f"{cpu_time_ms:.2f}" if cpu_time_ms is not None else "na",
                    "proc_cpu_pct": f"{proc_cpu:.1f}" if proc_cpu is not None else "na",
                    "proc_rss_mb": f"{proc_rss:.1f}" if proc_rss is not None else "na",
                    "read_err": str(win_reads_err),
                    "write_err": str(win_writes_err),
                })
            except Exception:
                pass
            last_cpu_time = cpu_time_now if cpu_time_now is not None else last_cpu_time
            last_report = now
            win_reads_ok = 0
            win_reads_err = 0
            win_writes_ok = 0
            win_writes_err = 0
            win_read_ms_sum = 0.0
            win_write_ms_sum = 0.0
            win_loops = 0
            win_overruns = 0
            loop_samples_ms.clear()
        to_sleep = max(0.0, interval - dt)
        if to_sleep > 0:
            stop_event.wait(timeout=to_sleep)


@router.get("")
def list_jobs() -> Dict[str, Any]:
    return {"items": Store.instance().list_jobs()}


@router.post("")
def create_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        job = Store.instance().create_job(payload)
        return {"success": True, "item": job}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/metrics/summary")
def jobs_metrics_summary() -> Dict[str, Any]:
    from ...metrics import metrics as METRICS
    summary = METRICS.jobs_summary()
    items = []
    for jid, s in summary.items():
        items.append({"jobId": jid, **s})
    return {"ok": True, "data": items}


@router.post("/{job_id}/start")
def start_job(job_id: str) -> Dict[str, Any]:
    job = Store.instance().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if _job_threads.get(job_id) and _job_threads[job_id].is_alive():
        return {"success": True, "message": "already_running"}
    ev = threading.Event()
    _job_stops[job_id] = ev
    thr = threading.Thread(target=_run_job_loop, args=(job_id,), daemon=True)
    _job_threads[job_id] = thr
    Store.instance().set_job_status(job_id, "running")
    thr.start()
    return {"success": True, "message": "started"}


@router.post("/{job_id}/pause")
def pause_job(job_id: str) -> Dict[str, Any]:
    if not Store.instance().get_job(job_id):
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    ev = _job_stops.get(job_id)
    if ev:
        ev.set()
    thr = _job_threads.get(job_id)
    if thr and thr.is_alive():
        thr.join(timeout=2.0)
    # finalize run metrics
    try:
        run = METRICS.get_job(job_id).end_run()
        if run:
            from .. import appdb
            appdb.insert_job_run(job_id, run)
    except Exception:
        pass
    Store.instance().set_job_status(job_id, "paused")
    return {"success": True, "message": "paused"}


@router.post("/{job_id}/stop")
def stop_job(job_id: str) -> Dict[str, Any]:
    if not Store.instance().get_job(job_id):
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    ev = _job_stops.get(job_id)
    if ev:
        ev.set()
    thr = _job_threads.get(job_id)
    if thr and thr.is_alive():
        thr.join(timeout=2.0)
    # finalize run metrics
    try:
        run = METRICS.get_job(job_id).end_run()
        if run:
            from .. import appdb
            appdb.insert_job_run(job_id, run)
    except Exception:
        pass
    Store.instance().set_job_status(job_id, "stopped")
    return {"success": True, "message": "stopped"}


@router.post("/stop_all")
def stop_all_jobs() -> Dict[str, Any]:
    store = Store.instance()
    jobs = store.list_jobs()
    stopped = 0
    for job in jobs:
        job_id = job.get("id")
        if not job_id:
            continue
        ev = _job_stops.get(job_id)
        if ev:
            ev.set()
        thr = _job_threads.get(job_id)
        if thr and thr.is_alive():
            thr.join(timeout=2.0)
        try:
            run = METRICS.get_job(job_id).end_run()
            if run:
                from .. import appdb
                appdb.insert_job_run(job_id, run)
        except Exception:
            pass
        store.set_job_status(job_id, "stopped")
        stopped += 1
    return {"success": True, "stopped": stopped}


@router.post("/{job_id}/dry_run")
def dry_run(job_id: str) -> Dict[str, Any]:
    job = Store.instance().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    samples = []
    for tbl_id in job.get("tables") or []:
        try:
            vals = _read_mapping_values(tbl_id)
            samples.append({"tableId": tbl_id, "values": vals, "ts": datetime.now(timezone.utc).isoformat()})
        except Exception as e:
            samples.append({"tableId": tbl_id, "error": str(e)})
    return {"success": True, "items": samples}


@router.get("/{job_id}/metrics")
def job_metrics(job_id: str, range: Optional[str] = None) -> Dict[str, Any]:
    def _parse_range(r: Optional[str]) -> int:
        if not r:
            return 900
        s = str(r).strip().lower()
        try:
            if s.endswith("ms"):
                return max(1, int(int(s[:-2]) / 1000))
            if s.endswith("s"):
                return max(1, int(s[:-1]))
            if s.endswith("m"):
                return max(1, int(float(s[:-1]) * 60))
            if s.endswith("h"):
                return max(1, int(float(s[:-1]) * 3600))
            return max(1, int(s))
        except Exception:
            return 900
    from ...metrics import metrics as METRICS
    jm = METRICS.get_job(job_id)
    window_secs = _parse_range(range)
    series = jm.timeseries(window_secs)
    summary = jm.summary_last_secs(min(window_secs, 60))
    return {"ok": True, "data": {"timeseries": series, "summary": summary}}


@router.delete("/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    """Stop if running, delete from App DB + memory, and clear metrics/history.
    Returns success or raises appropriate errors.
    """
    job = Store.instance().get_job(job_id)
    if not job:
        # Idempotent delete; return success=false to allow UI to update
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    # Stop any running thread
    try:
        ev = _job_stops.get(job_id)
        if ev:
            ev.set()
        thr = _job_threads.get(job_id)
        if thr and thr.is_alive():
            thr.join(timeout=2.0)
        # finalize run metrics (persist last run)
        try:
            run = METRICS.get_job(job_id).end_run()
            if run:
                from .. import appdb
                appdb.insert_job_run(job_id, run)
        except Exception:
            pass
    except Exception:
        # non-fatal
        pass
    # Remove from store + DB (cascades in appdb)
    try:
        ok = Store.instance().delete_job(job_id)
    except Exception:
        raise HTTPException(status_code=500, detail="JOB_DELETE_FAILED")
    if not ok:
        raise HTTPException(status_code=500, detail="JOB_DELETE_FAILED")
    # Cleanup metrics memory
    try:
        METRICS.jobs.pop(job_id, None)
        _job_threads.pop(job_id, None)
        _job_stops.pop(job_id, None)
        _job_last_values.pop(job_id, None)
        _job_cooldowns.pop(job_id, None)
    except Exception:
        pass
    return {"success": True}


@router.delete("")
def delete_jobs_bulk(payload: Dict[str, Any]) -> Dict[str, Any]:
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="NO_JOB_IDS")
    deleted = 0
    failed: List[Dict[str, Any]] = []
    for job_id in ids:
        try:
            job = Store.instance().get_job(job_id)
            if not job:
                failed.append({"id": job_id, "error": "JOB_NOT_FOUND"})
                continue
            try:
                ev = _job_stops.get(job_id)
                if ev:
                    ev.set()
                thr = _job_threads.get(job_id)
                if thr and thr.is_alive():
                    thr.join(timeout=2.0)
                try:
                    run = METRICS.get_job(job_id).end_run()
                    if run:
                        from .. import appdb
                        appdb.insert_job_run(job_id, run)
                except Exception:
                    pass
            except Exception:
                pass
            ok = Store.instance().delete_job(job_id)
            if not ok:
                failed.append({"id": job_id, "error": "JOB_DELETE_FAILED"})
                continue
            try:
                METRICS.jobs.pop(job_id, None)
                _job_threads.pop(job_id, None)
                _job_stops.pop(job_id, None)
                _job_last_values.pop(job_id, None)
                _job_cooldowns.pop(job_id, None)
            except Exception:
                pass
            deleted += 1
        except Exception as e:
            failed.append({"id": job_id, "error": str(e)})
    return {"success": True, "deleted": deleted, "failed": failed}


@router.get("/{job_id}/runs")
def job_runs(job_id: str, frm: Optional[str] = None, to: Optional[str] = None) -> Dict[str, Any]:
    from .. import appdb
    items = appdb.load_job_runs(job_id, frm=frm, to=to)
    # Include active run (synthetic, not yet persisted) for real-time UI updates
    try:
        jm = METRICS.get_job(job_id)
        ar = jm.active_run
        if ar:
            # Compute derived fields similar to end_run()
            r_n = max(1, int(ar.get("read_lat_n") or 0))
            w_n = max(1, int(ar.get("write_lat_n") or 0))
            read_lat_avg = float(ar.get("read_lat_sum") or 0.0) / r_n
            write_lat_avg = float(ar.get("write_lat_sum") or 0.0) / w_n
            rows = max(1, int(ar.get("rows") or 0))
            err_pct = (float(ar.get("errors") or 0) / float(rows)) * 100.0
            active = {
                "id": 0,
                "job_id": job_id,
                "started_at": ar.get("started_at"),
                "stopped_at": None,
                "duration_ms": None,
                "rows": ar.get("rows") or 0,
                "read_lat_avg": read_lat_avg,
                "write_lat_avg": write_lat_avg,
                "error_pct": err_pct,
            }
            items = [active] + items
    except Exception:
        pass
    return {"ok": True, "data": items}


@router.get("/{job_id}/errors")
def job_errors(job_id: str, frm: Optional[str] = None, to: Optional[str] = None) -> Dict[str, Any]:
    # For now, return in-memory aggregated error counts with last message
    from ...metrics import metrics as METRICS
    jm = METRICS.get_job(job_id)
    errs = []
    for code, (cnt, last_msg, last_ts) in jm.errors.items():
        errs.append({"code": code, "count": cnt, "lastMessage": last_msg, "lastTs": int(last_ts)})
    return {"ok": True, "data": errs}


@router.post("/{job_id}/backfill")
def backfill(job_id: str) -> Dict[str, Any]:
    job = Store.instance().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    wrote = 0
    for tbl_id in job.get("tables") or []:
        try:
            vals = _read_mapping_values(tbl_id)
            engine = _db_engine_for_table(tbl_id)
            table = Store.instance().get_table(tbl_id)
            name = table.get("name") if table else None
            if not name:
                continue
            cols = ["timestamp_utc"] + list(vals.keys())
            placeholders = ",".join([":ts"] + [f":{k}" for k in vals.keys()])
            params = {"ts": _now_ist_iso(), **vals}
            col_list = ",".join(cols)
            sql = f"INSERT INTO {name} ({col_list}) VALUES ({placeholders})"
            with engine.begin() as conn:
                conn.execute(text(sql), params)
            wrote += 1
        except Exception as e:
            return {"success": False, "message": str(e), "wrote": wrote}
    return {"success": True, "wrote": wrote}
IST = timezone(timedelta(hours=5, minutes=30))
def _now_ist_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


# ---- Boot helpers ----
def start_enabled_jobs_on_boot() -> int:
    """Start threads for jobs that are marked enabled (idempotent)."""
    store = Store.instance()
    started = 0
    for j in store.list_jobs():
        try:
            if not j.get("enabled"):
                continue
            jid = j.get("id")
            if not jid:
                continue
            thr = _job_threads.get(jid)
            if thr and thr.is_alive():
                continue
            ev = threading.Event()
            _job_stops[jid] = ev
            t = threading.Thread(target=_run_job_loop, args=(jid,), daemon=True)
            _job_threads[jid] = t
            store.set_job_status(jid, "running")
            try:
                t.start()
                started += 1
            except Exception:
                store.set_job_status(jid, "stopped")
        except Exception:
            pass
    if started:
        log.info("Boot-started %s enabled jobs", started)
    return started
