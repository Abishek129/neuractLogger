# Logger v2: follow-up on your 2026-10-23 answers

Thank you for the quick round. This note does three things:
1. It withdraws every ask that would need changes to the logging engine, or to how existing endpoints behave.
2. It asks you to confirm that what shipped keeps v1 clients working exactly as before.
3. It lists the little that is still open.

**Our rule from now on.** We only ask for:
- answers to questions;
- docs;
- operations items, such as Keycloak details and sample data;
- small additive API fields or endpoints that change nothing existing clients see.

We won't ask for changes to the Rust engine, to how existing endpoints behave, or to what gets recorded. Where your API can't do something, v2 hides it or builds it from calls that already exist.

Item numbers follow the files you answered: `Logger-v2-backend-asks.md` (A, S, Q) and `Logger-v2-backend-asks_2.md` (F1–F29).

## 1. Withdrawn: please don't build these

| Item | Why we withdraw it |
|---|---|
| F12 Job types and triggers beyond `continuous` / `trigger` | Engine scheduling. v2 offers only what `/jobs2` accepts today |
| F13 Job event log | The engine would have to emit events |
| F14 Serial mode (RTU / ASCII) | Driver / engine |
| F19 Mark mapping rows as validated | v1 never stored this either. Check mapping and Migrate already work |
| F22 Electrical checks on the server | It would change how attach behaves. The screen keeps its own warnings |
| F25 Nameplate | A large new feature. Not needed for v2 now |
| F27 AI assistant for v2 | The assistant stays off in v2 for now |
| S2 `/tables` paging: the 422 and ordering changes | These change existing behaviour. v2 copes with today's paging. Only the question "how do we get all tables, and what is the largest `pageSize`?" remains |
| S4 Timestamps in Z | This changes an existing format. v2 reads `+05:30` correctly |
| B3 / nice-to-have: ping with an empty body | v2 already sends `{}` |
| Nice-to-haves: gzip, ETag / 304, atomic move, create-with-attach | Not needed |

You've already said no to F2, F6, F9 and S3. That's fine: v2 shows them as not available on this server.

## 2. Please confirm v1 is unaffected by what shipped

v1 is in production on these endpoints, and it must keep working exactly as before. Each item below changed existing behaviour. Please confirm it is safe for v1, or tell us if it isn't.

1. **`REAL` now decodes as float32 (F5).** Before, it fell back to one 16-bit register.
   - Does this apply to mapping rows of tables that are **already migrated and recording** at plants? If so, the values recorded before and after the change mean different things.
   - Is the new encoding applied only to new or edited rows, or to every existing row as well?
   - If existing rows changed, which plants are affected, and can existing rows keep their old encoding until someone chooses to change it?
2. **Units are now validated (F5).** `POST /schemas` and the field routes refuse a unit outside the list (`UNIT_INVALID`). Can a v1 user still type a unit that isn't in the list, as before? If not, v1's schema editor will start getting errors.
3. **Mapping import now merges by default (B5).** It used to replace every row. Does v1's import send `"mode": "replace"`? If v1 depends on replace, its imports will now behave differently.
4. **GETs now need a token (B4).** Does v1 send a token on every GET, including `/devices`, `/schemas`, `/tables` and `/jobs2`?
5. **`PUT /devices/{id}` now applies `protocol` and `params` (F7)**, and resets the device status and its saved verification. If v1's edit form sends the whole device object, saving only a name now changes the address as well. Is that what v1 sends?
6. **Migrate failures now return 4xx/500 instead of 404 (B5).** Does v1 rely on the 404?
7. **Category changes are now re-checked at both ends (A2).** Some edits that used to succeed are now refused. Does v1 offer category changes on equipment?

## 3. Still open

- **A5 / A6: sample data or a sandbox we may write to.** This is the only must-have left. Without it we can't test saving against your server. Either option works:
  - a small seeded plant on the shared instance;
  - a second instance we may write to.

  The instance with auth on that you offered would also let us test 401 and 403.
- **Keycloak for the browser** (A4), for the shared instance and each plant: a URL the browser can reach, the realm, a public PKCE client with our origins, and the issuer.
- **Q3**, the note on how the existing APIs behave, which you said would follow separately. The parts we need most:
  - what the create calls return;
  - whether `preview_sample` reads live values;
  - where a direct device's host lives;
  - what happens to tables bound to a deleted device.
- **New question:** `/jobs2/{id}/runs` lists only the old router's runs. For a `/jobs2` job, is there anything v2 can show as run history: last start and stop, last write, last error? Please answer from what exists today. We are not asking for an engine change.

## 4. Questions on what shipped (answers only, no changes)

1. **Delete with things attached.** Does deleting a panel with members detach them, and does deleting the source of a direct link remove the link? §3.2 still says 409 while attached; §8 says only a member gets `EQUIPMENT_IN_USE`.
2. **Direct links.**
   - What code does a duplicate link get?
   - Does `NO_SPARE` count a single item's capacity across bus attachments and direct links together?
   - Does `CYCLE` check across both kinds of connection?
   - Does `USE_BUS` also apply when the source is a panel?
3. **Detach and bus count.**
   - Does detach also answer `{item, owner, attached}`?
   - What does `PUT /equipment/{id}/buses/count` answer?
4. **Row delete.**
   - What does `DELETE /mappings/{tableId}/{fieldKey}` do to the recorded column?
   - What does it do on a table that a running job logs?
   - What code does an unknown key get?
5. **Migrate.**
   - What are the `MIGRATE_FAILED` reasons?
   - What does migrate do on a table that is already migrated?
6. **Job edit.** Does a PATCH without `triggers` leave them unchanged? What must `triggers` hold for a trigger job?
7. **Device edit.** On `PUT /devices/{id}`, does re-sending an unchanged `protocol` or `params` count as a change, disconnecting the device and clearing its verification?
8. **Units (a data item, not code).** Plants use `ms`, `mA`, `PF` and `kVAR`. Could they be added to the units list if they're missing? Is unit matching case-sensitive (`kVAR` vs `kvar`)?

## 5. Small doc updates, when convenient

The parts below still read as before this round:
- **§3.2:** delete, `used`, and the connections list (no position, direct links, versions);
- **§4:** device PUT and verification;
- **§5.1 and §5.3:** schema GET, rename and description; job GET, PATCH and resume;
- **§6:** verification persistence.

The doc also says `/jobs2` has no run records, yet `/jobs2/{id}/runs` answers with the old router's runs.

## 6. Later, only if each is API-only and changes nothing existing

v2 doesn't depend on any of these. Please treat them as optional:
- F11 dates;
- F15 store the last ping result;
- F16 the OPC UA device body (a question);
- F17 duplicate equipment;
- F18 supply role;
- F20 table list import / export;
- F21 copy a schema;
- F23 replace equipment;
- F24 plant rule settings;
- F26 Excel;
- F28 `/capabilities` and `/me`;
- F29 Idempotency-Key.
