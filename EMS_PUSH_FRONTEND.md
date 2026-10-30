# Push to EMS: frontend guide

One action sends the whole EMS map from the Electrical Elements screen to the EMS app's sidebar. The EMS sidebar is **replaced**: anything not in the push leaves it. Because of that, the UI always shows a preview first and writes only after the user confirms.

Backend endpoint: `POST /equipment/push/ems`.

## 1. The flow

1. The user clicks **Push to EMS**. Call the preview: `POST /equipment/push/ems` (no `commit`). Nothing is written anywhere.
2. Show the preview dialog (§4): what will be created, changed, hidden or retired in the EMS, what was left out (`skipped`), and any errors.
3. If `success` is `true`, enable **Confirm**. It calls `POST /equipment/push/ems?commit=true`.
4. Show the result. If `success` is `false`, nothing was written: show the errors.

The commit rebuilds the body from the map as it is at that moment. If the map was edited after the preview, run the preview again before confirming.

## 2. Request

```
POST /equipment/push/ems                preview
POST /equipment/push/ems?commit=true    write (only if the EMS finds no errors at all)
Authorization: Bearer <token>
```

- **No request body.** The backend reads the map itself.
- **Role:** `logger-write`. Show the action only to users who can edit elements, as for the other write actions.
- **Timeout:** a push can take much longer than the app's default `api.timeoutMs` (15 s): the backend waits up to 120 s for the EMS. Give this call its own timeout of about 130 s.
- Disable the button while a request is in flight. Never retry a commit automatically.

## 3. Response

`200` when the EMS accepts the push, `400` when it reports errors. Both have the same keys:

```json
{
  "success": true,
  "committed": false,
  "skipped": [
    {"element": "Untyped Board", "reason": "no type"},
    {"table": "gic_01_n5_SPARE_2", "element": "MLDB-1", "reason": "table not migrated"}
  ],
  "request": {
    "schemas": [{"code": "sch_EM6400_NG+", "version": 1, "logger_id": "sch_1788521250508", "timestamp_column": "timestamp_utc", "fields": ["…"]}],
    "categories": [
      {"label": "PCC Panels",
       "panels": [{"name": "PCC-1", "panel_kind": "pcc_panel", "nameplate": {"nominal_voltage_v": 415.0},
                   "incoming": [{"table_name": "gic_01_n2_TF_1_INCOMER", "schema": "sch_EM6400_NG+"}],
                   "outgoing": [{"table_name": "gic_01_n3_OG_MLDB_1", "schema": "sch_EM6400_NG+"}],
                   "spare":    [{"table_name": "gic_01_n4_SPARE_1", "schema": "sch_EM6400_NG+"}]}],
       "meters": []}
    ]
  },
  "ems": {
    "ok": true,
    "committed": false,
    "summary": {"schema": {"create": 2}, "category": {"unchanged": 1, "create": 2, "update": 1, "hide": 6},
                "panel": {"create": 4}, "mfm": {"create": 5}, "membership": {"create": 5}},
    "errors": [],
    "warnings": [],
    "changes": [
      {"entity": "category", "action": "create", "name": "LT Panels", "path": "categories[1]", "detail": ""},
      {"entity": "category", "action": "hide", "name": "AMF Panels", "path": "", "detail": "not in the push"},
      {"entity": "panel", "action": "create", "name": "PCC-1", "path": "categories[3].panels[0]",
       "detail": "under PCC Panels; nominal_voltage_v: — → 415.0"},
      {"entity": "membership", "action": "create", "name": "TF_1_INCOMER → PCC-1 (incoming)",
       "path": "categories[3].panels[0].incoming[0]", "detail": ""}
    ],
    "nav": {"count": 4, "leaf_count": 6, "tree": ["…the EMS sidebar exactly as it will look…"]}
  }
}
```

The `400` body adds `detail: "EMS_PUSH_INVALID: N error(s); nothing was saved"`, with `success: false`. When the EMS finds errors, `ems.summary` and `ems.changes` are empty and there is no `ems.nav`:

```json
{
  "detail": "EMS_PUSH_INVALID: 1 error(s); nothing was saved",
  "success": false,
  "committed": false,
  "skipped": [],
  "request": {"…": "…"},
  "ems": {
    "ok": false, "committed": false, "summary": {}, "warnings": [], "changes": [],
    "errors": [{"path": "categories[0].panels[0].outgoing[0]",
                "message": "table \"gic_99_missing\" is not a migrated LoggerFast table"}]
  }
}
```

### Fields

| Key | Meaning |
|---|---|
| `success` | The EMS accepted the push. Same as `ems.ok` |
| `committed` | `true` only after a successful `?commit=true` |
| `skipped` | Map items that were **not sent**, with the reason (§5). Can be non-empty when `success` is `true` |
| `request` | The exact body sent to the EMS. `ems.errors[].path` and `ems.changes[].path` point into it |
| `ems.summary` | Counts per entity and action, including `unchanged` (unchanged rows appear only here) |
| `ems.changes` | One row per real change: `{entity, action, name, path, detail}` |
| `ems.errors` | `{path, message}`. Every error is reported at once |
| `ems.warnings` | Same shape as `errors`; don't block on them |
| `ems.nav` | The EMS sidebar after the push, in the shape of the EMS's `GET /api/ems/`. Only present when `ems.ok` is `true` |

`changes[].entity` is one of: `schema`, `category`, `panel`, `membership`, `mfm`, `group`.
`changes[].action` is one of: `create`, `update`, `reactivate`, `retire`, `hide`, `unfile`, `delete`.

## 4. The preview dialog

**Headline from `ems.summary`.** For example: "4 panels and 5 meters will be created; 6 sidebar categories will be hidden". Ignore `unchanged`, except for an "everything is up to date" message when it is the only action.

