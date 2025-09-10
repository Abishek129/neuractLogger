from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _app_folder() -> Path:
    base = os.environ.get("ProgramData") or os.getcwd()
    folder = Path(base) / "PLCLogger" / "agent"
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
            try:
                ports = _json.loads(r["ports_json"]) if r["ports_json"] else []
            except Exception:
                ports = []
            try:
                tags = _json.loads(r["tags_json"]) if r["tags_json"] else []
            except Exception:
                tags = []
            try:
                last_ping = _json.loads(r["last_ping_json"]) if r["last_ping_json"] else None
            except Exception:
                last_ping = None
            try:
                last_tcp = _json.loads(r["last_tcp_json"]) if r["last_tcp_json"] else None
            except Exception:
                last_tcp = None
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "host": r["host"],
                    "adapter_id": r.get("adapter_id"),
                    "nic_hint": r.get("nic_hint") or r.get("adapter_id"),
                    "ports": ports,
                    "protocol_hint": r.get("protocol_hint"),
                    "tags": tags,
                    "status": r.get("status") or "unknown",
                    "last_ping": last_ping,
                    "last_tcp": last_tcp,
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "last_test_at": r.get("last_test_at"),
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


# ---------- Devices ----------
def load_devices() -> List[Dict[str, Any]]:
    with _conn() as c:
        rs = c.execute(
            "SELECT id,name,protocol,params_json,status,latency_ms,last_error FROM app_devices ORDER BY name"
        ).fetchall()
        out: List[Dict[str, Any]] = []
        import json as _json
        for r in rs:
            params = None
            try:
                params = _json.loads(r["params_json"]) if r["params_json"] else None
            except Exception:
                params = None
            out.append({
                "id": r["id"],
                "name": r["name"],
                "protocol": r["protocol"],
                "params": params or {},
                "status": r["status"],
                "latencyMs": r["latency_ms"],
                "lastError": r["last_error"],
            })
        return out


def upsert_device(dev: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        # Prevent duplicates by name
        row = c.execute("SELECT id FROM app_devices WHERE name=?", (dev.get("name"),)).fetchone()
        if row:
            # Return existing
            existing = c.execute(
                "SELECT id,name,protocol,params_json,status,latency_ms,last_error FROM app_devices WHERE id=?",
                (row["id"],),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "name": existing["name"], "protocol": existing["protocol"], "params": dev.get("params") or {}, "status": existing["status"], "latencyMs": existing["latency_ms"], "lastError": existing["last_error"]}
        import json as _json
        c.execute(
            "INSERT OR REPLACE INTO app_devices (id,name,protocol,params_json,status,latency_ms,last_error) VALUES (?,?,?,?,?,?,?)",
            (
                dev["id"],
                dev.get("name"),
                dev.get("protocol"),
                _json.dumps(dev.get("params") or {}),
                dev.get("status"),
                dev.get("latencyMs"),
                dev.get("lastError"),
            ),
        )
        return dev


def update_device_status(dev_id: str, *, status: Optional[str], latency_ms: Optional[int], last_error: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE app_devices SET status=?, latency_ms=?, last_error=? WHERE id=?",
            (status, latency_ms, last_error, dev_id),
        )


def update_device_metadata(dev_id: str, *, name: Optional[str] = None) -> None:
    if name is None:
        return
    with _conn() as c:
        c.execute("UPDATE app_devices SET name=? WHERE id=?", (name, dev_id))


def delete_device(dev_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM app_devices WHERE id=?", (dev_id,))
