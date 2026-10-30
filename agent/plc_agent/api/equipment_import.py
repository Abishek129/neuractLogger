"""EMS elements from a spreadsheet (POST /equipment/import/ems).

Workbook (.xlsx; a .csv is the Elements sheet alone). Header names are matched
case-insensitively; spaces and underscores are interchangeable.

* Elements: name*, kind (single | distribution; required for a new element),
  type (type name or id), zone (zone name or id), max incomers, max outgoers
  (single elements), incoming types, outgoing types (comma-separated; a
  panel's lists apply to every one of its buses), spare (yes/no),
  description, and one column per nameplate field of the row's type (its
  label or id, e.g. "Primary voltage" = "33 kV").
* Buses: panel*, bus*, incomers, outgoers, incoming types, outgoing types
  (comma-separated type names or ids).
* Connections: panel*, bus (required for a distribution panel; blank for a
  direct link from a single element), role (incomer | outgoer), element*,
  position (1 = first).
* Meters (after the relations exist): table* (the logger table that is the
  MFM; "mfm" is read as the same column, as in v1), element* (a single
  element: the MFM sits on it; or a distribution panel), bus (panels), role
  (incoming | outgoing | spare; v1's Incomings / Outgoings / Spare also
  read), measures (the attached element it measures: required for incoming;
  blank on outgoing = a spare), schema (optional: must be the table's).

Every element is created in the EMS category. Rows are upserts: an existing
element name / bus / connection is updated from the sheet; blank cells leave
the stored value alone; nothing is ever deleted.

All or nothing: the whole workbook runs in one transaction through the same
service functions as the API (same rules, same errors), one savepoint per
row. A dry run, or any row error, rolls everything back; the report lists
every row either way.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from . import equipment as eq
from .appdb import _engine, _fetchall, _fetchone

CATEGORY = "ems"
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
_SHEETS = ("elements", "buses", "connections", "meters")
_METER_ROLES = {
    "incoming": "incomer", "incomings": "incomer", "incomer": "incomer",
    "outgoing": "outgoer", "outgoings": "outgoer", "outgoer": "outgoer",
    "spare": "spare", "spares": "spare",
}
_ELEMENT_COLUMNS = {"name", "kind", "type", "zone", "max incomers", "max outgoers", "incoming types",
                    "outgoing types", "spare", "description"}
_QTY = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([^\d\s].*?)?\s*$")
_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}

Row = Tuple[int, Dict[str, Any]]  # (spreadsheet row number, {header: value})


class ImportError_(Exception):
    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.status = status
        self.detail = f"{code}: {message}" if message else code


def _norm(h: Any) -> str:
    return " ".join(str(h or "").replace("_", " ").split()).lower()


def _cell(v: Any) -> Optional[str]:
    """Cell as trimmed text; None when empty. Whole floats lose their '.0'."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


# ---------- Reading ----------
def _rows(header: List[Any], body) -> List[Row]:
    keys = [_norm(h) for h in header]
    out: List[Row] = []
    for n, raw in body:
        vals = {k: _cell(v) for k, v in zip(keys, raw) if k}
        if any(v is not None for v in vals.values()):
            out.append((n, vals))
        if len(out) > MAX_ROWS:
            raise ImportError_(400, "TOO_MANY_ROWS", f"at most {MAX_ROWS} rows per sheet")
    return out


def read_workbook(filename: str, data: bytes) -> Dict[str, List[Row]]:
    if len(data) > MAX_BYTES:
        raise ImportError_(413, "FILE_TOO_LARGE", f"at most {MAX_BYTES // (1024 * 1024)} MB")
    name = (filename or "").lower()
    if name.endswith(".csv"):
        try:
            text_ = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ImportError_(400, "FILE_INVALID", "a .csv must be UTF-8")
        lines = list(csv.reader(io.StringIO(text_)))
        if not lines:
            raise ImportError_(400, "SHEET_EMPTY", "Elements")
        return {"elements": _rows(lines[0], ((i + 2, r) for i, r in enumerate(lines[1:])))}
    if not (name.endswith(".xlsx") or data[:2] == b"PK"):
        raise ImportError_(400, "FILE_TYPE", "upload a .xlsx or .csv file")
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ImportError_(400, "FILE_INVALID", f"not a readable .xlsx ({type(e).__name__})")
    out: Dict[str, List[Row]] = {}
    for ws in wb.worksheets:
        key = _norm(ws.title)
        if key not in _SHEETS:
            continue  # e.g. the template's "Types" reference sheet
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if header is None:
            continue
        out[key] = _rows(list(header), ((i + 2, list(r)) for i, r in enumerate(it)))
    wb.close()
    if not out:
        raise ImportError_(400, "SHEETS_MISSING", "the workbook needs an Elements, Buses, Connections or Meters sheet")
    return out


