"""Push the electrical map to the EMS sidebar (POST /equipment/push/ems).

The EMS backend's ``POST /api/ems/push/`` replaces its whole sidebar in one
request: categories, each with its distribution panels (incoming / outgoing /
spare meters) and standalone meters, plus the logger schemas the meters are
read with. This builds that body from the map and sends it.

Map -> EMS sidebar (the element's category is the sidebar: EMS; its kind
decides panel or standalone meters; its type is the nav category; zones are
not part of the EMS nav)
* type -> nav category, labelled with the type name in the plural ("HT Panel"
  -> "HT Panels"), in type order. The EMS matches categories by label, so this
  lands in its existing "HT Panels". Types with nothing to show are left out.
* distribution element -> panel, matched by name on the EMS side.
  ``panel_kind`` comes from the type's name (HT / PCC / AMF / UPS, else
  distribution_panel); nameplate ``nominal_voltage_v`` from its voltage field.
  Its buses' MFMs, bus by bus in slot order: incomer slot -> incoming,
  outgoer slot -> outgoing, spare -> spare.
* An MFM on a feed between two panels is listed at both ends (outgoing of the
  feeding panel, incoming of the fed one) unless that end has its own MFM for
  the same feed: in the EMS one meter may sit in several panels.
* MFMs of a single element -> standalone meters of its type's category.
* meter = its logger table (``table_name``); the EMS names a new meter after
  the device. ``schema`` = the table's schema (EMS code = schema name,
  ``logger_id`` = schema id, version 1); nameplate ``nominal_voltage_v`` from
  the device.

Left out, and listed in ``skipped``: elements without a type, spare elements
("not on the map"), and MFMs the EMS cannot bind (table not migrated, no
device, or a device with several migrated tables: the EMS binds a meter
through its device). Source and BMS elements are not part of the EMS sidebar.

The EMS side is a full sync: panels and categories missing from the push are
retired / hidden there. Without ``commit`` it is a preview (the EMS rolls it
back). Configuration (backend env): EMS_API_URL, EMS_API_USER and
EMS_API_PASSWORD (an active EMS staff user, sent as HTTP Basic), EMS_API_TIMEOUT.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import equipment as eq
from .appdb import _fetchall, load_schemas

logger = logging.getLogger(__name__)

CATEGORY = "ems"
TIMESTAMP_COLUMN = "timestamp_utc"
_PANEL_KINDS = (("HT", "ht_panel"), ("PCC", "pcc_panel"), ("AMF", "amf_panel"), ("UPS", "ups_panel"))
_VOLTS = {"kv": 1000.0, "v": 1.0}


def _config() -> Tuple[str, str, str, float]:
    url = (os.environ.get("EMS_API_URL") or "http://127.0.0.1:18889").rstrip("/")
    user, password = os.environ.get("EMS_API_USER") or "", os.environ.get("EMS_API_PASSWORD") or ""
    if not user or not password:
        raise eq.EquipmentError(503, "EMS_NOT_CONFIGURED", "set EMS_API_USER and EMS_API_PASSWORD in the backend env")
    try:
        timeout = float(os.environ.get("EMS_API_TIMEOUT") or 120)
    except ValueError:
        timeout = 120.0
    return url, user, password, timeout


def _plural(name: str) -> str:
    """Nav category label of a type, as the EMS names them: "HT Panel" -> "HT Panels"."""
    if name[-1:].lower() == "s":
        return name
    if len(name) > 1 and name[-1:].lower() == "y" and name[-2].lower() not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _panel_kind(type_name: Optional[str]) -> str:
    """Whole words of the type name: "HT Panel" -> ht_panel; "LT Panel" -> distribution_panel."""
    words = set(re.split(r"[^A-Z0-9]+", (type_name or "").upper()))
    return next((kind for word, kind in _PANEL_KINDS if word in words), "distribution_panel")


def _volts(values: Dict[str, Any], fields: List[Dict[str, Any]]) -> Optional[float]:
    """Volts of the element's voltage field (role voltage, else voltage.in)."""
    by_role = {f.get("role"): f["id"] for f in fields if f.get("role")}
    v = values.get(by_role.get("voltage") or by_role.get("voltage.in") or "")
    factor = _VOLTS.get(str((v or {}).get("unit") or "").lower())
    return float(v["value"]) * factor if v and factor else None


def _number(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _whole(v: Any) -> Optional[int]:
    n = _number(v)
    return int(n) if n is not None and n.is_integer() and n >= 0 else None


def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}


def _schema_def(s: Dict[str, Any]) -> Dict[str, Any]:
    """An EMS schema definition. Fields in key order: the EMS stores each
    field's position, and a re-push must match the stored version exactly."""
    fields = []
    for f in sorted(s["fields"], key=lambda f: f["key"]):
        formula = (f.get("formula") or "").strip()
        fields.append(_compact({
            "name": f["key"],
            "kind": "derived" if formula else "measured",
            "data_type": f.get("type"),
            "unit": f.get("unit"),
            "address": None if formula else f.get("address"),
            "scale": _number(f.get("scale")),
            "formula": formula,
            "evaluation_order": _whole(f.get("eval_order")) if formula else None,
            "description": f.get("desc"),
        }))
    return _compact({
        "code": s["name"], "version": 1, "name": s["name"], "logger_id": s["id"],
        "timestamp_column": TIMESTAMP_COLUMN, "description": s.get("description"), "fields": fields,
    })


