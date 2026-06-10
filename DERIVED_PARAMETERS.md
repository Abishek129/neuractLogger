# Derived Parameters

Derived parameters are formula-based fields computed at runtime from device-read values. They allow users to define calculated metrics (e.g., apparent power from active and reactive power) without additional hardware or external computation.

## How It Works

```
Schema (formula definition)
    |
    v
Table Migration (writes formula to device_mappings)
    |
    v
Rust Job Runner (reads formula, evaluates with meval, writes result to DB)
```

### Step 1: Define Formula in Schema

Formulas are defined as part of schema fields. A derived field has a `formula` property containing a math expression that references other field keys in the same schema.

**Supported operations:** `+`, `-`, `*`, `/`, `%` (remainder), `^` (power), unary minus, parentheses
**Supported functions** (exactly the meval 0.2 builtins — verified against the vendored crate):
`sqrt`, `exp`, `ln`, `abs`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`, `asinh`, `acosh`, `atanh`, `floor`, `ceil`, `round`, `signum`, `atan2(y, x)`, `min(a, ...)`, `max(a, ...)`
**Built-in constants:** `pi` and `e` are predefined variables and always usable in formulas. A schema field named `pi` or `e` shadows the constant at runtime.

> **Note:** `pow`, `log` and `log2` are NOT meval builtins and are rejected at
> validation with `FORMULA_UNKNOWN_FUNCTION` (they previously validated but
> produced NULL on every row). Use `x^2` instead of `pow(x, 2)`.
> Formula syntax is fully parse-checked at config time
> (`FORMULA_SYNTAX_INVALID`); an identifier is a function call only when
> directly followed by `(` — a bare identifier is always a variable, even if
> it collides with a function name.

Example: A schema with 2 device fields and 1 derived field:

```json
{
  "name": "power_meter",
  "fields": [
    { "key": "active_power_total_kw", "type": "float32" },
    { "key": "reactive_power_total_kvar", "type": "float32" },
    {
      "key": "apparent_power_check",
      "type": "float64",
      "formula": "sqrt(active_power_total_kw^2 + reactive_power_total_kvar^2)"
    }
  ]
}
```

### Step 2: Table Migration

When `POST /tables/migrate` is called, the migration process:

1. Creates/updates the physical table column for the derived field
2. Writes the formula into `neuract.device_mappings` with:
   - `protocol` = `"derived"`
   - `address` = the formula string
   - `scale` = `eval_order` (dependency ordering)
   - `device_id` = `NULL`

### Step 3: Rust Job Runner Evaluation

The Rust job runner (`neuract-job-runner`) picks up derived fields automatically:

1. Loads all mappings from `neuract.device_mappings`
2. Partitions rows into device mappings (`modbus`, `opcua`, `mqtt`) and derived mappings (`derived`)
3. Reads device values (Phase 1)
4. Evaluates derived formulas using `meval` in dependency order (Phase 1.5)
5. Writes all values (device + derived) to the target database (Phase 2)

### Evaluation Failure Semantics (engine)

Any derived result that is **NaN or ±Infinity — or any evaluation error — is
written as SQL `NULL`** and is *not* fed into the meval context. Downstream
formulas referencing the failed field therefore see an unknown variable and
also evaluate to `NULL` (a deliberate, consistent NULL-cascade; Infinity is
never stored). Failures are surfaced via a rate-limited engine warning plus a
row in the error CSV.

### Dependency Ordering

Derived fields can reference other derived fields. The system uses topological sort (Kahn's algorithm) to determine evaluation order. Circular dependencies are rejected at schema creation time — **including self-references** (`acc = acc + delta` is a 1-node cycle and is rejected with `FORMULA_SELF_REFERENCE`; accumulator-style formulas are not supported).

`eval_order` is recomputed and persisted for **all** derived fields of a schema on every create/add/patch/import, and recomputed again from the formulas at migrate time (stored values are never trusted), so stale orders self-heal.

Example:
```json
{
  "fields": [
    { "key": "voltage", "type": "float32" },
    { "key": "current", "type": "float32" },
    { "key": "power", "formula": "voltage * current" },
    { "key": "power_kw", "formula": "power / 1000" }
  ]
}
```

`power` gets `eval_order=0`, `power_kw` gets `eval_order=1`.

## API Endpoints for Frontend

### Schemas (formula definition)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/schemas` | List all schemas |
| `POST` | `/schemas` | Create schema with fields (including derived) |
| `POST` | `/schemas/{schema_id}/fields` | Add a single field (regular or derived) |
| `DELETE` | `/schemas/{schema_id}/fields/{field_key}` | Delete a field |
| `DELETE` | `/schemas/{schema_id}` | Delete entire schema |

#### Create Schema with Derived Field

```
POST /schemas
```

```json
{
  "name": "mfm_power_meter",
  "fields": [
    { "key": "active_power_total_kw", "type": "float32", "unit": "kW" },
    { "key": "reactive_power_total_kvar", "type": "float32", "unit": "kVAR" },
    {
      "key": "apparent_power_kva",
      "type": "float64",
      "formula": "sqrt(active_power_total_kw^2 + reactive_power_total_kvar^2)",
      "unit": "kVA",
      "desc": "Computed apparent power"
    }
  ]
}
```

**Response:**

```json
{
  "success": true,
  "message": "schema_created",
  "item": {
    "id": "sch_...",
    "name": "mfm_power_meter",
    "fields": [
      { "key": "active_power_total_kw", "type": "float32", "unit": "kW" },
      { "key": "reactive_power_total_kvar", "type": "float32", "unit": "kVAR" },
      {
        "key": "apparent_power_kva",
        "type": "float64",
        "formula": "sqrt(active_power_total_kw^2 + reactive_power_total_kvar^2)",
        "unit": "kVA",
        "desc": "Computed apparent power",
        "eval_order": 0
      }
    ]
  }
}
```

**Error responses:**

| Error Code | Meaning |
|------------|---------|
| `FORMULA_UNKNOWN_VARS:field_key:var1,var2` | Formula references variables not in the schema (pi/e excepted) |
| `FORMULA_CIRCULAR_DEPENDENCY:field1,field2` | Circular dependency between derived fields |
| `FORMULA_SELF_REFERENCE:field_key` | Formula references its own field key (1-node cycle) |
| `FORMULA_SYNTAX_INVALID:field_key:detail` | Formula does not parse under the meval grammar |
| `FORMULA_UNKNOWN_FUNCTION:field_key:name` | Call of a function that is not a meval builtin (e.g. `pow`, `log`) |
| `FORMULA_NON_NUMERIC_FIELD:field_key:var` | Formula references a field with a non-numeric declared type (e.g. text) |
| `FIELD_KEY_INVALID:key` | Invalid field key format (must match `^[A-Za-z_][A-Za-z0-9_]*$`, max 63 chars) |
| `FIELD_KEY_DUPLICATE:key` | Duplicate field key |
| `FIELD_KEY_EXISTS:key` (HTTP 409) | `POST /schemas/{id}/fields` with an existing key (use PATCH to edit) |
| `FIELD_TYPE_INVALID:type` | Invalid field type; derived fields accept only `float64` (default) or `float32` |
| `FIELD_REFERENCED_BY_FORMULA:key:deps` | DELETE of a field that other formulas still reference |

The exact same validation pipeline runs on `POST /schemas`, `POST/PATCH /schemas/{id}/fields` and `POST /schemas/import` (imports recompute `eval_order` and reject any invalid item).

#### Add Derived Field to Existing Schema

```
POST /schemas/{schema_id}/fields
```

```json
{
  "key": "efficiency_pct",
  "formula": "active_power_total_kw / apparent_power_kva * 100",
  "unit": "%"
}
```

The `type` defaults to `float64` for derived fields.

### Tables (migration triggers formula persistence)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/tables/migrate` | Migrate tables (creates columns + writes derived mappings) |

When migrating a table whose schema has derived fields, the migration automatically populates `neuract.device_mappings` with the formula rows. No extra API call is needed. The derived row set is replaced atomically on every migrate (stale rows from deleted/renamed derived fields are removed), and `eval_order` is recomputed from the formulas.

**Lifecycle propagation:** adding, editing or deleting a derived field via the
schema endpoints immediately updates `neuract.device_mappings` for every
*already-migrated* table bound to that schema (no re-migrate needed). The Rust
engine, however, **reloads mappings only on job (re)start** — restart the job
to pick up formula changes.

### Mappings (derived fields are protected)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/mappings/{table_id}` | Get all mappings (includes derived rows) |
| `POST` | `/mappings/{table_id}` | Upsert mappings (derived fields are stripped) |
| `POST` | `/mappings/{table_id}/bulk_apply` | Bulk apply (derived fields are stripped) |
| `POST` | `/mappings/{table_id}/validate` | Validate (derived fields excluded from required check) |

Derived fields are **read-only** in the mappings API. Any attempt to manually map a derived field via `POST /mappings/{table_id}`, `bulk_apply` or `import` is silently ignored. `POST /mappings/{table_id}/import` replaces only manual rows — `protocol='derived'` rows are preserved (they are owned by the schema/migrate pipeline). All mapping field keys must match `^[A-Za-z_][A-Za-z0-9_]*$` (max 63 chars) or the request is rejected with `FIELD_KEY_INVALID`.

### Jobs (start/stop execution)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/jobs2` | List all jobs |
| `POST` | `/jobs2` | Create a job |
| `POST` | `/jobs2/{job_id}/start` | Start a job (sets status to `running`) |
| `POST` | `/jobs2/{job_id}/stop` | Stop a job |
| `POST` | `/jobs2/{job_id}/dry_run` | Test-read device values (does not evaluate derived fields) |

## Frontend Integration Guide

### Displaying Derived Fields

When listing schema fields, check for the `formula` property to distinguish derived fields from regular device-mapped fields:

```js
const isDerived = (field) => !!field.formula;
```

Derived fields should be:
- Shown with a visual indicator (e.g., "computed" badge)
- Excluded from the mapping UI (they cannot be manually mapped)
- Shown as read-only in mapping views

### Creating a Derived Field (UI Flow)

1. User opens schema editor
2. User adds a new field and toggles "Derived/Formula" mode
3. User types a formula referencing existing field keys
4. Frontend calls `POST /schemas/{schema_id}/fields` with the `formula` property
5. If validation fails, show the error (unknown vars, circular dependency)
6. After adding, call `POST /tables/migrate` to persist the formula to the target DB

### Validation

The backend validates:
- Formula syntax (full parse against the meval grammar) and function names/arity
- All variables in the formula must be existing field keys in the schema (or the builtin constants `pi`/`e`)
- Referenced fields must have a numeric declared type
- No circular dependencies between derived fields, including self-references
- Field keys must match `^[A-Za-z_][A-Za-z0-9_]*$` and be at most 63 characters
- Derived field type must be `float64` (default) or `float32`

The frontend can pre-validate by checking that all identifiers in the formula exist in the current schema's field keys.

## Database Storage

### `neuract.device_mappings` table

Derived fields are stored alongside device mappings:

| Column | Device Field | Derived Field |
|--------|-------------|---------------|
| `table_name` | table name | table name |
| `field_key` | field key | field key |
| `protocol` | `modbus` / `opcua` / `mqtt` | `derived` |
| `address` | register address / node ID | formula string |
| `data_type` | `float` / `int` | `float` |
| `scale` | scaling factor | `eval_order` (int) |
| `encoding` | `float32` / `uint16` / etc. | `float64` |
| `device_id` | device UUID | `NULL` |

### Target Table

Derived field values are written as regular columns. The column type in the target table is determined by the DDL migration (typically `TEXT` due to the generic migration logic).
