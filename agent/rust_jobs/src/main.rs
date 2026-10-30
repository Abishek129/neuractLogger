use std::collections::HashMap;
use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Context, Result};
use base64::Engine;
use byteorder::{BigEndian, ByteOrder};
use chrono::{Utc, Local, FixedOffset, SecondsFormat};
use log::{error, info, warn, LevelFilter};
use opcua::client::prelude::*;
use opcua::sync::RwLock;
use opcua::types::Variant;
use tokio_modbus::prelude::{Reader, Slave, SlaveContext};
use tokio_postgres::{Client as PgClient, NoTls};
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::{HLOCAL, LocalFree};
#[cfg(target_os = "windows")]
use windows::Win32::Security::Cryptography::{
    CryptUnprotectData, CRYPTPROTECT_LOCAL_MACHINE, CRYPT_INTEGER_BLOB,
};
use futures::future::join_all;
use sysinfo::{Pid, System};
use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};

const ERROR_LOG_FILENAME: &str = "error_log_rust.csv";
const LOG_FILENAME: &str = "agent_rust.log";
const MQTT_LOG_FILENAME: &str = "mqtt_jobs.log";
/// Per-file size cap. Override with LOGGER_LOG_MAX_MB (megabytes).
fn log_max_bytes() -> u64 {
    env::var("LOGGER_LOG_MAX_MB")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .map(|mb| mb.max(1) * 1024 * 1024)
        .unwrap_or(100 * 1024 * 1024)
}

