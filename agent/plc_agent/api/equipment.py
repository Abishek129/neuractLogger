"""Electrical elements ("Electrical Elements" screen).

Model
* app_equipment_category: EMS / Source / BMS (seed data, edited in the DB).
  ``kinds_json`` = the kinds its elements may have.
* app_equipment_type: user-defined types (Load, HT Panel, Transformer, ...),
  one global list; ``config_json`` = the type's nameplate field definitions
  plus the default capacity of a single element's main node.
* app_equipment: one row per element = category + ``kind`` (``single`` |
  ``distribution``, fixed at create) + optional type. ``values_json`` holds
  the type's field values, plus ``spare`` ("not expected on the map") and
  ``version``.
* app_equipment_zone: user-managed zones; an element may sit in one.
* app_bus = connection nodes. Distribution elements have 1..N buses (Bus A,
  B, ...); single elements have exactly one hidden main node (is_main = 1)
  that carries the element's own incoming/outgoing capacity and rules.
* app_bus_type: allowed types per node and side.
* app_bus_equipment: what feeds what, in order (``sort_order`` = position,
  0-based, compact per node and side).
    - an element attached to a **bus** as incomer (it feeds the bus) or
      outgoer (the bus feeds it);
    - on a single element's **main node**, an outgoer row is a **direct
      link** single -> single (e.g. Grid -> Transformer).
  Every connection checks the rules at both ends (allowed types and
  capacity of the bus/main node on each side). Multiple parents are allowed;
  loops (in flow direction) are rejected.
* app_bus_meter: MFMs on a node. An MFM is a **logger table** (where its
  readings are written); its device and schema come from the table. On a bus
  each MFM sits in the slot of an attached incomer / outgoer (one per
  relation) or, outgoing only, is a spare that takes a free outgoing point; a
  single element's MFMs sit on its main node. A table is on one node only.

Concurrency: every change to an equipment, its nodes, rules, attachments or
meters bumps its ``version``. Writes accept ``If-Match: <version>`` (of the
equipment that owns the bus / node); a stale one is 409 VERSION_CONFLICT.
Without the header, the last write wins.

Reads go straight to the metadata DB (no Store cache): this is configuration
the Rust engine never reads. Every mutation runs in one transaction.
"""
from __future__ import annotations

import json
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import bindparam, text

from .appdb import EQUIPMENT_KINDS, _conn as _db_conn, _fetchall, _fetchone, _params_load

# A spreadsheet import runs every operation in one transaction it controls
# (rolled back on a dry run or any error); everything else commits per call.
_SHARED_CONN: ContextVar[Any] = ContextVar("equipment_shared_conn", default=None)


@contextmanager
def _conn():
    shared = _SHARED_CONN.get()
    if shared is not None:
        yield shared
        return
    with _db_conn() as c:
        yield c


_MAX_BUSES = 26
_MAX_FEEDERS = 999  # incomers / outgoers per node
_ROLES = ("incomer", "outgoer")
_ROLE_TYPES = {"incomer": "incomingTypes", "outgoer": "outgoingTypes"}
_FIELD_KINDS = ("quantity", "choice", "text")
_FIELD_ROLES = ("voltage", "voltage.in", "voltage.out")


class EquipmentError(Exception):
    """Validation/conflict error mapped to an HTTP status by the router."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.status = status
        self.code = code
        self.message = message

    @property
    def detail(self) -> str:
        return f"{self.code}: {self.message}" if self.message else self.code


def _bad(code: str, message: str = "") -> EquipmentError:
    return EquipmentError(400, code, message)


def _missing(code: str, message: str = "") -> EquipmentError:
    return EquipmentError(404, code, message)


def _conflict(code: str, message: str = "") -> EquipmentError:
    return EquipmentError(409, code, message)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{secrets.token_hex(2)}"


def _req_str(payload: Dict[str, Any], key: str, code: str) -> str:
    val = payload.get(key)
    if not isinstance(val, str) or not val.strip():
        raise _bad(code)
    return val.strip()


def _snake(key: str) -> str:
    return "".join(f"_{ch.lower()}" if ch.isupper() else ch for ch in key)


def _int(payload: Dict[str, Any], key: str, lo: int, hi: int, default: Optional[int] = None) -> int:
    val = payload.get(key, default)
    if isinstance(val, bool) or not isinstance(val, int) or not lo <= val <= hi:
        raise _bad(f"{_snake(key).upper()}_INVALID", f"{key} must be a whole number {lo}..{hi}")
    return val


def _opt_position(payload: Dict[str, Any]) -> Optional[int]:
    if payload.get("position") is None:
        return None
    return _int(payload, "position", 0, 10**6)


def _bool(payload: Dict[str, Any], key: str) -> bool:
    val = payload.get(key)
    if not isinstance(val, bool):
        raise _bad(f"{_snake(key).upper()}_INVALID", f"{key} must be true or false")
    return val


def _opt_text(payload: Dict[str, Any], key: str) -> Optional[str]:
    v = payload.get(key)
    if v is not None and not isinstance(v, str):
        raise _bad(f"{_snake(key).upper()}_INVALID")
    return v.strip() if isinstance(v, str) and v.strip() else None


def _json_load(raw: Optional[str], default):
    try:
        val = json.loads(raw) if raw else default
        return val if isinstance(val, type(default)) else default
    except Exception:
        return default


# ---------- Versions ----------
def _check_version(c, eq_id: str, if_match: Optional[str]) -> None:
    """If-Match: <version> must equal the equipment's current version."""
    if if_match is None:
        return
    raw = if_match.strip()
    if raw.startswith("W/"):
        raw = raw[2:]
    raw = raw.strip('"').strip()
    if not raw.isdigit():
        raise _bad("IF_MATCH_INVALID", "If-Match must be the equipment version (an integer)")
    row = _fetchone(c, "SELECT version FROM app_equipment WHERE id=:id", {"id": eq_id})
    if row and int(row["version"]) != int(raw):
        raise _conflict("VERSION_CONFLICT", eq_id)


def _touch(c, *eq_ids: str) -> None:
    """Bump version + updatedAt of each equipment touched by a change."""
    now = _now()
    for eq_id in dict.fromkeys(e for e in eq_ids if e):
        c.execute(
            text("UPDATE app_equipment SET version = version + 1, updated_at=:now WHERE id=:id"),
            {"now": now, "id": eq_id},
        )


