from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logging
from fastapi import APIRouter, Depends, HTTPException

from ..equipment import EquipmentError
from ..permissions import require_logger_write

from .. import appdb
from ..store import Store


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices")


def _with_verification(item: Optional[Dict[str, Any]], saved: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Attach the last saved quick_test result as `verification` (null if never verified)."""
    if not item:
        return item
    saved = saved if saved is not None else appdb.load_device_verifications()
    return {**item, "verification": saved.get(item.get("id"))}


@router.get("")
def list_devices() -> Dict[str, Any]:
    saved = appdb.load_device_verifications()
    return {"items": [_with_verification(d, saved) for d in Store.instance().list_devices()]}


@router.post("", dependencies=[Depends(require_logger_write)])
def create_device(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="NAME_REQUIRED")
    items = Store.instance().list_devices()
    for d in items:
        if (d.get("name") or "").lower() == name.lower():
            return {"success": True, "item": d}
    proto = (payload.get("protocol") or "").strip().lower()
    if proto and not Store.instance().is_valid_protocol(proto):
        raise HTTPException(
            status_code=400,
            detail=f"PROTOCOL_INVALID: '{proto}'. Valid: {', '.join(Store.instance().list_protocol_types())}"
        )
    params = payload.get("params") or {}
    extra = {}
    if payload.get("gatewayId"):
        extra["gatewayId"] = payload["gatewayId"]
    if payload.get("port") is not None:
        extra["port"] = payload["port"]
    if payload.get("unitId") is not None:
        extra["unitId"] = payload["unitId"]
    ok, latency, err = Store.instance().test_device_params(proto or "modbus", params, **extra)
    item = Store.instance().add_device(payload)
    if ok:
        Store.instance().mark_manual_disconnect(item["id"], False)
        Store.instance().set_device_status(item["id"], status="connected", latency_ms=latency, last_error=None)
    else:
        Store.instance().set_device_status(item["id"], status="degraded", latency_ms=None, last_error=err or "TEST_FAILED")
    stored = Store.instance().get_device(item["id"]) or item
    return {"success": ok, "item": stored, "error": err}


@router.put("/{dev_id}", dependencies=[Depends(require_logger_write)])
def update_device(dev_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Partial update. Metadata: name, autoReconnect, unitId, port, gatewayId
    (null = direct device), nominalVoltage. Connection: protocol and params (host, endpoint,
    ... merged into the stored params; null removes a key). Changing the
    address resets the device to "disconnected" and clears its verification."""
    store = Store.instance()
    if not store.get_device(dev_id):
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    proto = patch.get("protocol")
    if proto is not None:
        if not isinstance(proto, str) or not store.is_valid_protocol(proto.strip()):
            raise HTTPException(
                status_code=400,
                detail=f"PROTOCOL_INVALID: '{proto}'. Valid: {', '.join(store.list_protocol_types())}",
            )
    params = patch.get("params")
    if params is not None and not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="PARAMS_INVALID: params must be an object")
    allowed = {
        k: v for k, v in patch.items()
        if k in ("name", "autoReconnect", "unitId", "port", "gatewayId", "nominalVoltage") and v is not None
    }
    try:
        item = store.update_device_metadata(dev_id, allowed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    clear_gateway = "gatewayId" in patch and patch["gatewayId"] is None
    if proto is not None or params is not None or clear_gateway:
        item = store.update_device_connection(
            dev_id, protocol=proto.strip() if isinstance(proto, str) else None, params=params, clear_gateway=clear_gateway
        )
    return {"success": True, "item": _with_verification(item)}


@router.delete("/{dev_id}", dependencies=[Depends(require_logger_write)])  # SEC-3/C6
def delete_device(dev_id: str) -> Dict[str, Any]:
    try:
        ok = Store.instance().delete_device(dev_id)
    except EquipmentError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    if not ok:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    return {"success": True}


@router.post("/{dev_id}/connect", dependencies=[Depends(require_logger_write)])
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


@router.post("/{dev_id}/disconnect", dependencies=[Depends(require_logger_write)])
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


@router.post("/{dev_id}/quick_test", dependencies=[Depends(require_logger_write)])
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
    # F8: keep the result; GET /devices returns it as `verification`.
    verification = {"ok": bool(ok), "latencyMs": latency if ok else None, "error": None if ok else (err or "TEST_FAILED"),
                    "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")}
    try:
        appdb.save_device_verification(dev_id, verification["ok"], verification["latencyMs"], verification["error"], verification["at"])
    except Exception:
        logger.exception("Failed to save verification", extra={"device_id": dev_id})
    return {"success": ok, "latencyMs": latency, "error": err, "verification": verification}
