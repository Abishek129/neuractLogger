from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

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


@router.websocket("/ws/live/{table_id}")
async def ws_live_table(ws: WebSocket, table_id: str):
    """Live stream of device reads for a table.

    Authenticates using JWT (?token= query param or Authorization header).
    Reads mapping for the table, then continuously reads from the device
    and sends field values as JSON every ~1 second.

    Query params:
      - token: JWT token
      - interval: read interval in ms (default 1000, min 500)
    """
    claims = await ws_accept_or_reject(ws)
    if claims is None:
        return

    from urllib.parse import parse_qs
    qs = parse_qs(ws.scope.get("query_string", b"").decode("utf-8", errors="ignore"))
    interval_ms = 1000
    try:
        interval_ms = max(500, int(qs.get("interval", ["1000"])[0]))
    except (ValueError, IndexError):
        pass
    interval_s = interval_ms / 1000.0

    try:
        from .jobs2 import _read_mapping_values
        from ..store import Store

        # Validate table exists
        store = Store.instance()
        t = store.get_table(table_id)
        if not t:
            await ws.send_text(json.dumps({"error": "TABLE_NOT_FOUND"}))
            await ws.close(code=1008)
            return

        table_name = t.get("name", table_id)
        log.info("ws_live started table=%s interval=%dms user=%s",
                 table_id, interval_ms, claims.get("preferred_username", "?"))

        while True:
            try:
                values = await asyncio.get_event_loop().run_in_executor(
                    None, _read_mapping_values, table_id
                )
                # Convert non-JSON-safe values
                safe = {}
                for k, v in values.items():
                    if isinstance(v, float):
                        safe[k] = round(v, 6)
                    elif v is None or isinstance(v, (int, bool, str)):
                        safe[k] = v
                    else:
                        safe[k] = str(v)

                msg = {
                    "tableId": table_id,
                    "tableName": table_name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "values": safe,
                    "fields": len(safe),
                }
                await ws.send_text(json.dumps(msg))
            except Exception as e:
                err_msg = {"tableId": table_id, "error": str(e),
                           "ts": datetime.now(timezone.utc).isoformat()}
                await ws.send_text(json.dumps(err_msg))

            await asyncio.sleep(interval_s)

    except WebSocketDisconnect:
        log.debug("ws_live client disconnected table=%s", table_id)
    except Exception as e:
        log.warning("ws_live error table=%s: %s", table_id, e)
    finally:
        log.info("ws_live ended table=%s", table_id)
