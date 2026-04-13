# Neuract Logger — Frontend API Reference

**Base URL:** `http://127.0.0.1:5175`
**Content-Type:** `application/json`
**Auth:** Keycloak JWT — `Authorization: Bearer <access_token>`
**Token expiry:** 300 seconds (5 minutes)

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Health](#2-health)
3. [Schemas](#3-schemas)
4. [Tables](#4-tables)
5. [Devices](#5-devices)
6. [Gateways](#6-gateways)
7. [Mappings](#7-mappings)
8. [Jobs](#8-jobs)
9. [Storage Targets](#9-storage-targets)
10. [Protocol Types](#10-protocol-types)
11. [Bulk Import](#11-bulk-import)
12. [Network Diagnostics](#12-network-diagnostics)
13. [Notifications](#13-notifications)
14. [System Metrics](#14-system-metrics)
15. [Database Metrics](#15-database-metrics)
16. [Reports](#16-reports)
17. [WebSocket](#17-websocket)
18. [Error Reference](#18-error-reference)

---

## 1. Authentication

### POST /auth/login

Get JWT tokens. Call this first — store the `access_token` for all subsequent requests.

**Request:**
```json
{
  "username": "rohith",
  "password": "neuract"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzUxMiIs...",
  "expires_in": 300,
  "token_type": "Bearer"
}
```

> Re-login or implement silent refresh every ~4 minutes to avoid `TOKEN_EXPIRED` errors.

---

### POST /auth/register

Create a new user in Keycloak.

**Request:**
```json
{
  "username": "john",
  "email": "john@example.com",
  "password": "secret123",
  "first_name": "John",
  "last_name": "Doe"
}
```

**Response:**
```json
{
  "ok": true,
  "user_id": "aed23084-0997-4e2e-8c2c-01d1dc866044",
  "username": "john"
}
```

---

### POST /auth/assign-role/{username}

Assign `neuract-admin` role to a user.

**Response:**
```json
{
  "ok": true,
  "username": "john",
  "role": "neuract-admin"
}
```

---

## 2. Health

### GET /health

```json
{ "status": "ok", "agent": "plc-agent", "version": "0.1.0" }
```

### GET /version

```json
{
  "appVersion": "0.1.0",
  "python": "3.11.9",
  "platform": "linux",
  "fastapi": "0.115.6",
  "port": 5175
}
```

---

## 3. Schemas

Schemas define the column structure for device tables. Each schema has a set of fields (columns) with type and unit metadata.

### GET /schemas

List all schemas.

**Response:**
```json
{
  "items": [
    {
      "id": "sch_1773215587071",
      "name": "mfm",
      "fields": [
        { "key": "current_r", "type": "float", "unit": "A", "scale": null, "desc": null },
        { "key": "voltage_ry", "type": "float", "unit": "V", "scale": null, "desc": null }
      ]
    }
  ]
}
```

---

### POST /schemas

> **Auth required:** `logger_write`

Create a schema.

**Request:**
```json
{
  "id": "my_schema",
  "name": "Custom Sensor",
  "fields": [
    { "key": "temperature", "type": "float", "unit": "°C" },
    { "key": "status", "type": "int" }
  ]
}
```

**Field types:** `float`, `int`, `bool`, `string`

---

### GET /schemas/export

Export all schemas as JSON (for backup or migration).

**Response:**
```json
{ "schemas": [ ... ] }
```

---

### POST /schemas/import

Import schemas from an export payload.

**Request:**
```json
{ "schemas": [ ... ] }
```

**Response:**
```json
{ "imported": 7 }
```

---

## 4. Tables

Tables are logging targets — each table stores time-series data for one device. Tables are linked to a schema (column structure) and a storage target (database).

### GET /tables

List tables with pagination and optional filters.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | 1 | Page number |
| pageSize | int | 50 | Items per page (use 300 to get all) |
| parentSchemaId | string | — | Filter by schema |
| dbTargetId | string | — | Filter by DB target |
| status | string | — | `migrated` or `not_migrated` |
| name | string | — | Name search |

**Response:**
```json
{
  "success": true,
  "total": 275,
  "page": 1,
  "items": [
    {
      "id": "tbl_1773826827214_276",
      "name": "mfm_001",
      "schemaId": "sch_1773215587071",
      "dbTargetId": "db_1773214350018",
      "status": "migrated",
      "lastMigratedAt": "2026-03-18T10:00:00Z",
      "columnCount": 39,
      "mappingExists": true,
      "mappingStatus": "Mapped"
    }
  ]
}
```

---

### GET /tables/{table_id}

Get single table details with schema and mapping health.

**Response:**
```json
{
  "success": true,
  "item": { ... },
  "schema": { "id": "sch_...", "name": "mfm", "fields": [...] },
  "mappingHealth": "Mapped"
}
```

**Mapping health values:** `Mapped`, `Partially Mapped`, `Unmapped`

---

### POST /tables/bulk_create

> **Auth required:** `logger_write`

Create multiple tables at once. Supports pattern expansion or explicit names.

**Request (pattern):**
```json
{
  "parentSchemaId": "sch_1773215587071",
  "pattern": "mfm_{1..10}",
  "dbTargetId": "db_1773214350018"
}
```

**Request (explicit names):**
```json
{
  "parentSchemaId": "sch_1773215587131",
  "names": ["ahu_001", "ahu_002", "ahu_003"],
  "dbTargetId": "db_1773214350018"
}
```

> **Note:** `pattern` does not zero-pad. Use `names` for zero-padded names like `mfm_001`.

**Response:**
```json
{
  "success": true,
  "count": 3,
  "items": [ ... ]
}
```

---

### POST /tables/migrate

> **Auth required:** `logger_write`

Create or update the physical tables in the target database.

**Request:**
```json
{ "ids": ["tbl_..._1", "tbl_..._2"] }
```

**Response:**
```json
{
  "success": true,
  "items": [
    { "id": "tbl_..._1", "name": "mfm_001", "status": "created" },
    { "id": "tbl_..._2", "name": "mfm_002", "status": "updated" }
  ]
}
```

---

### POST /tables/bulk_update_target

> **Auth required:** `logger_write`

Change the DB target for a set of tables.

**Request:**
```json
{
  "dbTargetId": "db_new_target",
  "ids": ["tbl_1", "tbl_2"]
}
```

---

### POST /tables/dry_run_ddl

Preview the SQL that would be executed by migrate (without executing).

**Request:**
```json
{ "ids": ["tbl_1"] }
```

**Response:**
```json
{
  "success": true,
  "items": [
    {
      "id": "tbl_1",
      "name": "mfm_001",
      "operations": [
        "CREATE TABLE neuract.mfm_001 (timestamp_utc TIMESTAMPTZ NOT NULL, current_r REAL, ...)",
        "CREATE INDEX IF NOT EXISTS idx_mfm_001_ts ON neuract.mfm_001(timestamp_utc)"
      ]
    }
  ]
}
```

---

### GET /tables/discover

List tables that exist physically in the DB (migrated) vs those that are only configured (planned).

**Query Parameters:** `dbTargetId` (optional)

**Response:**
```json
{
  "success": true,
  "planned": [ ... ],
  "migrated": [ ... ]
}
```

---

## 5. Devices

Devices are the Modbus/OPC UA endpoints that the Rust runner reads data from. Each device maps to one table.

### GET /devices

List all devices.

**Query Parameters:** `pageSize` (default 50, use 300 to get all)

**Response:**
```json
{
  "items": [
    {
      "id": "dev_1773826228313",
      "name": "mfm_001",
      "protocol": "modbus",
      "gatewayId": "gw_...",
      "port": 502,
      "unitId": 1,
      "status": "connected",
      "latencyMs": 2,
      "lastError": null,
      "params": { "host": "10.10.1.10" },
      "autoReconnect": true
    }
  ]
}
```

---

### POST /devices

> **Auth required:** `logger_write`

Create a device (also tests the connection).

**Request:**
```json
{
  "name": "mfm_001",
  "protocol": "modbus",
  "gatewayId": "gw_...",
  "port": 502,
  "unitId": 1,
  "params": { "host": "10.10.1.10" }
}
```

**Protocols:** `modbus`, `opcua`

**Response:**
```json
{
  "success": true,
  "item": { ... },
  "error": null
}
```

---

### PUT /devices/{dev_id}

> **Auth required:** `logger_write`

Update device fields (partial update).

**Request:**
```json
{
  "name": "mfm_001_updated",
  "unitId": 2,
  "autoReconnect": false
}
```

---

### DELETE /devices/{dev_id}

Delete a device.

---

### POST /devices/{dev_id}/connect

> **Auth required:** `logger_write`

Test and mark as connected.

**Response:**
```json
{ "success": true, "latencyMs": 3 }
```

---

### POST /devices/{dev_id}/disconnect

> **Auth required:** `logger_write`

Mark device as disconnected.

---

### POST /devices/{dev_id}/quick_test

> **Auth required:** `logger_write`

Test connection without changing device state.

**Response:**
```json
{ "success": true, "latencyMs": 3, "error": null }
```

---

## 6. Gateways

Gateways represent network endpoints (IP addresses) that host one or more devices.

### GET /networking/gateways

List all gateways.

**Response:**
```json
{
  "items": [
    {
      "id": "gw_...",
      "name": "GIC-01",
      "host": "10.10.1.10",
      "protocol_hint": "modbus",
      "ports": [502],
      "status": "active"
    }
  ]
}
```

---

### GET /networking/gateways_with_devices

List gateways with their linked devices.

**Response:**
```json
{
  "items": [
    {
      "id": "gw_...",
      "name": "GIC-01",
      "host": "10.10.1.10",
      "deviceCount": 10,
      "devices": [ ... ]
    }
  ]
}
```

---

### POST /networking/gateways

> **Auth required:** `logger_write`

Create a gateway.

**Request:**
```json
{
  "name": "GIC-01",
  "host": "10.10.1.10",
  "protocol_hint": "modbus",
  "ports": [502]
}
```

---

### PUT /networking/gateways/{gid}

> **Auth required:** `logger_write`

Update gateway fields (partial update).

---

### DELETE /networking/gateways/{gid}

Delete a gateway. Fails if devices are linked.

---

### POST /networking/gateways/{gid}/ping

ICMP ping a gateway. Rate-limited (3 second minimum interval).

**Request:**
```json
{ "count": 4, "timeoutMs": 800 }
```

**Response:**
```json
{ "ok": true, "lossPct": 0, "min": 1, "avg": 2, "max": 3, "samples": [1,2,3,2] }
```

---

### POST /networking/gateways/{gid}/tcp

TCP port test on a gateway.

**Request:**
```json
{ "ports": [502], "timeoutMs": 1000 }
```

**Response:**
```json
{
  "ok": true,
  "results": [
    { "port": 502, "ok": true, "status": "open", "timeMs": 2 }
  ]
}
```

---

## 7. Mappings

Mappings bind each table field (column) to a device register address. This tells the Rust runner what to read and where to write.

### GET /mappings/{table_id}

Get the mapping for a table.

**Response:**
```json
{
  "success": true,
  "health": "Mapped",
  "item": {
    "tableId": "tbl_...",
    "deviceId": "dev_...",
    "rows": {
      "current_r":   { "protocol": "modbus", "address": "0",  "dataType": "float", "encoding": "float32" },
      "current_y":   { "protocol": "modbus", "address": "2",  "dataType": "float", "encoding": "float32" },
      "voltage_ry":  { "protocol": "modbus", "address": "8",  "dataType": "float", "encoding": "float32" },
      "ahu_running_status": { "protocol": "modbus", "address": "0", "dataType": "int", "encoding": "uint16_enum" }
    }
  }
}
```

**Health values:** `Mapped`, `Partially Mapped`, `Unmapped`

---

### POST /mappings/{table_id}

> **Auth required:** `logger_write`

Upsert mapping rows (merges with existing).

**Request:**
```json
{
  "deviceId": "dev_...",
  "dbTargetId": "db_...",
  "rows": {
    "current_r": {
      "protocol": "modbus",
      "address": "0",
      "encoding": "float32",
      "dataType": "float"
    }
  }
}
```

---

### POST /mappings/{table_id}/bulk_apply

> **Auth required:** `logger_write`

Replace all mapping rows at once (full replacement).

**Request:** Same structure as upsert above.

---

### POST /mappings/{table_id}/validate

Validate a mapping — checks device binding, field completeness, and live register read.

**Response:**
```json
{
  "success": true,
  "health": "Mapped",
  "problems": []
}
```

**Problem codes:** `DEVICE_NOT_BOUND`, `MAPPING_INCOMPLETE`, `MAPPING_TYPE_MISMATCH`, `TAG_UNREADABLE`

---

### GET /mappings/{table_id}/export

Export mapping as JSON (for copy/backup).

---

### POST /mappings/{table_id}/import

Import a previously exported mapping.

**Request:**
```json
{
  "mapping": {
    "deviceId": "dev_...",
    "rows": { ... }
  }
}
```

---

### POST /mappings/{src_table_id}/copy_to/{dst_table_id}

Copy a mapping from one table to another (both must share the same DB target).

---

### DELETE /mappings/{table_id}/{field_key}

Delete a single field mapping row.

---

## 8. Jobs

Jobs are the data logging tasks executed by the Rust runner. A job binds a set of tables together and runs on a fixed interval.

### GET /jobs2

List all jobs.

**Response:**
```json
{
  "items": [
    {
      "id": "job_1773829817113",
      "name": "Seetharampur Full Site",
      "type": "continuous",
      "tables": ["tbl_..._1", "tbl_..._2"],
      "intervalMs": 1000,
      "status": "running",
      "enabled": true,
      "triggers": [],
      "batching": {},
      "cpuBudget": "balanced"
    }
  ]
}
```

**Status values:** `running`, `stopped`, `paused`
**Type values:** `continuous`, `trigger`

---

### POST /jobs2

> **Auth required:** `logger_write`

Create a new job.

**Request:**
```json
{
  "name": "Seetharampur Full Site",
  "type": "continuous",
  "tables": ["tbl_..._1", "tbl_..._2"],
  "intervalMs": 1000,
  "enabled": true,
  "triggers": [],
  "batching": {},
  "cpuBudget": "balanced"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Job display name |
| type | string | Yes | `continuous` or `trigger` |
| tables | array | Yes | List of table IDs |
| intervalMs | int | Yes | Read interval in milliseconds |
| enabled | bool | No | Default `true` |
| triggers | array | No | Trigger conditions (see below) |
| cpuBudget | string | No | `fast`, `balanced`, `eco` |

**Trigger condition object:**
```json
{
  "tableId": "tbl_...",
  "field": "active_power_total_kw",
  "op": ">",
  "value": 2000,
  "deadband": 50,
  "cooldownMs": 5000
}
```
**Operators:** `change`, `>`, `>=`, `<`, `<=`, `==`, `!=`, `rising`, `falling`

**Response:**
```json
{
  "success": true,
  "item": {
    "id": "job_1773829817113",
    "name": "Seetharampur Full Site",
    "status": "stopped",
    ...
  }
}
```

---

### POST /jobs2/{job_id}/start

> **Auth required:** `logger_write`

Start a job. The Rust runner picks it up within ~2 seconds.
Also sends a notification to all `logger_read` users and broadcasts via WebSocket.

**Response:**
```json
{ "success": true, "message": "started" }
```

---

### POST /jobs2/{job_id}/stop

> **Auth required:** `logger_write`

Stop a running job.

**Response:**
```json
{ "success": true, "message": "stopped" }
```

---

### POST /jobs2/{job_id}/pause

> **Auth required:** `logger_write`

Pause a job.

**Response:**
```json
{ "success": true, "message": "paused" }
```

---

### POST /jobs2/stop_all

> **Auth required:** `logger_write`

Stop all running jobs.

**Response:**
```json
{ "success": true, "stopped": 1 }
```

---

### POST /jobs2/{job_id}/dry_run

> **Auth required:** `logger_write`

Sample live device values without writing to the database. Useful for testing mappings.

**Response:**
```json
{
  "success": true,
  "items": [
    {
      "tableId": "tbl_...",
      "values": { "current_r": 127.3, "voltage_ry": 10918.5 },
      "ts": "2026-03-18T10:43:00+00:00"
    },
    {
      "tableId": "tbl_..._bad",
      "error": "DEVICE_NOT_BOUND"
    }
  ]
}
```

---

### POST /jobs2/{job_id}/backfill

> **Auth required:** `logger_write`

Write one sample row per table to the database immediately (one-shot write).

**Response:**
```json
{ "success": true, "wrote": 275 }
```

---

### DELETE /jobs2/{job_id}

Delete a job and clear its metrics history.

---

### DELETE /jobs2

Bulk delete jobs.

**Request:**
```json
{ "ids": ["job_1", "job_2"] }
```

---

### GET /jobs2/{job_id}/runs

Get job execution history.

**Query Parameters:** `frm` (datetime), `to` (datetime)

**Response:**
```json
{
  "items": [
    {
      "id": "run_...",
      "jobId": "job_...",
      "startedAt": "2026-03-18T10:00:00Z",
      "stoppedAt": "2026-03-18T10:43:00Z",
      "durationMs": 2580000,
      "rows": 750750,
      "readLatAvg": 0.8,
      "writeLatAvg": 18.0,
      "errorPct": 0.0
    }
  ]
}
```

---

## 9. Storage Targets

Storage targets define where data is written (the time-series database).

### GET /storage/targets

List all configured database targets.

**Response:**
```json
{
  "items": [
    {
      "id": "db_1773214350018",
      "provider": "postgresql",
      "conn": "postgresql://postgres@localhost/latest_target_v2",
      "status": "untested",
      "lastMsg": null
    }
  ],
  "defaultId": "db_1773214350018"
}
```

**Providers:** `postgresql`, `sqlite`, `sqlserver`, `mysql`

---

### POST /storage/targets

Add a storage target.

**Request:**
```json
{
  "id": "my_target",
  "provider": "postgresql",
  "conn": "postgresql://user:pass@host:5432/dbname"
}
```

---

### PUT /storage/targets/{tid}

Update a storage target (partial update).

---

### DELETE /storage/targets/{tid}

Delete a target. Fails if it is the default or in use (use `?force=true` to override).

---

### POST /storage/targets/default

Set the default storage target.

**Request:**
```json
{ "id": "db_1773214350018" }
```

**Response:**
```json
{ "ok": true, "defaultId": "db_1773214350018" }
```

---

### POST /storage/targets/test

Test database connectivity.

**Request:**
```json
{ "provider": "postgresql", "conn": "postgresql://postgres@localhost/mydb" }
```

Or test an existing target by ID:
```json
{ "id": "db_1773214350018" }
```

**Response:**
```json
{ "ok": true, "message": "Connection OK" }
```

---

## 10. Protocol Types

### GET /protocol_types

```json
{
  "items": [
    { "type": "modbus" },
    { "type": "opcua" }
  ]
}
```

### POST /protocol_types

Add a protocol type.

```json
{ "type": "custom_protocol" }
```

### DELETE /protocol_types/{protocol_type}

Delete a protocol type. Fails if any device or gateway is using it.

---

## 11. Bulk Import

### POST /bulk_import/devices

Import devices from a list — auto-creates gateways by IP if they don't exist.

**Request:**
```json
{
  "devices": [
    {
      "name": "mfm_001",
      "ip": "10.10.1.10",
      "port": 502,
      "protocol": "modbus",
      "unit": 1,
      "connections": "GIC-01"
    },
    {
      "name": "ahu_001",
      "ip": "127.0.0.1",
      "port": 5020,
      "protocol": "modbus",
      "unit": 100,
      "connections": "Equipment Gateway"
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| name | Yes | Device name |
| ip | Yes | IP — used to find or create the gateway |
| port | No | Connection port |
| protocol | No | `modbus` (default) or `opcua` |
| unit | No | Modbus unit ID (1-247) |
| connections | No | Gateway name (used as label when creating) |

**Response:**
```json
{
  "success": true,
  "summary": {
    "total": 275,
    "created_gateways": 23,
    "created_devices": 275,
    "skipped": 0,
    "failed": 0
  },
  "results": [ ... ]
}
```

---

## 12. Network Diagnostics

### POST /networking/ping

ICMP ping any host.

**Request:**
```json
{ "target": "10.10.1.10", "count": 4, "timeoutMs": 800 }
```

**Response:**
```json
{ "ok": true, "lossPct": 0, "min": 1, "avg": 2, "max": 3 }
```

---

### POST /networking/tcp_test

TCP port connectivity test.

**Request:**
```json
{ "host": "10.10.1.10", "port": 502, "timeoutMs": 1000 }
```

**Response:**
```json
{ "ok": true, "status": "open", "timeMs": 2 }
```

**Status values:** `open`, `timeout`, `closed`

---

### POST /networking/modbus/test

Test a live Modbus register read.

**Request:**
```json
{
  "host": "10.10.1.10",
  "port": 502,
  "unitId": 1,
  "address": 0,
  "count": 2
}
```

Or test by device ID (reads host/port from config):
```json
{ "deviceId": "dev_...", "unitId": 1, "address": 0, "count": 2 }
```

**Response:**
```json
{ "ok": true, "protocol": "modbus", "values": [16982, 17408], "latencyMs": 3 }
```

---

### POST /networking/opcua/test

Test an OPC UA connection (optionally read a node value).

**Request:**
```json
{
  "endpoint": "opc.tcp://127.0.0.1:4840/neuract/server",
  "nodeId": "ns=2;i=1001"
}
```

**Response:**
```json
{ "ok": true, "protocol": "opcua", "value": 127.3, "latencyMs": 45 }
```

---

### POST /networking/opcua/browse

Browse the OPC UA node tree.

**Request:**
```json
{ "endpoint": "opc.tcp://127.0.0.1:4840/neuract/server", "nodeId": "i=85" }
```

**Response:**
```json
{
  "ok": true,
  "items": [
    { "nodeId": "ns=2;i=1001", "browseName": "2:mfm_001" }
  ]
}
```

---

### GET /networking/nics

List active network interfaces on the host.

**Response:**
```json
{
  "items": [
    { "id": "eth0", "label": "Ethernet", "ip": "192.168.1.20", "cidr": 24 },
    { "id": "lo",   "label": "Loopback", "ip": "127.0.0.1",    "cidr": 8 }
  ]
}
```

---

## 13. Notifications

### POST /auth/notifications

Create and broadcast a notification via Redis → WebSocket.

**Status Code:** 201

**Request:**
```json
{
  "message": "Sensor threshold exceeded on mfm_001",
  "type": "alert"
}
```

**Types:** `job`, `alert`, `info`, `warning`, `error`

**Response:**
```json
{
  "ok": true,
  "id": "a1b2c3d4-...",
  "type": "alert",
  "message": "Sensor threshold exceeded on mfm_001",
  "read": false,
  "time": "2026-03-18T10:43:00Z"
}
```

---

### GET /auth/notifications/list

List all notifications for the current user (most recent first).

**Response:**
```json
[
  {
    "id": "a1b2c3d4-...",
    "type": "job",
    "message": "Job job_1773829817113 was started by rohith",
    "read": false,
    "time": "2026-03-18T10:43:00Z"
  }
]
```

> **Auto-notifications:** Every time a job is started via `POST /jobs2/{id}/start`, the system automatically creates a notification for all `logger_read` users and pushes it over WebSocket.

---

## 14. System Metrics

### GET /system/metrics

System resource usage over a time range.

**Query Parameters:** `range` — e.g. `300`, `5m`, `1h` (default: 300 seconds)

**Response:**
```json
{
  "ok": true,
  "data": {
    "timeseries": [
      {
        "ts": 1742291040,
        "cpu": 12.5,
        "mem": 2048,
        "disk_rps": 100,
        "disk_wps": 50,
        "net_rxps": 1024,
        "net_txps": 512,
        "proc_cpu": 8.2,
        "proc_rss_mb": 64
      }
    ],
    "now": "2026-03-18T10:43:00Z",
    "devices": {
      "connected": 275,
      "disconnected": 0,
      "unknown": 0
    }
  }
}
```

---

### GET /system/summary

Compact status snapshot — good for a status bar or dashboard header.

**Response:**
```json
{
  "ok": true,
  "devicesConnected": 275,
  "defaultDbOk": true,
  "jobsRunning": 1
}
```

---

## 15. Database Metrics

### GET /db/metrics

Database write performance metrics (latency, error rate).

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| target_id | string | Specific DB target (uses default if omitted) |
| range | string | Time range e.g. `300s`, `1h` |

**Response:**
```json
{
  "ok": true,
  "data": {
    "targetId": "db_1773214350018",
    "writeP50": 14.0,
    "writeP95": 18.0,
    "errorPct": 0.0,
    "writes": 275,
    "writeErrors": 0
  }
}
```

---

## 16. Reports

These endpoints return CSV — pass to a `<a href>` download link or parse on frontend.

### GET /reports/runs.csv

Export job run history as CSV.

**Query Parameters:**

| Param | Description |
|-------|-------------|
| job_id | Filter by job (all if omitted) |
| frm | Start date (ISO 8601) |
| to | End date (ISO 8601) |

**CSV columns:**
```
id, job_id, started_at, stopped_at, duration_ms, rows, read_lat_avg, write_lat_avg, error_pct
```

---

### GET /reports/errors.csv

Export aggregated error log as CSV.

**Query Parameters:** `job_id` (optional)

**CSV columns:**
```
job_id, code, count, last_message, last_ts
```

---

## 17. WebSocket

### WS /ws/logs

Real-time notification stream. Connects via Redis pub/sub channel `logger_read`.

**Connection:**
```
ws://127.0.0.1:5175/ws/logs?token=YOUR_JWT_TOKEN
```

**Auth:** JWT required. Pass as `?token=` query param (headers not supported by browsers on WS).
**Role required:** `logger_read`

**JavaScript example:**
```javascript
const token = 'YOUR_JWT_TOKEN'; // from POST /auth/login

const ws = new WebSocket(`ws://127.0.0.1:5175/ws/logs?token=${token}`);

ws.onopen = () => {
  console.log('Connected to notification stream');
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log('Notification:', msg);
  // msg.type: "job" | "alert" | "info" | "warning" | "error"
};

ws.onerror = (err) => console.error('WS error:', err);

ws.onclose = (event) => {
  console.log('Closed:', event.code, event.reason);
  // Reconnect logic here
};
```

**Incoming message format:**
```json
{
  "type": "job",
  "action": "create",
  "notification_id": "a1b2c3d4-...",
  "message": "Job job_1773829817113 was started by rohith",
  "user": "aed23084-...",
  "read": false,
  "time": "2026-03-18T10:43:00Z"
}
```

**Message types:**

| type | When it fires |
|------|--------------|
| `job` | Job started, stopped, or paused |
| `alert` | Trigger condition fired |
| `info` | General system info |
| `warning` | Non-critical issue |
| `error` | Error condition |

**Close codes:**

| Code | Meaning |
|------|---------|
| 1000 | Normal closure |
| 1008 | Authentication failed (bad/missing token) |
| 1011 | Server error (e.g. Redis unavailable) |

> **Reconnect:** The server does not send keepalive pings. Implement reconnect logic on `onclose` with exponential backoff.

---

## 18. Error Reference

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request / validation error |
| 401 | Unauthorized (missing or invalid JWT) |
| 403 | Forbidden (insufficient role) |
| 404 | Not found |
| 429 | Rate limited |
| 500 | Server error |
| 502 | Bad gateway (Keycloak unavailable) |

### Error response format

All errors follow this shape:
```json
{
  "detail": {
    "success": false,
    "error": "TOKEN_EXPIRED",
    "message": "Token has expired"
  }
}
```

### Application Error Codes

**Auth:**
`TOKEN_EXPIRED`, `INVALID_TOKEN`, `INSUFFICIENT_ROLE`

**Devices:**
`NAME_REQUIRED`, `PROTOCOL_INVALID`, `GATEWAY_NOT_FOUND`, `DEVICE_NOT_FOUND`

**Gateways:**
`NAME_AND_HOST_REQUIRED`, `PROTOCOL_HINT_INVALID`, `INVALID_PORTS`

**Mappings:**
`DEVICE_NOT_BOUND`, `MAPPING_INCOMPLETE`, `MAPPING_TYPE_MISMATCH`, `TAG_UNREADABLE`

**Jobs:**
`JOB_NOT_FOUND`, `NO_TABLES`, `NO_MAPPED_COLUMNS`, `JOB_DELETE_FAILED`, `NO_JOB_IDS`

**Protocols:**
`PROTOCOL_IN_USE`, `PROTOCOL_NOT_SUPPORTED`, `MODBUS_HOST_MISSING`

---

## Quick Reference

### Modbus encoding types

| Encoding | Data type | Register count | Description |
|----------|-----------|----------------|-------------|
| `float32` | float | 2 | IEEE 754 single-precision |
| `float64` | float | 4 | IEEE 754 double-precision |
| `uint16` | int | 1 | Unsigned 16-bit integer |
| `uint16_enum` | int | 1 | Enum value (status codes) |
| `int16` | int | 1 | Signed 16-bit integer |
| `uint32` | int | 2 | Unsigned 32-bit integer |
| `int32` | int | 2 | Signed 32-bit integer |
| `bool16` | bool | 1 | Boolean stored as 16-bit |

### Database providers

| Provider | Connection string |
|----------|-------------------|
| PostgreSQL | `postgresql://user:pass@host:5432/dbname` |
| SQLite | `/path/to/database.db` |
| SQL Server | `mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+17+for+SQL+Server` |
| MySQL | `mysql+pymysql://user:pass@host:3306/dbname` |

### Data table location (PostgreSQL)

All time-series data is written to the `neuract` schema:
```sql
SELECT * FROM neuract.mfm_001 ORDER BY timestamp_utc DESC LIMIT 10;
SELECT * FROM neuract.ahu_001 ORDER BY timestamp_utc DESC LIMIT 10;
```

Every table has `timestamp_utc TIMESTAMPTZ` as the first column, followed by one column per schema field.
