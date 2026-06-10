"""Tier 1 — regression locks for the data-integrity / derived-params / DDL
fix round (findings DP1, DP2, DP3, DP5, DP6, DP7, SEC-2, L19, L6, L2,
H-DBC-2, M19 and the two Store bugs found by the test build).

Each test cites the finding id from FINDINGS_VERIFIED.md it locks in.
"""
from __future__ import annotations

import conftest as cf


def _detail(resp) -> str:
    return str(resp.json().get("detail", ""))


# ---------------------------------------------------------------------------
# DP1 — self-referential formulas rejected at EVERY entry point
# (the create_schema path is covered by the now-XPASS test_pending_fixes.py)
# ---------------------------------------------------------------------------
def test_dp1_self_ref_rejected_on_add_field(api, client):
    schema = api.create_schema("dp1_add", [{"key": "delta", "type": "float32"}])
    r = client.post(
        f"/schemas/{schema['id']}/fields",
        json={"key": "acc", "formula": "acc + delta"},
    )
    assert r.status_code == 400
    assert "FORMULA_SELF_REFERENCE" in _detail(r)


def test_dp1_self_ref_rejected_on_patch_field(api, client):
    schema = api.create_schema(
        "dp1_patch",
        [
            {"key": "v", "type": "float32"},
            {"key": "d", "type": "float64", "formula": "v * 2"},
        ],
    )
    r = client.patch(
        f"/schemas/{schema['id']}/fields/d", json={"formula": "d + v"}
    )
    assert r.status_code == 400
    assert "FORMULA_SELF_REFERENCE" in _detail(r)


def test_dp1_self_ref_rejected_on_import(client):
    r = client.post(
        "/schemas/import",
        json={
            "schemas": [
                {
                    "name": "dp1_imp",
                    "fields": [
                        {"key": "delta", "type": "float32"},
                        {"key": "acc", "type": "float64", "formula": "acc + delta"},
                    ],
                }
            ]
        },
    )
    assert r.status_code == 400
    assert "FORMULA_SELF_REFERENCE" in _detail(r)


# ---------------------------------------------------------------------------
# DP2 — coherent eval_order persistence + migrate-time self-healing
# ---------------------------------------------------------------------------
def test_dp2_add_field_persists_recomputed_orders_for_all_derived(api, client, meta_query):
    schema = api.create_schema(
        "dp2_orders",
        [
            {"key": "base", "type": "float32"},
            {"key": "c1", "type": "float64", "formula": "base + 1"},
        ],
    )
    sid = schema["id"]
    # only derived field -> order 0
    assert {f["key"]: f.get("eval_order") for f in schema["fields"] if f.get("formula")} == {"c1": 0}
    # Adding c0 reorders the peer (queue is sorted lexicographically): c0=0, c1=1.
    r = client.post(f"/schemas/{sid}/fields", json={"key": "c0", "formula": "base * 2"})
    assert r.status_code == 200, r.text
    rows = meta_query(
        "SELECT key, eval_order FROM app_schema_fields WHERE schema_id=%s AND formula IS NOT NULL",
        (sid,),
    )
    # DP2: the OLD code persisted only the touched field, leaving c1's stored
    # order stale (a live inversion existed in meta_data_version1).
    assert dict(rows) == {"c0": 0, "c1": 1}


