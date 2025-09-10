from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from sqlalchemy import create_engine

from ..store import Store
from .. import appdb


router = APIRouter(prefix="/storage")


@router.get("/targets")
def list_targets() -> Dict[str, Any]:
    # Internal structure kept in store; expose safe metadata
    items = []
    for v in Store.instance()._db_targets.values():  # type: ignore[attr-defined]
        items.append({"id": v.get("id"), "provider": v.get("provider"), "conn": v.get("conn"), "status": v.get("status"), "lastMsg": v.get("lastMsg")})
    return {"items": items, "defaultId": Store.instance().get_default_db_target()}


@router.post("/targets")
def add_target(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        item = Store.instance().add_db_target(payload)
        return {"success": True, "item": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/targets/{tid}")
def update_target(tid: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = Store.instance().get_db_target(tid)
    if not cur:
        raise HTTPException(status_code=404, detail="not_found")
    cur.update({k: v for k, v in patch.items() if k in ("provider", "conn", "status", "lastMsg")})
    return {"success": True, "item": cur}


@router.delete("/targets/{tid}")
def delete_target(tid: str, force: bool = False) -> Dict[str, Any]:
    st = Store.instance()
    # Check existence
    cur = st.get_db_target(tid)
    if not cur:
        raise HTTPException(status_code=404, detail="TARGET_NOT_FOUND")
    # Block if default
    if st.get_default_db_target() == tid:
        raise HTTPException(status_code=400, detail="TARGET_IS_DEFAULT")
    # Block if referenced by device tables
    used = appdb.count_tables_referencing_target(tid)
    if used > 0 and not force:
        # Policy 1 (block)
        raise HTTPException(status_code=400, detail="TARGET_IN_USE")
    # Remove
    st._db_targets.pop(tid, None)  # type: ignore[attr-defined]
    appdb.delete_target(tid)
    return {"success": True}


@router.post("/targets/test")
def test_target(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_id = payload.get("id")
    target = Store.instance().get_db_target(target_id) if target_id else payload
    if not target:
        raise HTTPException(status_code=404, detail="not_found")
    provider = (target.get("provider") or "sqlite").lower()
    conn = target.get("conn") or ":memory:"
    try:
        if provider == "sqlite":
            url = f"sqlite:///{conn}" if not str(conn).startswith("sqlite:") else conn
        elif provider == "postgres":
            url = conn
        elif provider == "sqlserver":
            url = conn
        elif provider == "mysql":
            url = conn
        else:
            return {"ok": False, "message": "provider_not_supported"}
        engine = create_engine(url)
        with engine.connect() as _:
            pass
        Store.instance().add_db_target({"id": target.get("id"), "provider": provider, "conn": conn, "status": "ok", "lastMsg": "Test OK"})
        return {"ok": True, "message": "Connection OK"}
    except Exception as e:
        Store.instance().add_db_target({"id": target.get("id"), "provider": provider, "conn": conn, "status": "fail", "lastMsg": str(e)})
        return {"ok": False, "message": "DB_TARGET_UNREACHABLE", "error": str(e)}


@router.post("/targets/default")
def set_default(payload: Dict[str, Any]) -> Dict[str, Any]:
    tid = payload.get("id")
    if not tid:
        raise HTTPException(status_code=400, detail="id required")
    if not Store.instance().get_db_target(tid):
        raise HTTPException(status_code=404, detail="not_found")
    Store.instance().set_default_db_target(tid)
    return {"ok": True, "defaultId": tid}


@router.post("/targets/create_db")
def create_db(payload: Dict[str, Any]) -> Dict[str, Any]:
    target_id = payload.get("id")
    target = Store.instance().get_db_target(target_id) if target_id else payload
    if not target:
        raise HTTPException(status_code=404, detail="not_found")
    provider = (target.get("provider") or "sqlite").lower()
    conn = target.get("conn") or ":memory:"
    if provider != "sqlite":
        return {"ok": False, "message": "only_sqlite_supported_in_stub"}
    url = f"sqlite:///{conn}" if not str(conn).startswith("sqlite:") else conn
    try:
        engine = create_engine(url)
        with engine.begin() as _:
            pass
        return {"ok": True, "message": "db_ready"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
