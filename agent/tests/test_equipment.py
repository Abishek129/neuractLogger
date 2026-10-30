"""Tier 1 — electrical equipment (/equipment), the "Electrical Elements" screen.

Categories (DB-only, type single|distribution, field definitions) ->
equipment -> connection nodes: buses (distribution) or one hidden main node
(single), with capacity, allowed categories, attached equipment and MFMs.
"""
from __future__ import annotations


def _bus_count(client, eq_id, n):
    return client.put(f"/equipment/{eq_id}/buses/count", json={"count": n})


def _attach(client, bus_id, eq_id, role):
    return client.post(f"/equipment/buses/{bus_id}/equipment", json={"equipmentId": eq_id, "role": role})


def _mfm(api, name):
    """An MFM = a logger table (bound to a device of the same name). Returns the table id."""
    ctx = getattr(api, "_mfm_ctx", None)
    if ctx is None:
        schema = api.create_schema("mfm_schema", [{"key": "v", "type": "float32"}])
        ctx = api._mfm_ctx = (schema["id"], api.create_pg_target())
    dev = api.create_device(name, port=1)["item"]["id"]
    return api.bulk_create(ctx[0], [name], ctx[1], device_id=dev)[0]["id"]


V = lambda value, unit: {"value": value, "unit": unit}  # noqa: E731


# ---------- Categories + types ----------
def test_seeded_categories_and_types(client):
    cats = client.get("/equipment/categories").json()["items"]
    assert [(c["id"], c["name"], c["kinds"]) for c in cats] == [
        ("ems", "EMS", ["single", "distribution"]), ("source", "Source", []), ("bms", "BMS", [])]
    types = {t["id"]: t for t in client.get("/equipment/types").json()["items"]}
    assert list(types) == ["source", "transformer", "ht_panel", "lt_panel", "load"]
    tf = {f["id"]: f for f in types["transformer"]["fields"]}
    assert tf["primary_voltage"]["required"] and tf["primary_voltage"]["units"] == ["kV", "V"]
    assert types["transformer"]["defaultCapacity"] == {"incomers": 1, "outgoers": 1}
    assert types["load"]["defaultCapacity"] == {"incomers": 1, "outgoers": 0}
    assert client.post("/equipment/categories", json={"id": "x"}).status_code == 405


