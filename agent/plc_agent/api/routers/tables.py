from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from ..permissions import require_logger_write

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
    REAL,
)

from .. import appdb
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


# SEC-2/L6: PostgreSQL identifier length limit (also a sane cap for SQLite).
MAX_IDENT_LEN = 63


def _sql_safe(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)) and len(name) <= MAX_IDENT_LEN


def _q(engine, name: str) -> str:
    """Quote a single SQL identifier with the dialect's preparer (SEC-2/L6)."""
    return engine.dialect.identifier_preparer.quote(name)


def _q_qualified(engine, ident: Dict[str, Any]) -> str:
    """Quoted (schema-)qualified table reference for DDL built via f-strings."""
    if ident.get("schema"):
        return f"{_q(engine, ident['schema'])}.{_q(engine, ident['name'])}"
    return _q(engine, ident["name"])


_engine_cache: Dict[str, Any] = {}


def _engine_for_target(target_id: Optional[str]):
    store = Store.instance()
    url = SQLITE_FALLBACK_URL
    if target_id:
        t = store.get_db_target(target_id)
    else:
        did = store.get_default_db_target()
        t = store.get_db_target(did) if did else None
    if t:
        provider = (t.get("provider") or "sqlite").lower()
        conn = t.get("conn") or ":memory:"
        if provider == "sqlite":
            if str(conn).startswith("sqlite:"):
                url = str(conn)
            else:
                # Resolve to absolute path to avoid CWD ambiguity
                try:
                    p = Path(str(conn)).expanduser().resolve()
                    url = f"sqlite:///{p.as_posix()}"
                except Exception:
                    url = f"sqlite:///{conn}"
        elif provider in ("postgres", "postgresql", "psycopg2", "sqlserver", "mssql", "mysql"):
            # Use raw SQLAlchemy URL for non-sqlite targets.
            url = str(conn)
    if url in _engine_cache:
        return _engine_cache[url]
    engine = create_engine(url, pool_size=5, max_overflow=10, pool_pre_ping=True)
    _engine_cache[url] = engine
    return engine


def _to_sa_type(ftype: str):
    # A type word from the DB-managed list (e.g. "REAL") is reduced to its
    # register encoding first; only new columns are affected (migrate never
    # alters existing ones).
    k = (ftype or "").lower()
    try:
        k = {r["id"].lower(): r["encoding"] for r in appdb.load_field_types()}.get(k, k)
    except Exception:
        pass
    if k in ("int", "integer", "uint16", "uint16_enum", "int16", "uint32", "int32", "uint64", "int64"):
        return REAL
    if k in ("float", "double", "number", "float32", "float64"):
        return REAL
    if k in ("bool", "boolean", "bool16"):
        return REAL
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


@router.post("/bulk_create", dependencies=[Depends(require_logger_write)])
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
            if len(safe) > MAX_IDENT_LEN:  # SEC-2/L6: Postgres identifier cap
                raise HTTPException(status_code=400, detail=f"TABLE_NAME_INVALID:{n}")
            warnings.append({"original": n, "normalized": safe})
            normalized.append(safe)

    db_target_id = payload.get("dbTargetId") or Store.instance().get_default_db_target()
    device_id = payload.get("deviceId") or payload.get("device_id") or None
    if device_id and not Store.instance().get_device(device_id):
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")

    created = Store.instance().add_tables_bulk(parent_id, normalized, db_target_id, device_id=device_id)
    resp: Dict[str, Any] = {"success": True, "message": "tables_created", "count": len(created), "items": created}
    if warnings:
        resp["warnings"] = warnings
    return resp