**Removals, highlighted.** These rows of `ems.changes` remove something from the EMS sidebar, so show them in a warning colour:

| action | What the user should read |
|---|---|
| `hide` (category) | The category disappears from the EMS sidebar. No element in the map has its type |
| `retire` (panel) | The panel leaves the EMS sidebar. It isn't in the map any more |
| `delete` (membership) | The meter is no longer listed under that panel |
| `unfile` (mfm) | The meter is no longer listed directly under a category |
| `retire` (group) | An old grouping is removed from the sidebar |

Nothing is deleted in the EMS for good: pushing the item again brings it back.

**Errors.** Each `path` is relative to `request`, so it can be turned into a name:

```ts
const atPath = (root: unknown, path: string): any =>
  (path.match(/[^.[\]]+/g) ?? []).reduce<any>((node, key) => node?.[key], root);

// "categories[0].panels[0].outgoing[0]" -> {table_name: "gic_99_missing", …}
const item = atPath(res.request, err.path);
const label = item?.name ?? item?.table_name ?? item?.label ?? item?.code ?? "the push";
```

An error with `path: ""` is about the whole push (see §6).

**Skipped.** List them under a "Not sent" heading (§5). They don't block the push.

**Optional tree preview.** `ems.nav.tree` is the EMS sidebar itself: categories → panels → Overview / Incoming / Outgoing / Spare → meters, each node with a `label`.

## 5. Skipped items

Two shapes: `{element, reason}` (a whole element) and `{table, element, reason}` (one MFM of that element).

| reason | What the user can do |
|---|---|
| `no type` | Give the element a type. The type decides its EMS sidebar category |
| `spare (not on the map)` | Nothing. Spare elements are not on the map by design |
| `table not migrated` | Migrate the logger table, or remove the MFM |
| `table has no device` | Bind the table to a device |
| `its device has several migrated tables (A, B)` | The EMS finds a meter through its device, so the device must have exactly one migrated table. Delete or un-migrate the other table |

## 6. Errors from the backend itself

These come before or instead of an EMS report. Their `detail` is a string `"CODE: message"`: the code is the part before the first `:`.

| Status | Code | Show the user |
|---|---|---|
| 400 | `NOTHING_TO_PUSH` | "Nothing to send: no EMS element with a type has a panel or a meter." |
| 503 | `EMS_NOT_CONFIGURED` | "The EMS connection isn't set up. Contact an administrator." |
| 502 | `EMS_AUTH_FAILED` | "The EMS refused LoggerFast's login. Contact an administrator." |
| 502 | `EMS_UNREACHABLE` | "The EMS isn't responding. Try again later." |
| 502 | `EMS_BAD_RESPONSE` | "The EMS gave an unexpected answer. Try again later." |
| 401 | `detail.error`: `PERMISSION_DENIED` / `TOKEN_EXPIRED` | The usual re-login handling. Here `detail` is an object `{success, error, message}` |
| 403 | `detail.error`: `INSUFFICIENT_ROLE` | "You need write access to push to the EMS." |

One EMS error (`400`, `path: ""`) also needs an administrator: *"Cannot check table names against LoggerFast: …"*. The EMS couldn't read LoggerFast's devices and tables. That's a server setting, not something the user can fix in the map.

## 7. How the map becomes the EMS sidebar

Use this for help text or a tooltip on the button.

| In the map | In the EMS sidebar |
|---|---|
| **Category** (EMS / Source / BMS) | Only **EMS** elements are sent |
| **Type** | The sidebar category, named with the type in the plural: "HT Panel" → **HT Panels**, "PCC Panel" → **PCC Panels**. If the EMS already has a category with that name, it is reused |
| **Kind**: distribution | A panel with **Incoming / Outgoing / Spare** meters, from its buses: incomer slots → Incoming, outgoer slots → Outgoing, spares → Spare |
| **Kind**: single | Its MFMs are listed directly under its type's category |
| A feed between two panels | Its MFM shows under both: Outgoing of the feeding panel and Incoming of the fed panel (unless that panel has its own MFM for the feed) |
| **Zone** | Not used by the EMS sidebar |
| MFM (logger table) | An EMS meter. A new meter is named after its device |

Panel order follows the type order, then the name. Types with nothing to show don't appear.

## 8. Types

```ts
type Skipped =
  | { element: string; reason: string }
  | { table: string; element: string; reason: string };

interface EmsChange {
  entity: "schema" | "category" | "panel" | "membership" | "mfm" | "group";
  action: "create" | "update" | "reactivate" | "retire" | "hide" | "unfile" | "delete";
  name: string;
  path: string;    // into `request`; "" = not tied to one item
  detail: string;  // e.g. "nominal_voltage_v: — → 415.0"
}

interface EmsIssue { path: string; message: string }

interface EmsPushResponse {
  success: boolean;
  committed: boolean;
  skipped: Skipped[];
  request: { schemas: unknown[]; categories: unknown[] };
  ems: {
    ok: boolean;
    committed: boolean;
    summary: Record<string, Record<string, number>>;
    errors: EmsIssue[];
    warnings: EmsIssue[];
    changes: EmsChange[];
    nav?: { count: number; tree: unknown[] } & Record<string, unknown>;
  };
  detail?: string; // on 400: "EMS_PUSH_INVALID: N error(s); nothing was saved"
}
```

## 9. Good to know

- **Last commit wins.** There is no locking between two people pushing.
- **Sizes.** `request` and `ems.nav` grow with the plant (around 100 KB for about 100 meters). Keep them only while the dialog is open, and don't log them.
- **Re-pushing an unchanged map is safe.** Everything comes back `unchanged`.
- **After a commit, the EMS app** shows the new sidebar on its next load. Pages already open there keep their old meter connections until they are reopened.