def test_dp2_migrate_self_heals_corrupt_stored_eval_order(api, client, target_query):
    from plc_agent.api.store import Store

    schema = api.create_schema(
        "dp2_heal",
        [
            {"key": "base", "type": "float32"},
            {"key": "d1", "type": "float64", "formula": "base + 1"},
            {"key": "d2", "type": "float64", "formula": "d1 + 1"},
        ],
    )
    sid = schema["id"]
    target_id = api.create_pg_target()
    table_id = api.bulk_create(sid, ["dp2_heal_t"], target_id)[0]["id"]
    # Corrupt the stored topological order (mirrors the live sch_1773858592326
    # inversion) and pull the corruption into the Store's memory.
    cf.pg_query(
        cf.META_DB,
        "UPDATE app_schema_fields SET eval_order = CASE key WHEN 'd1' THEN 1 WHEN 'd2' THEN 0 END "
        "WHERE schema_id=%s AND key IN ('d1','d2')",
        (sid,),
    )
    Store.instance().load_from_app_db()
    res = api.migrate([table_id])
    assert res["items"][0].get("status") in ("created", "updated"), res
    # migrate must recompute the order from the formulas, not trust the DB.
    rows = dict(
        target_query(
            "SELECT field_key, scale FROM neuract.device_mappings "
            "WHERE table_name=%s AND protocol='derived'",
            ("dp2_heal_t",),
        )
    )
    assert rows == {"d1": 0.0, "d2": 1.0}, f"eval_order not self-healed: {rows}"


# ---------------------------------------------------------------------------
# DP3 — whitelist == real meval 0.2 builtins; pi/e usable
# ---------------------------------------------------------------------------
def test_dp3_real_meval_builtins_accepted(api):
    schema = api.create_schema(
        "dp3_builtins",
        [
            {"key": "v", "type": "float32"},
            {
                "key": "d",
                "type": "float64",
                "formula": "floor(v) + ceil(v) + round(v) + signum(v) + atan2(v, 2) + sin(pi) + e",
            },
        ],
    )
    assert any(f["key"] == "d" for f in schema["fields"])


def test_dp3_pow_log_log2_rejected_at_validation(api, client):
    # pow/log/log2 validated under the old whitelist but meval has none of
    # them -> permanent NULL at runtime. Now a 400 at config time.
    for formula in ("pow(v, 2)", "log(v)", "log2(v)"):
        r = client.post(
            "/schemas",
            json={
                "name": f"dp3_{formula[:3]}",
                "fields": [
                    {"key": "v", "type": "float32"},
                    {"key": "d", "type": "float64", "formula": formula},
                ],
            },
        )
        assert r.status_code == 400, f"{formula} was accepted: {r.text}"
        assert "FORMULA_UNKNOWN_FUNCTION" in _detail(r)


def test_dp3_function_named_field_usable_as_variable(api):
    # DP9 refutation: meval resolves Var and Call in separate namespaces, so a
    # field named like a function is referenceable as a bare variable.
    schema = api.create_schema(
        "dp3_shadow",
        [
            {"key": "min", "type": "float32"},
            {"key": "z", "type": "float64", "formula": "min * 2"},
        ],
    )
    z = next(f for f in schema["fields"] if f["key"] == "z")
    assert z.get("eval_order") == 0


# ---------------------------------------------------------------------------
# DP5 — /schemas/import has full create parity
# ---------------------------------------------------------------------------
def test_dp5_import_rejects_bad_key_type_and_dup(client):
    base = {"key": "ok", "type": "float32"}
    bad_items = [
        ([{**base}, {"key": "bad key;drop", "type": "float32"}], "FIELD_KEY_INVALID"),
        ([{**base}, {"key": "t", "type": "banana"}], "FIELD_TYPE_INVALID"),
        ([{**base}, {**base}], "FIELD_KEY_DUPLICATE"),
    ]
    for fields, code in bad_items:
        r = client.post(
            "/schemas/import",
            json={"schemas": [{"name": "dp5_bad", "fields": fields}]},
        )
        assert r.status_code == 400, f"{code}: import accepted {r.text}"
        assert code in _detail(r)


