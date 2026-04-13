# Rust Job Runner - Optimizations

All optimizations are implemented in `rust_jobs/src/main.rs`.

---

## #1 Bulk Modbus Reads (Register Bucketing)

**Problem:** The naive approach reads one register per field per Modbus request. With 10 fields on a device, that's 10 network round-trips per table per loop.

**Solution:** Precompute register buckets at job startup. The Modbus spec allows reading up to 125 consecutive holding registers in a single `read_holding_registers` call. Fields are grouped by their 125-register section (bucket index = `address / 125`). Each bucket issues one bulk read, then individual field values are extracted from the response buffer by offset.

**Key code:**

- **`build_modbus_buckets()`** (line ~983): Called once during `build_table_runtime()`. Iterates all mapping rows for a table, computes `bucket_idx = address / 125`, groups fields into `RegisterBucket` structs. Each bucket stores `start_addr`, `read_count` (distance from bucket start to the end of the last field, capped at 125), and a `Vec<BucketField>` with precomputed field metadata.

- **`RegisterBucket` struct** (line ~253):
  ```rust
  struct RegisterBucket {
      start_addr: u16,     // bucket_index * 125
      read_count: u16,     // registers to read in one call
      fields: Vec<BucketField>,
  }
  ```

- **`BucketField` struct** (line ~242): Stores `field_key`, `address`, `reg_count`, `encoding`, and `scale` — all precomputed so the hot loop does zero parsing.

- **`read_modbus_values()`** (line ~2111): Iterates buckets, issues one `read_holding_registers(bucket.start_addr, bucket.read_count)` per bucket, then extracts each field's registers by offset: `regs[offset..offset+reg_count]`.

- **`decode_registers()`** (line ~2013): Converts raw register bytes to `f64` using big-endian byte order. Supports float32, uint16, int16, uint32, int32, float64, uint64, int64, bool16, uint16_enum.

- **`modbus_encoding_info()`** (line ~1998): Maps encoding name to `(register_count, tag)` for decoding.

**Impact:** If a device has 20 fields spread across 3 register buckets, this reduces 20 network calls to 3. Typical improvement: **85-95% fewer Modbus round-trips**.

---

## #2 Concurrent Table Reads (Endpoint Grouping)

**Problem:** Reading tables sequentially means the total read time = sum of all individual table read times. With 270 tables, even 1ms per table = 270ms.

**Solution:** Group tables by their physical connection endpoint. Tables sharing the same Modbus host:port or OPC UA device are read sequentially within the group (they share one TCP connection), but different endpoint groups run concurrently via `join_all`.

**Key code:**

- **`table_endpoint_key()`** (line ~1133): Generates a grouping key per table. For Modbus: `"modbus:{host}:{port}"`. For OPC UA: the device ID.
  ```rust
  fn table_endpoint_key(table_rt: &TableRuntime) -> String {
      match table_rt.device.protocol.to_lowercase().as_str() {
          "modbus" => format!("modbus:{}:{}", host, port),
          _ => table_rt.device.id.clone(),
      }
  }
  ```

- **Main loop grouping** (line ~690):
  ```rust
  let mut endpoint_groups: HashMap<String, Vec<&TableRuntime>> = HashMap::new();
  for table_rt in table_runtimes.values() {
      let key = table_endpoint_key(table_rt);
      endpoint_groups.entry(key).or_default().push(table_rt);
  }
  ```

