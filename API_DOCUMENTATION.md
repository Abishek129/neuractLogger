# LoggerFast API Reference Guide

## Base Configuration

**Base URL:** `http://127.0.0.1:5175` (configurable via environment)
**API Version:** Neuract Logger Agent (see `/version` endpoint)
**Authentication:** Keycloak JWT tokens (except public endpoints)

---

## Table of Contents

1. [Health & Status Endpoints](#1-health--status-endpoints)
2. [Authentication Endpoints](#2-authentication-endpoints)
3. [Schema Management](#3-schema-management)
4. [Table Management](#4-table-management)
5. [Device Management](#5-device-management)
6. [Protocol Types Management](#6-protocol-types-management)
7. [Bulk Import](#7-bulk-import)
8. [Gateway Management](#8-gateway-management)
9. [Network Diagnostics](#9-network-diagnostics)
10. [Mapping Management](#10-mapping-management)
11. [Job Management](#11-job-management)
12. [Storage Management](#12-storage-management)
13. [System Metrics & Monitoring](#13-system-metrics--monitoring)
14. [Database Metrics](#14-database-metrics)
15. [Reports](#15-reports)
16. [Debug Endpoints](#16-debug-endpoints)
17. [Notifications (REST)](#17-notifications-rest)
18. [WebSocket Endpoints](#18-websocket-endpoints)
19. [Authentication & Authorization](#authentication--authorization)
20. [Error Handling](#error-handling)
21. [Supported Protocols](#supported-protocols)

---

## 1. Health & Status Endpoints

### Get Health Status
**Endpoint:** `GET /health`
**Authentication:** Public (no auth required)
**Response:**
```json
{
  "status": "ok",
  "agent": "plc-agent",
  "version": "1.0.0"
}
```

### Get System Version & Tech Stack
**Endpoint:** `GET /version`
**Authentication:** Public
**Response:**
```json
{
  "appVersion": "1.0.0",
  "python": "3.11.0",
  "platform": "Linux-6.18.6-arch1-1",
  "fastapi": "0.104.1",
  "sqlalchemy": "2.0.23",
  "uvicorn": "0.24.0",
  "port": 5175
}
```

### Shutdown Agent
**Endpoint:** `POST /shutdown`
**Authentication:** Public
**Response:**
```json
{
  "ok": true,
  "message": "shutting_down"
}
```

---

## 2. Authentication Endpoints

**Prefix:** `/auth`
**Authentication:** Public (user registration/login)

### Register New User
**Endpoint:** `POST /auth/register`
**Authentication:** Public
**Request Body:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "secure_password",
  "first_name": "John",
  "last_name": "Doe",
  "enabled": true
}
```
**Response:**
```json
{
  "ok": true,
  "user_id": "uuid",
  "username": "john_doe",
  "email": "john@example.com"
}
```

### User Login
**Endpoint:** `POST /auth/login`
**Authentication:** Public
**Request Body:**
```json
{
  "username": "john_doe",
  "password": "secure_password"
}
```
**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### Assign Admin Role
**Endpoint:** `POST /auth/assign-role/{username}`
**Authentication:** Public
**URL Parameters:** `username` (string)
**Response:**
```json
{
  "ok": true,
  "username": "john_doe",
  "user_id": "uuid",
  "client": "neuract-admin",
  "role": "neuract-admin"
}
```

---

## 3. Schema Management

**Prefix:** `/` (root)
**Authentication:** Public

### List All Schemas
**Endpoint:** `GET /schemas`
**Response:**
```json
{
  "items": [
    {
      "id": "schema_1",
      "name": "Temperature Sensor",
      "fields": [
        {
          "key": "temperature",
          "type": "float",
          "unit": "°C",
          "scale": 0.1,
          "desc": "Room temperature"
        },
        {
          "key": "humidity",
          "type": "float",
          "unit": "%",
          "scale": 1.0
        }
      ]
    }
  ]
}
```

### Create Schema
**Endpoint:** `POST /schemas`
**Request Body:**
```json
{
  "id": "schema_1",
  "name": "Sensor Schema",
  "fields": [
    {
      "key": "temperature",
      "type": "float",
      "unit": "°C",
      "scale": 0.1,
      "desc": "Temperature reading"
    },
    {
      "key": "status",
      "type": "string"
    }
  ]
}
```
**Response:**
```json
{
  "success": true,
  "message": "schema_created",
  "item": { /* schema object */ }
}
```

### Export Schemas
**Endpoint:** `GET /schemas/export`
**Response:**
```json
{
  "schemas": [ /* array of schemas */ ]
}
```

### Import Schemas
**Endpoint:** `POST /schemas/import`
**Request Body:**
```json
{
  "schemas": [ /* array of schema objects */ ]
}
```
**Response:**
```json
{
  "imported": 3
}
```

---

## 4. Table Management

**Prefix:** `/tables`
**Authentication:** Public (for most operations)

### List Tables
**Endpoint:** `GET /tables`
**Query Parameters:**
- `parentSchemaId` (optional): Filter by schema
- `dbTargetId` (optional): Filter by database target
- `status` (optional): Filter by status (not_migrated, migrated)
- `name` (optional): Filter by name pattern
- `page` (optional, default=1): Page number
- `pageSize` (optional, default=50): Items per page

**Response:**
```json
{
  "success": true,
  "total": 10,
  "page": 1,
  "items": [
    {
      "id": "table_1",
      "name": "sensor_data",
      "schemaId": "schema_1",
      "dbTargetId": "target_1",
      "status": "migrated",
      "lastMigratedAt": "2024-02-13T10:30:00+05:30",
      "parentSchema": {
        "id": "schema_1",
        "name": "Sensor Schema"
      },
      "dbTarget": { "id": "target_1" },
      "columnCount": 3,
      "mappingExists": true,
      "mappingStatus": "complete",
      "mappingRows": { /* mapping details */ }
    }
  ]
}
```

### Create Tables (Bulk)
**Endpoint:** `POST /tables/bulk_create`
**Request Body:**
```json
{
  "parentSchemaId": "schema_1",
  "names": ["table1", "table2", "table3"],
  "dbTargetId": "target_1"
}
```
**Supports name expansion:** `"pattern": "sensor_{0..10}"`

**Response:**
```json
{
  "success": true,
  "message": "tables_created",
  "count": 3,
  "items": [ /* created table objects */ ],
  "warnings": [ /* normalization warnings */ ]
}
```

### Update Target for Tables (Bulk)
**Endpoint:** `POST /tables/bulk_update_target`
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
  "items": [ /* updated table objects */ ]
}
```

### Discover Tables
**Endpoint:** `GET /tables/discover`
**Query Parameters:** `dbTargetId` (optional)
**Response:**
```json
{
  "success": true,
  "planned": [ /* tables not yet migrated */ ],
  "migrated": [ /* tables that exist in database */ ]
}
```

### Get Table Details
**Endpoint:** `GET /tables/{table_id}`
**Response:**
```json
{
  "success": true,
  "item": { /* table object */ },
  "schema": { /* schema with fields */ },
  "mappingHealth": {
    "complete": 2,
    "incomplete": 1,
    "unmapped": 0
  }
}
```

### Dry Run DDL
**Endpoint:** `POST /tables/dry_run_ddl`
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

### Migrate Tables to Database
**Endpoint:** `POST /tables/migrate`
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
      "status": "created"
    }
  ]
}
```

---

## 5. Device Management

**Prefix:** `/devices`
**Authentication:** Public

### List Devices
**Endpoint:** `GET /devices`
**Response:**
```json
{
  "items": [
    {
      "id": "device_1",
      "name": "Sensor 01",
      "protocol": "modbus",
      "gatewayId": "gateway_1",
      "port": 502,
      "unitId": 1,
      "status": "connected",
      "latencyMs": 45,
      "lastError": null,
      "params": { /* protocol-specific params */ },
      "autoReconnect": true,
      "connected": true
    }
  ]
}
```

### Create Device
**Endpoint:** `POST /devices`
**Request Body:**
```json
{
  "name": "Modbus Sensor",
  "protocol": "modbus",
  "gatewayId": "gateway_1",
  "port": 502,
  "unitId": 1,
  "params": {
    "host": "192.168.1.100"
  }
}
```
**Response:**
```json
{
  "success": true,
  "item": { /* device object */ },
  "error": null
}
```

### Update Device
**Endpoint:** `PUT /devices/{dev_id}`
**Request Body:** (partial update)
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
  "item": { /* updated device */ }
}
```

### Delete Device
**Endpoint:** `DELETE /devices/{dev_id}`
**Response:**
```json
{
  "success": true
}
```

### Connect Device
**Endpoint:** `POST /devices/{dev_id}/connect`
**Response:**
```json
{
  "success": true,
  "latencyMs": 42
}
```

### Disconnect Device
**Endpoint:** `POST /devices/{dev_id}/disconnect`
**Response:**
```json
{
  "success": true
}
```

### Quick Test Device Connection
**Endpoint:** `POST /devices/{dev_id}/quick_test`
**Response:**
```json
{
  "success": true,
  "latencyMs": 38,
  "error": null
}
```

---

## 6. Protocol Types Management

**Prefix:** `/protocol_types`
**Authentication:** Public

### List Protocol Types
**Endpoint:** `GET /protocol_types`
**Response:**
```json
{
  "items": ["modbus", "opcua", "s7", "dnp3"]
}
```

### Create Protocol Type
**Endpoint:** `POST /protocol_types`
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

### Delete Protocol Type
**Endpoint:** `DELETE /protocol_types/{protocol_type}`
**Fails if:** Devices or gateways are using this protocol
**Response:**
```json
{
  "success": true
}
```

---

## 7. Bulk Import

**Prefix:** `/bulk_import`
**Authentication:** Public

### Bulk Import Devices
**Endpoint:** `POST /bulk_import/devices`
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
      "name": "Device 2",
      "ip": "192.168.1.101",
      "protocol": "opcua",
      "port": 4840
    }
  ]
}
```
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
      "device": { /* device object */ },
      "gateway": { /* gateway object */ },
      "gateway_created": true,
      "message": "Device created with new gateway"
    }
  ]
}
```

**Field Mapping:**
- `name` (required): Device name
- `ip` (required): IP address for gateway lookup/creation
- `port` (optional): Port number
- `mac` (optional): MAC address
- `protocol` (optional, default="modbus"): Protocol type
- `unit` (optional): Modbus unit ID (1-247)
- `connections` (optional): Gateway name

---

## 8. Gateway Management

**Prefix:** `/networking/gateways`
**Authentication:** Protected (requires admin for write operations)

### List Gateways
**Endpoint:** `GET /networking/gateways`
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
      "status": "active",
      "lastHealthCheck": "2024-02-13T10:30:00Z"
    }
  ]
}
```

### List Gateways with Devices
**Endpoint:** `GET /networking/gateways_with_devices`
**Response:**
```json
{
  "items": [
    {
      "id": "gateway_1",
      "name": "Main PLC Gateway",
      "host": "192.168.1.50",
      "devices": [ /* array of device objects */ ],
      "deviceCount": 5
    }
  ]
}
```

### Add Gateway
**Endpoint:** `POST /networking/gateways`
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
  "item": { /* gateway object */ }
}
```

### Update Gateway
**Endpoint:** `PUT /networking/gateways/{gid}`
**Request Body:** (partial update)
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
  "item": { /* updated gateway */ }
}
```

### Delete Gateway
**Endpoint:** `DELETE /networking/gateways/{gid}`
**Response:**
```json
{
  "success": true
}
```

### Ping Gateway
**Endpoint:** `POST /networking/gateways/{gid}/ping`
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
  "samples": [15, 20, 28]
}
```

### TCP Test on Gateway Ports
**Endpoint:** `POST /networking/gateways/{gid}/tcp`
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
    {
      "port": 502,
      "ok": true,
      "status": "open",
      "timeMs": 45
    },
    {
      "port": 503,
      "ok": false,
      "status": "closed",
      "message": "Connection refused"
    }
  ]
}
```

---

## 9. Network Diagnostics

**Prefix:** `/networking`
**Authentication:** Protected

### List Network Interfaces
**Endpoint:** `GET /networking/nics`
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

### Ping Host
**Endpoint:** `POST /networking/ping`
**Request Body:**
```json
{
  "target": "192.168.1.100",
  "count": 4,
  "timeoutMs": 800
}
```
**Response:**
```json
{
  "ok": true,
  "lossPct": 0,
  "min": 12,
  "avg": 18,
  "max": 25,
  "samples": [12, 18, 25]
}
```

### TCP Test
**Endpoint:** `POST /networking/tcp_test`
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

### Modbus Test
**Endpoint:** `POST /networking/modbus/test`
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
**Response:**
```json
{
  "ok": true,
  "protocol": "modbus",
  "values": [1234, 5678],
  "latencyMs": 52
}
```

### OPC UA Test
**Endpoint:** `POST /networking/opcua/test`
**Request Body:**
```json
{
  "endpoint": "opc.tcp://192.168.1.100:4840/freeopcua/server/",
  "nodeId": "ns=2;i=2"
}
```
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

### OPC UA Browse
**Endpoint:** `POST /networking/opcua/browse`
**Request Body:**
```json
{
  "endpoint": "opc.tcp://192.168.1.100:4840/freeopcua/server/",
  "nodeId": "i=85"
}
```
**Response:**
```json
{
  "ok": true,
  "items": [
    {
      "nodeId": "ns=0;i=84",
      "browseName": "0:Objects"
    },
    {
      "nodeId": "ns=0;i=86",
      "browseName": "0:Views"
    }
  ]
}
```

---

## 10. Mapping Management

**Prefix:** `/mappings`
**Authentication:** Public

### Get Mapping
**Endpoint:** `GET /mappings/{table_id}`
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
        "encoding": "float32",
        "scale": 0.1,
        "deadband": 0.5
      },
      "humidity": {
        "protocol": "modbus",
        "address": "102",
        "encoding": "float32",
        "scale": 1.0
      }
    }
  },
  "health": {
    "status": "Mapped",
    "complete": 2,
    "incomplete": 0,
    "unmapped": 0
  }
}
```

### Upsert Mapping
**Endpoint:** `POST /mappings/{table_id}`
**Request Body:**
```json
{
  "deviceId": "device_1",
  "rows": {
    "temperature": {
      "protocol": "modbus",
      "address": "100",
      "encoding": "float32",
      "scale": 0.1
    },
    "humidity": {
      "protocol": "modbus",
      "address": "102",
      "encoding": "float32"
    }
  },
  "dbTargetId": "target_1"
}
```
**Response:**
```json
{
  "success": true,
  "message": "mapping_upserted",
  "item": { /* mapping object */ },
  "health": { /* health status */ }
}
```

### Bulk Apply Mapping
**Endpoint:** `POST /mappings/{table_id}/bulk_apply`
**Request Body:**
```json
{
  "rows": { /* mapping rows */ },
  "deviceId": "device_1",
  "dbTargetId": "target_1"
}
```
**Response:**
```json
{
  "success": true,
  "message": "mapping_applied",
  "item": { /* mapping object */ }
}
```

### Import Mapping
**Endpoint:** `POST /mappings/{table_id}/import`
**Request Body:**
```json
{
  "mapping": {
    "deviceId": "device_1",
    "rows": { /* mapping rows */ }
  },
  "dbTargetId": "target_1"
}
```
**Response:**
```json
{
  "success": true,
  "message": "mapping_imported",
  "item": { /* mapping object */ },
  "health": { /* health status */ }
}
```

### Validate Mapping
**Endpoint:** `POST /mappings/{table_id}/validate`
**Request Body:** (optional payload)
```json
{
  "rows": { /* mapping to validate */ },
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
      "code": "TAG_UNREADABLE",
      "message": "Cannot read from device"
    }
  ]
}
```

### Delete Mapping Row
**Endpoint:** `DELETE /mappings/{table_id}/{field_key}`
**Response:**
```json
{
  "success": true,
  "message": "row_deleted",
  "item": { /* updated mapping */ }
}
```

### Export Mapping
**Endpoint:** `GET /mappings/{table_id}/export`
**Response:**
```json
{
  "mapping": {
    "deviceId": "device_1",
    "rows": { /* all mapping rows */ }
  }
}
```

### Copy Mapping
**Endpoint:** `POST /mappings/{src_table_id}/copy_to/{dst_table_id}`
**Response:**
```json
{
  "success": true,
  "message": "mapping_copied",
  "item": { /* copied mapping */ }
}
```

---

## 11. Job Management

**Prefix:** `/jobs`
**Authentication:** Protected (Keycloak JWT required)

### List Jobs
**Endpoint:** `GET /jobs`
**Response:**
```json
{
  "items": [
    {
      "id": "job_1",
      "name": "Data Collector 1",
      "type": "continuous",
      "tables": ["table_1", "table_2"],
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

### Create Job
**Endpoint:** `POST /jobs`
**Request Body:**
```json
{
  "name": "New Job",
  "type": "continuous",
  "tables": ["table_1", "table_2"],
  "intervalMs": 1000,
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
  ]
}
```

**Job Types:**
- `continuous`: Periodic data collection
- `trigger`: Event-based data collection

**Trigger Operators:**
- `change`: Value changed beyond deadband
- `>`, `>=`, `<`, `<=`, `==`, `!=`: Comparison operators
- `rising`: Value crossed threshold upward
- `falling`: Value crossed threshold downward

**Response:**
```json
{
  "success": true,
  "item": { /* job object */ }
}
```

### Start Job
**Endpoint:** `POST /jobs/{job_id}/start`
**Response:**
```json
{
  "success": true,
  "message": "started"
}
```

### Pause Job
**Endpoint:** `POST /jobs/{job_id}/pause`
**Response:**
```json
{
  "success": true,
  "message": "paused"
}
```

### Stop Job
**Endpoint:** `POST /jobs/{job_id}/stop`
**Response:**
```json
{
  "success": true,
  "message": "stopped"
}
```

### Stop All Jobs
**Endpoint:** `POST /jobs/stop_all`
**Response:**
```json
{
  "success": true,
  "stopped": 5
}
```

### Dry Run Job
**Endpoint:** `POST /jobs/{job_id}/dry_run`
**Response:**
```json
{
  "success": true,
  "items": [
    {
      "tableId": "table_1",
      "values": {
        "temperature": 45.5,
        "humidity": 65.2
      },
      "ts": "2024-02-13T10:30:00Z"
    }
  ]
}
```

### Delete Job
**Endpoint:** `DELETE /jobs/{job_id}`
**Response:**
```json
{
  "success": true
}
```

### Bulk Delete Jobs
**Endpoint:** `DELETE /jobs`
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
    {
      "id": "job_3",
      "error": "JOB_NOT_FOUND"
    }
  ]
}
```

### Get Job Metrics
**Endpoint:** `GET /jobs/{job_id}/metrics`
**Query Parameters:** `range` (optional, e.g., "5m", "1h", "900s")
**Response:**
```json
{
  "ok": true,
  "data": {
    "timeseries": [
      {
        "ts": 1707815400,
        "reads_ok": 120,
        "reads_err": 2,
        "writes_ok": 118,
        "writes_err": 0,
        "read_lat_avg": 25.5,
        "write_lat_avg": 45.2
      }
    ],
    "summary": {
      "reads_per_sec": 2.0,
      "writes_per_sec": 1.97,
      "read_lat_avg": 25.5,
      "write_lat_avg": 45.2,
      "error_pct": 1.67
    }
  }
}
```

### Get Job Runs
**Endpoint:** `GET /jobs/{job_id}/runs`
**Query Parameters:**
- `frm` (optional): Start timestamp
- `to` (optional): End timestamp

**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "id": 1,
      "job_id": "job_1",
      "started_at": "2024-02-13T10:00:00Z",
      "stopped_at": "2024-02-13T10:01:00Z",
      "duration_ms": 60000,
      "rows": 120,
      "read_lat_avg": 25.5,
      "write_lat_avg": 45.3,
      "error_pct": 0.5
    }
  ]
}
```

### Get Job Errors
**Endpoint:** `GET /jobs/{job_id}/errors`
**Query Parameters:**
- `frm` (optional): Start timestamp
- `to` (optional): End timestamp

**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "code": "READ_ERROR",
      "count": 5,
      "lastMessage": "Connection timeout",
      "lastTs": 1707815400000
    }
  ]
}
```

### Get Job Metrics Summary
**Endpoint:** `GET /jobs/metrics/summary`
**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "jobId": "job_1",
      "reads_per_sec": 2.0,
      "writes_per_sec": 1.97,
      "read_lat_avg": 25.5,
      "write_lat_avg": 45.2,
      "error_pct": 1.67
    }
  ]
}
```

### Backfill Job Data
**Endpoint:** `POST /jobs/{job_id}/backfill`
**Response:**
```json
{
  "success": true,
  "wrote": 2
}
```

---

## 12. Storage Management

**Prefix:** `/storage/targets`
**Authentication:** Protected

### List Database Targets
**Endpoint:** `GET /storage/targets`
**Response:**
```json
{
  "items": [
    {
      "id": "target_1",
      "provider": "sqlite",
      "conn": "/data/myapp.db",
      "status": "ok",
      "lastMsg": "Test OK"
    },
    {
      "id": "target_2",
      "provider": "postgres",
      "conn": "postgresql://user:pass@localhost/neuract",
      "status": "ok",
      "lastMsg": "Connection OK"
    }
  ],
  "defaultId": "target_1"
}
```

### Add Database Target
**Endpoint:** `POST /storage/targets`
**Request Body:**
```json
{
  "provider": "sqlite",
  "conn": "/data/myapp.db"
}
```

**Supported Providers:**
- `sqlite`: SQLite database
- `postgres` / `postgresql`: PostgreSQL
- `sqlserver` / `mssql`: Microsoft SQL Server
- `mysql`: MySQL

**Response:**
```json
{
  "success": true,
  "item": { /* target object */ }
}
```

### Update Database Target
**Endpoint:** `PUT /storage/targets/{tid}`
**Request Body:** (partial update)
```json
{
  "status": "ok",
  "lastMsg": "Connection verified"
}
```
**Response:**
```json
{
  "success": true,
  "item": { /* updated target */ }
}
```

### Delete Database Target
**Endpoint:** `DELETE /storage/targets/{tid}`
**Query Parameters:** `force` (optional, boolean)
**Response:**
```json
{
  "success": true
}
```

### Test Database Target
**Endpoint:** `POST /storage/targets/test`
**Request Body:**
```json
{
  "id": "target_1"
}
```
Or provide inline target:
```json
{
  "provider": "sqlite",
  "conn": "/data/test.db"
}
```
**Response:**
```json
{
  "ok": true,
  "message": "Connection OK"
}
```

### Set Default Database Target
**Endpoint:** `POST /storage/targets/default`
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

### Create Database
**Endpoint:** `POST /storage/targets/create_db`
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
  "message": "db_ready"
}
```

---

## 13. System Metrics & Monitoring

**Prefix:** `/system`
**Authentication:** Protected

### Get System Metrics
**Endpoint:** `GET /system/metrics`
**Query Parameters:** `range` (optional, e.g., "5m", "1h", "300" for seconds)
**Response:**
```json
{
  "ok": true,
  "data": {
    "timeseries": [
      {
        "timestamp": "2024-02-13T10:30:00Z",
        "cpu": 45.2,
        "memory": 2048,
        "disk": 15360,
        "network": 1024
      }
    ],
    "now": "2024-02-13T10:35:00Z",
    "devices": {
      "connected": 5,
      "disconnected": 1,
      "unknown": 2
    },
    "db": {}
  }
}
```

### Get System Summary
**Endpoint:** `GET /system/summary`
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

**Prefix:** `/db`
**Authentication:** Protected

### Get Database Metrics
**Endpoint:** `GET /db/metrics`
**Query Parameters:**
- `target_id` (optional): Specific database target
- `range` (optional): Time range

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

**Prefix:** `/reports`
**Authentication:** Protected

### Export Job Runs as CSV
**Endpoint:** `GET /reports/runs.csv`
**Query Parameters:**
- `job_id` (optional): Specific job
- `frm` (optional): Start date
- `to` (optional): End date

**Response:** CSV file with columns:
```
id,job_id,started_at,stopped_at,duration_ms,rows,read_lat_avg,write_lat_avg,error_pct
```

### Export Errors as CSV
**Endpoint:** `GET /reports/errors.csv`
**Query Parameters:** `job_id` (optional)
**Response:** CSV file with columns:
```
job_id,code,count,last_message,last_ts
```

---

## 16. Debug Endpoints

**Prefix:** `/debug`
**Authentication:** Protected

### Echo Request
**Endpoint:** `POST /debug/echo`
**Response:**
```json
{
  "ok": true,
  "headers": { /* request headers */ },
  "bodyPrefix": "First 512 bytes of body..."
}
```

---

## 17. Notifications (REST)

**Prefix:** `/auth/notifications`
**Authentication:** Protected (requires `logger-read` role)

### Create Notification
**Endpoint:** `POST /auth/notifications`
**Request Body:**
```json
{
  "message": "Job completed successfully",
  "type": "job"
}
```
**Valid Types:** job, alert, info, warning, error

**Response:**
```json
{
  "ok": true,
  "id": "notif_uuid",
  "type": "job",
  "message": "Job completed successfully",
  "user": "user_uuid",
  "read": false,
  "time": "2024-02-13T10:30:00Z"
}
```

### List Notifications
**Endpoint:** `GET /auth/notifications/list`
**Response:**
```json
{
  "notifications": [
    {
      "id": "notif_uuid",
      "type": "job",
      "message": "...",
      "user": "user_uuid",
      "read": false,
      "time": "2024-02-13T10:30:00Z"
    }
  ]
}
```

---

## 18. WebSocket Endpoints

### Real-time Notification Stream
**Endpoint:** `WebSocket /ws/logs`
**Authentication:** JWT token required (via Authorization header or `?token=` query param)
**Requirements:** `logger-read` role

**Connection Protocol:**
1. Connect with Authorization header or token query parameter:
   ```
   ws://127.0.0.1:5175/ws/logs?token=YOUR_JWT_TOKEN
   ```
   Or with header:
   ```javascript
   const ws = new WebSocket('ws://127.0.0.1:5175/ws/logs', {
     headers: { 'Authorization': 'Bearer YOUR_JWT_TOKEN' }
   });
   ```

2. Server accepts connection if JWT is valid
3. Server subscribes to Redis `logger_read` channel
4. Receive JSON messages for each notification

**Message Format:**
```json
{
  "type": "job",
  "action": "create",
  "notification_id": "notif_uuid",
  "message": "Job completed",
  "user": "user_uuid",
  "read": false,
  "time": "2024-02-13T10:30:00Z"
}
```

**Close Codes:**
- 1000: Normal closure
- 1008: Policy violation (authentication failed)
- 1011: Server error (e.g., Redis unavailable)

**JavaScript Example:**
```javascript
const token = 'YOUR_JWT_TOKEN';
const ws = new WebSocket(`ws://127.0.0.1:5175/ws/logs?token=${token}`);

ws.onopen = () => {
  console.log('Connected to notification stream');
};

ws.onmessage = (event) => {
  const notification = JSON.parse(event.data);
  console.log('New notification:', notification);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = (event) => {
  console.log('Connection closed:', event.code, event.reason);
};
```

---

## Authentication & Authorization

### Access Control

**Public Endpoints** (no authentication required):
- `/health`
- `/version`
- `/shutdown`
- `/auth/*` (register, login, assign-role)
- `/schemas*`
- `/tables*`
- `/devices*`
- `/protocol_types*`
- `/bulk_import*`
- `/jobs2*` (legacy unprotected)

**Protected Endpoints** (require valid Keycloak JWT):
- `/jobs*` (requires admin role for write operations)
- `/networking*`
- `/storage*`
- `/mappings*`
- `/system*`
- `/db*`
- `/reports*`
- `/debug*`
- `/auth/notifications*` (requires `logger-read` role)
- `/ws/logs` (WebSocket, requires `logger-read` role)

### JWT Token Format

Tokens are obtained via `/auth/login` and must be included in subsequent requests:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Token Refresh

Use the refresh token from login response to get a new access token when expired.

---

## Error Handling

### Standard Error Response
```json
{
  "detail": "ERROR_CODE_OR_MESSAGE"
}
```

### Common HTTP Status Codes
- `200 OK`: Success
- `201 Created`: Resource created
- `400 Bad Request`: Invalid input
- `401 Unauthorized`: Missing/invalid authentication
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation error
- `429 Too Many Requests`: Rate limited
- `500 Internal Server Error`: Server error
- `502 Bad Gateway`: External service error

### Common Error Codes

**Device Errors:**
- `NAME_REQUIRED`: Device name missing
- `PROTOCOL_INVALID`: Invalid protocol type
- `GATEWAY_NOT_FOUND`: Referenced gateway doesn't exist
- `DEVICE_NOT_FOUND`: Device ID not found

**Gateway Errors:**
- `NAME_AND_HOST_REQUIRED`: Gateway name or host missing
- `PROTOCOL_HINT_INVALID`: Invalid protocol hint
- `INVALID_PORTS`: Port validation failed

**Mapping Errors:**
- `DEVICE_NOT_BOUND`: Table not linked to device
- `MAPPING_INCOMPLETE`: Required fields not mapped
- `TAG_UNREADABLE`: Cannot read from device address

**Job Errors:**
- `JOB_NOT_FOUND`: Job ID not found
- `NO_TABLES`: No tables specified for job
- `NO_MAPPED_COLUMNS`: Table has no mapped fields

**Protocol Errors:**
- `PROTOCOL_IN_USE`: Cannot delete protocol (devices using it)
- `MODBUS_HOST_MISSING`: Modbus connection requires host
- `OPCUA_PKG_MISSING`: OPC UA library not installed

---

## Supported Protocols

### Modbus TCP

**Features:**
- Holding registers read/write
- Multiple encodings: float32, float64, int16, int32, uint16, uint32, int64, uint64
- Unit ID support (slave addressing)
- Scaling and offset transformations
- Register address mapping

**Configuration:**
- Host: IP address from gateway
- Port: Port number from device (default: 502)
- Unit ID: Device-level configuration (default: 1)

**Mapping Fields:**
- `protocol`: "modbus"
- `address`: Register number (e.g., "40001")
- `encoding`: Data type (e.g., "float32")
- `scale`: Multiplication factor
- `deadband`: Change threshold for triggers

### OPC UA

**Features:**
- Node browsing and discovery
- Value subscription and reading
- Endpoint URL configuration
- Node ID addressing

**Configuration:**
- Endpoint: Full OPC UA URL from gateway.host (e.g., "opc.tcp://192.168.1.20:4840/server")

**Mapping Fields:**
- `protocol`: "opcua"
- `address`: Node ID (e.g., "ns=2;i=1001")
- `scale`: Multiplication factor
- `deadband`: Change threshold for triggers

---

## Database Targets

### Supported Providers

#### 1. SQLite (default)
**Connection String:**
```
/path/to/database.db
```
**Schema:** Tables prefixed with `neuract__`
**Example:**
```json
{
  "provider": "sqlite",
  "conn": "/data/sensors.db"
}
```

#### 2. PostgreSQL
**Connection String:**
```
postgresql://user:password@host:5432/database
```
**Schema:** Tables in `neuract` schema
**Example:**
```json
{
  "provider": "postgresql",
  "conn": "postgresql://postgres:password@localhost:5432/neuract"
}
```

#### 3. Microsoft SQL Server
**Connection String:**
```
mssql+pyodbc://user:password@host/database?driver=ODBC+Driver+17+for+SQL+Server
```
**Schema:** Tables in `neuract` schema
**Example:**
```json
{
  "provider": "sqlserver",
  "conn": "mssql+pyodbc://sa:password@localhost/neuract?driver=ODBC+Driver+17+for+SQL+Server"
}
```

#### 4. MySQL
**Connection String:**
```
mysql+pymysql://user:password@host:3306/database
```
**Schema:** Tables prefixed with `neuract__`
**Example:**
```json
{
  "provider": "mysql",
  "conn": "mysql+pymysql://root:password@localhost:3306/neuract"
}
```

---

## Configuration via Environment Variables

### Required
- `APP_DB_URL`: PostgreSQL connection for metadata storage
  ```bash
  APP_DB_URL=postgresql://postgres@localhost/meta_data_fast
  ```

### Optional
- `CORS_ORIGIN`: CORS origin (default: http://127.0.0.1:5173)
- `AGENT_PORT`: Server port (default: 5175)
- `AGENT_LOG_LEVEL`: Logging level (default: INFO)
- `REDIS_URL`: Redis for pub/sub (default: redis://127.0.0.1:6379/3)

---

## Running the Server

### Start Command
```bash
cd /home/rohith/desktop/LoggerFast/agent
APP_DB_URL=postgresql://postgres@localhost/meta_data_fast python run_agent.py
```

### Or with uvicorn directly
```bash
cd /home/rohith/desktop/LoggerFast/agent
APP_DB_URL=postgresql://postgres@localhost/meta_data_fast \
uvicorn plc_agent.api.app:app --host 127.0.0.1 --port 5175 --reload
```

### With .env file
Create `/home/rohith/desktop/LoggerFast/agent/.env`:
```bash
APP_DB_URL=postgresql://postgres@localhost/meta_data_fast
CORS_ORIGIN=http://127.0.0.1:5173
AGENT_PORT=5175
REDIS_URL=redis://127.0.0.1:6379/3
```

Then run:
```bash
cd /home/rohith/desktop/LoggerFast/agent
python run_agent.py
```

---

## Quick Start Examples

### 1. Create Complete Data Collection Pipeline

```bash
# 1. Import devices from spreadsheet
curl -X POST http://127.0.0.1:5175/bulk_import/devices \
  -H "Content-Type: application/json" \
  -d '{
    "devices": [
      {
        "name": "Temperature Sensor",
        "ip": "192.168.1.100",
        "port": 502,
        "protocol": "modbus",
        "unit": 1
      }
    ]
  }'

# 2. Create schema
curl -X POST http://127.0.0.1:5175/schemas \
  -H "Content-Type: application/json" \
  -d '{
    "id": "temp_schema",
    "name": "Temperature Schema",
    "fields": [
      {"key": "temperature", "type": "float", "unit": "°C"}
    ]
  }'

# 3. Create table
curl -X POST http://127.0.0.1:5175/tables/bulk_create \
  -H "Content-Type: application/json" \
  -d '{
    "parentSchemaId": "temp_schema",
    "names": ["sensor_data"]
  }'

# 4. Migrate table to database
curl -X POST http://127.0.0.1:5175/tables/migrate \
  -H "Content-Type: application/json" \
  -d '{"ids": ["table_id_from_step_3"]}'

# 5. Create mapping
curl -X POST http://127.0.0.1:5175/mappings/table_id_from_step_3 \
  -H "Content-Type: application/json" \
  -d '{
    "deviceId": "device_id_from_step_1",
    "rows": {
      "temperature": {
        "protocol": "modbus",
        "address": "100",
        "encoding": "float32",
        "scale": 0.1
      }
    }
  }'

# 6. Create and start job
curl -X POST http://127.0.0.1:5175/jobs \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Temperature Logger",
    "tables": ["table_id_from_step_3"],
    "intervalMs": 5000,
    "enabled": true
  }'

curl -X POST http://127.0.0.1:5175/jobs/job_id_from_above/start \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### 2. Monitor Job Performance

```bash
# Get real-time metrics
curl http://127.0.0.1:5175/jobs/job_id/metrics?range=5m \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Get job runs history
curl http://127.0.0.1:5175/jobs/job_id/runs \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Export runs to CSV
curl http://127.0.0.1:5175/reports/runs.csv?job_id=job_id \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -o runs.csv
```

### 3. Test Device Connectivity

```bash
# Modbus test
curl -X POST http://127.0.0.1:5175/networking/modbus/test \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "host": "192.168.1.100",
    "port": 502,
    "unitId": 1,
    "address": 0,
    "count": 10
  }'

# OPC UA test
curl -X POST http://127.0.0.1:5175/networking/opcua/test \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "endpoint": "opc.tcp://192.168.1.100:4840/server",
    "nodeId": "ns=2;i=2"
  }'
```

---

## Version History

- **1.0.0** - Initial release with Modbus and OPC UA support
- Gateway-based architecture
- Bulk device import
- Protocol type management
- Real-time WebSocket notifications

---

## Support & Contributing

For issues and feature requests, contact the development team.

**Documentation Last Updated:** February 13, 2024
