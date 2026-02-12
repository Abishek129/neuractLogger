from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from ..keycloak_admin import (
    KeycloakAdminError,
    get_service_account_token,
    create_user,
    set_user_password,
    get_user_id_by_username,
    get_client_uuid,
    get_client_role,
    assign_client_role_to_user,
    user_login,
)
from ..keycloak_config import KEYCLOAK_ADMIN_CLIENT_ID

router = APIRouter(prefix="/auth")


@router.post("/register")
async def register(payload: Dict[str, Any]):
    """Create a new user in Keycloak. Public endpoint (no auth required).

    Body: {"username": "...", "email": "...", "password": "...",
           "first_name": "...", "last_name": "...", "enabled": true}
    """
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    enabled = bool(payload.get("enabled", True))

    if not username or not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username, email, and password are required",
        )

    try:
        token = await get_service_account_token()
        user_id = await create_user(
            token=token,
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            enabled=enabled,
        )
        await set_user_password(token=token, user_id=user_id, password=password, temporary=False)
    except KeycloakAdminError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "keycloak_error", "message": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "server_error", "message": str(e)},
        )

    return {"ok": True, "user_id": user_id, "username": username, "email": email}


@router.post("/login")
async def login(payload: Dict[str, Any]):
    """Authenticate against Keycloak and return JWT tokens. Public endpoint.

    Body: {"username": "...", "password": "..."}
    """
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username and password are required",
        )

    try:
        token_data = await user_login(username, password)
    except KeycloakAdminError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login failed",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "keycloak_error", "message": str(e)},
        )

    return token_data


@router.post("/assign-role/{username}")
async def assign_role(username: str):
    """Assign the neuract-admin client role to a user. Public endpoint (mirrors Django)."""
    try:
        token = await get_service_account_token()

        user_id = await get_user_id_by_username(token, username)
        if not user_id:
            raise HTTPException(status_code=404, detail="User not found")

        client_uuid = await get_client_uuid(token, KEYCLOAK_ADMIN_CLIENT_ID)
        if not client_uuid:
            raise HTTPException(status_code=500, detail="Keycloak client not found")

        role = await get_client_role(token, client_uuid, "neuract-admin")
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        await assign_client_role_to_user(token, user_id, client_uuid, role)
    except HTTPException:
        raise
    except KeycloakAdminError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "keycloak_error", "message": str(e)},
        )

    return {
        "ok": True,
        "username": username,
        "user_id": user_id,
        "client": KEYCLOAK_ADMIN_CLIENT_ID,
        "role": "neuract-admin",
    }
