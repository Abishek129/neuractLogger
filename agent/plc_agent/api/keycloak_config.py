from __future__ import annotations

import os
from typing import List

# Keycloak server connection
KEYCLOAK_BASE_URL: str = os.environ.get("KC_URL", "http://192.168.1.20:8080/keycloak").rstrip("/")
KEYCLOAK_REALM: str = os.environ.get("KC_REALM", "desktop")

# Allowed JWT issuers (Keycloak may be accessed via different hostnames)
_default_issuer = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}"
_extra_issuers = [
    s.strip()
    for s in os.environ.get("KC_ALLOWED_ISSUERS", "").split(",")
    if s.strip()
]
# Include common localhost proxy issuers so JWTs obtained via Vite dev proxies are accepted
_localhost_issuers = [
    f"http://localhost:5180/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://localhost:5182/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://100.90.185.31:5182/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://100.90.185.31:5180/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://127.0.0.1:8080/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://localhost:8080/keycloak/realms/{KEYCLOAK_REALM}",
    f"http://100.90.185.31:8080/keycloak/realms/{KEYCLOAK_REALM}",
]
KEYCLOAK_ALLOWED_ISSUERS: List[str] = list(dict.fromkeys([_default_issuer, *_localhost_issuers, *_extra_issuers]))

# Admin client credentials (service account for user management)
KEYCLOAK_ADMIN_CLIENT_ID: str = os.environ.get("KC_ADMIN_CLIENT_ID", "neuract_owner")
KEYCLOAK_ADMIN_CLIENT_SECRET: str = os.environ.get("KC_ADMIN_CLIENT_SECRET", "SwNbUunGlyDZaxWJoxpTUAwDYuuJqxB5")

# Derived URLs
KEYCLOAK_JWKS_URL: str = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
KEYCLOAK_TOKEN_URL: str = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
KEYCLOAK_ADMIN_BASE_URL: str = f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}"
