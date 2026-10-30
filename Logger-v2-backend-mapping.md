# Logger v2 — how our backend answers the contract

Companion to `Logger-v2-backend-contract.md`. It covers what the v2 frontend can use today, where it must change, and which backend changes are still open.

- **Backend:** the FastAPI agent in `agent/plc_agent/api`, port **5175**. It is not the Django/DRF repo the contract assumes.
- **Precedence:** where the contract and the backend's electrical model disagree, **the backend model is the one to follow** (agreed with the backend owner). The contract's §3.6/§3.7 shapes are replaced by the `/equipment` API described in §3 below.
- **Fields at the time of writing:** as of 2026-10-22. Every path and key below was checked against the running code.

---

## 1. TL;DR

| Area | Status |
|---|---|
| Connection, auth, errors | Works, but with **different conventions**: no trailing slashes, `{"items": …}` envelopes, camelCase keys, `{"detail": "CODE"}` errors. See §2 |
| **Electrical tab** (contract §3.6) | **Built**, on a different model: `/equipment` (§3). It is not `/element-types/` + `/elements/` |
| **Map / topology** (contract §3.7) | **Not built yet**. Meter attachments exist, but on equipment and buses (§3.6), not in a topology document |
| **Comms tab** (contract §3.1, §3.8) | Devices and gateways **exist** (§4). There is no logger-server level (only one server, not needed). Verification stays as it is today |
| Schemas, tables, mappings, jobs (contract §3.2–3.4) | Exist with **different paths and shapes**. Some contract routes are missing (§5) |
| AI assistant (contract §3.5) | A different API, off by default. Set `assistant.enabled: false` (§5.5) |
| **Alerts on readings** (not in the contract) | **Built** 2026-10-25: levels, schema rules, per-table overrides, live state and history (§11) |

---

## 2. Connection and global conventions

### 2.1 Base URL, prefix, slashes
- Routes are mounted at the **root**: `http://<host>:5175/equipment`, `/devices`, …. There is no `/core` or `/api` prefix, so run the dev proxy with `LOGGER_DEV_API_PREFIX=''`.
- **No trailing slashes.** `GET /devices/` answers **307 → `http://localhost:5175/devices`**. Through the Vite proxy that redirect sends the browser to `localhost`, which fails.

  **Frontend change:** drop the trailing slash on every path, `/devices` not `/devices/`.
- Tailscale address: `http://100.90.185.31:5175`. Health check: `GET /health` → `{"status":"ok","agent":"plc-agent","version":"…"}` (no auth).

### 2.2 Auth
- **Token:** `Authorization: Bearer <Keycloak access token>`. The header `X-Agent-Token` is also accepted.
- **Accepted issuers:** `KC_URL` + `KC_REALM` (`agent/.env`, currently `http://localhost:8080/keycloak`, realm `desktop`), a few built-in localhost / Tailscale proxy issuers, and anything listed in `KC_ALLOWED_ISSUERS`. To accept a new issuer, add it to `KC_ALLOWED_ISSUERS` (no code change).
- **Roles:** reads need the realm role `logger-read`; writes need the realm role `logger-write` **or the client role `neuract-admin`** (any client, e.g. `resource_access["neuract-logger"]`). Write implies read. *(Changed 2026-10-23, B1.)*
- **401 vs 403:** a missing, invalid or expired token is a real **401**; a missing role is **403**. This already matches BR-19.
- **Dev mode:** `LOGGER_AUTH_DISABLED=1` (currently on in `agent/.env`) treats every request as an admin. This is the equivalent of the contract's `DEV_ANONYMOUS_AUTH`, so `auth.mode: "none"` works against it as is.
- **Routes with no token:** only `/health`, `/version` and the auth endpoints. Since 2026-10-23 (B4), the `/devices`, `/schemas`, `/tables` and `/jobs2` GETs need a token like every other router.

### 2.3 Shapes
| Contract (DRF) | Ours |
|---|---|
| Lists are bare arrays `[ … ]` | `{"items": [ … ]}` (`/tables` adds `total`, `page`; job metrics and runs use `{"ok": true, "data": [ … ]}`) |
| Create → 201 with the object | 200 `{"success": true, "item": { … }}` |
| Update → 200 with the object | 200 `{"success": true, "item": { … }}` |
| Delete → 204 | 200 `{"success": true}` |
| snake_case keys | **camelCase** (`latencyMs`, `unitId`, `gatewayId`, `categoryId` …). A few older gateway keys are snake_case (`nic_hint`, `last_ping`) |
| Timestamps with `Z` | Equipment uses `…Z`. Job runs and migrations emit `+05:30`; it parses, but it isn't `Z` |

### 2.4 Errors
- **Our errors:** `{"detail": "CODE"}` or `{"detail": "CODE: context"}`, for example `{"detail": "EQUIPMENT_EXISTS: PCC-01"}`. Status: 400 for validation, 404 for missing, 409 for conflicts.
- **Auth errors:** `{"detail": {"success": false, "error": "PERMISSION_DENIED|TOKEN_EXPIRED|INSUFFICIENT_ROLE", "message": "…"}}`. Here `detail` is an object.
- **Body validation by FastAPI:** 422 `{"detail": [{"loc", "msg", "type"}]}`.
- **No DRF field errors** (`{"name": ["…"]}`), and no HTML 500 pages to sniff.

**Frontend change:** read `detail`. If it's a string, take the `CODE` before the first `:` as the machine code and the rest as the message. If it's an object, use `detail.message`. The contract's 401/403 handling (§5 there) works unchanged.

---

## 3. Electrical tab → `/equipment` (replaces contract §3.6 and the meter part of §3.7)

### 3.1 The model, and how it differs from the contract

```
Category (DB-managed)            type = single | distribution, plus field definitions
 └─ Equipment                    name, subtype, spare, description, values
     ├─ distribution: buses      Bus A, B…  (= the contract's "sections")
     │    each bus: incomer/outgoer capacity, allowed categories per side,
     │              attached equipment per side, MFMs on incomer/outgoer points,
     │              coupler to the next bus
     └─ single: itself           incomer/outgoer capacity, allowed categories per side, MFMs
```

| Contract concept | Ours |
|---|---|
| `families` + `types` catalog (`GET /element-types/`) | **Categories** (`GET /equipment/categories`): Source, Transformer, HT Panel, LT Panel, Load. These are edited in the DB, with no write endpoint. There is no separate family/type level |
| Type `fields` (`quantity` / `count` / `choice`) | Category `fields`: `quantity` (with `units`), `choice` (with `options`), `text`; `required`; optional `role` (`voltage`, `voltage.in`, `voltage.out`) |
| Element `values` `{id: {value, unit, source}}` | `values` `{id: {value, unit}}`. The value is stored as a **number**, and there is no `source` |
| `sections` `[{max_incomers, feeders}]` | `buses[]`, each with `incomers`, `outgoers` (numbers) and a `name` |
| `couplings` `[[0,1]]` | `coupledNext: true` on the bus (neighbours only) |
| `rules.incoming` / `rules.outgoing` (types) | `incomingCategories` / `outgoingCategories`: **category ids**. Per **bus** on distribution equipment, on the **equipment** for single equipment. An empty list means not restricted |
| `limits.maxIn` / `maxOut` | Single equipment: `maxIncomers` / `maxOutgoers`. Buses: `incomers` / `outgoers` |
| `spare` | `spare` (same meaning: "Spare / not on map") |
| Readiness (computed in the frontend from the catalog) | **Computed by the server:** `readiness: {ready, missing: [field labels]}`. The frontend should display it, not compute it |
| Voltage column | Computed by the server: `voltage: {in, out, text}`, e.g. `"33 kV → 11 kV"` |
| `meter_attachments` (topology, with point `element`/`incomer`/`feeder` + `slot`, kind) | MFMs on **single equipment** (several allowed), or on a **bus** with `role: incomer` / `outgoer`. No slot index, no meter `kind` (no MFM/PQM split). A device sits in one place only |
| Element → element `connections` (topology) | Two kinds, both checked at both ends. **Bus attachments:** equipment attached to a bus as an incomer or outgoer. **Direct links:** single → single, e.g. Grid → TF or UPS → load (`POST /equipment/{id}/connections`). Each connection has a `position` (feeder order). Multiple parents are allowed; loops in flow direction are rejected |
| `If-Match` / `updated_at` concurrency (BR-22) | **Supported (2026-10-23):** an integer `version` per equipment, sent as `If-Match: <version>`; a stale one answers 409 `VERSION_CONFLICT` (§8 A1) |
| `subtype`, `nameplate`, `rules_lock`, `bridge`, `kind_of`, `phase_compat`, `voltage_tolerance_pct`, `rule_settings` | `subtype` is supported. The others don't exist (no voltage, phase or frequency compatibility checks) |
| **Not required in ours** | — (the old `nav_category` requirement is gone in this model) |

### 3.2 Endpoints
All endpoints are under `/equipment` and need a token (`logger-read` to read, `logger-write` to write).

**Catalog**
- `GET /equipment/categories` → `{"items": [{id, name, type, sortOrder, fields: [...], defaultCapacity?}]}`. `defaultCapacity` is set on single categories only.

**List** — the table on the Electrical tab
- `GET /equipment?categoryId=&type=&q=&metered=&ready=&used=&spare=` → `{"items": [<equipment>]}`.
  - `q` searches name and subtype.
  - `metered`, `ready`, `used` and `spare` each take `true` / `false`. These are the screen's filter chips.

| Column | Key |
|---|---|
| Element | `name`; subtitle `categoryName · subtype` |
| Voltage | `voltage.text` |
| Metering, single equipment | `metering.meters[]`, each shown as `deviceName · U{unitId}` / `gatewayName · host`. Empty means "No meter attached" |
| Metering, distribution | `metering.pointsMetered` / `metering.points` "points metered", plus `metering.meterCount` MFMs |
| Connection readiness | `readiness.ready`, plus `readiness.missing.length` "fields missing" |
| Map | `used`. **For now** this means "connected on a bus"; it will mean "on the map" once the map exists |
| "Spare" tag | `spare` |

**Equipment**
- **`POST /equipment`** creates one. Body: `{name, categoryId, subtype?, spare?, description?, values?}`; for single equipment also `{maxIncomers?, maxOutgoers?, incomingCategories?, outgoingCategories?}`.
  - **Name:** required and unique, ignoring case (409 `EQUIPMENT_EXISTS`).
  - **Starting state:** distribution equipment starts with Bus A. Single equipment starts with its category's `defaultCapacity`.
- **`GET /equipment/{id}`**, **`PUT /equipment/{id}`**, **`DELETE /equipment/{id}`**.
  - **PUT** accepts the same keys as POST.
  - **`values`:** a **merge**. Only the fields you send change, and `null` or `""` clears one.
  - **`categoryId`:** can only change to a category of the same type (400 `CATEGORY_TYPE_CHANGE`).
  - **DELETE:** returns 409 `EQUIPMENT_IN_USE` while the equipment is attached to a bus.

**Buses** (distribution equipment) — Bus sections, Bus section A/B, Bus Coupling, Rules

| Call | Body |
|---|---|
| `PUT /equipment/{id}/buses/count` | `{count}` (1–26): the "Bus sections" selector |
| `POST /equipment/{id}/buses` | `{name?, incomers?, outgoers?, incomingCategories?, outgoingCategories?}` |
| `PUT /equipment/buses/{busId}` | `{name?, incomers?, outgoers?, coupledNext?, incomingCategories?, outgoingCategories?}`. Here `incomers` = "Maximum incomers" and `outgoers` = "Outgoing feeder capacity" |
| `DELETE /equipment/buses/{busId}` | The last bus, or a bus with anything attached, is refused (409) |

**Connections** — what feeds what
- `POST /equipment/buses/{busId}/equipment` with `{equipmentId, role: "incomer"|"outgoer"}`, and `DELETE /equipment/buses/{busId}/equipment/{equipmentId}`.
- The checks give these codes:
  - `ALREADY_ATTACHED`: the equipment is already on this bus.
  - `CATEGORY_NOT_ALLOWED`: a category rule fails, on the bus side, or on the equipment's own side when it is single equipment.
  - `NO_SPARE`: a side is at capacity, on either end.
  - `SELF_ATTACH`: a panel on its own bus.
  - `CYCLE`: the connection would form a loop.
