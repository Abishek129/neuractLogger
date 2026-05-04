# mypy: ignore-errors
"""
LoggerFast AI Tools — read-only tools for the Hermes agent.

Each tool is an async function that receives a ToolContext and keyword
arguments (from the LLM's function call). Tools access the Store
singleton directly — no HTTP calls.

Phase 1A tools (3):
    read_config        — system overview (entity counts)
    read_gateway_list  — all gateways with connection details
    read_schema_list   — all schemas with field definitions

Phase 1B tools (5):
    read_table_mapping — table info + mapping rows + health
    read_job_status    — job config + recent run history
    read_live_values   — current register values (real device I/O)
    read_device_status — device connection status + latency
    read_source_file   — read source files for code awareness
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path as _Path
from typing import Any, Callable, Dict, List

from .session import AISession

logger = logging.getLogger("loggerfast.ai.tools")


# ---------------------------------------------------------------------------
# Tool Context — carried into the Hermes thread via ContextVar
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """Context available to every tool invocation."""
    session: AISession
    event_queue: asyncio.Queue  # shared with HermesAgent._ndjson_queue
    tool_call_counts: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-tool call limits (per session). Tools not listed have no limit.
# ---------------------------------------------------------------------------

TOOL_CALL_LIMITS: Dict[str, int] = {
    "read_raw_registers": 50,
    "read_source_file": 20,
    "query_db": 20,
    "start_job": 10,
    "create_schema": 10,
    # Phase 2B — discovery limits
    "scan_subnet": 5,
    "enumerate_unit_ids": 20,
    "identify_device": 50,
    "discover_and_identify": 3,
    # Phase 2C — retrain limit
    "retrain_anomaly_model": 3,
    # Phase 3B — temporal model limits
    "train_temporal_model": 10,
    "retrain_temporal_model": 5,
    # Phase 3D — advanced limits
    "infer_topology": 5,
    "cloud_identify": 5,
    "marketplace_publish": 10,
    "create_session_group": 3,
    # Phase 4 — manage/mutate limits
    "delete_gateway": 10,
    "update_gateway": 10,
    "delete_device": 20,
    "update_device": 20,
    "connect_device": 20,
    "disconnect_device": 20,
    "delete_schema": 10,
    "add_schema_field": 20,
    "delete_schema_field": 20,
    "update_table": 20,
    "delete_table": 20,
    "delete_mapping_row": 50,
    "copy_mappings": 10,
    "stop_job": 10,
    "pause_job": 10,
    "delete_job": 10,
    "add_db_target": 10,
    "update_db_target": 5,
    "delete_db_target": 5,
    "set_default_db_target": 5,
}

# Dynamic limits: tools that scale with plan size (plan_count + 5, floor 10)
_DYNAMIC_LIMIT_TOOLS = {"create_device", "apply_mappings", "migrate_table", "create_table"}


def get_effective_limit(tool_name: str, session: "AISession") -> int | None:
    """Return the effective call limit for a tool, considering plan size."""
    static = TOOL_CALL_LIMITS.get(tool_name)
    if static is not None:
        return static
    if tool_name in _DYNAMIC_LIMIT_TOOLS:
        plan = getattr(session, "staged_plan", None) or {}
        summary = plan.get("summary", {})
        plan_count = sum(summary.get(k, 0) for k in ("devices", "tables", "mappings"))
        return max(plan_count + 5, 10)
    return None


# ---------------------------------------------------------------------------
# Exception classes (infrastructure for Phase 1C state enforcement)
# ---------------------------------------------------------------------------

class PreconditionError(Exception):
    """Tool called in wrong session state. Caught by make_sync_handler."""
    pass


class CallLimitExceeded(Exception):
    """Tool call budget exceeded. Caught by make_sync_handler."""
    pass


def _require_state(ctx: ToolContext, *allowed) -> None:
    """Raise PreconditionError if session is not in an allowed state.

    Phase 1B: no read-only tool calls this. Infrastructure for Phase 1C
    write tools that need state gates.
    """
    from .session import SessionState
    if allowed and ctx.session.state not in allowed:
        raise PreconditionError(
            f"Requires state {[s.value for s in allowed]}, "
            f"current is {ctx.session.state.value}"
        )


# ---------------------------------------------------------------------------
# Phase 1E — Error Taxonomy
# ---------------------------------------------------------------------------

ERROR_TAXONOMY = frozenset({
    "device:connection_failed", "device:timeout", "device:not_found",
    "device:protocol_unsupported", "device:auth_required",
    "mapping:invalid_address", "mapping:encoding_mismatch",
    "mapping:byte_order_wrong", "mapping:unmapped_table",
    "schema:duplicate_name", "schema:field_type_invalid",
    "job:start_failed", "job:no_mapped_tables",
    "validation:value_out_of_range", "validation:cross_check_failed",
    "validation:anomaly_high", "validation:anomaly_moderate",
    "gateway:name_host_required", "gateway:invalid_ports",
    "precondition:wrong_state", "gate:approval_required",
    "limit:call_limit_reached",
    "tool:timeout", "tool:execution_failed", "tool:import_failed",
    "discovery:no_response", "discovery:multiple_candidates",
    "discovery:scan_timeout", "discovery:enumeration_failed",
    "prediction:baseline_drift", "prediction:trend_alert",
    "prediction:deviation",
    "topology:insufficient_data", "topology:no_incomer_found",
    "topology:power_imbalance",
    "cloud:unavailable", "cloud:rate_limited", "cloud:timeout",
    "cloud:identification_failed",
    "session:entity_locked", "session:group_not_found",
    "session:scope_conflict",
})

# Substring → taxonomy code mapping for error classification
_ERROR_MAP: Dict[str, str] = {
    "call_limit_exceeded": "limit:call_limit_reached",
    "precondition_failed": "precondition:wrong_state",
    "tool_timeout": "tool:timeout",
    "tool_execution_failed": "tool:execution_failed",
    "IMPORT_FAILED": "tool:import_failed",
    "DEVICE_NOT_FOUND": "device:not_found",
    "DEVICE_NOT_BOUND": "mapping:unmapped_table",
    "TABLE_NOT_FOUND": "mapping:unmapped_table",
    "connect_failed": "device:connection_failed",
    "TCP_CONNECT_FAILED": "device:connection_failed",
    "CONNECTION_FAILED": "device:connection_failed",
    "GATEWAY_NOT_FOUND": "device:not_found",
    "NAME_AND_HOST_REQUIRED": "gateway:name_host_required",
    "INVALID_PORTS": "gateway:invalid_ports",
    "PROTOCOL_INVALID": "device:protocol_unsupported",
    "PROTOCOL_UNSUPPORTED": "device:protocol_unsupported",
    "NO_MAPPED_COLUMNS": "job:no_mapped_tables",
    "NO_TABLES": "job:no_mapped_tables",
    "name required": "schema:duplicate_name",
    "TYPE_INVALID": "schema:field_type_invalid",
    "READ_FAILED": "device:connection_failed",
    "MIGRATION_FAILED": "tool:execution_failed",
    "START_FAILED": "job:start_failed",
    "TEST_FAILED": "device:connection_failed",
    "modbus_error": "device:connection_failed",
    "anomaly_high": "validation:anomaly_high",
    "anomaly_moderate": "validation:anomaly_moderate",
    "no_response": "discovery:no_response",
    "multiple_candidates": "discovery:multiple_candidates",
    "scan_timeout": "discovery:scan_timeout",
    "enumeration_failed": "discovery:enumeration_failed",
    "DEVICE_NOT_MONITORED": "prediction:baseline_drift",
    "PREDICTION_MODULE_UNAVAILABLE": "tool:import_failed",
    "TOPOLOGY_MODULE_UNAVAILABLE": "tool:import_failed",
    "INSUFFICIENT_DEVICES": "topology:insufficient_data",
    "CLOUD_UNAVAILABLE": "cloud:unavailable",
    "CLOUD_MODULE_UNAVAILABLE": "tool:import_failed",
    "CLOUD_CALL_FAILED": "cloud:timeout",
    "MARKETPLACE_MODULE_UNAVAILABLE": "tool:import_failed",
    "MULTI_SESSION_MODULE_UNAVAILABLE": "tool:import_failed",
    "ENTITY_LOCKED": "session:entity_locked",
    "GROUP_NOT_FOUND": "session:group_not_found",
    "auth_required": "device:auth_required",
    "AUTH_REQUIRED": "device:auth_required",
}

# Non-retryable error types
_NON_RETRYABLE = frozenset({
    "precondition:wrong_state", "gate:approval_required", "limit:call_limit_reached",
})


def _classify_error(tool_name: str, raw_result: dict) -> str | None:
    """Map a tool result error string to a taxonomy code. Returns None if no error."""
    error = raw_result.get("error") if isinstance(raw_result, dict) else None
    if not error:
        return None
    error_str = str(error)
    for substring, code in _ERROR_MAP.items():
        if substring in error_str:
            return code
    return "tool:execution_failed"


# ---------------------------------------------------------------------------
# Phase 1E — Sanitization Gate
# ---------------------------------------------------------------------------

import re as _re

_IP_PATTERN = _re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
_CONN_STRING_PATTERN = _re.compile(r'\w+://\S+')

# Tools whose results should have IPs masked
_IP_SENSITIVE_TOOLS = frozenset({
    "create_gateway", "create_device", "test_device",
    "ping_host", "scan_port", "read_raw_registers", "browse_opcua_nodes",
    "scan_subnet", "enumerate_unit_ids", "identify_device", "discover_and_identify",
    "update_gateway", "connect_device", "add_db_target", "update_db_target",
})

# Tools whose results pass through without sanitization
_PASSTHROUGH_TOOLS = frozenset({
    "read_config", "read_gateway_list", "read_schema_list",
    "read_table_mapping", "read_job_status", "read_device_status",
    "read_source_file", "read_live_values", "validate_live_readings",
    "run_anomaly_check", "read_prediction_status",
    "read_topology", "marketplace_search",
    "list_mfm_models", "lookup_mfm_model", "read_document",
    "read_document_page_image", "read_mfm_document", "search_mfm_document",
    # Phase 4 — simple status responses
    "delete_gateway", "delete_device", "disconnect_device",
    "delete_schema", "delete_schema_field",
    "delete_table", "unbind_device_from_table",
    "delete_mapping_row", "delete_job",
    "delete_db_target", "set_default_db_target",
    "stop_job", "pause_job",
})

# Keys whose values should always be redacted
_SENSITIVE_KEYS = frozenset({"password", "pass", "credentials", "secret", "token"})


def _mask_ips(obj):
    """Recursively mask IP addresses in strings within a dict/list."""
    if isinstance(obj, str):
        return _IP_PATTERN.sub("x.x.x.x", obj)
    if isinstance(obj, dict):
        return {k: _mask_ips(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_ips(v) for v in obj]
    return obj


def _strip_sensitive_keys(obj):
    """Recursively replace sensitive key values with '***'."""
    if isinstance(obj, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_KEYS else _strip_sensitive_keys(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_strip_sensitive_keys(v) for v in obj]
    return obj


def _redact_conn_strings(obj):
    """Recursively redact connection strings (containing ://)."""
    if isinstance(obj, str) and _CONN_STRING_PATTERN.search(obj):
        return "[redacted]"
    if isinstance(obj, dict):
        return {k: _redact_conn_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_conn_strings(v) for v in obj]
    return obj


def _sanitize_for_agent(tool_name: str, raw_result: dict, args: dict) -> dict:
    """Sanitize a tool result before Hermes sees it.

    Strips IPs, credentials, connection strings. Adds error_type + retryable
    on error path. Passthrough for read-only tools.
    """
    if not isinstance(raw_result, dict):
        return raw_result

    # Error path — classify and tag
    error_type = _classify_error(tool_name, raw_result)
    if error_type:
        sanitized = dict(raw_result)
        sanitized["error_type"] = error_type
        sanitized["retryable"] = error_type not in _NON_RETRYABLE
        return _strip_sensitive_keys(sanitized)

    # Passthrough tools — no filtering needed
    if tool_name in _PASSTHROUGH_TOOLS:
        return _strip_sensitive_keys(raw_result)

    # IP-sensitive tools — mask IPs
    result = dict(raw_result)
    if tool_name in _IP_SENSITIVE_TOOLS:
        result = _mask_ips(result)

    # Always strip credentials and connection strings
    result = _strip_sensitive_keys(result)
    result = _redact_conn_strings(result)

    # query_db: strip raw SQL echo, keep structure
    if tool_name == "query_db" and "rows" in result:
        rows = result.get("rows", [])
        if len(rows) > 20:
            result["rows"] = rows[:20]
            result["rows_truncated"] = True

    return result


# ---------------------------------------------------------------------------
# Phase 1A tools
# ---------------------------------------------------------------------------

async def read_config(ctx: ToolContext, **kwargs) -> dict:
    """Return a high-level summary of the LoggerFast system configuration."""
    from ..store import Store
    store = Store.instance()
    return {
        "gateways": len(store.list_gateways()),
        "devices": len(store.list_devices()),
        "schemas": len(store.list_schemas()),
        "tables": len(store.list_tables()),
        "jobs": len(store.list_jobs()),
    }


async def read_gateway_list(ctx: ToolContext, **kwargs) -> dict:
    """Return all gateways with id, name, host, status, and ports."""
    from ..store import Store
    store = Store.instance()
    gateways = store.list_gateways()
    items = []
    for gw in gateways:
        items.append({
            "id": gw.get("id"),
            "name": gw.get("name"),
            "host": gw.get("host"),
            "status": gw.get("status", "unknown"),
            "ports": gw.get("ports", []),
            "protocol_hint": gw.get("protocol_hint"),
            "tags": gw.get("tags", []),
        })
    return {"gateways": items, "count": len(items)}


async def read_schema_list(ctx: ToolContext, **kwargs) -> dict:
    """Return all schemas with id, name, and field definitions."""
    from ..store import Store
    store = Store.instance()
    schemas = store.list_schemas()
    items = []
    for sch in schemas:
        items.append({
            "id": sch.get("id"),
            "name": sch.get("name"),
            "fields": sch.get("fields", []),
            "field_count": len(sch.get("fields", [])),
        })
    return {"schemas": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Phase 1B tools
# ---------------------------------------------------------------------------

async def read_table_mapping(ctx: ToolContext, *, table_id: str, **kwargs) -> dict:
    """Get table info, mapping rows, and health status for a specific table."""
    from ..store import Store
    store = Store.instance()

    table = store.get_table(table_id)
    if not table:
        return {"error": "TABLE_NOT_FOUND", "table_id": table_id}

    mapping = store.get_mapping(table_id)
    rows = mapping.get("rows") or {}

    # Get schema for field list + health check
    schema_id = table.get("schemaId")
    required_fields = []
    schema_info = None
    if schema_id:
        schema = store.get_schema(schema_id)
        if schema:
            schema_info = {"id": schema["id"], "name": schema.get("name")}
            required_fields = [f["key"] for f in schema.get("fields", []) if "key" in f]

    health = store.mapping_health(table_id, required_fields=required_fields)

    return {
        "table": {
            "id": table.get("id"),
            "name": table.get("name"),
            "schemaId": table.get("schemaId"),
            "deviceId": table.get("deviceId"),
            "status": table.get("status"),
            "dbTargetId": table.get("dbTargetId"),
            "lastMigratedAt": table.get("lastMigratedAt"),
        },
        "schema": schema_info,
        "mapping": {
            "deviceId": mapping.get("deviceId"),
            "health": health,
            "field_count": len(rows),
            "rows": rows,
        },
    }


async def read_job_status(ctx: ToolContext, *, job_id: str = "", **kwargs) -> dict:
    """Get job details and recent run history. If no job_id, list all jobs."""
    from ..store import Store
    from .. import appdb
    store = Store.instance()

    if not job_id:
        jobs = store.list_jobs()
        running = sum(1 for j in jobs if (j.get("status") or "").lower() == "running")
        stopped = sum(1 for j in jobs if (j.get("status") or "").lower() in ("stopped", "paused"))
        items = []
        for j in jobs:
            items.append({
                "id": j.get("id"),
                "name": j.get("name"),
                "type": j.get("type"),
                "enabled": j.get("enabled"),
                "status": j.get("status"),
                "intervalMs": j.get("intervalMs"),
                "tables": j.get("tables"),
            })
        # Put summary FIRST so it's never truncated by the 8000-char limit
        return {
            "total": len(items),
            "running": running,
            "stopped": stopped,
            "jobs": items,
        }

    job = store.get_job(job_id)
    if not job:
        return {"error": "JOB_NOT_FOUND", "job_id": job_id}

    # Recent run history (last 20)
    try:
        runs = appdb.load_job_runs(job_id)[:20]
    except Exception:
        runs = []

    return {
        "job": {
            "id": job.get("id"),
            "name": job.get("name"),
            "type": job.get("type"),
            "tables": job.get("tables"),
            "columns": job.get("columns"),
            "intervalMs": job.get("intervalMs"),
            "enabled": job.get("enabled"),
            "status": job.get("status"),
            "batching": job.get("batching"),
            "cpuBudget": job.get("cpuBudget"),
            "triggers": job.get("triggers"),
            "metrics": job.get("metrics"),
        },
        "recent_runs": runs,
        "run_count": len(runs),
    }


async def read_live_values(ctx: ToolContext, *, table_id: str, **kwargs) -> dict:
    """Read current register values from a running device for a table.

    Performs real Modbus/OPC-UA I/O — may take several seconds.
    """
    from functools import partial

    try:
        from ..routers.jobs import _read_mapping_values
    except ImportError:
        return {"error": "IMPORT_FAILED",
                "message": "Cannot import live value reader."}

    loop = asyncio.get_running_loop()
    try:
        values = await loop.run_in_executor(
            None, partial(_read_mapping_values, table_id)
        )
    except RuntimeError as e:
        msg = str(e)
        if "DEVICE_NOT_BOUND" in msg:
            return {"error": "DEVICE_NOT_BOUND", "table_id": table_id,
                    "message": "Table has no device binding. Assign a device first."}
        if "DEVICE_NOT_FOUND" in msg:
            return {"error": "DEVICE_NOT_FOUND", "table_id": table_id,
                    "message": "Bound device not found in store."}
        return {"error": "READ_FAILED", "table_id": table_id, "message": msg}
    except Exception as e:
        return {"error": "READ_FAILED", "table_id": table_id, "message": str(e)}

    result = {
        "table_id": table_id,
        "values": values,
        "field_count": len(values) if isinstance(values, dict) else 0,
    }

    # Auto-validate if we got values (Phase 1H integration)
    if isinstance(values, dict) and values:
        try:
            validation = await _run_validation(ctx, table_id, values)
            if validation:
                result["validation"] = validation
        except Exception:
            logger.debug("auto_validation_failed", exc_info=True)

        # Layer 2 — anomaly detection (Phase 1I integration)
        try:
            from .validation.anomaly import AnomalyDetector
            from .mfm_kb import get_kb_manager
            from ..store import Store

            # Resolve model name from table → device → schema lookup
            store = Store.instance()
            table_info = store.get_table(table_id) or {}
            device_id = table_info.get("deviceId") or table_info.get("device_id")
            model_name = None
            kb_registers = None
            if device_id:
                device = store.get_device(device_id) or {}
                model_name = device.get("model") or device.get("params", {}).get("model")
            if model_name:
                kb_mgr = get_kb_manager()
                kb_entry = kb_mgr.get_entry(model_name) if hasattr(kb_mgr, 'get_entry') else None
                if kb_entry:
                    kb_registers = getattr(kb_entry, "registers", None)
                    if kb_registers:
                        kb_registers = [r.model_dump() if hasattr(r, "model_dump") else r for r in kb_registers]

            if model_name and kb_registers:
                detector = AnomalyDetector.instance()
                anomaly = detector.check(values, model_name, kb_registers)
                if anomaly:
                    result["anomaly"] = {
                        "score": anomaly.score,
                        "severity": anomaly.severity,
                        "top_contributors": anomaly.top_contributors[:5],
                        "interpretation": anomaly.interpretation,
                    }
        except ImportError:
            pass  # Anomaly module not available
        except Exception:
            logger.debug("auto_anomaly_check_failed", exc_info=True)

    return result


async def validate_live_readings(ctx: ToolContext, *, table_id: str, **kwargs) -> dict:
    """Validate current device readings against physical rules and cross-checks.

    Reads live values from the device, then runs Layer 1 validation:
    range checks (voltage, current, PF, frequency, power) and cross-parameter
    consistency (V_LN×√3≈V_LL, P≈V×I×PF×√3, S²≈P²+Q², phase balance).
    Returns confidence score (High/Medium/Low) and per-parameter results.
    """
    from functools import partial

    try:
        from ..routers.jobs import _read_mapping_values
    except ImportError:
        return {"error": "IMPORT_FAILED",
                "message": "Cannot import live value reader."}

    loop = asyncio.get_running_loop()
    try:
        values = await loop.run_in_executor(
            None, partial(_read_mapping_values, table_id)
        )
    except RuntimeError as e:
        msg = str(e)
        if "DEVICE_NOT_BOUND" in msg:
            return {"error": "DEVICE_NOT_BOUND", "table_id": table_id,
                    "message": "Table has no device binding."}
        if "DEVICE_NOT_FOUND" in msg:
            return {"error": "DEVICE_NOT_FOUND", "table_id": table_id,
                    "message": "Bound device not found."}
        return {"error": "READ_FAILED", "table_id": table_id, "message": msg}
    except Exception as e:
        return {"error": "READ_FAILED", "table_id": table_id, "message": str(e)}

    if not isinstance(values, dict) or not values:
        return {"error": "NO_VALUES", "table_id": table_id,
                "message": "No values returned from device."}

    validation = await _run_validation(ctx, table_id, values)
    return {
        "table_id": table_id,
        "values": values,
        "field_count": len(values),
        "validation": validation or {"error": "validation_unavailable"},
    }


async def _run_validation(ctx: ToolContext, table_id: str, values: dict) -> dict | None:
    """Run Layer 1 validation on a set of readings. Returns serializable dict."""
    try:
        from .validation import validate_readings
        from ..store import Store
    except ImportError:
        return None

    store = Store.instance()

    # Get schema field metadata for parameter classification
    table = store.get_table(table_id)
    schema_fields = None
    if table and table.get("schemaId"):
        schema = store.get_schema(table.get("schemaId"))
        if schema:
            schema_fields = schema.get("fields")

    result = validate_readings(values, schema_fields=schema_fields)

    # Serialize ValidationResult to dict
    checks = []
    for c in result.checks:
        checks.append({
            "check_id": c.check_id,
            "severity": c.severity.value,
            "message": c.message,
            "expected": c.expected,
            "actual": c.actual,
            "field_keys": list(c.field_keys) if c.field_keys else [],
        })

    return {
        "confidence": result.confidence.value,
        "confidence_score": round(result.confidence_score, 2),
        "total_checks": result.total_checks,
        "passed": result.passed,
        "warnings": result.warnings,
        "failures": result.failures,
        "checks": checks,
    }


async def read_device_status(ctx: ToolContext, *, device_id: str = "", **kwargs) -> dict:
    """Get device connection status. If no device_id, list all devices."""
    from ..store import Store
    store = Store.instance()

    if not device_id:
        devices = store.list_devices()
        by_status = {}
        for d in devices:
            st = (d.get("status") or "unknown").lower()
            by_status[st] = by_status.get(st, 0) + 1
        items = []
        for d in devices:
            items.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "protocol": d.get("protocol"),
                "status": d.get("status"),
                "latencyMs": d.get("latencyMs"),
                "lastError": d.get("lastError"),
                "gatewayId": d.get("gatewayId"),
            })
        # Put summary FIRST so it's never truncated by the 8000-char limit
        return {"total": len(items), "by_status": by_status, "devices": items}

    dev = store.get_device(device_id)
    if not dev:
        return {"error": "DEVICE_NOT_FOUND", "device_id": device_id}

    return {
        "device": {
            "id": dev.get("id"),
            "name": dev.get("name"),
            "protocol": dev.get("protocol"),
            "status": dev.get("status"),
            "latencyMs": dev.get("latencyMs"),
            "lastError": dev.get("lastError"),
            "autoReconnect": dev.get("autoReconnect"),
            "unitId": dev.get("unitId"),
            "port": dev.get("port"),
            "gatewayId": dev.get("gatewayId"),
            "params": dev.get("params"),  # already redacted by Store
        },
    }


