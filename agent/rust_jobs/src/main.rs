use std::collections::HashMap;
use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Context, Result};
use base64::Engine;
use byteorder::{BigEndian, ByteOrder};
use chrono::{Utc, Local};
use log::{error, info, warn, LevelFilter};
use opcua::client::prelude::*;
use opcua::sync::RwLock;
use opcua::types::Variant;
use tokio_modbus::prelude::{Reader, Slave, SlaveContext};
use tokio_postgres::{Client as PgClient, NoTls};
use tokio_postgres::types::{ToSql, Type};
use windows::Win32::Foundation::{HLOCAL, LocalFree};
use windows::Win32::Security::Cryptography::{
    CryptUnprotectData, CRYPTPROTECT_LOCAL_MACHINE, CRYPT_INTEGER_BLOB,
};
use futures::future::join_all;
use sysinfo::{Pid, System};

const DEFAULT_OPCUA_ENDPOINT: &str = "opc.tcp://127.0.0.1:4840/freeopcua/server/";
const ERROR_LOG_FILENAME: &str = "error_log_rust.csv";
const LOG_FILENAME: &str = "agent_rust.log";
const LOG_MAX_BYTES: u64 = 500 * 1024 * 1024; // 500 MB, matches Python

// --- Rotating file writer (mirrors Python RotatingFileHandler) ---

struct RotatingFileWriter {
    path: PathBuf,
    file: std::fs::File,
    written: u64,
    max_bytes: u64,
}

impl RotatingFileWriter {
    fn new(path: PathBuf, max_bytes: u64) -> std::io::Result<Self> {
        let existing_size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        Ok(Self {
            path,
            file,
            written: existing_size,
            max_bytes,
        })
    }

    fn rotate(&mut self) -> std::io::Result<()> {
        // Shift existing rotated files: .999 <- .998 <- ... <- .2 <- .1 <- current
        // Find the highest existing backup number
        let mut max_n = 0u32;
        for n in 1..=9999 {
            let backup = format!("{}.{}", self.path.display(), n);
            if fs::metadata(&backup).is_ok() {
                max_n = n;
            } else {
                break;
            }
        }
        // Shift files up: .N -> .N+1
        for n in (1..=max_n).rev() {
            let from = format!("{}.{}", self.path.display(), n);
            let to = format!("{}.{}", self.path.display(), n + 1);
            let _ = fs::rename(&from, &to);
        }
        // Rename current -> .1
        let backup1 = format!("{}.1", self.path.display());
        let _ = fs::rename(&self.path, &backup1);
        // Open fresh file
        self.file = OpenOptions::new().create(true).append(true).open(&self.path)?;
        self.written = 0;
        Ok(())
    }
}

impl std::io::Write for RotatingFileWriter {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        if self.written >= self.max_bytes {
            self.rotate()?;
        }
        let n = self.file.write(buf)?;
        self.written += n as u64;
        Ok(n)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        self.file.flush()
    }
}

fn log_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("logs")
}

fn setup_logging() {
    let lvl = env::var("RUST_LOG")
        .ok()
        .and_then(|s| s.parse::<LevelFilter>().ok())
        .unwrap_or(LevelFilter::Info);

    let dir = log_dir();
    let _ = fs::create_dir_all(&dir);
    let log_path = dir.join(LOG_FILENAME);

    // File writer (rotating)
    let file_writer = match RotatingFileWriter::new(log_path.clone(), LOG_MAX_BYTES) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("File logging setup warning: {}", e);
            // Fall back to console only
            fern::Dispatch::new()
                .format(|out, message, record| {
                    out.finish(format_args!(
                        "{} [{}] {}: {}",
                        Local::now().format("%Y-%m-%d %H:%M:%S"),
                        record.level(),
                        record.target(),
                        message
                    ))
                })
                .level(lvl)
                .chain(std::io::stderr())
                .apply()
                .ok();
            return;
        }
    };

    let file_writer = Mutex::new(file_writer);

    fern::Dispatch::new()
        .format(|out, message, record| {
            out.finish(format_args!(
                "{} [{}] {}: {}",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                record.level(),
                record.target(),
                message
            ))
        })
        .level(lvl)
        .chain(std::io::stderr())
        .chain(fern::Output::call(move |record| {
            let msg = format!(
                "{} [{}] {}: {}\n",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                record.level(),
                record.target(),
                record.args()
            );
            if let Ok(mut w) = file_writer.lock() {
                let _ = w.write_all(msg.as_bytes());
                let _ = w.flush();
            }
        }))
        .apply()
        .ok();

    info!("Logging to file: {}", log_path.display());
}

#[derive(Clone, Debug)]
struct JobDef {
    id: String,
    name: String,
    job_type: JobType,
    interval_ms: u64,
    tables: Vec<String>,
    triggers: Vec<Trigger>,
    batch_count: u64,
    batch_ms: f64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum JobType {
    Continuous,
    Trigger,
}

#[derive(Clone, Debug)]
struct Trigger {
    table_id: Option<String>,
    field_key: String,
    op: String,
    value: Option<f64>,
    deadband: f64,
}

#[derive(Clone, Debug)]
struct TableDef {
    id: String,
    name: String,
    db_target_id: Option<String>,
    device_id: Option<String>,
}

#[derive(Clone, Debug)]
struct DbTarget {
    id: String,
    provider: String,
    conn: String,
}

#[derive(Clone, Debug)]
struct Device {
    id: String,
    protocol: String,
    params: serde_json::Value,
    unit_id: Option<i32>,
    port: Option<i32>,
    gateway_id: Option<String>,
}

#[derive(Clone, Debug)]
struct MappingRow {
    field_key: String,
    protocol: String,
    address: String,
    data_type: String,
    scale: Option<f64>,
    deadband: Option<f64>,
    device_id: Option<String>,
}

#[derive(Clone, Debug)]
struct Gateway {
    id: String,
    name: Option<String>,
    host: Option<String>,
}

/// A field within a register bucket, precomputed at job startup.
#[derive(Clone, Debug)]
struct BucketField {
    field_key: String,
    address: u16,
    reg_count: u16,
    encoding: String,
    scale: Option<f64>,
}

/// A group of fields whose registers fall within the same 125-register section.
/// Bucket index = address / 125. All fields in bucket N have start addresses in [N*125, (N+1)*125).
#[derive(Clone, Debug)]
struct RegisterBucket {
    /// Start address for the bulk read (bucket_index * 125)
    start_addr: u16,
    /// Number of registers to read = max(field_addr + reg_count) - start_addr, capped at 125
    read_count: u16,
    /// Fields within this bucket
    fields: Vec<BucketField>,
}

struct TableRuntime {
    table: TableDef,
    target_client: Arc<PgClient>,
    mapping: Vec<MappingRow>,
    device: Device,
    gateway: Option<Gateway>,
    /// Precomputed register buckets for Modbus bulk reads (empty for non-Modbus devices)
    modbus_buckets: Vec<RegisterBucket>,
    /// #6: Cached prepared statement for single-row inserts (trigger path)
    cached_insert_sql: Option<String>,
}

struct ReadTimings {
    connect_ms: f64,
    fields_ms: f64,
}

struct WriteTimings {
    build_ms: f64,
    execute_ms: f64,
}

#[derive(Clone, Debug)]
enum FieldValue {
    Float(f64),
    Int(i64),
    Bool(bool),
    Text(String),
}

type FieldMap = HashMap<String, FieldValue>;

impl FieldValue {
    fn as_f64(&self) -> Option<f64> {
        match self {
            FieldValue::Float(v) => Some(*v),
            FieldValue::Int(v) => Some(*v as f64),
            FieldValue::Bool(v) => Some(if *v { 1.0 } else { 0.0 }),
            FieldValue::Text(_) => None,
        }
    }

    fn to_sql_literal(&self) -> String {
        match self {
            FieldValue::Float(v) => {
                if v.is_nan() {
                    "NULL".to_string()
                } else if v.is_infinite() {
                    if *v > 0.0 { "'Infinity'".to_string() } else { "'-Infinity'".to_string() }
                } else {
                    v.to_string()
                }
            }
            FieldValue::Int(v) => v.to_string(),
            FieldValue::Bool(v) => if *v { "TRUE".to_string() } else { "FALSE".to_string() },
            FieldValue::Text(s) => pg_escape_literal(s),
        }
    }
}

impl std::fmt::Display for FieldValue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FieldValue::Float(v) => write!(f, "{}", v),
            FieldValue::Int(v) => write!(f, "{}", v),
            FieldValue::Bool(v) => write!(f, "{}", v),
            FieldValue::Text(s) => write!(f, "{}", s),
        }
    }
}

struct BufferedRow {
    timestamp_utc: String,
    values: FieldMap,
}

static ERROR_CSV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

struct DeviceSession {
    endpoint: String,
    client: Client,
    session: Arc<RwLock<Session>>,
    nodes: HashMap<String, NodeId>,
    last_used: Instant,
}

struct DeviceManager {
    sessions: Mutex<HashMap<String, Arc<Mutex<DeviceSession>>>>,
}

impl DeviceManager {
    fn new() -> Self {
        Self { sessions: Mutex::new(HashMap::new()) }
    }

    fn get_session(&self, device: &Device) -> Result<Arc<Mutex<DeviceSession>>> {
        let dev_id = device.id.clone();
        if let Some(sess) = self.sessions.lock().unwrap().get(&dev_id) {
            return Ok(sess.clone());
        }
        let endpoint = device
            .params
            .get("endpoint")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .unwrap_or(DEFAULT_OPCUA_ENDPOINT);
        let endpoint = normalize_endpoint(endpoint);
        let endpoint_id = "default";
        let client = ClientBuilder::new()
            .application_name("neuract-job-runner")
            .application_uri("urn:neuract:job-runner")
            .product_uri("urn:neuract:job-runner")
            .trust_server_certs(true)
            .create_sample_keypair(true)
            .session_retry_limit(1)
            .endpoint(endpoint_id, ClientEndpoint::new(endpoint.clone()))
            .default_endpoint(endpoint_id)
            .client()
            .ok_or_else(|| anyhow!("opcua client build failed"))?;
        let mut client = client;
        let session = client
            .connect_to_endpoint_id(None)
            .map_err(|e| anyhow!("opcua connect failed: {}", e))?;
        let sess = DeviceSession {
            endpoint,
            client,
            session,
            nodes: HashMap::new(),
            last_used: Instant::now(),
        };
        let handle = Arc::new(Mutex::new(sess));
        self.sessions.lock().unwrap().insert(dev_id, handle.clone());
        Ok(handle)
    }
}

struct TargetManager {
    clients: Mutex<HashMap<String, Arc<PgClient>>>,
}