- Each equipment response has `attachedTo: [{busId, busName, equipmentId, equipmentName, role}]`.

**MFMs**
- **Single equipment:** `POST /equipment/{id}/meters` `{deviceId}`, `DELETE /equipment/{id}/meters/{deviceId}`.
- **Distribution, per bus point:** `POST /equipment/buses/{busId}/meters` `{deviceId, role}`, `DELETE /equipment/buses/{busId}/meters/{deviceId}`.
- **Pickers:** `GET /equipment/available_meters` lists unattached devices, with `unitId`, `gatewayName` and `host`.
- **Conflicts:** a device is in one place only (409 `METER_IN_USE`). Deleting an attached device returns 409 `DEVICE_ATTACHED_TO_EQUIPMENT`.

Full request and response examples: `API_DOCUMENTATION.md` §24.

### 3.3 What the Electrical tab must change (frontend)
1. **Remove the catalog dependency.** Drop `/element-types/` and drive the form from `GET /equipment/categories`:
   - render `fields` by `kind`;
   - for single categories, show capacity and allowed incoming / outgoing;
   - for distribution categories, show Bus sections.
2. **Use the server's readiness and voltage.** Show `readiness` and `voltage` as returned.
3. **Edit rules per bus on panels.** For distribution panels, the Rules block (allowed incoming / outgoing) is **per bus**. Show it inside each "Bus section" card, not once per panel.
4. **Drop "Multiple incomers: Allowed".** It's covered by the bus `incomers` capacity.
5. **Couplers.** Show the bus coupler as `coupledNext` on bus *i* (A ↔ B means Bus A `coupledNext: true`).
6. **Metering line.** Build "15 of 20 points metered · 15 MFMs" from `metering`. Drop the "· 2 PQMs" part, because there is no meter kind.
7. **Hide what isn't built.** Hide Import / Export, View / Upload Nameplate and "View in map" (§6).

---

## 4. Comms tab → `/devices` and `/networking` (contract §3.1, §3.8)

| Screen | Ours |
|---|---|
| GIC rows with their meters | `GET /networking/gateways_with_devices` → `{"items": [{id, name, host, ports, status, last_ping, devices: [...], deviceCount, …}]}` |
| **+ Add GIC** / edit / delete | `POST /networking/gateways` `{name, host, ports, …}`, `PUT` / `DELETE /networking/gateways/{gid}` |
| **Ping** | `POST /networking/gateways/{gid}/ping` with a JSON body (`{}` at least; **an empty body gives 422**) → `{ok, lossPct, min, avg, max, samples}` or `{ok: false, code, message}`. `/tcp` checks the port. Limit: one call every 3 s per gateway (429) |
| Direct devices | `GET /devices` → `{"items": [...]}`; direct devices are those with `gatewayId: null` |
| Device item | `{id, name, protocol, status, latencyMs, lastError, autoReconnect, unitId, port, gatewayId, params: {host, …}}`. These are flat keys, **not** `modbus_config` / `opcua_config` |
| Add / edit / delete device | `POST /devices` `{name, protocol, params: {host}, port, unitId, gatewayId?}` (it runs a connection test and creates the device even if the test fails). `PUT /devices/{id}` changes only `name`, `autoReconnect`, `unitId`, `port`, `gatewayId`. `DELETE /devices/{id}` |
| Test / Verify | `POST /devices/{id}/quick_test` → `{success, latencyMs, error}`. **It stores the device status** (`connected` / `degraded`). There's no `?save=1`; verification stays like this (agreed) |
| Connect / disconnect | `POST /devices/{id}/connect` → `{success, latencyMs}` (a failure is 400 `{"detail": …}`); `/disconnect` → `{success}` |

**Not provided (agreed):**
- **Logger-server level (BR-31):** there is a single server, so show gateways at the top level.
- **Electrical attachment column:** not provided.
- **Meter kind and `serial_protocol`:** not provided.

**Frontend changes:**
1. **Paths:** gateways live under `/networking/gateways`.
2. **Device keys:** read `params.host`, `port` and `unitId`, not `modbus_config`.
3. **Ok flags:** read `success`, not `ok`, on quick_test / connect / disconnect. Ping uses `ok`.
4. **Ping body:** send `{}` as the body.

---

## 5. Schemas, tables, mappings, jobs, AI (contract §3.2–3.5)

These existed before v2. They work, but their paths and shapes differ a lot from the contract. **Recommendation:** keep the v1 screens' behaviour behind adapters in the frontend's `src/data/*/wire.ts`, or hide these screens until each item in §7 is decided.

### 5.1 Schemas
| Contract | Ours | Notes |
|---|---|---|
| `GET /schemas/` | `GET /schemas` → `{"items": [{id, name, fields: [{key, type, unit, scale, desc, formula, eval_order}]}]}` | Fields come with the list. No `created_at` and no `description` |
| `GET /schemas/{id}/` | **missing** | Use the list |
| `POST /schemas/` | `POST /schemas` `{name, fields: [{key, type, unit, scale, desc, formula?}]}` | The keys are **`type` and `desc`**: `field_type` / `description` are ignored, and a missing `type` becomes `float32`. A derived field means a `formula` is present. Types: `float32 float uint16 uint16_enum int16 uint32 int32 float64 uint64 int64 bool16`; **`bool`, `int` and `string` are rejected** |
| `PUT /schemas/{id}/` | **missing** | Field-level only: `POST /schemas/{id}/fields`, `PATCH` / `DELETE /schemas/{id}/fields/{key}`. No rename |
| `DELETE /schemas/{id}/` | `DELETE /schemas/{id}` | In use → **400** `SCHEMA_IN_USE` |
| `fork/` | missing | |

### 5.2 Tables and mappings
| Contract | Ours | Notes |
|---|---|---|
| `GET /tables/` | `GET /tables` → `{success, total, page, items}` (**paginated**, `pageSize` 50) | Items: `{id, name, schemaId, dbTargetId, deviceId, status: not_migrated|migrated, mappingHealth, mappingStatus, parentSchema, …}` |
| `GET /tables/{id}/` | `GET /tables/{id}` → `{item, schema, mappingHealth}` | Rows: `GET /mappings/{tableId}` → `{item: {deviceId, rows: {fieldKey: {protocol, address, dataType, scale, deadband, encoding}}}}`. A dict keyed by field, with no row ids |
| `POST /tables/` | `POST /tables/bulk_create` `{schemaId, names: [...], dbTargetId?, deviceId?}` | |
| `PATCH /tables/{id}/` | `PATCH /tables/{id}` `{name?, schemaId?, dbTargetId?}`; device via `POST /tables/{id}/bind_device` `{deviceId}` / `unbind_device` | |
| `DELETE /tables/{id}/` | `DELETE /tables/{id}` | 409 `TABLE_HAS_RUNNING_JOBS` |
| `POST /tables/{id}/mappings/bulk/` | `POST /tables/{id}/mappings/bulk` `{mappings: [{field_key, protocol, address, data_type, scale, deadband}], deviceId?}` | Upsert, as in the contract. **`byte_order` is dropped.** Response: `{item: {deviceId, rows}}`, without `created` / `updated` |
| `POST /tables/{id}/mappings/validate/` | `POST /tables/{id}/mappings/validate` → `{success, health, problems: [{field, code, message}]}` | A **static** check: no live read values, no `total` / `ok` / `failed` |
| Delete one row | `DELETE /mappings/{tableId}/{fieldKey}` | Persists (fixed 2026-10-23, B5). A derived row answers 400 `DERIVED_ROW` |
| Row export / import | `GET /mappings/{tableId}/export`, `POST /mappings/{tableId}/import` `{rows: {…}, mode?}` | **Merges by default.** It replaces the non-derived rows only with `"mode": "replace"`. A body without `rows` answers 400 `ROWS_REQUIRED` (fixed 2026-10-23, B5) |
| `POST /tables/{id}/migrate/` | `POST /tables/{id}/migrate` → `{item: {id, name, status}}` | 404 only for an unknown table. A failure answers 500 (or the 4xx that caused it) with `MIGRATE_FAILED: …` (fixed 2026-10-23, B5) |
| List import / export, `set_validated` | missing | |

### 5.3 Jobs
- **Use `/jobs2`, not `/jobs`.**
  - **`/jobs2`** only changes the job status. The Rust engine does the logging, which is how logging is meant to work.
  - **`/jobs`** starts in-process Python acquisition threads, which can write twice alongside Rust.
- **Endpoints:** `GET /jobs2`, `POST /jobs2`, `POST /jobs2/{id}/start|pause|stop`, `DELETE /jobs2/{id}`, `GET /jobs2/{id}/runs`.
- **Keys:** `type` (`continuous` / `trigger`), `tables`, `intervalMs`, `enabled`, `batching`, `cpuBudget`.
- **Responses:** `{success, message}` (no `status`); runs come as `{ok, data: [...]}`.
- **Missing:** `GET /jobs/{id}/`, `PATCH`, resume / restart, `events`.
- **Metrics:** `GET /jobs/metrics/summary` → `{ok, data: [{jobId, reads, readErrors, writes, writeErrors, readP95, …}]}`.

### 5.4 Cross-cutting
- **`/capabilities/` and `/me/`:** missing. Keep using `config.json` flags.
- **Health:** `GET /health` exists.