async def read_source_file(ctx: ToolContext, *, path: str, **kwargs) -> dict:
    """Read a source file from agent/plc_agent/ for debugging."""

    _BASE = _Path(__file__).resolve().parents[2]  # ai/ → api/ → plc_agent/

    _BLOCKED_SEGMENTS = {"vendor", "__pycache__", "data", "node_modules", ".git"}
    _BLOCKED_NAMES = {".env", ".env.example", ".envrc"}
    _BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".so",
                         ".dll", ".xlsx", ".xls", ".csv", ".log", ".err", ".out", ".pid"}
    _ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
                         ".cfg", ".ini", ".sh", ".rst", ".rs"}
    _SENSITIVE_WORDS = {"credential", "secret", "token", "password", "private_key"}
    _MAX_LINES = 500

    if not path or not path.strip():
        return {"error": "EMPTY_PATH", "message": "No file path provided."}

    clean = path.strip().lstrip("/")
    target = (_BASE / clean).resolve()

    # Escape check
    if not str(target).startswith(str(_BASE)):
        return {"error": "PATH_OUTSIDE_PROJECT",
                "message": "Path must be within agent/plc_agent/."}

    # Blocked segments
    try:
        rel_parts = target.relative_to(_BASE).parts
    except ValueError:
        return {"error": "PATH_OUTSIDE_PROJECT",
                "message": "Path must be within agent/plc_agent/."}

    for part in rel_parts:
        if part in _BLOCKED_SEGMENTS:
            return {"error": "BLOCKED_PATH",
                    "message": f"Cannot read files in '{part}/' directory."}

    # Blocked filenames
    if target.name in _BLOCKED_NAMES:
        return {"error": "BLOCKED_FILE",
                "message": f"Cannot read '{target.name}' (sensitive file)."}

    # Blocked suffixes
    if target.suffix.lower() in _BLOCKED_SUFFIXES:
        return {"error": "BLOCKED_EXTENSION",
                "message": f"Cannot read '*{target.suffix}' files."}

    # Allowed suffixes
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        return {"error": "UNSUPPORTED_EXTENSION",
                "message": f"Only source files readable: {sorted(_ALLOWED_SUFFIXES)}"}

    # Sensitive name check
    name_lower = target.stem.lower()
    for word in _SENSITIVE_WORDS:
        if word in name_lower:
            return {"error": "SENSITIVE_FILE",
                    "message": f"Cannot read files with '{word}' in the name."}

    if not target.is_file():
        return {"error": "FILE_NOT_FOUND",
                "path": str(target.relative_to(_BASE)),
                "message": "File does not exist."}

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        truncated = len(lines) > _MAX_LINES
        content = "\n".join(lines[:_MAX_LINES])
        if truncated:
            content += f"\n\n... [truncated at {_MAX_LINES} lines, total {len(lines)} lines]"
    except Exception as e:
        return {"error": "READ_FAILED", "message": str(e)}

    return {
        "path": str(target.relative_to(_BASE)),
        "lines": min(len(lines), _MAX_LINES),
        "total_lines": len(lines),
        "truncated": truncated,
        "content": content,
    }


# ---------------------------------------------------------------------------
# Phase 1C — Write tool helpers
# ---------------------------------------------------------------------------

def _ensure_applying(ctx: ToolContext) -> None:
    """Transition APPROVED → APPLYING on first write tool execution."""
    from .session import SessionState
    if ctx.session.state == SessionState.APPROVED:
        ctx.session.transition(SessionState.APPLYING)
        ctx.session.save()


def _check_entity_lock(ctx: ToolContext, entity_type: str, entity_name: str) -> dict | None:
    """Check multi-session entity lock. Returns error dict if locked, None if OK."""
    try:
        from .multi_session import SessionCoordinator
        coord = SessionCoordinator.instance()
        group = coord.find_group_for_session(ctx.session.session_id)
        if group is None:
            return None  # not in a group — no locking needed
        if not coord.acquire_lock(group.group_id, ctx.session.session_id,
                                   entity_type, entity_name):
            return {
                "error": "ENTITY_LOCKED",
                "message": f"{entity_type} '{entity_name}' is locked by another session in this group.",
            }
    except ImportError:
        pass
    return None


