"""Builds the EMS import workbook (Elements, Buses, Connections, Meters) from
ems_mfm.json (parse_ems_mfm.py). Usage: python gen_equipment_xlsx.py <ems_mfm.json> <out.xlsx>"""
import json, sys
from collections import Counter
from openpyxl import Workbook

d = json.load(open(sys.argv[1]))
td, dv = d["table_device"], d["device_volts"]
TYPE = {"ht": "HT Panel", "amf": "AMF Panel", "pcc": "PCC Panel", "ups": "UPS Panel", "utility": "Utility Panel"}
ROLE = {"Incomings": "incoming", "Outgoings": "outgoing", "Spare": "spare"}
CONN = {"Incomings": "incomer", "Outgoings": "outgoer"}
SOURCE = "EMS inventory 2026-10-30"


def volts(tables):
    v = {dv.get(td[t]) for t in tables}
    if len(v) != 1 or None in v:
        return None
    n = float(v.pop())
    return f"{n / 1000:g} kV" if n >= 1000 else f"{n:g} V"


taken = Counter()


def element_name(mfm):
    """The MFM's own name, made unique (element names are unique, ignoring case)."""
    taken[mfm.lower()] += 1
    return mfm if taken[mfm.lower()] == 1 else f"{mfm}_{taken[mfm.lower()]}"


elements, buses, connections, meters = [], [], [], []
for p in d["panels"]:
    inc = [m for m in p["members"] if m["role"] == "Incomings"]
    elements.append([p["name"], "distribution", TYPE[p["category"]], volts(m["table"] for m in inc), None])
    n = Counter(m["role"] for m in p["members"])
    buses.append([p["name"], "Bus A", n["Incomings"], n["Outgoings"] + n["Spare"]])
    for role in ("Incomings", "Outgoings", "Spare"):
        for m in (x for x in p["members"] if x["role"] == role):
            if role == "Spare":
                meters.append([m["table"], p["name"], "Bus A", "spare", None])
                continue
            el = element_name(m["mfm"])
            elements.append([el, "single", None, None,
                             f"Named after its MFM {m['mfm']} ({m['table']}), from the {SOURCE}; asset not yet identified"])
            connections.append([p["name"], "Bus A", CONN[role], el])
            meters.append([m["table"], p["name"], "Bus A", ROLE[role], el])
for m in d["standalone"]:
    el = element_name(m["mfm"])
    elements.append([el, "single", "Production Panel", volts([m["table"]]), f"Standalone MFM {m['table']}, from the {SOURCE}"])
    meters.append([m["table"], el, None, None, None])

wb = Workbook()
wb.remove(wb.active)
for title, header, rows in (
    ("Elements", ["name", "kind", "type", "bus_voltage", "description"], elements),
    ("Buses", ["panel", "bus", "incomers", "outgoers"], buses),
    ("Connections", ["panel", "bus", "role", "element"], connections),
    ("Meters", ["table", "element", "bus", "role", "measures"], meters),
):
    ws = wb.create_sheet(title)
    ws.append(header)
    for r in rows:
        ws.append(r)
wb.save(sys.argv[2])
renamed = [e[0] for e in elements if e[0] not in {m["mfm"] for p in d["panels"] for m in p["members"]} | {m["mfm"] for m in d["standalone"]} | {p["name"] for p in d["panels"]}]
print(f"elements {len(elements)} (panels {len(d['panels'])}), buses {len(buses)}, connections {len(connections)}, meters {len(meters)}; renamed: {renamed}")
