"""Tier 1 — error-path validation.

Each test asserts the exact error code string the API returns today.
"""
from __future__ import annotations

import conftest as cf


def _detail(resp) -> str:
    return str(resp.json().get("detail", ""))


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
def test_field_type_invalid(client):
    r = client.post(
        "/schemas",
        json={"name": "ve_type", "fields": [{"key": "v", "type": "banana"}]},
    )
    assert r.status_code == 400
    assert _detail(r).startswith("FIELD_TYPE_INVALID")


def test_field_key_duplicate(client):
    r = client.post(
        "/schemas",
        json={
            "name": "ve_dup",
            "fields": [
                {"key": "v", "type": "float32"},
                {"key": "v", "type": "float32"},
            ],
        },
    )
    assert r.status_code == 400
    assert _detail(r).startswith("FIELD_KEY_DUPLICATE")


def test_formula_unknown_vars(client):
    r = client.post(
        "/schemas",
        json={
            "name": "ve_unknown",
            "fields": [
                {"key": "v", "type": "float32"},
                {"key": "d", "type": "float64", "formula": "v * not_a_field"},
            ],
        },
    )
    assert r.status_code == 400
    assert _detail(r).startswith("FORMULA_UNKNOWN_VARS")
    assert "not_a_field" in _detail(r)


def test_formula_circular_dependency_two_node_cycle(client):
    # a -> b -> a : a genuine 2-node cycle IS caught by Kahn's sort.
    # (The 1-node self-cycle a -> a is NOT — that is open finding DP1,
    # covered as xfail in test_pending_fixes.py.)
    r = client.post(
        "/schemas",
        json={
            "name": "ve_cycle",
            "fields": [
                {"key": "x", "type": "float32"},
                {"key": "a", "type": "float64", "formula": "b + x"},
                {"key": "b", "type": "float64", "formula": "a + x"},
            ],
        },
    )
    assert r.status_code == 400
    assert _detail(r).startswith("FORMULA_CIRCULAR_DEPENDENCY")


# ---------------------------------------------------------------------------
# Migrate payload
# ---------------------------------------------------------------------------
def test_migrate_bad_payload_no_table_ids(client):
    # GETTING_STARTED.md's documented key "tableIds" is wrong (finding E2E3);
    # the endpoint only reads "ids"/"id" and 400s otherwise.
    r = client.post("/tables/migrate", json={"tableIds": ["whatever"]})
    assert r.status_code == 400
    assert _detail(r) == "NO_TABLE_IDS"


def test_migrate_unknown_table_reports_table_not_found_per_item(client):
    # Current contract: migrate is a batch endpoint that returns 200 with a
    # per-item error rather than failing the whole request.
    r = client.post("/tables/migrate", json={"ids": ["tbl_does_not_exist"]})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["id"] == "tbl_does_not_exist"
    assert items[0]["error"] == "TABLE_NOT_FOUND"


def test_delete_unknown_table_404_table_not_found(client):
    r = client.delete("/tables/tbl_does_not_exist")
    assert r.status_code == 404
    assert _detail(r) == "TABLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Job preflight
# ---------------------------------------------------------------------------
def test_job_create_unmapped_table_no_mapped_columns(api, client):
    schema = api.create_schema("ve_job", [{"key": "v", "type": "float32"}])
    target_id = api.create_pg_target()
    table_id = api.bulk_create(schema["id"], ["ve_job_t1"], target_id)[0]["id"]
    # no mapping applied -> preflight must reject
    r = client.post(
        "/jobs2",
        json={"name": "ve_job", "type": "continuous", "tables": [table_id], "intervalMs": 1000},
    )
    assert r.status_code == 400
    assert _detail(r) == "NO_MAPPED_COLUMNS"


def test_job_create_unknown_table_no_mapped_columns(client):
    # A nonexistent table id also surfaces as NO_MAPPED_COLUMNS today
    # (store.create_job treats missing tables as Unmapped).
    r = client.post(
        "/jobs2",
        json={"name": "ve_job2", "type": "continuous", "tables": ["tbl_ghost"], "intervalMs": 1000},
    )
    assert r.status_code == 400
    assert _detail(r) == "NO_MAPPED_COLUMNS"


def test_bulk_create_unknown_schema_404(client):
    r = client.post("/tables/bulk_create", json={"schemaId": "sch_ghost", "names": ["t1"]})
    assert r.status_code == 404
    assert _detail(r) == "PARENT_SCHEMA_NOT_FOUND"
