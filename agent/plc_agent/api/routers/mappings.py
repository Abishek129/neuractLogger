from __future__ import annotations

from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException
import logging

from ..store import Store
from sqlalchemy import create_engine, text  # type: ignore


router = APIRouter(prefix="/mappings")
log = logging.getLogger(__name__)


@router.get("/{table_id}")
def get_mapping(table_id: str) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    # Fallback for physically discovered tables (no local catalog entry)
    if not t:
        if table_id.startswith("phy_"):
            name = table_id[4:]
            t = {"id": table_id, "name": name, "dbTargetId": Store.instance().get_default_db_target()}
        else:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    loaded = _load_mapping_from_user_db(t)
    try:
        n = len((loaded or {}).get("rows") or {})
        log.info(f"mappings.get: table={table_id} name={t.get('name')} rows_from_userdb={n}")
    except Exception:
        pass
    if loaded:
        # Sync into in-memory store (device binding preserved from store)
        Store.instance().replace_mapping(table_id, {"deviceId": loaded.get("deviceId"), "rows": loaded.get("rows") or {}})
    m = loaded or Store.instance().get_mapping(table_id)
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    required = [f.get("key") for f in (schema.get("fields") or [])]
    health = Store.instance().mapping_health(table_id, required_fields=required)
    return {"success": True, "item": {"tableId": table_id, **m}, "health": health}


