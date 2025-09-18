# Project: PLC Data Logger (Windows Desktop)

## Goal

A native-feeling desktop app that:

1. **Connects** to PLCs via **Modbus** and **OPC UA**
2. **Defines parent schemas** and **creates device tables** that inherit columns 1:1
3. **Maps columns** to protocol addresses
4. **Logs data** (continuous or trigger-based) into SQL

## Stack & Architecture

- **UI:** **Tauri + React (JavaScript, not TypeScript)**
- **Local Agent (sidecar process):** **Python** backend (HTTP on `localhost`) for connectors, migrations, and logging
  - UI ↔ Agent via **HTTP/JSON** (gRPC optional later)
- **Storage targets:** SQLite (default) and user-provided SQL (SQL Server / Postgres/Timescale / MySQL)
  **Why:** Clean separation; UI restarts don’t kill jobs; easy to later replace the agent with .NET/Rust.

## Core Concepts (what I mean by “parent schemas” and “tables”)

- **Parent Schema (Template):** A category definition only; **no table is created**.
  Examples: `LTPanel`, `HTPanel`, `Inverter` with fields like `r_current`, `y_current`, `voltage`, etc.
- **Device Table (Instance):** Physical device table (e.g., `Transformer_1`, `HTTransformer_3`, `Inverter_7`) that **inherits all columns 1:1** from exactly one Parent Schema.
  - Every table **must** include `timestamp_utc`.
  - Only **device tables** are migrated/created in the database.
- **Column Mapping:** For **each column** in **each device table**, map → `Protocol` (Modbus/OPC UA), `Address/NodeId`, `DataType`, `Scale`, `Deadband`, optional `Poll ms`.
- **Jobs:** Per-table logging configuration:
  - **Continuous** (interval)
  - **Trigger-based** (change with deadband, rising/falling edges, or comparisons)

## UI Information Architecture (exactly three tabs)

### 1 Networking

- **Devices panel**
  - **Modbus:** host, port, unit id, TCP/RTU, timeout, retries, endianness; **Test Read/Probe** (value + latency)
  - **OPC UA:** endpoint discovery, security policy, auth (Anon/User/Cert), trust store; **Browse** namespaces; **Test Read**; **60-sec subscription preview**
- **Storage target (inline on this tab)**
  - Add DB target: provider, host/port, DB name, schema, creds, SSL
  - **Test Connection**, **Create DB** (if permitted), **Set Default**
- **Gate:** Proceed only when ≥1 device connection **Connected** and ≥1 DB target **OK**.

### 2 Tables & Mapping

- **Parent Schemas**
  - Create/modify schema; fields: `key`, `type {float|int|bool|string}`, `unit`, `scale`
  - Import/Export CSV/JSON
- **Bulk Device Table Creation**
  - Pick Parent Schema → enter names (`Transformer-{1..70}`, `HTTransformer-{1..30}`, `Inverter-{1..20}` or paste list) → choose DB target → **Create**
- **Migration**
  - **Dry-Run DDL** preview → **Migrate** (creates/updates only **device tables**)
  - **Schema change policy:** allow **ADD COLUMN** across all child tables; block/guide renames/removals
- **Column Mapping**
  - Grid per device table: `Field | Protocol | Address/NodeId | Kind | Scale | Deadband | Poll ms | Preview`
  - Helpers: OPC UA browser scratchpad (drag/drop), Modbus address assistant (function/length/endian validation)
  - **Bulk mapping:** copy mapping from one device to many (e.g., all `Transformer_*`); CSV import for mappings
  - Validation: unresolved nodes, type mismatch, duplicates, illegal poll rates

### 3 Logging & Schedules

- **Jobs list:** `Table | Type | Interval ms | Trigger (field, op, value, deadband) | Enabled | Status | Last run | Errors`
- **Continuous logging:** per-table interval; optional per-column `poll ms`; batching (insert every N samples)
- **Trigger logging:** `change` (with **deadband**), `rising/falling edge`, `> >= < <= == !=`
- Controls: **Start/Stop**, **60-sec Dry-Run**, **Backfill once** (snapshot read), live mini-charts
- Health: read latency, write throughput, error %, queue depth

---

## Agent Responsibilities (backend sidecar)

- **Connectors**
  - **Modbus:** pooled range reads; endianness & 16/32-bit; retry/backoff
  - **OPC UA:** sessions + **subscriptions** for triggers; reconnects
- **Schema Migrator**
  - Generate/alter **device tables** only; record mapping snapshot for lineage
- **Storage Manager**
  - Targets: SQLite / Postgres/Timescale / SQL Server / MySQL
  - Bulk inserts; retention policies; optional store-and-forward (disk buffer)
- **Scheduler**
  - One job per table; respects per-column `poll ms`; backpressure handling
- **Security**
  - OPC UA trust store; credentials via OS vault/DPAPI; least-privilege DB users

---

## Logging Model (per device table)

- Columns = **all fields** inherited from Parent Schema **+** `timestamp_utc`
- **Primary index** on `timestamp_utc` (descending)
- Optional per-column indexes (only when needed)
- **Deadband semantics:** for `change` triggers, ignore changes whose absolute delta < deadband.

---

## Expected Scale (example)

- \~120 tables (≈70 LT, 30 HT, 20 Inverters)
- \~30 columns/table @ 1 Hz → \~3,600 values/s total
- Use batch inserts and pooled reads; prefer Timescale/SQL Server partitioning at high volumes

---

## Acceptance Criteria (must pass)

1. **Networking**

   - Add one Modbus and one OPC UA connection; **Test** shows value + latency; status **Connected**
   - Add a DB target; **Test** passes; **Set Default**

2. **Tables & Mapping**

   - Create Parent Schemas: `LTPanel`, `HTPanel`, `Inverter` with representative fields
   - **Bulk create** device tables: `Transformer-{1..70}`, `HTTransformer-{1..30}`, `Inverter-{1..20}`
   - **Migrate** produces physical tables (each includes `timestamp_utc`)
   - Map columns for one `Transformer_1`; **Bulk apply** to all `Transformer_*`
   - Validation blocks inconsistent mappings

3. **Logging & Schedules**

   - Start a **continuous** job @ 1000 ms for 5 LT devices; rows land in their tables with correct columns + `timestamp_utc`
   - Add a **trigger** job (e.g., `voltage change deadband=0.5`); logs only when delta ≥ 0.5
   - Health shows non-zero write throughput and stable error rate (≈0%)

4. **Resilience**
   - If device offline → job status **Degraded**; resumes automatically
   - If DB offline → bounded buffer; flushes when back online

---

## Deliverables

- **Tauri + React (JavaScript) desktop app** with the three tabs above
- **Python agent** exposing the HTTP API and implementing connectors, migrator, scheduler
- **Installer** (MSI/MSIX) and **README** with run/build steps
- Config & logs stored in known locations; agent starts/stops with the app

---

## Non-Goals (v1)

- Centralized multi-site server
- Role-based access control/SSO
- Advanced analytics dashboards (beyond basic charts/preview)

---

## Nice-to-Have (later)

- Dual-write (local SQLite + central Postgres)
- Export sinks (CSV/Parquet)
- Expression editor for complex trigger logic

---
