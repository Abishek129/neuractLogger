# Getting Started

This project has two backend services that work together:

1. **FastAPI (Python)** - HTTP API for configuration (schemas, tables, devices, mappings, jobs)
2. **Rust Job Runner** - High-performance data acquisition engine that reads devices and writes to databases

```
┌─────────────┐     polls job status     ┌──────────────────┐
│  Frontend   │ ──── HTTP API ─────────> │  FastAPI (Python) │
└─────────────┘                          │  Port 8003        │
                                         └────────┬─────────┘
                                                  │ writes to
                                                  v
                                         ┌──────────────────┐
                                         │  PostgreSQL       │
                                         │  (metadata DB)    │
                                         └────────┬─────────┘
                                                  │ reads from
                                                  v
                                         ┌──────────────────┐
                                         │  Rust Job Runner  │
                                         │  (neuract-job-    │
                                         │   runner)         │
                                         └──────────────────┘
                                                  │
                                    reads devices │ writes data
                                         ┌────────┴─────────┐
                                         │  Modbus / OPC UA  │
                                         │  / MQTT Devices   │
                                         └──────────────────┘
```

## Prerequisites

- **Python** >= 3.9 (tested with 3.11, 3.12)
- **Rust** (stable toolchain)
- **PostgreSQL** (metadata DB + target DB)
- **Redis** (for WebSocket notification broadcasting)

## 1. PostgreSQL Setup

Create the metadata database:

```bash
createdb meta_data_version1
```

The application tables (`app_jobs`, `app_devices`, `app_device_tables`, `app_schemas`, `app_db_targets`, `app_gateways`, `app_meta`) are created automatically by the FastAPI app on startup.

Create a target database for logged data (optional, can use same DB):

```bash
createdb target_version1
```

The `neuract` schema and data tables are created via the `/tables/migrate` API endpoint.

## 2. Environment Variables

All config lives in `agent/.env`:

```env
# Required
APP_DB_URL=postgresql://postgres@localhost/meta_data_version1

# Optional
AGENT_PORT=8003
AGENT_HOST=0.0.0.0
REDIS_URL=redis://127.0.0.1:6379/3
META_BREAKPOINT_DB_URL=postgresql://postgres@localhost/meta_data_break_point

# Keycloak (if auth is enabled)
KC_URL=http://localhost:8080/keycloak
KC_REALM=desktop
KC_ALLOWED_ISSUERS=http://localhost:8080/keycloak/realms/desktop
KC_ADMIN_CLIENT_ID=neuract_owner
KC_ADMIN_CLIENT_SECRET=<your-secret>

# CORS (recommended for production). Comma-separated EXACT origins.
# When set, only these origins are allowed and the permissive dev default
# (any localhost/LAN/Tailscale origin plus app:// and tauri:// schemes) is
# disabled. When unset, the dev allowlist is kept for compatibility.
LOGGER_CORS_ORIGINS=http://localhost:5173,https://tauri.localhost

# Optional: restrict accepted JWTs to specific Keycloak client IDs (azp/aud)
# KC_REQUIRED_AZP=neuract-logger-ui
```

## 3. Start FastAPI

```bash
cd agent

# Install dependencies
pip install -r ../requirements.txt

# Start the API server
uvicorn plc_agent.api.app:app --host 0.0.0.0 --port 8003
```

The API will be available at `http://localhost:8003`.

### Verify

```bash
curl http://localhost:8003/health
# {"status":"ok","version":"..."}
```

### Key API Routes

| Route Prefix | Description |
|-------------|-------------|
| `/schemas` | Schema definitions (field types, formulas) |
| `/tables` | Table management and DDL migration |
| `/mappings` | Device-to-field mapping configuration |
| `/jobs2` | Job lifecycle (create, start, stop, dry_run) |
| `/auth` | Authentication and notifications |

## 4. Start Rust Job Runner

The Rust job runner is a separate binary that polls the metadata DB for jobs with `status='running'` and executes them.

