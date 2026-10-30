"""Electrical equipment API (see equipment.py for the model and rules).

Categories are read-only here; they are edited directly in the DB.
Mounted behind require_safe_or_write: reads need logger-read, writes need
logger-write. Every write accepts ``If-Match: <version>`` of the equipment
it changes (for bus / attachment / meter routes: the equipment that owns
the bus or node); a stale version answers 409 VERSION_CONFLICT.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, TypeVar

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .. import equipment as svc
from .. import equipment_import as imp


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/equipment")

T = TypeVar("T")


def _call(fn: Callable[..., T], *args: Any) -> T:
    try:
        return fn(*args)
    except svc.EquipmentError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except IntegrityError:
        # Lost a race against a concurrent write; the DB constraint caught it.
        logger.warning("equipment integrity conflict in %s", fn.__name__, exc_info=True)
        raise HTTPException(status_code=409, detail="CONFLICT")


def _pair(res: Dict[str, Any]) -> Dict[str, Any]:
    """Attach / detach / reorder answers: the bus (if any) as item, plus both changed equipment."""
    out: Dict[str, Any] = {"success": True, "owner": res["owner"], "attached": res["attached"]}
    if "bus" in res:
        out["item"] = res["bus"]
    return out


IfMatch = Optional[str]


# ---------- Categories (EMS / Source / BMS, read-only) ----------
@router.get("/categories")
def list_categories() -> Dict[str, Any]:
    return {"items": _call(svc.list_categories)}


# ---------- Spreadsheet import (EMS) ----------
@router.get("/import/ems/template")
def import_ems_template() -> Response:
    return Response(
        content=imp.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ems_elements_template.xlsx"'},
    )


@router.get("/export/ems")
def export_ems(typeId: Optional[str] = None) -> Response:
    """EMS elements as .xlsx in the plant template's layout (a sheet per type,
    Bus Sections, Lists)."""
    from datetime import date

    return Response(
        content=imp.export_ems_xlsx(typeId),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="ems_elements_{date.today():%Y%m%d}.xlsx"'},
    )


@router.post("/import/ems")
async def import_ems(file: UploadFile = File(...), dryRun: bool = False) -> Any:
    """Create / update EMS elements, buses and connections from a .xlsx or .csv.
    All or nothing; ?dryRun=true reports without saving."""
    data = await file.read(imp.MAX_BYTES + 1)
    try:
        report = await run_in_threadpool(imp.import_ems, file.filename or "", data, dryRun)
    except imp.ImportError_ as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    if not report["success"] and not dryRun:
        n = report["summary"]["errors"]
        return JSONResponse(
            status_code=400,
            content={"detail": f"IMPORT_INVALID: {n} row(s) have errors; nothing was saved", **report},
        )
    return report


# ---------- Zones (user-managed) ----------
@router.get("/zones")
def list_zones() -> Dict[str, Any]:
    return {"items": _call(svc.list_zones)}


@router.post("/zones")
def create_zone(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_zone, payload)}


@router.put("/zones/{zone_id}")
def update_zone(zone_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_zone, zone_id, payload)}


@router.delete("/zones/{zone_id}")
def delete_zone(zone_id: str) -> Dict[str, Any]:
    _call(svc.delete_zone, zone_id)
    return {"success": True}


# ---------- Types (user-defined) ----------
@router.get("/types")
def list_types() -> Dict[str, Any]:
    return {"items": _call(svc.list_types)}


@router.post("/types")
def create_type(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_type, payload)}


@router.put("/types/{type_id}")
def update_type(type_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_type, type_id, payload)}


@router.delete("/types/{type_id}")
def delete_type(type_id: str) -> Dict[str, Any]:
    _call(svc.delete_type, type_id)
    return {"success": True}


# ---------- Buses (by bus id) ----------
@router.put("/buses/{bus_id}/meters/{table_id}")
def assign_bus_meter(bus_id: str, table_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.assign_bus_meter, bus_id, table_id, payload, if_match)}


@router.put("/buses/{bus_id}")
def update_bus(bus_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_bus, bus_id, payload, if_match)}


@router.delete("/buses/{bus_id}")
def delete_bus(bus_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    _call(svc.delete_bus, bus_id, if_match)
    return {"success": True}


@router.post("/buses/{bus_id}/meters")
def attach_bus_meter(bus_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.attach_bus_meter, bus_id, payload, if_match)}


@router.delete("/buses/{bus_id}/meters/{table_id}")
def detach_bus_meter(bus_id: str, table_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.detach_bus_meter, bus_id, table_id, if_match)}


@router.post("/buses/{bus_id}/equipment")
def attach_equipment(bus_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.attach_equipment, bus_id, payload, if_match))


@router.put("/buses/{bus_id}/equipment/{eq_id}")
def move_attachment(bus_id: str, eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.move_attachment, bus_id, eq_id, payload, if_match))


@router.delete("/buses/{bus_id}/equipment/{eq_id}")
def detach_equipment(bus_id: str, eq_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.detach_equipment, bus_id, eq_id, if_match))


@router.get("/available_meters")
def available_meters() -> Dict[str, Any]:
    return {"items": _call(svc.available_meters)}


# ---------- Equipment ----------
@router.get("")
def list_equipment(
    categoryId: Optional[str] = None,
    kind: Optional[str] = None,
    typeId: Optional[str] = None,
    zoneId: Optional[str] = None,
    q: Optional[str] = None,
    metered: Optional[str] = None,
    ready: Optional[str] = None,
    used: Optional[str] = None,
    spare: Optional[str] = None,
) -> Dict[str, Any]:
    return {"items": _call(svc.list_equipment, categoryId, kind, typeId, q, metered, ready, used, spare, zoneId)}


@router.post("")
def create_equipment(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_equipment, payload)}


@router.get("/{eq_id}")
def get_equipment(eq_id: str) -> Dict[str, Any]:
    return {"item": _call(svc.get_equipment, eq_id)}


@router.put("/{eq_id}")
def update_equipment(eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.update_equipment, eq_id, payload, if_match)}


@router.delete("/{eq_id}")
def delete_equipment(eq_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    _call(svc.delete_equipment, eq_id, if_match)
    return {"success": True}


# ---------- Buses (of an equipment) ----------
@router.get("/{eq_id}/buses")
def list_buses(eq_id: str) -> Dict[str, Any]:
    return {"items": _call(svc.list_buses, eq_id)}


@router.post("/{eq_id}/buses")
def create_bus(eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "item": _call(svc.create_bus, eq_id, payload, if_match)}


@router.put("/{eq_id}/buses/count")
def set_bus_count(eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "items": _call(svc.set_bus_count, eq_id, payload, if_match)}


# ---------- Direct links (single -> single) ----------
@router.post("/{eq_id}/connections")
def connect_direct(eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.connect_direct, eq_id, payload, if_match))


@router.put("/{eq_id}/connections/{target_id}")
def move_direct(eq_id: str, target_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.move_direct, eq_id, target_id, payload, if_match))


@router.delete("/{eq_id}/connections/{target_id}")
def disconnect_direct(eq_id: str, target_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return _pair(_call(svc.disconnect_direct, eq_id, target_id, if_match))


# ---------- MFMs ----------
@router.get("/{eq_id}/meters")
def list_meters(eq_id: str) -> Dict[str, Any]:
    return {"items": _call(svc.list_meters, eq_id)}


@router.post("/{eq_id}/meters")
def attach_meter(eq_id: str, payload: Dict[str, Any], if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "items": _call(svc.attach_meter, eq_id, payload, if_match)}


@router.delete("/{eq_id}/meters/{table_id}")
def detach_meter(eq_id: str, table_id: str, if_match: IfMatch = Header(default=None)) -> Dict[str, Any]:
    return {"success": True, "items": _call(svc.detach_meter, eq_id, table_id, if_match)}