@router.post("/{table_id}")
def upsert_mapping(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    device_id = payload.get("deviceId")
    rows_patch = payload.get("rows") or {}
    _save_mapping_to_user_db(t, rows_patch, device_id)
    m = Store.instance().upsert_mapping(table_id, device_id=device_id, rows_patch=rows_patch)
    # Recompute health after save
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    required = [f.get("key") for f in (schema.get("fields") or [])]
    health = Store.instance().mapping_health(table_id, required_fields=required)
    return {"success": True, "message": "mapping_upserted", "item": m, "health": health}


@router.post("/{table_id}/bulk_apply")
def bulk_apply(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    rows = payload.get("rows") or {}
    _save_mapping_to_user_db(t, rows, payload.get("deviceId"))
    m = Store.instance().upsert_mapping(table_id, rows_patch=rows)
    return {"success": True, "message": "mapping_applied", "item": m}


@router.post("/{table_id}/import")
def import_mapping(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    mapping = payload.get("mapping") or payload
    rows = mapping.get("rows") or {}
    _replace_mapping_in_user_db(t, rows, mapping.get("deviceId") or payload.get("deviceId"))
    m = Store.instance().replace_mapping(table_id, mapping)
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    required = [f.get("key") for f in (schema.get("fields") or [])]
    health = Store.instance().mapping_health(table_id, required_fields=required)
    return {"success": True, "message": "mapping_imported", "item": m, "health": health}


@router.post("/{table_id}/validate")
def validate_mapping(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    m = Store.instance().get_mapping(table_id)
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    required = [f.get("key") for f in (schema.get("fields") or [])]
    # Validate against provided payload when present (no write), else current stored mapping
    rows = (payload.get("rows") if isinstance(payload, dict) else None) or (m.get("rows") or {})
    device_id = (payload.get("deviceId") if isinstance(payload, dict) else None) or m.get("deviceId")
    problems = []
    if not device_id:
        problems.append({"code": "DEVICE_NOT_BOUND"})
    # Attempt live-read validation when device is present
    device = Store.instance().get_device(device_id) if device_id else None
    for k in required:
        r = rows.get(k) or {}
        if not r:
            problems.append({"field": k, "code": "MAPPING_INCOMPLETE"})
        else:
            proto = r.get("protocol")
            if proto not in ("modbus", "opcua"):
                problems.append({"field": k, "code": "MAPPING_TYPE_MISMATCH"})
            if not r.get("address"):
                problems.append({"field": k, "code": "MAPPING_INCOMPLETE"})
            # For OPC UA, datatype is informational; skip hard requirement
            if proto != "opcua":
                if r.get("dataType") not in ("float", "int", "bool", "string"):
                    problems.append({"field": k, "code": "MAPPING_TYPE_MISMATCH"})
            # Live-read check (best-effort)
            if device and not _can_read_field(device, r):
                problems.append({"field": k, "code": "TAG_UNREADABLE"})
    # Compute health based on provided rows without mutating store
    # Create a temporary projection of mapping rows for health computation
    tmp = {"deviceId": device_id, "rows": rows}
    # piggyback on health logic by temporarily replacing mapping in memory
    # (without persistence). Simulate via local function using same rules as Store.mapping_health
    required_keys = required
    ok = 0
    for fk in required_keys:
        rr = rows.get(fk) or {}
        p = rr.get("protocol")
        if p == "opcua":
            if rr.get("address"):
                ok += 1
        elif p == "modbus":
            if rr.get("address") and rr.get("dataType"):
                ok += 1
    health = "Unmapped"
    if ok == 0:
        health = "Unmapped"
    elif ok == len(required_keys):
        health = "Mapped"
    else:
        health = "Partially Mapped"
    # Success if no hard errors beyond incompletes (allow partial saves)
    # i.e., all provided tags must be readable/valid; missing tags do not block save
    hard_errors = [p for p in problems if p.get("code") not in ("MAPPING_INCOMPLETE",)]
    ok = len(hard_errors) == 0
    return {"success": ok, "health": health, "problems": problems}


# ---------- Live-read helpers ----------
def _can_read_field(device: Dict[str, Any], row: Dict[str, Any]) -> bool:
    try:
        proto = (row.get("protocol") or device.get("protocol") or "").lower()
        if proto == "opcua":
            return _opcua_can_read(device, row)
        if proto == "modbus":
            return _modbus_can_read(device, row)
    except Exception:
        return False
    return False


def _opcua_can_read(device: Dict[str, Any], row: Dict[str, Any]) -> bool:
    try:
        try:
            from opcua import Client  # type: ignore
        except Exception:
            return False
        params = device.get("params") or {}
        ep = (params.get("endpoint") or "").strip()
        if not ep:
            return False
        node_id = (row.get("address") or row.get("nodeId") or "").strip()
        if not node_id:
            return False
        # Avoid wildcard/broadcast endpoints
        if "0.0.0.0" in ep:
            ep = ep.replace("0.0.0.0", "127.0.0.1")
        client = Client(ep)
        try:
            client.connect()
            node = client.get_node(node_id)
            val = node.get_value()
            # Any non-exceptional read counts as readable
            _ = val  # noqa
            return True
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
    except Exception:
        return False


def _modbus_can_read(device: Dict[str, Any], row: Dict[str, Any]) -> bool:
    try:
        try:
            from pymodbus.client import ModbusTcpClient  # type: ignore
        except Exception:
            return False
        params = device.get("params") or {}
        host = (params.get("host") or params.get("ip") or "").strip()
        port = int(params.get("port", 502))
        if not host:
            return False
        addr_raw = str(row.get("address") or "").strip()
        if not addr_raw or not addr_raw.isdigit():
            # Accept numeric-like strings; anything else skip
            try:
                int(addr_raw)
            except Exception:
                return False
        try:
            address = int(addr_raw)
        except Exception:
            return False
        # Heuristic: map address to function/register type
        def read_one(cli, start):
            r = cli.read_holding_registers(start, 1)
            if hasattr(r, "isError"):
                return not r.isError()
            return not getattr(r, "isError", True)
        start = 0
        fn_ok = False
        client = ModbusTcpClient(host=host, port=port)
        try:
            if not client.connect():
                return False
            if address >= 40001:
                start = address - 40001
                fn_ok = read_one(client, start)
            elif address >= 30001:
                start = address - 30001
                r = client.read_input_registers(start, 1)
                fn_ok = (not r.isError()) if hasattr(r, "isError") else True
            elif address >= 10001:
                start = address - 10001
                r = client.read_coils(start, 1)
                fn_ok = (not r.isError()) if hasattr(r, "isError") else True
            else:
                start = max(0, address)
                fn_ok = read_one(client, start)
        finally:
            try:
                client.close()
            except Exception:
                pass
        return bool(fn_ok)
    except Exception:
        return False


@router.delete("/{table_id}/{field_key}")
def delete_mapping_row(table_id: str, field_key: str) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    m = Store.instance().delete_mapping_row(table_id, field_key)
    return {"success": True, "message": "row_deleted", "item": m}


@router.get("/{table_id}/export")
def export_mapping(table_id: str) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    return {"mapping": Store.instance().get_mapping(table_id)}


@router.post("/{src_table_id}/copy_to/{dst_table_id}")
def copy_mapping(src_table_id: str, dst_table_id: str) -> Dict[str, Any]:
    if not Store.instance().get_table(src_table_id) or not Store.instance().get_table(dst_table_id):
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    m = Store.instance().copy_mapping(src_table_id, dst_table_id)
    # Try to mirror in User DB when both share the same target
    src_t = Store.instance().get_table(src_table_id)
    dst_t = Store.instance().get_table(dst_table_id)
    if src_t and dst_t:
        src_target = src_t.get("dbTargetId") or Store.instance().get_default_db_target()
        dst_target = dst_t.get("dbTargetId") or Store.instance().get_default_db_target()
        if src_target == dst_target:
            _replace_mapping_in_user_db(dst_t, m.get("rows") or {})
    return {"success": True, "message": "mapping_copied", "item": m}


@router.post("/{table_id}/preview_sample")
def preview_sample(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Stub non-blocking preview: returns structure without device IO
    if not Store.instance().get_table(table_id):
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    return {"success": False, "message": "PREVIEW_NOT_IMPLEMENTED", "warnings": ["stub_preview"]}


@router.post("/{table_id}/preview_60s")
def preview_60s(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Stub: return a token that would be used to poll status
    if not Store.instance().get_table(table_id):
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    return {"success": True, "token": f"prev_{table_id}", "message": "started", "warnings": ["stub_preview"]}


# ------- Helpers for mapping persistence in the User DB -------
def _engine_for_target_id(target_id: Optional[str]):
    from ..routers.tables import _engine_for_target as _eng  # reuse helper
    return _eng(target_id)


# Namespace helpers (mirror tables router)
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


def _ensure_namespace(engine) -> None:
    if _uses_schema(engine):
        try:
            name = _dialect_name(engine)
            with engine.begin() as conn:
                if name.startswith("postgres"):
                    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {NEURACT_SCHEMA}"))
                else:
                    try:
                        conn.execute(text(f"CREATE SCHEMA {NEURACT_SCHEMA}"))
                    except Exception:
                        pass
        except Exception:
            pass


def _device_ident(engine, logical_name: str) -> dict:
    if _uses_schema(engine):
        return {"schema": NEURACT_SCHEMA, "name": logical_name, "qualified": f"{NEURACT_SCHEMA}.{logical_name}"}
    name = f"{NEURACT_PREFIX}{logical_name}"
    return {"schema": None, "name": name, "qualified": name}


def _mapping_ident(engine) -> dict:
    if _uses_schema(engine):
        return {"schema": NEURACT_SCHEMA, "name": "device_mappings", "qualified": f"{NEURACT_SCHEMA}.device_mappings"}
    name = f"{NEURACT_PREFIX}device_mappings"
    return {"schema": None, "name": name, "qualified": name}


def _ensure_mapping_table(engine, table_name: Optional[str] = None) -> None:
    _ensure_namespace(engine)
    ident = _mapping_ident(engine)
    target = table_name or ident["qualified"]
    ddl = (
        f"CREATE TABLE IF NOT EXISTS {target} ("
        "table_name TEXT NOT NULL,"
        "field_key TEXT NOT NULL,"
        "protocol TEXT,"
        "address TEXT,"
        "data_type TEXT,"
        "scale REAL,"
        "deadband REAL,"
        "device_id TEXT,"
        "PRIMARY KEY (table_name, field_key)"
        ")"
    )
    with engine.begin() as conn:
        try:
            conn.execute(text(ddl))
        except Exception:
            # Fallback without IF NOT EXISTS
            try:
                conn.execute(text(ddl.replace(" IF NOT EXISTS", "")))
            except Exception:
                pass


def _ensure_mapping_table_columns(engine, table_name: str) -> None:
    # Best-effort ensure device_id column exists
    try:
        with engine.begin() as conn:
            try:
                cols = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            except Exception:
                cols = []
            names = set()
            for c in cols or []:
                # Support various row formats (tuple or Row)
                try:
                    names.add(c[1])
                except Exception:
                    try:
                        names.add(c["name"])  # type: ignore[index]
                    except Exception:
                        pass
            if "device_id" not in names:
                try:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN device_id TEXT"))
                except Exception:
                    pass
    except Exception:
        pass


def _mapping_table_candidates(engine) -> list[str]:
    if _uses_schema(engine):
        return [f"{NEURACT_SCHEMA}.device_mappings", "device_mappings"]
    # Engines without schemas (SQLite/MySQL)
    return [f"{NEURACT_PREFIX}device_mappings", "neuract_device_mappings", "device_mappings"]


def _select_mapping_table(engine, *, create: bool = False) -> str:
    """Return a qualified mapping table name to use. Prefer existing; else create standard.
    """
    # Probe candidates by issuing a no-op select
    with engine.connect() as conn:
        for name in _mapping_table_candidates(engine):
            try:
                conn.execute(text(f"SELECT 1 FROM {name} WHERE 1=0"))
                # ensure expected columns exist
                _ensure_mapping_table_columns(engine, name)
                return name
            except Exception:
                continue
    if create:
        _ensure_mapping_table(engine)
        ident = _mapping_ident(engine)
        _ensure_mapping_table_columns(engine, ident["qualified"])
        return ident["qualified"]
    # Default to standard name even if not present
    ident = _mapping_ident(engine)
    _ensure_mapping_table_columns(engine, ident["qualified"])
    return ident["qualified"]


def _save_mapping_to_user_db(table: Dict[str, Any], rows: Dict[str, Dict[str, Any]], device_id: Optional[str] = None) -> None:
    engine = _engine_for_target_id(table.get("dbTargetId"))
    # Choose existing mapping table when present; create standard if none
    m_table = _select_mapping_table(engine, create=True)
    t_ident = _device_ident(engine, table.get("name"))
    with engine.begin() as conn:
        for k, v in (rows or {}).items():
            try:
                conn.execute(
                    text(
                        f"INSERT OR REPLACE INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id)"
                        " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev)"
                    ),
                    {
                        "t": t_ident["name"],
                        "k": k,
                        "p": v.get("protocol"),
                        "a": v.get("address") or v.get("nodeId"),
                        "dt": v.get("dataType"),
                        "s": v.get("scale"),
                        "d": v.get("deadband"),
                        "dev": device_id,
                    },
                )
            except Exception:
                # Basic upsert fallback: delete then insert
                try:
                    conn.execute(text(f"DELETE FROM {m_table} WHERE table_name=:t AND field_key=:k"), {"t": t_ident["name"], "k": k})
                    conn.execute(
                        text(
                            f"INSERT INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id)"
                            " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev)"
                        ),
                        {
                            "t": t_ident["name"],
                            "k": k,
                            "p": v.get("protocol"),
                            "a": v.get("address") or v.get("nodeId"),
                            "dt": v.get("dataType"),
                            "s": v.get("scale"),
                            "d": v.get("deadband"),
                            "dev": device_id,
                        },
                    )
                except Exception:
                    pass


def _replace_mapping_in_user_db(table: Dict[str, Any], rows: Dict[str, Dict[str, Any]], device_id: Optional[str] = None) -> None:
    engine = _engine_for_target_id(table.get("dbTargetId"))
    m_table = _select_mapping_table(engine, create=True)
    t_ident = _device_ident(engine, table.get("name"))
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {m_table} WHERE table_name=:t"), {"t": t_ident["name"]})
        for k, v in (rows or {}).items():
            conn.execute(
                text(
                    f"INSERT INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id)"
                    " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev)"
                ),
                {
                    "t": t_ident["name"],
                    "k": k,
                    "p": v.get("protocol"),
                    "a": v.get("address") or v.get("nodeId"),
                    "dt": v.get("dataType"),
                    "s": v.get("scale"),
                    "d": v.get("deadband"),
                    "dev": device_id,
                },
            )


def _load_mapping_from_user_db(table: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        engine = _engine_for_target_id(table.get("dbTargetId"))
        t_ident = _device_ident(engine, table.get("name"))
        logical = table.get("name")
        prefixed = t_ident["name"]
        m_table = _select_mapping_table(engine, create=False)
        try:
            log.info(f"mappings._load.init: url={getattr(engine, 'url', '')} m_table={m_table} logical={logical} prefixed={prefixed}")
        except Exception:
            pass
        rows = []
        with engine.begin() as conn:
            # Try logical name first
            try:
                rows = conn.execute(
                    text(f"SELECT field_key,protocol,address,data_type,scale,deadband,device_id FROM {m_table} WHERE table_name=:t"),
                    {"t": logical},
                ).fetchall()
                try:
                    log.info(f"mappings._load.query: table={logical} -> {len(rows)} rows")
                except Exception:
                    pass
            except Exception:
                rows = []
            if not rows and prefixed != logical:
                try:
                    rows = conn.execute(
                        text(f"SELECT field_key,protocol,address,data_type,scale,deadband,device_id FROM {m_table} WHERE table_name=:t"),
                        {"t": prefixed},
                    ).fetchall()
                    try:
                        log.info(f"mappings._load.query: table={prefixed} -> {len(rows)} rows")
                    except Exception:
                        pass
                except Exception:
                    rows = []
        # Determine deviceId from rows if present
        dev_id: Optional[str] = None
        for r in rows or []:
            try:
                val = r["device_id"]
            except Exception:
                try:
                    val = r[6]
                except Exception:
                    val = None
            if val:
                dev_id = val
                break
        # Robust row extraction supporting tuple or Row objects
        def _get(r, key: str, idx: int):
            try:
                return r[key]  # type: ignore[index]
            except Exception:
                try:
                    return r[idx]
                except Exception:
                    return None

        out: Dict[str, Any] = {
            "deviceId": dev_id if dev_id is not None else Store.instance().get_mapping(table.get("id")).get("deviceId"),
            "rows": {},
        }
        for r in rows:
            fk = _get(r, "field_key", 0)
            if not fk:
                continue
            out["rows"][fk] = {
                "protocol": _get(r, "protocol", 1),
                "address": _get(r, "address", 2),
                "dataType": _get(r, "data_type", 3),
                "scale": _get(r, "scale", 4),
                "deadband": _get(r, "deadband", 5),
            }
        try:
            log.info(f"mappings._load: table={table.get('id')} name={table.get('name')} target={table.get('dbTargetId')} rows={len(out['rows'])} dev={out.get('deviceId')}")
        except Exception:
            pass
        return out
    except Exception:
        return None