impl TargetManager {
    fn new() -> Self {
        Self { clients: Mutex::new(HashMap::new()) }
    }

    async fn get_client(&self, conn: &str) -> Result<Arc<PgClient>> {
        // #7: Check if cached client is still alive
        if let Some(c) = self.clients.lock().unwrap().get(conn) {
            // Quick health check — if this fails, drop and reconnect
            match c.simple_query("").await {
                Ok(_) => return Ok(c.clone()),
                Err(_) => {
                    warn!("target db connection stale, reconnecting: {}", conn);
                    self.clients.lock().unwrap().remove(conn);
                }
            }
        }
        let (client, connection) = tokio_postgres::connect(conn, NoTls)
            .await
            .context("target db connect failed")?;
        tokio::spawn(async move {
            if let Err(e) = connection.await {
                error!("target db connection error: {}", e);
            }
        });
        let client = Arc::new(client);
        self.clients.lock().unwrap().insert(conn.to_string(), client.clone());
        Ok(client)
    }
}

struct ProcSampler {
    system: System,
    pid: Pid,
    prev_thread_cpu_ns: u64,
}

impl ProcSampler {
    fn new() -> Self {
        let mut system = System::new();
        let pid = Pid::from_u32(std::process::id());
        system.refresh_process(pid);
        let prev_thread_cpu_ns = Self::thread_cpu_ns();
        Self { system, pid, prev_thread_cpu_ns }
    }

    fn thread_cpu_ns() -> u64 {
        let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
        unsafe { libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID, &mut ts) };
        ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
    }

    fn sample(&mut self, window_secs: f64) -> (Option<f64>, Option<f64>, Option<f64>) {
        // Per-thread CPU
        let now_ns = Self::thread_cpu_ns();
        let delta_ns = now_ns.saturating_sub(self.prev_thread_cpu_ns);
        self.prev_thread_cpu_ns = now_ns;
        let cpu_time_ms = delta_ns as f64 / 1_000_000.0;
        let cpu_pct = if window_secs > 0.0 {
            (cpu_time_ms / (window_secs * 1000.0)) * 100.0
        } else {
            0.0
        };

        // RSS is still process-wide (no per-thread alternative)
        self.system.refresh_process(self.pid);
        let rss_mb = self.system.process(self.pid)
            .map(|p| p.memory() as f64 / 1024.0)
            .unwrap_or(0.0);

        (Some(cpu_time_ms), Some(cpu_pct), Some(rss_mb))
    }
}

struct JobHandle {
    stop: Arc<AtomicBool>,
    join: std::thread::JoinHandle<()>,
}

#[tokio::main]
async fn main() -> Result<()> {
    setup_logging();
    let app_db_url = env::var("APP_DB_URL").context("APP_DB_URL is required")?;
    let bench_db_url = env::var("BENCH_DB_URL")
        .unwrap_or_else(|_| "postgresql://postgres@localhost/loggerfast_metrics".to_string());
    let poll_ms: u64 = env::var("JOB_POLL_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2000);

    let (meta_client, meta_conn) = tokio_postgres::connect(&app_db_url, NoTls)
        .await
        .context("metadata db connect failed")?;
    tokio::spawn(async move {
        if let Err(e) = meta_conn.await {
            error!("metadata db connection error: {}", e);
        }
    });

    // Connect to bench metrics DB
    let (bench_client, bench_conn) = tokio_postgres::connect(&bench_db_url, NoTls)
        .await
        .context("bench metrics db connect failed")?;
    tokio::spawn(async move {
        if let Err(e) = bench_conn.await {
            error!("bench metrics db connection error: {}", e);
        }
    });
    bench_client.execute(
        "CREATE TABLE IF NOT EXISTS bench_metrics (
            id              BIGSERIAL PRIMARY KEY,
            ts_utc          TIMESTAMPTZ NOT NULL DEFAULT now(),
            job_id          TEXT NOT NULL,
            window_secs     DOUBLE PRECISION,
            reads_per_sec   DOUBLE PRECISION,
            writes_per_sec  DOUBLE PRECISION,
            read_avg_ms     DOUBLE PRECISION,
            write_avg_ms    DOUBLE PRECISION,
            modbus_connect_avg_ms  DOUBLE PRECISION,
            modbus_fields_avg_ms   DOUBLE PRECISION,
            sql_build_avg_ms       DOUBLE PRECISION,
            db_execute_avg_ms      DOUBLE PRECISION,
            loop_p95_ms     DOUBLE PRECISION,
            overrun_pct     DOUBLE PRECISION,
            cpu_time_ms     DOUBLE PRECISION,
            proc_cpu_pct    DOUBLE PRECISION,
            proc_rss_mb     DOUBLE PRECISION,
            read_err        BIGINT DEFAULT 0,
            write_err       BIGINT DEFAULT 0
        )", &[]
    ).await.context("create bench_metrics table failed")?;
    info!("bench metrics DB connected: {}", bench_db_url);
    let bench_client = Arc::new(bench_client);

    let device_manager = Arc::new(DeviceManager::new());

    let meta_client = Arc::new(meta_client);
    let mut running: HashMap<String, JobHandle> = HashMap::new();

    loop {
        let jobs = load_running_jobs(meta_client.as_ref()).await?;
        let want: HashMap<String, JobDef> = jobs.into_iter().map(|j| (j.id.clone(), j)).collect();

        for job in want.values() {
            if running.contains_key(&job.id) {
                continue;
            }
            let stop = Arc::new(AtomicBool::new(false));
            let meta = meta_client.clone();
            let dm = device_manager.clone();
            let bc = bench_client.clone();
            let job_clone = job.clone();
            let job_id = job.id.clone();
            let stop_thread = stop.clone();
            let join = std::thread::spawn(move || {
                let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                    Ok(rt) => rt,
                    Err(e) => {
                        error!("job {} runtime init failed: {}", job_id, e);
                        return;
                    }
                };
                if let Err(e) = rt.block_on(run_job(job_clone, meta, dm, bc, stop_thread)) {
                    error!("job {} failed: {}", job_id, e);
                }
            });
            running.insert(job.id.clone(), JobHandle { stop, join });
        }

        let mut to_stop = Vec::new();
        for job_id in running.keys() {
            if !want.contains_key(job_id) {
                to_stop.push(job_id.clone());
            }
        }
        for job_id in to_stop {
            if let Some(handle) = running.remove(&job_id) {
                handle.stop.store(true, Ordering::Relaxed);
                let join = handle.join;
                std::thread::spawn(move || {
                    let _ = join.join();
                });
            }
        }

        tokio::time::sleep(Duration::from_millis(poll_ms)).await;
    }
}

