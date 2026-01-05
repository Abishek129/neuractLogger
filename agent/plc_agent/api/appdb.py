from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_ENGINE: Optional[Engine] = None


def _app_folder() -> Path:
    """Return a writable folder for the agent app data."""
    override = os.environ.get("APP_DB_DIR")
    if override:
        folder = Path(override)
    else:
        candidates = []
        pd = os.environ.get("ProgramData")
        if pd:
            for brand in ("NeuractLogger", "PLCLogger"):
                candidates.append(Path(pd) / brand / "agent")
        ld = os.environ.get("LOCALAPPDATA")
        if ld:
            for brand in ("NeuractLogger", "PLCLogger"):
                candidates.append(Path(ld) / brand / "agent")
        try:
            candidates.append(Path(__file__).resolve().parents[3])
        except Exception:
            candidates.append(Path(os.getcwd()))
        folder = None
        last_error: Exception | None = None
        for cand in candidates:
            try:
                cand.mkdir(parents=True, exist_ok=True)
                folder = cand
                break
            except PermissionError as e:
                last_error = e
                continue
        if folder is None:
            if last_error:
                raise last_error
            folder = Path(os.getcwd())
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def app_db_path() -> Path:
    return _app_folder() / "app.db"


def _db_url() -> str:
    url = os.environ.get("APP_DB_URL")
    if not url:
        raise RuntimeError("APP_DB_URL is required for metadata storage.")
    return url


def _engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(_db_url(), pool_pre_ping=True)
    return _ENGINE


@contextmanager
def _conn():
    with _engine().begin() as conn:
        yield conn


def _dialect_name() -> str:
    try:
        return _engine().dialect.name or ""
    except Exception:
        return ""


def _fetchall(conn, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows = conn.execute(text(sql), params or {}).mappings().all()
    return [dict(r) for r in rows]


def _fetchone(conn, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    row = conn.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def _column_names(conn, table: str) -> set[str]:
    if _dialect_name() == "postgresql":
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=:t AND table_schema=current_schema()"
            ),
            {"t": table},
        ).fetchall()
        return {r[0] for r in rows}
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _ensure_column(conn, table: str, col: str, typ: str) -> None:
    if _dialect_name() == "postgresql":
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}"))
        return
    cols = _column_names(conn, table)
    if col in cols:
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))


def _upsert_sql(table: str, cols: List[str], conflict_cols: List[str], update_cols: Optional[List[str]] = None) -> str:
    insert_cols = ", ".join(cols)
    placeholders = ", ".join([f":{c}" for c in cols])
    if conflict_cols:
        if update_cols is None:
            update_cols = [c for c in cols if c not in conflict_cols]
        if update_cols:
            updates = ", ".join([f"{c}=excluded.{c}" for c in update_cols])
            return (
                f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
                f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {updates}"
            )
        return (
            f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        )
    return f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders})"


