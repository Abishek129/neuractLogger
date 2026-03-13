from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException

from ..store import Store
from .. import appdb

router = APIRouter(prefix="/protocol_types")


@router.get("")
def list_protocol_types() -> Dict[str, Any]:
    """List all valid protocol types."""
    return {"items": Store.instance().list_protocol_types()}


@router.post("")
def create_protocol_type(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a new protocol type.
    Body: {"type": "protocol_name"}
    """
    protocol_type = (payload.get("type") or "").strip().lower()
    if not protocol_type:
        raise HTTPException(status_code=400, detail="TYPE_REQUIRED")

    try:
        item = appdb.add_protocol_type(protocol_type)
        Store.instance().refresh_protocol_types()
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{protocol_type}")
def delete_protocol_type(protocol_type: str) -> Dict[str, Any]:
    """Delete a protocol type. Fails if devices are using it."""
    # Check usage in devices
    devices = Store.instance().list_devices()
    using_devices = [d for d in devices if d.get("protocol", "").lower() == protocol_type.lower()]

    if using_devices:
        raise HTTPException(
            status_code=400,
            detail=f"PROTOCOL_IN_USE: {len(using_devices)} device(s) using this protocol"
        )

    # Check usage in gateways
    gateways = Store.instance().list_gateways()
    using_gateways = [g for g in gateways if (g.get("protocol_hint") or "").lower() == protocol_type.lower()]

    if using_gateways:
        raise HTTPException(
            status_code=400,
            detail=f"PROTOCOL_IN_USE: {len(using_gateways)} gateway(s) using this protocol"
        )

    ok = appdb.delete_protocol_type(protocol_type)
    if not ok:
        raise HTTPException(status_code=404, detail="PROTOCOL_TYPE_NOT_FOUND")

    Store.instance().refresh_protocol_types()
    return {"success": True}
