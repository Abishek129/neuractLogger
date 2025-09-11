# PLC Logger System Overview

This document summarizes the architecture, files, and behaviors of the PLC Logger system, across the backend (Agent) and the frontend (Desktop UI).

## High-Level Architecture

- Backend (“Agent”): Python service exposing a REST API (FastAPI/Uvicorn), managing devices, mappings, schedules (jobs), and metrics; persists configuration/state in a local SQLite app DB (`app.db`), and reads/writes data/mappings to a user-selected database (commonly SQLite `mydatabase.db`).
- Frontend (“Desktop UI”): React + Vite application (with a light use of MUI and custom CSS) for configuring connectivity, device tables, mappings, and logging jobs. It talks to the Agent via HTTP using a small fetch client with token handshake.

---

## Backend (Agent)

Location: `agent/plc_agent/api` (FastAPI) and `agent/run_agent.py` (launcher)

### Tech Stack

- Python 3.13 (logs confirm: Tech Stack Verified)
- FastAPI + Uvicorn (preferred) or a minimal fallback HTTP server
- SQLite (local app DB via `sqlite3`), SQLAlchemy (for user DB operations)
- Optional: `python-opcua` (OPC UA Client), `pymodbus` (Modbus TCP Client), `psutil` (system metrics)

### Entry Points

- `agent/run_agent.py`: Launch helper used by `scripts/dev_start.ps1` (writes lockfile with token/port for the UI).
- `agent/plc_agent/api/app.py`: `create_app()` configures middleware, routers, loads state, starts background threads, returns FastAPI app.
- `agent/plc_agent/api/server.py`: Fallback single-file server (used when `AGENT_USE_UVICORN=0`). Limited endpoints; no CORS.

### Key Modules / Files

- `app.py`:
  - Registers CORS (allows `http://127.0.0.1:5173`, `http://localhost:5173`, plus `CORS_ORIGIN` env override)
  - Adds token auth middleware
  - Includes routers (see below)
  - Loads state from `app.db` and starts:
    - Device auto-reconnect loop
    - System metrics sampler

- `security.py`: Token middleware; uses `X-Agent-Token` or `Authorization: Bearer`.
- `store.py`: In-memory store coordinating app state, persistence to `app.db`, device reconnect background loop, mapping health, etc.
- `appdb.py`: SQLite accessors for `app.db`; creates tables on init; DPAPI best-effort encryption for device params on Windows.
- `metrics.py`: In-memory metrics registry; per-job run summaries and system metrics sampler.

### Routers and Endpoints (Selected)

- `routers/auth.py`:
  - `GET /auth/handshake`: Issues a token for the UI to store and use in subsequent calls.

- `routers/health.py`:
  - `GET /health`: Basic health check.

- `routers/networking.py`:
  - `GET /networking/nics`: NICs list (reachability helpers)
  - `POST /networking/ping`: Ping a target
  - `POST /networking/tcp_test`: Attempt TCP connections to ports
  - `GET/POST/PUT/DELETE /networking/gateways[...]`: Manage saved gateways; record last ping/TCP tests

- `routers/devices.py`:
  - `GET /devices`: List devices
  - `POST /devices`: Create with fast preflight connectivity check (OPC UA / Modbus)
  - `PUT /devices/{id}`: Update name, autoReconnect
  - `DELETE /devices/{id}`: Delete device
  - `POST /devices/{id}/connect|disconnect|quick_test`: Status helpers

- `routers/storage.py`:
  - `GET /storage/targets`: List DB targets; default target
  - `POST /storage/targets`: Add/Upsert target (SQLite DSN or file path, etc.)
  - `POST /storage/targets/test`: Test DB connectivity
  - `POST /storage/targets/default`: Set default DB target
  - `DELETE /storage/targets/{id}`: Remove if not default and not referenced

- `routers/schemas.py`: CRUD for parent schemas (columns/field definitions).

- `routers/tables.py`:
  - Manage logical device tables (planned/migrated)
  - Discover physical tables in the user DB (namespace `neuract`)
  - `POST /tables/bulk_create`, `GET /tables`, `GET /tables/discover`, `GET /tables/{id}`, `POST /tables/migrate`, etc.

- `routers/mappings.py`:
  - `GET /mappings/{tableId}`: Load mapping rows (from user DB) and merge with Store state
  - `POST /mappings/{tableId}`: Upsert mapping rows and optional device binding
  - `POST /mappings/{tableId}/import|bulk_apply|validate`, `DELETE /mappings/{tableId}/{field}`
  - Writes to a dedicated mapping table in the user DB (see “Mappings & Namespace” below)

