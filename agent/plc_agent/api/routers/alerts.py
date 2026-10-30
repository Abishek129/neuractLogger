"""Alerts on readings API (see alerts.py for the model).

Mounted behind require_safe_or_write: reads need logger-read, writes logger-write.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TypeVar

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError

from .. import alerts as svc

router = APIRouter()
T = TypeVar("T")


def _call(fn: Callable[..., T], *args: Any) -> T:
    try:
        return fn(*args)
    except svc.AlertError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="CONFLICT")


# ---------- Levels ----------
@router.get("/alerts/levels")
def list_levels() -> Dict[str, Any]:
    return {"items": _call(svc.list_levels)}


@router.post("/alerts/levels")
def create_level(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_level, payload)}


@router.put("/alerts/levels/{alert_id}")
def update_level(alert_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_level, alert_id, payload)}


@router.delete("/alerts/levels/{alert_id}")
def delete_level(alert_id: str) -> Dict[str, Any]:
    _call(svc.delete_level, alert_id)
    return {"success": True}


# ---------- State + history ----------
@router.get("/alerts/active")
def active(tableId: Optional[str] = None) -> Dict[str, Any]:
    return {"items": _call(svc.active_alerts, tableId)}


@router.get("/alerts/events")
def events(tableId: Optional[str] = None, frm: Optional[str] = None, to: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    return {"items": _call(svc.alert_events, tableId, frm, to, limit)}


# ---------- Schema rules (blueprint) ----------
@router.get("/schemas/{schema_id}/alerts")
def list_schema_rules(schema_id: str) -> Dict[str, Any]:
    return {"items": _call(svc.list_schema_rules, schema_id)}


@router.post("/schemas/{schema_id}/alerts")
def create_schema_rule(schema_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_schema_rule, schema_id, payload)}


@router.put("/schemas/{schema_id}/alerts/{rule_id}")
def update_schema_rule(schema_id: str, rule_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_schema_rule, schema_id, rule_id, payload)}


@router.delete("/schemas/{schema_id}/alerts/{rule_id}")
def delete_schema_rule(schema_id: str, rule_id: str) -> Dict[str, Any]:
    _call(svc.delete_schema_rule, schema_id, rule_id)
    return {"success": True}


# ---------- Table overrides / effective rules ----------
@router.get("/tables/{table_id}/alerts")
def list_table_rules(table_id: str) -> Dict[str, Any]:
    return _call(svc.list_table_rules, table_id)


@router.put("/tables/{table_id}/alerts")
def set_table_override(table_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, **_call(svc.set_table_override, table_id, payload)}


@router.delete("/tables/{table_id}/alerts/{override_id}")
def delete_table_override(table_id: str, override_id: str) -> Dict[str, Any]:
    return {"success": True, **_call(svc.delete_table_override, table_id, override_id)}
