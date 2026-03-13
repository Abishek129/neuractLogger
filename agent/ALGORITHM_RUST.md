# Rust Job Runner Algorithm

File: `agent/rust_jobs/src/main.rs`

---

## 1. Job Start — External Trigger Model

The Rust runner does NOT have its own API. It relies on the FastAPI server (jobs2.py) to set job status:

```
POST /jobs2/{job_id}/start  →  sets status='running' in app_jobs
```

The Rust runner polls the database every 2 seconds and picks up jobs with `status='running'`.

### Process startup

```rust
#[tokio::main]
async fn main() {
    setup_logging();                                    // fern: stderr + rotating file
    let app_db_url = env::var("APP_DB_URL");            // PostgreSQL metadata DB
    let poll_ms = env::var("JOB_POLL_MS") or 2000;      // poll interval

    let (meta_client, meta_conn) = tokio_postgres::connect(&app_db_url, NoTls);
    tokio::spawn(meta_conn);                            // background connection task

    let device_manager = Arc<DeviceManager>;            // OPC UA session cache
    let mut running: HashMap<String, JobHandle> = {};   // active job handles

    loop {
        let jobs = load_running_jobs(&meta_client);     // SELECT ... WHERE status='running'
        // start new, stop removed
        tokio::time::sleep(poll_ms);
    }
}
```

---

## 2. Job Discovery & Thread Spawning

Every 2 seconds, the main loop:

### 2a. Start new jobs

```rust
let want: HashMap<String, JobDef> = load_running_jobs();

for job in want.values() {
    if running.contains_key(&job.id) { continue; }     // already running

    let stop = Arc<AtomicBool>(false);
    let join = std::thread::spawn(move || {
        // Each job gets its own OS thread + single-threaded tokio runtime
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build();
        rt.block_on(run_job(job, meta_client, device_manager, stop));
    });
    running.insert(job.id, JobHandle { stop, join });
}
```

### 2b. Stop removed jobs

```rust
for job_id in running.keys() {
    if !want.contains_key(job_id) {                     // no longer in DB as 'running'
        handle.stop.store(true, Ordering::Relaxed);     // signal stop via AtomicBool
        std::thread::spawn(|| handle.join.join());      // join in background
    }
}
```

### Thread model
- Each job runs on its **own OS thread** with a **single-threaded tokio runtime**.
- The main async runtime handles only the 2-second poll loop.
- Stop is signaled via `AtomicBool` (lock-free, checked each iteration).

---

## 3. Job Setup — `run_job()`

Before the loop starts:

```rust
async fn run_job(job, meta_client, device_manager, stop) {
    let interval = Duration::from_millis(job.interval_ms.max(100));
    let report_every = 2.0 seconds;

    // Load DB resources
    let default_target = load_default_target(&meta_client);
    let target_manager = TargetManager::new();           // PostgreSQL target connection cache
    let modbus_manager = ModbusManager::new();           // Modbus TCP connection cache

    // Pre-build TableRuntime for each table (done ONCE, not per-loop)
    let mut table_runtimes: HashMap<String, TableRuntime> = {};
    for tid in job.tables {
        let table = load_table(&meta_client, tid);       // from app_device_tables
        let rt = build_table_runtime(table, ...);        // loads mapping, device, gateway, target
        table_runtimes.insert(table.id, rt);
    }

    // Initialize bench counters
    // ... then enter the loop
}
```

### `build_table_runtime()` loads everything needed for a table:

```rust
TableRuntime {
    table:         TableDef,           // id, name, db_target_id
    target_client: Arc<PgClient>,      // connection to target PostgreSQL
    mapping:       Vec<MappingRow>,    // field_key, protocol, address, data_type, scale
    device:        Device,             // id, protocol, params, unit_id, port, gateway_id
    gateway:       Option<Gateway>,    // id, name, host (for Modbus host resolution)
}
```

This is loaded from the **target database** (not app DB):
```sql
SELECT ... FROM neuract.device_mappings WHERE table_name = $1
```

---

## 4. Main Loop

```rust
loop {
    if stop.load(Ordering::Relaxed) { break; }
    let start = Instant::now();

    match job.job_type {
        Continuous => { ... }
        Trigger    => { ... }
    }

    // Timing & bench reporting
    let elapsed = start.elapsed();
    if elapsed > interval { win_overruns += 1; }
    if last_report.elapsed() >= report_every {
        // Log bench line, write CSV, reset counters
    }

    // Sleep remaining time
    let sleep = if elapsed >= interval { 0 } else { interval - elapsed };
    tokio::time::sleep(sleep).await;
}
```

---

## 5. Continuous Job Path

For each `table_rt` in `table_runtimes`:

### 5a. READ

```rust
let values = read_table_values_cached(table_rt, &device_manager, &modbus_manager).await;
```

Dispatches by `device.protocol`:

**OPC UA path — `read_opcua_values_blocking()`:**
```rust
let session = device_manager.get_session(&device);     // cached by device_id
// For each mapping row:
    let node_id = NodeId::from_str(&row.address);
    let value = session.read(&node_id);                 // opcua crate blocking read
    if let Some(scale) = row.scale { val *= scale; }
    values.insert(field_key, val.to_string());
```

**Modbus TCP path — `read_modbus_values()`:**
```rust
let host    = resolve_modbus_host(device, gateway);    // gateway.host > params.host > params.ip
let port    = resolve_modbus_port(device);             // device.port > params.port > 502
let unit_id = resolve_modbus_unit_id(device);          // device.unit_id > 1
let key     = format!("{}:{}", host, port);

// Take context from cache (ownership needed for async)
let mut ctx = modbus_manager.contexts.lock().remove(&key);

// Connect if not cached
if ctx.is_none() {
    ctx = tcp::connect_slave(addr, Slave(unit_id)).await;
}

// Read each field
for row in mapping {
    let encoding  = row.data_type or "float32";
    let reg_count = modbus_encoding_info(&encoding).0;

    ctx.set_slave(Slave(unit_id));
    let regs = ctx.read_holding_registers(address, reg_count).await;

    match regs {
        Ok(Ok(regs)) => {
            let val = decode_registers(&regs, &encoding);
            // Post-decode: bool16 → "true"/"false", uint16_enum → int string
            if let Some(scale) = row.scale { val *= scale; }
            values.insert(field_key, val.to_string());
        }
        Ok(Err(exception)) => warn!("modbus exception"),
        Err(io_err) => { drop context, reconnect next time }
    }
}

// Put context back into cache
modbus_manager.contexts.lock().insert(key, ctx);
```

### 5b. WRITE — `write_values_cached()`

```rust
let mut cols: Vec<String> = vec![];
let mut params: Vec<String> = vec![];

cols.push("timestamp_utc");
params.push(Utc::now().to_rfc3339());     // e.g. "2026-02-26T03:44:01+00:00"

for (k, v) in values {
    cols.push(k);
    params.push(v);                         // all values as strings
}

let sql = "INSERT INTO neuract.{table_name} ({cols}) VALUES ($1, $2, ...)";

// Key: use prepare_typed with all params as TEXT
// PostgreSQL handles text→column_type conversion (like Python's SQLAlchemy)
let types = vec![Type::TEXT; params.len()];
let stmt = target_client.prepare_typed(&sql, &types).await;
target_client.execute(&stmt, &params).await;
```

**Why `prepare_typed` with `Type::TEXT`?**
- Python (psycopg2/SQLAlchemy) sends all parameters as text — PostgreSQL parses them.
- Rust (tokio-postgres) defaults to binary protocol with strict type checking.
- `prepare_typed(..., &[Type::TEXT])` forces text mode, matching Python's behavior.
- PostgreSQL automatically converts text strings to the target column types (REAL, INTEGER, BOOLEAN, etc.).

---

## 6. Trigger Job Path

```rust
JobType::Trigger => {
    let by_table = group_triggers(&job);    // HashMap<table_id, Vec<Trigger>>

    for (table_id, triggers) in by_table {
        let values = read_table_values_cached(table_rt, ...).await;

        let should_fire = eval_triggers(&triggers, &values, &mut last_values);
        if should_fire {
            write_values_cached(table_rt, &values).await;
        }
        update_last_values(table_id, &values, &mut last_values);
    }
}
```

### `eval_triggers()`:
- For each trigger, compares current vs previous value.
- Operators: `change` (with deadband), `>`, `>=`, `<`, `<=`, `==`, `!=`.
- Returns `true` if ANY trigger fires.

### `eval_op()`:
```rust
"change" => abs(current - previous) > deadband
">"      => current > threshold
">="     => current >= threshold
// etc.
```

---

## 7. Bench Metrics Reporting

Every 2 seconds:

```
Job {id} bench window=2.0s reads/s=1.0 writes/s=1.0 read_avg_ms=2.93
    write_avg_ms=1.12 loop_p95_ms=3.47 overrun_pct=0.0 read_err=0 write_err=0
```

Also includes process-level stats via `sysinfo` crate:
- `cpu_time_ms`, `proc_cpu_pct`, `proc_rss_mb`

Written to: `agent/rust_jobs/logs/bench_metrics_rust.csv`

---

## 8. Connection Caching

| Resource            | Cache Structure                              | Key              | Lifecycle             |
|---------------------|----------------------------------------------|------------------|-----------------------|
| OPC UA sessions     | `DeviceManager { Mutex<HashMap> }`           | device_id        | Permanent, per device |
| Modbus contexts     | `ModbusManager { Mutex<HashMap> }`           | "host:port"      | Dropped on IO error   |
| Target DB clients   | `TargetManager { Mutex<HashMap<Arc<PgClient>>>}` | connection URL | Permanent             |
| Metadata DB client  | `Arc<PgClient>` (single)                     | —                | Permanent             |