async fn run_job(
    job: JobDef,
    meta_client: Arc<PgClient>,
    device_manager: Arc<DeviceManager>,
    bench_client: Arc<PgClient>,
    stop: Arc<AtomicBool>,
) -> Result<()> {
    let interval = Duration::from_millis(job.interval_ms.max(100));
    let report_every = Duration::from_secs_f64(
        env::var("JOB_BENCH_WINDOW_SEC")
            .ok()
            .and_then(|v| v.parse::<f64>().ok())
            .unwrap_or(2.0)
            .max(0.5),
    );
    let default_target = load_default_target(meta_client.as_ref()).await?;
    let target_manager = TargetManager::new();
    let modbus_manager = ModbusManager::new();
    let mut tables = Vec::new();
    for tid in &job.tables {
        if let Some(t) = load_table(meta_client.as_ref(), tid).await? {
            tables.push(t);
        }
    }
    let mut table_runtimes: HashMap<String, TableRuntime> = HashMap::new();
    for table in tables {
        match build_table_runtime(table, &default_target, meta_client.as_ref(), &target_manager).await {
            Ok(Some(rt)) => {
                table_runtimes.insert(rt.table.id.clone(), rt);
            }
            Ok(None) => {
                warn!("job {} table runtime skipped (missing mapping/device)", job.id);
            }
            Err(e) => {
                warn!("job {} table runtime build failed: {}", job.id, e);
            }
        }
    }
    let mut last_values: HashMap<String, FieldMap> = HashMap::new();
    let mut last_report = Instant::now();
    let mut win_reads_ok: u64 = 0;
    let mut win_reads_err: u64 = 0;
    let mut win_writes_ok: u64 = 0;
    let mut win_writes_err: u64 = 0;
    let mut win_read_ms_sum = 0.0f64;
    let mut win_write_ms_sum = 0.0f64;
    let mut win_modbus_connect_ms_sum = 0.0f64;
    let mut win_modbus_fields_ms_sum = 0.0f64;
    let mut win_sql_build_ms_sum = 0.0f64;
    let mut win_db_execute_ms_sum = 0.0f64;
    let mut win_loops: u64 = 0;
    let mut win_overruns: u64 = 0;
    let mut loop_samples_ms: Vec<f64> = Vec::with_capacity(256);
    let mut proc_sampler = ProcSampler::new();
    let use_batching = job.job_type == JobType::Continuous
        && (job.batch_count > 1 || job.batch_ms > 0.0);
    let mut batch_buffers: HashMap<String, Vec<BufferedRow>> = HashMap::new();
    let mut batch_flush_ts: HashMap<String, Instant> = HashMap::new();
    info!(
        "job {} started type={:?} interval_ms={} batching={}",
        job.id, job.job_type, job.interval_ms,
        if use_batching { format!("count={} ms={}", job.batch_count, job.batch_ms) } else { "off".to_string() }
    );

    // #4: Background write handle — overlap reads with previous write
    let mut pending_write_handle: Option<tokio::task::JoinHandle<(Result<WriteTimings>, f64, usize)>> = None;

    loop {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        let start = Instant::now();
        match job.job_type {
            JobType::Continuous => {
                // #4: Collect result from previous background write (if any)
                if let Some(handle) = pending_write_handle.take() {
                    match handle.await {
                        Ok((Ok(wt), write_ms, table_count)) => {
                            win_writes_ok += 1;
                            win_write_ms_sum += write_ms;
                            win_sql_build_ms_sum += wt.build_ms;
                            win_db_execute_ms_sum += wt.execute_ms;
                            info!("Job {} [WRITE_ALL_BG_DONE] tables={} elapsed_ms={:.2}", job.id, table_count, write_ms);
                        }
                        Ok((Err(e), _, _)) => {
                            win_writes_err += 1;
                            let emsg = e.to_string();
                            warn!("job {} batch write all failed: {}", job.id, emsg);
                            let _ = append_error_csv(&job.id, "ALL", "write", &emsg);
                        }
                        Err(e) => {
                            win_writes_err += 1;
                            warn!("job {} write task panicked: {}", job.id, e);
                        }
                    }
                }

                // Phase 1: Read all tables concurrently (grouped by endpoint)
                let mut endpoint_groups: HashMap<String, Vec<&TableRuntime>> = HashMap::new();
                for table_rt in table_runtimes.values() {
                    let key = table_endpoint_key(table_rt);
                    endpoint_groups.entry(key).or_default().push(table_rt);
                }
                info!(
                    "Job {} [READ_PHASE] groups={} tables={}",
                    job.id, endpoint_groups.len(), table_runtimes.len()
                );

                let group_futures: Vec<_> = endpoint_groups.into_values().map(|tables| {
                    read_endpoint_group(tables, &device_manager, &modbus_manager, &job.id)
                }).collect();
                let all_results = join_all(group_futures).await;

                let mut pending_writes: Vec<(&TableRuntime, FieldMap)> = Vec::new();
                for group in all_results {
                    for (table_rt, result, read_ms) in group {
                        match result {
                            Ok((v, rt)) => {
                                win_reads_ok += 1;
                                win_read_ms_sum += read_ms;
                                win_modbus_connect_ms_sum += rt.connect_ms;
                                win_modbus_fields_ms_sum += rt.fields_ms;
                                info!("Job {} [READ] table={} fields={} elapsed_ms={:.2}", job.id, table_rt.table.id, v.len(), read_ms);
                                pending_writes.push((table_rt, v));
                            }
                            Err(e) => {
                                win_reads_err += 1;
                                let emsg = e.to_string();
                                warn!("job {} table {} read failed: {}", job.id, table_rt.table.id, emsg);
                                let _ = append_error_csv(&job.id, &table_rt.table.id, "read", &emsg);
                            }
                        }
                    }
                }

                // Phase 2: Write all tables — fire and continue (#4: overlap with next read)
                if !use_batching {
                    if !pending_writes.is_empty() {
                        // Build owned data for the background task
                        let owned_writes: Vec<(Arc<PgClient>, String, FieldMap)> = pending_writes
                            .iter()
                            .filter(|(_, v)| !v.is_empty())
                            .map(|(rt, v)| (rt.target_client.clone(), rt.table.name.clone(), v.clone()))
                            .collect();
                        let table_count = owned_writes.len();
                        let job_id_clone = job.id.clone();
                        pending_write_handle = Some(tokio::spawn(async move {
                            let t_write = Instant::now();
                            let result = write_all_tables_batch_owned(&owned_writes, &job_id_clone).await;
                            let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
                            (result, write_ms, table_count)
                        }));
                    }
                } else {
                    // Buffer all reads
                    let ts = Utc::now().to_rfc3339();
                    for (table_rt, values) in pending_writes {
                        let tid = table_rt.table.id.clone();
                        batch_buffers.entry(tid.clone()).or_default()
                            .push(BufferedRow { timestamp_utc: ts.clone(), values });
                        batch_flush_ts.entry(tid).or_insert_with(Instant::now);
                    }

                    // Collect all buffers that need flushing
                    let mut to_flush: Vec<(String, Vec<BufferedRow>)> = Vec::new();
                    for (tid, buf) in batch_buffers.iter_mut() {
                        if buf.is_empty() { continue; }
                        let count_trigger = buf.len() as u64 >= job.batch_count;
                        let time_trigger = job.batch_ms > 0.0
                            && batch_flush_ts.get(tid).map_or(false, |t| t.elapsed().as_secs_f64() * 1000.0 >= job.batch_ms);
                        if count_trigger || time_trigger {
                            to_flush.push((tid.clone(), std::mem::take(buf)));
                        }
                    }

                    // Flush all due buffers in one batch
                    let flush_count = to_flush.len();
                    if !to_flush.is_empty() {
                        let total_rows: usize = to_flush.iter().map(|(_, rows)| rows.len()).sum();
                        let t_write = Instant::now();
                        match flush_all_buffered(&table_runtimes, &to_flush, &job.id).await {
                            Ok(wt) => {
                                let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
                                win_writes_ok += 1;
                                win_write_ms_sum += write_ms;
                                win_sql_build_ms_sum += wt.build_ms;
                                win_db_execute_ms_sum += wt.execute_ms;
                                info!("Job {} [FLUSH_ALL] tables={} rows={} elapsed_ms={:.2}", job.id, flush_count, total_rows, write_ms);
                            }
                            Err(e) => {
                                win_writes_err += 1;
                                let emsg = e.to_string();
                                warn!("job {} flush all failed: {}", job.id, emsg);
                                let _ = append_error_csv(&job.id, "ALL", "write", &emsg);
                            }
                        }
                        for (tid, _) in &to_flush {
                            batch_flush_ts.insert(tid.clone(), Instant::now());
                        }
                    }
                    let total_buffered: usize = batch_buffers.values().map(|b| b.len()).sum();
                    info!("Job {} [BATCH_STATUS] buffered={} flushed_tables={}", job.id, total_buffered, flush_count);
                }
            }
            JobType::Trigger => {
                let by_table = group_triggers(&job);
                for (table_id, triggers) in by_table {
                    let table_rt = match table_runtimes.get(&table_id) {
                        Some(rt) => rt,
                        None => continue,
                    };
                    let t_read = Instant::now();
                    let values = match read_table_values_cached(table_rt, &device_manager, &modbus_manager, &job.id).await {
                        Ok((v, rt)) => {
                            let read_ms = t_read.elapsed().as_secs_f64() * 1000.0;
                            win_reads_ok += 1;
                            win_read_ms_sum += read_ms;
                            win_modbus_connect_ms_sum += rt.connect_ms;
                            win_modbus_fields_ms_sum += rt.fields_ms;
                            info!("Job {} [TRIG_READ] table={} fields={} elapsed_ms={:.2}", job.id, table_id, v.len(), read_ms);
                            v
                        }
                        Err(e) => {
                            win_reads_err += 1;
                            let emsg = e.to_string();
                            warn!("job {} table {} read failed: {}", job.id, table_id, emsg);
                            let _ = append_error_csv(&job.id, &table_id, "read", &emsg);
                            continue;
                        }
                    };
                    let should_fire = eval_triggers(&triggers, table_id.as_str(), &values, &mut last_values);
                    info!("Job {} [TRIG_EVAL] table={} fired={}", job.id, table_id, should_fire);
                    if should_fire {
                        let t_write = Instant::now();
                        match write_values_cached(table_rt, &values, &job.id).await {
                            Ok(wt) => {
                                let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
                                win_writes_ok += 1;
                                win_write_ms_sum += write_ms;
                                win_sql_build_ms_sum += wt.build_ms;
                                win_db_execute_ms_sum += wt.execute_ms;
                                info!("Job {} [TRIG_WRITE] table={} elapsed_ms={:.2}", job.id, table_id, write_ms);
                            }
                            Err(e) => {
                                win_writes_err += 1;
                                let emsg = e.to_string();
                                warn!("job {} trigger write failed table {}: {}", job.id, table_id, emsg);
                                let _ = append_error_csv(&job.id, &table_id, "write", &emsg);
                            }
                        }
                    }
                    update_last_values(table_id.as_str(), &values, &mut last_values);
                }
            }
        }
        let elapsed = start.elapsed();
        win_loops += 1;
        if elapsed > interval {
            win_overruns += 1;
        }
        loop_samples_ms.push(elapsed.as_secs_f64() * 1000.0);
        if last_report.elapsed() >= report_every {
            let window_secs = last_report.elapsed().as_secs_f64();
            let reads_per_sec = if window_secs > 0.0 { win_reads_ok as f64 / window_secs } else { 0.0 };
            let writes_per_sec = if window_secs > 0.0 { win_writes_ok as f64 / window_secs } else { 0.0 };
            let read_avg_ms = if win_reads_ok > 0 { win_read_ms_sum / win_reads_ok as f64 } else { 0.0 };
            let write_avg_ms = if win_writes_ok > 0 { win_write_ms_sum / win_writes_ok as f64 } else { 0.0 };
            let modbus_connect_avg_ms = if win_reads_ok > 0 { win_modbus_connect_ms_sum / win_reads_ok as f64 } else { 0.0 };
            let modbus_fields_avg_ms = if win_reads_ok > 0 { win_modbus_fields_ms_sum / win_reads_ok as f64 } else { 0.0 };
            let sql_build_avg_ms = if win_writes_ok > 0 { win_sql_build_ms_sum / win_writes_ok as f64 } else { 0.0 };
            let db_execute_avg_ms = if win_writes_ok > 0 { win_db_execute_ms_sum / win_writes_ok as f64 } else { 0.0 };
            let p95 = percentile_ms(&mut loop_samples_ms, 95.0);
            let overrun_pct = if win_loops > 0 { (win_overruns as f64 / win_loops as f64) * 100.0 } else { 0.0 };
            let p95_txt = p95.map(|v| format!("{:.2}", v)).unwrap_or_else(|| "na".to_string());
            let (cpu_time_ms, proc_cpu_pct, proc_rss_mb) = proc_sampler.sample(window_secs);
            info!(
                "Job {} bench window={:.1}s reads/s={:.1} writes/s={:.1} read_avg_ms={:.3} write_avg_ms={:.3} connect_avg_ms={:.3} fields_avg_ms={:.3} build_avg_ms={:.3} exec_avg_ms={:.3} loop_p95_ms={} overrun_pct={:.1} read_err={} write_err={}",
                job.id,
                window_secs,
                reads_per_sec,
                writes_per_sec,
                read_avg_ms,
                write_avg_ms,
                modbus_connect_avg_ms,
                modbus_fields_avg_ms,
                sql_build_avg_ms,
                db_execute_avg_ms,
                p95_txt,
                overrun_pct,
                win_reads_err,
                win_writes_err,
            );
            // #9: Fire-and-forget bench DB write — don't block the loop
            {
                let bc = bench_client.clone();
                let jid = job.id.clone();
                tokio::spawn(async move {
                    if let Err(e) = append_bench_db(
                        &bc,
                        &jid,
                        window_secs,
                        reads_per_sec,
                        writes_per_sec,
                        read_avg_ms,
                        write_avg_ms,
                        modbus_connect_avg_ms,
                        modbus_fields_avg_ms,
                        sql_build_avg_ms,
                        db_execute_avg_ms,
                        p95,
                        overrun_pct,
                        cpu_time_ms,
                        proc_cpu_pct,
                        proc_rss_mb,
                        win_reads_err,
                        win_writes_err,
                    ).await {
                        warn!("job {} bench db write failed: {}", jid, e);
                    }
                });
            }
            last_report = Instant::now();
            win_reads_ok = 0;
            win_reads_err = 0;
            win_writes_ok = 0;
            win_writes_err = 0;
            win_read_ms_sum = 0.0;
            win_write_ms_sum = 0.0;
            win_modbus_connect_ms_sum = 0.0;
            win_modbus_fields_ms_sum = 0.0;
            win_sql_build_ms_sum = 0.0;
            win_db_execute_ms_sum = 0.0;
            win_loops = 0;
            win_overruns = 0;
            loop_samples_ms.clear();
        }
        let sleep = if elapsed >= interval { Duration::from_millis(0) } else { interval - elapsed };
        tokio::time::sleep(sleep).await;
    }
    // #4: Drain pending background write before stopping
    if let Some(handle) = pending_write_handle.take() {
        match handle.await {
            Ok((Ok(wt), write_ms, table_count)) => {
                info!("Job {} [WRITE_ALL_BG_FINAL] tables={} elapsed_ms={:.2}", job.id, table_count, write_ms);
            }
            Ok((Err(e), _, _)) => {
                warn!("job {} final background write failed: {}", job.id, e);
            }
            Err(e) => {
                warn!("job {} final write task panicked: {}", job.id, e);
            }
        }
    }
    // Final flush: write any remaining buffered rows before stopping
    if use_batching {
        let mut final_flush: Vec<(String, Vec<BufferedRow>)> = Vec::new();
        for (tid, buf) in batch_buffers.iter_mut() {
            if !buf.is_empty() {
                final_flush.push((tid.clone(), std::mem::take(buf)));
            }
        }
        if !final_flush.is_empty() {
            let total_rows: usize = final_flush.iter().map(|(_, rows)| rows.len()).sum();
            info!("Job {} [FLUSH_FINAL] tables={} rows={}", job.id, final_flush.len(), total_rows);
            match flush_all_buffered(&table_runtimes, &final_flush, &job.id).await {
                Ok(_) => {
                    info!("Job {} [FLUSH_FINAL] OK", job.id);
                }
                Err(e) => {
                    warn!("job {} final flush failed: {}", job.id, e);
                }
            }
        }
    }
    info!("job {} stopped", job.id);
    Ok(())
}