def test_user_types_crud(api, client):
    from plc_agent.api import appdb

    r = client.post("/equipment/types", json={
        "name": "Busduct", "fields": [{"id": "rating", "label": "Rating", "kind": "text", "required": True}]})
    assert r.status_code == 200, r.text
    bd = r.json()["item"]
    assert bd["id"].startswith("typ_") and bd["used"] == 0 and bd["fields"][0]["required"] is True
    # Any type works with either kind; the element decides.
    d = api.create_equipment("BD-1", bd["id"], kind="distribution")
    s1 = api.create_equipment("BD-2", bd["id"], kind="single")
    assert [b["name"] for b in d["buses"]] == ["Bus A"] and d["typeName"] == "Busduct"
    assert d["nameplate"] == {"complete": False, "missing": ["Rating"]} and (s1["maxIncomers"], s1["maxOutgoers"]) == (1, 1)

    for bad in ([{"id": "a"}], [{"id": "a", "label": "A", "kind": "x"}], [{"id": "a", "label": "A", "kind": "choice"}],
                [{"id": "a", "label": "A"}, {"id": "A", "label": "B"}], [{"id": "a", "label": "A", "role": "x"}], "x"):
        r = client.post("/equipment/types", json={"name": "Bad", "fields": bad})
        assert r.status_code == 400 and r.json()["detail"].startswith("FIELDS_INVALID"), (bad, r.text)
    r = client.post("/equipment/types", json={"name": "busduct"})
    assert r.status_code == 409 and r.json()["detail"].startswith("TYPE_EXISTS")

    # Redefining fields: nameplate completeness follows the current fields; stored values stay.
    r = client.put(f"/equipment/types/{bd['id']}", json={"name": "Bus duct", "fields": [], "defaultCapacity": {"incomers": 2, "outgoers": 3}})
    assert r.status_code == 200 and r.json()["item"]["used"] == 2 and r.json()["item"]["defaultCapacity"] == {"incomers": 2, "outgoers": 3}
    assert client.get(f"/equipment/{d['id']}").json()["item"]["nameplate"]["complete"] is True

    r = client.delete(f"/equipment/types/{bd['id']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("TYPE_IN_USE: 2 element(s)")
    for e in (d, s1):
        client.delete(f"/equipment/{e['id']}")
    assert client.delete(f"/equipment/types/{bd['id']}").status_code == 200
    assert client.delete(f"/equipment/types/{bd['id']}").status_code == 404

    # A built-in type the user deletes is not seeded again.
    assert client.delete("/equipment/types/source").status_code == 200
    appdb.seed_equipment_types()
    assert "source" not in [t["id"] for t in client.get("/equipment/types").json()["items"]]


def test_category_kind_and_optional_type(api, client):
    r = client.post("/equipment", json={"name": "S-1", "categoryId": "source", "kind": "single"})
    assert r.status_code == 400 and r.json()["detail"].startswith("KIND_NOT_ALLOWED")
    r = client.post("/equipment", json={"name": "S-1", "categoryId": "ems", "kind": "panel"})
    assert r.status_code == 400 and r.json()["detail"].startswith("KIND_INVALID")
    r = client.post("/equipment", json={"name": "S-1", "categoryId": "ems", "kind": "single", "typeId": "nope"})
    assert r.status_code == 404 and r.json()["detail"].startswith("TYPE_NOT_FOUND")

    u = client.post("/equipment", json={"name": "U-1", "categoryId": "ems", "kind": "single"}).json()["item"]
    assert (u["categoryId"], u["categoryName"], u["kind"], u["typeId"], u["typeName"]) == ("ems", "EMS", "single", None, None)
    assert u["values"] == {} and u["nameplate"]["complete"] and (u["maxIncomers"], u["maxOutgoers"]) == (1, 1)
    assert "subtype" not in u and "type" not in u
    r = client.put(f"/equipment/{u['id']}", json={"values": {"x": V(1, "V")}})
    assert r.status_code == 400 and r.json()["detail"].startswith("FIELD_UNKNOWN")
    r = client.put(f"/equipment/{u['id']}", json={"kind": "distribution"})
    assert r.status_code == 400 and r.json()["detail"].startswith("KIND_IMMUTABLE")
    r = client.put(f"/equipment/{u['id']}", json={"categoryId": "bms"})
    assert r.status_code == 400 and r.json()["detail"].startswith("KIND_NOT_ALLOWED")

    ld = api.create_equipment("LOAD-D", "load", kind="distribution")
    names = lambda **p: [i["name"] for i in client.get("/equipment", params=p).json()["items"]]  # noqa: E731
    assert names(kind="distribution") == ["LOAD-D"] and names(typeId="load") == ["LOAD-D"]
    assert sorted(names(categoryId="ems")) == ["LOAD-D", "U-1"] and names(categoryId="bms") == []
    assert names(q="load") == ["LOAD-D"]

    # Bus rules are by type: an untyped element is refused where types are set.
    pcc = api.create_equipment("PCC-T", "lt_panel")
    bus = pcc["buses"][0]["id"]
    r = client.put(f"/equipment/buses/{bus}", json={"outgoers": 2, "outgoingTypes": ["load"]})
    assert r.status_code == 200 and r.json()["item"]["outgoingTypes"] == ["load"]
    r = _attach(client, bus, u["id"], "outgoer")
    assert r.status_code == 400 and r.json()["detail"].startswith("TYPE_NOT_ALLOWED")
    assert client.put(f"/equipment/{u['id']}", json={"typeId": "load"}).status_code == 200
    assert _attach(client, bus, u["id"], "outgoer").status_code == 200
    r = client.put(f"/equipment/{u['id']}", json={"typeId": None})
    assert r.status_code == 409 and r.json()["detail"].startswith("TYPE_NOT_ALLOWED_ON_BUS: PCC-T Bus A")
    r = client.put(f"/equipment/buses/{bus}", json={"outgoingTypes": ["transformer"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("ATTACHED_OUTSIDE_TYPES")


# ---------- Equipment ----------
def test_equipment_crud_fields_voltage_readiness(api, client):
    tf = api.create_equipment("TF-01", "transformer",
                              values={"primary_voltage": V("33", "kV"), "phase": V("3 Phase", None)})
    assert (tf["typeName"], tf["kind"], tf["categoryId"], tf["spare"]) == ("Transformer", "single", "ems", False)
    assert tf["values"]["primary_voltage"] == {"value": 33.0, "unit": "kV"}
    assert tf["voltage"] == {"in": "33 kV", "out": None, "text": "33 kV"}
    assert tf["nameplate"] == {"complete": False, "missing": ["Secondary voltage", "Rated capacity"]}
    # Connection readiness: its one incoming and one outgoing slot are empty.
    assert tf["readiness"] == {"ready": False, "incomers": {"filled": 0, "total": 1}, "outgoers": {"filled": 0, "total": 1}}
    assert (tf["maxIncomers"], tf["maxOutgoers"]) == (1, 1)
    assert "buses" not in tf

    r = client.put(f"/equipment/{tf['id']}", json={
        "values": {"secondary_voltage": V(11, "kV"), "rated_capacity": V("20", "MVA"), "phase": None},
        "spare": True,
    })
    assert r.status_code == 200, r.text
    tf = r.json()["item"]
    assert tf["voltage"]["text"] == "33 kV → 11 kV" and tf["spare"] is True
    assert tf["nameplate"]["missing"] == ["Phase"]

    for bad, code in (
        ({"values": {"nope": V(1, "V")}}, "FIELD_UNKNOWN"),
        ({"values": {"primary_voltage": V("abc", "kV")}}, "FIELD_INVALID"),
        ({"values": {"primary_voltage": V("33", "A")}}, "FIELD_INVALID"),
        ({"values": {"phase": V("2 Phase", None)}}, "FIELD_INVALID"),
        ({"values": [1]}, "VALUES_INVALID"),
        ({"spare": "yes"}, "SPARE_INVALID"),
        ({"maxIncomers": -1}, "MAX_INCOMERS_INVALID"),
    ):
        r = client.put(f"/equipment/{tf['id']}", json=bad)
        assert r.status_code == 400 and r.json()["detail"].startswith(code), (bad, r.text)

    pcc = api.create_equipment("PCC-01", "lt_panel", values={"bus_voltage": V(415, "V")})
    assert pcc["voltage"]["text"] == "415 V" and pcc["nameplate"]["complete"] and pcc["readiness"]["ready"]  # 0/0 slots
    assert [(b["name"], b["incomers"], b["outgoers"]) for b in pcc["buses"]] == [("Bus A", 0, 0)]

    r = client.post("/equipment", json={"name": "pcc-01", "categoryId": "ems", "kind": "distribution", "typeId": "ht_panel"})
    assert r.status_code == 409 and r.json()["detail"].startswith("EQUIPMENT_EXISTS")
    assert client.post("/equipment", json={"name": "X", "categoryId": "nope", "kind": "single"}).status_code == 404
    # A type change keeps only values of fields the new type has.
    r = client.put(f"/equipment/{pcc['id']}", json={"typeId": "ht_panel"})
    assert r.status_code == 200 and r.json()["item"]["values"] == {"bus_voltage": {"value": 415.0, "unit": "V"}}

    assert client.delete(f"/equipment/{tf['id']}").status_code == 200
    assert client.get(f"/equipment/{tf['id']}").status_code == 404


def test_list_filters(api, client):
    a = api.create_equipment("GRID-01", "source", values={"voltage": V(33, "kV")})
    b = api.create_equipment("TF-03", "transformer", spare=True)
    pcc = api.create_equipment("PCC-01", "lt_panel", values={"bus_voltage": V(415, "V")})
    client.put(f"/equipment/buses/{pcc['buses'][0]['id']}", json={"incomers": 1})
    _attach(client, pcc["buses"][0]["id"], b["id"], "incomer")
    client.post(f"/equipment/{a['id']}/meters", json={"tableId": _mfm(api, "MFM-1")})

    names = lambda **p: [i["name"] for i in client.get("/equipment", params=p).json()["items"]]  # noqa: E731
    assert names() == ["GRID-01", "TF-03", "PCC-01"]  # type order
    assert names(typeId="source") == ["GRID-01"]
    assert names(q="transf") == ["TF-03"] and names(q="pcc") == ["PCC-01"]
    assert names(metered="true") == ["GRID-01"]
    # Ready = every slot connected: PCC's one incomer is TF-03; TF-03 is fed by
    # nothing yet and GRID-01 feeds nothing.
    assert names(ready="false") == ["GRID-01", "TF-03"] and names(ready="true") == ["PCC-01"]
    items = {i["name"]: i for i in client.get("/equipment").json()["items"]}
    assert items["TF-03"]["readiness"] == {"ready": False, "incomers": {"filled": 0, "total": 1}, "outgoers": {"filled": 1, "total": 1}}
    assert items["PCC-01"]["readiness"]["incomers"] == {"filled": 1, "total": 1}
    assert names(used="true") == ["TF-03", "PCC-01"]
    assert names(spare="true") == ["TF-03"]
    assert names(kind="distribution") == ["PCC-01"]


# ---------- Buses ----------
def test_buses_counts_coupling(api, client):
    load = api.create_equipment("AHU-1", "load")
    r = _bus_count(client, load["id"], 2)
    assert r.status_code == 400 and r.json()["detail"].startswith("BUSES_NOT_ALLOWED")

    pcc = api.create_equipment("PCC", "lt_panel")
    r = _bus_count(client, pcc["id"], 2)
    a, b = r.json()["items"]
    assert (a["name"], b["name"]) == ("Bus A", "Bus B")
    r = client.put(f"/equipment/buses/{a['id']}", json={"incomers": 1, "outgoers": 9, "coupledNext": True})
    assert r.status_code == 200 and r.json()["item"]["coupledNext"] and r.json()["item"]["points"] == 10
    r = client.put(f"/equipment/buses/{b['id']}", json={"coupledNext": True})
    assert r.status_code == 400 and r.json()["detail"].startswith("NO_NEXT_BUS")
    # Removing Bus B leaves Bus A last: its coupler is cleared.
    r = _bus_count(client, pcc["id"], 1)
    assert r.json()["items"][0]["coupledNext"] is False

    r = client.delete(f"/equipment/buses/{a['id']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("LAST_BUS")
    for bad in (0, 27, "2"):
        assert _bus_count(client, pcc["id"], bad).status_code == 400
    # The hidden main node of single equipment is never a bus.
    assert client.get(f"/equipment/{load['id']}/buses").status_code == 400


# ---------- Rules on both ends ----------
def test_attach_checks_bus_and_single_equipment_rules(api, client):
    pcc = api.create_equipment("PCC", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"incomers": 2, "outgoers": 3,
               "incomingTypes": ["transformer", "source"], "outgoingTypes": ["load", "lt_panel"]})
    tf = api.create_equipment("TF-1", "transformer", outgoingTypes=["lt_panel"])
    assert tf["outgoingTypes"] == ["lt_panel"]
    ahu = api.create_equipment("AHU-1", "load", incomingTypes=["ht_panel"])

    assert _attach(client, bus, tf["id"], "incomer").status_code == 200
    # AHU only accepts HT panels as its incoming: the load-side rule refuses.
    r = _attach(client, bus, ahu["id"], "outgoer")
    assert r.status_code == 400 and r.json()["detail"] == "TYPE_NOT_ALLOWED: AHU-1 incomers must be of type: ht_panel"
    client.put(f"/equipment/{ahu['id']}", json={"incomingTypes": []})
    assert _attach(client, bus, ahu["id"], "outgoer").status_code == 200
    # AHU allows 1 incoming connection (Load default): a second panel cannot feed it.
    pcc2 = api.create_equipment("PCC-2", "lt_panel")
    bus2 = pcc2["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus2}", json={"outgoers": 1})
    r = _attach(client, bus2, ahu["id"], "outgoer")
    assert r.status_code == 409 and r.json()["detail"].startswith("NO_SPARE: AHU-1 allows 1 incoming")
    # Load has no outgoing side (capacity 0): it cannot feed a bus.
    load2 = api.create_equipment("AHU-2", "load")
    r = _attach(client, bus, load2["id"], "incomer")
    assert r.status_code == 400  # type (bus incoming allows transformer/source)

    # Bus-side checks.
    r = _attach(client, bus, api.create_equipment("TF-2", "transformer")["id"], "outgoer")
    assert r.status_code == 400 and r.json()["detail"].startswith("TYPE_NOT_ALLOWED: Bus A")
    r = _attach(client, bus, tf["id"], "outgoer")
    assert r.status_code == 409 and r.json()["detail"].startswith("ALREADY_ATTACHED")

    detail = client.get(f"/equipment/{tf['id']}").json()["item"]
    assert detail["attachedTo"] == [{"busId": bus, "busName": "Bus A", "equipmentId": pcc["id"],
                                     "equipmentName": "PCC", "role": "incomer", "position": 0,
                                     "direct": False}] and detail["used"]

    # Guards while connected.
    assert client.put(f"/equipment/{tf['id']}", json={"maxOutgoers": 0}).status_code == 409
    r = client.put(f"/equipment/{tf['id']}", json={"outgoingTypes": ["ht_panel"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("ATTACHED_OUTSIDE_TYPES")
    r = client.put(f"/equipment/buses/{bus}", json={"outgoers": 0})
    assert r.status_code == 409 and r.json()["detail"].startswith("CAPACITY_BELOW_ATTACHED")
    assert client.delete(f"/equipment/{ahu['id']}").status_code == 409

    r = client.delete(f"/equipment/buses/{bus}/equipment/{ahu['id']}")
    assert r.status_code == 200 and r.json()["item"]["outgoingEquipment"] == []
    assert client.delete(f"/equipment/{pcc['id']}").status_code == 200  # its attachments go
    assert client.get(f"/equipment/{tf['id']}").json()["item"]["attachedTo"] == []


def test_attach_rejects_self_and_loops(api, client):
    pcc, mcc, db = (api.create_equipment(n, "lt_panel") for n in ("PCC", "MCC", "DB"))
    bus = {e["name"]: e["buses"][0]["id"] for e in (pcc, mcc, db)}
    for b in bus.values():
        client.put(f"/equipment/buses/{b}", json={"incomers": 2, "outgoers": 2})
    r = _attach(client, bus["PCC"], pcc["id"], "outgoer")
    assert r.status_code == 400 and r.json()["detail"].startswith("SELF_ATTACH")
    assert _attach(client, bus["PCC"], mcc["id"], "outgoer").status_code == 200
    assert _attach(client, bus["MCC"], db["id"], "outgoer").status_code == 200
    r = _attach(client, bus["DB"], pcc["id"], "outgoer")
    assert r.status_code == 400 and r.json()["detail"] == "CYCLE: PCC already feeds DB"


# ---------- MFMs ----------
def test_mfms_on_single_equipment_and_on_bus_points(api, client, meta_query):
    tf = api.create_equipment("TF-1", "transformer")
    pcc = api.create_equipment("PCC", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"incomers": 1, "outgoers": 2})
    m = [_mfm(api, f"MFM-{i}") for i in range(6)]

    # Single equipment: several MFMs on the equipment itself.
    for d in m[:2]:
        assert client.post(f"/equipment/{tf['id']}/meters", json={"tableId": d}).status_code == 200
    tfd = client.get(f"/equipment/{tf['id']}").json()["item"]
    assert [x["deviceName"] for x in tfd["metering"]["meters"]] == ["MFM-0", "MFM-1"]
    assert tfd["metering"]["meters"][0]["unitId"] == 1 and tfd["metering"]["meters"][0]["role"] is None

    # Distribution: MFMs go on buses, in the slot of a relation (an incoming
    # MFM always measures an attached incomer) or as an outgoing spare.
    r = client.post(f"/equipment/{pcc['id']}/meters", json={"tableId": m[2]})
    assert r.status_code == 400 and r.json()["detail"].startswith("USE_BUS_METERS")
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[2], "role": "incomer"})
    assert r.status_code == 400 and r.json()["detail"].startswith("EQUIPMENT_REQUIRED")
    assert _attach(client, bus, tf["id"], "incomer").status_code == 200
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[2], "role": "incomer", "equipmentId": tf["id"]})
    assert r.status_code == 200 and r.json()["item"]["pointsMetered"] == 1
    assert r.json()["item"]["incomingEquipment"][0]["meter"]["tableId"] == m[2]
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[3], "role": "incomer", "equipmentId": tf["id"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("RELATION_METERED")
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[3], "role": "outgoer"})
    assert r.status_code == 200 and [x["tableId"] for x in r.json()["item"]["spares"]] == [m[3]]
    pd = client.get(f"/equipment/{pcc['id']}").json()["item"]
    assert pd["metering"] == {**pd["metering"], "points": 3, "pointsMetered": 2, "meterCount": 2}
    assert client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[4], "role": "x"}).status_code == 400

    # One place per MFM (table).
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m[0], "role": "outgoer"})
    assert r.status_code == 409 and r.json()["detail"].startswith("METER_IN_USE: attached to TF-1")
    r = client.post(f"/equipment/{tf['id']}/meters", json={"tableId": m[2]})
    assert r.status_code == 409 and r.json()["detail"].startswith("METER_IN_USE: attached to PCC Bus A")
    avail = {d["tableId"] for d in client.get("/equipment/available_meters").json()["items"]}
    assert not avail & set(m[:4]) and {m[4], m[5]} <= avail

    # Guards.
    r = client.put(f"/equipment/buses/{bus}", json={"incomers": 0})
    assert r.status_code == 409 and r.json()["detail"].startswith("CAPACITY_BELOW_ATTACHED")
    r = client.delete(f"/equipment/buses/{bus}/equipment/{tf['id']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("RELATION_METERED")
    assert _bus_count(client, pcc["id"], 2).status_code == 200
    assert _bus_count(client, pcc["id"], 1).status_code == 200  # the new Bus B was empty
    # Neither the MFM's table nor its device can be deleted while it is attached.
    r = client.delete(f"/tables/{m[2]}")
    assert r.status_code == 409 and r.json()["detail"].startswith("TABLE_ATTACHED_TO_EQUIPMENT: PCC Bus A")
    dev = next(x for x in client.get(f"/equipment/{pcc['id']}/meters").json()["items"] if x["tableId"] == m[2])
    assert (dev["tableName"], dev["deviceName"], dev["schemaName"]) == ("MFM_2", "MFM-2", "mfm_schema")
    r = client.delete(f"/devices/{dev['deviceId']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("DEVICE_ATTACHED_TO_EQUIPMENT: table MFM_2 on PCC Bus A")

    assert client.delete(f"/equipment/buses/{bus}/meters/{m[2]}").status_code == 200
    assert client.delete(f"/equipment/buses/{bus}/meters/{m[2]}").status_code == 404
    r = client.delete(f"/equipment/{tf['id']}/meters/{m[0]}")
    assert r.status_code == 200 and [x["tableId"] for x in r.json()["items"]] == [m[1]]
    assert [x["tableId"] for x in client.get(f"/equipment/{pcc['id']}/meters").json()["items"]] == [m[3]]

    assert client.delete(f"/equipment/buses/{bus}/equipment/{tf['id']}").status_code == 200
    client.delete(f"/equipment/{tf['id']}")
    client.delete(f"/equipment/{pcc['id']}")
    assert meta_query("SELECT COUNT(*) FROM app_bus_meter")[0][0] == 0
    assert meta_query("SELECT COUNT(*) FROM app_bus")[0][0] == 0


# ---------- Versions (If-Match) ----------
def test_versions_and_if_match(api, client):
    pcc = api.create_equipment("PCC", "lt_panel")
    tf = api.create_equipment("TF-1", "transformer")
    assert pcc["version"] == 1 and pcc["buses"][0]["equipmentVersion"] == 1
    bus = pcc["buses"][0]["id"]

    # Stale If-Match -> 409; matching -> applied and bumped.
    r = client.put(f"/equipment/{pcc['id']}", json={"description": "PCC"}, headers={"If-Match": "7"})
    assert r.status_code == 409 and r.json()["detail"] == f"VERSION_CONFLICT: {pcc['id']}"
    r = client.put(f"/equipment/{pcc['id']}", json={"description": "PCC"}, headers={"If-Match": '"1"'})
    assert r.status_code == 200 and r.json()["item"]["version"] == 2
    assert client.put(f"/equipment/{pcc['id']}", json={}, headers={"If-Match": "x"}).status_code == 400

    # Bus routes check the owning equipment's version and bump it.
    assert client.put(f"/equipment/buses/{bus}", json={"incomers": 1}, headers={"If-Match": "1"}).status_code == 409
    r = client.put(f"/equipment/buses/{bus}", json={"incomers": 1}, headers={"If-Match": "2"})
    assert r.status_code == 200 and r.json()["item"]["equipmentVersion"] == 3

    # Attach returns both changed objects, each bumped.
    r = client.post(f"/equipment/buses/{bus}/equipment", json={"equipmentId": tf["id"], "role": "incomer"},
                    headers={"If-Match": "3"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owner"]["version"] == 4 and body["attached"]["version"] == 2
    assert body["item"]["incomingEquipment"][0]["id"] == tf["id"]
    # Without If-Match: last write wins (today's behaviour).
    r = client.delete(f"/equipment/buses/{bus}/equipment/{tf['id']}")
    assert r.status_code == 200 and r.json()["owner"]["version"] == 5 and r.json()["attached"]["attachedTo"] == []
    assert client.delete(f"/equipment/{pcc['id']}", headers={"If-Match": "1"}).status_code == 409


# ---------- Feeder order + feeder-named bus meters ----------
def test_feeder_positions_and_reorder(api, client):
    pcc = api.create_equipment("PCC", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"outgoers": 5})
    a, b, d = (api.create_equipment(n, "load") for n in ("A", "B", "D"))

    _attach(client, bus, a["id"], "outgoer")
    _attach(client, bus, b["id"], "outgoer")
    r = client.post(f"/equipment/buses/{bus}/equipment", json={"equipmentId": d["id"], "role": "outgoer", "position": 0})
    out = r.json()["item"]["outgoingEquipment"]
    assert [(e["name"], e["position"]) for e in out] == [("D", 0), ("A", 1), ("B", 2)]

    r = client.put(f"/equipment/buses/{bus}/equipment/{d['id']}", json={"position": 9})
    assert [e["name"] for e in r.json()["item"]["outgoingEquipment"]] == ["A", "B", "D"]
    assert client.put(f"/equipment/buses/{bus}/equipment/{d['id']}", json={"position": -1}).status_code == 400
    assert client.put(f"/equipment/buses/{bus}/equipment/eq_nope", json={"position": 0}).status_code == 404

    # Detach keeps the others compact and in order.
    r = client.delete(f"/equipment/buses/{bus}/equipment/{a['id']}")
    assert [(e["name"], e["position"]) for e in r.json()["item"]["outgoingEquipment"]] == [("B", 0), ("D", 1)]
    assert client.get(f"/equipment/{d['id']}").json()["item"]["attachedTo"][0]["position"] == 1


def test_bus_meter_names_its_feeder(api, client):
    pcc = api.create_equipment("PCC", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"incomers": 1, "outgoers": 2})
    ahu = api.create_equipment("AHU-1", "load")
    _attach(client, bus, ahu["id"], "outgoer")
    m1, m2 = _mfm(api, "M1"), _mfm(api, "M2")

    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m1, "role": "outgoer", "equipmentId": ahu["id"]})
    assert r.status_code == 200 and r.json()["item"]["meters"][0]["equipmentId"] == ahu["id"]
    # The feeder must be on this bus, on the same side.
    r = client.post(f"/equipment/buses/{bus}/meters", json={"tableId": m2, "role": "incomer", "equipmentId": ahu["id"]})
    assert r.status_code == 400 and r.json()["detail"].startswith("FEEDER_NOT_ON_BUS")
    # Detaching the feeder keeps the meter on the point, unnamed.
    r = client.delete(f"/equipment/buses/{bus}/equipment/{ahu['id']}")
    assert r.json()["item"]["meters"][0]["equipmentId"] is None