### Modbus take/put pattern:
```rust
// Take: remove from HashMap (needed because async methods require ownership)
let mut ctx = map.remove(&key);

// ... use ctx for reads ...

// Put: return to HashMap for reuse
map.insert(key, ctx);
```

---

## 9. Encoding Map (Modbus)

```rust
fn modbus_encoding_info(enc: &str) -> (u16, &str) {
    "float32" | "float" => (2, "f32"),     // 2 registers, big-endian float
    "uint16" | "uint16_enum" | "bool16" => (1, "u16"),
    "int16"   => (1, "i16"),
    "uint32"  => (2, "u32"),
    "int32"   => (2, "i32"),
    "float64" => (4, "f64"),
    "uint64"  => (4, "u64"),
    "int64"   => (4, "i64"),
}
```

Decode: pack registers as big-endian bytes via `byteorder` crate, then read as target type.

---

## 10. Logging

### Setup: `setup_logging()`

Uses `fern` crate for dual output:

| Output   | Destination                                  | Format                                          |
|----------|----------------------------------------------|-------------------------------------------------|
| Console  | stderr                                       | `2026-02-26 09:14:01 [INFO] target: message`    |
| File     | `agent/rust_jobs/logs/agent_rust.log`        | Same format                                     |

### Rotating file writer: `RotatingFileWriter`

- Custom `std::io::Write` implementation.
- On each `write()`, checks if `written >= 500 MB`.
- If exceeded: closes file, shifts `.1` → `.2` → ... → `.N+1`, renames current → `.1`, opens fresh file.
- Unlimited backup count (matches Python's `RotatingFileHandler`).

### Log level

From `RUST_LOG` env var, default: `info`.

---

## 11. Data Structures

```rust
struct JobDef {
    id: String,
    name: String,
    job_type: JobType,          // Continuous | Trigger
    interval_ms: u64,
    tables: Vec<String>,        // table IDs
    triggers: Vec<Trigger>,
}

struct TableRuntime {
    table: TableDef,            // id, name, db_target_id
    target_client: Arc<PgClient>,
    mapping: Vec<MappingRow>,   // field_key, protocol, address, data_type, scale
    device: Device,             // id, protocol, params_json, unit_id, port, gateway_id
    gateway: Option<Gateway>,   // id, name, host
}

struct Device {
    id: String,
    protocol: String,           // "opcua" or "modbus"
    params: serde_json::Value,  // {endpoint, host, ip, port, ...}
    unit_id: Option<i32>,       // Modbus slave ID
    port: Option<i32>,          // Modbus port override
    gateway_id: Option<String>,
}
```

---

## 12. Differences from Python

| Aspect              | Python (jobs.py)                          | Rust (main.rs)                              |
|---------------------|-------------------------------------------|---------------------------------------------|
| **Execution model** | Thread per job, spawned by FastAPI        | Thread per job, spawned by poll loop        |
| **Job discovery**   | API call triggers thread start            | Polls `app_jobs` every 2s                   |
| **Async runtime**   | None (synchronous threading)              | Single-threaded tokio per job thread        |
| **OPC UA library**  | python-opcua (synchronous)                | opcua crate (sync wrapped in tokio)         |
| **Modbus library**  | pymodbus (synchronous)                    | tokio-modbus (async)                        |
| **DB writes**       | SQLAlchemy text() — all params as text    | tokio-postgres prepare_typed(TEXT)           |
| **Timestamp**       | IST ISO: `2026-02-26T09:14:01+05:30`     | UTC RFC3339: `2026-02-26T03:44:01+00:00`    |
| **Batching**        | Supported (count + time triggers)         | Not implemented (single-row writes only)    |
| **Cooldown**        | Supported for trigger jobs                | Not implemented                             |
| **Metrics system**  | In-process METRICS object                 | CSV-only                                    |
| **Stop signal**     | `threading.Event.set()`                   | `AtomicBool` (lock-free)                    |
| **Table setup**     | Per-loop: load mapping, engine, ident     | Pre-loop: `build_table_runtime()` once      |

---

## 13. Key File Paths

| File | Purpose |
|------|---------|
| `agent/rust_jobs/src/main.rs` | Entire Rust job runner (single file) |
| `agent/rust_jobs/Cargo.toml` | Dependencies (tokio, tokio-postgres, opcua, tokio-modbus, fern, etc.) |
| `agent/rust_jobs/logs/agent_rust.log` | Rotating log file (500 MB max) |
| `agent/rust_jobs/logs/bench_metrics_rust.csv` | Performance metrics CSV |

---

## 14. Environment Variables

| Variable            | Default  | Purpose                                  |
|---------------------|----------|------------------------------------------|
| `APP_DB_URL`        | required | PostgreSQL connection string for metadata |
| `JOB_POLL_MS`       | 2000     | How often to poll for job status changes  |
| `JOB_BENCH_WINDOW_SEC` | 2.0  | Bench reporting interval                  |
| `RUST_LOG`          | info     | Log level (trace, debug, info, warn, error) |
| `RUST_BENCH_LOG_DIR`| (auto)   | Override bench CSV output directory       |
