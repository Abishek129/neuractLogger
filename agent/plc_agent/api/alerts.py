"""Alerts on readings.

* app_alert: alert levels (Critical / Mild / Info seeded once; user-managed).
* app_schema_alert: the blueprint — `field op threshold` rules on a schema
  field, one per (schema, field, level). Every table of the schema inherits them.
* app_table_alert: per-table override for the same (field, level): a different
  op/threshold, or `enabled: false` to switch the inherited rule off.
* app_alert_state / app_alert_event: written by the Rust engine. Each table
  field has one state — normal, or the most severe level whose rule matches
  the latest reading — and every change of state is one event.

The engine loads a table's effective rules when a job starts, so rule edits
apply at the next job (re)start.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from .appdb import ALERT_OPS, _conn, _fetchall, _fetchone


class AlertError(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.status = status
        self.detail = f"{code}: {message}" if message else code


def _bad(code: str, msg: str = "") -> AlertError:
    return AlertError(400, code, msg)


def _missing(code: str, msg: str = "") -> AlertError:
    return AlertError(404, code, msg)


def _conflict(code: str, msg: str = "") -> AlertError:
    return AlertError(409, code, msg)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{secrets.token_hex(2)}"


def _req_str(payload: Dict[str, Any], key: str, code: str) -> str:
    v = payload.get(key)
    if not isinstance(v, str) or not v.strip():
        raise _bad(code)
    return v.strip()


def _op(payload: Dict[str, Any]) -> str:
    op = payload.get("op")
    if op not in ALERT_OPS:
        raise _bad("OP_INVALID", f"op must be one of {' '.join(ALERT_OPS)}")
    return op


def _threshold(payload: Dict[str, Any]) -> float:
    v = payload.get("threshold")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise _bad("THRESHOLD_INVALID", "threshold must be a number")
    return float(v)


# ---------- Levels ----------
def _level_out(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": r["id"], "name": r["name"], "severity": r["severity"], "color": r["color"], "sortOrder": r["sort_order"]}


def _get_level(c, alert_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_alert WHERE id=:id", {"id": alert_id})
    if not row:
        raise _missing("ALERT_LEVEL_NOT_FOUND", alert_id)
    return row


def _check_level_name(c, name: str, exclude: str = "") -> None:
    if _fetchone(c, "SELECT id FROM app_alert WHERE lower(name)=lower(:n) AND id<>:x", {"n": name, "x": exclude}):
        raise _conflict("ALERT_LEVEL_EXISTS", name)


def list_levels() -> List[Dict[str, Any]]:
    with _conn() as c:
        return [_level_out(r) for r in _fetchall(c, "SELECT * FROM app_alert ORDER BY severity DESC, sort_order, name")]


def create_level(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _req_str(payload, "name", "NAME_REQUIRED")
    sev = payload.get("severity", 1)
    if isinstance(sev, bool) or not isinstance(sev, int) or sev < 0:
        raise _bad("SEVERITY_INVALID", "severity must be a whole number >= 0 (higher = more severe)")
    color = payload.get("color")
    if color is not None and not isinstance(color, str):
        raise _bad("COLOR_INVALID")
    with _conn() as c:
        _check_level_name(c, name)
        aid = _new_id("al")
        order = _fetchone(c, "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM app_alert")["n"]
        c.execute(
            text("INSERT INTO app_alert (id, name, severity, color, sort_order) VALUES (:id, :n, :s, :c, :o)"),
            {"id": aid, "n": name, "s": sev, "c": color, "o": order},
        )
        return _level_out(_get_level(c, aid))


def update_level(alert_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        row = _get_level(c, alert_id)
        if "name" in payload:
            row["name"] = _req_str(payload, "name", "NAME_REQUIRED")
            _check_level_name(c, row["name"], exclude=alert_id)
        if "severity" in payload:
            sev = payload["severity"]
            if isinstance(sev, bool) or not isinstance(sev, int) or sev < 0:
                raise _bad("SEVERITY_INVALID")
            row["severity"] = sev
        if "color" in payload:
            if payload["color"] is not None and not isinstance(payload["color"], str):
                raise _bad("COLOR_INVALID")
            row["color"] = payload["color"]
        if "sortOrder" in payload:
            so = payload["sortOrder"]
            if isinstance(so, bool) or not isinstance(so, int):
                raise _bad("SORT_ORDER_INVALID")
            row["sort_order"] = so
        c.execute(
            text("UPDATE app_alert SET name=:name, severity=:severity, color=:color, sort_order=:sort_order WHERE id=:id"),
            row,
        )
        return _level_out(row)


def delete_level(alert_id: str) -> None:
    with _conn() as c:
        _get_level(c, alert_id)
        used = (
            _fetchone(c, "SELECT COUNT(*) AS n FROM app_schema_alert WHERE alert_id=:a", {"a": alert_id})["n"]
            + _fetchone(c, "SELECT COUNT(*) AS n FROM app_table_alert WHERE alert_id=:a", {"a": alert_id})["n"]
            + _fetchone(c, "SELECT COUNT(*) AS n FROM app_alert_state WHERE alert_id=:a", {"a": alert_id})["n"]
        )
        if used:
            raise _conflict("ALERT_LEVEL_IN_USE", f"{used} rule(s) or active state(s) use it")
        c.execute(text("DELETE FROM app_alert WHERE id=:id"), {"id": alert_id})


# ---------- Schema rules (the blueprint) ----------
def _schema_fields(c, schema_id: str) -> Dict[str, Dict[str, Any]]:
    if not _fetchone(c, "SELECT id FROM app_schemas WHERE id=:id", {"id": schema_id}):
        raise _missing("SCHEMA_NOT_FOUND", schema_id)
    return {r["key"]: r for r in _fetchall(c, "SELECT key, type, unit FROM app_schema_fields WHERE schema_id=:s", {"s": schema_id})}


_RULE_SELECT = "SELECT r.*, a.name AS alert_name, a.severity, a.color FROM {t} r JOIN app_alert a ON a.id = r.alert_id "


def _rule_out(r: Dict[str, Any], unit: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "id": r["id"],
        "fieldKey": r["field_key"],
        "alertId": r["alert_id"],
        "alertName": r["alert_name"],
        "severity": r["severity"],
        "color": r["color"],
        "op": r["op"],
        "threshold": r["threshold"],
    }
    if unit is not None:
        out["unit"] = unit
    return out


def list_schema_rules(schema_id: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        fields = _schema_fields(c, schema_id)
        rows = _fetchall(
            c, _RULE_SELECT.format(t="app_schema_alert") + "WHERE r.schema_id=:s ORDER BY r.field_key, a.severity DESC",
            {"s": schema_id},
        )
        return [_rule_out(r, (fields.get(r["field_key"]) or {}).get("unit")) for r in rows]


def create_schema_rule(schema_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    field_key = _req_str(payload, "fieldKey", "FIELD_REQUIRED")
    alert_id = _req_str(payload, "alertId", "ALERT_LEVEL_REQUIRED")
    op, threshold = _op(payload), _threshold(payload)
    with _conn() as c:
        fields = _schema_fields(c, schema_id)
        if field_key not in fields:
            raise _bad("FIELD_UNKNOWN", f"{field_key} is not a field of this schema")
        if fields[field_key]["type"] and str(fields[field_key]["type"]).lower() == "string":
            raise _bad("FIELD_NOT_NUMERIC", field_key)
        _get_level(c, alert_id)
        if _fetchone(
            c, "SELECT id FROM app_schema_alert WHERE schema_id=:s AND field_key=:f AND alert_id=:a",
            {"s": schema_id, "f": field_key, "a": alert_id},
        ):
            raise _conflict("ALERT_RULE_EXISTS", f"{field_key} already has a rule for this level")
        rid = _new_id("sar")
        c.execute(
            text(
                "INSERT INTO app_schema_alert (id, schema_id, field_key, alert_id, op, threshold) "
                "VALUES (:id, :s, :f, :a, :op, :t)"
            ),
            {"id": rid, "s": schema_id, "f": field_key, "a": alert_id, "op": op, "t": threshold},
        )
        row = _fetchone(c, _RULE_SELECT.format(t="app_schema_alert") + "WHERE r.id=:id", {"id": rid})
        return _rule_out(row, fields[field_key].get("unit"))


def _get_schema_rule(c, schema_id: str, rule_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_schema_alert WHERE id=:id AND schema_id=:s", {"id": rule_id, "s": schema_id})
    if not row:
        raise _missing("ALERT_RULE_NOT_FOUND", rule_id)
    return row


def update_schema_rule(schema_id: str, rule_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        row = _get_schema_rule(c, schema_id, rule_id)
        for key in ("fieldKey", "alertId"):
            if key in payload and payload[key] != row["field_key" if key == "fieldKey" else "alert_id"]:
                raise _bad("FIELD_IMMUTABLE", f"{key} cannot change; delete and recreate the rule")
        if "op" in payload:
            row["op"] = _op(payload)
        if "threshold" in payload:
            row["threshold"] = _threshold(payload)
        c.execute(text("UPDATE app_schema_alert SET op=:op, threshold=:threshold WHERE id=:id"), row)
        out = _fetchone(c, _RULE_SELECT.format(t="app_schema_alert") + "WHERE r.id=:id", {"id": rule_id})
        return _rule_out(out, (_schema_fields(c, schema_id).get(row["field_key"]) or {}).get("unit"))


def delete_schema_rule(schema_id: str, rule_id: str) -> None:
    with _conn() as c:
        _get_schema_rule(c, schema_id, rule_id)
        c.execute(text("DELETE FROM app_schema_alert WHERE id=:id"), {"id": rule_id})


# ---------- Table overrides + effective rules ----------
def _table(c, table_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT id, name, schema_id FROM app_device_tables WHERE id=:id", {"id": table_id})
    if not row:
        raise _missing("TABLE_NOT_FOUND", table_id)
    return row


def effective_rules(c, table_id: str) -> List[Dict[str, Any]]:
    """Schema rules merged with the table's overrides (the engine applies the same merge).

    source: "schema" (inherited), "overridden" (table changed op/threshold),
    "table" (table-only rule), "disabled" (inherited rule switched off)."""
    t = _table(c, table_id)
    fields = {r["key"]: r for r in _fetchall(c, "SELECT key, unit FROM app_schema_fields WHERE schema_id=:s", {"s": t["schema_id"]})}
    merged: Dict[tuple, Dict[str, Any]] = {}
    for r in _fetchall(c, _RULE_SELECT.format(t="app_schema_alert") + "WHERE r.schema_id=:s", {"s": t["schema_id"]}):
        item = _rule_out(r, (fields.get(r["field_key"]) or {}).get("unit"))
        item.update({"source": "schema", "schemaRuleId": r["id"], "overrideId": None, "enabled": True})
        merged[(r["field_key"], r["alert_id"])] = item
    for r in _fetchall(c, _RULE_SELECT.format(t="app_table_alert") + "WHERE r.table_id=:t", {"t": table_id}):
        key = (r["field_key"], r["alert_id"])
        base = merged.get(key)
        enabled = bool(r["enabled"])
        if base:
            item = dict(base)
            item["overrideId"] = r["id"]
            item["enabled"] = enabled
            if not enabled:
                item["source"] = "disabled"
            else:
                item["source"] = "overridden"
                item["op"] = r["op"] or base["op"]
                item["threshold"] = r["threshold"] if r["threshold"] is not None else base["threshold"]
        else:
            item = _rule_out(r, (fields.get(r["field_key"]) or {}).get("unit"))
            item.update({"source": "table", "schemaRuleId": None, "overrideId": r["id"], "enabled": enabled})
            if not enabled:
                item["source"] = "disabled"
        item.pop("id", None)
        merged[key] = item
    for item in merged.values():
        item.pop("id", None)
    return sorted(merged.values(), key=lambda x: (x["fieldKey"], -x["severity"]))


def list_table_rules(table_id: str) -> Dict[str, Any]:
    with _conn() as c:
        return {"tableId": table_id, "items": effective_rules(c, table_id)}


def set_table_override(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create or replace this table's override for (fieldKey, alertId).

    Body: {fieldKey, alertId, op?, threshold?, enabled?}. With an inherited
    schema rule, op/threshold default to it; without one, op and threshold
    are required (a table-only rule)."""
    field_key = _req_str(payload, "fieldKey", "FIELD_REQUIRED")
    alert_id = _req_str(payload, "alertId", "ALERT_LEVEL_REQUIRED")
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _bad("ENABLED_INVALID")
    with _conn() as c:
        t = _table(c, table_id)
        if not _fetchone(c, "SELECT key FROM app_schema_fields WHERE schema_id=:s AND key=:k", {"s": t["schema_id"], "k": field_key}):
            raise _bad("FIELD_UNKNOWN", f"{field_key} is not a field of this table's schema")
        _get_level(c, alert_id)
        inherited = _fetchone(
            c, "SELECT * FROM app_schema_alert WHERE schema_id=:s AND field_key=:f AND alert_id=:a",
            {"s": t["schema_id"], "f": field_key, "a": alert_id},
        )
        op = _op(payload) if "op" in payload else None
        threshold = _threshold(payload) if "threshold" in payload else None
        if not inherited and enabled and (op is None or threshold is None):
            raise _bad("RULE_REQUIRED", "no schema rule to inherit: op and threshold are required")
        c.execute(
            text("DELETE FROM app_table_alert WHERE table_id=:t AND field_key=:f AND alert_id=:a"),
            {"t": table_id, "f": field_key, "a": alert_id},
        )
        c.execute(
            text(
                "INSERT INTO app_table_alert (id, table_id, field_key, alert_id, op, threshold, enabled) "
                "VALUES (:id, :t, :f, :a, :op, :th, :en)"
            ),
            {"id": _new_id("tar"), "t": table_id, "f": field_key, "a": alert_id, "op": op, "th": threshold,
             "en": 1 if enabled else 0},
        )
        return {"tableId": table_id, "items": effective_rules(c, table_id)}


