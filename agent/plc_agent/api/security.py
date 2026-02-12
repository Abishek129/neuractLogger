from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient

from .keycloak_config import KEYCLOAK_JWKS_URL, KEYCLOAK_ALLOWED_ISSUERS

log = logging.getLogger(__name__)

_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            KEYCLOAK_JWKS_URL,
            cache_keys=True,
            lifespan=300,
        )
    return _jwks_client


def decode_jwt(token: str) -> Dict[str, Any]:
    """Validate and decode a Keycloak JWT token. Returns claims dict."""
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=KEYCLOAK_ALLOWED_ISSUERS,
        options={"verify_aud": False},
    )
    return claims


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract token from 'Bearer <token>' header value."""
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip() or None
    return None
