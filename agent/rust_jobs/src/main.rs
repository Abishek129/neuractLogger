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
use chrono::Utc;
use log::{error, info, warn};
use opcua::client::prelude::*;
use opcua::sync::RwLock;
use opcua::types::Variant;
use tokio_postgres::{Client as PgClient, NoTls};
use tokio_postgres::types::ToSql;
use windows::Win32::Foundation::{HLOCAL, LocalFree};
use windows::Win32::Security::Cryptography::{
    CryptUnprotectData, CRYPTPROTECT_LOCAL_MACHINE, CRYPT_INTEGER_BLOB,
};
use sysinfo::{Pid, System};

const DEFAULT_OPCUA_ENDPOINT: &str = "opc.tcp://127.0.0.1:4840/freeopcua/server/";
const BENCH_METRICS_FILENAME: &str = "bench_metrics_rust.csv";

#[derive(Clone, Debug)]
struct JobDef {
    id: String,
    name: String,
    job_type: JobType,
    interval_ms: u64,
    tables: Vec<String>,
    triggers: Vec<Trigger>,
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

struct TableRuntime {
    table: TableDef,
    target_client: Arc<PgClient>,
    mapping: Vec<MappingRow>,
    device: Device,
}

static BENCH_CSV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

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
        if let Some(c) = self.clients.lock().unwrap().get(conn) {
            return Ok(c.clone());
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
}

impl ProcSampler {
    fn new() -> Self {
        let mut system = System::new();
        let pid = Pid::from_u32(std::process::id());
        system.refresh_process(pid);
        Self { system, pid }
    }

