from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status

# from ..permissions import require_logger_read
from ..appdb import create_notification, list_notifications, NOTIFICATION_TYPES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/3")


async def _publish_to_redis(channel: str, payload: dict) -> None:
    """Publish a message to a Redis pub/sub channel."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.publish(channel, json.dumps(payload))
        await r.aclose()
    except Exception as e:
        log.warning("Redis publish failed: %s", e)


async def notify_job_started(job_id: str, started_by: str) -> None:
    """Create a 'job' notification for every user with the logger_read realm role.

    Called as a BackgroundTask from start_job endpoints.
    """
    try:
        from ..keycloak_admin import get_service_account_token, get_users_by_realm_role

        token = await get_service_account_token()
        users = await get_users_by_realm_role(token, "logger_read")

        message = f"Job {job_id} was started by {started_by}"

        for user in users:
            user_id = user.get("id", "unknown")
            try:
                notif = create_notification("job", message, user_id)
                ws_payload = {
                    "type": notif["type"],
                    "action": "create",
                    "notification_id": notif["id"],
                    "message": notif["message"],
                    "user": notif["user"],
                    "read": notif["read"],
                    "time": notif["time"],
                }
                await _publish_to_redis("logger_read", ws_payload)
            except Exception as e:
                log.warning("Failed to create notification for user %s: %s", user_id, e)
    except Exception as e:
        log.error("notify_job_started failed: %s", e)


@router.post("/notifications", status_code=201)
async def create(
    payload: Dict[str, Any],
    request: Request,
    # claims: Dict[str, Any] = Depends(require_logger_read),
):
    """Create a notification and broadcast via Redis pub/sub.

    Body: {"message": "...", "type": "job"} (type optional, defaults to "job")
    """
    # user_uuid = claims.get("sub")
    # if not user_uuid:
    #     raise HTTPException(status_code=400, detail="User id not found in token")
    user_uuid = "anonymous"

    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    notif_type = payload.get("type", "job")
    if notif_type not in NOTIFICATION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type. Must be one of: {', '.join(sorted(NOTIFICATION_TYPES))}",
        )

    notif = create_notification(notif_type, message, user_uuid)

    ws_payload = {
        "type": notif["type"],
        "action": "create",
        "notification_id": notif["id"],
        "message": notif["message"],
        "user": notif["user"],
        "read": notif["read"],
        "time": notif["time"],
    }
    await _publish_to_redis("logger_read", ws_payload)

    return {"ok": True, **notif}


@router.get("/notifications/list")
async def list_all(
    request: Request,
    # claims: Dict[str, Any] = Depends(require_logger_read),
):
    """List notifications for the current user."""
    # user_uuid = claims.get("sub")
    # if not user_uuid:
    #     raise HTTPException(status_code=400, detail="User id not found in token")
    user_uuid = "anonymous"

    return list_notifications(user_uuid)
