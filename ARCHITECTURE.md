# LoggerFast Architecture

LoggerFast is a high-performance industrial data logger that reads field values from PLC/IoT devices over **Modbus TCP**, **OPC UA**, and **MQTT**, then writes time-series rows into **PostgreSQL**. It ships as a **FastAPI** Python backend (configuration, API, UI) + a **Rust** async job runner (data acquisition at tight intervals).

---

## System Overview

```
                        +--------------------------+
                        |   Frontend / Desktop UI  |
                        |   (Tauri + Vite, :5173)  |
                        +------------+-------------+
                                     |  REST / WS
                        +------------v-------------+
                        |   FastAPI Python Backend  |
                        |   agent/plc_agent/api/    |
                        |   (uvicorn, :8003)        |
                        +--+-----+-----+-----+-----+
                           |     |     |     |
           +-------+  +---v-+ +-v---+ +v----v-----+
           | Redis |  | Keycloak |  |  WebSocket  |
           | :6379 |  | JWT Auth |  | Notifications|
           +-------+  +----------+  +-------------+
                           |
              +------------v-----------------+
              |  PostgreSQL  (meta_data_*)   |
              |  Configuration & Metrics DB  |
              |  14 internal tables          |
              +------------+-----------------+
                           |  Polled every 2 s
              +------------v-----------------+
              |  Rust Job Runner             |
              |  agent/rust_jobs/src/main.rs |
              |  (tokio async, OS threads)   |
              +--+--------+--------+--------+
                 |        |        |
          +------v-+  +---v----+  +v--------+
          | Modbus |  | OPC UA |  |  MQTT   |
          |  TCP   |  | Client |  |  Broker |
          | (:502) |  | (:4840)|  | (:1883) |
          +---+----+  +---+----+  +----+----+
              |           |            |
        +-----v-----------v------------v-----+
        |   PLC / Meter / Sensor Devices     |
        +------------------------------------+
                           |
              +------------v-----------------+
              |  Target PostgreSQL DBs       |
              |  neuract."table_name"        |
              |  (time-series data rows)     |
              +------------------------------+
              |  Bench Metrics DB            |
              |  loggerfast_metrics          |
              |  bench_metrics table         |
              +------------------------------+
```

---

## Database Schema

All configuration tables live in a single PostgreSQL database (`APP_DB_URL`, default: `postgresql://postgres@localhost/meta_data_version1`). They are created by `appdb.init()` in [appdb.py](agent/plc_agent/api/appdb.py).

### Core Tables

#### `app_meta`
Key-value store for application metadata.

| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | Setting name |
| `value` | TEXT | Setting value |

#### `app_schemas`
Defines a reusable data schema (a template of fields for a device table).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | Human-readable name (e.g. "MFM Panel 3-Phase") |

#### `app_schema_fields`
Individual fields within a schema. Each field maps to a register/address on a device.

| Column | Type | Description |
|--------|------|-------------|
| `schema_id` | TEXT | FK to `app_schemas.id` |
| `key` | TEXT | Field name (e.g. "voltage_r", "kW") |
| `type` | TEXT | Data type (`float`, `int`, `bool`, `text`) |
| `unit` | TEXT | Engineering unit (e.g. "V", "kW", "A") |
| `scale` | REAL | Multiplier applied after raw read |
| `desc_text` | TEXT | Description |
| **PK** | | `(schema_id, key)` |

#### `app_db_targets`
Connection strings for target databases where logged data is written.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `provider` | TEXT | Database type (e.g. "postgresql") |
| `conn` | TEXT | Connection string |
| `status` | TEXT | Current status |
| `last_msg` | TEXT | Last status message |

#### `app_device_tables`
A "device table" is the actual PostgreSQL table that receives time-series rows. Each one links a schema, a target DB, and a device.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | Table name in target DB (e.g. `"mfm_panel_1"`) |
| `schema_id` | TEXT | FK to `app_schemas.id` |
| `db_target_id` | TEXT | FK to `app_db_targets.id` |
| `status` | TEXT | Migration status |
| `last_migrated_at` | TEXT | Last DDL sync timestamp |
| `schema_hash` | TEXT | Hash to detect schema drift |
| `mapping_health` | TEXT | Mapping validation status |
| `device_id` | TEXT | FK to `app_devices.id` |

