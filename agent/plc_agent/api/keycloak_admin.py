from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .keycloak_config import (
    KEYCLOAK_ADMIN_BASE_URL,
    KEYCLOAK_ADMIN_CLIENT_ID,
    KEYCLOAK_ADMIN_CLIENT_SECRET,
    KEYCLOAK_TOKEN_URL,
)

log = logging.getLogger(__name__)


class KeycloakAdminError(Exception):
    pass


_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15.0)
    return _client


async def get_service_account_token() -> str:
    """Obtain admin token via client_credentials grant."""
    client = _get_client()
    resp = await client.post(
        KEYCLOAK_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": KEYCLOAK_ADMIN_CLIENT_ID,
            "client_secret": KEYCLOAK_ADMIN_CLIENT_SECRET,
        },
    )
    if resp.status_code != 200:
        raise KeycloakAdminError(f"Failed to get admin token: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


async def create_user(
    token: str,
    username: str,
    email: str,
    first_name: str = "",
    last_name: str = "",
    enabled: bool = True,
) -> str:
    """Create a user in Keycloak. Returns user_id (UUID)."""
    client = _get_client()
    payload: Dict[str, Any] = {
        "username": username,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "enabled": enabled,
        "emailVerified": False,
    }
    resp = await client.post(
        f"{KEYCLOAK_ADMIN_BASE_URL}/users",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code not in (201, 204):
        raise KeycloakAdminError(f"User create failed: {resp.status_code} {resp.text}")

    location = resp.headers.get("location", "")
    if not location:
        user_id = await get_user_id_by_username(token, username)
        if not user_id:
            raise KeycloakAdminError("User created but user_id not found")
        return user_id
    return location.rstrip("/").split("/")[-1]


async def set_user_password(token: str, user_id: str, password: str, temporary: bool = False) -> None:
    client = _get_client()
    resp = await client.put(
        f"{KEYCLOAK_ADMIN_BASE_URL}/users/{user_id}/reset-password",
        json={"type": "password", "value": password, "temporary": temporary},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 204:
        raise KeycloakAdminError(f"Set password failed: {resp.status_code} {resp.text}")


async def get_user_id_by_username(token: str, username: str) -> Optional[str]:
    client = _get_client()
    resp = await client.get(
        f"{KEYCLOAK_ADMIN_BASE_URL}/users",
        params={"username": username, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return None
    users = resp.json()
    if not users:
        return None
    return users[0].get("id")


async def get_users_by_realm_role(token: str, role_name: str) -> List[Dict[str, Any]]:
    """Return all users who have the given realm-level role."""
    client = _get_client()
    resp = await client.get(
        f"{KEYCLOAK_ADMIN_BASE_URL}/roles/{role_name}/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 404:
        log.warning("Realm role '%s' not found in Keycloak", role_name)
        return []
    if resp.status_code != 200:
        raise KeycloakAdminError(
            f"Failed to get users for realm role '{role_name}': {resp.status_code} {resp.text}"
        )
    return resp.json()


async def get_client_uuid(token: str, client_id: str) -> Optional[str]:
    client = _get_client()
    resp = await client.get(
        f"{KEYCLOAK_ADMIN_BASE_URL}/clients",
        params={"clientId": client_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        raise KeycloakAdminError(f"Client lookup failed: {resp.status_code} {resp.text}")
    arr = resp.json()
    if not arr:
        return None
    return arr[0]["id"]


async def get_client_role(token: str, client_uuid: str, role_name: str) -> Optional[Dict[str, Any]]:
    client = _get_client()
    resp = await client.get(
        f"{KEYCLOAK_ADMIN_BASE_URL}/clients/{client_uuid}/roles/{role_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise KeycloakAdminError(f"Client role fetch failed: {resp.status_code} {resp.text}")
    return resp.json()


async def assign_client_role_to_user(
    token: str, user_id: str, client_uuid: str, role_repr: Dict[str, Any]
) -> None:
    client = _get_client()
    resp = await client.post(
        f"{KEYCLOAK_ADMIN_BASE_URL}/users/{user_id}/role-mappings/clients/{client_uuid}",
        json=[role_repr],
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 204:
        raise KeycloakAdminError(f"Assign client role failed: {resp.status_code} {resp.text}")


async def user_login(username: str, password: str) -> Dict[str, Any]:
    """Authenticate user via password grant. Returns token response."""
    client = _get_client()
    data: Dict[str, str] = {
        "grant_type": "password",
        "client_id": KEYCLOAK_ADMIN_CLIENT_ID,
        "username": username,
        "password": password,
    }
    if KEYCLOAK_ADMIN_CLIENT_SECRET:
        data["client_secret"] = KEYCLOAK_ADMIN_CLIENT_SECRET
    resp = await client.post(KEYCLOAK_TOKEN_URL, data=data)
    if resp.status_code != 200:
        raise KeycloakAdminError(f"Login failed: {resp.status_code} {resp.text}")
    return resp.json()
