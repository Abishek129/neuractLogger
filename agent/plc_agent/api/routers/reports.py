from __future__ import annotations

import io
import csv
from typing import Dict, Any, Optional

from fastapi import APIRouter, Response, Query

from .. import appdb
from ...metrics import metrics as METRICS


router = APIRouter(prefix="/reports")


@router.get("/runs.csv")
def export_runs(job_id: Optional[str] = Query(None), frm: Optional[str] = None, to: Optional[str] = None) -> Response:
    # Load runs for one job or all jobs
    rows = []
    if job_id:
        rows = appdb.load_job_runs(job_id, frm=frm, to=to)
    else:
        # No multi-job query in appdb; best-effort: list known jobs from METRICS
        for jid in list(METRICS.jobs.keys()):  # type: ignore[attr-defined]
            rows.extend(appdb.load_job_runs(jid, frm=frm, to=to))
    # CSV
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "job_id", "started_at", "stopped_at", "duration_ms", "rows", "read_lat_avg", "write_lat_avg", "error_pct"])
    for r in rows:
        w.writerow([
            r.get("id"), r.get("job_id"), r.get("started_at"), r.get("stopped_at"), r.get("duration_ms"),
            r.get("rows"), r.get("read_lat_avg"), r.get("write_lat_avg"), r.get("error_pct")
        ])
    data = buf.getvalue()
    return Response(content=data, media_type="text/csv")


@router.get("/errors.csv")
def export_errors(job_id: Optional[str] = Query(None)) -> Response:
    # Export in-memory aggregated errors; for persistence, a separate rollup table would be used
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["job_id", "code", "count", "last_message", "last_ts"])
    if job_id:
        jids = [job_id]
    else:
        jids = list(METRICS.jobs.keys())  # type: ignore[attr-defined]
    for jid in jids:
        jm = METRICS.get_job(jid)
        for code, (cnt, last_msg, last_ts) in jm.errors.items():
            w.writerow([jid, code, cnt, last_msg, int(last_ts)])
    data = buf.getvalue()
    return Response(content=data, media_type="text/csv")