# ---------- Direct links (single -> single) ----------
def test_direct_links(api, client):
    grid = api.create_equipment("GRID-01", "source", outgoingTypes=["transformer"], maxOutgoers=2)
    tf = api.create_equipment("TF-01", "transformer")
    tf2 = api.create_equipment("TF-02", "transformer")
    ups = api.create_equipment("UPS-01", "load")
    pcc = api.create_equipment("PCC", "lt_panel")

    r = client.post(f"/equipment/{grid['id']}/connections", json={"equipmentId": tf["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["name"] for e in body["owner"]["outgoingEquipment"]] == ["TF-01"] and body["owner"]["used"]
    assert body["attached"]["attachedTo"] == [{"busId": None, "busName": None, "equipmentId": grid["id"],
                                               "equipmentName": "GRID-01", "role": "outgoer", "position": 0,
                                               "direct": True}]
    r = client.post(f"/equipment/{grid['id']}/connections", json={"equipmentId": tf2["id"], "position": 0})
    assert [e["name"] for e in r.json()["owner"]["outgoingEquipment"]] == ["TF-02", "TF-01"]

    # Rules at both ends: grid only feeds transformers; TF accepts 1 incoming.
    r = client.post(f"/equipment/{grid['id']}/connections", json={"equipmentId": ups["id"]})
    assert r.status_code == 400 and r.json()["detail"].startswith("TYPE_NOT_ALLOWED: GRID-01")
    grid2 = api.create_equipment("GRID-02", "source")
    r = client.post(f"/equipment/{grid2['id']}/connections", json={"equipmentId": tf["id"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("NO_SPARE: TF-01 allows 1 incoming")
    # Load has 0 outgoing by default: it cannot feed anything.
    r = client.post(f"/equipment/{ups['id']}/connections", json={"equipmentId": tf2["id"]})
    assert r.status_code in (400, 409)

    # Panels connect through buses, not direct links.
    r = client.post(f"/equipment/{grid['id']}/connections", json={"equipmentId": pcc["id"]})
    assert r.status_code == 400 and r.json()["detail"].startswith("USE_BUS")
    assert client.post(f"/equipment/{pcc['id']}/connections", json={"equipmentId": tf["id"]}).status_code == 400
    r = client.post(f"/equipment/{grid['id']}/connections", json={"equipmentId": tf["id"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("ALREADY_ATTACHED")

    # Loops are checked in flow direction: GRID-01 feeds TF-02, so TF-02 -> GRID-01
    # would close a loop (give the grid an incoming side first so only CYCLE can refuse it).
    client.put(f"/equipment/{grid['id']}", json={"maxIncomers": 1, "incomingTypes": []})
    client.put(f"/equipment/{tf2['id']}", json={"outgoingTypes": []})
    r = client.post(f"/equipment/{tf2['id']}/connections", json={"equipmentId": grid["id"]})
    assert r.status_code == 400 and r.json()["detail"] == "CYCLE: GRID-01 already feeds TF-02"

    # Reorder / disconnect; deleting a fed equipment is refused while connected.
    r = client.put(f"/equipment/{grid['id']}/connections/{tf['id']}", json={"position": 0})
    assert [e["name"] for e in r.json()["owner"]["outgoingEquipment"]] == ["TF-01", "TF-02"]
    r = client.delete(f"/equipment/{tf['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "EQUIPMENT_IN_USE: connected to GRID-01"
    r = client.delete(f"/equipment/{grid['id']}/connections/{tf['id']}")
    assert r.status_code == 200 and r.json()["attached"]["attachedTo"] == []
    # Deleting the source removes its direct links (targets are kept, versions bumped).
    v = client.get(f"/equipment/{tf2['id']}").json()["item"]["version"]
    assert client.delete(f"/equipment/{grid['id']}").status_code == 200
    after = client.get(f"/equipment/{tf2['id']}").json()["item"]
    assert after["attachedTo"] == [] and after["version"] == v + 1


def test_type_change_rechecks_rules_at_the_other_end(api, client):
    """A panel changing to a type its attached element's own rules exclude is refused."""
    pcc = api.create_equipment("PCC", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"outgoers": 1})
    ahu = api.create_equipment("AHU-1", "load", incomingTypes=["lt_panel"])
    assert _attach(client, bus, ahu["id"], "outgoer").status_code == 200
    r = client.put(f"/equipment/{pcc['id']}", json={"typeId": "ht_panel"})
    assert r.status_code == 409 and r.json()["detail"] == "TYPE_NOT_ALLOWED_ON_BUS: AHU-1 does not allow HT Panel incomers"
    # Direct link: the target's incoming rule is re-checked when the source moves.
    src = api.create_equipment("TF-A", "transformer", outgoingTypes=[])
    load = api.create_equipment("LOAD-B", "load", incomingTypes=["transformer"])
    assert client.post(f"/equipment/{src['id']}/connections", json={"equipmentId": load["id"]}).status_code == 200
    r = client.put(f"/equipment/{src['id']}", json={"typeId": "source"})
    assert r.status_code == 409 and r.json()["detail"].startswith("TYPE_NOT_ALLOWED_ON_BUS: LOAD-B")


# ---------- Auth ----------
def test_equipment_requires_token(no_auth, client):
    assert client.get("/equipment/categories").status_code == 401
    assert client.post("/equipment", json={}).status_code == 401


def test_equipment_read_vs_write_roles(client, auth_role):
    auth_role("read")
    assert client.get("/equipment/categories").status_code == 200
    assert client.post("/equipment", json={"name": "X", "categoryId": "ems", "kind": "single", "typeId": "load"}).status_code == 403
    auth_role("write")
    assert client.post("/equipment", json={"name": "X", "categoryId": "ems", "kind": "single", "typeId": "load"}).status_code == 200


def test_auth_disabled_switch(no_auth, client, monkeypatch):
    assert client.post("/equipment", json={"name": "X", "categoryId": "ems", "kind": "single", "typeId": "load"}).status_code == 401
    monkeypatch.setenv("LOGGER_AUTH_DISABLED", "1")
    assert client.post("/equipment", json={"name": "X", "categoryId": "ems", "kind": "single", "typeId": "load"}).status_code == 200


# ---------- List performance ----------
def _plant(api, client, prefix, panels):
    """`panels` PCCs, each fed by a transformer and feeding 3 loads, with an
    MFM on the bus and one on a load."""
    for p in range(panels):
        pcc = api.create_equipment(f"{prefix}-PCC-{p}", "lt_panel")
        bus = pcc["buses"][0]["id"]
        client.put(f"/equipment/buses/{bus}", json={"incomers": 1, "outgoers": 3})
        tf = api.create_equipment(f"{prefix}-TF-{p}", "transformer")
        assert _attach(client, bus, tf["id"], "incomer").status_code == 200
        loads = [api.create_equipment(f"{prefix}-L-{p}-{i}", "load") for i in range(3)]
        for ld in loads:
            assert _attach(client, bus, ld["id"], "outgoer").status_code == 200
        r = client.post(f"/equipment/buses/{bus}/meters",
                        json={"tableId": _mfm(api, f"{prefix}-BM-{p}"), "role": "incomer", "equipmentId": tf["id"]})
        assert r.status_code == 200, r.text
        client.post(f"/equipment/{loads[0]['id']}/meters", json={"tableId": _mfm(api, f"{prefix}-LM-{p}")})


def _count_queries(fn):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    n = [0]

    def _on(_conn, _cur, statement, *_a, **_k):
        # Only the equipment reads: background threads (the device reconnector)
        # also run SQL on this engine while the request is in flight.
        if "app_equipment" in statement or "app_bus" in statement:
            n[0] += 1

    event.listen(Engine, "before_cursor_execute", _on)
    try:
        result = fn()
    finally:
        event.remove(Engine, "before_cursor_execute", _on)
    return n[0], result


def test_list_query_count_does_not_grow_with_plant(api, client):
    """GET /equipment used to run ~5 whole-table reads per item (quadratic:
    3,000 items took ~45 s). It must take a fixed number of queries."""
    _plant(api, client, "A", 2)
    small, r = _count_queries(lambda: client.get("/equipment"))
    assert r.status_code == 200 and len(r.json()["items"]) == 10
    _plant(api, client, "B", 6)
    large, r = _count_queries(lambda: client.get("/equipment"))
    items = r.json()["items"]
    assert len(items) == 40
    assert large == small, f"query count grew with the plant: {small} -> {large}"

    # The list's items are exactly what the detail endpoint returns (apart from
    # the MFMs' live device status, which the reconnector updates meanwhile).
    def _steady(x):
        if isinstance(x, dict):
            return {k: _steady(v) for k, v in x.items() if k != "status"}
        return [_steady(v) for v in x] if isinstance(x, list) else x

    for it in items:
        assert _steady(client.get(f"/equipment/{it['id']}").json()["item"]) == _steady(it), it["name"]
    pcc = next(i for i in items if i["name"] == "B-PCC-3")
    bus = pcc["buses"][0]
    assert [e["name"] for e in bus["outgoingEquipment"]] == ["B-L-3-0", "B-L-3-1", "B-L-3-2"]
    assert [e["name"] for e in bus["incomingEquipment"]] == ["B-TF-3"]
    assert [m["deviceName"] for m in bus["meters"]] == ["B-BM-3"] and pcc["metering"]["meterCount"] == 1
    load = next(i for i in items if i["name"] == "B-L-3-0")
    assert load["metering"]["meterCount"] == 1 and load["attachedTo"][0]["equipmentName"] == "B-PCC-3"
    assert load["used"] is True


# ---------- MFM slots: relations and spares ----------
def test_outgoing_spares_and_reassign(api, client):
    pcc = api.create_equipment("PCC-S", "lt_panel")
    bus = pcc["buses"][0]["id"]
    client.put(f"/equipment/buses/{bus}", json={"incomers": 0, "outgoers": 2})
    l1, l2 = (api.create_equipment(n, "load") for n in ("L-1", "L-2"))
    a, b = _mfm(api, "MFM-A"), _mfm(api, "MFM-B")
    meter = lambda d, **kw: client.post(f"/equipment/buses/{bus}/meters", json={"tableId": d, "role": "outgoer", **kw})  # noqa: E731
    assign = lambda d, feeder: client.put(f"/equipment/buses/{bus}/meters/{d}", json={"equipmentId": feeder})  # noqa: E731

    for ld in (l1, l2):
        assert _attach(client, bus, ld["id"], "outgoer").status_code == 200
    assert meter(a, equipmentId=l1["id"]).status_code == 200
    r = meter(b)  # both outgoing points are connected: no room for a spare
    assert r.status_code == 409 and r.json()["detail"].startswith("NO_FREE_POINT")

    # A spare takes a point: the bus is full again.
    assert client.delete(f"/equipment/buses/{bus}/equipment/{l2['id']}").status_code == 200
    r = meter(b)
    assert r.status_code == 200 and [m["tableId"] for m in r.json()["item"]["spares"]] == [b]
    assert (r.json()["item"]["spareMeters"], r.json()["item"]["spareOutgoers"]) == (1, 0)
    r = _attach(client, bus, l2["id"], "outgoer")
    assert r.status_code == 409 and r.json()["detail"].startswith("NO_SPARE")

    # Disconnecting a metered outgoer leaves its MFM behind as a spare.
    item = client.delete(f"/equipment/buses/{bus}/equipment/{l1['id']}").json()["item"]
    assert sorted(m["tableId"] for m in item["spares"]) == sorted([a, b]) and item["outgoingEquipment"] == []

    # Connect a feeder at a spare's point: that MFM now measures it.
    r = client.post(f"/equipment/buses/{bus}/equipment", json={"equipmentId": l1["id"], "role": "outgoer", "spareTableId": a})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["outgoingEquipment"][0]["meter"]["tableId"] == a and [m["tableId"] for m in item["spares"]] == [b]
    r = client.post(f"/equipment/buses/{bus}/equipment", json={"equipmentId": l2["id"], "role": "outgoer", "spareTableId": a})
    assert r.status_code == 400 and r.json()["detail"].startswith("NOT_A_SPARE")

    # Re-slotting: same rules (one MFM per relation, a spare needs a free point).
    r = assign(b, l1["id"])
    assert r.status_code == 409 and r.json()["detail"].startswith("RELATION_METERED")
    r = assign(a, None)  # 1 connected + 1 spare = 2 points: no room for another spare
    assert r.status_code == 409 and r.json()["detail"].startswith("NO_FREE_POINT")
    client.put(f"/equipment/buses/{bus}", json={"outgoers": 3})
    assert assign(a, None).status_code == 200
    r = assign(b, l1["id"])
    assert r.status_code == 200 and r.json()["item"]["outgoingEquipment"][0]["meter"]["tableId"] == b
    assert client.put(f"/equipment/buses/{bus}/meters/{b}", json={}).status_code == 400
    assert client.put(f"/equipment/buses/{bus}/meters/nope", json={"equipmentId": None}).status_code == 404

    # Capacity cannot drop below connections + spares.
    r = client.put(f"/equipment/buses/{bus}", json={"outgoers": 1})
    assert r.status_code == 409 and r.json()["detail"].startswith("CAPACITY_BELOW_ATTACHED")


# ---------- Migration from the category model (2026-10-27) ----------
def test_migrates_old_category_model_in_place(meta_query):
    """Old schema: app_equipment_category = Transformer / LT Panel (with type
    single|distribution and group_id), app_equipment_group = EMS..., and
    app_bus_category. After init: types, categories, kinds, bus type rules."""
    from plc_agent.api import appdb

    q = meta_query
    try:
        for t in ("app_bus_type", "app_bus_meter", "app_bus_equipment", "app_bus", "app_equipment",
                  "app_equipment_type", "app_equipment_category"):
            q(f"DROP TABLE IF EXISTS {t} CASCADE")
        q("CREATE TABLE app_equipment_group (id TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0)")
        q("CREATE UNIQUE INDEX ux_equipment_group_name ON app_equipment_group (lower(name))")
        q("INSERT INTO app_equipment_group VALUES ('ems','EMS',1),('source','Source',2),('bms','BMS',3)")
        q("CREATE TABLE app_equipment_category (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
          "type TEXT NOT NULL CHECK (type IN ('single','distribution')), sort_order INTEGER NOT NULL DEFAULT 0, "
          "config_json TEXT, group_id TEXT REFERENCES app_equipment_group(id))")
        q("CREATE UNIQUE INDEX ux_equipment_category_name ON app_equipment_category (lower(name))")
        q("""INSERT INTO app_equipment_category VALUES
             ('transformer','Transformer','single',2,'{"fields":[],"node":{"incomers":1,"outgoers":1}}','ems'),
             ('lt_panel','LT Panel','distribution',4,'{"fields":[]}','ems')""")
        q("CREATE TABLE app_equipment (id TEXT PRIMARY KEY, name TEXT NOT NULL, category_id TEXT NOT NULL "
          "CONSTRAINT fk_equipment_category REFERENCES app_equipment_category(id), description TEXT, created_at TEXT, "
          "updated_at TEXT, subtype TEXT, spare INTEGER NOT NULL DEFAULT 0, values_json TEXT, version INTEGER NOT NULL DEFAULT 1)")
        q("CREATE INDEX ix_equipment_category ON app_equipment (category_id)")
        q("INSERT INTO app_equipment (id, name, category_id) VALUES ('e_tf','TF-1','transformer'), ('e_pcc','PCC-1','lt_panel')")
        q("CREATE TABLE app_bus (id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL, name TEXT NOT NULL, sort_order INTEGER "
          "NOT NULL DEFAULT 0, incomers INTEGER NOT NULL DEFAULT 0, outgoers INTEGER NOT NULL DEFAULT 0, "
          "is_main INTEGER NOT NULL DEFAULT 0, coupled_next INTEGER NOT NULL DEFAULT 0)")
        q("INSERT INTO app_bus VALUES ('b_main','e_tf','main',0,1,1,1,0), ('b_a','e_pcc','Bus A',0,1,2,0,0)")
        q("CREATE TABLE app_bus_category (bus_id TEXT NOT NULL, role TEXT NOT NULL, category_id TEXT NOT NULL, "
          "PRIMARY KEY (bus_id, role, category_id))")
        q("INSERT INTO app_bus_category VALUES ('b_a','incomer','transformer')")
        q("CREATE TABLE app_bus_equipment (bus_id TEXT NOT NULL, equipment_id TEXT NOT NULL, role TEXT NOT NULL, "
          "sort_order INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (bus_id, equipment_id))")
        q("INSERT INTO app_bus_equipment VALUES ('b_a','e_tf','incomer',0)")
        q("DELETE FROM app_meta WHERE key='equipment_types_seeded'")

        appdb.init()

        assert q("SELECT id, kind, category_id, type_id FROM app_equipment ORDER BY id") == [
            ("e_pcc", "distribution", "ems", "lt_panel"), ("e_tf", "single", "ems", "transformer")]
        assert q("SELECT id FROM app_equipment_type ORDER BY sort_order") == [("transformer",), ("lt_panel",)]
        assert q("SELECT id, kinds_json FROM app_equipment_category ORDER BY sort_order") == [
            ("ems", '["single", "distribution"]'), ("source", "[]"), ("bms", "[]")]
        assert q("SELECT bus_id, role, type_id FROM app_bus_type") == [("b_a", "incomer", "transformer")]
        assert "type" not in {r[0] for r in q("SELECT column_name FROM information_schema.columns WHERE table_name='app_equipment_type'")}
        fks = {r[0] for r in q("SELECT conname FROM pg_constraint WHERE contype='f'")}
        assert {"fk_element_category", "fk_element_type", "fk_bus_type_type", "fk_bus_type_bus"} <= fks
        assert "fk_equipment_category" not in fks
        # The type is optional after migration (the old column was NOT NULL).
        assert q("SELECT is_nullable FROM information_schema.columns WHERE table_name='app_equipment' AND column_name='type_id'") == [("YES",)]
        q("INSERT INTO app_equipment (id, name, category_id, kind) VALUES ('e_untyped','U-1','ems','single')")
        appdb.init()  # idempotent
        assert q("SELECT count(*) FROM app_equipment")[0][0] == 3
    finally:
        # Leave a fresh, current schema for the other tests.
        for t in ("app_bus_type", "app_bus_meter", "app_bus_equipment", "app_bus", "app_equipment",
                  "app_equipment_type", "app_equipment_category", "app_equipment_group", "app_bus_category"):
            q(f"DROP TABLE IF EXISTS {t} CASCADE")
        q("DELETE FROM app_meta WHERE key='equipment_types_seeded'")
        appdb.init()


# ---------- Zones ----------
def test_zones_crud_and_on_elements(api, client):
    r = client.post("/equipment/zones", json={"name": "North"})
    assert r.status_code == 200, r.text
    north = r.json()["item"]
    south = client.post("/equipment/zones", json={"name": "South"}).json()["item"]
    assert north["id"].startswith("zone_") and north["used"] == 0 and south["sortOrder"] == north["sortOrder"] + 1
    r = client.post("/equipment/zones", json={"name": "north"})
    assert r.status_code == 409 and r.json()["detail"].startswith("ZONE_EXISTS")

    tf = api.create_equipment("TF-Z", "transformer", zoneId=north["id"])
    assert (tf["zoneId"], tf["zoneName"]) == (north["id"], "North")
    api.create_equipment("PCC-Z", "lt_panel")
    assert [i["name"] for i in client.get("/equipment", params={"zoneId": north["id"]}).json()["items"]] == ["TF-Z"]
    r = client.post("/equipment", json={"name": "X", "categoryId": "ems", "kind": "single", "zoneId": "nope"})
    assert r.status_code == 404 and r.json()["detail"].startswith("ZONE_NOT_FOUND")

    r = client.put(f"/equipment/zones/{north['id']}", json={"name": "North Block"})
    assert r.status_code == 200 and r.json()["item"] == {**north, "name": "North Block", "used": 1}
    assert client.get(f"/equipment/{tf['id']}").json()["item"]["zoneName"] == "North Block"
    r = client.delete(f"/equipment/zones/{north['id']}")
    assert r.status_code == 409 and r.json()["detail"].startswith("ZONE_IN_USE: 1")
    r = client.put(f"/equipment/{tf['id']}", json={"zoneId": None})
    assert r.status_code == 200 and r.json()["item"]["zoneId"] is None
    assert client.delete(f"/equipment/zones/{north['id']}").status_code == 200
    assert [z["name"] for z in client.get("/equipment/zones").json()["items"]] == ["South"]
