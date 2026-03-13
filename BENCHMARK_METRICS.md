# Benchmark Metrics Reference

This document describes every metric column stored in the `bench_metrics` table (`loggerfast_metrics` database) by the Rust job runner.

## How Metrics Are Collected

Each job thread reports metrics every **2 seconds** (configurable via `JOB_BENCH_WINDOW_SEC` env var). All values are **averages or totals** across all tables processed by that job within the reporting window.

---

## Table: `bench_metrics`

### Identity & Timing

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Auto-incrementing primary key |
| `ts_utc` | TIMESTAMPTZ | Timestamp when the metric row was inserted (UTC) |
| `job_id` | TEXT | The job identifier (e.g., `job_1772016285456`) |
| `window_secs` | DOUBLE PRECISION | Actual elapsed time of the reporting window in seconds (~2.0s) |

### Throughput

| Column | Type | Description |
|--------|------|-------------|
| `reads_per_sec` | DOUBLE PRECISION | Number of successful table reads per second. One "read" = reading all fields from one table via Modbus/OPC UA |
| `writes_per_sec` | DOUBLE PRECISION | Number of successful table writes per second. One "write" = inserting one row into the target PostgreSQL table |

### Total Read/Write Latency

| Column | Type | Description |
|--------|------|-------------|
| `read_avg_ms` | DOUBLE PRECISION | Average time (ms) to complete one full table read. Includes connection + all field reads. Should approximately equal `modbus_connect_avg_ms + modbus_fields_avg_ms` |
| `write_avg_ms` | DOUBLE PRECISION | Average time (ms) to complete one full table write. Includes SQL building + DB execution. Should approximately equal `sql_build_avg_ms + db_execute_avg_ms` |

### Read Sub-Timings

| Column | Type | Description |
|--------|------|-------------|
| `modbus_connect_avg_ms` | DOUBLE PRECISION | Average time (ms) to obtain a Modbus TCP connection. **~0ms when cached** (connection reused from previous read). Only non-zero on first connection or after a connection error forces reconnection |
| `modbus_fields_avg_ms` | DOUBLE PRECISION | Average time (ms) to read all register fields sequentially from the device. Each table has ~60 fields, each requiring a separate `read_holding_registers` call. This is typically the dominant component of read time |

**Breakdown:** `read_avg_ms ≈ modbus_connect_avg_ms + modbus_fields_avg_ms`

### Write Sub-Timings

| Column | Type | Description |
|--------|------|-------------|
| `sql_build_avg_ms` | DOUBLE PRECISION | Average time (ms) to construct the INSERT SQL statement — building column list, parameter placeholders, and the SQL string. Typically **~0.015ms** (negligible) |
| `db_execute_avg_ms` | DOUBLE PRECISION | Average time (ms) for the PostgreSQL round-trip — `prepare_typed` (compile the statement) + `execute` (send data, wait for confirmation). This is the dominant component of write time |

**Breakdown:** `write_avg_ms ≈ sql_build_avg_ms + db_execute_avg_ms`

### Loop Performance

| Column | Type | Description |
|--------|------|-------------|
| `loop_p95_ms` | DOUBLE PRECISION | 95th percentile of full loop iteration time (ms). One loop = read + write for ALL tables in the job. If this exceeds `interval_ms` (typically 1000ms), the job is overrunning |
| `overrun_pct` | DOUBLE PRECISION | Percentage of loop iterations that took longer than the configured interval. **0% = all loops completed within the interval.** High values indicate the job has too many tables for the given interval |

### Resource Usage

| Column | Type | Description |
|--------|------|-------------|
| `cpu_time_ms` | DOUBLE PRECISION | Thread CPU time consumed during the reporting window (ms). Measured via `CLOCK_THREAD_CPUTIME_ID` — this is **per-thread**, not process-wide |
| `proc_cpu_pct` | DOUBLE PRECISION | Thread CPU utilization as a percentage. Calculated as `(cpu_time_ms / window_ms) × 100`. Each job runs in its own thread, so this shows CPU usage for that specific job |
| `proc_rss_mb` | DOUBLE PRECISION | Process-wide Resident Set Size in MB. This is the total memory used by the entire Rust job runner process (shared across all job threads). **Not per-thread** — memory is shared |

### Error Counts

| Column | Type | Description |
|--------|------|-------------|
| `read_err` | BIGINT | Number of failed table reads during the window. Common causes: Modbus connection timeout, device not responding, simulator down |
| `write_err` | BIGINT | Number of failed table writes during the window. Common causes: target DB connection error, table schema mismatch, broken transformer tables |

---

## Typical Values (from benchmarks)

| Metric | 5 tables | 120 tables | 240 tables |
|--------|----------|------------|------------|
| `read_avg_ms` | ~2.3 | ~2.3 | ~2.3 |
| `modbus_connect_avg_ms` | ~0.0 | ~0.0 | ~0.0 |
| `modbus_fields_avg_ms` | ~2.3 | ~2.3 | ~2.3 |
| `write_avg_ms` | ~1.8 | ~1.8 | ~1.8 |
| `sql_build_avg_ms` | ~0.015 | ~0.015 | ~0.015 |
| `db_execute_avg_ms` | ~1.8 | ~1.8 | ~1.8 |
| `loop_p95_ms` | ~20 | ~500 | ~1000 |
| `overrun_pct` | 0% | 0% | 0-10% |
| `proc_cpu_pct` | ~0.1% | ~0.3% | ~0.5% |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCH_DB_URL` | `postgresql://postgres@localhost/loggerfast_metrics` | Connection string for the metrics database |
| `JOB_BENCH_WINDOW_SEC` | `2.0` | Reporting interval in seconds (how often metrics are flushed to DB) |

---

## Error Log (separate)

Individual errors are logged to a CSV file at `agent/rust_jobs/logs/error_log_rust.csv` with columns:

| Column | Description |
|--------|-------------|
| `ts_utc` | Timestamp of the error (RFC 3339) |
| `job_id` | Job that encountered the error |
| `table_id` | Table involved in the error |
| `operation` | `read` or `write` |
| `error_message` | Full error message text |