#### `app_gateways`
Edge gateways that bridge the network to field devices.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT UNIQUE | Display name |
| `host` | TEXT UNIQUE | IP address / hostname |
| `adapter_id` | TEXT | Network adapter |
| `ports_json` | TEXT | JSON array of open ports |
| `protocol_hint` | TEXT | FK to `app_protocol_types.type` |
| `tags_json` | TEXT | User-defined tags |
| `nic_hint` | TEXT | NIC hint |
| `status` | TEXT | `online` / `offline` |
| `last_ping_json` | TEXT | Last ICMP ping result |
| `last_tcp_json` | TEXT | Last TCP probe result |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `last_test_at` | TEXT | ISO timestamp |

#### `app_devices`
A physical device (PLC, meter, sensor) that the system reads data from.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT UNIQUE | Display name |
| `protocol` | TEXT | `modbus`, `opcua`, or `mqtt` |
| `params_json` | TEXT | JSON connection params (host, port, endpoint, topic, etc.) |
| `status` | TEXT | `connected` / `disconnected` |
| `latency_ms` | INTEGER | Last measured latency |
| `last_error` | TEXT | Last error message |
| `auto_reconnect` | INTEGER | 1 = auto-reconnect enabled |
| `unit_id` | INTEGER | Modbus slave/unit ID |
| `port` | INTEGER | TCP port override |
| `gateway_id` | TEXT | FK to `app_gateways.id` |

#### `app_jobs`
A job is a scheduled data collection task that reads one or more tables at a fixed interval.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | Human-readable name |
| `type` | TEXT | `continuous` or `trigger` |
| `tables_json` | TEXT | JSON array of device table IDs |
| `columns_json` | TEXT | JSON column config |
| `interval_ms` | INTEGER | Poll interval in milliseconds |
| `enabled` | INTEGER | 1 = active, 0 = stopped |
| `status` | TEXT | Runtime status |
| `batching_json` | TEXT | `{"count": N, "ms": M}` batch config |
| `cpu_budget` | TEXT | CPU budget hint |
| `triggers_json` | TEXT | JSON array of trigger definitions |
| `metrics_json` | TEXT | Cached latest metrics |

### Metrics & Observability Tables

#### `app_job_runs`
Historical log of each job execution window.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | Auto-increment |
| `job_id` | TEXT | FK to `app_jobs.id` |
| `started_at` | TEXT | ISO timestamp |
| `stopped_at` | TEXT | ISO timestamp |
| `duration_ms` | INTEGER | Total runtime |
| `rows` | INTEGER | Rows written |
| `read_lat_avg` | REAL | Average read latency (ms) |
| `write_lat_avg` | REAL | Average write latency (ms) |
| `error_pct` | REAL | Error percentage |

#### `app_metrics_jobs_minute`
Per-job, per-minute aggregated metrics.

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | TEXT | FK to `app_jobs.id` |
| `minute_utc` | TEXT | UTC minute bucket |
| `reads` | INTEGER | Successful reads |
| `read_err` | INTEGER | Failed reads |
| `writes` | INTEGER | Successful writes |
| `write_err` | INTEGER | Failed writes |
| `read_p50` | REAL | Median read latency |
| `read_p95` | REAL | 95th percentile read latency |
| `write_p50` | REAL | Median write latency |
| `write_p95` | REAL | 95th percentile write latency |
| `triggers` | INTEGER | Trigger evaluations |
| `fires` | INTEGER | Trigger fires |
| `suppressed` | INTEGER | Suppressed by deadband |
| **PK** | | `(job_id, minute_utc)` |

#### `app_metrics_system_minute`
System-level metrics sampled every minute.

| Column | Type | Description |
|--------|------|-------------|
| `minute_utc` | TEXT PK | UTC minute bucket |
| `cpu` | REAL | System CPU % |
| `mem` | REAL | System memory % |
| `disk_rps` | REAL | Disk reads/sec |
| `disk_wps` | REAL | Disk writes/sec |
| `net_rxps` | REAL | Network RX bytes/sec |
| `net_txps` | REAL | Network TX bytes/sec |
| `proc_cpu` | REAL | Process CPU % |
| `proc_rss_mb` | REAL | Process RSS (MB) |
| `proc_handles` | INTEGER | Open handles/FDs |

