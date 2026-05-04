# mypy: ignore-errors
"""
LoggerFast AI Discovery — network scanning + device identification.

Phase 2B: Hermes drives discovery via these tools to scan subnets,
enumerate Modbus unit IDs, and identify devices against the MFM KB.
"""
from .types import (
    ConfidenceLevel,
    DiscoveredHost,
    DiscoveryReport,
    IdentificationCandidate,
    IdentificationResult,
    PortResult,
    RespondingUnit,
)
from .scanner import scan_subnet_impl
from .enumerator import enumerate_unit_ids_impl
from .fingerprint import identify_device_impl

__all__ = [
    "ConfidenceLevel",
    "DiscoveredHost",
    "DiscoveryReport",
    "IdentificationCandidate",
    "IdentificationResult",
    "PortResult",
    "RespondingUnit",
    "scan_subnet_impl",
    "enumerate_unit_ids_impl",
    "identify_device_impl",
]