def test_dp5_import_recomputes_eval_order(client, meta_query):
    # Imported eval_order values are garbage on purpose — the import must
    # recompute the topological order from the formulas (self-healing).
    r = client.post(
        "/schemas/import",
        json={
            "schemas": [
                {
                    "id": "sch_dp5_order",
                    "name": "dp5_order",
                    "fields": [
                        {"key": "base", "type": "float32"},
                        {"key": "d1", "type": "float64", "formula": "base + 1", "eval_order": 7},
                        {"key": "d2", "type": "float64", "formula": "d1 + 1", "eval_order": 0},
                    ],
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    rows = meta_query(
        "SELECT key, eval_order FROM app_schema_fields "
        "WHERE schema_id='sch_dp5_order' AND formula IS NOT NULL"
    )
    assert dict(rows) == {"d1": 0, "d2": 1}


# ---------------------------------------------------------------------------
# DP6 — formula syntax check, derived type whitelist, formula clearing,
#       duplicate-add conflict
# ---------------------------------------------------------------------------
def test_dp6a_formula_syntax_rejected(client):
    for formula in ("voltage +* 2", "DROP TABLE x", "voltage +", "sqrt(voltage",
                    "atan2(voltage)", "voltage $ 2"):
        r = client.post(
            "/schemas",
            json={
                "name": "dp6a",
                "fields": [
                    {"key": "voltage", "type": "float32"},
                    {"key": "d", "type": "float64", "formula": formula},
                ],
            },
        )
        assert r.status_code == 400, f"syntax accepted: {formula!r} -> {r.text}"
        assert "FORMULA_SYNTAX_INVALID" in _detail(r), f"{formula!r}: {_detail(r)}"


def test_dp6b_derived_type_restricted_and_defaulted(api, client):
    # invalid derived type -> 400 (was: any string accepted)
    r = client.post(
        "/schemas",
        json={
            "name": "dp6b_bad",
            "fields": [
                {"key": "v", "type": "float32"},
                {"key": "d", "type": "banana", "formula": "v * 2"},
            ],
        },
    )
    assert r.status_code == 400
    assert "FIELD_TYPE_INVALID" in _detail(r)
    # no type -> defaults to float64
    schema = api.create_schema(
        "dp6b_ok",
        [
            {"key": "v", "type": "float32"},
            {"key": "d", "formula": "v * 2"},
        ],
    )
    d = next(f for f in schema["fields"] if f["key"] == "d")
    assert d["type"] == "float64"


def test_dp6c_patch_can_clear_formula(api, client, meta_query):
    schema = api.create_schema(
        "dp6c",
        [
            {"key": "v", "type": "float32"},
            {"key": "d", "type": "float64", "formula": "v * 2"},
        ],
    )
    sid = schema["id"]
    r = client.patch(f"/schemas/{sid}/fields/d", json={"formula": ""})
    assert r.status_code == 200, r.text
    item_fields = {f["key"]: f for f in r.json()["item"]["fields"]}
    assert not item_fields["d"].get("formula"), "formula not cleared (DP6c)"
    row = meta_query(
        "SELECT formula, eval_order FROM app_schema_fields WHERE schema_id=%s AND key='d'",
        (sid,),
    )[0]
    assert row == (None, None)


def test_dp6d_add_existing_key_conflicts(api, client):
    schema = api.create_schema("dp6d", [{"key": "v", "type": "float32"}])
    r = client.post(f"/schemas/{schema['id']}/fields", json={"key": "v", "type": "float32"})
    assert r.status_code == 409
    assert "FIELD_KEY_EXISTS" in _detail(r)


# ---------------------------------------------------------------------------
# DP7 — lifecycle: schema edits propagate to device_mappings of migrated
#       tables; mapping import preserves derived rows
# ---------------------------------------------------------------------------
def _derived_rows(target_query, table):
    return {
        k: (a, s)
        for k, a, s in target_query(
            "SELECT field_key, address, scale FROM neuract.device_mappings "
            "WHERE table_name=%s AND protocol='derived'",
            (table,),
        )
    }


def test_dp7_field_edits_propagate_to_migrated_tables(api, client, target_query):
    schema = api.create_schema(
        "dp7_life",
        [
            {"key": "voltage", "type": "float32"},
            {"key": "s", "type": "float64", "formula": "voltage * 2"},
        ],
    )
    sid = schema["id"]
    target_id = api.create_pg_target()
    api.migrate([api.bulk_create(sid, ["dp7_t"], target_id)[0]["id"]])
    assert _derived_rows(target_query, "dp7_t") == {"s": ("voltage * 2", 0.0)}

    # PATCH formula -> mapping row updated WITHOUT a re-migrate
    r = client.patch(f"/schemas/{sid}/fields/s", json={"formula": "voltage * 3"})
    assert r.status_code == 200, r.text
    assert _derived_rows(target_query, "dp7_t") == {"s": ("voltage * 3", 0.0)}

    # POST new derived field -> new row appears with its eval_order
    r = client.post(f"/schemas/{sid}/fields", json={"key": "s2", "formula": "s + 1"})
    assert r.status_code == 200, r.text
    assert _derived_rows(target_query, "dp7_t") == {
        "s": ("voltage * 3", 0.0),
        "s2": ("s + 1", 1.0),
    }

    # Deleting a field other formulas reference is blocked
    r = client.delete(f"/schemas/{sid}/fields/s")
    assert r.status_code == 400
    assert "FIELD_REFERENCED_BY_FORMULA" in _detail(r)

    # DELETE leaf derived field -> its mapping row is removed (no ghost eval)
    r = client.delete(f"/schemas/{sid}/fields/s2")
    assert r.status_code == 200, r.text
    assert _derived_rows(target_query, "dp7_t") == {"s": ("voltage * 3", 0.0)}

    # Clearing the formula (derived -> regular) also removes the row
    r = client.patch(f"/schemas/{sid}/fields/s", json={"formula": None})
    assert r.status_code == 200, r.text
    assert _derived_rows(target_query, "dp7_t") == {}


def test_dp7b_mapping_import_preserves_derived_rows(api, client, target_query):
    schema = api.create_schema(
        "dp7b",
        [
            {"key": "voltage", "type": "float32"},
            {"key": "s", "type": "float64", "formula": "voltage * 2"},
        ],
    )
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["dp7b_t"], target_id)[0]["id"]
    api.migrate([table_id])
    assert _derived_rows(target_query, "dp7b_t") == {"s": ("voltage * 2", 0.0)}

    # import replaces manual rows but must keep (and not duplicate) derived
    # rows — the old code DELETEd ALL rows and reinserted only manual ones.
    r = client.post(
        f"/mappings/{table_id}/import",
        json={
            "mapping": {
                "rows": {
                    "voltage": {"protocol": "modbus", "address": "0", "dataType": "float"},
                    # manual attempt to map the derived field must be stripped
                    "s": {"protocol": "modbus", "address": "99", "dataType": "float"},
                }
            }
        },
    )
    assert r.status_code == 200, r.text
    assert _derived_rows(target_query, "dp7b_t") == {"s": ("voltage * 2", 0.0)}
    manual = target_query(
        "SELECT field_key, protocol FROM neuract.device_mappings "
        "WHERE table_name=%s AND protocol='modbus'",
        ("dp7b_t",),
    )
    assert manual == [("voltage", "modbus")]


# ---------------------------------------------------------------------------
# SEC-2 / L19 / L6 — identifier validation + quoted DDL
# ---------------------------------------------------------------------------
def test_sec2_mapping_field_keys_charset_validated(api, client):
    schema = api.create_schema("sec2_keys", [{"key": "v", "type": "float32"}])
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["sec2_t"], target_id)[0]["id"]
    hostile = 'x INTEGER); DROP TABLE neuract.sec2_t;--'
    for path in (f"/mappings/{table_id}", f"/mappings/{table_id}/bulk_apply",
                 f"/mappings/{table_id}/import"):
        r = client.post(path, json={"rows": {hostile: {"protocol": "modbus", "address": "0"}}})
        assert r.status_code == 400, f"{path} accepted hostile key: {r.text}"
        assert "FIELD_KEY_INVALID" in _detail(r)


def test_sec2_field_key_length_cap(client):
    r = client.post(
        "/schemas",
        json={"name": "sec2_len", "fields": [{"key": "k" * 64, "type": "float32"}]},
    )
    assert r.status_code == 400
    assert "FIELD_KEY_INVALID" in _detail(r)


def test_l6_reserved_word_field_keys_survive_quoted_ddl(api, client, target_query):
    # 'select' / 'order' are legal per the key regex but are SQL reserved
    # words — the unquoted ALTER/CREATE DDL used to be one bypass away from
    # breakage/injection. With identifier quoting both paths work.
    schema = api.create_schema("l6_quoted", [{"key": "select", "type": "float32"}])
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["l6_t"], target_id)[0]["id"]
    res = api.migrate([table_id])
    assert res["items"][0]["status"] == "created", res
    # add another reserved-word column -> exercises the ALTER TABLE path
    r = client.post(f"/schemas/{schema['id']}/fields", json={"key": "order", "type": "float32"})
    assert r.status_code == 200, r.text
    res = api.migrate([table_id])
    assert res["items"][0]["status"] == "updated", res
    cols = {
        row[0]
        for row in target_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='neuract' AND table_name='l6_t'"
        )
    }
    assert {"select", "order", "timestamp_utc"} <= cols