#### `app_job_errors_minute`
Per-job error tracking aggregated by minute.

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | TEXT | FK to `app_jobs.id` |
| `code` | TEXT | Error code/category |
| `minute_utc` | TEXT | UTC minute bucket |
| `count` | INTEGER | Error count in this minute |
| `last_message` | TEXT | Last error message |
| **PK** | | `(job_id, code, minute_utc)` |

### Supporting Tables

#### `app_notifications`
In-app notification queue (job alerts, trigger fires, errors).

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `type` | TEXT | `job`, `system`, etc. |
| `message` | TEXT | Notification body |
| `user` | TEXT | Target user |
| `read` | BOOLEAN | Read flag |
| `time` | TEXT | ISO timestamp |

#### `app_protocol_types`
Enumeration of supported protocols. Pre-populated with `modbus`, `opcua`, `mqtt`.

| Column | Type | Description |
|--------|------|-------------|
| `type` | TEXT PK | Protocol name |

#### `app_device_topology`
SLD (Single Line Diagram) topology inference for power distribution hierarchy.

| Column | Type | Description |
|--------|------|-------------|
| `device_id` | TEXT PK | FK to `app_devices.id` |
| `parent_device_id` | TEXT | Parent device in hierarchy |
| `hierarchy_level` | TEXT | `incomer`, `feeder`, `load`, `unknown` |
| `load_pattern` | TEXT | Inferred load type |
| `confidence` | REAL | Inference confidence (0-1) |
| `gateway_id` | TEXT | FK to `app_gateways.id` |
| `inferred_at` | TEXT | ISO timestamp |
| `snapshot_count` | INTEGER | Data snapshots used |

### Bench Metrics Table (separate DB)

Created by the Rust runner in `loggerfast_metrics` DB:

#### `bench_metrics`

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | Auto-increment |
| `ts_utc` | TIMESTAMPTZ | Sample time |
| `job_id` | TEXT | Job identifier |
| `window_secs` | DOUBLE | Reporting window |
| `reads_per_sec` | DOUBLE | Read throughput |
| `writes_per_sec` | DOUBLE | Write throughput |
| `read_avg_ms` | DOUBLE | Avg read latency |
| `write_avg_ms` | DOUBLE | Avg write latency |
| `modbus_connect_avg_ms` | DOUBLE | Modbus TCP connect latency |
| `modbus_fields_avg_ms` | DOUBLE | Modbus field decode latency |
| `sql_build_avg_ms` | DOUBLE | SQL statement build time |
| `db_execute_avg_ms` | DOUBLE | DB execute time |
| `loop_p95_ms` | DOUBLE | 95th percentile loop time |
| `overrun_pct` | DOUBLE | % loops exceeding interval |
| `cpu_time_ms` | DOUBLE | Thread CPU time |
| `proc_cpu_pct` | DOUBLE | Process CPU % |
| `proc_rss_mb` | DOUBLE | Process RSS (MB) |
| `read_err` | BIGINT | Read errors in window |
| `write_err` | BIGINT | Write errors in window |

---

## Entity Relationships

```
app_schemas ──< app_schema_fields     (1 schema has many fields)
app_schemas ──< app_device_tables     (1 schema used by many tables)
app_db_targets ──< app_device_tables  (1 target DB hosts many tables)
app_devices ──< app_device_tables     (1 device feeds many tables)
app_gateways ──< app_devices          (1 gateway connects many devices)
app_protocol_types ──< app_gateways   (FK: protocol_hint)
app_jobs ──< app_job_runs             (1 job has many run records)
app_jobs ──< app_metrics_jobs_minute  (1 job has many metric windows)
app_jobs ──< app_job_errors_minute    (1 job has many error windows)
app_devices ──< app_device_topology   (1 device has 1 topology entry)

app_jobs.tables_json ──> [app_device_tables.id, ...]  (JSON array of table IDs)
app_jobs.triggers_json ──> [{field_key, op, value, deadband, table_id}, ...]
```

---

## Rust Job Runner — `rust_jobs/src/main.rs`

The Rust binary is the performance-critical core. It reads device data and writes it to PostgreSQL as fast as the configured interval allows.

### Data Structures

