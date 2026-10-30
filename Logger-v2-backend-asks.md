# Logger v2 on plc-agent: what we still need (2026-10-23)

Thanks for the mapping doc. We follow your conventions and your `/equipment` model:
- no trailing slashes;
- `{items}` and `{success, item}`;
- `{"detail": "CODE: context"}`.

For Schemas, Tables and mappings, Jobs and Devices/gateways we use your existing endpoints as they are, and ask for nothing new. Jobs go through `/jobs2` only, never `/jobs`. The only items below that touch those endpoints are your own B5 bug fixes and questions about how they behave today.

We checked everything against your live `/openapi.json` and GET-only calls, so nothing below exists already. The shapes are suggestions: anything additive works.

**Must have before plants**

**A1. Versions on equipment writes.** Several operators configure one plant, and today the last save silently wins.
- **A version on each equipment object:** an integer `version` that goes up on any change to it, its buses, its rules, the attachments on its buses or its meters, plus `updatedAt` in Z.
- **Writes check it.** They accept `If-Match: <version>`, and a stale one gets 409 `VERSION_CONFLICT: <id>`.
  - Bus, attach and meter routes check the equipment that owns the bus.
  - With no header, today's behaviour applies.
- **Attach and detach return both changed objects.**
- **A plant-wide revision is fine,** if that is much simpler.

**A2. Edits that shrink or break what is attached.** Please tell us today's behaviour, and ideally refuse rather than detach:
- bus `incomers` or `outgoers` set below the number attached (409 `CAPACITY_BELOW_ATTACHED`);
- `buses/count` lowered:
  - Which buses go?
  - Is it 409 `BUS_IN_USE` if they have attachments or meters?
  - Is `coupledNext` cleared on the new last bus?
- `maxIncomers` or `maxOutgoers` below what is attached;
- an allowed-category or `categoryId` change that existing attachments break: is it refused, or accepted and marked (for example `attachedTo[].violation`)?
- DELETE on equipment that has meters;
- `spare: true` on attached equipment.

Also: is `PUT /equipment/{id}` partial at the top level?

**A3. Feeder order, and which feeder a bus meter measures.** Our single-line diagram draws feeders as lanes. We need this before map editing ships.
- **Order.** Each attachment gets a `position`, unique per bus and role.
  - Lists and `attachedTo[]` are sorted by it.
  - Attach accepts an optional `position`, and `PUT /equipment/buses/{busId}/equipment/{eqId}` `{position}` reorders.
  - A detach keeps the others in order.
- **Bus meters.** A bus meter can name the feeder it measures (`equipmentId`).
- **Points.** Please define `metering.points` and `pointsMetered`.
- **Panel → panel.** Which bus of the attached panel receives the link, and whose capacity does `NO_SPARE` count? We plan to store the downstream panel as an outgoer on the upstream bus. Please confirm, or record both ends.

**A4. Sign-in and serving (your B1 and B4).**
- **Roles.** Please also accept the client role `neuract-admin` for writes, so existing Keycloak setups work. We read both that role and the realm role `logger-write`.
- **Keycloak for the browser.** For the shared instance and each plant:
  - a Keycloak URL the browser can reach (not `localhost:8080`);
  - the realm;
  - a public PKCE client with our origins;
  - the issuer for `KC_ALLOWED_ISSUERS`.
- **B4.** Yes, please require a token on the `/devices`, `/schemas`, `/tables` and `/jobs2` GETs too.
- **Testing auth.** A port with auth on, so we can test 401 and 403. The shared instance accepts `Bearer bad`.
- **Serving.** We plan to serve the UI from the API's own origin through a reverse proxy, so no CORS change should be needed. Please confirm. Today your CORS refuses hostnames, `10.x` and `172.16.x`.

