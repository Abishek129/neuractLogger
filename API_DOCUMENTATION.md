# LoggerFast API Reference

**Base URL:** `http://127.0.0.1:5175`
**Content-Type:** `application/json` (except CSV endpoints)
**Authentication:** Keycloak JWT Bearer tokens

---

## Table of Contents

1. [Health & System](#1-health--system)
2. [Authentication](#2-authentication)
3. [Schemas](#3-schemas)
4. [Tables](#4-tables)
5. [Devices](#5-devices)
6. [Protocol Types](#6-protocol-types)
7. [Bulk Import](#7-bulk-import)
8. [Gateways](#8-gateways)
9. [Network Diagnostics](#9-network-diagnostics)
10. [Mappings](#10-mappings)
11. [Jobs](#11-jobs)
12. [Storage Targets](#12-storage-targets)
13. [System Metrics](#13-system-metrics)
14. [Database Metrics](#14-database-metrics)
15. [Reports](#15-reports)
16. [Notifications](#16-notifications)
17. [WebSocket — Real-time Notifications](#17-websocket--real-time-notifications)
18. [Debug](#18-debug)
19. [Authentication & Authorization](#19-authentication--authorization)
20. [Error Codes](#20-error-codes)
21. [Supported Protocols](#21-supported-protocols)
22. [Database Providers](#22-database-providers)
23. [Environment Variables](#23-environment-variables)

---

## 1. Health & System

### GET /health

Returns agent health status.

**Response:**
```json
{
  "status": "ok",
  "agent": "plc-agent",
  "version": "1.0.0"
}
```

### GET /version

Returns detailed version and tech stack info.

**Response:**
```json
{
  "appVersion": "1.0.0",
  "python": "3.11.6",
  "platform": "Linux-6.18.6-arch1-1-x86_64-with-glibc2.41",
  "fastapi": "0.115.6",
  "sqlalchemy": "2.0.36",
  "uvicorn": "0.34.0",
  "port": 5175
}
```

### POST /shutdown

Gracefully shuts down the agent (200ms delay for response flush).

**Response:**
```json
{
  "ok": true,
  "message": "shutting_down"
}
```

---

## 2. Authentication

Prefix: `/auth`

### POST /auth/register

Create a new user in Keycloak.

**Request Body:**
```json
{
  "username": "john",
  "email": "john@example.com",
  "password": "secret123",
  "first_name": "John",
  "last_name": "Doe",
  "enabled": true
}
```

| Field | Type | Required | Default |
|-------|------|----------|---------|
| username | string | Yes | — |
| email | string | Yes | — |
| password | string | Yes | — |
| first_name | string | No | `""` |
| last_name | string | No | `""` |
| enabled | boolean | No | `true` |

**Response (200):**
```json
{
  "ok": true,
  "user_id": "aed23084-0997-4e2e-8c2c-01d1dc866044",
  "username": "john",
  "email": "john@example.com"
}
```

### POST /auth/login

Authenticate and get JWT tokens.

**Request Body:**
```json
{
  "username": "rohith",
  "password": "neuract"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "expires_in": 300,
  "refresh_expires_in": 1800,
  "refresh_token": "eyJhbGciOiJIUzUxMiIs...",
  "token_type": "Bearer",
  "not-before-policy": 0,
  "session_state": "...",
  "scope": "profile email"
}
```

### POST /auth/assign-role/{username}

Assign `neuract-admin` client role to a user.

**Path Parameters:** `username` (string)

**Response (200):**
```json
{
  "ok": true,
  "username": "john",
  "user_id": "aed23084-...",
  "client": "neuract_owner",
  "role": "neuract-admin"
}
```

---

## 3. Schemas

### GET /schemas

List all schemas.

**Response:**
```json
{
  "items": [
    {
      "id": "schema_1",
      "name": "Temperature Sensors",
      "fields": [
        {
          "key": "temperature",
          "type": "float",
          "unit": "°C",
          "scale": 0.1,
          "desc": "Ambient temperature"
        }
      ]
    }
  ]
}
```

### POST /schemas

> **Auth:** Requires `logger_write` role

Create a new schema.

**Request Body:**
```json
{
  "id": "temp_schema",
  "name": "Temperature Schema",
  "fields": [
    { "key": "temperature", "type": "float", "unit": "°C", "scale": 0.1 },
    { "key": "humidity", "type": "float", "unit": "%", "desc": "Relative humidity" }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | No | Auto-generated if omitted |
| name | string | Yes | Schema display name |
| fields | array | Yes | At least one field |
| fields[].key | string | Yes | Alphanumeric + underscore only |
| fields[].type | string | No | Data type |
| fields[].unit | string | No | Unit label |
| fields[].scale | number | No | Scale factor |
| fields[].desc | string | No | Description |

**Response (200):**
```json
{
  "success": true,
  "message": "schema_created",
  "item": { "id": "temp_schema", "name": "Temperature Schema", "fields": [...] }
}
```

### GET /schemas/export

Export all schemas.

**Response:**
```json
{
  "schemas": [ ... ]
}
```

### POST /schemas/import

> **Auth:** Requires `logger_write` role

Import schemas from export payload.

**Request Body:**
```json
{
  "schemas": [ ... ]
}
```

**Response:**
```json
{
  "imported": 3
}
```

### DELETE /schemas/{schema_id}

> **Auth:** Requires `logger_write` role

Delete a schema. Fails if tables are linked to it.

**Response (success):**
```json
{
  "success": true
}
```

**Response (schema has linked tables):**
```json
{
  "detail": "SCHEMA_IN_USE"
}
```

---

## 4. Tables

Prefix: `/tables`

### GET /tables

List tables with pagination and filters.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| parentSchemaId | string | — | Filter by schema |
| dbTargetId | string | — | Filter by DB target |
| status | string | — | `"migrated"` or `"not_migrated"` |
| name | string | — | Name filter |
| page | int | 1 | Page number |
| pageSize | int | 50 | Items per page |

**Response:**
```json
{
  "success": true,
  "total": 25,
  "page": 1,
  "items": [
    {
      "id": "table_1",
      "name": "sensor_data",
      "schemaId": "schema_1",
      "dbTargetId": "target_1",
      "status": "migrated",
      "lastMigratedAt": "2025-01-15T10:30:00Z",
      "parentSchema": { "id": "schema_1", "name": "Temperature Schema" },
      "dbTarget": { "id": "target_1" },
      "columnCount": 3,
      "mappingExists": true,
      "mappingStatus": "Mapped",
      "mappingRows": { "temperature": { "protocol": "modbus", "address": "100" } }
    }
  ]
}
```

### POST /tables/bulk_create

> **Auth:** Requires `logger_write` role

Create one or more tables.

**Request Body:**
```json
{
  "parentSchemaId": "schema_1",
  "names": ["sensor_01", "sensor_02"],
  "dbTargetId": "target_1",
  "deviceId": "dev_123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parentSchemaId` | string | Yes | Schema ID to use |
| `names` / `name` / `pattern` | string[] / string | Yes | Table name(s), supports `{1..10}` patterns |
| `dbTargetId` | string | No | Storage target (defaults to system default) |
| `deviceId` | string | No | Device to bind to the created tables |

Supports pattern expansion: `"pattern": "sensor_{1..10}"` generates `sensor_1` through `sensor_10`.

**Response:**
```json
{
  "success": true,
  "message": "tables_created",
  "count": 2,
  "items": [ ... ],
  "warnings": [
    { "original": "Sensor 01", "normalized": "sensor_01" }
  ]
}
```

### POST /tables/bulk_update_target

> **Auth:** Requires `logger_write` role

Update database target for multiple tables.

**Request Body:**
```json
{
  "dbTargetId": "target_2",
  "ids": ["table_1", "table_2"]
}
```

**Response:**
```json
{
  "success": true,
  "updated": 2,
  "items": [ ... ]
}
```

### GET /tables/discover

Discover planned (not yet migrated) and migrated tables.

**Query Parameters:** `dbTargetId` (optional)

**Response:**
```json
{
  "success": true,
  "planned": [ ... ],
  "migrated": [ ... ]
}
```

### GET /tables/{table_id}

Get table details with schema and mapping health.

**Response:**
```json
{
  "success": true,
  "item": { ... },
  "schema": { "id": "schema_1", "name": "...", "fields": [...] },
  "mappingHealth": "Mapped"
}
```

### POST /tables/dry_run_ddl

> **Auth:** Requires `logger_write` role

Preview SQL DDL without executing.

**Request Body:**
```json
{
  "ids": ["table_1", "table_2"]
}
```

**Response:**
```json
{
  "success": true,
  "items": [
    {
      "id": "table_1",
      "name": "neuract.sensor_data",
      "operations": [
        "CREATE TABLE neuract.sensor_data (timestamp_utc DATETIME NOT NULL, temperature REAL, humidity REAL)",
        "CREATE INDEX IF NOT EXISTS idx_sensor_data_ts ON neuract.sensor_data(timestamp_utc)"
      ]
    }
  ]
}
```

### POST /tables/migrate

> **Auth:** Requires `logger_write` role

Create or update tables in the target database.

**Request Body:**
```json
{
  "ids": ["table_1", "table_2"]
}
```

**Response:**
```json
{
  "success": true,
  "items": [
    { "id": "table_1", "name": "neuract.sensor_data", "status": "created" },
    { "id": "table_2", "name": "neuract.pump_data", "status": "updated" }
  ]
}
```

### DELETE /tables/{table_id}

> **Auth:** Requires `logger_write` role

Delete a table from the meta DB. Optionally drops the physical table in the target DB.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `dropPhysical` | boolean | `false` | Also drop the physical table and mapping rows in the target DB |

**Response:**
```json
{
  "success": true,
  "message": "table_deleted",
  "physicalDropped": false
}
```

**Error Responses:**
- `404` — `TABLE_NOT_FOUND`
- `409` — `TABLE_HAS_RUNNING_JOBS` (table is part of a running job)

---

### PATCH /tables/{table_id}

> **Auth:** Requires `logger_write` role

Update table properties (name, schema, target DB).

**Request Body:**
```json
{
  "name": "new_table_name",
  "schemaId": "sch_123",
  "dbTargetId": "db_456"
}
```
All fields are optional — only include fields to update.

**Response:**
```json
{
  "success": true,
  "item": { "id": "tbl_1", "name": "new_table_name", "schemaId": "sch_123", ... },
  "warnings": ["Table is migrated; name change requires re-migration"]
}
```

**Error Responses:**
- `400` — `INVALID_NAME`, `SCHEMA_NOT_FOUND`, `NO_FIELDS_TO_UPDATE`
- `404` — `TABLE_NOT_FOUND`

---

### POST /tables/{table_id}/bind_device

> **Auth:** Requires `logger_write` role

Bind a device to a table.

**Request Body:**
```json
{
  "deviceId": "dev_123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "device_bound",
  "tableId": "tbl_1",
  "deviceId": "dev_123"
}
```

**Error Responses:**
- `400` — `DEVICE_ID_REQUIRED`
- `404` — `TABLE_NOT_FOUND`, `DEVICE_NOT_FOUND`

---

### POST /tables/{table_id}/unbind_device

> **Auth:** Requires `logger_write` role

Remove device binding from a table.

**Response:**
```json
{
  "success": true,
  "message": "device_unbound",
  "tableId": "tbl_1"
}
```

**Error Responses:**
- `404` — `TABLE_NOT_FOUND`

---

### POST /tables/{table_id}/mappings/bulk

> **Auth:** Requires `logger_write` role

Bulk update mapping rows for a table. Delegates to `POST /mappings/{table_id}/bulk_apply`.

**Request Body:**
```json
{
  "deviceId": "dev_123",
  "rows": {
    "temperature": { "protocol": "modbus", "address": "0", "dataType": "float", "encoding": "float32" },
    "status": { "protocol": "modbus", "address": "2", "dataType": "int", "encoding": "uint16_enum" }
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "mapping_upserted",
  "item": { "deviceId": "dev_123", "rows": { ... } }
}
```

---

### POST /tables/{table_id}/mappings/validate

> **Auth:** Requires `logger_write` role

Validate mapping rows for a table. Delegates to `POST /mappings/{table_id}/validate`.

**Response:**
```json
{
  "success": true,
  "health": "Mapped",
  "problems": []
}
```

If issues are found:
```json
{
  "success": false,
  "health": "Partially Mapped",
  "problems": [
    { "field": "temperature", "code": "TAG_UNREADABLE" }
  ]
}
```

---

## 5. Devices

Prefix: `/devices`

### GET /devices

List all devices.

**Response:**
```json
{
  "items": [
    {
      "id": "device_1",
      "name": "Modbus Sensor 01",
      "protocol": "modbus",
      "gatewayId": "gateway_1",
      "port": 502,
      "unitId": 1,
      "status": "connected",
      "latencyMs": 45,
      "lastError": null,
      "params": { "host": "192.168.1.100" },
      "autoReconnect": true
    }
  ]
}
```

### POST /devices

> **Auth:** Requires `logger_write` role

Create a device (also performs connection test).

**Request Body:**
```json
{
  "name": "Modbus Sensor",
  "protocol": "modbus",
  "gatewayId": "gateway_1",
  "port": 502,
  "unitId": 1,
  "params": { "host": "192.168.1.100" }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| name | string | Yes | Device display name |
| protocol | string | No | `"modbus"` or `"opcua"` |
| gatewayId | string | No | Link to gateway |
| port | int | No | Connection port |
| unitId | int | No | Modbus unit ID |
| params | object | No | Protocol-specific parameters |
| autoReconnect | boolean | No | Auto-reconnect on failure |

**Response:**
```json
{
  "success": true,
  "item": { ... },
  "error": null
}
```

### PUT /devices/{dev_id}

> **Auth:** Requires `logger_write` role

Update device metadata (partial update).

**Request Body:**
```json
{
  "name": "Updated Name",
  "autoReconnect": false,
  "unitId": 2,
  "port": 503,
  "gatewayId": "gateway_2"
}
```

**Response:**
```json
{
  "success": true,
  "item": { ... }
}
```

### DELETE /devices/{dev_id}

Delete a device.

**Response:**
```json
{
  "success": true
}
```

### POST /devices/{dev_id}/connect

> **Auth:** Requires `logger_write` role

Test connection and mark device as connected.

**Response:**
```json
{
  "success": true,
  "latencyMs": 42
}
```

### POST /devices/{dev_id}/disconnect

> **Auth:** Requires `logger_write` role

Mark device as disconnected.

**Response:**
```json
{
  "success": true
}
```

### POST /devices/{dev_id}/quick_test

> **Auth:** Requires `logger_write` role

Quick connection test without changing device state.

**Response:**
```json
{
  "success": true,
  "latencyMs": 38,
  "error": null
}
```

---

## 6. Protocol Types

Prefix: `/protocol_types`

### GET /protocol_types

List all registered protocol types.

**Response:**
```json
{
  "items": [
    { "type": "modbus" },
    { "type": "opcua" }
  ]
}
```

### POST /protocol_types

Add a new protocol type.

**Request Body:**
```json
{
  "type": "custom_protocol"
}
```

**Response:**
```json
{
  "success": true,
  "item": { "type": "custom_protocol" }
}
```

### DELETE /protocol_types/{protocol_type}

Delete a protocol type. Fails if devices or gateways are using it.

**Response:**
```json
{
  "success": true
}
```

---

## 7. Bulk Import

Prefix: `/bulk_import`

### POST /bulk_import/devices

Import devices from spreadsheet data. Auto-creates gateways by IP.

**Request Body:**
```json
{
  "devices": [
    {
      "name": "Device 1",
      "ip": "192.168.1.100",
      "port": 502,
      "mac": "AA:BB:CC:DD:EE:FF",
      "protocol": "modbus",
      "unit": 1,
      "connections": "Factory Floor"
    },
    {
      "name": "OPC UA Device",
      "ip": "192.168.1.101",
      "protocol": "opcua",
      "port": 4840
    }
  ]
}
```

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| name | string | Yes | — | Device name |
| ip | string | Yes | — | IP for gateway lookup/creation |
| port | int | No | — | Connection port |
| mac | string | No | — | MAC address |
| protocol | string | No | `"modbus"` | Protocol type |
| unit | int | No | — | Modbus unit ID (1-247) |
| connections | string | No | — | Gateway name |

**Response:**
```json
{
  "success": true,
  "summary": {
    "total": 2,
    "created_gateways": 1,
    "created_devices": 2,
    "skipped": 0,
    "failed": 0
  },
  "results": [
    {
      "row": 0,
      "status": "created",
      "device": { ... },
      "gateway": { ... },
      "gateway_created": true,
      "connected": true,
      "latencyMs": 42,
      "message": "Device created with new gateway"
    }
  ]
}
```

---

## 8. Gateways

Prefix: `/networking/gateways`

### GET /networking/gateways

List all gateways.

**Response:**
```json
{
  "items": [
    {
      "id": "gateway_1",
      "name": "Main PLC Gateway",
      "host": "192.168.1.50",
      "protocol_hint": "modbus",
      "ports": [502, 503],
      "status": "active"
    }
  ]
}
```

### GET /networking/gateways_with_devices

List gateways with their linked devices.

**Response:**
```json
{
  "items": [
    {
      "id": "gateway_1",
      "name": "Main PLC Gateway",
      "host": "192.168.1.50",
      "devices": [ ... ],
      "deviceCount": 5
    }
  ]
}
```

### POST /networking/gateways

Add a gateway.

**Request Body:**
```json
{
  "name": "New Gateway",
  "host": "192.168.1.55",
  "protocol_hint": "modbus",
  "ports": [502]
}
```

**Response:**
```json
{
  "success": true,
  "item": { ... }
}
```

### PUT /networking/gateways/{gid}

Update a gateway (partial update).

**Request Body:**
```json
{
  "name": "Updated Name",
  "ports": [502, 503, 504]
}
```

**Response:**
```json
{
  "success": true,
  "item": { ... }
}
```

### DELETE /networking/gateways/{gid}

Delete a gateway. Fails if devices are linked to it (400).

**Response:**
```json
{
  "success": true
}
```

### POST /networking/gateways/{gid}/ping

ICMP ping a gateway. Rate-limited (3 second minimum interval, 429 if too frequent).

**Request Body:**
```json
{
  "count": 4,
  "timeoutMs": 800
}
```

**Response:**
```json
{
  "ok": true,
  "lossPct": 0,
  "min": 15,
  "avg": 20,
  "max": 28,
  "samples": [15, 20, 28, 18]
}
```

### POST /networking/gateways/{gid}/tcp

TCP port test on a gateway.

**Request Body:**
```json
{
  "ports": [502, 503],
  "timeoutMs": 1000
}
```

**Response:**
```json
{
  "ok": true,
  "results": [
    { "port": 502, "ok": true, "status": "open", "timeMs": 45 },
    { "port": 503, "ok": false, "status": "closed", "timeMs": 0 }
  ]
}
```

---

## 9. Network Diagnostics

Prefix: `/networking`

### GET /networking/nics

List active network interfaces.

**Response:**
```json
{
  "items": [
    {
      "id": "eth0",
      "label": "Ethernet",
      "ip": "192.168.1.20",
      "cidr": 24,
      "gateway": null
    }
  ]
}
```

### POST /networking/ping

ICMP ping any host.

**Request Body:**
```json
{
  "target": "192.168.1.100",
  "count": 4,
  "timeoutMs": 800
}
```

`host` is also accepted as an alias for `target`.

**Response:**
```json
{
  "ok": true,
  "lossPct": 0,
  "min": 12,
  "avg": 18,
  "max": 25,
  "samples": [12, 18, 25, 17]
}
```

### POST /networking/tcp_test

TCP port connectivity test.

**Request Body:**
```json
{
  "host": "192.168.1.100",
  "port": 502,
  "timeoutMs": 1000
}
```

**Response:**
```json
{
  "ok": true,
  "status": "open",
  "timeMs": 45
}
```

Status values: `"open"`, `"timeout"`, `"closed"`

### POST /networking/modbus/test

Test Modbus TCP register read.

**Request Body:**
```json
{
  "host": "192.168.1.100",
  "port": 502,
  "unitId": 1,
  "address": 0,
  "count": 1
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| deviceId | string | — | Read host/port from device config |
| host / ip | string | — | Direct host |
| port | int | 502 | Modbus port |
| unitId | int | 1 | Slave address |
| address | int | 1 | Register address |
| count | int | 1 | Number of registers |

**Response:**
```json
{
  "ok": true,
  "protocol": "modbus",
  "values": [1234],
  "latencyMs": 52
}
```

### POST /networking/opcua/test

Test OPC UA endpoint (optionally read a node).

**Request Body:**
```json
{
  "endpoint": "opc.tcp://192.168.1.100:4840/freeopcua/server/",
  "nodeId": "ns=2;i=2"
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| deviceId | string | — | Read endpoint from device config |
| endpoint | string | `opc.tcp://127.0.0.1:4840` | OPC UA endpoint URL |
| nodeId | string | — | If provided, reads the node value |

**Response:**
```json
{
  "ok": true,
  "protocol": "opcua",
  "endpoint": "opc.tcp://192.168.1.100:4840/freeopcua/server/",
  "value": 45.5,
  "latencyMs": 120
}
```

### POST /networking/opcua/browse

Browse OPC UA node tree.

**Request Body:**
```json
{
  "endpoint": "opc.tcp://192.168.1.100:4840/freeopcua/server/",
  "nodeId": "i=85"
}
```

| Field | Type | Default |
|-------|------|---------|
| endpoint | string | `opc.tcp://127.0.0.1:4840/freeopcua/server/` |
| nodeId | string | `i=85` (Objects root) |

**Response:**
```json
{
  "ok": true,
  "items": [
    { "nodeId": "ns=0;i=84", "browseName": "0:Objects" },
    { "nodeId": "ns=0;i=86", "browseName": "0:Views" }
  ]
}
```

---

## 10. Mappings

Prefix: `/mappings`

Mappings bind schema fields to device registers/nodes.

### GET /mappings/{table_id}

Get mapping for a table.

**Response:**
```json
{
  "success": true,
  "item": {
    "tableId": "table_1",
    "deviceId": "device_1",
    "rows": {
      "temperature": {
        "protocol": "modbus",
        "address": "100",
        "dataType": "float",
        "encoding": "float32",
        "scale": 0.1,
        "deadband": 0.5
      },
      "humidity": {
        "protocol": "modbus",
        "address": "102",
        "dataType": "float",
        "encoding": "float32",
        "scale": 1.0
      }
    }
  },
  "health": "Mapped"
}
```

Health values: `"Mapped"`, `"Partially Mapped"`, `"Unmapped"`

### POST /mappings/{table_id}

Upsert mapping (partial update — merges with existing rows).

**Request Body:**
```json
{
  "deviceId": "device_1",
  "dbTargetId": "target_1",
  "rows": {
    "temperature": {
      "protocol": "modbus",
      "address": "100",
      "encoding": "float32",
      "scale": 0.1
    }
  }
}
```

**Response:**
```json
{
  "success": true,
  "item": { ... },
  "health": "Partially Mapped"
}
```

### POST /mappings/{table_id}/bulk_apply

Replace all rows at once.

**Request Body:**
```json
{
  "deviceId": "device_1",
  "dbTargetId": "target_1",
  "rows": { ... }
}
```

### POST /mappings/{table_id}/import

Import mapping (full replacement).

**Request Body:**
```json
{
  "mapping": {
    "deviceId": "device_1",
    "rows": { ... }
  }
}
```

### POST /mappings/{table_id}/validate

Validate mapping. Checks device binding, field completeness, and live-read.

**Request Body (optional):**
```json
{
  "rows": { ... },
  "deviceId": "device_1"
}
```

**Response:**
```json
{
  "success": true,
  "health": "Mapped",
  "problems": [
    {
      "field": "temperature",
      "code": "TAG_UNREADABLE"
    }
  ]
}
```

Problem codes: `DEVICE_NOT_BOUND`, `MAPPING_INCOMPLETE`, `MAPPING_TYPE_MISMATCH`, `TAG_UNREADABLE`

### DELETE /mappings/{table_id}/{field_key}

Delete a single field mapping.

**Response:**
```json
{
  "success": true,
  "message": "row_deleted",
  "item": { ... }
}
```

### GET /mappings/{table_id}/export

Export mapping for a table.

**Response:**
```json
{
  "mapping": {
    "deviceId": "device_1",
    "rows": { ... }
  }
}
```

### POST /mappings/{src_table_id}/copy_to/{dst_table_id}

Copy mapping between tables (must share the same DB target).

**Response:**
```json
{
  "success": true,
  "message": "mapping_copied",
  "item": { ... }
}
```

---

## 11. Jobs

Prefix: `/jobs2`

Jobs manage data logging lifecycle. The `jobs2` router handles job state management — actual execution is handled by the external Rust job runner.

### GET /jobs2

List all jobs.

**Response:**
```json
{
  "items": [
    {
      "id": "job_1773669704217",
      "name": "Data Collector 1",
      "type": "continuous",
      "tables": ["table_1", "table_2"],
      "intervalMs": 1000,
      "status": "running",
      "enabled": true,
      "batching": {},
      "cpuBudget": "balanced"
    }
  ]
}
```

### POST /jobs2

> **Auth:** Requires `logger_write` role

Create a new job.

**Request Body:**
```json
{
  "name": "Temperature Logger",
  "type": "continuous",
  "tables": ["table_1", "table_2"],
  "intervalMs": 5000,
  "enabled": true,
  "triggers": [
    {
      "tableId": "table_1",
      "field": "temperature",
      "op": ">",
      "value": 50,
      "deadband": 2,
      "cooldownMs": 5000
    }
  ],
  "batching": {},
  "cpuBudget": "balanced"
}
```

**Job Types:**
- `continuous` — Periodic data collection at `intervalMs`
- `trigger` — Event-based data collection

**Trigger Operators:** `change`, `>`, `>=`, `<`, `<=`, `==`, `!=`, `rising`, `falling`

**Response:**
```json
{
  "success": true,
  "item": { ... }
}
```

### POST /jobs2/{job_id}/start

> **Auth:** Requires `logger_write` role

Start a job. Sets status to `"running"` and sends a notification to all users with the `logger_read` role (background task).

**Response:**
```json
{
  "success": true,
  "message": "started"
}
```

If already running:
```json
{
  "success": true,
  "message": "already_running"
}
```

### POST /jobs2/{job_id}/pause

> **Auth:** Requires `logger_write` role

Pause a job.

**Response:**
```json
{
  "success": true,
  "message": "paused"
}
```

### POST /jobs2/{job_id}/stop

> **Auth:** Requires `logger_write` role

Stop a job.

**Response:**
```json
{
  "success": true,
  "message": "stopped"
}
```

### POST /jobs2/stop_all

> **Auth:** Requires `logger_write` role

Stop all jobs.

**Response:**
```json
{
  "success": true,
  "stopped": 5
}
```

### POST /jobs2/{job_id}/dry_run

> **Auth:** Requires `logger_write` role

Sample device values without writing to the database.

**Response:**
```json
{
  "success": true,
  "items": [
    {
      "tableId": "table_1",
      "values": { "temperature": 45.5, "humidity": 65.2 },
      "ts": "2025-01-15T10:30:00+00:00"
    },
    {
      "tableId": "table_2",
      "error": "DEVICE_NOT_BOUND"
    }
  ]
}
```

### POST /jobs2/{job_id}/backfill

> **Auth:** Requires `logger_write` role

Write one sample row per table to the database.

**Response:**
```json
{
  "success": true,
  "wrote": 2
}
```

On partial failure:
```json
{
  "success": false,
  "message": "DEVICE_NOT_FOUND",
  "wrote": 1
}
```

### DELETE /jobs2/{job_id}

Delete a job and clear its metrics/history.

**Response:**
```json
{
  "success": true
}
```

### DELETE /jobs2

Bulk delete jobs.

**Request Body:**
```json
{
  "ids": ["job_1", "job_2", "job_3"]
}
```

**Response:**
```json
{
  "success": true,
  "deleted": 2,
  "failed": [
    { "id": "job_3", "error": "JOB_NOT_FOUND" }
  ]
}
```

### GET /jobs2/{job_id}/runs

Get job execution history.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| frm | string | Start datetime filter |
| to | string | End datetime filter |

**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "id": 1,
      "job_id": "job_1",
      "started_at": "2025-01-15T10:00:00Z",
      "stopped_at": "2025-01-15T10:01:00Z",
      "duration_ms": 60000,
      "rows": 120,
      "read_lat_avg": 25.5,
      "write_lat_avg": 45.3,
      "error_pct": 0.5
    }
  ]
}
```

---

## 12. Storage Targets

Prefix: `/storage/targets`

### GET /storage/targets

List database targets.

**Response:**
```json
{
  "items": [
    {
      "id": "target_1",
      "provider": "postgres",
      "conn": "postgresql://postgres@localhost/neuract",
      "status": "ok",
      "lastMsg": "Connection OK"
    }
  ],
  "defaultId": "target_1"
}
```

### POST /storage/targets

Add a database target.

**Request Body:**
```json
{
  "provider": "postgres",
  "conn": "postgresql://postgres@localhost/neuract"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| id | string | No | Auto-generated |
| provider | string | Yes | `sqlite`, `postgres`, `sqlserver`, `mysql` |
| conn | string | Yes | Connection string |

**Response:**
```json
{
  "success": true,
  "item": { ... }
}
```

### PUT /storage/targets/{tid}

Update a database target (partial update).

**Request Body:**
```json
{
  "conn": "postgresql://postgres@newhost/neuract",
  "status": "ok"
}
```

### DELETE /storage/targets/{tid}

Delete a database target. Fails if it's the default or in use (unless `force=true`).

**Query Parameters:** `force` (boolean, optional)

### POST /storage/targets/test

Test database connectivity.

**Request Body:**
```json
{
  "provider": "postgres",
  "conn": "postgresql://postgres@localhost/neuract"
}
```

Or by ID:
```json
{
  "id": "target_1"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "Connection OK"
}
```

### POST /storage/targets/default

Set the default database target.

**Request Body:**
```json
{
  "id": "target_1"
}
```

**Response:**
```json
{
  "ok": true,
  "defaultId": "target_1"
}
```

### POST /storage/targets/create_db

Create or verify a database file (SQLite only).

**Request Body:**
```json
{
  "provider": "sqlite",
  "conn": "/data/myapp.db"
}
```

**Response:**
```json
{
  "ok": true,
  "message": "db_ready"
}
```

---

## 13. System Metrics

Prefix: `/system`

### GET /system/metrics

System resource metrics over a time range.

**Query Parameters:** `range` (optional, e.g. `"300"`, `"5m"`, `"1h"` — default 300 seconds)

**Response:**
```json
{
  "ok": true,
  "data": {
    "timeseries": [
      {
        "ts": 1707815400,
        "cpu": 45.2,
        "mem": 2048,
        "disk_rps": 100,
        "disk_wps": 50,
        "net_rxps": 1024,
        "net_txps": 512,
        "proc_cpu": 12.5,
        "proc_rss_mb": 128,
        "proc_handles": 45
      }
    ],
    "now": "2025-01-15T10:35:00Z",
    "devices": {
      "connected": 5,
      "disconnected": 1,
      "unknown": 2
    },
    "db": {}
  }
}
```

### GET /system/summary

Compact status summary (for system tray).

**Response:**
```json
{
  "ok": true,
  "devicesConnected": 5,
  "defaultDbOk": true,
  "jobsRunning": 2
}
```

---

## 14. Database Metrics

Prefix: `/db`

### GET /db/metrics

Database write performance metrics.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| target_id | string | Specific DB target (uses default if omitted) |
| range | string | Time range (e.g. `"300s"`) |

**Response:**
```json
{
  "ok": true,
  "data": {
    "targetId": "target_1",
    "writeP50": 35.5,
    "writeP95": 120.3,
    "errorPct": 0.2,
    "writes": 10000,
    "writeErrors": 20
  }
}
```

---

## 15. Reports

Prefix: `/reports`

### GET /reports/runs.csv

Export job run history as CSV.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| job_id | string | Filter by job (all if omitted) |
| frm | string | Start date |
| to | string | End date |

**Response:** `text/csv`
```
id,job_id,started_at,stopped_at,duration_ms,rows,read_lat_avg,write_lat_avg,error_pct
```

### GET /reports/errors.csv

Export aggregated errors as CSV.

**Query Parameters:** `job_id` (optional)

**Response:** `text/csv`
```
job_id,code,count,last_message,last_ts
```

---

## 16. Notifications

Prefix: `/auth`

### POST /auth/notifications

Create a notification and broadcast via Redis pub/sub.

**Status Code:** 201

**Request Body:**
```json
{
  "message": "Job completed successfully",
  "type": "job"
}
```

| Field | Type | Required | Default |
|-------|------|----------|---------|
| message | string | Yes | — |
| type | string | No | `"job"` |

**Valid Types:** `job`, `alert`, `info`, `warning`, `error`

**Response (201):**
```json
{
  "ok": true,
  "id": "a1b2c3d4-...",
  "type": "job",
  "message": "Job completed successfully",
  "user": "aed23084-...",
  "read": false,
  "time": "2025-01-15T10:30:00Z"
}
```

### GET /auth/notifications/list

List notifications for the current user.

**Response:**
```json
[
  {
    "id": "a1b2c3d4-...",
    "type": "job",
    "message": "Job job_1773669704217 was started by rohith",
    "user": "aed23084-...",
    "read": false,
    "time": "2025-01-15T10:30:00Z"
  }
]
```

### Background Notification: Job Start

When a job is started via `POST /jobs2/{job_id}/start`, the system automatically:

1. Queries Keycloak for all users with the `logger_read` realm role
2. Creates a notification for each user: `"Job {job_id} was started by {username}"`
3. Broadcasts each notification to the `logger_read` Redis pub/sub channel
4. WebSocket clients subscribed to `/ws/logs` receive the notification in real-time

This runs as a FastAPI background task and does not block the start response.

---

## 17. WebSocket — Real-time Notifications

### WS /ws/logs

Real-time notification stream via WebSocket. Subscribes to Redis pub/sub channel `logger_read` and forwards all messages to connected clients.

**Authentication:** JWT required via `Authorization` header or `?token=` query parameter. Requires `logger-read` role.

**Connection:**
```
ws://127.0.0.1:5175/ws/logs?token=YOUR_JWT_TOKEN
```

Or with header:
```javascript
const ws = new WebSocket('ws://127.0.0.1:5175/ws/logs', {
  headers: { 'Authorization': 'Bearer YOUR_JWT_TOKEN' }
});
```

**Incoming Message Format:**
```json
{
  "type": "job",
  "action": "create",
  "notification_id": "a1b2c3d4-...",
  "message": "Job job_1773669704217 was started by rohith",
  "user": "aed23084-...",
  "read": false,
  "time": "2025-01-15T10:30:00Z"
}
```

**Close Codes:**
| Code | Meaning |
|------|---------|
| 1000 | Normal closure |
| 1008 | Authentication failed |
| 1011 | Server error (e.g. Redis unavailable) |

**JavaScript Example:**
```javascript
const token = 'YOUR_JWT_TOKEN';
const ws = new WebSocket(`ws://127.0.0.1:5175/ws/logs?token=${token}`);

ws.onopen = () => console.log('Connected');

ws.onmessage = (event) => {
  const notification = JSON.parse(event.data);
  console.log('Notification:', notification);
};

ws.onerror = (error) => console.error('Error:', error);

ws.onclose = (event) => console.log('Closed:', event.code, event.reason);
```

---

## 18. Debug

Prefix: `/debug`

### POST /debug/echo

Echo request headers and body prefix (for debugging).

**Request Body:** Any JSON

**Response:**
```json
{
  "ok": true,
  "headers": { "content-type": "application/json", "host": "127.0.0.1:5175" },
  "bodyPrefix": "First 512 bytes of request body..."
}
```

---

## 19. Authentication & Authorization

### JWT Token Flow

1. Login via `POST /auth/login` to get `access_token` and `refresh_token`
2. Include token in requests: `Authorization: Bearer <access_token>`
3. Token expires in 300 seconds (5 minutes) — use refresh token to renew

### Role-Based Access

| Role | Scope |
|------|-------|
| `logger_read` | Read access, WebSocket notifications |
| `logger_write` | Write operations (create, update, start/stop) |
| `logger_delete` | Delete operations |

### Protected Endpoints Summary

The following endpoints require a valid JWT with the `logger_write` role:

| Endpoint | Method |
|----------|--------|
| `/schemas` | POST |
| `/schemas/import` | POST |
| `/tables/bulk_create` | POST |
| `/tables/bulk_update_target` | POST |
| `/tables/dry_run_ddl` | POST |
| `/tables/migrate` | POST |
| `/devices` | POST |
| `/devices/{id}` | PUT |
| `/devices/{id}/connect` | POST |
| `/devices/{id}/disconnect` | POST |
| `/devices/{id}/quick_test` | POST |
| `/jobs2` | POST |
| `/jobs2/{id}/start` | POST |
| `/jobs2/{id}/pause` | POST |
| `/jobs2/{id}/stop` | POST |
| `/jobs2/stop_all` | POST |
| `/jobs2/{id}/dry_run` | POST |
| `/jobs2/{id}/backfill` | POST |

### Error Responses

**401 Unauthorized** — Missing or invalid token:
```json
{
  "detail": {
    "success": false,
    "error": "INVALID_TOKEN",
    "message": "Token validation failed"
  }
}
```

**403 Forbidden** — Insufficient role:
```json
{
  "detail": {
    "success": false,
    "error": "INSUFFICIENT_ROLE",
    "message": "logger-write role required"
  }
}
```

---

## 20. Error Codes

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request / validation error |
| 401 | Unauthorized (missing/invalid JWT) |
| 403 | Forbidden (insufficient role) |
| 404 | Not found |
| 429 | Rate limited |
| 500 | Server error |
| 502 | Bad gateway (Keycloak unavailable) |

### Application Error Codes

**Devices:**
`NAME_REQUIRED`, `PROTOCOL_INVALID`, `GATEWAY_NOT_FOUND`, `DEVICE_NOT_FOUND`

**Gateways:**
`NAME_AND_HOST_REQUIRED`, `PROTOCOL_HINT_INVALID`, `INVALID_PORTS`

**Mappings:**
`DEVICE_NOT_BOUND`, `MAPPING_INCOMPLETE`, `MAPPING_TYPE_MISMATCH`, `TAG_UNREADABLE`

**Jobs:**
`JOB_NOT_FOUND`, `NO_TABLES`, `NO_MAPPED_COLUMNS`, `JOB_DELETE_FAILED`, `NO_JOB_IDS`

**Protocols:**
`PROTOCOL_IN_USE`, `PROTOCOL_NOT_SUPPORTED`, `MODBUS_HOST_MISSING`, `OPCUA_PKG_MISSING`

---

## 21. Supported Protocols

### Modbus TCP

| Field | Description |
|-------|-------------|
| host | IP from gateway |
| port | Default 502 |
| unitId | Slave address (1-247) |
| address | Register number (e.g. `"40001"`) |
| encoding | `float32`, `float64`, `int16`, `int32`, `uint16`, `uint32`, `int64`, `uint64` |
| scale | Multiplication factor |
| deadband | Change threshold for triggers |

### OPC UA

| Field | Description |
|-------|-------------|
| endpoint | Full URL (e.g. `opc.tcp://192.168.1.20:4840/server`) |
| nodeId | Node address (e.g. `ns=2;i=1001`) |
| scale | Multiplication factor |
| deadband | Change threshold for triggers |

---

## 22. Database Providers

| Provider | Connection String Format | Schema Strategy |
|----------|-------------------------|-----------------|
| `sqlite` | `/path/to/database.db` | Tables prefixed `neuract__` |
| `postgres` | `postgresql://user:pass@host:5432/db` | Tables in `neuract` schema |
| `sqlserver` | `mssql+pyodbc://user:pass@host/db?driver=...` | Tables in `neuract` schema |
| `mysql` | `mysql+pymysql://user:pass@host:3306/db` | Tables prefixed `neuract__` |

---

## 23. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_PORT` | `5175` | Server port |
| `AGENT_HOST` | `127.0.0.1` | Bind host |
| `APP_DB_URL` | — | PostgreSQL URL for metadata storage |
| `META_BREAKPOINT_DB_URL` | — | PostgreSQL URL for breakpoint metadata |
| `CORS_ORIGIN` | `http://127.0.0.1:5173` | CORS allowed origin |
| `AGENT_LOG_LEVEL` | `INFO` | Logging level |
| `REDIS_URL` | `redis://127.0.0.1:6379/3` | Redis for WebSocket pub/sub |
| `KC_URL` | `http://192.168.1.20:8080/keycloak` | Keycloak base URL |
| `KC_REALM` | `desktop` | Keycloak realm |
| `KC_ALLOWED_ISSUERS` | — | Comma-separated list of allowed JWT issuers |
| `KC_ADMIN_CLIENT_ID` | `neuract_owner` | Keycloak service account client |
| `KC_ADMIN_CLIENT_SECRET` | — | Keycloak service account secret |
| `AGENT_STRICT_PORT` | `0` | If `1`, exit if preferred port is busy |
