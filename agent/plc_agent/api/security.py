from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient

from .keycloak_config import (
    KEYCLOAK_ALLOWED_ISSUERS,
    KEYCLOAK_JWKS_URL,
    KEYCLOAK_REALM,
)

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


def validate_issuer(issuer: str) -> None:
    """M13: issuer must EXACTLY match the configured allowlist.

    KEYCLOAK_ALLOWED_ISSUERS is built from KC_URL/KC_REALM plus the
    KC_ALLOWED_ISSUERS env var. Only if the allowlist is somehow empty do we
    fall back to the legacy realm-suffix check.
    """
    allowed = KEYCLOAK_ALLOWED_ISSUERS
    if allowed:
        if issuer not in allowed:
            raise jwt.InvalidIssuerError(f"Issuer not in allowlist: {issuer}")
    elif not issuer.endswith(f"/realms/{KEYCLOAK_REALM}"):
        raise jwt.InvalidIssuerError(f"Unexpected realm in issuer: {issuer}")


def validate_azp(claims: Dict[str, Any]) -> None:
    """Optional azp/aud enforcement (M13), off unless KC_REQUIRED_AZP is set.

    KC_REQUIRED_AZP is a comma-separated list of trusted client IDs. The
    token's azp (authorized party) — or, failing that, its aud — must contain
    one of them.
    """
    required = [
        s.strip()
        for s in os.environ.get("KC_REQUIRED_AZP", "").split(",")
        if s.strip()
    ]
    if not required:
        return
    azp = claims.get("azp")
    if azp in required:
        return
    aud = claims.get("aud")
    auds = aud if isinstance(aud, (list, tuple)) else [aud]
    if any(a in required for a in auds):
        return
    raise jwt.InvalidAudienceError(
        f"azp/aud not in trusted clients: azp={azp!r} aud={aud!r}"
    )


def decode_jwt(token: str) -> Dict[str, Any]:
    """Validate and decode a Keycloak JWT token. Returns claims dict.

    JWKS signature verification proves the token was issued by our Keycloak.
    Issuer must match the KC_ALLOWED_ISSUERS allowlist exactly (M13); azp/aud
    is additionally enforced when KC_REQUIRED_AZP is configured.
    """
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "verify_iss": False},
        )
        validate_issuer(claims.get("iss", ""))
        validate_azp(claims)
        return claims
    except Exception as e:
        log.error("decode_jwt FAILED: %s: %s", type(e).__name__, e)
        raise


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract token from 'Bearer <token>' header value."""
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip() or None
    return None
