# mypy: ignore-errors
"""
Parameter identification — maps raw field keys and unit annotations to
ParameterType + phase number.

Three-strategy priority chain:
    1. KB register metadata  (exact match on `parameter` field)
    2. Key pattern matching  (regex against field key name)
    3. Unit annotation       (from schema field metadata)
"""
from __future__ import annotations

import re
from typing import Any

from .types import ClassifiedParam, ParameterType


# ---------------------------------------------------------------------------
# Phase extraction helpers
# ---------------------------------------------------------------------------

def _extract_phase(m: re.Match) -> int | None:
    """Extract single phase number from first capture group."""
    try:
        return int(m.group(1))
    except (IndexError, TypeError, ValueError):
        return None


def _extract_phase_pair(m: re.Match) -> int | None:
    """Extract phase from line-to-line pattern (e.g. voltage_l12 → phase 1)."""
    try:
        return int(m.group(1))
    except (IndexError, TypeError, ValueError):
        return None


def _no_phase(_m: re.Match) -> int | None:
    return None


# ---------------------------------------------------------------------------
# Key pattern table (compiled regexes)
# ---------------------------------------------------------------------------

# Each entry: (pattern, ParameterType, phase_extractor)
_KEY_PATTERNS: list[tuple[re.Pattern, ParameterType, Any]] = [
    # Voltage line-to-neutral
    (re.compile(r"volt(?:age)?_l(\d)n", re.I), ParameterType.VOLTAGE_LN, _extract_phase),
    (re.compile(r"volt(?:age)?_ln(?:_avg)?$", re.I), ParameterType.VOLTAGE_LN, _no_phase),
    (re.compile(r"v_l(\d)n", re.I), ParameterType.VOLTAGE_LN, _extract_phase),
    (re.compile(r"v_ln$", re.I), ParameterType.VOLTAGE_LN, _no_phase),

    # Voltage line-to-line
    (re.compile(r"volt(?:age)?_l(\d)\d", re.I), ParameterType.VOLTAGE_LL, _extract_phase_pair),
    (re.compile(r"volt(?:age)?_ll(?:_avg)?$", re.I), ParameterType.VOLTAGE_LL, _no_phase),
    (re.compile(r"v_l(\d)\d$", re.I), ParameterType.VOLTAGE_LL, _extract_phase_pair),
    (re.compile(r"v_ll$", re.I), ParameterType.VOLTAGE_LL, _no_phase),

    # Current
    (re.compile(r"curr(?:ent)?_l(\d)", re.I), ParameterType.CURRENT, _extract_phase),
    (re.compile(r"^curr(?:ent)?(?:_avg)?$", re.I), ParameterType.CURRENT, _no_phase),
    (re.compile(r"i_l(\d)$", re.I), ParameterType.CURRENT, _extract_phase),

    # Power factor
    (re.compile(r"p(?:ower)?_?f(?:actor)?_l(\d)", re.I), ParameterType.POWER_FACTOR, _extract_phase),
    (re.compile(r"p(?:ower)?_?f(?:actor)?(?:_(?:avg|total))?$", re.I), ParameterType.POWER_FACTOR, _no_phase),
    (re.compile(r"^pf$", re.I), ParameterType.POWER_FACTOR, _no_phase),

    # Frequency
    (re.compile(r"freq(?:uency)?", re.I), ParameterType.FREQUENCY, _no_phase),

    # Reactive power (MUST be before generic "power" patterns)
    (re.compile(r"reactive_?power_l(\d)", re.I), ParameterType.REACTIVE_POWER, _extract_phase),
    (re.compile(r"reactive_?power(?:_(?:total|avg))?$", re.I), ParameterType.REACTIVE_POWER, _no_phase),
    (re.compile(r"^kvar(?:_total)?$", re.I), ParameterType.REACTIVE_POWER, _no_phase),

    # Apparent power (MUST be before generic "power" patterns)
    (re.compile(r"apparent_?power_l(\d)", re.I), ParameterType.APPARENT_POWER, _extract_phase),
    (re.compile(r"apparent_?power(?:_(?:total|avg))?$", re.I), ParameterType.APPARENT_POWER, _no_phase),
    (re.compile(r"^kva(?:_total)?$", re.I), ParameterType.APPARENT_POWER, _no_phase),

    # Active power (generic "power" patterns last — specific types matched above)
    (re.compile(r"active_?power_l(\d)", re.I), ParameterType.ACTIVE_POWER, _extract_phase),
    (re.compile(r"active_?power(?:_(?:total|avg))?$", re.I), ParameterType.ACTIVE_POWER, _no_phase),
    (re.compile(r"^(?:real_?)?power_l(\d)$", re.I), ParameterType.ACTIVE_POWER, _extract_phase),
    (re.compile(r"^(?:real_?)?power(?:_total)?$", re.I), ParameterType.ACTIVE_POWER, _no_phase),
    (re.compile(r"^kw(?:_total)?$", re.I), ParameterType.ACTIVE_POWER, _no_phase),

    # Energy active
    (re.compile(r"energy_?active", re.I), ParameterType.ENERGY_ACTIVE, _no_phase),
    (re.compile(r"^kwh(?:_total)?$", re.I), ParameterType.ENERGY_ACTIVE, _no_phase),
    (re.compile(r"^wh_total$", re.I), ParameterType.ENERGY_ACTIVE, _no_phase),

    # Energy reactive
    (re.compile(r"energy_?reactive", re.I), ParameterType.ENERGY_REACTIVE, _no_phase),
    (re.compile(r"^kvarh(?:_total)?$", re.I), ParameterType.ENERGY_REACTIVE, _no_phase),
]