# ---------- Categories (EMS / Source / BMS, read-only) + types ----------
def _config(t: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return _json_load((t or {}).get("config_json"), {})


def _fields(t: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Field definitions of a type row (or of an element row, which carries its type's config)."""
    return [f for f in _config(t).get("fields", []) if isinstance(f, dict) and f.get("id")]


def _category_out(r: Dict[str, Any]) -> Dict[str, Any]:
    kinds = [k for k in _json_load(r.get("kinds_json"), []) if k in EQUIPMENT_KINDS]
    return {"id": r["id"], "name": r["name"], "sortOrder": r["sort_order"], "kinds": kinds}


def _get_category(c, category_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_equipment_category WHERE id=:id", {"id": category_id})
    if not row:
        raise _missing("CATEGORY_NOT_FOUND", category_id)
    return row


def list_categories() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT * FROM app_equipment_category ORDER BY sort_order, name")
    return [_category_out(r) for r in rows]


def _check_kind(category: Dict[str, Any], kind: Any) -> str:
    if kind not in EQUIPMENT_KINDS:
        raise _bad("KIND_INVALID", "kind must be single or distribution")
    if kind not in _category_out(category)["kinds"]:
        raise _bad("KIND_NOT_ALLOWED", f"{category['name']} does not take {kind} elements")
    return kind


def _type_out(r: Dict[str, Any], used: Optional[int] = None) -> Dict[str, Any]:
    node = _config(r).get("node") or {}
    out = {
        "id": r["id"],
        "name": r["name"],
        "sortOrder": r["sort_order"],
        "fields": _fields(r),
        # Capacity of a single element's main node when it is created.
        "defaultCapacity": {"incomers": int(node.get("incomers", 1)), "outgoers": int(node.get("outgoers", 1))},
    }
    if used is not None:
        out["used"] = used
    return out


def _get_type(c, type_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_equipment_type WHERE id=:id", {"id": type_id})
    if not row:
        raise _missing("TYPE_NOT_FOUND", type_id)
    return row


def _type_usage(c, type_id: str) -> Dict[str, int]:
    return {
        "elements": _fetchone(c, "SELECT COUNT(*) AS n FROM app_equipment WHERE type_id=:t", {"t": type_id})["n"],
        "busRules": _fetchone(c, "SELECT COUNT(*) AS n FROM app_bus_type WHERE type_id=:t", {"t": type_id})["n"],
    }


def list_types() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT * FROM app_equipment_type ORDER BY sort_order, name")
        counts = {r["type_id"]: r["n"] for r in _fetchall(
            c, "SELECT type_id, COUNT(*) AS n FROM app_equipment WHERE type_id IS NOT NULL GROUP BY type_id")}
    return [_type_out(r, counts.get(r["id"], 0)) for r in rows]


def _fields_in(val: Any) -> List[Dict[str, Any]]:
    """Validate a type's field definitions: [{id, label, kind, units?, options?, required?, role?}]."""
    if not isinstance(val, list):
        raise _bad("FIELDS_INVALID", "fields must be a list")
    out, seen = [], set()
    for i, f in enumerate(val):
        if not isinstance(f, dict):
            raise _bad("FIELDS_INVALID", f"field {i} must be an object")
        fid, label = f.get("id"), f.get("label")
        if not isinstance(fid, str) or not fid.strip() or not isinstance(label, str) or not label.strip():
            raise _bad("FIELDS_INVALID", f"field {i} needs an id and a label")
        fid = fid.strip()
        if fid.lower() in seen:
            raise _bad("FIELDS_INVALID", f"duplicate field id {fid}")
        seen.add(fid.lower())
        kind = f.get("kind", "text")
        if kind not in _FIELD_KINDS:
            raise _bad("FIELDS_INVALID", f"{fid}: kind must be one of {', '.join(_FIELD_KINDS)}")
        item: Dict[str, Any] = {"id": fid, "label": label.strip(), "kind": kind, "required": bool(f.get("required", False))}
        for key in ("units", "options"):
            lst = f.get(key)
            if lst is None:
                continue
            if not isinstance(lst, list) or not all(isinstance(x, str) and x.strip() for x in lst):
                raise _bad("FIELDS_INVALID", f"{fid}: {key} must be a list of text")
            item[key] = [x.strip() for x in lst]
        if kind == "choice" and not item.get("options"):
            raise _bad("FIELDS_INVALID", f"{fid}: a choice field needs options")
        role = f.get("role")
        if role is not None:
            if role not in _FIELD_ROLES:
                raise _bad("FIELDS_INVALID", f"{fid}: role must be one of {', '.join(_FIELD_ROLES)}")
            item["role"] = role
        out.append(item)
    return out


def _type_config(payload: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(current)
    if "fields" in payload:
        cfg["fields"] = _fields_in(payload["fields"])
    if "defaultCapacity" in payload:
        cap = payload["defaultCapacity"]
        if not isinstance(cap, dict):
            raise _bad("DEFAULT_CAPACITY_INVALID", "defaultCapacity must be {incomers, outgoers}")
        cfg["node"] = {"incomers": _int(cap, "incomers", 0, _MAX_FEEDERS, 1), "outgoers": _int(cap, "outgoers", 0, _MAX_FEEDERS, 1)}
    return cfg


def _check_type_name_free(c, name: str, exclude_id: str = "") -> None:
    if _fetchone(c, "SELECT id FROM app_equipment_type WHERE lower(name)=lower(:n) AND id<>:x", {"n": name, "x": exclude_id}):
        raise _conflict("TYPE_EXISTS", name)


def create_type(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _req_str(payload, "name", "NAME_REQUIRED")
    cfg = _type_config(payload, {"fields": []})
    with _conn() as c:
        _check_type_name_free(c, name)
        order = payload.get("sortOrder")
        if order is None:
            order = _fetchone(c, "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM app_equipment_type")["n"]
        else:
            order = _int(payload, "sortOrder", 0, 10**6)
        tid = _new_id("typ")
        c.execute(
            text("INSERT INTO app_equipment_type (id, name, sort_order, config_json) VALUES (:id, :n, :o, :cfg)"),
            {"id": tid, "n": name, "o": order, "cfg": json.dumps(cfg)},
        )
        return _type_out(_get_type(c, tid), 0)


def update_type(type_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Rename / reorder / redefine fields. Stored values of removed fields stay
    on the elements but are ignored (readiness follows the current fields)."""
    with _conn() as c:
        row = _get_type(c, type_id)
        name, order = row["name"], row["sort_order"]
        if "name" in payload:
            name = _req_str(payload, "name", "NAME_REQUIRED")
            _check_type_name_free(c, name, exclude_id=type_id)
        if "sortOrder" in payload:
            order = _int(payload, "sortOrder", 0, 10**6)
        cfg = _type_config(payload, _config(row))
        c.execute(
            text("UPDATE app_equipment_type SET name=:n, sort_order=:o, config_json=:cfg WHERE id=:id"),
            {"n": name, "o": order, "cfg": json.dumps(cfg), "id": type_id},
        )
        return _type_out(_get_type(c, type_id), _type_usage(c, type_id)["elements"])


def delete_type(type_id: str) -> None:
    with _conn() as c:
        _get_type(c, type_id)
        use = _type_usage(c, type_id)
        if use["elements"] or use["busRules"]:
            raise _conflict("TYPE_IN_USE", f"{use['elements']} element(s), {use['busRules']} bus rule(s)")
        c.execute(text("DELETE FROM app_equipment_type WHERE id=:id"), {"id": type_id})


# ---------- Zones (user-managed) ----------
def _zone_out(r: Dict[str, Any], used: Optional[int] = None) -> Dict[str, Any]:
    out = {"id": r["id"], "name": r["name"], "sortOrder": r["sort_order"]}
    if used is not None:
        out["used"] = used
    return out


def _get_zone(c, zone_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_equipment_zone WHERE id=:id", {"id": zone_id})
    if not row:
        raise _missing("ZONE_NOT_FOUND", zone_id)
    return row


def _zone_used(c, zone_id: str) -> int:
    return _fetchone(c, "SELECT COUNT(*) AS n FROM app_equipment WHERE zone_id=:z", {"z": zone_id})["n"]


def _check_zone_name_free(c, name: str, exclude_id: str = "") -> None:
    if _fetchone(c, "SELECT id FROM app_equipment_zone WHERE lower(name)=lower(:n) AND id<>:x", {"n": name, "x": exclude_id}):
        raise _conflict("ZONE_EXISTS", name)


def list_zones() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = _fetchall(c, "SELECT * FROM app_equipment_zone ORDER BY sort_order, name")
        counts = {r["zone_id"]: r["n"] for r in _fetchall(
            c, "SELECT zone_id, COUNT(*) AS n FROM app_equipment WHERE zone_id IS NOT NULL GROUP BY zone_id")}
    return [_zone_out(r, counts.get(r["id"], 0)) for r in rows]


def create_zone(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _req_str(payload, "name", "NAME_REQUIRED")
    with _conn() as c:
        _check_zone_name_free(c, name)
        if payload.get("sortOrder") is None:
            order = _fetchone(c, "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM app_equipment_zone")["n"]
        else:
            order = _int(payload, "sortOrder", 0, 10**6)
        zid = _new_id("zone")
        c.execute(text("INSERT INTO app_equipment_zone (id, name, sort_order) VALUES (:id, :n, :o)"),
                  {"id": zid, "n": name, "o": order})
        return _zone_out(_get_zone(c, zid), 0)


def update_zone(zone_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        row = _get_zone(c, zone_id)
        name, order = row["name"], row["sort_order"]
        if "name" in payload:
            name = _req_str(payload, "name", "NAME_REQUIRED")
            _check_zone_name_free(c, name, exclude_id=zone_id)
        if "sortOrder" in payload:
            order = _int(payload, "sortOrder", 0, 10**6)
        c.execute(text("UPDATE app_equipment_zone SET name=:n, sort_order=:o WHERE id=:id"), {"n": name, "o": order, "id": zone_id})
        return _zone_out(_get_zone(c, zone_id), _zone_used(c, zone_id))


def delete_zone(zone_id: str) -> None:
    with _conn() as c:
        _get_zone(c, zone_id)
        used = _zone_used(c, zone_id)
        if used:
            raise _conflict("ZONE_IN_USE", f"{used} element(s)")
        c.execute(text("DELETE FROM app_equipment_zone WHERE id=:id"), {"id": zone_id})


def _zone_ref(c, payload: Dict[str, Any]) -> Optional[str]:
    """zoneId from a payload: an existing zone id, or None to clear."""
    z = payload.get("zoneId")
    if z is None:
        return None
    if not isinstance(z, str) or not z.strip():
        raise _bad("ZONE_INVALID")
    return _get_zone(c, z.strip())["id"]


# ---------- Field values ----------
def _values_in(cat: Optional[Dict[str, Any]], current: Dict[str, Any], patch: Any) -> Dict[str, Any]:
    """Merge a values patch ({fieldId: {value, unit} | null}) into current values."""
    if patch is None:
        return current
    if not isinstance(patch, dict):
        raise _bad("VALUES_INVALID", "values must be an object")
    fields = {f["id"]: f for f in _fields(cat)}
    out = dict(current)
    for fid, item in patch.items():
        f = fields.get(fid)
        if not f:
            raise _bad("FIELD_UNKNOWN", f"{fid} is not a field of this element's type")
        if item is None or (isinstance(item, dict) and item.get("value") in (None, "")):
            out.pop(fid, None)
            continue
        if not isinstance(item, dict):
            raise _bad("FIELD_INVALID", f"{fid} must be {{value, unit}}")
        val, unit = item.get("value"), item.get("unit")
        kind = f.get("kind", "text")
        if kind == "quantity":
            try:
                num = float(str(val).strip())
            except ValueError:
                raise _bad("FIELD_INVALID", f"{fid}: '{val}' is not a number")
            if num < 0:
                raise _bad("FIELD_INVALID", f"{fid} must be >= 0")
            units = f.get("units") or []
            unit = unit or (units[0] if units else None)
            if units and unit not in units:
                raise _bad("FIELD_INVALID", f"{fid}: unit must be one of {', '.join(units)}")
            out[fid] = {"value": num, "unit": unit}
        elif kind == "choice":
            if val not in (f.get("options") or []):
                raise _bad("FIELD_INVALID", f"{fid} must be one of {', '.join(f.get('options') or [])}")
            out[fid] = {"value": val, "unit": None}
        else:
            if not isinstance(val, str):
                raise _bad("FIELD_INVALID", f"{fid} must be text")
            out[fid] = {"value": val.strip(), "unit": None}
    return out


def _fmt_q(v: Dict[str, Any]) -> str:
    n = v["value"]
    num = str(int(n)) if isinstance(n, (int, float)) and float(n).is_integer() else str(n)
    return f"{num} {v['unit']}".strip() if v.get("unit") else num


def _voltage(cat: Dict[str, Any], values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Voltage column: from the fields with a voltage role ("33 kV", "33 kV → 11 kV")."""
    by_role = {f.get("role"): f["id"] for f in _fields(cat) if f.get("role")}
    vin = values.get(by_role.get("voltage.in") or by_role.get("voltage", ""))
    vout = values.get(by_role.get("voltage.out", ""))
    if not vin and not vout:
        return None
    parts = [_fmt_q(v) for v in (vin, vout) if v]
    return {"in": _fmt_q(vin) if vin else None, "out": _fmt_q(vout) if vout else None, "text": " → ".join(parts)}


def _nameplate(cat: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    """Required nameplate fields of the type that have no value yet."""
    missing = [f["label"] for f in _fields(cat) if f.get("required") and f["id"] not in values]
    return {"complete": not missing, "missing": missing}


def _readiness(in_filled: int, in_total: int, out_filled: int, out_total: int) -> Dict[str, Any]:
    """Connection readiness: every incoming and outgoing slot has an element connected."""
    return {
        "ready": in_filled >= in_total and out_filled >= out_total,
        "incomers": {"filled": in_filled, "total": in_total},
        "outgoers": {"filled": out_filled, "total": out_total},
    }


# ---------- Nodes (buses + single equipment's main node) ----------
def _bus_label(i: int) -> str:
    return f"Bus {chr(ord('A') + i)}" if i < 26 else f"Bus {i + 1}"


def _insert_bus(c, eq_id: str, name: str, sort_order: int, incomers: int = 0, outgoers: int = 0, is_main: bool = False) -> str:
    bus_id = _new_id("bus")
    c.execute(
        text(
            "INSERT INTO app_bus (id, equipment_id, name, sort_order, incomers, outgoers, is_main, coupled_next) "
            "VALUES (:id, :e, :n, :s, :i, :o, :m, 0)"
        ),
        {"id": bus_id, "e": eq_id, "n": name, "s": sort_order, "i": incomers, "o": outgoers, "m": 1 if is_main else 0},
    )
    return bus_id


def _get_bus(c, bus_id: str, allow_main: bool = False) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_bus WHERE id=:id", {"id": bus_id})
    if not row or (row["is_main"] and not allow_main):
        raise _missing("BUS_NOT_FOUND", bus_id)
    return row


def _main_node(c, eq_id: str) -> Dict[str, Any]:
    row = _fetchone(c, "SELECT * FROM app_bus WHERE equipment_id=:e AND is_main=1", {"e": eq_id})
    if not row:  # defensive: init backfills these
        raise _conflict("NODE_MISSING", eq_id)
    return row


_IN_CHUNK = 5000


def _fetch_in(c, sql: str, ids: List[str], params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """_fetchall for a query with an ``IN :ids`` list (chunked for big plants).
    Rows keep the query's ORDER BY within each chunk; callers group by key."""
    out: List[Dict[str, Any]] = []
    stmt = text(sql).bindparams(bindparam("ids", expanding=True))
    for i in range(0, len(ids), _IN_CHUNK):
        rows = c.execute(stmt, {**(params or {}), "ids": ids[i:i + _IN_CHUNK]}).mappings().all()
        out.extend(dict(r) for r in rows)
    return out


def _node_types(c, bus_ids: List[str]) -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {b: {"incomer": [], "outgoer": []} for b in bus_ids}
    if not bus_ids:
        return out
    for r in _fetch_in(
        c,
        "SELECT bt.bus_id, bt.role, bt.type_id FROM app_bus_type bt "
        "JOIN app_equipment_type t ON t.id = bt.type_id WHERE bt.bus_id IN :ids ORDER BY t.sort_order, t.name",
        bus_ids,
    ):
        if r["bus_id"] in out:
            out[r["bus_id"]][r["role"]].append(r["type_id"])
    return out


def _bus_attached(c, bus_ids: List[str]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {b: {"incomer": [], "outgoer": []} for b in bus_ids}
    if not bus_ids:
        return out
    for r in _fetch_in(
        c,
        "SELECT be.bus_id, be.role, be.sort_order, e.id, e.name, e.category_id, e.kind, e.type_id, t.name AS type_name "
        "FROM app_bus_equipment be JOIN app_equipment e ON e.id = be.equipment_id "
        "LEFT JOIN app_equipment_type t ON t.id = e.type_id WHERE be.bus_id IN :ids ORDER BY be.sort_order, e.name",
        bus_ids,
    ):
        if r["bus_id"] in out:
            out[r["bus_id"]][r["role"]].append(
                {"id": r["id"], "name": r["name"], "categoryId": r["category_id"], "kind": r["kind"],
                 "typeId": r["type_id"], "typeName": r["type_name"], "position": r["sort_order"]}
            )
    return out


def _meter_info(c) -> Dict[str, Dict[str, Any]]:
    """logger table id -> what an MFM shows: the table, its schema, and its
    bound device (name, unit id, gateway, host)."""
    gws = {g["id"]: g for g in _fetchall(c, "SELECT id, name, host FROM app_gateways")}
    devs = {d["id"]: d for d in _fetchall(c, "SELECT id, name, protocol, status, unit_id, port, gateway_id, params_json FROM app_devices")}
    out = {}
    for t in _fetchall(
        c, "SELECT t.id, t.name, t.schema_id, s.name AS schema_name, t.device_id FROM app_device_tables t "
        "LEFT JOIN app_schemas s ON s.id = t.schema_id"
    ):
        d = devs.get(t["device_id"]) or {}
        gw = gws.get(d.get("gateway_id")) or {}
        out[t["id"]] = {
            "tableId": t["id"],
            "tableName": t["name"],
            "schemaId": t["schema_id"],
            "schemaName": t["schema_name"],
            "deviceId": t["device_id"],
            "deviceName": d.get("name"),
            "protocol": d.get("protocol"),
            "status": d.get("status"),
            "unitId": d.get("unit_id"),
            "gatewayId": d.get("gateway_id"),
            "gatewayName": gw.get("name"),
            "host": gw.get("host") or (_params_load(d.get("params_json")) or {}).get("host") if d else None,
            "port": d.get("port"),
        }
    return out


def _node_meters(c, bus_ids: List[str], info: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {b: [] for b in bus_ids}
    if not bus_ids:
        return out
    info = info if info is not None else _meter_info(c)
    for r in _fetch_in(
        c, "SELECT bus_id, table_id, role, equipment_id FROM app_bus_meter WHERE bus_id IN :ids ORDER BY sort_order", bus_ids
    ):
        if r["bus_id"] in out:
            m = dict(info.get(r["table_id"]) or {"tableId": r["table_id"]})
            m["role"] = r["role"]
            m["equipmentId"] = r["equipment_id"]
            out[r["bus_id"]].append(m)
    return out


def _bus_out(r: Dict[str, Any], cats, attached, meters, version: int) -> Dict[str, Any]:
    met_in = sum(1 for m in meters if m["role"] == "incomer")
    met_out = sum(1 for m in meters if m["role"] == "outgoer")
    by_feeder = {m["equipmentId"]: m for m in meters if m.get("equipmentId")}
    spares = [m for m in meters if m["role"] == "outgoer" and not m.get("equipmentId")]

    def slots(side: str) -> List[Dict[str, Any]]:
        return [{**e, "meter": by_feeder.get(e["id"])} for e in attached[side]]

    return {
        "id": r["id"],
        "equipmentId": r["equipment_id"],
        "equipmentVersion": version,
        "name": r["name"],
        "sortOrder": r["sort_order"],
        "incomers": r["incomers"],
        "outgoers": r["outgoers"],
        "coupledNext": bool(r["coupled_next"]),
        "incomingTypes": cats["incomer"],
        "outgoingTypes": cats["outgoer"],
        "incomingEquipment": slots("incomer"),
        "outgoingEquipment": slots("outgoer"),
        "spareIncomers": max(r["incomers"] - len(attached["incomer"]), 0),
        # Free outgoing points: not connected and not holding a spare MFM.
        "spareOutgoers": max(r["outgoers"] - len(attached["outgoer"]) - len(spares), 0),
        "spares": spares,
        "spareMeters": len(spares),
        "meters": meters,
        "points": r["incomers"] + r["outgoers"],
        "pointsMetered": min(met_in, r["incomers"]) + min(met_out, r["outgoers"]),
    }


def _version(c, eq_id: str) -> int:
    row = _fetchone(c, "SELECT version FROM app_equipment WHERE id=:id", {"id": eq_id})
    return int(row["version"]) if row else 0


def _buses(c, eq_id: str, info=None) -> List[Dict[str, Any]]:
    rows = _fetchall(
        c, "SELECT * FROM app_bus WHERE equipment_id=:e AND is_main=0 ORDER BY sort_order, name", {"e": eq_id}
    )
    ids = [r["id"] for r in rows]
    cats, att, met = _node_types(c, ids), _bus_attached(c, ids), _node_meters(c, ids, info)
    version = _version(c, eq_id)
    return [_bus_out(r, cats[r["id"]], att[r["id"]], met[r["id"]], version) for r in rows]


def _one_bus(c, bus_id: str) -> Dict[str, Any]:
    r = _get_bus(c, bus_id)
    return _bus_out(
        r, _node_types(c, [bus_id])[bus_id], _bus_attached(c, [bus_id])[bus_id],
        _node_meters(c, [bus_id])[bus_id], _version(c, r["equipment_id"]),
    )


def _type_list(c, payload: Dict[str, Any], key: str) -> Optional[List[str]]:
    """Validate a list of type ids (None if the key is absent); duplicates collapse."""
    if key not in payload:
        return None
    val = payload[key]
    if val is None:
        return []
    if not isinstance(val, list) or not all(isinstance(v, str) and v.strip() for v in val):
        raise _bad(f"{_snake(key).upper()}_INVALID", f"{key} must be a list of type ids")
    ids: List[str] = []
    for v in val:
        v = v.strip()
        _get_type(c, v)
        if v not in ids:
            ids.append(v)
    return ids


def _connections_of(c, node: Dict[str, Any], role: str) -> List[Dict[str, Any]]:
    """Equipment currently connected on a node's side.

    Bus: the equipment attached to that side. Main node of a single
    equipment X:
      * outgoing side: the buses X feeds (X is their incomer) + the equipment
        X feeds directly (outgoer rows on X's own main node);
      * incoming side: whatever feeds X (X is an outgoer of a bus, or of
        another single equipment's main node)."""
    if not node["is_main"]:
        return _fetchall(
            c,
            "SELECT e.id, e.name, e.type_id FROM app_bus_equipment be JOIN app_equipment e "
            "ON e.id = be.equipment_id WHERE be.bus_id=:b AND be.role=:r",
            {"b": node["id"], "r": role},
        )
    eq_id = node["equipment_id"]
    if role == "outgoer":
        fed_buses = _fetchall(
            c,
            "SELECT p.id, p.name, p.type_id FROM app_bus_equipment be JOIN app_bus b ON b.id = be.bus_id "
            "JOIN app_equipment p ON p.id = b.equipment_id WHERE be.equipment_id=:e AND be.role='incomer'",
            {"e": eq_id},
        )
        direct = _fetchall(
            c,
            "SELECT e.id, e.name, e.type_id FROM app_bus_equipment be JOIN app_equipment e "
            "ON e.id = be.equipment_id WHERE be.bus_id=:b AND be.role='outgoer'",
            {"b": node["id"]},
        )
        return fed_buses + direct
    return _fetchall(
        c,
        "SELECT p.id, p.name, p.type_id FROM app_bus_equipment be JOIN app_bus b ON b.id = be.bus_id "
        "JOIN app_equipment p ON p.id = b.equipment_id WHERE be.equipment_id=:e AND be.role='outgoer'",
        {"e": eq_id},
    )


def _set_node_rules(c, node: Dict[str, Any], payload: Dict[str, Any], cap_keys=("incomers", "outgoers")) -> bool:
    """Apply capacity + allowed types from a payload to a node, checking
    current connections. Returns True if anything changed."""
    changed = False
    upd = {}
    for role, key in zip(_ROLES, cap_keys):
        if key in payload:
            n = _int(payload, key, 0, _MAX_FEEDERS)
            used = _side_used(c, node, role)
            if n < used:
                raise _conflict("CAPACITY_BELOW_ATTACHED", f"{used} {role} point(s) in use (connections and spare MFMs); free some first")
            if not node["is_main"]:
                metered = _fetchone(
                    c, "SELECT COUNT(*) AS n FROM app_bus_meter WHERE bus_id=:b AND role=:r", {"b": node["id"], "r": role}
                )["n"]
                if n < metered:
                    raise _conflict("CAPACITY_BELOW_METERED", f"{metered} {role} points metered; detach MFMs first")
            upd["incomers" if role == "incomer" else "outgoers"] = n
    if upd:
        sets = ", ".join(f"{k}=:{k}" for k in upd)
        c.execute(text(f"UPDATE app_bus SET {sets} WHERE id=:id"), {**upd, "id": node["id"]})
        changed = True
    for role, key in _ROLE_TYPES.items():
        ids = _type_list(c, payload, key)
        if ids is None:
            continue
        if ids:
            outside = [x["name"] for x in _connections_of(c, node, role) if x["type_id"] not in ids]
            if outside:
                raise _conflict("ATTACHED_OUTSIDE_TYPES", f"{role}s {', '.join(sorted(outside))} are of another type")
        c.execute(text("DELETE FROM app_bus_type WHERE bus_id=:b AND role=:r"), {"b": node["id"], "r": role})
        for tid in ids:
            c.execute(
                text("INSERT INTO app_bus_type (bus_id, role, type_id) VALUES (:b, :r, :t)"),
                {"b": node["id"], "r": role, "t": tid},
            )
        changed = True
    return changed


# ---------- Equipment ----------
_EQUIPMENT_SELECT = (
    "SELECT e.*, cat.name AS category_name, t.name AS type_name, t.config_json, z.name AS zone_name "
    "FROM app_equipment e JOIN app_equipment_category cat ON cat.id = e.category_id "
    "LEFT JOIN app_equipment_type t ON t.id = e.type_id "
    "LEFT JOIN app_equipment_zone z ON z.id = e.zone_id "
)


def _get_equipment(c, eq_id: str) -> Dict[str, Any]:
    row = _fetchone(c, _EQUIPMENT_SELECT + "WHERE e.id=:id", {"id": eq_id})
    if not row:
        raise _missing("EQUIPMENT_NOT_FOUND", eq_id)
    return row


def _attached_to(c, eq_id: str) -> List[Dict[str, Any]]:
    """Where this equipment is connected as a member: on a bus, or fed directly
    by another single equipment (direct: true, busId/busName null)."""
    return _attached_to_many(c, [eq_id])[eq_id]


def _attached_to_many(c, eq_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {e: [] for e in eq_ids}
    if not eq_ids:
        return out
    for a in _fetch_in(
        c,
        "SELECT be.equipment_id, be.bus_id, be.role, be.sort_order, b.name AS bus_name, b.is_main, "
        "p.id AS panel_id, p.name AS panel_name "
        "FROM app_bus_equipment be JOIN app_bus b ON b.id = be.bus_id JOIN app_equipment p ON p.id = b.equipment_id "
        "WHERE be.equipment_id IN :ids ORDER BY p.name, b.sort_order",
        eq_ids,
    ):
        direct = bool(a["is_main"])
        out[a["equipment_id"]].append(
            {
                "busId": None if direct else a["bus_id"],
                "busName": None if direct else a["bus_name"],
                "equipmentId": a["panel_id"],
                "equipmentName": a["panel_name"],
                "role": a["role"],
                "position": a["sort_order"],
                "direct": direct,
            }
        )
    return out


def _prefetch(c, rows: List[Dict[str, Any]], info=None) -> Dict[str, Any]:
    """Everything _equipment_out needs for these equipment rows, in a fixed
    number of queries however many rows there are (the list used to run five
    whole-table reads per item, which grew quadratically with the plant)."""
    ids = [r["id"] for r in rows]
    nodes = _fetch_in(c, "SELECT * FROM app_bus WHERE equipment_id IN :ids ORDER BY sort_order, name", ids) if ids else []
    main: Dict[str, Dict[str, Any]] = {}
    buses: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        if n["is_main"]:
            main[n["equipment_id"]] = n
        else:
            buses.setdefault(n["equipment_id"], []).append(n)
    node_ids = [n["id"] for n in nodes]
    info = info if info is not None else _meter_info(c)
    return {
        "attachedTo": _attached_to_many(c, ids),
        "main": main,
        "buses": buses,
        "cats": _node_types(c, node_ids),
        "attached": _bus_attached(c, node_ids),
        "meters": _node_meters(c, node_ids, info),
    }


def _equipment_out(c, r: Dict[str, Any], info=None, pre: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    values = _json_load(r.get("values_json"), {})
    pre = pre if pre is not None else _prefetch(c, [r], info)
    attached_to = pre["attachedTo"][r["id"]]
    out = {
        "id": r["id"],
        "name": r["name"],
        "categoryId": r["category_id"],
        "categoryName": r["category_name"],
        "kind": r["kind"],
        "typeId": r.get("type_id"),
        "typeName": r.get("type_name"),
        "zoneId": r.get("zone_id"),
        "zoneName": r.get("zone_name"),
        "spare": bool(r.get("spare")),
        "description": r["description"],
        "values": values,
        "voltage": _voltage(r, values),
        "nameplate": _nameplate(r, values),
        "attachedTo": attached_to,
        "version": int(r.get("version") or 1),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }
    if r["kind"] == "distribution":
        version = int(r["version"])
        buses = [
            _bus_out(b, pre["cats"][b["id"]], pre["attached"][b["id"]], pre["meters"][b["id"]], version)
            for b in pre["buses"].get(r["id"], [])
        ]
        out["buses"] = buses
        meters = [m for b in buses for m in b["meters"]]
        out["metering"] = {
            "points": sum(b["points"] for b in buses),
            "pointsMetered": sum(b["pointsMetered"] for b in buses),
            "meterCount": len(meters),
            "meters": meters,
        }
        has_children = any(b["incomingEquipment"] or b["outgoingEquipment"] for b in buses)
        out["used"] = bool(attached_to) or has_children
        out["readiness"] = _readiness(
            sum(min(len(b["incomingEquipment"]), b["incomers"]) for b in buses), sum(b["incomers"] for b in buses),
            sum(min(len(b["outgoingEquipment"]), b["outgoers"]) for b in buses), sum(b["outgoers"] for b in buses),
        )
    else:
        node = pre["main"].get(r["id"])
        if not node:  # defensive: init backfills these
            raise _conflict("NODE_MISSING", r["id"])
        cats = pre["cats"][node["id"]]
        meters = pre["meters"][node["id"]]
        feeds = pre["attached"][node["id"]]["outgoer"]
        out.update(
            {
                "maxIncomers": node["incomers"],
                "maxOutgoers": node["outgoers"],
                "incomingTypes": cats["incomer"],
                "outgoingTypes": cats["outgoer"],
                # Direct links: single equipment this one feeds (ordered by position).
                "outgoingEquipment": feeds,
                "metering": {"meterCount": len(meters), "meters": meters},
            }
        )
        out["used"] = bool(attached_to) or bool(feeds)
        # Fed by: outgoer of a bus or a direct link. Feeds: buses (as their
        # incomer) and direct links from its own node.
        fed_by = sum(1 for a in attached_to if a["role"] == "outgoer")
        feeding = sum(1 for a in attached_to if a["role"] == "incomer") + len(feeds)
        out["readiness"] = _readiness(
            min(fed_by, node["incomers"]), node["incomers"], min(feeding, node["outgoers"]), node["outgoers"]
        )
    return out


def _check_name_free(c, name: str, exclude_id: str = "") -> None:
    row = _fetchone(
        c, "SELECT id FROM app_equipment WHERE lower(name)=lower(:n) AND id<>:x", {"n": name, "x": exclude_id}
    )
    if row:
        raise _conflict("EQUIPMENT_EXISTS", name)


def _flag(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    return str(v).lower() in ("1", "true", "yes")


def list_equipment(
    category_id: Optional[str] = None,
    kind: Optional[str] = None,
    type_id: Optional[str] = None,
    q: Optional[str] = None,
    metered: Optional[str] = None,
    ready: Optional[str] = None,
    used: Optional[str] = None,
    spare: Optional[str] = None,
    zone_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List with the screen's filters: category, kind, type, zone, search (name /
    type name), metered (has any MFM), ready (every slot connected), used, spare."""
    where, params = [], {}
    if zone_id:
        where.append("e.zone_id=:z")
        params["z"] = zone_id
    if category_id:
        where.append("e.category_id=:c")
        params["c"] = category_id
    if kind:
        where.append("e.kind=:k")
        params["k"] = kind
    if type_id:
        where.append("e.type_id=:t")
        params["t"] = type_id
    if q and q.strip():
        where.append("(lower(e.name) LIKE :q OR lower(COALESCE(t.name, '')) LIKE :q)")
        params["q"] = f"%{q.strip().lower()}%"
    sql = (
        _EQUIPMENT_SELECT + (("WHERE " + " AND ".join(where) + " ") if where else "")
        + "ORDER BY cat.sort_order, COALESCE(t.sort_order, 1000000), e.name"
    )
    want = {"metered": _flag(metered), "ready": _flag(ready), "used": _flag(used), "spare": _flag(spare)}
    with _conn() as c:
        rows = _fetchall(c, sql, params)
        pre = _prefetch(c, rows)
        items = [_equipment_out(c, r, pre=pre) for r in rows]
    out = []
    for i in items:
        actual = {
            "metered": i["metering"]["meterCount"] > 0,
            "ready": i["readiness"]["ready"],
            "used": i["used"],
            "spare": i["spare"],
        }
        if all(w is None or actual[k] == w for k, w in want.items()):
            out.append(i)
    return out


def get_equipment(eq_id: str) -> Dict[str, Any]:
    with _conn() as c:
        return _equipment_out(c, _get_equipment(c, eq_id))


def create_equipment(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = _req_str(payload, "name", "NAME_REQUIRED")
    category_id = _req_str(payload, "categoryId", "CATEGORY_REQUIRED")
    type_id = payload.get("typeId")
    if type_id is not None and (not isinstance(type_id, str) or not type_id.strip()):
        raise _bad("TYPE_INVALID")
    with _conn() as c:
        kind = _check_kind(_get_category(c, category_id), payload.get("kind"))
        typ = _get_type(c, type_id.strip()) if type_id else None
        zone_id = _zone_ref(c, payload)
        _check_name_free(c, name)
        values = _values_in(typ, {}, payload.get("values"))
        spare = _bool(payload, "spare") if "spare" in payload else False
        now = _now()
        eq_id = _new_id("eq")
        c.execute(
            text(
                "INSERT INTO app_equipment (id, name, category_id, kind, type_id, zone_id, spare, description, values_json, "
                "version, created_at, updated_at) VALUES (:id, :n, :c, :k, :t, :z, :sp, :d, :v, 1, :now, :now)"
            ),
            {
                "id": eq_id, "n": name, "c": category_id, "k": kind, "t": typ["id"] if typ else None, "z": zone_id,
                "sp": 1 if spare else 0, "d": _opt_text(payload, "description"), "v": json.dumps(values), "now": now,
            },
        )
        if kind == "distribution":
            _insert_bus(c, eq_id, _bus_label(0), 0)
        else:
            node = _config(typ).get("node") or {}
            node_id = _insert_bus(
                c, eq_id, "main", 0, int(node.get("incomers", 1)), int(node.get("outgoers", 1)), is_main=True
            )
            _set_node_rules(c, _get_bus(c, node_id, allow_main=True), payload, ("maxIncomers", "maxOutgoers"))
        return _equipment_out(c, _get_equipment(c, eq_id))


def _rules_seeing(c, eq_id: str) -> List[Dict[str, Any]]:
    """The node sides whose allowed types apply to this element's type.

    * the node it is connected to as a member (a bus side, or the outgoing
      side of the single equipment that feeds it directly);
    * for each single equipment connected on its own nodes: that equipment's
      own side facing it (fed by it -> incoming side; feeding it -> outgoing)."""
    out = []
    for a in _fetchall(c, "SELECT bus_id, role FROM app_bus_equipment WHERE equipment_id=:e", {"e": eq_id}):
        out.append({"bus_id": a["bus_id"], "role": a["role"]})
    for a in _fetchall(
        c,
        "SELECT be.equipment_id, be.role, m.kind FROM app_bus_equipment be JOIN app_bus b ON b.id = be.bus_id "
        "JOIN app_equipment m ON m.id = be.equipment_id WHERE b.equipment_id=:e",
        {"e": eq_id},
    ):
        if a["kind"] == "single":
            node = _main_node(c, a["equipment_id"])
            out.append({"bus_id": node["id"], "role": "incomer" if a["role"] == "outgoer" else "outgoer"})
    return out


def _check_type_change(c, eq_id: str, new_type: Optional[Dict[str, Any]]) -> None:
    new_id = new_type["id"] if new_type else None
    label = new_type["name"] if new_type else "untyped"
    for s in _rules_seeing(c, eq_id):
        allowed = _node_types(c, [s["bus_id"]])[s["bus_id"]][s["role"]]
        if allowed and new_id not in allowed:
            node = _get_bus(c, s["bus_id"], allow_main=True)
            owner = _get_equipment(c, node["equipment_id"])
            where = owner["name"] if node["is_main"] else f"{owner['name']} {node['name']}"
            raise _conflict("TYPE_NOT_ALLOWED_ON_BUS", f"{where} does not allow {label} {s['role']}s")


def update_equipment(eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        row = _get_equipment(c, eq_id)
        _check_version(c, eq_id, if_match)
        upd = {
            "id": eq_id,
            "name": row["name"],
            "category_id": row["category_id"],
            "type_id": row.get("type_id"),
            "zone_id": row.get("zone_id"),
            "spare": row.get("spare") or 0,
            "description": row["description"],
            "values_json": row.get("values_json") or "{}",
        }
        if "name" in payload:
            upd["name"] = _req_str(payload, "name", "NAME_REQUIRED")
            _check_name_free(c, upd["name"], exclude_id=eq_id)
        if "kind" in payload and payload["kind"] != row["kind"]:
            raise _bad("KIND_IMMUTABLE", "kind is fixed at create (buses vs MFMs depend on it)")
        if "categoryId" in payload and payload["categoryId"] != row["category_id"]:
            cat = _get_category(c, _req_str(payload, "categoryId", "CATEGORY_REQUIRED"))
            _check_kind(cat, row["kind"])
            upd["category_id"] = cat["id"]
        typ = row  # carries the current type's config_json
        if "typeId" in payload and payload["typeId"] != row.get("type_id"):
            new_id = payload["typeId"]
            if new_id is not None and (not isinstance(new_id, str) or not new_id.strip()):
                raise _bad("TYPE_INVALID")
            typ = _get_type(c, new_id.strip()) if new_id else None
            _check_type_change(c, eq_id, typ)
            upd["type_id"] = typ["id"] if typ else None
            # Values of fields the new type does not have are dropped.
            keep = {f["id"] for f in _fields(typ)}
            upd["values_json"] = json.dumps(
                {k: v for k, v in _json_load(upd["values_json"], {}).items() if k in keep}
            )
        if "values" in payload:
            upd["values_json"] = json.dumps(_values_in(typ, _json_load(upd["values_json"], {}), payload["values"]))
        if "zoneId" in payload:
            upd["zone_id"] = _zone_ref(c, payload)
        if "spare" in payload:
            upd["spare"] = 1 if _bool(payload, "spare") else 0
        if "description" in payload:
            upd["description"] = _opt_text(payload, "description")
        upd["updated_at"] = _now()
        c.execute(
            text(
                "UPDATE app_equipment SET name=:name, category_id=:category_id, type_id=:type_id, zone_id=:zone_id, spare=:spare, "
                "description=:description, values_json=:values_json, updated_at=:updated_at, "
                "version = version + 1 WHERE id=:id"
            ),
            upd,
        )
        if row["kind"] == "single":
            _set_node_rules(c, _main_node(c, eq_id), payload, ("maxIncomers", "maxOutgoers"))
        return _equipment_out(c, _get_equipment(c, eq_id))


def delete_equipment(eq_id: str, if_match: Optional[str] = None) -> None:
    with _conn() as c:
        _get_equipment(c, eq_id)
        _check_version(c, eq_id, if_match)
        parents = _attached_to(c, eq_id)
        if parents:
            raise _conflict(
                "EQUIPMENT_IN_USE",
                "connected to " + ", ".join(
                    p["equipmentName"] if p["direct"] else f"{p['equipmentName']} {p['busName']}" for p in parents
                ),
            )
        # Explicit child deletes (SQLite has no FK cascade by default). Its own
        # nodes' connections go too (the connected equipment is kept, and its
        # version bumps), and its MFMs are detached (the devices are kept).
        nodes = "(SELECT id FROM app_bus WHERE equipment_id=:id)"
        members = [r["equipment_id"] for r in _fetchall(c, f"SELECT equipment_id FROM app_bus_equipment WHERE bus_id IN {nodes}", {"id": eq_id})]
        for t in ("app_bus_equipment", "app_bus_type", "app_bus_meter"):
            c.execute(text(f"DELETE FROM {t} WHERE bus_id IN {nodes}"), {"id": eq_id})
        c.execute(text("DELETE FROM app_bus WHERE equipment_id=:id"), {"id": eq_id})
        c.execute(text("DELETE FROM app_equipment WHERE id=:id"), {"id": eq_id})
        _touch(c, *members)


# ---------- Buses ----------
def _distribution(c, eq_id: str) -> Dict[str, Any]:
    eq = _get_equipment(c, eq_id)
    if eq["kind"] != "distribution":
        raise _bad("BUSES_NOT_ALLOWED", f"{eq['name']} is a single element; only distribution elements have buses")
    return eq


def _check_bus_name_free(c, eq_id: str, name: str, exclude_id: str = "") -> None:
    row = _fetchone(
        c,
        "SELECT id FROM app_bus WHERE equipment_id=:e AND lower(name)=lower(:n) AND id<>:x",
        {"e": eq_id, "n": name, "x": exclude_id},
    )
    if row:
        raise _conflict("BUS_EXISTS", name)


def _bus_busy(c, bus_id: str) -> bool:
    return bool(
        _fetchone(c, "SELECT 1 AS x FROM app_bus_equipment WHERE bus_id=:b", {"b": bus_id})
        or _fetchone(c, "SELECT 1 AS x FROM app_bus_meter WHERE bus_id=:b", {"b": bus_id})
    )


def _remove_bus(c, bus_id: str) -> None:
    c.execute(text("DELETE FROM app_bus_type WHERE bus_id=:id"), {"id": bus_id})
    c.execute(text("DELETE FROM app_bus WHERE id=:id"), {"id": bus_id})


def _fix_last_coupler(c, eq_id: str) -> None:
    """The last bus has no neighbour to couple to."""
    last = _fetchone(
        c,
        "SELECT id FROM app_bus WHERE equipment_id=:e AND is_main=0 ORDER BY sort_order DESC, name DESC LIMIT 1",
        {"e": eq_id},
    )
    if last:
        c.execute(text("UPDATE app_bus SET coupled_next=0 WHERE id=:id"), {"id": last["id"]})


def list_buses(eq_id: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        _distribution(c, eq_id)
        return _buses(c, eq_id)


def create_bus(eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        _distribution(c, eq_id)
        _check_version(c, eq_id, if_match)
        existing = _buses(c, eq_id)
        if len(existing) >= _MAX_BUSES:
            raise _bad("BUS_LIMIT", f"at most {_MAX_BUSES} buses")
        if payload.get("name") is not None:
            name = _req_str(payload, "name", "NAME_REQUIRED")
        else:
            taken = {b["name"].lower() for b in existing}
            i = 0
            while _bus_label(i).lower() in taken:
                i += 1
            name = _bus_label(i)
        _check_bus_name_free(c, eq_id, name)
        order = max([b["sortOrder"] for b in existing], default=-1) + 1
        bus_id = _insert_bus(c, eq_id, name, order)
        _set_node_rules(c, _get_bus(c, bus_id), payload)
        _touch(c, eq_id)
        return _one_bus(c, bus_id)


def set_bus_count(eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> List[Dict[str, Any]]:
    """The "Bus sections" selector: add buses (Bus A, B, ...) at the end, or remove trailing ones."""
    count = _int(payload, "count", 1, _MAX_BUSES)
    with _conn() as c:
        _distribution(c, eq_id)
        _check_version(c, eq_id, if_match)
        existing = _buses(c, eq_id)
        if count < len(existing):
            drop = existing[count:]
            busy = [b["name"] for b in drop if _bus_busy(c, b["id"])]
            if busy:
                raise _conflict("BUS_NOT_EMPTY", ", ".join(busy) + " still have equipment or MFMs attached")
            for b in drop:
                _remove_bus(c, b["id"])
        else:
            taken = {b["name"].lower() for b in existing}
            order = max([b["sortOrder"] for b in existing], default=-1) + 1
            i = 0
            for _ in range(count - len(existing)):
                while _bus_label(i).lower() in taken:
                    i += 1
                _insert_bus(c, eq_id, _bus_label(i), order)
                taken.add(_bus_label(i).lower())
                order += 1
        _fix_last_coupler(c, eq_id)
        if count != len(existing):
            _touch(c, eq_id)
        return _buses(c, eq_id)


def update_bus(bus_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        if "name" in payload:
            name = _req_str(payload, "name", "NAME_REQUIRED")
            _check_bus_name_free(c, bus["equipment_id"], name, exclude_id=bus_id)
            c.execute(text("UPDATE app_bus SET name=:n WHERE id=:id"), {"n": name, "id": bus_id})
        if "sortOrder" in payload:
            c.execute(
                text("UPDATE app_bus SET sort_order=:s WHERE id=:id"),
                {"s": _int(payload, "sortOrder", -(10**6), 10**6), "id": bus_id},
            )
        if "coupledNext" in payload:
            coupled = _bool(payload, "coupledNext")
            if coupled:
                nxt = _fetchone(
                    c,
                    "SELECT id FROM app_bus WHERE equipment_id=:e AND is_main=0 AND "
                    "(sort_order > :s OR (sort_order = :s AND name > :n)) LIMIT 1",
                    {"e": bus["equipment_id"], "s": bus["sort_order"], "n": bus["name"]},
                )
                if not nxt:
                    raise _bad("NO_NEXT_BUS", "the last bus has no neighbour to couple to")
            c.execute(text("UPDATE app_bus SET coupled_next=:v WHERE id=:id"), {"v": 1 if coupled else 0, "id": bus_id})
        _set_node_rules(c, bus, payload)
        _touch(c, bus["equipment_id"])
        return _one_bus(c, bus_id)


def delete_bus(bus_id: str, if_match: Optional[str] = None) -> None:
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        n = _fetchone(
            c, "SELECT COUNT(*) AS n FROM app_bus WHERE equipment_id=:e AND is_main=0", {"e": bus["equipment_id"]}
        )["n"]
        if n <= 1:
            raise _conflict("LAST_BUS", "a distribution equipment keeps at least one bus")
        if _bus_busy(c, bus_id):
            raise _conflict("BUS_NOT_EMPTY", f"{bus['name']} still has equipment or MFMs attached")
        _remove_bus(c, bus_id)
        _fix_last_coupler(c, bus["equipment_id"])
        _touch(c, bus["equipment_id"])


# ---------- Connections (bus attachments + direct links) ----------
def _flow_edges(c) -> Dict[str, Set[str]]:
    """equipment -> equipment it feeds, over every connection.

    Bus outgoer / direct link: owner feeds member. Bus incomer: member feeds owner."""
    edges: Dict[str, Set[str]] = {}
    for r in _fetchall(
        c,
        "SELECT b.equipment_id AS owner, be.equipment_id AS member, be.role FROM app_bus_equipment be "
        "JOIN app_bus b ON b.id = be.bus_id",
    ):
        src, dst = (r["owner"], r["member"]) if r["role"] == "outgoer" else (r["member"], r["owner"])
        edges.setdefault(src, set()).add(dst)
    return edges


def _reaches(edges: Dict[str, Set[str]], start: str, target: str) -> bool:
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        for nxt in edges.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _ordered_members(c, node_id: str, role: str) -> List[str]:
    return [
        r["equipment_id"]
        for r in _fetchall(
            c,
            "SELECT equipment_id FROM app_bus_equipment WHERE bus_id=:b AND role=:r ORDER BY sort_order, equipment_id",
            {"b": node_id, "r": role},
        )
    ]


def _renumber(c, node_id: str, role: str, ordered: List[str]) -> None:
    """Positions 0..n-1 in the given order (keeps them compact and unique)."""
    for i, eq_id in enumerate(ordered):
        c.execute(
            text("UPDATE app_bus_equipment SET sort_order=:s WHERE bus_id=:b AND role=:r AND equipment_id=:e"),
            {"s": i, "b": node_id, "r": role, "e": eq_id},
        )


def _spare_meters(c, node: Dict[str, Any]) -> int:
    """Outgoing MFMs on a bus with no relation (spares). Each takes an outgoing point."""
    if node["is_main"]:
        return 0
    return _fetchone(
        c, "SELECT COUNT(*) AS n FROM app_bus_meter WHERE bus_id=:b AND role='outgoer' AND equipment_id IS NULL",
        {"b": node["id"]},
    )["n"]


def _side_used(c, node: Dict[str, Any], side: str) -> int:
    """Points in use on a side: connections, plus spare MFMs on a bus's outgoing side."""
    used = len(_connections_of(c, node, side))
    return used + (_spare_meters(c, node) if side == "outgoer" else 0)


def _check_side(c, node: Dict[str, Any], side: str, other: Dict[str, Any], label: str, freed: int = 0) -> None:
    """Allowed types + capacity of one side of a node, for connecting `other`.
    `freed`: points the caller releases in the same step (a spare MFM taken over)."""
    allowed = _node_types(c, [node["id"]])[node["id"]][side]
    if allowed and other.get("type_id") not in allowed:
        raise _bad("TYPE_NOT_ALLOWED", f"{label} {side}s must be of type: {', '.join(allowed)}")
    cap = node["incomers" if side == "incomer" else "outgoers"]
    if _side_used(c, node, side) - freed >= cap:
        if node["is_main"]:
            word = "incoming" if side == "incomer" else "outgoing"
            raise _conflict("NO_SPARE", f"{label} allows {cap} {word} connection(s), all in use")
        raise _conflict("NO_SPARE", f"{label} has {cap} {side}(s), all in use; raise the count first")


def _connect(c, node: Dict[str, Any], role: str, eq: Dict[str, Any], position: Optional[int]) -> None:
    """Insert a connection row at `position` (append if None) and renumber."""
    ordered = _ordered_members(c, node["id"], role)
    c.execute(
        text("INSERT INTO app_bus_equipment (bus_id, equipment_id, role, sort_order) VALUES (:b, :e, :r, 0)"),
        {"b": node["id"], "e": eq["id"], "r": role},
    )
    pos = len(ordered) if position is None else min(position, len(ordered))
    ordered.insert(pos, eq["id"])
    _renumber(c, node["id"], role, ordered)


def _disconnect(c, node_id: str, eq_id: str) -> str:
    row = _fetchone(c, "SELECT role FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e", {"b": node_id, "e": eq_id})
    if not row:
        raise _missing("NOT_ATTACHED", eq_id)
    meter = _fetchone(c, "SELECT table_id FROM app_bus_meter WHERE bus_id=:b AND equipment_id=:e", {"b": node_id, "e": eq_id})
    if meter and row["role"] == "incomer":
        # Only an outgoing MFM can stay behind as a spare.
        raise _conflict("RELATION_METERED", f"incomer {eq_id} has MFM {meter['table_id']}; remove the MFM first")
    c.execute(text("DELETE FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e"), {"b": node_id, "e": eq_id})
    # The outgoing MFM stays on the bus with no relation: a spare.
    c.execute(text("UPDATE app_bus_meter SET equipment_id=NULL WHERE bus_id=:b AND equipment_id=:e"), {"b": node_id, "e": eq_id})
    _renumber(c, node_id, row["role"], _ordered_members(c, node_id, row["role"]))
    return row["role"]


def _move(c, node_id: str, eq_id: str, payload: Dict[str, Any]) -> None:
    position = _int(payload, "position", 0, 10**6)
    row = _fetchone(c, "SELECT role FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e", {"b": node_id, "e": eq_id})
    if not row:
        raise _missing("NOT_ATTACHED", eq_id)
    ordered = [x for x in _ordered_members(c, node_id, row["role"]) if x != eq_id]
    ordered.insert(min(position, len(ordered)), eq_id)
    _renumber(c, node_id, row["role"], ordered)


def _both(c, owner_id: str, member_id: str, bus_id: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "owner": _equipment_out(c, _get_equipment(c, owner_id)),
        "attached": _equipment_out(c, _get_equipment(c, member_id)),
    }
    if bus_id:
        out["bus"] = _one_bus(c, bus_id)
    return out


def attach_equipment(bus_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    """Attach an equipment to a bus as an incomer (it feeds the bus) or outgoer (fed by it).

    `spareTableId` (outgoer only): connect it at a spare MFM's point; that MFM
    then measures the new relation."""
    eq_id = _req_str(payload, "equipmentId", "EQUIPMENT_REQUIRED")
    role = payload.get("role")
    if role not in _ROLES:
        raise _bad("ROLE_INVALID", "role must be incomer or outgoer")
    position = _opt_position(payload)
    spare = payload.get("spareTableId")
    if spare is not None and (not isinstance(spare, str) or not spare.strip()):
        raise _bad("SPARE_INVALID")
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        if spare is not None:
            spare = spare.strip()
            if role != "outgoer" or not _fetchone(
                c, "SELECT 1 AS x FROM app_bus_meter WHERE bus_id=:b AND table_id=:d AND role='outgoer' AND equipment_id IS NULL",
                {"b": bus_id, "d": spare},
            ):
                raise _bad("NOT_A_SPARE", f"{spare} is not a spare MFM of {bus['name']}")
        panel = _get_equipment(c, bus["equipment_id"])
        eq = _get_equipment(c, eq_id)
        if eq_id == panel["id"]:
            raise _bad("SELF_ATTACH", "a panel cannot be attached to its own bus")
        current = _fetchone(c, "SELECT role FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e", {"b": bus_id, "e": eq_id})
        if current:
            raise _conflict("ALREADY_ATTACHED", f"{eq['name']} is already a {current['role']} of {bus['name']}")
        _check_side(c, bus, role, eq, bus["name"], freed=1 if spare else 0)
        # The other end: a single equipment's own node. Feeding the bus (incomer)
        # uses its outgoing side; being fed (outgoer) uses its incoming side.
        if eq["kind"] == "single":
            _check_side(c, _main_node(c, eq_id), "outgoer" if role == "incomer" else "incomer", panel, eq["name"])
        src, dst = (panel, eq) if role == "outgoer" else (eq, panel)
        if _reaches(_flow_edges(c), dst["id"], src["id"]):
            raise _bad("CYCLE", f"{dst['name']} already feeds {src['name']}")
        _connect(c, bus, role, eq, position)
        if spare:
            c.execute(text("UPDATE app_bus_meter SET equipment_id=:e WHERE bus_id=:b AND table_id=:d"),
                      {"e": eq_id, "b": bus_id, "d": spare})
        _touch(c, panel["id"], eq_id)
        return _both(c, panel["id"], eq_id, bus_id)


def detach_equipment(bus_id: str, eq_id: str, if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        _disconnect(c, bus_id, eq_id)
        _touch(c, bus["equipment_id"], eq_id)
        return _both(c, bus["equipment_id"], eq_id, bus_id)


def move_attachment(bus_id: str, eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    """Reorder a feeder within its side of the bus (position 0 = first)."""
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        _move(c, bus_id, eq_id, payload)
        _touch(c, bus["equipment_id"], eq_id)
        return _both(c, bus["equipment_id"], eq_id, bus_id)


def _single(c, eq_id: str, code: str, hint: str) -> Dict[str, Any]:
    eq = _get_equipment(c, eq_id)
    if eq["kind"] != "single":
        raise _bad(code, hint)
    return eq


def connect_direct(eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    """Direct link single -> single (e.g. Grid -> Transformer): `eq_id` feeds `equipmentId`."""
    target_id = _req_str(payload, "equipmentId", "EQUIPMENT_REQUIRED")
    position = _opt_position(payload)
    with _conn() as c:
        src = _single(c, eq_id, "USE_BUS", "distribution panels connect through their buses")
        _check_version(c, eq_id, if_match)
        dst = _get_equipment(c, target_id)
        if dst["kind"] != "single":
            raise _bad("USE_BUS", f"attach {src['name']} to a bus of {dst['name']} as an incomer instead")
        if target_id == eq_id:
            raise _bad("SELF_ATTACH", "an equipment cannot feed itself")
        node = _main_node(c, eq_id)
        if _fetchone(c, "SELECT 1 AS x FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e", {"b": node["id"], "e": target_id}):
            raise _conflict("ALREADY_ATTACHED", f"{src['name']} already feeds {dst['name']}")
        _check_side(c, node, "outgoer", dst, src["name"])
        _check_side(c, _main_node(c, target_id), "incomer", src, dst["name"])
        if _reaches(_flow_edges(c), target_id, eq_id):
            raise _bad("CYCLE", f"{dst['name']} already feeds {src['name']}")
        _connect(c, node, "outgoer", dst, position)
        _touch(c, eq_id, target_id)
        return _both(c, eq_id, target_id)


def disconnect_direct(eq_id: str, target_id: str, if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        _single(c, eq_id, "USE_BUS", "distribution panels connect through their buses")
        _check_version(c, eq_id, if_match)
        _disconnect(c, _main_node(c, eq_id)["id"], target_id)
        _touch(c, eq_id, target_id)
        return _both(c, eq_id, target_id)


def move_direct(eq_id: str, target_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        _single(c, eq_id, "USE_BUS", "distribution panels connect through their buses")
        _check_version(c, eq_id, if_match)
        _move(c, _main_node(c, eq_id)["id"], target_id, payload)
        _touch(c, eq_id, target_id)
        return _both(c, eq_id, target_id)


# ---------- MFMs (logger tables) ----------
def meter_owner(table_id: str) -> Optional[Dict[str, Any]]:
    """The element a logger table is attached to as an MFM (on any node), or None."""
    with _conn() as c:
        return _meter_owner(c, table_id)


def device_meter_owner(device_id: str) -> Optional[Dict[str, Any]]:
    """An element one of this device's logger tables is attached to, or None."""
    with _conn() as c:
        return _fetchone(
            c,
            "SELECT e.id, e.name, b.id AS bus_id, b.name AS bus_name, b.is_main, t.name AS table_name FROM app_bus_meter m "
            "JOIN app_device_tables t ON t.id = m.table_id JOIN app_bus b ON b.id = m.bus_id "
            "JOIN app_equipment e ON e.id = b.equipment_id WHERE t.device_id=:d LIMIT 1",
            {"d": device_id},
        )


def _meter_owner(c, table_id: str) -> Optional[Dict[str, Any]]:
    return _fetchone(
        c,
        "SELECT e.id, e.name, b.id AS bus_id, b.name AS bus_name, b.is_main FROM app_bus_meter m "
        "JOIN app_bus b ON b.id = m.bus_id JOIN app_equipment e ON e.id = b.equipment_id WHERE m.table_id=:t",
        {"t": table_id},
    )


def _where(owner: Dict[str, Any]) -> str:
    return owner["name"] if owner["is_main"] else f"{owner['name']} {owner['bus_name']}"


def _add_meter(c, node: Dict[str, Any], table_id: str, role: Optional[str], feeder: Optional[str] = None) -> None:
    if not _fetchone(c, "SELECT id FROM app_device_tables WHERE id=:t", {"t": table_id}):
        raise _missing("TABLE_NOT_FOUND", table_id)
    owner = _meter_owner(c, table_id)
    if owner:
        if owner["bus_id"] == node["id"]:
            raise _conflict("METER_ALREADY_ATTACHED", f"already on {_where(owner)}")
        raise _conflict("METER_IN_USE", f"attached to {_where(owner)}")
    if role is not None:
        _check_meter_slot(c, node, role, feeder)
    order = _fetchone(
        c, "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM app_bus_meter WHERE bus_id=:b", {"b": node["id"]}
    )["n"]
    c.execute(
        text("INSERT INTO app_bus_meter (bus_id, table_id, role, equipment_id, sort_order) VALUES (:b, :t, :r, :f, :s)"),
        {"b": node["id"], "t": table_id, "r": role, "f": feeder, "s": order},
    )


def _check_meter_slot(c, node: Dict[str, Any], role: str, feeder: Optional[str], moving: Optional[str] = None) -> None:
    """Where a bus MFM may go: the slot of an attached incomer / outgoer (one MFM
    per relation), or, outgoing only, a spare that takes a free outgoing point.
    `moving` is the table being re-slotted (its current slot does not count)."""
    if feeder is None:
        if role == "incomer":
            raise _bad("EQUIPMENT_REQUIRED", "an incoming MFM measures an attached incomer: give equipmentId")
        if _side_used(c, node, "outgoer") >= node["outgoers"]:
            raise _conflict("NO_FREE_POINT", f"{node['name']} has {node['outgoers']} outgoer point(s), none free for a spare MFM")
        return
    if not _fetchone(
        c, "SELECT 1 AS x FROM app_bus_equipment WHERE bus_id=:b AND equipment_id=:e AND role=:r",
        {"b": node["id"], "e": feeder, "r": role},
    ):
        raise _bad("FEEDER_NOT_ON_BUS", f"{feeder} is not a {role} of {node['name']}")
    taken = _fetchone(
        c, "SELECT table_id FROM app_bus_meter WHERE bus_id=:b AND equipment_id=:e", {"b": node["id"], "e": feeder}
    )
    if taken and taken["table_id"] != moving:
        raise _conflict("RELATION_METERED", f"{feeder} already has MFM {taken['table_id']}")


def list_meters(eq_id: str) -> List[Dict[str, Any]]:
    """All MFMs of an equipment (its own, or on any of its buses)."""
    with _conn() as c:
        _get_equipment(c, eq_id)
        ids = [b["id"] for b in _fetchall(c, "SELECT id FROM app_bus WHERE equipment_id=:e ORDER BY sort_order", {"e": eq_id})]
        met = _node_meters(c, ids)
        return [m for i in ids for m in met[i]]


def attach_meter(eq_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> List[Dict[str, Any]]:
    """Single equipment: attach an MFM to the equipment itself."""
    table_id = _req_str(payload, "tableId", "TABLE_REQUIRED")
    with _conn() as c:
        eq = _get_equipment(c, eq_id)
        if eq["kind"] != "single":
            raise _bad("USE_BUS_METERS", "distribution panels meter their buses: POST /equipment/buses/{busId}/meters")
        _check_version(c, eq_id, if_match)
        node = _main_node(c, eq_id)
        _add_meter(c, node, table_id, None)
        _touch(c, eq_id)
        return _node_meters(c, [node["id"]])[node["id"]]


def detach_meter(eq_id: str, table_id: str, if_match: Optional[str] = None) -> List[Dict[str, Any]]:
    with _conn() as c:
        _get_equipment(c, eq_id)
        _check_version(c, eq_id, if_match)
        res = c.execute(
            text(
                "DELETE FROM app_bus_meter WHERE table_id=:t AND bus_id IN (SELECT id FROM app_bus WHERE equipment_id=:e)"
            ),
            {"t": table_id, "e": eq_id},
        )
        if not res.rowcount:
            raise _missing("METER_NOT_ATTACHED", table_id)
        _touch(c, eq_id)
    return list_meters(eq_id)


def attach_bus_meter(bus_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    """Distribution panel: attach an MFM to a bus, metering an incomer or outgoer
    point; optionally naming the feeder (attached equipment) it measures."""
    table_id = _req_str(payload, "tableId", "TABLE_REQUIRED")
    role = payload.get("role")
    if role not in _ROLES:
        raise _bad("ROLE_INVALID", "role must be incomer or outgoer")
    feeder = payload.get("equipmentId")
    if feeder is not None and (not isinstance(feeder, str) or not feeder.strip()):
        raise _bad("EQUIPMENT_INVALID")
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        _add_meter(c, bus, table_id, role, feeder.strip() if feeder else None)
        _touch(c, bus["equipment_id"])
        return _one_bus(c, bus_id)


def assign_bus_meter(bus_id: str, table_id: str, payload: Dict[str, Any], if_match: Optional[str] = None) -> Dict[str, Any]:
    """Move a bus MFM to another relation's slot ({equipmentId}) or, outgoing
    only, make it a spare ({equipmentId: null}). Its role stays."""
    if "equipmentId" not in payload:
        raise _bad("EQUIPMENT_REQUIRED", "give equipmentId (an attached feeder) or null for a spare")
    feeder = payload["equipmentId"]
    if feeder is not None and (not isinstance(feeder, str) or not feeder.strip()):
        raise _bad("EQUIPMENT_INVALID")
    feeder = feeder.strip() if feeder else None
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        row = _fetchone(c, "SELECT role, equipment_id FROM app_bus_meter WHERE bus_id=:b AND table_id=:t", {"b": bus_id, "t": table_id})
        if not row:
            raise _missing("METER_NOT_ATTACHED", table_id)
        if row["equipment_id"] != feeder:
            # To a spare: needs a free outgoing point (it leaves its relation's
            # point to the feeder). From a spare to a relation: frees one.
            _check_meter_slot(c, bus, row["role"], feeder, moving=table_id)
            c.execute(text("UPDATE app_bus_meter SET equipment_id=:f WHERE bus_id=:b AND table_id=:t"),
                      {"f": feeder, "b": bus_id, "t": table_id})
            _touch(c, bus["equipment_id"])
        return _one_bus(c, bus_id)


def detach_bus_meter(bus_id: str, table_id: str, if_match: Optional[str] = None) -> Dict[str, Any]:
    with _conn() as c:
        bus = _get_bus(c, bus_id)
        _check_version(c, bus["equipment_id"], if_match)
        res = c.execute(text("DELETE FROM app_bus_meter WHERE bus_id=:b AND table_id=:t"), {"b": bus_id, "t": table_id})
        if not res.rowcount:
            raise _missing("METER_NOT_ATTACHED", table_id)
        _touch(c, bus["equipment_id"])
        return _one_bus(c, bus_id)


def available_meters() -> List[Dict[str, Any]]:
    """Logger tables not attached anywhere yet (the MFM picker), with schema and device."""
    with _conn() as c:
        info = _meter_info(c)
        taken = {r["table_id"] for r in _fetchall(c, "SELECT table_id FROM app_bus_meter")}
    return sorted((v for k, v in info.items() if k not in taken), key=lambda d: (d["tableName"] or "").lower())
