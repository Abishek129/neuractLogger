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
    # repo/bench/run_baseline_rust.py -> repo/agent/rust_jobs/logs
    return Path(__file__).resolve().parents[1] / "agent" / "rust_jobs" / "logs"


def _bench_metrics_path() -> Path:
    return _logs_dir() / "bench_metrics_rust.csv"


def _bench_metrics_paths() -> List[Path]:
    base = _logs_dir()
    return [
        base / "bench_metrics_rust.csv",
        base / "bench_metrics_rust_pending.csv",
    ]


def _summary_path() -> Path:
    return _logs_dir() / "bench_baseline_summary_rust.csv"


def _baseline_log_path() -> Path:
    return _logs_dir() / "bench_baseline_run_rust.log"


def _setup_logger() -> logging.Logger:
    log_dir = _logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bench_baseline_rust")
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
    return [{"key": f"field{i}", "type": "float"} for i in range(1, count + 1)]


def _mapping_rows(count: int) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for i in range(1, count + 1):
        dev_num = ((i - 1) % 10) + 1
        rows[f"field{i}"] = {
            "protocol": "opcua",
            "address": f"ns=2;s=Device{dev_num}.Temperature",
            "dataType": "float",
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
    db_target_id: str,
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
        client.request(
            "POST",
            "/tables/bulk_create",
            payload={
                "parentSchemaId": schema_id,
                "names": missing,
                "dbTargetId": db_target_id,
            },
        )
    # ensure dbTargetId for all tables in this group
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
    rows = _mapping_rows(cols)
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
        "/jobs2",
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
    client.request("POST", f"/jobs2/{job_id}/start")


def stop_job(client: ApiClient, job_id: str) -> None:
    client.request("POST", f"/jobs2/{job_id}/stop")


def delete_job(client: ApiClient, job_id: str) -> None:
    client.request("DELETE", f"/jobs2/{job_id}")


def summarize_job(job_id: str) -> Dict[str, Any]:
    rows = []
    paths = _bench_metrics_paths()
    if not any(p.exists() for p in paths):
        raise RuntimeError(f"bench_metrics_rust.csv not found in {paths[0].parent}")
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("job_id") == job_id:
                    rows.append(r)
    if not rows:
        raise RuntimeError(f"No bench metrics found for job {job_id}")
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
    parser = argparse.ArgumentParser(description="Run baseline benchmarks for Rust job runner.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--db-target-id", required=True)
    parser.add_argument("--interval-ms", type=int, default=20000)
    parser.add_argument("--run-minutes", type=int, default=5)
    parser.add_argument("--cols", default="1,5,10,15,25,50,100")
    parser.add_argument("--tables", default="5,10,25,50")
    parser.add_argument("--prefix", default="bench_rust")
    args = parser.parse_args()

    logger = _setup_logger()
    logger.info(
        "Rust baseline start base_url=%s device_id=%s db_target_id=%s cols=%s tables=%s interval_ms=%s run_minutes=%s",
        args.base_url,
        args.device_id,
        args.db_target_id,
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
    for cols in col_counts:
        try:
            schema_name = f"{args.prefix}_cols_{cols}"
            schema_id = ensure_schema(client, schema_name, cols)
            tables = ensure_tables(client, schema_id, cols, args.db_target_id, args.prefix, max_tables)
            # stable order by name
            tables = sorted(tables, key=lambda t: t.get("name") or "")
            table_ids = [t.get("id") for t in tables if t.get("id")]
            apply_mappings(client, table_ids, args.device_id, cols)
            migrate_tables(client, table_ids)
        except Exception:
            logger.exception("Setup failed for cols=%s", cols)
            continue

        for count in table_counts:
            subset = table_ids[:count]
            scenario = f"{args.prefix}_cols{cols}_tables{count}"
            job_name = f"{scenario}_int{args.interval_ms}"
            job_id: Optional[str] = None
            try:
                hydrate_mappings(client, subset)
                job_id = create_job(client, job_name, subset, args.interval_ms)
                start_job(client, job_id)
                time.sleep(run_secs)
                stop_job(client, job_id)
                # Allow bench metrics to flush
                time.sleep(3)
                summary = summarize_job(job_id)
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
            except Exception:
                logger.exception("Scenario failed %s", scenario)
            finally:
                if job_id:
                    try:
                        stop_job(client, job_id)
                    except Exception:
                        logger.warning("Stop failed for %s", job_id)
                    try:
                        delete_job(client, job_id)
                    except Exception:
                        logger.warning("Delete failed for %s", job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
