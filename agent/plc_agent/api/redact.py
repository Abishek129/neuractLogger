"""Log-redaction helpers (H-OBS-4).

Connection strings routinely carry passwords (``postgresql://user:pass@host/db``
or libpq keyword form ``password=...``). Every log site that prints a DSN/conn
string MUST pass it through :func:`redact_dsn` first. Host and database stay
visible for diagnostics; only the password component is masked.

This module is intentionally dependency-free (stdlib ``re`` only) so it can be
imported from anywhere in the package without creating import cycles.
"""
from __future__ import annotations

import re
from typing import Any

# URL form: scheme://user:password@host...  ->  scheme://user:***@host...
# Mirrors the Rust engine's redaction (':[^@/]*@' -> ':***@') but anchors on
# '://user' so 'host:port' pairs are never touched.
_URL_PASSWORD_RE = re.compile(r"(://[^/@:]+):[^@/]*@")

# libpq keyword form: "host=h password=secret dbname=d"
_KEYWORD_PASSWORD_RE = re.compile(r"(password\s*=\s*)[^\s]+", re.IGNORECASE)


def redact_dsn(dsn: Any) -> str:
    """Return ``dsn`` as a string with any password component masked.

    Safe on arbitrary input: non-strings are str()-ed, values without a
    password (sqlite paths, plain hosts, garbage) come back unchanged.
    """
    try:
        s = dsn if isinstance(dsn, str) else str(dsn)
    except Exception:
        return "<unprintable-dsn>"
    s = _URL_PASSWORD_RE.sub(r"\1:***@", s)
    s = _KEYWORD_PASSWORD_RE.sub(r"\1***", s)
    return s