async fn process_table(
    job: &JobDef,
    table: &TableDef,
    default_target: &Option<String>,
    meta_client: &PgClient,
    device_manager: &Arc<DeviceManager>,
    target_manager: &Arc<TargetManager>,
) -> Result<()> {
    let values = read_table_values(table, default_target, meta_client, device_manager, target_manager).await?;
    write_values(table, default_target, meta_client, target_manager, &values).await?;
    Ok(())
}

/// Precompute register buckets for Modbus bulk reads.
/// Divides the register address space into 125-register sections and groups fields by section.
fn build_modbus_buckets(mapping: &[MappingRow]) -> Vec<RegisterBucket> {
    let mut bucket_map: HashMap<u16, Vec<BucketField>> = HashMap::new();

    for row in mapping {
        if !row.protocol.eq_ignore_ascii_case("modbus") {
            continue;
        }
        let addr_raw = row.address.trim();
        if addr_raw.is_empty() {
            continue;
        }
        let address: u16 = match addr_raw.parse() {
            Ok(a) => a,
            Err(_) => continue,
        };
        let encoding = if row.data_type.is_empty() {
            "float32".to_string()
        } else {
            row.data_type.to_lowercase()
        };
        let (reg_count, _) = modbus_encoding_info(&encoding);

        let bucket_idx = address / 125;
        bucket_map.entry(bucket_idx).or_default().push(BucketField {
            field_key: row.field_key.clone(),
            address,
            reg_count,
            encoding,
            scale: row.scale,
        });
    }

    let mut buckets: Vec<RegisterBucket> = Vec::new();
    for (bucket_idx, fields) in bucket_map {
        let start_addr = bucket_idx * 125;
        // read_count = distance from bucket start to the end of the last field, capped at 125
        let max_end = fields.iter()
            .map(|f| f.address + f.reg_count)
            .max()
            .unwrap_or(start_addr);
        let read_count = (max_end - start_addr).min(125);

        buckets.push(RegisterBucket {
            start_addr,
            read_count,
            fields,
        });
    }

    buckets.sort_by_key(|b| b.start_addr);
    buckets
}

async fn build_table_runtime(
    table: TableDef,
    default_target: &Option<String>,
    meta_client: &PgClient,
    target_manager: &TargetManager,
) -> Result<Option<TableRuntime>> {
    let target_id = table.db_target_id.clone().or_else(|| default_target.clone());
    let Some(target_id) = target_id else {
        return Ok(None);
    };
    let target = load_target(meta_client, &target_id).await?
        .ok_or_else(|| anyhow!("db target not found: {}", target_id))?;
    if !is_postgres_provider(&target.provider) {
        return Err(anyhow!("unsupported target provider: {}", target.provider));
    }
    let target_client = target_manager.get_client(&target.conn).await?;
    let mapping = load_mapping_rows(target_client.as_ref(), &table.name).await?;
    if mapping.is_empty() {
        return Ok(None);
    }
    let device_id = mapping.iter().find_map(|m| m.device_id.clone()).or_else(|| table.device_id.clone());
    let Some(device_id) = device_id else {
        return Ok(None);
    };
    let device = load_device(meta_client, &device_id).await?
        .ok_or_else(|| anyhow!("device not found: {}", device_id))?;
    // Load gateway if device has one (needed for Modbus host resolution)
    let gateway = if let Some(ref gw_id) = device.gateway_id {
        load_gateway(meta_client, gw_id).await.unwrap_or(None)
    } else {
        None
    };
    let modbus_buckets = if device.protocol.eq_ignore_ascii_case("modbus") {
        build_modbus_buckets(&mapping)
    } else {
        Vec::new()
    };
    // #6: Precompute the INSERT SQL for trigger-mode writes
    let mut field_keys: Vec<String> = mapping.iter().map(|m| m.field_key.clone()).collect();
    field_keys.sort();
    field_keys.dedup();
    let mut cols = vec![quote_ident("timestamp_utc")];
    for fk in &field_keys {
        cols.push(quote_ident(fk));
    }
    let placeholders: Vec<String> = (1..=cols.len()).map(|i| format!("${}", i)).collect();
    let tbl_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table.name));
    let cached_insert_sql = Some(format!(
        "INSERT INTO {} ({}) VALUES ({})",
        tbl_name, cols.join(","), placeholders.join(",")
    ));

    Ok(Some(TableRuntime {
        table,
        target_client,
        mapping,
        device,
        gateway,
        modbus_buckets,
        cached_insert_sql,
    }))
}

async fn read_table_values_cached(
    table_rt: &TableRuntime,
    device_manager: &Arc<DeviceManager>,
    modbus_manager: &ModbusManager,
    job_id: &str,
) -> Result<(FieldMap, ReadTimings)> {
    match table_rt.device.protocol.to_lowercase().as_str() {
        "opcua" => {
            read_opcua_values_blocking(
                device_manager.clone(),
                table_rt.device.clone(),
                table_rt.mapping.clone(),
                job_id.to_string(),
            )
            .await
        }
        "modbus" => {
            read_modbus_values(
                modbus_manager,
                &table_rt.device,
                table_rt.gateway.as_ref(),
                &table_rt.modbus_buckets,
                job_id,
            )
            .await
        }
        other => Err(anyhow!("device protocol not supported: {}", other)),
    }
}

/// Determine the connection endpoint key for a table, used to group concurrent reads.
/// Tables sharing the same physical connection serialize; different endpoints run concurrently.
fn table_endpoint_key(table_rt: &TableRuntime) -> String {
    match table_rt.device.protocol.to_lowercase().as_str() {
        "modbus" => {
            let host = resolve_modbus_host(&table_rt.device, table_rt.gateway.as_ref())
                .unwrap_or_else(|_| table_rt.device.id.clone());
            let port = resolve_modbus_port(&table_rt.device);
            format!("modbus:{}:{}", host, port)
        }
        // OPC UA and others: group by device ID (each device has its own session)
        _ => table_rt.device.id.clone(),
    }
}

/// Read all tables in an endpoint group sequentially.
/// Called concurrently across groups via join_all.
async fn read_endpoint_group<'a>(
    tables: Vec<&'a TableRuntime>,
    device_manager: &Arc<DeviceManager>,
    modbus_manager: &ModbusManager,
    job_id: &str,
) -> Vec<(&'a TableRuntime, Result<(FieldMap, ReadTimings)>, f64)> {
    let mut results = Vec::with_capacity(tables.len());
    for table_rt in tables {
        let t_read = Instant::now();
        let result = read_table_values_cached(table_rt, device_manager, modbus_manager, job_id).await;
        let read_ms = t_read.elapsed().as_secs_f64() * 1000.0;
        results.push((table_rt, result, read_ms));
    }
    results
}

async fn write_values_cached(
    table_rt: &TableRuntime,
    values: &FieldMap,
    job_id: &str,
) -> Result<WriteTimings> {
    if values.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }
    let t_build = Instant::now();
    // #6: Use batch_execute with inline literals (same as batch path) to avoid TEXT type mismatch
    let ts_literal = pg_escape_literal(&Utc::now().to_rfc3339());
    let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));
    let mut cols = vec![quote_ident("timestamp_utc")];
    let mut vals = vec![ts_literal];
    for (k, v) in values {
        cols.push(quote_ident(k));
        vals.push(v.to_sql_literal());
    }
    let sql = format!(
        "INSERT INTO {} ({}) VALUES ({})",
        table_name, cols.join(","), vals.join(",")
    );
    let build_ms = t_build.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [WRITE_DETAIL] table={} [SQL_BUILD] cols={} elapsed_ms={:.2}",
        job_id, table_rt.table.id, cols.len(), build_ms
    );
    let t_exec = Instant::now();
    table_rt.target_client.batch_execute(&sql).await
        .context("single table write failed")?;
    let execute_ms = t_exec.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [WRITE_DETAIL] table={} [DB_EXECUTE] elapsed_ms={:.2}",
        job_id, table_rt.table.id, execute_ms
    );
    Ok(WriteTimings { build_ms, execute_ms })
}

const PG_PARAM_LIMIT: usize = 32000;

