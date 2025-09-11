from __future__ import annotations

from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Query, HTTPException

from ...metrics import metrics as METRICS
from ..store import Store


router = APIRouter(prefix="/db")


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
def db_metrics(target_id: Optional[str] = Query(None), range: Optional[str] = Query(None)) -> Dict[str, Any]:
    # Aggregate across jobs that target this DB (best-effort)
    if not target_id:
        # try default
        target_id = Store.instance().get_default_db_target()
        if not target_id:
            raise HTTPException(status_code=400, detail="TARGET_ID_REQUIRED")
    window_secs = _parse_range(range)
    # Collect write latencies and errors for jobs referencing this target
    w_lat: List[float] = []
    writes = 0
    w_err = 0
    for jid, jm in list(METRICS.jobs.items()):  # type: ignore[attr-defined]
        # check if any table in this job maps to target_id
        job = Store.instance().get_job(jid)
        if not job:
            continue
        tables = job.get("tables") or []
        relevant = False
        for tid in tables:
            t = Store.instance().get_table(tid)
            if t and (t.get("dbTargetId") or Store.instance().get_default_db_target()) == target_id:
                relevant = True
                break
        if not relevant:
            continue
        # approx: use job write latencies
        w_lat.extend(list(jm.write_lat_ms)[-600:])
        ts = jm.timeseries(window_secs)
        for s in ts:
            writes += int(s.get("writes") or 0)
            w_err += int(s.get("writeErrors") or 0)
    p50 = p95 = None
    if w_lat:
        arr = sorted(w_lat)
        k50 = max(0, min(len(arr) - 1, int(0.5 * (len(arr) - 1))))
        k95 = max(0, min(len(arr) - 1, int(0.95 * (len(arr) - 1))))
        p50 = float(arr[k50]); p95 = float(arr[k95])
    err_rate = (w_err / max(1, writes)) * 100.0
    return {"ok": True, "data": {"targetId": target_id, "writeP50": p50, "writeP95": p95, "errorPct": err_rate, "writes": writes, "writeErrors": w_err}}
