# mypy: ignore-errors
"""Data types for Layer 3 predictive runtime monitoring."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BaselineStatus(str, Enum):
    LEARNING = "learning"       # Window not yet full
    ACTIVE = "active"           # Monitoring, no alerts
    ALERTING = "alerting"       # Active alerts present


class AlertCode(str, Enum):
    BASELINE_DRIFT = "prediction:baseline_drift"
    TREND_ALERT = "prediction:trend_alert"
    DEVIATION = "prediction:deviation"
    TEMPORAL_ANOMALY = "prediction:temporal_anomaly"
    TEMPORAL_PATTERN_BREAK = "prediction:temporal_pattern_break"


@dataclass
class TrendInfo:
    """Per-parameter trend data."""
    parameter: str
    slope_per_hour: float       # %/hr relative to mean
    direction: str              # "up" | "down" | "stable"
    r_squared: float            # goodness of fit 0-1
    window_size: int
    hw_level: float             # Holt-Winters smoothed level
    hw_trend: float             # Holt-Winters trend component

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "slope_per_hour": round(self.slope_per_hour, 4),
            "direction": self.direction,
            "r_squared": round(self.r_squared, 4),
            "window_size": self.window_size,
            "hw_level": round(self.hw_level, 4),
            "hw_trend": round(self.hw_trend, 4),
        }


@dataclass
class AlertInfo:
    """Active alert details."""
    alert_code: AlertCode
    parameter: str
    message: str
    sigma: float                # current z-score deviation
    timestamp: str
    device_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_code": self.alert_code.value,
            "parameter": self.parameter,
            "message": self.message,
            "sigma": round(self.sigma, 2),
            "timestamp": self.timestamp,
            "device_id": self.device_id,
        }


@dataclass
class PredictionStatus:
    """Output type for read_prediction_status tool."""
    device_id: str
    baseline_status: BaselineStatus
    monitoring_since: str
    window_fill_pct: float      # 0-100
    current_deviations: dict[str, float]    # param -> z-score
    active_alerts: list[AlertInfo]
    trends: list[TrendInfo]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "baseline_status": self.baseline_status.value,
            "monitoring_since": self.monitoring_since,
            "window_fill_pct": round(self.window_fill_pct, 1),
            "current_deviations": {
                k: round(v, 3) for k, v in self.current_deviations.items()
            },
            "active_alerts": [a.to_dict() for a in self.active_alerts],
            "trends": [t.to_dict() for t in self.trends],
            "config": self.config,
        }


@dataclass
class ParameterState:
    """Per-parameter rolling state. Designed for minimal memory."""
    values: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    hw_level: float = 0.0
    hw_trend: float = 0.0
    hw_initialized: bool = False


@dataclass
class DeviceBaseline:
    """Per-device monitoring state."""
    device_id: str
    table_ids: list[str] = field(default_factory=list)
    params: dict[str, ParameterState] = field(default_factory=dict)
    monitoring_since: str = ""
    active_alerts: dict[str, AlertInfo] = field(default_factory=dict)
    last_alert_times: dict[str, float] = field(default_factory=dict)
