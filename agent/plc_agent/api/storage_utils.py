from __future__ import annotations

from typing import Dict, Any

from sqlalchemy import create_engine

from .store import Store


def test_connection(target: Dict[str, Any]) -> Dict[str, Any]:
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
        with engine.connect():
            pass
        Store.instance().add_db_target({
            "id": target.get("id"),
            "provider": provider,
            "conn": conn,
            "status": "ok",
            "lastMsg": "Test OK",
        })
        return {"ok": True, "message": "Connection OK"}
    except Exception as e:
        Store.instance().add_db_target({
            "id": target.get("id"),
            "provider": provider,
            "conn": conn,
            "status": "fail",
            "lastMsg": str(e),
        })
        return {"ok": False, "message": "DB_TARGET_UNREACHABLE", "error": str(e)}
