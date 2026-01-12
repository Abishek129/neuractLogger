from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request


class ApiClient:
    def __init__(self, base_url: str, token: str, *, logger: logging.Logger, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.logger = logger
        self.timeout = timeout

    def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, method=method.upper())
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    self.logger.error("JSON decode failed for %s %s: %s", method, url, raw[:500])
                    raise
        except error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            self.logger.error("HTTP error %s %s -> %s %s", method, url, e.code, body)
            raise
        except error.URLError as e:
            self.logger.error("URL error %s %s -> %s", method, url, e)
            raise


def _logs_dir() -> Path:
    # repo/plc_logger/bench/run_modbus_baseline.py -> repo/plc_logger/agent/plc_agent/api/logs
    return Path(__file__).resolve().parents[1] / "agent" / "plc_agent" / "api" / "logs"


def _bench_metrics_path() -> Path:
    return _logs_dir() / "bench_modbus_metrics.csv"


def _bench_metrics_paths() -> List[Path]:
    base = _logs_dir()
    return [
        base / "bench_modbus_metrics.csv",
        base / "bench_metrics.csv",  # Fallback to standard metrics
        base / "bench_metrics_pending.csv",
    ]


def _summary_path() -> Path:
    return _logs_dir() / "bench_modbus_baseline_summary.csv"


def _baseline_log_path() -> Path:
    return _logs_dir() / "bench_modbus_baseline_run.log"


def _setup_logger() -> logging.Logger:
    log_dir = _logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bench_modbus_baseline")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(_baseline_log_path(), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _fields_payload(count: int) -> List[Dict[str, Any]]:
    """
    Generate field definitions for schema.
    Uses float for all fields to match Modbus server temperature values.
    """
    fields = []
    for i in range(1, count + 1):
        fields.append({"key": f"field{i}", "type": "float"})
    return fields


def _mapping_rows_modbus(count: int) -> Dict[str, Dict[str, Any]]:
    """
    Create Modbus mapping rows reused across 10 temperature registers.

    Mapping strategy:
    - Fields are distributed round-robin across Device1-Device10 temperatures
    - All fields map to float temperature registers (no flip_bit)
    """
    rows: Dict[str, Dict[str, Any]] = {}
    for i in range(1, count + 1):
        # Distribute across 10 devices (round-robin)
        dev_num = ((i - 1) % 10) + 1

        # Device1=40001, Device2=40003, ..., Device10=40019 (float, 2 registers each)
        base_reg = 40001 + (dev_num - 1) * 2

        rows[f"field{i}"] = {
            "protocol": "modbus",
            "address": str(base_reg),
            "dataType": "float",
            "byteOrder": "ABCD",
            "scale": 1,
            "deadband": 0,
        }
    return rows


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / float(len(values))


def _parse_float(val: str) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "na":
        return None
    try:
        return float(s)
    except Exception:
        return None


def ensure_schema(client: ApiClient, name: str, cols: int) -> str:
    schemas = client.request("GET", "/schemas").get("items") or []
    for s in schemas:
        if s.get("name") == name:
            return s.get("id")
    resp = client.request(
        "POST",
        "/schemas",
        payload={"name": name, "fields": _fields_payload(cols)},
    )
    return resp["item"]["id"]