def init() -> None:
    with _conn() as c:
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
        )
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_schemas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_schema_fields (
                    schema_id TEXT,
                    key TEXT,
                    type TEXT,
                    unit TEXT,
                    scale REAL,
                    desc_text TEXT,
                    PRIMARY KEY (schema_id, key)
                )
                """
            )
        )
        _ensure_column(c, "app_schema_fields", "desc_text", "TEXT")
        try:
            c.execute(
                text("UPDATE app_schema_fields SET desc_text = 'desc' WHERE desc_text IS NULL")
            )
        except Exception:
            pass
        c.execute(
            text(
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
        )
        c.execute(
            text(
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
        )
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_gateways (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE,
                    host TEXT UNIQUE,
                    adapter_id TEXT
                )
                """
            )
        )
        _ensure_column(c, "app_gateways", "ports_json", "TEXT")
        _ensure_column(c, "app_gateways", "protocol_hint", "TEXT")
        _ensure_column(c, "app_gateways", "tags_json", "TEXT")
        _ensure_column(c, "app_gateways", "nic_hint", "TEXT")
        _ensure_column(c, "app_gateways", "status", "TEXT")
        _ensure_column(c, "app_gateways", "last_ping_json", "TEXT")
        _ensure_column(c, "app_gateways", "last_tcp_json", "TEXT")
        _ensure_column(c, "app_gateways", "created_at", "TEXT")
        _ensure_column(c, "app_gateways", "updated_at", "TEXT")
        _ensure_column(c, "app_gateways", "last_test_at", "TEXT")
        c.execute(
            text(
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
        )
        _ensure_column(c, "app_devices", "auto_reconnect", "INTEGER")
        c.execute(
            text(
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
        )
        if _dialect_name() == "postgresql":
            run_id = "id BIGSERIAL PRIMARY KEY"
        else:
            run_id = "id INTEGER PRIMARY KEY AUTOINCREMENT"
        c.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS app_job_runs (
                    {run_id},
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
        )
        c.execute(
            text(
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
        )
        c.execute(
            text(
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
        )
        c.execute(
            text(
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
        )

# ---------- Schemas ----------
def load_schemas() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT id, name FROM app_schemas ORDER BY name")
        out: List[Dict[str, Any]] = []
        for r in rows:
            f = _fetchall(
                c,
                "SELECT key, type, unit, scale, desc_text AS \"desc\" "
                "FROM app_schema_fields WHERE schema_id=:schema_id ORDER BY key",
                {"schema_id": r["id"]},
            )
            out.append({"id": r["id"], "name": r["name"], "fields": f})
        return out


def save_schema(schema: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_schemas", ["id", "name"], ["id"])),
            {"id": schema["id"], "name": schema["name"]},
        )
        c.execute(text("DELETE FROM app_schema_fields WHERE schema_id=:schema_id"), {"schema_id": schema["id"]})
        for fld in schema.get("fields") or []:
            c.execute(
                text(
                    _upsert_sql(
                        "app_schema_fields",
                        ["schema_id", "key", "type", "unit", "scale", "desc_text"],
                        ["schema_id", "key"],
                    )
                ),
                {
                    "schema_id": schema["id"],
                    "key": fld.get("key"),
                    "type": fld.get("type"),
                    "unit": fld.get("unit"),
                    "scale": fld.get("scale"),
                    "desc_text": fld.get("desc"),
                },
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
        items = _fetchall(c, "SELECT id,provider,conn,status,last_msg FROM app_db_targets ORDER BY id")
        row = _fetchone(c, "SELECT value FROM app_meta WHERE key='default_db_target'")
        default_id = row["value"] if row else None
        return items, default_id


def save_target(item: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_db_targets", ["id", "provider", "conn", "status", "last_msg"], ["id"])),
            {
                "id": item["id"],
                "provider": item.get("provider"),
                "conn": item.get("conn"),
                "status": item.get("status"),
                "last_msg": item.get("lastMsg"),
            },
        )


def set_default_target(tid: str) -> None:
    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_meta", ["key", "value"], ["key"])),
            {"key": "default_db_target", "value": tid},
        )


# ---------- Device tables ----------
def load_device_tables() -> List[Dict[str, Any]]:
    with _conn() as c:
        return _fetchall(
            c,
            "SELECT id,name,schema_id,db_target_id,status,last_migrated_at,schema_hash,mapping_health,device_id "
            "FROM app_device_tables ORDER BY name",
        )


def add_tables_bulk(items: List[Dict[str, Any]]) -> None:
    with _conn() as c:
        for t in items:
            c.execute(
                text(
                    _upsert_sql(
                        "app_device_tables",
                        [
                            "id",
                            "name",
                            "schema_id",
                            "db_target_id",
                            "status",
                            "last_migrated_at",
                            "schema_hash",
                            "mapping_health",
                            "device_id",
                        ],
                        ["id"],
                    )
                ),
                {
                    "id": t["id"],
                    "name": t["name"],
                    "schema_id": t["schemaId"],
                    "db_target_id": t.get("dbTargetId"),
                    "status": t.get("status"),
                    "last_migrated_at": t.get("lastMigratedAt"),
                    "schema_hash": t.get("schemaHash"),
                    "mapping_health": t.get("mappingHealth"),
                    "device_id": t.get("deviceId"),
                },
            )


def set_table_status(table_id: str, status: str, last_migrated_at: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_device_tables SET status=:status, last_migrated_at=:last_migrated_at WHERE id=:id"),
            {"status": status, "last_migrated_at": last_migrated_at, "id": table_id},
        )


def delete_table(table_id: str) -> None:
    with _conn() as c:
        c.execute(text("DELETE FROM app_device_tables WHERE id=:id"), {"id": table_id})


def update_mapping_health(table_id: str, health: str) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_device_tables SET mapping_health=:health WHERE id=:id"),
            {"health": health, "id": table_id},
        )


def set_table_device_binding(table_id: str, device_id: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_device_tables SET device_id=:device_id WHERE id=:id"),
            {"device_id": device_id, "id": table_id},
        )


def set_table_db_target(table_id: str, db_target_id: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_device_tables SET db_target_id=:db_target_id WHERE id=:id"),
            {"db_target_id": db_target_id, "id": table_id},
        )

# ---------- Gateways ----------
def load_gateways() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = _fetchall(
            c,
            "SELECT id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,"
            "last_ping_json,last_tcp_json,created_at,updated_at,last_test_at FROM app_gateways ORDER BY name",
        )
        out: List[Dict[str, Any]] = []
        import json as _json
        for d in rs:
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
        existing = _fetchone(
            c,
            "SELECT id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,"
            "last_ping_json,last_tcp_json,created_at,updated_at,last_test_at "
            "FROM app_gateways WHERE name=:name OR host=:host",
            {"name": gw.get("name"), "host": gw.get("host")},
        )
        if existing:
            return existing
        ports = gw.get("ports") or []
        tags = gw.get("tags") or []
        c.execute(
            text(
                """
                INSERT INTO app_gateways
                (id,name,host,adapter_id,nic_hint,ports_json,protocol_hint,tags_json,status,last_ping_json,last_tcp_json,created_at,updated_at,last_test_at)
                VALUES (:id,:name,:host,:adapter_id,:nic_hint,:ports_json,:protocol_hint,:tags_json,:status,:last_ping_json,:last_tcp_json,:created_at,:updated_at,:last_test_at)
                """
            ),
            {
                "id": gw["id"],
                "name": gw.get("name"),
                "host": gw.get("host"),
                "adapter_id": gw.get("adapterId"),
                "nic_hint": gw.get("nic_hint") or gw.get("adapterId"),
                "ports_json": _json.dumps(ports),
                "protocol_hint": gw.get("protocol_hint"),
                "tags_json": _json.dumps(tags),
                "status": gw.get("status") or "unknown",
                "last_ping_json": None,
                "last_tcp_json": None,
                "created_at": now_iso,
                "updated_at": now_iso,
                "last_test_at": None,
            },
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
        c.execute(text("DELETE FROM app_gateways WHERE id=:id"), {"id": gid})


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
        row = _fetchone(c, "SELECT id FROM app_gateways WHERE id=:id", {"id": gid})
        if not row:
            return None
        fields = []
        values: Dict[str, Any] = {"id": gid}
        if "name" in patch:
            fields.append("name=:name")
            values["name"] = patch.get("name")
        if "host" in patch:
            fields.append("host=:host")
            values["host"] = patch.get("host")
        if "adapterId" in patch or "nic_hint" in patch:
            fields.append("nic_hint=:nic_hint")
            values["nic_hint"] = patch.get("nic_hint") or patch.get("adapterId")
        if "ports" in patch:
            fields.append("ports_json=:ports_json")
            values["ports_json"] = _json.dumps(patch.get("ports") or [])
        if "protocol_hint" in patch:
            fields.append("protocol_hint=:protocol_hint")
            values["protocol_hint"] = patch.get("protocol_hint")
        if "tags" in patch:
            fields.append("tags_json=:tags_json")
            values["tags_json"] = _json.dumps(patch.get("tags") or [])
        fields.append("updated_at=:updated_at")
        values["updated_at"] = time_iso()
        if fields:
            sql = f"UPDATE app_gateways SET {', '.join(fields)} WHERE id=:id"
            c.execute(text(sql), values)
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
        row = _fetchone(c, "SELECT id FROM app_gateways WHERE id=:id", {"id": gid})
        if not row:
            return None
        fields = []
        values: Dict[str, Any] = {"id": gid}
        if status is not None:
            fields.append("status=:status")
            values["status"] = status
        if last_ping is not None:
            fields.append("last_ping_json=:last_ping_json")
            values["last_ping_json"] = _json.dumps(last_ping)
        if last_tcp is not None:
            fields.append("last_tcp_json=:last_tcp_json")
            values["last_tcp_json"] = _json.dumps(last_tcp)
        fields.append("last_test_at=:last_test_at")
        values["last_test_at"] = time_iso()
        sql = f"UPDATE app_gateways SET {', '.join(fields)} WHERE id=:id"
        c.execute(text(sql), values)
    return get_gateway(gid)


# ---------- Targets helpers ----------
def delete_target(tid: str) -> bool:
    with _conn() as c:
        res = c.execute(text("DELETE FROM app_db_targets WHERE id=:id"), {"id": tid})
        return bool(res.rowcount and res.rowcount > 0)


def count_tables_referencing_target(tid: str) -> int:
    with _conn() as c:
        row = _fetchone(
            c,
            "SELECT COUNT(1) AS n FROM app_device_tables WHERE db_target_id=:id",
            {"id": tid},
        )
        return int(row["n"] if row else 0)

# ---------- Simple DPAPI helpers (best-effort) ----------
def _dpapi_available() -> bool:
    try:
        import ctypes  # noqa: F401
        return os.name == "nt"
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

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), wt.LPBYTE))
        blob_out = DATA_BLOB()
        flags = 0
        try:
            if os.environ.get("APP_DPAPI_MACHINE") in ("1", "true", "True") or os.environ.get(
                "AGENT_DPAPI_MACHINE"
            ) in ("1", "true", "True"):
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

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, wt.LPBYTE))
        blob_out = DATA_BLOB()
        flags = 0
        try:
            if os.environ.get("APP_DPAPI_MACHINE") in ("1", "true", "True") or os.environ.get(
                "AGENT_DPAPI_MACHINE"
            ) in ("1", "true", "True"):
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
        raw = _json.dumps(params or {}).encode("utf-8")
    except Exception:
        raw = b"{}"
    enc = _dpapi_protect(raw)
    if enc is None:
        return _json.dumps(params or {})
    import base64 as _b64
    return "ENCv1:" + _b64.b64encode(enc).decode("ascii")


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
            return _json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
    try:
        import json as _json
        return _json.loads(s)
    except Exception:
        return {}