# ---------------------------------------------------------------------------
# Unit-based fallback
# ---------------------------------------------------------------------------

_UNIT_MAP: dict[str, ParameterType] = {
    "A": ParameterType.CURRENT,
    "Hz": ParameterType.FREQUENCY,
    "W": ParameterType.ACTIVE_POWER,
    "kW": ParameterType.ACTIVE_POWER,
    "MW": ParameterType.ACTIVE_POWER,
    "VAR": ParameterType.REACTIVE_POWER,
    "kVAR": ParameterType.REACTIVE_POWER,
    "VA": ParameterType.APPARENT_POWER,
    "kVA": ParameterType.APPARENT_POWER,
    "Wh": ParameterType.ENERGY_ACTIVE,
    "kWh": ParameterType.ENERGY_ACTIVE,
    "VARh": ParameterType.ENERGY_REACTIVE,
    "kVARh": ParameterType.ENERGY_REACTIVE,
}


def _classify_voltage_by_value(value: float) -> ParameterType:
    """When unit is 'V' and key pattern is ambiguous, use the value."""
    if 150 <= value <= 300:
        return ParameterType.VOLTAGE_LN
    if 300 < value <= 500:
        return ParameterType.VOLTAGE_LL
    # Outside common ranges — default to LN
    return ParameterType.VOLTAGE_LN


# ---------------------------------------------------------------------------
# KB register metadata lookup
# ---------------------------------------------------------------------------

