from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from ..permissions import require_logger_write

from ..store import Store

import re


router = APIRouter()

VALID_FIELD_TYPES = {
    "float32", "float", "uint16", "uint16_enum", "int16",
    "uint32", "int32", "float64", "uint64", "int64", "bool16",
}


@router.get("/schemas")
def list_schemas() -> Dict[str, List[Dict[str, Any]]]:
    # Logical parent schemas from in-memory store (no DDL)
    return {"items": Store.instance().list_schemas()}


@router.post("/schemas", dependencies=[Depends(require_logger_write)])
def create_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Expected payload: { id?: str, name: str, fields: [{ key, type, unit?, scale?, desc? }] }
    try:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("NAME_REQUIRED")
        fields = payload.get("fields") or []
        seen = set()
        for f in fields:
            k = (f.get("key") or "").strip()
            if not k:
                raise ValueError("FIELD_KEY_REQUIRED")
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                raise ValueError(f"FIELD_KEY_INVALID:{k}")
            if k in seen:
                raise ValueError(f"FIELD_KEY_DUPLICATE:{k}")
            seen.add(k)
            ftype = (f.get("type") or "float32").lower()
            if ftype not in VALID_FIELD_TYPES:
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
            f["type"] = ftype
        schema = Store.instance().create_schema({
            "id": payload.get("id"),
            "name": name,
            "fields": fields,
        })
        return {"success": True, "message": "schema_created", "item": schema}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/schemas/{schema_id}/fields", dependencies=[Depends(require_logger_write)])
def add_schema_field(schema_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add a single field to a schema. Payload: { key, type, unit?, scale?, desc? }"""
    try:
        key = (payload.get("key") or "").strip()
        if not key:
            raise ValueError("FIELD_KEY_REQUIRED")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"FIELD_KEY_INVALID:{key}")
        ftype = (payload.get("type") or "float32").lower()
        if ftype not in VALID_FIELD_TYPES:
            raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
        field = {
            "key": key,
            "type": ftype,
            "unit": payload.get("unit"),
            "scale": payload.get("scale"),
            "desc": payload.get("desc"),
        }
        schema = Store.instance().add_schema_field(schema_id, field)
        return {"success": True, "item": schema}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/schemas/{schema_id}", dependencies=[Depends(require_logger_write)])
def delete_schema(schema_id: str) -> Dict[str, Any]:
    """Delete a schema and all its fields. Fails if tables reference it."""
    try:
        deleted = Store.instance().delete_schema(schema_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="SCHEMA_NOT_FOUND")
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/schemas/{schema_id}/fields/{field_key}", dependencies=[Depends(require_logger_write)])
def delete_schema_field(schema_id: str, field_key: str) -> Dict[str, Any]:
    """Delete a single field from a schema."""
    try:
        deleted = Store.instance().delete_schema_field(schema_id, field_key)
        if not deleted:
            raise HTTPException(status_code=404, detail="FIELD_NOT_FOUND")
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schemas/export")
def export_schemas() -> Dict[str, Any]:
    return {"schemas": Store.instance().list_schemas()}


@router.post("/schemas/import", dependencies=[Depends(require_logger_write)])
def import_schemas(payload: Dict[str, Any]) -> Dict[str, Any]:
    count = Store.instance().import_schemas(payload.get("schemas") or payload.get("items") or [])
    return {"imported": count}
