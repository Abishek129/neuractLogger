from __future__ import annotations

import time
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from ..store import Store


router = APIRouter(prefix="/devices")


@router.get("")
def list_devices() -> Dict[str, Any]:
    return {"items": Store.instance().list_devices()}


@router.post("")
def create_device(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Enforce uniqueness by name
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="NAME_REQUIRED")
    items = Store.instance().list_devices()
    for d in items:
        if (d.get("name") or "").lower() == name.lower():
            return {"success": True, "item": d}
    # Fast connectivity test prior to save
    proto = (payload.get("protocol") or "").lower()
    params = payload.get("params") or {}
    try:
        if proto == "opcua":
            ep = (params.get("endpoint") or "").strip()
            if not ep:
                raise HTTPException(status_code=400, detail="ENDPOINT_REQUIRED")
            if "0.0.0.0" in ep:
                ep = ep.replace("0.0.0.0", "127.0.0.1")
            try:
                from opcua import Client  # type: ignore
            except Exception:
                raise HTTPException(status_code=400, detail="OPCUA_PKG_MISSING")
            try:
                c = Client(ep)
                c.connect(); c.disconnect()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"TEST_FAILED: {e}")
        elif proto == "modbus":
            host = (params.get("host") or params.get("ip") or "").strip()
            port = int(params.get("port", 502))
            if not host:
                raise HTTPException(status_code=400, detail="HOST_REQUIRED")
            try:
                from pymodbus.client import ModbusTcpClient  # type: ignore
            except Exception:
                raise HTTPException(status_code=400, detail="PYMODBUS_MISSING")
            client = ModbusTcpClient(host=host, port=port)
            ok = False
            try:
                ok = client.connect()
            finally:
                try: client.close()
                except Exception: pass
            if not ok:
                raise HTTPException(status_code=400, detail="TEST_FAILED")
        else:
            raise HTTPException(status_code=400, detail="PROTOCOL_INVALID")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"TEST_FAILED: {e}")
    item = Store.instance().add_device(payload)
    return {"success": True, "item": item}


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
    item = Store.instance().get_device(dev_id)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    # For now: optimistic connect; a real connector would establish session
    Store.instance().set_device_status(dev_id, status="connected", latency_ms=0)
    return {"success": True}


@router.post("/{dev_id}/disconnect")
def disconnect_device(dev_id: str) -> Dict[str, Any]:
    item = Store.instance().get_device(dev_id)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    Store.instance().set_device_status(dev_id, status="disconnected", latency_ms=None)
    return {"success": True}


@router.post("/{dev_id}/quick_test")
def quick_test(dev_id: str) -> Dict[str, Any]:
    item = Store.instance().get_device(dev_id)
    if not item:
        raise HTTPException(status_code=404, detail="DEVICE_NOT_FOUND")
    # Simulate a quick probe
    t = int(20 + (time.time() * 1000) % 100)
    Store.instance().set_device_status(dev_id, status="connected", latency_ms=t)
    return {"success": True, "latencyMs": t}