```rust
// Job definition loaded from app_jobs table
JobDef { id, name, job_type, interval_ms, tables, triggers, batch_count, batch_ms }

// Two job modes
enum JobType { Continuous, Trigger }

// Trigger condition
Trigger { table_id, field_key, op, value, deadband }

// Runtime context per table (built once at job start)
TableRuntime { table, target_client, mapping, device, gateway, modbus_buckets, cached_insert_sql }

// Value types read from devices
enum FieldValue { Float(f64), Int(i64), Bool(bool), Text(String) }

// Modbus register grouping for bulk reads
RegisterBucket { start_addr, read_count, reg_type, fields: Vec<BucketField> }
BucketField { field_key, address, reg_count, encoding, scale }
```

### Function Reference

#### Entry Point & Job Management

| Function | Lines | Description |
|----------|-------|-------------|
| `main()` | 594-717 | Entry point. Connects to metadata DB and bench DB. Polls `app_jobs` every `JOB_POLL_MS` (default 2s). Starts new OS threads for enabled jobs, sends stop signals for disabled ones. Each job thread gets its own single-threaded tokio runtime. |
| `run_job()` | 719-1130 | Core job execution loop. Builds `TableRuntime` for each table in the job, then enters a `loop` that runs at `interval_ms`. Handles both Continuous and Trigger modes. Tracks per-window metrics (reads/s, writes/s, latencies, errors) and flushes them to `bench_metrics` every `JOB_BENCH_WINDOW_SEC` (default 2s). |
| `load_running_jobs()` | ~1131+ | Queries `app_jobs WHERE enabled = 1` from metadata DB, parses `tables_json`, `triggers_json`, and `batching_json` into `JobDef` structs. |
| `load_table()` | ~1200+ | Loads a single `app_device_tables` row by ID. |
| `build_table_runtime()` | ~1220+ | Assembles the full runtime context for a table: loads the device, gateway, mapping rows, target DB client, and precomputes Modbus register buckets. |

#### Read Operations

| Function | Lines | Description |
|----------|-------|-------------|
| `read_endpoint_group()` | ~1260+ | Reads all tables sharing the same device endpoint concurrently. Calls `read_table_values_cached()` for each table. |
| `read_table_values_cached()` | ~1280+ | Dispatcher: routes to `read_modbus_values()`, `read_opcua_values()`, or `read_mqtt_values()` based on `device.protocol`. Returns `(FieldMap, ReadTimings)`. |
| `read_modbus_values()` | 2610-2738 | Reads all register buckets for a Modbus device. For each bucket: gets/creates a TCP connection from the `ModbusManager` pool, issues a bulk read (FC 3/4 for registers, FC 1/2 for coils/discretes), decodes raw registers to field values using the encoding (float32, float64, uint16, int16, uint16_enum, bool16), applies scale factors. |
| `read_opcua_values()` | 2775-2815 | Reads OPC UA nodes via `spawn_blocking()`. Gets a session from `DeviceManager`, resolves node IDs (cached), reads each mapped field's value, applies scale. |
| `read_mqtt_values()` | 2459-2567 | Reads from the MQTT message cache. Looks up the latest JSON payload for the device's gateway label, finds the meter by `unit_id`, extracts fields by address key (e.g. "V1", "kW"), applies scale. |

#### Write Operations

| Function | Lines | Description |
|----------|-------|-------------|
| `write_values_cached()` | 1351-1387 | Single-row insert using inline SQL literals. Used by trigger jobs. Format: `INSERT INTO neuract."table" ("timestamp_utc", field1, ...) VALUES (now, val1, ...)`. Uses a cached SQL template for the trigger path. |
| `write_all_tables_batch()` | 1391-1449 | Multi-row batch insert. Groups rows by chunks of 32000 parameters (PostgreSQL limit), uses prepared statements with type hints. |
| `write_all_tables_batch_owned()` | 1531-1549 | Owned version of batch write for `tokio::spawn()` — enables background write overlap with the next read cycle. |
| `flush_all_buffered()` | 1459-1529 | Flushes buffered rows when batching is enabled. Groups writes by target client, wraps in `BEGIN; INSERT ...; COMMIT;` per client for transactional consistency. |

#### Modbus Internals

