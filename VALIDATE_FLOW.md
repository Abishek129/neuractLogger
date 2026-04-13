# Validate & Live Stream — Implementation Guide

## Overview

When a user clicks **"Dry Run & Validate"** on a table, the system validates the mapping and then streams live device values via WebSocket.

---

## Backend Endpoints Used

### 1. Validate Mapping

```
POST /mappings/{table_id}/validate
Authorization: Bearer <JWT>
Content-Type: application/json
Body: {}
```

**Response (success):**
```json
{
  "success": true,
  "health": "Mapped",
  "problems": []
}
```

**Response (issues found):**
```json
{
  "success": false,
  "health": "Partially Mapped",
  "problems": [
    { "field": "temperature", "code": "MAPPING_INCOMPLETE" },
    { "field": "pressure", "code": "TAG_UNREADABLE" }
  ]
}
```

**Validation checks performed:**

| Check | Error Code | Meaning |
|-------|-----------|---------|
| Device bound to table? | `DEVICE_NOT_BOUND` | No device selected |
| Mapping row exists with protocol + address? | `MAPPING_INCOMPLETE` | Field not mapped |
| Protocol is valid? | `MAPPING_TYPE_MISMATCH` | Invalid protocol |
| DataType is valid (float/int/bool/string)? | `MAPPING_TYPE_MISMATCH` | Invalid data type |
| Can read from device? | `TAG_UNREADABLE` | Device read failed |

### 2. Live Stream WebSocket

```
ws://host:5175/ws/live/{table_id}?token=<JWT>&interval=1000
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `token` | string | required | JWT auth token |
| `interval` | int (ms) | 1000 | Read interval (min 500ms) |

**Message format (every interval):**
```json
{
  "tableId": "tbl_123",
  "tableName": "ahu_005",
  "ts": "2026-03-24T11:59:24.123456+00:00",
  "values": {
    "ahu_running_status": 1,
    "supply_air_temp_c": 16.8,
    "vfd_fan_speed_rpm": 1317.0,
    "heater_status": 2
  },
  "fields": 27
}
```

**Error message:**
```json
{
  "tableId": "tbl_123",
  "error": "MODBUS_CONNECT_FAILED: 10.10.23.10:502",
  "ts": "2026-03-24T11:59:24.123456+00:00"
}
```

### Tested Results

**Validate** — `POST /mappings/tbl_1773859189539_250/validate`:
```json
{ "health": "Partially Mapped", "problems": [28 items] }
```

> **Fixed:** The validator's `_modbus_can_read()` was failing due to incorrect pymodbus API usage (positional args instead of keyword args, missing `device_id`). This has been fixed — validation now correctly reads from the device and reports `Mapped` with 0 problems when all fields are properly configured.

**Tested — chiller_001 (80 fields):**
```json
{ "health": "Mapped", "problems": [] }
```

**Live Stream** — `ws://host:5175/ws/live/{table_id}?token=JWT&interval=1000`:
```
[1/5] ts=12:55:52 fields=27 supply_air_temp=16.200001
[2/5] ts=12:55:53 fields=27 supply_air_temp=16.200001
[3/5] ts=12:55:54 fields=27 supply_air_temp=16.200001
[4/5] ts=12:55:55 fields=27 supply_air_temp=16.200001
[5/5] ts=12:55:56 fields=27 supply_air_temp=16.200001
```
All fields returned with real device values every second.

---

## Frontend Flow

### Step 1 — User clicks "Dry Run & Validate"

Call the validate endpoint:

```js
const res = await api.post(`/mappings/${tableId}/validate`, {});
const { health, problems } = res.data;
```

### Step 2 — Determine per-field status

Build a status map from the problems array:

```js
const fieldStatus = {};  // key → "valid" | "invalid" | "pending"
const mappingRows = Object.keys(currentMapping.rows);

// Start all mapped fields as "pending"
mappingRows.forEach(key => { fieldStatus[key] = "pending"; });

// Mark fields with problems
problems.forEach(p => {
  if (p.field) {
    fieldStatus[p.field] = "invalid";
  }
});

// If health === "Mapped" and no problems, all fields are valid structurally
if (health === "Mapped" && problems.length === 0) {
  mappingRows.forEach(key => { fieldStatus[key] = "valid"; });
}
```

### Step 3 — If validation passes, connect WebSocket

Only connect if there are no hard errors (device bound, at least some fields mapped):

```js
if (problems.some(p => p.code === "DEVICE_NOT_BOUND")) {
  // Show error: "No device bound to this table"
  return;
}

// Connect WebSocket
const token = keycloak.token;
const ws = new WebSocket(
  `ws://${window.location.hostname}:5175/ws/live/${tableId}?token=${token}&interval=1000`
);
```

### Step 4 — Open "Dry Run & Validate" panel

Show a sliding panel / modal with:

**Header row:**
- Summary counts: `{pending} pending`, `{valid} Valid`, `{invalid} Invalid`
- Close (X) button

**Column headers:**
| Time | Field 1 | Field 2 | Field 3 | ... |

Each field header shows a status badge:
- **Valid** (green) — validation passed AND live values are non-null
- **Invalid** (red) — validation failed or live values are consistently null
- **Validate** (yellow/pending) — waiting for first live read to confirm

### Step 5 — Stream live values using a queue structure

Use a **fixed-size circular queue** per field to store the last N values (1 per second). This lets the UI show a rolling history and detect value stability.

```js
const QUEUE_SIZE = 5;  // Keep last 5 seconds of data per field

