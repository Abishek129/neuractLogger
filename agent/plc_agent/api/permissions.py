from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decode_jwt, extract_bearer_token

log = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_roles(claims: Dict[str, Any]) -> list[str]:
    """Extract realm roles from JWT claims."""
    return (claims.get("realm_access") or {}).get("roles") or []


_ADMIN_ROLE_NAMES = {"neuract-admin", "neuract_admin", "admin"}


def has_logger_read_role(claims: Dict[str, Any]) -> bool:
    """Realm logger-read, or anything that may write (write implies read)."""
    roles = _get_roles(claims)
    return "logger-read" in roles or "logger_read" in roles or has_logger_write_role(claims)


def has_logger_write_role(claims: Dict[str, Any]) -> bool:
    """Realm logger-write, or the neuract-admin client role (existing Keycloak
    setups grant only that, e.g. resource_access["neuract-logger"])."""
    roles = _get_roles(claims)
    return "logger-write" in roles or "logger_write" in roles or has_admin_role(claims)


def _all_roles(claims: Dict[str, Any]) -> set[str]:
    """Realm roles + every client's roles from resource_access."""
    roles = set(_get_roles(claims))
    for client in (claims.get("resource_access") or {}).values():
        for r in (client or {}).get("roles") or []:
            roles.add(r)
    return roles


def has_admin_role(claims: Dict[str, Any]) -> bool:
    """neuract-admin is a Keycloak *client* role, so scan realm + client roles."""
    return bool(_all_roles(claims) & _ADMIN_ROLE_NAMES)


def auth_disabled() -> bool:
    """LOGGER_AUTH_DISABLED=1 turns off all permission checks (local demo only)."""
    return os.environ.get("LOGGER_AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")


# Claims granted to every request while auth is disabled: read + write + admin.
_DEV_CLAIMS: Dict[str, Any] = {
    "realm_access": {"roles": ["logger-read", "logger-write"]},
    "resource_access": {"neuract_owner": {"roles": ["neuract-admin"]}},
    "preferred_username": "dev-no-auth",
    "sub": "00000000-0000-4000-8000-00000000dev0",
}


async def get_claims(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """Core dependency: validate JWT and return claims. Raises 401 if invalid."""
    if auth_disabled():
        request.state.auth = dict(_DEV_CLAIMS)
        return request.state.auth

    token: Optional[str] = None

    if credentials and credentials.credentials:
        token = credentials.credentials

    if not token:
        token = extract_bearer_token(request.headers.get("authorization"))

    # Fallback: X-Agent-Token header (used by desktop frontend client.js)
    if not token:
        token = request.headers.get("x-agent-token") or None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "PERMISSION_DENIED", "message": "Missing authentication token"},
            headers={"WWW-Authenticate": "Bearer realm=plc-agent"},
        )

    try:
        claims = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "TOKEN_EXPIRED", "message": "Token has expired"},
            headers={"WWW-Authenticate": "Bearer realm=plc-agent"},
        )
    except (jwt.InvalidTokenError, Exception) as e:
        log.debug("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "PERMISSION_DENIED", "message": "Invalid token"},
            headers={"WWW-Authenticate": "Bearer realm=plc-agent"},
        )

    request.state.auth = claims
    return claims


async def require_logger_read(
    claims: Dict[str, Any] = Depends(get_claims),
) -> Dict[str, Any]:
    """Dependency: requires valid JWT + logger-read role."""
    if not has_logger_read_role(claims):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "logger-read role required"},
        )
    return claims


async def require_logger_write(
    claims: Dict[str, Any] = Depends(get_claims),
) -> Dict[str, Any]:
    """Dependency: requires valid JWT + logger-write role."""
    if not has_logger_write_role(claims):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "logger-write role required"},
        )
    return claims


async def require_safe_or_write(
    request: Request,
    claims: Dict[str, Any] = Depends(get_claims),
) -> Dict[str, Any]:
    """SAFE methods need logger_read (or write/admin); UNSAFE need logger_write.

    C2 remainder: a merely-valid token (zero roles) must not grant read access,
    otherwise any self-registered account could read every protected router.
    """
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not has_logger_write_role(claims):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "logger-write role required for write operations"},
            )
    elif not (
        has_logger_read_role(claims)
        or has_logger_write_role(claims)
        or has_admin_role(claims)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "logger-read role required"},
        )
    return claims


async def require_admin(
    claims: Dict[str, Any] = Depends(get_claims),
) -> Dict[str, Any]:
    """Dependency: requires valid JWT + neuract-admin (client) role.

    Use for privilege-granting and process-control endpoints (role assignment,
    shutdown). The first admin must be bootstrapped directly in Keycloak.
    """
    if not has_admin_role(claims):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "neuract-admin role required"},
        )
    return claims