**A5. Your B5 fixes, all three.** Until they ship we hide row delete, never call mapping import, and re-word migrate errors.
- `DELETE /mappings/{tableId}/{fieldKey}` must persist.
- `POST /mappings/{tableId}/import` must not wipe the table on an unknown body: answer 400 when `rows` is missing, and replace only with an explicit `"mode": "replace"`.
- Migrate failures answer 400, 409 or 500 with `MIGRATE_FAILED: …`. Use 404 only for an unknown table.

**A6. Something to integrate against.** `/equipment` is empty on the shared instance, and we only send GETs there. Please do one of these, and also send `API_DOCUMENTATION.md` §24:
- **Seed a small plant:** one source, one transformer, an HT panel with 2 buses and a coupler, an LT panel, 4 loads, and 3 meters, one of them on a bus outgoer.
- **Or give us a sandbox we may write to.** It would also answer Q3's response shapes.

**Should have**
- **S1. An error-code table.** Every code per route, with its HTTP status, context format and meaning. Please keep the codes stable. Include:
  - the old routes (`SCHEMA_IN_USE`, `TABLE_HAS_RUNNING_JOBS`, `DEVICE_ATTACHED_TO_EQUIPMENT`);
  - the bus routes;
  - the ping 429;
  - auth.
- **S2. `/tables` paging,** as behaviour fixes only:
  - the supported way to get all tables, and the maximum `pageSize`;
  - 422 for `pageSize < 1` or `page < 1` (today `pageSize=-1` silently drops the last row);
  - order by `lower(name), id` (two tables named `new12` come back in no fixed order).
- **S3. Meter kind on the meter attachment** (not on `/devices`).
  - An optional `kind` (`mfm` \| `pqm`) on `POST /equipment/{id}/meters` and `POST /equipment/buses/{busId}/meters`, returned in `metering.meters[]`.
  - Please also reserve an optional `label` (main/check).
- **S4. Timestamps in Z everywhere.** Job runs and `lastMigratedAt` use `+05:30`.

**Questions (an answer is enough)**
- **Q1. The map document (BR-29).** Is it coming, when, and in which model? We suggest a layout-only document over your equipment graph, with connections staying as bus attachments.
- **Q2. Card-to-card.** Every attach has a bus at one end, so Grid → Transformer or UPS → load cannot be stored without a panel in between. Is that intended?
- **Q3. How your existing APIs behave** (no change asked):
  - **Write answers.** What do `POST /tables/bulk_create`, `POST /jobs2` and `POST /schemas` return? Do they include the new ids? Is `columns: "all"` required on `POST /jobs2`?
  - **Schema fields.**
    - Can `PATCH /schemas/{id}/fields/{key}` change `key`, `eval_order` and `formula`?
    - How are fields reordered?
    - Is your formula syntax the same as ours? We will send examples.
  - **Mapping rows.**
    - Is a row's `encoding` the byte order, and does `POST /tables/{id}/mappings/bulk` accept it?
    - Which `data_type` words does bulk accept?
    - Does `POST /mappings/{id}/preview_sample` return live read values?
  - **Words and units.**
    - The full `mappingHealth` list (we see `Mapped` and `Partially Mapped`).
    - The unit of a run's `error_pct` (we saw 4300.0).
    - The shape of `last_ping` and `last_tcp`.
  - **Device host.** For a direct device (`gatewayId: null`), where is the host? No live device has `params.host`.

**Nice to have**
- Ping accepting an empty body (B3). We send `{}` anyway.
- gzip on JSON. `/tables` is about 3.6 KB per table.
- Typed openapi response models, `/equipment*` first.
- ETag and 304 on the big GETs.
- An atomic move (`POST /equipment/buses/{busId}/equipment/{eqId}/move`), and create-with-attach.
- `apiVersion` and `features[]` on `GET /version`.

**Not asking**
- New endpoints for schemas, tables, jobs or devices.
- Trailing slashes (B2), or renaming `/jobs2` (B6).
- `/capabilities` and `/me`.
- Idempotency-Key.
- Topology PUT/PATCH and an atomic element apply.
- Logger servers, nameplate, Excel, and the AI assistant.
