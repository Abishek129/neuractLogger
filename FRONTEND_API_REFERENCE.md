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
19. [Electrical Equipment](#19-electrical-equipment)

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

---

## 19. Electrical Equipment

Prefix: `/equipment`. All routes need a token: reads need `logger_read`, writes need `logger_write`. This section backs the **Electrical Elements** screen: the list, adding, and the edit panel.

**Model:**
- **Category:** read-only here and edited in the DB. Its `type` is `single` or `distribution`, and it carries:
  - **`fields`:** the electrical fields (id, label, kind `quantity` / `choice` / `text`, units or options, `required`, and an optional `role` of `voltage`, `voltage.in` or `voltage.out`).
  - **`defaultCapacity`:** single categories only.

  Seeded categories: Source, Transformer, HT Panel, LT Panel and Load.
- **Equipment:** name, category, `subtype`, `spare` ("not on map"), `description`, and `values` (field id → `{value, unit}`).
- **Connection nodes:**
  - **Distribution equipment** has buses (Bus A, B…). Each bus has incomer and outgoer capacity, allowed categories, attached equipment, MFMs metering its incomer and outgoer **points**, and a coupler flag to the next bus.
  - **Single equipment** has the same rules on itself: `maxIncomers` / `maxOutgoers`, `incomingCategories` / `outgoingCategories`, and MFMs.
- **Attaching equipment to a bus checks both ends:** the bus side, and, if the attached equipment is single, its own side as well. Equipment can be fed from several places, and loops are rejected.

**Errors:** `{"detail": "CODE"}` or `{"detail": "CODE: context"}`, with 400 for validation, 404 for missing records and 409 for conflicts.

### GET /equipment/categories
```json
{ "items": [
  { "id": "transformer", "name": "Transformer", "type": "single", "sortOrder": 2,
    "fields": [ { "id": "primary_voltage", "label": "Primary voltage", "kind": "quantity", "units": ["kV","V"], "required": true, "role": "voltage.in" },
                { "id": "secondary_voltage", "label": "Secondary voltage", "kind": "quantity", "units": ["kV","V"], "required": true, "role": "voltage.out" },
                { "id": "rated_capacity", "label": "Rated capacity", "kind": "quantity", "units": ["kVA","MVA"], "required": true },
                { "id": "phase", "label": "Phase", "kind": "choice", "options": ["3 Phase","1 Phase"], "required": true } ],
    "defaultCapacity": { "incomers": 1, "outgoers": 1 } },
  { "id": "lt_panel", "name": "LT Panel", "type": "distribution", "sortOrder": 4,
    "fields": [ { "id": "bus_voltage", "label": "Bus / operating voltage", "kind": "quantity", "units": ["kV","V"], "required": true, "role": "voltage" } ] } ] }
```

### GET /equipment — the list
Query filters, all optional: `categoryId`, `type` (`single` / `distribution`), `q` (searches name and subtype), and `metered`, `ready`, `used`, `spare` (each `true` / `false`). Items come back in category order, then by name.

```json
{ "items": [
  { "id": "eq_…", "name": "TF-01", "categoryId": "transformer", "categoryName": "Transformer", "type": "single",
    "subtype": "33/11 kV", "spare": false, "description": null,
    "values": { "primary_voltage": { "value": 33.0, "unit": "kV" }, "secondary_voltage": { "value": 11.0, "unit": "kV" } },
    "voltage": { "in": "33 kV", "out": "11 kV", "text": "33 kV → 11 kV" },
    "readiness": { "ready": false, "missing": ["Rated capacity", "Phase"] },
    "used": true,
    "attachedTo": [ { "busId": "bus_…", "busName": "Bus A", "equipmentId": "eq_pcc", "equipmentName": "PCC-01", "role": "incomer" } ],
    "maxIncomers": 1, "maxOutgoers": 1, "incomingCategories": [], "outgoingCategories": ["lt_panel"],
    "metering": { "meterCount": 1, "meters": [
      { "deviceId": "dev_…", "deviceName": "MFM-04", "unitId": 4, "gatewayId": "gw_…", "gatewayName": "GIC-01",
        "host": "10.90.200.11", "port": 502, "protocol": "modbus", "status": "connected", "role": null } ] },
    "createdAt": "…Z", "updatedAt": "…Z" },
  { "id": "eq_pcc", "name": "PCC-01", "categoryId": "lt_panel", "type": "distribution", "subtype": "PCC",
    "voltage": { "in": "415 V", "out": null, "text": "415 V" }, "readiness": { "ready": true, "missing": [] }, "used": true,
    "metering": { "points": 20, "pointsMetered": 15, "meterCount": 15, "meters": [ … ] },
    "buses": [ <bus>, … ], … } ] }
```

The screen's columns map onto these keys:

| Column | Key |
|---|---|
| Element | `name`, plus `categoryName · subtype` |
| Voltage | `voltage.text` |
| Metering, single equipment | `metering.meters`, each shown as `deviceName · U{unitId}` / `gatewayName · host`; empty means "No meter attached" |
| Metering, panels | `metering.pointsMetered / metering.points` points metered · `meterCount` MFMs |
| Connection readiness | `readiness.ready`, plus `readiness.missing.length` fields missing |
| Map | `used` |
| "Spare" tag | `spare` |

`used` currently means the equipment is connected on a bus (attached to one, or a panel with something attached). It will switch to "placed on the map" once the map exists.

### POST /equipment — Add element
```json
{ "name": "TF-01", "categoryId": "transformer", "subtype": "33/11 kV", "spare": false, "description": null,
  "values": { "primary_voltage": { "value": "33", "unit": "kV" } },
  "maxIncomers": 1, "maxOutgoers": 1, "incomingCategories": ["ht_panel"], "outgoingCategories": ["lt_panel"] }
```
- **Required:** `name` (unique, ignoring case; 409 `EQUIPMENT_EXISTS`) and `categoryId`.
- **Distribution equipment** starts with **Bus A**.
- **Single equipment** starts with its category's `defaultCapacity`. The last four fields above are optional and apply to single equipment only.
- **Value errors:**
  - `FIELD_UNKNOWN`: the field doesn't belong to the category.
  - `FIELD_INVALID`: not a number ≥ 0, a unit that isn't allowed, a choice that isn't in the options, or text that isn't a string.
  - `VALUES_INVALID`: `values` isn't an object.

### GET /equipment/{id} · PUT /equipment/{id} · DELETE /equipment/{id}
**PUT** (the edit panel) accepts any of `name`, `categoryId`, `subtype`, `spare`, `description` and `values`. For single equipment it also accepts `maxIncomers`, `maxOutgoers`, `incomingCategories` and `outgoingCategories`.
- **`values` is a merge:** only the fields you send change, and `null` or an empty value clears one.
- **`categoryId`:** can only change to a category of the same type (`CATEGORY_TYPE_CHANGE`). Values of fields the new category doesn't have are dropped.
- **Capacity and category changes are checked against current connections:**
  - 409 `CAPACITY_BELOW_ATTACHED`: the new capacity is below the number already connected.
  - 409 `ATTACHED_OUTSIDE_CATEGORIES`: the new categories exclude something already connected.
  - 409 `CATEGORY_NOT_ALLOWED_ON_BUS`: the equipment is attached to a bus that doesn't allow the new category.

**DELETE** returns 409 `EQUIPMENT_IN_USE` while the equipment is attached to a bus. Otherwise it also removes its buses, their attachments and its MFM links; the devices and the attached equipment are kept.

### Buses (distribution equipment) — "Bus sections", "Bus section A / B", "Bus Coupling"

| Call | Body | Notes |
|---|---|---|
| `GET /equipment/{id}/buses` | — | 400 `BUSES_NOT_ALLOWED` on single equipment |
| `PUT /equipment/{id}/buses/count` | `{ "count": 2 }` | The "Bus sections" selector (1–26). Adds Bus A, B, C… at the end, or removes trailing buses; a bus with equipment or MFMs on it is never removed (409 `BUS_NOT_EMPTY`). The new last bus's coupler is cleared |
| `POST /equipment/{id}/buses` | `{ "name"?, "incomers"?, "outgoers"?, "incomingCategories"?, "outgoingCategories"? }` | Adds one bus |
| `PUT /equipment/buses/{busId}` | `{ "name"?, "sortOrder"?, "incomers"?, "outgoers"?, "coupledNext"?, "incomingCategories"?, "outgoingCategories"? }` | `incomers` = "Maximum incomers" and `outgoers` = "Outgoing feeder capacity" (0–999). `coupledNext: true` couples this bus with the next one ("Section A ↔ Section B"); the last bus can't be coupled (400 `NO_NEXT_BUS`). The checks match equipment PUT, plus 409 `CAPACITY_BELOW_METERED` |
| `DELETE /equipment/buses/{busId}` | — | 409 `LAST_BUS` or `BUS_NOT_EMPTY` |

Bus object:
```json
{ "id": "bus_…", "equipmentId": "eq_pcc", "name": "Bus A", "sortOrder": 0, "incomers": 1, "outgoers": 9, "coupledNext": true,
  "incomingCategories": ["transformer"], "outgoingCategories": ["lt_panel", "load"],
  "incomingEquipment": [ { "id": "eq_tf", "name": "TF-01", "categoryId": "transformer", "categoryName": "Transformer", "type": "single" } ],
  "outgoingEquipment": [ … ], "spareIncomers": 0, "spareOutgoers": 7,
  "meters": [ { "deviceId": "dev_…", "deviceName": "MFM-04", "unitId": 4, "gatewayName": "GIC-01", "host": "10.90.200.11", "role": "incomer", … } ],
  "points": 10, "pointsMetered": 8 }
```

### Connecting equipment to buses
`POST /equipment/buses/{busId}/equipment` with `{ "equipmentId": "eq_…", "role": "incomer" | "outgoer" }`, and `DELETE /equipment/buses/{busId}/equipment/{equipmentId}`. Both return the bus.

The attach checks run in this order:
1. **Duplicates:** the equipment is already on this bus (409 `ALREADY_ATTACHED`).
2. **The bus side:**
   - its allowed categories (400 `CATEGORY_NOT_ALLOWED: Bus A …`);
   - a spare place on that side (409 `NO_SPARE`).
3. **The equipment's own side, if it is single equipment:**
   - feeding the bus (as an `incomer`) uses its **outgoing** side, and being fed (as an `outgoer`) uses its **incoming** side;
   - that side's allowed categories (400 `CATEGORY_NOT_ALLOWED: <name> …`);
   - that side's capacity (409 `NO_SPARE: <name> allows n …`). A Load has 0 outgoing by default, so it can't feed a bus.
4. **Self:** a panel can't be attached to its own bus (400 `SELF_ATTACH`).
5. **Loops:** 400 `CYCLE`.

### MFMs

| Call | Body | For |
|---|---|---|
| `POST /equipment/{id}/meters` | `{ "deviceId": "dev_…" }` | **Single** equipment: several MFMs on the equipment itself. On a distribution panel this returns 400 `USE_BUS_METERS` |
| `POST /equipment/buses/{busId}/meters` | `{ "deviceId": "dev_…", "role": "incomer" \| "outgoer" }` | **Distribution** panels: the MFM meters an incomer or outgoer point of that bus. At most as many per side as its capacity (409 `NO_FREE_POINT`) |
| `DELETE /equipment/{id}/meters/{deviceId}` · `DELETE /equipment/buses/{busId}/meters/{deviceId}` | — | Detach (404 `METER_NOT_ATTACHED`) |
| `GET /equipment/{id}/meters` | — | All MFMs of the equipment, including those on its buses |
| `GET /equipment/available_meters` | — | Devices not attached anywhere, with `unitId`, `gatewayName`, `host` |

A device is on one place only (409 `METER_IN_USE: attached to <where>`). `DELETE /devices/{id}` on an attached device returns 409 `DEVICE_ATTACHED_TO_EQUIPMENT`.

### Versions (If-Match)
- **The field:** every equipment has an integer `version` (and buses return `equipmentVersion`).
- **What bumps it:** any change to the equipment, its buses, rules, connections or meters. A connection change bumps both ends.
- **Writes:** every write route accepts `If-Match: <version>` of the equipment that owns what is being changed. A stale version answers 409 `VERSION_CONFLICT: <id>`; a non-integer one, 400 `IF_MATCH_INVALID`. Without the header, the last write wins.
- **Responses:** attach, detach, reorder and direct-link routes return both changed objects: `{"success": true, "item": <bus>, "owner": <equipment>, "attached": <equipment>}` (`item` only on bus routes).

### Feeder order
- **Positions:** every connection has a `position` (0-based, compact per node and side), shown on `incomingEquipment[]` / `outgoingEquipment[]` and `attachedTo[]`.
- **Attaching:** `POST /equipment/buses/{busId}/equipment` accepts an optional `position`.
- **Reordering:** `PUT /equipment/buses/{busId}/equipment/{equipmentId}` with `{"position": n}`.
- **Detaching:** a detach renumbers the rest.

### Bus meters naming their feeder
`POST /equipment/buses/{busId}/meters` accepts an optional `equipmentId`, the attached equipment the meter measures. It must sit on that bus on the same side (400 `FEEDER_NOT_ON_BUS`). It's returned as `meters[].equipmentId`, and set back to `null` if that feeder is detached.

### Direct links (single → single)

| Call | Body | Notes |
|---|---|---|
| `POST /equipment/{sourceId}/connections` | `{ "equipmentId": "<target>", "position"? }` | The source feeds the target (e.g. Grid → TF). Both must be single equipment (400 `USE_BUS` otherwise). It checks the source's outgoing side and the target's incoming side (categories, capacity), plus `ALREADY_ATTACHED`, `SELF_ATTACH` and `CYCLE` |
| `PUT /equipment/{sourceId}/connections/{targetId}` | `{ "position": n }` | Reorder |
| `DELETE /equipment/{sourceId}/connections/{targetId}` | — | Remove the link |

- **In responses:** the source lists its direct links in `outgoingEquipment[]`. The target's `attachedTo[]` includes `{"equipmentId": <source>, "role": "outgoer", "direct": true, "busId": null, "busName": null, "position": n}`.
- **Deleting:** deleting a target answers 409 `EQUIPMENT_IN_USE` while it is fed. Deleting a source removes its links.
- **Loops:** checked in flow direction across bus attachments and direct links. A bus incomer feeds the panel, a bus outgoer is fed by the panel, and a direct link goes from source to target.

**Not covered yet:** Import / Export (Excel), View / Upload Nameplate, View in map, and the map itself.

### Schema, device and job additions (2026-10-23)

| Route | Change |
|---|---|
| `GET /schemas/field_types` | DB-managed list of field `type` words: `{"items": [{id, label, encoding}]}`. `encoding` is the register decoding used for mapping rows (e.g. `real` → `float32`, `boolean` → `bool16`). Edited in the DB (`app_field_type`) |
| `GET /schemas/units` | DB-managed list of field units (`app_field_unit`). A field `unit` must be in it or empty (400 `UNIT_INVALID`) |
| `GET /schemas/{id}` | One schema, with `description` |
| `PATCH /schemas/{id}` | `{name?, description?}`. A duplicate name (ignoring case) is 409 `SCHEMA_EXISTS` |
| `POST /schemas` | Accepts `description`. Field types and units are validated against the two lists above |
| `PUT /devices/{id}` | Also applies `protocol` and `params` (merged; `null` removes a key; `"***"` keeps a stored secret), and `gatewayId: null`. An address change resets `status` to `disconnected` and clears `verification` |
| `GET /devices` | Each device has `verification: {ok, latencyMs, error, at}` or `null` |
| `POST /devices/{id}/quick_test` | Saves the result; the response includes `verification` |
| `GET /jobs2/{id}` | One job |
| `PATCH /jobs2/{id}` | `name`, `tables`, `intervalMs`, `enabled`, `cpuBudget`, `type`, `triggers`. 409 `JOB_RUNNING` while the job is running |
| `POST /jobs2/{id}/resume` | Only from `paused` (409 `JOB_NOT_PAUSED`). Sets the job back to running |

---

## 20. Alerts

Rules are set on the **schema** (the blueprint), inherited by every table of that schema, and can be overridden per table. The engine keeps one state per table field: normal, or the worst matching level. It records an event and sends a WebSocket/notification of type `alert` only when that state changes. **Rule edits apply at the next job restart.**

| Screen need | Call |
|---|---|
| Level list / colours | `GET /alerts/levels` → `{items:[{id,name,severity,color,sortOrder}]}` |
| Manage levels | `POST /alerts/levels {name,severity,color}`, `PUT /alerts/levels/{id}`, `DELETE /alerts/levels/{id}` |
| Schema rules | `GET/POST /schemas/{id}/alerts` `{fieldKey, alertId, op, threshold}`; `PUT/DELETE /schemas/{id}/alerts/{ruleId}` |
| Table rules (effective) | `GET /tables/{id}/alerts` → items with `source: schema \| overridden \| table \| disabled` |
| Override / disable / table-only rule | `PUT /tables/{id}/alerts {fieldKey, alertId, op?, threshold?, enabled?}` |
| Reset to schema rule | `DELETE /tables/{id}/alerts/{overrideId}` |
| Live badges | `GET /alerts/active?tableId=` |
| History | `GET /alerts/events?tableId=&frm=&to=&limit=` (`from`/`to` = `null` means normal) |

`op` is one of `> >= < <= == !=`, and `threshold` is a number. Errors: `OP_INVALID`, `THRESHOLD_INVALID`, `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `ALERT_RULE_EXISTS` (409), `RULE_REQUIRED`, `ALERT_LEVEL_IN_USE` (409). Full details are in API_DOCUMENTATION.md §25.

---

## 21. Electrical: hierarchy and MFM slots

| Need | Call |
|---|---|
| Navigation tree (EMS / Source / BMS → categories) | `GET /equipment/groups` |
| Equipment of one group | `GET /equipment?groupId=ems` |
| Meter a relation | `POST /equipment/buses/{busId}/meters {deviceId, role, equipmentId}` (`equipmentId` is required for incoming) |
| Add a spare MFM | `POST /equipment/buses/{busId}/meters {deviceId, role: "outgoer"}` |
| Move an MFM / make it a spare | `PUT /equipment/buses/{busId}/meters/{deviceId} {equipmentId \| null}` |
| Connect a feeder at a spare | `POST /equipment/buses/{busId}/equipment {equipmentId, role: "outgoer", spareDeviceId}` |

Bus: `incomingEquipment[].meter`, `outgoingEquipment[].meter`, `spares[]`, `spareMeters`, and `spareOutgoers` (free points). Codes: `EQUIPMENT_REQUIRED`, `FEEDER_NOT_ON_BUS`, `RELATION_METERED`, `NO_FREE_POINT`, `NO_SPARE`, `NOT_A_SPARE`. See mapping doc §13.

---

## 22. Elements: category + kind + type (2026-10-27, breaking)

| Need | Call |
|---|---|
| Categories (EMS / Source / BMS) and which kinds they allow | `GET /equipment/categories` |
| Type list / manage types and their fields | `GET` / `POST /equipment/types`, `PUT` / `DELETE /equipment/types/{id}` |
| Create an element | `POST /equipment {name, categoryId, kind, typeId?}` |
| Filter | `GET /equipment?categoryId=&kind=&typeId=&q=` |
| Allowed types on a bus or node side | `incomingTypes` / `outgoingTypes` |

Element keys: `categoryId`, `categoryName`, `kind`, `typeId`, `typeName`. **Gone:** `subtype`, `groupId`, `type`, and `/equipment/groups`. See mapping doc §14 for the full old → new table.

---

## 23. EMS import (spreadsheet)

| Need | Call |
|---|---|
| Template to fill | `GET /equipment/import/ems/template` (xlsx download) |
| Preview / validate | `POST /equipment/import/ems?dryRun=true`, form field `file` |
| Import | `POST /equipment/import/ems`, form field `file`. 200 when saved; 400 `IMPORT_INVALID` with `results[]` when anything failed (nothing saved) |

Show `results[]` grouped by `sheet` and `row`, with `status` / `error`. See mapping doc §15.

---

## 24. Zones and export

| Need | Call |
|---|---|
| Zone list / manage | `GET` / `POST /equipment/zones`, `PUT` / `DELETE /equipment/zones/{id}` |
| Element's zone | `zoneId` on create/edit; `zoneName` in the output; filter `?zoneId=` |
| Export button | `GET /equipment/export/ems` (optional `?typeId=`): an xlsx download in the plant template layout |

---

## 25. MFMs = logger tables (breaking)

Replace `deviceId` with **`tableId`** in every meter call, and `spareDeviceId` with `spareTableId`. The MFM picker (`GET /equipment/available_meters`) now lists logger tables, with `schemaName` and `deviceName`. Show an MFM as `tableName`, with its schema and device underneath. See mapping doc §17.
