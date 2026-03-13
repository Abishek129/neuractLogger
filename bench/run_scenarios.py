"""
Benchmark scenario runner for LoggerFast.

Type 1: Fixed 1 job, varying table count (1, 10, 20, ..., 250)
Type 2: Fixed 250 tables, varying job count (1, 2, 3, ..., 10)

Each scenario runs for a configurable duration (default 5 minutes).
Results are written to agent/plc_agent/api/logs/scenario_summary.csv.

Usage:
    python bench/run_scenarios.py --base-url http://localhost:5175
    python bench/run_scenarios.py --base-url http://localhost:5175 --run-minutes 2
    python bench/run_scenarios.py --base-url http://localhost:5175 --type 1   # only Type 1
    python bench/run_scenarios.py --base-url http://localhost:5175 --type 2   # only Type 2
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _logs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "plc_agent" / "api" / "logs"


def _bench_metrics_paths() -> List[Path]:
    d = _logs_dir()
    return [d / "bench_metrics.csv", d / "bench_metrics_pending.csv"]


def _summary_path() -> Path:
    return _logs_dir() / "scenario_summary.csv"


def _run_log_path() -> Path:
    return _logs_dir() / "scenario_run.log"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _setup_logger() -> logging.Logger:
    _logs_dir().mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("run_scenarios")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(_run_log_path(), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# API client (adapted from run_baseline.py)
# ---------------------------------------------------------------------------

class ApiClient:
    def __init__(self, base_url: str, *, logger: logging.Logger, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.timeout = timeout

    def req(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
            payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        r = request.Request(url, data=data, method=method.upper())
        r.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(r, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            self.logger.error("HTTP %s %s -> %s %s", method, url, e.code, body[:300])
            raise
        except error.URLError as e:
            self.logger.error("URL error %s %s -> %s", method, url, e)
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "na":
        return None
    try:
        return float(s)
    except Exception:
        return None


def delete_old_logs(logger: logging.Logger) -> None:
    for p in _bench_metrics_paths():
        if p.exists():
            p.unlink()
            logger.info("Deleted %s", p)


def fetch_table_ids(client: ApiClient) -> List[str]:
    """Fetch all 250 existing table IDs sorted by name."""
    tables = client.req("GET", "/tables", params={"pageSize": 500}).get("items") or []
    # Exclude physical-only entries
    tables = [t for t in tables if not str(t.get("id", "")).startswith("phy_")]
    tables.sort(key=lambda t: t.get("name", ""))
    return [t["id"] for t in tables]


def stop_all_jobs(client: ApiClient, logger: logging.Logger) -> None:
    try:
        client.req("POST", "/jobs/stop_all")
        logger.info("Stopped all running jobs")
    except Exception as e:
        logger.warning("stop_all failed (may be fine): %s", e)


def create_job(client: ApiClient, name: str, table_ids: List[str], interval_ms: int) -> str:
    resp = client.req("POST", "/jobs", payload={
        "name": name,
        "type": "continuous",
        "tables": table_ids,
        "intervalMs": interval_ms,
        "enabled": True,
    })
    return resp["item"]["id"]


def start_job(client: ApiClient, job_id: str) -> None:
    client.req("POST", f"/jobs/{job_id}/start")


def stop_job(client: ApiClient, job_id: str) -> None:
    client.req("POST", f"/jobs/{job_id}/stop")


def delete_job(client: ApiClient, job_id: str) -> None:
    client.req("DELETE", f"/jobs/{job_id}")


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

def collect_metrics(job_ids: List[str]) -> Dict[str, Any]:
    """Read bench_metrics.csv and aggregate rows matching any of the given job_ids."""
    job_set = set(job_ids)
    rows: List[Dict[str, str]] = []
    for path in _bench_metrics_paths():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("job_id") in job_set:
                    rows.append(r)

    metric_keys = [
        "reads_per_sec", "writes_per_sec", "read_avg_ms", "write_avg_ms",
        "loop_p95_ms", "overrun_pct", "cpu_time_ms", "proc_cpu_pct", "proc_rss_mb",
    ]
    accum: Dict[str, List[float]] = {k: [] for k in metric_keys}
    total_read_err = 0
    total_write_err = 0

    for r in rows:
        for k in metric_keys:
            v = _parse_float(r.get(k))
            if v is not None:
                accum[k].append(v)
        try:
            total_read_err += int(float(r.get("read_err") or 0))
        except Exception:
            pass
        try:
            total_write_err += int(float(r.get("write_err") or 0))
        except Exception:
            pass

    summary: Dict[str, Any] = {"samples": len(rows), "total_read_err": total_read_err, "total_write_err": total_write_err}
    for k, vals in accum.items():
        summary[f"avg_{k}"] = _mean(vals)
    return summary


# ---------------------------------------------------------------------------
# Summary CSV
# ---------------------------------------------------------------------------

SUMMARY_HEADER = [
    "ts_utc", "scenario_type", "scenario_name", "num_jobs", "num_tables",
    "tables_per_job", "interval_ms", "run_secs", "samples",
    "avg_reads_per_sec", "avg_writes_per_sec", "avg_read_avg_ms", "avg_write_avg_ms",
    "avg_loop_p95_ms", "avg_overrun_pct", "avg_cpu_time_ms", "avg_proc_cpu_pct",
    "avg_proc_rss_mb", "total_read_err", "total_write_err",
]


def append_summary(row: Dict[str, Any]) -> None:
    out = _summary_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not out.exists()
    with out.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_HEADER)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Scenario runners
# ---------------------------------------------------------------------------

def run_type1(client: ApiClient, all_table_ids: List[str], interval_ms: int,
              run_secs: int, logger: logging.Logger) -> None:
    """Type 1: 1 job, varying table count."""
    table_counts = [1] + list(range(10, 251, 10))  # [1, 10, 20, ..., 250]
    total = len(table_counts)

    for i, n_tables in enumerate(table_counts, 1):
        scenario = f"type1_1job_{n_tables}tables"
        logger.info("=== Type 1 scenario %d/%d: %s ===", i, total, scenario)

        subset = all_table_ids[:n_tables]
        job_id = None
        try:
            job_id = create_job(client, scenario, subset, interval_ms)
            logger.info("Created job %s with %d tables", job_id, n_tables)

            start_job(client, job_id)
            logger.info("Job started, running for %d seconds...", run_secs)

            time.sleep(run_secs)

            stop_job(client, job_id)
            logger.info("Job stopped, flushing...")
            time.sleep(3)

            metrics = collect_metrics([job_id])
            logger.info("Collected %d metric samples", metrics.get("samples", 0))

            append_summary({
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "scenario_type": "type1_vary_tables",
                "scenario_name": scenario,
                "num_jobs": 1,
                "num_tables": n_tables,
                "tables_per_job": n_tables,
                "interval_ms": interval_ms,
                "run_secs": run_secs,
                "samples": metrics.get("samples"),
                "avg_reads_per_sec": metrics.get("avg_reads_per_sec"),
                "avg_writes_per_sec": metrics.get("avg_writes_per_sec"),
                "avg_read_avg_ms": metrics.get("avg_read_avg_ms"),
                "avg_write_avg_ms": metrics.get("avg_write_avg_ms"),
                "avg_loop_p95_ms": metrics.get("avg_loop_p95_ms"),
                "avg_overrun_pct": metrics.get("avg_overrun_pct"),
                "avg_cpu_time_ms": metrics.get("avg_cpu_time_ms"),
                "avg_proc_cpu_pct": metrics.get("avg_proc_cpu_pct"),
                "avg_proc_rss_mb": metrics.get("avg_proc_rss_mb"),
                "total_read_err": metrics.get("total_read_err"),
                "total_write_err": metrics.get("total_write_err"),
            })
            logger.info("Summary appended for %s", scenario)
        except Exception:
            logger.exception("Scenario failed: %s", scenario)
        finally:
            if job_id:
                try:
                    stop_job(client, job_id)
                except Exception:
                    pass
                try:
                    delete_job(client, job_id)
                except Exception:
                    logger.warning("Delete failed for job %s", job_id)


def run_type2(client: ApiClient, all_table_ids: List[str], interval_ms: int,
              run_secs: int, logger: logging.Logger) -> None:
    """Type 2: 250 tables, varying job count."""
    job_counts = list(range(1, 11))  # [1, 2, 3, ..., 10]
    total_tables = len(all_table_ids)
    total = len(job_counts)

    for i, n_jobs in enumerate(job_counts, 1):
        scenario = f"type2_{n_jobs}jobs_{total_tables}tables"
        logger.info("=== Type 2 scenario %d/%d: %s ===", i, total, scenario)

        # Split tables equally across N jobs
        chunk_size = total_tables // n_jobs
        chunks: List[List[str]] = []
        for j in range(n_jobs):
            start = j * chunk_size
            if j == n_jobs - 1:
                # Last job gets the remainder
                chunks.append(all_table_ids[start:])
            else:
                chunks.append(all_table_ids[start:start + chunk_size])

        job_ids: List[str] = []
        try:
            # Create all jobs
            for j, chunk in enumerate(chunks):
                job_name = f"{scenario}_part{j + 1}"
                jid = create_job(client, job_name, chunk, interval_ms)
                job_ids.append(jid)
                logger.info("Created job %d/%d (%s) with %d tables", j + 1, n_jobs, jid, len(chunk))

            # Start all jobs
            for jid in job_ids:
                start_job(client, jid)
            logger.info("All %d jobs started, running for %d seconds...", n_jobs, run_secs)

            time.sleep(run_secs)

            # Stop all jobs
            for jid in job_ids:
                try:
                    stop_job(client, jid)
                except Exception:
                    pass
            logger.info("All jobs stopped, flushing...")
            time.sleep(3)

            metrics = collect_metrics(job_ids)
            logger.info("Collected %d metric samples across %d jobs", metrics.get("samples", 0), n_jobs)

            tables_per_job = f"{chunk_size}" if total_tables % n_jobs == 0 else f"{chunk_size}-{chunk_size + total_tables % n_jobs}"
            append_summary({
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "scenario_type": "type2_vary_jobs",
                "scenario_name": scenario,
                "num_jobs": n_jobs,
                "num_tables": total_tables,
                "tables_per_job": tables_per_job,
                "interval_ms": interval_ms,
                "run_secs": run_secs,
                "samples": metrics.get("samples"),
                "avg_reads_per_sec": metrics.get("avg_reads_per_sec"),
                "avg_writes_per_sec": metrics.get("avg_writes_per_sec"),
                "avg_read_avg_ms": metrics.get("avg_read_avg_ms"),
                "avg_write_avg_ms": metrics.get("avg_write_avg_ms"),
                "avg_loop_p95_ms": metrics.get("avg_loop_p95_ms"),
                "avg_overrun_pct": metrics.get("avg_overrun_pct"),
                "avg_cpu_time_ms": metrics.get("avg_cpu_time_ms"),
                "avg_proc_cpu_pct": metrics.get("avg_proc_cpu_pct"),
                "avg_proc_rss_mb": metrics.get("avg_proc_rss_mb"),
                "total_read_err": metrics.get("total_read_err"),
                "total_write_err": metrics.get("total_write_err"),
            })
            logger.info("Summary appended for %s", scenario)
        except Exception:
            logger.exception("Scenario failed: %s", scenario)
        finally:
            for jid in job_ids:
                try:
                    stop_job(client, jid)
                except Exception:
                    pass
                try:
                    delete_job(client, jid)
                except Exception:
                    logger.warning("Delete failed for job %s", jid)


# ---------------------------------------------------------------------------
# Type 3: 240 working tables, varying job count
# ---------------------------------------------------------------------------

BROKEN_TABLE_IDS = {
    "tbl_1772513235871_241", "tbl_1772513235871_242", "tbl_1772513235871_243",
    "tbl_1772513235871_244", "tbl_1772513235871_245", "tbl_1772513235871_246",
    "tbl_1772513235871_247", "tbl_1772513235871_248", "tbl_1772513235871_249",
    "tbl_1772513235871_250",
}


def run_type3(client: ApiClient, all_table_ids: List[str], interval_ms: int,
              run_secs: int, logger: logging.Logger) -> None:
    """Type 3: 240 working tables (excluding broken), varying job count."""
    working_ids = [tid for tid in all_table_ids if tid not in BROKEN_TABLE_IDS]
    total_tables = len(working_ids)
    logger.info("Type 3: using %d working tables (excluded %d broken)", total_tables, len(all_table_ids) - total_tables)

    job_counts = list(range(1, 11))  # [1, 2, 3, ..., 10]
    total = len(job_counts)

    for i, n_jobs in enumerate(job_counts, 1):
        scenario = f"type3_{n_jobs}jobs_{total_tables}tables"
        logger.info("=== Type 3 scenario %d/%d: %s ===", i, total, scenario)

        chunk_size = total_tables // n_jobs
        chunks: List[List[str]] = []
        for j in range(n_jobs):
            start = j * chunk_size
            if j == n_jobs - 1:
                chunks.append(working_ids[start:])
            else:
                chunks.append(working_ids[start:start + chunk_size])

        job_ids: List[str] = []
        try:
            for j, chunk in enumerate(chunks):
                job_name = f"{scenario}_part{j + 1}"
                jid = create_job(client, job_name, chunk, interval_ms)
                job_ids.append(jid)
                logger.info("Created job %d/%d (%s) with %d tables", j + 1, n_jobs, jid, len(chunk))

            for jid in job_ids:
                start_job(client, jid)
            logger.info("All %d jobs started, running for %d seconds...", n_jobs, run_secs)

            time.sleep(run_secs)

            for jid in job_ids:
                try:
                    stop_job(client, jid)
                except Exception:
                    pass
            logger.info("All jobs stopped, flushing...")
            time.sleep(3)

            metrics = collect_metrics(job_ids)
            logger.info("Collected %d metric samples across %d jobs", metrics.get("samples", 0), n_jobs)

            tables_per_job = f"{chunk_size}" if total_tables % n_jobs == 0 else "{}-{}".format(chunk_size, chunk_size + total_tables % n_jobs)
            append_summary({
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "scenario_type": "type3_working_tables",
                "scenario_name": scenario,
                "num_jobs": n_jobs,
                "num_tables": total_tables,
                "tables_per_job": tables_per_job,
                "interval_ms": interval_ms,
                "run_secs": run_secs,
                "samples": metrics.get("samples"),
                "avg_reads_per_sec": metrics.get("avg_reads_per_sec"),
                "avg_writes_per_sec": metrics.get("avg_writes_per_sec"),
                "avg_read_avg_ms": metrics.get("avg_read_avg_ms"),
                "avg_write_avg_ms": metrics.get("avg_write_avg_ms"),
                "avg_loop_p95_ms": metrics.get("avg_loop_p95_ms"),
                "avg_overrun_pct": metrics.get("avg_overrun_pct"),
                "avg_cpu_time_ms": metrics.get("avg_cpu_time_ms"),
                "avg_proc_cpu_pct": metrics.get("avg_proc_cpu_pct"),
                "avg_proc_rss_mb": metrics.get("avg_proc_rss_mb"),
                "total_read_err": metrics.get("total_read_err"),
                "total_write_err": metrics.get("total_write_err"),
            })
            logger.info("Summary appended for %s", scenario)
        except Exception:
            logger.exception("Scenario failed: %s", scenario)
        finally:
            for jid in job_ids:
                try:
                    stop_job(client, jid)
                except Exception:
                    pass
                try:
                    delete_job(client, jid)
                except Exception:
                    logger.warning("Delete failed for job %s", jid)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Run benchmark scenarios for LoggerFast.")
    parser.add_argument("--base-url", default="http://localhost:5175")
    parser.add_argument("--interval-ms", type=int, default=1000, help="Job interval in ms (default 1000)")
    parser.add_argument("--run-minutes", type=int, default=5, help="Duration per scenario in minutes (default 5)")
    parser.add_argument("--type", type=int, choices=[1, 2, 3], default=None, help="Run only Type 1, 2, or 3 (default: all)")
    args = parser.parse_args()

    logger = _setup_logger()
    run_secs = args.run_minutes * 60

    logger.info("=" * 60)
    logger.info("Benchmark started: base_url=%s interval_ms=%d run_minutes=%d type=%s",
                args.base_url, args.interval_ms, args.run_minutes, args.type or "all")
    logger.info("=" * 60)

    client = ApiClient(args.base_url, logger=logger)

    # Step 0: Clean old logs
    delete_old_logs(logger)

    # Step 1: Stop any running jobs
    stop_all_jobs(client, logger)

    # Step 2: Fetch all table IDs
    all_table_ids = fetch_table_ids(client)
    logger.info("Found %d tables", len(all_table_ids))
    if not all_table_ids:
        logger.error("No tables found! Create tables first.")
        return 1

    # Step 3: Run scenarios
    run_type = args.type

    if run_type is None or run_type == 1:
        logger.info("Starting Type 1 scenarios (1 job, varying tables)...")
        run_type1(client, all_table_ids, args.interval_ms, run_secs, logger)

    if run_type is None or run_type == 2:
        logger.info("Starting Type 2 scenarios (250 tables, varying jobs)...")
        run_type2(client, all_table_ids, args.interval_ms, run_secs, logger)

    if run_type is None or run_type == 3:
        logger.info("Starting Type 3 scenarios (240 working tables, varying jobs)...")
        run_type3(client, all_table_ids, args.interval_ms, run_secs, logger)

    logger.info("=" * 60)
    logger.info("All scenarios complete. Summary: %s", _summary_path())
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