# ---------- Devices ----------
def load_devices() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = _fetchall(
            c,
            "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect FROM app_devices ORDER BY name",
        )
        out: List[Dict[str, Any]] = []
        for r in rs:
            params = _params_load(r["params_json"]) if r.get("params_json") else {}
            ar = r.get("auto_reconnect")
            if ar is None:
                ar = 1
            out.append(
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "protocol": r.get("protocol"),
                    "params": params or {},
                    "status": r.get("status"),
                    "latencyMs": r.get("latency_ms"),
                    "lastError": r.get("last_error"),
                    "autoReconnect": bool(ar),
                }
            )
        return out


def upsert_device(dev: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        row = _fetchone(c, "SELECT id FROM app_devices WHERE name=:name", {"name": dev.get("name")})
        if row:
            existing = _fetchone(
                c,
                "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect FROM app_devices WHERE id=:id",
                {"id": row["id"]},
            )
            if existing:
                ar = existing.get("auto_reconnect")
                if ar is None:
                    ar = 1
                return {
                    "id": existing.get("id"),
                    "name": existing.get("name"),
                    "protocol": existing.get("protocol"),
                    "params": dev.get("params") or {},
                    "status": existing.get("status"),
                    "latencyMs": existing.get("latency_ms"),
                    "lastError": existing.get("last_error"),
                    "autoReconnect": bool(ar),
                }
        params_blob = _params_dump(dev.get("params") or {})
        c.execute(
            text(
                _upsert_sql(
                    "app_devices",
                    ["id", "name", "protocol", "params_json", "status", "latency_ms", "last_error", "auto_reconnect"],
                    ["id"],
                )
            ),
            {
                "id": dev["id"],
                "name": dev.get("name"),
                "protocol": dev.get("protocol"),
                "params_json": params_blob,
                "status": dev.get("status"),
                "latency_ms": dev.get("latencyMs"),
                "last_error": dev.get("lastError"),
                "auto_reconnect": 1 if dev.get("autoReconnect", True) else 0,
            },
        )
        return dev


def update_device_status(dev_id: str, *, status: Optional[str], latency_ms: Optional[int], last_error: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_devices SET status=:status, latency_ms=:latency_ms, last_error=:last_error WHERE id=:id"),
            {"status": status, "latency_ms": latency_ms, "last_error": last_error, "id": dev_id},
        )

# ---------- Jobs ----------
def load_jobs() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = _fetchall(
            c,
            "SELECT id,name,type,tables_json,columns_json,interval_ms,enabled,status,batching_json,cpu_budget,triggers_json,metrics_json "
            "FROM app_jobs ORDER BY name",
        )
        import json as _json
        out: List[Dict[str, Any]] = []
        for r in rs:
            try:
                tables = _json.loads(r.get("tables_json") or "[]")
            except Exception:
                tables = []
            try:
                columns = _json.loads(r.get("columns_json") or '"all"')
            except Exception:
                columns = "all"
            try:
                batching = _json.loads(r.get("batching_json") or "{}")
            except Exception:
                batching = {}
            try:
                triggers = _json.loads(r.get("triggers_json") or "[]")
            except Exception:
                triggers = []
            try:
                metrics = _json.loads(r.get("metrics_json") or "{}")
            except Exception:
                metrics = {}
            out.append(
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "tables": tables,
                    "columns": columns,
                    "intervalMs": r.get("interval_ms"),
                    "enabled": bool(r.get("enabled")),
                    "status": r.get("status"),
                    "batching": batching,
                    "cpuBudget": r.get("cpu_budget"),
                    "triggers": triggers,
                    "metrics": metrics,
                }
            )
        return out


