from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    Float,
    Boolean,
    String,
    inspect,
    text,
)

from ..store import Store
from pathlib import Path
import logging


router = APIRouter(prefix="/tables")
log = logging.getLogger(__name__)


SQLITE_FALLBACK_URL = "sqlite:///mydatabase.db"


def _expand_pattern(name_or_pattern: str) -> List[str]:
    m = re.match(r"^(.*)\{(\d+)\.\.(\d+)\}(.*)$", name_or_pattern or "")
    if not m:
        return [name_or_pattern]
    pre, a, b, post = m.groups()
    start, end = int(a), int(b)
    return [f"{pre}{i}{post}" for i in range(start, end + 1)]


def _sql_safe(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def _engine_for_target(target_id: Optional[str]):
    store = Store.instance()
    url = SQLITE_FALLBACK_URL
    if target_id:
        t = store.get_db_target(target_id)
    else:
        did = store.get_default_db_target()
        t = store.get_db_target(did) if did else None
    if t and t.get("provider") == "sqlite":
        conn = t.get("conn") or ":memory:"
        if str(conn).startswith("sqlite:"):
            url = str(conn)
        else:
            # Resolve to absolute path to avoid CWD ambiguity
            try:
                p = Path(str(conn)).expanduser().resolve()
                url = f"sqlite:///{p.as_posix()}"
            except Exception:
                url = f"sqlite:///{conn}"
    return create_engine(url)


def _to_sa_type(ftype: str):
    k = (ftype or "").lower()
    if k in ("int", "integer"):
        return Integer
    if k in ("float", "double", "number"):
        return Float
    if k in ("bool", "boolean"):
        return Boolean
    return String


# ---------------- NEURACT namespace helpers ----------------
# Canonical namespace per requirements
NEURACT_SCHEMA = "neuract"
NEURACT_PREFIX = "neuract__"

# Reserved meta tables to exclude from discovery
NEURACT_RESERVED_TABLES = {
    "device_mappings",
    "mappings",
    "mapping_history",
}
NEURACT_RESERVED_PREFIXES = (
    "meta_",
    "system_",
)

def _is_neuract_meta_table(physical_name: str) -> bool:
    """Return True if the given physical table name is an internal/meta table that must be hidden."""
    n = physical_name or ""
    # Prefix mode (no schema support): names start with NEURACT_PREFIX
    if n.startswith(NEURACT_PREFIX):
        logical = n[len(NEURACT_PREFIX):]
        if logical in NEURACT_RESERVED_TABLES:
            return True
        if any(logical.startswith(p) for p in NEURACT_RESERVED_PREFIXES):
            return True
        if logical.startswith("neuract__meta_"):
            return True
        return False
    # Schema mode: physical names are bare logical names under the schema
    logical = n
    if logical in NEURACT_RESERVED_TABLES:
        return True
    if any(logical.startswith(p) for p in NEURACT_RESERVED_PREFIXES):
        return True
    return False


def _dialect_name(engine) -> str:
    try:
        return getattr(engine.dialect, "name", "") or ""
    except Exception:
        return ""


def _uses_schema(engine) -> bool:
    name = _dialect_name(engine)
    # PostgreSQL and SQL Server support schemas; MySQL and SQLite do not (in the intended sense)
    return name in ("postgresql", "psycopg2", "mssql", "sqlserver")


def _ensure_namespace(engine) -> None:
    if _uses_schema(engine):
        # Create schema if possible (idempotent on PG; best-effort on MSSQL)
        try:
            name = _dialect_name(engine)
            with engine.begin() as conn:
                if name.startswith("postgres"):
                    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {NEURACT_SCHEMA}"))
                else:
                    # Best-effort for MSSQL; ignore if already exists
                    try:
                        conn.execute(text(f"CREATE SCHEMA {NEURACT_SCHEMA}"))
                    except Exception:
                        pass
        except Exception:
            # Non-fatal; fall back to default schema
            pass


def _physical_ident(engine, logical_name: str) -> Dict[str, str]:
    """Return dict with schema (or None), physical table name and qualified reference."""
    if _uses_schema(engine):
        schema = NEURACT_SCHEMA
        name = logical_name
        qualified = f"{schema}.{name}"
        return {"schema": schema, "name": name, "qualified": qualified}
    # Prefix for engines without schema support (SQLite, MySQL)
    name = f"{NEURACT_PREFIX}{logical_name}"
    return {"schema": None, "name": name, "qualified": name}


@router.post("/bulk_create")
def bulk_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    parent_id = (payload.get("parentSchemaId") or payload.get("schemaId") or "").strip()
    if not parent_id:
        raise HTTPException(status_code=400, detail="PARENT_SCHEMA_NOT_FOUND")
    schema = Store.instance().get_schema(parent_id)
    if not schema:
        raise HTTPException(status_code=404, detail="PARENT_SCHEMA_NOT_FOUND")

    names: List[str] = []
    if isinstance(payload.get("names"), list):
        for n in payload.get("names"):
            names.extend(_expand_pattern(str(n)))
    elif isinstance(payload.get("pattern"), str):
        names.extend(_expand_pattern(payload.get("pattern")))
    elif isinstance(payload.get("name"), str):
        names.extend(_expand_pattern(payload.get("name")))
    names = [n.strip() for n in names if n and isinstance(n, str)]
    if not names:
        raise HTTPException(status_code=400, detail="TABLE_NAME_INVALID")

    normalized = []
    warnings: List[Dict[str, Any]] = []
    for n in names:
        if _sql_safe(n):
            normalized.append(n)
        else:
            # normalize to SQL-safe: replace non-word chars with '_', ensure leading char is letter/underscore
            safe = re.sub(r"[^A-Za-z0-9_]", "_", n)
            if not re.match(r"^[A-Za-z_]", safe):
                safe = "t_" + safe
            warnings.append({"original": n, "normalized": safe})
            normalized.append(safe)

    db_target_id = payload.get("dbTargetId") or Store.instance().get_default_db_target()

    created = Store.instance().add_tables_bulk(parent_id, normalized, db_target_id)
    resp: Dict[str, Any] = {"success": True, "message": "tables_created", "count": len(created), "items": created}
    if warnings:
        resp["warnings"] = warnings
    return resp


@router.get("")
def list_tables(
    parentSchemaId: Optional[str] = Query(None),
    dbTargetId: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    page: int = 1,
    pageSize: int = 50,
) -> Dict[str, Any]:
    # Load from local app DB first
    base = Store.instance().list_tables(
        parent_schema_id=parentSchemaId, db_target_id=dbTargetId, status=status, name_like=name
    )

    # Discover physical tables in user DB
    sel_target_id = dbTargetId or Store.instance().get_default_db_target()
    discovered: List[str] = []
    try:
        if sel_target_id:
            engine = _engine_for_target(sel_target_id)
            insp = inspect(engine)
            if _uses_schema(engine):
                try:
                    discovered = list(insp.get_table_names(schema=NEURACT_SCHEMA))
                except Exception:
                    discovered = []
            else:
                try:
                    all_names = list(insp.get_table_names())
                    discovered = [n for n in all_names if n.startswith(NEURACT_PREFIX)]
                except Exception:
                    discovered = []
    except Exception:
        discovered = []

    # Normalize discovered names and filter meta/system
    phys_logical: List[str] = []
    for phys in discovered:
        if _is_neuract_meta_table(phys):
            continue
        logical = phys[len(NEURACT_PREFIX):] if phys.startswith(NEURACT_PREFIX) else phys
        phys_logical.append(logical)
    phys_set = set(phys_logical)

    # Build response: keep unmigrated; keep migrated only if physically present
    out: List[Dict[str, Any]] = []
    names_out: set[str] = set()
    for t in base:
        st = (t.get("status") or "").lower()
        if st == "migrated" and t.get("name") not in phys_set:
            continue
        schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
        fields = schema.get("fields") or []
        # Ensure mapping rows are hydrated from User DB so status reflects saved mapping
        try:
            from . import mappings as _mp  # local import to avoid cycles
            loaded = _mp._load_mapping_from_user_db(t)  # type: ignore[attr-defined]
            if loaded and (loaded.get("rows") or {}):
                Store.instance().replace_mapping(t.get("id"), {"deviceId": loaded.get("deviceId"), "rows": loaded.get("rows") or {}})
                # Ensure table device binding is set when available
                if loaded.get("deviceId"):
                    Store.instance().set_table_device_binding(t.get("id"), loaded.get("deviceId"))
                try:
                    log.info(f"tables.list: table={t.get('id')} name={t.get('name')} loaded_rows={len((loaded.get('rows') or {}))}")
                except Exception:
                    pass
        except Exception:
            pass
        mapping = Store.instance().get_mapping(t.get("id"))
        mapping_exists = bool((mapping.get("rows") or {}))
        required_keys = [f.get("key") for f in fields]
        health = Store.instance().mapping_health(t.get("id"), required_fields=required_keys)
        out.append({
            **t,
            "parentSchema": {"id": schema.get("id"), "name": schema.get("name")},
            "dbTarget": {"id": t.get("dbTargetId") or Store.instance().get_default_db_target()},
            "columnCount": len(fields) + 1,
            "mappingExists": mapping_exists,
            "mappingStatus": health,
            "mappingRows": mapping.get("rows") or {},
        })
        names_out.add(t.get("name"))

    # Append physical-only items not represented in local catalog
    if sel_target_id:
        for logical in phys_logical:
            if logical in names_out:
                continue
            out.append({
                "id": f"phy_{logical}",
                "name": logical,
                "schemaId": None,
                "dbTargetId": sel_target_id,
                "status": "migrated",
                "lastMigratedAt": None,
                "parentSchema": None,
                "dbTarget": {"id": sel_target_id},
                "columnCount": None,
                "mappingExists": None,
                "mappingStatus": None,
            })

    total = len(out)
    start = max(0, (page - 1) * pageSize)
    end = start + pageSize
    return {"success": True, "total": total, "page": page, "items": out[start:end]}


@router.get("/discover")
def discover(
    dbTargetId: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Return planned (non-migrated in App DB) and migrated (discovered in User DB)."""
    # Planned from App DB
    planned = Store.instance().list_tables(db_target_id=dbTargetId, status="not_migrated")
    # Migrated: only those that exist physically in User DB
    local_migrated = Store.instance().list_tables(db_target_id=dbTargetId, status="migrated")
    migrated: List[Dict[str, Any]] = []
    try:
        sel_target_id = dbTargetId or Store.instance().get_default_db_target()
        if sel_target_id:
            engine = _engine_for_target(sel_target_id)
            insp = inspect(engine)
            if _uses_schema(engine):
                phys = list(insp.get_table_names(schema=NEURACT_SCHEMA))
            else:
                phys = [n for n in insp.get_table_names() if n.startswith(NEURACT_PREFIX)]
            phys_logical = []
            for p in phys:
                if _is_neuract_meta_table(p):
                    continue
                phys_logical.append(p[len(NEURACT_PREFIX):] if p.startswith(NEURACT_PREFIX) else p)
            phys_set = set(phys_logical)
            # Keep only local migrated that exist physically
            for t in local_migrated:
                if t.get("name") in phys_set:
                    # Hydrate mapping rows for correct status
                    try:
                        from . import mappings as _mp  # local import to avoid cycles
                        loaded = _mp._load_mapping_from_user_db(t)  # type: ignore[attr-defined]
                        if loaded and (loaded.get("rows") or {}):
                            Store.instance().replace_mapping(t.get("id"), {"deviceId": loaded.get("deviceId"), "rows": loaded.get("rows") or {}})
                            try:
                                log.info(f"tables.discover: table={t.get('id')} name={t.get('name')} loaded_rows={len((loaded.get('rows') or {}))}")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Also include mapping rows in payload
                    mapping = Store.instance().get_mapping(t.get("id"))
                    t_with_map = {**t, "mappingRows": mapping.get("rows") or {}}
                    migrated.append(t_with_map)
            # Append extra discovered that are not in local catalog
            have_local_names = {t.get("name") for t in migrated}
            for ln in phys_logical:
                if ln in have_local_names:
                    continue
                # Try to hydrate mapping rows directly from user DB
                mapping_rows = {}
                device_id = None
                try:
                    from . import mappings as _mp  # local import to avoid cycles
                    t_stub = {"id": f"phy_{ln}", "name": ln, "dbTargetId": sel_target_id}
                    loaded = _mp._load_mapping_from_user_db(t_stub)  # type: ignore[attr-defined]
                    mapping_rows = (loaded or {}).get("rows") or {}
                    device_id = (loaded or {}).get("deviceId")
                    try:
                        log.info(f"tables.discover.extra: name={ln} loaded_rows={len(mapping_rows)}")
                    except Exception:
                        pass
                except Exception:
                    pass
                migrated.append({
                    "id": f"phy_{ln}",
                    "name": ln,
                    "schemaId": None,
                    "dbTargetId": sel_target_id,
                    "status": "migrated",
                    "lastMigratedAt": None,
                    "mappingRows": mapping_rows,
                    "deviceId": device_id,
                })
    except Exception:
        pass
    return {"success": True, "planned": planned, "migrated": migrated}


@router.get("/{table_id}")
def get_table_details(table_id: str) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        # Fallback: physically discovered only
        if table_id.startswith("phy_"):
            logical = table_id[4:]
            t = {
                "id": table_id,
                "name": logical,
                "schemaId": None,
                "dbTargetId": Store.instance().get_default_db_target(),
                "status": "migrated",
                "lastMigratedAt": None,
            }
        else:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    schema = Store.instance().get_schema(t.get("schemaId")) or {}
    fields = [f.get("key") for f in (schema.get("fields") or [])]
    health = Store.instance().mapping_health(table_id, required_fields=fields)
    return {
        "success": True,
        "item": t,
        "schema": {"id": schema.get("id"), "name": schema.get("name"), "fields": schema.get("fields")},
        "mappingHealth": health,
    }


@router.post("/dry_run_ddl")
def dry_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[str] = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="NO_TABLE_IDS")
    results: List[Dict[str, Any]] = []
    for tid in ids:
        t = Store.instance().get_table(tid)
        if not t:
            results.append({"id": tid, "error": "TABLE_NOT_FOUND"})
            continue
        schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
        field_types = {f["key"]: _to_sa_type(f.get("type", "string")) for f in (schema.get("fields") or [])}

        engine = _engine_for_target(t.get("dbTargetId"))
        _ensure_namespace(engine)
        ident = _physical_ident(engine, t.get("name"))
        insp = inspect(engine)
        exists = insp.has_table(ident["name"], schema=ident["schema"]) if hasattr(insp, "has_table") else insp.has_table(ident["name"])  # type: ignore[attr-defined]
        ops: List[str] = []
        if not exists:
            cols = ["timestamp_utc DATETIME NOT NULL"] + [f"{k} {_sa_type_to_sql(v)}" for k, v in field_types.items()]
            ops.append(f"CREATE TABLE {ident['qualified']} (" + ", ".join(cols) + ")")
        else:
            cols_existing = {c["name"] for c in insp.get_columns(ident["name"], schema=ident["schema"]) }
            for k, v in field_types.items():
                if k not in cols_existing:
                    ops.append(f"ALTER TABLE {ident['qualified']} ADD COLUMN {k} {_sa_type_to_sql(v)}")
            if "timestamp_utc" not in cols_existing:
                ops.append(f"ALTER TABLE {ident['qualified']} ADD COLUMN timestamp_utc DATETIME NOT NULL")
        results.append({"id": t.get("id"), "name": ident["qualified"], "operations": ops})
    return {"success": True, "items": results}


def _sa_type_to_sql(t):
    if t is Integer:
        return "INTEGER"
    if t is Float:
        return "REAL"
    if t is Boolean:
        return "BOOLEAN"
    return "TEXT"


@router.post("/migrate")
def migrate(payload: Dict[str, Any]) -> Dict[str, Any]:
    ids: List[str] = payload.get("ids") or ([] if not payload.get("id") else [payload.get("id")])
    if not ids:
        raise HTTPException(status_code=400, detail="NO_TABLE_IDS")
    results: List[Dict[str, Any]] = []
    for tid in ids:
        t = Store.instance().get_table(tid)
        if not t:
            results.append({"id": tid, "error": "TABLE_NOT_FOUND"})
            continue
        schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
        field_types = {f["key"]: _to_sa_type(f.get("type", "string")) for f in (schema.get("fields") or [])}
        engine = _engine_for_target(t.get("dbTargetId"))
        _ensure_namespace(engine)
        ident = _physical_ident(engine, t.get("name"))
        md = MetaData()
        md.reflect(bind=engine)
        insp = inspect(engine)
        has_tbl = insp.has_table(ident["name"], schema=ident["schema"]) if hasattr(insp, "has_table") else insp.has_table(ident["name"])  # type: ignore[attr-defined]
        if not has_tbl:
            # create table
            columns = [Column("timestamp_utc", String, nullable=False)]
            for k, typ in field_types.items():
                columns.append(Column(k, typ))
            # Place in neuract schema when supported
            if ident["schema"]:
                new_table = Table(ident["name"], md, *columns, schema=ident["schema"])  # type: ignore[arg-type]
            else:
                new_table = Table(ident["name"], md, *columns)
            md.create_all(bind=engine, tables=[new_table])
            # ensure index on timestamp_utc
            with engine.begin() as conn:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{ident['name']}_ts ON {ident['qualified']}(timestamp_utc)"))
                except Exception:
                    # Fallback for engines without IF NOT EXISTS
                    try:
                        conn.execute(text(f"CREATE INDEX idx_{ident['name']}_ts ON {ident['qualified']}(timestamp_utc)"))
                    except Exception:
                        pass
            # Maintain local catalog entry for status/mapping tracking
            Store.instance().set_table_status(tid, "migrated", migrated_at_iso=_now_ist_iso())
            results.append({"id": tid, "name": ident["qualified"], "status": "created"})
        else:
            # add missing columns
            existing_cols = {c["name"] for c in insp.get_columns(ident["name"], schema=ident["schema"]) }
            with engine.begin() as conn:
                for k, typ in field_types.items():
                    if k not in existing_cols:
                        conn.execute(text(f"ALTER TABLE {ident['qualified']} ADD COLUMN {k} {_sa_type_to_sql(typ)}"))
                if "timestamp_utc" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {ident['qualified']} ADD COLUMN timestamp_utc DATETIME NOT NULL"))
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{ident['name']}_ts ON {ident['qualified']}(timestamp_utc)"))
                except Exception:
                    try:
                        conn.execute(text(f"CREATE INDEX idx_{ident['name']}_ts ON {ident['qualified']}(timestamp_utc)"))
                    except Exception:
                        pass
            # Maintain local catalog entry for status/mapping tracking
            Store.instance().set_table_status(tid, "migrated", migrated_at_iso=_now_ist_iso())
            results.append({"id": tid, "name": ident["qualified"], "status": "updated"})
    return {"success": True, "items": results}
IST = timezone(timedelta(hours=5, minutes=30))
def _now_ist_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()
