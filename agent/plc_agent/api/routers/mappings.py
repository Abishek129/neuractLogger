from __future__ import annotations

import re
import time as _time
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException
import logging

from ..store import Store
from ..redact import redact_dsn
from sqlalchemy import create_engine, text  # type: ignore


router = APIRouter(prefix="/mappings")
log = logging.getLogger(__name__)

# L19/SEC-2: mapping field keys become SQL column identifiers in the Rust
# engine's INSERTs — enforce the same charset/length rule as schema fields.
_FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_IDENT_LEN = 63


def _validate_row_field_keys(rows: Dict[str, Any]) -> None:
    for k in rows.keys():
        if not isinstance(k, str) or not _FIELD_KEY_RE.match(k) or len(k) > _MAX_IDENT_LEN:
            raise HTTPException(status_code=400, detail=f"FIELD_KEY_INVALID:{k}")


def _resolve_table(table_id: str, *, db_target_override: Optional[str] = None) -> Dict[str, Any]:
    table = Store.instance().get_table(table_id)
    if table:
        return table
    if table_id.startswith("phy_"):
        logical = table_id[4:]
        target = db_target_override or Store.instance().get_default_db_target()
        if not target:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
        return {"id": table_id, "name": logical, "dbTargetId": target, "schemaId": None}
    raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")


_INT_ENCODINGS = {"uint16_enum", "uint16", "int16", "bool16", "uint32", "int32", "uint64", "int64"}

# Registers each encoding occupies — mirrors modbus_encoding_info() in the Rust
# engine (rust_jobs/src/main.rs). The live-read check must request the same width
# the engine will, or the meter rejects a partial read of a multi-register value.
# Total wall-clock budget for the per-field live-read probing in validate_mapping.
# Comfortably under nginx's 60s proxy_read_timeout so validation can never 504.
_VALIDATE_PROBE_BUDGET_SEC = 40

# Gap between consecutive field probes. Serial (RS-485) gateways cannot absorb
# dozens of back-to-back requests: the meter answers the first few then goes
# quiet, which looks exactly like a dead device. The Rust engine never hits this
# because it issues a handful of BUCKETED reads, not one request per field.
_VALIDATE_PROBE_GAP_SEC = 0.06


def _why_unreachable(host: str, port: int) -> str:
    """Classify a failed Modbus connect by probing the raw socket for the errno."""
    import socket as _socket

    s = _socket.socket()
    s.settimeout(3)
    try:
        s.connect((host, port))
        # Reachable now — the Modbus client's failure was transient.
        return "gateway is reachable; the Modbus session was refused (try again)"
    except _socket.timeout:
        return "no response — gateway powered off, or blocked by the network"
    except OSError as e:
        if e.errno == 113:  # EHOSTUNREACH
            return "no route to host — gateway is off the network or the IP is wrong"
        if e.errno == 111:  # ECONNREFUSED
            return (
                "connection refused — nothing is listening on :502 "
                "(gateway rebooting, or Modbus TCP disabled)"
            )
        return f"{e.strerror or e}"
    finally:
        try:
            s.close()
        except Exception:
            pass


def _is_unreachable(reason: str) -> bool:
    """True when the reason means the DEVICE is unusable, not the tag.

    Re-probing every remaining field after this is pure latency — the answer will
    be identical for all of them.
    """
    r = (reason or "").lower()
    return any(
        s in r
        for s in ("could not connect", "connection dropped", "no host", "not installed", "timed out")
    )


_MODBUS_REG_COUNT = {
    "float32": 2, "float": 2, "uint32": 2, "int32": 2,
    "uint16": 1, "uint16_enum": 1, "int16": 1, "bool16": 1, "bool": 1, "int": 1,
    "float64": 4, "uint64": 4, "int64": 4,
}


def _build_field_type_map(table: Dict[str, Any]) -> Dict[str, str]:
    """Build {field_key: encoding_type} from the table's schema fields."""
    schema = Store.instance().get_schema(table.get("schemaId")) or {"fields": []}
    return {f["key"]: f.get("type", "float32") for f in schema.get("fields", [])}


