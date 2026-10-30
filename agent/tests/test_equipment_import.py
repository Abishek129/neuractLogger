"""Tier 1 — EMS elements from a spreadsheet (POST /equipment/import/ems)."""
from __future__ import annotations

import io

from openpyxl import Workbook, load_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(**sheets) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, data: bytes, name="plant.xlsx", dry=False, ctype=XLSX):
    return client.post("/equipment/import/ems" + ("?dryRun=true" if dry else ""), files={"file": (name, data, ctype)})


PLANT = dict(
    Elements=[
        ["Name", "Kind", "Type", "Max Incomers", "Max Outgoers", "Spare", "Description",
         "Primary voltage", "Secondary voltage", "Rated capacity", "Phase", "Bus / operating voltage", "Supply voltage", "Voltage"],
        ["GRID-01", "single", "Source", None, 1, None, "Utility", None, None, None, None, None, None, "33 kV"],
        ["TF-01", "single", "Transformer", 1, 1, "no", None, "33 kV", "11 kV", "20 MVA", "3 Phase", None, None, None],
        ["PCC-01", "Distribution", "LT Panel", None, None, None, None, None, None, None, None, "415 V", None, None],
        ["AHU-01", "single", "load", None, None, None, None, None, None, None, "3 Phase", None, 415, None],
    ],
    Buses=[
        ["panel", "bus", "incomers", "outgoers", "incoming types", "outgoing types"],
        ["PCC-01", "Bus 1", 1, 2, "Transformer", "Load"],
        ["PCC-01", "Bus 2", 0, 1, None, None],
    ],
    Connections=[
        ["panel", "bus", "role", "element", "position"],
        ["GRID-01", None, "outgoer", "TF-01", None],
        ["PCC-01", "Bus 1", "incomer", "TF-01", 1],
        ["PCC-01", "Bus 1", "outgoer", "AHU-01", 1],
    ],
)


def _items(client):
    return {i["name"]: i for i in client.get("/equipment").json()["items"]}


def test_template_lists_sheets_fields_and_types(client):
    r = client.get("/equipment/import/ems/template")
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Elements", "Buses", "Connections", "Meters", "Types"]
    header = [c.value for c in next(wb["Elements"].iter_rows(max_row=1))]
    assert header[:10] == ["name", "kind", "type", "zone", "max incomers", "max outgoers", "incoming types",
                           "outgoing types", "spare", "description"]
    assert "Primary voltage" in header and "Supply voltage" in header
    types = {row[0] for row in wb["Types"].iter_rows(min_row=2, values_only=True)}
    assert {"Transformer", "Load", "LT Panel"} <= types


def test_dry_run_then_import_a_plant(client):
    data = _xlsx(**PLANT)
    r = _upload(client, data, dry=True)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert (rep["success"], rep["dryRun"], rep["saved"]) == (True, True, False)
    assert rep["summary"]["elements"]["created"] == 4 and rep["summary"]["buses"]["created"] == 2
    assert rep["summary"]["connections"]["created"] == 3 and rep["summary"]["errors"] == 0
    assert _items(client) == {}  # nothing saved

    r = _upload(client, data)
    assert r.status_code == 200 and r.json()["saved"] is True, r.text
    items = _items(client)
    assert set(items) == {"GRID-01", "TF-01", "PCC-01", "AHU-01"}
    assert {i["categoryId"] for i in items.values()} == {"ems"}
    tf, pcc, ahu = items["TF-01"], items["PCC-01"], items["AHU-01"]
    assert tf["values"]["rated_capacity"] == {"value": 20.0, "unit": "MVA"} and tf["voltage"]["text"] == "33 kV → 11 kV"
    assert ahu["values"]["supply_voltage"] == {"value": 415.0, "unit": "V"} and ahu["nameplate"]["complete"]
    assert items["GRID-01"]["description"] == "Utility"
    # The new panel's automatic "Bus A" became the sheet's first bus.
    assert [(b["name"], b["incomers"], b["outgoers"]) for b in pcc["buses"]] == [("Bus 1", 1, 2), ("Bus 2", 0, 1)]
    bus1 = pcc["buses"][0]
    assert (bus1["incomingTypes"], bus1["outgoingTypes"]) == (["transformer"], ["load"])
    assert [e["name"] for e in bus1["incomingEquipment"]] == ["TF-01"]
    assert [e["name"] for e in bus1["outgoingEquipment"]] == ["AHU-01"]
    assert [e["name"] for e in items["GRID-01"]["outgoingEquipment"]] == ["TF-01"]  # direct link
    assert tf["readiness"]["ready"] is True  # fed by GRID-01, feeds PCC-01 Bus 1

    # Importing the same file again creates nothing new.
    r = _upload(client, data)
    rep = r.json()
    assert r.status_code == 200 and rep["summary"]["elements"]["created"] == 0
    assert rep["summary"]["connections"] == {"created": 0, "updated": 0, "unchanged": 3}
    assert len(_items(client)) == 4 and len(_items(client)["PCC-01"]["buses"]) == 2