async fn write_values_batch(
    table_rt: &TableRuntime,
    rows: &[BufferedRow],
    job_id: &str,
) -> Result<WriteTimings> {
    if rows.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }
    let first = &rows[0];
    let mut field_keys: Vec<String> = first.values.keys().cloned().collect();
    field_keys.sort();
    let mut col_names: Vec<String> = vec!["timestamp_utc".to_string()];
    col_names.extend(field_keys.iter().cloned());
    let num_cols = col_names.len();
    let chunk_size = (PG_PARAM_LIMIT / num_cols).max(1);
    let cols_quoted: Vec<String> = col_names.iter().map(|c| quote_ident(c)).collect();
    let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));
    let mut total_build_ms = 0.0f64;
    let mut total_execute_ms = 0.0f64;

    for chunk in rows.chunks(chunk_size) {
        let t_build = Instant::now();
        let mut placeholders_all = Vec::with_capacity(chunk.len());
        let mut params: Vec<String> = Vec::with_capacity(chunk.len() * num_cols);
        for (row_idx, row) in chunk.iter().enumerate() {
            let base = row_idx * num_cols;
            let ph: Vec<String> = (1..=num_cols).map(|i| format!("${}", base + i)).collect();
            placeholders_all.push(format!("({})", ph.join(",")));
            params.push(row.timestamp_utc.clone());
            for fk in &field_keys {
                params.push(row.values.get(fk).map(|v| v.to_string()).unwrap_or_default());
            }
        }
        let sql = format!(
            "INSERT INTO {} ({}) VALUES {}",
            table_name,
            cols_quoted.join(","),
            placeholders_all.join(",")
        );
        let build_ms = t_build.elapsed().as_secs_f64() * 1000.0;
        info!(
            "Job {} [WRITE_BATCH_DETAIL] table={} [SQL_BUILD] cols={} rows={} elapsed_ms={:.2}",
            job_id, table_rt.table.id, num_cols, chunk.len(), build_ms
        );
        let t_exec = Instant::now();
        let types: Vec<Type> = vec![Type::TEXT; params.len()];
        let stmt = table_rt.target_client.prepare_typed(&sql, &types).await?;
        let params_ref: Vec<&(dyn ToSql + Sync)> =
            params.iter().map(|p| p as &(dyn ToSql + Sync)).collect();
        table_rt.target_client.execute(&stmt, &params_ref).await?;
        let execute_ms = t_exec.elapsed().as_secs_f64() * 1000.0;
        info!(
            "Job {} [WRITE_BATCH_DETAIL] table={} [DB_EXECUTE] rows={} elapsed_ms={:.2}",
            job_id, table_rt.table.id, chunk.len(), execute_ms
        );
        total_build_ms += build_ms;
        total_execute_ms += execute_ms;
    }
    Ok(WriteTimings { build_ms: total_build_ms, execute_ms: total_execute_ms })
}

/// Escape a string value for use as a PostgreSQL literal in batch SQL.
fn pg_escape_literal(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

/// Write one row per table in a single batch_execute transaction.
/// Groups inserts by target client and sends all INSERTs in one network round-trip.
async fn write_all_tables_batch(
    pending: &[(&TableRuntime, FieldMap)],
    job_id: &str,
) -> Result<WriteTimings> {
    if pending.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }

    let t_build = Instant::now();
    let ts_literal = pg_escape_literal(&Utc::now().to_rfc3339());

    // Group by target client pointer identity
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for (i, (table_rt, _)) in pending.iter().enumerate() {
        let ptr = Arc::as_ptr(&table_rt.target_client) as usize;
        groups.entry(ptr).or_default().push(i);
    }

    let mut total_build_ms = 0.0f64;
    let mut total_execute_ms = 0.0f64;

    for indices in groups.values() {
        let client = &pending[indices[0]].0.target_client;
        let mut sql = String::with_capacity(indices.len() * 512);
        sql.push_str("BEGIN;\n");

        let mut table_count = 0u32;
        for &idx in indices {
            let (table_rt, values) = &pending[idx];
            if values.is_empty() {
                continue;
            }
            let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));
            let mut cols = vec![quote_ident("timestamp_utc")];
            let mut vals = vec![ts_literal.clone()];
            for (k, v) in values {
                cols.push(quote_ident(k));
                vals.push(v.to_sql_literal());
            }
            sql.push_str(&format!(
                "INSERT INTO {} ({}) VALUES ({});\n",
                table_name, cols.join(","), vals.join(",")
            ));
            table_count += 1;
        }
        sql.push_str("COMMIT;\n");

        let build_ms = t_build.elapsed().as_secs_f64() * 1000.0;
        total_build_ms += build_ms;

        info!(
            "Job {} [WRITE_ALL_BATCH] [SQL_BUILD] tables={} sql_bytes={} elapsed_ms={:.2}",
            job_id, table_count, sql.len(), build_ms
        );

        let t_exec = Instant::now();
        client.batch_execute(&sql).await
            .context("batch write all tables failed")?;
        let execute_ms = t_exec.elapsed().as_secs_f64() * 1000.0;
        total_execute_ms += execute_ms;

        info!(
            "Job {} [WRITE_ALL_BATCH] [DB_EXECUTE] tables={} elapsed_ms={:.2}",
            job_id, table_count, execute_ms
        );
    }

    Ok(WriteTimings { build_ms: total_build_ms, execute_ms: total_execute_ms })
}

/// #4: Owned version of write_all_tables_batch for background spawning.
/// Takes Vec of (client, table_name, values) so it can be 'static.
async fn write_all_tables_batch_owned(
    pending: &[(Arc<PgClient>, String, FieldMap)],
    job_id: &str,
) -> Result<WriteTimings> {
    if pending.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }

    let t_build = Instant::now();
    let ts_literal = pg_escape_literal(&Utc::now().to_rfc3339());

    // Group by target client pointer identity
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for (i, (client, _, _)) in pending.iter().enumerate() {
        let ptr = Arc::as_ptr(client) as usize;
        groups.entry(ptr).or_default().push(i);
    }

    let mut total_build_ms = 0.0f64;
    let mut total_execute_ms = 0.0f64;

    for indices in groups.values() {
        let client = &pending[indices[0]].0;
        let mut sql = String::with_capacity(indices.len() * 512);
        sql.push_str("BEGIN;\n");

        let mut table_count = 0u32;
        for &idx in indices {
            let (_, ref table_name, ref values) = pending[idx];
            if values.is_empty() {
                continue;
            }
            let full_name = format!("{}.{}", quote_ident("neuract"), quote_ident(table_name));
            let mut cols = vec![quote_ident("timestamp_utc")];
            let mut vals = vec![ts_literal.clone()];
            for (k, v) in values {
                cols.push(quote_ident(k));
                vals.push(v.to_sql_literal());
            }
            sql.push_str(&format!(
                "INSERT INTO {} ({}) VALUES ({});\n",
                full_name, cols.join(","), vals.join(",")
            ));
            table_count += 1;
        }
        sql.push_str("COMMIT;\n");

        let build_ms = t_build.elapsed().as_secs_f64() * 1000.0;
        total_build_ms += build_ms;

        info!(
            "Job {} [WRITE_ALL_BATCH] [SQL_BUILD] tables={} sql_bytes={} elapsed_ms={:.2}",
            job_id, table_count, sql.len(), build_ms
        );

        let t_exec = Instant::now();
        client.batch_execute(&sql).await
            .context("batch write all tables failed")?;
        let execute_ms = t_exec.elapsed().as_secs_f64() * 1000.0;
        total_execute_ms += execute_ms;

        info!(
            "Job {} [WRITE_ALL_BATCH] [DB_EXECUTE] tables={} elapsed_ms={:.2}",
            job_id, table_count, execute_ms
        );
    }

    Ok(WriteTimings { build_ms: total_build_ms, execute_ms: total_execute_ms })
}

/// Flush multiple tables' buffered rows in a single batch_execute transaction.
async fn flush_all_buffered(
    table_runtimes: &HashMap<String, TableRuntime>,
    to_flush: &[(String, Vec<BufferedRow>)],
    job_id: &str,
) -> Result<WriteTimings> {
    if to_flush.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }

    let t_build = Instant::now();

    // Group by target client pointer identity
    let mut groups: HashMap<usize, Vec<usize>> = HashMap::new();
    for (i, (tid, _)) in to_flush.iter().enumerate() {
        if let Some(table_rt) = table_runtimes.get(tid) {
            let ptr = Arc::as_ptr(&table_rt.target_client) as usize;
            groups.entry(ptr).or_default().push(i);
        }
    }

    let mut total_build_ms = 0.0f64;
    let mut total_execute_ms = 0.0f64;

    for indices in groups.values() {
        let first_tid = &to_flush[indices[0]].0;
        let client = &table_runtimes[first_tid].target_client;
        let mut sql = String::with_capacity(8192);
        sql.push_str("BEGIN;\n");

        let mut total_rows = 0usize;
        for &idx in indices {
            let (tid, rows) = &to_flush[idx];
            let table_rt = match table_runtimes.get(tid) {
                Some(rt) => rt,
                None => continue,
            };
            if rows.is_empty() {
                continue;
            }
            let first = &rows[0];
            let mut field_keys: Vec<String> = first.values.keys().cloned().collect();
            field_keys.sort();
            let mut col_names = vec!["timestamp_utc".to_string()];
            col_names.extend(field_keys.iter().cloned());
            let cols_quoted: Vec<String> = col_names.iter().map(|c| quote_ident(c)).collect();
            let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));

            let mut value_rows = Vec::with_capacity(rows.len());
            for row in rows {
                let mut vals = vec![pg_escape_literal(&row.timestamp_utc)];
                for fk in &field_keys {
                    vals.push(
                        row.values.get(fk)
                            .map(|v| v.to_sql_literal())
                            .unwrap_or_else(|| "NULL".to_string())
                    );
                }
                value_rows.push(format!("({})", vals.join(",")));
            }

            sql.push_str(&format!(
                "INSERT INTO {} ({}) VALUES {};\n",
                table_name, cols_quoted.join(","), value_rows.join(",")
            ));
            total_rows += rows.len();
        }
        sql.push_str("COMMIT;\n");

        let build_ms = t_build.elapsed().as_secs_f64() * 1000.0;
        total_build_ms += build_ms;

        let t_exec = Instant::now();
        client.batch_execute(&sql).await
            .context("batch flush all tables failed")?;
        let execute_ms = t_exec.elapsed().as_secs_f64() * 1000.0;
        total_execute_ms += execute_ms;

        info!(
            "Job {} [FLUSH_ALL_BATCH] [DB_EXECUTE] tables={} rows={} elapsed_ms={:.2}",
            job_id, indices.len(), total_rows, execute_ms
        );
    }

    Ok(WriteTimings { build_ms: total_build_ms, execute_ms: total_execute_ms })
}