/// Rotated backups kept per log file. Override with LOGGER_LOG_BACKUPS.
fn log_max_backups() -> u32 {
    env::var("LOGGER_LOG_BACKUPS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .map(|n| n.max(1))
        .unwrap_or(5)
}

// --- Rotating file writer (mirrors Python RotatingFileHandler) ---

struct RotatingFileWriter {
    path: PathBuf,
    file: std::fs::File,
    written: u64,
    max_bytes: u64,
    max_backups: u32,
}

impl RotatingFileWriter {
    fn new(path: PathBuf, max_bytes: u64, max_backups: u32) -> std::io::Result<Self> {
        let existing_size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        Ok(Self {
            path,
            file,
            written: existing_size,
            max_bytes,
            max_backups: max_backups.max(1),
        })
    }

    fn rotate(&mut self) -> std::io::Result<()> {
        // Drop the oldest backup, shift the rest up: .N -> .N+1, current -> .1
        let oldest = format!("{}.{}", self.path.display(), self.max_backups);
        let _ = fs::remove_file(&oldest);
        for n in (1..self.max_backups).rev() {
            let from = format!("{}.{}", self.path.display(), n);
            let to = format!("{}.{}", self.path.display(), n + 1);
            let _ = fs::rename(&from, &to);
        }
        // Clean up any backups beyond the cap left over from older builds
        for n in (self.max_backups + 1)..=9999 {
            let stale = format!("{}.{}", self.path.display(), n);
            if fs::remove_file(&stale).is_err() {
                break;
            }
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
    let file_writer = match RotatingFileWriter::new(log_path.clone(), log_max_bytes(), log_max_backups()) {
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

// --- MQTT-specific log file ---

static MQTT_LOGGER: OnceLock<Mutex<RotatingFileWriter>> = OnceLock::new();

fn setup_mqtt_logging() {
    let dir = log_dir();
    let _ = fs::create_dir_all(&dir);
    let path = dir.join(MQTT_LOG_FILENAME);
    match RotatingFileWriter::new(path.clone(), log_max_bytes(), log_max_backups()) {
        Ok(w) => {
            MQTT_LOGGER.set(Mutex::new(w)).ok();
            info!("MQTT log file: {}", path.display());
        }
        Err(e) => {
            warn!("MQTT log file setup failed: {}", e);
        }
    }
}

/// Write a line to the MQTT-specific log file (in addition to the main log).
fn mqtt_log(level: &str, msg: &str) {
    if let Some(lock) = MQTT_LOGGER.get() {
        if let Ok(mut w) = lock.lock() {
            let line = format!(
                "{} [{}] {}\n",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                level,
                msg
            );
            let _ = w.write_all(line.as_bytes());
            let _ = w.flush();
        }
    }
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
struct TriggerFireInfo {
    field_key: String,
    op: String,
    current_value: Option<f64>,
    previous_value: Option<f64>,
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
    /// Rated line-to-line voltage of the installation this device measures.
    /// Per device, because one meter model serves 415 V panels and 33 kV
    /// incomers alike; exposed to formulas as dev_nominal_voltage.
    nominal_voltage: Option<f64>,
}

#[derive(Clone, Debug)]
struct MappingRow {
    field_key: String,
    protocol: String,
    address: String,
    data_type: String,
    encoding: String,
    scale: Option<f64>,
    device_id: Option<String>,
}

#[derive(Clone, Debug)]
struct Gateway {
    host: Option<String>,
}

/// Modbus register type, derived from industry-standard address prefixes.
#[derive(Clone, Debug, Copy, PartialEq, Eq, Hash)]
enum RegisterType {
    Coil,            // 0xxxx — FC 1/5/15
    DiscreteInput,   // 1xxxx — FC 2
    InputRegister,   // 3xxxx — FC 4
    HoldingRegister, // 4xxxx — FC 3 (default)
}

/// Parse a Modbus address string into (RegisterType, raw_register).
/// Supports industry-standard prefixed addresses and raw numeric addresses.
///   "40001" → (HoldingRegister, 0)   — 4xxxx prefix, 1-based
///   "30001" → (InputRegister, 0)     — 3xxxx prefix, 1-based
///   "10001" → (DiscreteInput, 0)     — 1xxxx prefix, 1-based
///   "00001" → (Coil, 0)             — 0xxxx prefix, 1-based
///   "0"     → (HoldingRegister, 0)   — raw register, no prefix
///   "100"   → (HoldingRegister, 100) — raw register, no prefix
fn parse_modbus_address(raw: &str) -> Option<(RegisterType, u16, Option<u8>)> {
    let s = raw.trim();
    if s.is_empty() {
        return None;
    }

    // Optional "<reg>,<bit>" suffix → extract a single bit (0-15) from the word,
    // e.g. "40101,0" (holding reg bit) or "D200,3" (Delta D-register bit).
    let (reg_part, bit) = match s.split_once(',') {
        Some((r, b)) => {
            let bit = b.trim().parse::<u8>().ok().filter(|&n| n < 16)?;
            (r.trim(), Some(bit))
        }
        None => (s, None),
    };

    // Delta D-register: "D100" → holding register 0x1000 + N (Delta DVP Modbus convention).
    if let Some(rest) = reg_part.strip_prefix(|c| c == 'D' || c == 'd') {
        let n: u32 = rest.parse().ok()?;
        let addr = 0x1000u32 + n;
        if addr > 65535 {
            return None;
        }
        return Some((RegisterType::HoldingRegister, addr as u16, bit));
    }

    let num: u32 = reg_part.parse().ok()?;

    // 5-digit industry-standard addresses (40001-49999, 30001-39999, etc.)
    if num >= 40001 && num <= 49999 {
        return Some((RegisterType::HoldingRegister, (num - 40001) as u16, bit));
    }
    if num >= 30001 && num <= 39999 {
        return Some((RegisterType::InputRegister, (num - 30001) as u16, bit));
    }
    if num >= 10001 && num <= 19999 {
        return Some((RegisterType::DiscreteInput, (num - 10001) as u16, bit));
    }
    if num >= 1 && num <= 9999 && reg_part.len() == 5 {
        // 5-digit with leading zero: "00001" → coil 0
        return Some((RegisterType::Coil, (num - 1) as u16, bit));
    }

    // 6-digit extended addresses (400001-465535, 300001-365535)
    if num >= 400001 && num <= 465535 {
        return Some((RegisterType::HoldingRegister, (num - 400001) as u16, bit));
    }
    if num >= 300001 && num <= 365535 {
        return Some((RegisterType::InputRegister, (num - 300001) as u16, bit));
    }
    if num >= 100001 && num <= 165535 {
        return Some((RegisterType::DiscreteInput, (num - 100001) as u16, bit));
    }
    if num >= 1 && num <= 65535 && reg_part.len() == 6 {
        return Some((RegisterType::Coil, (num - 1) as u16, bit));
    }

    // Raw numeric — treat as holding register (backwards compatible)
    if num <= 65535 {
        return Some((RegisterType::HoldingRegister, num as u16, bit));
    }

    None
}

/// A field within a register bucket, precomputed at job startup.
#[derive(Clone, Debug)]
struct BucketField {
    field_key: String,
    address: u16,
    reg_count: u16,
    encoding: String,
    scale: Option<f64>,
    /// For "<reg>,<bit>" addresses: extract this single bit (0-15) from the word
    /// (Delta/SCADA breaker-status feedbacks packed into a holding register).
    bit: Option<u8>,
}

/// A group of fields whose registers fall within the same 125-register section.
/// Bucket index = address / 125. All fields in bucket N have start addresses in [N*125, (N+1)*125).
#[derive(Clone, Debug)]
struct RegisterBucket {
    /// Start address for the bulk read (bucket_index * 125)
    start_addr: u16,
    /// Number of registers to read = max(field_addr + reg_count) - start_addr, capped at 125
    read_count: u16,
    /// Register type for this bucket (all fields in a bucket share the same type)
    reg_type: RegisterType,
    /// Fields within this bucket
    fields: Vec<BucketField>,
}

/// A derived (formula-based) field — evaluated at runtime from device-read values.
#[derive(Clone, Debug)]
struct DerivedField {
    field_key: String,
    formula_str: String,
    eval_order: i32,
}

struct TableRuntime {
    table: TableDef,
    target_client: Arc<PgClient>,
    /// Target-DB conn string — used to re-acquire a client when the cached
    /// connection dies (target-DB restart) so buffered rows can be retried.
    target_conn: String,
    mapping: Vec<MappingRow>,
    device: Device,
    gateway: Option<Gateway>,
    /// Precomputed register buckets for Modbus bulk reads (empty for non-Modbus devices)
    modbus_buckets: Vec<RegisterBucket>,
    /// Derived fields with formulas, sorted by eval_order for single-pass evaluation
    derived_fields: Vec<DerivedField>,
    /// Effective alert rules (schema rules merged with this table's overrides),
    /// loaded at job start.
    alert_rules: Vec<AlertRule>,
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
    /// f32-origin value (Modbus float32, OPC UA Float). Kept as f32 so SQL
    /// serialization uses the f32 shortest-roundtrip representation
    /// ("229.4", not "229.39999389648438").
    Float32(f32),
    Int(i64),
    Bool(bool),
    Text(String),
}

type FieldMap = HashMap<String, FieldValue>;

impl FieldValue {
    fn as_f64(&self) -> Option<f64> {
        match self {
            FieldValue::Float(v) => Some(*v),
            FieldValue::Float32(v) => Some(*v as f64),
            FieldValue::Int(v) => Some(*v as f64),
            FieldValue::Bool(v) => Some(if *v { 1.0 } else { 0.0 }),
            FieldValue::Text(_) => None,
        }
    }

    fn to_sql_literal(&self) -> String {
        match self {
            // Any non-finite numeric (NaN OR +/-Infinity) becomes SQL NULL —
            // Infinity in the DB poisons downstream aggregates (avg/sum) and
            // NaN-vs-Inf asymmetry made failures formula-dependent.
            FieldValue::Float(v) => {
                if v.is_finite() {
                    v.to_string()
                } else {
                    "NULL".to_string()
                }
            }
            FieldValue::Float32(v) => {
                if v.is_finite() {
                    v.to_string()
                } else {
                    "NULL".to_string()
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
            FieldValue::Float32(v) => write!(f, "{}", v),
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
    /// Kept alive for the lifetime of the session — dropping the opcua Client
    /// tears down the underlying connection (never read directly).
    _client: Client,
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

    fn get_session(&self, device: &Device, gateway: Option<&Gateway>) -> Result<Arc<Mutex<DeviceSession>>> {
        let dev_id = device.id.clone();
        if let Some(sess) = self.sessions.lock().unwrap_or_else(std::sync::PoisonError::into_inner).get(&dev_id) {
            return Ok(sess.clone());
        }
        let endpoint = normalize_endpoint(&opcua_endpoint_url(device, gateway)?);
        let mut client = ClientBuilder::new()
            .application_name("neuract-job-runner")
            .application_uri("urn:neuract:job-runner")
            .product_uri("urn:neuract:job-runner")
            .trust_server_certs(true)
            .create_sample_keypair(true)
            .session_retry_limit(1)
            .client()
            .ok_or_else(|| anyhow!("opcua client build failed"))?;
        let server_endpoints = client
            .get_server_endpoints_from_url(endpoint.as_str())
            .map_err(|e| anyhow!("opcua connect failed: {}: {}", endpoint, e))?;
        let chosen = pick_opcua_endpoint(&server_endpoints, &endpoint)
            .ok_or_else(|| anyhow!("opcua server at {} offers no unsecured (None) endpoint", endpoint))?;
        let session = client
            .new_session_from_info((chosen, IdentityToken::Anonymous))
            .map_err(|e| anyhow!("opcua session failed: {}", e))?;
        session
            .write()
            .connect_and_activate()
            .map_err(|e| anyhow!("opcua connect failed: {}: {}", endpoint, e))?;
        let sess = DeviceSession {
            endpoint,
            _client: client,
            session,
            nodes: HashMap::new(),
            last_used: Instant::now(),
        };
        let handle = Arc::new(Mutex::new(sess));
        self.sessions.lock().unwrap_or_else(std::sync::PoisonError::into_inner).insert(dev_id, handle.clone());
        Ok(handle)
    }

    /// Forget a device's session after a failed read so the next poll
    /// reconnects (e.g. after the OPC UA server restarted).
    fn drop_session(&self, device_id: &str) {
        self.sessions.lock().unwrap_or_else(std::sync::PoisonError::into_inner).remove(device_id);
    }
}

/// Where an OPC UA device lives, as the API's connection test resolves it:
/// params.endpoint, else an opc.tcp:// gateway host, else the gateway host
/// (or params.host) with the device port (default 4840).
fn opcua_endpoint_url(device: &Device, gateway: Option<&Gateway>) -> Result<String> {
    let param = |k: &str| {
        device.params.get(k).and_then(|v| v.as_str()).map(str::trim).filter(|v| !v.is_empty()).map(str::to_string)
    };
    if let Some(ep) = param("endpoint") {
        return Ok(ep);
    }
    let gw_host = gateway.and_then(|g| g.host.as_deref()).map(str::trim).filter(|h| !h.is_empty());
    if let Some(h) = gw_host.filter(|h| h.starts_with("opc.tcp://")) {
        return Ok(h.to_string());
    }
    let host = gw_host.map(str::to_string).or_else(|| param("host")).or_else(|| param("ip"));
    match host {
        Some(h) => Ok(format!("opc.tcp://{}:{}", h, device.port.unwrap_or(4840))),
        None => Err(anyhow!("OPCUA_ENDPOINT_MISSING: device {} has no endpoint or host", device.id)),
    }
}

/// Split an opc.tcp URL into "opc.tcp://host:port" and its path ("" if none).
fn split_opc_url(url: &str) -> Option<(&str, &str)> {
    let start = url.find("://")? + 3;
    Some(match url[start..].find('/') {
        Some(i) => (&url[..start + i], &url[start + i..]),
        None => (url, ""),
    })
}

/// The server endpoint to open a session on: one with security None that
/// matches the configured URL, else (devices are often entered as just
/// opc.tcp://ip:port) the server's unsecured endpoint path at our host:port.
fn pick_opcua_endpoint(server_endpoints: &[EndpointDescription], url: &str) -> Option<EndpointDescription> {
    if let Some(e) = Client::find_matching_endpoint(server_endpoints, url, SecurityPolicy::None, MessageSecurityMode::None) {
        return Some(e);
    }
    let mut e = server_endpoints
        .iter()
        .find(|e| {
            e.security_mode == MessageSecurityMode::None
                && SecurityPolicy::from_uri(e.security_policy_uri.as_ref()) == SecurityPolicy::None
        })?
        .clone();
    let (base, _) = split_opc_url(url)?;
    let (_, path) = split_opc_url(e.endpoint_url.as_ref())?;
    e.endpoint_url = format!("{}{}", base, path).into();
    Some(e)
}

struct TargetManager {
    clients: Mutex<HashMap<String, Arc<PgClient>>>,
}

impl TargetManager {
    fn new() -> Self {
        Self { clients: Mutex::new(HashMap::new()) }
    }

    async fn get_client(&self, conn: &str) -> Result<Arc<PgClient>> {
        // #7: Check if cached client is still alive.
        // IMPORTANT: clone the Arc out and drop the mutex guard BEFORE any
        // .await or re-lock — holding the guard across the health check
        // self-deadlocked when the stale branch re-locked the same mutex.
        let cached = self.clients
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(conn)
            .cloned();
        if let Some(c) = cached {
            // Quick health check — if this fails, drop and reconnect
            if !c.is_closed() && c.simple_query("").await.is_ok() {
                return Ok(c);
            }
            warn!("target db connection stale, reconnecting: {}", redact_dsn(conn));
            self.clients.lock().unwrap_or_else(std::sync::PoisonError::into_inner).remove(conn);
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
        self.clients.lock().unwrap_or_else(std::sync::PoisonError::into_inner).insert(conn.to_string(), client.clone());
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

/// Connect to the metadata DB and spawn its connection-driver task.
/// The driver task only logs on error; liveness is detected via
/// `client.is_closed()` in the supervisor loop, which reconnects.
async fn connect_meta_db(app_db_url: &str) -> Result<Arc<PgClient>> {
    let (client, conn) = tokio_postgres::connect(app_db_url, NoTls)
        .await
        .context("metadata db connect failed")?;
    tokio::spawn(async move {
        if let Err(e) = conn.await {
            error!("metadata db connection error: {}", e);
        }
    });
    Ok(Arc::new(client))
}

/// Connect to the bench-metrics DB, spawn its connection-driver task and make
/// sure the bench_metrics table exists. Mirrors connect_meta_db: the driver
/// task only logs on error; a dead client is detected via `is_closed()` by
/// each job's report loop, which reconnects with capped backoff (non-fatal).
async fn connect_bench_db(bench_db_url: &str) -> Result<Arc<PgClient>> {
    let (client, conn) = tokio_postgres::connect(bench_db_url, NoTls)
        .await
        .context("bench metrics db connect failed")?;
    tokio::spawn(async move {
        if let Err(e) = conn.await {
            error!("bench metrics db connection error: {}", e);
        }
    });
    client.execute(
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
    Ok(Arc::new(client))
}

/// Resolves when SIGINT (ctrl-c) or, on unix, SIGTERM is received.
async fn shutdown_signal() {
    #[cfg(unix)]
    {
        let mut term = match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(s) => s,
            Err(e) => {
                error!("failed to install SIGTERM handler: {}", e);
                let _ = tokio::signal::ctrl_c().await;
                return;
            }
        };
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = term.recv() => {},
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

/// Sleep for `total`, waking early (within ~200ms) if `flag` becomes true.
async fn sleep_unless(total: Duration, flag: &AtomicBool) {
    let slice = Duration::from_millis(200);
    let deadline = Instant::now() + total;
    while Instant::now() < deadline {
        if flag.load(Ordering::Relaxed) {
            return;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        tokio::time::sleep(remaining.min(slice)).await;
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    setup_logging();
    setup_mqtt_logging();
    let app_db_url = env::var("APP_DB_URL").context("APP_DB_URL is required")?;
    let bench_db_url = env::var("BENCH_DB_URL")
        .unwrap_or_else(|_| "postgresql://postgres@localhost/loggerfast_metrics".to_string());
    let poll_ms: u64 = env::var("JOB_POLL_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2000);

    // Graceful shutdown: SIGTERM/SIGINT set this flag; the supervisor loop
    // then stops all jobs (each drains pending writes + flushes its batch
    // buffers) and exits 0.
    let shutdown = Arc::new(AtomicBool::new(false));
    {
        let sd = shutdown.clone();
        tokio::spawn(async move {
            shutdown_signal().await;
            info!("shutdown signal received — stopping jobs and flushing buffers");
            sd.store(true, Ordering::SeqCst);
        });
    }

    let mut meta_client = connect_meta_db(&app_db_url).await?;

    // Connect to bench metrics DB (jobs self-heal this connection later)
    let bench_client = connect_bench_db(&bench_db_url).await?;
    info!("bench metrics DB connected: {}", redact_dsn(&bench_db_url));

    let device_manager = Arc::new(DeviceManager::new());

    let api_base_url = env::var("API_BASE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:5175".to_string());
    let http_client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .context("Failed to build HTTP client")?;
    let notify_cooldown_sec: u64 = env::var("TRIGGER_NOTIFY_COOLDOWN_SEC")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(10);

    let mut running: HashMap<String, JobHandle> = HashMap::new();
    // Supervisor resilience: transient metadata-DB errors must never escape
    // this loop — running jobs hold their own target-DB connections and keep
    // acquiring through a meta-DB outage.
    let mut meta_err_streak: u32 = 0;

    loop {
        if shutdown.load(Ordering::SeqCst) {
            break;
        }

        // Detect a dead metadata connection and reconnect (the connection
        // driver task exits on error; it never reconnects by itself).
        if meta_client.is_closed() {
            match connect_meta_db(&app_db_url).await {
                Ok(c) => {
                    info!("metadata db reconnected");
                    meta_client = c;
                    meta_err_streak = 0;
                }
                Err(e) => {
                    meta_err_streak = meta_err_streak.saturating_add(1);
                    let backoff = meta_backoff(poll_ms, meta_err_streak);
                    warn!(
                        "metadata db reconnect failed (attempt {}): {} — retrying in {:.1}s; running jobs unaffected",
                        meta_err_streak, e, backoff.as_secs_f64()
                    );
                    sleep_unless(backoff, &shutdown).await;
                    continue;
                }
            }
        }

        let jobs = match load_running_jobs(meta_client.as_ref()).await {
            Ok(jobs) => {
                meta_err_streak = 0;
                jobs
            }
            Err(e) => {
                meta_err_streak = meta_err_streak.saturating_add(1);
                let backoff = meta_backoff(poll_ms, meta_err_streak);
                warn!(
                    "supervisor poll failed (attempt {}): {} — retrying in {:.1}s; running jobs unaffected",
                    meta_err_streak, e, backoff.as_secs_f64()
                );
                sleep_unless(backoff, &shutdown).await;
                continue;
            }
        };
        let want: HashMap<String, JobDef> = jobs.into_iter().map(|j| (j.id.clone(), j)).collect();

        for job in want.values() {
            if running.contains_key(&job.id) {
                continue;
            }
            let stop = Arc::new(AtomicBool::new(false));
            let meta = meta_client.clone();
            let dm = device_manager.clone();
            let bc = bench_client.clone();
            let bdu = bench_db_url.clone();
            let job_clone = job.clone();
            let job_id = job.id.clone();
            let stop_thread = stop.clone();
            let hc = http_client.clone();
            let abu = api_base_url.clone();
            let ncs = notify_cooldown_sec;
            let join = std::thread::spawn(move || {
                let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                    Ok(rt) => rt,
                    Err(e) => {
                        error!("job {} runtime init failed: {}", job_id, e);
                        return;
                    }
                };
                if let Err(e) = rt.block_on(run_job(job_clone, meta, dm, bc, bdu, stop_thread, hc, abu, ncs)) {
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

        sleep_unless(Duration::from_millis(poll_ms), &shutdown).await;
    }

    // Graceful shutdown: signal every job to stop, then join each job thread.
    // run_job's epilogue drains the pending background write and flushes all
    // buffered batch rows before returning, so no in-flight data is lost.
    let n = running.len();
    info!("graceful shutdown: stopping {} running job(s)", n);
    for handle in running.values() {
        handle.stop.store(true, Ordering::SeqCst);
    }
    for (job_id, handle) in running.drain() {
        let join = handle.join;
        match tokio::task::spawn_blocking(move || join.join()).await {
            Ok(Ok(())) => info!("job {} stopped cleanly", job_id),
            Ok(Err(_)) => error!("job {} thread panicked during shutdown", job_id),
            Err(e) => error!("job {} join task failed during shutdown: {}", job_id, e),
        }
    }
    info!("graceful shutdown complete ({} job(s) stopped) — exiting 0", n);
    Ok(())
}

/// Capped exponential backoff for metadata-DB failures: poll_ms * 2^(streak-1),
/// capped at 30s, with a 250ms floor.
fn meta_backoff(poll_ms: u64, streak: u32) -> Duration {
    let base = poll_ms.max(250);
    let factor = 1u64 << streak.saturating_sub(1).min(10);
    Duration::from_millis(base.saturating_mul(factor).min(30_000))
}

async fn run_job(
    job: JobDef,
    meta_client: Arc<PgClient>,
    device_manager: Arc<DeviceManager>,
    mut bench_client: Arc<PgClient>,
    bench_db_url: String,
    stop: Arc<AtomicBool>,
    http_client: reqwest::Client,
    api_base_url: String,
    notify_cooldown_sec: u64,
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
    let mqtt_manager = Arc::new(MqttManager::new());
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
    let mut last_notification: HashMap<String, Instant> = HashMap::new();
    let notify_cooldown = Duration::from_secs(notify_cooldown_sec);
    // Alert state per (table, field): the alert level id currently active, or
    // None = normal. Seeded from app_alert_state so a restart does not re-raise.
    let mut alert_states = load_alert_states(meta_client.as_ref(), &job.tables).await;
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
    // M11: hard cap on buffered rows per table while the target DB is down.
    // When the cap forces dropping, the drop is loudly logged + error-CSV'd.
    let buffer_cap_rows: usize = env::var("BATCH_BUFFER_CAP_ROWS")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|&n: &usize| n > 0)
        .unwrap_or(10_000);
    let mut flush_fail_streak: u32 = 0;
    let mut flush_backoff_until: Option<Instant> = None;
    // Bench-metrics self-healing (mirrors the meta-DB reconnect pattern):
    // the connection driver task never reconnects by itself, so without this
    // every report window after an outage logged 'bench db write failed'
    // forever. Non-fatal: data acquisition is unaffected either way.
    let mut bench_err_streak: u32 = 0;
    let mut bench_retry_at: Option<Instant> = None;
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
        // Heal dead target-DB connections (e.g. after a target-DB restart) so
        // buffered rows can be retried instead of failing forever. is_closed()
        // is a cheap local check; reconnect attempts are bounded by a timeout.
        for rt in table_runtimes.values_mut() {
            if rt.target_client.is_closed() {
                let conn = rt.target_conn.clone();
                let reconnect = tokio::time::timeout(
                    Duration::from_secs(5),
                    target_manager.get_client(&conn),
                ).await;
                match reconnect {
                    Ok(Ok(c)) => {
                        info!("job {} table {} target db reconnected", job.id, rt.table.id);
                        rt.target_client = c;
                    }
                    Ok(Err(e)) => {
                        let key = format!("target_reconnect:{}:{}", job.id, rt.table.id);
                        if let Some(n) = rate_limit_event(&key, 1, Duration::from_secs(15)) {
                            warn!(
                                "job {} table {} target db reconnect failed: {} [{} attempt(s) since last report]",
                                job.id, rt.table.id, e, n
                            );
                        }
                    }
                    Err(_) => {
                        let key = format!("target_reconnect:{}:{}", job.id, rt.table.id);
                        if let Some(n) = rate_limit_event(&key, 1, Duration::from_secs(15)) {
                            warn!(
                                "job {} table {} target db reconnect timed out [{} attempt(s) since last report]",
                                job.id, rt.table.id, n
                            );
                        }
                    }
                }
            }
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
                    read_endpoint_group(tables, &device_manager, &modbus_manager, &mqtt_manager, &job.id)
                }).collect();
                let all_results = join_all(group_futures).await;
                // H-DBC-1: capture the row timestamp once, right after the
                // device reads complete, and carry it into the write path —
                // never stamp rows at write-execute time.
                // Stamp rows in IST (+05:30) per deployment preference (column name stays timestamp_utc).
                let cycle_ts = Utc::now().with_timezone(&FixedOffset::east_opt(19800).unwrap()).to_rfc3339();

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

                // Phase 1.5: Evaluate derived fields for each table
                for (table_rt, values) in pending_writes.iter_mut() {
                    eval_derived_fields(&job.id, &table_rt.table.id, &table_rt.derived_fields, values, table_rt.device.nominal_voltage);
                }
                // Phase 1.6: alert states (act only when a field's state changes)
                for (table_rt, values) in pending_writes.iter() {
                    let changes = detect_alert_changes(&mut alert_states, &table_rt.table.id, &table_rt.alert_rules, values);
                    for ch in changes {
                        persist_alert_change(meta_client.as_ref(), &http_client, &api_base_url, &job.id, &table_rt.table.name, &ch).await;
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
                        let ts_clone = cycle_ts.clone();
                        pending_write_handle = Some(tokio::spawn(async move {
                            let t_write = Instant::now();
                            let result = write_all_tables_batch_owned(&owned_writes, &job_id_clone, &ts_clone).await;
                            let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
                            (result, write_ms, table_count)
                        }));
                    }
                } else {
                    // Buffer all reads, stamped with the read-time timestamp
                    for (table_rt, values) in pending_writes {
                        let tid = table_rt.table.id.clone();
                        let buf = batch_buffers.entry(tid.clone()).or_default();
                        buf.push(BufferedRow { timestamp_utc: cycle_ts.clone(), values });
                        // M11: enforce the hard buffer cap at insert time so the
                        // buffer cannot grow unbounded during a target-DB outage.
                        if buf.len() > buffer_cap_rows {
                            let overflow = buf.len() - buffer_cap_rows;
                            buf.drain(..overflow);
                            let key = format!("buffer_drop:{}:{}", job.id, tid);
                            if let Some(n) = rate_limit_event(&key, overflow as u64, Duration::from_secs(10)) {
                                error!(
                                    "job {} table {} buffer cap {} reached — DROPPED {} oldest row(s) (target DB unreachable too long)",
                                    job.id, tid, buffer_cap_rows, n
                                );
                                let _ = append_error_csv(
                                    &job.id, &tid, "buffer_drop",
                                    &format!("dropped_rows={} buffer_cap={}", n, buffer_cap_rows),
                                );
                            }
                        }
                        batch_flush_ts.entry(tid).or_insert_with(Instant::now);
                    }

                    // M11: while in failure backoff, skip flush attempts (rows
                    // keep accumulating under the cap and are retried later).
                    let in_backoff = flush_backoff_until.map_or(false, |t| Instant::now() < t);

                    // Collect all buffers that need flushing
                    let mut to_flush: Vec<(String, Vec<BufferedRow>)> = Vec::new();
                    if !in_backoff {
                        for (tid, buf) in batch_buffers.iter_mut() {
                            if buf.is_empty() { continue; }
                            let count_trigger = buf.len() as u64 >= job.batch_count;
                            let time_trigger = job.batch_ms > 0.0
                                && batch_flush_ts.get(tid).map_or(false, |t| t.elapsed().as_secs_f64() * 1000.0 >= job.batch_ms);
                            if count_trigger || time_trigger {
                                to_flush.push((tid.clone(), std::mem::take(buf)));
                            }
                        }
                    }

                    // Flush all due buffers (per-table statements; one bad
                    // table no longer aborts the other tables' rows)
                    let flush_count = to_flush.len();
                    if !to_flush.is_empty() {
                        let flushed_tids: Vec<String> = to_flush.iter().map(|(tid, _)| tid.clone()).collect();
                        let total_rows: usize = to_flush.iter().map(|(_, rows)| rows.len()).sum();
                        let t_write = Instant::now();
                        let (wt, failed) = flush_all_buffered(&table_runtimes, to_flush, &job.id).await;
                        let write_ms = t_write.elapsed().as_secs_f64() * 1000.0;
                        if failed.is_empty() {
                            win_writes_ok += 1;
                            win_write_ms_sum += write_ms;
                            win_sql_build_ms_sum += wt.build_ms;
                            win_db_execute_ms_sum += wt.execute_ms;
                            flush_fail_streak = 0;
                            flush_backoff_until = None;
                            info!("Job {} [FLUSH_ALL] tables={} rows={} elapsed_ms={:.2}", job.id, flush_count, total_rows, write_ms);
                        } else {
                            win_writes_err += 1;
                            // M11: re-queue failed tables' rows (in front, to
                            // preserve time order) for bounded retry with backoff.
                            for (tid, mut rows, emsg) in failed {
                                warn!("job {} table {} flush failed ({} rows re-queued): {}", job.id, tid, rows.len(), emsg);
                                let _ = append_error_csv(&job.id, &tid, "write", &emsg);
                                let buf = batch_buffers.entry(tid.clone()).or_default();
                                let newer = std::mem::take(buf);
                                rows.extend(newer);
                                if rows.len() > buffer_cap_rows {
                                    let overflow = rows.len() - buffer_cap_rows;
                                    rows.drain(..overflow);
                                    let key = format!("buffer_drop:{}:{}", job.id, tid);
                                    if let Some(n) = rate_limit_event(&key, overflow as u64, Duration::from_secs(10)) {
                                        error!(
                                            "job {} table {} buffer cap {} reached — DROPPED {} oldest row(s) after flush failure",
                                            job.id, tid, buffer_cap_rows, n
                                        );
                                        let _ = append_error_csv(
                                            &job.id, &tid, "buffer_drop",
                                            &format!("dropped_rows={} buffer_cap={}", n, buffer_cap_rows),
                                        );
                                    }
                                }
                                *buf = rows;
                            }
                            flush_fail_streak = flush_fail_streak.saturating_add(1);
                            let backoff_ms = 500u64
                                .saturating_mul(1 << flush_fail_streak.min(6))
                                .min(30_000);
                            flush_backoff_until = Some(Instant::now() + Duration::from_millis(backoff_ms));
                            warn!(
                                "job {} flush failure streak={} — next flush attempt in {}ms",
                                job.id, flush_fail_streak, backoff_ms
                            );
                        }
                        for tid in &flushed_tids {
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
                    let values = match read_table_values_cached(table_rt, &device_manager, &modbus_manager, &mqtt_manager, &job.id).await {
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
                    // H-DBC-1: stamp the row at read time, not at write time
                    let read_ts = Utc::now().with_timezone(&FixedOffset::east_opt(19800).unwrap()).to_rfc3339();
                    // Evaluate derived fields before trigger evaluation
                    let mut values = values;
                    eval_derived_fields(&job.id, &table_id, &table_rt.derived_fields, &mut values, table_rt.device.nominal_voltage);
                    // Alert states (act only when a field's state changes)
                    for ch in detect_alert_changes(&mut alert_states, &table_id, &table_rt.alert_rules, &values) {
                        persist_alert_change(meta_client.as_ref(), &http_client, &api_base_url, &job.id, &table_rt.table.name, &ch).await;
                    }
                    let fire_info = eval_triggers(&triggers, table_id.as_str(), &values, &mut last_values);
                    let should_fire = fire_info.is_some();
                    info!("Job {} [TRIG_EVAL] table={} fired={}", job.id, table_id, should_fire);
                    if should_fire {
                        // Fire-and-forget trigger notification
                        if let Some(ref info) = fire_info {
                            let tname = table_rt.table.name.clone();
                            let key = format!("{}:{}", table_id, info.field_key);
                            let should_notify = last_notification.get(&key)
                                .map(|t| t.elapsed() >= notify_cooldown)
                                .unwrap_or(true);
                            if should_notify {
                                last_notification.insert(key, Instant::now());
                                let client = http_client.clone();
                                let url = api_base_url.clone();
                                let jname = job.name.clone();
                                let info_c = info.clone();
                                tokio::spawn(async move {
                                    send_trigger_notification(&client, &url, &jname, &tname, &info_c).await;
                                });
                            }
                        }
                        let t_write = Instant::now();
                        match write_values_cached(table_rt, &values, &job.id, &read_ts).await {
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
            // Log metrics to MQTT-specific log if this job has any MQTT devices
            {
                let has_mqtt = table_runtimes.values().any(|rt| rt.device.protocol.eq_ignore_ascii_case("mqtt"));
                if has_mqtt {
                    mqtt_log("METRICS", &format!(
                        "job={} window={:.1}s reads/s={:.1} writes/s={:.1} read_avg_ms={:.3} write_avg_ms={:.3} connect_avg_ms={:.3} fields_avg_ms={:.3} build_avg_ms={:.3} exec_avg_ms={:.3} loop_p95_ms={} overrun_pct={:.1} read_err={} write_err={}",
                        job.id, window_secs, reads_per_sec, writes_per_sec,
                        read_avg_ms, write_avg_ms,
                        modbus_connect_avg_ms, modbus_fields_avg_ms,
                        sql_build_avg_ms, db_execute_avg_ms,
                        p95_txt, overrun_pct,
                        win_reads_err, win_writes_err,
                    ));
                }
            }
            // Heal a dead bench-metrics connection (is_closed() is a cheap
            // local check) with capped backoff between attempts.
            if bench_client.is_closed() {
                let now = Instant::now();
                if bench_retry_at.map_or(true, |t| now >= t) {
                    match tokio::time::timeout(
                        Duration::from_secs(5),
                        connect_bench_db(&bench_db_url),
                    ).await {
                        Ok(Ok(c)) => {
                            info!("job {} bench metrics db reconnected", job.id);
                            bench_client = c;
                            bench_err_streak = 0;
                            bench_retry_at = None;
                        }
                        Ok(Err(e)) => {
                            bench_err_streak = bench_err_streak.saturating_add(1);
                            let backoff = meta_backoff(1000, bench_err_streak);
                            warn!(
                                "job {} bench metrics db reconnect failed (attempt {}): {} — next attempt in {:.1}s; data writes unaffected",
                                job.id, bench_err_streak, e, backoff.as_secs_f64()
                            );
                            bench_retry_at = Some(now + backoff);
                        }
                        Err(_) => {
                            bench_err_streak = bench_err_streak.saturating_add(1);
                            let backoff = meta_backoff(1000, bench_err_streak);
                            warn!(
                                "job {} bench metrics db reconnect timed out (attempt {}) — next attempt in {:.1}s; data writes unaffected",
                                job.id, bench_err_streak, backoff.as_secs_f64()
                            );
                            bench_retry_at = Some(now + backoff);
                        }
                    }
                }
            }
            // #9: Fire-and-forget bench DB write — don't block the loop
            if !bench_client.is_closed() {
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
        // Wake early when stop is requested so graceful shutdown is prompt
        sleep_unless(sleep, &stop).await;
    }
    // #4: Drain pending background write before stopping
    if let Some(handle) = pending_write_handle.take() {
        match handle.await {
            Ok((Ok(_wt), write_ms, table_count)) => {
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
    // Final flush: write any remaining buffered rows before stopping.
    // Retried with short backoff; if rows still cannot be written, the loss
    // is logged loudly with exact row counts and recorded in the error CSV.
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
            let mut remaining = final_flush;
            let max_attempts = 3u32;
            for attempt in 1..=max_attempts {
                let (_, failed) = flush_all_buffered(&table_runtimes, remaining, &job.id).await;
                if failed.is_empty() {
                    info!("Job {} [FLUSH_FINAL] OK", job.id);
                    remaining = Vec::new();
                    break;
                }
                remaining = failed
                    .into_iter()
                    .map(|(tid, rows, _)| (tid, rows))
                    .collect();
                if attempt < max_attempts {
                    let retry_rows: usize = remaining.iter().map(|(_, rows)| rows.len()).sum();
                    warn!(
                        "job {} final flush attempt {}/{} failed for {} table(s) ({} rows) — retrying",
                        job.id, attempt, max_attempts, remaining.len(), retry_rows
                    );
                    tokio::time::sleep(Duration::from_millis(500 * attempt as u64)).await;
                }
            }
            for (tid, rows) in &remaining {
                error!(
                    "job {} table {} FINAL FLUSH FAILED after {} attempts — DROPPED {} row(s)",
                    job.id, tid, max_attempts, rows.len()
                );
                let _ = append_error_csv(
                    &job.id, tid, "buffer_drop",
                    &format!("dropped_rows={} reason=final_flush_failed attempts={}", rows.len(), max_attempts),
                );
            }
        }
    }
    // Release the gateway's Modbus session before the thread goes away. Without
    // this the socket stays open for the life of the process and nothing else can
    // talk to the meter (single-session gateways).
    modbus_manager.disconnect_all().await;
    info!("job {} stopped", job.id);
    Ok(())
}

/// Precompute register buckets for Modbus bulk reads.
/// Divides the register address space into 125-register sections and groups fields by section.
fn build_modbus_buckets(mapping: &[MappingRow]) -> Vec<RegisterBucket> {
    // Key: (register_type, bucket_index) → fields
    let mut bucket_map: HashMap<(RegisterType, u16), Vec<BucketField>> = HashMap::new();

    for row in mapping {
        if !row.protocol.eq_ignore_ascii_case("modbus") {
            continue;
        }
        let (reg_type, address, bit) = match parse_modbus_address(&row.address) {
            Some(v) => v,
            None => continue,
        };
        let encoding = if !row.encoding.is_empty() {
            row.encoding.to_lowercase()
        } else if !row.data_type.is_empty() {
            row.data_type.to_lowercase()
        } else {
            "float32".to_string()
        };
        // A "<reg>,<bit>" field reads exactly one register and masks the bit;
        // otherwise the register count comes from the encoding width.
        let reg_count = if bit.is_some() { 1 } else { modbus_encoding_info(&encoding).0 };

        let bucket_idx = address / 125;
        bucket_map.entry((reg_type, bucket_idx)).or_default().push(BucketField {
            field_key: row.field_key.clone(),
            address,
            reg_count,
            encoding,
            scale: row.scale,
            bit,
        });
    }

    let mut buckets: Vec<RegisterBucket> = Vec::new();
    for ((reg_type, bucket_idx), fields) in bucket_map {
        // FIX 1 (bucket): start the bulk read at the FIRST mapped register, not the 125-aligned
        // boundary. Meters whose registers begin above the boundary (e.g. Mitsubishi EMMS796,
        // first reg 768 -> boundary 750) otherwise get IllegalDataAddress because the read would
        // span non-existent registers 750..767. min..max keeps the request inside the real range;
        // bucket_idx still groups fields into <=125-register windows.
        let start_addr = fields.iter().map(|f| f.address).min().unwrap_or(bucket_idx * 125);
        // read_count = first mapped register .. end of the last field, capped at 125
        let max_end = fields.iter()
            .map(|f| f.address + f.reg_count)
            .max()
            .unwrap_or(start_addr);
        let read_count = (max_end - start_addr).min(125);

        buckets.push(RegisterBucket {
            start_addr,
            read_count,
            reg_type,
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
    let table_id_for_alerts = table.id.clone();
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
    let all_mapping = load_mapping_rows(target_client.as_ref(), &table.name).await?;
    if all_mapping.is_empty() {
        return Ok(None);
    }

    // Partition into device-read rows and derived (formula) rows
    let (derived_rows, device_rows): (Vec<MappingRow>, Vec<MappingRow>) = all_mapping
        .into_iter()
        .partition(|m| m.protocol.eq_ignore_ascii_case("derived"));

    // Build derived fields sorted by eval_order (stored in scale column)
    let mut derived_fields: Vec<DerivedField> = derived_rows
        .iter()
        .map(|r| DerivedField {
            field_key: r.field_key.clone(),
            formula_str: r.address.clone(),
            eval_order: r.scale.unwrap_or(0.0) as i32,
        })
        .collect();
    sort_derived_fields(&mut derived_fields);

    // If there are no device rows, we still need a device for non-derived tables
    if device_rows.is_empty() && derived_fields.is_empty() {
        return Ok(None);
    }

    let device_id = device_rows.iter().find_map(|m| m.device_id.clone()).or_else(|| table.device_id.clone());
    let Some(device_id) = device_id else {
        if !derived_fields.is_empty() {
            // Pure-derived table with no device rows — should not happen in same-table design
            warn!("table {} has only derived fields but no device rows, skipping", table.id);
        }
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
        build_modbus_buckets(&device_rows)
    } else {
        Vec::new()
    };

    if !derived_fields.is_empty() {
        info!(
            "table {} has {} derived fields (eval_order: {:?})",
            table.id,
            derived_fields.len(),
            derived_fields.iter().map(|d| (&d.field_key, d.eval_order)).collect::<Vec<_>>()
        );
    }

    Ok(Some(TableRuntime {
        table,
        target_client,
        target_conn: target.conn.clone(),
        mapping: device_rows,
        device,
        gateway,
        modbus_buckets,
        derived_fields,
        alert_rules: load_alert_rules(meta_client, &table_id_for_alerts).await,
    }))
}

async fn read_table_values_cached(
    table_rt: &TableRuntime,
    device_manager: &Arc<DeviceManager>,
    modbus_manager: &ModbusManager,
    mqtt_manager: &Arc<MqttManager>,
    job_id: &str,
) -> Result<(FieldMap, ReadTimings)> {
    match table_rt.device.protocol.to_lowercase().as_str() {
        "opcua" => {
            read_opcua_values_blocking(
                device_manager.clone(),
                table_rt.device.clone(),
                table_rt.gateway.clone(),
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
        "mqtt" => {
            read_mqtt_values(
                mqtt_manager,
                &table_rt.device,
                &table_rt.mapping,
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
        // MQTT: group all devices on the same broker together (one background task per broker)
        "mqtt" => {
            let host = table_rt.device.params.get("host")
                .or_else(|| table_rt.device.params.get("ip"))
                .and_then(|v| v.as_str())
                .unwrap_or(&table_rt.device.id);
            let port = resolve_mqtt_port(&table_rt.device);
            format!("mqtt:{}:{}", host, port)
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
    mqtt_manager: &Arc<MqttManager>,
    job_id: &str,
) -> Vec<(&'a TableRuntime, Result<(FieldMap, ReadTimings)>, f64)> {
    let mut results = Vec::with_capacity(tables.len());
    for table_rt in tables {
        let t_read = Instant::now();
        let result = read_table_values_cached(table_rt, device_manager, modbus_manager, mqtt_manager, job_id).await;
        let read_ms = t_read.elapsed().as_secs_f64() * 1000.0;
        results.push((table_rt, result, read_ms));
    }
    results
}

async fn write_values_cached(
    table_rt: &TableRuntime,
    values: &FieldMap,
    job_id: &str,
    read_ts: &str,
) -> Result<WriteTimings> {
    if values.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }
    let t_build = Instant::now();
    // #6: Use batch_execute with inline literals (same as batch path) to avoid TEXT type mismatch
    // H-DBC-1: timestamp captured at read time by the caller
    let ts_literal = pg_escape_literal(read_ts);
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

/// Escape a string value for use as a PostgreSQL literal in batch SQL.
///
/// Device-sourced strings can contain anything. Rules:
/// - NUL bytes are stripped (Postgres rejects NUL in text values outright).
/// - Single quotes are doubled.
/// - Backslashes and C0/DEL control characters force the E'...' escape-string
///   form with backslash escapes, which is correct regardless of the server's
///   standard_conforming_strings setting.
fn pg_escape_literal(s: &str) -> String {
    let mut needs_escape_form = false;
    let mut out = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '\0' => { /* strip: not representable in PG text */ }
            '\'' => out.push_str("''"),
            '\\' => {
                out.push_str("\\\\");
                needs_escape_form = true;
            }
            '\n' => {
                out.push_str("\\n");
                needs_escape_form = true;
            }
            '\r' => {
                out.push_str("\\r");
                needs_escape_form = true;
            }
            '\t' => {
                out.push_str("\\t");
                needs_escape_form = true;
            }
            c if (c as u32) < 0x20 || (c as u32) == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32));
                needs_escape_form = true;
            }
            c => out.push(c),
        }
    }
    if needs_escape_form {
        format!("E'{}'", out)
    } else {
        format!("'{}'", out)
    }
}

// --- Rate-limited warning helper ---

static RATE_LIMITER: OnceLock<Mutex<HashMap<String, (u64, Instant)>>> = OnceLock::new();

/// Accumulates `count` occurrences for `key`. Returns Some(total_since_last_log)
/// when the event should be logged now (first occurrence, or `min_interval`
/// elapsed since last log), otherwise None. Keeps repetitive per-tick warnings
/// (derived NaN, buffer drops) from flooding the logs while never being silent.
fn rate_limit_event(key: &str, count: u64, min_interval: Duration) -> Option<u64> {
    let map = RATE_LIMITER.get_or_init(|| Mutex::new(HashMap::new()));
    let mut map = map.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    match map.get_mut(key) {
        None => {
            map.insert(key.to_string(), (0, Instant::now()));
            Some(count)
        }
        Some((pending, last_logged)) => {
            *pending += count;
            if last_logged.elapsed() >= min_interval {
                let total = *pending;
                *pending = 0;
                *last_logged = Instant::now();
                Some(total)
            } else {
                None
            }
        }
    }
}

/// DP2: deterministic derived evaluation order — sort by (eval_order, field_key).
///
/// eval_order ties (duplicated orders persisted by older API builds) used to
/// leave evaluation order dependent on DB row order, which Postgres does not
/// guarantee without ORDER BY. The field_key tiebreak makes the single-pass
/// evaluation in eval_derived_fields reproducible across restarts.
fn sort_derived_fields(fields: &mut [DerivedField]) {
    fields.sort_by(|a, b| {
        a.eval_order
            .cmp(&b.eval_order)
            .then_with(|| a.field_key.cmp(&b.field_key))
    });
}

/// Evaluate derived (formula) fields for one table into `values`.
///
/// Consistent non-finite rule (DP4): a derived result that is NaN or +/-Infinity
/// — or an eval error — produces SQL NULL for that field, is NOT fed into the
/// meval context (so downstream formulas referencing it also fail to NULL),
/// and is surfaced via a rate-limited warn + error-CSV row. Never silent.
fn eval_derived_fields(job_id: &str, table_id: &str, derived: &[DerivedField], values: &mut FieldMap, nominal_voltage: Option<f64>) {
    if derived.is_empty() {
        return;
    }
    // Build f64 context from device-read values
    let mut ctx: meval::Context = meval::Context::new();
    for (k, v) in values.iter() {
        if let Some(f) = v.as_f64() {
            ctx.var(k.clone(), f);
        }
    }
    // Device-level constants. Nominal voltage is a property of the installation,
    // not of the meter model, so it cannot live in the schema formula. Both the
    // line-to-line rating and its line-to-neutral equivalent are exposed; a device
    // with no rating set simply leaves them undefined, and any formula using them
    // evaluates to NULL (loudly, via the eval-error path below) instead of lying.
    if let Some(nv) = nominal_voltage.filter(|v| v.is_finite() && *v > 0.0) {
        ctx.var("dev_nominal_voltage".to_string(), nv);
        ctx.var("dev_nominal_voltage_ln".to_string(), nv / 3f64.sqrt());
    }
    // Single-pass evaluation — derived fields are pre-sorted by eval_order
    for field in derived {
        let outcome = meval::eval_str_with_context(&field.formula_str, &ctx);
        match outcome {
            Ok(val) if val.is_finite() => {
                ctx.var(field.field_key.clone(), val);
                values.insert(field.field_key.clone(), FieldValue::Float(val));
            }
            other => {
                let reason = match other {
                    Ok(v) => format!("non-finite result ({})", v),
                    Err(e) => format!("eval error: {}", e),
                };
                let rl_key = format!("derived:{}:{}:{}", job_id, table_id, field.field_key);
                if let Some(n) = rate_limit_event(&rl_key, 1, Duration::from_secs(30)) {
                    warn!(
                        "Job {} table {} derived field {} -> NULL ({}) [{} occurrence(s) since last report]",
                        job_id, table_id, field.field_key, reason, n
                    );
                    let _ = append_error_csv(
                        job_id,
                        table_id,
                        "derived",
                        &format!("field={} {} occurrences={}", field.field_key, reason, n),
                    );
                }
                // NaN serializes to SQL NULL via to_sql_literal
                values.insert(field.field_key.clone(), FieldValue::Float(f64::NAN));
            }
        }
    }
}

/// #4: Owned table-write batch for background spawning.
/// Takes Vec of (client, table_name, values) so it can be `static.
///
/// Each table's INSERT runs as its own statement (implicit transaction), so a
/// bad value in one table fails only that table's row, never the whole group.
/// Per-table failures are logged + error-CSV'd here; the returned Err is a
/// summary so the caller's write_err counter still increments.
async fn write_all_tables_batch_owned(
    pending: &[(Arc<PgClient>, String, FieldMap)],
    job_id: &str,
    read_ts: &str,
) -> Result<WriteTimings> {
    if pending.is_empty() {
        return Ok(WriteTimings { build_ms: 0.0, execute_ms: 0.0 });
    }

    // H-DBC-1: timestamp captured at read time by the caller
    let ts_literal = pg_escape_literal(read_ts);

    let mut total_build_ms = 0.0f64;
    let mut total_execute_ms = 0.0f64;
    let mut total_tables = 0u32;
    let mut failed_tables = 0u32;

    for (client, table_name, values) in pending {
        if values.is_empty() {
            continue;
        }
        total_tables += 1;
        let t_build = Instant::now();
        let full_name = format!("{}.{}", quote_ident("neuract"), quote_ident(table_name));
        let mut cols = vec![quote_ident("timestamp_utc")];
        let mut vals = vec![ts_literal.clone()];
        for (k, v) in values {
            cols.push(quote_ident(k));
            vals.push(v.to_sql_literal());
        }
        let sql = format!(
            "INSERT INTO {} ({}) VALUES ({});",
            full_name, cols.join(","), vals.join(",")
        );
        total_build_ms += t_build.elapsed().as_secs_f64() * 1000.0;

        let t_exec = Instant::now();
        if let Err(e) = client.batch_execute(&sql).await {
            failed_tables += 1;
            let detail = if let Some(d) = e.as_db_error() {
                format!(
                    "severity={} code={} message={} detail={:?}",
                    d.severity(), d.code().code(), d.message(), d.detail()
                )
            } else {
                e.to_string()
            };
            warn!(
                "Job {} [WRITE_ALL_BATCH] table {} failed: {} | sql_preview: {}",
                job_id, table_name, detail, &sql[..sql.len().min(600)]
            );
            let _ = append_error_csv(job_id, table_name, "write", &detail);
            continue;
        }
        total_execute_ms += t_exec.elapsed().as_secs_f64() * 1000.0;
    }

    info!(
        "Job {} [WRITE_ALL_BATCH] [DB_EXECUTE] tables={} failed={} elapsed_ms={:.2}",
        job_id, total_tables, failed_tables, total_execute_ms
    );

    if failed_tables > 0 {
        return Err(anyhow!(
            "{}/{} table writes failed (per-table details in log + error CSV)",
            failed_tables, total_tables
        ));
    }
    Ok(WriteTimings { build_ms: total_build_ms, execute_ms: total_execute_ms })
}

/// Flush multiple tables' buffered rows.
///
/// Each table's rows go in ONE multi-row INSERT executed as its own implicit
/// transaction — per-table atomicity is preserved, but one bad value (or one
/// table's error) no longer rolls back every other table's rows.
///
/// Returns the timings plus the tables that failed, with their rows handed
/// back to the caller for re-queueing (M11) and the error message.
async fn flush_all_buffered(
    table_runtimes: &HashMap<String, TableRuntime>,
    to_flush: Vec<(String, Vec<BufferedRow>)>,
    job_id: &str,
) -> (WriteTimings, Vec<(String, Vec<BufferedRow>, String)>) {
    let mut timings = WriteTimings { build_ms: 0.0, execute_ms: 0.0 };
    let mut failed: Vec<(String, Vec<BufferedRow>, String)> = Vec::new();
    if to_flush.is_empty() {
        return (timings, failed);
    }

    let mut flushed_tables = 0usize;
    let mut flushed_rows = 0usize;

    for (tid, rows) in to_flush {
        if rows.is_empty() {
            continue;
        }
        let table_rt = match table_runtimes.get(&tid) {
            Some(rt) => rt,
            None => {
                failed.push((tid, rows, "table runtime not found".to_string()));
                continue;
            }
        };

        let t_build = Instant::now();
        let first = &rows[0];
        let mut field_keys: Vec<String> = first.values.keys().cloned().collect();
        field_keys.sort();
        let mut col_names = vec!["timestamp_utc".to_string()];
        col_names.extend(field_keys.iter().cloned());
        let cols_quoted: Vec<String> = col_names.iter().map(|c| quote_ident(c)).collect();
        let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));

        let mut value_rows = Vec::with_capacity(rows.len());
        for row in &rows {
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

        let sql = format!(
            "INSERT INTO {} ({}) VALUES {};",
            table_name, cols_quoted.join(","), value_rows.join(",")
        );
        timings.build_ms += t_build.elapsed().as_secs_f64() * 1000.0;

        let t_exec = Instant::now();
        match table_rt.target_client.batch_execute(&sql).await {
            Ok(()) => {
                timings.execute_ms += t_exec.elapsed().as_secs_f64() * 1000.0;
                flushed_tables += 1;
                flushed_rows += rows.len();
            }
            Err(e) => {
                let emsg = e.to_string();
                failed.push((tid, rows, emsg));
            }
        }
    }

    info!(
        "Job {} [FLUSH_ALL_BATCH] [DB_EXECUTE] tables={} rows={} failed_tables={} elapsed_ms={:.2}",
        job_id, flushed_tables, flushed_rows, failed.len(), timings.execute_ms
    );

    (timings, failed)
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
    let _guard = error_csv_lock().lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    // Bounded: roll to a single .1 backup once the CSV exceeds the cap
    // (LOGGER_ERROR_CSV_MAX_MB, default 50 MB) so it can never grow unbounded.
    let csv_cap = env::var("LOGGER_ERROR_CSV_MAX_MB")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .map(|mb| mb.max(1) * 1024 * 1024)
        .unwrap_or(50 * 1024 * 1024);
    if fs::metadata(&path).map(|m| m.len() >= csv_cap).unwrap_or(false) {
        let backup = format!("{}.1", path.display());
        let _ = fs::remove_file(&backup);
        let _ = fs::rename(&path, &backup);
    }
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

async fn send_trigger_notification(
    client: &reqwest::Client,
    api_base_url: &str,
    job_name: &str,
    table_name: &str,
    info: &TriggerFireInfo,
) {
    let message = format!(
        "Trigger fired: job='{}' table='{}' field='{}' op='{}' value={} prev={}",
        job_name,
        table_name,
        info.field_key,
        info.op,
        info.current_value
            .map(|v| format!("{:.4}", v))
            .unwrap_or_else(|| "N/A".into()),
        info.previous_value
            .map(|v| format!("{:.4}", v))
            .unwrap_or_else(|| "N/A".into()),
    );
    let url = format!("{}/auth/notifications", api_base_url);
    let payload = serde_json::json!({
        "type": "trigger",
        "message": message,
    });
    match client.post(&url).json(&payload).send().await {
        Ok(r) if !r.status().is_success() => {
            warn!("Trigger notify HTTP {}", r.status());
        }
        Err(e) => {
            warn!("Trigger notify failed: {}", e);
        }
        _ => {}
    }
}

fn eval_triggers(
    triggers: &[Trigger],
    table_id: &str,
    values: &FieldMap,
    last_values: &mut HashMap<String, FieldMap>,
) -> Option<TriggerFireInfo> {
    let last = last_values.entry(table_id.to_string()).or_insert_with(HashMap::new);
    for tr in triggers {
        let cur = values.get(&tr.field_key).and_then(|v| v.as_f64());
        let prev = last.get(&tr.field_key).and_then(|v| v.as_f64());
        if eval_op(cur, prev, &tr.op, tr.value, tr.deadband) {
            return Some(TriggerFireInfo {
                field_key: tr.field_key.clone(),
                op: tr.op.clone(),
                current_value: cur,
                previous_value: prev,
            });
        }
    }
    None
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

// --- Alerts on readings ---
//
// Rules come from app_schema_alert (the schema blueprint) merged with
// app_table_alert (per-table override for the same field + level, or
// enabled = 0 to switch it off). Each table field has one state: normal, or
// the most severe level whose rule matches the latest reading. Only a change
// of state is acted on: app_alert_state is updated, an app_alert_event row is
// written and an "alert" notification is posted.

#[derive(Clone, Debug, PartialEq)]
struct AlertRule {
    field_key: String,
    alert_id: String,
    alert_name: String,
    severity: i64,
    op: String,
    threshold: f64,
}

/// A table override row: op/threshold None = inherit the schema rule's.
#[derive(Clone, Debug)]
struct AlertOverride {
    field_key: String,
    alert_id: String,
    alert_name: String,
    severity: i64,
    op: Option<String>,
    threshold: Option<f64>,
    enabled: bool,
}

#[derive(Clone, Debug, PartialEq)]
struct AlertChange {
    table_id: String,
    field_key: String,
    from_alert_id: Option<String>,
    to: Option<AlertRule>,
    value: f64,
}

/// Effective rules = schema rules, with overrides for the same (field, level)
/// replacing them; an override without a schema rule is a table-only rule.
fn merge_alert_rules(schema: Vec<AlertRule>, overrides: Vec<AlertOverride>) -> Vec<AlertRule> {
    let mut out: Vec<AlertRule> = schema;
    for o in overrides {
        let pos = out.iter().position(|r| r.field_key == o.field_key && r.alert_id == o.alert_id);
        if !o.enabled {
            if let Some(i) = pos {
                out.remove(i);
            }
            continue;
        }
        match pos {
            Some(i) => {
                if let Some(op) = o.op {
                    out[i].op = op;
                }
                if let Some(t) = o.threshold {
                    out[i].threshold = t;
                }
            }
            None => {
                if let (Some(op), Some(t)) = (o.op, o.threshold) {
                    out.push(AlertRule {
                        field_key: o.field_key,
                        alert_id: o.alert_id,
                        alert_name: o.alert_name,
                        severity: o.severity,
                        op,
                        threshold: t,
                    });
                }
            }
        }
    }
    out
}

/// The state of every field that has rules and a numeric reading:
/// Some(most severe matching rule) or None (normal). Fields without a
/// numeric value in this reading are left out (their state is unchanged).
fn eval_alert_state(rules: &[AlertRule], values: &FieldMap) -> Vec<(String, f64, Option<AlertRule>)> {
    let mut fields: Vec<&str> = rules.iter().map(|r| r.field_key.as_str()).collect();
    fields.sort();
    fields.dedup();
    let mut out = Vec::new();
    for f in fields {
        let Some(v) = values.get(f).and_then(|fv| fv.as_f64()).filter(|v| v.is_finite()) else { continue; };
        let mut best: Option<&AlertRule> = None;
        for r in rules.iter().filter(|r| r.field_key == f) {
            if eval_op(Some(v), None, &r.op, Some(r.threshold), 0.0)
                && best.map_or(true, |b| r.severity > b.severity)
            {
                best = Some(r);
            }
        }
        out.push((f.to_string(), v, best.cloned()));
    }
    out
}

/// Compare against the tracked state; update it and return the changes.
fn detect_alert_changes(
    states: &mut HashMap<(String, String), Option<String>>,
    table_id: &str,
    rules: &[AlertRule],
    values: &FieldMap,
) -> Vec<AlertChange> {
    let mut changes = Vec::new();
    if rules.is_empty() {
        return changes;
    }
    for (field, value, rule) in eval_alert_state(rules, values) {
        let key = (table_id.to_string(), field.clone());
        let old = states.get(&key).cloned().flatten();
        let new = rule.as_ref().map(|r| r.alert_id.clone());
        if old != new {
            states.insert(key, new);
            changes.push(AlertChange { table_id: table_id.to_string(), field_key: field, from_alert_id: old, to: rule, value });
        }
    }
    changes
}

async fn load_alert_rules(client: &PgClient, table_id: &str) -> Vec<AlertRule> {
    let schema_rows = client
        .query(
            "SELECT sa.field_key, sa.alert_id, a.name, a.severity::bigint AS severity, sa.op, sa.threshold \
             FROM app_schema_alert sa JOIN app_alert a ON a.id = sa.alert_id \
             JOIN app_device_tables t ON t.schema_id = sa.schema_id WHERE t.id = $1",
            &[&table_id],
        )
        .await;
    let override_rows = client
        .query(
            "SELECT ta.field_key, ta.alert_id, a.name, a.severity::bigint AS severity, ta.op, ta.threshold, ta.enabled::bigint AS enabled \
             FROM app_table_alert ta JOIN app_alert a ON a.id = ta.alert_id WHERE ta.table_id = $1",
            &[&table_id],
        )
        .await;
    let (Ok(schema_rows), Ok(override_rows)) = (schema_rows, override_rows) else {
        warn!("table {} alert rules not loaded (alert tables missing?) — alerts off for it", table_id);
        return Vec::new();
    };
    let schema: Vec<AlertRule> = schema_rows
        .iter()
        .map(|r| AlertRule {
            field_key: r.get("field_key"),
            alert_id: r.get("alert_id"),
            alert_name: r.get("name"),
            severity: r.get("severity"),
            op: r.get("op"),
            threshold: r.get("threshold"),
        })
        .collect();
    let overrides: Vec<AlertOverride> = override_rows
        .iter()
        .map(|r| AlertOverride {
            field_key: r.get("field_key"),
            alert_id: r.get("alert_id"),
            alert_name: r.get("name"),
            severity: r.get("severity"),
            op: r.get("op"),
            threshold: r.get("threshold"),
            enabled: r.get::<_, i64>("enabled") != 0,
        })
        .collect();
    let rules = merge_alert_rules(schema, overrides);
    if !rules.is_empty() {
        info!("table {} loaded {} alert rule(s)", table_id, rules.len());
    }
    rules
}

async fn load_alert_states(client: &PgClient, table_ids: &[String]) -> HashMap<(String, String), Option<String>> {
    let mut out = HashMap::new();
    match client
        .query("SELECT table_id, field_key, alert_id FROM app_alert_state WHERE table_id = ANY($1)", &[&table_ids])
        .await
    {
        Ok(rows) => {
            for r in rows {
                out.insert((r.get::<_, String>("table_id"), r.get::<_, String>("field_key")), Some(r.get::<_, String>("alert_id")));
            }
        }
        Err(e) => warn!("alert states not loaded: {}", e),
    }
    out
}

static ALERT_EVENT_SEQ: AtomicU64 = AtomicU64::new(0);

/// Write one state change: app_alert_state (upsert or delete), an
/// app_alert_event row, and a fire-and-forget "alert" notification.
async fn persist_alert_change(
    meta: &PgClient,
    http_client: &reqwest::Client,
    api_base_url: &str,
    job_id: &str,
    table_name: &str,
    ch: &AlertChange,
) {
    let at = Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true);
    let state_res = match &ch.to {
        Some(rule) => {
            meta.execute(
                "INSERT INTO app_alert_state (table_id, field_key, alert_id, value, since) VALUES ($1, $2, $3, $4, $5) \
                 ON CONFLICT (table_id, field_key) DO UPDATE SET alert_id = EXCLUDED.alert_id, value = EXCLUDED.value, since = EXCLUDED.since",
                &[&ch.table_id, &ch.field_key, &rule.alert_id, &ch.value, &at],
            )
            .await
        }
        None => {
            meta.execute(
                "DELETE FROM app_alert_state WHERE table_id = $1 AND field_key = $2",
                &[&ch.table_id, &ch.field_key],
            )
            .await
        }
    };
    if let Err(e) = state_res {
        warn!("alert state write failed table={} field={}: {}", ch.table_id, ch.field_key, e);
    }
    let seq = ALERT_EVENT_SEQ.fetch_add(1, Ordering::Relaxed);
    let event_id = format!("ae_{}_{}", Utc::now().timestamp_millis(), seq);
    let to_id = ch.to.as_ref().map(|r| r.alert_id.clone());
    let op = ch.to.as_ref().map(|r| r.op.clone());
    let threshold = ch.to.as_ref().map(|r| r.threshold);
    if let Err(e) = meta
        .execute(
            "INSERT INTO app_alert_event (id, table_id, field_key, from_alert_id, to_alert_id, value, op, threshold, job_id, at) \
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            &[&event_id, &ch.table_id, &ch.field_key, &ch.from_alert_id, &to_id, &ch.value, &op, &threshold, &job_id, &at],
        )
        .await
    {
        warn!("alert event write failed table={} field={}: {}", ch.table_id, ch.field_key, e);
    }
    let message = match &ch.to {
        Some(r) => format!("Alert {}: {}.{} = {} ({} {})", r.alert_name, table_name, ch.field_key, ch.value, r.op, r.threshold),
        None => format!("Alert cleared: {}.{} = {} (back to normal)", table_name, ch.field_key, ch.value),
    };
    info!("job {} {}", job_id, message);
    let client = http_client.clone();
    let url = format!("{}/auth/notifications", api_base_url);
    tokio::spawn(async move {
        let payload = serde_json::json!({ "type": "alert", "message": message });
        match client.post(&url).json(&payload).send().await {
            Ok(r) if !r.status().is_success() => warn!("Alert notify HTTP {}", r.status()),
            Err(e) => warn!("Alert notify failed: {}", e),
            _ => {}
        }
    });
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
            "SELECT provider,conn FROM app_db_targets WHERE id=$1",
            &[&target_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    Ok(Some(DbTarget {
        provider: r.get("provider"),
        conn: r.get("conn"),
    }))
}

async fn load_device(client: &PgClient, device_id: &str) -> Result<Option<Device>> {
    let rows = client
        .query(
            "SELECT id,protocol,params_json,unit_id,port,gateway_id,nominal_voltage FROM app_devices WHERE id=$1",
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
        // Stored as REAL (float4); accept float8 too in case the column type changes.
        nominal_voltage: r
            .try_get::<_, Option<f32>>("nominal_voltage")
            .ok()
            .flatten()
            .map(|v| v as f64)
            .or_else(|| r.try_get::<_, Option<f64>>("nominal_voltage").ok().flatten()),
    }))
}

async fn load_gateway(client: &PgClient, gateway_id: &str) -> Result<Option<Gateway>> {
    let rows = client
        .query(
            "SELECT host FROM app_gateways WHERE id=$1",
            &[&gateway_id],
        )
        .await?;
    if rows.is_empty() {
        return Ok(None);
    }
    let r = &rows[0];
    Ok(Some(Gateway {
        host: r.try_get("host").ok().flatten(),
    }))
}

async fn load_mapping_rows(target_client: &PgClient, table_name: &str) -> Result<Vec<MappingRow>> {
    // Try with encoding column first; fall back without it for older schemas.
    // DP2: ORDER BY field_key — without it Postgres row order is unspecified
    // and derived evaluation order could differ between restarts.
    let rows_result = target_client
        .query(
            "SELECT table_name,field_key,protocol,address,data_type,scale,device_id,encoding \
             FROM neuract.device_mappings WHERE table_name=$1 ORDER BY field_key",
            &[&table_name],
        )
        .await;
    let (rows, has_encoding) = match rows_result {
        Ok(r) => (r, true),
        Err(_) => {
            let r = target_client
                .query(
                    "SELECT table_name,field_key,protocol,address,data_type,scale,device_id \
                     FROM neuract.device_mappings WHERE table_name=$1 ORDER BY field_key",
                    &[&table_name],
                )
                .await?;
            (r, false)
        }
    };
    let mut out = Vec::new();
    for r in rows {
        let enc: String = if has_encoding {
            r.try_get::<_, Option<String>>("encoding")
                .ok()
                .flatten()
                .unwrap_or_default()
        } else {
            String::new()
        };
        out.push(MappingRow {
            field_key: r.get("field_key"),
            protocol: r.get("protocol"),
            address: r.get("address"),
            data_type: r.get("data_type"),
            encoding: enc,
            scale: read_optional_f64(&r, "scale"),
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
        // Logical-type fallbacks (when encoding column is absent, data_type is used)
        "int" | "bool" | "string" => (1, "u16"),
        _ => (1, "u16"), // fallback: single register as u16
    }
}

/// Reorder registers according to byte-order code before big-endian decode.
/// ABCD = Big Endian (no change), CDAB = word-swapped, BADC = byte-swapped, DCBA = little endian.
fn reorder_registers(regs: &[u16], order: &str) -> Vec<u16> {
    match order {
        "CDAB" => regs.iter().rev().copied().collect(),
        "BADC" => regs.iter().map(|r| r.swap_bytes()).collect(),
        "DCBA" => regs.iter().rev().map(|r| r.swap_bytes()).collect(),
        _ => regs.to_vec(), // ABCD or unknown → no change
    }
}

/// Decode raw Modbus registers into a float value (mirrors Python _decode_registers).
fn decode_registers(regs: &[u16], encoding: &str, byte_order: &str) -> Option<f64> {
    let enc = encoding.to_lowercase();
    let (count, tag) = modbus_encoding_info(&enc);
    if regs.len() < count as usize {
        return None;
    }
    let subset = &regs[..count as usize];
    // Apply byte-order reordering for multi-register types
    let ordered = if count > 1 {
        reorder_registers(subset, byte_order)
    } else {
        subset.to_vec()
    };
    // Pack registers as big-endian 16-bit words into byte buffer
    let mut buf = vec![0u8; count as usize * 2];
    for (i, &reg) in ordered.iter().enumerate() {
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
        self.contexts.lock().unwrap_or_else(std::sync::PoisonError::into_inner).remove(key);
    }

    /// #7: Drop stale connections that have been idle too long
    fn drop_stale(&self) {
        let mut map = self.contexts.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let max_idle = self.max_idle;
        map.retain(|_, (_, last_used)| last_used.elapsed() < max_idle);
    }

    /// Explicitly close every cached connection.
    ///
    /// Dropping the map is NOT enough: the TCP socket stays ESTABLISHED after the
    /// job thread exits. Most Modbus gateways permit a single concurrent session,
    /// so a leaked socket locks out dry-run, mapping validation and any external
    /// tool until the whole engine is restarted. Called on the job stop path.
    async fn disconnect_all(&self) {
        // Drain under the lock, then await outside it — a std Mutex guard cannot
        // be held across an await point.
        let drained: Vec<(String, tokio_modbus::client::Context)> = {
            let mut map = self
                .contexts
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            map.drain().map(|(k, (ctx, _))| (k, ctx)).collect()
        };
        for (key, mut ctx) in drained {
            // tokio-modbus signals a successful disconnect as an Err (the peer
            // closes the connection), so the result is deliberately ignored.
            let _ = ctx.disconnect().await;
            info!("modbus connection closed {}", key);
        }
    }
}

// --- MQTT connection manager ---

struct BrokerState {
    cache: Arc<Mutex<HashMap<String, serde_json::Value>>>, // gw_label → latest payload
    _client: AsyncClient,                                  // kept alive so channel stays open
    _task: tokio::task::JoinHandle<()>,
}

struct MqttManager {
    brokers: Mutex<HashMap<String, BrokerState>>,
}

impl MqttManager {
    fn new() -> Self {
        Self { brokers: Mutex::new(HashMap::new()) }
    }

    async fn ensure_connected(
        &self,
        broker_key: &str,
        host: &str,
        port: u16,
        username: &str,
        password: &str,
        topic: &str,
    ) -> Result<Arc<Mutex<HashMap<String, serde_json::Value>>>> {
        // Return existing connection if the background task is still alive
        {
            let brokers = self.brokers.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(state) = brokers.get(broker_key) {
                if !state._task.is_finished() {
                    return Ok(state.cache.clone());
                }
            }
        }

        let client_id = format!("neuract-{}", broker_key.replace(':', "-"));
        let mut options = MqttOptions::new(client_id, host, port);
        options.set_keep_alive(Duration::from_secs(30));
        if !username.is_empty() {
            options.set_credentials(username, password);
        }

        let (client, event_loop) = AsyncClient::new(options, 128);
        client
            .subscribe(topic, QoS::AtMostOnce)
            .await
            .map_err(|e| anyhow!("MQTT subscribe failed for {}: {}", broker_key, e))?;

        let cache: Arc<Mutex<HashMap<String, serde_json::Value>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let cache_clone = cache.clone();
        let key_log = broker_key.to_string();
        let task = tokio::spawn(mqtt_broker_task(event_loop, cache_clone, key_log));

        info!("MQTT connected to broker {} topic={}", broker_key, topic);
        mqtt_log("INFO", &format!("CONNECTED broker={} topic={}", broker_key, topic));
        let state = BrokerState { cache: cache.clone(), _client: client, _task: task };
        self.brokers.lock().unwrap_or_else(std::sync::PoisonError::into_inner).insert(broker_key.to_string(), state);
        Ok(cache)
    }
}

/// Background task: drives the MQTT event loop and updates the gw-label cache on every publish.
async fn mqtt_broker_task(
    mut event_loop: rumqttc::EventLoop,
    cache: Arc<Mutex<HashMap<String, serde_json::Value>>>,
    broker_key: String,
) {
    loop {
        match event_loop.poll().await {
            Ok(Event::Incoming(Packet::Publish(p))) => {
                match serde_json::from_slice::<serde_json::Value>(&p.payload) {
                    Ok(payload) => {
                        if let Some(gw) = payload.get("gw").and_then(|v| v.as_str()) {
                            let meter_count = payload.get("meters").and_then(|m| m.as_array()).map(|a| a.len()).unwrap_or(0);
                            mqtt_log("DATA", &format!("broker={} gw={} meters={}", broker_key, gw, meter_count));
                            cache.lock().unwrap_or_else(std::sync::PoisonError::into_inner).insert(gw.to_string(), payload);
                        }
                    }
                    Err(e) => {
                        warn!("MQTT [{}] JSON parse error: {}", broker_key, e);
                        mqtt_log("ERROR", &format!("broker={} JSON parse error: {}", broker_key, e));
                    }
                }
            }
            Err(e) => {
                warn!("MQTT [{}] event loop error: {} — will retry on next poll", broker_key, e);
                mqtt_log("ERROR", &format!("broker={} event loop error: {}", broker_key, e));
                tokio::time::sleep(Duration::from_secs(3)).await;
            }
            _ => {} // Ack packets, connack, suback — ignore
        }
    }
}

// --- MQTT host / port resolution ---

fn resolve_mqtt_host(device: &Device) -> Result<String> {
    let host = device
        .params
        .get("host")
        .or_else(|| device.params.get("ip"))
        .and_then(|v| v.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    host.ok_or_else(|| anyhow!("MQTT_HOST_MISSING for device {}", device.id))
}

fn resolve_mqtt_port(device: &Device) -> u16 {
    if let Some(p) = device.port {
        return p as u16;
    }
    device
        .params
        .get("port")
        .and_then(|v| v.as_u64().or_else(|| v.as_str().and_then(|s| s.parse().ok())))
        .unwrap_or(1883) as u16
}

// --- MQTT read implementation ---

async fn read_mqtt_values(
    mqtt_manager: &Arc<MqttManager>,
    device: &Device,
    mapping: &[MappingRow],
    job_id: &str,
) -> Result<(FieldMap, ReadTimings)> {
    let t0 = Instant::now();

    let host = resolve_mqtt_host(device)?;
    let port = resolve_mqtt_port(device);
    let username = device
        .params
        .get("username")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let password = device
        .params
        .get("password")
        .or_else(|| device.params.get("pass"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let mqtt_gw = device
        .params
        .get("mqtt_gateway")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let topic = device
        .params
        .get("topic")
        .and_then(|v| v.as_str())
        .unwrap_or("factory/#")
        .to_string();
    let meter_id = device.unit_id.unwrap_or(1) as i64;
    let broker_key = format!("{}:{}", host, port);

    let cache = mqtt_manager
        .ensure_connected(&broker_key, &host, port, &username, &password, &topic)
        .await?;
    let connect_ms = t0.elapsed().as_secs_f64() * 1000.0;

    let t_fields = Instant::now();

    // Snapshot the latest payload for this gw label (lock held briefly)
    let payload = {
        let map = cache.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        map.get(&mqtt_gw).cloned()
    };
    let payload = match payload {
        Some(p) => p,
        None => {
            let msg = format!("MQTT_NO_DATA: no message received yet for gw='{}' on {}", mqtt_gw, broker_key);
            mqtt_log("WARN", &format!("job={} {}", job_id, msg));
            return Err(anyhow!("{}", msg));
        }
    };

    let meters = payload
        .get("meters")
        .and_then(|m| m.as_array())
        .ok_or_else(|| anyhow!("MQTT_NO_METERS: payload missing 'meters' array for gw='{}'", mqtt_gw))?;

    let meter = meters
        .iter()
        .find(|m| m.get("id").and_then(|v| v.as_i64()) == Some(meter_id))
        .ok_or_else(|| {
            anyhow!(
                "MQTT_METER_NOT_FOUND: meter id={} not found in gw='{}' payload",
                meter_id,
                mqtt_gw
            )
        })?;

    let mut values: FieldMap = HashMap::new();
    for row in mapping {
        if row.protocol.to_lowercase() != "mqtt" {
            continue;
        }
        // address = JSON field name in the meter object (e.g. "V1", "kW", "PF")
        let fv_opt: Option<FieldValue> = match meter.get(&row.address) {
            Some(serde_json::Value::Number(n)) => n.as_f64().map(FieldValue::Float),
            Some(serde_json::Value::Bool(b)) => Some(FieldValue::Float(if *b { 1.0 } else { 0.0 })),
            Some(serde_json::Value::String(s)) => Some(FieldValue::Text(s.clone())),
            _ => None,
        };
        if let Some(fv) = fv_opt {
            let fv = if let (Some(scale), Some(f)) = (row.scale, fv.as_f64()) {
                FieldValue::Float(f * scale)
            } else {
                fv
            };
            values.insert(row.field_key.clone(), fv);
        }
    }

    let fields_ms = t_fields.elapsed().as_secs_f64() * 1000.0;
    let total_ms = t0.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [READ_MAPPING] [TOTAL] proto=mqtt gw={} meter_id={} fields={} elapsed_ms={:.2}",
        job_id, mqtt_gw, meter_id, values.len(), total_ms
    );
    mqtt_log("READ", &format!(
        "job={} gw={} meter_id={} fields={} elapsed_ms={:.2}",
        job_id, mqtt_gw, meter_id, values.len(), total_ms
    ));
    Ok((values, ReadTimings { connect_ms, fields_ms }))
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

/// Open a fresh Modbus/TCP connection with a bounded connect timeout.
/// Used by the per-bucket read retry: some gateways (e.g. flaky Moxa/NPort
/// units) reset the TCP session intermittently, so on a transport error we
/// reconnect and retry rather than skipping the meter for the whole cycle.
/// The connect is time-boxed so a "reset-then-refuse" gateway can't hang the job.
async fn modbus_reconnect(host: &str, port: u16, unit_id: u8) -> Result<tokio_modbus::client::Context> {
    let socket_addr = format!("{}:{}", host, port);
    let addr: std::net::SocketAddr = socket_addr
        .parse()
        .map_err(|e| anyhow!("invalid modbus address {}: {}", socket_addr, e))?;
    match tokio::time::timeout(
        std::time::Duration::from_secs(3),
        tokio_modbus::client::tcp::connect_slave(addr, Slave(unit_id)),
    ).await {
        Ok(Ok(c)) => Ok(c),
        Ok(Err(e)) => Err(anyhow!("MODBUS_RECONNECT_FAILED {}:{} err={}", host, port, e)),
        Err(_) => Err(anyhow!("MODBUS_RECONNECT_TIMEOUT {}:{}", host, port)),
    }
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
        let mut map = modbus_manager.contexts.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
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

    // Byte order: ABCD (default big endian), CDAB, BADC, DCBA
    let byte_order = device.params.get("order")
        .and_then(|v| v.as_str())
        .unwrap_or("ABCD");

    ctx.set_slave(Slave(unit_id));

    for bucket in buckets {
        let t_bucket = Instant::now();
        match bucket.reg_type {
            RegisterType::HoldingRegister | RegisterType::InputRegister => {
                // Per-read timeout + bounded retry on transient transport resets.
                //  - Timeout (meter silent = down)      -> skip meter, NO retry (a
                //    genuinely-dead unit must not cost 3x the timeout every cycle;
                //    the cycle awaits ALL reads, so a hung meter can't be retried).
                //  - Modbus exception (device said "no") -> skip bucket, keep connection.
                //  - Connection reset / broken pipe      -> reconnect + retry: some
                //    gateways drop the TCP session intermittently (flaky Moxa/NPort),
                //    so a single-shot read would fail forever. Only THIS branch retries.
                const MODBUS_READ_RETRIES: u32 = 2; // up to 3 total attempts
                let mut attempt: u32 = 0;
                let regs_opt: Option<Vec<u16>> = loop {
                    let read_result = match tokio::time::timeout(
                        std::time::Duration::from_secs(3),
                        async {
                            match bucket.reg_type {
                                RegisterType::HoldingRegister => ctx.read_holding_registers(bucket.start_addr, bucket.read_count).await,
                                _ => ctx.read_input_registers(bucket.start_addr, bucket.read_count).await,
                            }
                        },
                    ).await {
                        Ok(r) => r,
                        Err(_) => {
                            warn!("modbus bucket read timeout start={} count={} unit={} (meter not responding)",
                                  bucket.start_addr, bucket.read_count, unit_id);
                            modbus_manager.drop_context(&key);
                            return Err(anyhow!("modbus read timeout unit={}", unit_id));
                        }
                    };
                    match read_result {
                        Ok(Ok(regs)) => break Some(regs),
                        Ok(Err(exception)) => {
                            warn!("modbus bucket exception start={} count={} unit={} err={:?}",
                                  bucket.start_addr, bucket.read_count, unit_id, exception);
                            break None;
                        }
                        Err(e) if attempt < MODBUS_READ_RETRIES => {
                            attempt += 1;
                            warn!("modbus bucket read reset start={} count={} unit={} attempt={}/{} err={} — reconnecting",
                                  bucket.start_addr, bucket.read_count, unit_id, attempt, MODBUS_READ_RETRIES, e);
                            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                            match modbus_reconnect(&host, port, unit_id).await {
                                Ok(c) => { ctx = c; ctx.set_slave(Slave(unit_id)); }
                                Err(re) => { modbus_manager.drop_context(&key); return Err(re); }
                            }
                        }
                        Err(e) => {
                            warn!("modbus bucket read error start={} count={} unit={} err={} (retries exhausted)",
                                  bucket.start_addr, bucket.read_count, unit_id, e);
                            modbus_manager.drop_context(&key);
                            return Err(anyhow!("modbus read failed: {}", e));
                        }
                    }
                };
                if let Some(regs) = regs_opt {
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
                        // "<reg>,<bit>" → extract a single bit from the word as 0/1 (breaker/relay status).
                        if let Some(b) = field.bit {
                            let on = (field_regs[0] >> b) & 1 == 1;
                            values.insert(field.field_key.clone(), FieldValue::Bool(on));
                        } else if let Some(mut val) = decode_registers(field_regs, &field.encoding, byte_order) {
                            // Post-decode coercion
                            if field.encoding == "bool16" {
                                val = if val != 0.0 { 1.0 } else { 0.0 };
                            }
                            // Apply scale (computed in f64)
                            if let Some(scale) = field.scale {
                                val *= scale;
                            }
                            // H-RUST-2: float32-encoded values keep f32 precision
                            // so serialization round-trips ("229.4", not
                            // "229.39999389648438"). Scale math stays in f64,
                            // then rounds to f32 — matching the REAL columns.
                            let is_f32_origin = modbus_encoding_info(&field.encoding).1 == "f32";
                            let fv = if field.encoding == "uint16_enum" {
                                FieldValue::Int(val as i64)
                            } else if field.encoding == "bool16" {
                                FieldValue::Bool(val != 0.0)
                            } else if is_f32_origin {
                                FieldValue::Float32(val as f32)
                            } else {
                                FieldValue::Float(val)
                            };
                            values.insert(field.field_key.clone(), fv);
                        }
                    }
                }
            }
            // M-RUST-5: coils (FC1) and discrete inputs (FC2) are bit-valued —
            // read them with the proper function codes instead of silently
            // falling back to holding registers (which returned wrong data).
            RegisterType::Coil | RegisterType::DiscreteInput => {
                let read_result = match bucket.reg_type {
                    RegisterType::Coil => ctx.read_coils(bucket.start_addr, bucket.read_count).await,
                    _ => ctx.read_discrete_inputs(bucket.start_addr, bucket.read_count).await,
                };
                match read_result {
                    Ok(Ok(bits)) => {
                        info!(
                            "Job {} [READ_MAPPING] [MODBUS_BUCKET] type={:?} start={} count={} got={} elapsed_ms={:.2}",
                            job_id, bucket.reg_type, bucket.start_addr, bucket.read_count, bits.len(),
                            t_bucket.elapsed().as_secs_f64() * 1000.0
                        );
                        for field in &bucket.fields {
                            let offset = (field.address - bucket.start_addr) as usize;
                            match bits.get(offset) {
                                Some(&bit) => {
                                    values.insert(field.field_key.clone(), FieldValue::Bool(bit));
                                }
                                None => {
                                    warn!(
                                        "modbus coil/discrete field beyond read range field={} addr={} bits_len={}",
                                        field.field_key, field.address, bits.len()
                                    );
                                    let _ = append_error_csv(
                                        job_id, &field.field_key, "read",
                                        &format!("coil/discrete bit at addr {} outside response ({} bits)", field.address, bits.len()),
                                    );
                                }
                            }
                        }
                    }
                    Ok(Err(exception)) => {
                        warn!(
                            "modbus coil/discrete exception type={:?} start={} count={} unit={} err={:?}",
                            bucket.reg_type, bucket.start_addr, bucket.read_count, unit_id, exception
                        );
                    }
                    Err(e) => {
                        warn!(
                            "modbus coil/discrete read error type={:?} start={} count={} unit={} err={}",
                            bucket.reg_type, bucket.start_addr, bucket.read_count, unit_id, e
                        );
                        // On connection error, don't cache the broken context
                        modbus_manager.drop_context(&key);
                        return Err(anyhow!("modbus coil/discrete read failed: {}", e));
                    }
                }
            }
        }
    }
    let fields_ms = t_fields.elapsed().as_secs_f64() * 1000.0;
    info!(
        "Job {} [READ_MAPPING] [MODBUS_FIELDS_TOTAL] buckets={} fields={} elapsed_ms={:.2}",
        job_id, buckets.len(), values.len(), fields_ms
    );

    // Put context back for reuse with timestamp
    modbus_manager.contexts.lock().unwrap_or_else(std::sync::PoisonError::into_inner).insert(key, (ctx, Instant::now()));

    info!(
        "Job {} [READ_MAPPING] [TOTAL] proto=modbus fields={} elapsed_ms={:.2}",
        job_id, values.len(), t_fn.elapsed().as_secs_f64() * 1000.0
    );
    Ok((values, ReadTimings { connect_ms, fields_ms }))
}

fn read_opcua_value(session: &Arc<Mutex<DeviceSession>>, row: &MappingRow, job_id: &str) -> Result<Option<FieldValue>> {
    let t_field = Instant::now();
    let mut sess = session.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    let node_id = if let Some(node_id) = sess.nodes.get(&row.address) {
        node_id.clone()
    } else {
        let Ok(parsed) = NodeId::from_str(&row.address) else {
            // A mistyped NodeId is a mapping error for this field only — skip
            // it (NULL) instead of failing the whole table's read.
            warn!("Job {} field {}: invalid OPC UA node id {:?} — skipped", job_id, row.field_key, row.address);
            return Ok(None);
        };
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
            // Preserve f32 origin through scaling (scale math in f64, then
            // round back to f32) so SQL serialization stays shortest-roundtrip.
            *fv = match fv {
                FieldValue::Float32(_) => FieldValue::Float32((n * scale) as f32),
                _ => FieldValue::Float(n * scale),
            };
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
    gateway: Option<Gateway>,
    mapping: Vec<MappingRow>,
    job_id: String,
) -> Result<(FieldMap, ReadTimings)> {
    tokio::task::spawn_blocking(move || {
        let t_fn = Instant::now();
        let t_conn = Instant::now();
        let session = device_manager.get_session(&device, gateway.as_ref())?;
        let endpoint = session.lock().unwrap_or_else(std::sync::PoisonError::into_inner).endpoint.clone();
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
            let value = match read_opcua_value(&session, &row, &job_id) {
                Ok(v) => v,
                Err(e) => {
                    // A broken connection fails every read: drop the session
                    // so the next poll reconnects instead of failing forever.
                    device_manager.drop_session(&device.id);
                    return Err(e);
                }
            };
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
        // H-RUST-2: OPC UA Float is f32 — keep f32 precision for serialization
        Variant::Float(b) => Some(FieldValue::Float32(*b)),
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

/// Mask the password component of a connection string for logging.
/// Mirrors the Python redact_dsn helper: user:secret@host -> user:***@host,
/// password=secret -> password=***. Host/db stay visible.
fn redact_dsn(dsn: &str) -> String {
    // URL form: scheme://user:password@host/...
    if let Some(scheme_end) = dsn.find("://") {
        let (scheme, rest) = dsn.split_at(scheme_end + 3);
        if let Some(at) = rest.find('@') {
            let creds = &rest[..at];
            if let Some(colon) = creds.find(':') {
                return format!("{}{}:***{}", scheme, &creds[..colon], &rest[at..]);
            }
        }
    }
    // Keyword form: password=secret (space- or end-delimited)
    if let Some(idx) = dsn.to_ascii_lowercase().find("password=") {
        let val_start = idx + "password=".len();
        let val_end = dsn[val_start..]
            .find(char::is_whitespace)
            .map(|i| val_start + i)
            .unwrap_or(dsn.len());
        return format!("{}***{}", &dsn[..val_start], &dsn[val_end..]);
    }
    dsn.to_string()
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

#[cfg(target_os = "windows")]
fn dpapi_unprotect(data: &[u8]) -> Option<Vec<u8>> {
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

#[cfg(not(target_os = "windows"))]
fn dpapi_unprotect(_data: &[u8]) -> Option<Vec<u8>> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rule(field: &str, id: &str, sev: i64, op: &str, t: f64) -> AlertRule {
        AlertRule { field_key: field.into(), alert_id: id.into(), alert_name: id.into(), severity: sev, op: op.into(), threshold: t }
    }

    fn reading(v: f64) -> FieldMap {
        let mut m = FieldMap::new();
        m.insert("voltage".into(), FieldValue::Float(v));
        m
    }

    fn opcua_dev(params: serde_json::Value, port: Option<i32>) -> Device {
        Device { id: "d1".into(), protocol: "opcua".into(), params, unit_id: None, port, gateway_id: None, nominal_voltage: None }
    }

    #[test]
    fn opcua_endpoint_resolution_order() {
        let gw = |h: &str| Gateway { host: Some(h.into()) };
        let ep = serde_json::json!({"endpoint": "opc.tcp://10.0.0.5:4840/srv/"});
        // params.endpoint wins
        assert_eq!(opcua_endpoint_url(&opcua_dev(ep, None), Some(&gw("opc.tcp://1.1.1.1:1"))).unwrap(), "opc.tcp://10.0.0.5:4840/srv/");
        // bulk import: endpoint on the gateway
        let none = serde_json::json!({"host": "10.0.0.9"});
        assert_eq!(opcua_endpoint_url(&opcua_dev(none.clone(), Some(4841)), Some(&gw("opc.tcp://10.0.0.9:4841"))).unwrap(), "opc.tcp://10.0.0.9:4841");
        // plain gateway host + device port, then params.host + default port
        assert_eq!(opcua_endpoint_url(&opcua_dev(none.clone(), Some(4999)), Some(&gw("10.0.0.7"))).unwrap(), "opc.tcp://10.0.0.7:4999");
        assert_eq!(opcua_endpoint_url(&opcua_dev(none, None), None).unwrap(), "opc.tcp://10.0.0.9:4840");
        // nothing configured: an error, never a hardcoded localhost server
        assert!(opcua_endpoint_url(&opcua_dev(serde_json::json!({}), None), None).is_err());
    }

    #[test]
    fn opcua_endpoint_pick_uses_server_path_at_our_address() {
        let adv = |url: &str, mode: MessageSecurityMode, pol: &str| -> EndpointDescription {
            (url, pol, mode, UserTokenPolicy::anonymous()).into()
        };
        let server = vec![
            adv("opc.tcp://plc-host:4840/neuract/sim/", MessageSecurityMode::SignAndEncrypt, SecurityPolicy::Basic256Sha256.to_uri()),
            adv("opc.tcp://plc-host:4840/neuract/sim/", MessageSecurityMode::None, SecurityPolicy::None.to_uri()),
        ];
        // exact path: hostname swapped for ours by the library
        let e = pick_opcua_endpoint(&server, "opc.tcp://10.0.0.5:4840/neuract/sim/").unwrap();
        assert_eq!(e.endpoint_url.as_ref(), "opc.tcp://10.0.0.5:4840/neuract/sim/");
        assert_eq!(e.security_mode, MessageSecurityMode::None);
        // entered without a path: server's path at our host:port
        let e = pick_opcua_endpoint(&server, "opc.tcp://10.0.0.5:4840").unwrap();
        assert_eq!(e.endpoint_url.as_ref(), "opc.tcp://10.0.0.5:4840/neuract/sim/");
        // secured-only server: nothing to pick
        assert!(pick_opcua_endpoint(&server[..1], "opc.tcp://10.0.0.5:4840").is_none());
        assert_eq!(split_opc_url("opc.tcp://h:1"), Some(("opc.tcp://h:1", "")));
    }

    #[test]
    fn alert_merge_override_disable_and_table_only() {
        let schema = vec![rule("voltage", "critical", 3, ">", 250.0), rule("voltage", "mild", 2, ">", 240.0)];
        let ov = vec![
            AlertOverride { field_key: "voltage".into(), alert_id: "critical".into(), alert_name: "critical".into(), severity: 3,
                            op: None, threshold: Some(260.0), enabled: true },
            AlertOverride { field_key: "voltage".into(), alert_id: "mild".into(), alert_name: "mild".into(), severity: 2,
                            op: None, threshold: None, enabled: false },
            AlertOverride { field_key: "current".into(), alert_id: "info".into(), alert_name: "info".into(), severity: 1,
                            op: Some("<".into()), threshold: Some(1.0), enabled: true },
        ];
        let merged = merge_alert_rules(schema, ov);
        assert_eq!(merged.len(), 2);
        assert_eq!(merged[0], rule("voltage", "critical", 3, ">", 260.0)); // threshold overridden, op inherited
        assert_eq!(merged[1].field_key, "current"); // table-only rule; mild disabled
    }

    #[test]
    fn alert_state_changes_only_on_transition_and_worst_wins() {
        let rules = vec![rule("voltage", "critical", 3, ">", 250.0), rule("voltage", "mild", 2, ">", 240.0)];
        let mut st: HashMap<(String, String), Option<String>> = HashMap::new();
        let ids = |c: &Vec<AlertChange>| c.iter().map(|x| x.to.as_ref().map(|r| r.alert_id.clone())).collect::<Vec<_>>();

        // First reading: normal -> nothing tracked yet, None == None => no change.
        assert!(detect_alert_changes(&mut st, "t1", &rules, &reading(230.0)).is_empty());
        let c = detect_alert_changes(&mut st, "t1", &rules, &reading(245.0));
        assert_eq!(ids(&c), vec![Some("mild".into())]);
        assert!(detect_alert_changes(&mut st, "t1", &rules, &reading(246.0)).is_empty()); // same state
        let c = detect_alert_changes(&mut st, "t1", &rules, &reading(255.0));
        assert_eq!(ids(&c), vec![Some("critical".into())]); // both match -> worst only
        assert_eq!(c[0].from_alert_id.as_deref(), Some("mild"));
        let c = detect_alert_changes(&mut st, "t1", &rules, &reading(243.0));
        assert_eq!(ids(&c), vec![Some("mild".into())]);
        let c = detect_alert_changes(&mut st, "t1", &rules, &reading(235.0));
        assert_eq!(ids(&c), vec![None]); // cleared
        assert_eq!(c[0].value, 235.0);
    }

    #[test]
    fn alert_state_skips_missing_values_and_seeded_state() {
        let rules = vec![rule("voltage", "critical", 3, ">", 250.0)];
        let mut st: HashMap<(String, String), Option<String>> = HashMap::new();
        // Seeded from app_alert_state: already critical -> a critical reading is not a change.
        st.insert(("t1".into(), "voltage".into()), Some("critical".into()));
        assert!(detect_alert_changes(&mut st, "t1", &rules, &reading(255.0)).is_empty());
        // No numeric value this read -> state untouched.
        let mut m = FieldMap::new();
        m.insert("voltage".into(), FieldValue::Text("n/a".into()));
        assert!(detect_alert_changes(&mut st, "t1", &rules, &m).is_empty());
        assert!(detect_alert_changes(&mut st, "t1", &rules, &FieldMap::new()).is_empty());
        // Other operators.
        let low = vec![rule("voltage", "critical", 3, "<", 200.0)];
        let mut st2 = HashMap::new();
        assert_eq!(detect_alert_changes(&mut st2, "t1", &low, &reading(190.0)).len(), 1);
    }

    // --- pg_escape_literal ---

    #[test]
    fn escape_plain_string() {
        assert_eq!(pg_escape_literal("hello"), "'hello'");
    }

    #[test]
    fn escape_empty_string() {
        assert_eq!(pg_escape_literal(""), "''");
    }

    #[test]
    fn escape_single_quote_doubled() {
        assert_eq!(pg_escape_literal("it's"), "'it''s'");
        assert_eq!(pg_escape_literal("''"), "''''''");
    }

    #[test]
    fn escape_nul_byte_stripped() {
        // Postgres rejects NUL in text — must be stripped, not passed through
        assert_eq!(pg_escape_literal("ab\0cd"), "'abcd'");
        assert_eq!(pg_escape_literal("\0"), "''");
    }

    #[test]
    fn escape_backslash_uses_escape_form() {
        assert_eq!(pg_escape_literal("a\\b"), "E'a\\\\b'");
    }

    #[test]
    fn escape_newline_tab_cr() {
        assert_eq!(pg_escape_literal("a\nb"), "E'a\\nb'");
        assert_eq!(pg_escape_literal("a\tb"), "E'a\\tb'");
        assert_eq!(pg_escape_literal("a\rb"), "E'a\\rb'");
    }

    #[test]
    fn escape_other_control_chars_hex() {
        assert_eq!(pg_escape_literal("a\x01b"), "E'a\\x01b'");
        assert_eq!(pg_escape_literal("a\x7fb"), "E'a\\x7fb'");
    }

    #[test]
    fn escape_mixed_quote_nul_control() {
        // quote doubling + NUL strip + control escape in one value
        assert_eq!(pg_escape_literal("o'\0k\n"), "E'o''k\\n'");
    }

    #[test]
    fn escape_unicode_passthrough() {
        assert_eq!(pg_escape_literal("température °C"), "'température °C'");
    }

    // --- to_sql_literal: f32 vs f64 formatting, non-finite -> NULL ---

    #[test]
    fn sql_literal_f32_shortest_roundtrip() {
        // The H-RUST-2 case: f32 229.4 widened to f64 prints 229.39999389648438;
        // Float32 must print the shortest f32 roundtrip instead.
        assert_eq!(FieldValue::Float32(229.4_f32).to_sql_literal(), "229.4");
        assert_eq!(FieldValue::Float32(0.1_f32).to_sql_literal(), "0.1");
        // Same value via the old widening path shows the phantom digits
        assert_eq!(FieldValue::Float(229.4_f32 as f64).to_sql_literal(), "229.39999389648438");
    }

    #[test]
    fn sql_literal_f64_untouched() {
        assert_eq!(FieldValue::Float(0.1).to_sql_literal(), "0.1");
        assert_eq!(FieldValue::Float(1234.5678).to_sql_literal(), "1234.5678");
        assert_eq!(FieldValue::Float(-3.0).to_sql_literal(), "-3");
    }

    #[test]
    fn sql_literal_nonfinite_is_null() {
        // DP4: NaN AND +/-Infinity all become SQL NULL — no more
        // Infinity-in-DB vs NaN->NULL asymmetry.
        assert_eq!(FieldValue::Float(f64::NAN).to_sql_literal(), "NULL");
        assert_eq!(FieldValue::Float(f64::INFINITY).to_sql_literal(), "NULL");
        assert_eq!(FieldValue::Float(f64::NEG_INFINITY).to_sql_literal(), "NULL");
        assert_eq!(FieldValue::Float32(f32::NAN).to_sql_literal(), "NULL");
        assert_eq!(FieldValue::Float32(f32::INFINITY).to_sql_literal(), "NULL");
        assert_eq!(FieldValue::Float32(f32::NEG_INFINITY).to_sql_literal(), "NULL");
    }

    #[test]
    fn sql_literal_int_bool_text() {
        assert_eq!(FieldValue::Int(-42).to_sql_literal(), "-42");
        assert_eq!(FieldValue::Bool(true).to_sql_literal(), "TRUE");
        assert_eq!(FieldValue::Bool(false).to_sql_literal(), "FALSE");
        assert_eq!(FieldValue::Text("a'b\0".to_string()).to_sql_literal(), "'a''b'");
    }

    #[test]
    fn field_value_as_f64() {
        assert_eq!(FieldValue::Float32(1.5).as_f64(), Some(1.5));
        assert_eq!(FieldValue::Float(2.5).as_f64(), Some(2.5));
        assert_eq!(FieldValue::Int(3).as_f64(), Some(3.0));
        assert_eq!(FieldValue::Bool(true).as_f64(), Some(1.0));
        assert_eq!(FieldValue::Text("x".into()).as_f64(), None);
    }

    // --- parse_modbus_address: register class parsing ---

    #[test]
    fn modbus_addr_holding_5digit() {
        assert_eq!(parse_modbus_address("40001"), Some((RegisterType::HoldingRegister, 0, None)));
        assert_eq!(parse_modbus_address("49999"), Some((RegisterType::HoldingRegister, 9998, None)));
    }

    #[test]
    fn modbus_addr_input_5digit() {
        assert_eq!(parse_modbus_address("30001"), Some((RegisterType::InputRegister, 0, None)));
        assert_eq!(parse_modbus_address("30100"), Some((RegisterType::InputRegister, 99, None)));
    }

    #[test]
    fn modbus_addr_discrete_5digit() {
        assert_eq!(parse_modbus_address("10001"), Some((RegisterType::DiscreteInput, 0, None)));
        assert_eq!(parse_modbus_address("19999"), Some((RegisterType::DiscreteInput, 9998, None)));
    }

    #[test]
    fn modbus_addr_coil_5digit_leading_zero() {
        assert_eq!(parse_modbus_address("00001"), Some((RegisterType::Coil, 0, None)));
        assert_eq!(parse_modbus_address("00010"), Some((RegisterType::Coil, 9, None)));
    }

    #[test]
    fn modbus_addr_extended_6digit() {
        assert_eq!(parse_modbus_address("400001"), Some((RegisterType::HoldingRegister, 0, None)));
        assert_eq!(parse_modbus_address("465535"), Some((RegisterType::HoldingRegister, 65534, None)));
        assert_eq!(parse_modbus_address("300001"), Some((RegisterType::InputRegister, 0, None)));
        assert_eq!(parse_modbus_address("100001"), Some((RegisterType::DiscreteInput, 0, None)));
        assert_eq!(parse_modbus_address("000001"), Some((RegisterType::Coil, 0, None)));
    }

    #[test]
    fn modbus_addr_raw_numeric_is_holding() {
        assert_eq!(parse_modbus_address("0"), Some((RegisterType::HoldingRegister, 0, None)));
        assert_eq!(parse_modbus_address("100"), Some((RegisterType::HoldingRegister, 100, None)));
        assert_eq!(parse_modbus_address("65535"), Some((RegisterType::HoldingRegister, 65535, None)));
    }

    #[test]
    fn modbus_addr_invalid() {
        assert_eq!(parse_modbus_address(""), None);
        assert_eq!(parse_modbus_address("  "), None);
        assert_eq!(parse_modbus_address("abc"), None);
        assert_eq!(parse_modbus_address("-1"), None);
        assert_eq!(parse_modbus_address("99999"), None); // 5-digit, no class
        assert_eq!(parse_modbus_address("700000"), None);
    }

    #[test]
    fn modbus_addr_whitespace_trimmed() {
        assert_eq!(parse_modbus_address(" 40001 "), Some((RegisterType::HoldingRegister, 0, None)));
    }

    #[test]
    fn modbus_addr_bit_suffix() {
        // "<reg>,<bit>" → holding/extended register + a single bit 0-15
        assert_eq!(parse_modbus_address("40101,0"), Some((RegisterType::HoldingRegister, 100, Some(0))));
        assert_eq!(parse_modbus_address("40101,15"), Some((RegisterType::HoldingRegister, 100, Some(15))));
        assert_eq!(parse_modbus_address("100,3"), Some((RegisterType::HoldingRegister, 100, Some(3))));
        assert_eq!(parse_modbus_address("40101,16"), None); // bit out of range (0-15)
        assert_eq!(parse_modbus_address("40101,x"), None); // malformed bit
    }

    #[test]
    fn modbus_addr_delta_d_register() {
        // Delta D-register: D_N → holding 0x1000 + N, with optional bit
        assert_eq!(parse_modbus_address("D0"), Some((RegisterType::HoldingRegister, 0x1000, None)));
        assert_eq!(parse_modbus_address("D100"), Some((RegisterType::HoldingRegister, 0x1000 + 100, None)));
        assert_eq!(parse_modbus_address("D200,3"), Some((RegisterType::HoldingRegister, 0x1000 + 200, Some(3))));
    }

    // --- derived-field evaluation: non-finite -> NULL-marker, chains ---

    fn derived(key: &str, formula: &str, order: i32) -> DerivedField {
        DerivedField {
            field_key: key.to_string(),
            formula_str: formula.to_string(),
            eval_order: order,
        }
    }

    fn is_null_marker(v: Option<&FieldValue>) -> bool {
        matches!(v, Some(FieldValue::Float(f)) if f.is_nan())
    }

    #[test]
    fn derived_eval_happy_path() {
        let mut values: FieldMap = HashMap::new();
        values.insert("a".into(), FieldValue::Float(3.0));
        values.insert("b".into(), FieldValue::Float(4.0));
        let dfs = vec![derived("c", "sqrt(a^2 + b^2)", 0)];
        eval_derived_fields("tjob", "ttab", &dfs, &mut values, None);
        match values.get("c") {
            Some(FieldValue::Float(v)) => assert!((v - 5.0).abs() < 1e-12),
            other => panic!("expected Float(5.0), got {:?}", other),
        }
    }

    #[test]
    fn derived_eval_uses_device_nominal_voltage() {
        // 415 V nominal, measuring 420 V L-L -> +1.2% deviation.
        let mut values: FieldMap = HashMap::new();
        values.insert("voltage_avg".into(), FieldValue::Float(420.0));
        let dfs = vec![derived(
            "kpi_voltage_deviation_pct",
            "(voltage_avg - dev_nominal_voltage) / dev_nominal_voltage * 100",
            0,
        )];
        eval_derived_fields("tjob", "ttab_nom", &dfs, &mut values, Some(415.0));
        match values.get("kpi_voltage_deviation_pct") {
            Some(FieldValue::Float(v)) => assert!((v - 100.0 * 5.0 / 415.0).abs() < 1e-9, "got {}", v),
            other => panic!("expected a deviation, got {:?}", other),
        }
    }

    #[test]
    fn derived_eval_nominal_ln_is_ll_over_sqrt3() {
        let mut values: FieldMap = HashMap::new();
        values.insert("voltage_r_n".into(), FieldValue::Float(239.6));
        let dfs = vec![derived("ln_ref", "dev_nominal_voltage_ln", 0)];
        eval_derived_fields("tjob", "ttab_ln", &dfs, &mut values, Some(415.0));
        match values.get("ln_ref") {
            Some(FieldValue::Float(v)) => assert!((v - 415.0 / 3f64.sqrt()).abs() < 1e-9, "got {}", v),
            other => panic!("expected the L-N nominal, got {:?}", other),
        }
    }

    #[test]
    fn derived_eval_without_nominal_voltage_is_null_not_wrong() {
        // A device with no rating must NOT silently produce a number.
        let mut values: FieldMap = HashMap::new();
        values.insert("voltage_avg".into(), FieldValue::Float(420.0));
        let dfs = vec![derived(
            "kpi_voltage_deviation_pct",
            "(voltage_avg - dev_nominal_voltage) / dev_nominal_voltage * 100",
            0,
        )];
        eval_derived_fields("tjob", "ttab_nonom", &dfs, &mut values, None);
        assert!(is_null_marker(values.get("kpi_voltage_deviation_pct")));
    }

    #[test]
    fn derived_eval_rejects_zero_nominal_voltage() {
        // 0 would divide by zero and yield inf; it must be treated as "unset".
        let mut values: FieldMap = HashMap::new();
        values.insert("voltage_avg".into(), FieldValue::Float(420.0));
        let dfs = vec![derived("d", "(voltage_avg - dev_nominal_voltage) / dev_nominal_voltage * 100", 0)];
        eval_derived_fields("tjob", "ttab_zero", &dfs, &mut values, Some(0.0));
        assert!(is_null_marker(values.get("d")));
    }

    #[test]
    fn derived_eval_error_becomes_null_marker() {
        let mut values: FieldMap = HashMap::new();
        values.insert("a".into(), FieldValue::Float(1.0));
        let dfs = vec![derived("bad", "a + missing_var", 0)];
        eval_derived_fields("tjob", "ttab_err", &dfs, &mut values, None);
        assert!(is_null_marker(values.get("bad")));
        assert_eq!(values.get("bad").unwrap().to_sql_literal(), "NULL");
    }

    #[test]
    fn derived_eval_infinity_becomes_null_marker() {
        // DP4: 1/0 used to be written as 'Infinity' into Postgres
        let mut values: FieldMap = HashMap::new();
        values.insert("a".into(), FieldValue::Float(1.0));
        let dfs = vec![derived("inf_field", "a / 0", 0)];
        eval_derived_fields("tjob", "ttab_inf", &dfs, &mut values, None);
        assert!(is_null_marker(values.get("inf_field")));
        assert_eq!(values.get("inf_field").unwrap().to_sql_literal(), "NULL");
    }

    #[test]
    fn derived_eval_nan_becomes_null_marker() {
        let mut values: FieldMap = HashMap::new();
        values.insert("a".into(), FieldValue::Float(0.0));
        let dfs = vec![derived("nan_field", "a / 0", 0)]; // 0/0 = NaN
        eval_derived_fields("tjob", "ttab_nan", &dfs, &mut values, None);
        assert!(is_null_marker(values.get("nan_field")));
    }

    #[test]
    fn derived_eval_chain_in_order() {
        let mut values: FieldMap = HashMap::new();
        values.insert("x".into(), FieldValue::Float(2.0));
        let dfs = vec![derived("y", "x * 10", 0), derived("z", "y + 1", 1)];
        eval_derived_fields("tjob", "ttab_chain", &dfs, &mut values, None);
        match values.get("z") {
            Some(FieldValue::Float(v)) => assert!((v - 21.0).abs() < 1e-12),
            other => panic!("expected Float(21.0), got {:?}", other),
        }
    }

    #[test]
    fn derived_eval_nonfinite_not_fed_downstream() {
        // Consistent rule: a non-finite intermediate is NOT placed in the eval
        // context, so a downstream formula referencing it also fails to NULL
        // (instead of meval min/max absorbing the NaN into a real number).
        let mut values: FieldMap = HashMap::new();
        values.insert("a".into(), FieldValue::Float(0.0));
        let dfs = vec![
            derived("bad", "a / 0", 0),            // NaN
            derived("capped", "min(bad, 5)", 1),   // must NOT become 5
        ];
        eval_derived_fields("tjob", "ttab_cascade", &dfs, &mut values, None);
        assert!(is_null_marker(values.get("bad")));
        assert!(is_null_marker(values.get("capped")));
    }

    #[test]
    fn derived_sort_deterministic_eval_order_then_field_key() {
        // DP2 leftover: load_mapping_rows has ORDER BY field_key, and ties on
        // eval_order (duplicated orders from older API builds) must fall back
        // to field_key so evaluation order never depends on DB row order.
        let mut dfs = vec![
            derived("zeta", "1", 1),
            derived("beta", "1", 0),
            derived("alpha", "1", 1),
            derived("gamma", "1", 0),
            derived("omega", "1", -1),
        ];
        sort_derived_fields(&mut dfs);
        let got: Vec<(i32, &str)> = dfs.iter().map(|d| (d.eval_order, d.field_key.as_str())).collect();
        assert_eq!(
            got,
            vec![(-1, "omega"), (0, "beta"), (0, "gamma"), (1, "alpha"), (1, "zeta")]
        );
        // Re-sorting an already-sorted vec is a no-op (stable + total order)
        let before: Vec<String> = dfs.iter().map(|d| d.field_key.clone()).collect();
        sort_derived_fields(&mut dfs);
        let after: Vec<String> = dfs.iter().map(|d| d.field_key.clone()).collect();
        assert_eq!(before, after);
    }

    #[test]
    fn derived_eval_f32_origin_inputs_work() {
        let mut values: FieldMap = HashMap::new();
        values.insert("v".into(), FieldValue::Float32(229.4));
        let dfs = vec![derived("v2", "v * 2", 0)];
        eval_derived_fields("tjob", "ttab_f32", &dfs, &mut values, None);
        match values.get("v2") {
            Some(FieldValue::Float(v)) => assert!((v - 458.8).abs() < 0.01),
            other => panic!("expected Float(~458.8), got {:?}", other),
        }
    }

    // --- modbus encoding info + register decode sanity for f32 path ---

    #[test]
    fn encoding_info_f32_tags() {
        assert_eq!(modbus_encoding_info("float32"), (2, "f32"));
        assert_eq!(modbus_encoding_info("float"), (2, "f32"));
        assert_eq!(modbus_encoding_info("float64"), (4, "f64"));
        assert_eq!(modbus_encoding_info("uint16"), (1, "u16"));
    }

    #[test]
    fn decode_f32_value_widens_then_f32_roundtrips() {
        // 229.4f32 = 0x4365 6666 big-endian
        let bits = 229.4_f32.to_bits();
        let regs = [(bits >> 16) as u16, (bits & 0xFFFF) as u16];
        let decoded = decode_registers(&regs, "float32", "ABCD").unwrap();
        // Widened f64 is NOT exactly 229.4 ...
        assert!(decoded != 229.4_f64);
        // ... but the Float32 representation prints cleanly
        assert_eq!(FieldValue::Float32(decoded as f32).to_sql_literal(), "229.4");
    }

    // --- rate limiter ---

    #[test]
    fn rate_limiter_first_logs_then_accumulates() {
        let key = "test:rate:limiter:unique-key-1";
        // First occurrence logs immediately
        assert_eq!(rate_limit_event(key, 1, Duration::from_secs(3600)), Some(1));
        // Subsequent occurrences within the interval are suppressed but counted
        assert_eq!(rate_limit_event(key, 1, Duration::from_secs(3600)), None);
        assert_eq!(rate_limit_event(key, 5, Duration::from_secs(3600)), None);
        // With a zero interval the accumulated count is released
        assert_eq!(rate_limit_event(key, 1, Duration::from_millis(0)), Some(7));
    }

    // --- backoff helper ---

    #[test]
    fn meta_backoff_caps_at_30s() {
        assert_eq!(meta_backoff(2000, 1), Duration::from_millis(2000));
        assert_eq!(meta_backoff(2000, 2), Duration::from_millis(4000));
        assert_eq!(meta_backoff(2000, 5), Duration::from_millis(30_000));
        assert_eq!(meta_backoff(2000, 60), Duration::from_millis(30_000)); // no overflow
        assert_eq!(meta_backoff(0, 1), Duration::from_millis(250)); // floor
    }

    // --- quote_ident ---

    #[test]
    fn quote_ident_doubles_embedded_quotes() {
        assert_eq!(quote_ident("plain"), "\"plain\"");
        assert_eq!(quote_ident("we\"ird"), "\"we\"\"ird\"");
    }

    // --- redact_dsn ---

    #[test]
    fn redact_dsn_masks_passwords_only() {
        assert_eq!(
            redact_dsn("postgresql://user:topsecret@dbhost:5432/mydb"),
            "postgresql://user:***@dbhost:5432/mydb"
        );
        // No password -> unchanged (host:port colon must not be masked)
        assert_eq!(
            redact_dsn("postgresql://postgres@localhost/meta"),
            "postgresql://postgres@localhost/meta"
        );
        // Keyword form
        assert_eq!(
            redact_dsn("host=localhost password=hunter2 dbname=x"),
            "host=localhost password=*** dbname=x"
        );
        assert_eq!(
            redact_dsn("host=localhost password=endofstring"),
            "host=localhost password=***"
        );
        // Garbage passes through
        assert_eq!(redact_dsn("not a dsn"), "not a dsn");
    }
}

/// Only referenced by the Windows DPAPI path (dpapi_unprotect); cfg-gated so
/// Linux builds emit no dead-code warning (M-RUST-3).
#[cfg(target_os = "windows")]
fn env_truthy(name: &str) -> bool {
    matches!(env::var(name).ok().as_deref(), Some("1") | Some("true") | Some("True"))
}
