# mypy: ignore-errors
"""Data types for Phase 3B — per-device temporal (TCN) anomaly detection."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np


class LoadClass(str, Enum):
    MOTOR_LOAD = "motor_load"
    LIGHTING_PANEL = "lighting_panel"
    UPS_LOAD = "ups_load"
    MIXED_LOAD = "mixed_load"
    UNKNOWN = "unknown"


class TemporalAlertCode(str, Enum):
    TEMPORAL_ANOMALY = "temporal:anomaly"
    TEMPORAL_PATTERN_BREAK = "temporal:pattern_break"
    TEMPORAL_LOAD_SHIFT = "temporal:load_shift"


@dataclass
class TemporalAlertInfo:
    alert_code: TemporalAlertCode
    parameter: str
    message: str
    anomaly_score: float
    expected_value: float
    actual_value: float
    timestamp: str
    device_id: str
    hour_of_day: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_code": self.alert_code.value,
            "parameter": self.parameter,
            "message": self.message,
            "anomaly_score": round(self.anomaly_score, 4),
            "expected_value": round(self.expected_value, 4),
            "actual_value": round(self.actual_value, 4),
            "timestamp": self.timestamp,
            "device_id": self.device_id,
            "hour_of_day": self.hour_of_day,
        }


@dataclass
class TemporalModelStatus:
    device_id: str
    model_status: str  # "accumulating" | "training" | "active" | "retraining"
    load_class: LoadClass
    samples_collected: int
    samples_needed: int
    model_version: int
    last_trained: str
    anomaly_threshold: float
    recent_scores: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "model_status": self.model_status,
            "load_class": self.load_class.value,
            "samples_collected": self.samples_collected,
            "samples_needed": self.samples_needed,
            "model_version": self.model_version,
            "last_trained": self.last_trained,
            "anomaly_threshold": round(self.anomaly_threshold, 6),
            "recent_scores": [round(s, 4) for s in self.recent_scores],
        }


@dataclass
class DeviceTemporalState:
    """Mutable per-device state held in memory by TemporalManager."""
    device_id: str
    model: Any = None  # NumpyTCN | None — avoid circular import
    load_class: LoadClass = LoadClass.UNKNOWN
    status: str = "accumulating"
    baseline_buffer: list = field(default_factory=list)  # list[np.ndarray]
    baseline_timestamps: list = field(default_factory=list)  # list[float]
    samples_needed: int = 4320  # 3 days @ 60s polling
    model_version: int = 0
    last_trained_ts: float = 0.0
    recent_scores: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=5)
    )
    active_alerts: dict = field(default_factory=dict)
    last_alert_times: dict = field(default_factory=dict)