# ---------------------------------------------------------------------------
# H-DBC-2 — migrate is per-table fault-isolated
# ---------------------------------------------------------------------------
def test_hdbc2_migrate_batch_isolates_target_failures(api, client, meta_query):
    schema = api.create_schema("hdbc2", [{"key": "v", "type": "float32"}])
    good_target = api.create_pg_target()
    r = client.post(
        "/storage/targets",
        json={"provider": "postgres", "conn": "postgresql://postgres@127.0.0.1:1/nope"},
    )
    assert r.status_code == 200
    bad_target = r.json()["item"]["id"]
    bad = api.bulk_create(schema["id"], ["hdbc2_bad"], bad_target)[0]
    good = api.bulk_create(schema["id"], ["hdbc2_good"], good_target)[0]
    # bad table FIRST: under the old code its exception 500'd the whole batch
    res = client.post("/tables/migrate", json={"ids": [bad["id"], good["id"]]})
    assert res.status_code == 200, res.text  # 200-batch contract preserved
    items = {i["id"]: i for i in res.json()["items"]}
    assert items[bad["id"]].get("error") == "MIGRATE_FAILED", items
    assert items[good["id"]].get("status") in ("created", "updated"), items
    statuses = dict(
        meta_query(
            "SELECT id, status FROM app_device_tables WHERE id IN (%s, %s)",
            (bad["id"], good["id"]),
        )
    )
    # failed table's catalog status is unchanged; good one is migrated
    assert statuses[bad["id"]] == "not_migrated"
    assert statuses[good["id"]] == "migrated"