| Function | Lines | Description |
|----------|-------|-------------|
| `parse_modbus_address()` | 298-348 | Parses industry-standard Modbus addresses: `40001` = Holding Register 0, `30001` = Input Register 0, `10001` = Discrete Input 0, `00001` = Coil 0. Supports 5-digit and 6-digit extended formats. Raw numbers default to Holding Register. |
| `build_modbus_buckets()` | 1150-1203 | Groups mapping fields into 125-register buckets. Bucket index = `address / 125`. One bulk read per bucket per register type. Precomputed at job startup for zero runtime overhead. |
| `encoding_reg_count()` | 1164-1170 | Returns register count for an encoding: `float32` = 2, `float64` = 4, `uint16`/`int16`/`uint16_enum`/`bool16` = 1. |
| `decode_register_value()` | ~2680+ | Converts raw u16 registers to `FieldValue` using BigEndian byte order. Handles float32, float64, uint16, int16, uint16_enum (→ Text), bool16 (→ Bool). |

#### MQTT Internals

| Function | Lines | Description |
|----------|-------|-------------|
| `MqttManager::new()` | 2345-2398 | Manages per-broker state. Caches `BrokerState { cache, _client, _task }`. Auto-reconnects if the background event loop dies. |
| `MqttManager::ensure_broker()` | 2354-2370 | Connects to the MQTT broker if not already connected. Subscribes to the configured topic (default `factory/#`). Spawns a background task to drive `rumqttc::EventLoop` and update the message cache. |
| `mqtt_bg_task()` | 2401-2431 | Background async task: loops on `eventloop.poll()`, parses JSON payloads, indexes by gateway label into the shared cache. |
| `extract_mqtt_values()` | 2459-2567 | Reads cached MQTT payload → finds meter by `unit_id` → extracts fields by address key → applies scale. |

#### OPC UA Internals

| Function | Lines | Description |
|----------|-------|-------------|
| `DeviceManager::get_session()` | 460-509 | Per-device OPC UA session pool. Creates `ClientBuilder` with trust-all-certs, connects, caches the session. Reuses on subsequent calls. |
| `read_opcua_values()` | 2775-2815 | Reads each mapped field's OPC UA NodeId via `spawn_blocking()` to avoid blocking tokio. Caches parsed NodeIds in the session. |

#### Connection Management

| Function | Lines | Description |
|----------|-------|-------------|
| `TargetManager::get_client()` | 511-543 | PostgreSQL connection pool for target DBs. Health-checks cached connections with `simple_query("")`, drops and reconnects on stale connections. |
| `ModbusManager` | 2315-2334 | Per-`host:port` Modbus TCP connection cache. Context pooling: removes context from cache, uses it, returns it. Idle timeout cleanup. |

#### Trigger Evaluation

| Function | Lines | Description |
|----------|-------|-------------|
| `group_triggers()` | ~1300+ | Groups job triggers by `table_id`. Returns `HashMap<table_id, Vec<Trigger>>`. |
| `eval_triggers()` | ~1310+ | Evaluates trigger conditions against current values vs. previous values. Supports operators: `>`, `<`, `>=`, `<=`, `==`, `!=`, `change`. Applies deadband suppression (ignores changes smaller than `deadband`). Returns `Option<TriggerFireInfo>`. |
| `update_last_values()` | ~1340+ | Stores current values as previous values for next trigger evaluation cycle. |
| `send_trigger_notification()` | ~1350+ | Fire-and-forget HTTP POST to the API backend to create a notification when a trigger fires. Respects a cooldown period (`TRIGGER_NOTIFY_COOLDOWN_SEC`, default 10s). |

#### Metrics & Logging

| Function | Lines | Description |
|----------|-------|-------------|
| `setup_logging()` | 107-172 | Configures `fern` logger with dual output: stderr + rotating file (`agent_rust.log`, 500 MB max). |
| `setup_mqtt_logging()` | 178-191 | Separate rotating log file for MQTT-specific messages (`mqtt_jobs.log`). |
| `mqtt_log()` | 194-207 | Writes to the MQTT-specific log in addition to the main log. |
| `ProcSampler::sample()` | 567-586 | Samples per-thread CPU time (`CLOCK_THREAD_CPUTIME_ID`) and process RSS memory. |
| `percentile_ms()` | ~1095+ | Computes Pth percentile from a sorted array of loop timing samples. |
| `append_bench_db()` | ~1100+ | Inserts a row into `bench_metrics` table with all per-window aggregations. Fire-and-forget via `tokio::spawn()`. |
| `append_error_csv()` | ~1770+ | Appends a row to `error_log_rust.csv` for persistent error tracking. |

