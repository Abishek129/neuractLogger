"""Tier 1 — wire the standalone derived-parameters harness in as a regression
oracle.

validate_derived_params.py (repo root) AST-loads the REAL validator from
agent/plc_agent/api/routers/schemas.py and replays a 74-case corpus
(derived_param_cases.json) against it plus a simulated Rust/meval evaluator.
Exit code 0 == all non-skipped cases pass.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import conftest as cf


@pytest.mark.slow
@pytest.mark.timeout(330)
def test_validate_derived_params_corpus_passes():
    proc = subprocess.run(
        [sys.executable, "validate_derived_params.py"],
        cwd=str(cf.REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        "derived-params oracle failed (rc={}):\n--- tail of output ---\n{}".format(
            proc.returncode, (proc.stdout + proc.stderr)[-3000:]
        )
    )