def test_any_error_saves_nothing_and_reports_every_row(client):
    data = _xlsx(
        Elements=[
            ["name", "kind", "type", "Primary voltage", "Colour"],
            ["OK-1", "single", "Transformer", "33 kV", None],
            ["NO-KIND", None, "Load", None, None],
            ["BAD-COL", "single", "Load", None, "red"],
            ["BAD-QTY", "single", "Transformer", "abc", None],
            ["ok-1", "single", None, None, None],
            ["X-1", "single", "Nope", None, None],
            ["X-2", "panel", None, None, None],
        ],
        Connections=[["panel", "bus", "role", "element"], ["GHOST", "Bus A", "incomer", "OK-1"]],
    )
    r = _upload(client, data)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"].startswith("IMPORT_INVALID: 7 row(s)") and body["saved"] is False
    errs = {(x["sheet"], x["row"]): x.get("error", x["status"]) for x in body["results"]}
    assert errs[("Elements", 2)] == "created"  # valid, but rolled back with the rest
    assert errs[("Elements", 3)].startswith("KIND_REQUIRED")
    assert errs[("Elements", 4)].startswith("FIELD_UNKNOWN: column 'colour'")
    assert errs[("Elements", 5)].startswith("FIELD_INVALID")
    assert errs[("Elements", 6)].startswith("DUPLICATE_IN_SHEET: ok-1 is also on row 2")
    assert errs[("Elements", 7)].startswith("TYPE_NOT_FOUND")
    assert errs[("Elements", 8)].startswith("KIND_INVALID")
    assert errs[("Connections", 2)].startswith("ELEMENT_NOT_FOUND: GHOST")
    assert _items(client) == {}


def test_existing_elements_are_updated(api, client):
    tf = api.create_equipment("TF-X", "transformer", values={"primary_voltage": {"value": 33, "unit": "kV"}})
    pcc = api.create_equipment("PCC-X", "lt_panel")
    data = _xlsx(
        Elements=[["name", "kind", "Secondary voltage", "Max Outgoers"], ["tf-x", None, "11 kV", 2]],
        Buses=[["panel", "bus", "outgoers"], ["PCC-X", "Bus A", 3], ["PCC-X", "Bus B", 1]],
    )
    r = _upload(client, data)
    assert r.status_code == 200, r.text
    rep = r.json()["summary"]
    assert rep["elements"]["updated"] == 1 and rep["buses"] == {"created": 1, "updated": 1, "unchanged": 0}
    items = _items(client)
    assert items["TF-X"]["values"] == {"primary_voltage": {"value": 33.0, "unit": "kV"},
                                       "secondary_voltage": {"value": 11.0, "unit": "kV"}}
    assert items["TF-X"]["maxOutgoers"] == 2 and items["TF-X"]["version"] > tf["version"]
    assert [(b["name"], b["outgoers"]) for b in items["PCC-X"]["buses"]] == [("Bus A", 3), ("Bus B", 1)]
    assert items["PCC-X"]["id"] == pcc["id"]

    r = _upload(client, _xlsx(Elements=[["name", "kind"], ["TF-X", "distribution"]]))
    assert r.status_code == 400 and r.json()["results"][0]["error"].startswith("KIND_IMMUTABLE")
    r = _upload(client, _xlsx(Elements=[["name", "max incomers"], ["PCC-X", 2]]))
    assert r.json()["results"][0]["error"].startswith("LIMITS_ON_DISTRIBUTION")


def test_csv_is_the_elements_sheet_and_bad_files_are_refused(client):
    csv_data = "name,kind,type,Supply voltage\nAHU-9,single,Load,415 V\n".encode()
    r = _upload(client, csv_data, name="elements.csv", ctype="text/csv")
    assert r.status_code == 200 and r.json()["summary"]["elements"]["created"] == 1, r.text
    assert _items(client)["AHU-9"]["values"]["supply_voltage"]["value"] == 415.0

    r = _upload(client, b"hello", name="notes.txt", ctype="text/plain")
    assert r.status_code == 400 and r.json()["detail"].startswith("FILE_TYPE")
    r = _upload(client, b"PK\x03\x04broken", name="x.xlsx")
    assert r.status_code == 400 and r.json()["detail"].startswith("FILE_INVALID")
    r = _upload(client, _xlsx(Other=[["a"], [1]]))
    assert r.status_code == 400 and r.json()["detail"].startswith("SHEETS_MISSING")