def upsert_job(job: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    with _conn() as c:
        c.execute(
            text(
                _upsert_sql(
                    "app_jobs",
                    [
                        "id",
                        "name",
                        "type",
                        "tables_json",
                        "columns_json",
                        "interval_ms",
                        "enabled",
                        "status",
                        "batching_json",
                        "cpu_budget",
                        "triggers_json",
                        "metrics_json",
                    ],
                    ["id"],
                )
            ),
            {
                "id": job["id"],
                "name": job.get("name"),
                "type": job.get("type"),
                "tables_json": _json.dumps(job.get("tables") or []),
                "columns_json": _json.dumps(job.get("columns") if job.get("columns") is not None else "all"),
                "interval_ms": job.get("intervalMs"),
                "enabled": 1 if job.get("enabled") else 0,
                "status": job.get("status"),
                "batching_json": _json.dumps(job.get("batching") or {}),
                "cpu_budget": job.get("cpuBudget"),
                "triggers_json": _json.dumps(job.get("triggers") or []),
                "metrics_json": _json.dumps(job.get("metrics") or {}),
            },
        )
    return job


def update_job_status(job_id: str, status: str) -> None:
    with _conn() as c:
        c.execute(text("UPDATE app_jobs SET status=:status WHERE id=:id"), {"status": status, "id": job_id})


def delete_job(job_id: str) -> bool:
    """Delete job config and cascade related history/metrics."""
    with _conn() as c:
        res = c.execute(text("DELETE FROM app_jobs WHERE id=:id"), {"id": job_id})
        try:
            c.execute(text("DELETE FROM app_job_runs WHERE job_id=:id"), {"id": job_id})
        except Exception:
            pass
        try:
            c.execute(text("DELETE FROM app_metrics_jobs_minute WHERE job_id=:id"), {"id": job_id})
        except Exception:
            pass
        try:
            c.execute(text("DELETE FROM app_job_errors_minute WHERE job_id=:id"), {"id": job_id})
        except Exception:
            pass
        return bool(res.rowcount and res.rowcount > 0)


def update_device_metadata(dev_id: str, *, name: Optional[str] = None, auto_reconnect: Optional[bool] = None) -> None:
    fields: List[str] = []
    values: Dict[str, Any] = {"id": dev_id}
    if name is not None:
        fields.append("name=:name")
        values["name"] = name
    if auto_reconnect is not None:
        fields.append("auto_reconnect=:auto_reconnect")
        values["auto_reconnect"] = 1 if auto_reconnect else 0
    if not fields:
        return
    with _conn() as c:
        sql = f"UPDATE app_devices SET {', '.join(fields)} WHERE id=:id"
        c.execute(text(sql), values)


def delete_device(dev_id: str) -> None:
    with _conn() as c:
        c.execute(text("DELETE FROM app_devices WHERE id=:id"), {"id": dev_id})


# ---------- Secrets rekey (DPAPI scope alignment) ----------
def rekey_all_device_params() -> int:
    """Re-encode stored device params using current DPAPI scope."""
    try:
        with _conn() as c:
            rs = _fetchall(c, "SELECT id, params_json FROM app_devices")
            updated = 0
            for r in rs:
                try:
                    dev_id = r.get("id")
                    current = r.get("params_json")
                    params = _params_load(current)
                    fresh = _params_dump(params)
                    if fresh != current:
                        c.execute(
                            text("UPDATE app_devices SET params_json=:params_json WHERE id=:id"),
                            {"params_json": fresh, "id": dev_id},
                        )
                        updated += 1
                except Exception:
                    pass
            return updated
    except Exception:
        return 0


# ---------- Job run history ----------
def insert_job_run(job_id: str, run: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            text(
                """
                INSERT INTO app_job_runs
                (job_id, started_at, stopped_at, duration_ms, rows, read_lat_avg, write_lat_avg, error_pct)
                VALUES (:job_id,:started_at,:stopped_at,:duration_ms,:rows,:read_lat_avg,:write_lat_avg,:error_pct)
                """
            ),
            {
                "job_id": job_id,
                "started_at": run.get("started_at"),
                "stopped_at": run.get("stopped_at"),
                "duration_ms": run.get("duration_ms"),
                "rows": run.get("rows"),
                "read_lat_avg": run.get("read_lat_avg"),
                "write_lat_avg": run.get("write_lat_avg"),
                "error_pct": run.get("error_pct"),
            },
        )


def load_job_runs(job_id: str, frm: Optional[str] = None, to: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = (
        "SELECT id,job_id,started_at,stopped_at,duration_ms,rows,read_lat_avg,write_lat_avg,error_pct "
        "FROM app_job_runs WHERE job_id=:job_id"
    )
    params: Dict[str, Any] = {"job_id": job_id}
    if frm:
        sql += " AND started_at >= :frm"
        params["frm"] = frm
    if to:
        sql += " AND (stopped_at <= :to OR (stopped_at IS NULL AND started_at <= :to))"
        params["to"] = to
    sql += " ORDER BY id DESC LIMIT 500"
    with _conn() as c:
        return _fetchall(c, sql, params)