def _emit_progress(ctx: ToolContext, stage: str, status: str, detail: str = "") -> None:
    """Push a progress event into the NDJSON queue."""
    try:
        ctx.event_queue.put_nowait({
            "event": "stage",
            "stage": stage,
            "status": status,
            "detail": detail,
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 1C — Write tools
# ---------------------------------------------------------------------------

async def propose_plan(ctx: ToolContext, *, plan: dict, **kwargs) -> dict:
    """Stage a configuration plan for engineer approval.

    The plan dict must contain:
      steps: [{action: "create_gateway", params: {...}}, ...]
    The summary is auto-computed from steps — any AI-provided summary is overridden.
    """
    from .session import SessionState
    _require_state(ctx, SessionState.CHATTING)

    if not isinstance(plan, dict) or "steps" not in plan:
        return {"error": "INVALID_PLAN", "message": "Plan must have 'steps' array."}

    steps = plan.get("steps", [])
    if not steps:
        return {"error": "EMPTY_PLAN", "message": "Plan has no steps."}

    # Always build numeric summary from steps (the AI sometimes puts a
    # description string in "summary" instead of counts)
    from collections import Counter
    counts = Counter(s.get("action", "") for s in steps)
    plan["summary"] = {
        "gateways": counts.get("create_gateway", 0),
        "devices": counts.get("create_device", 0),
        "schemas": counts.get("create_schema", 0),
        "tables": counts.get("create_table", 0),
        "mappings": counts.get("apply_mappings", 0),
        "jobs": counts.get("create_job", 0),
    }

    ctx.session.staged_plan = plan
    ctx.session.transition(SessionState.PLAN_PROPOSED)
    ctx.session.save()

    # Emit NDJSON events
    try:
        ctx.event_queue.put_nowait({
            "event": "plan_proposed",
            "plan": plan["summary"],
        })
        ctx.event_queue.put_nowait({
            "event": "approval_required",
            "plan_id": ctx.session.session_id,
            "message": "Configuration plan requires engineer approval before execution.",
        })
    except Exception:
        pass

    return {
        "status": "ok",
        "state": "plan_proposed",
        "summary": plan["summary"],
        "step_count": len(steps),
        "message": "Plan staged. Waiting for engineer approval.",
    }


async def create_gateway(ctx: ToolContext, *, name: str, host: str,
                          ports: list | None = None, protocol_hint: str = "",
                          tags: list | None = None, **kwargs) -> dict:
    """Create a network gateway."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    lock_err = _check_entity_lock(ctx, "gateway", name)
    if lock_err:
        return lock_err
    _emit_progress(ctx, "create_gateway", "running", f"Creating gateway '{name}'")

    from ..store import Store
    try:
        gw = Store.instance().add_gateway({
            "name": name, "host": host,
            "ports": ports or [], "protocol_hint": protocol_hint,
            "tags": tags or [],
        })
    except ValueError as e:
        return {"error": str(e), "message": f"Failed to create gateway: {e}"}

    ctx.session.track_entity("gateway", gw.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "create_gateway", "complete", f"Gateway '{name}' → {gw.get('id')}")
    return {"status": "ok", "gateway": gw}


async def create_device(ctx: ToolContext, *, name: str = "", protocol: str = "modbus",
                         params: dict | None = None, gateway_id: str = "",
                         unit_id: int | str = "", port: int | str = "",
                         auto_reconnect: bool = True, **kwargs) -> dict:
    """Create a device behind a gateway."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    lock_err = _check_entity_lock(ctx, "device", name)
    if lock_err:
        return lock_err
    _emit_progress(ctx, "create_device", "running", f"Creating device '{name}'")

    from ..store import Store
    payload = {"name": name, "protocol": protocol, "params": params or {},
               "autoReconnect": auto_reconnect}
    if gateway_id:
        payload["gatewayId"] = gateway_id
    if unit_id != "":
        payload["unitId"] = unit_id
    if port != "":
        payload["port"] = port

    try:
        dev = Store.instance().add_device(payload)
    except ValueError as e:
        return {"error": str(e), "message": f"Failed to create device: {e}"}

    ctx.session.track_entity("device", dev.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "create_device", "complete", f"Device '{name}' → {dev.get('id')}")
    return {"status": "ok", "device": dev}


async def test_device(ctx: ToolContext, *, device_id: str, **kwargs) -> dict:
    """Test connectivity to a configured device. Auto-approved (no state gate)."""
    from ..store import Store
    loop = asyncio.get_running_loop()

    def _test():
        return Store.instance().test_device_connection(device_id)

    try:
        ok, latency, error = await loop.run_in_executor(None, _test)
    except Exception as e:
        return {"error": "TEST_FAILED", "device_id": device_id, "message": str(e)}

    return {
        "status": "ok" if ok else "failed",
        "device_id": device_id,
        "connected": ok,
        "latency_ms": latency,
        "error": error,
    }


async def create_schema(ctx: ToolContext, *, name: str,
                         fields: list, **kwargs) -> dict:
    """Create a field schema (template) for data tables."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    lock_err = _check_entity_lock(ctx, "schema", name)
    if lock_err:
        return lock_err
    _emit_progress(ctx, "create_schema", "running", f"Creating schema '{name}' ({len(fields)} fields)")

    from ..store import Store
    try:
        schema = Store.instance().create_schema({"name": name, "fields": fields})
    except ValueError as e:
        return {"error": str(e), "message": f"Failed to create schema: {e}"}

    ctx.session.track_entity("schema", schema.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "create_schema", "complete", f"Schema '{name}' → {schema.get('id')}")
    return {"status": "ok", "schema": schema}


async def create_table(ctx: ToolContext, *, schema_id: str, names: list,
                        db_target_id: str = "", device_id: str = "",
                        **kwargs) -> dict:
    """Create one or more data tables bound to a schema."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    for tname in names:
        lock_err = _check_entity_lock(ctx, "table", tname)
        if lock_err:
            return lock_err
    _emit_progress(ctx, "create_table", "running", f"Creating {len(names)} table(s)")

    from ..store import Store
    store = Store.instance()
    target = db_target_id or store.get_default_db_target()
    try:
        tables = store.add_tables_bulk(
            schema_id, names, target,
            device_id=device_id or None,
        )
    except Exception as e:
        return {"error": str(e), "message": f"Failed to create tables: {e}"}

    for t in tables:
        ctx.session.track_entity("table", t.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "create_table", "complete", f"{len(tables)} table(s) created")
    return {"status": "ok", "tables": tables, "count": len(tables)}


async def apply_mappings(ctx: ToolContext, *, table_id: str,
                          device_id: str = "", rows_patch: dict | None = None,
                          **kwargs) -> dict:
    """Bind register addresses to table fields."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "apply_mappings", "running", f"Applying mappings to {table_id}")

    from ..store import Store
    try:
        mapping = Store.instance().upsert_mapping(
            table_id,
            device_id=device_id or None,
            rows_patch=rows_patch,
        )
    except Exception as e:
        return {"error": str(e), "message": f"Failed to apply mappings: {e}"}

    _emit_progress(ctx, "apply_mappings", "complete", f"Mappings applied to {table_id}")
    return {"status": "ok", "mapping": mapping}


async def migrate_table(ctx: ToolContext, *, table_id: str, **kwargs) -> dict:
    """Create the physical database table for a LoggerFast table."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "migrate_table", "running", f"Migrating {table_id}")

    loop = asyncio.get_running_loop()

    def _migrate():
        from ..routers.tables import migrate
        try:
            return migrate({"ids": [table_id]})
        except Exception as e:
            # migrate() may raise HTTPException for NO_TABLE_IDS
            return {"error": str(e), "message": str(e)}

    try:
        result = await loop.run_in_executor(None, _migrate)
    except Exception as e:
        return {"error": "MIGRATION_FAILED", "table_id": table_id, "message": str(e)}

    items = result.get("items", [])
    if items and "error" in items[0]:
        return {"error": items[0]["error"], "table_id": table_id,
                "message": f"Migration failed: {items[0].get('error')}"}

    _emit_progress(ctx, "migrate_table", "complete", f"Table {table_id} migrated")
    return {"status": "ok", "table_id": table_id,
            "result": items[0] if items else {}}


async def create_job(ctx: ToolContext, *, name: str, tables: list | None = None,
                      type: str = "continuous", interval_ms: int = 1000,
                      enabled: bool = False, batching: dict | None = None,
                      **kwargs) -> dict:
    """Create a data collection job. Rejects unmapped tables."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "create_job", "running", f"Creating job '{name}'")

    from ..store import Store
    try:
        job = Store.instance().create_job({
            "name": name,
            "type": type,
            "tables": tables or [],
            "intervalMs": interval_ms,
            "enabled": enabled,
            "status": "stopped",
            "batching": batching or {},
        })
    except ValueError as e:
        return {"error": str(e), "message": f"Failed to create job: {e}"}

    ctx.session.track_entity("job", job.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "create_job", "complete", f"Job '{name}' → {job.get('id')}")
    return {"status": "ok", "job": job}


async def start_job(ctx: ToolContext, *, job_id: str, **kwargs) -> dict:
    """Start a data collection job (begins polling devices)."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "start_job", "running", f"Starting job {job_id}")

    loop = asyncio.get_running_loop()

    def _start():
        import threading
        from ..routers.jobs import _job_threads, _job_stops, _run_job_loop
        from ..store import Store
        store = Store.instance()

        job = store.get_job(job_id)
        if not job:
            return {"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

        if _job_threads.get(job_id) and _job_threads[job_id].is_alive():
            return {"status": "ok", "message": "already_running", "job_id": job_id}

        ev = threading.Event()
        _job_stops[job_id] = ev
        thr = threading.Thread(target=_run_job_loop, args=(job_id,), daemon=True)
        _job_threads[job_id] = thr
        store.set_job_status(job_id, "running")
        thr.start()
        return {"status": "ok", "message": "started", "job_id": job_id}

    try:
        result = await loop.run_in_executor(None, _start)
    except Exception as e:
        return {"error": "START_FAILED", "message": str(e)}

    _emit_progress(ctx, "start_job", "complete", f"Job {job_id} started")
    return result


# ---------------------------------------------------------------------------
# Phase 4 — Manage / Mutate tools (full parity with desktop UI)
# ---------------------------------------------------------------------------


def _require_manage_state(ctx: ToolContext) -> None:
    """Allow CHATTING, APPROVED, or APPLYING. Raises PreconditionError otherwise."""
    from .session import SessionState
    allowed = {SessionState.CHATTING, SessionState.APPROVED, SessionState.APPLYING}
    if ctx.session.state not in allowed:
        raise PreconditionError(
            f"Tool requires state chatting/approved/applying, got '{ctx.session.state.value}'")


def _maybe_ensure_applying(ctx: ToolContext) -> None:
    """Transition APPROVED → APPLYING only if in APPROVED. No-op in CHATTING."""
    from .session import SessionState
    if ctx.session.state == SessionState.APPROVED:
        _ensure_applying(ctx)


# --- Gateway Management ---


async def update_gateway(ctx: ToolContext, *, gateway_id: str, patch: dict, **kwargs) -> dict:
    """Update a gateway's configuration (name, host, ports, etc.)."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "update_gateway", "running", f"Updating gateway {gateway_id}")

    from ..store import Store
    try:
        gw = Store.instance().update_gateway(gateway_id, patch)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to update gateway: {e}"}
    if not gw:
        return {"error": "GATEWAY_NOT_FOUND", "message": f"Gateway {gateway_id} not found."}

    ctx.session.save()
    _emit_progress(ctx, "update_gateway", "complete", f"Gateway {gateway_id} updated")
    return {"status": "ok", "gateway": gw}


async def delete_gateway(ctx: ToolContext, *, gateway_id: str, **kwargs) -> dict:
    """Delete a gateway. Fails if devices still reference it."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_gateway", "running", f"Deleting gateway {gateway_id}")

    from ..store import Store
    try:
        ok = Store.instance().delete_gateway(gateway_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete gateway: {e}"}
    if not ok:
        return {"error": "GATEWAY_NOT_FOUND_OR_IN_USE",
                "message": f"Gateway {gateway_id} not found or has bound devices."}

    _emit_progress(ctx, "delete_gateway", "complete", f"Gateway {gateway_id} deleted")
    return {"status": "ok", "gateway_id": gateway_id, "deleted": True}


# --- Device Management ---


async def update_device(ctx: ToolContext, *, device_id: str, patch: dict, **kwargs) -> dict:
    """Update device metadata (name, autoReconnect, unitId, port, gatewayId)."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "update_device", "running", f"Updating device {device_id}")

    allowed = {k: v for k, v in patch.items()
               if k in ("name", "autoReconnect", "unitId", "port", "gatewayId")}
    if not allowed:
        return {"error": "NO_ALLOWED_FIELDS",
                "message": "Allowed fields: name, autoReconnect, unitId, port, gatewayId"}

    from ..store import Store
    try:
        dev = Store.instance().update_device_metadata(device_id, allowed)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to update device: {e}"}
    if not dev:
        return {"error": "DEVICE_NOT_FOUND", "message": f"Device {device_id} not found."}

    ctx.session.save()
    _emit_progress(ctx, "update_device", "complete", f"Device {device_id} updated")
    return {"status": "ok", "device": dev}


async def delete_device(ctx: ToolContext, *, device_id: str, **kwargs) -> dict:
    """Delete a device from the system."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_device", "running", f"Deleting device {device_id}")

    from ..store import Store
    try:
        ok = Store.instance().delete_device(device_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete device: {e}"}
    if not ok:
        return {"error": "DEVICE_NOT_FOUND", "message": f"Device {device_id} not found."}

    _emit_progress(ctx, "delete_device", "complete", f"Device {device_id} deleted")
    return {"status": "ok", "device_id": device_id, "deleted": True}


async def connect_device(ctx: ToolContext, *, device_id: str, **kwargs) -> dict:
    """Test connectivity and mark device as connected."""
    from ..store import Store
    loop = asyncio.get_running_loop()

    def _connect():
        store = Store.instance()
        dev = store.get_device(device_id)
        if not dev:
            return {"error": "DEVICE_NOT_FOUND", "message": f"Device {device_id} not found."}
        ok, latency, error = store.test_device_connection(device_id)
        if ok:
            store.set_device_status(device_id, status="connected",
                                    latency_ms=latency, last_error=None)
        else:
            store.set_device_status(device_id, status="degraded",
                                    latency_ms=latency, last_error=error)
        store.mark_manual_disconnect(device_id, False)
        return {"status": "ok" if ok else "degraded", "device_id": device_id,
                "connected": ok, "latency_ms": latency, "error": error}

    try:
        return await loop.run_in_executor(None, _connect)
    except Exception as e:
        return {"error": "CONNECT_FAILED", "device_id": device_id, "message": str(e)}


async def disconnect_device(ctx: ToolContext, *, device_id: str, **kwargs) -> dict:
    """Manually disconnect a device."""
    from ..store import Store
    store = Store.instance()
    dev = store.get_device(device_id)
    if not dev:
        return {"error": "DEVICE_NOT_FOUND", "message": f"Device {device_id} not found."}
    store.set_device_status(device_id, status="disconnected",
                            latency_ms=None, last_error=None)
    store.mark_manual_disconnect(device_id, True)
    return {"status": "ok", "device_id": device_id, "disconnected": True}


# --- Schema Management ---


async def delete_schema(ctx: ToolContext, *, schema_id: str, **kwargs) -> dict:
    """Delete a schema definition."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_schema", "running", f"Deleting schema {schema_id}")

    from ..store import Store
    try:
        ok = Store.instance().delete_schema(schema_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete schema: {e}"}
    if not ok:
        return {"error": "SCHEMA_NOT_FOUND", "message": f"Schema {schema_id} not found."}

    _emit_progress(ctx, "delete_schema", "complete", f"Schema {schema_id} deleted")
    return {"status": "ok", "schema_id": schema_id, "deleted": True}


async def add_schema_field(ctx: ToolContext, *, schema_id: str, field: dict, **kwargs) -> dict:
    """Add a field to an existing schema."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "add_schema_field", "running",
                   f"Adding field '{field.get('key', '?')}' to schema {schema_id}")

    from ..store import Store
    try:
        result = Store.instance().add_schema_field(schema_id, field)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to add field: {e}"}

    ctx.session.track_entity("schema", schema_id)
    ctx.session.save()
    _emit_progress(ctx, "add_schema_field", "complete",
                   f"Field '{field.get('key', '?')}' added to {schema_id}")
    return {"status": "ok", "schema": result}


async def delete_schema_field(ctx: ToolContext, *, schema_id: str,
                               field_key: str, **kwargs) -> dict:
    """Remove a field from a schema."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_schema_field", "running",
                   f"Removing field '{field_key}' from schema {schema_id}")

    from ..store import Store
    try:
        ok = Store.instance().delete_schema_field(schema_id, field_key)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete field: {e}"}
    if not ok:
        return {"error": "FIELD_NOT_FOUND",
                "message": f"Field '{field_key}' not found in schema {schema_id}."}

    _emit_progress(ctx, "delete_schema_field", "complete",
                   f"Field '{field_key}' removed from {schema_id}")
    return {"status": "ok", "schema_id": schema_id, "field_key": field_key, "deleted": True}


# --- Table Management ---


async def update_table(ctx: ToolContext, *, table_id: str, patch: dict, **kwargs) -> dict:
    """Update table metadata (name, schemaId, dbTargetId)."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "update_table", "running", f"Updating table {table_id}")

    from ..store import Store
    try:
        tbl = Store.instance().update_table(table_id, patch)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to update table: {e}"}
    if not tbl:
        return {"error": "TABLE_NOT_FOUND", "message": f"Table {table_id} not found."}

    ctx.session.save()
    _emit_progress(ctx, "update_table", "complete", f"Table {table_id} updated")
    return {"status": "ok", "table": tbl}


async def delete_table(ctx: ToolContext, *, table_id: str,
                        drop_physical: bool = False, **kwargs) -> dict:
    """Delete a table. Set drop_physical=true to also DROP the database table."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_table", "running", f"Deleting table {table_id}")

    from ..store import Store
    store = Store.instance()
    tbl = store.get_table(table_id)
    if not tbl:
        return {"error": "TABLE_NOT_FOUND", "message": f"Table {table_id} not found."}

    # Drop physical table if requested and it was migrated
    if drop_physical and tbl.get("status") == "migrated":
        try:
            from ..routers.tables import migrate as _migrate_fn
            db_target_id = tbl.get("dbTargetId") or store.get_default_db_target()
            target = store.get_db_target(db_target_id) if db_target_id else None
            if target and target.get("conn"):
                from sqlalchemy import create_engine, text
                import re as _re_drop
                engine = create_engine(target["conn"])
                table_name = tbl.get("name", "")
                # Sanitize table name to prevent SQL injection
                if not table_name or not _re_drop.match(r'^[a-zA-Z0-9_]+$', table_name):
                    logger.warning("drop_physical_table_rejected: unsafe name %r", table_name)
                else:
                    with engine.connect() as conn:
                        conn.execute(text(f'DROP TABLE IF EXISTS "neuract"."{table_name}"'))
                        conn.commit()
        except Exception as e:
            logger.warning("drop_physical_table_failed: %s", e)

    try:
        ok = store.delete_table(table_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete table: {e}"}
    if not ok:
        return {"error": "DELETE_FAILED", "message": f"Could not delete table {table_id}."}

    _emit_progress(ctx, "delete_table", "complete", f"Table {table_id} deleted")
    return {"status": "ok", "table_id": table_id, "deleted": True,
            "physical_dropped": drop_physical}


async def bind_device_to_table(ctx: ToolContext, *, table_id: str,
                                device_id: str, **kwargs) -> dict:
    """Bind a device to a table for data collection."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "bind_device_to_table", "running",
                   f"Binding device {device_id} to table {table_id}")

    from ..store import Store
    store = Store.instance()
    if not store.get_table(table_id):
        return {"error": "TABLE_NOT_FOUND", "message": f"Table {table_id} not found."}
    if not store.get_device(device_id):
        return {"error": "DEVICE_NOT_FOUND", "message": f"Device {device_id} not found."}

    try:
        store.set_table_device_binding(table_id, device_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to bind device: {e}"}

    ctx.session.save()
    _emit_progress(ctx, "bind_device_to_table", "complete",
                   f"Device {device_id} bound to table {table_id}")
    return {"status": "ok", "table_id": table_id, "device_id": device_id}


async def unbind_device_from_table(ctx: ToolContext, *, table_id: str, **kwargs) -> dict:
    """Unbind the device from a table."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "unbind_device_from_table", "running",
                   f"Unbinding device from table {table_id}")

    from ..store import Store
    store = Store.instance()
    if not store.get_table(table_id):
        return {"error": "TABLE_NOT_FOUND", "message": f"Table {table_id} not found."}

    try:
        store.set_table_device_binding(table_id, None)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to unbind device: {e}"}

    _emit_progress(ctx, "unbind_device_from_table", "complete",
                   f"Device unbound from table {table_id}")
    return {"status": "ok", "table_id": table_id, "unbound": True}


# --- Mapping Management ---


async def delete_mapping_row(ctx: ToolContext, *, table_id: str,
                              field_key: str, **kwargs) -> dict:
    """Delete a single mapping row from a table."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)

    from ..store import Store
    try:
        result = Store.instance().delete_mapping_row(table_id, field_key)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete mapping row: {e}"}

    return {"status": "ok", "table_id": table_id, "field_key": field_key, "deleted": True}


async def copy_mappings(ctx: ToolContext, *, src_table_id: str,
                         dst_table_id: str, **kwargs) -> dict:
    """Copy all mappings from one table to another."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "copy_mappings", "running",
                   f"Copying mappings {src_table_id} → {dst_table_id}")

    from ..store import Store
    try:
        mapping = Store.instance().copy_mapping(src_table_id, dst_table_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to copy mappings: {e}"}

    _emit_progress(ctx, "copy_mappings", "complete",
                   f"Mappings copied to {dst_table_id}")
    return {"status": "ok", "src_table_id": src_table_id,
            "dst_table_id": dst_table_id, "mapping": mapping}


# --- Job Management ---


async def stop_job(ctx: ToolContext, *, job_id: str, **kwargs) -> dict:
    """Stop a running data collection job."""
    _emit_progress(ctx, "stop_job", "running", f"Stopping job {job_id}")
    loop = asyncio.get_running_loop()

    def _stop():
        from ..routers.jobs import _job_threads, _job_stops
        from ..store import Store
        from ...metrics import metrics as METRICS
        store = Store.instance()

        job = store.get_job(job_id)
        if not job:
            return {"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

        ev = _job_stops.get(job_id)
        thr = _job_threads.get(job_id)
        if ev:
            ev.set()
        if thr and thr.is_alive():
            thr.join(timeout=2)
        try:
            METRICS.get_job(job_id).end_run()
        except Exception:
            pass
        store.set_job_status(job_id, "stopped")
        return {"status": "ok", "job_id": job_id, "stopped": True}

    try:
        result = await loop.run_in_executor(None, _stop)
    except Exception as e:
        return {"error": "STOP_FAILED", "message": str(e)}

    _emit_progress(ctx, "stop_job", "complete", f"Job {job_id} stopped")
    return result


async def pause_job(ctx: ToolContext, *, job_id: str, **kwargs) -> dict:
    """Pause a running data collection job."""
    _emit_progress(ctx, "pause_job", "running", f"Pausing job {job_id}")
    loop = asyncio.get_running_loop()

    def _pause():
        from ..routers.jobs import _job_threads, _job_stops
        from ..store import Store
        from ...metrics import metrics as METRICS
        store = Store.instance()

        job = store.get_job(job_id)
        if not job:
            return {"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

        ev = _job_stops.get(job_id)
        thr = _job_threads.get(job_id)
        if ev:
            ev.set()
        if thr and thr.is_alive():
            thr.join(timeout=2)
        try:
            METRICS.get_job(job_id).end_run()
        except Exception:
            pass
        store.set_job_status(job_id, "paused")
        return {"status": "ok", "job_id": job_id, "paused": True}

    try:
        result = await loop.run_in_executor(None, _pause)
    except Exception as e:
        return {"error": "PAUSE_FAILED", "message": str(e)}

    _emit_progress(ctx, "pause_job", "complete", f"Job {job_id} paused")
    return result


async def delete_job(ctx: ToolContext, *, job_id: str, **kwargs) -> dict:
    """Delete a job. Stops it first if running."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_job", "running", f"Deleting job {job_id}")
    loop = asyncio.get_running_loop()

    def _delete():
        from ..routers.jobs import _job_threads, _job_stops
        from ..store import Store
        from ...metrics import metrics as METRICS
        store = Store.instance()

        job = store.get_job(job_id)
        if not job:
            return {"error": "JOB_NOT_FOUND", "message": f"Job {job_id} not found."}

        # Stop if running
        ev = _job_stops.get(job_id)
        thr = _job_threads.get(job_id)
        if ev:
            ev.set()
        if thr and thr.is_alive():
            thr.join(timeout=2)
        try:
            METRICS.get_job(job_id).end_run()
        except Exception:
            pass

        ok = store.delete_job(job_id)
        _job_threads.pop(job_id, None)
        _job_stops.pop(job_id, None)
        try:
            METRICS.jobs.pop(job_id, None)
        except Exception:
            pass

        if not ok:
            return {"error": "DELETE_FAILED", "message": f"Could not delete job {job_id}."}
        return {"status": "ok", "job_id": job_id, "deleted": True}

    try:
        result = await loop.run_in_executor(None, _delete)
    except Exception as e:
        return {"error": "DELETE_FAILED", "message": str(e)}

    _emit_progress(ctx, "delete_job", "complete", f"Job {job_id} deleted")
    return result


# --- Storage / DB Target Management ---


async def add_db_target(ctx: ToolContext, *, provider: str, conn: str, **kwargs) -> dict:
    """Add a database storage target (postgres, sqlite, sqlserver, mysql).
    WARNING: Only use when the user explicitly provides a connection string.
    The system already has a default target — do NOT create targets with made-up credentials."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)

    from ..store import Store
    store = Store.instance()

    # Guard: if a default target already exists, warn the AI and return it instead
    default_id = store.get_default_db_target()
    if default_id:
        existing = store.get_db_target(default_id)
        if existing:
            return {
                "status": "skipped",
                "message": f"A default DB target already exists (id={default_id}). "
                           f"Use this target instead of creating a new one. "
                           f"Only create a new target if the user explicitly asked for a different database.",
                "existing_target": existing,
            }

    _emit_progress(ctx, "add_db_target", "running", f"Adding DB target ({provider})")

    try:
        target = store.add_db_target({"provider": provider, "conn": conn})
    except Exception as e:
        return {"error": str(e), "message": f"Failed to add DB target: {e}"}

    ctx.session.track_entity("db_target", target.get("id"))
    ctx.session.save()
    _emit_progress(ctx, "add_db_target", "complete", f"DB target → {target.get('id')}")
    return {"status": "ok", "target": target}


async def update_db_target(ctx: ToolContext, *, target_id: str, patch: dict, **kwargs) -> dict:
    """Update a database target's configuration."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "update_db_target", "running", f"Updating DB target {target_id}")

    from ..store import Store
    store = Store.instance()
    target = store.get_db_target(target_id)
    if not target:
        return {"error": "TARGET_NOT_FOUND", "message": f"DB target {target_id} not found."}

    allowed = {k: v for k, v in patch.items() if k in ("provider", "conn", "status", "lastMsg")}
    if not allowed:
        return {"error": "NO_ALLOWED_FIELDS", "message": "No valid fields to update. Allowed: provider, conn, status, lastMsg."}
    target.update(allowed)
    from .. import appdb
    try:
        appdb.save_target(target)
    except Exception as e:
        return {"error": "SAVE_FAILED", "message": f"Failed to persist DB target: {e}"}
    _emit_progress(ctx, "update_db_target", "complete", f"DB target {target_id} updated")
    return {"status": "ok", "target_id": target_id, "updated": list(allowed.keys())}


async def delete_db_target(ctx: ToolContext, *, target_id: str,
                            force: bool = False, **kwargs) -> dict:
    """Delete a database target. Fails if it is the default or in use (unless force=true)."""
    _require_manage_state(ctx)
    _maybe_ensure_applying(ctx)
    _emit_progress(ctx, "delete_db_target", "running", f"Deleting DB target {target_id}")

    from ..store import Store
    store = Store.instance()

    target = store.get_db_target(target_id)
    if not target:
        return {"error": "TARGET_NOT_FOUND", "message": f"DB target {target_id} not found."}

    default_id = store.get_default_db_target()
    if target_id == default_id and not force:
        return {"error": "TARGET_IS_DEFAULT",
                "message": "Cannot delete the default DB target. Use force=true or change default first."}

    try:
        from ..appdb import count_tables_referencing_target, delete_target as appdb_delete_target
        ref_count = count_tables_referencing_target(target_id)
        if ref_count > 0 and not force:
            return {"error": "TARGET_IN_USE",
                    "message": f"DB target is used by {ref_count} table(s). Use force=true to delete anyway."}
        store._db_targets.pop(target_id, None)
        appdb_delete_target(target_id)
    except ImportError:
        store._db_targets.pop(target_id, None)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to delete DB target: {e}"}

    _emit_progress(ctx, "delete_db_target", "complete", f"DB target {target_id} deleted")
    return {"status": "ok", "target_id": target_id, "deleted": True}


async def set_default_db_target(ctx: ToolContext, *, target_id: str, **kwargs) -> dict:
    """Set the default database target for new tables."""
    from .session import SessionState
    _require_state(ctx, SessionState.APPROVED, SessionState.APPLYING)
    _ensure_applying(ctx)
    _emit_progress(ctx, "set_default_db_target", "running",
                   f"Setting default DB target to {target_id}")

    from ..store import Store
    store = Store.instance()
    if not store.get_db_target(target_id):
        return {"error": "TARGET_NOT_FOUND", "message": f"DB target {target_id} not found."}

    try:
        store.set_default_db_target(target_id)
    except Exception as e:
        return {"error": str(e), "message": f"Failed to set default: {e}"}

    ctx.session.save()
    _emit_progress(ctx, "set_default_db_target", "complete",
                   f"Default DB target set to {target_id}")
    return {"status": "ok", "target_id": target_id, "is_default": True}


# ---------------------------------------------------------------------------
# Phase 1I — Anomaly detection
# ---------------------------------------------------------------------------

async def run_anomaly_check(ctx: ToolContext, *, table_id: str, model: str, **kwargs) -> dict:
    """Run Layer 2 anomaly detection on live device readings.

    Uses a neural network autoencoder trained on synthetic physics-aware data
    for the specified MFM model. Catches subtle issues that pass Layer 1
    rule-based checks: reversed CT wiring, wrong byte order, misidentified model.
    """
    from functools import partial

    try:
        from .validation.anomaly import AnomalyDetector
    except ImportError:
        return {"error": "ANOMALY_MODULE_UNAVAILABLE",
                "message": "Anomaly detection module not installed."}

    try:
        from .mfm_kb.manager import KBManager
    except ImportError:
        return {"error": "KB_MODULE_UNAVAILABLE",
                "message": "MFM Knowledge Base module not installed."}

    # Look up KB entry
    mgr = KBManager.instance()
    kb_entry = mgr.get_entry(model)
    if kb_entry is None:
        return {"error": "MODEL_NOT_FOUND", "model": model,
                "message": f"Model '{model}' not found in MFM Knowledge Base."}

    kb_registers = [r.model_dump() for r in kb_entry.registers]

    # Read live values
    try:
        from ..routers.jobs import _read_mapping_values
    except ImportError:
        return {"error": "IMPORT_FAILED",
                "message": "Cannot import live value reader."}

    loop = asyncio.get_running_loop()
    try:
        values = await loop.run_in_executor(
            None, partial(_read_mapping_values, table_id)
        )
    except RuntimeError as e:
        msg = str(e)
        if "DEVICE_NOT_BOUND" in msg:
            return {"error": "DEVICE_NOT_BOUND", "table_id": table_id,
                    "message": "Table has no device binding."}
        if "DEVICE_NOT_FOUND" in msg:
            return {"error": "DEVICE_NOT_FOUND", "table_id": table_id,
                    "message": "Bound device not found."}
        return {"error": "READ_FAILED", "table_id": table_id, "message": msg}
    except Exception as e:
        return {"error": "READ_FAILED", "table_id": table_id, "message": str(e)}

    if not isinstance(values, dict) or not values:
        return {"error": "NO_VALUES", "table_id": table_id,
                "message": "No values returned from device."}

    # Run anomaly detection (may trigger cold-start training on first call)
    try:
        detector = AnomalyDetector.instance()
        result = detector.check(values, model, kb_registers)
    except Exception as e:
        logger.exception("anomaly_check_failed")
        return {"error": "ANOMALY_CHECK_FAILED", "message": str(e)}

    return {
        "table_id": table_id,
        "model": model,
        "values": values,
        "field_count": len(values),
        "anomaly": result.to_dict(),
    }


async def retrain_anomaly_model(ctx: ToolContext, *, model: str, **kwargs) -> dict:
    """Retrain anomaly detection model using collected real data + synthetic data."""
    loop = asyncio.get_running_loop()

    try:
        from .validation.anomaly import AnomalyDetector, _sanitize_key
        from .mfm_kb.manager import KBManager
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Anomaly or KB module unavailable."}

    key = _sanitize_key(model)
    mgr = KBManager.instance()
    kb_entry = mgr.get_entry(model)
    if kb_entry is None:
        return {"error": "MODEL_NOT_FOUND", "model": model,
                "message": f"No KB entry for model '{model}'."}

    regs = kb_entry.registers
    kb_regs = [r.model_dump() if hasattr(r, "model_dump") else r for r in regs]

    detector = AnomalyDetector.instance()

    def _retrain():
        return detector.retrain_model(key, kb_regs)

    try:
        stats = await loop.run_in_executor(None, _retrain)
    except Exception as e:
        return {"error": "RETRAIN_FAILED", "model": model, "message": str(e)}

    return {"status": "ok", **stats}


# ---------------------------------------------------------------------------
# Phase 3A — Predictive Runtime (Layer 3)
# ---------------------------------------------------------------------------

async def read_prediction_status(
    ctx: ToolContext, *, device_id: str = "", **kwargs,
) -> dict:
    """Read Layer 3 prediction status for a device or all devices.

    Returns baseline status, current z-score deviations, active alerts,
    and trend summary.  If *device_id* is empty, returns all monitored devices.
    """
    try:
        from .prediction.monitor import PredictionManager
    except ImportError:
        return {
            "error": "PREDICTION_MODULE_UNAVAILABLE",
            "message": "Prediction module not installed.",
        }

    manager = PredictionManager.instance()

    if device_id:
        status = manager.get_status(device_id)
        if status is None:
            return {
                "error": "DEVICE_NOT_MONITORED",
                "device_id": device_id,
                "message": (
                    f"Device '{device_id}' is not being monitored by Layer 3. "
                    "Ensure a job is running for this device."
                ),
            }
        return {"device_id": device_id, "prediction": status.to_dict()}
    else:
        statuses = manager.get_all_statuses()
        return {
            "device_count": len(statuses),
            "devices": [s.to_dict() for s in statuses],
        }


# ---------------------------------------------------------------------------
# Phase 3B — Temporal model tools
# ---------------------------------------------------------------------------

async def read_temporal_status(
    ctx: ToolContext, *, device_id: str = "", **kwargs,
) -> dict:
    """Read temporal (TCN) model status for a device or all devices.

    Returns model status (accumulating/active/retraining), load classification,
    samples collected, anomaly scores, and model version.
    """
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        return {"error": "TEMPORAL_MODULE_UNAVAILABLE"}

    manager = TemporalManager.instance()

    if device_id:
        status = manager.get_status(device_id)
        if status is None:
            return {"error": "DEVICE_NOT_MONITORED", "device_id": device_id}
        return {"device_id": device_id, "temporal": status.to_dict()}
    else:
        statuses = manager.get_all_statuses()
        return {
            "device_count": len(statuses),
            "devices": [s.to_dict() for s in statuses],
        }


async def train_temporal_model(
    ctx: ToolContext, *, device_id: str, **kwargs,
) -> dict:
    """Manually trigger temporal model training for a device.

    The device must have accumulated enough baseline data (default 3 days).
    """
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        return {"error": "TEMPORAL_MODULE_UNAVAILABLE"}

    manager = TemporalManager.instance()
    state = manager._devices.get(device_id)
    if state is None:
        return {"error": "DEVICE_NOT_FOUND", "device_id": device_id}

    if state.status == "active":
        return {"error": "ALREADY_TRAINED", "device_id": device_id, "version": state.model_version}

    if len(state.baseline_buffer) < 100:
        return {
            "error": "INSUFFICIENT_DATA",
            "samples": len(state.baseline_buffer),
            "needed": state.samples_needed,
        }

    # Force training even if below default threshold
    state.samples_needed = min(state.samples_needed, len(state.baseline_buffer))
    manager._trigger_training(state)

    return {
        "device_id": device_id,
        "status": state.status,
        "load_class": state.load_class.value,
        "model_version": state.model_version,
    }


async def retrain_temporal_model(
    ctx: ToolContext, *, device_id: str, **kwargs,
) -> dict:
    """Force retrain a device's temporal model with current data."""
    try:
        from .prediction.temporal_monitor import TemporalManager
    except ImportError:
        return {"error": "TEMPORAL_MODULE_UNAVAILABLE"}

    manager = TemporalManager.instance()
    return manager.trigger_retrain(device_id)


# ---------------------------------------------------------------------------
# Phase 3D — Advanced: Topology, Cloud Fallback, Marketplace, Multi-Session
# ---------------------------------------------------------------------------

async def infer_topology(
    ctx: ToolContext, *, gateway_id: str, snapshots: int = 5, **kwargs,
) -> dict:
    """Infer SLD topology (incomer/feeder/load hierarchy) from power flow patterns."""
    try:
        from .topology.inference import TopologyInferenceEngine
        from .topology.naming import suggest_names
    except ImportError:
        return {"error": "TOPOLOGY_MODULE_UNAVAILABLE"}

    loop = asyncio.get_running_loop()

    # Gather devices on this gateway with live readings
    try:
        from ..store import Store
        from ..routers.jobs import _read_mapping_values
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Store or jobs module unavailable."}

    store = Store.instance()
    devices_data = []
    for dev in store.list_devices():
        if dev.get("gatewayId") != gateway_id and dev.get("gateway_id") != gateway_id:
            continue
        dev_id = dev.get("id")
        # Find tables mapped to this device and read values
        for tbl in store.list_tables():
            mapping = store.get_mapping(tbl.get("id", ""))
            if mapping and mapping.get("deviceId") == dev_id:
                try:
                    values = await loop.run_in_executor(
                        None, lambda tid=tbl["id"]: _read_mapping_values(tid),
                    )
                    devices_data.append({
                        "device_id": dev_id,
                        "device_name": dev.get("name", dev_id),
                        "gateway_id": gateway_id,
                        "readings": values,
                    })
                except Exception:
                    pass
                break  # one table per device is enough

    if len(devices_data) < 2:
        return {
            "error": "INSUFFICIENT_DEVICES",
            "message": f"Need at least 2 devices on gateway '{gateway_id}', found {len(devices_data)}.",
        }

    engine = TopologyInferenceEngine()
    graph = engine.infer(devices_data, snapshots=snapshots)
    names = suggest_names(graph)
    graph_dict = graph.to_dict()
    graph_dict["suggested_names"] = names

    # Persist topology to DB
    try:
        from ..appdb import _conn
        from sqlalchemy import text
        with _conn() as c:
            for dev_id, node in graph.nodes.items():
                c.execute(text(
                    "INSERT OR REPLACE INTO app_device_topology "
                    "(device_id, parent_device_id, hierarchy_level, load_pattern, "
                    "confidence, gateway_id, inferred_at, snapshot_count) "
                    "VALUES (:did, :pid, :hl, :lp, :conf, :gid, :at, :sc)"
                ), {
                    "did": dev_id, "pid": node.parent_id,
                    "hl": node.level.value, "lp": node.load_pattern.value,
                    "conf": node.confidence, "gid": gateway_id,
                    "at": graph.inferred_at, "sc": snapshots,
                })
    except Exception as e:
        logger.warning("topology_persist_failed: %s", e)

    return graph_dict


async def read_topology(
    ctx: ToolContext, *, gateway_id: str = "", **kwargs,
) -> dict:
    """Read inferred SLD topology. Returns hierarchy, load patterns, confidence."""
    try:
        from ..appdb import _conn
        from sqlalchemy import text
    except ImportError:
        return {"error": "IMPORT_FAILED"}

    with _conn() as c:
        if gateway_id:
            rows = c.execute(text(
                "SELECT * FROM app_device_topology WHERE gateway_id = :gid"
            ), {"gid": gateway_id}).mappings().all()
        else:
            rows = c.execute(text(
                "SELECT * FROM app_device_topology"
            )).mappings().all()

    if not rows:
        return {"device_count": 0, "devices": [], "message": "No topology inferred yet."}

    devices = [dict(r) for r in rows]
    return {"device_count": len(devices), "devices": devices}


async def cloud_identify(
    ctx: ToolContext, *, ip: str = "", port: int = 502, unit_id: int = 1,
    register_data: dict = None, local_candidates: list = None, **kwargs,
) -> dict:
    """Escalate uncertain device identification to cloud model.

    Only use when local identification confidence < 70%.
    Requires CLOUD_ENABLED=true in environment.
    """
    try:
        from .cloud_fallback import CloudFallbackClient, get_cloud_config
    except ImportError:
        return {"error": "CLOUD_MODULE_UNAVAILABLE"}

    config = get_cloud_config()
    client = CloudFallbackClient(config)

    if not client.is_available():
        return {
            "error": "CLOUD_UNAVAILABLE",
            "message": "Cloud fallback not configured (set CLOUD_ENABLED=true) or rate limit reached.",
            "remaining_calls": client.remaining_calls(),
        }

    # Get KB model list for context
    try:
        from .mfm_kb.manager import KBManager
        kb_models = [e.model for e in KBManager.instance().list_models()]
    except Exception:
        kb_models = []

    result = await client.identify_device(
        register_data=register_data or {},
        candidates=local_candidates or [],
        kb_models=kb_models,
    )
    return {
        "cloud_result": result,
        "remaining_calls": client.remaining_calls(),
    }


async def marketplace_search(
    ctx: ToolContext, *, query: str = "", tags: list = None,
    min_rating: float = 0.0, **kwargs,
) -> dict:
    """Search the skill marketplace for reusable procedures."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        return {"error": "MARKETPLACE_MODULE_UNAVAILABLE"}

    mp = SkillMarketplace.instance()
    results = mp.search(query=query, tags=tags, min_rating=min_rating)
    return {
        "result_count": len(results),
        "skills": [e.to_dict() for e in results],
    }


async def marketplace_publish(
    ctx: ToolContext, *, skill_name: str, description: str = "",
    tags: list = None, **kwargs,
) -> dict:
    """Publish a learned skill to the marketplace."""
    try:
        from .marketplace import SkillMarketplace
    except ImportError:
        return {"error": "MARKETPLACE_MODULE_UNAVAILABLE"}

    mp = SkillMarketplace.instance()
    content = {
        "description": description,
        "tags": tags or [],
        "source_session": ctx.session.session_id,
    }
    entry = mp.publish(skill_name, content)
    return {"status": "ok", "entry": entry.to_dict()}


async def create_session_group(
    ctx: ToolContext, *, name: str, scopes: list = None, **kwargs,
) -> dict:
    """Create a multi-session group for configuring a large site in parallel."""
    try:
        from .multi_session import SessionCoordinator
    except ImportError:
        return {"error": "MULTI_SESSION_MODULE_UNAVAILABLE"}

    coord = SessionCoordinator.instance()
    group = coord.create_group(name)

    # Auto-join current session with first scope
    session_scope = (scopes or ["default"])[0] if scopes else "default"
    coord.add_session(group.group_id, ctx.session.session_id, session_scope)

    return {
        "status": "ok",
        "group": group.to_dict(),
        "planned_scopes": scopes or [],
    }


# ---------------------------------------------------------------------------
# Phase 1D — Diagnostic helpers
# ---------------------------------------------------------------------------

def _decode_registers(registers: list[int], data_type: str) -> list:
    """Decode raw u16 Modbus register values based on data_type (big-endian)."""
    if data_type == "uint16":
        return registers
    elif data_type == "int16":
        return [struct.unpack('>h', struct.pack('>H', r))[0] for r in registers]
    elif data_type == "float32":
        if len(registers) % 2 != 0:
            return registers  # can't decode odd count
        return [
            round(struct.unpack('>f', struct.pack('>HH', registers[i], registers[i + 1]))[0], 4)
            for i in range(0, len(registers), 2)
        ]
    elif data_type == "float64":
        if len(registers) % 4 != 0:
            return registers
        return [
            round(struct.unpack('>d', struct.pack('>HHHH', *registers[i:i + 4]))[0], 6)
            for i in range(0, len(registers), 4)
        ]
    elif data_type == "uint32":
        if len(registers) % 2 != 0:
            return registers
        return [
            struct.unpack('>I', struct.pack('>HH', registers[i], registers[i + 1]))[0]
            for i in range(0, len(registers), 2)
        ]
    elif data_type == "int32":
        if len(registers) % 2 != 0:
            return registers
        return [
            struct.unpack('>i', struct.pack('>HH', registers[i], registers[i + 1]))[0]
            for i in range(0, len(registers), 2)
        ]
    return registers


# ---------------------------------------------------------------------------
# Phase 1D — Diagnostic tools
# ---------------------------------------------------------------------------

async def read_raw_registers(ctx: ToolContext, **kwargs) -> dict:
    """Read raw Modbus TCP holding registers by IP (no pre-configured device needed)."""
    ip = kwargs.get("ip", "127.0.0.1")
    port = int(kwargs.get("port", 502))
    unit_id = int(kwargs.get("unit_id", 1))
    start_address = int(kwargs.get("start_address", 0))
    count = int(kwargs.get("count", 1))
    data_type = kwargs.get("data_type", "uint16")

    if count < 1 or count > 125:
        return {"error": "invalid_count", "message": "Count must be 1-125 (Modbus limit)."}

    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        return {"error": "pymodbus_missing", "message": "pymodbus is not installed."}

    loop = asyncio.get_running_loop()

    def _read():
        t0 = time.perf_counter()
        client = ModbusTcpClient(host=ip, port=port)
        if not client.connect():
            return {"error": "connect_failed", "message": f"Cannot connect to {ip}:{port}"}
        try:
            result = client.read_holding_registers(address=start_address, count=count, slave=unit_id)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if hasattr(result, 'isError') and result.isError():
                return {"error": "modbus_error", "message": str(result), "latency_ms": latency_ms}
            raw_values = list(result.registers)
            decoded = _decode_registers(raw_values, data_type)
            return {
                "ok": True,
                "raw_uint16": raw_values,
                "decoded": decoded,
                "data_type": data_type,
                "address_range": f"{start_address}-{start_address + count - 1}",
                "latency_ms": latency_ms,
            }
        finally:
            client.close()

    try:
        return await loop.run_in_executor(None, _read)
    except Exception as e:
        logger.exception("read_raw_registers failed")
        return {"error": "exception", "message": str(e)}


async def browse_opcua_nodes(ctx: ToolContext, **kwargs) -> dict:
    """Browse OPC UA node tree from an endpoint (no pre-configured device needed)."""
    endpoint = kwargs.get("endpoint", "opc.tcp://127.0.0.1:4840")
    node_id = kwargs.get("node_id", "i=85")
    max_results = int(kwargs.get("max_results", 50))

    try:
        from opcua import Client
    except ImportError:
        return {"error": "opcua_missing", "message": "opcua package is not installed."}

    loop = asyncio.get_running_loop()

    def _browse():
        client = Client(endpoint)
        t0 = time.perf_counter()
        client.connect()
        try:
            node = client.get_node(node_id)
            children = node.get_children()
            items = []
            for ch in children[:max_results]:
                try:
                    bn = ch.get_browse_name()
                    items.append({
                        "node_id": ch.nodeid.to_string(),
                        "browse_name": f"{bn.NamespaceIndex}:{bn.Name}",
                        "node_class": str(ch.get_node_class()),
                    })
                except Exception:
                    pass
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return {"ok": True, "items": items, "count": len(items), "latency_ms": latency_ms}
        finally:
            client.disconnect()

    try:
        return await loop.run_in_executor(None, _browse)
    except Exception as e:
        logger.exception("browse_opcua_nodes failed")
        return {"error": "exception", "message": str(e)}


async def ping_host(ctx: ToolContext, **kwargs) -> dict:
    """ICMP ping a host to check reachability."""
    host = kwargs.get("host")
    if not host:
        return {"error": "missing_param", "message": "host is required."}
    count = int(kwargs.get("count", 4))
    timeout_s = int(kwargs.get("timeout_ms", 800)) / 1000.0

    try:
        from icmplib import ping as icmp_ping
    except ImportError:
        return {"error": "icmplib_missing", "message": "icmplib is not installed."}

    loop = asyncio.get_running_loop()

    def _ping():
        result = icmp_ping(host, count=count, interval=0.2, timeout=timeout_s, privileged=False)
        return {
            "ok": True,
            "alive": result.is_alive,
            "loss_pct": round((1 - (result.packets_received / max(1, result.packets_sent))) * 100, 1),
            "min_ms": round(result.min_rtt, 2),
            "avg_ms": round(result.avg_rtt, 2),
            "max_ms": round(result.max_rtt, 2),
        }

    try:
        return await loop.run_in_executor(None, _ping)
    except Exception as e:
        logger.exception("ping_host failed")
        return {"error": "exception", "message": str(e)}


async def scan_port(ctx: ToolContext, **kwargs) -> dict:
    """TCP connect test to check if a port is open."""
    host = kwargs.get("host")
    port = kwargs.get("port")
    if not host or port is None:
        return {"error": "missing_param", "message": "host and port are required."}
    port = int(port)
    timeout_s = int(kwargs.get("timeout_ms", 1000)) / 1000.0

    t0 = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_s,
        )
        writer.close()
        await writer.wait_closed()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "open": True, "latency_ms": latency_ms}
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "open": False, "status": "timeout", "latency_ms": latency_ms}
    except OSError as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "open": False, "status": "closed", "message": str(e), "latency_ms": latency_ms}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


async def query_db(ctx: ToolContext, **kwargs) -> dict:
    """Run a read-only SQL query against a LoggerFast database.

    Parameters
    ----------
    sql : str
        SELECT query to run.
    db : str, optional
        Which database to query:
        - "app" (default) — metadata DB (gateways, devices, schemas, tables, jobs)
        - "metrics" — loggerfast_metrics DB
        - a db_target ID (e.g. "db_1773214350018") — query logged data in a target DB
    """
    sql = (kwargs.get("sql") or "").strip()
    db = (kwargs.get("db") or "app").strip()
    if not sql:
        return {"error": "missing_param", "message": "sql is required."}

    # Strict read-only enforcement
    normalized = sql.upper().lstrip()
    if not normalized.startswith("SELECT"):
        return {"error": "write_not_allowed",
                "message": "Only SELECT queries are allowed."}

    _FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                  "TRUNCATE", "REPLACE", "ATTACH", "DETACH")
    for kw in _FORBIDDEN:
        if kw in normalized:
            return {"error": "write_not_allowed",
                    "message": f"Query contains forbidden keyword: {kw}"}

    loop = asyncio.get_running_loop()

    def _run():
        from sqlalchemy import text, create_engine as _ce

        # Resolve database URL
        if db == "app":
            from ..appdb import _engine
            engine = _engine()
        elif db == "metrics":
            import os
            url = os.environ.get("BENCH_DB_URL", "postgresql://postgres@localhost/loggerfast_metrics")
            engine = _ce(url, pool_pre_ping=True)
        elif db.startswith("db_"):
            # db_target ID — look up connection string from app_db_targets
            from ..appdb import _engine as _app_engine
            with _app_engine().connect() as c:
                row = c.execute(text(
                    "SELECT conn FROM app_db_targets WHERE id = :id"
                ), {"id": db}).mappings().first()
            if not row:
                return {"error": "DB_TARGET_NOT_FOUND", "message": f"No db_target with id '{db}'."}
            engine = _ce(row["conn"], pool_pre_ping=True)
        else:
            return {"error": "INVALID_DB", "message": f"Unknown db '{db}'. Use 'app', 'metrics', or a db_target ID."}

        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(r) for r in result.mappings().all()]
            max_rows = 200
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            return {
                "ok": True,
                "db": db,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
            }

    try:
        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.exception("query_db failed")
        return {"error": "exception", "message": str(e)}


# ---------------------------------------------------------------------------
# Phase 2B — Discovery tools
# ---------------------------------------------------------------------------

async def scan_subnet(ctx: ToolContext, **kwargs) -> dict:
    """Ping sweep + port scan a subnet to find alive hosts with open ports."""
    subnet = kwargs.get("subnet")
    if not subnet:
        return {"error": "missing_param", "message": "subnet required (CIDR, e.g. '10.10.1.0/24')."}
    ports = kwargs.get("ports", [502, 4840])
    if isinstance(ports, str):
        ports = [int(p.strip()) for p in ports.split(",")]
    timeout_ms = int(kwargs.get("timeout_ms", 800))
    max_hosts = int(kwargs.get("max_hosts", 254))

    try:
        from .discovery.scanner import scan_subnet_impl
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Discovery module not available."}

    try:
        hosts = await scan_subnet_impl(subnet, ports=ports, timeout_ms=timeout_ms, max_hosts=max_hosts)
        alive = [h for h in hosts if h.alive]
        with_ports = [h for h in alive if any(p.open for p in h.ports)]
        return {
            "ok": True,
            "subnet": subnet,
            "hosts_scanned": len(hosts),
            "hosts_alive": len(alive),
            "hosts_with_open_ports": len(with_ports),
            "hosts": [h.to_dict() for h in alive],
        }
    except Exception as e:
        logger.exception("scan_subnet failed")
        return {"error": "exception", "message": str(e)}


async def enumerate_unit_ids(ctx: ToolContext, **kwargs) -> dict:
    """Modbus TCP: find which unit IDs respond at an IP."""
    ip = kwargs.get("ip")
    if not ip:
        return {"error": "missing_param", "message": "ip required."}
    port = int(kwargs.get("port", 502))
    start = int(kwargs.get("start", 1))
    end = int(kwargs.get("end", 10))
    probe_address = int(kwargs.get("probe_address", 0))
    probe_count = int(kwargs.get("probe_count", 2))

    if end > 247:
        end = 247
    if end - start > 50:
        return {"error": "range_too_large", "message": "Max 50 unit IDs per call."}

    try:
        from .discovery.enumerator import enumerate_unit_ids_impl
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Discovery module not available."}

    try:
        units = await enumerate_unit_ids_impl(ip, port, start, end, probe_address, probe_count)
        return {
            "ok": True,
            "ip": ip, "port": port,
            "range_scanned": f"{start}-{end}",
            "responding_units": [
                {"unit_id": u.unit_id, "raw_values": u.raw_values, "latency_ms": u.latency_ms}
                for u in units
            ],
            "count": len(units),
        }
    except Exception as e:
        logger.exception("enumerate_unit_ids failed")
        return {"error": "exception", "message": str(e)}


async def identify_device(ctx: ToolContext, **kwargs) -> dict:
    """Identify a Modbus device by fingerprinting against the MFM Knowledge Base."""
    ip = kwargs.get("ip")
    if not ip:
        return {"error": "missing_param", "message": "ip required."}
    port = int(kwargs.get("port", 502))
    unit_id = int(kwargs.get("unit_id", 1))

    try:
        from .discovery.fingerprint import identify_device_impl
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Discovery module not available."}

    try:
        result = await identify_device_impl(ip, port, unit_id)
        result_dict = {"ok": True, **result.to_dict()}
        # Suggest cloud fallback for low-confidence identifications
        if result.best_match and result.best_match.score < 0.7:
            try:
                from .cloud_fallback import get_cloud_config
                cfg = get_cloud_config()
                result_dict["cloud_fallback_available"] = cfg.enabled
                if cfg.enabled:
                    result_dict["suggestion"] = (
                        "Confidence is below 70%. Consider using cloud_identify for disambiguation."
                    )
            except Exception:
                result_dict["cloud_fallback_available"] = False
        return result_dict
    except Exception as e:
        logger.exception("identify_device failed")
        return {"error": "exception", "message": str(e)}


async def discover_and_identify(ctx: ToolContext, **kwargs) -> dict:
    """Full discovery: scan subnet → enumerate unit IDs → identify each device."""
    subnet = kwargs.get("subnet")
    if not subnet:
        return {"error": "missing_param", "message": "subnet required."}
    ports = kwargs.get("ports", [502])
    unit_id_range = kwargs.get("unit_id_range", [1, 10])
    if isinstance(unit_id_range, list) and len(unit_id_range) == 2:
        uid_start, uid_end = int(unit_id_range[0]), int(unit_id_range[1])
    else:
        uid_start, uid_end = 1, 10
    max_total_reads = int(kwargs.get("max_total_reads", 2000))
    max_devices = int(kwargs.get("max_devices", 50))

    try:
        from .discovery.scanner import scan_subnet_impl
        from .discovery.enumerator import enumerate_unit_ids_impl
        from .discovery.fingerprint import identify_device_impl
        from .discovery.types import ConfidenceLevel, DiscoveryReport
    except ImportError:
        return {"error": "IMPORT_FAILED", "message": "Discovery module not available."}

    try:
        # Phase 1: Subnet scan
        _emit_progress(ctx, "discover_and_identify", "running", "Scanning subnet...")
        hosts = await scan_subnet_impl(subnet, ports=ports)
        active = [h for h in hosts if h.alive and any(p.open for p in h.ports)]

        # Phase 2+3: Enumerate + Identify (with budget tracking)
        total_reads = 0
        all_ids = []
        budget_exhausted = False
        for i, host in enumerate(active):
            if budget_exhausted:
                break
            _emit_progress(ctx, "discover_and_identify", "running",
                           f"Probing host {i+1}/{len(active)}: {host.ip}")
            modbus_ports = [p.port for p in host.ports if p.open and p.port != 4840]
            for mp in modbus_ports:
                if budget_exhausted:
                    break
                units = await enumerate_unit_ids_impl(host.ip, mp, uid_start, uid_end)
                for unit in units:
                    if total_reads >= max_total_reads or len(all_ids) >= max_devices:
                        budget_exhausted = True
                        break
                    result = await identify_device_impl(host.ip, mp, unit.unit_id)
                    total_reads += result.register_reads
                    all_ids.append(result)

        identified = sum(
            1 for r in all_ids
            if r.best_match and r.best_match.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
        )

        report = DiscoveryReport(
            subnet=subnet,
            hosts_scanned=len(hosts),
            hosts_alive=sum(1 for h in hosts if h.alive),
            devices_found=len(all_ids),
            devices_identified=identified,
            hosts=[h for h in hosts if h.alive],
            identifications=all_ids,
        )
        result_dict = {"ok": True, **report.to_dict()}
        result_dict["total_register_reads"] = total_reads
        if budget_exhausted:
            result_dict["budget_exhausted"] = True
            result_dict["message"] = (
                f"Discovery stopped: register read budget ({max_total_reads}) "
                f"or device limit ({max_devices}) reached."
            )
        return result_dict
    except Exception as e:
        logger.exception("discover_and_identify failed")
        return {"error": "exception", "message": str(e)}


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    # --- Phase 1A: no-param tools ---
    {
        "type": "function",
        "function": {
            "name": "read_config",
            "description": (
                "Get a summary of the LoggerFast system configuration: "
                "counts of gateways, devices, schemas, tables, and jobs. "
                "Call this first to understand the current system state."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_gateway_list",
            "description": (
                "List all configured gateways with their id, name, host "
                "address, connection status, port numbers, and protocol hint. "
                "Gateways are network endpoints that connect to industrial devices."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_schema_list",
            "description": (
                "List all data schemas with their id, name, and field "
                "definitions. Each schema defines the structure (fields with "
                "key, type, unit) for data logging tables."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # --- Phase 1B: parameterized tools ---
    {
        "type": "function",
        "function": {
            "name": "read_table_mapping",
            "description": (
                "Get detailed info about a specific table: its schema binding, "
                "device binding, mapping rows (register-to-field assignments), "
                "and mapping health (Mapped/Unmapped/Partially Mapped). "
                "Use this to diagnose why a table is not collecting data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "The ID of the table to inspect.",
                    },
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_job_status",
            "description": (
                "Get job configuration and recent run history. "
                "If job_id is omitted, returns a summary list of all jobs. "
                "If job_id is provided, returns full details plus the last 20 "
                "runs with duration, row count, latency, and error percentage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The ID of the job to inspect. Omit to list all jobs.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_live_values",
            "description": (
                "Read CURRENT register values from a physical device. Performs real "
                "Modbus/OPC-UA I/O — may take seconds. Auto-runs Layer 1 validation "
                "and Layer 2 anomaly detection. Requires table to have device binding "
                "and valid mapping. Use sparingly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "The ID of the table whose mapped registers to read.",
                    },
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_device_status",
            "description": (
                "Get device connection status, latency, and error info. "
                "If device_id is omitted, returns a summary list of all devices. "
                "If device_id is provided, returns full details including protocol, "
                "connection parameters, and gateway binding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The ID of the device to inspect. Omit to list all devices.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_source_file",
            "description": (
                "Read a source file from the LoggerFast codebase (agent/plc_agent/) "
                "for debugging or code understanding. Supports .py, .md, .json, "
                ".yaml, .toml, .rs files. Paths relative to agent/plc_agent/ — "
                "e.g. 'api/store.py' or 'api/routers/jobs.py'. "
                "Blocked: .env, .db, vendor/, credentials."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path within agent/plc_agent/. "
                            "Example: 'api/routers/jobs.py'"
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    # --- Phase 1C: Write tools ---
    {
        "type": "function",
        "function": {
            "name": "propose_plan",
            "description": (
                "Stage a configuration plan for engineer approval. Call this IMMEDIATELY "
                "when the user asks to set up, create, or configure anything. The plan "
                "must have a 'steps' array listing what will be created. The system "
                "auto-computes the summary counts — do NOT provide a summary object."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "object",
                        "description": (
                            "Plan object with 'steps': [{action, params}...]. "
                            "action = tool name (create_gateway, create_device, etc). "
                            "params = arguments for that tool. "
                            "Do NOT include 'summary' — it is auto-computed from steps."
                        ),
                        "properties": {
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string", "description": "Tool name to execute."},
                                        "params": {"type": "object", "description": "Arguments for the tool."},
                                    },
                                    "required": ["action", "params"],
                                },
                                "description": "Ordered list of steps to execute after approval.",
                            },
                        },
                        "required": ["steps"],
                    },
                },
                "required": ["plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_gateway",
            "description": "Create a network gateway endpoint for industrial devices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Gateway name."},
                    "host": {"type": "string", "description": "IP address or hostname."},
                    "ports": {"type": "array", "items": {"type": "integer"}, "description": "Port numbers (e.g. [502])."},
                    "protocol_hint": {"type": "string", "description": "Protocol hint: modbus, opcua, mqtt."},
                },
                "required": ["name", "host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_device",
            "description": "Create a device (PLC/meter) behind a gateway.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Device name."},
                    "protocol": {"type": "string", "description": "Protocol: modbus, opcua, mqtt."},
                    "params": {"type": "object", "description": "Protocol-specific connection params."},
                    "gateway_id": {"type": "string", "description": "Gateway ID to bind to."},
                    "unit_id": {"type": "integer", "description": "Modbus unit ID."},
                    "port": {"type": "integer", "description": "Device port number."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test_device",
            "description": "Test connectivity to a configured device. Returns success, latency, and any error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID of the device to test."},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_schema",
            "description": "Create a field schema (template) defining the columns for data tables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Schema name."},
                    "fields": {
                        "type": "array",
                        "description": "Field definitions: [{key, type, unit?, scale?}].",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "type": {"type": "string", "description": "float32, uint16, int16, etc."},
                                "unit": {"type": "string"},
                                "scale": {"type": "number"},
                            },
                            "required": ["key", "type"],
                        },
                    },
                },
                "required": ["name", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_table",
            "description": "Create one or more data logging tables bound to a schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_id": {"type": "string", "description": "Schema ID to bind tables to."},
                    "names": {"type": "array", "items": {"type": "string"}, "description": "Table names to create."},
                    "db_target_id": {"type": "string", "description": "Database target ID. ALWAYS OMIT this — the system uses the default target automatically. Never create a new target."},
                    "device_id": {"type": "string", "description": "Device ID to bind all tables to."},
                },
                "required": ["schema_id", "names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_mappings",
            "description": "Bind register addresses to table fields (register-to-column mapping).",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "Table ID to apply mappings to."},
                    "device_id": {"type": "string", "description": "Device ID to bind."},
                    "rows_patch": {
                        "type": "object",
                        "description": "Mapping rows: {field_key: {protocol, address, dataType, encoding, scale}}.",
                    },
                },
                "required": ["table_id", "rows_patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "migrate_table",
            "description": "Create the physical database table with columns from the schema. Required before jobs can write data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "Table ID to migrate."},
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_job",
            "description": "Create a data collection job. Rejects tables without mappings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Job name."},
                    "tables": {"type": "array", "items": {"type": "string"}, "description": "Table IDs to poll."},
                    "type": {"type": "string", "description": "Job type: continuous or trigger.", "default": "continuous"},
                    "interval_ms": {"type": "integer", "description": "Polling interval in ms.", "default": 1000},
                },
                "required": ["name", "tables"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_job",
            "description": "Start a data collection job (begins polling devices and writing to tables).",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID to start."},
                },
                "required": ["job_id"],
            },
        },
    },
    # --- Phase 1H: Validation ---
    {
        "type": "function",
        "function": {
            "name": "validate_live_readings",
            "description": (
                "Read live values from a device and validate them against "
                "physical rules: voltage/current/PF/frequency range checks, "
                "plus cross-parameter consistency (V_LN*sqrt(3)~V_LL, "
                "P~V*I*PF*sqrt(3), S^2~P^2+Q^2, phase balance). "
                "Returns confidence score (High/Medium/Low) and per-check results. "
                "Use after configuring a device to verify readings are sane."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "The ID of the table whose device readings to validate.",
                    },
                },
                "required": ["table_id"],
            },
        },
    },
    # --- Phase 1I: Anomaly detection ---
    {
        "type": "function",
        "function": {
            "name": "run_anomaly_check",
            "description": (
                "Run Layer 2 anomaly detection on live device readings using a "
                "neural network autoencoder. Catches subtle issues that pass "
                "rule-based checks: reversed CT wiring, wrong byte order, "
                "misidentified meter model. Returns anomaly score (0-1) and "
                "per-parameter contribution showing which readings drive the "
                "anomaly. Thresholds: <0.2 normal, 0.2-0.5 moderate (investigate), "
                ">0.5 high (flag to engineer). "
                "Requires the device model to exist in the MFM Knowledge Base."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "The ID of the table whose device readings to check.",
                    },
                    "model": {
                        "type": "string",
                        "description": "MFM model name from the Knowledge Base (e.g. 'PM5110').",
                    },
                },
                "required": ["table_id", "model"],
            },
        },
    },
    # --- Phase 2C: Retrain ---
    {
        "type": "function",
        "function": {
            "name": "retrain_anomaly_model",
            "description": (
                "Retrain the anomaly detection autoencoder for a specific MFM model "
                "using collected real-world readings + fresh synthetic data. "
                "Real data gets 2x weight. Improves detection accuracy over time. "
                "Only useful after collecting readings from clean_run sessions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "MFM model name from the KB (e.g. 'PM5110').",
                    },
                },
                "required": ["model"],
            },
        },
    },
    # --- Phase 1D: Diagnostic tools ---
    {
        "type": "function",
        "function": {
            "name": "read_raw_registers",
            "description": (
                "Read raw Modbus TCP holding registers from a device by IP address. "
                "No pre-configured device needed. Supports decoding as uint16, int16, "
                "uint32, int32, float32, or float64 (big-endian). "
                "Use to investigate unknown devices or debug Modbus issues. Limit: 50 calls/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "Target device IP address."},
                    "port": {"type": "integer", "description": "Modbus TCP port (default 502).", "default": 502},
                    "unit_id": {"type": "integer", "description": "Modbus unit/slave ID (default 1).", "default": 1},
                    "start_address": {"type": "integer", "description": "Starting register address (0-based)."},
                    "count": {"type": "integer", "description": "Number of 16-bit registers to read (1-125).", "default": 1},
                    "data_type": {
                        "type": "string",
                        "description": "How to decode the raw registers.",
                        "enum": ["uint16", "int16", "uint32", "int32", "float32", "float64"],
                        "default": "uint16",
                    },
                },
                "required": ["ip", "start_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_opcua_nodes",
            "description": (
                "Browse OPC UA node tree from an endpoint URL. Returns child nodes "
                "with node IDs, browse names, and node classes. No pre-configured "
                "device needed. Start from root (i=85) and drill down."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "OPC UA endpoint (e.g. 'opc.tcp://192.168.1.100:4840')."},
                    "node_id": {"type": "string", "description": "Node ID to browse (default 'i=85' = Objects).", "default": "i=85"},
                    "max_results": {"type": "integer", "description": "Max children to return (default 50).", "default": 50},
                },
                "required": ["endpoint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping_host",
            "description": (
                "ICMP ping a host to check network reachability. Returns alive status, "
                "packet loss, and round-trip times. Use as first step for connectivity issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Hostname or IP to ping."},
                    "count": {"type": "integer", "description": "Ping packet count (default 4).", "default": 4},
                    "timeout_ms": {"type": "integer", "description": "Timeout per packet in ms (default 800).", "default": 800},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_port",
            "description": (
                "TCP connect test to check if a port is open. Returns open/closed status "
                "and latency. Common ports: 502 (Modbus), 4840 (OPC UA), 80 (HTTP)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Hostname or IP address."},
                    "port": {"type": "integer", "description": "TCP port number."},
                    "timeout_ms": {"type": "integer", "description": "Timeout in ms (default 1000).", "default": 1000},
                },
                "required": ["host", "port"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_db",
            "description": (
                "Run a read-only SQL SELECT query against any LoggerFast database. "
                "Use db='app' (default) for metadata (app_gateways, app_devices, app_schemas, "
                "app_schema_fields, app_device_tables, app_jobs, app_job_runs, app_notifications, "
                "app_db_targets, app_metrics_jobs_minute). "
                "Use db='metrics' for loggerfast_metrics. "
                "Use db=<db_target_id> (e.g. 'db_1773859505950') to query logged device data "
                "in a target database. IMPORTANT: Data tables are in the 'neuract' schema — "
                "always use neuract.<table_name> (e.g. 'SELECT * FROM neuract.mfm_001 LIMIT 5'). "
                "Only SELECT allowed — no mutations. Limit: 20 calls/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query to execute."},
                    "db": {"type": "string", "description": "Database to query: 'app' (default), 'metrics', or a db_target ID."},
                },
                "required": ["sql"],
            },
        },
    },
    # --- Phase 2B: Discovery tools ---
    {
        "type": "function",
        "function": {
            "name": "scan_subnet",
            "description": (
                "Ping sweep + port scan a subnet to find alive hosts with open industrial ports "
                "(Modbus 502, OPC UA 4840). First step in network discovery. Limit: 5/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet": {"type": "string", "description": "CIDR subnet (e.g. '10.10.1.0/24')."},
                    "ports": {"type": "array", "items": {"type": "integer"}, "description": "Ports to scan (default [502, 4840])."},
                    "timeout_ms": {"type": "integer", "description": "Timeout per host in ms (default 800)."},
                    "max_hosts": {"type": "integer", "description": "Max hosts to scan (default 254)."},
                },
                "required": ["subnet"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enumerate_unit_ids",
            "description": (
                "Modbus TCP: scan a range of unit IDs at an IP to find which ones respond. "
                "Single connection, probes each slave ID. Max 50 per call. Limit: 20/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "Target IP address."},
                    "port": {"type": "integer", "description": "Modbus TCP port (default 502)."},
                    "start": {"type": "integer", "description": "First unit ID (default 1)."},
                    "end": {"type": "integer", "description": "Last unit ID (default 10, max 247)."},
                    "probe_address": {"type": "integer", "description": "Register to probe (default 0)."},
                    "probe_count": {"type": "integer", "description": "Registers to read (default 2)."},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "identify_device",
            "description": (
                "Identify a Modbus device by fingerprinting against the MFM Knowledge Base. "
                "Reads key registers, matches against all KB entries. Returns ranked candidates "
                "with confidence (High/Medium/Low). Uses: ID register, existence pattern, "
                "value plausibility, byte order consistency. Limit: 50/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "Target IP."},
                    "port": {"type": "integer", "description": "Modbus TCP port (default 502)."},
                    "unit_id": {"type": "integer", "description": "Modbus unit/slave ID (default 1)."},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_and_identify",
            "description": (
                "Full network discovery: scan subnet → enumerate unit IDs → identify each device. "
                "One-shot tool that runs the complete discovery pipeline. Returns hosts, "
                "responding units, and identification results. Limit: 3/session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subnet": {"type": "string", "description": "CIDR subnet (e.g. '10.10.1.0/24')."},
                    "ports": {"type": "array", "items": {"type": "integer"}, "description": "Ports to scan (default [502])."},
                    "unit_id_range": {"type": "array", "items": {"type": "integer"}, "description": "Unit ID range [start, end] (default [1, 10])."},
                    "max_total_reads": {"type": "integer", "description": "Max total register reads before stopping (default 2000)."},
                    "max_devices": {"type": "integer", "description": "Max devices to identify before stopping (default 50)."},
                },
                "required": ["subnet"],
            },
        },
    },
    # --- Phase 3A: Prediction status ---
    {
        "type": "function",
        "function": {
            "name": "read_prediction_status",
            "description": (
                "Read Layer 3 predictive runtime status for a device. "
                "Returns baseline status (learning/active/alerting), current z-score "
                "deviations per parameter, active prediction alerts, and trend summary "
                "(direction, slope %/hr). If device_id is omitted, returns all monitored devices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Device ID to check. Omit for all devices.",
                    },
                },
                "required": [],
            },
        },
    },
    # --- Phase 3B: Temporal model tools ---
    {
        "type": "function",
        "function": {
            "name": "read_temporal_status",
            "description": (
                "Read temporal (TCN) model status for a device. "
                "Returns model status (accumulating/training/active/retraining), "
                "load classification (motor/lighting/ups/mixed), samples collected, "
                "anomaly scores, and model version. Omit device_id for all devices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Device ID to check. Omit for all devices.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "train_temporal_model",
            "description": (
                "Manually trigger temporal TCN model training for a device. "
                "Requires accumulated baseline data (default 3 days). "
                "Classifies the device load type and trains a per-device model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Device ID to train temporal model for.",
                    },
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrain_temporal_model",
            "description": (
                "Force retrain a device's temporal TCN model with current data. "
                "Backs up the old model and trains a new version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Device ID to retrain temporal model for.",
                    },
                },
                "required": ["device_id"],
            },
        },
    },
    # --- Phase 3D: Advanced tools ---
    {
        "type": "function",
        "function": {
            "name": "infer_topology",
            "description": (
                "Infer SLD topology (incomer/feeder/load hierarchy) from power flow "
                "patterns across devices on a gateway. Reads current power values and "
                "uses subset-sum matching to determine parent-child relationships."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_id": {"type": "string", "description": "Gateway ID to analyze."},
                    "snapshots": {"type": "integer", "description": "Snapshots to average (default 5)."},
                },
                "required": ["gateway_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_topology",
            "description": (
                "Read inferred SLD topology graph. Returns hierarchy levels, load "
                "patterns, confidence scores, and suggested names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_id": {"type": "string", "description": "Gateway ID. Omit for all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cloud_identify",
            "description": (
                "Escalate uncertain device identification to cloud model "
                "(Claude/Qwen API). Only use when local identification confidence "
                "< 70%. Requires CLOUD_ENABLED=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "Device IP address."},
                    "port": {"type": "integer", "description": "Port (default 502)."},
                    "unit_id": {"type": "integer", "description": "Modbus unit ID (default 1)."},
                    "register_data": {"type": "object", "description": "Raw register values."},
                    "local_candidates": {"type": "array", "description": "Candidates from identify_device."},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "marketplace_search",
            "description": (
                "Search the skill marketplace for reusable procedures. "
                "Filter by tags, minimum rating, or keyword query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags."},
                    "min_rating": {"type": "number", "description": "Minimum success rate (0-1)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "marketplace_publish",
            "description": (
                "Publish a learned skill to the marketplace. Auto-versions if "
                "skill name already exists with different content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "Skill name to publish."},
                    "description": {"type": "string", "description": "Skill description."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Skill tags."},
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_session_group",
            "description": (
                "Create a multi-session group for configuring a large site "
                "in parallel. Each session works on a non-overlapping scope."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Group name (e.g. 'Site Seetharampur')."},
                    "scopes": {"type": "array", "items": {"type": "string"}, "description": "Planned scope descriptions."},
                },
                "required": ["name"],
            },
        },
    },
    # ------------------------------------------------------------------
    # Phase 4 — Manage / Mutate tool schemas
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "update_gateway",
            "description": "Update a gateway's configuration (name, host, ports, protocol_hint). Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_id": {"type": "string", "description": "ID of the gateway to update."},
                    "patch": {"type": "object", "description": "Fields to update: name, host, ports, protocol_hint, tags.",
                              "properties": {
                                  "name": {"type": "string"}, "host": {"type": "string"},
                                  "ports": {"type": "array", "items": {"type": "integer"}},
                                  "protocol_hint": {"type": "string"},
                                  "tags": {"type": "array", "items": {"type": "string"}},
                              }},
                },
                "required": ["gateway_id", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_gateway",
            "description": "Delete a gateway. Fails if devices still reference it. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "gateway_id": {"type": "string", "description": "ID of the gateway to delete."},
                },
                "required": ["gateway_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_device",
            "description": "Update device metadata. Allowed fields: name, autoReconnect, unitId, port, gatewayId. Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID of the device to update."},
                    "patch": {"type": "object", "description": "Fields to update.",
                              "properties": {
                                  "name": {"type": "string"}, "autoReconnect": {"type": "boolean"},
                                  "unitId": {"type": "integer"}, "port": {"type": "integer"},
                                  "gatewayId": {"type": "string"},
                              }},
                },
                "required": ["device_id", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_device",
            "description": "Delete a device from the system. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID of the device to delete."},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connect_device",
            "description": "Test connectivity and mark device as connected. Always available (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID of the device to connect."},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disconnect_device",
            "description": "Manually disconnect a device. Always available (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "ID of the device to disconnect."},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schema",
            "description": "Delete a schema definition. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_id": {"type": "string", "description": "ID of the schema to delete."},
                },
                "required": ["schema_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_schema_field",
            "description": "Add a new field to an existing schema. Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_id": {"type": "string", "description": "ID of the schema."},
                    "field": {"type": "object", "description": "Field definition with key, type, and optional unit/scale/desc.",
                              "properties": {
                                  "key": {"type": "string"}, "type": {"type": "string"},
                                  "unit": {"type": "string"}, "scale": {"type": "number"},
                                  "desc": {"type": "string"},
                              },
                              "required": ["key", "type"]},
                },
                "required": ["schema_id", "field"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schema_field",
            "description": "Remove a field from a schema. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_id": {"type": "string", "description": "ID of the schema."},
                    "field_key": {"type": "string", "description": "Key of the field to remove."},
                },
                "required": ["schema_id", "field_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_table",
            "description": "Update table metadata (name, schemaId, dbTargetId). Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "ID of the table to update."},
                    "patch": {"type": "object", "description": "Fields to update.",
                              "properties": {
                                  "name": {"type": "string"}, "schemaId": {"type": "string"},
                                  "dbTargetId": {"type": "string"},
                              }},
                },
                "required": ["table_id", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_table",
            "description": "Delete a table. Set drop_physical=true to also DROP the physical database table (irreversible data loss). Available in chatting state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "ID of the table to delete."},
                    "drop_physical": {"type": "boolean", "description": "If true, also DROP the physical DB table. Default false.", "default": False},
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bind_device_to_table",
            "description": "Bind a device to a table for data collection. Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "ID of the table."},
                    "device_id": {"type": "string", "description": "ID of the device to bind."},
                },
                "required": ["table_id", "device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unbind_device_from_table",
            "description": "Unbind the device from a table. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "ID of the table."},
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_mapping_row",
            "description": "Delete a single field mapping from a table. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "ID of the table."},
                    "field_key": {"type": "string", "description": "Field key to unmap."},
                },
                "required": ["table_id", "field_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_mappings",
            "description": "Copy all register mappings (not device binding) from one table to another. Requires approved plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src_table_id": {"type": "string", "description": "Source table ID to copy from."},
                    "dst_table_id": {"type": "string", "description": "Destination table ID to copy to."},
                },
                "required": ["src_table_id", "dst_table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_job",
            "description": "Stop a running data collection job. Always available (no plan needed). Use when a job needs to be halted immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "ID of the job to stop."},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_job",
            "description": "Pause a running data collection job. Always available (no plan needed). The job can be resumed later with start_job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "ID of the job to pause."},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_job",
            "description": "Delete a job. Stops it first if running. Available in chatting state (no plan needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "ID of the job to delete."},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_db_target",
            "description": "Add a database storage target. RARELY NEEDED — the system already has a default target. Only use if the user EXPLICITLY provides a different database connection string. Never invent connection strings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Database provider: postgres, sqlite, sqlserver, mysql.",
                                 "enum": ["postgres", "sqlite", "sqlserver", "mysql"]},
                    "conn": {"type": "string", "description": "Connection string, e.g. postgresql://user:pass@host/db"},
                },
                "required": ["provider", "conn"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_db_target",
            "description": "Update a database target's configuration (provider, conn, status). Requires approved plan. Rarely needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "ID of the DB target."},
                    "patch": {"type": "object", "description": "Fields to update: provider, conn, status, lastMsg.",
                              "properties": {
                                  "provider": {"type": "string"}, "conn": {"type": "string"},
                                  "status": {"type": "string"}, "lastMsg": {"type": "string"},
                              }},
                },
                "required": ["target_id", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_db_target",
            "description": "Delete a database target. Fails if it is the default or in use (unless force=true). Available in chatting state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "ID of the DB target to delete."},
                    "force": {"type": "boolean", "description": "Force delete even if in use. Default false.", "default": False},
                },
                "required": ["target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_default_db_target",
            "description": "Set the default database target for new tables. Requires approved plan. Rarely needed — a default is usually already set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "ID of the DB target to set as default."},
                },
                "required": ["target_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch table — tool_name → async handler
# ---------------------------------------------------------------------------

TOOL_DISPATCH: Dict[str, Callable] = {
    # Phase 1A — system overview
    "read_config": read_config,
    "read_gateway_list": read_gateway_list,
    "read_schema_list": read_schema_list,
    # Phase 1B — full read surface
    "read_table_mapping": read_table_mapping,
    "read_job_status": read_job_status,
    "read_live_values": read_live_values,
    "read_device_status": read_device_status,
    "read_source_file": read_source_file,
    # Phase 1C — write tools
    "propose_plan": propose_plan,
    "create_gateway": create_gateway,
    "create_device": create_device,
    "test_device": test_device,
    "create_schema": create_schema,
    "create_table": create_table,
    "apply_mappings": apply_mappings,
    "migrate_table": migrate_table,
    "create_job": create_job,
    "start_job": start_job,
    # Phase 1H — validation
    "validate_live_readings": validate_live_readings,
    # Phase 1I — anomaly detection
    "run_anomaly_check": run_anomaly_check,
    "retrain_anomaly_model": retrain_anomaly_model,
    # Phase 1D — diagnostics
    "read_raw_registers": read_raw_registers,
    "browse_opcua_nodes": browse_opcua_nodes,
    "ping_host": ping_host,
    "scan_port": scan_port,
    "query_db": query_db,
    # Phase 2B — discovery
    "scan_subnet": scan_subnet,
    "enumerate_unit_ids": enumerate_unit_ids,
    "identify_device": identify_device,
    "discover_and_identify": discover_and_identify,
    # Phase 3A — prediction
    "read_prediction_status": read_prediction_status,
    # Phase 3B — temporal models
    "read_temporal_status": read_temporal_status,
    "train_temporal_model": train_temporal_model,
    "retrain_temporal_model": retrain_temporal_model,
    # Phase 3D — advanced
    "infer_topology": infer_topology,
    "read_topology": read_topology,
    "cloud_identify": cloud_identify,
    "marketplace_search": marketplace_search,
    "marketplace_publish": marketplace_publish,
    "create_session_group": create_session_group,
    # Phase 4 — manage/mutate tools
    "update_gateway": update_gateway,
    "delete_gateway": delete_gateway,
    "update_device": update_device,
    "delete_device": delete_device,
    "connect_device": connect_device,
    "disconnect_device": disconnect_device,
    "delete_schema": delete_schema,
    "add_schema_field": add_schema_field,
    "delete_schema_field": delete_schema_field,
    "update_table": update_table,
    "delete_table": delete_table,
    "bind_device_to_table": bind_device_to_table,
    "unbind_device_from_table": unbind_device_from_table,
    "delete_mapping_row": delete_mapping_row,
    "copy_mappings": copy_mappings,
    "stop_job": stop_job,
    "pause_job": pause_job,
    "delete_job": delete_job,
    "add_db_target": add_db_target,
    "update_db_target": update_db_target,
    "delete_db_target": delete_db_target,
    "set_default_db_target": set_default_db_target,
}

# ---------------------------------------------------------------------------
# Phase 1F — MFM Knowledge Base tools (merged from sub-package)
# ---------------------------------------------------------------------------
try:
    from .mfm_kb.tools import MFM_KB_TOOL_SCHEMAS, MFM_KB_TOOL_DISPATCH
    TOOL_SCHEMAS.extend(MFM_KB_TOOL_SCHEMAS)
    TOOL_DISPATCH.update(MFM_KB_TOOL_DISPATCH)
except ImportError:
    logger.warning("mfm_kb tools not available (Phase 1F not installed)")