fn bench_log_dir() -> PathBuf {
    if let Ok(p) = env::var("RUST_BENCH_LOG_DIR") {
        return PathBuf::from(p);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("logs")
}

async fn append_bench_db(
    client: &PgClient,
    job_id: &str,
    window_secs: f64,
    reads_per_sec: f64,
    writes_per_sec: f64,
    read_avg_ms: f64,
    write_avg_ms: f64,
    modbus_connect_avg_ms: f64,
    modbus_fields_avg_ms: f64,
    sql_build_avg_ms: f64,
    db_execute_avg_ms: f64,
    loop_p95_ms: Option<f64>,
    overrun_pct: f64,
    cpu_time_ms: Option<f64>,
    proc_cpu_pct: Option<f64>,
    proc_rss_mb: Option<f64>,
    read_err: u64,
    write_err: u64,
) -> Result<()> {
    client.execute(
        "INSERT INTO bench_metrics (
            job_id, window_secs, reads_per_sec, writes_per_sec,
            read_avg_ms, write_avg_ms,
            modbus_connect_avg_ms, modbus_fields_avg_ms,
            sql_build_avg_ms, db_execute_avg_ms,
            loop_p95_ms, overrun_pct,
            cpu_time_ms, proc_cpu_pct, proc_rss_mb,
            read_err, write_err
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)",
        &[
            &job_id,
            &window_secs,
            &reads_per_sec,
            &writes_per_sec,
            &read_avg_ms,
            &write_avg_ms,
            &modbus_connect_avg_ms,
            &modbus_fields_avg_ms,
            &sql_build_avg_ms,
            &db_execute_avg_ms,
            &loop_p95_ms,
            &overrun_pct,
            &cpu_time_ms,
            &proc_cpu_pct,
            &proc_rss_mb,
            &(read_err as i64),
            &(write_err as i64),
        ],
    ).await.context("insert bench_metrics row")?;
    Ok(())
}

fn error_csv_lock() -> &'static Mutex<()> {
    ERROR_CSV_LOCK.get_or_init(|| Mutex::new(()))
}

fn append_error_csv(
    job_id: &str,
    table_id: &str,
    operation: &str,
    error_msg: &str,
) -> Result<()> {
    let log_dir = bench_log_dir();
    fs::create_dir_all(&log_dir).context("create error log dir")?;
    let path = log_dir.join(ERROR_LOG_FILENAME);
    let _guard = error_csv_lock().lock().unwrap();
    let needs_header = match fs::metadata(&path) {
        Ok(meta) => meta.len() == 0,
        Err(_) => true,
    };
    let mut file = OpenOptions::new().create(true).append(true).open(&path)?;
    if needs_header {
        writeln!(file, "ts_utc,job_id,table_id,operation,error_message")?;
    }
    let ts = Utc::now().to_rfc3339();
    // CSV-escape error_message: quote it if it contains comma, quote, or newline
    let safe_msg = if error_msg.contains(',') || error_msg.contains('"') || error_msg.contains('\n') {
        format!("\"{}\"", error_msg.replace('"', "\"\""))
    } else {
        error_msg.to_string()
    };
    writeln!(file, "{},{},{},{},{}", ts, job_id, table_id, operation, safe_msg)?;
    Ok(())
}

fn percentile_ms(samples: &mut [f64], pct: f64) -> Option<f64> {
    if samples.is_empty() {
        return None;
    }
    samples.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let idx = ((pct / 100.0) * ((samples.len() - 1) as f64)).round() as usize;
    samples.get(idx).copied()
}

async fn read_table_values(
    table: &TableDef,
    default_target: &Option<String>,
    meta_client: &PgClient,
    device_manager: &Arc<DeviceManager>,
    target_manager: &Arc<TargetManager>,
) -> Result<FieldMap> {
    let target_id = table.db_target_id.clone().or_else(|| default_target.clone());
    let target_id = target_id.ok_or_else(|| anyhow!("no db target for table {}", table.id))?;
    let target = load_target(meta_client, &target_id).await?
        .ok_or_else(|| anyhow!("db target not found: {}", target_id))?;
    if !is_postgres_provider(&target.provider) {
        return Err(anyhow!("unsupported target provider: {}", target.provider));
    }
    let target_client = target_manager.get_client(&target.conn).await?;
    let mapping = load_mapping_rows(target_client.as_ref(), &table.name).await?;
    if mapping.is_empty() {
        return Ok(HashMap::new());
    }
    let device_id = mapping.iter().find_map(|m| m.device_id.clone()).or_else(|| table.device_id.clone());
    let device_id = device_id.ok_or_else(|| anyhow!("device not bound for table {}", table.id))?;
    let device = load_device(meta_client, &device_id).await?
        .ok_or_else(|| anyhow!("device not found: {}", device_id))?;
    match device.protocol.to_lowercase().as_str() {
        "opcua" => read_opcua_values_blocking(device_manager.clone(), device, mapping, "unknown".to_string()).await.map(|(v, _)| v),
        "modbus" => {
            let gateway = if let Some(ref gw_id) = device.gateway_id {
                load_gateway(meta_client, gw_id).await.unwrap_or(None)
            } else {
                None
            };
            let mgr = ModbusManager::new();
            let buckets = build_modbus_buckets(&mapping);
            read_modbus_values(&mgr, &device, gateway.as_ref(), &buckets, "unknown").await.map(|(v, _)| v)
        }
        other => Err(anyhow!("device protocol not supported: {}", other)),
    }
}

async fn write_values(
    table: &TableDef,
    default_target: &Option<String>,
    meta_client: &PgClient,
    target_manager: &Arc<TargetManager>,
    values: &FieldMap,
) -> Result<()> {
    if values.is_empty() {
        return Ok(());
    }
    let target_id = table.db_target_id.clone().or_else(|| default_target.clone());
    let Some(target_id) = target_id else {
        return Err(anyhow!("no db target for table {}", table.id));
    };
    let target = load_target(meta_client, &target_id).await?
        .ok_or_else(|| anyhow!("db target not found: {}", target_id))?;
    let target_client = target_manager.get_client(&target.conn).await?;

    let mut cols = Vec::new();
    let mut params: Vec<String> = Vec::new();
    cols.push(quote_ident("timestamp_utc"));
    params.push(Utc::now().to_rfc3339());
    for (k, v) in values {
        cols.push(quote_ident(k));
        params.push(v.to_string());
    }
    let placeholders: Vec<String> = (1..=cols.len()).map(|i| format!("${}", i)).collect();
    let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table.name));
    let sql = format!("INSERT INTO {} ({}) VALUES ({})", table_name, cols.join(","), placeholders.join(","));
    let types: Vec<Type> = vec![Type::TEXT; params.len()];
    let stmt = target_client.prepare_typed(&sql, &types).await?;
    let params_ref: Vec<&(dyn ToSql + Sync)> =
        params.iter().map(|p| p as &(dyn ToSql + Sync)).collect();
    target_client.execute(&stmt, &params_ref).await?;
    Ok(())
}

fn parse_param_value(raw: &str) -> Box<dyn ToSql + Sync + Send> {
    if raw.eq_ignore_ascii_case("true") {
        return Box::new(true);
    }
    if raw.eq_ignore_ascii_case("false") {
        return Box::new(false);
    }
    if let Ok(n) = raw.parse::<i64>() {
        return Box::new(n);
    }
    if let Ok(n) = raw.parse::<f64>() {
        return Box::new(n);
    }
    Box::new(raw.to_string())
}

fn parse_param_value_for_type(raw: &str, data_type: Option<&str>) -> Box<dyn ToSql + Sync + Send> {
    let dt = data_type.unwrap_or("").to_lowercase();
    if dt.contains("bool") {
        if raw.eq_ignore_ascii_case("true") {
            return Box::new(true);
        }
        if raw.eq_ignore_ascii_case("false") {
            return Box::new(false);
        }
        if let Ok(n) = raw.parse::<i64>() {
            return Box::new(n != 0);
        }
    }
    if dt.contains("float") || dt.contains("double") || dt.contains("real") || dt.contains("numeric") {
        if let Ok(n) = raw.parse::<f64>() {
            return Box::new(n);
        }
    }
    if dt.contains("int") || dt.contains("uint") || dt.contains("short") || dt.contains("long") {
        if let Ok(n) = raw.parse::<i64>() {
            return Box::new(n);
        }
    }
    parse_param_value(raw)
}

fn eval_triggers(
    triggers: &[Trigger],
    table_id: &str,
    values: &FieldMap,
    last_values: &mut HashMap<String, FieldMap>,
) -> bool {
    let last = last_values.entry(table_id.to_string()).or_insert_with(HashMap::new);
    for tr in triggers {
        let cur = values.get(&tr.field_key).and_then(|v| v.as_f64());
        let prev = last.get(&tr.field_key).and_then(|v| v.as_f64());
        if eval_op(cur, prev, &tr.op, tr.value, tr.deadband) {
            return true;
        }
    }
    false
}

fn update_last_values(table_id: &str, values: &FieldMap, last_values: &mut HashMap<String, FieldMap>) {
    let last = last_values.entry(table_id.to_string()).or_insert_with(HashMap::new);
    for (k, v) in values {
        last.insert(k.clone(), v.clone());
    }
}

fn eval_op(val: Option<f64>, prev: Option<f64>, op: &str, threshold: Option<f64>, deadband: f64) -> bool {
    match op {
        "change" => {
            if let (Some(v), Some(p)) = (val, prev) {
                return (v - p).abs() > deadband;
            }
            false
        }
        ">" => match (val, threshold) { (Some(v), Some(t)) => v > t, _ => false },
        ">=" => match (val, threshold) { (Some(v), Some(t)) => v >= t, _ => false },
        "<" => match (val, threshold) { (Some(v), Some(t)) => v < t, _ => false },
        "<=" => match (val, threshold) { (Some(v), Some(t)) => v <= t, _ => false },
        "==" => match (val, threshold) { (Some(v), Some(t)) => (v - t).abs() < f64::EPSILON, _ => false },
        "!=" => match (val, threshold) { (Some(v), Some(t)) => (v - t).abs() >= f64::EPSILON, _ => false },
        "rising" => match (val, prev, threshold) { (Some(v), Some(p), Some(t)) => p <= t && v > t, _ => false },
        "falling" => match (val, prev, threshold) { (Some(v), Some(p), Some(t)) => p >= t && v < t, _ => false },
        _ => false,
    }
}

fn group_triggers(job: &JobDef) -> HashMap<String, Vec<Trigger>> {
    let mut out: HashMap<String, Vec<Trigger>> = HashMap::new();
    for tr in &job.triggers {
        let tid = tr.table_id.clone().or_else(|| job.tables.first().cloned());
        let Some(tid) = tid else { continue; };
        out.entry(tid).or_default().push(tr.clone());
    }
    out
}