def delete_table_override(table_id: str, override_id: str) -> Dict[str, Any]:
    """Remove an override: the table falls back to the inherited schema rule (if any)."""
    with _conn() as c:
        _table(c, table_id)
        res = c.execute(text("DELETE FROM app_table_alert WHERE id=:id AND table_id=:t"), {"id": override_id, "t": table_id})
        if not res.rowcount:
            raise _missing("OVERRIDE_NOT_FOUND", override_id)
        return {"tableId": table_id, "items": effective_rules(c, table_id)}


# ---------- State + history (written by the engine) ----------
def active_alerts(table_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = (
        "SELECT s.*, a.name AS alert_name, a.severity, a.color, t.name AS table_name FROM app_alert_state s "
        "JOIN app_alert a ON a.id = s.alert_id LEFT JOIN app_device_tables t ON t.id = s.table_id "
    )
    params: Dict[str, Any] = {}
    if table_id:
        sql += "WHERE s.table_id=:t "
        params["t"] = table_id
    sql += "ORDER BY a.severity DESC, s.since"
    with _conn() as c:
        rows = _fetchall(c, sql, params)
    return [
        {"tableId": r["table_id"], "tableName": r["table_name"], "fieldKey": r["field_key"], "alertId": r["alert_id"],
         "alertName": r["alert_name"], "severity": r["severity"], "color": r["color"], "value": r["value"], "since": r["since"]}
        for r in rows
    ]


def alert_events(table_id: Optional[str] = None, frm: Optional[str] = None, to: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    where, params = [], {"lim": max(1, min(int(limit), 1000))}
    if table_id:
        where.append("e.table_id=:t")
        params["t"] = table_id
    if frm:
        where.append("e.at >= :frm")
        params["frm"] = frm
    if to:
        where.append("e.at <= :to")
        params["to"] = to
    sql = (
        "SELECT e.*, fa.name AS from_name, ta.name AS to_name, t.name AS table_name FROM app_alert_event e "
        "LEFT JOIN app_alert fa ON fa.id = e.from_alert_id LEFT JOIN app_alert ta ON ta.id = e.to_alert_id "
        "LEFT JOIN app_device_tables t ON t.id = e.table_id "
        + ("WHERE " + " AND ".join(where) + " " if where else "")
        + "ORDER BY e.at DESC LIMIT :lim"
    )
    with _conn() as c:
        rows = _fetchall(c, sql, params)
    return [
        {"id": r["id"], "tableId": r["table_id"], "tableName": r["table_name"], "fieldKey": r["field_key"],
         "from": {"alertId": r["from_alert_id"], "alertName": r["from_name"]} if r["from_alert_id"] else None,
         "to": {"alertId": r["to_alert_id"], "alertName": r["to_name"]} if r["to_alert_id"] else None,
         "value": r["value"], "op": r["op"], "threshold": r["threshold"], "jobId": r["job_id"], "at": r["at"]}
        for r in rows
    ]