- `routers/jobs.py`:
  - `GET /jobs`, `POST /jobs`: Create jobs (continuous or trigger)
  - `POST /jobs/{id}/start|pause|stop|dry_run|backfill`: Control job lifecycle
  - `GET /jobs/{id}/metrics|runs|errors`, `GET /jobs/metrics/summary`
  - `DELETE /jobs/{id}`: Remove job and cascade delete history/rollups (implemented)

- `routers/reports.py`, `routers/db_metrics.py`: CSV exports and DB usage metrics.

### Persistence: App Local DB (`app.db`)

Tables (created on `appdb.init()`):

- `app_schemas`, `app_schema_fields`
- `app_device_tables` (logical tables; includes `device_id`, `mapping_health`)
- `app_db_targets` (provider/conn, status, last msg) + `app_meta` (default target id)
- `app_gateways` (reachability; ports/tags, last ping/TCP JSON)
- `app_devices` (metadata only; params protected via DPAPI on Windows)
- `app_jobs`, `app_job_runs`, `app_metrics_jobs_minute`, `app_metrics_system_minute`, `app_job_errors_minute`

Environment override: set `APP_DB_DIR` to change the folder for `app.db`.

### User Database (“Target DB”) and Namespace

- The UI configures a target DB (SQLite by default, e.g., `mydatabase.db`).
- The system writes device table rows there and persists mapping rows in a dedicated mapping table.
- Namespace rules (SQLite/MySQL): physical names are prefixed with `neuract__`.
- Namespace rules (Postgres/SQL Server): uses schema `neuract` with logical names.

Mapping table candidates (auto-detected or created):

- Without schemas: `neuract__device_mappings` (preferred), `neuract_device_mappings`, or `device_mappings`
- With schemas: `neuract.device_mappings`

Mapping table columns: `table_name, field_key, protocol, address, data_type, scale, deadband, device_id`.

### Devices & Protocols

- OPC UA: uses `python-opcua` for connectivity tests and simple reads; normalizes `0.0.0.0` endpoints to `127.0.0.1`.
- Modbus TCP: uses `pymodbus.client.ModbusTcpClient` for connect/read probes.
- Auto-reconnect loop: periodically attempts reconnects for devices with `autoReconnect=true` and updates status and latency.

### CORS, Auth, and Dev Server Notes

- CORS: Enabled via `fastapi.middleware.cors.CORSMiddleware`; allows `http://127.0.0.1:5173` and `http://localhost:5173` by default. Override with `CORS_ORIGIN`.
- Auth: UI obtains a token from `GET /auth/handshake` and sends it as `X-Agent-Token` and `Authorization: Bearer`.
- Uvicorn vs Fallback: If `AGENT_USE_UVICORN=0`, the minimal fallback server is used (no CORS headers; many routes `501`). For development with the UI, ensure Uvicorn/FastAPI is active (default). Environment: `AGENT_USE_UVICORN` not set or set to `1`.

### Scripts

- `scripts/dev_start.ps1`: Starts agent (writes lockfile to `C:\ProgramData\PLCLogger\agent\agent.lock.json`, sets `VITE_AGENT_BASE_URL`/token for the UI) and the Vite dev server.
- `scripts/db_inspect.py`: Inspect SQLite DBs (app.db / mydatabase.db) from the terminal.
- `agent/db_dev_scripts/*`: DB helpers.

---

## Frontend (Desktop UI)

Location: `apps/desktop`

### Tech Stack

- React + Vite (development server at `http://localhost:5173`)
- Light usage of MUI (`@mui/material`) for tabs/layout in `App.jsx`
- Custom CSS per area: `styles/networking.css`, `styles/tables.css`, `styles/logging.css`
- Optional packaging via Tauri (`apps/desktop/src-tauri`)

### Key Files / Structure

- `src/App.jsx`: Top-level app with tabs for Networking, Tables & Mapping, Logging & Schedules. Renders `<Toast />` notification container.
- Pages:
  - `pages/Networking/index.jsx`: Reachability (ping/TCP), Gateways, Connect (device add), Saved Devices, Databases.
  - `pages/TablesMapping/*`: Device tables, schema fields, mapping editor and discovery.
  - `pages/LoggingSchedules/*`: Job management (create/start/stop/pause), metrics, dry-run/backfill, history/reports.