async fn load_running_jobs(client: &PgClient) -> Result<Vec<JobDef>> {
    let rows = client
        .query(
            "SELECT id,name,type,tables_json,interval_ms::text AS interval_ms_text,enabled,status,triggers_json,batching_json FROM app_jobs WHERE status='running'",
            &[],
        )
        .await?;
    let mut out = Vec::new();
    for r in rows {
        let job_id: String = r.get("id");
        let name: String = r.get("name");
        let jtype: String = r.get("type");
        let interval_ms_raw: Option<String> = r.get("interval_ms_text");
        let interval_ms = interval_ms_raw
            .as_deref()
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or(1000);
        let tables_json: Option<String> = r.get("tables_json");
        let triggers_json: Option<String> = r.get("triggers_json");
        let tables: Vec<String> = tables_json
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();
        let triggers = parse_triggers(triggers_json);
        let batching_json: Option<String> = r.get("batching_json");
        let (batch_count, batch_ms) = parse_batching(batching_json);
        out.push(JobDef {
            id: job_id,
            name,
            job_type: parse_job_type(&jtype),
            interval_ms: interval_ms.max(100) as u64,
            tables,
            triggers,
            batch_count,
            batch_ms,
        });
    }
    Ok(out)
}

fn parse_job_type(s: &str) -> JobType {
    let v = s.to_lowercase();
    if v == "trigger" || v == "triggered" {
        JobType::Trigger
    } else {
        JobType::Continuous
    }
}

fn parse_batching(raw: Option<String>) -> (u64, f64) {
    let Some(raw) = raw else { return (1, 0.0); };
    let Ok(val) = serde_json::from_str::<serde_json::Value>(&raw) else { return (1, 0.0); };
    let count = val.get("count").and_then(|v| v.as_u64()).unwrap_or(1).max(1);
    let ms = val.get("ms").and_then(|v| v.as_f64()).unwrap_or(0.0);
    (count, ms)
}

