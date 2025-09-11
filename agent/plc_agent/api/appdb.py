from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _app_folder() -> Path:
    # Prefer explicit override; else ProgramData for production; else repo root; fallback to CWD
    override = os.environ.get("APP_DB_DIR")
    if override:
        folder = Path(override)
    else:
        pd = os.environ.get("ProgramData")
        if pd:
            folder = Path(pd) / "PLCLogger" / "agent"
        else:
            try:
                # repo root: agent/plc_agent/api/appdb.py -> up 3 levels
                folder = Path(__file__).resolve().parents[3]
            except Exception:
                folder = Path(os.getcwd())
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def app_db_path() -> Path:
    return _app_folder() / "app.db"


def _conn() -> sqlite3.Connection:
    p = app_db_path()
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_schemas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_schema_fields (
                schema_id TEXT,
                key TEXT,
                type TEXT,
                unit TEXT,
                scale REAL,
                desc TEXT,
                PRIMARY KEY (schema_id, key)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_db_targets (
                id TEXT PRIMARY KEY,
                provider TEXT,
                conn TEXT,
                status TEXT,
                last_msg TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_device_tables (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                schema_id TEXT NOT NULL,
                db_target_id TEXT,
                status TEXT,
                last_migrated_at TEXT,
                schema_hash TEXT,
                mapping_health TEXT,
                device_id TEXT
            )
            """
        )
        # Saved gateways (reachability)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_gateways (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                host TEXT UNIQUE,
                adapter_id TEXT
            )
            """
        )
        # Ensure extended columns for gateways (SQLite ALTERs are additive)
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(app_gateways)").fetchall()}
        except Exception:
            cols = set()
        def _ensure(col: str, typ: str) -> None:
            if col not in cols:
                try:
                    c.execute(f"ALTER TABLE app_gateways ADD COLUMN {col} {typ}")
                    cols.add(col)
                except Exception:
                    pass
        _ensure("ports_json", "TEXT")
        _ensure("protocol_hint", "TEXT")
        _ensure("tags_json", "TEXT")
        _ensure("nic_hint", "TEXT")
        _ensure("status", "TEXT")
        _ensure("last_ping_json", "TEXT")
        _ensure("last_tcp_json", "TEXT")
        _ensure("created_at", "TEXT")
        _ensure("updated_at", "TEXT")
        _ensure("last_test_at", "TEXT")
        # Saved devices catalog (metadata only; no secrets)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_devices (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                protocol TEXT,
                params_json TEXT,
                status TEXT,
                latency_ms INTEGER,
                last_error TEXT
            )
            """
        )
        # Ensure extended columns for devices
        try:
            dcols = {r[1] for r in c.execute("PRAGMA table_info(app_devices)").fetchall()}
        except Exception:
            dcols = set()
        def _ensure_dev(col: str, typ: str) -> None:
            if col not in dcols:
                try:
                    c.execute(f"ALTER TABLE app_devices ADD COLUMN {col} {typ}")
                    dcols.add(col)
                except Exception:
                    pass
        _ensure_dev("auto_reconnect", "INTEGER")
        # Jobs config persistence
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                tables_json TEXT,
                columns_json TEXT,
                interval_ms INTEGER,
                enabled INTEGER,
                status TEXT,
                batching_json TEXT,
                cpu_budget TEXT,
                triggers_json TEXT,
                metrics_json TEXT
            )
            """
        )
        # Job run history
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TEXT,
                stopped_at TEXT,
                duration_ms INTEGER,
                rows INTEGER,
                read_lat_avg REAL,
                write_lat_avg REAL,
                error_pct REAL
            )
            """
        )
        # Per-minute rollups (jobs)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metrics_jobs_minute (
                job_id TEXT NOT NULL,
                minute_utc TEXT NOT NULL,
                reads INTEGER,
                read_err INTEGER,
                writes INTEGER,
                write_err INTEGER,
                read_p50 REAL,
                read_p95 REAL,
                write_p50 REAL,
                write_p95 REAL,
                triggers INTEGER,
                fires INTEGER,
                suppressed INTEGER,
                PRIMARY KEY (job_id, minute_utc)
            )
            """
        )
        # Per-minute rollups (system)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metrics_system_minute (
                minute_utc TEXT PRIMARY KEY,
                cpu REAL,
                mem REAL,
                disk_rps REAL,
                disk_wps REAL,
                net_rxps REAL,
                net_txps REAL,
                proc_cpu REAL,
                proc_rss_mb REAL,
                proc_handles INTEGER
            )
            """
        )
        # Aggregated job errors per minute
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_job_errors_minute (
                job_id TEXT NOT NULL,
                code TEXT NOT NULL,
                minute_utc TEXT NOT NULL,
                count INTEGER,
                last_message TEXT,
                PRIMARY KEY (job_id, code, minute_utc)
            )
            """
        )