def test_import_needs_write_permission(client, auth_role):
    auth_role("read")
    assert _upload(client, _xlsx(**PLANT)).status_code == 403
    assert client.get("/equipment/import/ems/template").status_code == 200


def test_zone_and_panel_allowed_types(client):
    client.post("/equipment/zones", json={"name": "Utility Block"})
    data = _xlsx(
        Elements=[
            ["name", "kind", "type", "zone", "incoming types", "outgoing types", "max incomers"],
            ["PCC-Z", "distribution", "LT Panel", "utility block", "Transformer", "Load, LT Panel", None],
            ["AHU-Z", "single", "Load", None, "LT Panel", None, 1],
            ["BAD-Z", "single", "Load", "Mars", None, None, None],
        ],
        Buses=[["panel", "bus", "outgoers", "outgoing types"], ["PCC-Z", "Bus 1", 2, None], ["PCC-Z", "Bus 2", 1, "Load"]],
    )
    r = _upload(client, data, dry=True)
    errs = [x for x in r.json()["results"] if x["status"] == "failed"]
    assert [(x["row"], x["error"].split(":")[0]) for x in errs] == [(4, "ZONE_NOT_FOUND")]

    data = _xlsx(
        Elements=[
            ["name", "kind", "type", "zone", "incoming types", "outgoing types", "max incomers"],
            ["PCC-Z", "distribution", "LT Panel", "utility block", "Transformer", "Load, LT Panel", None],
            ["AHU-Z", "single", "Load", None, "LT Panel", None, 1],
        ],
        Buses=[["panel", "bus", "outgoers", "outgoing types"], ["PCC-Z", "Bus 1", 2, None], ["PCC-Z", "Bus 2", 1, "Load"]],
    )
    r = _upload(client, data)
    assert r.status_code == 200, r.text
    items = _items(client)
    pcc = items["PCC-Z"]
    assert pcc["zoneName"] == "Utility Block"
    # Panel-level lists on every bus; a bus row's own list wins.
    assert [(b["name"], b["incomingTypes"], b["outgoingTypes"]) for b in pcc["buses"]] == [
        ("Bus 1", ["transformer"], ["lt_panel", "load"]), ("Bus 2", ["transformer"], ["load"])]
    assert items["AHU-Z"]["incomingTypes"] == ["lt_panel"]  # a single element's own node


def test_export_in_plant_template_layout(api, client):
    zone = client.post("/equipment/zones", json={"name": "North"}).json()["item"]
    pcc = api.create_equipment("PCC-01", "lt_panel", zoneId=zone["id"], values={"bus_voltage": {"value": 415, "unit": "V"}})
    client.put(f"/equipment/{pcc['id']}/buses/count", json={"count": 2})
    bus_a = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus_a}", json={"incomers": 1, "outgoers": 6, "outgoingTypes": ["load"]})
    tf = api.create_equipment("TF-01", "transformer", values={"rated_capacity": {"value": 2, "unit": "MVA"}})
    client.post("/equipment", json={"name": "U-1", "categoryId": "ems", "kind": "single"})  # untyped

    r = client.get("/equipment/export/ems")
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    assert "ems_elements_" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Transformer", "LT Panel", "Untyped", "Bus Sections", "Meters", "Lists"]

    lt = list(wb["LT Panel"].iter_rows(values_only=True))
    assert lt[0][0] == "REQUIRED" and "NAMEPLATE / OPTIONAL" in lt[0]
    head = dict(zip(lt[1], lt[2]))
    assert head["Element ID *"] == pcc["id"] and head["Name *"] == "PCC-01" and head["Zone"] == "North"
    assert head["Bus / operating voltage *"] == "415 V" and head["Number of Bus Sections"] == 2
    assert head["Allowed Outgoing Types"] == "Load"

    tfs = list(wb["Transformer"].iter_rows(values_only=True))
    row = dict(zip(tfs[1], tfs[2]))
    assert row["Element ID *"] == tf["id"] and row["Rated capacity *"] == "2 MVA" and (row["Max Incomers"], row["Max Outgoers"]) == (1, 1)

    buses = list(wb["Bus Sections"].iter_rows(values_only=True))
    assert buses[1][:6] == ("Element ID *", "Element Name", "Bus ID *", "Bus Section *", "Maximum Incomers *", "Outgoing Feeder Capacity *")
    assert [(b[1], b[3], b[4], b[5]) for b in buses[2:]] == [("PCC-01", "Bus A", 1, 6), ("PCC-01", "Bus B", 0, 0)]
    lists = list(wb["Lists"].iter_rows(values_only=True))
    assert lists[0] == ("Zones", "Element types", "Kinds") and lists[1][0] == "North"

    only = load_workbook(io.BytesIO(client.get("/equipment/export/ems", params={"typeId": "transformer"}).content))
    assert only.sheetnames == ["Transformer", "Bus Sections", "Meters", "Lists"]