// Queue: { [fieldKey]: Array<{ ts: string, value: any }> }
const fieldQueues = {};
const mappingFields = Object.keys(currentMapping.rows);

// Initialize empty queues
mappingFields.forEach(key => {
  fieldQueues[key] = [];
});

// Rows for table display (latest at index 0)
const rows = [];

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.error) {
    // Show error banner in the panel
    return;
  }

  const ts = new Date(data.ts).toLocaleTimeString();

  // Push each field value into its queue
  Object.entries(data.values).forEach(([key, val]) => {
    if (!fieldQueues[key]) {
      fieldQueues[key] = [];
    }

    // Enqueue
    fieldQueues[key].push({ ts, value: val });

    // Dequeue if over limit (circular behavior)
    if (fieldQueues[key].length > QUEUE_SIZE) {
      fieldQueues[key].shift();
    }
  });

  // Add row for table display
  rows.unshift({ ts, values: data.values });
  if (rows.length > QUEUE_SIZE) rows.pop();

  // Update field statuses based on queue history
  Object.entries(fieldQueues).forEach(([key, queue]) => {
    if (queue.length === 0) return;

    const lastVal = queue[queue.length - 1].value;
    const allNull = queue.every(entry => entry.value === null);
    const hasValue = lastVal !== null;

    if (allNull && queue.length >= 3) {
      // 3+ consecutive nulls → mark invalid
      fieldStatus[key] = "invalid";
    } else if (hasValue) {
      fieldStatus[key] = "valid";
    }
    // else: stays "pending" until enough data
  });

  // Re-render the table
  renderDryRunTable(rows, fieldStatus);
};
```

**Queue structure per field:**

```
fieldQueues = {
  "supply_air_temp_c": [
    { ts: "08:26:01", value: 16.8 },
    { ts: "08:26:02", value: 16.9 },
    { ts: "08:26:03", value: 16.8 },
    ...  // max 5 entries (last 5 seconds)
  ],
  "ahu_running_status": [
    { ts: "08:26:01", value: 1 },
    { ts: "08:26:02", value: 1 },
    ...
  ]
}
```

**What you can derive from the queue:**

| Query | How |
|-------|-----|
| Latest value | `queue[queue.length - 1].value` |
| Previous value | `queue[queue.length - 2].value` |
| Value changed? | `latest !== previous` |
| All nulls (dead field)? | `queue.every(e => e.value === null)` |
| Stable (no change)? | `new Set(queue.map(e => e.value)).size === 1` |
| Min/Max in window | `Math.min/max(...queue.map(e => e.value))` |
| Rate of change | `(latest - oldest) / queue.length` |
```

### Step 6 — Render the table

```
+--------+-----------+-----------+-----------+-----------+-----------+
| Time   | Valid     | Invalid   | Validate  | Validate  | Valid     |
|        | Field_1   | Field_2   | Field_3   | Field_4   | Field_5   |
+--------+-----------+-----------+-----------+-----------+-----------+
| 08:26  | 1         | 12°C      | 12°C      | 12°C      | 12°C      |
| 08:25  | 1         | 12°C      | 12°C      | 12°C      | 12°C      |
| 08:24  | 1         | 12°C      | 12°C      | 12°C      | 12°C      |
+--------+-----------+-----------+-----------+-----------+-----------+
                                            [ Cancel ]  [ Done ]
```

### Step 7 — User clicks "Done" or "Cancel"

```js
// Close WebSocket
ws.close();

// If "Done":
//   - Update field validation statuses in the mapping
//   - Optionally mark fields as "validated" in the store
//   - Close the panel

// If "Cancel":
//   - Just close the panel, discard results
```

---

## State Machine

```
[Idle]
  │
  ▼  click "Dry Run & Validate"
[Validating]  →  POST /mappings/{table_id}/validate
  │
  ├─ DEVICE_NOT_BOUND → [Error: show message, stay on mapping page]
  │
  ├─ problems found → [Show panel with field statuses, connect WS anyway]
  │
  ▼  health = "Mapped" or "Partially Mapped"
[Streaming]  →  ws://host:5175/ws/live/{table_id}
  │
  │  each message → add row to table, update field statuses
  │
  ├─ WS error → show error banner, keep panel open
  │
  ├─ "Cancel" → close WS, close panel
  │
  ▼  "Done"
[Complete]  →  close WS, update UI, close panel
```

---

## Field Status Badge Colors

| Status | Color | Badge Text | Meaning |
|--------|-------|-----------|---------|
| valid | Green | Valid | Mapping correct, live read returns value |
| invalid | Red | Invalid | Mapping error or live read returns null |
| pending | Yellow | Validate | Waiting for first live read |

---

## Notes

- The WebSocket reads directly from the device (modbus/opcua), not from the database
- No data is written to the database during dry run / validation
- The interval can be adjusted via the `interval` query param (default 1000ms)
- Token expiry: if the JWT expires during streaming, the WebSocket will close with code 1008. Frontend should handle reconnection with a fresh token.
- Keep a maximum of 5 rows in the UI table (rolling queue per field)