### 5.5 AI assistant
Only mounted when `LOGGER_ENABLE_AI=1` (it's off). It's a different API: `/ai/sessions` with an NDJSON `chat` stream and per-session `approve` / `apply`, and there is **no `/ws/ai/sessions/{id}/` socket**. **Set `"flags": {"assistant.enabled": false}`.**

---

## 6. Not built yet

| Feature | Contract | Plan |
|---|---|---|
| Map / topology document (placed elements, connections, revision) | BR-29 | Later. Bus connections (§3.2) already give the "what feeds what" tree |
| Nameplate upload / extract | BR-32 | Later |
| Excel import / export of elements | BR-32 | Later |
| Logger servers | BR-31 | Not needed (single server) |
| Meter kind (MFM / PQM), verification persistence | BR-30, BR-31 | Not planned for now |
| Capabilities map, `/me/`, events, pagination opt-in | BR-01, BR-21, BR-17, BR-20 | Not planned for now |

---

## 7. Open items

### Backend (decisions for the backend owner; not done)
| # | Item | Why |
|---|---|---|
| B1 | ✅ Done 2026-10-23: the client role `neuract-admin` grants read + write | |
| B2 | Optional: accept both `/x` and `/x/` without a redirect (turn `redirect_slashes` off and register both) | Lets the frontend keep the DRF-style paths |
| B3 | `POST /networking/gateways/{gid}/ping` should accept an empty body | It answers 422 today |
| B4 | ✅ Done 2026-10-23: those GETs require a token | |
| B5 | ✅ Done 2026-10-23: row delete persists, import merges unless `mode: replace`, migrate errors are 4xx/500 | |
| B6 | Optional: rename `/jobs2` → `/jobs` once the Python-thread `/jobs` router is retired | |
| B7 | The engine's `alert` / job notifications need a service token (or an internal route) before auth is switched back on | They're posted without a token today (§11.3) |

### Frontend (to adapt to this backend)
| # | Item |
|---|---|
| F1 | Base URL without a prefix; **no trailing slashes** |
| F2 | Unwrap `{"items": …}` and `{"success", "item"}`; treat a 200 delete as success; read camelCase keys |
| F3 | Error parsing: `detail` string `CODE: message`, or object `{error, message}` |
| F4 | Electrical tab on `/equipment` (§3.3) instead of `/element-types/` + `/elements/` |
| F5 | Comms tab on `/networking/gateways*` and `/devices` with the flat device keys (§4) |
| F6 | Jobs on `/jobs2` |
| F7 | Hide AI, the map, nameplate, Excel import / export, logger servers and meter kinds |
| F8 | Alerts (§11): rule editors on the schema and table screens, live badges from `/alerts/active`, a history list from `/alerts/events`, and handle WebSocket messages of `type: "alert"` |

---

## 8. Answers to `Logger-v2-backend-asks.md` (2026-10-23)

Items marked **shipped** are live on 5175 and covered by tests. Full request and response shapes are in `API_DOCUMENTATION.md` §24.

### A1. Versions on equipment writes — shipped
- **The field:** every equipment has an integer `version`, starting at 1, plus `updatedAt` (Z). Buses also return `equipmentVersion`.
- **What bumps it:** any change to the equipment itself, its buses, its rules, its attachments, connections made to or from it, or its meters.
- **Attachments bump both ends:** attaching, detaching or reordering bumps the owner of the bus or node **and** the attached equipment. Deleting a panel bumps everything that was attached to it.
- **Writes check it:**
  - **Which version to send:** writes accept `If-Match: <version>` (`"3"` and `W/"3"` are also accepted).
  - **Which equipment is checked:** for bus, attachment, connection and meter routes, the equipment that **owns** the bus or node.
  - **Stale:** 409 `VERSION_CONFLICT: <id>`. A non-integer value: 400 `IF_MATCH_INVALID`.
  - **No header:** last write wins, as before.
- **Attach / detach / reorder / direct links return both changed objects:**
  `{"success": true, "item": <bus, when on a bus>, "owner": <equipment>, "attached": <equipment>}`.

### A2. Edits that shrink or break what is attached (today's behaviour: every case is refused)
| Case | Answer |
|---|---|
| Bus `incomers` / `outgoers` set below the number attached | 409 `CAPACITY_BELOW_ATTACHED` (and below the number of metered points: 409 `CAPACITY_BELOW_METERED`) |
| `buses/count` lowered | The **trailing** buses (highest `sortOrder`) are removed. If any has attachments or meters: 409 **`BUS_NOT_EMPTY`** (that's the code, not `BUS_IN_USE`). `coupledNext` on the new last bus **is cleared** |
| `maxIncomers` / `maxOutgoers` set below what is connected | 409 `CAPACITY_BELOW_ATTACHED` |
| Allowed-category change that breaks existing connections | Refused, 409 `ATTACHED_OUTSIDE_CATEGORIES` (nothing is accepted-and-marked) |
| `categoryId` change that a rule elsewhere excludes | Refused, 409 `CATEGORY_NOT_ALLOWED_ON_BUS`. **Both ends are re-checked:** the bus or source it is connected to, **and** the own rules of single equipment connected to it (fixed today; previously a panel could change category under its loads' rules) |
| DELETE on equipment that has meters | Allowed: its meters are detached and the devices kept. DELETE is refused (409 `EQUIPMENT_IN_USE: connected to …`) only while the equipment is connected as a member somewhere |
| `spare: true` on attached equipment | Accepted. `spare` is informational and has no checks |
| Is `PUT /equipment/{id}` partial? | Yes, at the top level. `values` merges per field (`null` clears one) |

### A3. Feeder order and which feeder a bus meter measures — shipped
- **Order:**
  - **Positions:** every connection has a `position`, 0-based and compact per node and side. It's returned on `incomingEquipment[]` / `outgoingEquipment[]` and on `attachedTo[]`, and lists are sorted by it.
  - **Attaching:** attach accepts an optional `position` (inserted there; a value past the end appends).
  - **Reordering:** `PUT /equipment/buses/{busId}/equipment/{eqId}` with `{"position": n}`. Direct links have the same: `PUT /equipment/{id}/connections/{eqId}`.
  - **Detaching:** the others are renumbered and keep their order.
- **Bus meters:** `POST /equipment/buses/{busId}/meters` accepts an optional `equipmentId`, the feeder it measures. It must be attached to that bus on the same side, otherwise 400 `FEEDER_NOT_ON_BUS`. It's returned as `meters[].equipmentId`. If the feeder is detached, the meter stays on the point with `equipmentId: null`.
- **Points:** per bus, `points = incomers + outgoers` (the capacity) and `pointsMetered = min(#incomer meters, incomers) + min(#outgoer meters, outgoers)`. `metering.points` / `pointsMetered` on a panel are the sums over its buses.
- **Panel → panel:** confirmed, your plan matches. The downstream panel is stored as an **outgoer on the upstream bus**.
  - **Checked:** only the upstream bus's categories and capacity count for `NO_SPARE`.
  - **Not recorded:** which bus of the downstream panel receives the link. Its own buses' rules aren't applied.

### A4. Sign-in and serving
- **Roles:** shipped. The client role `neuract-admin` (in any client, including `resource_access["neuract-logger"]`) grants read and write. The realm roles `logger-read` / `logger-write` keep working.
- **B4:** shipped. `/devices`, `/schemas`, `/tables` and `/jobs2` GETs need a token.
- **Keycloak for the browser** (browser-reachable URL, realm, public PKCE client with your origins, issuer): this is an operations item, to be sent separately for the shared instance and each plant. Any issuer can be accepted with `KC_ALLOWED_ISSUERS` (no code change).
- **Testing auth:** the shared instance runs with `LOGGER_AUTH_DISABLED=1`, which is why `Bearer bad` passes. A second instance with auth on can be provided on request.
- **Serving the UI from the API's own origin** through a reverse proxy: confirmed, no CORS change is needed for same-origin requests.

### A5. B5 fixes — shipped
- `DELETE /mappings/{tableId}/{fieldKey}` persists in the target DB. Derived rows answer 400 `DERIVED_ROW`.
- `POST /mappings/{tableId}/import` answers 400 `ROWS_REQUIRED` without `rows`. It **merges by default** and replaces only with `"mode": "replace"`. Any other mode answers 400 `MODE_INVALID`. The response includes the `mode` that was applied.
- `POST /tables/{id}/migrate`: 404 `TABLE_NOT_FOUND` only for an unknown table. A failure is 500, or the 4xx that caused it, with `MIGRATE_FAILED: <reason>`.

### A6. Something to integrate against
Not done yet (not in this round). API docs §24 is up to date.

### Should have
- **S1 (error-code table), S2 (`/tables` paging fixes), S4 (Z timestamps):** not in this round.
- **S3 (meter kind):** **won't do.** There will be many meter types, so the backend won't distinguish MFM / PQM or other kinds on attachments.

### Questions
- **Q1, the map document:** there's no date yet. The direction matches your suggestion: connections stay in the equipment graph (bus attachments + direct links), and a later map document would only hold layout.
- **Q2, card-to-card:** **now supported** (shipped today). `POST /equipment/{sourceId}/connections` with `{"equipmentId": "<target>", "position"?}` links single → single, e.g. Grid → TF or UPS → load.
  - **Rules:** checked at both ends (the source's outgoing side, the target's incoming side).
  - **Loops:** rejected.
  - **Panels:** a panel answers 400 `USE_BUS`; panels connect through their buses.
  - **In responses:** the source lists them in `outgoingEquipment[]`, and the target shows `attachedTo[]` with `direct: true` (`busId` / `busName` null).
  - **Changes:** `PUT` (position) and `DELETE /equipment/{sourceId}/connections/{targetId}`.
- **Q3, how the existing APIs behave:** to follow in a separate note.

---

## 9. Answers to `Logger-v2-backend-asks_2.md` — feature gaps (2026-10-23)

A1–A6, S1–S4 and Q1–Q3 repeat the first asks file and are answered in §8. Of the feature gaps, the **high group** is done in this round: F1, F3, F4, F5, F7, F8, F10 are shipped, and F2, F6, F9 won't be done. The medium and later items (F11–F29) and the nice-to-haves will follow in a later round.

### Shipped
**F1. Edit a job**
- **Routes:** `GET /jobs2/{id}` → `{"item": <job>}`, and `PATCH /jobs2/{id}` with any of `name`, `tables`, `intervalMs` (≥ 100), `enabled`, `cpuBudget` (`low` / `balanced` / `high`), `type` (`continuous` / `trigger`), `triggers` → `{"success": true, "item": <job>}`.
- **Running jobs:** a **running job must be stopped or paused first**, otherwise 409 `JOB_RUNNING`. The Rust engine reads a job's config only when it starts the job, so an edit to a running job would never take effect.
- **Validation errors:** `NAME_REQUIRED`, `TYPE_INVALID`, `NO_TABLES` / `NO_MAPPED_COLUMNS`, `INTERVAL_INVALID`, `ENABLED_INVALID`, `CPU_BUDGET_INVALID`, `TRIGGERS_INVALID`.

**F3. Rename a schema**
- **Routes:** `GET /schemas/{id}` → `{"item": <schema>}`, and `PATCH /schemas/{id}` with `{name?, description?}` → `{"success": true, "item"}`.
- **Duplicates:** a name already used, ignoring case, gets 409 `SCHEMA_EXISTS: <name>`.
- **Fields:** still edited through `/schemas/{id}/fields`.

**F4. Schema description**
- **Where:** `description` on `GET /schemas`, `GET /schemas/{id}`, `POST /schemas` and the schema PATCH. `null` or `""` clears it.

**F5. Field types and units are DB-managed lists.** Neither list has write endpoints; both are edited in the DB, like equipment categories.
- **Field types:** `GET /schemas/field_types` → `{"items": [{id, label, encoding}]}`.
  - **`id`:** the word a field's `type` may use, matched case-insensitively.
  - **`encoding`:** the register decoding the engine applies. Mapping rows get the encoding, so `REAL` now decodes as `float32` instead of falling back to one 16-bit register.
  - **Seeded:** the usual words plus the stored older ones, `real` → `float32` and `boolean` → `bool16`. Schemas using them can be edited and copied.
  - **Derived fields:** their type must decode as `float32` or `float64`.
- **Units:** `GET /schemas/units` → `{"items": [{id, label}]}`.
  - **Seeded:** a common set plus every unit already used in stored schemas.
  - **Validation:** a field `unit` must be in the list or empty (400 `UNIT_INVALID:<unit>`). An unknown type is 400 `FIELD_TYPE_INVALID:<word>`.

**F7. Edit a device's address**
- **What `PUT /devices/{id}` now applies:** `protocol` and `params`, merged into the stored params (`host`, `endpoint`, …; `null` removes a key, and a masked `"***"` secret keeps the stored value). It also applies `name`, `autoReconnect`, `unitId`, `port` and `gatewayId` (`null` = direct device).
- **When the protocol or params change:** the device goes back to `status: "disconnected"` and its saved verification is cleared.
- **Errors:** `PROTOCOL_INVALID`, `PARAMS_INVALID`, `GATEWAY_NOT_FOUND`, 404 `DEVICE_NOT_FOUND`.

**F8. Keep verification results**
- **Saving:** `POST /devices/{id}/quick_test` stores its result, and the response also carries `verification`.
- **Reading:** `GET /devices` returns each device's last result as `verification: {ok, latencyMs, error, at (Z)}`, or `null` if it was never verified or its address changed since.
- **No history:** only the last result is kept.

**F10. Resume**
- **Route:** `POST /jobs2/{id}/resume`. It works only from `paused` (409 `JOB_NOT_PAUSED` otherwise) and sets the job back to running; the engine picks it up on its next poll, with the job's current config.
- **No run to continue:** jobs on `/jobs2` (the Rust engine) have **no run records**, since `/jobs2/{id}/runs` only lists runs of the old `/jobs` router. So there's no run to continue: resume means "start again from paused", with no new run record created.

### Won't do
- **F2** (batch size on jobs), **F6** (change a table's schema), **F9** (live job metrics for `/jobs2`).

### Later
F11–F29 and the nice-to-haves will be done in a later round.

---

## 10. Example requests and responses (what shipped on 2026-10-23)

These are real responses captured from the API on a test database; ids and timestamps will differ. Where a response repeats a full equipment or bus object, the repeated object is trimmed to the relevant keys, and `"…"` marks what was left out.

### Equipment: create
Single equipment (the full object):

```http
POST /equipment
{"name": "TF-01", "categoryId": "transformer", "subtype": "33/0.415 kV", "values": {"primary_voltage": {"value": "33", "unit": "kV"}, "secondary_voltage": {"value": "415", "unit": "V"}}, "outgoingCategories": ["lt_panel"]}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "eq_1792745477326_4dbf",
    "name": "TF-01",
    "categoryId": "transformer",
    "categoryName": "Transformer",
    "type": "single",
    "subtype": "33/0.415 kV",
    "spare": false,
    "description": null,
    "values": {
      "primary_voltage": {
        "value": 33.0,
        "unit": "kV"
      },
      "secondary_voltage": {
        "value": 415.0,
        "unit": "V"
      }
    },
    "voltage": {
      "in": "33 kV",
      "out": "415 V",
      "text": "33 kV → 415 V"
    },
    "readiness": {
      "ready": false,
      "missing": [
        "Rated capacity",
        "Phase"
      ]
    },
    "attachedTo": [],
    "version": 1,
    "createdAt": "2026-10-23T08:51:17Z",
    "updatedAt": "2026-10-23T08:51:17Z",
    "maxIncomers": 1,
    "maxOutgoers": 1,
    "incomingCategories": [],
    "outgoingCategories": [
      "lt_panel"
    ],
    "outgoingEquipment": [],
    "metering": {
      "meterCount": 0,
      "meters": []
    },
    "used": false
  }
}
```

Distribution equipment comes back with `buses` (Bus A) and `metering.points` / `pointsMetered` instead of `maxIncomers` / `outgoingEquipment`.

### A1. Versions
Bus update with a matching `If-Match` (the owning equipment's version):

```http
PUT /equipment/buses/bus_1792745477320_bd4b   -H 'If-Match: 1'
{"incomers": 1, "outgoers": 4}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "bus_1792745477320_bd4b",
    "equipmentId": "eq_1792745477320_6450",
    "equipmentVersion": 2,
    "name": "Bus A",
    "incomers": 1,
    "outgoers": 4,
    "incomingEquipment": [],
    "outgoingEquipment": [],
    "spareIncomers": 1,
    "spareOutgoers": 4,
    "meters": [],
    "points": 5,
    "pointsMetered": 0,
    "…": "incomingCategories, outgoingCategories, coupledNext, sortOrder"
  }
}
```

Stale version:

```http
PUT /equipment/eq_1792745477320_6450   -H 'If-Match: 1'
{"subtype": "Main PCC"}
```
→ **409**
```json
{
  "detail": "VERSION_CONFLICT: eq_1792745477320_6450"
}
```

Attach returns the bus plus **both** changed equipment, each with its new `version`:

```http
POST /equipment/buses/bus_1792745477320_bd4b/equipment   -H 'If-Match: 2'
{"equipmentId": "eq_1792745477326_4dbf", "role": "incomer"}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "bus_1792745477320_bd4b",
    "equipmentId": "eq_1792745477320_6450",
    "equipmentVersion": 3,
    "name": "Bus A",
    "incomers": 1,
    "outgoers": 4,
    "incomingEquipment": [
      {
        "id": "eq_1792745477326_4dbf",
        "name": "TF-01",
        "categoryId": "transformer",
        "categoryName": "Transformer",
        "type": "single",
        "position": 0
      }
    ],
    "outgoingEquipment": [],
    "spareIncomers": 0,
    "spareOutgoers": 4,
    "meters": [],
    "points": 5,
    "pointsMetered": 0,
    "…": "incomingCategories, outgoingCategories, coupledNext, sortOrder"
  },
  "owner": {
    "id": "eq_1792745477320_6450",
    "name": "PCC-01",
    "categoryId": "lt_panel",
    "type": "distribution",
    "version": 3,
    "attachedTo": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  },
  "attached": {
    "id": "eq_1792745477326_4dbf",
    "name": "TF-01",
    "categoryId": "transformer",
    "type": "single",
    "version": 2,
    "attachedTo": [
      {
        "busId": "bus_1792745477320_bd4b",
        "busName": "Bus A",
        "equipmentId": "eq_1792745477320_6450",
        "equipmentName": "PCC-01",
        "role": "incomer",
        "position": 0,
        "direct": false
      }
    ],
    "outgoingEquipment": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  }
}
```

### A3. Feeder order and feeder-named bus meters
Attach at a position:

```http
POST /equipment/buses/bus_1792745477320_bd4b/equipment
{"equipmentId": "eq_1792745477345_f1ab", "role": "outgoer", "position": 0}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "bus_1792745477320_bd4b",
    "equipmentId": "eq_1792745477320_6450",
    "equipmentVersion": 5,
    "name": "Bus A",
    "incomers": 1,
    "outgoers": 4,
    "incomingEquipment": [
      {
        "id": "eq_1792745477326_4dbf",
        "name": "TF-01",
        "categoryId": "transformer",
        "categoryName": "Transformer",
        "type": "single",
        "position": 0
      }
    ],
    "outgoingEquipment": [
      {
        "id": "eq_1792745477345_f1ab",
        "name": "AHU-02",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 0
      },
      {
        "id": "eq_1792745477341_05b6",
        "name": "AHU-01",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 1
      }
    ],
    "spareIncomers": 0,
    "spareOutgoers": 2,
    "meters": [],
    "points": 5,
    "pointsMetered": 0,
    "…": "incomingCategories, outgoingCategories, coupledNext, sortOrder"
  },
  "owner": {
    "id": "eq_1792745477320_6450",
    "name": "PCC-01",
    "categoryId": "lt_panel",
    "type": "distribution",
    "version": 5,
    "attachedTo": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  },
  "attached": {
    "id": "eq_1792745477345_f1ab",
    "name": "AHU-02",
    "categoryId": "load",
    "type": "single",
    "version": 2,
    "attachedTo": [
      {
        "busId": "bus_1792745477320_bd4b",
        "busName": "Bus A",
        "equipmentId": "eq_1792745477320_6450",
        "equipmentName": "PCC-01",
        "role": "outgoer",
        "position": 0,
        "direct": false
      }
    ],
    "outgoingEquipment": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  }
}
```

Reorder:

```http
PUT /equipment/buses/bus_1792745477320_bd4b/equipment/eq_1792745477345_f1ab
{"position": 1}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "bus_1792745477320_bd4b",
    "equipmentId": "eq_1792745477320_6450",
    "equipmentVersion": 6,
    "name": "Bus A",
    "incomers": 1,
    "outgoers": 4,
    "incomingEquipment": [
      {
        "id": "eq_1792745477326_4dbf",
        "name": "TF-01",
        "categoryId": "transformer",
        "categoryName": "Transformer",
        "type": "single",
        "position": 0
      }
    ],
    "outgoingEquipment": [
      {
        "id": "eq_1792745477341_05b6",
        "name": "AHU-01",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 0
      },
      {
        "id": "eq_1792745477345_f1ab",
        "name": "AHU-02",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 1
      }
    ],
    "spareIncomers": 0,
    "spareOutgoers": 2,
    "meters": [],
    "points": 5,
    "pointsMetered": 0,
    "…": "incomingCategories, outgoingCategories, coupledNext, sortOrder"
  },
  "owner": {
    "id": "eq_1792745477320_6450",
    "name": "PCC-01",
    "categoryId": "lt_panel",
    "type": "distribution",
    "version": 6,
    "attachedTo": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  },
  "attached": {
    "id": "eq_1792745477345_f1ab",
    "name": "AHU-02",
    "categoryId": "load",
    "type": "single",
    "version": 3,
    "attachedTo": [
      {
        "busId": "bus_1792745477320_bd4b",
        "busName": "Bus A",
        "equipmentId": "eq_1792745477320_6450",
        "equipmentName": "PCC-01",
        "role": "outgoer",
        "position": 1,
        "direct": false
      }
    ],
    "outgoingEquipment": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  }
}
```

A bus meter naming the feeder it measures:

```http
POST /equipment/buses/bus_1792745477320_bd4b/meters
{"deviceId": "dev_1792745477373", "role": "outgoer", "equipmentId": "eq_1792745477341_05b6"}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "bus_1792745477320_bd4b",
    "equipmentId": "eq_1792745477320_6450",
    "equipmentVersion": 7,
    "name": "Bus A",
    "incomers": 1,
    "outgoers": 4,
    "incomingEquipment": [
      {
        "id": "eq_1792745477326_4dbf",
        "name": "TF-01",
        "categoryId": "transformer",
        "categoryName": "Transformer",
        "type": "single",
        "position": 0
      }
    ],
    "outgoingEquipment": [
      {
        "id": "eq_1792745477341_05b6",
        "name": "AHU-01",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 0
      },
      {
        "id": "eq_1792745477345_f1ab",
        "name": "AHU-02",
        "categoryId": "load",
        "categoryName": "Load",
        "type": "single",
        "position": 1
      }
    ],
    "spareIncomers": 0,
    "spareOutgoers": 2,
    "meters": [
      {
        "deviceId": "dev_1792745477373",
        "deviceName": "MFM-04",
        "unitId": 4,
        "gatewayName": null,
        "host": "127.0.0.1",
        "role": "outgoer",
        "equipmentId": "eq_1792745477341_05b6"
      }
    ],
    "points": 5,
    "pointsMetered": 1,
    "…": "incomingCategories, outgoingCategories, coupledNext, sortOrder"
  }
}
```

### Q2. Direct links (single → single)

```http
POST /equipment/eq_1792745477387_1dc5/connections
{"equipmentId": "eq_1792745477392_c5ab"}
```
→ **200**
```json
{
  "success": true,
  "owner": {
    "id": "eq_1792745477387_1dc5",
    "name": "GRID-01",
    "categoryId": "source",
    "type": "single",
    "version": 2,
    "attachedTo": [],
    "outgoingEquipment": [
      {
        "id": "eq_1792745477392_c5ab",
        "name": "TF-02",
        "categoryId": "transformer",
        "categoryName": "Transformer",
        "type": "single",
        "position": 0
      }
    ],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  },
  "attached": {
    "id": "eq_1792745477392_c5ab",
    "name": "TF-02",
    "categoryId": "transformer",
    "type": "single",
    "version": 2,
    "attachedTo": [
      {
        "busId": null,
        "busName": null,
        "equipmentId": "eq_1792745477387_1dc5",
        "equipmentName": "GRID-01",
        "role": "outgoer",
        "position": 0,
        "direct": true
      }
    ],
    "outgoingEquipment": [],
    "used": true,
    "…": "other keys as GET /equipment/{id}"
  }
}
```

A panel can't be the target of a direct link:

```http
POST /equipment/eq_1792745477387_1dc5/connections
{"equipmentId": "eq_1792745477320_6450"}
```
→ **400**
```json
{
  "detail": "USE_BUS: attach GRID-01 to a bus of PCC-01 as an incomer instead"
}
```

### A2. Refusals

```http
PUT /equipment/buses/bus_1792745477320_bd4b
{"outgoers": 1}
```
→ **409**
```json
{
  "detail": "CAPACITY_BELOW_ATTACHED: 2 outgoers connected; detach some first"
}
```

```http
DELETE /equipment/eq_1792745477392_c5ab
```
→ **409**
```json
{
  "detail": "EQUIPMENT_IN_USE: connected to GRID-01"
}
```

### F5. Field types and units

```http
GET /schemas/field_types
```
→ **200**
```json
{
  "items": [
    {
      "id": "float32",
      "label": "Float 32-bit",
      "encoding": "float32"
    },
    {
      "id": "float",
      "label": "Float (32-bit)",
      "encoding": "float32"
    },
    {
      "id": "float64",
      "label": "Float 64-bit",
      "encoding": "float64"
    },
    {
      "id": "real",
      "label": "REAL (32-bit float)",
      "encoding": "float32"
    },
    {
      "id": "boolean",
      "label": "Boolean",
      "encoding": "bool16"
    }
  ]
}
```
_Trimmed to five of the entries._

```http
GET /schemas/units
```
→ **200**
```json
{
  "items": [
    {
      "id": "V",
      "label": "V"
    },
    {
      "id": "kV",
      "label": "kV"
    },
    {
      "id": "A",
      "label": "A"
    },
    {
      "id": "kA",
      "label": "kA"
    },
    {
      "id": "W",
      "label": "W"
    },
    {
      "id": "kW",
      "label": "kW"
    }
  ]
}
```
_Trimmed: 33 entries on the test DB._

An older type word is accepted and stored in its listed form; a unit outside the list is refused:

```http
POST /schemas
{"name": "LT Panel", "description": "Main LT meters", "fields": [{"key": "voltage_ry", "type": "REAL", "unit": "V"}, {"key": "trip", "type": "boolean"}]}
```
→ **200**
```json
{
  "success": true,
  "message": "schema_created",
  "item": {
    "id": "sch_1792745477416",
    "name": "LT Panel",
    "description": "Main LT meters",
    "fields": [
      {
        "key": "voltage_ry",
        "type": "real",
        "unit": "V",
        "eval_order": null
      },
      {
        "key": "trip",
        "type": "boolean",
        "eval_order": null
      }
    ]
  }
}
```

```http
POST /schemas/sch_1792745477416/fields
{"key": "x", "type": "float32", "unit": "parsecs"}
```
→ **400**
```json
{
  "detail": "UNIT_INVALID:parsecs"
}
```

### F3 / F4. Schema GET, rename, description

```http
GET /schemas/sch_1792745477416
```
→ **200**
```json
{
  "item": {
    "id": "sch_1792745477416",
    "name": "LT Panel",
    "description": "Main LT meters",
    "fields": [
      {
        "key": "trip",
        "type": "boolean",
        "unit": null,
        "scale": null,
        "desc": null,
        "formula": null,
        "eval_order": null
      },
      {
        "key": "voltage_ry",
        "type": "real",
        "unit": "V",
        "scale": null,
        "desc": null,
        "formula": null,
        "eval_order": null
      }
    ]
  }
}
```

```http
PATCH /schemas/sch_1792745477416
{"name": "LT Panel v2", "description": "Renamed"}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "sch_1792745477416",
    "name": "LT Panel v2",
    "description": "Renamed",
    "fields": [
      {
        "key": "trip",
        "type": "boolean",
        "unit": null,
        "scale": null,
        "desc": null,
        "formula": null,
        "eval_order": null
      },
      {
        "key": "voltage_ry",
        "type": "real",
        "unit": "V",
        "scale": null,
        "desc": null,
        "formula": null,
        "eval_order": null
      }
    ]
  }
}
```

```http
PATCH /schemas/sch_1792745477423
{"name": "lt panel v2"}
```
→ **409**
```json
{
  "detail": "SCHEMA_EXISTS: lt panel v2"
}
```

### F8. Verification results

```http
POST /devices/dev_1792745477502/quick_test
```
→ **200**
```json
{
  "success": false,
  "latencyMs": 0,
  "error": "TCP_CONNECT_FAILED",
  "verification": {
    "ok": false,
    "latencyMs": null,
    "error": "TCP_CONNECT_FAILED",
    "at": "2026-10-23T08:51:17Z"
  }
}
```

```http
GET /devices
```
→ **200**
```json
{
  "items": [
    {
      "id": "dev_1792745477502",
      "name": "dev_ahu_04",
      "protocol": "modbus",
      "status": "degraded",
      "latencyMs": null,
      "lastError": "TCP_CONNECT_FAILED",
      "params": {
        "host": "127.0.0.1"
      },
      "autoReconnect": true,
      "manualDisconnect": false,
      "unitId": 1,
      "port": 41119,
      "gatewayId": null,
      "verification": {
        "ok": false,
        "latencyMs": null,
        "error": "TCP_CONNECT_FAILED",
        "at": "2026-10-23T08:51:17Z"
      }
    }
  ]
}
```

### F7. Device address edit

```http
PUT /devices/dev_1792745477502
{"params": {"host": "10.20.1.90"}, "unitId": 7}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "dev_1792745477502",
    "name": "dev_ahu_04",
    "protocol": "modbus",
    "status": "disconnected",
    "latencyMs": null,
    "lastError": null,
    "params": {
      "host": "10.20.1.90"
    },
    "autoReconnect": true,
    "manualDisconnect": false,
    "unitId": 7,
    "port": 41119,
    "gatewayId": null,
    "verification": null
  }
}
```

The address changed, so `status` is back to `disconnected` and `verification` is cleared.

### A5. Mapping fixes

```http
POST /mappings/tbl_1792745477532_1/import
{"mappings": [{"field_key": "v"}]}
```
→ **400**
```json
{
  "detail": "ROWS_REQUIRED: body must carry rows {fieldKey: {...}}"
}
```

```http
POST /mappings/tbl_1792745477532_1/import
{"rows": {"v": {"protocol": "modbus", "address": "10"}}}
```
→ **200**
```json
{
  "success": true,
  "message": "mapping_imported",
  "mode": "merge",
  "health": "Mapped"
}
```
_The response also carries `item` (the full mapping); it's left out here._

```http
DELETE /mappings/tbl_1792745477532_1/i
```
→ **200**
```json
{
  "success": true,
  "message": "row_deleted"
}
```
_The response also carries `item` (the remaining mapping); it's left out here. The row stays deleted after a reload._

```http
POST /tables/tbl_nope/migrate
```
→ **404**
```json
{
  "detail": "TABLE_NOT_FOUND"
}
```

### F1 / F10. Jobs

```http
GET /jobs2/job_1792745477589
```
→ **200**
```json
{
  "item": {
    "id": "job_1792745477589",
    "name": "Hourly",
    "type": "continuous",
    "tables": [
      "tbl_1792745477532_1"
    ],
    "columns": "all",
    "intervalMs": 1000,
    "enabled": false,
    "status": "stopped",
    "batching": {},
    "cpuBudget": "balanced",
    "metrics": {},
    "triggers": []
  }
}
```

```http
PATCH /jobs2/job_1792745477589
{"name": "Hourly LT", "intervalMs": 5000, "cpuBudget": "low"}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "job_1792745477589",
    "name": "Hourly LT",
    "type": "continuous",
    "tables": [
      "tbl_1792745477532_1"
    ],
    "columns": "all",
    "intervalMs": 5000,
    "enabled": false,
    "status": "stopped",
    "batching": {},
    "cpuBudget": "low",
    "metrics": {},
    "triggers": []
  }
}
```

While the job is running:

```http
PATCH /jobs2/job_1792745477589
{"intervalMs": 2000}
```
→ **409**
```json
{
  "detail": "JOB_RUNNING: stop or pause the job before editing it"
}
```

```http
POST /jobs2/job_1792745477589/resume
```
→ **409**
```json
{
  "detail": "JOB_NOT_PAUSED: status is running"
}
```

After `POST /jobs2/{id}/pause`:

```http
POST /jobs2/job_1792745477589/resume
```
→ **200**
```json
{
  "success": true,
  "message": "resumed"
}
```

---

## 11. Alerts on readings (shipped 2026-10-25)

This is not in the contract. It follows the backend's own conventions (§2): `{"items": …}` lists, `{"success", "item"}` writes, camelCase keys and `{"detail": "CODE: msg"}` errors.

### 11.1 The model
Alert rules work like **scales and units**: the schema holds the blueprint, every table of that schema inherits it, and a table can override it.

| Piece | What it is |
|---|---|
| **Level** | `Critical` (severity 3), `Mild` (2) and `Info` (1) exist from first boot. Users can add, rename, recolour or delete levels. A higher `severity` means worse; `color` is for badges |
| **Schema rule** | `fieldKey op threshold` for one level, for example `voltage > 250 → Critical`. A field can have one rule per level. `op` is one of `> >= < <= == !=`. Only numeric fields can have rules |
| **Table override** | For the same (field, level) on one table: a different op/threshold, or `enabled: false` to switch the inherited rule off. A table can also add its **own** rule, with no schema rule behind it, which needs op + threshold |
| **State** | One per table field: normal, or the **most severe** level whose rule matches the latest reading. Kept by the Rust engine |
| **Event** | One row per state change, for example normal → Mild, Mild → Critical, or Critical → normal |

**How the engine behaves (the screens should reflect this):**
- **Edits apply at the next job (re)start.** The engine loads the rules when a job starts. After saving a rule, tell the user to restart the job, or restart it for them.
- **Only changes are recorded.** A field that stays Critical produces no new events or notifications.
- **No deadband.** A reading that flaps across the threshold (249.9 → 250.1 → 249.9) produces one event per crossing.
- **Gaps are ignored.** A missing or non-numeric reading leaves the state as it was.

### 11.2 Endpoints
| Screen need | Call | Answer |
|---|---|---|
| Level list (pickers, badge colours) | `GET /alerts/levels` | `{items: [{id, name, severity, color, sortOrder}]}`, highest severity first |
| Add / edit / delete a level | `POST /alerts/levels {name, severity?, color?}`, `PUT /alerts/levels/{id} {name?, severity?, color?, sortOrder?}`, `DELETE /alerts/levels/{id}` | `{success, item}`. A delete is refused (409 `ALERT_LEVEL_IN_USE`) while rules or active states use the level |
| Schema screen: rules per field | `GET /schemas/{id}/alerts` | `{items: [rule]}`, where rule = `{id, fieldKey, alertId, alertName, severity, color, op, threshold, unit}` |
| Add / edit / delete a schema rule | `POST /schemas/{id}/alerts {fieldKey, alertId, op, threshold}`, `PUT /schemas/{id}/alerts/{ruleId} {op?, threshold?}`, `DELETE /schemas/{id}/alerts/{ruleId}` | `{success, item}`. `fieldKey` / `alertId` can't change: delete the rule and add a new one |
| Table screen: effective rules | `GET /tables/{id}/alerts` | `{tableId, items: [rule + {source, schemaRuleId, overrideId, enabled}]}` |
| Override, disable, or add a table-only rule | `PUT /tables/{id}/alerts {fieldKey, alertId, op?, threshold?, enabled?}` | `{success, tableId, items}`: the full effective list again, so the screen can re-render from the answer |
| "Reset to schema" | `DELETE /tables/{id}/alerts/{overrideId}` | `{success, tableId, items}` |
| Live badges | `GET /alerts/active?tableId=` (leave out `tableId` for all tables) | `{items: [{tableId, tableName, fieldKey, alertId, alertName, severity, color, value, since}]}` |
| History | `GET /alerts/events?tableId=&frm=&to=&limit=` | Newest first. `limit` defaults to 200 and is capped at 1000. `from` / `to` are `null` for normal |

`source` on the table list:
- `schema`: inherited as is.
- `overridden`: this table changed op/threshold.
- `table`: a table-only rule.
- `disabled`: switched off for this table.

An override that sets only `threshold` keeps the schema's `op`, and the other way round.

**Errors:**
- 400: `FIELD_REQUIRED`, `ALERT_LEVEL_REQUIRED`, `FIELD_UNKNOWN`, `FIELD_NOT_NUMERIC`, `OP_INVALID`, `THRESHOLD_INVALID`, `RULE_REQUIRED`, `FIELD_IMMUTABLE`, `NAME_REQUIRED`, `SEVERITY_INVALID`.
- 404: `ALERT_LEVEL_NOT_FOUND`, `ALERT_RULE_NOT_FOUND`, `OVERRIDE_NOT_FOUND`, `SCHEMA_NOT_FOUND`, `TABLE_NOT_FOUND`.
- 409: `ALERT_LEVEL_EXISTS`, `ALERT_RULE_EXISTS`, `ALERT_LEVEL_IN_USE`.

**Cleanup:**
- Deleting a table removes its overrides and state.
- Deleting a schema removes its rules.
- Deleting a schema field removes that field's rules, overrides and states.
- History is kept in all cases.

### 11.3 Live notifications
On every state change the engine posts a notification of `type: "alert"`. It arrives on the existing notification WebSocket and in `GET /auth/notifications/list`, the same as job notifications:
```json
{
  "type": "alert",
  "action": "create",
  "notification_id": "…",
  "message": "Alert Critical: al_t1.voltage = 262.4 (>= 255)",
  "user": "…",
  "read": false,
  "time": "…"
}
```
When a field returns to normal, the message reads `"Alert cleared: al_t1.voltage = 238.2 (back to normal)"`. The message is for display only. To update badges, re-fetch `/alerts/active` when an `alert` message arrives.

> **Backend note:** the engine posts this without a token, so it is delivered only while `LOGGER_AUTH_DISABLED=1`. A service token is needed before auth is switched back on (open item B7).

### 11.4 Example requests and responses
These were captured from the running code on 2026-10-25, using a schema with `voltage` (V) and `current` (A), and table `al_t1`.

**Levels**
```http
GET /alerts/levels
```
→ **200**
```json
{
  "items": [
    {"id": "critical", "name": "Critical", "severity": 3, "color": "#b42318", "sortOrder": 1},
    {"id": "mild", "name": "Mild", "severity": 2, "color": "#b54708", "sortOrder": 2},
    {"id": "info", "name": "Info", "severity": 1, "color": "#175cd3", "sortOrder": 3}
  ]
}
```

```http
POST /alerts/levels
{"name": "Warning", "severity": 2, "color": "#dc6803"}
```
→ **200**
```json
{
  "success": true,
  "item": {"id": "al_1792938452156_c1d6", "name": "Warning", "severity": 2, "color": "#dc6803", "sortOrder": 4}
}
```

```http
DELETE /alerts/levels/critical
```
→ **409**
```json
{"detail": "ALERT_LEVEL_IN_USE: 1 rule(s) or active state(s) use it"}
```

**Schema rules**
```http
POST /schemas/sch_1792938452141/alerts
{"fieldKey": "voltage", "alertId": "critical", "op": ">", "threshold": 250}
```
→ **200**
```json
{
  "success": true,
  "item": {
    "id": "sar_1792938452159_0b6b",
    "fieldKey": "voltage",
    "alertId": "critical",
    "alertName": "Critical",
    "severity": 3,
    "color": "#b42318",
    "op": ">",
    "threshold": 250.0,
    "unit": "V"
  }
}
```

Adding a second Critical rule on `voltage` → **409** `{"detail": "ALERT_RULE_EXISTS: voltage already has a rule for this level"}`.
An unknown field → **400** `{"detail": "FIELD_UNKNOWN: nope is not a field of this schema"}`.

```http
PUT /schemas/sch_1792938452141/alerts/sar_1792938452159_0b6b
{"op": ">=", "threshold": 255}
```
→ **200**, with the same `item` shape: `"op": ">="`, `"threshold": 255.0`.

```http
GET /schemas/sch_1792938452141/alerts
```
→ **200**
```json
{
  "items": [
    {"id": "sar_1792938452159_0b6b", "fieldKey": "voltage", "alertId": "critical", "alertName": "Critical", "severity": 3, "color": "#b42318", "op": ">=", "threshold": 255.0, "unit": "V"},
    {"id": "sar_1792938452162_e525", "fieldKey": "voltage", "alertId": "mild", "alertName": "Mild", "severity": 2, "color": "#b54708", "op": ">", "threshold": 240.0, "unit": "V"}
  ]
}
```

**Table: inherited rules**
```http
GET /tables/tbl_1792938452152_1/alerts
```
→ **200**
```json
{
  "tableId": "tbl_1792938452152_1",
  "items": [
    {"fieldKey": "voltage", "alertId": "critical", "alertName": "Critical", "severity": 3, "color": "#b42318", "op": ">=", "threshold": 255.0, "unit": "V",
     "source": "schema", "schemaRuleId": "sar_1792938452159_0b6b", "overrideId": null, "enabled": true},
    {"fieldKey": "voltage", "alertId": "mild", "alertName": "Mild", "severity": 2, "color": "#b54708", "op": ">", "threshold": 240.0, "unit": "V",
     "source": "schema", "schemaRuleId": "sar_1792938452162_e525", "overrideId": null, "enabled": true}
  ]
}
```

**Table: override, disable, table-only rule**

These three requests were sent in turn; the response below is the answer to the last one:
```http
PUT /tables/tbl_1792938452152_1/alerts
{"fieldKey": "voltage", "alertId": "critical", "threshold": 260}

PUT /tables/tbl_1792938452152_1/alerts
{"fieldKey": "voltage", "alertId": "mild", "enabled": false}

PUT /tables/tbl_1792938452152_1/alerts
{"fieldKey": "current", "alertId": "info", "op": "<", "threshold": 0.5}
```
→ **200**
```json
{
  "success": true,
  "tableId": "tbl_1792938452152_1",
  "items": [
    {"fieldKey": "current", "alertId": "info", "alertName": "Info", "severity": 1, "color": "#175cd3", "op": "<", "threshold": 0.5, "unit": "A",
     "source": "table", "schemaRuleId": null, "overrideId": "tar_1792938452181_776f", "enabled": true},
    {"fieldKey": "voltage", "alertId": "critical", "alertName": "Critical", "severity": 3, "color": "#b42318", "op": ">=", "threshold": 260.0, "unit": "V",
     "source": "overridden", "schemaRuleId": "sar_1792938452159_0b6b", "overrideId": "tar_1792938452175_c112", "enabled": true},
    {"fieldKey": "voltage", "alertId": "mild", "alertName": "Mild", "severity": 2, "color": "#b54708", "op": ">", "threshold": 240.0, "unit": "V",
     "source": "disabled", "schemaRuleId": "sar_1792938452162_e525", "overrideId": "tar_1792938452178_544d", "enabled": false}
  ]
}
```

A table-only rule without op/threshold:
```http
PUT /tables/tbl_1792938452152_1/alerts
{"fieldKey": "current", "alertId": "info"}
```
→ **400**
```json
{"detail": "RULE_REQUIRED: no schema rule to inherit: op and threshold are required"}
```

**Reset to schema**
```http
DELETE /tables/tbl_1792938452152_1/alerts/tar_1792938452175_c112
```
→ **200** `{success, tableId, items}`. The Critical rule is back to `"source": "schema"`, `"threshold": 255.0`, `"overrideId": null`.

**Live state**
```http
GET /alerts/active?tableId=tbl_1792938452152_1
```
→ **200**
```json
{
  "items": [
    {"tableId": "tbl_1792938452152_1", "tableName": "al_t1", "fieldKey": "voltage", "alertId": "critical", "alertName": "Critical",
     "severity": 3, "color": "#b42318", "value": 262.4, "since": "2026-10-25T09:12:03Z"}
  ]
}
```

**History**
```http
GET /alerts/events?tableId=tbl_1792938452152_1&limit=50
```
→ **200**
```json
{
  "items": [
    {"id": "ae_1792919523120_1", "tableId": "tbl_1792938452152_1", "tableName": "al_t1", "fieldKey": "voltage",
     "from": {"alertId": "mild", "alertName": "Mild"}, "to": {"alertId": "critical", "alertName": "Critical"},
     "value": 262.4, "op": ">=", "threshold": 255.0, "jobId": "job_1792900000000", "at": "2026-10-25T09:12:03Z"},
    {"id": "ae_1792919523120_0", "tableId": "tbl_1792938452152_1", "tableName": "al_t1", "fieldKey": "voltage",
     "from": null, "to": {"alertId": "mild", "alertName": "Mild"},
     "value": 244.1, "op": ">", "threshold": 240.0, "jobId": "job_1792900000000", "at": "2026-10-25T09:11:58Z"}
  ]
}
```
In a "back to normal" event, `to` is `null` and `op`/`threshold` are `null`.

---

## 12. Device bulk import (`POST /bulk_import/devices`), answered 2026-10-25

v2 can use the endpoint v1 uses. It is unchanged.

### 12.1 Same file as v1?
**Yes. The backend never receives the file.** v1's frontend reads the sheet and posts the rows as JSON. v2 should reuse v1's sheet parsing and send the same JSON, so any file v1 accepts works the same way. There is no file-upload (multipart) endpoint.

### 12.2 Request
```http
POST /bulk_import/devices
{
  "testConnections": false,
  "devices": [
    {"name": "mfm_001", "ip": "10.10.1.10", "port": 502, "protocol": "modbus", "unit": 1, "connections": "GIC-01"},
    {"name": "mfm_002", "ip": "10.10.1.10", "port": 502, "protocol": "modbus", "unit": 2, "connections": "GIC-01", "order": "CDAB"}
  ]
}
```

| Key (sheet column) | Required | Meaning |
|---|---|---|
| `name` | yes | Device name. It is the duplicate key (see 12.4) |
| `ip` | yes | Device / gateway host. Gateways are matched on this |
| `port` | no | Device port. OPC UA defaults to 4840 |
| `protocol` | no | Defaults to `modbus`. Must be a known protocol type (`GET /protocol_types`) |
| `unit` | no | Modbus / MQTT unit id. Defaults to 1 |
| `order` | no | Modbus byte order: `ABCD` (the default), `CDAB`, `BADC` or `DCBA` |
| `connections` | no | Name for a **new** gateway. Defaults to `Gateway-<ip>` |
| `mac` | no | Saved in `params.mac` |
| `mqtt_gateway` | no | MQTT logical gateway label (e.g. `GW-01`) |
| `testConnections` (top level) | no | `true` tests each device's connection before saving it. Off by default, because each unreachable host makes the request wait its full timeout |

Unknown keys are ignored. The endpoint needs `logger-write`.

### 12.3 Answer
The answer is always **200**, even when every row fails. Each row reports its own result, and nothing is rolled back: rows that succeed are saved even if others fail.

```json
{
  "success": true,
  "summary": {"total": 5, "created_gateways": 1, "created_devices": 2, "skipped": 1, "failed": 2},
  "results": [
    {"row": 0, "status": "created",
     "device": {"id": "dev_1792943465112", "name": "mfm_001", "protocol": "modbus", "status": "disconnected", "latencyMs": null, "lastError": null,
                "params": {"host": "10.10.1.10"}, "autoReconnect": true, "manualDisconnect": false, "unitId": 1, "port": 502,
                "gatewayId": "gw_1792943465110", "nominalVoltage": null},
     "gateway": {"id": "gw_1792943465110", "name": "GIC-01", "host": "10.10.1.10", "adapterId": null, "nic_hint": null, "ports": [502],
                 "protocol_hint": "modbus", "tags": [], "status": "unknown", "last_ping": null, "last_tcp": null},
     "gateway_created": true, "connected": null, "latencyMs": null, "connectionError": null,
     "message": "Device created with new gateway"},
    {"row": 1, "status": "created", "device": {"…": "…", "params": {"host": "10.10.1.10", "order": "CDAB"}, "unitId": 2},
     "gateway": {"id": "gw_1792943465110", "…": "…"}, "gateway_created": false, "message": "Device created"},
    {"row": 2, "status": "skipped", "device": {"id": "dev_1792943465112", "name": "mfm_001", "…": "…"}, "message": "Device already exists"},
    {"row": 3, "status": "failed", "error": "NAME_REQUIRED", "input": {"name": "", "ip": "10.10.1.11"}},
    {"row": 4, "status": "failed", "error": "PROTOCOL_INVALID: 'foo'", "input": {"name": "x_1", "ip": "10.10.1.12", "protocol": "foo"}}
  ]
}
```
- **`row`** is the index into `devices`, starting at 0, not the spreadsheet row number. Add the header offset when you show it.
- **`status`** is `created`, `skipped` or `failed`.
- **Row errors:** `NAME_REQUIRED`, `IP_REQUIRED`, `PROTOCOL_INVALID: '…'`, `GATEWAY_CREATE_FAILED: …`, `DEVICE_CREATE_FAILED: …`, `UNEXPECTED_ERROR: …`.
- **Whole-request error:** an empty or missing `devices` → **400** `{"detail": "DEVICES_ARRAY_REQUIRED"}`.
- **Key style:** this response uses some **snake_case** keys (`created_gateways`, `created_devices`, `gateway_created`, and the gateway's `nic_hint` / `last_ping`). It is kept as v1 has it.
- **When `testConnections` is true:** `connected`, `latencyMs` and `connectionError` are filled in, and the device is saved as `connected` or `degraded`.

### 12.4 Devices that already exist
**They are skipped, not updated or refused.**
- **The match is on `name`, ignoring case.** In the example, row 2 (`MFM_001`, another IP) was skipped as a duplicate of `mfm_001`. The existing device was **not** changed, and the row comes back with the existing `device`.
- **Duplicates inside the same sheet:** the first one is created and the later ones are skipped.
- **Re-importing the same file is safe:** every row comes back `skipped`, and nothing changes.
- **Gateways are reused by host (`ip`), never duplicated.** If the `connections` name is already taken by a gateway on another host, the new gateway is named `GIC-01 (10.10.1.99)`.
- **To change existing devices**, use `PUT /devices/{id}` (§10 F7), or delete them and import again.

---

## 13. Electrical: EMS / Source / BMS hierarchy and MFM slots (2026-10-26)

> **Superseded in part by §14 (2026-10-27).** The hierarchy (§13.1) now uses different names: `groupId` → `categoryId`, categories → types, and `/equipment/groups` is removed. The MFM slot rules (§13.2) stay valid.

All changes are additive: every existing key and route stays. Response examples were captured from the running code.

### 13.1 Hierarchy
Equipment now sits in a three-level tree: **group** (EMS, Source, BMS) → **category** (Transformer, HT Panel, LT Panel, Load…, each `single` or `distribution`) → **equipment**.
- **Groups:** the three groups are seeded and DB-managed, like categories, with no write endpoints.
- **Under EMS:** all of today's categories.
- **Source and BMS:** empty for now; their contents come later.

| Call | Answer |
|---|---|
| `GET /equipment/groups` | The navigation tree: `{items: [{id, name, sortOrder, categories: [category…]}]}` |
| `GET /equipment/categories` | Each category now also has `groupId` and `groupName` |
| `GET /equipment`, `GET /equipment/{id}` | Each item now also has `groupId` and `groupName` |
| `GET /equipment?groupId=ems` | A new filter, alongside `categoryId`, `type`, `q`, … |

```json
{"items": [
  {"id": "ems", "name": "EMS", "sortOrder": 1, "categories": [
    {"id": "transformer", "name": "Transformer", "type": "single", "groupId": "ems", "groupName": "EMS", "sortOrder": 2, "fields": ["…"], "defaultCapacity": {"incomers": 1, "outgoers": 1}},
    {"id": "lt_panel", "name": "LT Panel", "type": "distribution", "groupId": "ems", "groupName": "EMS", "sortOrder": 4, "fields": ["…"]}
  ]},
  {"id": "source", "name": "Source", "sortOrder": 2, "categories": []},
  {"id": "bms", "name": "BMS", "sortOrder": 3, "categories": []}
]}
```

### 13.2 Relations first, MFMs in slots
- **Relations first.** Equipment is attached to a bus as an incomer or outgoer (`POST /equipment/buses/{busId}/equipment`), as today.
- **MFMs go into the slot of a relation:**
  - an **incoming MFM always measures an attached incomer**, so `equipmentId` is required;
  - an outgoing MFM measures an attached outgoer;
  - **one MFM per relation.**
- **Spare** = an **outgoing MFM with no relation**. It takes an outgoing point.
- **Disconnecting a metered outgoer** leaves its MFM on the bus **as a spare**. Disconnecting a metered **incomer** is refused: remove the MFM first.
- **Capacity:** outgoing points in use = connected outgoers + spare MFMs. Attach, adding a spare and lowering capacity all count both.
- **Single equipment is unchanged:** MFMs go directly on the equipment (`POST /equipment/{id}/meters`).

| Call | What it does |
|---|---|
| `POST /equipment/buses/{busId}/meters {deviceId, role, equipmentId?}` | Puts an MFM in a relation's slot. With no `equipmentId` and `role: "outgoer"`, it adds a spare |
| `PUT /equipment/buses/{busId}/meters/{deviceId} {equipmentId \| null}` | **New.** Moves an MFM to another relation, or turns it into a spare (`null`, outgoing only). The role stays the same. Answers `{success, item: bus}` |
| `POST /equipment/buses/{busId}/equipment {…, spareDeviceId}` | **New field.** Connects an outgoer at a spare's point; that MFM then measures the new relation. This is how a full bus with spares takes a new feeder |

**Bus response, new keys:**
- each `incomingEquipment[]` / `outgoingEquipment[]` entry has `meter` (the MFM in that slot, or `null`);
- `spares` is the list of spare MFMs, and `spareMeters` is their count;
- `spareOutgoers` now counts **free** points: neither connected nor holding a spare.
```json
{"id": "bus_…", "name": "Bus A", "incomers": 1, "outgoers": 3,
 "incomingEquipment": [{"id": "eq_…tf", "name": "TF-1", "position": 0,
                        "meter": {"deviceId": "dev_…in", "deviceName": "MFM-IN", "role": "incomer", "equipmentId": "eq_…tf", "…": "…"}}],
 "outgoingEquipment": [{"id": "eq_…ahu", "name": "AHU-1", "position": 0,
                        "meter": {"deviceId": "dev_…ahu", "deviceName": "MFM-AHU", "role": "outgoer", "equipmentId": "eq_…ahu", "…": "…"}}],
 "spares": [{"deviceId": "dev_…sp", "deviceName": "MFM-SP", "role": "outgoer", "equipmentId": null, "…": "…"}],
 "spareMeters": 1, "spareIncomers": 0, "spareOutgoers": 1, "points": 4, "pointsMetered": 3, "meters": ["… all three, as before"]}
```

**Errors:**

| Case | Answer |
|---|---|
| Incoming MFM without `equipmentId` | 400 `EQUIPMENT_REQUIRED` |
| `equipmentId` not attached on that side | 400 `FEEDER_NOT_ON_BUS` |
| Relation already has an MFM | 409 `RELATION_METERED` |
| Spare with no free outgoing point | 409 `NO_FREE_POINT` |
| Attach when every point is connected or holds a spare | 409 `NO_SPARE` (use `spareDeviceId`, or raise `outgoers`) |
| `spareDeviceId` that isn't a spare MFM of this bus | 400 `NOT_A_SPARE` |
| Detach a metered incomer | 409 `RELATION_METERED` |
| Lower capacity below connections + spares | 409 `CAPACITY_BELOW_ATTACHED` |
| `PUT …/meters/{deviceId}` without `equipmentId` / unknown device | 400 `EQUIPMENT_REQUIRED` / 404 `METER_NOT_ATTACHED` |

**What changed for existing clients:**
- Incoming bus MFMs now need `equipmentId`.
- Outgoing MFMs without one are spares and take a point.
- No data had to change: no site had bus MFMs yet, and archbox has none.

---

## 14. Elements = category + kind + type (2026-10-27) — **breaking rename**

The names now follow the product's terms:

| Term | Meaning | Managed |
|---|---|---|
| **Category** | EMS, Source, BMS | In the DB, read-only API. Each category has `kinds`: EMS allows `single` and `distribution`; Source and BMS allow none until decided |
| **Kind** | `single` (MFMs directly on the element) or `distribution` (buses) | Chosen per element at create. It **can't be changed** later |
| **Type** | Load, HT Panel, LT Panel, Transformer, … | **User-defined**, in one global list, each with its own nameplate fields. Any type can be used with either kind |
| **Element** | category + kind + **optional** type | — |

The free-text `subtype` is **removed**.

### 14.1 What to change in the frontend (old → new)

| Before (§3 / §13) | Now |
|---|---|
| `GET /equipment/categories` listed Transformer, HT Panel, … | `GET /equipment/categories` lists **EMS / Source / BMS** `{id, name, sortOrder, kinds}`. The old list is now `GET /equipment/types` |
| `GET /equipment/groups` | **Removed.** Use `/equipment/categories` and `/equipment/types` |
| Element `categoryId` / `categoryName` = Transformer… | Element `typeId` / `typeName`, which may be `null` |
| Element `groupId` / `groupName` = EMS | Element `categoryId` / `categoryName` |
| Element `type` = single / distribution | Element `kind` |
| Element `subtype` | Removed |
| `POST /equipment {name, categoryId: "transformer"}` | `POST /equipment {name, categoryId: "ems", kind: "single", typeId: "transformer"}` |
| `PUT /equipment/{id} {categoryId}` changed the type | `{typeId}` (or `null`) changes the type; `{categoryId}` moves the element to another category; `{kind}` gives 400 `KIND_IMMUTABLE` |
| `GET /equipment?categoryId=…&type=…&groupId=…` | `GET /equipment?categoryId=ems&kind=single&typeId=load`. `q` searches the name and the type name |
| `incomingCategories` / `outgoingCategories` (bus and single element rules) | `incomingTypes` / `outgoingTypes` |
| Attached entries `{…, categoryId, categoryName, type}` | `{id, name, categoryId, kind, typeId, typeName, position, meter}` |
| `CATEGORY_NOT_ALLOWED`, `CATEGORY_NOT_ALLOWED_ON_BUS`, `ATTACHED_OUTSIDE_CATEGORIES`, `CATEGORY_TYPE_CHANGE` | `TYPE_NOT_ALLOWED`, `TYPE_NOT_ALLOWED_ON_BUS`, `ATTACHED_OUTSIDE_TYPES`, (none: the type can change freely) |

**New errors:**
- `KIND_INVALID`, `KIND_NOT_ALLOWED` (the category doesn't take that kind), `KIND_IMMUTABLE`;
- `TYPE_NOT_FOUND`, `TYPE_EXISTS`, `TYPE_IN_USE`, `FIELDS_INVALID`.

### 14.2 Types (user-defined)

| Call | Body / answer |
|---|---|
| `GET /equipment/types` | `{items: [{id, name, sortOrder, fields, defaultCapacity, used}]}`. `used` = the number of elements of this type |
| `POST /equipment/types` | `{name, fields?, defaultCapacity?, sortOrder?}` → `{success, item}`. The id is generated (`typ_…`). Names are unique, ignoring case (409 `TYPE_EXISTS`) |
| `PUT /equipment/types/{id}` | The same keys, all optional |
| `DELETE /equipment/types/{id}` | 409 `TYPE_IN_USE: N element(s), M bus rule(s)` while it's in use |

**Fields:** `[{id, label, kind: quantity|choice|text, units?, options?, required?, role?}]`.
- `id`s are unique within a type.
- A `choice` field needs `options`.
- `role` ∈ `voltage`, `voltage.in`, `voltage.out` drives the Voltage column.

If fields are removed from a type, elements keep their stored values, but readiness only checks the current fields. `defaultCapacity` `{incomers, outgoers}` sets the capacity of a **single** element's own node when it is created; the default is 1/1.

The built-in five types (source, transformer, ht_panel, lt_panel, load) are seeded once. A built-in type the user deletes doesn't come back.

```json
{"id": "transformer", "name": "Transformer", "sortOrder": 2,
 "fields": [{"id": "primary_voltage", "label": "Primary voltage", "kind": "quantity", "units": ["kV", "V"], "required": true, "role": "voltage.in"},
            {"id": "secondary_voltage", "label": "Secondary voltage", "kind": "quantity", "units": ["kV", "V"], "required": true, "role": "voltage.out"},
            {"id": "rated_capacity", "label": "Rated capacity", "kind": "quantity", "units": ["kVA", "MVA"], "required": true},
            {"id": "phase", "label": "Phase", "kind": "choice", "options": ["3 Phase", "1 Phase"], "required": true}],
 "defaultCapacity": {"incomers": 1, "outgoers": 1}, "used": 0}
```

### 14.3 Elements
```http
POST /equipment
{"name": "AHU-1", "categoryId": "ems", "kind": "single", "typeId": "load", "values": {"supply_voltage": {"value": 415, "unit": "V"}}}
```
An element with **no type** is allowed: it has no fields and is `ready`. Where a bus side restricts types, an element without a type is refused with `TYPE_NOT_ALLOWED`.

Element (live, archbox):
```json
{"id": "eq_1793007538155_4f89", "name": "TEST-p9scale-20261026093718-LD-00001",
 "categoryId": "ems", "categoryName": "EMS", "kind": "single", "typeId": "load", "typeName": "Load", "spare": false,
 "values": {"supply_voltage": {"value": 415.0, "unit": "V"}, "phase": {"value": "3 Phase", "unit": null}},
 "voltage": {"in": "415 V", "out": null, "text": "415 V"}, "readiness": {"ready": true, "missing": []},
 "maxIncomers": 1, "maxOutgoers": 0, "incomingTypes": [], "outgoingTypes": [], "version": 2, "…": "…"}
```
Attached entry on a bus:
```json
{"id": "eq_1793007538155_4f89", "name": "TEST-p9scale-…-LD-00001", "categoryId": "ems", "kind": "single",
 "typeId": "load", "typeName": "Load", "position": 0, "meter": null}
```

**Unchanged:**
- buses, positions, direct links, versions (If-Match);
- MFM slots and spares (§13.2);
- list speed (archbox: 3,000 elements in 0.17 s).

**Existing data was migrated in place.** On archbox: the 2,700 Load and 300 LT Panel elements kept their type, got `kind` from it (single / distribution) and `categoryId: "ems"`, and all 2,700 relations are intact.

### 14.4 Electrical Elements list (screen 1), 2026-10-27

`GET /equipment` serves the whole screen, one row per element:

| Column / control | Field / query |
|---|---|
| Name, icon | `name`, `kind` (single / distribution) |
| Subtitle | `typeName` (the type only) |
| Voltage | `voltage.text` (from the type's voltage fields) |
| Metering, distribution | `metering.pointsMetered` / `metering.points`, e.g. "20 / 20 MFMs". These are the MFMs on its buses' slots |
| Metering, single | `metering.meterCount`, e.g. "2 MFMs" ("—" when 0). Single elements have no MFM limit |
| Connection readiness | `readiness` (**changed meaning, breaking**): `{ready, incomers: {filled, total}, outgoers: {filled, total}}`. `ready` means **every incoming and outgoing slot has an element connected**. MFMs don't count. "Incomplete" can show e.g. "1 / 2 incomers" |
| Nameplate completeness | `nameplate: {complete, missing: [labels]}`. These are the required fields of the type; this was `readiness` before |
| Map: Used / Not used | `used` |
| Type chips | `?typeId=` |
| Metering / Readiness / In Map filters | `?metered=true\|false`, `?ready=true\|false`, `?used=true\|false` |
| Search | `?q=` (name or type name) |

**How the slots are counted:**
- **Distribution:** summed over its buses. Each bus has `incomers` / `outgoers` limits (`PUT /equipment/buses/{busId}`), and the filled count is the number of attached elements.
- **Single:** its own limits `maxIncomers` / `maxOutgoers` (`PUT /equipment/{id}`; the defaults come from the type's `defaultCapacity`).
  - Incoming = what feeds it: a bus it is an outgoer of, or a direct link.
  - Outgoing = what it feeds: buses it is an incomer of, plus its direct links.
- An element with **0 / 0** slots counts as ready.

```json
"readiness": {"ready": false, "incomers": {"filled": 0, "total": 1}, "outgoers": {"filled": 1, "total": 1}},
"nameplate": {"complete": false, "missing": ["Secondary voltage", "Rated capacity"]}
```

---

## 15. EMS elements from a spreadsheet (2026-10-27)

There is one import endpoint per category. This one always creates elements in **EMS**, so the sheet has no category column.

| Call | What it does |
|---|---|
| `GET /equipment/import/ems/template` | Downloads `ems_elements_template.xlsx`. It has the Elements, Buses and Connections sheets with their headers (one column per nameplate field of any type), plus a **Types** reference sheet listing each type's fields, units or options, and which are required |
| `POST /equipment/import/ems` (multipart, field `file`, `.xlsx` or `.csv`, max 5 MB) | Imports the file. `?dryRun=true` checks everything and saves nothing |

### 15.1 Workbook
Header names are matched ignoring case, and `_` and spaces are interchangeable. Columns marked * are required. A `.csv` is read as the **Elements** sheet only.

| Sheet | Columns |
|---|---|
| **Elements** | `name`*, `kind` (`single` / `distribution`; required for a new element), `type` (name or id), `max incomers`, `max outgoers` (single elements only), `spare` (yes/no), `description`, plus **one column per nameplate field** of the row's type, by label or id (e.g. `Primary voltage` = `33 kV`; a bare number gets the field's first unit) |
| **Buses** | `panel`*, `bus`*, `incomers`, `outgoers`, `incoming types`, `outgoing types` (comma-separated type names) |
| **Connections** | `panel`*, `bus` (required for a distribution panel; leave it blank for a direct link from a single element), `role` (`incomer` / `outgoer`), `element`*, `position` (1 = first) |

**Rules:**
- Sheets run in order: Elements → Buses → Connections, so later sheets can use elements created earlier in the same file.
- **Existing names are updated:**
  - blank cells leave stored values alone;
  - nothing is ever deleted;
  - a different `kind` on an existing element gives `KIND_IMMUTABLE`.
- A **new** panel's automatic "Bus A" takes the name of its first row in the Buses sheet, rather than staying as an extra bus.
- The import uses the **same rules as the API**: allowed types, capacity (`NO_SPARE`), loops (`CYCLE`), name clashes, etc.
- **All or nothing.** If any row fails, nothing is saved.

### 15.2 Answer
```json
{"success": true, "dryRun": false, "saved": true,
 "summary": {"elements": {"created": 4, "updated": 0, "unchanged": 0},
             "buses": {"created": 2, "updated": 0, "unchanged": 0},
             "connections": {"created": 3, "updated": 0, "unchanged": 0}, "errors": 0},
 "results": [{"sheet": "Elements", "row": 2, "key": "GRID-01", "status": "created"}, "…"]}
```
- **`row`** is the spreadsheet row number (the header is row 1). `status` is `created`, `updated`, `unchanged` or `failed`; a failed row also has an `error`.
- **Dry run:** always 200, with `saved: false`.
- **Real import with errors:** **400**, with the full report plus `"detail": "IMPORT_INVALID: N row(s) have errors; nothing was saved"`.

**Row errors** (same codes as the API, plus):
- `NAME_REQUIRED`, `KIND_REQUIRED`, `DUPLICATE_IN_SHEET`, `FIELD_UNKNOWN: column '…'`, `FIELD_INVALID`;
- `ELEMENT_NOT_FOUND`, `BUS_NOT_FOUND`, `BUS_REQUIRED`, `NOT_A_PANEL`, `LIMITS_ON_DISTRIBUTION` (put a panel's limits in the Buses sheet), `ROLE_INVALID`, `POSITION_INVALID`.

**File errors** (whole request):
- 400 `FILE_TYPE`, `FILE_INVALID`, `SHEETS_MISSING`, `TOO_MANY_ROWS` (20,000 per sheet);
- 413 `FILE_TOO_LARGE`.

The import needs `logger-write`. The template only needs read.

### 15.3 Additions (2026-10-27): zones and panel-level allowed types
New **Elements** columns:
- **`zone`** (zone name or id; it must exist, otherwise `ZONE_NOT_FOUND`).
- **`incoming types` / `outgoing types`** (comma-separated type names):
  - **on a panel**, they apply to **every bus**, including buses the Buses sheet adds later in the same file; a Buses row's own list wins;
  - **on a single element**, they set its own node's allowed types.

The template now carries these columns as well.

---

## 16. Zones and export in the plant-template layout (2026-10-27)

### 16.1 Zones
A zone is an element property backed by a user-managed list (North, South, Production Block A, …).

| Call | Body / answer |
|---|---|
| `GET /equipment/zones` | `{items: [{id, name, sortOrder, used}]}` |
| `POST /equipment/zones` | `{name, sortOrder?}` → `{success, item}`. The id is generated (`zone_…`); 409 `ZONE_EXISTS` (names compared ignoring case) |
| `PUT /equipment/zones/{id}` | `{name?, sortOrder?}` |
| `DELETE /equipment/zones/{id}` | 409 `ZONE_IN_USE: N element(s)` |

**Elements:**
- `zoneId` on `POST` / `PUT /equipment` (`null` clears it; an unknown id gives 404 `ZONE_NOT_FOUND`);
- the output carries `zoneId` and `zoneName`;
- `GET /equipment?zoneId=` filters by zone.

**Element ID:** this is the generated `id` (`eq_…`), and `name` is the name the user keeps.

### 16.2 Export: `GET /equipment/export/ems?typeId=`
This downloads `ems_elements_YYYYMMDD.xlsx` in the **plant template's layout** (like "Logger - PCC Panels template.xlsx"):
- **One sheet per type** (plus "Untyped").
  - Row 1 is the group row: **REQUIRED** | **NAMEPLATE / OPTIONAL**.
  - Row 2 holds the headers: `Element ID *`, `Name *`, `Zone`, the type's required fields (`*`, with the unit in the header when the field has exactly one unit), `Number of Bus Sections` (panels) or `Max Incomers` / `Max Outgoers` (single), `Allowed Incoming Types`, `Allowed Outgoing Types`, then the optional fields, `Spare` and `Description`.
  - A panel's allowed types are the union over its buses.
- **Bus Sections:** `Element ID *`, `Element Name`, `Bus ID *`, `Bus Section *`, `Maximum Incomers *`, `Outgoing Feeder Capacity *`, plus each bus's allowed types.
- **Lists:** zones, element types and kinds.

`?typeId=` limits the file to one type. This is the file for the screen's **Export** button. The **import** keeps our own format (§15). On archbox, exporting 3,000 elements takes 0.33 s.

---

## 17. MFMs are logger tables (2026-10-27) — **breaking**

As in v1, an MFM **is a logger table**: the table its readings are written to. The table's **device** (the physical meter) and its **schema** (the field layout) come from the table, so neither is stored a second time. Everything in §13.2 still applies (relation slots, spares, one MFM per relation), with the **table** in the slot.

### 17.1 What changed (old → new)
| Before | Now |
|---|---|
| `POST /equipment/{id}/meters {deviceId}` | `{tableId}` |
| `DELETE /equipment/{id}/meters/{deviceId}` | `DELETE /equipment/{id}/meters/{tableId}` |
| `POST /equipment/buses/{busId}/meters {deviceId, role, equipmentId?}` | `{tableId, role, equipmentId?}` |
| `PUT` / `DELETE /equipment/buses/{busId}/meters/{deviceId}` | `…/meters/{tableId}` |
| `POST /equipment/buses/{busId}/equipment {…, spareDeviceId}` | `{…, spareTableId}` |
| `GET /equipment/available_meters`: devices not attached | **Logger tables** not attached |
| Error `DEVICE_REQUIRED` / `DEVICE_NOT_FOUND` | `TABLE_REQUIRED` / `TABLE_NOT_FOUND` |
| One **device**, one place | One **table**, one place. Two tables of the same device can sit in two places |

**Every MFM in a response** (`metering.meters`, bus `meters`, `spares`, relation `meter`, `available_meters`):
```json
{"tableId": "tbl_…", "tableName": "pcc_in", "schemaId": "sch_…", "schemaName": "MFM 3ph",
 "deviceId": "dev_…", "deviceName": "dev_pcc_in", "protocol": "modbus", "status": "connected",
 "unitId": 1, "gatewayId": "gw_…", "gatewayName": "GIC-01", "host": "10.10.1.10", "port": 502,
 "role": "incomer", "equipmentId": "eq_…"}
```
`deviceId` / `deviceName` are `null` when the table isn't bound to a device.

**Guards:**
- Deleting a logger table that is an MFM → 409 `TABLE_ATTACHED_TO_EQUIPMENT: <element> <bus>`. This is checked **before** the table's storage is touched.
- Deleting a device while one of its tables is an MFM → 409 `DEVICE_ATTACHED_TO_EQUIPMENT: table <name> on <element> <bus>`.

### 17.2 Meters sheet (EMS import, §15)
The 4th sheet runs after Elements, Buses and Connections: **relations first, then MFMs**.

| Column | Meaning |
|---|---|
| `table`* | The logger table that is the MFM. A column headed **`MFM`** is read as the same thing, as in v1 |
| `element`* | A single element (the MFM sits on it) or a distribution panel |
| `bus` | Required for a panel |
| `role` | `incoming` / `outgoing` / `spare`; v1's `Incomings` / `Outgoings` / `Spare` also work. Leave it blank for a single element |
| `measures` | The attached element it measures. **Required for incoming**; blank on outgoing = a spare |
| `schema` | Optional check: it must be the table's schema (name or id), otherwise `SCHEMA_MISMATCH` |

**Re-running a sheet:**
- same place → `unchanged`;
- same bus but another element → the MFM moves there (`updated`);
- placed somewhere else → `METER_IN_USE` (never moved silently);
- a different role in place → `ROLE_CHANGE`.

**New codes:** `TABLE_REQUIRED`, `TABLE_NOT_FOUND`, `SCHEMA_MISMATCH`, `SPARE_MEASURES`, `ROLE_CHANGE`.

**Template and export:**
- The template has a Meters sheet (`table, element, bus, role, measures, schema`).
- The export has a **Meters** sheet: `Table (MFM)`, `Element`, `Bus`, `Role`, `Measures`, `Schema`, `Device`.

Existing data: archbox had no MFMs placed. The one-time migration keeps any old device slot whose device has exactly one table, and logs the rest.
