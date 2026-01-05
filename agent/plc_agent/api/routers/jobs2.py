from __future__ import annotations

import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text

from ..store import Store
router = APIRouter(prefix="/jobs2")

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
        if target and target.get("provider") == "sqlite":
            conn = target.get("conn") or ":memory:"
            url = f"sqlite:///{conn}" if not str(conn).startswith("sqlite:") else conn
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


_opcua_clients: Dict[str, Any] = {}
_opcua_nodes: Dict[tuple[str, str], Any] = {}
_opcua_lock = threading.RLock()


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
        # TODO: Implement TCP/RTU reads. For now, stub None values.
        for field, spec in rows.items():
            values[field] = None
    else:
        raise RuntimeError("PROTOCOL_NOT_SUPPORTED")
    return values


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


@router.post("/{job_id}/start")
def start_job(job_id: str) -> Dict[str, Any]:
    job = Store.instance().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if (job.get("status") or "").lower() == "running":
        return {"success": True, "message": "already_running"}
    Store.instance().set_job_status(job_id, "running")
    return {"success": True, "message": "started"}


@router.post("/{job_id}/pause")
def pause_job(job_id: str) -> Dict[str, Any]:
    if not Store.instance().get_job(job_id):
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    Store.instance().set_job_status(job_id, "paused")
    return {"success": True, "message": "paused"}


@router.post("/{job_id}/stop")
def stop_job(job_id: str) -> Dict[str, Any]:
    if not Store.instance().get_job(job_id):
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
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


@router.delete("/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    """Delete from App DB + memory, and clear metrics/history."""
    job = Store.instance().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    try:
        ok = Store.instance().delete_job(job_id)
    except Exception:
        raise HTTPException(status_code=500, detail="JOB_DELETE_FAILED")
    if not ok:
        raise HTTPException(status_code=500, detail="JOB_DELETE_FAILED")
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
            ok = Store.instance().delete_job(job_id)
            if not ok:
                failed.append({"id": job_id, "error": "JOB_DELETE_FAILED"})
                continue
            deleted += 1
        except Exception as e:
            failed.append({"id": job_id, "error": str(e)})
    return {"success": True, "deleted": deleted, "failed": failed}


@router.get("/{job_id}/runs")
def job_runs(job_id: str, frm: Optional[str] = None, to: Optional[str] = None) -> Dict[str, Any]:
    from .. import appdb
    items = appdb.load_job_runs(job_id, frm=frm, to=to)
    return {"ok": True, "data": items}


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
    """Mark enabled jobs as running (execution handled externally)."""
    store = Store.instance()
    started = 0
    for j in store.list_jobs():
        try:
            if not j.get("enabled"):
                continue
            jid = j.get("id")
            if not jid:
                continue
            if (j.get("status") or "").lower() == "running":
                continue
            store.set_job_status(jid, "running")
            started += 1
        except Exception:
            pass
    if started:
        log.info("Boot-marked %s enabled jobs as running", started)
    return started