@router.get("/{table_id}")
def get_mapping(table_id: str) -> Dict[str, Any]:
    t = _resolve_table(table_id)
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
    schema_fields = schema.get("fields") or []
    required = [f.get("key") for f in schema_fields]
    health = Store.instance().mapping_health(table_id, required_fields=required, schema_fields=schema_fields)
    return {"success": True, "item": {"tableId": table_id, **m}, "health": health}


@router.get("/{table_id}/fields")
def list_schema_fields(table_id: str) -> Dict[str, Any]:
    """Every field of the table's schema, merged with its current mapping row.

    Drives the mapping grid: the schema defines which columns the table has, the
    mapping defines where each value is read from. Unmapped fields come back with
    a blank address so the UI can render the full expected field list instead of
    an empty grid the user has to retype field names into.
    """
    t = _resolve_table(table_id)
    loaded = _load_mapping_from_user_db(t)
    if loaded:
        Store.instance().replace_mapping(
            table_id, {"deviceId": loaded.get("deviceId"), "rows": loaded.get("rows") or {}}
        )
    m = loaded or Store.instance().get_mapping(table_id)
    rows = m.get("rows") or {}
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []

    items = []
    for f in schema_fields:
        key = f.get("key")
        r = rows.get(key) or {}
        encoding = r.get("encoding") or f.get("type") or "float32"
        scale = r.get("scale")
        if scale is None:
            scale = f.get("scale") if f.get("scale") is not None else 1
        items.append(
            {
                "fieldKey": key,
                "type": f.get("type"),
                "unit": f.get("unit"),
                "desc": f.get("desc"),
                # Derived fields are computed from a formula, never read from the
                # device — upsert_mapping rejects them, so flag them for the UI.
                "derived": bool(f.get("formula")),
                "formula": f.get("formula"),
                # Only a committed device_mappings row counts as mapped. A row with
                # mapped=false but a non-empty address is "suggested by the schema,
                # not yet confirmed" — the engine reads device_mappings, not schemas.
                "mapped": bool(r.get("address")),
                "protocol": r.get("protocol") or "",
                # Mapping row wins; the schema field is the per-meter-model default.
                "address": r.get("address") or f.get("address") or "",
                "dataType": r.get("dataType")
                or ("int" if encoding in _INT_ENCODINGS else "float"),
                # The wire format (int16, uint32, float32, ...). dataType above is
                # only the logical kind and cannot tell int16 from int32.
                "encoding": encoding,
                "scale": scale,
                "deadband": r.get("deadband") if r.get("deadband") is not None else 0,
            }
        )

    required = [f.get("key") for f in schema_fields]
    health = Store.instance().mapping_health(
        table_id, required_fields=required, schema_fields=schema_fields
    )
    return {
        "success": True,
        "tableId": table_id,
        "schema": {"id": schema.get("id"), "name": schema.get("name")},
        "deviceId": m.get("deviceId"),
        "items": items,
        "health": health,
    }