# ---------- Lookups (inside the import transaction) ----------
def _element(c, name: str) -> Optional[Dict[str, Any]]:
    return _fetchone(c, "SELECT * FROM app_equipment WHERE lower(name)=lower(:n)", {"n": name})


def _need_element(c, name: Optional[str], col: str) -> Dict[str, Any]:
    if not name:
        raise eq._bad(f"{col.upper()}_REQUIRED")
    row = _element(c, name)
    if not row:
        raise eq._missing("ELEMENT_NOT_FOUND", name)
    if row["category_id"] != CATEGORY:
        raise eq._bad("ELEMENT_NOT_EMS", f"{name} is in category {row['category_id']}")
    return row


def _type_id(c, ref: str) -> str:
    row = _fetchone(c, "SELECT id FROM app_equipment_type WHERE id=:r OR lower(name)=lower(:r)", {"r": ref})
    if not row:
        raise eq._missing("TYPE_NOT_FOUND", ref)
    return row["id"]


def _zone_id(c, ref: str) -> str:
    row = _fetchone(c, "SELECT id FROM app_equipment_zone WHERE id=:r OR lower(name)=lower(:r)", {"r": ref})
    if not row:
        raise eq._missing("ZONE_NOT_FOUND", ref)
    return row["id"]


def _type_ids(c, cell: Optional[str]) -> Optional[List[str]]:
    if cell is None:
        return None
    return [_type_id(c, part.strip()) for part in cell.split(",") if part.strip()]


def _int(cell: Optional[str], col: str) -> Optional[int]:
    if cell is None:
        return None
    try:
        return int(float(cell))
    except ValueError:
        raise eq._bad(f"{col.upper().replace(' ', '_')}_INVALID", f"{col} must be a whole number")


def _bool(cell: Optional[str], col: str) -> Optional[bool]:
    if cell is None:
        return None
    v = cell.lower()
    if v in _YES:
        return True
    if v in _NO:
        return False
    raise eq._bad(f"{col.upper()}_INVALID", f"{col} must be yes or no")


def _field_value(field: Dict[str, Any], cell: str) -> Dict[str, Any]:
    if field.get("kind") == "quantity":
        m = _QTY.match(cell)
        if not m:
            raise eq._bad("FIELD_INVALID", f"{field['label']}: '{cell}' is not a number (e.g. '33 kV')")
        return {"value": m.group(1), "unit": (m.group(2) or "").strip() or None}
    return {"value": cell, "unit": None}