def test_meters_sheet_places_logger_tables(api, client):
    """An MFM is a logger table (as in v1); its device and schema come from the table."""
    assert _upload(client, _xlsx(**PLANT)).status_code == 200
    schema = api.create_schema("MFM 3ph", [{"key": "v", "type": "float32"}])
    other = api.create_schema("PQM", [{"key": "v", "type": "float32"}])
    target = api.create_pg_target()
    for n in ("pcc_in", "pcc_ahu", "pcc_spare", "tf_mfm", "grid_mfm", "new_mfm"):
        dev = api.create_device(f"dev_{n}", port=1)["item"]["id"]
        api.bulk_create(schema["id"], [n], target, device_id=dev)
    api.bulk_create(other["id"], ["pqm_tbl"], target)

    meters = [
        ["Table", "Element", "Bus", "Role", "Measures", "Schema"],
        ["pcc_in", "PCC-01", "Bus 1", "Incomings", "TF-01", "MFM 3ph"],
        ["pcc_ahu", "PCC-01", "Bus 1", "outgoing", "AHU-01", None],
        ["pcc_spare", "PCC-01", "Bus 2", "Spare", None, None],
        ["tf_mfm", "TF-01", None, None, None, None],
    ]
    v1_style = [["MFM", "Element"], ["grid_mfm", "GRID-01"]]  # v1 put the table in the MFM column
    r = _upload(client, _xlsx(Meters=meters + v1_style[1:]))
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["meters"] == {"created": 5, "updated": 0, "unchanged": 0}
    items = _items(client)
    bus1, bus2 = items["PCC-01"]["buses"]
    m_in = bus1["incomingEquipment"][0]["meter"]
    assert (m_in["tableName"], m_in["schemaName"], m_in["deviceName"]) == ("pcc_in", "MFM 3ph", "dev_pcc_in")
    assert bus1["outgoingEquipment"][0]["meter"]["tableName"] == "pcc_ahu"
    assert [m["tableName"] for m in bus2["spares"]] == ["pcc_spare"]
    assert [m["tableName"] for m in items["TF-01"]["metering"]["meters"]] == ["tf_mfm"]
    assert [m["tableName"] for m in items["GRID-01"]["metering"]["meters"]] == ["grid_mfm"]
    assert [x["tableName"] for x in client.get("/equipment/available_meters").json()["items"]] == ["new_mfm", "pqm_tbl"]

    r = _upload(client, _xlsx(Meters=meters))
    assert r.json()["summary"]["meters"] == {"created": 0, "updated": 0, "unchanged": 4}

    bad = [
        ["table", "element", "bus", "role", "measures", "schema"],
        ["nope_tbl", "PCC-01", "Bus 1", "incoming", "TF-01", None],
        ["pcc_in", "TF-01", None, None, None, None],
        ["pcc_spare", "PCC-01", "Bus 2", "spare", "AHU-01", None],
        ["pcc_spare", "PCC-01", "Bus 2", "incoming", "AHU-01", None],
        ["pcc_ahu", "PCC-01", None, "outgoing", "AHU-01", None],
        ["pcc_ahu", "PCC-01", "Bus 1", "sideways", None, None],
        ["new_mfm", "PCC-01", "Bus 1", "incoming", None, None],
        ["pqm_tbl", "TF-01", None, None, None, "MFM 3ph"],
        [None, "TF-01", None, None, None, None],
    ]
    r = _upload(client, _xlsx(Meters=bad), dry=True)
    assert [x.get("error", "").split(":")[0] for x in r.json()["results"]] == [
        "TABLE_NOT_FOUND", "METER_IN_USE", "SPARE_MEASURES", "ROLE_CHANGE", "BUS_REQUIRED",
        "ROLE_INVALID", "EQUIPMENT_REQUIRED", "SCHEMA_MISMATCH", "TABLE_REQUIRED"]

    # A table that is an MFM cannot be deleted.
    r = client.delete(f"/tables/{m_in['tableId']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("TABLE_ATTACHED_TO_EQUIPMENT: PCC-01 Bus 1")

    wb = load_workbook(io.BytesIO(client.get("/equipment/export/ems").content))
    rows = list(wb["Meters"].iter_rows(values_only=True))
    assert rows[0] == ("Table (MFM)", "Element", "Bus", "Role", "Measures", "Schema", "Device")
    assert ("pcc_spare", "PCC-01", "Bus 2", "spare", None, "MFM 3ph", "dev_pcc_spare") in rows
    assert ("pcc_in", "PCC-01", "Bus 1", "incoming", "TF-01", "MFM 3ph", "dev_pcc_in") in rows
