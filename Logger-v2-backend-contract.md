# Logger v2 — API contract for the backend developer

## What changed since the previous version (2026-10-21)

Only these items changed; everything else is as before. All are in proposed requests (BR = backend request, see §4: BR-26, BR-30, BR-31), so nothing that v1 uses is affected.

1. **Voltage tolerance (catalog, BR-26).** New optional `voltage_tolerance_pct` on `GET /element-types/` (a number, default 8). Two nominal voltages within this percentage of each other count as a match (400/415/433 V, 11/11.5 kV); the screen allows the connection and shows a "nominal voltages differ" note. §3.6.
2. **Phase table (catalog, BR-26).** `phase_compat` is now a **list of rows** `{ "source", "target", "voltage_ratios": [numbers] }`. A row says a `source` phase may feed a `target` phase when the target's nominal voltage is the source's times one of the ratios, or equals it (ratio 1 is always allowed, so list only the extra ratios; a row with `[1]` only grants the phase pairing). A match at a ratio other than 1 carries no note. A near match at ratio 1 carries the "nominal voltages differ" note. A ratio of 0 or below is ignored, and a row left with no ratio is ignored. A ratio that is not a JSON number (a string, null) is a contract error for the whole catalog, like the old object form. Example: `3 Phase` feeds `1 Phase` at ratios `[1, 0.5773502691896258]` (so a 240 V single-phase load sits on a 415 V supply). An empty list (or none) means equal phases only. **The old object form `{ "3 Phase": ["1 Phase"] }` is no longer accepted.** §3.6.
3. **Field start value (catalog, BR-26).** Fields may carry an optional `initial` (text), the value a new element starts with, e.g. frequency `"50 Hz"`. §3.6.
4. **Editable connection counts (catalog data, BR-26).** No new keys: the catalog now lists the `maxIn`/`maxOut` limits of transformers and the UPS, and the `maxIn` limit of the other loads (APFC, AHF and the rest have no outgoing port), as `visible: true` with `permitted` bounds 1–99 and default `"1"`. A source's `maxOut` of `"0"` or blank means no limit. §3.6.
5. **Spare elements (BR-26).** Elements gain an optional boolean `spare` ("Spare / not on map"; absent = false). It is optional on writes too: absent on POST = false, absent on PUT = keep the stored value. The frontend always sends it on create and update. Store and return it. §3.6.
6. **Bus couplers between neighbours only (BR-26).** `couplings` keeps its shape (a list of `[low, high]` section pairs), but only neighbouring sections are valid: `[0,1]`, `[1,2]`, `[2,3]`, inside the element's `sections`. Please answer 400 for any other pair. The frontend never sends one, and drops any it reads. §3.6.
7. **Meter kind on attachments (topology, BR-30).** Each `meter_attachments` row gains `kind` (`"mfm"` | `"pqm"`, or another word kept as-is). A point holds **at most one meter of each kind** (one MFM plus one PQM), and a device still sits on at most one point. Enforce uniqueness per **(point, kind)** and answer 400 when a body breaks it. Please always return `kind` on GET and accept it on PUT. On a PUT, a row without `kind` (or with a blank one) is a row the frontend could not classify: accept it, store it unchanged, and count it for the one-point-per-device rule only, never for the (point, `kind`) rule. On a GET, a row without `kind` is resolved by the frontend from the device's own `kind` (`GET /devices/`); if the device has none, the row is kept and written back without `kind`. §3.7.
8. **Verification resets (BR-31).** Clear a device's `verification` and `verified_at` when its `unit_id`, `kind`, `serial_protocol`, `gateway`, host or port changes, and for every meter of a gateway whose host or port changes. §3.1, §3.8.
9. **Rule switches per plant (catalog, BR-26).** New optional `rule_settings` on `GET /element-types/`: a map from a rule id to `"block"` (today's behaviour, the default), `"warn"` (allowed, with a note) or `"off"` (not checked). Example: `{ "frequency": "off", "phase": "warn" }`. Only some rules can be switched; the others always block. An unknown rule id or mode is ignored. Absent = every rule blocks, as today. §3.6.

Audience: the person running the Django backend on port 5175. Scope: every request the v2 frontend makes, the exact response shape it accepts, and what we need added (backend requests, "BR-nn").
Companion file: `openapi-v2.yaml` (OpenAPI 3.1, same content, machine-readable). Source of truth in the frontend: `src/data/endpoints.ts` (paths), `src/data/*/wire.ts` (response schemas), `src/platform/flags/ledger/*.ts` (BRs).

Provenance tags used throughout:

| Tag | Meaning |
|---|---|
| proven | v1's production UI already calls it. Must not change. |
| inferred | Another method on a route v1 already uses (same DRF route). |
| unproven | Exists in the repo backend or v1 client code, but v1 production never calls it. The v2 UI keeps it behind a flag (off against a real backend) until you confirm it works (BR-28). |
| proposed | Does not exist. A backend request (BR) tagged with its id. |

## Start here: what to build, in order

1. **Change nothing that is proven.** Every endpoint tagged proven (section 3) is live for v1 clients; extend only with new optional fields or new endpoints (section 2).
2. **Make your dev instance reachable (section 1).** Bind to `0.0.0.0:5175`, put the Tailscale IP in `ALLOWED_HOSTS`, note that routes sit under the `/core` prefix, relax auth for dev as described in section 1, and tell us which Keycloak issuer your tokens carry. Then send the items in section 6.
3. **Build the requests in this order.** Each one switches on a frontend flag (the flags stay off against a real backend until the request ships and is added to `config.json`, section 4):

| Order | Request | Frontend flag it turns on |
|---|---|---|
| 1 | **BR-28**: confirm the existing device CRUD/connect/disconnect, the `/gateways/` routes and the other unproven endpoints (3.1, 3.8), and make `GET /devices/` return `modbus_config`/`opcua_config`/`last_error` (3.1; without them Comms shows no meters and no gateway grouping) | `comms.deviceEdit`, `comms.gateways`, and `tables.rowDelete`, `tables.rebind`, `tables.migrate`, `tables.mappingTransfer`, `jobs.pause`, `jobs.liveMetrics`, `jobs.runHistory` |
| 2 | **BR-26**: element type catalog and elements (3.6) | `elements.electrical` (the Electrical tab) |
| 3 | **BR-29**: topology document (3.7), then **BR-30**: meter attachments and `Device.kind` | `screens.mappings`, then `mappings.meterAttachments` |
| 4 | **BR-31**: logger servers, gateway and device foreign keys, saved verification (3.1, 3.8) | `comms.hierarchy` |
| 5 | **BR-32**: nameplate upload/extract and Excel import/export of elements (3.6) | `elements.nameplate`, `elements.excel` |
| 6 | The rest, by screen. Schemas: BR-02 to BR-06. Tables: BR-07 to BR-11. Jobs: BR-12 to BR-18, BR-23. Assistant and shell: BR-21, BR-24, BR-25. Platform: BR-01, BR-19, BR-20, BR-22, BR-27, S1 | `schemas.*`, `tables.*`, `jobs.*`, `shell.roleAwareUi`, `assistant.screenContext` (BR-19, BR-20, BR-22, BR-25, BR-27 and S1 turn nothing on) |

Everything after row 1 is optional per request: the screen it unlocks simply stays hidden until it ships.

---

## 1. Connection and setup

**Base URL and prefix.** The frontend calls `{baseUrl}{path}`. In dev, `baseUrl` is `/api` (same origin as the Vite dev server at http://127.0.0.1:3170). We run the Vite dev server on our machine, with a proxy that forwards `/api` and `/ws` to yours (you do not run this; it shows what reaches you):

```
# LOGGER_DEV_API_PREFIX: '/core' for the repo backend; '' if you mount at the root; unset = no rewrite
# npm run dev:5175 serves config/dev-5175.config.json as /config.json
LOGGER_DEV_API=http://<your-tailscale-ip>:5175 LOGGER_DEV_API_PREFIX=/core npm run dev:5175
```

- The proxy rewrites `/api/...` to `{LOGGER_DEV_API_PREFIX}/...`. The repo backend mounts every route under `/core/` (`logger/urls.py`), so use `/core`. If your instance mounts its routes at `/api` (as v1 production does: `https://192.168.1.20:8443/api`), leave the variable unset (no rewrite).
- The WebSocket proxy (`/ws`) is **not** rewritten. The socket path must be exactly `/ws/ai/sessions/{id}/` on your server.
- Runtime config (`/config.json`, no rebuild needed): `api.baseUrl`, `api.timeoutMs` (15000), `ws.baseUrl` (null = same origin), `auth` (`mode: "keycloak"` with `url`, `realm`, `clientId`, `writeRole`; or the dev-only `mode: "none"` with a fixed `user` {name, email, roles} and `writeRole`), `plant.{name,code}` (which plant the deployment serves), `plantTimeZone` (Asia/Kolkata), `polling.{jobsMs:10000, metricsMs:5000, aiFallbackMs:5000}`.
- **Auth in `dev:5175` today.** Keycloak sign-in exists (`auth.mode: "keycloak"`, `src/platform/auth/keycloakAuth.ts`). It mirrors v1: public client `neuract-logger`, Authorization Code + PKCE S256, `login-required`, the token refreshed with `updateToken(60)` before each request and every 30 s, tokens kept in memory only. Until you confirm which Keycloak and issuer your dev instance accepts (section 6, item 3), `config/dev-5175.config.json` stays on the dev-only `auth.mode: "none"`. With `dataMode: "api"` the frontend then sends **no `Authorization` header** (and no `?token=` on the AI socket). Run your dev instance with authentication relaxed for these requests. A `DEFAULT_PERMISSION_CLASSES` change is not enough: every viewset sets `permission_classes = [IsNeuractAdminForUnsafeMethods]`, which refuses a request without token claims (403 "Authentication credentials were not provided.", which the frontend reads as an expired session). Instead, behind a dev-only setting (for example `DEV_ANONYMOUS_AUTH = True`), add a second authentication class after `KeycloakJWTAuthentication` in `DEFAULT_AUTHENTICATION_CLASSES`. When the request has no `Authorization` header, it returns `(None, {"preferred_username": "dev", "resource_access": {"neuract-logger": {"roles": ["neuract-admin"]}}})`, so the permission class passes and reads and writes work. Never enable it outside dev. We switch dev-5175 to `auth.mode: "keycloak"` once you confirm. Production builds refuse `auth.mode: "none"`.

**Tailscale.** Start Django bound to all interfaces: `python manage.py runserver 0.0.0.0:5175` (or the ASGI server equivalent). Add your Tailscale IP / MagicDNS name to `ALLOWED_HOSTS` (currently `[]`, which only accepts localhost and gives 400 DisallowedHost for anything else; the proxy uses `changeOrigin`, so the Host header is your IP:5175). Send us the Tailscale IP.

**CORS.** Not needed in dev: the browser only talks to the Vite origin and the proxy forwards server-side. CORS and the Keycloak web origins for the real v2 origin are BR-27 (deploy-time only).

**Auth.** Every request carries `Authorization: Bearer <Keycloak access token>` (the frontend obtains it from Keycloak directly; it does not call `/login/`). The repo verifies RS256 against the realm JWKS and requires the issuer to equal `http://localhost:8080/realms/logger` exactly, so a token issued via another host name fails. Production (v1) tokens are issued by realm `master` on `http://192.168.1.20:8082` (from our reference `config/prod.config.json`), so their `iss` is `http://192.168.1.20:8082/realms/master`. The repo's `core_logger/auth.py` builds both the issuer and the JWKS URL from `KEYCLOAK_BASE_URL = "http://localhost:8080"` and `KEYCLOAK_REALM = "logger"` (`logger/settings.py`), so it rejects those tokens. Make the issuer and JWKS URL configurable (or accept the production one), and tell us which issuer your dev tokens carry. Until then dev auth stays relaxed (`auth.mode: "none"`, above). GET needs any valid token; POST/PUT/PATCH/DELETE need the client role `neuract-admin` in `resource_access["neuract-logger"].roles`.
- 401 vs 403: DRF currently returns **403** for a missing token, an invalid/expired token, and a missing role. The frontend copes: a 403 whose `detail` matches `invalid token | authentication credentials | expired` is treated as "session expired" (one forced token refresh and retry), any other 403 is "forbidden" (no permission). A real 401 is treated as session expired. BR-19 asks for a proper 401.
- We never call `/register/`, `/login/` or the role-grant endpoint (see S1 in section 4).

**Trailing slashes.** Every path keeps DRF's trailing slash. The frontend always sends it. Do not add redirects (a POST redirected to the slashless form breaks).

**JSON.** Requests with a JSON body send `Content-Type: application/json`. The BR-32 uploads (`/elements/{id}/nameplate/`, `/elements/import/`) send `multipart/form-data` with one part `file` (the browser sets the boundary). Every request sends `Accept: application/json`, except `GET /elements/export/`, which sends `Accept: */*` and expects the .xlsx bytes. Responses must otherwise be JSON (an HTML 500 page is tolerated only for classification, see section 5). DELETE success may be an empty 204.

**IDs.** UUID strings (the frontend also accepts integers and stringifies them). Treat ids in paths as opaque. Exception: topology connection ids are minted by the client (section 3.7).

**Timestamps.** ISO 8601, prefer UTC with `Z` (DRF default for model fields). A timestamp without offset (the job executor's live metrics today) is read as UTC. A present but unparseable string fails the whole response ("contract error"), so never send `""` for a time; send `null` or omit it.

**Nulls.** Where this document or the yaml marks a field nullable (`…|null`, `type: [x, 'null']`), `null` and "absent" are the same. Elsewhere, omit the key instead of sending `null`: a `null` there fails the whole response (contract error). Examples: schema field `kind`, table `created_at`/`updated_at`, mapping `validated`, job `enabled`, job command `job_id`, the catalog keys that have defaults (`pickable`, `creatable`, `bridge`, `fields`, `one_of`, `limits`, `metering`, `summary`, `capacity`, `defaults`, `permitted`, family `order`/`columns`), element `values`/`sections`/`couplings`, topology `placed`/`connections`, the import report's `updated`/`errors`, `bulk/`'s `errors`/`total_processed`, migrate's `table_id`/`table_name`/`status`. Blank strings (`""`) for free text are treated as "none".

---

## 2. The additive-only rule

v2 uses the same endpoints as v1 and v1 clients are live against the same backend. Therefore:

1. Existing response fields are **never renamed, retyped or removed**; existing enum words keep meaning what they mean.
2. New needs arrive as **new optional fields** on existing responses/requests, or **new endpoints**, each tagged with its BR id (below and in section 4).
3. The v2 frontend ignores unknown extra response fields, so adding fields is always safe for us. Vocabulary words are **open**: an unknown schema `field_type`, mapping `data_type`, `protocol` or `byte_order`, or device `protocol` is shown as-is, treated as unknown by the UI's rules (no scale rule, no address format check) and **written back unchanged** on the next save, never coerced to a known word. One odd word therefore never hides a whole schema, table or device list. An unknown schema field `kind` is not kept: it reads as `raw` (or `derived` when a `formula` is present) and is written back as that word. Job `status` / `job_type` and table `status` / `mapping_health` are tolerant too: an unknown word renders as "unknown". A blank job/table status or `job_type` also renders as "unknown", and a blank catalog or topology word reads as absent (§3.6, §3.7). A blank schema `field_type`, mapping `protocol`/`data_type` or device `protocol`, a wrong JSON type, or a missing required key is still a contract error.
4. Every new request field is optional with a default that reproduces today's behaviour when omitted.

---

## 3. Endpoints by resource

Paths are relative to the base URL. `{id}` is a UUID. "Screen action" names where the UI uses it.

### 3.1 Devices (v1 Connected Devices; Elements › Comms)

#### GET `/devices/` — proven
Screen action: Elements › Comms (the device list and the comms tree); also the device picker when creating a table.
Response: array.

```json
[{
  "id": "5f0c...", "name": "PLC-1", "protocol": "modbus", "status": "connected",
  "latency_ms": 12, "last_error": null, "auto_reconnect": true,
  "modbus_config": { "host": "10.0.0.5", "port": 502, "unit_id": 1, "timeout_ms": 3000, "retries": 3 },
  "opcua_config": null,
  "kind": "mfm", "gateway": "<gateway id>", "serial_protocol": "rtu", "verification": "verified", "verified_at": "…Z"
}]
```
- Required: `id`, `name`, `protocol` (known: `modbus` | `opcua`; another non-blank word is shown as-is), `status` (any string; repo uses `disconnected|connected|error`).
- Optional/nullable: `latency_ms`, `last_error`, `auto_reconnect`, `modbus_config` (`host`, `port` required inside; `unit_id`, `timeout_ms`, `retries` optional), `opcua_config` (`endpoint` required, other keys allowed).
- BR optional (absent today): `kind` (BR-30: `mfm`, `pqm`, …, open), `gateway` (BR-31: gateway id, or null = no gateway: a direct device even when a gateway serves its host and port; when the key is **absent** the device joins the gateway serving its host and port; an id the gateway list lacks falls back to host and port too), `serial_protocol` (BR-31: `rtu|ascii`, open), `verification` (BR-31: `verified|failed|unverified`), `verified_at` (BR-31). Because this endpoint is proven, a malformed BR key is read as absent; it never fails the list.
- Note: the repo `DeviceListSerializer` returns only `id,name,protocol,status,latency_ms,auto_reconnect`. That is accepted, but host/port (and so gateway membership by host and port) need the configs in the list. v1's list mapper reads `modbus_config`/`opcua_config` from this list, so production presumably returns them. Please confirm (BR-28) and make your dev list include `modbus_config` (with `unit_id`), `opcua_config` and `last_error`. Without them Elements › Comms shows every device as direct (no gateway grouping, no meters): v2 never GETs a single device.

#### POST `/devices/{id}/quick_test/` — proven
Screen action: "Test connection" on a direct device; "Verify" on a meter. No body. Does not save status. With BR-31 (`comms.hierarchy` on) "Verify" on a meter sends `?save=1` (a direct device's "Test connection" never does), asking the server to persist `verification` (`verified`/`failed` from `ok`) and `verified_at`, which GET `/devices/` then returns; without the flag the request is exactly v1's. With BR-31 the server also **clears** `verification` and `verified_at` (back to `unverified`, null) when the device's `unit_id`, `kind`, `serial_protocol`, `gateway`, host or port changes, and for every meter of a gateway whose host or port changes. Without BR-31 the frontend applies the same rule to its own per-session results.
Response: `{ "ok": true, "latency_ms": 12, "error": null }`. Required: `ok`. Optional: `latency_ms`, `error`.
Errors: 404 (device gone), 4xx/5xx with `{error}`.

#### POST `/devices/`, PUT/DELETE `/devices/{id}/`, POST `/devices/{id}/connect/` and `/disconnect/` — unproven, flag `comms.deviceEdit`, BR-28
Screen action: add, edit, delete, connect and disconnect a device in Elements › Comms.
Evidence: v1's client object (`kl`) has these calls, but its UI never makes them. The only screen that uses the devices hook (`tx()`) takes `{devices, loading, error, fetchDevices, quickTest}` from it (`Zg()`). So the body is the repo `DeviceSerializer`'s, nested:
```json
{ "name": "MFM-01", "protocol": "modbus", "modbus_config": { "host": "10.90.200.11", "port": 502, "unit_id": 1 },
  "kind": "mfm", "gateway": "<gateway id>" | null, "serial_protocol": "rtu" }
```
- `opcua` devices send `"opcua_config": { "endpoint": "opc.tcp://…" }` instead. For an unknown protocol word, neither config is sent.
- `timeout_ms` and `retries` are never sent: an update keeps the stored values (`update_or_create`), and a create takes the defaults. `test_connection` is not sent (the repo tests on create).
- `kind` is sent only with BR-30 (`mappings.meterAttachments`); `gateway` and `serial_protocol` only with BR-31 (`comms.hierarchy`). `gateway: null` means no gateway (a direct device).
- Responses: create 201 / update 200 with the `DeviceSerializer` body (as GET). Delete 204. Connect: `{ "ok", "device_id", "device_name", "status", "latency_ms", "error" }`; disconnect: `{ "ok", "device_id", "status" }` (`ok` required).
- Until BR-28 confirms them, API mode shows the v1 list and Quick Test only.

### 3.2 Schemas

Field type words the frontend knows: `uint16 int16 uint32 int32 float32 float64 bool string int float`. Any other non-blank word is accepted on read, shown as-is and written back unchanged (open vocabulary, section 2 rule 3). For a new or changed field the user picks from the known words only: with the flags off (default against a real backend) v1's six, `float int16 int32 uint16 uint32 bool`; with BR-04 on all eight register types.

#### GET `/schemas/` — proven
Screen action: Schemas list, schema pickers.
```json
[{ "id": "…", "name": "LT Panel", "description": "", "field_count": 12, "created_at": "2026-10-03T08:00:00Z" }]
```
Required: `id`, `name`, `created_at`. Optional: `description`, `field_count`.

#### GET `/schemas/{id}/` — proven
Screen action: open a schema, edit, clone/export (composed from this GET).
```json
{
  "id": "…", "name": "LT Panel", "description": "",
  "fields": [{
    "id": "…", "key": "current_a", "field_type": "float", "unit": "A", "scale": 1.0, "description": "",
    "kind": "raw", "formula": null, "position": 0
  }],
  "created_at": "…Z", "updated_at": "…Z"
}
```
Required: `id`, `name`, `fields[]`, `created_at`, `updated_at`; per field `id`, `key`, `field_type`. Optional: `description`, per field `unit`, `scale`, `description`. BR optional per field: `kind` (`raw|derived`, BR-02; another word reads as raw, or derived when a formula is present), `formula` (string|null, BR-02), `position` (int, BR-03; when present fields must be returned ordered by it). Once a schema's fields carry `kind`, the frontend writes `kind` and `formula` back on every save of that schema, even while `schemas.derivedFields` is off, so derived fields survive edits to other fields.

#### POST `/schemas/` — proven
Screen action: Create schema; Clone schema (GET source, POST `"{name}_clone"`); Import schemas (one GET of the list, then one POST per schema in the file; one failing does not stop the rest). A name that matches an existing schema or an earlier one in the file, ignoring case, is not sent: the backend's unique check is case-sensitive, the screen's is not.
```json
{ "name": "LT Panel", "description": "", "fields": [
  { "key": "current_a", "field_type": "float", "unit": "A", "scale": 1, "description": "", "kind": "raw", "position": 0 },
  { "key": "current_max", "field_type": "float64", "unit": "A", "scale": 1, "description": "",
    "kind": "derived", "formula": "max(current_a, current_b)", "position": 1 } ] }
```
`kind` (on every field) and `formula` are sent only with BR-02 (`schemas.derivedFields`), or when the schema read already carried kinds. `position` (on every field, its index) is sent only with BR-03. A derived field is always sent as `field_type: "float64"`, `scale: 1`; a bool or string field's `scale` is sent as 1. With both flags off the body is v1's: `{ "key", "field_type", "unit", "scale", "description" }` per field. `unit`, `scale`, `description` are always sent. Response 201: same as GET detail. Errors: 400 `{name:["…"]}` for duplicate name, 400 `{fields:[{field_type:["…"]}]}`.

#### PUT `/schemas/{id}/` — proven
Screen action: Edit schema (rename and every field edit; v1 sends the whole schema, so field ids change on each save). Body as POST. Response 200: detail. BR-22 (proposed; v2 does not send it on schemas yet) would add `If-Match: <updated_at>` → 409.

#### DELETE `/schemas/{id}/` — proven
Screen action: Delete schema. Response 204 (body ignored). If a table uses the schema the repo raises ProtectedError (HTML 500); the UI maps that to "still in use". BR-06 asks for 409 `{"detail":"Schema is used by tables","tables":[{"id","name"}]}`.

#### POST `/schemas/{id}/fork/` — proposed, BR-05, flag `schemas.splitOnEdit`
Screen action: "Split schema" when editing a schema used by several tables. Atomically creates a new schema and re-points the listed tables to it.
```json
{ "name": "lt_v2", "table_ids": ["…"], "fields": [ { "key": "current_a", "field_type": "float32", "unit": "A", "scale": 1, "description": "" } ] }
```
Response 201: `{ "source": <Schema detail>, "created": <Schema detail> }`. Until shipped the UI edits in place after an impact confirmation.

### 3.3 Tables and mappings

Status words: table `status` is `pending|migrated|error`; `mapping_health` is `unmapped|partial|mapped`. Unknown words are tolerated (shown as unknown).

#### GET `/tables/` — proven
Screen action: Tables list.
```json
[{ "id": "…", "name": "lt_panel_1", "schema_name": "LT Panel", "device_name": "PLC-1", "status": "migrated", "mapping_health": "mapped",
   "storage_target_name": "Default", "schema_id": "…", "device_id": "…", "storage_target_id": "…",
   "row_count": 1200, "validated_count": 10, "conflict_count": 0, "attached_to_hierarchy": false }]
```
Required: `id`, `name`, `status`, `mapping_health`. Optional: `schema_name`, `device_name`, `storage_target_name`. BR optional: `schema_id`, `device_id`, `storage_target_id`, `row_count`, `validated_count`, `conflict_count` (BR-11: rows whose address another row of the table reads, whose field is mapped twice, or whose field is not a raw field of the schema; each row counted once); `attached_to_hierarchy` (BR-10). (Repo list serializer today has only the first six; `storage_target_name` is an additive field, in BR-11.)

#### GET `/tables/{id}/` — proven
Screen action: open table (mapping rows), clone table (composed), export rows.
```json
{
  "id": "…", "name": "lt_panel_1", "schema": "…", "schema_name": "LT Panel",
  "storage_target": "…", "storage_target_name": "Default", "device": "…", "device_name": "PLC-1",
  "status": "pending", "mapping_health": "partial", "last_migrated_at": null, "last_error": null,
  "mappings": [{
    "id": "…", "field_key": "current_a", "protocol": "modbus", "address": "40001",
    "data_type": "float", "scale": 1.0, "deadband": 0.0, "byte_order": "ABCD", "poll_interval_ms": null,
    "validated": false, "validated_at": null, "validated_by": null
  }],
  "created_at": "…Z", "updated_at": "…Z", "attached_to_hierarchy": false
}
```
Required: `id`, `name`, `schema`, `status`, `mapping_health`, `mappings[]`; per mapping `id`, `field_key`, `protocol` (known: `modbus|opcua`; any other non-blank word is kept as-is, with no address format check), `address`, `data_type` (open, as for fields), `scale` (number), `deadband` (number). Optional: `schema_name`, `storage_target(_name)`, `device(_name)` (null = unbound), `last_migrated_at`, `last_error`, `created_at`, `updated_at`, per mapping `byte_order` (known: `ABCD|DCBA|BADC|CDAB`, another word kept as-is, or `""`/null = not set), `poll_interval_ms`. BR-09 optional per mapping: `validated` (bool), `validated_at` (ISO|null), `validated_by` (string|null).

#### POST `/tables/` — proven
Screen action: New table; Clone table (creates without a device, then bulk-copies rows).
Body: `{ "name": "lt_panel_1", "schema": "<schema id>", "device": "<device id>" | null }` (v2 never sends `storage_target`; the server falls back to the default target).
Response 201: `{ "id", "name", "schema", "storage_target", "device" }` (required: `id`, `name`, `schema`).
Errors: 400 field errors; duplicate `(name, storage_target)` currently an IntegrityError HTML 500 → mapped to "already exists" (BR-06 asks for 400).

#### PATCH `/tables/{id}/` — rename: proven; rebind (schema/device): unproven, flag `tables.rebind`
Screen action: Rename table (`{ "name": "new" }`); Edit table (`{ "schema": "<id>" }` and/or `{ "device": "<id>" | null }`, only keys that changed). Response body ignored (200 with the table is fine).

#### DELETE `/tables/{id}/` — proven
Screen action: Delete table. 204. (Physical table is left in the storage target, as today.)

#### POST `/tables/{id}/mappings/bulk/` — proven
Screen action: Save mapping rows; Clone table; Import rows; fallback "delete a row" (v1's shape).
```json
{ "mappings": [{ "field_key": "current_a", "protocol": "modbus", "address": "40001", "data_type": "float", "scale": 1, "deadband": 0, "byte_order": "ABCD" }] }
```
All seven keys always sent. A row without a byte order is sent as `"ABCD"` (as v1 does). `data_type` is collapsed to `int|float|bool|string` unless BR-04 is on (then all register types verbatim). Response: `{ "created": 1, "updated": 0, "errors": [], "total_processed": 1, "total_errors": 0 }`. Required: `created`, `updated`; `errors` is a list (any element shape; strings or `{field_key, error}` objects are both read). Semantics: this is an upsert by `field_key`; omitting a key does **not** delete it (BR-07).

#### POST `/tables/{id}/mappings/validate/` — proven
Screen action: "Validate" (live read of every mapping). No body.
```json
{ "table_id": "…", "device_id": "…", "total": 2, "ok": 1, "failed": 1,
  "results": [ { "field_key": "current_a", "address": "40001", "protocol": "modbus", "ok": true, "value": 12.5, "error": null } ] }
```
Required: `total`, `ok`, `failed`, `results[]` (`field_key`, `ok`; `value` any; `address`, `protocol`, `error` optional). Non-2xx with `{error}` when the table has no device or the device is unreachable is shown as a failure message.

#### DELETE `/tables/{id}/mappings/{mappingId}/` — unproven, flag `tables.rowDelete`, BR-07
Screen action: delete one mapping row. 204. Until confirmed the UI uses bulk-without-the-row, refetches, and warns if the row survived.

#### POST `/tables/{id}/mappings/set_validated/` — proposed, BR-09, flag `tables.manualRowValidation`
Screen action: "Mark rows validated" / "Unmark". Body `{ "mapping_ids": ["…"], "validated": true }` → `{ "updated": 2 }`. Persists `validated`, `validated_at`, `validated_by` (token's `preferred_username`) on `FieldMapping`, returned by GET table.

#### GET `/tables/{id}/mappings/export/` and POST `/tables/{id}/mappings/import/` — unproven, flag `tables.mappingTransfer`
Screen action: Export rows / Import rows (one table). Export response: `{ "table_id", "table_name", "mappings": [ <mapping write shape; byte_order may be "", null or absent> ] }` (`mappings` required). Import body: `{ "mappings": [ … ] }` (same as bulk). Response: `{ "created": n, "errors": [] }` (`created` required). Note the repo import **replaces** all rows.

#### POST `/tables/{id}/migrate/` — unproven, flag `tables.migrate`
Screen action: "Migrate" (create the physical table). No body. Response: `{ "ok": true, "table_id": "…", "table_name": "…", "status": "migrated", "error": null }` (`ok` required). A failure is `ok:false` with `error` (HTTP 200 or 4xx/5xx with `{error}` both handled).

#### GET `/tables/export/` and POST `/tables/import/` — proposed, BR-08, flag `tables.listImportExport`
Screen action: list-level Import / Export of tables with their rows.
Export response: `{ "tables": [ { "name", "schema_name", "device_name": "PLC-1"|null, "mappings": [ <mapping write shape; byte_order may be "", null or absent> ] } ] }`. The file the frontend downloads from Export is this same snake_case shape (stored words as-is, a blank byte order as `""`), so Import accepts Logger's own exports; the row export downloads `{ "mappings": [ … ] }` in the same mapping shape.
Import body: the same `{tables:[…]}` shape, each row as in `bulk/` (`data_type` collapsed to `int|float|bool|string` unless BR-04; a row without a byte order as `"ABCD"`). Response: `{ "created": ["name", …], "errors": [ { "name": "…", "error": "…" } ] }`. Resolve schema/device by name; a missing one is an error entry for that table, not a 4xx for the whole call.
Route-order note: register `export/` and `import/` before the `{id}` detail route so they are not read as ids.

### 3.4 Jobs

`job_type` words read: `continuous`, `trigger` (also `triggered`), `scheduled`, `on_change`; anything else is shown as "unknown". Written today: `continuous` and `trigger`; `scheduled`/`on_change` only with BR-14. `status` read: `running|paused|stopped`; anything else (for example `error`, BR-15) is shown as "unknown".

#### GET `/jobs/` — proven
Screen action: Jobs list (polled every `polling.jobsMs` while the Jobs route is visible).
```json
[{ "id": "…", "name": "Hourly", "job_type": "continuous", "interval_ms": 1000, "enabled": true, "status": "stopped", "table_count": 3,
   "tables": ["…"], "batch_size": 1, "created_at": "…Z", "updated_at": "…Z",
   "cpu_budget": "balanced", "batch_window_ms": null, "last_write_at": null }]
```
Required: `id`, `name`, `job_type`, `interval_ms`, `status`. Optional: `enabled` (default true), `table_count`, `tables`, `batch_size`, `created_at`, `updated_at`. BR optional: `cpu_budget` (`low|balanced|high`, BR-12), `batch_window_ms` (int|null, BR-13), `last_write_at` (ISO|null, BR-23). The repo list omits `tables`, `batch_size` and the times; the UI then fetches the detail when it needs them.

#### GET `/jobs/{id}/` — inferred
Screen action: Job detail, Edit job, Clone job. Response = list item plus required `tables` (array of ids), `batch_size` (int), `created_at`, `updated_at`; optional `table_names` (array), `triggers` (array, opaque to v2).

#### POST `/jobs/` — proven
Screen action: New job; Clone job (POST a copy named "{name} (copy)", keeps batch size and exact interval).
```json
{ "name": "Hourly", "job_type": "continuous", "tables": ["<table id>"], "interval_ms": 1000, "enabled": true, "batch_size": 1,
  "cpu_budget": "balanced", "batch_window_ms": null }
```
`cpu_budget` only with BR-12; `batch_window_ms` (sent with `batch_size` 1 when batching by seconds, `null` when by rows) only with BR-13; `job_type` `scheduled|on_change` only with BR-14. `triggers` is **never sent** by v2 (it would replace v1 trigger configs). Response 201: job detail. Created stopped; the server never starts a job on create. BR-23 asks for 400 `{name:["job with this name already exists."]}`.

#### PATCH `/jobs/{id}/` — proven (v1 sends `{name}`; wider body to be calibrated)
Screen action: Edit job / rename. Any subset of the create keys except `enabled`. Response: job detail. `tables` sets the full list; omitted keys unchanged. Note: config is captured at start, so edits to a running job need a restart (BR-16 asks for reload).

#### DELETE `/jobs/{id}/` — proven. 204; stops the thread first.

#### POST `/jobs/{id}/start/`, `/stop/` — proven; `/pause/` — unproven (flag `jobs.pause`)
Screen action: Start / Stop / Pause buttons; Restart = stop then start (until BR-16); Resume = start (new run) (until BR-16). No body.
Response: `{ "ok": true, "job_id": "…", "status": "running" }` (required: `ok`, `status`; `job_id` optional). 400 `{error}` for "disabled" or "already running". `ok:false` with the old status is shown as a failure.

#### POST `/jobs/{id}/resume/` and `/jobs/{id}/restart/` — proposed, BR-16, flag `jobs.trueResume`
Same response as start. `resume` continues the paused run (no new JobRun, counters kept); `restart` is atomic stop+start reloading config.

#### GET `/jobs/metrics/summary/` — unproven, flag `jobs.liveMetrics`
Screen action: last-write, read/write rates (polled every `polling.metricsMs`).
```json
{ "live_metrics": [ { "job_id": "…", "reads": 100, "read_errors": 0, "writes": 100, "write_errors": 0, "rows_written": 100,
   "avg_read_latency_ms": 4.2, "p95_read_latency_ms": 9, "queue_size": 0, "started_at": "2026-10-03T08:00:00", "last_write_at": "2026-10-03T08:00:05" } ],
  "historical": { } }
```
`live_metrics` may be an **array** (repo; each item needs `job_id`) or an **object keyed by job id** (v1 production). Everything inside an item is optional; `started_at`/`last_write_at` may be naive (read as UTC). The UI derives rates as cumulative count / elapsed since `started_at`. `queue_size` is read if present (v1 sends it, the repo does not). Please confirm which shape production returns (BR-28).

#### GET `/jobs/{id}/runs/` — unproven, flag `jobs.runHistory`
Screen action: Job history (runs are projected to events when BR-17 is absent).
```json
[{ "id": "…", "started_at": "…Z", "stopped_at": null, "duration_ms": null, "rows_written": 0, "reads_count": 0, "read_errors": 0,
   "write_errors": 0, "avg_latency_ms": null, "p95_latency_ms": null, "avg_write_latency_ms": null,
   "error_log": [ { "code": "E1", "message": "…", "timestamp": "…Z" } ] }]
```
Required: `id`, `started_at`. All else optional.

#### GET `/jobs/events/?job=&before=&limit=` — proposed, BR-17/BR-18, flag `jobs.eventLog`
Response: `[ { "id", "job", "at", "kind": "started|paused|stopped|write|retry|error", "rows": 100|null, "detail": "…"|null, "actor": "preferred_username"|null } ]`. Required: `id`, `job`, `at`, `kind` (string; unknown kinds are dropped by the UI, not fatal). `before` is an ISO timestamp (return events strictly older), newest first; `limit` default 50. BR-18: record `actor` (token `preferred_username`) on start/stop/pause/resume/restart.

### 3.5 AI assistant (no repo implementation: production-only; shapes inferred from v1's bundle)

The repo backend has no AI endpoints and no `channels`. The shapes below are what v1 production uses and what v2's zod schemas accept. If your dev instance does not implement them, set the flag `assistant.enabled` to false in `config.json` (`"flags": {"assistant.enabled": false}`) and the panel is hidden.

Session object (response of create and get): `{ "id": "…", "status": "…", "current_stage": "…"|null, "goal": "…"|null, "latest_actions": [ { "id", "title", "risk_level": "…"|null, "status", "created_at": ISO|null } ]|null, "created_at": ISO|null, "updated_at": ISO|null }`. Required: `id`, `status`.

| Method + path | Screen action | Body | Response |
|---|---|---|---|
| POST `/ai/sessions/` | Start session (New chat) | `{ "goal": "Set up logger pipeline from devices to jobs", "autostart": true }` (v1's body, always this) | session object |
| GET `/ai/sessions/{id}/` | Poll session (every `aiFallbackMs` while the socket is down) | | session object |
| GET `/ai/sessions/{id}/events/` | Load/merge event timeline (merged by id) | | `[ { "id", "session": "…"|null, "stage": "…"|null, "event_type": "…", "message": "…"|null, "data_json": any, "created_at": ISO } ]` (required `id`, `event_type`, `created_at`) |
| GET `/ai/sessions/{id}/messages/` | Load messages | | `[ { "id", "role": "user"|"assistant"|…, "content": "…", "created_at": ISO } ]` (`id`, `role`, `created_at` required; `content` may be null, read as empty text; v1 never rendered these, so shape is a best guess) |
| POST `/ai/sessions/{id}/messages/` | Send a message | `{ "content": "…" }`; with BR-24 also `"context": { "screen": "tables", "entity_ids": ["…"] }` | any 2xx, body ignored |
| POST `/ai/sessions/{id}/run/` | Run/continue the session | none | body ignored |
| POST `/ai/sessions/{id}/cancel/` | Cancel | `{ "reason": "…" }` | body ignored |
| POST `/ai/actions/{id}/approve/` | Approve a proposed action | `{ "notes": "…" }` | body ignored |
| POST `/ai/actions/{id}/reject/` | Reject | `{ "notes": "…" }` | body ignored |

Provenance: all proven. BR-24 (context on messages) is proposed; the UI sends `{content}` only until `assistant.screenContext` is enabled.

**WebSocket** `WS /ws/ai/sessions/{id}/?token=<access token>` (proven, same origin as the page; the dev proxy forwards `/ws` unchanged). One JSON object per text frame:

```json
{ "event_id": "…", "session_id": "…", "stage": "plan", "event_type": "action_proposed", "message": "…", "data_json": {}, "created_at": "2026-10-03T08:00:00Z" }
```
Required: `event_id`, `event_type`, `created_at`; optional: `session_id`, `stage`, `message`, `data_json`. A malformed frame is logged once and skipped. On disconnect the UI auto-reconnects and meanwhile polls the REST endpoints; after reconnect it refetches events (so frames missed in the gap are recovered from `GET .../events/`). BR-25 asks to move the token out of the URL into `Sec-WebSocket-Protocol: bearer, <token>` (accept subprotocol `bearer`).

### 3.6 Elements: type catalog and electrical elements (BR-26, BR-32)

Flag `elements.electrical` (the Electrical tab). Vocabulary words in the catalog are open, case-sensitive data (section 2 rule 3). An unknown word never fails the catalog, and neither does a blank one (it reads as absent: the second column's fallback, except `rules_lock`, where blank = absent = `plant`; a blank field `kind` drops the field). Ids (`id`, `family`, `default_type`, field `id`) must not be blank.

| Word | Unknown value reads as |
|---|---|
| field `kind` (`quantity`, `count`, `choice`), or a quantity without units | the field is dropped; the element's stored value for it is kept and written back |
| `rules_lock` (`locked`, `editable`, `plant`) | `locked` (absent = `plant`, which defers to the plant flag `elements.rulesLocked`) |
| `ports.*` (`none`, `optional`, `required`) | `optional` |
| `shape` (`card`, `panelStrip`) / `supply` (`ac`, `dc`) | `card` / `ac` |
| `capacity.*.from` (`none`, `sections`, `limit`, `field`) | `none` |
| `sections.source` (`element`, `fields`) | no sections |
| field `role`, `summary`/`columns` keys, `metering` kinds, limit keys, `placement` | ignored (`placement` defaults to `bottom`) |
| element `type` | "Unknown type", never ready or connectable; written back unchanged |
| value `source` (`user`, `nameplate`) | `user`; the word is written back while the value and unit are unchanged |
| stored `rules.limits` key | kept and written back unchanged |

#### GET `/element-types/` — proposed, BR-26
```json
{ "version": "2026-10-04.1",
  "families": [{ "id": "transformer", "label": "Transformer", "order": 1, "default_type": "tf-power", "columns": ["voltage", "ratedCapacity"],
                 "map_group": "Transformers", "icon": "transformer", "subtype_placeholder": "e.g. Dry type" }],
  "types": [{
    "id": "tf-power", "family": "transformer", "label": "Power transformer", "short_label": "Power TF", "kind_of": null,
    "pickable": true, "creatable": true, "icon": "transformer", "shape": "card", "supply": "ac",
    "fields": [
      { "id": "primaryVoltage", "label": "Primary voltage", "kind": "quantity", "required": true, "role": "voltage.in", "units": ["kV", "V"], "placeholder": "33" },
      { "id": "phase", "label": "Phase", "kind": "choice", "required": true, "role": "phase", "options": ["3 Phase", "1 Phase"] },
      { "id": "frequency", "label": "Frequency", "kind": "choice", "required": true, "role": "frequency", "options": ["50 Hz", "60 Hz"], "initial": "50 Hz" },
      { "id": "taps", "label": "Taps", "kind": "count", "required": false, "min": 0, "max": null }
    ],
    "one_of": [{ "fields": ["ratedPower", "ratedCurrent"], "label": "Rated power or rated current" }],
    "sections": null,
    "ports": { "incoming": "required", "outgoing": "required" },
    "capacity": { "incoming": { "from": "limit", "key": "maxIn", "fallback": 1 }, "outgoing": { "from": "limit", "key": "maxOut", "fallback": 1 } },
    "limits": [{ "key": "maxIn", "label": "Maximum incoming connections", "kind": "count", "placement": "bottom", "visible": true },
               { "key": "maxOut", "label": "Maximum outgoing connections", "kind": "count", "placement": "bottom", "visible": true }],
    "defaults": { "incoming": ["ht-panel"], "outgoing": ["lt-panel"], "limits": { "maxIn": "1", "maxOut": "1" } },
    "permitted": { "incoming": "any", "outgoing": "any", "limits": { "maxIn": { "min": 1, "max": 99 }, "maxOut": { "min": 1, "max": 99 } } },
    "rules_lock": "plant", "bridge": true, "metering": ["element"], "summary": ["voltage", "ratedCapacity"]
  }],
  "phase_compat": [
    { "source": "3 Phase", "target": "3 Phase 4 Wire", "voltage_ratios": [1] },
    { "source": "3 Phase 4 Wire", "target": "3 Phase", "voltage_ratios": [1] },
    { "source": "3 Phase", "target": "1 Phase", "voltage_ratios": [1, 0.5773502691896258] },
    { "source": "3 Phase 4 Wire", "target": "1 Phase", "voltage_ratios": [1, 0.5773502691896258] }
  ],
  "voltage_tolerance_pct": 8,
  "rule_settings": { "frequency": "off", "phase": "warn" } }
```
- Required: `version`, `families[]` (`id`, `label`, `default_type`), `types[]` (`id`, `family`, `label`, `ports`). Everything else has a default: `pickable`/`creatable` true, `fields`/`one_of`/`limits`/`metering`/`summary` empty, `capacity` none (each side separately: a type may send only `capacity.outgoing`), `defaults` empty, `permitted` `any`, `bridge` false, `short_label` = `label`, `icon` `custom`.
- `sections`: `{ "source": "element", "initial": 1, "coupler": true }` (the element stores 1–4 bus sections) or `{ "source": "fields", "incomers": "<field id>", "feeders": "<field id>" }`.
- `kind_of` is the is-a parent ("chiller" is a kind of "load"): a rule allowing the parent accepts its descendants.
- `phase_compat`: a list of rows `{ "source", "target", "voltage_ratios" }`. A `source` phase may feed a `target` phase when the target's nominal voltage is the source's times one of `voltage_ratios`, or equals it (ratio 1 is always allowed, so list only the extra ratios; a row with `[1]` only grants the phase pairing), within the tolerance; `1/√3 ≈ 0.5773502691896258` is a line-to-neutral load on a three-phase supply. A match at a ratio other than 1 carries no note. A near match at ratio 1 carries the "nominal voltages differ" note. Equal phases always match at ratio 1 and need no row. An empty list, null or no key = equal phases only. Phase words are compared exactly as written, and an unknown one is kept. Absent `voltage_ratios` = `[1]`. A ratio of 0 or below is ignored, and a row left with no ratio is ignored. A ratio that is not a JSON number (a string, null) is a contract error for the whole catalog, like the old object form.
- `voltage_tolerance_pct` (optional number, default 8; absent, null or negative = 8): nominal voltages within this percentage of each other match (kV and V are compared in volts). A match that is not exact carries a "nominal voltages differ" note on screen.
- Field `initial` (optional text): the value a new element starts with (e.g. `"50 Hz"`). Blank = none.
- Limits: the `maxIn`/`maxOut` limits of transformers and the UPS, and the `maxIn` limit of the other loads (APFC, AHF and the rest have no outgoing port), are `visible: true`, `placement: "bottom"`, default `"1"` and `permitted` 1–99, so the user can edit them per element. A source's `maxOut` stays `placement: "top"` with `permitted` 0–99, and `"0"` or blank means no limit.
- **Rule switches (per plant)**, `rule_settings` (optional map from rule id to mode; absent = every rule blocks, today's behaviour). Modes:
  - `"block"`: the default. A connection that fails the rule is refused; an element that misses a readiness item is not Ready.
  - `"warn"`: a connection is allowed and carries a note. A readiness item is shown but does not stop Ready.
  - `"off"`: the rule is not checked.

  Configurable rule ids:
  - connection checks: `voltage`, `sourceFeedsType`, `targetReceivesType`, `supply`, `phase`, `frequency`;
  - readiness items: `requiredField`, `invalidNumber`, `oneOf`, `sectionIncomers`, `sectionFeeders`, `allowedIncoming`, `allowedOutgoing`, `outgoingOverLimit`, `limitOutOfRange`.

  Fixed rule ids always block, whatever `rule_settings` says: `self`, `duplicate`, `noOutgoingPort`, `noIncomingPort`, `targetIncomingFull`, `sourceOutgoingFull`, `cycle`, `unknownType`. An unknown rule id or mode is ignored (that rule blocks). A mode that is not a string is a contract error. Example: `"rule_settings": { "frequency": "off", "phase": "warn" }` stops checking frequency and lets a phase mismatch through with a note.

#### GET `/elements/` — proposed, BR-26
```json
[{ "id": "…", "name": "TF-01", "type": "tf-power", "subtype": "",
   "values": { "primaryVoltage": { "value": "33", "unit": "kV", "source": "user" }, "phase": { "value": "3 Phase", "unit": null, "source": "nameplate" } },
   "sections": [{ "max_incomers": "2", "feeders": "9" }, { "max_incomers": "1", "feeders": "6" }], "couplings": [[0, 1]],
   "rules": { "incoming": ["ht-panel"], "outgoing": ["lt-panel"], "limits": { "maxOut": "2" } },
   "nameplate": { "file_name": "tf01.jpg", "uploaded_at": "…Z" }, "spare": false, "updated_at": "…Z" }]
```
- Required: `id`, `name`, `type` (non-blank; a blank type fails the list). Values stay strings exactly as typed (a number is read as its text). `rules: null` means "use the catalog defaults"; the first rules edit stores a copy.
- `spare` (optional boolean, absent or null = false): "Spare / not on map". Such an element is left out of the map's "not placed" and "unconnected" warnings.
- `couplings`: bus couplers, as `[low, high]` section index pairs. Only **neighbouring** sections can be coupled: `[i, i + 1]` with `i + 1` inside `sections` (`[0,1]`, `[1,2]`, `[2,3]`). The frontend reads a reversed neighbour pair as the right way round, and drops any other pair (it never had an effect); its next save sends the cleaned list. Please validate the same rule and answer 400 for another pair.
- The server validates an element against the catalog (known type, field ids), not readiness: incomplete elements are normal while a plant is set up.

#### POST `/elements/`, PUT `/elements/{id}/`, DELETE `/elements/{id}/` — proposed, BR-26
- Body: `{ "name", "type", "subtype", "values", "sections", "couplings", "rules", "spare" }` (`nameplate` and `updated_at` are server-managed). `spare` is optional in the contract (absent on POST = false; absent on PUT = keep the stored value); v2 always sends it (true or false). `couplings` holds neighbour pairs only. Response: the element (201 / 200).
- PUT sends `If-Match` (BR-22) with the element's `updated_at` **exactly as the server last sent it** (same text: microseconds and the offset spelling are kept), when the element has one; compare it with the stored value and answer 409 when they differ.
- DELETE answers 204 and also removes the element from `/topology/` (placed, connections, meter attachments) and bumps the revision.
- 400 field errors as DRF (`{"name":["… already exists."]}`).

#### POST `/elements/{id}/nameplate/` and `/elements/{id}/nameplate/extract/` — proposed, BR-32, flag `elements.nameplate`
- Upload: `multipart/form-data` with part `file` (image or PDF; no JSON content type) → `{ "file_name", "uploaded_at" }`. Storing it may bump the element's `updated_at`: the client re-reads `/elements/` before its next write to that element.
- Extract: no body → `{ "fields": { "<catalog field id>": { "value": "11", "unit": "kV" } } }`. Unknown field ids are ignored; the UI fills blank fields only and tags them `source: "nameplate"`.

#### GET `/elements/export/` and POST `/elements/import/` — proposed, BR-32, flag `elements.excel`
- Export: the `.xlsx` file itself (one row per element).
- Import: `multipart/form-data` with part `file` (`.xlsx`) → `{ "created": 2, "updated": 1, "errors": [{ "row": 7, "name": "TF-09", "error": "Unknown type" }] }` (`created` required).
- Route-order note: register `export/` and `import/` before the `{id}` routes.

### 3.7 Topology: the single-line diagram document (BR-29, BR-30)

Flag `screens.mappings`. The document is replaced whole. Every write is pessimistic and carries the revision it was built on, as is: the client never re-targets a write at a newer revision, and never sends a second write while one is in flight (a second edit is refused on the client). `revision` may be any opaque token, including a content hash that recurs.

#### GET `/topology/` — proposed, BR-29
```json
{ "revision": "17",
  "placed": ["<element id>", "…"],
  "connections": [{ "id": "c1", "from": "<element id>", "to": "<element id>", "from_slot": 0, "to_slot": 1, "role": "normal" }],
  "meter_attachments": [
    { "point": { "kind": "incomer", "element": "<element id>", "slot": 0 }, "device": "<MFM device id>", "kind": "mfm" },
    { "point": { "kind": "incomer", "element": "<element id>", "slot": 0 }, "device": "<PQM device id>", "kind": "pqm" } ] }
```
- Required: `revision` (opaque string; a number is read as its text), `placed`, `connections` (`id`, `from`, `to`). `from_slot` is the source's outgoing slot (a panel's global feeder index, F01 = 0), `to_slot` the target's incoming slot (global incomer index); null on legacy data. `role` is `normal` (default) | `backup` | `alternate` | `emergency`; another word is shown as normal and written back unchanged on that connection (also after a replace or an undo) until the user picks a role. A new connection, even between the same two elements, never inherits it.
- `meter_attachments` is BR-30 (absent until it ships). `point.kind` is `element` (the whole element; no slot) | `incomer` | `feeder` (with `slot`). Each row's `kind` is the meter's kind: `mfm` | `pqm`, or another word, which is kept as-is. **A point holds at most one meter of each kind** (an MFM and a PQM may share it), and **a device sits on at most one point**: enforce uniqueness per (point, `kind`) and per device. Always send `kind`. A row without one (an older server) takes the device's own `kind` from `GET /devices/` (BR-30), and the next save sends it; when the device has no `kind`, the row is kept and written back as read. When rows break a uniqueness rule, the frontend keeps the first and drops the others on its next save (they are not written back). An attachment the UI cannot show (an unknown or blank `kind`, or an `incomer`/`feeder` without a `slot`) is kept and written back as read (ids as strings, a missing `slot` as `null`), unless its device or its (point, kind) is already taken by another row, or its element left the map. `placed`, `connections` and `meter_attachments` may be omitted on read (read as empty).

#### PUT `/topology/` — proposed, BR-29
- Body: the same document with the `revision` the edit was built on, **always as a JSON string** (a numeric revision is sent back as its text, 17 → "17", so compare revisions as text). Ids are sent as strings too. Every connection carries `from_slot`, `to_slot` (null when unknown) and a non-blank `role`; every attachment point carries `slot` (null for `element`). Undo sends the earlier snapshot with the **current** revision. Response 200: the stored document with a new revision.
- Connection `id`s are minted by the client for new connections (`c1`, `c2`, …: unique within the document, not UUIDs). Store each exactly as sent and return it unchanged, also when an undo sends an older snapshot; do not model it as a UUID primary key. `placed`, `from`, `to`, `element` and `device` are your element and device ids.
- 409 when `revision` is stale: the UI re-reads the map, clears its undo history and notes "The map changed elsewhere". Only a 409 means this; any other failure (including a 5xx Django IntegrityError page) is reported as a failed save, the map is re-read, and the undo history is kept.
- `meter_attachments` is sent only with BR-30 (`mappings.meterAttachments`); without the key the server keeps the stored attachments. When sent, each device and each (point, `kind`) appears at most once, and every row the frontend can show carries `kind`. A row without `kind` is exempt from the (point, `kind`) rule. Please answer 400 when a body breaks either rule.
- Optional: 400 `{ "connections.3": ["cycle"] }` if the server runs the same connection checks (check ids: `missingEndpoint`, `self`, `duplicate`, `noOutgoingPort`, `noIncomingPort`, `targetIncomingFull`, `sourceOutgoingFull`, `cycle`, `voltage`, `sourceFeedsType`, `targetReceivesType`, `supply`, `phase`, `frequency`).

### 3.8 Gateways and logger servers (Elements › Comms)

#### `/gateways/` CRUD and POST `/gateways/{id}/test/` — unproven, flag `comms.gateways`, BR-28
The repo `GatewayViewSet`; v1 never calls it.
```json
[{ "id": "…", "name": "GIC-01", "host": "10.90.200.11", "adapter_id": "", "ports": [502], "status": "reachable", "last_ping_ms": 4,
   "last_tcp_result": null, "created_at": "…Z", "updated_at": "…Z", "server": "<server id>", "protocol": "modbus_tcp", "port": 502 }]
```
- Required: `id`, `name`, `host`. `ports` is a free JSONField: whole numbers (also numeric strings such as `"502"`) are read, anything else is ignored. `status` `reachable|unreachable` (after a test); anything else, such as the repo default `unknown`, reads as untested.
- Membership: with BR-31 (`comms.hierarchy`) and the device's `gateway` key present, the key decides (an id joins that gateway; null = direct; an id the list lacks falls back to host and port). Otherwise a device belongs to the gateway whose `host` equals its host (trimmed, case-insensitive) and whose `ports` include its port; else it is a direct device. A device is a meter only when the list also carries its `modbus_config.unit_id`; without it the device is direct.
- Write body: `{ "name", "host", "ports": [<edited port first>, …] }`, plus BR-31 `server`, `protocol`, `port` only with `comms.hierarchy`.
- BR-31: a `PUT /gateways/{id}/` that changes `host` or `port` clears `verification` and `verified_at` (back to `unverified`, null) on every device of that gateway. See also §3.1 (`quick_test`).
- Test (ping): no body → `{ "ok", "gateway_id", "gateway_name", "host", "latency_ms", "error" }` (`ok` required; the repo's latency 0 on failure reads as none).
- BR-31 adds `server` (FK), `protocol` (`modbus_tcp` | `iec104`, open; absent = `modbus_tcp`) and a single `port` (else `ports[0]`).

#### `/logger-servers/` CRUD — proposed, BR-31, flag `comms.hierarchy`
`GET` → `[{ "id", "name", "ip" }]`; `POST`/`PUT {id}` body `{ "name", "ip" }` → the server; `DELETE {id}` → 204 (its gateways keep existing with `server: null`).

### 3.9 Cross-cutting new endpoints

- **GET `/capabilities/` — proposed, BR-01.** Returns `{ "schemas.derivedFields": true, "jobs.pause": false, … }` (flag key → bool). Not called by v2 yet (planned). When it is, a `true` turns on only the "Unlocks flag" entries of the proposed BRs, except `screens.mappings` (BR-29) and `shell.roleAwareUi` (BR-21). Those two and the BR-28 flags still need `config.json`, and `config.json` always wins. Not required for the other BRs.
- **GET `/me/` — proposed, BR-21, flag `shell.roleAwareUi`.** Returns `{ "username", "name", "email", "roles": ["neuract-admin"] }`. Alternative: confirm the production token carries `resource_access["neuract-logger"].roles`.

---

## 4. Backend requests (BR ledger)

Status for all: proposed (raised 2026-10-03). "Verify" is the read-only check we run. `$BASE` is the base URL (for example `http://<ip>:5175/core`); `$TOKEN` a bearer token; curl is `curl -sS -H "Authorization: Bearer $TOKEN"`.

| ID | Title | Ask (method path, fields) | Unlocks flag | UI fallback until shipped | Verify |
|---|---|---|---|---|---|
| BR-01 | Capabilities map | GET `/capabilities/` → `{"flag.key": bool}` | (none; informs all) | Flags from `config.json` only | `GET $BASE/capabilities/` |
| BR-02 | Derived schema fields | `PUT /schemas/{id}/` fields accept `kind` (`raw|derived`) and `formula`; echoed back; 400 `{fields:[{formula:["…"]}]}` for an unknown name, a later field (by position, BR-03) or, without positions, a cycle | `schemas.derivedFields` | Raw fields only; derived UI hidden | `GET /schemas/$ID/ | jq '.fields[0] | has("kind")'` |
| BR-03 | Field position | fields accept/return `position` (int); returned ordered by it | `schemas.fieldPosition` | Alphabetical order; no compute-order label | `GET /schemas/$ID/ | jq '[.fields[].position]'` |
| BR-04 | Full 8-type vocabulary | fields accept `uint16 int16 uint32 int32 float32 float64 bool string`; mappings `data_type` stored verbatim | `schemas.registerTypesFull`, `tables.registerTypesFull` | v1's six field types; rows collapse to int/float/bool/string | `OPTIONS $BASE/schemas/` or PUT a `float32` field |
| BR-05 | Atomic schema fork | `POST /schemas/{id}/fork/` `{name, table_ids[], fields[]}` → 201 `{source, created}` | `schemas.splitOnEdit` | Edit in place after an impact confirm | `OPTIONS $BASE/schemas/$ID/fork/` |
| BR-06 | Proper errors | `DELETE /schemas/{id}/` in use → 409 `{detail, tables:[{id,name}]}`; duplicate field key (schema PUT), duplicate `field_key` rows (`mappings/bulk/`), duplicate table `(name, storage_target)` (`POST /tables/`) → 400 field error (not an IntegrityError 500) | (none) | UI blocks deleting a schema with readers; 500 ProtectedError/IntegrityError mapped to "conflict" | delete a used schema, check status |
| BR-07 | Mapping delete semantics | Confirm `bulk/` is upsert (it is in the repo); support `DELETE /tables/{id}/mappings/{mapping_id}/` → 204 | `tables.rowDelete` | Bulk without the row, refetch, warn if it survived | bulk without a row, then GET the table |
| BR-08 | Table list import/export | `GET /tables/export/`, `POST /tables/import/` (shapes in 3.3) | `tables.listImportExport` | Hidden | `GET $BASE/tables/export/` |
| BR-09 | Persisted row validation | mappings add `validated`, `validated_at`, `validated_by`; `POST /tables/{id}/mappings/set_validated/` `{mapping_ids, validated}` → `{updated}` | `tables.manualRowValidation` | Row status from the live read only | `GET /tables/$ID/ | jq '.mappings[0] | has("validated")'` |
| BR-10 | Attached on the map | `GET /tables/` items add `attached_to_hierarchy` (bool) | `tables.electricalMap` | Map column shows mapping health | `jq '.[0] | has("attached_to_hierarchy")'` |
| BR-11 | Ids and counts on table list | items add `schema_id`, `device_id`, `storage_target_id`, `storage_target_name`, `row_count`, `validated_count`, `conflict_count` | `tables.rowStats` | Status from lifecycle/health; counts "—" | `jq '.[0] | has("row_count")'` |
| BR-12 | `Job.cpu_budget` | job create/patch/list/detail: `cpu_budget` = `low|balanced|high` | `jobs.cpuBudget` | Field hidden | `GET /jobs/$ID/ | jq 'has("cpu_budget")'` |
| BR-13 | `Job.batch_window_ms` | job accepts/returns `batch_window_ms` (int ms, null = batch by rows) | `jobs.batchSeconds` | Batching is "Batch size (rows)" | `jq 'has("batch_window_ms")'` |
| BR-14 | More job types | `job_type` accepts `scheduled`, `on_change` (+ their parameters, to be agreed) | `jobs.extraTypes` | Continuous and Triggered only | `OPTIONS $BASE/jobs/ | jq '.actions.POST.job_type.choices'` |
| BR-15 | Honest job status | `status` may be `error`; never `running` without a live thread (fix stale `running` after a restart) | (none) | Unknown status shown as "unknown"; Stop is allowed for unknown | restart server with a running job, GET `/jobs/` |
| BR-16 | True pause/resume | `POST /jobs/{id}/resume/` keeps the run; `POST /jobs/{id}/restart/` atomic; running jobs reload config on edit | `jobs.trueResume` | Resume = start (new run); restart = stop then start | `OPTIONS $BASE/jobs/$ID/resume/` |
| BR-17 | Job event log | `GET /jobs/events/?job=&before=&limit=` (shape in 3.4) | `jobs.eventLog` | History projected from runs | `GET $BASE/jobs/events/?limit=1` |
| BR-18 | Actor on job commands | event `actor` = token `preferred_username` (`request.user` is None today) | `jobs.eventLog` | No actor shown | `jq '.[0].actor'` |
| BR-19 | Error envelope; 401 vs 403; `Z` timestamps | `{"code","message","field_errors":{"name":["…"]}}`; 401 for bad/expired token, 403 for missing role; all timestamps with `Z` (job live metrics are naive today) | (none) | Reads the four dialects in section 5 | call with an expired token, expect 401 |
| BR-20 | Pagination and filters | opt-in `?limit=&offset=&q=` → `{count,next,previous,results}`; absent `limit` keeps the bare array | (none) | Bare arrays; client-side filtering | `GET $BASE/tables/?limit=1` |
| BR-21 | `/me/` | `GET /me/` → `{username,name,email,roles[]}` | `shell.roleAwareUi` | Role-aware UI off; the server's 403 is the gate | `GET $BASE/me/` |
| BR-22 | Optimistic concurrency | `If-Match: <updated_at>` precondition → 409 when stale. v2 sends it today only on `PUT /elements/{id}/` (BR-26, the exact `updated_at` text); `PUT /schemas/{id}/` will send it once a flag is added | (none) | Per-entity write ordering in the client; last write wins on the server | PUT with a stale header |
| BR-23 | `last_write_at`; unique job names | list items add `last_write_at`; duplicate job name → 400 `{name:[…]}` | (none) | Last write from metrics (if flagged) or "—" | `jq '.[0] | has("last_write_at")'` |
| BR-24 | Screen context on messages | `POST /ai/sessions/{id}/messages/` accepts `context:{screen, entity_ids[]}` | `assistant.screenContext` | Sent without context | POST then read back in `messages/` |
| BR-25 | WS auth without URL token | accept `Sec-WebSocket-Protocol: bearer, <token>` | (none) | `?token=` query | wscat with the header |
| BR-26 | Element type catalog and elements (rescoped) | `GET /element-types/` `{version, families, types, phase_compat: [{source, target, voltage_ratios}], voltage_tolerance_pct, rule_settings: {rule id: block|warn|off}}` (fields may carry `initial`); CRUD `/elements/` with `spare` and neighbour-only `couplings` (400 otherwise), BR-22 `If-Match` (the exact `updated_at` text last sent); delete cascades the element's topology (3.6) | `elements.electrical` | No Electrical tab; Elements opens on Comms | `GET $BASE/element-types/ | jq .version` |
| BR-27 | Ops for the real v2 origin | CORS, `ALLOWED_HOSTS`, Keycloak redirect/web origins, post-logout URI for the v2 origin | (deploy gate) | Dev proxy is same-origin | `curl -I -H "Origin: <v2 origin>" $BASE/schemas/` |
| BR-28 | Confirm unproven endpoints | Confirm production behaviour of: `DELETE mappings/{id}/` (204), `PATCH /tables/{id}/` (schema/device), `POST migrate/` (`{ok, table_id, table_name, status, error}`), mapping `export/` `import/` (import replaces all rows), `POST /jobs/{id}/pause/` (`{ok, job_id, status}`), `GET /jobs/metrics/summary/` (shape + `queue_size`), `GET /jobs/{id}/runs/`, `GET /devices/` carrying `modbus_config` (with `unit_id`), `opcua_config` and `last_error` (3.1), device CRUD/connect/disconnect with the nested body (3.1), `/gateways/` CRUD and `test/` (3.8); or give us access logs | `tables.rowDelete`, `tables.rebind`, `tables.migrate`, `tables.mappingTransfer`, `jobs.pause`, `jobs.liveMetrics`, `jobs.runHistory`, `comms.deviceEdit`, `comms.gateways` | Each stays off in API mode | contract probe (later milestone) |
| BR-29 | Topology document | `GET/PUT /topology/` `{revision, placed, connections:[{id, from, to, from_slot, to_slot, role}]}`; 409 when the revision is stale; optional 400 `{connections.N:[check_id]}` (3.7) | `screens.mappings` | Mappings: "Not available on this server yet" | `GET $BASE/topology/ | jq .revision` |
| BR-30 | Meter attachments; device kind | topology `meter_attachments:[{point:{kind, element, slot}, device, kind}]`, at most one meter per (point, `kind`) and one point per device (400 otherwise); `Device.kind` (`mfm`, `pqm`, …) | `mappings.meterAttachments` | No meters on the map; meters "Not attached" | `jq 'has("meter_attachments")'` on GET topology |
| BR-31 | Comms hierarchy | `/logger-servers/` CRUD `{id, name, ip}`; `Gateway.server` FK, `protocol`, single `port`; `Device.gateway` FK, `serial_protocol`; persisted `verification`, `verified_at` via `quick_test/?save=1`, cleared when the device's `unit_id`, `kind`, `serial_protocol`, `gateway`, host or port changes and for every meter of a gateway whose host or port changes (3.1, 3.8) | `comms.hierarchy` | Gateways at the top level; membership by host and port; verification per session | `GET $BASE/logger-servers/` |
| BR-32 | Nameplate and Excel | multipart `POST /elements/{id}/nameplate/`, `POST …/extract/` → `{fields:{id:{value, unit}}}`; `GET /elements/export/` (xlsx), multipart `POST /elements/import/` → row report (3.6) | `elements.nameplate`, `elements.excel` | Nameplate pane and Export/Import hidden | `OPTIONS $BASE/elements/export/` |
| S1 | Security | `register/` and `users/{username}/roles/client-neuract-admin/` currently need no token (anyone can grant `neuract-admin`); hardcoded `SECRET_KEY` / Keycloak secret / DEBUG | (none) | v2 never calls them | POST `/register/` with no token, expect 401/403 |

Flags that are off by default against a real backend: all of the above plus the unproven ones. Mock mode turns them on for design review only. To enable one for your instance, add it to `config.json` `"flags"` (for example `{"jobs.pause": true}`).

---

## 5. Error envelope expectations and current tolerance

Target (BR-19): `{ "code": "…", "message": "…", "field_errors": { "name": ["…"] } }`, with 401 for authentication failures and 403 for authorisation failures.

Today the frontend reads these and nothing else:

| Status | Body it understands | Becomes |
|---|---|---|
| network failure / abort after `timeoutMs` | n/a | "server could not be reached" / "took too long" |
| 401 | any | session expired (one forced token refresh + retry) |
| 403 | JSON with `detail` matching `invalid token`, `authentication credentials`, or `expired` | session expired (refresh + retry) |
| 403 | anything else | forbidden (message = `error` / `detail` / `message`) |
| 404 | any | "no longer exists" |
| 409 | optional message | conflict |
| 400, 422 | `{error}`, `{detail}`, `{message}`, `{non_field_errors}`, or DRF field errors `{field:["…"]}`, nested lists/objects (`{fields:[{}, {field_type:["…"]}]}` flatten to `fields.1.field_type`) | validation error with per-field messages |
| 5xx, body text contains `ProtectedError` | HTML debug page | conflict "still in use by other records" |
| 5xx, body text contains `IntegrityError` | HTML debug page | conflict "a record with the same key already exists" |
| other 5xx | optional JSON message | server error (`HTTP n`) |
| 2xx but body fails the schema | n/a | "contract error" naming the endpoint and issues: logged once, one alarm note in the assistant timeline naming the endpoint, and **the screen shows an error instead of data** (retrying will not help) |

Message precedence: `error`, then `detail`, then `message`, then `non_field_errors`, then the first field error. Please keep `error` on custom action failures and use 4xx (not 200 with `ok:false`) only where today's code does.

Note for `DEBUG=True`: the HTML debug page is what lets us recognise ProtectedError/IntegrityError today; once BR-06 ships these become 409/400 with JSON.

---

## 6. Wiring checklist

**Send us**
1. Tailscale IP (or MagicDNS name) and confirmation that `0.0.0.0:5175` is reachable from our machine (`curl http://<ip>:5175/core/health/`).
2. The URL prefix (`/core`, `/api`, or none).
3. Keycloak: base URL (reachable from the browser over Tailscale; repo default `http://localhost:8080` will not work from our machine), realm (repo uses `logger`; v1 production (our reference `config/prod.config.json`) uses realm `master` at `http://192.168.1.20:8082`; our `dev-5175.config.json` has no Keycloak settings yet and runs `auth.mode: "none"` until you send these), client id (`neuract-logger`) and whether it is a public client with Authorization Code + PKCE and our dev origin (`http://127.0.0.1:3170`) registered as redirect and web origin; the write role name (`neuract-admin`). And the issuer string your tokens carry, which your `auth.py` must accept.
4. A test user with and without `neuract-admin`.
5. Sample JSON (redacted is fine) from: `GET /devices/`, `GET /schemas/` and one `/schemas/{id}/`, `GET /tables/` and one `/tables/{id}/`, `GET /jobs/` and one `/jobs/{id}/`, `GET /jobs/metrics/summary/`, `GET /jobs/{id}/runs/`, one validate result, and (if implemented) one AI session, events, and a WebSocket frame.
6. Whether the AI endpoints exist on your instance (section 3.5).

**Self-check with curl** (read-only; `TOKEN` from Keycloak; `BASE=http://<ip>:5175/core`):

```bash
H="Authorization: Bearer $TOKEN"
curl -sS $BASE/health/                                   # {"status":"ok",...}, no auth
curl -sS -H "$H" $BASE/devices/ | jq '.[0]'              # id name protocol status
curl -sS -H "$H" $BASE/schemas/ | jq '.[0] | keys'       # id name created_at required
ID=$(curl -sS -H "$H" $BASE/schemas/ | jq -r '.[0].id')
curl -sS -H "$H" $BASE/schemas/$ID/ | jq '.fields[0]'   # field_type: any non-blank word (unknown words are shown and written back as-is)
curl -sS -H "$H" $BASE/tables/ | jq '.[0]'
curl -sS -H "$H" $BASE/jobs/ | jq '.[0]'
curl -sS -H "$H" $BASE/jobs/metrics/summary/ | jq 'type, (.live_metrics|type)'
# auth behaviour (BR-19): expect 403 today, 401 after BR-19
curl -sS -o /dev/null -w '%{http_code}\n' $BASE/schemas/
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer bad" $BASE/schemas/
# write path needs neuract-admin: expect 201 then clean up with DELETE
curl -sS -H "$H" -H 'Content-Type: application/json' -X POST $BASE/schemas/ -d '{"name":"zz_probe","description":"","fields":[{"key":"a","field_type":"float","unit":"","scale":1,"description":""}]}'
# trailing slash and type vocabulary: this must NOT be a 400 once BR-04 ships
curl -sS -H "$H" -H 'Content-Type: application/json' -X POST $BASE/schemas/ -d '{"name":"zz_probe2","description":"","fields":[{"key":"a","field_type":"int16","unit":"","scale":1,"description":""}]}'
```
A response is acceptable when `jq` shows the required keys of section 3 and every timestamp parses. The automated contract probe (`npm run contract:probe -- --base $BASE`, read-only, validates every GET against the zod schemas and OPTIONS-checks the BR routes) is a later milestone; until then use the commands above and send us the output.

---

## 7. Known mismatches between the frontend and the repo backend (please confirm which is right for your instance)

1. **Schema field types.** Repo `DataType` = `bool|int|float|string` (`models.py`), so the serializer rejects `int16`, `int32`, `uint16`, `uint32`. v1 production's field-type select sends `float, int16, int32, uint16, uint32, bool`, and v2 accepts/sends those. Either production runs a different codebase or v1 gets 400s. If your dev backend is the repo, schema create with `int16` fails with 400 (BR-04 covers widening the choices).
2. **AI assistant.** v1 production calls `/ai/sessions/...`, `/ai/actions/...` and `WS /ws/ai/sessions/{id}/`; the repo has none of it (no `channels`, stock ASGI). Production is therefore not this repo.
3. **Auth.** The repo expects issuer `http://localhost:8080/realms/logger`; v1 production (our reference `config/prod.config.json`) uses realm `master` at `http://192.168.1.20:8082`; `dev-5175.config.json` has no Keycloak settings yet. Over Tailscale the issuer will differ.
4. **Prefix.** Repo mounts at `/core/`; v1 production/our config use `/api`.
5. **Job live metrics.** Repo: array with `job_id`, naive timestamps, no `queue_size`. v1 production: object keyed by job id, with `queue_size`. v2 accepts both.
6. **List serializers are thin.** Repo `DeviceListSerializer` has no `modbus_config`/`last_error`; `JobListSerializer` has no `tables`, `batch_size`, times; `DeviceTableListSerializer` has no ids. Accepted (optional), but without the device configs Comms cannot group devices or show meters (there is no per-device GET); jobs fetch `GET /jobs/{id}/` for the missing keys; table ids need BR-11.
7. **Unhandled 500s.** ProtectedError (delete schema in use) and IntegrityError (duplicate field key, mapping key, table name) arrive as HTML 500; handled by sniffing the body, brittle if `DEBUG=False` (BR-06).
8. **Job command results.** Repo returns HTTP 200 `{ok:false, status:<stale>}` when a thread does not exist (for example `stop` after a server restart); the UI shows a failure and the stale `running` status (BR-15).
9. **Mapping upsert.** `bulk/` upserts, so v1's "delete a row" (bulk without it) does not delete (BR-07). Repo `import/` replaces everything, unlike `bulk/`.