# ---------- Sheets ----------
def _element_row(c, vals: Dict[str, Any], seen: Dict[str, int], created_panels: set, panel_rules: Dict[str, Dict[str, Any]]) -> str:
    name = vals.get("name")
    if not name:
        raise eq._bad("NAME_REQUIRED")
    key = name.lower()
    if key in seen:
        raise eq._bad("DUPLICATE_IN_SHEET", f"{name} is also on row {seen[key]}")
    existing = _element(c, name)
    payload: Dict[str, Any] = {}
    kind = vals.get("kind")
    if kind is not None:
        payload["kind"] = kind.lower()
    if vals.get("type") is not None:
        payload["typeId"] = _type_id(c, vals["type"])
    if vals.get("zone") is not None:
        payload["zoneId"] = _zone_id(c, vals["zone"])
    rules = {}
    for col, key_ in (("incoming types", "incomingTypes"), ("outgoing types", "outgoingTypes")):
        ids = _type_ids(c, vals.get(col))
        if ids is not None:
            rules[key_] = ids
    type_id = payload.get("typeId", existing.get("type_id") if existing else None)
    fields = eq._fields(_fetchone(c, "SELECT config_json FROM app_equipment_type WHERE id=:t", {"t": type_id})) if type_id else []
    by_col = {}
    for f in fields:
        by_col[_norm(f["label"])] = f
        by_col[_norm(f["id"])] = f
    values = {}
    for col, cell in vals.items():
        if col in _ELEMENT_COLUMNS or cell is None:
            continue
        f = by_col.get(col)
        if not f:
            raise eq._bad("FIELD_UNKNOWN", f"column '{col}' is not a field of this element's type")
        values[f["id"]] = _field_value(f, cell)
    if values:
        payload["values"] = values
    for col, key_ in (("max incomers", "maxIncomers"), ("max outgoers", "maxOutgoers")):
        n = _int(vals.get(col), col)
        if n is not None:
            payload[key_] = n
    spare = _bool(vals.get("spare"), "spare")
    if spare is not None:
        payload["spare"] = spare
    if vals.get("description") is not None:
        payload["description"] = vals["description"]
    if ("maxIncomers" in payload or "maxOutgoers" in payload) and (payload.get("kind") or (existing or {}).get("kind")) == "distribution":
        raise eq._bad("LIMITS_ON_DISTRIBUTION", "a distribution panel's limits are per bus: use the Buses sheet")

    kind_ = payload.get("kind") or (existing or {}).get("kind")
    if kind_ == "single":
        payload.update(rules)  # a single element's own node rules
    if existing:
        if existing["category_id"] != CATEGORY:
            raise eq._bad("ELEMENT_NOT_EMS", f"{name} is in category {existing['category_id']}")
        if not payload and not rules:
            return "unchanged"
        if payload:
            eq.update_equipment(existing["id"], payload)
        eq_id = existing["id"]
        status = "updated"
    else:
        if "kind" not in payload:
            raise eq._bad("KIND_REQUIRED", "a new element needs kind: single or distribution")
        item = eq.create_equipment({"name": name, "categoryId": CATEGORY, **payload})
        eq_id = item["id"]
        if item["kind"] == "distribution":
            created_panels.add(eq_id)
        status = "created"
    if kind_ == "distribution" and rules:
        # Panel-level allowed types: every bus now, and buses the Buses sheet adds.
        panel_rules[eq_id] = rules
        for b in _fetchall(c, "SELECT id FROM app_bus WHERE equipment_id=:e AND is_main=0", {"e": eq_id}):
            eq.update_bus(b["id"], rules)
    return status


def _bus_row(c, vals: Dict[str, Any], created_panels: set, renamed: set, panel_rules: Dict[str, Dict[str, Any]]) -> str:
    panel = _need_element(c, vals.get("panel"), "panel")
    if panel["kind"] != "distribution":
        raise eq._bad("NOT_A_PANEL", f"{panel['name']} is a single element; buses belong to distribution panels")
    bus_name = vals.get("bus")
    if not bus_name:
        raise eq._bad("BUS_REQUIRED")
    payload: Dict[str, Any] = {}
    for col in ("incomers", "outgoers"):
        n = _int(vals.get(col), col)
        if n is not None:
            payload[col] = n
    for col, key in (("incoming types", "incomingTypes"), ("outgoing types", "outgoingTypes")):
        ids = _type_ids(c, vals.get(col))
        if ids is not None:
            payload[key] = ids
    bus = _fetchone(
        c, "SELECT * FROM app_bus WHERE equipment_id=:e AND is_main=0 AND lower(name)=lower(:n)",
        {"e": panel["id"], "n": bus_name},
    )
    if not bus:
        # A new bus takes the panel's allowed types unless its row sets its own.
        payload = {**panel_rules.get(panel["id"], {}), **payload}
    if not bus and panel["id"] in created_panels and panel["id"] not in renamed:
        # A panel created by this import starts with "Bus A": its first bus row
        # names that bus instead of adding another one.
        renamed.add(panel["id"])
        first = _fetchone(c, "SELECT id FROM app_bus WHERE equipment_id=:e AND is_main=0", {"e": panel["id"]})
        eq.update_bus(first["id"], {"name": bus_name, **payload})
        return "created"
    if panel["id"] in created_panels and panel["id"] not in renamed:
        renamed.add(panel["id"])
        if bus:  # the sheet names the automatic first bus itself
            if payload:
                eq.update_bus(bus["id"], payload)
            return "created"
    if bus:
        if not payload:
            return "unchanged"
        eq.update_bus(bus["id"], payload)
        return "updated"
    eq.create_bus(panel["id"], {"name": bus_name, **payload})
    return "created"