def ensure_tables(
    client: ApiClient,
    schema_id: str,
    cols: int,
    db_target_id: Optional[str],
    prefix: str,
    max_tables: int,
) -> List[Dict[str, Any]]:
    name_prefix = f"{prefix}_c{cols}_t"
    tables = client.request(
        "GET",
        "/tables",
        params={"name": name_prefix, "pageSize": 1000},
    ).get("items") or []
    # Filter to exact prefix and exclude physical-only entries
    tables = [
        t for t in tables
        if (t.get("name") or "").startswith(name_prefix) and not str(t.get("id") or "").startswith("phy_")
    ]
    existing_by_name = {t.get("name"): t for t in tables if t.get("name")}
    expected_names = [f"{name_prefix}{i}" for i in range(1, max_tables + 1)]
    missing = [n for n in expected_names if n not in existing_by_name]
    if missing:
        payload = {
            "parentSchemaId": schema_id,
            "names": missing,
        }
        if db_target_id:
            payload["dbTargetId"] = db_target_id
        client.request("POST", "/tables/bulk_create", payload=payload)

    # ensure dbTargetId for all tables in this group (if specified)
    if db_target_id:
        client.request(
            "POST",
            "/tables/bulk_update_target",
            payload={"dbTargetId": db_target_id, "nameLike": name_prefix},
        )

    # reload list
    tables = client.request(
        "GET",
        "/tables",
        params={"name": name_prefix, "pageSize": 1000},
    ).get("items") or []
    tables = [
        t for t in tables
        if (t.get("name") or "").startswith(name_prefix) and not str(t.get("id") or "").startswith("phy_")
    ]
    return tables


def apply_mappings(client: ApiClient, table_ids: List[str], device_id: str, cols: int) -> None:
    rows = _mapping_rows_modbus(cols)
    payload = {"deviceId": device_id, "rows": rows}
    # Use import to replace any prior mapping rows (avoid stale field keys)
    for tid in table_ids:
        client.request("POST", f"/mappings/{tid}/import", payload=payload)


def hydrate_mappings(client: ApiClient, table_ids: List[str]) -> None:
    # Ensure mappings are loaded into the in-memory store before job creation.
    for tid in table_ids:
        client.request("GET", f"/mappings/{tid}")


def migrate_tables(client: ApiClient, table_ids: List[str]) -> None:
    client.request("POST", "/tables/migrate", payload={"ids": table_ids})


def create_job(client: ApiClient, name: str, table_ids: List[str], interval_ms: int) -> str:
    resp = client.request(
        "POST",
        "/jobs",
        payload={
            "name": name,
            "type": "continuous",
            "tables": table_ids,
            "intervalMs": interval_ms,
            "enabled": True,
        },
    )
    return resp["item"]["id"]


def start_job(client: ApiClient, job_id: str) -> None:
    client.request("POST", f"/jobs/{job_id}/start")


def stop_job(client: ApiClient, job_id: str) -> None:
    client.request("POST", f"/jobs/{job_id}/stop")


def delete_job(client: ApiClient, job_id: str) -> None:
    client.request("DELETE", f"/jobs/{job_id}")


def summarize_job(job_id: str) -> Dict[str, Any]:
    rows = []
    paths = _bench_metrics_paths()
    found_path = None
    for path in paths:
        if path.exists():
            found_path = path
            break

    if not found_path:
        raise RuntimeError(f"No bench metrics file found in {_logs_dir()}")

    with found_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("job_id") == job_id:
                rows.append(r)

    if not rows:
        raise RuntimeError(f"No bench metrics found for job {job_id} in {found_path}")

    metrics: Dict[str, List[float]] = {
        "reads_per_sec": [],
        "writes_per_sec": [],
        "read_avg_ms": [],
        "write_avg_ms": [],
        "loop_p95_ms": [],
        "overrun_pct": [],
        "cpu_time_ms": [],
        "proc_cpu_pct": [],
        "proc_rss_mb": [],
    }
    read_err = 0
    write_err = 0
    for r in rows:
        for k in metrics.keys():
            val = _parse_float(r.get(k))
            if val is not None:
                metrics[k].append(val)
        try:
            read_err += int(float(r.get("read_err") or 0))
        except Exception:
            pass
        try:
            write_err += int(float(r.get("write_err") or 0))
        except Exception:
            pass
    summary: Dict[str, Any] = {
        "samples": len(rows),
        "read_err_sum": read_err,
        "write_err_sum": write_err,
    }
    for k, vals in metrics.items():
        avg = _mean(vals)
        summary[f"avg_{k}"] = avg
    return summary


