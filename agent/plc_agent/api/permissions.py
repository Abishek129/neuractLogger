from __future__ import annotations

import logging
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


def has_logger_read_role(claims: Dict[str, Any]) -> bool:
    roles = _get_roles(claims)
    return "logger-read" in roles or "logger_read" in roles


def has_logger_write_role(claims: Dict[str, Any]) -> bool:
    roles = _get_roles(claims)
    return "logger-write" in roles or "logger_write" in roles


async def get_claims(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """Core dependency: validate JWT and return claims. Raises 401 if invalid."""
    token: Optional[str] = None

    if credentials and credentials.credentials:
        token = credentials.credentials

    if not token:
        token = extract_bearer_token(request.headers.get("authorization"))

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


async def require_safe_or_write(
    request: Request,
    claims: Dict[str, Any] = Depends(get_claims),
) -> Dict[str, Any]:
    """SAFE methods need valid token only; UNSAFE methods need logger_write role."""
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not has_logger_write_role(claims):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"success": False, "error": "INSUFFICIENT_ROLE", "message": "logger-write role required for write operations"},
            )
    return claims