def _connection_row(c, vals: Dict[str, Any]) -> str:
    panel = _need_element(c, vals.get("panel"), "panel")
    member = _need_element(c, vals.get("element"), "element")
    role = (vals.get("role") or "").lower() or None
    pos = _int(vals.get("position"), "position")
    if pos is not None and pos < 1:
        raise eq._bad("POSITION_INVALID", "position starts at 1")
    position = pos - 1 if pos is not None else None
    if panel["kind"] == "single":
        # A direct link: the single element feeds `element`.
        if vals.get("bus"):
            raise eq._bad("NOT_A_PANEL", f"{panel['name']} is a single element and has no buses")
        if role not in (None, "outgoer"):
            raise eq._bad("ROLE_INVALID", "a direct link from a single element is an outgoer")
        node = eq._main_node(c, panel["id"])
        current = _fetchone(c, "SELECT sort_order FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e",
                            {"b": node["id"], "e": member["id"]})
        if current:
            if position is None or position == current["sort_order"]:
                return "unchanged"
            eq.move_direct(panel["id"], member["id"], {"position": position})
            return "updated"
        eq.connect_direct(panel["id"], {"equipmentId": member["id"], "position": position})
        return "created"
    if not vals.get("bus"):
        raise eq._bad("BUS_REQUIRED", f"{panel['name']} is a distribution panel: name the bus")
    bus = _fetchone(
        c, "SELECT * FROM app_bus WHERE equipment_id=:e AND is_main=0 AND lower(name)=lower(:n)",
        {"e": panel["id"], "n": vals["bus"]},
    )
    if not bus:
        raise eq._missing("BUS_NOT_FOUND", f"{panel['name']} {vals['bus']}")
    if role not in eq._ROLES:
        raise eq._bad("ROLE_INVALID", "role must be incomer or outgoer")
    current = _fetchone(c, "SELECT role, sort_order FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e",
                        {"b": bus["id"], "e": member["id"]})
    if current:
        if current["role"] != role:
            raise eq._conflict("ALREADY_ATTACHED", f"{member['name']} is already a {current['role']} of {bus['name']}")
        if position is None or position == current["sort_order"]:
            return "unchanged"
        eq.move_attachment(bus["id"], member["id"], {"position": position})
        return "updated"
    eq.attach_equipment(bus["id"], {"equipmentId": member["id"], "role": role, "position": position})
    return "created"


def _meter_table(c, vals: Dict[str, Any]) -> Dict[str, Any]:
    ref = vals.get("table") or vals.get("mfm")
    if not ref:
        raise eq._bad("TABLE_REQUIRED", "give the MFM's logger table")
    t = _fetchone(
        c, "SELECT t.id, t.name, t.schema_id, s.name AS schema_name FROM app_device_tables t "
        "LEFT JOIN app_schemas s ON s.id = t.schema_id WHERE t.id=:r OR lower(t.name)=lower(:r)", {"r": ref},
    )
    if not t:
        raise eq._missing("TABLE_NOT_FOUND", ref)
    want = vals.get("schema")
    if want and want.lower() not in {(t["schema_id"] or "").lower(), (t["schema_name"] or "").lower()}:
        raise eq._bad("SCHEMA_MISMATCH", f"table {t['name']} uses schema {t['schema_name']}, not {want}")
    return t