# Mapping from KB `parameter` field to ParameterType
_KB_PARAM_MAP: dict[str, ParameterType] = {
    "voltage_l1n": ParameterType.VOLTAGE_LN,
    "voltage_l2n": ParameterType.VOLTAGE_LN,
    "voltage_l3n": ParameterType.VOLTAGE_LN,
    "voltage_ln_avg": ParameterType.VOLTAGE_LN,
    "voltage_l12": ParameterType.VOLTAGE_LL,
    "voltage_l23": ParameterType.VOLTAGE_LL,
    "voltage_l31": ParameterType.VOLTAGE_LL,
    "voltage_ll_avg": ParameterType.VOLTAGE_LL,
    "current_l1": ParameterType.CURRENT,
    "current_l2": ParameterType.CURRENT,
    "current_l3": ParameterType.CURRENT,
    "current_avg": ParameterType.CURRENT,
    "power_factor": ParameterType.POWER_FACTOR,
    "power_factor_l1": ParameterType.POWER_FACTOR,
    "power_factor_l2": ParameterType.POWER_FACTOR,
    "power_factor_l3": ParameterType.POWER_FACTOR,
    "frequency": ParameterType.FREQUENCY,
    "active_power": ParameterType.ACTIVE_POWER,
    "active_power_l1": ParameterType.ACTIVE_POWER,
    "active_power_l2": ParameterType.ACTIVE_POWER,
    "active_power_l3": ParameterType.ACTIVE_POWER,
    "reactive_power": ParameterType.REACTIVE_POWER,
    "reactive_power_l1": ParameterType.REACTIVE_POWER,
    "reactive_power_l2": ParameterType.REACTIVE_POWER,
    "reactive_power_l3": ParameterType.REACTIVE_POWER,
    "apparent_power": ParameterType.APPARENT_POWER,
    "apparent_power_l1": ParameterType.APPARENT_POWER,
    "apparent_power_l2": ParameterType.APPARENT_POWER,
    "apparent_power_l3": ParameterType.APPARENT_POWER,
    "energy_active": ParameterType.ENERGY_ACTIVE,
    "energy_reactive": ParameterType.ENERGY_REACTIVE,
}


def _phase_from_key(key: str) -> int | None:
    """Try to extract phase number from end of key."""
    m = re.search(r"_l(\d)$", key, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"_l(\d)\d$", key, re.I)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Main classification function
# ---------------------------------------------------------------------------

def classify_readings(
    readings: dict[str, float],
    *,
    schema_fields: list[dict[str, Any]] | None = None,
    kb_registers: list[dict[str, Any]] | None = None,
) -> list[ClassifiedParam]:
    """Classify each reading into a ParameterType with phase info.

    Args:
        readings: field_key → value
        schema_fields: Optional schema field metadata [{key, type, unit, ...}]
        kb_registers: Optional KB register metadata [{parameter, unit, ...}]

    Returns:
        List of ClassifiedParam, one per reading.
    """
    # Build lookup tables
    unit_by_key: dict[str, str] = {}
    if schema_fields:
        for f in schema_fields:
            k = f.get("key", "")
            u = f.get("unit", "")
            if k and u:
                unit_by_key[k] = u

    kb_by_key: dict[str, dict] = {}
    if kb_registers:
        for reg in kb_registers:
            param_name = reg.get("parameter", "")
            if param_name:
                kb_by_key[param_name] = reg

    result: list[ClassifiedParam] = []

    for key, value in readings.items():
        param_type = ParameterType.UNKNOWN
        phase: int | None = None
        unit = unit_by_key.get(key, "")

        # Strategy 1: KB register metadata
        if key in kb_by_key:
            kb_type = _KB_PARAM_MAP.get(key)
            if kb_type:
                param_type = kb_type
                phase = _phase_from_key(key)
                if not unit:
                    unit = kb_by_key[key].get("unit", "")

        # Strategy 2: Key pattern matching
        if param_type == ParameterType.UNKNOWN:
            for pattern, ptype, phase_fn in _KEY_PATTERNS:
                m = pattern.search(key)
                if m:
                    param_type = ptype
                    phase = phase_fn(m)
                    break

        # Strategy 3: Unit annotation fallback
        if param_type == ParameterType.UNKNOWN and unit:
            mapped = _UNIT_MAP.get(unit)
            if mapped:
                param_type = mapped
                phase = _phase_from_key(key)
            elif unit == "V":
                param_type = _classify_voltage_by_value(value)
                phase = _phase_from_key(key)

        # If still unknown, try inferring unit from key for self-describing names
        if param_type == ParameterType.UNKNOWN and not unit:
            phase = _phase_from_key(key)

        result.append(ClassifiedParam(
            key=key,
            param_type=param_type,
            phase=phase,
            value=value,
            unit=unit,
        ))

    return result
