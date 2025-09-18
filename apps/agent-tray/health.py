import os
import time
from dataclasses import dataclass
from typing import Optional

import requests


DEFAULT_HOST = os.environ.get("AGENT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("AGENT_PORT", "5175"))


@dataclass
class HealthStatus:
    ok: bool
    port: int
    detail: Optional[str] = None
    last_ok_ts: Optional[float] = None


def check_health(port: int = DEFAULT_PORT, timeout: float = 1.5) -> HealthStatus:
    url = f"http://{DEFAULT_HOST}:{port}/health"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        ok = (data or {}).get("status") == "ok"
        return HealthStatus(ok=ok, port=port, detail=None if ok else str(data), last_ok_ts=time.time() if ok else None)
    except Exception as e:
        return HealthStatus(ok=False, port=port, detail=str(e))