def _meter_row(c, vals: Dict[str, Any]) -> str:
    tbl = _meter_table(c, vals)
    host = _need_element(c, vals.get("element"), "element")
    placed = _fetchone(
        c, "SELECT m.bus_id, m.role, m.equipment_id, b.equipment_id AS owner FROM app_bus_meter m "
        "JOIN app_bus b ON b.id = m.bus_id WHERE m.table_id=:t", {"t": tbl["id"]},
    )
    if host["kind"] == "single":
        if vals.get("bus") or vals.get("measures"):
            raise eq._bad("NOT_A_PANEL", f"{host['name']} is a single element: its MFMs sit on it directly")
        if placed and placed["owner"] == host["id"]:
            return "unchanged"
        eq.attach_meter(host["id"], {"tableId": tbl["id"]})
        return "created"
    if not vals.get("bus"):
        raise eq._bad("BUS_REQUIRED", f"{host['name']} is a distribution panel: name the bus")
    bus = _fetchone(
        c, "SELECT * FROM app_bus WHERE equipment_id=:e AND is_main=0 AND lower(name)=lower(:n)",
        {"e": host["id"], "n": vals["bus"]},
    )
    if not bus:
        raise eq._missing("BUS_NOT_FOUND", f"{host['name']} {vals['bus']}")
    role = _METER_ROLES.get((vals.get("role") or "").lower())
    if not role:
        raise eq._bad("ROLE_INVALID", "role must be incoming, outgoing or spare")
    feeder = _need_element(c, vals["measures"], "measures")["id"] if vals.get("measures") else None
    if role == "spare":
        if feeder:
            raise eq._bad("SPARE_MEASURES", "a spare MFM measures nothing: leave measures blank")
        role = "outgoer"
    if placed and placed["bus_id"] == bus["id"]:
        if placed["role"] != role:
            raise eq._conflict("ROLE_CHANGE", f"{tbl['name']} is a {placed['role']} MFM here; remove it and add it again")
        if placed["equipment_id"] == feeder:
            return "unchanged"
        eq.assign_bus_meter(bus["id"], tbl["id"], {"equipmentId": feeder})
        return "updated"
    payload = {"tableId": tbl["id"], "role": role}
    if feeder:
        payload["equipmentId"] = feeder
    eq.attach_bus_meter(bus["id"], payload)
    return "created"


# ---------- Run ----------
def import_ems(filename: str, data: bytes, dry_run: bool) -> Dict[str, Any]:
    sheets = read_workbook(filename, data)
    results: List[Dict[str, Any]] = []
    summary = {s: {"created": 0, "updated": 0, "unchanged": 0} for s in _SHEETS}
    conn = _engine().connect()
    trans = conn.begin()
    token = eq._SHARED_CONN.set(conn)
    try:
        created_panels: set = set()
        renamed: set = set()
        panel_rules: Dict[str, Dict[str, Any]] = {}
        seen: Dict[str, int] = {}

        def run(sheet: str, key_cols: Tuple[str, ...], fn: Callable[[Dict[str, Any]], str]) -> None:
            for n, vals in sheets.get(sheet, []):
                key = " / ".join(v for v in (vals.get(k) for k in key_cols) if v)
                item = {"sheet": sheet.capitalize(), "row": n, "key": key}
                try:
                    with conn.begin_nested():
                        item["status"] = fn(vals)
                    summary[sheet][item["status"]] += 1
                except eq.EquipmentError as e:
                    item.update({"status": "failed", "error": e.detail})
                except IntegrityError:
                    item.update({"status": "failed", "error": "CONFLICT: a concurrent change; retry"})
                results.append(item)
                if sheet == "elements" and vals.get("name") and item["status"] != "failed":
                    seen.setdefault(vals["name"].lower(), n)

        run("elements", ("name",), lambda v: _element_row(conn, v, seen, created_panels, panel_rules))
        run("buses", ("panel", "bus"), lambda v: _bus_row(conn, v, created_panels, renamed, panel_rules))
        run("connections", ("panel", "bus", "role", "element"), lambda v: _connection_row(conn, v))
        run("meters", ("table", "mfm", "element", "bus"), lambda v: _meter_row(conn, v))
        errors = [r for r in results if r["status"] == "failed"]
        saved = not dry_run and not errors
        if saved:
            trans.commit()
        else:
            trans.rollback()
    except Exception:
        trans.rollback()
        raise
    finally:
        eq._SHARED_CONN.reset(token)
        conn.close()
    return {
        "success": not errors,
        "dryRun": dry_run,
        "saved": saved,
        "summary": {**summary, "errors": len(errors)},
        "results": results,
    }