@router.post("/bulk_update_target", dependencies=[Depends(require_logger_write)])
def bulk_update_target(payload: Dict[str, Any]) -> Dict[str, Any]:
    db_target_id = payload.get("dbTargetId")
    if not db_target_id:
        raise HTTPException(status_code=400, detail="DB_TARGET_REQUIRED")
    ids: List[str] = payload.get("ids") or []
    name_like = payload.get("nameLike")
    if not ids and not name_like:
        raise HTTPException(status_code=400, detail="NO_TABLES")
    tables: List[Dict[str, Any]] = []
    if ids:
        for tid in ids:
            t = Store.instance().get_table(tid)
            if t:
                tables.append(t)
    if name_like:
        tables.extend(Store.instance().list_tables(name_like=name_like))
    # De-dup by id
    seen: set[str] = set()
    uniq: List[Dict[str, Any]] = []
    for t in tables:
        tid = t.get("id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        uniq.append(t)
    updated = 0
    items: List[Dict[str, Any]] = []
    for t in uniq:
        tid = t.get("id")
        if not tid:
            continue
        ut = Store.instance().set_table_db_target(tid, db_target_id)
        if ut:
            updated += 1
            items.append(ut)
    return {"success": True, "updated": updated, "items": items}


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


@router.post("/{table_id}/migrate", dependencies=[Depends(require_logger_write)])
def migrate_single(table_id: str) -> Dict[str, Any]:
    """Migrate a single table by path parameter."""
    result = migrate({"ids": [table_id]})
    items = result.get("items", [])
    if items and "error" in items[0]:
        err = items[0]
        if err["error"] == "TABLE_NOT_FOUND":
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
        # Only an unknown table is a 404; a failed migration is 4xx/500.
        status = err.get("status") if isinstance(err.get("status"), int) and 400 <= err["status"] < 600 else 500
        raise HTTPException(status_code=status, detail=f"MIGRATE_FAILED: {err.get('detail') or 'unknown error'}")
    return {"success": True, "item": items[0] if items else {}}


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


@router.post("/dry_run_ddl", dependencies=[Depends(require_logger_write)])
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
        qualified = _q_qualified(engine, ident)  # SEC-2/L6: quoted identifiers
        if not exists:
            cols = ["timestamp_utc DATETIME NOT NULL"] + [f"{_q(engine, k)} {_sa_type_to_sql(v)}" for k, v in field_types.items()]
            ops.append(f"CREATE TABLE {qualified} (" + ", ".join(cols) + ")")
        else:
            cols_existing = {c["name"] for c in insp.get_columns(ident["name"], schema=ident["schema"]) }
            for k, v in field_types.items():
                if k not in cols_existing:
                    ops.append(f"ALTER TABLE {qualified} ADD COLUMN {_q(engine, k)} {_sa_type_to_sql(v)}")
            if "timestamp_utc" not in cols_existing:
                ops.append(f"ALTER TABLE {qualified} ADD COLUMN timestamp_utc DATETIME NOT NULL")
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


@router.post("/migrate", dependencies=[Depends(require_logger_write)])
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
        # H-DBC-2: fault-isolate each table — target DDL + derived-mapping
        # population either fully succeed (then status='migrated') or this
        # item reports an error and the catalog status stays unchanged.
        try:
            results.append(_migrate_one(tid, t))
        except HTTPException as e:
            log.warning("migrate: table=%s name=%s refused: %s", tid, t.get("name"), e.detail)
            results.append({"id": tid, "error": "MIGRATE_FAILED", "detail": str(e.detail), "status": e.status_code})
        except Exception as e:
            log.warning("migrate: table=%s name=%s failed: %s", tid, t.get("name"), e)
            results.append({"id": tid, "error": "MIGRATE_FAILED", "detail": str(e)})

    return {"success": True, "items": results}


def _migrate_one(tid: str, t: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate a single table. Raises on failure; only flips status='migrated'
    after DDL AND derived-mapping population succeeded (H-DBC-2)."""
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []
    field_types = {f["key"]: _to_sa_type(f.get("type", "string")) for f in schema_fields}
    # SEC-2/L6: legacy/imported rows may predate route-level validation —
    # never let an unsafe identifier reach DDL.
    table_name = t.get("name") or ""
    if not _sql_safe(table_name):
        raise ValueError(f"TABLE_NAME_INVALID:{table_name}")
    bad_keys = [k for k in field_types if not _sql_safe(k)]
    if bad_keys:
        raise ValueError(f"FIELD_KEY_INVALID:{','.join(sorted(bad_keys))}")
    # DP2 self-heal: recompute eval_order from the formulas BEFORE any DDL so a
    # corrupt/invalid stored order (or formula) fails the item up front.
    derived_fields = [
        f for f in _recompute_derived_eval_orders(schema_fields) if f.get("formula")
    ]
    engine = _engine_for_target(t.get("dbTargetId"))
    _ensure_namespace(engine)
    ident = _physical_ident(engine, table_name)
    md = MetaData()
    md.reflect(bind=engine)
    insp = inspect(engine)
    has_tbl = insp.has_table(ident["name"], schema=ident["schema"]) if hasattr(insp, "has_table") else insp.has_table(ident["name"])  # type: ignore[attr-defined]
    qualified = _q_qualified(engine, ident)
    warnings: List[str] = []
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
        _ensure_ts_index(engine, ident, qualified, warnings)
        status = "created"
    else:
        # add missing columns
        existing_cols = {c["name"] for c in insp.get_columns(ident["name"], schema=ident["schema"]) }
        with engine.begin() as conn:
            for k, typ in field_types.items():
                if k not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {qualified} ADD COLUMN {_q(engine, k)} {_sa_type_to_sql(typ)}"))
            if "timestamp_utc" not in existing_cols:
                conn.execute(text(f"ALTER TABLE {qualified} ADD COLUMN timestamp_utc DATETIME NOT NULL"))
        # Index creation runs OUTSIDE the ALTER transaction: a failed CREATE
        # INDEX inside the same txn silently rolled the ALTERs back on PG.
        _ensure_ts_index(engine, ident, qualified, warnings)
        status = "updated"
    # Auto-populate device_mappings for derived (formula) fields BEFORE the
    # status flip so a failure here leaves the table re-migratable (H-DBC-2).
    # Always called: also clears stale derived rows after field deletion (DP7).
    _populate_derived_mappings(engine, ident, derived_fields)
    # Maintain local catalog entry for status/mapping tracking
    Store.instance().set_table_status(tid, "migrated", migrated_at_iso=_now_ist_iso())
    item: Dict[str, Any] = {"id": tid, "name": ident["qualified"], "status": status}
    if warnings:
        item["warnings"] = warnings
    return item


def _ensure_ts_index(engine, ident: Dict[str, Any], qualified: str, warnings: List[str]) -> None:
    """Best-effort timestamp index; failures are surfaced, not swallowed (H-DBC-2)."""
    idx_name = f"idx_{ident['name']}_ts"
    with engine.begin() as conn:
        try:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {_q(engine, idx_name)} ON {qualified}(timestamp_utc)"))
            return
        except Exception:
            pass  # engine without IF NOT EXISTS — retried below in a fresh txn
    with engine.begin() as conn:
        try:
            conn.execute(text(f"CREATE INDEX {_q(engine, idx_name)} ON {qualified}(timestamp_utc)"))
        except Exception as e:
            log.warning("migrate: index create failed table=%s idx=%s err=%s", ident["qualified"], idx_name, e)
            warnings.append(f"INDEX_CREATE_FAILED:{idx_name}")


def _recompute_derived_eval_orders(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """DP2 self-heal: recompute the topological eval_order from the formulas —
    never trust stored eval_order (live DBs contain incoherent orders written
    by the old single-field persistence). Returns a deep copy; raises
    ValueError when the stored formulas are invalid."""
    import copy as _copy
    from .schemas import _validate_and_order_derived_fields  # local import avoids cycle
    work = _copy.deepcopy(fields)
    _validate_and_order_derived_fields(work)
    return work


def sync_derived_mappings_for_schema(schema_id: str) -> List[str]:
    """DP7: push the current derived-formula rows (formula in ``address``,
    eval_order in ``scale``) to neuract.device_mappings for every
    already-migrated table bound to this schema. Used by the schema field
    add/patch/delete endpoints so edits do not silently wait for the next
    migrate. NOTE: the Rust engine reloads mappings only on job (re)start.
    Returns per-table warning strings (best-effort; failures are logged)."""
    store = Store.instance()
    schema = store.get_schema(schema_id) or {}
    fields = schema.get("fields") or []
    try:
        derived = [f for f in _recompute_derived_eval_orders(fields) if f.get("formula")]
    except ValueError as e:
        log.warning("sync_derived_mappings: schema=%s invalid: %s", schema_id, e)
        return [f"DERIVED_ORDER_RECOMPUTE_FAILED:{e}"]
    warnings: List[str] = []
    for t in store.list_tables(parent_schema_id=schema_id, status="migrated"):
        try:
            engine = _engine_for_target(t.get("dbTargetId"))
            ident = _physical_ident(engine, t.get("name"))
            _populate_derived_mappings(engine, ident, derived)
        except Exception as e:
            log.warning("sync_derived_mappings: table=%s name=%s err=%s", t.get("id"), t.get("name"), e)
            warnings.append(f"DERIVED_MAPPING_SYNC_FAILED:{t.get('name')}:{e}")
    return warnings


def _populate_derived_mappings(engine, ident: Dict[str, str], derived_fields: List[Dict[str, Any]]) -> None:
    """Write derived field formulas to neuract.device_mappings so Rust can discover them.

    Derived rows are fully engine-owned: the table's 'derived' set is replaced
    atomically (delete-then-write), so removed/renamed derived fields never
    leave stale rows evaluating forever (DP7)."""
    from .mappings import _select_mapping_table, _mapping_ident, _ensure_mapping_table
    m_table = _select_mapping_table(engine, create=True)
    table_name = ident["name"]
    dialect = ""
    try:
        dialect = getattr(engine.dialect, "name", "") or ""
    except Exception:
        pass
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {m_table} WHERE table_name=:t AND protocol='derived'"),
            {"t": table_name},
        )
        for f in derived_fields:
            params = {
                "t": table_name,
                "k": f["key"],
                "p": "derived",
                "a": f["formula"],
                "dt": "float",
                "s": float(f.get("eval_order") or 0),  # reuse scale column for eval_order
                "d": None,
                "dev": None,
                "enc": "float64",
            }
            if dialect.startswith("postgres"):
                conn.execute(
                    text(
                        f"INSERT INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id,encoding) "
                        "VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev,:enc) "
                        "ON CONFLICT (table_name, field_key) DO UPDATE SET "
                        "protocol=EXCLUDED.protocol, address=EXCLUDED.address, data_type=EXCLUDED.data_type, "
                        "scale=EXCLUDED.scale, deadband=EXCLUDED.deadband, device_id=EXCLUDED.device_id, "
                        "encoding=EXCLUDED.encoding"
                    ),
                    params,
                )
            else:
                conn.execute(
                    text(
                        f"INSERT OR REPLACE INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id,encoding)"
                        " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev,:enc)"
                    ),
                    params,
                )


IST = timezone(timedelta(hours=5, minutes=30))
def _now_ist_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


# ---------- DELETE /tables/{table_id} ----------
def purge_table_storage(t: Dict[str, Any]) -> None:
    """Remove a table's physical data table and ALL its mapping rows in the target DB.

    Deleting a table must leave nothing behind. A leftover physical table reappears
    in GET /tables as a phy_ orphan, and leftover device_mappings rows are silently
    re-attached to any new table created with the same name, because mappings are
    keyed by table NAME, not id. Runs regardless of catalog status: a table can hold
    data while its catalog row says not_migrated. Raises on failure so the caller
    can abort before removing the catalog row.
    """
    from sqlalchemy import inspect as _sa_inspect

    engine = _engine_for_target(t.get("dbTargetId") or Store.instance().get_default_db_target())
    ident = _physical_ident(engine, t.get("name"))
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {_q_qualified(engine, ident)}"))
        if _sa_inspect(engine).has_table("device_mappings", schema=NEURACT_SCHEMA):
            conn.execute(
                text(f"DELETE FROM {NEURACT_SCHEMA}.device_mappings WHERE table_name=:tn"),
                {"tn": t.get("name")},
            )


@router.delete("/{table_id}", dependencies=[Depends(require_logger_write)])
def delete_table(table_id: str) -> Dict[str, Any]:
    """Delete a table completely: physical table, mapping rows, then the catalog row.

    Always full removal, so re-creating a table with the same name starts fresh.
    (The old dropPhysical flag defaulted to false and the UI never sent it, so every
    delete left orphans; an unknown query param is simply ignored by FastAPI.)
    """
    t = Store.instance().get_table(table_id)
    orphan = False
    if not t:
        # Physically-discovered orphan: GET /tables lists a physical table with no
        # catalog row as "phy_<name>". There is no catalog row to remove, so purging
        # its storage is the whole delete.
        if table_id.startswith("phy_"):
            orphan = True
            t = {
                "id": table_id,
                "name": table_id[4:],
                "dbTargetId": Store.instance().get_default_db_target(),
                "status": "migrated",
            }
        else:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    # Safety: reject if table is in a running job
    if _in_running_job(table_id):
        raise HTTPException(status_code=409, detail="TABLE_HAS_RUNNING_JOBS")
    # An element measures through this table (MFM): detach it there first.
    # Checked before the purge so storage is never dropped for a refused delete.
    from ..equipment import meter_owner

    owner = meter_owner(table_id)
    if owner:
        where = owner["name"] if owner["is_main"] else f"{owner['name']} {owner['bus_name']}"
        raise HTTPException(status_code=409, detail=f"TABLE_ATTACHED_TO_EQUIPMENT: {where} ({owner['id']})")
    try:
        purge_table_storage(t)
    except Exception as e:
        log.warning("delete_table: storage purge failed table=%s err=%s", table_id, e)
        # Abort BEFORE touching the catalog: catalog gone but data and mappings left
        # behind is exactly the orphan this delete exists to prevent. Retryable.
        raise HTTPException(status_code=500, detail=f"TABLE_PURGE_FAILED: {e}") from e
    if not orphan:
        Store.instance().delete_table(table_id)
    return {
        "success": True,
        "message": "table_deleted",
        "physicalDropped": True,
        "mappingsDeleted": True,
    }


def _in_running_job(table_id: str) -> bool:
    for job in Store.instance().list_jobs():
        if table_id in (job.get("tables") or []) and (job.get("status") or "").lower() in ("running", "started"):
            return True
    return False


# ---------- PATCH /tables/{table_id} ----------
class TableRenameConflict(ValueError):
    """Rename refused: the table is in a running job, or the new name is already in use."""


def rename_table_storage(t: Dict[str, Any], new_name: str) -> Dict[str, Any]:
    """Carry a table rename through the target DB in one transaction: the physical
    table, its timestamp index, and every device_mappings row.

    device_mappings is keyed by table NAME, and both the Rust engine and the mapping
    loader look tables up by name, so a catalog-only rename strands the data table
    and all mappings under the old name. Raises TableRenameConflict if the new name
    is already used in the target DB.
    """
    from sqlalchemy import inspect as _sa_inspect

    old_name = t.get("name")
    engine = _engine_for_target(t.get("dbTargetId") or Store.instance().get_default_db_target())
    old_ident = _physical_ident(engine, old_name)
    new_ident = _physical_ident(engine, new_name)
    insp = _sa_inspect(engine)
    if insp.has_table(new_ident["name"], schema=new_ident["schema"]):
        raise TableRenameConflict("TABLE_NAME_TAKEN")
    has_data = insp.has_table(old_ident["name"], schema=old_ident["schema"])
    has_mappings = insp.has_table("device_mappings", schema=NEURACT_SCHEMA)
    moved = 0
    with engine.begin() as conn:
        if has_mappings and conn.execute(
            text(f"SELECT COUNT(*) FROM {NEURACT_SCHEMA}.device_mappings WHERE table_name=:tn"),
            {"tn": new_name},
        ).scalar():
            raise TableRenameConflict("TABLE_NAME_HAS_MAPPINGS")
        if has_data:
            conn.execute(text(
                f"ALTER TABLE {_q_qualified(engine, old_ident)} RENAME TO {_q(engine, new_ident['name'])}"
            ))
            if _dialect_name(engine).startswith("postgres"):
                # Keep _ensure_ts_index's naming. A stale idx_<old>_ts would make a future
                # table reusing the old name silently skip its own index (IF NOT EXISTS).
                old_idx = {"schema": old_ident["schema"], "name": f"idx_{old_ident['name']}_ts"}
                new_idx = f"idx_{new_ident['name']}_ts"
                try:
                    with conn.begin_nested():
                        conn.execute(text(
                            f"ALTER INDEX IF EXISTS {_q_qualified(engine, old_idx)} RENAME TO {_q(engine, new_idx)}"
                        ))
                except Exception as e:
                    # Cosmetic only; never fail the rename over the index name.
                    log.warning("rename: index rename skipped %s -> %s err=%s", old_idx["name"], new_idx, e)
        if has_mappings:
            moved = conn.execute(
                text(f"UPDATE {NEURACT_SCHEMA}.device_mappings SET table_name=:new WHERE table_name=:old"),
                {"new": new_name, "old": old_name},
            ).rowcount
    return {"from": old_name, "to": new_name, "physicalRenamed": has_data, "mappingsMoved": moved}


def update_table_and_storage(table_id: str, patch: Dict[str, Any]) -> tuple:
    """Store.update_table, carrying a name change through the target DB first.

    Returns (updated_table or None, rename summary or None). Shared by PATCH
    /tables and the AI update_table tool so neither can do a catalog-only rename.
    """
    store = Store.instance()
    t = store.get_table(table_id)
    if not t:
        return None, None
    old_name = t.get("name")
    new_name = patch.get("name")
    if new_name is None or new_name == old_name:
        return store.update_table(table_id, {k: v for k, v in patch.items() if k != "name"}), None
    if not isinstance(new_name, str) or not _sql_safe(new_name):
        raise ValueError("INVALID_NAME")
    if _in_running_job(table_id):
        # The engine reads the table name once at job start; renaming under it breaks writes.
        raise TableRenameConflict("TABLE_HAS_RUNNING_JOBS")
    if any(o.get("id") != table_id and o.get("name") == new_name for o in store.list_tables()):
        raise TableRenameConflict("TABLE_NAME_TAKEN")
    renamed = rename_table_storage(t, new_name)
    try:
        updated = store.update_table(table_id, patch)
    except Exception:
        # Put the target DB back so it never disagrees with the catalog row.
        try:
            rename_table_storage({**t, "name": new_name}, old_name)
        except Exception as undo_err:
            log.error("rename: catalog update failed and undo failed table=%s %s->%s err=%s",
                      table_id, old_name, new_name, undo_err)
        raise
    return updated, renamed


@router.patch("/{table_id}", dependencies=[Depends(require_logger_write)])
def patch_table(table_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    patch: Dict[str, Any] = {}
    warnings: List[str] = []
    if "name" in payload:
        new_name = (payload["name"] or "").strip()
        if not new_name or not _sql_safe(new_name):
            raise HTTPException(status_code=400, detail="INVALID_NAME")
        patch["name"] = new_name
    if "schemaId" in payload:
        sid = payload["schemaId"]
        if sid and not Store.instance().get_schema(sid):
            # M-API-1: unknown-resource conditions are 404 everywhere else
            # (bulk_create PARENT_SCHEMA_NOT_FOUND, DEVICE/TABLE_NOT_FOUND);
            # this was the lone 400 for an equivalent not-found.
            raise HTTPException(status_code=404, detail="SCHEMA_NOT_FOUND")
        patch["schemaId"] = sid
        warnings.append("Schema changed; existing mappings may need update")
    if "dbTargetId" in payload:
        patch["dbTargetId"] = payload["dbTargetId"]
        if (t.get("status") or "").lower() == "migrated":
            warnings.append("DB target changed; re-migration needed")
    if not patch:
        raise HTTPException(status_code=400, detail="NO_FIELDS_TO_UPDATE")
    try:
        updated, renamed = update_table_and_storage(table_id, patch)
    except TableRenameConflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        log.warning("patch_table: update failed table=%s err=%s", table_id, e)
        raise HTTPException(status_code=500, detail=f"TABLE_UPDATE_FAILED: {e}") from e
    resp: Dict[str, Any] = {"success": True, "item": updated}
    if renamed:
        resp["renamed"] = renamed
    if warnings:
        resp["warnings"] = warnings
    return resp


# ---------- POST /tables/{table_id}/bind_device ----------
@router.post("/{table_id}/bind_device", dependencies=[Depends(require_logger_write)])
def bind_device(table_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    device_id = payload.get("deviceId") or payload.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="DEVICE_ID_REQUIRED")
    dev = Store.instance().get_device(device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    Store.instance().set_table_device_binding(table_id, device_id)
    return {"ok": True, "success": True, "message": "device_bound", "table_id": table_id, "device_id": device_id, "device_name": dev.get("name", "")}


# ---------- POST /tables/{table_id}/unbind_device ----------
@router.post("/{table_id}/unbind_device", dependencies=[Depends(require_logger_write)])
def unbind_device(table_id: str) -> Dict[str, Any]:
    t = Store.instance().get_table(table_id)
    if not t:
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    Store.instance().set_table_device_binding(table_id, None)
    return {"ok": True, "success": True, "message": "device_unbound", "table_id": table_id, "device_id": None}


# ---------- POST /tables/{table_id}/mappings/bulk ----------
@router.post("/{table_id}/mappings/bulk", dependencies=[Depends(require_logger_write)])
def table_mappings_bulk(table_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from .mappings import bulk_apply
    return bulk_apply(table_id, payload)


# ---------- POST /tables/{table_id}/mappings/validate ----------
@router.post("/{table_id}/mappings/validate", dependencies=[Depends(require_logger_write)])
def table_mappings_validate(table_id: str, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    from .mappings import validate_mapping
    return validate_mapping(table_id, payload)
