# Python (FastAPI) Job Runner Algorithm

File: `agent/plc_agent/api/routers/jobs.py`

---

## 1. Job Start

```
POST /jobs/{job_id}/start
```

1. API endpoint `start_job()` receives the request.
2. Calls `Store.instance().set_job_status(job_id, "running")` — writes `status='running'` into the `app_jobs` table in PostgreSQL.
3. Creates a `threading.Event` in `_job_stops[job_id]` (used to signal stop).
4. Spawns a **new Python thread** via `threading.Thread(target=_run_job_loop, args=(job_id,))`.
5. Stores the thread handle in `_job_threads[job_id]`.
6. Returns `{"success": True}` immediately — execution happens in the background thread.

### Thread model
- Each running job gets its **own OS thread**.
- The thread runs `_run_job_loop(job_id)` which contains the main while-loop.
- Thread-local storage (`threading.local()`) is used for per-thread DB engine caches.

---

## 2. Job Loop — `_run_job_loop(job_id)`

### Initialization (before the loop)

```python
store = Store.instance()
job   = store.get_job(job_id)               # fetch job definition from in-memory store
interval = max(0.1, intervalMs / 1000.0)    # minimum 100ms
stop_event = _job_stops[job_id]             # threading.Event for graceful stop
jtype = (job.type or "continuous").lower()   # "continuous" or "trigger"
```

Batching config (continuous jobs only):
```python
batch_count = job.batching.count   # default 1 (no batching)
batch_ms    = job.batching.ms      # default 0 (no time-based flush)
use_batching = (batch_count > 1 or batch_ms > 0)
```

Benchmark counters are initialized:
- `win_reads_ok`, `win_reads_err`, `win_writes_ok`, `win_writes_err`
- `win_read_ms_sum`, `win_write_ms_sum`
- `win_loops`, `win_overruns`
- `loop_samples_ms` (deque, max 1000)
- `report_every = 2.0` seconds

### Main Loop

```
while not stop_event.is_set():
    t_start = time.perf_counter()

    if jtype == "continuous":
        ... continuous path ...
    else:
        ... trigger path ...

    # Timing
    dt = time.perf_counter() - t_start
    if dt > interval: win_overruns += 1

    # Bench reporting (every 2 seconds)
    if (now - last_report) >= report_every:
        ... log bench metrics ...
        ... write bench_metrics.csv ...
        ... reset counters ...

    # Sleep remaining time
    to_sleep = max(0.0, interval - dt)
    stop_event.wait(timeout=to_sleep)
```

---

## 3. Continuous Job Path

For each table in `job.tables`:

### 3a. READ

```python
vals = _read_mapping_values(tbl_id)
```

This function:
1. Loads the **mapping** from the in-memory Store (field → address/nodeId/encoding/scale).
2. Loads the **device** (protocol, params, gatewayId).
3. Dispatches by protocol:

**OPC UA path:**
```
endpoint = gateway.host OR device.params.endpoint OR default
client   = _get_opcua_client(endpoint)     # cached dict, keyed by endpoint
for each field in mapping:
    node = client.get_node(nodeId)         # cached dict, keyed by (endpoint, nodeId)
    val  = node.get_value()                # synchronous OPC UA read
    if scale: val = val * scale
    values[field] = val
```

**Modbus TCP path:**
```
host    = gateway.host OR device.params.host/ip
port    = device.port OR device.params.port OR 502
unit_id = device.unitId OR 1
client  = _get_modbus_client(host, port)   # cached dict, keyed by "host:port"
for each field in mapping:
    address  = int(spec.address)
    encoding = spec.encoding OR "float32"
    reg_count = ENCODING_MAP[encoding][0]
    rr = client.read_holding_registers(address, reg_count, device_id=unit_id)
    val = _decode_registers(rr.registers, encoding)
    # Post-decode coercion: bool16 → bool, uint16_enum → str
    if scale: val = val * scale
    values[field] = val
```

### 3b. WRITE (single-row path, no batching)

```python
engine = _db_engine_for_table(tbl_id)       # SQLAlchemy engine, thread-local cache
ident  = _physical_ident(engine, table.name) # e.g. "neuract"."apfc_005"
cols   = ["timestamp_utc"] + list(vals.keys())
params = {"ts": _now_ist_iso(), **vals}      # timestamp as IST ISO string
sql    = INSERT INTO {qualified} ({cols}) VALUES ({placeholders})
with engine.begin() as conn:
    conn.execute(text(sql), params)          # SQLAlchemy text query, all params as text
```

### 3c. WRITE (batched path)

