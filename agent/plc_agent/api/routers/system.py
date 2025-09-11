from __future__ import annotations

from typing import Dict, Any, Optional

from fastapi import APIRouter, Query

from ...metrics import metrics as METRICS
from ..store import Store


router = APIRouter(prefix="/system")


def _parse_range(r: Optional[str]) -> int:
    if not r:
        return 300
    s = str(r).strip().lower()
    try:
        if s.endswith("ms"):
            return max(1, int(int(s[:-2]) / 1000))
        if s.endswith("s"):
            return max(1, int(s[:-1]))
        if s.endswith("m"):
            return max(1, int(float(s[:-1]) * 60))
        if s.endswith("h"):
            return max(1, int(float(s[:-1]) * 3600))
        return max(1, int(s))
    except Exception:
        return 300


@router.get("/metrics")
def system_metrics(range: Optional[str] = Query(None)) -> Dict[str, Any]:
    window_secs = _parse_range(range)
    snap = METRICS.system.snapshot(window_secs)
    # device health counts
    devs = Store.instance().list_devices()
    counts = {"connected": 0, "disconnected": 0, "unknown": 0}
    for d in devs:
        st = (d.get("status") or "unknown").lower()
        if st not in counts:
            st = "unknown"
        counts[st] += 1
    # best-effort DB health using write latencies across jobs (p50/p95, error rate)
    db_summary: Dict[str, Any] = {}
    return {
        "ok": True,
        "data": {
            "timeseries": snap.get("items"),
            "now": snap.get("now"),
            "devices": counts,
            "db": db_summary,
        },
    }


@router.get("/summary")
def system_summary() -> Dict[str, Any]:
    """Compact status summary for tray: connected devices, default DB OK, running jobs count."""
    store = Store.instance()
    # Devices
    devs = store.list_devices()
    connected = sum(1 for d in devs if (d.get("status") or "").lower() in ("connected", "degraded"))
    # Default DB target
    default_id = store.get_default_db_target()
    default_ok = False
    if default_id:
        t = store.get_db_target(default_id)
        default_ok = bool(t and (t.get("status") == "ok"))
    # Jobs running
    jobs = store.list_jobs()
    running = sum(1 for j in jobs if (j.get("status") or "").lower() == "running")
    return {
        "ok": True,
        "devicesConnected": connected,
        "defaultDbOk": default_ok,
        "jobsRunning": running,
    }