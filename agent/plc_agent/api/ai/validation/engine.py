# mypy: ignore-errors
"""
Validation engine — orchestrates parameter classification, range checks,
and cross-parameter consistency checks into a single ValidationResult.

Pure logic. No FastAPI, no Hermes, no Store dependency.
"""
from __future__ import annotations

import logging
from typing import Any

from .params import classify_readings
from .rules import ALL_CROSS_CHECKS, check_range
from .types import (
    CheckResult,
    Confidence,
    ParameterType,
    Severity,
    ValidationResult,
)

logger = logging.getLogger("loggerfast.ai.validation")

# ---------------------------------------------------------------------------
# Confidence scoring penalties (tunable)
# ---------------------------------------------------------------------------

_PENALTY_RANGE_FAIL = 0.15
_PENALTY_RANGE_WARN = 0.05
_PENALTY_CROSS_FAIL = 0.10
_PENALTY_CROSS_WARN = 0.03


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------

def _compute_confidence(checks: list[CheckResult]) -> tuple[Confidence, float]:
    """Compute confidence from check results.

    Starts at 1.0, subtracts penalties per check severity.
    Only checks that actually ran count.
    """
    if not checks:
        # No checks ran (e.g. all params unknown) — can't validate
        return Confidence.LOW, 0.0

    score = 1.0
    for c in checks:
        is_cross = c.check_id.startswith("cross.")
        if c.severity == Severity.FAIL:
            score -= _PENALTY_CROSS_FAIL if is_cross else _PENALTY_RANGE_FAIL
        elif c.severity == Severity.WARNING:
            score -= _PENALTY_CROSS_WARN if is_cross else _PENALTY_RANGE_WARN

    score = max(0.0, min(1.0, score))

    if score >= 0.9:
        return Confidence.HIGH, score
    if score >= 0.7:
        return Confidence.MEDIUM, score
    return Confidence.LOW, score


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(checks: list[CheckResult], confidence: Confidence, score: float) -> str:
    """Build a one-line human-readable summary."""
    passed = sum(1 for c in checks if c.severity == Severity.PASS)
    warned = sum(1 for c in checks if c.severity == Severity.WARNING)
    failed = sum(1 for c in checks if c.severity == Severity.FAIL)
    total = len(checks)

    parts = []

    if failed == 0 and warned == 0:
        parts.append(f"All {total} checks passed")
    else:
        if failed > 0:
            fail_msgs = [c.message for c in checks if c.severity == Severity.FAIL]
            parts.append(f"{failed} failure(s): {'; '.join(fail_msgs[:3])}")
        if warned > 0:
            warn_msgs = [c.message for c in checks if c.severity == Severity.WARNING]
            parts.append(f"{warned} warning(s): {'; '.join(warn_msgs[:3])}")

    parts.append(f"Confidence: {confidence.value} ({score*100:.0f}%)")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_PENALTY_KB_UNVERIFIED = 0.10


def validate_readings(
    readings: dict[str, float],
    *,
    schema_fields: list[dict[str, Any]] | None = None,
    kb_registers: list[dict[str, Any]] | None = None,
    ct_rating: float | None = None,
    kb_verified: bool = True,
) -> ValidationResult:
    """Validate a set of MFM readings using rule-based checks.

    Args:
        readings: field_key → value (e.g. {"voltage_l1n": 231.5, ...})
        schema_fields: Optional schema field metadata for unit annotation
        kb_registers: Optional KB register metadata for parameter identification
        ct_rating: Optional CT rating for current upper-bound validation
        kb_verified: Whether the KB entry has been verified by an engineer.
            Unverified (draft) entries receive a confidence penalty.

    Returns:
        ValidationResult with per-check results and confidence score.
    """
    # 1. Classify parameters
    classified = classify_readings(
        readings,
        schema_fields=schema_fields,
        kb_registers=kb_registers,
    )

    params_classified = sum(1 for p in classified if p.param_type != ParameterType.UNKNOWN)
    params_unknown = sum(1 for p in classified if p.param_type == ParameterType.UNKNOWN)

    # 2. Range checks (one per classified param)
    checks: list[CheckResult] = []

    # Warn if KB entry is unverified
    if not kb_verified:
        checks.append(CheckResult(
            check_id="meta.kb_unverified",
            severity=Severity.WARNING,
            message="KB entry is an unverified draft — register map may be inaccurate. Results should be treated with lower confidence.",
            expected="verified KB entry",
            actual="unverified draft",
            field_keys=(),
        ))

    for param in classified:
        result = check_range(param, ct_rating=ct_rating)
        if result is not None:
            checks.append(result)

    # 3. Cross-parameter checks (on all classified params together)
    known_params = [p for p in classified if p.param_type != ParameterType.UNKNOWN]
    for cross_fn in ALL_CROSS_CHECKS:
        result = cross_fn(known_params)
        if result is not None:
            checks.append(result)

    # 4. Confidence scoring (with optional KB unverified penalty)
    confidence, score = _compute_confidence(checks)
    if not kb_verified:
        score = max(0.0, score - _PENALTY_KB_UNVERIFIED)
        # Re-classify confidence after penalty
        if score >= 0.9:
            confidence = Confidence.HIGH
        elif score >= 0.7:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW

    # 5. Summary
    summary = _build_summary(checks, confidence, score)

    return ValidationResult(
        confidence=confidence,
        confidence_score=score,
        checks=checks,
        summary=summary,
        params_classified=params_classified,
        params_unknown=params_unknown,
    )