# ---------------------------------------------------------------------------
# Store bugs found by the test build
# ---------------------------------------------------------------------------
def test_store_resync_clears_ghost_mappings(client):
    # 9(a): load_from_app_db now resets _mappings (conftest workaround removed)
    from plc_agent.api.store import Store

    store = Store.instance()
    store._mappings["tbl_ghost_9a"] = {
        "deviceId": None,
        "rows": {"v": {"protocol": "modbus", "address": "1"}},
    }
    store.load_from_app_db()
    assert store.get_mapping("tbl_ghost_9a")["rows"] == {}


def test_derived_only_table_job_creation_succeeds(api, client):
    # 9(b): a table whose loggable fields are ALL derived needs no device
    # mapping rows — create_job used to reject it with NO_MAPPED_COLUMNS
    # because mapping_health was called without schema_fields.
    schema = api.create_schema(
        "store9b",
        [{"key": "const_out", "type": "float64", "formula": "pi * 2"}],
    )
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["store9b_t"], target_id)[0]["id"]
    api.migrate([table_id])
    r = client.post(
        "/jobs2",
        json={"name": "store9b_job", "type": "continuous", "tables": [table_id], "intervalMs": 1000},
    )
    assert r.status_code == 200, f"derived-only table rejected: {r.text}"
    assert r.json()["item"]["status"] == "stopped"
