# mypy: ignore-errors
"""
Anomaly detection result types — Layer 2 validation.

Pure data — no logic dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Anomaly score thresholds (from spec)
# ---------------------------------------------------------------------------

THRESHOLD_NORMAL = 0.2      # score < 0.2 → normal
THRESHOLD_MODERATE = 0.5    # 0.2 ≤ score < 0.5 → moderate (investigate)
                            # score ≥ 0.5 → high (flag to engineer)


def _severity_from_score(score: float) -> str:
    if score < THRESHOLD_NORMAL:
        return "normal"
    if score < THRESHOLD_MODERATE:
        return "moderate"
    return "high"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    """Result of Layer 2 anomaly detection on a set of readings."""

    score: float                        # 0.0–1.0 (calibrated)
    severity: str                       # "normal" | "moderate" | "high"
    contributions: dict[str, float]     # param_name → contribution fraction
    top_contributors: list[str]         # top 5 driving parameters
    model_family: str                   # KB model used
    interpretation: str                 # human-readable explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_score": round(self.score, 4),
            "severity": self.severity,
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "top_contributors": self.top_contributors,
            "model_family": self.model_family,
            "interpretation": self.interpretation,
        }
