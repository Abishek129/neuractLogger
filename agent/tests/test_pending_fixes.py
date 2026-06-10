"""Known-bug regression file.

Each test asserts the CORRECT behavior for a finding from
FINDINGS_VERIFIED.md. These started life as xfail(strict=False) contracts
while the bugs were open; the fixes landed (hardening rounds 1-2, 2026-06-10)
and the markers were removed to lock the fixes in as hard regressions.

Findings covered:
  DP1  — self-referential derived formula accepted by the validator
  DP5  — POST /schemas/import bypasses all field/formula validation
  C2   — POST /auth/register is public (remainder of the C2 finding)
  E2E  — DELETE /devices/{id} has no auth guard (noted in E2E survey)
"""
from __future__ import annotations

def test_dp1_self_referential_formula_rejected(client):
    r = client.post(
        "/schemas",
        json={
            "name": "dp1_selfref",
            "fields": [
                {"key": "delta", "type": "float32"},
                # 'accumulator' trap: references itself
                {"key": "acc", "type": "float64", "formula": "acc + delta"},
            ],
        },
    )
    # Correct behavior: reject as a (1-node) circular dependency.
    assert r.status_code == 400, (
        f"self-referential formula was accepted (HTTP {r.status_code}): {r.text}"
    )
    detail = str(r.json().get("detail", ""))
    assert "FORMULA_CIRCULAR_DEPENDENCY" in detail or "FORMULA_SELF_REFERENCE" in detail


def test_dp5_schemas_import_validates_like_create(client):
    payload = {
        "schemas": [
            {
                "id": "sch_dp5_bad",
                "name": "dp5_bad",
                "fields": [
                    {"key": "ok_field", "type": "float32"},
                    # formula references a variable that does not exist —
                    # create_schema would 400 with FORMULA_UNKNOWN_VARS
                    {"key": "bad", "type": "float64", "formula": "no_such_var * 2"},
                ],
            }
        ]
    }
    r = client.post("/schemas/import", json=payload)
    # Correct behavior: imports run the same validation pipeline as create.
    assert r.status_code == 400, (
        f"import with invalid formula was accepted (HTTP {r.status_code}): {r.text}"
    )


def test_c2_register_rejects_anonymous_before_keycloak(no_auth, client):
    # KC_URL points at a dead port in this harness, so if the endpoint gets as
    # far as calling Keycloak it fails with 400/500 — proving auth was NOT
    # enforced first. Correct behavior: 401/403 BEFORE any Keycloak call.
    r = client.post(
        "/auth/register",
        json={
            "username": "pytest_anon",
            "email": "pytest_anon@example.invalid",
            "password": "irrelevant",
        },
    )
    assert r.status_code in (401, 403), (
        f"register did not reject anonymous caller pre-Keycloak (HTTP {r.status_code}): {r.text}"
    )


def test_delete_device_requires_token(no_auth, client):
    r = client.delete("/devices/dev_does_not_exist")
    # Correct behavior: 401 without a token. Today the handler runs (no auth
    # guard) and returns 404 DEVICE_NOT_FOUND.
    assert r.status_code == 401, (
        f"DELETE /devices ran without auth (HTTP {r.status_code}): {r.text}"
    )