```bash
cd agent/rust_jobs

# Build (first time takes a few minutes)
cargo build --release

# Run
APP_DB_URL="postgresql://postgres@localhost/meta_data_version1" \
BENCH_DB_URL="postgresql://postgres@localhost/loggerfast_metrics" \
./target/release/neuract-job-runner
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `APP_DB_URL` | Yes | - | Metadata database connection string |
| `BENCH_DB_URL` | No | `postgresql://postgres@localhost/loggerfast_metrics` | Benchmark metrics database |
| `JOB_POLL_MS` | No | `2000` | How often to check for new/removed jobs (ms) |
| `JOB_BENCH_WINDOW_SEC` | No | `2.0` | Performance metrics reporting window |
| `MODBUS_MAX_IDLE_MS` | No | `30000` | Max idle time before Modbus reconnect |
| `RUST_LOG` | No | `info` | Log level (`debug`, `info`, `warn`, `error`) |

### Logs

Logs are written to `agent/rust_jobs/logs/`:

| File | Content |
|------|---------|
| `agent_rust.log` | Main application log (rotating, 500MB) |
| `mqtt_jobs.log` | MQTT-specific diagnostics |
| `error_log_rust.csv` | CSV of read/write errors |

### Verify

Once running, the job runner will log messages like:

```
Job job_xxx started type=Continuous interval_ms=1000 batching=off
Job job_xxx [READ_PHASE] groups=1 tables=1
Job job_xxx [READ] table=tbl_xxx fields=39 elapsed_ms=0.43
Job job_xxx [WRITE_ALL_BATCH] [DB_EXECUTE] tables=1 elapsed_ms=2.41
```

## 5. End-to-End Workflow

Once both services are running:

> **Authentication:** every mutating endpoint (`POST`/`PATCH`/`DELETE`) requires a
> Keycloak bearer token carrying the `logger_write` realm role. Obtain one via the
> password grant (`POST /auth/login` with `{"username": ..., "password": ...}`) and
> add `-H "Authorization: Bearer <access_token>"` to each curl below.

1. **Create a schema** with fields (and optionally derived fields with formulas):
   ```bash
   curl -X POST http://localhost:8003/schemas \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"name": "power_meter", "fields": [{"key": "voltage", "type": "float32"}, {"key": "current", "type": "float32"}]}'
   ```

2. **Create a database target** (where logged data is written) and make it the default:
   ```bash
   curl -X POST http://localhost:8003/storage/targets \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"provider": "postgres", "conn": "postgresql://postgres@localhost/target_version1"}'

   curl -X POST http://localhost:8003/storage/targets/default \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"id": "<target_id>"}'
   ```
   Without a Postgres target the tables fall back to a local SQLite file, which the
   Rust job runner cannot read (it supports Postgres targets only).

3. **Create a device** (Modbus/OPC UA/MQTT):
   ```bash
   curl -X POST http://localhost:8003/devices \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"name": "MFM-001", "protocol": "modbus", "params": {"host": "192.168.1.10"}, "port": 502, "unitId": 1}'
   ```

4. **Create a table** linked to the schema:
   ```bash
   curl -X POST http://localhost:8003/tables/bulk_create \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"schemaId": "<schema_id>", "names": ["mfm_001"], "dbTargetId": "<target_id>"}'
   ```

5. **Migrate the table** (creates physical table + derived mappings):
   ```bash
   curl -X POST http://localhost:8003/tables/migrate \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"ids": ["<table_id>"]}'
   ```

6. **Map fields** to device registers:
   ```bash
   curl -X POST http://localhost:8003/mappings/<table_id>/bulk_apply \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"deviceId": "<device_id>", "rows": {"voltage": {"protocol": "modbus", "address": "0", "encoding": "float32"}, "current": {"protocol": "modbus", "address": "2", "encoding": "float32"}}}'
   ```

7. **Create and start a job**:
   ```bash
   # Create
   curl -X POST http://localhost:8003/jobs2 \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"name": "power_logging", "type": "continuous", "tables": ["<table_id>"], "intervalMs": 1000}'

   # Start
   curl -X POST http://localhost:8003/jobs2/<job_id>/start \
     -H "Authorization: Bearer $TOKEN"
   ```

8. The **Rust job runner** automatically picks up the job and starts reading/writing data.

## Running Both Services Together

For development, open two terminals:

**Terminal 1 (API):**
```bash
cd agent
uvicorn plc_agent.api.app:app --host 0.0.0.0 --port 8003 --reload
```

**Terminal 2 (Job Runner):**
```bash
cd agent/rust_jobs
APP_DB_URL="postgresql://postgres@localhost/meta_data_version1" cargo run --release
```

For production, use systemd services or process managers to keep both services running.
