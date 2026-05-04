# mypy: ignore-errors
"""
Validation data types — enums and dataclasses for Layer 1 rule-based validation.

Pure data — no logic, no imports beyond stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ParameterType(str, Enum):
    """Electrical parameter types recognised by the validator."""
    VOLTAGE_LN = "voltage_ln"
    VOLTAGE_LL = "voltage_ll"
    CURRENT = "current"
    POWER_FACTOR = "power_factor"
    FREQUENCY = "frequency"
    ACTIVE_POWER = "active_power"
    REACTIVE_POWER = "reactive_power"
    APPARENT_POWER = "apparent_power"
    ENERGY_ACTIVE = "energy_active"
    ENERGY_REACTIVE = "energy_reactive"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class Confidence(str, Enum):
    HIGH = "high"       # >90%
    MEDIUM = "medium"   # 70-90%
    LOW = "low"         # <70%


@dataclass(frozen=True)
class ClassifiedParam:
    """A reading after parameter identification."""
    key: str                        # Original field key (e.g. "voltage_l1n")
    param_type: ParameterType
    phase: int | None               # 1, 2, 3 or None for totals/avg
    value: float
    unit: str                       # From schema or inferred


@dataclass(frozen=True)
class CheckResult:
    """Result of a single validation check."""
    check_id: str                   # e.g. "range.voltage_l1n", "cross.vln_vll"
    severity: Severity
    message: str                    # Human-readable description
    expected: str                   # e.g. "220-254V"
    actual: str                     # e.g. "231.5V"
    field_keys: tuple[str, ...]     # Original field keys involved


@dataclass
class ValidationResult:
    """Complete validation output for a set of readings."""
    confidence: Confidence
    confidence_score: float         # 0.0 - 1.0
    checks: list[CheckResult]
    summary: str                    # One-line human summary
    params_classified: int          # How many params were identified
    params_unknown: int             # How many could not be classified
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # -- serialisation --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence.value,
            "confidence_score": round(self.confidence_score, 3),
            "summary": self.summary,
            "params_classified": self.params_classified,
            "params_unknown": self.params_unknown,
            "timestamp": self.timestamp,
            "checks": [
                {
                    "check_id": c.check_id,
                    "severity": c.severity.value,
                    "message": c.message,
                    "expected": c.expected,
                    "actual": c.actual,
                    "field_keys": list(c.field_keys),
                }
                for c in self.checks
            ],
        }

    def to_ndjson_event(self) -> dict[str, Any]:
        passed = sum(1 for c in self.checks if c.severity == Severity.PASS)
        warned = sum(1 for c in self.checks if c.severity == Severity.WARNING)
        failed = sum(1 for c in self.checks if c.severity == Severity.FAIL)
        return {
            "event": "validation",
            "confidence": self.confidence.value,
            "confidence_score": round(self.confidence_score, 3),
            "checks_passed": passed,
            "checks_warned": warned,
            "checks_failed": failed,
            "summary": self.summary,
        }
