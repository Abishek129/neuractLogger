from __future__ import annotations

import os
from fastapi import APIRouter

from ..security import get_or_create_token


router = APIRouter(prefix="/auth")


@router.get("/handshake")
def handshake():
    """Return the ephemeral token and current port for the local UI.

    This endpoint is intentionally unauthenticated and intended for loopback
    clients to discover the per-run token. The auth middleware explicitly
    bypasses checks for this path.
    """
    tok = get_or_create_token()
    port = int(os.environ.get("AGENT_PORT", "0")) or None
    return {"success": True, "token": tok, "port": port}

