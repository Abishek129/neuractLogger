# LoggerFast E2E test suite (J1)

Automated pytest suite for the agent API and the full acquisition stack.

## Layout

| File | Tier | What it covers |
|---|---|---|
| `conftest.py` | — | env bootstrap, throwaway DBs, auth override, cleaners, API helper |
| `test_workflow_api.py` | 1 | full happy chain: schema → target → device → tables → migrate → mappings → jobs2 |
| `test_rbac.py` | 1 | auth matrix: 401 / 403 / 200, public GETs (pinned current behavior) |
| `test_validation_errors.py` | 1 | error codes: NO_MAPPED_COLUMNS, TABLE_NOT_FOUND, FIELD_*, FORMULA_*, NO_TABLE_IDS |
| `test_pending_fixes.py` | 1 | xfail regression tests for verified-open findings (DP1, DP5, C2-remainder, unguarded DELETE /devices) |
| `test_derived_params_oracle.py` | 1 | runs `validate_derived_params.py` (74-case corpus) as a subprocess oracle |
| `test_fullstack_e2e.py` | 2 (`@pytest.mark.e2e`) | Modbus simulator + prebuilt Rust engine: real acquisition + derived-column verification + stop plateau |
| `bin/neuract-job-runner` | 2 | prebuilt working-tree engine binary (gitignored, ~14 MB) |

## Running

```bash
cd /home/rohith/backend_LOS/LoggerFast/agent

# Tier 1 — API-level, fast (~seconds), no Rust/simulator:
python -m pytest tests/ -q

# Tier 2 — full stack (starts the Modbus simulator + Rust engine):
python -m pytest tests/ -q -m e2e
```

`pytest.ini` sets `addopts = -m "not e2e"`, so the plain invocation runs
tier 1 only; an explicit `-m e2e` on the command line overrides it.

## Prerequisites

- Local PostgreSQL on `localhost:5432`, user `postgres`, **no password**.
  The suite creates and drops two throwaway databases per session:
  `meta_test_e2e` (App/metadata DB, also the engine's bench-metrics DB) and
  `target_test_e2e` (user/target DB with the `neuract` schema).
  No other database is ever touched.
- Python 3.11 with `pytest`, `pytest-timeout`, `httpx`, `psycopg2`,
  `fastapi`/`sqlalchemy` (all already installed system-wide here).
- Tier 2 additionally needs the prebuilt engine at `tests/bin/neuract-job-runner`
  (stashed by the hardening campaign; **do not** `cargo build` from tests —
  the Rust sources may be mid-edit by a parallel task).

## How the auth override works

The product has no auth bypass. `permissions.get_claims` normally verifies a
Keycloak RS256 JWT via JWKS. The suite installs

```python
app.dependency_overrides[permissions.get_claims] = _override_get_claims
```

where the override returns fake claims built from a role mode
(`admin` / `write` / `read` / `none`) stored in `conftest._AUTH` — the
`auth_role` fixture switches modes per test, and also mirrors the real
dependency's side effect of setting `request.state.auth` (jobs2 start reads
it). Every role-guard dependency (`require_logger_write`,
`require_safe_or_write`, `require_admin`, ...) calls `Depends(get_claims)`,
so the single override unlocks/locks the whole API consistently. The
`no_auth` fixture *removes* the override for a test so guarded endpoints
exercise the real 401 path (no token sent → 401 before any JWKS fetch).

## Isolation rules baked into conftest

- All env vars (`APP_DB_URL`, `LOGGER_DISABLE_BOOT_JOBS=1`,
  `LOGGER_ENABLE_AI=0`, dead-port `KC_URL`/`REDIS_URL`,
  empty `KC_ADMIN_CLIENT_SECRET`) are set at conftest **module level**,
  before the app module is imported — `create_app()` runs at import time.
- One meta DB per pytest process: `appdb._ENGINE`, `Store._inst` and
  `tables._engine_cache` are process-global; never re-point `APP_DB_URL`
  inside a run.
- Between tests an autouse fixture truncates the `app_*` state tables
  (except `app_protocol_types`, which is seeded only by `appdb.init()`),
  drops the target `neuract` schema, clears the Store's in-memory `_mappings`
  cache and calls `Store.instance().load_from_app_db()` to resync memory.

## Known quirks the tests intentionally pin

- `POST /tables/migrate` takes `{"ids": [...]}` — the `tableIds` key shown in
  `GETTING_STARTED.md` is wrong (finding E2E3) and yields `NO_TABLE_IDS`.
- `GET /schemas`, `/tables`, `/devices`, `/jobs2` are public today (no token);
  `GET /storage/targets` is not. Pinned in `test_rbac.py`, flagged as under
  review.
- Device create runs a live probe; with no listener it returns
  `success: false` + status `degraded` but still persists the device.
- `test_pending_fixes.py` asserts the *correct* behavior for open findings and
  is `xfail(strict=False)`: when a fix lands the test XPASSes — then remove
  the marker to lock the fix in.
