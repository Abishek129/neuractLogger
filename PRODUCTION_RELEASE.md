# Logger backend — production release (2026-10-27)

This document covers everything in this release: how to deploy it, every new and changed endpoint, the database design, the migrations, and what the frontend must change. All of it was checked against the running code on archbox (`:5175`) on 2026-10-27.

| | |
|---|---|
| **Backend** | FastAPI agent, `agent/plc_agent/api`, port 5175 |
| **Engine** | Rust job runner, `agent/rust_jobs` (binary `neuract-job-runner`) |
| **Metadata DB** | Postgres, e.g. `meta_data_fast` (the `app_*` tables) |
| **Storage target(s)** | Postgres, e.g. `fast_target` (data tables plus `neuract.device_mappings`) |
| **Tests at release** | Tier 1: **135 passed, 0 failed**. Tier 2 (e2e, real engine plus simulators): **9 passed** |

---

## Contents

1. [What's in this release](#1-whats-in-this-release)
2. [Deploy steps](#2-deploy-steps)
3. [Configuration](#3-configuration)
4. [Database design](#4-database-design)
5. [Migrations (run automatically at start)](#5-migrations-run-automatically-at-start)
6. [Electrical elements: the model](#6-electrical-elements-the-model)
7. [Endpoints: electrical elements](#7-endpoints-electrical-elements)
8. [Endpoints: spreadsheet import and export (EMS)](#8-endpoints-spreadsheet-import-and-export-ems)
9. [Endpoints: alerts](#9-endpoints-alerts)
10. [Other changes](#10-other-changes)
11. [Error codes](#11-error-codes)
12. [Breaking changes for the frontend](#12-breaking-changes-for-the-frontend)
13. [Verification checklist (after deploy)](#13-verification-checklist-after-deploy)
14. [Rollback](#14-rollback)
15. [Known limits and open items](#15-known-limits-and-open-items)
16. [Files in this release](#16-files-in-this-release)

---

## 1. What's in this release

| Area | Summary |
|---|---|
| **Electrical elements** | New model: an element is a **category** (EMS / Source / BMS) + **kind** (single / distribution) + optional **type** (user-defined: Load, HT Panel, Transformer…), with an optional **zone**. Distribution panels have **buses**. Buses and single elements have **incomer / outgoer** limits, and relations are formed between elements |
| **MFMs** | An MFM is a **logger table** (as in v1); its device and schema come from the table. On a single element, MFMs attach directly. On a distribution panel, each MFM sits in the **slot of a bus relation**; an outgoing MFM with no element is a **spare** |
| **Readiness** | "Ready" = every incoming and outgoing slot has an element connected. Nameplate completeness is a separate field |
| **Spreadsheet** | EMS import (Elements, Buses, Connections, Meters sheets; all or nothing; dry run), a template download, and an export in the plant template's layout |
| **Alerts** | Alert levels; rules on schema fields with per-table overrides. The engine keeps one state per field, records every change, and sends a notification |
| **Engine** | Alert evaluation; OPC UA fixes (endpoint lookup, no panic on a URL mismatch, reconnect after a server restart) |
| **Fixes** | Mapping rows silently not saved (missing `encoding` column); `GET /equipment` slowed down sharply as the plant grew (47 s → 0.15 s at 3,000 items); type optional after migration |

---

## 2. Deploy steps

Run the steps in this order. The backend applies all database migrations **itself at start** (`appdb.init()`), and they are idempotent: safe to run more than once.

### 2.1 Before you start
1. **Back up both databases.** The migrations rename tables and columns in place.
   ```bash
   pg_dump -h <host> -U postgres -d meta_data_fast -Fc -f meta_data_fast_$(date +%F).dump
   pg_dump -h <host> -U postgres -d fast_target   -Fc -f fast_target_$(date +%F).dump
   ```
2. **Note the running jobs.** They are marked running in `app_jobs`, and the engine resumes them after its restart.

### 2.2 Code and Python packages
```bash
git pull                       # or copy the release
cd <repo>
.venv/bin/python -m pip install -r requirements.txt
```
**New Python packages** (both small, pure Python, pinned in `requirements.txt`):

| Package | Why |
|---|---|
| `python-multipart==0.0.22` | File upload (`POST /equipment/import/ems`) |
| `openpyxl==3.1.5` | Reading and writing `.xlsx` |

### 2.3 Rust engine
```bash
cd agent/rust_jobs
cargo build --release          # → target/release/neuract-job-runner
```
The new binary is needed for **alerts** and the **OPC UA fixes**. The old binary keeps logging, but it never evaluates alerts.

### 2.4 Restart, in this order
1. **Stop the engine** (`neuract-job-runner`).
2. **Restart the backend** (`run_agent.py`, port 5175). On start it creates or migrates the tables (see §5). Watch the log for `migrat` / `MFM slot dropped` warnings.
3. **Check the backend** with the commands in [§13](#13-verification-checklist-after-deploy).
4. **Start the new engine.** It resumes jobs whose `status='running'`, and loads alert rules at each job start.

### 2.5 Storage targets
No manual step. On the first mapping read or save, the backend adds the `encoding` (and `device_id`) column to an old `neuract.device_mappings` table if it's missing (§10.1).

To pre-apply it by hand on each storage DB:
```sql
ALTER TABLE neuract.device_mappings ADD COLUMN IF NOT EXISTS encoding TEXT;
```

---

## 3. Configuration

### 3.1 Backend (`agent/.env`)
| Variable | Meaning |
|---|---|
| `APP_DB_URL` | Metadata DB (Postgres) |
| `AGENT_HOST`, `AGENT_PORT` | Bind address and port (5175) |
| `LOGGER_AUTH_DISABLED` | `1` treats every request as admin. **Set it to `0` (or remove it) in production** (see §15, B7) |
| `KC_URL`, `KC_REALM`, `KC_ALLOWED_ISSUERS` | Keycloak token validation |
| `REDIS_URL` | WebSocket notifications |
| `LOGGER_DISABLE_BOOT_JOBS` | `1` = don't mark jobs running at boot (tests) |

### 3.2 Engine (environment)
| Variable | Meaning |
|---|---|
| `APP_DB_URL` | Same metadata DB. The engine also **writes** `app_alert_state` / `app_alert_event` here |
| `API_BASE_URL` | Backend URL, for job and alert notifications (`POST {API_BASE_URL}/auth/notifications`) |
| `JOB_POLL_MS` | How often it checks `app_jobs` |
| `RUST_LOG` | Log level |

### 3.3 Permissions
- Reads need `logger-read`.
- Writes need `logger-write` (or the client role `neuract-admin`).
- The spreadsheet **import** needs write; the **template** and **export** need read only.

---

## 4. Database design

### 4.1 Overview
```
                    app_equipment_category (EMS / Source / BMS)   app_equipment_type (user-defined)   app_equipment_zone
                                 │ kinds_json                             │ config_json (fields)            │
                                 ▼                                        ▼                                 ▼
app_equipment  (element) ── category_id (FK, NOT NULL) ── kind ── type_id (FK, NULL) ── zone_id (FK, NULL)
     │
     ├── app_bus (nodes)  distribution: Bus A, B, … (is_main=0)  |  single: one hidden "main" node (is_main=1)
     │      ├── app_bus_type       allowed types per side (incomer / outgoer)
     │      ├── app_bus_equipment  relations: elements attached as incomer / outgoer, ordered
     │      └── app_bus_meter      MFMs = logger tables (app_device_tables) in relation slots, or spares
     │
     └── (alerts are on logger tables, not elements)

app_alert (levels) ── app_schema_alert (rule on a schema field) ── app_table_alert (per-table override)
                      app_alert_state / app_alert_event (written by the engine)
```

### 4.2 Electrical tables

#### `app_equipment_category`: EMS / Source / BMS
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `ems`, `source`, `bms` |
| `name` | text NOT NULL | Unique on `lower(name)` (`ux_equipment_category_name`) |
| `sort_order` | integer NOT NULL, default 0 | |
| `kinds_json` | text | Allowed kinds: EMS `["single","distribution"]`; Source / BMS `[]` (decided later). Managed in the DB |

Seeded at start when missing; names, order and kinds edited in the DB are kept.

#### `app_equipment_type`: user-defined types
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | Built-in types: `source`, `transformer`, `ht_panel`, `lt_panel`, `load`. User types get `typ_<ms>_<hex>` |
| `name` | text NOT NULL | Unique on `lower(name)` (`ux_equipment_type_name`) |
| `sort_order` | integer NOT NULL, default 0 | |
| `config_json` | text | `{"fields": [...], "node": {"incomers": n, "outgoers": n}}`. `fields` are the nameplate fields; `node` is the default capacity of a single element's own node |

The built-in five are seeded **once** (`app_meta.equipment_types_seeded`). A built-in type that a user deletes stays deleted.

Field definition: `{id, label, kind: "quantity"|"choice"|"text", units?: [..], options?: [..], required?: bool, role?: "voltage"|"voltage.in"|"voltage.out"}`.

#### `app_equipment_zone`: user-managed zones
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `zone_<ms>_<hex>` |
| `name` | text NOT NULL | Unique on `lower(name)` |
| `sort_order` | integer NOT NULL, default 0 | |

#### `app_equipment`: elements
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `eq_<ms>_<hex>`. This is the **Element ID** |
| `name` | text NOT NULL | Unique on `lower(name)` (`ux_equipment_name`) |
| `category_id` | text NOT NULL | FK `fk_element_category` → `app_equipment_category` |
| `kind` | text NOT NULL | CHECK `single`/`distribution` (`ck_equipment_kind`). Fixed at create |
| `type_id` | text **NULL** | FK `fk_element_type` → `app_equipment_type`. Optional |
| `zone_id` | text NULL | FK `fk_element_zone` → `app_equipment_zone` |
| `values_json` | text | Nameplate values `{fieldId: {value, unit}}` |
| `spare` | integer NOT NULL, default 0 | "Not expected on the map" |
| `description` | text | |
| `version` | integer NOT NULL, default 1 | Bumped on every change (If-Match concurrency) |
| `created_at`, `updated_at` | text | ISO `…Z` |
| `subtype` | text | **No longer used** (kept in the DB only) |

Indexes: `ix_equipment_category`, `ix_equipment_type`, `ix_equipment_zone`.

#### `app_bus`: connection nodes
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `bus_<ms>_<hex>` |
| `equipment_id` | text NOT NULL | FK `fk_bus_equipment` → `app_equipment`, ON DELETE CASCADE |
| `name` | text NOT NULL | "Bus A"… (the main node is `main`). Unique per element (`ux_bus_name`) |
| `sort_order` | integer | |
| `incomers`, `outgoers` | integer NOT NULL, CHECK ≥ 0 | **Limits** (capacity) |
| `is_main` | integer | 1 = the hidden node of a single element |
| `coupled_next` | integer | Bus coupler to the next bus |

#### `app_bus_type`: allowed types per side
`(bus_id, role, type_id)` PK. `role` ∈ incomer/outgoer. FKs: `fk_bus_type_bus` (cascade), `fk_bus_type_type`. A side with no rows is unrestricted.

#### `app_bus_equipment`: relations
| Column | Notes |
|---|---|
| `bus_id`, `equipment_id` | PK `(bus_id, equipment_id)`: an element sits once per node. FKs to `app_bus` (cascade) and `app_equipment` |
| `role` | `incomer` (it feeds the bus) / `outgoer` (the bus feeds it) |
| `sort_order` | Position, 0-based, compact per node and side |

On a single element's **main node**, an `outgoer` row is a **direct link** (that element feeds the attached one).

#### `app_bus_meter`: MFMs
| Column | Notes |
|---|---|
| `bus_id` | FK `fk_bus_meter_bus` → `app_bus`, cascade |
| `table_id` | **The MFM = a logger table.** NOT NULL, **UNIQUE** (one place per table). FK `fk_bus_meter_table` → `app_device_tables(id)` |
| `role` | `incomer` / `outgoer` on a bus; NULL on a single element's main node |
| `equipment_id` | The relation (attached element) this MFM measures. NULL with `role='outgoer'` = **spare** |
| `sort_order` | |

PK `(bus_id, table_id)`. Partial unique index `ux_bus_meter_relation (bus_id, equipment_id) WHERE equipment_id IS NOT NULL` gives one MFM per relation.

### 4.3 Alert tables
| Table | Columns | Written by |
|---|---|---|
| `app_alert` | `id, name, severity INT, color, sort_order`. Unique `lower(name)`. Seeded once: `critical` (3, `#b42318`), `mild` (2, `#b54708`), `info` (1, `#175cd3`) | API |
| `app_schema_alert` | `id, schema_id, field_key, alert_id, op CHECK (> >= < <= == !=), threshold DOUBLE`. Unique `(schema_id, field_key, alert_id)` | API |
| `app_table_alert` | `id, table_id, field_key, alert_id, op NULL, threshold NULL, enabled INT DEFAULT 1`. Unique `(table_id, field_key, alert_id)`. A NULL op/threshold inherits from the schema rule | API |
| `app_alert_state` | `table_id, field_key, alert_id, value, since`. PK `(table_id, field_key)`. A row exists only while the field is **not normal** | **Engine** |
| `app_alert_event` | `id, table_id, field_key, from_alert_id, to_alert_id, value, op, threshold, job_id, at`. Index `(table_id, at)`. A NULL from/to means normal | **Engine** |

### 4.4 Other tables added in this cycle
| Table | Purpose |
|---|---|
| `app_field_type (id, label, encoding, sort_order)` | DB-managed schema field types (word → register encoding) |
| `app_field_unit (id, label, sort_order)` | DB-managed units list |
| `app_device_verification (device_id PK, ok, latency_ms, error, at)` | Last connection test per device |
| Columns `app_devices.nominal_voltage`, `app_schema_fields.address`, `app_schemas.description` | Added (p4 merge / schema metadata) |

### 4.5 Storage target (each `fast_target`)
`neuract.device_mappings (table_name, field_key, protocol, address, data_type, scale, deadband, device_id, encoding)`, PK `(table_name, field_key)`. **`encoding` is added automatically** if an older table lacks it (§10.1).

---

## 5. Migrations (run automatically at start)

All of them are in `agent/plc_agent/api/appdb.py → _init_equipment()` / `init()`. Each one runs **only on the old shape** and is idempotent.

| # | Migration | When it runs | What it does |
|---|---|---|---|
| M1 | `_migrate_equipment_to_types` | `app_equipment_category` still has its old `type` column | **Old category → type:** `app_equipment_category` → `app_equipment_type` (its `type` and `group_id` columns dropped). `app_equipment.category_id` → `type_id` (made **nullable**). New `app_equipment.category_id` = the old group (default `ems`). `kind` = the old category's type. `app_bus_category` → `app_bus_type` (`type_id`). `app_equipment_group` → `app_equipment_category`. Old indexes and FKs dropped, then re-added under the new names. Sets `equipment_types_seeded` |
| M1b | `type_id` repair | Every start (Postgres) | `ALTER … type_id DROP NOT NULL`: repairs databases migrated by the first build of M1 (archbox was fixed this way) |
| M2 | `_migrate_bus_meter_to_tables` | `app_bus_meter` still has `device_id` | **MFM slot device → logger table:** a slot whose device has exactly **one** table keeps that table; other slots are dropped and **logged** (`MFM slot dropped: device … has N tables`). The table is rebuilt with `table_id` |
| M3 | Seeds | Every start | Categories (insert when missing, `kinds_json` filled when NULL); built-in types (once); alert levels (once) |
| M4 | Columns and indexes | Every start | `zone_id`, `ux_bus_meter_relation`, FKs (each in a SAVEPOINT; a failure doesn't abort the start) |
| M5 | Storage `encoding` | First mapping read or save per storage target | `ADD COLUMN IF NOT EXISTS encoding` / `device_id` on `neuract.device_mappings` |

**On archbox, the migration result (real data):** 3,000 elements (2,700 Load single, 300 LT Panel distribution), all `categoryId=ems`, with their types kept; 2,700 relations intact; 0 MFMs (nothing to map).

> Before restarting production, check that no device holds **more than one** logger table while it sits in an MFM slot (M2 would drop that slot and log it):
> ```sql
> SELECT m.device_id, count(t.id) FROM app_bus_meter m JOIN app_device_tables t ON t.device_id = m.device_id GROUP BY 1 HAVING count(t.id) <> 1;
> ```
> (This runs only before M2. If it lists rows, write those slots down and re-place them after the deploy.)

---

## 6. Electrical elements: the model

### 6.1 Terms
| Term | Meaning |
|---|---|
| **Category** | EMS, Source, BMS. Each one's `kinds` says which kinds it accepts (EMS: both; Source / BMS: none for now → `KIND_NOT_ALLOWED`) |
| **Kind** | `single`: MFMs directly on the element, with a hidden main node holding its own incomers/outgoers. `distribution`: **buses**, each with incomers/outgoers. **Can't be changed after create** |
| **Type** | User-defined, one global list, with nameplate fields. Any type can be used with either kind. Optional on an element |
| **Zone** | Optional, from a user-managed list |
| **Element ID** | The generated `id` (`eq_…`). `name` is the user's name (unique) |

### 6.2 Incomers and outgoers (relations come first)
```
Single element (Transformer, Load, UPS…)          Distribution panel (PCC, MCC, HT panel…)
  own incomers / outgoers                            └── Bus A, Bus B, …   (the panel itself has none)
  limits maxIncomers / maxOutgoers                          incomers / outgoers, limits per bus
  (defaults from the type's defaultCapacity)
```
- An element can be attached to a bus as an **incomer** (it feeds the bus) or an **outgoer** (the bus feeds it).
- A single element can **feed another single element directly** (Grid → Transformer).
- **Checked at both ends:**
  - limits (`NO_SPARE`);
  - allowed types per side (`TYPE_NOT_ALLOWED`; an element with no type is refused where a side restricts types);
  - no loops (`CYCLE`);
  - an element sits once per node, but can have several parents (`ALREADY_ATTACHED`).

### 6.3 MFMs (added after the relations)
| Where | Rule |
|---|---|
| **Single element** | MFMs (logger tables) attach to the element itself, with no limit |
| **Bus, incoming** | The MFM must measure an **attached incomer** (`equipmentId` required) |
| **Bus, outgoing** | It measures an attached outgoer, **or** has no element: a **spare**, which takes an outgoing point |
| **One per relation** | A relation has at most one MFM (`RELATION_METERED`) |
| **One place per table** | A logger table is an MFM in one place only (`METER_IN_USE`) |
| **Capacity** | Outgoing points used = connected outgoers + spare MFMs |
| **Disconnect** | A metered **outgoer** → its MFM stays as a **spare**. A metered **incomer** → refused until the MFM is removed (`RELATION_METERED`) |
| **Spare → feeder** | Connect a new outgoer **at a spare's point** with `spareTableId`; that MFM then measures it |
| **Deletes** | A logger table that is an MFM can't be deleted (`TABLE_ATTACHED_TO_EQUIPMENT`); neither can its device (`DEVICE_ATTACHED_TO_EQUIPMENT`) |

### 6.4 What each element shows
| Field | Meaning |
|---|---|
| `readiness` | `{ready, incomers: {filled, total}, outgoers: {filled, total}}`. **Ready = every slot (within the limits) has an element connected.** MFMs don't count. 0/0 counts as ready |
| `nameplate` | `{complete, missing: [labels]}`: the type's required fields that have no value |
| `metering` | Distribution: `{points, pointsMetered, meterCount, meters}`. Single: `{meterCount, meters}` |
| `used` | The element is connected (as a member, or has children / direct links) |
| `voltage` | `{in, out, text}` from the type's voltage-role fields |

---

## 7. Endpoints: electrical elements

**General rules:**
- No trailing slashes.
- Lists come as `{"items": [...]}`; writes return `{"success": true, "item": {...}}`.
- Errors come as `{"detail": "CODE: message"}`, with status 400 (validation), 404 (missing) or 409 (conflict).
- **Concurrency:** writes accept an `If-Match: <version>` header (the version of the element that owns the node). A stale version gives 409 `VERSION_CONFLICT`. Without the header, the last write wins.

### 7.1 Categories, types, zones
| Method & path | Body / query | Answer |
|---|---|---|
| `GET /equipment/categories` | — | `{items: [{id, name, sortOrder, kinds}]}` |
| `GET /equipment/types` | — | `{items: [{id, name, sortOrder, fields, defaultCapacity, used}]}` |
| `POST /equipment/types` | `{name, fields?, defaultCapacity?: {incomers, outgoers}, sortOrder?}` | `{success, item}`. Errors: `TYPE_EXISTS`, `FIELDS_INVALID` |
| `PUT /equipment/types/{id}` | Same keys, all optional | Removed fields keep their stored values, but readiness ignores them |
| `DELETE /equipment/types/{id}` | — | 409 `TYPE_IN_USE: N element(s), M bus rule(s)` |
| `GET /equipment/zones` | — | `{items: [{id, name, sortOrder, used}]}` |
| `POST /equipment/zones` | `{name, sortOrder?}` | `ZONE_EXISTS` |
| `PUT /equipment/zones/{id}` | `{name?, sortOrder?}` | |
| `DELETE /equipment/zones/{id}` | — | 409 `ZONE_IN_USE` |

### 7.2 Elements
| Method & path | Body / query | Notes |
|---|---|---|
| `GET /equipment` | `?categoryId=&kind=&typeId=&zoneId=&q=&metered=&ready=&used=&spare=` | `q` searches the name and the type name. `metered` / `ready` / `used` / `spare` take `true`/`false`. A fixed number of queries at any plant size |
| `GET /equipment/{id}` | — | The same item shape as the list |
| `POST /equipment` | `{name, categoryId, kind, typeId?, zoneId?, values?, spare?, description?, maxIncomers?, maxOutgoers?, incomingTypes?, outgoingTypes?}` | A distribution element gets "Bus A"; a single element gets its main node, sized from the type's `defaultCapacity` (default 1/1). The last four keys are for single elements |
| `PUT /equipment/{id}` | Same keys, all optional; `typeId: null` / `zoneId: null` clear them | `kind` → `KIND_IMMUTABLE`. A `categoryId` change must allow the kind. A `typeId` change re-checks bus rules at both ends (`TYPE_NOT_ALLOWED_ON_BUS`) and drops values of fields the new type lacks |
| `DELETE /equipment/{id}` | — | 409 `EQUIPMENT_IN_USE` while it's attached somewhere. Its own buses, relations and MFM placements go with it; the attached elements and the logger tables are kept |

**Element item:**
```json
{"id": "eq_…", "name": "PCC-01", "categoryId": "ems", "categoryName": "EMS", "kind": "distribution",
 "typeId": "lt_panel", "typeName": "LT Panel", "zoneId": "zone_…", "zoneName": "North", "spare": false,
 "description": null, "values": {"bus_voltage": {"value": 415.0, "unit": "V"}},
 "voltage": {"in": "415 V", "out": null, "text": "415 V"},
 "nameplate": {"complete": true, "missing": []},
 "readiness": {"ready": true, "incomers": {"filled": 1, "total": 1}, "outgoers": {"filled": 6, "total": 6}},
 "attachedTo": [{"busId": "bus_…", "busName": "Bus A", "equipmentId": "eq_…", "equipmentName": "HT-01", "role": "outgoer", "position": 0, "direct": false}],
 "used": true, "version": 7, "createdAt": "…Z", "updatedAt": "…Z",
 "buses": ["…bus objects (distribution)…"],
 "metering": {"points": 7, "pointsMetered": 7, "meterCount": 7, "meters": ["…"]}}
```
A **single** element has `maxIncomers`, `maxOutgoers`, `incomingTypes`, `outgoingTypes`, `outgoingEquipment` (its direct links) and `metering: {meterCount, meters}` in place of `buses`.

### 7.3 Buses (distribution elements)
| Method & path | Body | Notes |
|---|---|---|
| `GET /equipment/{id}/buses` | — | `BUSES_NOT_ALLOWED` on a single element |
| `POST /equipment/{id}/buses` | `{name?, incomers?, outgoers?, incomingTypes?, outgoingTypes?}` | At most 26 buses (`BUS_LIMIT`) |
| `PUT /equipment/{id}/buses/count` | `{count: 1..26}` | Adds buses at the end, or removes trailing empty ones (`BUS_NOT_EMPTY`) |
| `PUT /equipment/buses/{busId}` | `{name?, sortOrder?, coupledNext?, incomers?, outgoers?, incomingTypes?, outgoingTypes?}` | Limits can't go below what's in use (`CAPACITY_BELOW_ATTACHED`, which counts spares); type rules must fit what's attached (`ATTACHED_OUTSIDE_TYPES`) |
| `DELETE /equipment/buses/{busId}` | — | `LAST_BUS`, `BUS_NOT_EMPTY` |

**Bus object:**
```json
{"id": "bus_…", "equipmentId": "eq_…", "equipmentVersion": 7, "name": "Bus A", "sortOrder": 0,
 "incomers": 1, "outgoers": 3, "coupledNext": false,
 "incomingTypes": ["transformer"], "outgoingTypes": ["load"],
 "incomingEquipment": [{"id": "eq_…", "name": "TF-1", "categoryId": "ems", "kind": "single", "typeId": "transformer", "typeName": "Transformer", "position": 0,
                        "meter": {"tableId": "tbl_…", "tableName": "pcc_in", "schemaName": "MFM 3ph", "deviceName": "dev_pcc_in", "role": "incomer", "equipmentId": "eq_…", "…": "…"}}],
 "outgoingEquipment": [{"…": "…", "meter": null}],
 "spares": [{"tableId": "tbl_…", "tableName": "pcc_spare", "role": "outgoer", "equipmentId": null, "…": "…"}],
 "spareMeters": 1, "spareIncomers": 0, "spareOutgoers": 1, "points": 4, "pointsMetered": 3, "meters": ["…all MFMs on the bus…"]}
```
`spareOutgoers` = free outgoing points: neither connected nor holding a spare MFM.

### 7.4 Relations
| Method & path | Body | Notes |
|---|---|---|
| `POST /equipment/buses/{busId}/equipment` | `{equipmentId, role: incomer\|outgoer, position?, spareTableId?}` | Attaches an element to the bus. `spareTableId` (outgoer only) connects it at that spare's point (`NOT_A_SPARE`) |
| `PUT /equipment/buses/{busId}/equipment/{eqId}` | `{position}` | Reorders it (0 = first) |
| `DELETE /equipment/buses/{busId}/equipment/{eqId}` | — | A metered outgoer's MFM becomes a spare; a metered incomer gives `RELATION_METERED` |
| `POST /equipment/{id}/connections` | `{equipmentId, position?}` | **Direct link**: single `id` feeds single `equipmentId` (`USE_BUS` when either is a panel) |
| `PUT /equipment/{id}/connections/{targetId}` | `{position}` | Reorders the link |
| `DELETE /equipment/{id}/connections/{targetId}` | — | Removes the link |

Attach, detach and move answer `{success, owner, attached, item?}`: both changed elements, plus the bus when there is one.

### 7.5 MFMs (logger tables)
| Method & path | Body | Notes |
|---|---|---|
| `GET /equipment/available_meters` | — | Logger tables **not placed** anywhere: the MFM picker |
| `GET /equipment/{id}/meters` | — | All MFMs of an element (its own, or on any of its buses) |
| `POST /equipment/{id}/meters` | `{tableId}` | Single elements only (`USE_BUS_METERS` on a panel) |
| `DELETE /equipment/{id}/meters/{tableId}` | — | |
| `POST /equipment/buses/{busId}/meters` | `{tableId, role, equipmentId?}` | Incoming needs `equipmentId`; outgoing without it is a **spare** |
| `PUT /equipment/buses/{busId}/meters/{tableId}` | `{equipmentId \| null}` | Moves the MFM to another relation, or makes it a spare (outgoing only). The role stays the same |
| `DELETE /equipment/buses/{busId}/meters/{tableId}` | — | |

**MFM object** (everywhere an MFM appears):
```json
{"tableId": "tbl_…", "tableName": "pcc_in", "schemaId": "sch_…", "schemaName": "MFM 3ph",
 "deviceId": "dev_…", "deviceName": "dev_pcc_in", "protocol": "modbus", "status": "connected",
 "unitId": 1, "gatewayId": "gw_…", "gatewayName": "GIC-01", "host": "10.10.1.10", "port": 502,
 "role": "incomer", "equipmentId": "eq_…"}
```
The device fields are `null` when the table isn't bound to a device. `status` is live device health.

---

## 8. Endpoints: spreadsheet import and export (EMS)

| Method & path | What it does |
|---|---|
| `GET /equipment/import/ems/template` | `ems_elements_template.xlsx`: the Elements / Buses / Connections / Meters sheets with their headers (one column per known nameplate field), plus a **Types** reference sheet |
| `POST /equipment/import/ems` | Multipart form, field **`file`** (`.xlsx` or `.csv`, ≤ 5 MB, ≤ 20,000 rows per sheet). `?dryRun=true` checks without saving |
| `GET /equipment/export/ems?typeId=` | `ems_elements_YYYYMMDD.xlsx` in the **plant template's layout** |

### 8.1 Import workbook
Everything goes into the **EMS** category, so there's no category column. Headers are matched ignoring case, and `_` and spaces are interchangeable. A `.csv` is read as the **Elements** sheet only. Sheets run in this order: **Elements → Buses → Connections → Meters**.

| Sheet | Columns (* = required) |
|---|---|
| **Elements** | `name`*, `kind` (`single`/`distribution`; required for a new element), `type`, `zone`, `max incomers`, `max outgoers` (single), `incoming types`, `outgoing types` (comma-separated; **on a panel they apply to every bus**, including buses added later in the file), `spare` (yes/no), `description`, plus **one column per nameplate field** of the row's type (by label or id; `33 kV`, or a bare number for the field's first unit) |
| **Buses** | `panel`*, `bus`*, `incomers`, `outgoers`, `incoming types`, `outgoing types` |
| **Connections** | `panel`*, `bus` (required for a panel; blank = a direct link from a single element), `role` (`incomer`/`outgoer`), `element`*, `position` (1 = first) |
| **Meters** | `table`* (the logger table that is the MFM; a column headed **`MFM`** reads the same, as in v1), `element`*, `bus` (panels), `role` (`incoming`/`outgoing`/`spare`; v1's `Incomings`/`Outgoings`/`Spare` work too), `measures` (required for incoming; blank on outgoing = a spare), `schema` (optional check: `SCHEMA_MISMATCH`) |

**Rules:**
- **Upsert:** an existing element name, bus or relation is **updated**. Blank cells leave stored values alone, and **nothing is ever deleted**.
- **A new panel's buses:** its automatic "Bus A" takes the name of its first row in the Buses sheet.
- **Meters on re-run:**
  - same place → `unchanged`;
  - same bus but another element → the MFM moves there;
  - placed elsewhere → `METER_IN_USE` (never moved silently);
  - a different role in place → `ROLE_CHANGE`.
- **Same rules as the API:** the import calls the same service functions, in one transaction, with a savepoint per row.
- **All or nothing:** one bad row means nothing is saved.

### 8.2 Answer
```json
{"success": true, "dryRun": false, "saved": true,
 "summary": {"elements": {"created": 4, "updated": 0, "unchanged": 0}, "buses": {"…": 0},
             "connections": {"…": 0}, "meters": {"…": 0}, "errors": 0},
 "results": [{"sheet": "Elements", "row": 2, "key": "GRID-01", "status": "created"}]}
```
- **`row`** is the spreadsheet row number (the header is row 1). `status` is `created`, `updated`, `unchanged` or `failed`, with an `error` on a failed row.
- **Dry run:** always **200**, with `saved: false`.
- **Real import with errors:** **400**, with the same report plus `"detail": "IMPORT_INVALID: N row(s) have errors; nothing was saved"`.
- **File errors:** 400 `FILE_TYPE`, `FILE_INVALID`, `SHEETS_MISSING`, `TOO_MANY_ROWS`; 413 `FILE_TOO_LARGE`.

### 8.3 Export layout (the plant template)
- **One sheet per type** (plus "Untyped"):
  - row 1 is the group row, `REQUIRED` | `NAMEPLATE / OPTIONAL`;
  - row 2 holds the headers: `Element ID *`, `Name *`, `Zone`, the type's required fields (`*`, with the unit in the header when the field has exactly one unit), `Number of Bus Sections` (panels) or `Max Incomers` / `Max Outgoers` (single), `Allowed Incoming Types`, `Allowed Outgoing Types`, then the optional fields, `Spare` and `Description`.
- **Bus Sections:** `Element ID *`, `Element Name`, `Bus ID *`, `Bus Section *`, `Maximum Incomers *`, `Outgoing Feeder Capacity *`, plus each bus's allowed types.
- **Meters:** `Table (MFM)`, `Element`, `Bus`, `Role`, `Measures`, `Schema`, `Device`.
- **Lists:** zones, element types and kinds.

On archbox, 3,000 elements export in about 0.3 s.

---

## 9. Endpoints: alerts

**The model:**
- Rules are set on the **schema** (the blueprint) and inherited by every table of that schema.
- A table can **override** a rule (another op/threshold), **disable** it, or add its **own** rule.
- **The engine:**
  - loads the rules when a job starts, so edits apply at the **next job restart**;
  - keeps **one state per table field** (normal, or the most severe matching level);
  - writes a state row and an event, and posts a notification of type `alert`, **only when that state changes**.
- There is no deadband, and missing readings are ignored.

| Method & path | Body / query | Notes |
|---|---|---|
| `GET /alerts/levels` | — | Highest severity first |
| `POST /alerts/levels` | `{name, severity?, color?}` | `ALERT_LEVEL_EXISTS` |
| `PUT /alerts/levels/{id}` | `{name?, severity?, color?, sortOrder?}` | |
| `DELETE /alerts/levels/{id}` | — | 409 `ALERT_LEVEL_IN_USE` |
| `GET /schemas/{id}/alerts` | — | The schema's rules |
| `POST /schemas/{id}/alerts` | `{fieldKey, alertId, op, threshold}` | `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `ALERT_RULE_EXISTS`; `op` ∈ `> >= < <= == !=` |
| `PUT /schemas/{id}/alerts/{ruleId}` | `{op?, threshold?}` | `fieldKey` / `alertId` are fixed (`FIELD_IMMUTABLE`) |
| `DELETE /schemas/{id}/alerts/{ruleId}` | — | |
| `GET /tables/{id}/alerts` | — | Effective rules, each with `source`: `schema` / `overridden` / `table` / `disabled` |
| `PUT /tables/{id}/alerts` | `{fieldKey, alertId, op?, threshold?, enabled?}` | Upserts the override (`RULE_REQUIRED` for a table-only rule without op+threshold) |
| `DELETE /tables/{id}/alerts/{overrideId}` | — | Back to the schema rule |
| `GET /alerts/active` | `?tableId=` | Current non-normal states |
| `GET /alerts/events` | `?tableId=&frm=&to=&limit=` (≤ 1000) | History, newest first; `from`/`to` = `null` means normal |

**Cleanup:**
- Deleting a table removes its overrides and states.
- Deleting a schema removes its rules.
- Deleting a schema field removes that field's rules, overrides and states.
- Events are always kept.

---

## 10. Other changes

### 10.1 Mapping rows silently not saved — fixed
- **The bug:** on storage targets whose `neuract.device_mappings` was created by v1 (no `encoding` column), every mapping save failed inside the DB, but the API answered **200** without storing anything.
- **Now:**
  - the backend adds the missing columns automatically on Postgres;
  - a failed save returns **500 `MAPPING_SAVE_FAILED: <field>: <reason>`**;
  - the column repair can no longer deadlock itself, because it runs after the probe connection closes.
- **Running jobs aren't affected:** the engine already reads the table with or without the column.

### 10.2 `GET /equipment` performance — fixed
- **The cause:** about 5 whole-table reads per item, which grew quadratically: 3,000 items took 39–47 s.
- **Now:** a fixed number of queries (about 7), so 3,000 items take **0.12–0.18 s**, and 8 parallel requests finish within 1.2 s. The response is unchanged.

### 10.3 OPC UA in the engine — fixed
- **Endpoint lookup:** the engine now finds the endpoint the same way the API does: `params.endpoint`, then the gateway host, then host:port (default 4840). It used to fall back to a hardcoded localhost server.
- **No panic on a URL mismatch:** when the configured path or port differs from what the server advertises, the engine uses the server's unsecured endpoint at our host and port.
- **Reconnect:** a failed read drops the session, so the next poll reconnects after a server restart.
- **A bad NodeId** skips only that field.
- **Tests:** an e2e test with an OPC UA simulator (`agent/tools/opcua_simulator.py`). Security modes other than None, and username/password login, are **not** supported.

### 10.4 Earlier in this cycle (already documented in `Logger-v2-backend-mapping.md`)
- **Schemas:** DB-managed field types and units.
- **Schemas and tables:** schema description and rename; schema field `address`.
- **Devices:**
  - device edit via `PUT /devices/{id}` (address / unit id);
  - verification results (`app_device_verification`);
  - `nominalVoltage`, and the device constants in formulas.
- **Fixes and auth:**
  - the B5 fixes (row delete persists, import merges unless `mode: replace`, migrate errors are 4xx/500);
  - the client role `neuract-admin` grants write;
  - GETs on devices, schemas, tables and jobs2 need a token.
- **Device bulk import:** `POST /bulk_import/devices` is unchanged (mapping doc §12).

---

## 11. Error codes

| Code | Status | Meaning |
|---|---|---|
| `CATEGORY_NOT_FOUND`, `TYPE_NOT_FOUND`, `ZONE_NOT_FOUND`, `EQUIPMENT_NOT_FOUND`, `BUS_NOT_FOUND`, `TABLE_NOT_FOUND`, `METER_NOT_ATTACHED`, `NOT_ATTACHED` | 404 | Unknown id |
| `KIND_INVALID` / `KIND_NOT_ALLOWED` / `KIND_IMMUTABLE` | 400 | Kind isn't single/distribution / the category doesn't take it / it can't change |
| `TYPE_EXISTS`, `ZONE_EXISTS`, `EQUIPMENT_EXISTS`, `BUS_EXISTS` | 409 | Name taken (compared ignoring case) |
| `TYPE_IN_USE`, `ZONE_IN_USE`, `EQUIPMENT_IN_USE` | 409 | Still referenced |
| `FIELDS_INVALID`, `FIELD_UNKNOWN`, `FIELD_INVALID`, `VALUES_INVALID` | 400 | Type field definitions / element values |
| `TYPE_NOT_ALLOWED` | 400 | The side's allowed types exclude this element (or it has no type) |
| `TYPE_NOT_ALLOWED_ON_BUS` | 409 | A type change would break a rule where the element is attached |
| `ATTACHED_OUTSIDE_TYPES`, `CAPACITY_BELOW_ATTACHED` | 409 | New rule or limit doesn't fit what's attached (spares count) |
| `NO_SPARE` | 409 | No free point on that side (connections + spare MFMs fill it) |
| `ALREADY_ATTACHED`, `CYCLE`, `SELF_ATTACH`, `USE_BUS`, `USE_BUS_METERS`, `BUSES_NOT_ALLOWED` | 400/409 | Relation rules |
| `BUS_LIMIT`, `LAST_BUS`, `BUS_NOT_EMPTY`, `NO_NEXT_BUS` | 400/409 | Bus rules |
| `TABLE_REQUIRED`, `EQUIPMENT_REQUIRED`, `FEEDER_NOT_ON_BUS` | 400 | MFM placement: table missing / incoming without a relation / element not attached on that side |
| `RELATION_METERED` | 409 | The relation already has an MFM / a metered incomer can't be detached |
| `NO_FREE_POINT` | 409 | No free outgoing point for a spare MFM |
| `NOT_A_SPARE` | 400 | `spareTableId` isn't a spare of this bus |
| `METER_IN_USE`, `METER_ALREADY_ATTACHED` | 409 | The table is an MFM somewhere else / already here |
| `TABLE_ATTACHED_TO_EQUIPMENT`, `DEVICE_ATTACHED_TO_EQUIPMENT` | 409 | Delete refused while an MFM |
| `VERSION_CONFLICT`, `IF_MATCH_INVALID` | 409/400 | Concurrency |
| `IMPORT_INVALID` | 400 | Import had row errors (nothing saved) |
| `FILE_TYPE`, `FILE_INVALID`, `SHEETS_MISSING`, `TOO_MANY_ROWS`, `FILE_TOO_LARGE` | 400/413 | Import file |
| Import row codes: `NAME_REQUIRED`, `KIND_REQUIRED`, `DUPLICATE_IN_SHEET`, `ELEMENT_NOT_FOUND`, `ELEMENT_NOT_EMS`, `NOT_A_PANEL`, `LIMITS_ON_DISTRIBUTION`, `BUS_REQUIRED`, `ROLE_INVALID`, `POSITION_INVALID`, `SPARE_MEASURES`, `ROLE_CHANGE`, `SCHEMA_MISMATCH` | in `results[]` | |
| `MAPPING_SAVE_FAILED` | 500 | A mapping row couldn't be stored (§10.1) |
| `CONFLICT` | 409 | A database constraint caught a concurrent write; retry |

---

## 12. Breaking changes for the frontend

This section can be sent to the frontend on its own.

| Before | Now |
|---|---|
| `GET /equipment/categories` listed Transformer, HT Panel… | It lists **EMS / Source / BMS** `{id, name, sortOrder, kinds}`. The old list is **`GET /equipment/types`** |
| `GET /equipment/groups` | **Removed** |
| Element `categoryId` = Transformer… | Element **`typeId` / `typeName`** (may be `null`) |
| Element `groupId` | Element **`categoryId` / `categoryName`** |
| Element `type` (single / distribution) | Element **`kind`** |
| Element `subtype` | **Removed** |
| `POST /equipment {name, categoryId}` | `{name, categoryId: "ems", kind, typeId?, zoneId?}` |
| `?type=` filter | `?kind=`, plus new `?typeId=` and `?zoneId=` |
| `incomingCategories` / `outgoingCategories` | **`incomingTypes` / `outgoingTypes`** |
| `readiness` = required fields filled | `readiness` = **every slot connected** `{ready, incomers, outgoers}`; required fields → **`nameplate`** |
| `CATEGORY_NOT_ALLOWED*`, `ATTACHED_OUTSIDE_CATEGORIES` | `TYPE_NOT_ALLOWED*`, `ATTACHED_OUTSIDE_TYPES` |
| MFM calls with `deviceId`; `spareDeviceId` | **`tableId`**; **`spareTableId`** (an MFM is a logger table) |
| `available_meters` = devices | **Logger tables** not placed |
| Incoming bus MFM without an element | Now **required**: `equipmentId` (`EQUIPMENT_REQUIRED`) |
| Outgoing bus MFM without an element | It's a **spare** (it takes a point) |

---

## 13. Verification checklist (after deploy)

Replace `$B` with the backend URL, and add `-H "Authorization: Bearer <token>"` when auth is on.

```bash
curl -s $B/health                                   # {"status":"ok",...}
curl -s $B/equipment/categories                     # ems [single,distribution], source [], bms []
curl -s $B/equipment/types | head -c 300            # built-in types plus any user types, with "used"
curl -s -o /dev/null -w "%{http_code} %{time_starttransfer}s\n" $B/equipment   # 200, well under 1 s
curl -s $B/equipment/available_meters | head -c 300 # logger tables, with schemaName and deviceName
curl -s -o /dev/null -w "%{http_code}\n" $B/equipment/import/ems/template      # 200
curl -s -o /dev/null -w "%{http_code}\n" $B/equipment/export/ems               # 200
curl -s $B/alerts/levels                            # critical / mild / info
```
In the metadata DB:
```sql
SELECT kind, category_id, type_id, count(*) FROM app_equipment GROUP BY 1,2,3;   -- every row has kind + category
SELECT is_nullable FROM information_schema.columns
 WHERE table_name='app_equipment' AND column_name='type_id';                     -- YES
SELECT conname FROM pg_constraint WHERE conname LIKE 'fk_element_%' OR conname LIKE 'fk_bus_%';
```
Engine: start a job and check that rows arrive in its table, as before. For an alert test, add a rule (`POST /schemas/{id}/alerts`), restart the job, and check `GET /alerts/active`.

---

## 14. Rollback

1. Stop the engine and the backend.
2. Restore both dumps from §2.1:
   ```bash
   pg_restore -h <host> -U postgres -d meta_data_fast --clean --if-exists meta_data_fast_<date>.dump
   pg_restore -h <host> -U postgres -d fast_target   --clean --if-exists fast_target_<date>.dump
   ```
3. Deploy the previous code and the previous engine binary, then start them.

The migrations rename tables and columns, so the **old code can't run on the migrated DB**. Roll back the database together with the code.

---

## 15. Known limits and open items

| # | Item | Impact / plan |
|---|---|---|
| **B7** | The engine posts its `job` and `alert` notifications to `/auth/notifications` **without a token** | With auth **on**, those WebSocket notifications aren't delivered. **Readings, alert states and alert events are still recorded**; only the live push is missing. Needs a service token or an internal route |
| — | Alert rule edits apply at the **next job restart** | By design; tell users in the UI |
| — | No alert deadband | By design: a value flapping across the threshold gives one event per crossing |
| — | The spreadsheet import runs each row through the full service | Thousands of rows take tens of seconds; acceptable for occasional imports |
| — | OPC UA: anonymous login and security None only; one read request per node | Fine for open servers; a site needing security won't connect |
| — | Source / BMS categories accept no kinds yet (`kinds_json = []`) | Change it in the DB when decided: `UPDATE app_equipment_category SET kinds_json='["single"]' WHERE id='source';` |
| — | The demo UI in `apps/desktop` is out of date with this model | Not part of production |
| — | Readable element codes (e.g. `PCC-003`) | Not built; the Element ID is the generated `eq_…` |

---

## 16. Files in this release

**New:**
- `agent/plc_agent/api/equipment.py`: elements, types, zones, buses, relations, MFMs.
- `agent/plc_agent/api/equipment_import.py`: EMS import, template, export.
- `agent/plc_agent/api/alerts.py`: the alerts service.
- `agent/plc_agent/api/routers/equipment.py` and `routers/alerts.py`.
- `agent/tools/opcua_simulator.py`.
- Tests:
  - `test_equipment.py`, `test_equipment_import.py`, `test_alerts.py`, `test_b5_fixes.py`, `test_v2_high_features.py`;
  - e2e: `test_alerts_e2e.py`, `test_opcua_e2e.py`.

**Changed:**
- **Backend core:** `agent/plc_agent/api/appdb.py` (schema, migrations, seeds), `app.py` (routers), `store.py` (delete guards).
- **Routers:** `routers/mappings.py` (save fix), `routers/tables.py` (table delete guard), `routers/devices.py`, `routers/schemas.py`, `routers/jobs*.py`.
- **Engine:** `agent/rust_jobs/src/main.rs` (alerts, OPC UA).
- **Tests:** `agent/tests/conftest.py`.
- **Dependencies:** `requirements.txt` (`python-multipart`, `openpyxl`).
- **Dev tooling:** `validate_derived_params.py` (dev oracle only).

**Docs:**
- this file;
- `Logger-v2-backend-mapping.md` (frontend contract answers; §13–§17 cover this release);
- `API_DOCUMENTATION.md`, `FRONTEND_API_REFERENCE.md`, `METADATA_DOCUMENTATION.md`.

> **Note:** none of this is committed yet. Commit and tag the release before deploying, so the rollback in §14 has an exact code version to return to.
