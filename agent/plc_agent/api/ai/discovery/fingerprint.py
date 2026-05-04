# mypy: ignore-errors
"""
KB fingerprint matching — identify a Modbus device by reading registers
and matching against all MFM Knowledge Base entries.

Scoring:
    ID register match    — 40% weight (if KB has identification block)
    Register existence   — 25% weight
    Value plausibility   — 25% weight
    Byte order           — 10% weight
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time as _time
from typing import Any

from .types import (
    ConfidenceLevel,
    IdentificationCandidate,
    IdentificationResult,
)

logger = logging.getLogger("loggerfast.ai.discovery.fingerprint")


async def identify_device_impl(
    ip: str,
    port: int = 502,
    unit_id: int = 1,
    timeout_ms: int = 1000,
) -> IdentificationResult:
    """Identify a device by fingerprinting against all KB models.

    Reads key registers, matches against every KBEntry, returns ranked
    candidates with confidence scores.
    """
    loop = asyncio.get_running_loop()

    def _identify():
        # Load all KB entries
        try:
            from ..mfm_kb.manager import KBManager
        except ImportError:
            return IdentificationResult(
                ip=ip, port=port, unit_id=unit_id,
                candidates=[], best_match=None, register_reads=0,
            )

        mgr = KBManager.instance()
        model_list = mgr.list_models()
        if not model_list:
            return IdentificationResult(
                ip=ip, port=port, unit_id=unit_id,
                candidates=[], best_match=None, register_reads=0,
            )

        # Connect once
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            return IdentificationResult(
                ip=ip, port=port, unit_id=unit_id,
                candidates=[], best_match=None, register_reads=0,
            )

        client = ModbusTcpClient(host=ip, port=port, timeout=timeout_ms / 1000.0)
        if not client.connect():
            return IdentificationResult(
                ip=ip, port=port, unit_id=unit_id,
                candidates=[], best_match=None, register_reads=0,
            )

        total_reads = 0
        candidates = []

        try:
            for m in model_list:
                entry = mgr.get_entry(m.model)
                if entry is None:
                    continue

                # Get registers as dicts
                regs = entry.registers if hasattr(entry, "registers") else []
                if hasattr(regs, "__iter__") and regs:
                    if hasattr(regs[0], "model_dump"):
                        reg_dicts = [r.model_dump() for r in regs]
                    elif hasattr(regs[0], "__dict__"):
                        reg_dicts = [r.__dict__ for r in regs]
                    else:
                        reg_dicts = list(regs)
                else:
                    reg_dicts = []

                if not reg_dicts:
                    continue

                # Get identification block
                ident = None
                if hasattr(entry, "identification") and entry.identification:
                    if hasattr(entry.identification, "model_dump"):
                        ident = entry.identification.model_dump()
                    elif hasattr(entry.identification, "__dict__"):
                        ident = entry.identification.__dict__
                    else:
                        ident = entry.identification

                manufacturer = getattr(entry, "manufacturer", "Unknown")
                model_name = getattr(entry, "model", m.model)

                # Score this model
                id_score, id_match, reads_id = _score_id_register(
                    client, ident, unit_id
                )
                total_reads += reads_id

                existence, reads_ex = _score_existence(
                    client, reg_dicts, unit_id
                )
                total_reads += reads_ex

                plausibility, byte_order_sc, detected_bo, reads_pl = _score_plausibility_and_byte_order(
                    client, reg_dicts, unit_id
                )
                total_reads += reads_pl

                # Composite score
                composite = _compute_composite(
                    id_score, existence, plausibility, byte_order_sc
                )

                # Confidence level
                if composite > 0.85:
                    confidence = ConfidenceLevel.HIGH
                elif composite > 0.60:
                    confidence = ConfidenceLevel.MEDIUM
                else:
                    confidence = ConfidenceLevel.LOW

                # Details string
                parts = []
                if id_match is True:
                    parts.append("ID register matched")
                elif id_match is False:
                    parts.append("ID register mismatch")
                parts.append(f"existence={existence:.0%}")
                parts.append(f"plausibility={plausibility:.0%}")
                parts.append(f"byte_order={detected_bo}")
                details = ", ".join(parts)

                if composite > 0.3:  # filter low-scoring noise
                    candidates.append(IdentificationCandidate(
                        model=model_name,
                        manufacturer=manufacturer,
                        score=composite,
                        confidence=confidence,
                        id_register_match=id_match,
                        existence_score=existence,
                        plausibility_score=plausibility,
                        byte_order_score=byte_order_sc,
                        detected_byte_order=detected_bo,
                        details=details,
                    ))
        finally:
            client.close()

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0] if candidates else None

        logger.info(
            "identify_complete ip=%s:%d uid=%d candidates=%d best=%s reads=%d",
            ip, port, unit_id, len(candidates),
            best.model if best else "none", total_reads,
        )

        return IdentificationResult(
            ip=ip, port=port, unit_id=unit_id,
            candidates=candidates, best_match=best,
            register_reads=total_reads,
        )

    return await loop.run_in_executor(None, _identify)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _read_regs(client, address: int, count: int, unit_id: int) -> list[int] | None:
    """Read holding registers. Returns list of uint16 or None on error."""
    try:
        rr = client.read_holding_registers(address=address, count=count, slave=unit_id)
        if rr and not rr.isError() and hasattr(rr, "registers"):
            return list(rr.registers)
    except Exception:
        pass
    return None


def _score_id_register(
    client, ident: dict | None, unit_id: int,
) -> tuple[float | None, bool | None, int]:
    """Check ID register against expected value.

    Returns (score, match_bool, reads_count).
    score: 1.0 if match, 0.0 if mismatch, None if no ID block.
    """
    if not ident or not ident.get("register_address"):
        return None, None, 0

    addr = int(ident["register_address"])
    expected = str(ident.get("expected_value", ""))
    count = max(1, len(expected) // 2 + 1)  # estimate register count for ASCII

    raw = _read_regs(client, addr, count, unit_id)
    if raw is None:
        return 0.0, False, 1

    # Try ASCII decode (pack uint16s to bytes) — exact match to avoid false positives
    import re as _re
    try:
        raw_bytes = b"".join(r.to_bytes(2, "big") for r in raw)
        ascii_val = raw_bytes.decode("ascii", errors="replace").strip("\x00 ")
        if _re.match(_re.escape(expected) + r"$", ascii_val, _re.IGNORECASE):
            return 1.0, True, 1
    except Exception:
        pass

    # Try hex comparison — exact match
    hex_val = "".join(f"{r:04X}" for r in raw)
    expected_hex = expected.replace("0x", "").replace("0X", "").upper()
    if expected_hex and hex_val.upper() == expected_hex:
        return 1.0, True, 1

    return 0.0, False, 1


def _score_existence(
    client, reg_dicts: list[dict], unit_id: int, sample_size: int = 10,
) -> tuple[float, int]:
    """Read a sample of registers, check how many return valid data.

    Returns (score 0-1, reads_count).
    """
    if not reg_dicts:
        return 0.0, 0

    # Sample: first 5 + last 5 (or all if < sample_size)
    if len(reg_dicts) <= sample_size:
        sample = reg_dicts
    else:
        half = sample_size // 2
        sample = reg_dicts[:half] + reg_dicts[-half:]

    valid = 0
    reads = 0
    for reg in sample:
        addr = reg.get("address", 0)
        count = reg.get("count", 1)
        raw = _read_regs(client, addr, count, unit_id)
        reads += 1
        if raw is not None and raw != [0xFFFF] * count:
            valid += 1

    score = valid / len(sample) if sample else 0.0
    return score, reads


def _score_plausibility_and_byte_order(
    client, reg_dicts: list[dict], unit_id: int, sample_size: int = 10,
) -> tuple[float, float, str, int]:
    """Decode register values and check against typical_range.

    Also compares big-endian vs little-endian plausibility.
    Returns (plausibility_score, byte_order_score, detected_byte_order, reads_count).
    """
    if not reg_dicts:
        return 0.0, 0.5, "big_endian", 0

    # Filter to registers with typical_range
    with_range = [r for r in reg_dicts if r.get("typical_range") and len(r.get("typical_range", [])) == 2]
    if not with_range:
        return 0.5, 0.5, "big_endian", 0  # can't assess without ranges

    # Sample
    if len(with_range) > sample_size:
        with_range = with_range[:sample_size]

    be_plausible = 0
    me_plausible = 0
    le_plausible = 0
    total_checked = 0
    reads = 0

    for reg in with_range:
        addr = reg.get("address", 0)
        count = reg.get("count", 1)
        data_type = reg.get("data_type", "float32")
        typical = reg.get("typical_range", [])

        raw = _read_regs(client, addr, count, unit_id)
        reads += 1
        if raw is None:
            continue

        lo, hi = float(typical[0]), float(typical[1])
        total_checked += 1

        # Try all 3 byte orders
        val_be = _decode_be(raw, data_type)
        val_me = _decode_mid_endian(raw, data_type)
        val_le = _decode_le(raw, data_type)

        if val_be is not None and lo <= val_be <= hi:
            be_plausible += 1
        if val_me is not None and lo <= val_me <= hi:
            me_plausible += 1
        if val_le is not None and lo <= val_le <= hi:
            le_plausible += 1

    if total_checked == 0:
        return 0.5, 0.5, "big_endian", reads

    plausibility = max(be_plausible, me_plausible, le_plausible) / total_checked

    # Byte order determination — pick the one with the most plausible values
    candidates = [
        (be_plausible, 1.0, "big_endian"),
        (me_plausible, 0.0, "mid_endian"),
        (le_plausible, 0.0, "little_endian"),
    ]
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_count, _, detected = candidates[0]

    # Score: 1.0 if clear winner, 0.5 if ambiguous
    if best_count > candidates[1][0]:
        byte_order_score = 1.0
    else:
        byte_order_score = 0.5
        detected = "big_endian"  # default on tie

    return plausibility, byte_order_score, detected, reads


def _compute_composite(
    id_score: float | None,
    existence: float,
    plausibility: float,
    byte_order: float,
) -> float:
    """Weighted composite score.

    Weights: ID 40%, existence 25%, plausibility 25%, byte_order 10%.
    If ID is None (no identification block), redistribute weight.
    """
    if id_score is not None:
        return (
            0.40 * id_score +
            0.25 * existence +
            0.25 * plausibility +
            0.10 * byte_order
        )
    else:
        # No ID register — redistribute 40% to other factors
        return (
            0.42 * existence +
            0.42 * plausibility +
            0.16 * byte_order
        )


# ---------------------------------------------------------------------------
# Register decoding (big-endian + little-endian)
# ---------------------------------------------------------------------------

def _decode_be(raw: list[int], data_type: str) -> float | None:
    """Decode raw uint16 registers as big-endian."""
    return _decode(raw, data_type, ">")


def _decode_mid_endian(raw: list[int], data_type: str) -> float | None:
    """Decode raw uint16 registers as mid-endian (word-swapped register order)."""
    if len(raw) >= 2:
        raw = list(reversed(raw))
    return _decode(raw, data_type, ">")  # struct still uses > but registers are swapped


def _decode_le(raw: list[int], data_type: str) -> float | None:
    """Decode raw uint16 registers as true little-endian (byte-swap within words)."""
    return _decode(raw, data_type, "<")


def _decode(raw: list[int], data_type: str, endian: str) -> float | None:
    """Decode raw uint16 registers to a value."""
    try:
        dt = data_type.lower()
        if dt in ("uint16", "uint16_enum", "bool16"):
            return float(raw[0]) if raw else None
        elif dt == "int16":
            return float(struct.unpack(f"{endian}h", struct.pack(f"{endian}H", raw[0]))[0]) if raw else None
        elif dt == "float32" and len(raw) >= 2:
            return float(struct.unpack(f"{endian}f", struct.pack(f"{endian}HH", raw[0], raw[1]))[0])
        elif dt == "uint32" and len(raw) >= 2:
            return float(struct.unpack(f"{endian}I", struct.pack(f"{endian}HH", raw[0], raw[1]))[0])
        elif dt == "int32" and len(raw) >= 2:
            return float(struct.unpack(f"{endian}i", struct.pack(f"{endian}HH", raw[0], raw[1]))[0])
        elif dt == "float64" and len(raw) >= 4:
            return float(struct.unpack(f"{endian}d", struct.pack(f"{endian}HHHH", *raw[:4]))[0])
        return float(raw[0]) if raw else None
    except Exception:
        return None