- State:
  - `state/store.jsx`: Custom Context + Reducer store for UI state.
  - `state/selectors.js`: Pure selectors for derived state (mapping status, gates, etc.).
- API client:
  - `lib/api/client.js`: `request()` with token handshake (`/auth/handshake`), base URL from `VITE_AGENT_BASE_URL`, stores token in localStorage.
  - `lib/api/networking.js`, `lib/api/tables.js`, `lib/api/mappings.js`, `lib/api/jobs.js`, `lib/api/metrics.js`, `lib/api/schemas.js`: Feature-specific wrappers.
- Components:
  - `components/Toast.jsx`: Global toast bus and renderer; named export `toast` (success/error/info/warn), default export `<Toast />` container.
  - `components/*`: DataGrid, TableToolbar, ConfirmDialog, Chart (stubs/helpers).

### Environment Variables (Frontend)

- `VITE_AGENT_BASE_URL`: Base URL for the Agent API (set by dev script from lockfile, defaults to `http://127.0.0.1:5175`).
- `VITE_AGENT_TOKEN`: Optional initial token (handshake usually provides one).

### UX Notes

- Networking: shows connectivity status, saved gateways, quick test UI for devices, and DB targets. Actions update inline indicators; toasts can be invoked via `toast.success('...')`, etc.
- Tables & Mapping: validates mapping completeness and syncs device bindings; shows mapping health (Unmapped/Partially Mapped/Mapped).
- Logging & Schedules: job creation (continuous/triggered), lifecycle controls, history tables, CSV export links.

---

## Data Flow Summary

1) Networking/Devices
   - UI tests connectivity (OPC UA/Modbus) → Agent checks and returns latency.
   - UI saves device (name, protocol, params) → Agent persists to `app.db` (params protected on Windows), starts auto-reconnect.

2) Tables & Mappings
   - UI loads/creates logical device tables in `app.db`.
   - Mapping rows are saved to the user DB mapping table; device binding also saved in `app.db` for durability across restarts.
   - On startup or retrieval, Agent hydrates mapping rows from user DB and reconciles with Store.

3) Jobs
   - UI creates jobs (validates mapped tables) → Agent persists jobs in `app.db`.
   - Running jobs: Agent reads from devices, writes to user DB, collects per-run metrics; history can be exported/reviewed.
   - Deleting a job removes config and cascades history/rollups from `app.db`.

---

## Common Development/Troubleshooting Notes

- CORS errors (browser console): ensure the Agent is running with Uvicorn/FastAPI (default). The fallback server (`AGENT_USE_UVICORN=0`) does not set CORS headers and returns `501` for many routes.
- Token/401: The UI handshakes to obtain a token; if a `401` occurs, it retries once automatically. Ensure the Agent printed a token or the handshake endpoint works.
- SQLite path ambiguity: The Agent resolves SQLite target paths to absolute paths to avoid opening an unintended DB from a different working directory.
- Mapping not visible after restart: Device binding is persisted in `app.db` and mapping rows in the user DB; hydration on startup syncs rows into Store. Verify mapping table exists and contains rows for the physical table name (`neuract__<logical>` in prefix mode).

---

## Scripts & Running Locally

- `scripts/dev_start.ps1` (recommended):
  1. Starts Agent on `127.0.0.1:5175` (writes lockfile with port/token under `C:\ProgramData\PLCLogger\agent\agent.lock.json`).
  2. Exports `VITE_AGENT_BASE_URL` (and token) for the UI dev server.
  3. Starts Vite dev server at `http://localhost:5173`.

- To package desktop app: see `apps/desktop/src-tauri/tauri.conf.json` (not covered in detail here).

---

## Notable Paths

- Backend
  - `agent/plc_agent/api/app.py`, `security.py`, `store.py`, `appdb.py`, `metrics.py`
  - Routers in `agent/plc_agent/api/routers/`: `devices.py`, `networking.py`, `storage.py`, `schemas.py`, `tables.py`, `mappings.py`, `jobs.py`, `health.py`, `auth.py`, `reports.py`, `db_metrics.py`
- Frontend
  - `apps/desktop/src/App.jsx`
  - `apps/desktop/src/pages/Networking/index.jsx`
  - `apps/desktop/src/pages/TablesMapping/*`
  - `apps/desktop/src/pages/LoggingSchedules/*`
  - `apps/desktop/src/lib/api/*`
  - `apps/desktop/src/components/*`
  - `apps/desktop/src/styles/*`