#### Utility

| Function | Lines | Description |
|----------|-------|-------------|
| `RotatingFileWriter` | 41-101 | Log file rotation: when file exceeds `max_bytes` (500 MB), renames current → `.1`, shifts `.N` → `.N+1`, opens fresh file. |
| `pg_escape_literal()` | ~1380+ | Escapes single quotes for safe SQL literal embedding. |
| `normalize_endpoint()` | ~509+ | Normalizes OPC UA endpoint URL format. |
| `table_endpoint_key()` | ~1250+ | Generates a grouping key from a table's device endpoint (for concurrent reads). |
| `decrypt_dpapi()` | 2873-2905 | Windows-only: decrypts `params_json` values prefixed with `ENCv1:` using Windows DPAPI (machine scope). |

---

## Job Types Explained

### Continuous Job
Runs in a tight loop at `interval_ms`:

1. **Read Phase**: Groups tables by device endpoint, reads all groups concurrently via `join_all()`.
2. **Write Phase** (no batching): Spawns a background write task (`tokio::spawn`) and immediately starts the next read — overlapping I/O.
3. **Write Phase** (batching): Buffers rows until `batch_count` or `batch_ms` threshold, then flushes all due buffers in a single transaction per target DB.

### Trigger Job
Evaluates conditions before writing:

1. **Read**: Reads the table's current values.
2. **Evaluate**: Compares current vs. previous values against trigger rules (e.g. `voltage_r > 250`, `kW change`). Deadband suppresses noise.
3. **Write**: Only inserts a row if a trigger fired. Sends a notification to the API.

---

## Data Flow Summary

```
1. User configures via UI:
   Schema → Schema Fields → Device → Gateway → Device Table → Mapping → Job

2. Rust runner polls metadata DB for enabled jobs (every 2s)

3. For each enabled job, spawns an OS thread with its own tokio runtime

4. Each job loop iteration:
   a. Read device registers/nodes/MQTT cache
   b. Decode raw values → FieldValue (float/int/bool/text)
   c. Apply scale factors
   d. Insert into target PostgreSQL table with UTC timestamp
   e. Record metrics → bench_metrics table

5. Metrics flow:
   Per-window stats → bench_metrics DB (Rust)
   Per-minute stats → app_metrics_jobs_minute (Python)
   System stats     → app_metrics_system_minute (Python)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_DB_URL` | `postgresql://postgres@localhost/meta_data_version1` | Metadata database |
| `BENCH_DB_URL` | `postgresql://postgres@localhost/loggerfast_metrics` | Bench metrics database |
| `AGENT_PORT` | `8003` | FastAPI server port |
| `AGENT_HOST` | `0.0.0.0` | FastAPI bind address |
| `JOB_POLL_MS` | `2000` | How often Rust polls for job changes |
| `JOB_BENCH_WINDOW_SEC` | `2.0` | Metrics reporting window |
| `API_BASE_URL` | `http://127.0.0.1:5175` | API URL for trigger notifications |
| `TRIGGER_NOTIFY_COOLDOWN_SEC` | `10` | Min seconds between notifications for same trigger |
| `RUST_LOG` | `info` | Log level filter |
| `KC_URL` | — | Keycloak server URL |
| `KC_REALM` | `desktop` | Keycloak realm |
| `REDIS_URL` | `redis://127.0.0.1:6379/3` | Redis for caching |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Tauri + Vite (React) |
| API | Python 3, FastAPI, uvicorn |
| ORM / DB | SQLAlchemy 2.0, psycopg2 |
| Job Runner | Rust, tokio (async), tokio-modbus, tokio-postgres, opcua, rumqttc |
| Database | PostgreSQL |
| Auth | Keycloak (JWT) |
| Cache | Redis |
| Gateway Firmware | ESP32 (Modbus TCP bridge) |
| Protocols | Modbus TCP, OPC UA, MQTT |
