from __future__ import annotations

import os
import secrets
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
import logging


def get_or_create_token() -> str:
    tok = os.environ.get("AGENT_TOKEN")
    if not tok:
        tok = secrets.token_urlsafe(24)
        os.environ["AGENT_TOKEN"] = tok
    return tok


def auth_middleware() -> Callable:
    token = get_or_create_token()

    async def middleware(request: Request, call_next):
        # Allow unauthenticated access for local handshake and basic liveness
        path = request.url.path or ""
        if path in ("/auth/handshake", "/health", "/version"):
            return await call_next(request)

        hdr = request.headers.get("x-agent-token") or request.headers.get("authorization")
        provided = None
        if hdr:
            if hdr.lower().startswith("bearer "):
                provided = hdr.split(" ", 1)[1]
            else:
                provided = hdr
        if provided != token:
            try:
                logging.getLogger(__name__).debug(
                    "Auth failed path=%s provided=%s expected=%s",
                    path,
                    (provided[:4] + "…" + provided[-4:]) if provided else None,
                    (token[:4] + "…" + token[-4:]) if token else None,
                )
            except Exception:
                pass
            resp = JSONResponse(status_code=401, content={
                "success": False,
                "error": "PERMISSION_DENIED",
                "message": "Missing or invalid token",
            })
            try:
                resp.headers["WWW-Authenticate"] = "Bearer realm=plc-agent"
            except Exception:
                pass
            return resp
        return await call_next(request)

    return middleware
