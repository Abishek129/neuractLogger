# mypy: ignore-errors
"""
Discovery data types — pure data classes for network discovery results.
No logic, no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConfidenceLevel(str, Enum):
    HIGH = "high"       # >0.85
    MEDIUM = "medium"   # 0.60-0.85
    LOW = "low"         # <0.60


@dataclass(frozen=True)
class PortResult:
    port: int
    open: bool
    latency_ms: int = 0


@dataclass
class DiscoveredHost:
    ip: str
    alive: bool
    ports: list[PortResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "alive": self.alive,
            "ports": [{"port": p.port, "open": p.open, "latency_ms": p.latency_ms}
                      for p in self.ports],
        }


@dataclass(frozen=True)
class RespondingUnit:
    unit_id: int
    raw_values: list[int]
    latency_ms: int


@dataclass
class IdentificationCandidate:
    model: str
    manufacturer: str
    score: float                        # 0.0-1.0 composite
    confidence: ConfidenceLevel
    id_register_match: bool | None      # None if KB has no ID block
    existence_score: float
    plausibility_score: float
    byte_order_score: float
    detected_byte_order: str            # "big_endian" or "mid_endian"
    details: str                        # human-readable explanation

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "manufacturer": self.manufacturer,
            "score": round(self.score, 3),
            "confidence": self.confidence.value,
            "id_register_match": self.id_register_match,
            "existence_score": round(self.existence_score, 3),
            "plausibility_score": round(self.plausibility_score, 3),
            "byte_order_score": round(self.byte_order_score, 3),
            "detected_byte_order": self.detected_byte_order,
            "details": self.details,
        }


@dataclass
class IdentificationResult:
    ip: str
    port: int
    unit_id: int
    candidates: list[IdentificationCandidate]
    best_match: IdentificationCandidate | None
    register_reads: int

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "port": self.port,
            "unit_id": self.unit_id,
            "candidates": [c.to_dict() for c in self.candidates],
            "best_match": self.best_match.to_dict() if self.best_match else None,
            "register_reads": self.register_reads,
        }


@dataclass
class DiscoveryReport:
    subnet: str
    hosts_scanned: int
    hosts_alive: int
    devices_found: int
    devices_identified: int
    hosts: list[DiscoveredHost] = field(default_factory=list)
    identifications: list[IdentificationResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subnet": self.subnet,
            "hosts_scanned": self.hosts_scanned,
            "hosts_alive": self.hosts_alive,
            "devices_found": self.devices_found,
            "devices_identified": self.devices_identified,
            "hosts": [h.to_dict() for h in self.hosts],
            "identifications": [i.to_dict() for i in self.identifications],
        }