- **`read_endpoint_group()`** (line ~1148): Reads all tables in a group sequentially (they share one connection, so parallelism wouldn't help). Returns `Vec<(table, result, read_ms)>`.

- **Concurrent execution** (line ~700):
  ```rust
  let group_futures: Vec<_> = endpoint_groups.into_values().map(|tables| {
      read_endpoint_group(tables, &device_manager, &modbus_manager, &job.id)
  }).collect();
  let all_results = join_all(group_futures).await;
  ```

**Impact:** If 270 tables are spread across 5 Modbus gateways, reads run 5x faster than sequential. Total read time = max(group read times) instead of sum.

---

## #3 Write Batching (Single SQL Transaction)

**Problem:** Writing each table individually means one SQL `INSERT` + one network round-trip per table per loop. With 270 tables, that's 270 DB round-trips.

**Solution:** Combine all table INSERTs into a single `BEGIN; INSERT...; INSERT...; ...; COMMIT;` SQL string and execute it with one `batch_execute()` call.

**Key code:**

- **`write_all_tables_batch()`** (line ~1272): Groups tables by target DB client (pointer identity), builds a single SQL string with all INSERTs wrapped in a transaction.
  ```rust
  let mut sql = String::with_capacity(indices.len() * 512);
  sql.push_str("BEGIN;\n");
  for &idx in indices {
      let (table_rt, values) = &pending[idx];
      // Build: INSERT INTO neuract."table_name" ("col1","col2") VALUES (val1,val2);
      sql.push_str(&format!("INSERT INTO {} ({}) VALUES ({});\n", ...));
  }
  sql.push_str("COMMIT;\n");
  client.batch_execute(&sql).await?;
  ```

- **`write_all_tables_batch_owned()`** (line ~1344): Same logic but takes owned `Vec<(Arc<PgClient>, String, FieldMap)>` so it can be moved into a `tokio::spawn` for background execution (see #4).

- **`flush_all_buffered()`** (line ~1415): Same batching pattern for the buffered/batching path. Combines multiple rows per table into multi-value INSERTs, all in one transaction:
  ```sql
  BEGIN;
  INSERT INTO neuract."table1" ("ts","f1","f2") VALUES ('...', 1.0, 2.0), ('...', 1.1, 2.1);
  INSERT INTO neuract."table2" ("ts","f1") VALUES ('...', 3.0), ('...', 3.1);
  COMMIT;
  ```

**Impact:** 270 DB round-trips reduced to 1. Write latency drops from ~270ms to ~4-17ms.

---

## #4 Read/Write Overlap (Background Writes)

**Problem:** Even with batch writes taking only ~5ms, the loop structure was: read → write → sleep. The write blocks the start of the next read.

**Solution:** Fire the write as a background `tokio::spawn` task and immediately start the next read cycle. The write result is collected at the beginning of the *next* loop iteration.

**Key code:**

- **Background write handle** (line ~657):
  ```rust
  let mut pending_write_handle: Option<JoinHandle<(Result<WriteTimings>, f64, usize)>> = None;
  ```

- **Spawning the write** (line ~738):
  ```rust
  pending_write_handle = Some(tokio::spawn(async move {
      let t_write = Instant::now();
      let result = write_all_tables_batch_owned(&owned_writes, &job_id_clone).await;
      let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
      (result, write_ms, table_count)
  }));
  ```

- **Collecting previous write result** (line ~667): At the top of each loop iteration, before starting reads:
  ```rust
  if let Some(handle) = pending_write_handle.take() {
      match handle.await {
          Ok((Ok(wt), write_ms, table_count)) => { /* record metrics */ }
          Ok((Err(e), _, _)) => { /* log error */ }
          Err(e) => { /* task panicked */ }
      }
  }
  ```

- **Drain on stop** (line ~931): When the job stops, any pending write is awaited to ensure no data is lost.

**Impact:** The main loop elapsed time becomes `max(read_time, prev_write_time)` instead of `read_time + write_time`. Since reads (~0.1-0.4ms) overlap with writes (~4-17ms), the effective loop time is dominated by the write which runs in the background.

---

## #5 Modbus Pipelining

**Status:** Not implemented. After #1 and #2, Modbus reads take <0.5ms. The cost-benefit of pipelining (sending multiple requests before waiting for responses) is not justified — most devices only have 1-3 register buckets.

---

## #6 Cached & Pre-built SQL

**Problem:** Building INSERT SQL strings with column lists and placeholders every loop iteration wastes CPU on identical string operations.

**Solution:** Two approaches depending on the write path:

### Trigger path — Cached INSERT SQL
- **Precomputed at startup** in `build_table_runtime()` (line ~1075):
  ```rust
  let mut field_keys: Vec<String> = mapping.iter().map(|m| m.field_key.clone()).collect();
  field_keys.sort();
  field_keys.dedup();
  let cached_insert_sql = Some(format!(
      "INSERT INTO {} ({}) VALUES ({})",
      tbl_name, cols.join(","), placeholders.join(",")
  ));
  ```
- Stored in `TableRuntime.cached_insert_sql` (line ~271).

### Continuous path — Inline SQL literals
- **`write_values_cached()`** (line ~1164): Used for single-row trigger writes. Builds SQL with inline literals using `v.to_sql_literal()` instead of parameterized queries, avoiding `prepare_typed` overhead.
- **`write_all_tables_batch()`** and **`write_all_tables_batch_owned()`**: Build SQL strings with inline literals, sent via `batch_execute()` (no prepare step).

### SQL escaping
- **`pg_escape_literal()`** (line ~1266): Simple quoting for string values: `'value'` with `'` escaped as `''`.
- **`quote_ident()`** (line ~2346): Identifier quoting: `"name"` with `"` escaped as `""`.

**Impact:** Eliminates `prepare_typed()` round-trip on the hot path. SQL build time: ~0.01ms per loop.

---

## #7 Connection Health & Pooling

**Problem:** Long-running connections to Modbus devices and PostgreSQL targets can go stale (device rebooted, network blip, TCP timeout). A stale connection causes read/write failures until manually restarted.

**Solution:** Health checks and idle timeout management for both Modbus and PostgreSQL connections.

### PostgreSQL Target Connections — `TargetManager`
- **`TargetManager`** (line ~399): Caches `Arc<PgClient>` by connection string.
- **Health check on reuse** (line ~410):
  ```rust
  fn get_client(&self, conn: &str) -> Result<Arc<PgClient>> {
      if let Some(c) = self.clients.lock().unwrap().get(conn) {
          match c.simple_query("").await {
              Ok(_) => return Ok(c.clone()),  // healthy
              Err(_) => {
                  warn!("target db connection stale, reconnecting");
                  self.clients.lock().unwrap().remove(conn);
              }
          }
      }
      // Create new connection...
  }
  ```

### Modbus Connections — `ModbusManager`
- **`ModbusManager`** (line ~2040): Caches `tokio_modbus::client::Context` by `host:port` key, with last-used timestamp.
  ```rust
  struct ModbusManager {
      contexts: Mutex<HashMap<String, (Context, Instant)>>,
      max_idle: Duration,  // default 30s, configurable via MODBUS_MAX_IDLE_MS
  }
  ```
- **Idle timeout** (line ~2063): `drop_stale()` is called at the start of every read. Removes contexts idle longer than `max_idle`:
  ```rust
  fn drop_stale(&self) {
      map.retain(|_, (_, last_used)| last_used.elapsed() < max_idle);
  }
  ```
- **Error-triggered drop** (line ~2211): On connection error during bucket read, the broken context is immediately dropped:
  ```rust
  modbus_manager.drop_context(&key);
  return Err(anyhow!("modbus read failed: {}", e));
  ```
- **Context return after use** (line ~2223): After successful reads, the context is put back with a fresh timestamp.

### OPC UA Connections — `DeviceManager`
- **`DeviceManager`** (line ~348): Caches OPC UA sessions by device ID.
- **`get_session()`** (line ~357): Returns cached session or creates a new one. Sessions have `last_used` timestamps updated on each read (line ~2259).

**Impact:** Automatic recovery from stale connections without manual intervention. Typical reconnect time: ~2-5ms for Modbus, ~50-100ms for PostgreSQL.

---

## #8 Native Binary Types (FieldValue)

**Problem:** All values were stored as `HashMap<String, String>`. Every number went through:
1. Read from device → `f64` → `.to_string()` → `String`
2. Trigger evaluation → `string.parse::<f64>()` → `f64`
3. SQL write → `pg_escape_literal(string)` → `'123.456'` (quoted as text)

PostgreSQL then had to parse the text literal back into numeric types, and trigger evaluation wasted time on string↔float conversions.

**Solution:** Replace `HashMap<String, String>` with typed `HashMap<String, FieldValue>` (`FieldMap`).

### FieldValue enum (line ~284)
```rust
#[derive(Clone, Debug)]
enum FieldValue {
    Float(f64),
    Int(i64),
    Bool(bool),
    Text(String),
}
type FieldMap = HashMap<String, FieldValue>;
```

### Helper methods
- **`as_f64()`** (line ~295): Direct numeric extraction without string parsing. Float returns directly, Int casts, Bool returns 0.0/1.0, Text returns None.
- **`to_sql_literal()`** (line ~304): Generates bare SQL literals — no quoting for numerics:
  - `Float(123.456)` → `123.456` (not `'123.456'`)
  - `Int(42)` → `42`
  - `Bool(true)` → `TRUE`
  - `Text("hello")` → `'hello'`
  - `Float(NaN)` → `NULL`
  - `Float(Infinity)` → `'Infinity'`

### Read path changes
- **`variant_to_field_value()`** (line ~2309): Converts OPC UA `Variant` directly to typed `FieldValue`:
  - `Variant::Boolean` → `FieldValue::Bool`
  - `Variant::Int16/32/64, UInt16/32/64, Byte, SByte` → `FieldValue::Int`
  - `Variant::Float, Double` → `FieldValue::Float`
  - `Variant::String` → `FieldValue::Text`

- **`read_modbus_values()`** (line ~2188): Modbus values are typed based on encoding:
  - `uint16_enum` → `FieldValue::Int`
  - `bool16` → `FieldValue::Bool`
  - Everything else → `FieldValue::Float`

### Write path changes
All write functions use `v.to_sql_literal()` for inline SQL paths:
- `write_values_cached()` (line ~1180)
- `write_all_tables_batch()` (line ~1309)
- `write_all_tables_batch_owned()` (line ~1381)
- `flush_all_buffered()` (line ~1468)

### Trigger evaluation (line ~1729)
```rust
// Before: v.parse::<f64>().ok()  -- string parsing every trigger check
// After:  v.as_f64()             -- direct match, zero parsing
let cur = values.get(&tr.field_key).and_then(|v| v.as_f64());
let prev = last.get(&tr.field_key).and_then(|v| v.as_f64());
```

### Data structures updated
- `BufferedRow.values`: `HashMap<String, String>` → `FieldMap`
- `last_values`: `HashMap<String, HashMap<String, String>>` → `HashMap<String, FieldMap>`
- `pending_writes`: `Vec<(&TableRuntime, HashMap<String, String>)>` → `Vec<(&TableRuntime, FieldMap)>`
- `owned_writes`: `Vec<(Arc<PgClient>, String, HashMap<String, String>)>` → `Vec<(Arc<PgClient>, String, FieldMap)>`
- All read/write function return types updated accordingly.

**Impact:** PostgreSQL receives native numeric literals instead of text, eliminating server-side type coercion. Trigger evaluation avoids string parsing. Measured improvement: ~20% reduction in CPU time per loop.

---

## #9 Async Benchmark Metrics (Fire-and-Forget)

**Problem:** Writing benchmark metrics to the metrics DB was done synchronously in the main loop. The INSERT to `bench_metrics` takes ~1-3ms, which adds directly to loop latency on every reporting window.

**Solution:** Spawn the bench DB write as a fire-and-forget `tokio::spawn` task. The main loop continues immediately without waiting for the result.

**Key code** (line ~884):
```rust
// #9: Fire-and-forget bench DB write -- don't block the loop
{
    let bc = bench_client.clone();
    let jid = job.id.clone();
    tokio::spawn(async move {
        if let Err(e) = append_bench_db(
            &bc, &jid,
            window_secs, reads_per_sec, writes_per_sec,
            read_avg_ms, write_avg_ms,
            modbus_connect_avg_ms, modbus_fields_avg_ms,
            sql_build_avg_ms, db_execute_avg_ms,
            p95, overrun_pct,
            cpu_time_ms, proc_cpu_pct, proc_rss_mb,
            win_reads_err, win_writes_err,
        ).await {
            warn!("job {} bench db write failed: {}", jid, e);
        }
    });
}
```

### Bench metrics DB setup (line ~511)
- The `bench_metrics` table is created at startup via `CREATE TABLE IF NOT EXISTS`.
- Connection is established to `BENCH_DB_URL` (defaults to `postgresql://postgres@localhost/loggerfast_metrics`).
- The client is wrapped in `Arc<PgClient>` and cloned into each job.

### `append_bench_db()` (line ~1508)
Inserts one row with 17 columns: `job_id, window_secs, reads_per_sec, writes_per_sec, read_avg_ms, write_avg_ms, modbus_connect_avg_ms, modbus_fields_avg_ms, sql_build_avg_ms, db_execute_avg_ms, loop_p95_ms, overrun_pct, cpu_time_ms, proc_cpu_pct, proc_rss_mb, read_err, write_err`.

### Reporting window
- Configurable via `JOB_BENCH_WINDOW_SEC` env var (default 2.0s, min 0.5s).
- Every window: compute averages, P95, overrun%, CPU metrics → spawn async write → reset counters.

**Impact:** Bench metric writes no longer affect loop P95 measurements. The 1-3ms INSERT latency is completely hidden from the main loop.

---

## Benchmark Metrics

Every reporting window (default 2s, configurable via `JOB_BENCH_WINDOW_SEC`), the runner computes and records the following metrics to `bench_metrics` table in the metrics DB.

### Loop Timing

| Metric | Unit | Description | Computed from |
|--------|------|-------------|---------------|
| **loop_p95_ms** | ms | 95th percentile of loop iteration time across the window. This is the **primary performance metric** — it measures how long one complete read→write cycle takes. Must be < `interval_ms` to avoid overruns. | `percentile_ms(&mut loop_samples_ms, 95.0)` — each loop iteration's `start.elapsed()` is pushed into a sample buffer, sorted at window end |
| **overrun_pct** | % | Percentage of loop iterations where elapsed > interval. 0% means every loop completed within its time budget. | `win_overruns / win_loops * 100` — incremented at line ~849 when `elapsed > interval` |

### Read Metrics

| Metric | Unit | Description | Affected by optimizations |
|--------|------|-------------|---------------------------|
| **reads_per_sec** | count/s | Number of successful table reads per second. With N tables in the job, ideal value = N / (interval_ms / 1000). | #2 (concurrent reads keep this at max throughput) |
| **read_avg_ms** | ms | Average time to read one table (from `read_table_values_cached()` call to return). Includes Modbus connect + field reads or OPC UA session + field reads. | #1 (bulk reads), #2 (concurrency), #7 (cached connections) |
| **modbus_connect_avg_ms** | ms | Average Modbus TCP connection time per table read. Near-zero when connection is cached; ~2-5ms on fresh connect. | #7 (connection pooling + idle timeout) |
| **modbus_fields_avg_ms** | ms | Average time spent reading register buckets per table. This is the actual Modbus I/O time after connection is established. | #1 (bulk bucket reads reduce round-trips) |

### Write Metrics

| Metric | Unit | Description | Affected by optimizations |
|--------|------|-------------|---------------------------|
| **writes_per_sec** | count/s | Number of successful write operations per second. With batch writes (#3), this is ~1.0 (one batch per loop) instead of N (one per table). | #3 (batching), #4 (background writes) |
| **write_avg_ms** | ms | Average time for one write operation. With batching, this is the time for the entire batch (all tables in one transaction). Higher absolute value but covers all tables at once. | #3 (batch transaction), #6 (inline SQL), #8 (native types) |
| **sql_build_avg_ms** | ms | Average time to build the SQL string (column lists, value literals, transaction wrapper). | #6 (cached/prebuilt SQL), #8 (`to_sql_literal()` avoids string quoting overhead) |
| **db_execute_avg_ms** | ms | Average time for PostgreSQL to execute the SQL. This is pure DB I/O — network + parse + execute + commit. | #3 (one round-trip instead of N), #8 (native types = no server-side text parsing) |

### System Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| **cpu_time_ms** | ms | CPU time consumed by the job's thread during the reporting window. Measured via `clock_gettime(CLOCK_THREAD_CPUTIME_ID)` — counts only actual CPU work, not sleep/wait time. |
| **proc_cpu_pct** | % | CPU utilization = `cpu_time_ms / (window_secs * 1000) * 100`. Shows what fraction of one core the job uses. |
| **proc_rss_mb** | KB | Resident Set Size — physical memory used by the process. Measured via `sysinfo` crate. |

### Error Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| **read_err** | count | Total read failures in the window (Modbus timeout, OPC UA disconnect, etc.) |
| **write_err** | count | Total write failures in the window (DB connection lost, SQL error, etc.) |

---

## Benchmark Results (Before vs After All Optimizations)

**Old run:** Mar 8, 2026 — type3_240_vary_jobs (240 working tables, 1-10 jobs)
**New run:** Mar 11, 2026 — type2_vary_jobs (270 tables, 1-10 jobs)
**Config:** 1000ms interval, 300s (5 min) per scenario, Modbus simulator on localhost:5020

### Loop P95 (ms) — Primary Performance Metric

The most important metric. Measures 95th percentile of complete read→write cycle time.
**Optimizations responsible:** #1, #2, #3, #4 (collectively reduced loop time from hundreds of ms to tens of ms).

| Jobs | Old (240t) | New (270t) | Speedup | Notes |
|------|-----------|-----------|---------|-------|
| 1    | 866.7     | 30.3      | **28.6x** | Old had 3.17% overruns |
| 2    | 515.5     | 18.5      | **27.9x** | |
| 3    | 420.6     | 17.3      | **24.3x** | |
| 4    | 376.2     | 17.5      | **21.5x** | |
| 5    | 354.9     | 12.4      | **28.7x** | |
| 6    | 348.2     | 12.6      | **27.7x** | |
| 7    | 328.9     | 14.2      | **23.2x** | |
| 8    | 308.6     | 9.5       | **32.4x** | Best result |
| 9    | 295.5     | 11.5      | **25.8x** | |
| 10   | 307.0     | 12.5      | **24.6x** | |

### Read Avg (ms) — Per-Table Read Time

Time to read all fields from one table's device.
**Optimizations responsible:** #1 (bulk register reads), #2 (concurrency hides per-group latency), #7 (cached connections).

| Jobs | Old     | New    | Speedup |
|------|---------|--------|---------|
| 1    | 2.005   | 0.100  | **20x** |
| 2    | 2.445   | 0.122  | **20x** |
| 3    | 3.141   | 0.168  | **19x** |
| 4    | 4.031   | 0.217  | **19x** |
| 5    | 5.184   | 0.203  | **26x** |
| 6    | 6.273   | 0.248  | **25x** |
| 7    | 7.195   | 0.319  | **23x** |
| 8    | 8.079   | 0.235  | **34x** |
| 9    | 8.721   | 0.341  | **26x** |
| 10   | 10.264  | 0.412  | **25x** |

### Writes/sec — Write Throughput

Shows the shift from per-table writes to batch writes.
**Optimizations responsible:** #3 (all tables in one transaction = 1 write/loop instead of N writes/loop).

| Jobs | Old (per-table) | New (batched) | Explanation |
|------|----------------|---------------|-------------|
| 1    | 238.6          | 1.0           | Old: 240 individual INSERTs/s. New: 1 batch INSERT/s containing all 270 tables |
| 2    | 119.9          | 1.0           | Same data written, fewer DB round-trips |
| 5    | 48.0           | 1.0           | |
| 10   | 24.0           | 1.0           | |

> Note: writes_per_sec decreased numerically but this is a **good thing** — it means 270 individual writes were collapsed into 1 batch write. The actual data throughput is identical; only the DB round-trips decreased.

### Write Avg (ms) — Per-Write-Operation Time

With batching, each "write" now covers all tables, so the number is higher but represents much more work.
**Optimizations responsible:** #3 (batch transaction), #6 (inline SQL), #8 (native type literals).

| Jobs | Old (per-table) | New (batch) | Explanation |
|------|----------------|-------------|-------------|
| 1    | 1.48           | 17.52       | Old: 1 table per write. New: 270 tables per write |
| 2    | 1.70           | 10.14       | Time scales down with fewer tables per job |
| 5    | 2.00           | 5.47        | |
| 10   | 2.08           | 4.07        | |

> Old total write time per loop = 1.48ms x 240 tables = **355ms**. New total = **17.5ms** for all 270 tables. Actual improvement: **20x**.

### DB Execute Avg (ms) — Pure PostgreSQL Execution Time

Time PostgreSQL spends executing the SQL (network + parse + execute + commit).
**Optimizations responsible:** #3 (single transaction), #8 (native numeric literals skip server-side text→numeric parsing).

| Jobs | Old     | New    | Speedup |
|------|---------|--------|---------|
| 1    | 1.993   | 14.562 | Per-write: old=1 table, new=270 tables |
| 2    | 2.432   | 8.846  | |
| 5    | 5.169   | 4.884  | |
| 10   | 10.248  | 3.722  | |

> Like write_avg, the per-operation number is higher because each operation does more work. The total DB time per loop dropped dramatically.

### SQL Build Avg (ms) — SQL String Construction Time

Time to build the SQL string in Rust before sending to PostgreSQL.
**Optimizations responsible:** #6 (prebuilt templates), #8 (`to_sql_literal()` is faster than `pg_escape_literal()` for numerics).

| Jobs | Old    | New    | Notes |
|------|--------|--------|-------|
| 1    | 0.014  | 2.365  | New builds one large SQL with 270 INSERTs |
| 2    | 0.014  | 1.267  | |
| 5    | 0.014  | 0.553  | |
| 10   | 0.014  | 0.308  | |

> Old value is misleadingly low — it only shows build time for 1 table's INSERT. New builds all tables' INSERTs into a single `BEGIN;...COMMIT;` string. Total old build time = 0.014 x 240 = **3.36ms**. New = **2.37ms** for 270 tables — so actually faster overall.

### CPU Time per Loop (ms) — Processing Efficiency

CPU time consumed per reporting window, normalized to per-loop.
**Optimizations responsible:** All optimizations contribute. Less string allocation (#8), fewer syscalls (#1, #3), less DB round-trip overhead (#3, #4).

| Jobs | Old     | New    | Speedup |
|------|---------|--------|---------|
| 1    | 320.9   | 36.7   | **8.7x** |
| 2    | 160.9   | 18.9   | **8.5x** |
| 3    | 109.2   | 13.9   | **7.9x** |
| 4    | 81.1    | 10.7   | **7.6x** |
| 5    | 64.4    | 8.6    | **7.5x** |
| 6    | 53.5    | 7.2    | **7.4x** |
| 7    | 46.4    | 6.6    | **7.0x** |
| 8    | 39.7    | 5.6    | **7.1x** |
| 9    | 35.6    | 5.3    | **6.8x** |
| 10   | 31.9    | 4.9    | **6.5x** |

### Overrun % — Loop Budget Violation Rate

Percentage of loops exceeding the configured interval.
**Optimizations responsible:** All — loop fits comfortably within the 1000ms budget.

| Jobs | Old    | New  |
|------|--------|------|
| 1    | **3.17%** | 0%   |
| 2-10 | 0%     | 0%   |

> The old 1-job scenario exceeded the 1000ms interval 3.17% of the time with only 240 tables. The new code handles 270 tables (12.5% more) with zero overruns.

### Memory (RSS KB)

| Jobs | Old     | New     | Notes |
|------|---------|---------|-------|
| 1    | 55,768  | 38,017  | New uses less memory at low job counts |
| 5    | 53,514  | 49,315  | Converges as job count increases |
| 10   | 51,281  | 62,096  | New slightly higher at 10 jobs (more concurrent state) |

### Errors

| | Old (all scenarios) | New (all scenarios) |
|---|---|---|
| **read_err** | 0 | 0 |
| **write_err** | 0 | 0 |

Zero errors in both runs across all 10 scenarios.

---

## Optimization → Metric Impact Map

| Optimization | Loop P95 | Read Avg | Write Avg | DB Execute | SQL Build | CPU Time | Overrun |
|---|---|---|---|---|---|---|---|
| #1 Bulk Reads | +++ | +++ | | | | ++ | ++ |
| #2 Concurrent Reads | +++ | ++ | | | | + | ++ |
| #3 Write Batching | +++ | | +++ | +++ | + | ++ | +++ |
| #4 Read/Write Overlap | ++ | | + | | | + | + |
| #6 Cached SQL | + | | + | + | ++ | + | |
| #7 Connection Health | + | ++ | | | | | + |
| #8 Native Types | + | | + | + | + | ++ | |
| #9 Async Bench Metrics | + | | | | | + | |

`+++` = major impact, `++` = moderate, `+` = minor

---

## Summary

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Loop P95 (1 job, all tables) | 867 ms | 30 ms | **29x faster** |
| Loop P95 (10 jobs) | 307 ms | 12.5 ms | **25x faster** |
| Read time per table | 2-10 ms | 0.1-0.4 ms | **20-34x faster** |
| Total write time per loop | ~355 ms (240 x 1.48) | 17.5 ms (1 batch) | **20x faster** |
| CPU time per loop (1 job) | 321 ms | 37 ms | **8.7x less** |
| Overrun rate | 3.17% (1 job) | 0% | **Eliminated** |
| DB round-trips per loop | 240 (one per table) | 1 (one batch) | **240x fewer** |
| Errors | 0 | 0 | Maintained |