def append_summary(row: Dict[str, Any]) -> None:
    out = _summary_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "ts_utc",
        "scenario",
        "cols",
        "tables_per_job",
        "interval_ms",
        "run_secs",
        "job_id",
        "samples",
        "avg_reads_per_sec",
        "avg_writes_per_sec",
        "avg_read_avg_ms",
        "avg_write_avg_ms",
        "avg_loop_p95_ms",
        "avg_overrun_pct",
        "avg_cpu_time_ms",
        "avg_proc_cpu_pct",
        "avg_proc_rss_mb",
        "read_err_sum",
        "write_err_sum",
    ]
    needs_header = not out.exists()
    with out.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Modbus baseline benchmarks across table/column scenarios.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python bench/run_modbus_baseline.py \\
    --base-url http://127.0.0.1:5175 \\
    --token YOUR_TOKEN \\
    --device-id modbus_test_device \\
    --cols "1,5,10" \\
    --tables "5,10" \\
    --run-minutes 2

Note: Expects mod_bus_server.py to be running on 127.0.0.1:5020
""")
    parser.add_argument("--base-url", required=True, help="API base URL (e.g., http://127.0.0.1:5175)")
    parser.add_argument("--token", required=True, help="API authentication token")
    parser.add_argument("--device-id", required=True, help="Modbus device ID to use for mappings")
    parser.add_argument("--db-target-id", default=None, help="Database target ID (omit for default SQLite)")
    parser.add_argument("--interval-ms", type=int, default=20000, help="Job interval in milliseconds (default: 20000)")
    parser.add_argument("--run-minutes", type=int, default=5, help="Run duration per scenario in minutes (default: 5)")
    parser.add_argument("--cols", default="1,5,10,15,25,50,100", help="Comma-separated column counts (default: 1,5,10,15,25,50,100)")
    parser.add_argument("--tables", default="5,10,25,50", help="Comma-separated table counts per job (default: 5,10,25,50)")
    parser.add_argument("--prefix", default="modbus_bench", help="Naming prefix for test objects (default: modbus_bench)")
    args = parser.parse_args()

    logger = _setup_logger()
    logger.info("=" * 60)
    logger.info("MODBUS BASELINE TEST - START")
    logger.info("=" * 60)
    logger.info(
        "Configuration: base_url=%s device_id=%s db_target_id=%s cols=%s tables=%s interval_ms=%s run_minutes=%s",
        args.base_url,
        args.device_id,
        args.db_target_id or "default",
        args.cols,
        args.tables,
        args.interval_ms,
        args.run_minutes,
    )
    col_counts = [int(x) for x in args.cols.split(",") if x.strip()]
    table_counts = [int(x) for x in args.tables.split(",") if x.strip()]
    max_tables = max(table_counts)
    run_secs = args.run_minutes * 60

    client = ApiClient(args.base_url, args.token, logger=logger)

    total_scenarios = len(col_counts) * len(table_counts)
    completed = 0

    for cols in col_counts:
        try:
            logger.info("Setting up schema and tables for %d columns...", cols)
            schema_name = f"{args.prefix}_cols_{cols}"
            schema_id = ensure_schema(client, schema_name, cols)
            tables = ensure_tables(client, schema_id, cols, args.db_target_id, args.prefix, max_tables)
            # stable order by name
            tables = sorted(tables, key=lambda t: t.get("name") or "")
            table_ids = [t.get("id") for t in tables if t.get("id")]
            logger.info("Created/found %d tables for %d columns", len(table_ids), cols)

            logger.info("Applying Modbus mappings to %d tables...", len(table_ids))
            apply_mappings(client, table_ids, args.device_id, cols)

            logger.info("Migrating tables...")
            migrate_tables(client, table_ids)
            logger.info("Setup complete for %d columns", cols)
        except Exception:
            logger.exception("Setup failed for cols=%s", cols)
            continue

        for count in table_counts:
            subset = table_ids[:count]
            scenario = f"{args.prefix}_cols{cols}_tables{count}"
            job_name = f"{scenario}_int{args.interval_ms}"
            job_id: Optional[str] = None

            completed += 1
            logger.info("=" * 60)
            logger.info("Scenario %d/%d: %s", completed, total_scenarios, scenario)
            logger.info("  Tables: %d, Columns: %d, Interval: %dms", count, cols, args.interval_ms)
            logger.info("=" * 60)

            try:
                logger.info("Hydrating mappings for %d tables...", len(subset))
                hydrate_mappings(client, subset)

                logger.info("Creating job: %s", job_name)
                job_id = create_job(client, job_name, subset, args.interval_ms)

                logger.info("Starting job %s...", job_id)
                start_job(client, job_id)

                logger.info("Running for %d seconds (%d minutes)...", run_secs, args.run_minutes)
                time.sleep(run_secs)

                logger.info("Stopping job %s...", job_id)
                stop_job(client, job_id)

                # Allow bench metrics to flush
                logger.info("Waiting for metrics to flush...")
                time.sleep(3)

                logger.info("Analyzing results...")
                summary = summarize_job(job_id)

                logger.info("Results for %s:", scenario)
                logger.info("  Samples: %d", summary.get("samples", 0))
                logger.info("  Avg Reads/sec: %.2f", summary.get("avg_reads_per_sec") or 0)
                logger.info("  Avg Writes/sec: %.2f", summary.get("avg_writes_per_sec") or 0)
                logger.info("  Avg Read Latency: %.2f ms", summary.get("avg_read_avg_ms") or 0)
                logger.info("  Avg Write Latency: %.2f ms", summary.get("avg_write_avg_ms") or 0)
                logger.info("  Avg CPU: %.2f%%", summary.get("avg_proc_cpu_pct") or 0)
                logger.info("  Avg Memory: %.2f MB", summary.get("avg_proc_rss_mb") or 0)
                logger.info("  Read Errors: %d", summary.get("read_err_sum", 0))
                logger.info("  Write Errors: %d", summary.get("write_err_sum", 0))

                append_summary({
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "scenario": scenario,
                    "cols": cols,
                    "tables_per_job": count,
                    "interval_ms": args.interval_ms,
                    "run_secs": run_secs,
                    "job_id": job_id,
                    "samples": summary.get("samples"),
                    "avg_reads_per_sec": summary.get("avg_reads_per_sec"),
                    "avg_writes_per_sec": summary.get("avg_writes_per_sec"),
                    "avg_read_avg_ms": summary.get("avg_read_avg_ms"),
                    "avg_write_avg_ms": summary.get("avg_write_avg_ms"),
                    "avg_loop_p95_ms": summary.get("avg_loop_p95_ms"),
                    "avg_overrun_pct": summary.get("avg_overrun_pct"),
                    "avg_cpu_time_ms": summary.get("avg_cpu_time_ms"),
                    "avg_proc_cpu_pct": summary.get("avg_proc_cpu_pct"),
                    "avg_proc_rss_mb": summary.get("avg_proc_rss_mb"),
                    "read_err_sum": summary.get("read_err_sum"),
                    "write_err_sum": summary.get("write_err_sum"),
                })
                logger.info("✓ Scenario complete: %s", scenario)
            except Exception:
                logger.exception("Scenario failed: %s", scenario)
            finally:
                if job_id:
                    try:
                        stop_job(client, job_id)
                    except Exception:
                        logger.warning("Stop failed for %s", job_id)
                    try:
                        delete_job(client, job_id)
                        logger.info("Deleted job %s", job_id)
                    except Exception:
                        logger.warning("Delete failed for %s", job_id)

    logger.info("=" * 60)
    logger.info("MODBUS BASELINE TEST - COMPLETE")
    logger.info("=" * 60)
    logger.info("Summary written to: %s", _summary_path())
    logger.info("Detailed logs: %s", _baseline_log_path())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
