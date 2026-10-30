from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_ENGINE: Optional[Engine] = None

# SEC-2: schema field keys become SQL column identifiers in target-DB DDL
# (tables.py migrate) and in the Rust engine's INSERT column lists. This is
# the persistence chokepoint — every write path (create, add/patch field,
# import, AI tools) funnels through save_schema/add_schema_field, so bad keys
# can never reach the catalog regardless of route-level validation.
_FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_IDENT_LEN = 63  # PostgreSQL identifier limit


def _check_field_key(key: Any) -> str:
    k = key or ""
    if not isinstance(k, str) or not _FIELD_KEY_RE.match(k) or len(k) > _MAX_IDENT_LEN:
        raise ValueError(f"FIELD_KEY_INVALID:{k}")
    return k


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
        _ensure_column(c, "app_schemas", "description", "TEXT")
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
        _ensure_column(c, "app_schema_fields", "formula", "TEXT")
        _ensure_column(c, "app_schema_fields", "eval_order", "INTEGER")
        # Per-meter-model default Modbus address. The effective per-table value
        # still lives in the target DB's device_mappings; this is the template
        # the mapping grid pre-fills from.
        _ensure_column(c, "app_schema_fields", "address", "TEXT")
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
        _ensure_column(c, "app_devices", "unit_id", "INTEGER")
        _ensure_column(c, "app_devices", "port", "INTEGER")
        _ensure_column(c, "app_devices", "gateway_id", "TEXT")
        # Nominal (rated) voltage of the installation this device measures. Per DEVICE,
        # not per schema: one meter model serves 415 V panels and 33 kV incomers alike,
        # so voltage-deviation formulas cannot hardcode it.
        _ensure_column(c, "app_devices", "nominal_voltage", "REAL")
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
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_notifications (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL DEFAULT 'job',
                    message TEXT NOT NULL,
                    "user" TEXT NOT NULL,
                    read BOOLEAN NOT NULL DEFAULT FALSE,
                    time TEXT NOT NULL
                )
                """
            )
        )
        # Protocol types table
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_protocol_types (
                    type TEXT PRIMARY KEY
                )
                """
            )
        )
        # Pre-populate with existing protocols
        for proto in ["modbus", "opcua", "mqtt", "derived"]:
            try:
                c.execute(
                    text(_upsert_sql("app_protocol_types", ["type"], ["type"])),
                    {"type": proto}
                )
            except Exception:
                pass  # Already exists

        # Add foreign key constraint from gateways.protocol_hint to protocol_types.type
        # Only for PostgreSQL (SQLite doesn't support ALTER TABLE ADD CONSTRAINT easily)
        try:
            dialect = c.connection.dialect.name
            if dialect in ("postgresql", "postgres", "psycopg2"):
                c.execute(
                    text(
                        """
                        ALTER TABLE app_gateways
                        ADD CONSTRAINT fk_gateway_protocol_hint
                        FOREIGN KEY (protocol_hint)
                        REFERENCES app_protocol_types(type)
                        """
                    )
                )
        except Exception:
            # Constraint already exists or not supported
            pass

        # Phase 3D — SLD topology inference
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_device_topology (
                    device_id TEXT PRIMARY KEY,
                    parent_device_id TEXT,
                    hierarchy_level TEXT NOT NULL DEFAULT 'unknown',
                    load_pattern TEXT NOT NULL DEFAULT 'unknown',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    gateway_id TEXT,
                    inferred_at TEXT,
                    snapshot_count INTEGER DEFAULT 0
                )
                """
            )
        )
    _init_equipment()
    _init_schema_vocab()
    _init_device_verification()
    _init_alerts()


# ---------- Schema field types + units (DB-managed lists) ----------
# app_field_type: the words a schema field's `type` may use. `encoding` is the
#   register decoding the Rust engine understands (float32, int16, ...); the
#   mapping row's encoding is taken from here, so a word like "REAL" decodes
#   as float32 instead of falling back to one u16 register.
# app_field_unit: the units a schema field may use.
# Both are seed data, edited directly in the DB (no write endpoints).
FIELD_ENCODINGS = ("float32", "float64", "uint16", "uint16_enum", "int16", "uint32", "int32", "uint64", "int64", "bool16")
_FIELD_TYPE_SEED = [
    # id (case-insensitive word), label, encoding, sort
    ("float32", "Float 32-bit", "float32", 1),
    ("float", "Float (32-bit)", "float32", 2),
    ("float64", "Float 64-bit", "float64", 3),
    ("int16", "Integer 16-bit", "int16", 4),
    ("uint16", "Unsigned 16-bit", "uint16", 5),
    ("uint16_enum", "Enum (unsigned 16-bit)", "uint16_enum", 6),
    ("int32", "Integer 32-bit", "int32", 7),
    ("uint32", "Unsigned 32-bit", "uint32", 8),
    ("int64", "Integer 64-bit", "int64", 9),
    ("uint64", "Unsigned 64-bit", "uint64", 10),
    ("bool16", "Boolean (16-bit register)", "bool16", 11),
    # Words found in stored schemas (older imports).
    ("real", "REAL (32-bit float)", "float32", 20),
    ("boolean", "Boolean", "bool16", 21),
]
_FIELD_UNIT_SEED = [
    "V", "kV", "A", "kA", "W", "kW", "MW", "VA", "kVA", "MVA", "var", "kvar", "Mvar",
    "Wh", "kWh", "MWh", "varh", "kvarh", "VAh", "kVAh", "Hz", "%", "°C", "°F",
    "bar", "kPa", "Pa", "m3/h", "l/s", "rpm", "s", "min", "h",
]


def _init_schema_vocab() -> None:
    with _conn() as c:
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_field_type (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    encoding TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_field_unit (
                    id TEXT PRIMARY KEY,
                    label TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        for tid, label, enc, order in _FIELD_TYPE_SEED:
            c.execute(
                text(_upsert_sql("app_field_type", ["id", "label", "encoding", "sort_order"], ["id"], [])),
                {"id": tid, "label": label, "encoding": enc, "sort_order": order},
            )
        # Units: the common set plus every unit already used by a stored field,
        # so existing schemas stay editable.
        used = [r[0] for r in c.execute(text("SELECT DISTINCT unit FROM app_schema_fields WHERE unit IS NOT NULL AND unit <> ''")).fetchall()]
        for i, u in enumerate(list(dict.fromkeys(_FIELD_UNIT_SEED + used))):
            c.execute(
                text(_upsert_sql("app_field_unit", ["id", "label", "sort_order"], ["id"], [])),
                {"id": u, "label": u, "sort_order": i + 1},
            )
        # Any stored type word missing from the list is added (decoding fallback
        # float32, the engine's numeric default) so no schema becomes uneditable.
        known = {r[0] for r in c.execute(text("SELECT id FROM app_field_type")).fetchall()}
        for (word,) in c.execute(text("SELECT DISTINCT lower(type) FROM app_schema_fields WHERE type IS NOT NULL")).fetchall():
            if word and word not in known:
                c.execute(
                    text(_upsert_sql("app_field_type", ["id", "label", "encoding", "sort_order"], ["id"], [])),
                    {"id": word, "label": word, "encoding": "float32", "sort_order": 99},
                )


def load_field_types() -> List[Dict[str, Any]]:
    with _conn() as c:
        return _fetchall(c, "SELECT id, label, encoding, sort_order FROM app_field_type ORDER BY sort_order, id")


def load_field_units() -> List[Dict[str, Any]]:
    with _conn() as c:
        return _fetchall(c, "SELECT id, label, sort_order FROM app_field_unit ORDER BY sort_order, id")


# ---------- Alerts on readings ----------
# app_alert: alert levels (user-managed; seeded Critical / Mild / Info).
# app_schema_alert: the blueprint — a rule on a schema field that applies to
#   every table of that schema.
# app_table_alert: per-table override of a rule for the same field + level
#   (enabled = 0 switches the inherited rule off for that table).
# app_alert_state: the current non-normal state per table field (written by
#   the Rust engine on state change).
# app_alert_event: one row per state change (written by the Rust engine).
ALERT_OPS = (">", ">=", "<", "<=", "==", "!=")
_ALERT_LEVEL_SEED = [
    # id, name, severity, color, sort
    ("critical", "Critical", 3, "#b42318", 1),
    ("mild", "Mild", 2, "#b54708", 2),
    ("info", "Info", 1, "#175cd3", 3),
]


def _init_alerts() -> None:
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS app_alert (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            severity INTEGER NOT NULL DEFAULT 1,
            color TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_name ON app_alert (lower(name))",
        """
        CREATE TABLE IF NOT EXISTS app_schema_alert (
            id TEXT PRIMARY KEY,
            schema_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            op TEXT NOT NULL CHECK (op IN ('>', '>=', '<', '<=', '==', '!=')),
            threshold DOUBLE PRECISION NOT NULL
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_schema_alert ON app_schema_alert (schema_id, field_key, alert_id)",
        """
        CREATE TABLE IF NOT EXISTS app_table_alert (
            id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            op TEXT CHECK (op IS NULL OR op IN ('>', '>=', '<', '<=', '==', '!=')),
            threshold DOUBLE PRECISION,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_table_alert ON app_table_alert (table_id, field_key, alert_id)",
        """
        CREATE TABLE IF NOT EXISTS app_alert_state (
            table_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            value DOUBLE PRECISION,
            since TEXT NOT NULL,
            PRIMARY KEY (table_id, field_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS app_alert_event (
            id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            field_key TEXT NOT NULL,
            from_alert_id TEXT,
            to_alert_id TEXT,
            value DOUBLE PRECISION,
            op TEXT,
            threshold DOUBLE PRECISION,
            job_id TEXT,
            at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_alert_event_table_at ON app_alert_event (table_id, at)",
    ]
    with _conn() as c:
        for stmt in ddl:
            c.execute(text(stmt))
        # Seed the default levels once (a level the user deletes must not come back).
        seeded = _fetchone(c, "SELECT value FROM app_meta WHERE key='alert_levels_seeded'")
        if not seeded:
            for aid, name, sev, color, order in _ALERT_LEVEL_SEED:
                c.execute(
                    text(_upsert_sql("app_alert", ["id", "name", "severity", "color", "sort_order"], ["id"], [])),
                    {"id": aid, "name": name, "severity": sev, "color": color, "sort_order": order},
                )
            c.execute(
                text(_upsert_sql("app_meta", ["key", "value"], ["key"])),
                {"key": "alert_levels_seeded", "value": "1"},
            )


# ---------- Device verification results (last quick_test per device) ----------
def _init_device_verification() -> None:
    with _conn() as c:
        c.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_device_verification (
                    device_id TEXT PRIMARY KEY,
                    ok INTEGER NOT NULL,
                    latency_ms INTEGER,
                    error TEXT,
                    at TEXT NOT NULL
                )
                """
            )
        )


def save_device_verification(device_id: str, ok: bool, latency_ms: Optional[int], error: Optional[str], at: str) -> None:
    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_device_verification", ["device_id", "ok", "latency_ms", "error", "at"], ["device_id"])),
            {"device_id": device_id, "ok": 1 if ok else 0, "latency_ms": latency_ms, "error": error, "at": at},
        )


def clear_device_verification(device_id: str) -> None:
    with _conn() as c:
        c.execute(text("DELETE FROM app_device_verification WHERE device_id=:d"), {"d": device_id})


def load_device_verifications() -> Dict[str, Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT device_id, ok, latency_ms, error, at FROM app_device_verification")
    return {
        r["device_id"]: {"ok": bool(r["ok"]), "latencyMs": r["latency_ms"], "error": r["error"], "at": r["at"]}
        for r in rows
    }


# ---------- Electrical equipment ----------
# An element (app_equipment) = category + kind + optional type:
# app_equipment_category: EMS / Source / BMS (seed data, edited in the DB).
#   `kinds_json` = the kinds its elements may have (EMS: single and
#   distribution; Source / BMS: none until decided).
# app_equipment.kind: "single" (MFMs directly, a hidden main node) or
#   "distribution" (buses). Fixed at create.
# app_equipment_type: user-defined types (Load, HT Panel, Transformer, ...),
#   one global list; `config_json` = its nameplate field definitions and the
#   default capacity of a single element's main node. The built-in five are
#   seeded once (types a user deletes do not come back).
# app_equipment_zone: user-managed zones (North, Production Block A, ...);
#   an element may sit in one (app_equipment.zone_id).
# app_bus: the connection nodes. Distribution elements have 1..N buses;
#   single elements have exactly one hidden "main" node (is_main = 1). A node
#   has incomer / outgoer capacity.
# app_bus_type: the types allowed on a node's incoming / outgoing side.
# app_bus_equipment: elements attached to a node as incomer / outgoer, in
#   order (sort_order = position). On a single element's main node, an
#   outgoer row is a direct link (that element feeds the attached one).
# app_bus_meter: MFMs on a node. An MFM is a logger table (where its readings
#   are written; its device and schema come from the table); a table is on
#   one node only. On a bus each MFM sits in a relation's slot (equipment_id = the attached
#   incomer / outgoer it measures, one MFM per relation) or, outgoing only,
#   with no relation: a spare.
EQUIPMENT_KINDS = ("single", "distribution")
_EQUIPMENT_CATEGORY_SEED = [
    # id, name, sort_order, allowed kinds
    ("ems", "EMS", 1, ["single", "distribution"]),
    ("source", "Source", 2, []),
    ("bms", "BMS", 3, []),
]
_V = ["kV", "V"]
_FIELD_VOLTAGE_IN = {"id": "voltage", "label": "Voltage", "kind": "quantity", "units": _V, "required": True}
_EQUIPMENT_TYPE_SEED = [
    # id, name, sort_order, config
    ("source", "Source", 1, {
        "fields": [
            {"id": "voltage", "label": "Voltage", "kind": "quantity", "units": _V, "required": True, "role": "voltage.out"},
            {"id": "rated_power", "label": "Rated power", "kind": "quantity", "units": ["kVA", "MVA", "kW", "MW"]},
            {"id": "phase", "label": "Phase", "kind": "choice", "options": ["3 Phase", "1 Phase"]},
        ],
        "node": {"incomers": 0, "outgoers": 1},
    }),
    ("transformer", "Transformer", 2, {
        "fields": [
            {"id": "primary_voltage", "label": "Primary voltage", "kind": "quantity", "units": _V, "required": True, "role": "voltage.in"},
            {"id": "secondary_voltage", "label": "Secondary voltage", "kind": "quantity", "units": _V, "required": True, "role": "voltage.out"},
            {"id": "rated_capacity", "label": "Rated capacity", "kind": "quantity", "units": ["kVA", "MVA"], "required": True},
            {"id": "phase", "label": "Phase", "kind": "choice", "options": ["3 Phase", "1 Phase"], "required": True},
        ],
        "node": {"incomers": 1, "outgoers": 1},
    }),
    ("ht_panel", "HT Panel", 3, {
        "fields": [
            {"id": "bus_voltage", "label": "Bus / operating voltage", "kind": "quantity", "units": _V, "required": True, "role": "voltage"},
        ],
    }),
    ("lt_panel", "LT Panel", 4, {
        "fields": [
            {"id": "bus_voltage", "label": "Bus / operating voltage", "kind": "quantity", "units": _V, "required": True, "role": "voltage"},
        ],
    }),
    ("load", "Load", 5, {
        "fields": [
            {"id": "supply_voltage", "label": "Supply voltage", "kind": "quantity", "units": ["V", "kV"], "required": True, "role": "voltage.in"},
            {"id": "phase", "label": "Phase", "kind": "choice", "options": ["3 Phase", "1 Phase"], "required": True},
            {"id": "rated_power", "label": "Rated power", "kind": "quantity", "units": ["kW", "MW"]},
            {"id": "rated_current", "label": "Rated current", "kind": "quantity", "units": ["A"]},
        ],
        "node": {"incomers": 1, "outgoers": 0},
    }),
]
# Tables of earlier equipment models, replaced by the ones above.
_OLD_EQUIPMENT_TABLES = [
    "app_equipment_map_links",
    "app_equipment_map_nodes",
    "app_equipment_bus_positions",
    "app_equipment_bus_members",
    "app_equipment_buses",
    "app_equipment_devices",
    "app_equipment_nav_categories",
    "app_equipment_types",
    "app_equipment_categories",
    "app_equipment_meter",
]
_EQUIPMENT_FKS = [
    ("fk_element_category", "app_equipment", "category_id", "app_equipment_category(id)", ""),
    ("fk_element_type", "app_equipment", "type_id", "app_equipment_type(id)", ""),
    ("fk_element_zone", "app_equipment", "zone_id", "app_equipment_zone(id)", ""),
    ("fk_bus_equipment", "app_bus", "equipment_id", "app_equipment(id)", "ON DELETE CASCADE"),
    ("fk_bus_type_bus", "app_bus_type", "bus_id", "app_bus(id)", "ON DELETE CASCADE"),
    ("fk_bus_type_type", "app_bus_type", "type_id", "app_equipment_type(id)", ""),
    ("fk_bus_equipment_bus", "app_bus_equipment", "bus_id", "app_bus(id)", "ON DELETE CASCADE"),
    ("fk_bus_equipment_equipment", "app_bus_equipment", "equipment_id", "app_equipment(id)", ""),
    ("fk_bus_meter_bus", "app_bus_meter", "bus_id", "app_bus(id)", "ON DELETE CASCADE"),
    ("fk_bus_meter_table", "app_bus_meter", "table_id", "app_device_tables(id)", ""),
]


def _drop_old_equipment_model(c) -> None:
    """One-time removal of earlier equipment models (idempotent)."""
    cascade = " CASCADE" if _dialect_name() == "postgresql" else ""
    if "nav_category_id" in _column_names(c, "app_equipment"):
        c.execute(text(f"DROP TABLE app_equipment{cascade}"))
    for t in _OLD_EQUIPMENT_TABLES:
        c.execute(text(f"DROP TABLE IF EXISTS {t}{cascade}"))


def _migrate_equipment_to_types(c) -> None:
    """One-time, in place (2026-10-27): the old category (Transformer, HT
    Panel, ...) becomes the user-defined *type*, the old group (EMS / Source /
    BMS) becomes the *category*, and single / distribution moves onto each
    element as its *kind*. Runs only on the old schema."""
    old_cols = _column_names(c, "app_equipment_category")
    if "type" not in old_cols or _column_names(c, "app_equipment_type"):
        return
    pg = _dialect_name() == "postgresql"
    ex = lambda sql: c.execute(text(sql))  # noqa: E731
    has_groups = bool(_column_names(c, "app_equipment_group"))
    # 1. Each element keeps what its old category said: kind, and its group.
    _ensure_column(c, "app_equipment", "kind", "TEXT")
    _ensure_column(c, "app_equipment", "new_category_id", "TEXT")
    ex("UPDATE app_equipment SET kind = (SELECT k.type FROM app_equipment_category k WHERE k.id = app_equipment.category_id)")
    group_src = (
        "(SELECT k.group_id FROM app_equipment_category k WHERE k.id = app_equipment.category_id)"
        if "group_id" in old_cols else "NULL"
    )
    ex(f"UPDATE app_equipment SET new_category_id = COALESCE({group_src}, 'ems')")
    # 2. Constraints that point at the old names go; the FK pass re-adds them.
    if pg:
        for t, name in (("app_equipment", "fk_equipment_category"), ("app_equipment_category", "fk_category_group"),
                        ("app_bus_category", "fk_bus_category_bus"), ("app_bus_category", "fk_bus_category_category")):
            ex(f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {name}")
    for idx in ("ix_equipment_category", "ux_equipment_category_name", "ux_equipment_group_name"):
        ex(f"DROP INDEX IF EXISTS {idx}")
    # 3. Renames: elements, the type table, bus rules, then the category table.
    ex("ALTER TABLE app_equipment RENAME COLUMN category_id TO type_id")
    ex("ALTER TABLE app_equipment RENAME COLUMN new_category_id TO category_id")
    ex("ALTER TABLE app_equipment_category RENAME TO app_equipment_type")
    for col in ("type", "group_id"):
        if col in old_cols:
            ex(f"ALTER TABLE app_equipment_type DROP COLUMN {col}")
    if _column_names(c, "app_bus_category"):
        ex("ALTER TABLE app_bus_category RENAME TO app_bus_type")
        ex("ALTER TABLE app_bus_type RENAME COLUMN category_id TO type_id")
    if has_groups:
        ex("ALTER TABLE app_equipment_group RENAME TO app_equipment_category")
    if pg:
        ex("ALTER TABLE app_equipment ALTER COLUMN type_id DROP NOT NULL")  # the type is optional
        ex("ALTER TABLE app_equipment ALTER COLUMN kind SET NOT NULL")
        ex("ALTER TABLE app_equipment ALTER COLUMN category_id SET NOT NULL")
        ex("ALTER TABLE app_equipment ADD CONSTRAINT ck_equipment_kind CHECK (kind IN ('single', 'distribution'))")
    # The built-in types exist already: never re-seed them.
    c.execute(text(_upsert_sql("app_meta", ["key", "value"], ["key"])), {"key": "equipment_types_seeded", "value": "1"})


def _migrate_bus_meter_to_tables(c) -> None:
    """One-time (2026-10-27): MFM slots hold the logger table, not the device.
    A slot whose device has exactly one table keeps that table; others are
    dropped (logged). Runs only while app_bus_meter still has device_id."""
    cols = _column_names(c, "app_bus_meter")
    if not cols or "table_id" in cols:
        return
    log = logging.getLogger(__name__)
    old = c.execute(text(
        "SELECT bus_id, device_id, role, " + ("equipment_id" if "equipment_id" in cols else "NULL") +
        " AS equipment_id, sort_order FROM app_bus_meter"
    )).mappings().all()
    keep = []
    for r in old:
        tables = c.execute(text("SELECT id FROM app_device_tables WHERE device_id=:d"), {"d": r["device_id"]}).fetchall()
        if len(tables) == 1:
            keep.append({**dict(r), "table_id": tables[0][0]})
        else:
            log.warning("MFM slot dropped: device %s has %d tables (bus %s)", r["device_id"], len(tables), r["bus_id"])
    cascade = " CASCADE" if _dialect_name() == "postgresql" else ""
    c.execute(text(f"DROP TABLE app_bus_meter{cascade}"))
    c.execute(text(
        "CREATE TABLE app_bus_meter (bus_id TEXT NOT NULL, table_id TEXT NOT NULL UNIQUE, "
        "role TEXT CHECK (role IS NULL OR role IN ('incomer', 'outgoer')), equipment_id TEXT, "
        "sort_order INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (bus_id, table_id))"
    ))
    for r in keep:
        c.execute(text(
            "INSERT INTO app_bus_meter (bus_id, table_id, role, equipment_id, sort_order) VALUES (:bus_id, :table_id, :role, :equipment_id, :sort_order)"
        ), r)


def seed_equipment_types(c=None) -> None:
    """Insert the built-in types once (a type the user deletes stays deleted)."""
    import json as _json

    if c is None:
        with _conn() as conn:
            return seed_equipment_types(conn)
    if _fetchone(c, "SELECT value FROM app_meta WHERE key='equipment_types_seeded'"):
        return
    for tid, name, order, config in _EQUIPMENT_TYPE_SEED:
        c.execute(
            text(_upsert_sql("app_equipment_type", ["id", "name", "sort_order", "config_json"], ["id"], [])),
            {"id": tid, "name": name, "sort_order": order, "config_json": _json.dumps(config)},
        )
    c.execute(text(_upsert_sql("app_meta", ["key", "value"], ["key"])), {"key": "equipment_types_seeded", "value": "1"})


def _init_equipment() -> None:
    import json as _json
    import secrets as _secrets
    import time as _time

    ddl = [
        """
        CREATE TABLE IF NOT EXISTS app_equipment_category (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_category_name ON app_equipment_category (lower(name))",
        """
        CREATE TABLE IF NOT EXISTS app_equipment_type (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            config_json TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_type_name ON app_equipment_type (lower(name))",
        """
        CREATE TABLE IF NOT EXISTS app_equipment_zone (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_zone_name ON app_equipment_zone (lower(name))",
        """
        CREATE TABLE IF NOT EXISTS app_equipment (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('single', 'distribution')),
            type_id TEXT,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_name ON app_equipment (lower(name))",
        "CREATE INDEX IF NOT EXISTS ix_equipment_category ON app_equipment (category_id)",
        "CREATE INDEX IF NOT EXISTS ix_equipment_type ON app_equipment (type_id)",
        """
        CREATE TABLE IF NOT EXISTS app_bus (
            id TEXT PRIMARY KEY,
            equipment_id TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            incomers INTEGER NOT NULL DEFAULT 0 CHECK (incomers >= 0),
            outgoers INTEGER NOT NULL DEFAULT 0 CHECK (outgoers >= 0)
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_bus_name ON app_bus (equipment_id, lower(name))",
        # Which types may be a node's incomers / outgoers.
        # No rows for a role = not restricted.
        """
        CREATE TABLE IF NOT EXISTS app_bus_type (
            bus_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('incomer', 'outgoer')),
            type_id TEXT NOT NULL,
            PRIMARY KEY (bus_id, role, type_id)
        )
        """,
        # Equipment attached to a bus as an incomer or outgoer. An equipment may
        # sit on several buses (multiple parents), once per bus.
        """
        CREATE TABLE IF NOT EXISTS app_bus_equipment (
            bus_id TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('incomer', 'outgoer')),
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bus_id, equipment_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_bus_equipment_equipment ON app_bus_equipment (equipment_id)",
        # MFMs on a node: logger tables. role = incomer / outgoer on a bus; NULL
        # for a single element's own meters. A table is on one node only.
        """
        CREATE TABLE IF NOT EXISTS app_bus_meter (
            bus_id TEXT NOT NULL,
            table_id TEXT NOT NULL UNIQUE,
            role TEXT CHECK (role IS NULL OR role IN ('incomer', 'outgoer')),
            equipment_id TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bus_id, table_id)
        )
        """,
    ]
    with _conn() as c:
        _drop_old_equipment_model(c)
        _migrate_equipment_to_types(c)
        _migrate_bus_meter_to_tables(c)
        for stmt in ddl:
            c.execute(text(stmt))
        _ensure_column(c, "app_equipment_category", "kinds_json", "TEXT")
        _ensure_column(c, "app_equipment", "zone_id", "TEXT")
        if _dialect_name() == "postgresql":
            # Repair: the first 2026-10-27 migration kept the old NOT NULL of
            # category_id on the renamed type_id. The type is optional.
            c.execute(text("ALTER TABLE app_equipment ALTER COLUMN type_id DROP NOT NULL"))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_equipment_zone ON app_equipment (zone_id)"))
        _ensure_column(c, "app_equipment", "subtype", "TEXT")
        _ensure_column(c, "app_equipment", "spare", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "app_equipment", "values_json", "TEXT")
        _ensure_column(c, "app_bus", "is_main", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "app_bus", "coupled_next", "INTEGER NOT NULL DEFAULT 0")
        # Optimistic concurrency: bumped on any change to the equipment, its
        # nodes, rules, attachments or meters.
        _ensure_column(c, "app_equipment", "version", "INTEGER NOT NULL DEFAULT 1")
        # Which feeder (attached equipment) a bus meter measures, if named.
        _ensure_column(c, "app_bus_meter", "equipment_id", "TEXT")
        # Categories: seeded rows are inserted when missing; names, order and
        # allowed kinds edited in the DB are kept.
        for cid, name, order, kinds in _EQUIPMENT_CATEGORY_SEED:
            c.execute(
                text(_upsert_sql("app_equipment_category", ["id", "name", "sort_order"], ["id"], [])),
                {"id": cid, "name": name, "sort_order": order},
            )
            c.execute(
                text("UPDATE app_equipment_category SET kinds_json=:k WHERE id=:id AND kinds_json IS NULL"),
                {"k": _json.dumps(kinds), "id": cid},
            )
        seed_equipment_types(c)
        # One MFM per relation: a relation (bus, attached equipment) has at most
        # one meter. Savepoint: existing duplicates must not abort init.
        try:
            with c.begin_nested():
                c.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_bus_meter_relation ON app_bus_meter (bus_id, equipment_id) "
                        "WHERE equipment_id IS NOT NULL"
                    )
                )
        except Exception as e:
            logging.getLogger(__name__).warning("ux_bus_meter_relation not created (duplicate meters on a relation?): %s", e)
        # Every single equipment has exactly one main node.
        orphans = c.execute(
            text(
                "SELECT e.id, t.config_json FROM app_equipment e LEFT JOIN app_equipment_type t ON t.id = e.type_id "
                "WHERE e.kind = 'single' AND NOT EXISTS "
                "(SELECT 1 FROM app_bus b WHERE b.equipment_id = e.id AND b.is_main = 1)"
            )
        ).fetchall()
        for eq_id, cfg in orphans:
            node = (_json.loads(cfg or "{}") or {}).get("node") or {}
            c.execute(
                text(
                    "INSERT INTO app_bus (id, equipment_id, name, sort_order, incomers, outgoers, is_main) "
                    "VALUES (:id, :e, 'main', 0, :i, :o, 1)"
                ),
                {
                    "id": f"bus_{int(_time.time() * 1000)}_{_secrets.token_hex(2)}",
                    "e": eq_id,
                    "i": int(node.get("incomers", 1)),
                    "o": int(node.get("outgoers", 1)),
                },
            )
        if _dialect_name() != "postgresql":
            return
        # FKs are a backstop for the validation in equipment.py; each attempt
        # runs in a SAVEPOINT so a failure cannot abort the transaction.
        existing = {
            r[0]
            for r in c.execute(
                text("SELECT conname FROM pg_constraint WHERE conname = ANY(:names)"),
                {"names": [f[0] for f in _EQUIPMENT_FKS]},
            ).fetchall()
        }
        for name, table, col, ref, extra in _EQUIPMENT_FKS:
            if name in existing:
                continue
            try:
                with c.begin_nested():
                    c.execute(
                        text(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({col}) REFERENCES {ref} {extra}")
                    )
            except Exception:
                pass


# ---------- Schemas ----------
def load_schemas() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT id, name, description FROM app_schemas ORDER BY name")
        out: List[Dict[str, Any]] = []
        for r in rows:
            f = _fetchall(
                c,
                "SELECT key, type, unit, scale, desc_text AS \"desc\", formula, eval_order, address "
                "FROM app_schema_fields WHERE schema_id=:schema_id ORDER BY key",
                {"schema_id": r["id"]},
            )
            out.append({"id": r["id"], "name": r["name"], "description": r.get("description"), "fields": f})
        return out


def update_schema_meta(schema_id: str, name: str, description: Optional[str]) -> None:
    with _conn() as c:
        c.execute(
            text("UPDATE app_schemas SET name=:n, description=:d WHERE id=:id"),
            {"n": name, "d": description, "id": schema_id},
        )


def save_schema(schema: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_schemas", ["id", "name", "description"], ["id"])),
            {"id": schema["id"], "name": schema["name"], "description": schema.get("description")},
        )
        c.execute(text("DELETE FROM app_schema_fields WHERE schema_id=:schema_id"), {"schema_id": schema["id"]})
        for fld in schema.get("fields") or []:
            c.execute(
                text(
                    _upsert_sql(
                        "app_schema_fields",
                        ["schema_id", "key", "type", "unit", "scale", "desc_text", "formula", "eval_order", "address"],
                        ["schema_id", "key"],
                    )
                ),
                {
                    "schema_id": schema["id"],
                    "key": _check_field_key(fld.get("key")),  # SEC-2 chokepoint
                    "type": fld.get("type"),
                    "unit": fld.get("unit"),
                    "scale": fld.get("scale"),
                    "desc_text": fld.get("desc"),
                    "formula": fld.get("formula"),
                    "eval_order": fld.get("eval_order"),
                    "address": fld.get("address"),
                },
            )


def add_schema_field(schema_id: str, field: Dict[str, Any]) -> None:
    """Add a single field to an existing schema (upsert by schema_id + key)."""
    with _conn() as c:
        c.execute(
            text(
                _upsert_sql(
                    "app_schema_fields",
                    ["schema_id", "key", "type", "unit", "scale", "desc_text", "formula", "eval_order"],
                    ["schema_id", "key"],
                )
            ),
            {
                "schema_id": schema_id,
                "key": _check_field_key(field.get("key")),  # SEC-2 chokepoint
                "type": field.get("type"),
                "unit": field.get("unit"),
                "scale": field.get("scale"),
                "desc_text": field.get("desc"),
                "formula": field.get("formula"),
                "eval_order": field.get("eval_order"),
            },
        )


def delete_schema(schema_id: str) -> bool:
    """Delete a schema and all its fields. Returns True if the schema was deleted."""
    with _conn() as c:
        c.execute(text("DELETE FROM app_schema_alert WHERE schema_id=:sid"), {"sid": schema_id})
        c.execute(text("DELETE FROM app_schema_fields WHERE schema_id=:sid"), {"sid": schema_id})
        result = c.execute(text("DELETE FROM app_schemas WHERE id=:sid"), {"sid": schema_id})
        return result.rowcount > 0


def delete_schema_field(schema_id: str, field_key: str) -> bool:
    """Delete a single field from a schema. Returns True if a row was deleted."""
    with _conn() as c:
        # Alert rules on the removed field go too: the schema's, and every
        # table override / active state for that field on this schema's tables.
        c.execute(text("DELETE FROM app_schema_alert WHERE schema_id=:sid AND field_key=:key"), {"sid": schema_id, "key": field_key})
        tables = "(SELECT id FROM app_device_tables WHERE schema_id=:sid)"
        c.execute(text(f"DELETE FROM app_table_alert WHERE field_key=:key AND table_id IN {tables}"), {"sid": schema_id, "key": field_key})
        c.execute(text(f"DELETE FROM app_alert_state WHERE field_key=:key AND table_id IN {tables}"), {"sid": schema_id, "key": field_key})
        result = c.execute(
            text("DELETE FROM app_schema_fields WHERE schema_id=:sid AND key=:key"),
            {"sid": schema_id, "key": field_key},
        )
        return result.rowcount > 0


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
        # Alert overrides and active states go with the table (event history is kept).
        c.execute(text("DELETE FROM app_table_alert WHERE table_id=:id"), {"id": table_id})
        c.execute(text("DELETE FROM app_alert_state WHERE table_id=:id"), {"id": table_id})
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


def update_table(table_id: str, patch: Dict[str, Any]) -> None:
    """Update app_device_tables columns from a camelCase patch dict."""
    col_map = {"name": "name", "schemaId": "schema_id", "dbTargetId": "db_target_id"}
    sets = []
    params: Dict[str, Any] = {"id": table_id}
    for key, col in col_map.items():
        if key in patch:
            sets.append(f"{col}=:{col}")
            params[col] = patch[key]
    if not sets:
        return
    sql = f"UPDATE app_device_tables SET {', '.join(sets)} WHERE id=:id"
    with _conn() as c:
        c.execute(text(sql), params)

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
            "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect,unit_id,port,gateway_id,nominal_voltage FROM app_devices ORDER BY name",
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
                    "unitId": r.get("unit_id"),
                    "port": r.get("port"),
                    "gatewayId": r.get("gateway_id"),
                    "nominalVoltage": r.get("nominal_voltage"),
                }
            )
        return out


def upsert_device(dev: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        row = _fetchone(c, "SELECT id FROM app_devices WHERE name=:name", {"name": dev.get("name")})
        if row:
            existing = _fetchone(
                c,
                "SELECT id,name,protocol,params_json,status,latency_ms,last_error,auto_reconnect,unit_id,port,gateway_id,nominal_voltage FROM app_devices WHERE id=:id",
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
                    "unitId": existing.get("unit_id"),
                    "port": existing.get("port"),
                    "gatewayId": existing.get("gateway_id"),
                    "nominalVoltage": existing.get("nominal_voltage"),
                }
        params_blob = _params_dump(dev.get("params") or {})
        c.execute(
            text(
                _upsert_sql(
                    "app_devices",
                    ["id", "name", "protocol", "params_json", "status", "latency_ms", "last_error", "auto_reconnect", "unit_id", "port", "gateway_id", "nominal_voltage"],
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
                "unit_id": dev.get("unitId"),
                "port": dev.get("port"),
                "gateway_id": dev.get("gatewayId"),
                "nominal_voltage": dev.get("nominalVoltage"),
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


def update_device_metadata(dev_id: str, *, name: Optional[str] = None, auto_reconnect: Optional[bool] = None, unit_id: Optional[int] = None, port: Optional[int] = None, gateway_id: Optional[str] = None, nominal_voltage: Optional[float] = None) -> None:
    fields: List[str] = []
    values: Dict[str, Any] = {"id": dev_id}
    if name is not None:
        fields.append("name=:name")
        values["name"] = name
    if auto_reconnect is not None:
        fields.append("auto_reconnect=:auto_reconnect")
        values["auto_reconnect"] = 1 if auto_reconnect else 0
    if unit_id is not None:
        fields.append("unit_id=:unit_id")
        values["unit_id"] = unit_id
    if port is not None:
        fields.append("port=:port")
        values["port"] = port
    if gateway_id is not None:
        fields.append("gateway_id=:gateway_id")
        values["gateway_id"] = gateway_id
    if nominal_voltage is not None:
        fields.append("nominal_voltage=:nominal_voltage")
        values["nominal_voltage"] = nominal_voltage
    if not fields:
        return
    with _conn() as c:
        sql = f"UPDATE app_devices SET {', '.join(fields)} WHERE id=:id"
        c.execute(text(sql), values)


def update_device_connection(dev_id: str, *, protocol: str, params: Dict[str, Any]) -> None:
    """Change a device's protocol / connection params (host, endpoint, ...)."""
    with _conn() as c:
        c.execute(
            text("UPDATE app_devices SET protocol=:p, params_json=:j WHERE id=:id"),
            {"p": protocol, "j": _params_dump(params), "id": dev_id},
        )


def clear_device_gateway(dev_id: str) -> None:
    with _conn() as c:
        c.execute(text("UPDATE app_devices SET gateway_id=NULL WHERE id=:id"), {"id": dev_id})


def delete_device(dev_id: str) -> None:
    with _conn() as c:
        c.execute(text("DELETE FROM app_device_verification WHERE device_id=:id"), {"id": dev_id})
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


# ---------- Notifications ----------

NOTIFICATION_TYPES = {"job", "trigger", "alert", "migration_failed", "migration_success", "slow_query", "performance_summary", "prediction"}


def create_notification(notif_type: str, message: str, user: str) -> Dict[str, Any]:
    import uuid
    from datetime import datetime, timezone
    notif_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            text(
                'INSERT INTO app_notifications (id, type, message, "user", read, time) '
                "VALUES (:id, :type, :message, :user, :read, :time)"
            ),
            {"id": notif_id, "type": notif_type, "message": message, "user": user, "read": False, "time": now},
        )
    return {"id": notif_id, "type": notif_type, "message": message, "user": user, "read": False, "time": now}


# ---------- Protocol Types ----------
def load_protocol_types() -> List[str]:
    """Load all valid protocol types."""
    with _conn() as c:
        rows = _fetchall(c, "SELECT type FROM app_protocol_types ORDER BY type")
        return [r["type"] for r in rows]


def add_protocol_type(protocol_type: str) -> Dict[str, Any]:
    """Add a new protocol type. Returns the created/existing protocol."""
    protocol_type = protocol_type.strip().lower()
    if not protocol_type:
        raise ValueError("PROTOCOL_TYPE_REQUIRED")

    with _conn() as c:
        c.execute(
            text(_upsert_sql("app_protocol_types", ["type"], ["type"])),
            {"type": protocol_type}
        )
    return {"type": protocol_type}


def delete_protocol_type(protocol_type: str) -> bool:
    """Delete a protocol type. Returns True if deleted, False if not found."""
    with _conn() as c:
        res = c.execute(
            text("DELETE FROM app_protocol_types WHERE type=:type"),
            {"type": protocol_type}
        )
        return bool(res.rowcount and res.rowcount > 0)


def is_valid_protocol(protocol: str) -> bool:
    """Check if a protocol type exists in the database."""
    if not protocol:
        return False
    with _conn() as c:
        row = _fetchone(
            c,
            "SELECT type FROM app_protocol_types WHERE type=:type",
            {"type": protocol.lower()}
        )
        return row is not None


def list_notifications(user_uuid: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        return _fetchall(
            c,
            'SELECT id, type, message, read, time FROM app_notifications WHERE "user" = :user ORDER BY time DESC',
            {"user": user_uuid},
        )