When batching is enabled (`batch_count > 1` or `batch_ms > 0`):
```python
row = {"timestamp_utc": _now_ist_iso(), **vals}
buf = _batch_buffers[tbl_id]
buf.append(row)

# Flush if count threshold or time threshold hit
if len(buf) >= batch_count OR time_elapsed >= batch_ms:
    _write_table_values_batch(engine, ident, buf)  # executemany
    buf.clear()
```

On job stop, any remaining buffered rows are flushed.

---

## 4. Trigger Job Path

Triggers are grouped by table ID.

For each table:
1. **Read** all mapping values (same `_read_mapping_values()`).
2. **Evaluate** each trigger condition:
   - Operators: `change`, `>`, `>=`, `<`, `<=`, `==`, `!=`, `rising`, `falling`
   - `change`: `abs(current - previous) > deadband`
   - `rising`: `prev <= threshold AND current > threshold`
   - `falling`: `prev >= threshold AND current < threshold`
3. If any trigger fires → **write one row** (same INSERT logic as continuous).
4. Update `_job_last_values[job_id][table_id]` with current values.
5. Cooldown: if `cooldownMs` is set, suppress writes within the cooldown window.

---

## 5. Bench Metrics Reporting

Every 2 seconds, the loop logs and writes a CSV row:

```
Job {id} bench window=2.0s reads/s=1.0 writes/s=1.0 read_avg_ms=3.21 write_avg_ms=1.45
    loop_p95_ms=4.12 overrun_pct=0.0 cpu_time_ms=12.3 proc_cpu_pct=2.1
    proc_rss_mb=45.2 read_err=0 write_err=0
```

Written to: `agent/plc_agent/api/logs/bench_metrics.csv`

If primary CSV write fails, rows go to `bench_metrics_pending.csv` and are drained back on next success.

---

## 6. Job Stop

```
POST /jobs/{job_id}/stop
```

1. Sets `status='stopped'` in `app_jobs`.
2. Signals `_job_stops[job_id].set()` — the threading.Event.
3. The `stop_event.wait(timeout=to_sleep)` in the loop returns immediately.
4. Loop exits, thread finishes.
5. If batching was active, remaining buffered rows are flushed before exit.

---

## 7. Connection Caching

| Resource        | Cache Structure                  | Key                    | Lifecycle           |
|-----------------|----------------------------------|------------------------|---------------------|
| OPC UA clients  | `_opcua_clients: Dict[str, Any]` | endpoint URL           | Dropped on error    |
| OPC UA nodes    | `_opcua_nodes: Dict[tuple, Any]` | (endpoint, nodeId)     | Dropped with client |
| Modbus clients  | `_modbus_clients: Dict[str, Any]`| "host:port"            | Dropped on error    |
| DB engines      | `_thread_local.engine_cache`     | connection URL         | Per-thread, permanent |

---

## 8. Encoding Map (Modbus)

```python
_ENCODING_MAP = {
    "float32":     (2, ">f"),    # 2 registers, big-endian float
    "uint16":      (1, ">H"),    # 1 register, unsigned 16-bit
    "bool16":      (1, ">H"),    # 1 register, interpreted as bool
    "uint16_enum": (1, ">H"),    # 1 register, converted to string
    "int16":       (1, ">h"),    # 1 register, signed 16-bit
    "uint32":      (2, ">I"),    # 2 registers, unsigned 32-bit
    "int32":       (2, ">i"),    # 2 registers, signed 32-bit
    "float64":     (4, ">d"),    # 4 registers, double
    "uint64":      (4, ">Q"),    # 4 registers
    "int64":       (4, ">q"),    # 4 registers
}
```

Decode: pack registers as big-endian 16-bit words → struct.unpack with format string.

---

## 9. Timestamp Format

```python
IST = timezone(timedelta(hours=5, minutes=30))

def _now_ist_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()
    # e.g. "2026-02-26T09:14:01+05:30"
```

---

## 10. Key File Paths

| File | Purpose |
|------|---------|
| `agent/plc_agent/api/routers/jobs.py` | Main job runner (threaded loop, read, write) |
| `agent/plc_agent/api/routers/jobs2.py` | Lightweight status-only API (for external runners like Rust) |
| `agent/plc_agent/api/store.py` | In-memory store (jobs, tables, devices, mappings) |
| `agent/plc_agent/api/appdb.py` | PostgreSQL schema (app_jobs, app_devices, etc.) |
| `agent/plc_agent/api/logs/agent.log` | Rotating log file (500 MB max, unlimited backups) |
| `agent/plc_agent/api/logs/bench_metrics.csv` | Performance metrics CSV |
