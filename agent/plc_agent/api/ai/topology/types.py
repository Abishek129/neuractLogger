# mypy: ignore-errors
"""Data types for SLD topology inference."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HierarchyLevel(str, Enum):
    INCOMER = "incomer"
    FEEDER = "feeder"
    SUB_FEEDER = "sub_feeder"
    LOAD = "load"
    UNKNOWN = "unknown"


class LoadPattern(str, Enum):
    MOTOR = "motor"             # PF 0.7-0.85, inrush spikes
    LIGHTING = "lighting"       # PF ~0.95+, stable, drops at night
    UPS = "ups"                 # constant base, brief spikes
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class DeviceNode:
    """Single device in the topology graph."""
    device_id: str
    device_name: str
    gateway_id: str
    active_power: float         # watts
    apparent_power: float       # VA
    power_factor: float
    level: HierarchyLevel = HierarchyLevel.UNKNOWN
    parent_id: Optional[str] = None
    children_ids: list[str] = field(default_factory=list)
    load_pattern: LoadPattern = LoadPattern.UNKNOWN
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "gateway_id": self.gateway_id,
            "active_power": round(self.active_power, 1),
            "apparent_power": round(self.apparent_power, 1),
            "power_factor": round(self.power_factor, 3),
            "level": self.level.value,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "load_pattern": self.load_pattern.value,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TopologyGraph:
    """Inferred topology for a gateway."""
    gateway_id: str
    nodes: dict[str, DeviceNode] = field(default_factory=dict)
    inferred_at: str = ""
    snapshot_count: int = 0
    power_balance_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "inferred_at": self.inferred_at,
            "snapshot_count": self.snapshot_count,
            "power_balance_score": round(self.power_balance_score, 3),
        }


