# mypy: ignore-errors
"""
LoggerFast AI Validation — Rule-based + anomaly detection for electrical readings.

Phase 1H: Static thresholds + cross-parameter consistency.
Phase 1I: Anomaly detection autoencoder (per MFM model family).
"""
from .engine import validate_readings
from .types import (
    CheckResult,
    ClassifiedParam,
    Confidence,
    ParameterType,
    Severity,
    ValidationResult,
)
from .anomaly import AnomalyDetector
from .anomaly_types import AnomalyResult

__all__ = [
    "validate_readings",
    "ValidationResult",
    "CheckResult",
    "ClassifiedParam",
    "Confidence",
    "ParameterType",
    "Severity",
    "AnomalyDetector",
    "AnomalyResult",
]
