from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/echo")
async def debug_echo(req: Request):
    hdrs = dict(req.headers)
    try:
        body = (await req.body())[:512].decode(errors="ignore")
    except Exception:
        body = ""
    return {"ok": True, "headers": hdrs, "bodyPrefix": body}