# ---------- Template ----------
def template_xlsx() -> bytes:
    """An empty workbook with the three sheets' headers, one column per known
    nameplate field, and a Types sheet listing each type's fields and units."""
    from openpyxl import Workbook

    with eq._conn() as c:
        types = _fetchall(c, "SELECT * FROM app_equipment_type ORDER BY sort_order, name")
    field_cols: List[str] = []
    for t in types:
        for f in eq._fields(t):
            if f["label"] not in field_cols:
                field_cols.append(f["label"])
    wb = Workbook()
    ws = wb.active
    ws.title = "Elements"
    ws.append(["name", "kind", "type", "zone", "max incomers", "max outgoers", "incoming types", "outgoing types",
               "spare", "description", *field_cols])
    wb.create_sheet("Buses").append(["panel", "bus", "incomers", "outgoers", "incoming types", "outgoing types"])
    wb.create_sheet("Connections").append(["panel", "bus", "role", "element", "position"])
    wb.create_sheet("Meters").append(["table", "element", "bus", "role", "measures", "schema"])
    ref = wb.create_sheet("Types")
    ref.append(["type", "field", "kind", "units / options", "required"])
    for t in types:
        fields = eq._fields(t) or [{}]
        for f in fields:
            ref.append([
                t["name"], f.get("label"), f.get("kind"),
                ", ".join(f.get("units") or f.get("options") or []), "yes" if f.get("required") else "",
            ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- Export (display layout of the plant template) ----------
def _sheet_title(name: str, taken: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name or "Untyped")[:31] or "Untyped"
    title, i = base, 2
    while title.lower() in taken:
        title = f"{base[:28]} {i}"
        i += 1
    taken.add(title.lower())
    return title


def _header(field: Dict[str, Any]) -> str:
    units = field.get("units") or []
    label = f"{field['label']} ({units[0]})" if field.get("kind") == "quantity" and len(units) == 1 else field["label"]
    return label + (" *" if field.get("required") else "")


def _value_cell(field: Dict[str, Any], v: Optional[Dict[str, Any]]) -> Any:
    if not v:
        return None
    if field.get("kind") != "quantity":
        return v.get("value")
    units = field.get("units") or []
    num = v.get("value")
    if isinstance(num, float) and num.is_integer():
        num = int(num)
    if len(units) == 1 and v.get("unit") in (None, units[0]):
        return num  # the unit is in the header
    return f"{num} {v['unit']}".strip() if v.get("unit") else num


def export_ems_xlsx(type_id: Optional[str] = None) -> bytes:
    """EMS elements in the plant template's layout: one sheet per type (group
    row REQUIRED / NAMEPLATE - OPTIONAL, then headers), a Bus Sections sheet
    and a Lists sheet (zones, types)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    items = eq.list_equipment(category_id=CATEGORY, type_id=type_id)
    with eq._conn() as c:
        types = _fetchall(c, "SELECT * FROM app_equipment_type ORDER BY sort_order, name")
        zones = _fetchall(c, "SELECT * FROM app_equipment_zone ORDER BY sort_order, name")
    type_name = {t["id"]: t["name"] for t in types}
    names = lambda ids: ", ".join(type_name.get(i, i) for i in ids) or None  # noqa: E731
    bold, group_fill = Font(bold=True), PatternFill("solid", fgColor="EDE7DD")

    wb = Workbook()
    wb.remove(wb.active)
    taken: set = set()
    groups: List[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]] = []
    for t in types + [None]:
        tid = t["id"] if t else None
        rows = [i for i in items if i["typeId"] == tid]
        if rows:
            groups.append((t, rows))
    bus_rows: List[List[Any]] = []
    for t, rows in groups:
        fields = eq._fields(t)
        req = [f for f in fields if f.get("required")]
        opt = [f for f in fields if not f.get("required")]
        panels = any(i["kind"] == "distribution" for i in rows)
        singles = any(i["kind"] == "single" for i in rows)
        conn_cols = (["Number of Bus Sections"] if panels else []) + (["Max Incomers", "Max Outgoers"] if singles else [])
        required = ["Element ID *", "Name *", "Zone", *[_header(f) for f in req], *conn_cols,
                    "Allowed Incoming Types", "Allowed Outgoing Types"]
        optional = [*[_header(f) for f in opt], "Spare", "Description"]
        ws = wb.create_sheet(_sheet_title(t["name"] if t else "Untyped", taken))
        ws.append(["REQUIRED"] + [None] * (len(required) - 1) + ["NAMEPLATE / OPTIONAL"] + [None] * (len(optional) - 1))
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(required))
        ws.merge_cells(start_row=1, start_column=len(required) + 1, end_row=1, end_column=len(required) + len(optional))
        ws.append(required + optional)
        for cell in ws[1] + ws[2]:
            cell.font = bold
        for cell in ws[1]:
            cell.fill, cell.alignment = group_fill, Alignment(horizontal="center")
        for i in rows:
            vals = i["values"]
            if i["kind"] == "distribution":
                buses = i.get("buses") or []
                inc = sorted({x for b in buses for x in b["incomingTypes"]}, key=lambda x: type_name.get(x, x))
                out = sorted({x for b in buses for x in b["outgoingTypes"]}, key=lambda x: type_name.get(x, x))
                conn = ([len(buses)] if panels else []) + ([None, None] if singles else [])
                for b in buses:
                    bus_rows.append([i["id"], i["name"], b["id"], b["name"], b["incomers"], b["outgoers"],
                                     names(b["incomingTypes"]), names(b["outgoingTypes"])])
            else:
                inc, out = i.get("incomingTypes") or [], i.get("outgoingTypes") or []
                conn = ([None] if panels else []) + ([i["maxIncomers"], i["maxOutgoers"]] if singles else [])
            ws.append([
                i["id"], i["name"], i.get("zoneName"), *[_value_cell(f, vals.get(f["id"])) for f in req], *conn,
                names(inc), names(out), *[_value_cell(f, vals.get(f["id"])) for f in opt],
                "yes" if i["spare"] else None, i.get("description"),
            ])
        ws.freeze_panes = "C3"
        for idx, col in enumerate(ws.iter_cols(min_row=2, values_only=True), start=1):
            width = max((len(str(v)) for v in col if v is not None), default=8)
            ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 40)

    bs = wb.create_sheet("Bus Sections")
    bs.append(["REQUIRED", None, None, None, None, None, "OPTIONAL", None])
    bs.merge_cells("A1:F1")
    bs.merge_cells("G1:H1")
    bs.append(["Element ID *", "Element Name", "Bus ID *", "Bus Section *", "Maximum Incomers *",
               "Outgoing Feeder Capacity *", "Allowed Incoming Types", "Allowed Outgoing Types"])
    for cell in bs[1] + bs[2]:
        cell.font = bold
    for r in bus_rows:
        bs.append(r)
    bs.freeze_panes = "A3"

    by_id = {i["id"]: i["name"] for i in items}
    ms = wb.create_sheet("Meters")
    ms.append(["Table (MFM)", "Element", "Bus", "Role", "Measures", "Schema", "Device"])
    for cell in ms[1]:
        cell.font = bold
    role_word = {"incomer": "incoming", "outgoer": "outgoing"}
    for i in items:
        if i["kind"] == "single":
            for m in i["metering"]["meters"]:
                ms.append([m.get("tableName") or m["tableId"], i["name"], None, None, None, m.get("schemaName"), m.get("deviceName")])
            continue
        for b in i.get("buses") or []:
            for m in b["meters"]:
                spare = m["role"] == "outgoer" and not m.get("equipmentId")
                ms.append([m.get("tableName") or m["tableId"], i["name"], b["name"],
                           "spare" if spare else role_word.get(m["role"], m["role"]), by_id.get(m.get("equipmentId")),
                           m.get("schemaName"), m.get("deviceName")])
    ms.freeze_panes = "A2"

    lists = wb.create_sheet("Lists")
    lists.append(["Zones", "Element types", "Kinds"])
    for cell in lists[1]:
        cell.font = bold
    zn, tn, kn = [z["name"] for z in zones], [t["name"] for t in types], list(eq.EQUIPMENT_KINDS)
    for k in range(max(len(zn), len(tn), len(kn))):
        lists.append([zn[k] if k < len(zn) else None, tn[k] if k < len(tn) else None, kn[k] if k < len(kn) else None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