fn parse_triggers(raw: Option<String>) -> Vec<Trigger> {
    let mut out = Vec::new();
    let Some(raw) = raw else { return out; };
    let Ok(val) = serde_json::from_str::<serde_json::Value>(&raw) else { return out; };
    let Some(arr) = val.as_array() else { return out; };
    for item in arr {
        let table_id = item.get("tableId").and_then(|v| v.as_str()).map(|s| s.to_string());
        let field_key = item
            .get("field")
            .or_else(|| item.get("fieldKey"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if field_key.is_empty() {
            continue;
        }
        let op = item.get("op").and_then(|v| v.as_str()).unwrap_or("change").to_string();
        let value = item.get("value").and_then(|v| v.as_f64());
        let deadband = item.get("deadband").and_then(|v| v.as_f64()).unwrap_or(0.0);
        out.push(Trigger {
            table_id,
            field_key,
            op,
            value,
            deadband,
        });
    }
    out
}

async fn load_table(client: &PgClient, table_id: &str) -> Result<Option<TableDef>> {
    let rows = client
        .query(
            "SELECT id,name,db_target_id,device_id FROM app_device_tables WHERE id=$1",
            &[&table_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    Ok(Some(TableDef {
        id: r.get("id"),
        name: r.get("name"),
        db_target_id: r.get("db_target_id"),
        device_id: r.get("device_id"),
    }))
}

async fn load_default_target(client: &PgClient) -> Result<Option<String>> {
    let rows = client
        .query("SELECT value FROM app_meta WHERE key='default_db_target'", &[])
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let v: String = rows[0].get("value");
    Ok(Some(v))
}

async fn load_target(client: &PgClient, target_id: &str) -> Result<Option<DbTarget>> {
    let rows = client
        .query(
            "SELECT id,provider,conn FROM app_db_targets WHERE id=$1",
            &[&target_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    Ok(Some(DbTarget {
        id: r.get("id"),
        provider: r.get("provider"),
        conn: r.get("conn"),
    }))
}

async fn load_device(client: &PgClient, device_id: &str) -> Result<Option<Device>> {
    let rows = client
        .query(
            "SELECT id,protocol,params_json,unit_id,port,gateway_id FROM app_devices WHERE id=$1",
            &[&device_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    let params_raw: Option<String> = r.get("params_json");
    let params = params_raw
        .as_deref()
        .map(params_load)
        .unwrap_or_else(|| serde_json::json!({}));
    Ok(Some(Device {
        id: r.get("id"),
        protocol: r.get("protocol"),
        params,
        unit_id: r.try_get("unit_id").ok().flatten(),
        port: r.try_get("port").ok().flatten(),
        gateway_id: r.try_get("gateway_id").ok().flatten(),
    }))
}

async fn load_gateway(client: &PgClient, gateway_id: &str) -> Result<Option<Gateway>> {
    let rows = client
        .query(
            "SELECT id,name,host FROM app_gateways WHERE id=$1",
            &[&gateway_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    Ok(Some(Gateway {
        id: r.get("id"),
        name: r.try_get("name").ok().flatten(),
        host: r.try_get("host").ok().flatten(),
    }))
}

async fn load_mapping_rows(target_client: &PgClient, table_name: &str) -> Result<Vec<MappingRow>> {
    let rows = target_client
        .query(
            "SELECT table_name,field_key,protocol,address,data_type,scale,deadband,device_id \
             FROM neuract.device_mappings WHERE table_name=$1",
            &[&table_name],
        )
        .await?;
    let mut out = Vec::new();
    for r in rows {
        out.push(MappingRow {
            field_key: r.get("field_key"),
            protocol: r.get("protocol"),
            address: r.get("address"),
            data_type: r.get("data_type"),
            scale: read_optional_f64(&r, "scale"),
            deadband: read_optional_f64(&r, "deadband"),
            device_id: r.get("device_id"),
        });
    }
    Ok(out)
}

fn read_optional_f64(row: &tokio_postgres::Row, col: &str) -> Option<f64> {
    if let Ok(v) = row.try_get::<_, Option<f64>>(col) {
        return v;
    }
    if let Ok(v) = row.try_get::<_, Option<f32>>(col) {
        return v.map(|n| n as f64);
    }
    if let Ok(v) = row.try_get::<_, Option<i64>>(col) {
        return v.map(|n| n as f64);
    }
    if let Ok(v) = row.try_get::<_, Option<i32>>(col) {
        return v.map(|n| n as f64);
    }
    if let Ok(v) = row.try_get::<_, Option<String>>(col) {
        return v.and_then(|s| s.trim().parse::<f64>().ok());
    }
    None
}

// --- Modbus encoding map + decode ---

/// Returns (register_count, encoding_tag) for a given encoding name.
fn modbus_encoding_info(enc: &str) -> (u16, &'static str) {
    match enc {
        "float32" | "float" => (2, "f32"),
        "uint16" | "uint16_enum" | "bool16" => (1, "u16"),
        "int16" => (1, "i16"),
        "uint32" => (2, "u32"),
        "int32" => (2, "i32"),
        "float64" => (4, "f64"),
        "uint64" => (4, "u64"),
        "int64" => (4, "i64"),
        _ => (1, "u16"), // fallback: single register as u16
    }
}

/// Decode raw Modbus registers into a float value (mirrors Python _decode_registers).
fn decode_registers(regs: &[u16], encoding: &str) -> Option<f64> {
    let enc = encoding.to_lowercase();
    let (count, tag) = modbus_encoding_info(&enc);
    if regs.len() < count as usize {
        return None;
    }
    // Pack registers as big-endian 16-bit words into byte buffer
    let mut buf = vec![0u8; count as usize * 2];
    for (i, &reg) in regs.iter().take(count as usize).enumerate() {
        BigEndian::write_u16(&mut buf[i * 2..i * 2 + 2], reg);
    }
    let val = match tag {
        "f32" => BigEndian::read_f32(&buf) as f64,
        "u16" => BigEndian::read_u16(&buf) as f64,
        "i16" => BigEndian::read_i16(&buf) as f64,
        "u32" => BigEndian::read_u32(&buf) as f64,
        "i32" => BigEndian::read_i32(&buf) as f64,
        "f64" => BigEndian::read_f64(&buf),
        "u64" => BigEndian::read_u64(&buf) as f64,
        "i64" => BigEndian::read_i64(&buf) as f64,
        _ => BigEndian::read_u16(&buf) as f64,
    };
    Some(val)
}

// --- Modbus connection manager ---

struct ModbusManager {
    contexts: Mutex<HashMap<String, (tokio_modbus::client::Context, Instant)>>,
    /// #7: Max idle time before forcing reconnect
    max_idle: Duration,
}

impl ModbusManager {
    fn new() -> Self {
        let max_idle_ms: u64 = env::var("MODBUS_MAX_IDLE_MS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(30_000);
        Self {
            contexts: Mutex::new(HashMap::new()),
            max_idle: Duration::from_millis(max_idle_ms),
        }
    }

    fn drop_context(&self, key: &str) {
        self.contexts.lock().unwrap().remove(key);
    }

    /// #7: Drop stale connections that have been idle too long
    fn drop_stale(&self) {
        let mut map = self.contexts.lock().unwrap();
        let max_idle = self.max_idle;
        map.retain(|_, (_, last_used)| last_used.elapsed() < max_idle);
    }
}

// --- Modbus host / port / unit resolution ---

fn resolve_modbus_host(device: &Device, gateway: Option<&Gateway>) -> Result<String> {
    // Priority: gateway.host > device.params.host > device.params.ip
    if let Some(gw) = gateway {
        if let Some(ref h) = gw.host {
            let h = h.trim();
            if !h.is_empty() {
                return Ok(h.to_string());
            }
        }
    }
    let host = device
        .params
        .get("host")
        .or_else(|| device.params.get("ip"))
        .and_then(|v| v.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    host.ok_or_else(|| anyhow!("MODBUS_HOST_MISSING for device {}", device.id))
}

fn resolve_modbus_port(device: &Device) -> u16 {
    // Priority: device.port > device.params.port > 502
    if let Some(p) = device.port {
        return p as u16;
    }
    device
        .params
        .get("port")
        .and_then(|v| v.as_u64().or_else(|| v.as_str().and_then(|s| s.parse().ok())))
        .unwrap_or(502) as u16
}

fn resolve_modbus_unit_id(device: &Device) -> u8 {
    // Priority: device.unit_id > 1
    device.unit_id.unwrap_or(1) as u8
}

// --- Modbus read implementation ---

async fn read_modbus_values(
    modbus_manager: &ModbusManager,
    device: &Device,
    gateway: Option<&Gateway>,
    buckets: &[RegisterBucket],
    job_id: &str,
) -> Result<(FieldMap, ReadTimings)> {
    let t_fn = Instant::now();
    let host = resolve_modbus_host(device, gateway)?;
    let port = resolve_modbus_port(device);
    let unit_id = resolve_modbus_unit_id(device);
    let key = format!("{}:{}", host, port);

    // #7: Drop stale contexts before lookup
    modbus_manager.drop_stale();

    // Try to take the cached context (we must own it for async calls)
    let mut ctx = {
        let mut map = modbus_manager.contexts.lock().unwrap();
        map.remove(&key).map(|(c, _)| c)
    };

    // If no cached context, create a new one
    let t_conn = Instant::now();
    let was_cached = ctx.is_some();
    if ctx.is_none() {
        let socket_addr = format!("{}:{}", host, port);
        let addr: std::net::SocketAddr = socket_addr
            .parse()
            .map_err(|e| anyhow!("invalid modbus address {}: {}", socket_addr, e))?;
        let new_ctx = tokio_modbus::client::tcp::connect_slave(addr, Slave(unit_id))
            .await
            .map_err(|e| anyhow!("MODBUS_CONNECT_FAILED {}:{} err={}", host, port, e))?;
        ctx = Some(new_ctx);
    }
    let connect_ms = t_conn.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [READ_MAPPING] [MODBUS_CONNECT] host={} port={} cached={} elapsed_ms={:.2}",
        job_id, host, port, was_cached, connect_ms
    );

    let mut ctx = ctx.unwrap();
    let mut values = HashMap::new();
    let t_fields = Instant::now();

    ctx.set_slave(Slave(unit_id));

    for bucket in buckets {
        let t_bucket = Instant::now();
        let read_result = ctx.read_holding_registers(bucket.start_addr, bucket.read_count).await;
        match read_result {
            Ok(Ok(regs)) => {
                info!(
                    "Job {} [READ_MAPPING] [MODBUS_BUCKET] start={} count={} got={} elapsed_ms={:.2}",
                    job_id, bucket.start_addr, bucket.read_count, regs.len(),
                    t_bucket.elapsed().as_secs_f64() * 1000.0
                );
                for field in &bucket.fields {
                    let offset = (field.address - bucket.start_addr) as usize;
                    let end = offset + field.reg_count as usize;
                    if end > regs.len() {
                        warn!(
                            "modbus bucket field beyond read range field={} addr={} end={} regs_len={}",
                            field.field_key, field.address, end, regs.len()
                        );
                        continue;
                    }
                    let field_regs = &regs[offset..end];
                    if let Some(mut val) = decode_registers(field_regs, &field.encoding) {
                        // Post-decode coercion
                        if field.encoding == "bool16" {
                            val = if val != 0.0 { 1.0 } else { 0.0 };
                        }
                        // Apply scale
                        if let Some(scale) = field.scale {
                            val *= scale;
                        }
                        let fv = if field.encoding == "uint16_enum" {
                            FieldValue::Int(val as i64)
                        } else if field.encoding == "bool16" {
                            FieldValue::Bool(val != 0.0)
                        } else {
                            FieldValue::Float(val)
                        };
                        values.insert(field.field_key.clone(), fv);
                    }
                }
            }
            Ok(Err(exception)) => {
                warn!(
                    "modbus bucket exception start={} count={} unit={} err={:?}",
                    bucket.start_addr, bucket.read_count, unit_id, exception
                );
            }
            Err(e) => {
                warn!(
                    "modbus bucket read error start={} count={} unit={} err={}",
                    bucket.start_addr, bucket.read_count, unit_id, e
                );
                // On connection error, don't cache the broken context
                modbus_manager.drop_context(&key);
                return Err(anyhow!("modbus read failed: {}", e));
            }
        }
    }
    let fields_ms = t_fields.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [READ_MAPPING] [MODBUS_FIELDS_TOTAL] buckets={} fields={} elapsed_ms={:.2}",
        job_id, buckets.len(), values.len(), fields_ms
    );

    // Put context back for reuse with timestamp
    modbus_manager.contexts.lock().unwrap().insert(key, (ctx, Instant::now()));

    info!(
        "Job {} [READ_MAPPING] [TOTAL] proto=modbus fields={} elapsed_ms={:.2}",
        job_id, values.len(), t_fn.elapsed().as_secs_f64() * 1000.0
    );
    Ok((values, ReadTimings { connect_ms, fields_ms }))
}

fn read_opcua_value(session: &Arc<Mutex<DeviceSession>>, row: &MappingRow, job_id: &str) -> Result<Option<FieldValue>> {
    let t_field = Instant::now();
    let mut sess = session.lock().unwrap();
    let node_id = if let Some(node_id) = sess.nodes.get(&row.address) {
        node_id.clone()
    } else {
        let parsed = NodeId::from_str(&row.address)
            .map_err(|e| anyhow!("invalid node id {}: {}", row.address, e))?;
        sess.nodes.insert(row.address.clone(), parsed.clone());
        parsed
    };
    let values = {
        let session_guard = sess.session.read();
        session_guard
            .read(&[ReadValueId::from(node_id)], TimestampsToReturn::Neither, 0.0)
            .map_err(|e| anyhow!("opcua read failed: {}", e))?
    };
    let dv = values
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("opcua read returned no values"))?;
    let mut val = dv.value.as_ref().and_then(variant_to_field_value);
    if let (Some(fv), Some(scale)) = (&mut val, row.scale) {
        if let Some(n) = fv.as_f64() {
            *fv = FieldValue::Float(n * scale);
        }
    }
    sess.last_used = Instant::now();
    info!(
        "Job {} [READ_MAPPING] [OPCUA_FIELD] field={} node={} elapsed_ms={:.2}",
        job_id, row.field_key, row.address, t_field.elapsed().as_secs_f64() * 1000.0
    );
    Ok(val)
}

async fn read_opcua_values_blocking(
    device_manager: Arc<DeviceManager>,
    device: Device,
    mapping: Vec<MappingRow>,
    job_id: String,
) -> Result<(FieldMap, ReadTimings)> {
    tokio::task::spawn_blocking(move || {
        let t_fn = Instant::now();
        let t_conn = Instant::now();
        let session = device_manager.get_session(&device)?;
        let endpoint = session.lock().unwrap().endpoint.clone();
        let connect_ms = t_conn.elapsed().as_secs_f64() * 1000.0;
        info!(
            "Job {} [READ_MAPPING] [OPCUA_CONNECT] endpoint={} elapsed_ms={:.2}",
            job_id, endpoint, connect_ms
        );
        let mut values: FieldMap = HashMap::new();
        let t_fields = Instant::now();
        for row in mapping {
            if row.protocol.to_lowercase() != "opcua" {
                continue;
            }
            let value = read_opcua_value(&session, &row, &job_id)?;
            if let Some(v) = value {
                values.insert(row.field_key, v);
            }
        }
        let fields_ms = t_fields.elapsed().as_secs_f64() * 1000.0;
        info!(
            "Job {} [READ_MAPPING] [OPCUA_FIELDS_TOTAL] count={} elapsed_ms={:.2}",
            job_id, values.len(), fields_ms
        );
        info!(
            "Job {} [READ_MAPPING] [TOTAL] proto=opcua fields={} elapsed_ms={:.2}",
            job_id, values.len(), t_fn.elapsed().as_secs_f64() * 1000.0
        );
        Ok((values, ReadTimings { connect_ms, fields_ms }))
    })
    .await
    .context("opcua blocking task failed")?
}

fn variant_to_field_value(v: &Variant) -> Option<FieldValue> {
    match v {
        Variant::Boolean(b) => Some(FieldValue::Bool(*b)),
        Variant::Byte(b) => Some(FieldValue::Int(*b as i64)),
        Variant::SByte(b) => Some(FieldValue::Int(*b as i64)),
        Variant::Int16(b) => Some(FieldValue::Int(*b as i64)),
        Variant::UInt16(b) => Some(FieldValue::Int(*b as i64)),
        Variant::Int32(b) => Some(FieldValue::Int(*b as i64)),
        Variant::UInt32(b) => Some(FieldValue::Int(*b as i64)),
        Variant::Int64(b) => Some(FieldValue::Int(*b as i64)),
        Variant::UInt64(b) => Some(FieldValue::Int(*b as i64)),
        Variant::Float(b) => Some(FieldValue::Float(*b as f64)),
        Variant::Double(b) => Some(FieldValue::Float(*b)),
        Variant::String(s) => {
            if s.is_null() {
                None
            } else {
                Some(FieldValue::Text(s.as_ref().to_string()))
            }
        }
        _ => None,
    }
}

fn is_postgres_provider(p: &str) -> bool {
    let v = p.to_lowercase();
    v.contains("postgres")
}

fn normalize_endpoint(ep: &str) -> String {
    if ep.contains("0.0.0.0") {
        ep.replace("0.0.0.0", "127.0.0.1")
    } else {
        ep.to_string()
    }
}

fn quote_ident(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}

fn params_load(raw: &str) -> serde_json::Value {
    if let Some(enc) = raw.strip_prefix("ENCv1:") {
        let Ok(blob) = base64::engine::general_purpose::STANDARD.decode(enc) else {
            return serde_json::json!({});
        };
        if let Some(clear) = dpapi_unprotect(&blob) {
            if let Ok(val) = serde_json::from_slice::<serde_json::Value>(&clear) {
                return val;
            }
        }
        return serde_json::json!({});
    }
    serde_json::from_str(raw).unwrap_or_else(|_| serde_json::json!({}))
}

fn dpapi_unprotect(data: &[u8]) -> Option<Vec<u8>> {
    if !cfg!(target_os = "windows") {
        return None;
    }
    unsafe {
        let mut in_blob = CRYPT_INTEGER_BLOB {
            cbData: data.len() as u32,
            pbData: data.as_ptr() as *mut u8,
        };
        let mut out_blob = CRYPT_INTEGER_BLOB::default();
        let mut flags: u32 = 0;
        let machine_scope = env_truthy("APP_DPAPI_MACHINE") || env_truthy("AGENT_DPAPI_MACHINE");
        if machine_scope {
            flags |= CRYPTPROTECT_LOCAL_MACHINE;
        }
        if CryptUnprotectData(&mut in_blob, None, None, None, None, flags, &mut out_blob).is_err() {
            return None;
        }
        if out_blob.pbData.is_null() {
            return None;
        }
        let slice = std::slice::from_raw_parts(out_blob.pbData, out_blob.cbData as usize);
        let out = slice.to_vec();
        let _ = LocalFree(HLOCAL(out_blob.pbData as _));
        Some(out)
    }
}

fn env_truthy(name: &str) -> bool {
    matches!(env::var(name).ok().as_deref(), Some("1") | Some("true") | Some("True"))
}
