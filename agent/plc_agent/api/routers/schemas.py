from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from ..store import Store

import re


router = APIRouter()


@router.get("/schemas")
def list_schemas() -> Dict[str, List[Dict[str, Any]]]:
    # Logical parent schemas from in-memory store (no DDL)
    return {"items": Store.instance().list_schemas()}


@router.post("/schemas")
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
        schema = Store.instance().create_schema({
            "id": payload.get("id"),
            "name": name,
            "fields": fields,
        })
        return {"success": True, "message": "schema_created", "item": schema}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schemas/export")
def export_schemas() -> Dict[str, Any]:
    return {"schemas": Store.instance().list_schemas()}


@router.post("/schemas/import")
def import_schemas(payload: Dict[str, Any]) -> Dict[str, Any]:
    count = Store.instance().import_schemas(payload.get("schemas") or payload.get("items") or [])
    return {"imported": count}
