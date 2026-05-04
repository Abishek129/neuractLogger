# mypy: ignore-errors
"""Pure statistical functions for Layer 3 prediction.

No project imports — independently testable.
"""
from __future__ import annotations

import math
from typing import Tuple


def z_score(values: list[float], current: float) -> float:
    """Calculate z-score of *current* against the rolling window.

    Returns 0.0 if window has < 2 values (insufficient data).
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)  # sample variance
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std < 1e-10:
        # All values nearly identical — use absolute deviation from mean.
        # If the mean is also near-zero, fall back to raw difference.
        ref = abs(mean) if abs(mean) > 1e-10 else 1.0
        deviation = abs(current - mean) / ref
        # Return a synthetic z-score proportional to % deviation (1% → 1σ)
        return math.copysign(deviation * 100, current - mean) if deviation > 1e-6 else 0.0
    return (current - mean) / std


def holt_winters_update(
    level: float,
    trend: float,
    new_value: float,
    alpha: float = 0.3,
    beta: float = 0.1,
    initialized: bool = True,
) -> Tuple[float, float]:
    """Double exponential smoothing (Holt's linear method, no seasonality).

    Returns ``(new_level, new_trend)``.
    If not yet initialised, seeds level = new_value, trend = 0.
    """
    if not initialized:
        return new_value, 0.0
    new_level = alpha * new_value + (1 - alpha) * (level + trend)
    new_trend = beta * (new_level - level) + (1 - beta) * trend
    return new_level, new_trend


def holt_winters_forecast(level: float, trend: float, steps: int = 1) -> float:
    """Forecast future value: ``level + trend * steps``."""
    return level + trend * steps


def linear_regression_slope(
    timestamps: list[float],
    values: list[float],
) -> Tuple[float, float]:
    """Simple OLS linear regression.

    *timestamps* are in seconds (e.g. ``time.time()``).
    Returns ``(slope_per_second, r_squared)``.
    Returns ``(0.0, 0.0)`` if fewer than 3 points.
    """
    n = len(values)
    if n < 3 or len(timestamps) != n:
        return 0.0, 0.0
    # Normalise timestamps to start at 0 for numerical stability
    t0 = timestamps[0]
    ts = [t - t0 for t in timestamps]
    sum_t = sum(ts)
    sum_v = sum(values)
    sum_tv = sum(t * v for t, v in zip(ts, values))
    sum_t2 = sum(t * t for t in ts)
    denom = n * sum_t2 - sum_t * sum_t
    if abs(denom) < 1e-10:
        return 0.0, 0.0
    slope = (n * sum_tv - sum_t * sum_v) / denom
    intercept = (sum_v - slope * sum_t) / n
    # R-squared
    mean_v = sum_v / n
    ss_tot = sum((v - mean_v) ** 2 for v in values)
    ss_res = sum((v - (intercept + slope * t)) ** 2 for t, v in zip(ts, values))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0
    return slope, max(0.0, min(1.0, r_squared))


def slope_per_hour(slope_per_second: float) -> float:
    """Convert slope from per-second to per-hour."""
    return slope_per_second * 3600.0


def classify_direction(slope_pct_hr: float, threshold: float = 0.01) -> str:
    """Classify trend direction based on slope magnitude (% / hr)."""
    if abs(slope_pct_hr) < threshold:
        return "stable"
    return "up" if slope_pct_hr > 0 else "down"
