from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from fastapi import WebSocket, status

from .security import decode_jwt
from .permissions import has_logger_read_role

log = logging.getLogger(__name__)


async def authenticate_websocket(ws: WebSocket) -> Optional[Dict[str, Any]]:
    """Authenticate a WebSocket connection.

    Extracts token from:
      1. Authorization header
      2. ?token= query parameter
    Returns claims dict on success, None on failure.
    """
    token: Optional[str] = None

    auth_header = ws.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()

    if not token:
        query_str = ws.scope.get("query_string", b"").decode("utf-8", errors="ignore")
        params = parse_qs(query_str)
        token_list = params.get("token")
        if token_list:
            token = token_list[0]

    if not token:
        log.debug("WebSocket auth: no token provided")
        return None

    try:
        claims = decode_jwt(token)
    except Exception as e:
        log.debug("WebSocket auth: JWT validation failed: %s", e)
        return None

    if not has_logger_read_role(claims):
        log.debug("WebSocket auth: missing logger-read role")
        return None

    return claims


async def ws_accept_or_reject(ws: WebSocket) -> Optional[Dict[str, Any]]:
    """Accept the WebSocket if authenticated with logger-read role, else close.

    Usage:
        @router.websocket("/ws/live")
        async def live(ws: WebSocket):
            claims = await ws_accept_or_reject(ws)
            if claims is None:
                return
            # ... proceed with authenticated connection
    """
    claims = await authenticate_websocket(ws)
    if claims is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    await ws.accept()
    ws.scope["auth"] = claims
    return claims