def build_payload() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """(EMS push body, what was left out and why) from the current map."""
    items = eq.list_equipment(category_id=CATEGORY)
    types = eq.list_types()
    type_fields = {t["id"]: t["fields"] for t in types}
    schemas = {s["id"]: s for s in load_schemas()}
    with eq._conn() as c:
        tables = {r["id"]: r for r in _fetchall(
            c, "SELECT t.id, t.name, t.schema_id, t.status, t.device_id, d.nominal_voltage "
            "FROM app_device_tables t LEFT JOIN app_devices d ON d.id = t.device_id"
        )}
    migrated: Dict[str, set] = {}
    for t in tables.values():
        if t["status"] == "migrated" and t["device_id"]:
            migrated.setdefault(t["device_id"], set()).add(t["name"])

    skipped: List[Dict[str, Any]] = []
    used_schemas: Dict[str, None] = {}

    def meter(m: Dict[str, Any], element: str) -> Optional[Dict[str, Any]]:
        t = tables.get(m["tableId"]) or {}
        name = t.get("name") or m["tableId"]
        reason = None
        if t.get("status") != "migrated":
            reason = "table not migrated"
        elif not t.get("device_id"):
            reason = "table has no device"
        elif len(migrated[t["device_id"]]) > 1:
            reason = "its device has several migrated tables (" + ", ".join(sorted(migrated[t["device_id"]])) + ")"
        if reason:
            skipped.append({"table": name, "element": element, "reason": reason})
            return None
        out: Dict[str, Any] = {"table_name": name}
        if t.get("schema_id") in schemas:
            used_schemas[t["schema_id"]] = None
            out["schema"] = schemas[t["schema_id"]]["name"]
        if _number(t.get("nominal_voltage")):
            out["nameplate"] = {"nominal_voltage_v": _number(t["nominal_voltage"])}
        return out

    content: Dict[str, Dict[str, list]] = {t["id"]: {"panels": [], "meters": []} for t in types}
    panels: Dict[str, Dict[str, Any]] = {}  # element id -> panel
    for i in items:
        if i["kind"] == "single" and not i["metering"]["meters"]:
            continue  # nothing to show
        if i["spare"] or not i.get("typeId"):
            skipped.append({"element": i["name"], "reason": "spare (not on the map)" if i["spare"] else "no type"})
            continue
        if i["kind"] == "single":
            content[i["typeId"]]["meters"] += [x for m in i["metering"]["meters"] if (x := meter(m, i["name"]))]
            continue
        p: Dict[str, Any] = {"name": i["name"], "panel_kind": _panel_kind(i.get("typeName"))}
        volts = _volts(i["values"], type_fields.get(i.get("typeId"), []))
        if volts:
            p["nameplate"] = {"nominal_voltage_v": volts}
        panels[i["id"]] = {**p, "incoming": [], "outgoing": [], "spare": []}
        content[i["typeId"]]["panels"].append(panels[i["id"]])

    # Members, once every pushed panel is known (a feed between two panels is
    # listed at both ends).
    own = set()  # (panel id, side, element at the other end) metered at the panel itself
    feeds = []
    for i in items:
        p = panels.get(i["id"])
        if p is None:
            continue
        for b in i["buses"]:
            for side, slots in (("incoming", b["incomingEquipment"]), ("outgoing", b["outgoingEquipment"])):
                for slot in slots:
                    x = meter(slot["meter"], i["name"]) if slot.get("meter") else None
                    if x:
                        p[side].append(x)
                        own.add((i["id"], side, slot["id"]))
                        if slot["id"] in panels:
                            feeds.append((slot["id"], "outgoing" if side == "incoming" else "incoming", i["id"], x))
            p["spare"] += [x for m in b["spares"] if (x := meter(m, i["name"]))]
    for other, side, panel_id, x in feeds:
        if (other, side, panel_id) not in own:
            panels[other][side].append(x)

    categories = [
        {"label": _plural(t["name"]), **content[t["id"]]}
        for t in types if content[t["id"]]["panels"] or content[t["id"]]["meters"]
    ]
    body = {"schemas": [_schema_def(schemas[s]) for s in used_schemas], "categories": categories}
    return body, skipped


def push(commit: bool = False) -> Dict[str, Any]:
    """Build the body and send it to the EMS. Returns what was sent, what was
    left out, and the EMS report; ``success`` is the EMS's ``ok``."""
    url, user, password, timeout = _config()
    body, skipped = build_payload()
    if not body["categories"]:
        raise eq._bad("NOTHING_TO_PUSH", "no typed EMS element has a panel or an MFM to show")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{url}/api/ems/push/", params={"commit": "true"} if commit else None, json=body, auth=(user, password)
            )
    except httpx.HTTPError as e:
        raise eq.EquipmentError(502, "EMS_UNREACHABLE", f"{url}: {e}")
    if resp.status_code == 401:
        raise eq.EquipmentError(502, "EMS_AUTH_FAILED", "the EMS refused EMS_API_USER (an active staff user is needed)")
    try:
        report = resp.json()
    except ValueError:
        report = None
    if resp.status_code not in (200, 400) or not isinstance(report, dict):
        raise eq.EquipmentError(502, "EMS_BAD_RESPONSE", f"HTTP {resp.status_code} from {url}/api/ems/push/")
    ok = resp.status_code == 200 and bool(report.get("ok"))
    if commit:
        logger.info("EMS push to %s: ok=%s committed=%s summary=%s", url, ok, report.get("committed"), report.get("summary"))
    return {"success": ok, "committed": bool(report.get("committed")), "skipped": skipped, "request": body, "ems": report}