# ---------- Schemas ----------
def load_schemas() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT id, name FROM app_schemas ORDER BY name").fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            f = c.execute(
                "SELECT key, type, unit, scale, desc FROM app_schema_fields WHERE schema_id=? ORDER BY key",
                (r["id"],),
            ).fetchall()
            out.append({
                "id": r["id"],
                "name": r["name"],
                "fields": [dict(x) for x in f],
            })
        return out


def save_schema(schema: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO app_schemas (id,name) VALUES (?,?)", (schema["id"], schema["name"]))
        c.execute("DELETE FROM app_schema_fields WHERE schema_id=?", (schema["id"],))
        for fld in schema.get("fields") or []:
            c.execute(
                "INSERT OR REPLACE INTO app_schema_fields (schema_id,key,type,unit,scale,desc) VALUES (?,?,?,?,?,?)",
                (schema["id"], fld.get("key"), fld.get("type"), fld.get("unit"), fld.get("scale"), fld.get("desc")),
            )


def import_schemas(items: List[Dict[str, Any]]) -> int:
    for it in items:
        if not it or not it.get("name"):
            continue
        save_schema({"id": it.get("id"), "name": it.get("name"), "fields": it.get("fields") or []})
    return len(items)


# ---------- Targets ----------
def load_targets() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    with _conn() as c:
        rs = c.execute("SELECT id,provider,conn,status,last_msg FROM app_db_targets ORDER BY id").fetchall()
        items = [dict(r) for r in rs]
        row = c.execute("SELECT value FROM app_meta WHERE key='default_db_target'").fetchone()
        default_id = row[0] if row else None
        return items, default_id


def save_target(item: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO app_db_targets (id,provider,conn,status,last_msg) VALUES (?,?,?,?,?)",
            (item["id"], item.get("provider"), item.get("conn"), item.get("status"), item.get("lastMsg")),
        )


def set_default_target(tid: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO app_meta (key,value) VALUES ('default_db_target',?)", (tid,))


# ---------- Device tables ----------
def load_device_tables() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = c.execute(
            "SELECT id,name,schema_id,db_target_id,status,last_migrated_at,schema_hash,mapping_health,device_id FROM app_device_tables ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rs]


def add_tables_bulk(items: List[Dict[str, Any]]) -> None:
    with _conn() as c:
        for t in items:
            c.execute(
                """
                INSERT OR REPLACE INTO app_device_tables (id,name,schema_id,db_target_id,status,last_migrated_at,schema_hash,mapping_health,device_id)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    t["id"],
                    t["name"],
                    t["schemaId"],
                    t.get("dbTargetId"),
                    t.get("status"),
                    t.get("lastMigratedAt"),
                    t.get("schemaHash"),
                    t.get("mappingHealth"),
                    t.get("deviceId"),
                ),
            )


def set_table_status(table_id: str, status: str, last_migrated_at: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE app_device_tables SET status=?, last_migrated_at=? WHERE id=?",
            (status, last_migrated_at, table_id),
        )


def delete_table(table_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM app_device_tables WHERE id=?", (table_id,))


def update_mapping_health(table_id: str, health: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE app_device_tables SET mapping_health=? WHERE id=?",
            (health, table_id),
        )


def set_table_device_binding(table_id: str, device_id: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE app_device_tables SET device_id=? WHERE id=?",
            (device_id, table_id),
        )


# ---------- Gateways ----------
def load_gateways() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = c.execute(
            "SELECT id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,last_ping_json,last_tcp_json,created_at,updated_at,last_test_at FROM app_gateways ORDER BY name"
        ).fetchall()
        out: List[Dict[str, Any]] = []
        import json as _json
        for r in rs:
            d = dict(r)
            try:
                ports = _json.loads(d.get("ports_json") or "[]")
            except Exception:
                ports = []
            try:
                tags = _json.loads(d.get("tags_json") or "[]")
            except Exception:
                tags = []
            try:
                last_ping = _json.loads(d.get("last_ping_json") or "null")
            except Exception:
                last_ping = None
            try:
                last_tcp = _json.loads(d.get("last_tcp_json") or "null")
            except Exception:
                last_tcp = None
            out.append(
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "host": d.get("host"),
                    "adapter_id": d.get("adapter_id"),
                    "nic_hint": d.get("nic_hint") or d.get("adapter_id"),
                    "ports": ports,
                    "protocol_hint": d.get("protocol_hint"),
                    "tags": tags,
                    "status": d.get("status") or "unknown",
                    "last_ping": last_ping,
                    "last_tcp": last_tcp,
                    "created_at": d.get("created_at"),
                    "updated_at": d.get("updated_at"),
                    "last_test_at": d.get("last_test_at"),
                }
            )
        return out


def upsert_gateway(gw: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    now_iso = time_iso()
    with _conn() as c:
        # Enforce uniqueness by name or host
        existing = c.execute(
            "SELECT id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,last_ping_json,last_tcp_json,created_at,updated_at,last_test_at FROM app_gateways WHERE name=? OR host=?",
            (gw.get("name"), gw.get("host")),
        ).fetchone()
        if existing:
            return dict(existing)
        ports = gw.get("ports") or []
        tags = gw.get("tags") or []
        c.execute(
            """
            INSERT INTO app_gateways (id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,last_ping_json,last_tcp_json,created_at,updated_at,last_test_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                gw["id"],
                gw.get("name"),
                gw.get("host"),
                gw.get("adapterId"),
                gw.get("nic_hint") or gw.get("adapterId"),
                _json.dumps(ports),
                gw.get("protocol_hint"),
                _json.dumps(tags),
                gw.get("status") or "unknown",
                None,
                None,
                now_iso,
                now_iso,
                None,
            ),
        )
        return {
            "id": gw["id"],
            "name": gw.get("name"),
            "host": gw.get("host"),
            "adapter_id": gw.get("adapterId"),
            "nic_hint": gw.get("nic_hint") or gw.get("adapterId"),
            "ports": ports,
            "protocol_hint": gw.get("protocol_hint"),
            "tags": tags,
            "status": gw.get("status") or "unknown",
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_test_at": None,
            "last_ping": None,
            "last_tcp": None,
        }


def delete_gateway(gid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM app_gateways WHERE id=?", (gid,))


# ---------- Gateway helpers ----------
def time_iso() -> str:
    import datetime as _dt
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def get_gateway(gid: str) -> Optional[Dict[str, Any]]:
    items = [g for g in load_gateways() if g.get("id") == gid]
    return items[0] if items else None


def update_gateway(gid: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT id FROM app_gateways WHERE id=?", (gid,)).fetchone()
        if not row:
            return None
        fields = []
        values: List[Any] = []
        if "name" in patch:
            fields.append("name=?"); values.append(patch.get("name"))
        if "host" in patch:
            fields.append("host=?"); values.append(patch.get("host"))
        if "adapterId" in patch or "nic_hint" in patch:
            fields.append("nic_hint=?"); values.append(patch.get("nic_hint") or patch.get("adapterId"))
        if "ports" in patch:
            fields.append("ports_json=?"); values.append(_json.dumps(patch.get("ports") or []))
        if "protocol_hint" in patch:
            fields.append("protocol_hint=?"); values.append(patch.get("protocol_hint"))
        if "tags" in patch:
            fields.append("tags_json=?"); values.append(_json.dumps(patch.get("tags") or []))
        # timestamps
        fields.append("updated_at=?"); values.append(time_iso())
        sql = f"UPDATE app_gateways SET {', '.join(fields)} WHERE id=?"
        values.append(gid)
        c.execute(sql, tuple(values))
    return get_gateway(gid)


def set_gateway_health(
    gid: str,
    *,
    status: Optional[str] = None,
    last_ping: Optional[Dict[str, Any]] = None,
    last_tcp: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    import json as _json
    with _conn() as c:
        row = c.execute("SELECT id FROM app_gateways WHERE id=?", (gid,)).fetchone()
        if not row:
            return None
        fields = []
        values: List[Any] = []
        if status is not None:
            fields.append("status=?"); values.append(status)
        if last_ping is not None:
            fields.append("last_ping_json=?"); values.append(_json.dumps(last_ping))
        if last_tcp is not None:
            fields.append("last_tcp_json=?"); values.append(_json.dumps(last_tcp))
        fields.append("last_test_at=?"); values.append(time_iso())
        sql = f"UPDATE app_gateways SET {', '.join(fields)} WHERE id=?"
        values.append(gid)
        c.execute(sql, tuple(values))
    return get_gateway(gid)


# ---------- Targets helpers ----------
def delete_target(tid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM app_db_targets WHERE id=?", (tid,))
        return cur.rowcount > 0


def count_tables_referencing_target(tid: str) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(1) AS n FROM app_device_tables WHERE db_target_id=?",
            (tid,),
        ).fetchone()
        return int(row[0] if row else 0)


# ---------- Simple DPAPI helpers (best-effort) ----------
def _dpapi_available() -> bool:
    try:
        import ctypes  # noqa: F401
        return os.name == 'nt'
    except Exception:
        return False


def _dpapi_protect(data: bytes) -> Optional[bytes]:
    if not _dpapi_available():
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", wt.LPBYTE)]

        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), wt.LPBYTE))
        blob_out = DATA_BLOB()
        # Use machine scope if requested (service context)
        flags = 0
        try:
            if os.environ.get('APP_DPAPI_MACHINE') in ('1','true','True') or os.environ.get('AGENT_DPAPI_MACHINE') in ('1','true','True'):
                flags |= 0x4  # CRYPTPROTECT_LOCAL_MACHINE
        except Exception:
            pass
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
            return None
        try:
            out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return out
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(data: bytes) -> Optional[bytes]:
    if not _dpapi_available():
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", wt.LPBYTE)]

        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, wt.LPBYTE))
        blob_out = DATA_BLOB()
        # Same flags used for protect (machine scope optional)
        flags = 0
        try:
            if os.environ.get('APP_DPAPI_MACHINE') in ('1','true','True') or os.environ.get('AGENT_DPAPI_MACHINE') in ('1','true','True'):
                flags |= 0x4
        except Exception:
            pass
        if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
            return None
        try:
            out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return out
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _params_dump(params: Dict[str, Any]) -> str:
    import json as _json
    try:
        raw = _json.dumps(params or {}).encode('utf-8')
    except Exception:
        raw = b"{}"
    enc = _dpapi_protect(raw)
    if enc is None:
        return _json.dumps(params or {})
    import base64 as _b64
    return "ENCv1:" + _b64.b64encode(enc).decode('ascii')


def _params_load(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        return {}
    s = str(text)
    if s.startswith("ENCv1:"):
        try:
            import base64 as _b64
            blob = _b64.b64decode(s[6:])
            raw = _dpapi_unprotect(blob)
            if raw is None:
                return {}
            import json as _json
            return _json.loads(raw.decode('utf-8'))
        except Exception:
            return {}
    # Plain JSON fallback
    try:
        import json as _json
        return _json.loads(s)
    except Exception:
        return {}


# ---------- Devices ----------
def load_devices() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = c.execute(
            "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect FROM app_devices ORDER BY name"
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rs:
            params = _params_load(r["params_json"]) if r["params_json"] else {}
            out.append({
                "id": r["id"],
                "name": r["name"],
                "protocol": r["protocol"],
                "params": params or {},
                "status": r["status"],
                "latencyMs": r["latency_ms"],
                "lastError": r["last_error"],
                "autoReconnect": bool(r.get("auto_reconnect", 1)) if hasattr(r, 'get') else bool(r["auto_reconnect"]) if "auto_reconnect" in r.keys() else True,
            })
        return out


def upsert_device(dev: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        # Prevent duplicates by name
        row = c.execute("SELECT id FROM app_devices WHERE name=?", (dev.get("name"),)).fetchone()
        if row:
            # Return existing
            existing = c.execute(
                "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect FROM app_devices WHERE id=?",
                (row["id"],),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "name": existing["name"], "protocol": existing["protocol"], "params": dev.get("params") or {}, "status": existing["status"], "latencyMs": existing["latency_ms"], "lastError": existing["last_error"], "autoReconnect": bool(existing.get("auto_reconnect", 1)) if hasattr(existing, 'get') else True}
        params_blob = _params_dump(dev.get("params") or {})
        c.execute(
            "INSERT OR REPLACE INTO app_devices (id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect) VALUES (?,?,?,?,?,?,?,?)",
            (
                dev["id"],
                dev.get("name"),
                dev.get("protocol"),
                params_blob,
                dev.get("status"),
                dev.get("latencyMs"),
                dev.get("lastError"),
                1 if dev.get("autoReconnect", True) else 0,
            ),
        )
        return dev


def update_device_status(dev_id: str, *, status: Optional[str], latency_ms: Optional[int], last_error: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE app_devices SET status=?, latency_ms=?, last_error=? WHERE id=?",
            (status, latency_ms, last_error, dev_id),
        )

# ---------- Jobs ----------
def load_jobs() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = c.execute(
            """
            SELECT id,name,type,tables_json,columns_json,interval_ms,enabled,status,batching_json,cpu_budget,triggers_json,metrics_json
            FROM app_jobs ORDER BY name
            """
        ).fetchall()
        import json as _json
        out: List[Dict[str, Any]] = []
        for r in rs:
            try:
                tables = _json.loads(r["tables_json"]) if r["tables_json"] else []
            except Exception:
                tables = []
            try:
                columns = _json.loads(r["columns_json"]) if r["columns_json"] else "all"
            except Exception:
                columns = "all"
            try:
                batching = _json.loads(r["batching_json"]) if r["batching_json"] else {}
            except Exception:
                batching = {}
            try:
                triggers = _json.loads(r["triggers_json"]) if r["triggers_json"] else []
            except Exception:
                triggers = []
            try:
                metrics = _json.loads(r["metrics_json"]) if r["metrics_json"] else {}
            except Exception:
                metrics = {}
            out.append({
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "tables": tables,
                "columns": columns,
                "intervalMs": r["interval_ms"],
                "enabled": bool(r["enabled"]),
                "status": r["status"],
                "batching": batching,
                "cpuBudget": r["cpu_budget"],
                "triggers": triggers,
                "metrics": metrics,
            })
        return out


def upsert_job(job: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    with _conn() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO app_jobs
            (id,name,type,tables_json,columns_json,interval_ms,enabled,status,batching_json,cpu_budget,triggers_json,metrics_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job["id"],
                job.get("name"),
                job.get("type"),
                _json.dumps(job.get("tables") or []),
                _json.dumps(job.get("columns") if job.get("columns") is not None else "all"),
                job.get("intervalMs"),
                1 if job.get("enabled") else 0,
                job.get("status"),
                _json.dumps(job.get("batching") or {}),
                job.get("cpuBudget"),
                _json.dumps(job.get("triggers") or []),
                _json.dumps(job.get("metrics") or {}),
            ),
        )
    return job


def update_job_status(job_id: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE app_jobs SET status=? WHERE id=?", (status, job_id))


def delete_job(job_id: str) -> bool:
    """Delete job config and cascade related history/metrics.
    - app_jobs (config)
    - app_job_runs (history)
    - app_metrics_jobs_minute (rollups)
    - app_job_errors_minute (error aggregates)
    Returns True if a job config row existed and was deleted.
    """
    with _conn() as c:
        cur = c.execute("DELETE FROM app_jobs WHERE id=?", (job_id,))
        # Best-effort cascade cleanup
        try:
            c.execute("DELETE FROM app_job_runs WHERE job_id=?", (job_id,))
        except Exception:
            pass
        try:
            c.execute("DELETE FROM app_metrics_jobs_minute WHERE job_id=?", (job_id,))
        except Exception:
            pass
        try:
            c.execute("DELETE FROM app_job_errors_minute WHERE job_id=?", (job_id,))
        except Exception:
            pass
        return cur.rowcount > 0


def update_device_metadata(dev_id: str, *, name: Optional[str] = None, auto_reconnect: Optional[bool] = None) -> None:
    fields: List[str] = []
    values: List[Any] = []
    if name is not None:
        fields.append("name=?"); values.append(name)
    if auto_reconnect is not None:
        fields.append("auto_reconnect=?"); values.append(1 if auto_reconnect else 0)
    if not fields:
        return
    with _conn() as c:
        sql = f"UPDATE app_devices SET {', '.join(fields)} WHERE id=?"
        values.append(dev_id)
        c.execute(sql, tuple(values))


def delete_device(dev_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM app_devices WHERE id=?", (dev_id,))


# ---------- Secrets rekey (DPAPI scope alignment) ----------
def rekey_all_device_params() -> int:
    """Re-encode stored device params using current DPAPI scope.
    This aligns plaintext or user-scoped blobs to machine scope when
    AGENT_DPAPI_MACHINE=1 (service context). Returns number of rows updated.
    """
    try:
        with _conn() as c:
            rs = c.execute("SELECT id, params_json FROM app_devices").fetchall()
            updated = 0
            for r in rs:
                try:
                    dev_id = r["id"]
                    current = r["params_json"]
                    # Load (supports ENCv1 and plain JSON)
                    params = _params_load(current)
                    # Dump using current DPAPI flags
                    fresh = _params_dump(params)
                    if fresh != current:
                        c.execute(
                            "UPDATE app_devices SET params_json=? WHERE id=?",
                            (fresh, dev_id),
                        )
                        updated += 1
                except Exception:
                    # Best-effort; continue scanning
                    pass
            return updated
    except Exception:
        return 0


# ---------- Job run history ----------
def insert_job_run(job_id: str, run: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO app_job_runs (job_id, started_at, stopped_at, duration_ms, rows, read_lat_avg, write_lat_avg, error_pct)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                run.get("started_at"),
                run.get("stopped_at"),
                run.get("duration_ms"),
                run.get("rows"),
                run.get("read_lat_avg"),
                run.get("write_lat_avg"),
                run.get("error_pct"),
            ),
        )


def load_job_runs(job_id: str, frm: Optional[str] = None, to: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT id,job_id,started_at,stopped_at,duration_ms,rows,read_lat_avg,write_lat_avg,error_pct FROM app_job_runs WHERE job_id=?"
    params: List[Any] = [job_id]
    if frm:
        sql += " AND started_at >= ?"; params.append(frm)
    if to:
        sql += " AND (stopped_at <= ? OR (stopped_at IS NULL AND started_at <= ?))"; params.append(to); params.append(to)
    sql += " ORDER BY id DESC LIMIT 500"
    with _conn() as c:
        rs = c.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rs]
