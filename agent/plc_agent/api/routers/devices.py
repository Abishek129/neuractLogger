from __future__ import annotations

import time
from typing import Dict, Any

import logging
from fastapi import APIRouter, HTTPException

from ..store import Store


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices")


@router.get("")
def list_devices() -> Dict[str, Any]:
    return {"items": Store.instance().list_devices()}


@router.post("")
def create_device(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="NAME_REQUIRED")
    items = Store.instance().list_devices()
    for d in items:
        if (d.get("name") or "").lower() == name.lower():
            return {"success": True, "item": d}
    proto = (payload.get("protocol") or "").lower()
    params = payload.get("params") or {}
    ok, latency, err = Store.instance().test_device_params(proto, params)
    item = Store.instance().add_device(payload)
    if ok:
        Store.instance().mark_manual_disconnect(item["id"], False)
        Store.instance().set_device_status(item["id"], status="connected", latency_ms=latency, last_error=None)
    else:
        Store.instance().set_device_status(item["id"], status="degraded", latency_ms=None, last_error=err or "TEST_FAILED")
    stored = Store.instance().get_device(item["id"]) or item
    return {"success": ok, "item": stored, "error": err}


@router.put("/{dev_id}")
def update_device(dev_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    # Allow updating name and autoReconnect
    allowed = {k: v for k, v in patch.items() if k in ("name", "autoReconnect")}
    item = Store.instance().update_device_metadata(dev_id, allowed)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    return {"success": True, "item": item}


@router.delete("/{dev_id}")
def delete_device(dev_id: str) -> Dict[str, Any]:
    ok = Store.instance().delete_device(dev_id)
    if not ok:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    return {"success": True}


@router.post("/{dev_id}/connect")
def connect_device(dev_id: str) -> Dict[str, Any]:
    raw = Store.instance().get_device(dev_id)
    if not raw:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    try:
        ok, latency, err = Store.instance().test_device_connection(dev_id)
    except Exception as exc:  # Defensive: avoid leaking stack traces to client
        logger.exception("Device connect test errored", extra={"device_id": dev_id})
        raise HTTPException(status_code=400, detail=str(exc) or "CONNECT_FAILED")
    if not ok:
        Store.instance().set_device_status(dev_id, status="degraded", latency_ms=None, last_error=err or "CONNECT_FAILED")
        raise HTTPException(status_code=400, detail=err or "CONNECT_FAILED")
    Store.instance().mark_manual_disconnect(dev_id, False)
    try:
        Store.instance().set_device_status(dev_id, status="connected", latency_ms=latency, last_error=None)
    except Exception as exc:
        logger.exception("Failed to persist connected state", extra={"device_id": dev_id})
        raise HTTPException(status_code=400, detail=str(exc) or "CONNECT_FAILED")
    return {"success": True, "latencyMs": latency}


@router.post("/{dev_id}/disconnect")
def disconnect_device(dev_id: str) -> Dict[str, Any]:
    item = Store.instance().get_device(dev_id)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    try:
        Store.instance().set_device_status(dev_id, status="disconnected", latency_ms=None, last_error=None)
    except Exception as exc:
        logger.exception("Failed to mark device disconnected", extra={"device_id": dev_id})
        raise HTTPException(status_code=400, detail=str(exc) or "DISCONNECT_FAILED")
    Store.instance().mark_manual_disconnect(dev_id, True)
    return {"success": True}


@router.post("/{dev_id}/quick_test")
def quick_test(dev_id: str) -> Dict[str, Any]:
    item = Store.instance().get_device(dev_id)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    try:
        ok, latency, err = Store.instance().test_device_connection(dev_id)
    except Exception as exc:
        logger.exception("Quick test errored", extra={"device_id": dev_id})
        ok, latency, err = False, 0, str(exc)
    if ok:
        Store.instance().mark_manual_disconnect(dev_id, False)
        try:
            Store.instance().set_device_status(dev_id, status="connected", latency_ms=latency, last_error=None)
        except Exception as exc:
            logger.exception("Failed to persist quick-test connected state", extra={"device_id": dev_id})
            ok = False
            err = err or str(exc) or "TEST_FAILED"
    else:
        try:
            Store.instance().set_device_status(dev_id, status="degraded", latency_ms=None, last_error=err or "TEST_FAILED")
        except Exception as exc:
            logger.exception("Failed to persist quick-test degraded state", extra={"device_id": dev_id})
            err = err or str(exc) or "TEST_FAILED"
    return {"success": ok, "latencyMs": latency, "error": err}