@router.post("/{table_id}")
def upsert_mapping(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = _resolve_table(table_id, db_target_override=payload.get("dbTargetId"))
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []
    derived_keys = {f.get("key") for f in schema_fields if f.get("formula")}
    device_id = payload.get("deviceId")
    rows_patch = payload.get("rows") or {}
    # Reject manual mapping of derived fields
    for k in list(rows_patch.keys()):
        if k in derived_keys:
            rows_patch.pop(k)
    _validate_row_field_keys(rows_patch)  # L19
    field_type_map = _build_field_type_map(t)
    # Enrich rows with auto-derived encoding/dataType so in-memory store stays consistent
    for k, v in rows_patch.items():
        if not v.get("encoding"):
            v["encoding"] = field_type_map.get(k, "float32")
        if not v.get("dataType"):
            v["dataType"] = "int" if v["encoding"] in _INT_ENCODINGS else "float"
    _save_mapping_to_user_db(t, rows_patch, device_id, field_type_map=field_type_map)
    m = Store.instance().upsert_mapping(table_id, device_id=device_id, rows_patch=rows_patch)
    # Recompute health after save
    required = [f.get("key") for f in schema_fields]
    health = Store.instance().mapping_health(table_id, required_fields=required, schema_fields=schema_fields)
    return {"success": True, "message": "mapping_upserted", "item": m, "health": health}


@router.post("/{table_id}/bulk_apply")
def bulk_apply(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = _resolve_table(table_id, db_target_override=payload.get("dbTargetId"))
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []
    derived_keys = {f.get("key") for f in schema_fields if f.get("formula")}
    # Accept both dict format {rows: {field: {...}}} and array format {mappings: [{field_key, ...}]}
    rows = payload.get("rows") or {}
    if not rows and isinstance(payload.get("mappings"), list):
        for entry in payload["mappings"]:
            fk = entry.get("field_key") or entry.get("fieldKey") or ""
            if fk:
                rows[fk] = {
                    "protocol": entry.get("protocol", "modbus"),
                    "address": str(entry.get("address", "")),
                    "dataType": entry.get("data_type") or entry.get("dataType") or "",
                    "encoding": entry.get("encoding") or "",
                    "scale": entry.get("scale"),
                    "deadband": entry.get("deadband"),
                }
    # Strip derived fields — they cannot be manually mapped
    for k in list(rows.keys()):
        if k in derived_keys:
            rows.pop(k)
    _validate_row_field_keys(rows)  # L19
    # The mapping grid sends the real wire encoding. Reject anything the engine
    # cannot decode instead of silently logging garbage; empty falls back to the
    # schema's field type below.
    for k, v in rows.items():
        enc = (v.get("encoding") or "").strip().lower()
        if enc and enc not in _MODBUS_REG_COUNT:
            raise HTTPException(status_code=400, detail=f"ENCODING_INVALID:{k}:{enc}")
        v["encoding"] = enc
    field_type_map = _build_field_type_map(t)
    for k, v in rows.items():
        if not v.get("encoding"):
            v["encoding"] = field_type_map.get(k, "float32")
        if not v.get("dataType"):
            v["dataType"] = "int" if v["encoding"] in _INT_ENCODINGS else "float"
    # Preserve existing device binding if no deviceId in payload
    device_id = payload.get("deviceId") or t.get("deviceId")
    _save_mapping_to_user_db(t, rows, device_id, field_type_map=field_type_map)
    m = Store.instance().upsert_mapping(table_id, device_id=device_id, rows_patch=rows)
    return {"success": True, "message": "mapping_applied", "item": m}


@router.post("/{table_id}/import")
def import_mapping(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    t = _resolve_table(table_id, db_target_override=payload.get("dbTargetId"))
    mapping = payload.get("mapping") or payload
    rows = mapping.get("rows") or {}
    # DP7(b): derived rows are engine-owned — strip them from manual imports
    # (the replace below also preserves existing protocol='derived' rows).
    derived_keys = {
        f.get("key")
        for f in ((Store.instance().get_schema(t.get("schemaId")) or {}).get("fields") or [])
        if f.get("formula")
    }
    for k in list(rows.keys()):
        if k in derived_keys:
            rows.pop(k)
    _validate_row_field_keys(rows)  # L19
    field_type_map = _build_field_type_map(t)
    _replace_mapping_in_user_db(t, rows, mapping.get("deviceId") or payload.get("deviceId"), field_type_map=field_type_map)
    m = Store.instance().replace_mapping(table_id, {"deviceId": mapping.get("deviceId") or payload.get("deviceId"), "rows": rows})
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []
    required = [f.get("key") for f in schema_fields]
    health = Store.instance().mapping_health(table_id, required_fields=required, schema_fields=schema_fields)
    return {"success": True, "message": "mapping_imported", "item": m, "health": health}


@router.post("/{table_id}/validate")
def validate_mapping(table_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    t = _resolve_table(table_id, db_target_override=payload.get("dbTargetId"))
    m = Store.instance().get_mapping(table_id)
    schema = Store.instance().get_schema(t.get("schemaId")) or {"fields": []}
    schema_fields = schema.get("fields") or []
    derived_keys = {f.get("key") for f in schema_fields if f.get("formula")}
    required = [f.get("key") for f in schema_fields if not f.get("formula")]
    # Validate against provided payload when present (no write), else current stored mapping
    rows = (payload.get("rows") if isinstance(payload, dict) else None) or (m.get("rows") or {})
    device_id = (payload.get("deviceId") if isinstance(payload, dict) else None) or m.get("deviceId")
    problems = []
    if not device_id:
        problems.append({"code": "DEVICE_NOT_BOUND"})
    # Attempt live-read validation when device is present.
    # This probes the device once per field, so it must stay bounded: a table with
    # 40 fields against an unresponsive gateway would otherwise spend 40x the socket
    # timeout and blow past nginx's proxy_read_timeout (observed as an HTTP 504).
    # Two guards: stop entirely once the device proves unreachable, and cap the
    # total time spent probing.
    device = Store.instance().get_device(device_id) if device_id else None
    probe_deadline = _time.monotonic() + _VALIDATE_PROBE_BUDGET_SEC
    dead_reason: Optional[str] = None
    # One Modbus connection reused across every field in this call (see
    # _modbus_can_read). Closed in the finally below.
    conn_cache: Dict[str, Any] = {}
    no_response_streak = 0
    probed_any = False
    for k in required:
        r = rows.get(k) or {}
        if not r:
            problems.append({"field": k, "code": "MAPPING_INCOMPLETE"})
        else:
            proto = r.get("protocol")
            if not Store.instance().is_valid_protocol(proto or ""):
                problems.append({
                    "field": k,
                    "code": "MAPPING_TYPE_MISMATCH",
                    "message": f"Invalid protocol: {proto}"
                })
            if not r.get("address"):
                problems.append({"field": k, "code": "MAPPING_INCOMPLETE"})
            # For OPC UA, datatype is informational; skip hard requirement
            if proto != "opcua":
                if r.get("dataType") not in ("float", "int", "bool", "string"):
                    problems.append({"field": k, "code": "MAPPING_TYPE_MISMATCH"})
            # Live-read check (best-effort). Carry the reason through so the UI can
            # tell a bad address apart from a busy gateway or an unreachable meter.
            if device:
                if dead_reason is not None:
                    # Device already proved unreachable — don't re-probe 39 more times.
                    problems.append(
                        {"field": k, "code": "TAG_UNREADABLE", "message": dead_reason}
                    )
                elif _time.monotonic() > probe_deadline:
                    problems.append({
                        "field": k,
                        "code": "TAG_UNCHECKED",
                        "message": (
                            f"not checked — validation stopped after "
                            f"{_VALIDATE_PROBE_BUDGET_SEC}s; fix the reported fields and re-run"
                        ),
                    })
                else:
                    if probed_any:
                        _time.sleep(_VALIDATE_PROBE_GAP_SEC)
                    probed_any = True
                    ok, reason = _can_read_field(device, r, conn_cache)
                    if not ok:
                        # A meter that stops answering makes every remaining probe
                        # cost a full timeout. After a few in a row, treat it as a
                        # device-level fault instead of burning the whole budget.
                        if "no response" in reason.lower():
                            no_response_streak += 1
                            # Threshold must exceed the noise floor of a flaky
                            # link. A marginal RS-485 run drops reads at random;
                            # tripping at 3 mislabels a working meter as dead.
                            if no_response_streak >= 12:
                                dead_reason = (
                                    f"device stopped responding after {no_response_streak} "
                                    f"consecutive reads — check unit id, wiring, or meter health"
                                )
                        else:
                            no_response_streak = 0
                        if _is_unreachable(reason):
                            dead_reason = reason
                        problems.append(
                            {"field": k, "code": "TAG_UNREADABLE", "message": reason}
                        )
    for _c in conn_cache.values():
        try:
            _c.close()
        except Exception:
            pass
    conn_cache.clear()

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
# These return (ok, reason). The reason is surfaced to the UI: a bare boolean
# collapses "register does not exist", "wrong register type", "meter not
# responding" and "could not get a socket" into one opaque TAG_UNREADABLE, and
# those four need completely different fixes.
def _can_read_field(
    device: Dict[str, Any], row: Dict[str, Any], conn_cache: Optional[Dict[str, Any]] = None
) -> tuple[bool, str]:
    try:
        proto = (row.get("protocol") or device.get("protocol") or "").lower()
        if proto == "opcua":
            return _opcua_can_read(device, row)
        if proto == "modbus":
            return _modbus_can_read(device, row, conn_cache)
    except Exception as e:
        return False, f"read check failed: {e}"
    return False, f"unsupported protocol: {proto or '(none)'}"


def _opcua_can_read(device: Dict[str, Any], row: Dict[str, Any]) -> tuple[bool, str]:
    try:
        try:
            from opcua import Client  # type: ignore
        except Exception:
            return False, "opcua client library not installed"
        # Resolve endpoint: gateway.host > params.endpoint
        from ..store import Store
        ep = None
        gateway_id = device.get("gatewayId")
        if gateway_id:
            gateway = Store.instance().get_gateway(gateway_id)
            if gateway and gateway.get("host"):
                gw_host = gateway["host"]
                if gw_host.startswith("opc.tcp://"):
                    ep = gw_host
                else:
                    gw_port = (gateway.get("ports") or [4840])[0] or 4840
                    ep = f"opc.tcp://{gw_host}:{gw_port}"
        if not ep:
            params = device.get("params") or {}
            ep = (params.get("endpoint") or "").strip()
        if not ep:
            return False, "no OPC UA endpoint on device or gateway"
        node_id = (row.get("address") or row.get("nodeId") or "").strip()
        if not node_id:
            return False, "no node id on the mapping row"
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
            return True, ""
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
    except Exception as e:
        return False, f"OPC UA read failed: {e}"


def _modbus_can_read(
    device: Dict[str, Any], row: Dict[str, Any], conn_cache: Optional[Dict[str, Any]] = None
) -> tuple[bool, str]:
    try:
        try:
            from pymodbus.client import ModbusTcpClient  # type: ignore
        except Exception:
            return False, "pymodbus not installed"
        # Get host - from gateway or fallback to params
        gateway_id = device.get("gatewayId")
        gateway = None
        if gateway_id:
            gateway = Store.instance().get_gateway(gateway_id)

        if gateway and gateway.get("host"):
            host = gateway.get("host")
        else:
            params = device.get("params") or {}
            host = (params.get("host") or params.get("ip") or "").strip()

        if not host:
            return False, "no host on device or gateway"

        # Get port - from device.port or fallback to params or default
        port = device.get("port")
        if port is None:
            params = device.get("params") or {}
            port = int(params.get("port", 502))
        else:
            port = int(port)
        addr_raw = str(row.get("address") or "").strip()
        if not addr_raw:
            return False, "no address on the mapping row"
        try:
            address = int(addr_raw)
        except Exception:
            return False, f"address {addr_raw!r} is not numeric"
        unit_id = int(device.get("unitId") or device.get("unit_id") or 1)
        # One TCP connection per FIELD makes validation O(fields) in round trips —
        # 36 fields took 21s and blew the probe budget. Reuse a single connection
        # for the whole validate call; the caller closes it.
        key = f"{host}:{port}"
        cached = conn_cache.get(key) if conn_cache is not None else None
        client = cached or ModbusTcpClient(
            host=host, port=port, timeout=1.5, retries=1
        )
        try:
            if not client.connect():
                # pymodbus's connect() returns a bare False, so probe the socket
                # ourselves to recover the real errno. "Host unreachable" (gateway
                # off/unplugged) and "refused/reset" (single-session gateway already
                # held by a running job) look identical otherwise, but need opposite
                # fixes — never blame the tag for either.
                return False, f"could not connect to {host}:{port} — {_why_unreachable(host, port)}"
            # Bounded ranges mirroring parse_modbus_address() in the Rust engine.
            # An unbounded `>= 40001` would swallow the 6-digit extended form
            # (421300 -> 381299 instead of 21299) and fail on valid addresses.
            if 40001 <= address <= 49999:
                start, kind, fc = address - 40001, "holding 4xxxx", "holding"
            elif 30001 <= address <= 39999:
                start, kind, fc = address - 30001, "input 3xxxx", "input"
            elif 10001 <= address <= 19999:
                start, kind, fc = address - 10001, "discrete 1xxxx", "holding"
            elif 400001 <= address <= 465535:
                start, kind, fc = address - 400001, "holding 4xxxxx (extended)", "holding"
            elif 300001 <= address <= 365535:
                start, kind, fc = address - 300001, "input 3xxxxx (extended)", "input"
            elif 100001 <= address <= 165535:
                start, kind, fc = address - 100001, "discrete 1xxxxx (extended)", "holding"
            else:
                start, kind, fc = max(0, address), "raw offset (0-based)", "holding"
            # Read the field's REAL width. A float32 spans 2 registers and these
            # meters reject a 1-register read of it with IllegalDataValue — a
            # hardcoded count=1 therefore fails on perfectly valid addresses.
            enc = str(row.get("encoding") or row.get("dataType") or "float32").lower()
            count = _MODBUS_REG_COUNT.get(enc, 2)
            if fc == "input":
                r = client.read_input_registers(address=start, count=count, device_id=unit_id)
            else:
                r = client.read_holding_registers(address=start, count=count, device_id=unit_id)
            if hasattr(r, "isError") and r.isError():
                # The Modbus exception code IS the diagnosis — pass it through.
                code = getattr(r, "exception_code", None)
                meaning = {
                    1: "IllegalFunction — device does not support this register type",
                    2: "IllegalDataAddress — register does not exist on this meter",
                    3: "IllegalDataValue — register count/span rejected",
                    4: "SlaveDeviceFailure",
                    6: "SlaveDeviceBusy",
                    11: "GatewayTargetDeviceFailedToRespond — check unit id / wiring",
                }.get(code, str(r))
                return False, (
                    f"{meaning} (addr {addr_raw} -> {kind} offset {start}, unit {unit_id})"
                )
            return True, ""
        finally:
            if conn_cache is None:
                try:
                    client.close()
                except Exception:
                    pass
            else:
                conn_cache[key] = client
    except (ConnectionResetError, BrokenPipeError) as e:
        # Classic single-session gateway symptom: the running job owns the socket
        # and the meter drops ours. Nothing to do with the address.
        return False, (
            f"connection dropped by the device ({e}) — a job is most likely holding "
            f"the only Modbus session; stop it and validate again"
        )
    except Exception as e:
        return False, f"modbus read failed: {e}"


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
            field_type_map = _build_field_type_map(dst_t)
            _replace_mapping_in_user_db(dst_t, m.get("rows") or {}, field_type_map=field_type_map)
    return {"success": True, "message": "mapping_copied", "item": m}


@router.post("/{table_id}/preview_sample")
def preview_sample(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Stub non-blocking preview: returns structure without device IO
    if not Store.instance().get_table(table_id):
        raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
    # H-API-3/M-API-1: an unimplemented operation must not report HTTP 200
    # with success:false — 501 with the standard error envelope.
    raise HTTPException(
        status_code=501,
        detail={
            "success": False,
            "error": "PREVIEW_NOT_IMPLEMENTED",
            "message": "preview_sample is not implemented",
        },
    )


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
        "encoding TEXT,"
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


def _save_mapping_to_user_db(table: Dict[str, Any], rows: Dict[str, Dict[str, Any]], device_id: Optional[str] = None, *, field_type_map: Optional[Dict[str, str]] = None) -> None:
    engine = _engine_for_target_id(table.get("dbTargetId"))
    # Choose existing mapping table when present; create standard if none
    m_table = _select_mapping_table(engine, create=True)
    t_ident = _device_ident(engine, table.get("name"))
    ftm = field_type_map or {}
    with engine.begin() as conn:
        for k, v in (rows or {}).items():
            try:
                enc = v.get("encoding") or ftm.get(k, "float32")
                dt = v.get("dataType") or ("int" if enc in _INT_ENCODINGS else "float")
                params = {
                    "t": t_ident["name"],
                    "k": k,
                    "p": v.get("protocol"),
                    "a": v.get("address") or v.get("nodeId"),
                    "dt": dt,
                    "s": v.get("scale"),
                    "d": v.get("deadband"),
                    "dev": device_id,
                    "enc": enc,
                }
                if _dialect_name(engine).startswith("postgres"):
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
            except Exception:
                # Basic upsert fallback: delete then insert
                try:
                    conn.execute(text(f"DELETE FROM {m_table} WHERE table_name=:t AND field_key=:k"), {"t": t_ident["name"], "k": k})
                    conn.execute(
                        text(
                            f"INSERT INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id,encoding)"
                            " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev,:enc)"
                        ),
                        params,
                    )
                except Exception:
                    pass


def _replace_mapping_in_user_db(table: Dict[str, Any], rows: Dict[str, Dict[str, Any]], device_id: Optional[str] = None, *, field_type_map: Optional[Dict[str, str]] = None) -> None:
    engine = _engine_for_target_id(table.get("dbTargetId"))
    m_table = _select_mapping_table(engine, create=True)
    t_ident = _device_ident(engine, table.get("name"))
    ftm = field_type_map or {}
    with engine.begin() as conn:
        # DP7(b): preserve protocol='derived' rows — they are owned by the
        # schema/migrate pipeline, not by manual mapping replaces/imports.
        conn.execute(
            text(f"DELETE FROM {m_table} WHERE table_name=:t AND (protocol IS NULL OR protocol <> 'derived')"),
            {"t": t_ident["name"]},
        )
        for k, v in (rows or {}).items():
            enc = v.get("encoding") or ftm.get(k, "float32")
            dt = v.get("dataType") or ("int" if enc in _INT_ENCODINGS else "float")
            conn.execute(
                text(
                    f"INSERT INTO {m_table} (table_name,field_key,protocol,address,data_type,scale,deadband,device_id,encoding)"
                    " VALUES (:t,:k,:p,:a,:dt,:s,:d,:dev,:enc)"
                ),
                {
                    "t": t_ident["name"],
                    "k": k,
                    "p": v.get("protocol"),
                    "a": v.get("address") or v.get("nodeId"),
                    "dt": dt,
                    "s": v.get("scale"),
                    "d": v.get("deadband"),
                    "dev": device_id,
                    "enc": enc,
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
            # H-OBS-4: engine.url may embed a password — redact before logging.
            log.info(f"mappings._load.init: url={redact_dsn(getattr(engine, 'url', ''))} m_table={m_table} logical={logical} prefixed={prefixed}")
        except Exception:
            pass
        rows = []
        with engine.begin() as conn:
            has_encoding = False
            try:
                dname = _dialect_name(engine)
                if dname.startswith("postgres"):
                    if "." in m_table:
                        schema_name, table_name = m_table.split(".", 1)
                    else:
                        schema_name, table_name = "public", m_table
                    enc_row = conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema=:s AND table_name=:t AND column_name='encoding' LIMIT 1"
                        ),
                        {"s": schema_name, "t": table_name},
                    ).first()
                    has_encoding = bool(enc_row)
                else:
                    # SQLite style table_info; works for local/fallback targets.
                    base_name = m_table.split(".")[-1]
                    cols = conn.execute(text(f"PRAGMA table_info({base_name})")).fetchall()
                    names = set()
                    for c in cols or []:
                        try:
                            names.add(c[1])
                        except Exception:
                            try:
                                names.add(c["name"])  # type: ignore[index]
                            except Exception:
                                pass
                    has_encoding = "encoding" in names
            except Exception:
                has_encoding = False

            def _fetch_rows(table_name: str):
                # Newer schema includes `encoding`; older deployments may not.
                if has_encoding:
                    return conn.execute(
                        text(f"SELECT field_key,protocol,address,data_type,scale,deadband,device_id,encoding FROM {m_table} WHERE table_name=:t"),
                        {"t": table_name},
                    ).fetchall()
                return conn.execute(
                    text(f"SELECT field_key,protocol,address,data_type,scale,deadband,device_id FROM {m_table} WHERE table_name=:t"),
                    {"t": table_name},
                ).fetchall()

            # Try logical name first
            try:
                rows = _fetch_rows(logical)
                try:
                    log.info(f"mappings._load.query: table={logical} -> {len(rows)} rows")
                except Exception:
                    pass
            except Exception:
                rows = []
            if not rows and prefixed != logical:
                try:
                    rows = _fetch_rows(prefixed)
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
                "encoding": _get(r, "encoding", 7),
            }
        try:
            log.info(f"mappings._load: table={table.get('id')} name={table.get('name')} target={table.get('dbTargetId')} rows={len(out['rows'])} dev={out.get('deviceId')}")
        except Exception:
            pass
        return out
    except Exception:
        return None
