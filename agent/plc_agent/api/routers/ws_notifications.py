from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ws_auth import ws_accept_or_reject

log = logging.getLogger(__name__)

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/3")


@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    """Real-time notification stream via WebSocket.

    Authenticates using JWT (Authorization header or ?token= query param).
    Requires logger-read role.
    Subscribes to Redis pub/sub channel "logger_read" and forwards messages.
    """
    claims = await ws_accept_or_reject(ws)
    if claims is None:
        return

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe("logger_read")
    except Exception as e:
        log.error("Redis connection failed for WebSocket: %s", e)
        await ws.close(code=1011)
        return

    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if msg and msg["type"] == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await ws.send_text(data)
            else:
                await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        log.debug("WebSocket client disconnected")
    except Exception as e:
        log.debug("WebSocket error: %s", e)
    finally:
        await pubsub.unsubscribe("logger_read")
        await pubsub.aclose()
        await r.aclose()