    fn sample(&mut self, window_secs: f64) -> (Option<f64>, Option<f64>, Option<f64>) {
        self.system.refresh_process(self.pid);
        let proc = match self.system.process(self.pid) {
            Some(p) => p,
            None => return (None, None, None),
        };
        let cpu_pct = proc.cpu_usage() as f64;
        let cpu_time_ms = if window_secs > 0.0 {
            (cpu_pct / 100.0) * window_secs * 1000.0
        } else {
            0.0
        };
        let rss_mb = proc.memory() as f64 / 1024.0;
        (Some(cpu_time_ms), Some(cpu_pct), Some(rss_mb))
    }
}

struct JobHandle {
    stop: Arc<AtomicBool>,
    join: std::thread::JoinHandle<()>,
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let app_db_url = env::var("APP_DB_URL").context("APP_DB_URL is required")?;
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
                if let Err(e) = rt.block_on(run_job(job_clone, meta, dm, stop_thread)) {
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
    let mut last_values: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut last_report = Instant::now();
    let mut win_reads_ok: u64 = 0;
    let mut win_reads_err: u64 = 0;
    let mut win_writes_ok: u64 = 0;
    let mut win_writes_err: u64 = 0;
    let mut win_read_ms_sum = 0.0f64;
    let mut win_write_ms_sum = 0.0f64;
    let mut win_loops: u64 = 0;
    let mut win_overruns: u64 = 0;
    let mut loop_samples_ms: Vec<f64> = Vec::with_capacity(256);
    let mut proc_sampler = ProcSampler::new();
    info!("job {} started type={:?} interval_ms={}", job.id, job.job_type, job.interval_ms);

    loop {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        let start = Instant::now();
        match job.job_type {
            JobType::Continuous => {
                for table_rt in table_runtimes.values() {
                    let t_read = Instant::now();
                    let values = match read_table_values_cached(table_rt, &device_manager).await {
                        Ok(v) => {
                            win_reads_ok += 1;
                            win_read_ms_sum += t_read.elapsed().as_secs_f64() * 1000.0;
                            v
                        }
                        Err(e) => {
                            win_reads_err += 1;
                            warn!("job {} table {} read failed: {}", job.id, table_rt.table.id, e);
                            continue;
                        }
                    };
                    let t_write = Instant::now();
                    match write_values_cached(table_rt, &values).await {
                        Ok(()) => {
                            win_writes_ok += 1;
                            win_write_ms_sum += t_write.elapsed().as_secs_f64() * 1000.0;
                        }
                        Err(e) => {
                            win_writes_err += 1;
                            warn!("job {} table {} write failed: {}", job.id, table_rt.table.id, e);
                        }
                    }
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
                    let values = match read_table_values_cached(table_rt, &device_manager).await {
                        Ok(v) => {
                            win_reads_ok += 1;
                            win_read_ms_sum += t_read.elapsed().as_secs_f64() * 1000.0;
                            v
                        }
                        Err(e) => {
                            win_reads_err += 1;
                            warn!("job {} table {} read failed: {}", job.id, table_id, e);
                            continue;
                        }
                    };
                    let should_fire = eval_triggers(&triggers, table_id.as_str(), &values, &mut last_values);
                    if should_fire {
                        let t_write = Instant::now();
                        match write_values_cached(table_rt, &values).await {
                            Ok(()) => {
                                win_writes_ok += 1;
                                win_write_ms_sum += t_write.elapsed().as_secs_f64() * 1000.0;
                            }
                            Err(e) => {
                                win_writes_err += 1;
                                warn!("job {} trigger write failed table {}: {}", job.id, table_id, e);
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
            let p95 = percentile_ms(&mut loop_samples_ms, 95.0);
            let overrun_pct = if win_loops > 0 { (win_overruns as f64 / win_loops as f64) * 100.0 } else { 0.0 };
            let p95_txt = p95.map(|v| format!("{:.2}", v)).unwrap_or_else(|| "na".to_string());
            let (cpu_time_ms, proc_cpu_pct, proc_rss_mb) = proc_sampler.sample(window_secs);
            info!(
                "Job {} bench window={:.1}s reads/s={:.1} writes/s={:.1} read_avg_ms={:.3} write_avg_ms={:.3} loop_p95_ms={} overrun_pct={:.1} read_err={} write_err={}",
                job.id,
                window_secs,
                reads_per_sec,
                writes_per_sec,
                read_avg_ms,
                write_avg_ms,
                p95_txt,
                overrun_pct,
                win_reads_err,
                win_writes_err,
            );
            if let Err(e) = append_bench_csv(
                &job.id,
                window_secs,
                reads_per_sec,
                writes_per_sec,
                read_avg_ms,
                write_avg_ms,
                p95,
                overrun_pct,
                cpu_time_ms,
                proc_cpu_pct,
                proc_rss_mb,
                win_reads_err,
                win_writes_err,
            ) {
                warn!("job {} bench csv write failed: {}", job.id, e);
            }
            last_report = Instant::now();
            win_reads_ok = 0;
            win_reads_err = 0;
            win_writes_ok = 0;
            win_writes_err = 0;
            win_read_ms_sum = 0.0;
            win_write_ms_sum = 0.0;
            win_loops = 0;
            win_overruns = 0;
            loop_samples_ms.clear();
        }
        let sleep = if elapsed >= interval { Duration::from_millis(0) } else { interval - elapsed };
        tokio::time::sleep(sleep).await;
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
    Ok(Some(TableRuntime {
        table,
        target_client,
        mapping,
        device,
    }))
}

async fn read_table_values_cached(
    table_rt: &TableRuntime,
    device_manager: &Arc<DeviceManager>,
) -> Result<HashMap<String, String>> {
    if table_rt.device.protocol.to_lowercase() != "opcua" {
        return Err(anyhow!("device protocol not supported: {}", table_rt.device.protocol));
    }
    read_opcua_values_blocking(
        device_manager.clone(),
        table_rt.device.clone(),
        table_rt.mapping.clone(),
    )
    .await
}

async fn write_values_cached(
    table_rt: &TableRuntime,
    values: &HashMap<String, String>,
) -> Result<()> {
    if values.is_empty() {
        return Ok(());
    }
    let mut cols = Vec::new();
    let mut params: Vec<Box<dyn ToSql + Sync + Send>> = Vec::new();
    cols.push(quote_ident("timestamp_utc"));
    params.push(Box::new(Utc::now().to_rfc3339()));
    for (k, v) in values {
        cols.push(quote_ident(k));
        let dtype = table_rt
            .mapping
            .iter()
            .find(|m| m.field_key == *k)
            .map(|m| m.data_type.as_str());
        params.push(parse_param_value_for_type(v, dtype));
    }
    let placeholders: Vec<String> = (1..=cols.len()).map(|i| format!("${}", i)).collect();
    let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table_rt.table.name));
    let sql = format!("INSERT INTO {} ({}) VALUES ({})", table_name, cols.join(","), placeholders.join(","));
    let params_ref: Vec<&(dyn ToSql + Sync)> =
        params.iter().map(|p| p.as_ref() as &(dyn ToSql + Sync)).collect();
    table_rt.target_client.execute(sql.as_str(), &params_ref).await?;
    Ok(())
}

fn bench_log_dir() -> PathBuf {
    if let Ok(p) = env::var("RUST_BENCH_LOG_DIR") {
        return PathBuf::from(p);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("logs")
}

fn bench_csv_lock() -> &'static Mutex<()> {
    BENCH_CSV_LOCK.get_or_init(|| Mutex::new(()))
}

fn append_bench_csv(
    job_id: &str,
    window_secs: f64,
    reads_per_sec: f64,
    writes_per_sec: f64,
    read_avg_ms: f64,
    write_avg_ms: f64,
    loop_p95_ms: Option<f64>,
    overrun_pct: f64,
    cpu_time_ms: Option<f64>,
    proc_cpu_pct: Option<f64>,
    proc_rss_mb: Option<f64>,
    read_err: u64,
    write_err: u64,
) -> Result<()> {
    let log_dir = bench_log_dir();
    fs::create_dir_all(&log_dir).context("create rust bench log dir")?;
    let path = log_dir.join(BENCH_METRICS_FILENAME);
    let _guard = bench_csv_lock().lock().unwrap();
    let needs_header = match fs::metadata(&path) {
        Ok(meta) => meta.len() == 0,
        Err(_) => true,
    };
    let mut file = OpenOptions::new().create(true).append(true).open(&path)?;
    if needs_header {
        writeln!(
            file,
            "ts_utc,job_id,window_secs,reads_per_sec,writes_per_sec,read_avg_ms,write_avg_ms,loop_p95_ms,overrun_pct,cpu_time_ms,proc_cpu_pct,proc_rss_mb,read_err,write_err"
        )?;
    }
    let ts = Utc::now().to_rfc3339();
    let loop_p95_txt = loop_p95_ms.map(|v| format!("{:.3}", v)).unwrap_or_else(|| "na".to_string());
    let cpu_time_txt = format_opt(cpu_time_ms);
    let proc_cpu_txt = format_opt(proc_cpu_pct);
    let proc_rss_txt = format_opt(proc_rss_mb);
    writeln!(
        file,
        "{},{},{:.3},{:.3},{:.3},{:.3},{:.3},{},{:.3},{},{},{},{},{}",
        ts,
        job_id,
        window_secs,
        reads_per_sec,
        writes_per_sec,
        read_avg_ms,
        write_avg_ms,
        loop_p95_txt,
        overrun_pct,
        cpu_time_txt,
        proc_cpu_txt,
        proc_rss_txt,
        read_err,
        write_err,
    )?;
    Ok(())
}

fn format_opt(val: Option<f64>) -> String {
    val.map(|v| format!("{:.3}", v)).unwrap_or_else(|| "na".to_string())
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
) -> Result<HashMap<String, String>> {
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
    if device.protocol.to_lowercase() != "opcua" {
        return Err(anyhow!("device protocol not supported: {}", device.protocol));
    }
    read_opcua_values_blocking(device_manager.clone(), device, mapping).await
}

async fn write_values(
    table: &TableDef,
    default_target: &Option<String>,
    meta_client: &PgClient,
    target_manager: &Arc<TargetManager>,
    values: &HashMap<String, String>,
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
    let mut params: Vec<Box<dyn ToSql + Sync + Send>> = Vec::new();
    cols.push(quote_ident("timestamp_utc"));
    params.push(Box::new(Utc::now().to_rfc3339()));
    for (k, v) in values {
        cols.push(quote_ident(k));
        params.push(parse_param_value(v));
    }
    let placeholders: Vec<String> = (1..=cols.len()).map(|i| format!("${}", i)).collect();
    let table_name = format!("{}.{}", quote_ident("neuract"), quote_ident(&table.name));
    let sql = format!("INSERT INTO {} ({}) VALUES ({})", table_name, cols.join(","), placeholders.join(","));
    let params_ref: Vec<&(dyn ToSql + Sync)> =
        params.iter().map(|p| p.as_ref() as &(dyn ToSql + Sync)).collect();
    target_client.execute(sql.as_str(), &params_ref).await?;
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
    values: &HashMap<String, String>,
    last_values: &mut HashMap<String, HashMap<String, String>>,
) -> bool {
    let last = last_values.entry(table_id.to_string()).or_insert_with(HashMap::new);
    for tr in triggers {
        let cur = values.get(&tr.field_key).and_then(|v| v.parse::<f64>().ok());
        let prev = last.get(&tr.field_key).and_then(|v| v.parse::<f64>().ok());
        if eval_op(cur, prev, &tr.op, tr.value, tr.deadband) {
            return true;
        }
    }
    false
}

fn update_last_values(table_id: &str, values: &HashMap<String, String>, last_values: &mut HashMap<String, HashMap<String, String>>) {
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
            "SELECT id,name,type,tables_json,interval_ms::text AS interval_ms_text,enabled,status,triggers_json FROM app_jobs WHERE status='running'",
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
        out.push(JobDef {
            id: job_id,
            name,
            job_type: parse_job_type(&jtype),
            interval_ms: interval_ms.max(100) as u64,
            tables,
            triggers,
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
            "SELECT id,protocol,params_json FROM app_devices WHERE id=$1",
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

fn read_opcua_value(session: &Arc<Mutex<DeviceSession>>, row: &MappingRow) -> Result<Option<String>> {
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
    let mut val = dv.value.as_ref().and_then(variant_to_string);
    if let (Some(v), Some(scale)) = (val.as_ref(), row.scale) {
        if let Ok(n) = v.parse::<f64>() {
            val = Some((n * scale).to_string());
        }
    }
    sess.last_used = Instant::now();
    Ok(val)
}

async fn read_opcua_values_blocking(
    device_manager: Arc<DeviceManager>,
    device: Device,
    mapping: Vec<MappingRow>,
) -> Result<HashMap<String, String>> {
    tokio::task::spawn_blocking(move || {
        let session = device_manager.get_session(&device)?;
        let mut values = HashMap::new();
        for row in mapping {
            if row.protocol.to_lowercase() != "opcua" {
                continue;
            }
            let value = read_opcua_value(&session, &row)?;
            if let Some(v) = value {
                values.insert(row.field_key, v);
            }
        }
        Ok(values)
    })
    .await
    .context("opcua blocking task failed")?
}

fn variant_to_string(v: &Variant) -> Option<String> {
    match v {
        Variant::Boolean(b) => Some(b.to_string()),
        Variant::Byte(b) => Some((*b as i64).to_string()),
        Variant::SByte(b) => Some((*b as i64).to_string()),
        Variant::Int16(b) => Some((*b as i64).to_string()),
        Variant::UInt16(b) => Some((*b as i64).to_string()),
        Variant::Int32(b) => Some((*b as i64).to_string()),
        Variant::UInt32(b) => Some((*b as i64).to_string()),
        Variant::Int64(b) => Some((*b as i64).to_string()),
        Variant::UInt64(b) => Some((*b as i64).to_string()),
        Variant::Float(b) => Some((*b as f64).to_string()),
        Variant::Double(b) => Some(b.to_string()),
        Variant::String(s) => {
            if s.is_null() {
                None
            } else {
                Some(s.as_ref().to_string())
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
