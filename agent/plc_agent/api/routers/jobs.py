from __future__ import annotations

import threading
import time
import logging
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


def _db_engine_for_table(table_id: str):
    store = Store.instance()
    t = store.get_table(table_id)
    if not t:
        raise RuntimeError("TABLE_NOT_FOUND")
    target_id = t.get("dbTargetId") or store.get_default_db_target()
    url = "sqlite:///mydatabase.db"
    if target_id:
        target = store.get_db_target(target_id)
        if target and target.get("provider") == "sqlite":
            conn = target.get("conn") or ":memory:"
            url = f"sqlite:///{conn}" if not str(conn).startswith("sqlite:") else conn
    return create_engine(url)


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
            from opcua import Client  # type: ignore
        except Exception as e:
            raise RuntimeError(f"OPCUA_PKG_MISSING: {e}")
        endpoint = params.get("endpoint") or "opc.tcp://127.0.0.1:4840/freeopcua/server/"
        # Some servers advertise 0.0.0.0 which is not connectable; replace with loopback
        if isinstance(endpoint, str) and "0.0.0.0" in endpoint:
            safe_ep = endpoint.replace("0.0.0.0", "127.0.0.1")
            log.info("OPC UA endpoint normalized from %s to %s", endpoint, safe_ep)
            endpoint = safe_ep
        client = Client(endpoint)
        try:
            log.info("OPC UA: connecting endpoint=%s", endpoint)
            client.connect()
            log.info("OPC UA: connected endpoint=%s", endpoint)
            for field, spec in rows.items():
                if (spec.get("protocol") or "").lower() != "opcua":
                    continue
                nid = spec.get("address") or spec.get("nodeId")
                if not nid:
                    continue
                try:
                    node = client.get_node(nid)
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
            raise
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
    elif proto == "modbus":
        # TODO: Implement TCP/RTU reads. For now, stub None values.
        for field, spec in rows.items():
            # For now we do not implement pyModbus here; return None
            values[field] = None
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
    while not stop_event.is_set():
        t_start = time.perf_counter()
        if jtype == "continuous":
            for tbl_id in job.get("tables") or []:
                # Read values
                try:
                    t0 = time.perf_counter()
                    vals = _read_mapping_values(tbl_id)
                    METRICS.get_job(job_id).record_read((time.perf_counter() - t0) * 1000.0, ok=True)
                except Exception as e:
                    log.warning("Job %s read failed for table %s: %s", job_id, tbl_id, e)
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
                    try:
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t1) * 1000.0, ok=True, rows=1, table_id=tbl_id, target_id=target_id)
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("Job %s write failed for table %s: %s", job_id, tbl_id, e)
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
                    METRICS.get_job(job_id).record_read((time.perf_counter() - t0) * 1000.0, ok=True)
                except Exception as e:
                    log.warning("Trigger job %s read failed for table %s: %s", job_id, tbl_id, e)
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
                    try:
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t1) * 1000.0, ok=True, rows=1, table_id=tbl_id, target_id=target_id)
                    except Exception:
                        pass
                except Exception as e:
                    log.warning("Trigger job %s write failed for table %s: %s", job_id, tbl_id, e)
                    try:
                        table = Store.instance().get_table(tbl_id)
                        target_id = table.get("dbTargetId") if table else None
                        METRICS.get_job(job_id).record_write((time.perf_counter() - t_start) * 1000.0, ok=False, rows=0, table_id=tbl_id, target_id=target_id)
                        METRICS.get_job(job_id).record_error("WRITE_ERROR", str(e))
                    except Exception:
                        pass
        # sleep remaining time
        dt = time.perf_counter() - t_start
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
