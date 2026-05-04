# mypy: ignore-errors
"""
Rule-based load pattern classification from PF profile + load curve.

Classes:
    MOTOR_LOAD — PF 0.65-0.85, variable current, PF drops under load
    LIGHTING_PANEL — PF >0.90, bimodal on/off, schedule-driven
    UPS_LOAD — PF >0.95, very flat load, minimal diurnal variation
    MIXED_LOAD — no dominant pattern
    UNKNOWN — insufficient data
"""
from __future__ import annotations

import math
from typing import Any

from .temporal_types import LoadClass


MIN_SAMPLES = 1440  # 1 day at 60s polling


def classify_load(
    pf_values: list[float],
    current_values: list[float],
    active_power_values: list[float],
    timestamps: list[float],
) -> tuple[LoadClass, dict[str, Any]]:
    """Classify device load type from baseline data.

    Returns (load_class, evidence_dict) where evidence_dict contains
    the computed features for debugging/logging.
    """
    n = len(pf_values)
    if n < MIN_SAMPLES:
        return LoadClass.UNKNOWN, {"reason": "insufficient_data", "samples": n}

    # Feature extraction
    pf_mean = _mean(pf_values)
    pf_std = _std(pf_values)
    current_mean = _mean(current_values)
    current_std = _std(current_values)
    current_cv = current_std / current_mean if current_mean > 1e-6 else 0.0

    # Diurnal ratio: average load during day (6-18h) vs night (18-6h)
    diurnal_ratio = _compute_diurnal_ratio(current_values, timestamps)

    # PF-power correlation
    pf_power_corr = _pearson(pf_values, active_power_values)

    evidence = {
        "pf_mean": round(pf_mean, 4),
        "pf_std": round(pf_std, 4),
        "current_cv": round(current_cv, 4),
        "diurnal_ratio": round(diurnal_ratio, 4),
        "pf_power_correlation": round(pf_power_corr, 4),
        "samples": n,
    }

    # Classification rules
    # UPS: very stable, high PF
    if pf_mean > 0.95 and current_cv < 0.05 and diurnal_ratio < 1.1:
        return LoadClass.UPS_LOAD, evidence

    # Motor: moderate PF, variable load, PF negatively correlated with power
    if 0.55 <= pf_mean <= 0.88 and current_cv > 0.15 and pf_power_corr < -0.1:
        return LoadClass.MOTOR_LOAD, evidence

    # Lighting: high PF, strong diurnal pattern (schedule-driven)
    if pf_mean > 0.90 and diurnal_ratio > 2.0:
        return LoadClass.LIGHTING_PANEL, evidence

    # Motor (relaxed): just based on PF range and variability
    if 0.55 <= pf_mean <= 0.88 and current_cv > 0.10:
        return LoadClass.MOTOR_LOAD, evidence

    # Lighting (relaxed): high PF with some diurnal
    if pf_mean > 0.88 and diurnal_ratio > 1.5:
        return LoadClass.LIGHTING_PANEL, evidence

    return LoadClass.MIXED_LOAD, evidence


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 on degenerate inputs."""
    n = min(len(x), len(y))
    if n < 10:
        return 0.0
    mx = sum(x[:n]) / n
    my = sum(y[:n]) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = math.sqrt(sum((x[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((y[i] - my) ** 2 for i in range(n)))
    if dx < 1e-10 or dy < 1e-10:
        return 0.0
    return num / (dx * dy)


def _compute_diurnal_ratio(
    current_values: list[float], timestamps: list[float],
    timezone_offset_hours: float = 0.0,
) -> float:
    """Ratio of average daytime (6-18h local) to nighttime load.

    Args:
        timezone_offset_hours: Offset from UTC for local time (e.g. 5.5 for IST).
    """
    from datetime import datetime, timezone as tz, timedelta

    local_tz = tz(timedelta(hours=timezone_offset_hours))
    day_vals = []
    night_vals = []
    for val, ts in zip(current_values, timestamps):
        try:
            dt = datetime.fromtimestamp(ts, tz=local_tz)
            if 6 <= dt.hour < 18:
                day_vals.append(val)
            else:
                night_vals.append(val)
        except (OSError, ValueError):
            continue

    day_avg = _mean(day_vals) if day_vals else 0.0
    night_avg = _mean(night_vals) if night_vals else 0.0

    if night_avg < 1e-6:
        return 1.0 if day_avg < 1e-6 else 10.0
    return day_avg / night_avg
