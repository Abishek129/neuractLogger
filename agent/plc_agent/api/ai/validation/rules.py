# mypy: ignore-errors
"""
Validation rules — static thresholds and cross-parameter consistency checks.

Layer 1: deterministic, instant, zero training.

Physical range thresholds are Indian industrial 3-phase defaults from
the AI_Integration spec. Cross-parameter checks verify that readings
are self-consistent (power triangle, voltage ratios, phase balance).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from .types import CheckResult, ClassifiedParam, ParameterType, Severity


# ---------------------------------------------------------------------------
# Threshold specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThresholdSpec:
    """Physical range for a parameter type."""
    param_type: ParameterType
    expected_min: float
    expected_max: float
    red_flag_min: float     # Below this → FAIL
    red_flag_max: float     # Above this → FAIL
    unit: str


THRESHOLDS: dict[ParameterType, ThresholdSpec] = {
    ParameterType.VOLTAGE_LL: ThresholdSpec(
        ParameterType.VOLTAGE_LL, 380, 440, 50, 600, "V",
    ),
    ParameterType.VOLTAGE_LN: ThresholdSpec(
        ParameterType.VOLTAGE_LN, 220, 254, 30, 350, "V",
    ),
    ParameterType.CURRENT: ThresholdSpec(
        ParameterType.CURRENT, 0, float("inf"), -0.001, float("inf"), "A",
    ),
    ParameterType.POWER_FACTOR: ThresholdSpec(
        ParameterType.POWER_FACTOR, -1.0, 1.0, -1.001, 1.001, "",
    ),
    ParameterType.FREQUENCY: ThresholdSpec(
        ParameterType.FREQUENCY, 49.5, 50.5, 45, 55, "Hz",
    ),
    ParameterType.ACTIVE_POWER: ThresholdSpec(
        ParameterType.ACTIVE_POWER, 0, float("inf"), -0.001, float("inf"), "kW",
    ),
    ParameterType.APPARENT_POWER: ThresholdSpec(
        ParameterType.APPARENT_POWER, 0, float("inf"), -0.001, float("inf"), "kVA",
    ),
    # Reactive power: allow any magnitude but flag negative on non-bidirectional meters
    ParameterType.REACTIVE_POWER: ThresholdSpec(
        ParameterType.REACTIVE_POWER, 0, float("inf"), -0.001, float("inf"), "kVAR",
    ),
}


# ---------------------------------------------------------------------------
# Range check
# ---------------------------------------------------------------------------

def check_range(
    param: ClassifiedParam,
    ct_rating: float | None = None,
) -> CheckResult | None:
    """Check a single parameter against its physical range thresholds.

    Returns None for parameter types with no threshold (e.g. UNKNOWN, ENERGY,
    REACTIVE_POWER).
    """
    import math

    # Guard: non-finite values (NaN/Inf) are immediate FAIL — encoding error
    if not math.isfinite(param.value):
        return CheckResult(
            check_id=f"range.{param.key}",
            severity=Severity.FAIL,
            message=f"{param.key}: value is {param.value} (non-finite — likely encoding error or device fault)",
            expected="finite number",
            actual=str(param.value),
            field_keys=(param.key,),
        )

    spec = THRESHOLDS.get(param.param_type)
    if spec is None:
        return None

    value = param.value

    # Dynamic bounds for current when CT rating is known
    red_max = spec.red_flag_max
    exp_max = spec.expected_max
    if param.param_type == ParameterType.CURRENT and ct_rating is not None:
        exp_max = ct_rating
        red_max = ct_rating * 10

    unit = spec.unit or param.unit
    expected_str = f"{spec.expected_min}-{exp_max}{unit}" if exp_max != float("inf") else f">={spec.expected_min}{unit}"

    # Determine severity
    if value < spec.red_flag_min or value > red_max:
        severity = Severity.FAIL
        if value < spec.red_flag_min:
            message = f"{param.key}: {value}{unit} is below red-flag threshold ({spec.red_flag_min}{unit})"
        else:
            message = f"{param.key}: {value}{unit} exceeds red-flag threshold ({red_max}{unit})"
    elif value < spec.expected_min or value > exp_max:
        severity = Severity.WARNING
        message = f"{param.key}: {value}{unit} is outside expected range ({expected_str})"
    else:
        severity = Severity.PASS
        message = f"{param.key}: {value}{unit} OK"

    return CheckResult(
        check_id=f"range.{param.key}",
        severity=severity,
        message=message,
        expected=expected_str,
        actual=f"{value}{unit}",
        field_keys=(param.key,),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_by_type(
    params: list[ClassifiedParam],
) -> dict[ParameterType, list[ClassifiedParam]]:
    """Group classified parameters by their type."""
    groups: dict[ParameterType, list[ClassifiedParam]] = {}
    for p in params:
        groups.setdefault(p.param_type, []).append(p)
    return groups


def _avg(params: list[ClassifiedParam]) -> float:
    """Average value of a list of classified params."""
    return sum(p.value for p in params) / len(params)


def _severity_from_deviation(deviation: float, tolerance: float) -> Severity:
    """Map a relative deviation to severity based on tolerance.

    PASS:    deviation <= tolerance
    WARNING: tolerance < deviation <= tolerance * 2
    FAIL:    deviation > tolerance * 2
    """
    if deviation <= tolerance:
        return Severity.PASS
    if deviation <= tolerance * 2:
        return Severity.WARNING
    return Severity.FAIL


# ---------------------------------------------------------------------------
# Cross-parameter checks
# ---------------------------------------------------------------------------

def cross_check_vln_vll(
    params: list[ClassifiedParam],
    tolerance: float = 0.05,
) -> CheckResult | None:
    """V_LN * sqrt(3) ~ V_LL within tolerance (default 5%)."""
    groups = _group_by_type(params)
    vln_list = groups.get(ParameterType.VOLTAGE_LN, [])
    vll_list = groups.get(ParameterType.VOLTAGE_LL, [])

    if not vln_list or not vll_list:
        return None

    vln_avg = _avg(vln_list)
    vll_avg = _avg(vll_list)

    if vll_avg == 0:
        return None

    expected_vll = vln_avg * math.sqrt(3)
    deviation = abs(expected_vll - vll_avg) / vll_avg

    severity = _severity_from_deviation(deviation, tolerance)
    keys = tuple(p.key for p in vln_list + vll_list)

    return CheckResult(
        check_id="cross.vln_vll",
        severity=severity,
        message=(
            f"V_LN*sqrt(3)={expected_vll:.1f}V vs V_LL={vll_avg:.1f}V "
            f"(deviation {deviation*100:.1f}%)"
        ),
        expected=f"V_LN*sqrt(3) ~ V_LL within {tolerance*100:.0f}%",
        actual=f"deviation={deviation*100:.1f}%",
        field_keys=keys,
    )


def cross_check_power_triangle(
    params: list[ClassifiedParam],
    tolerance: float = 0.05,
) -> CheckResult | None:
    """S^2 ~ P^2 + Q^2 within tolerance (default 5%)."""
    groups = _group_by_type(params)
    s_list = groups.get(ParameterType.APPARENT_POWER, [])
    p_list = groups.get(ParameterType.ACTIVE_POWER, [])
    q_list = groups.get(ParameterType.REACTIVE_POWER, [])

    if not s_list or not p_list or not q_list:
        return None

    s = _avg(s_list)
    p = _avg(p_list)
    q = _avg(q_list)

    if s == 0:
        return None

    s_sq = s ** 2
    pq_sq = p ** 2 + q ** 2
    deviation = abs(s_sq - pq_sq) / s_sq

    severity = _severity_from_deviation(deviation, tolerance)
    keys = tuple(x.key for x in s_list + p_list + q_list)

    return CheckResult(
        check_id="cross.power_triangle",
        severity=severity,
        message=(
            f"S^2={s_sq:.1f} vs P^2+Q^2={pq_sq:.1f} "
            f"(deviation {deviation*100:.1f}%)"
        ),
        expected=f"S^2 ~ P^2+Q^2 within {tolerance*100:.0f}%",
        actual=f"deviation={deviation*100:.1f}%",
        field_keys=keys,
    )


def cross_check_power_calculation(
    params: list[ClassifiedParam],
    tolerance: float = 0.10,
) -> CheckResult | None:
    """P ~ V * I * PF * sqrt(3) within tolerance (default 10%)."""
    groups = _group_by_type(params)
    p_list = groups.get(ParameterType.ACTIVE_POWER, [])
    pf_list = groups.get(ParameterType.POWER_FACTOR, [])
    i_list = groups.get(ParameterType.CURRENT, [])

    # Need voltage — prefer L-L, fall back to L-N
    v_list = groups.get(ParameterType.VOLTAGE_LL, []) or groups.get(ParameterType.VOLTAGE_LN, [])

    if not p_list or not v_list or not i_list or not pf_list:
        return None

    p_actual = _avg(p_list)
    v = _avg(v_list)
    i = _avg(i_list)
    pf = _avg(pf_list)

    # Determine if voltage is L-L or L-N
    is_ll = bool(groups.get(ParameterType.VOLTAGE_LL))

    if is_ll:
        p_calc = v * i * abs(pf) * math.sqrt(3)
    else:
        # V_LN based: P = 3 * V_LN * I * PF
        p_calc = 3 * v * i * abs(pf)

    if p_calc == 0:
        return None

    # Auto-scale: if one value is in W and the other in kW (>100x mismatch),
    # try the kW conversion before computing deviation
    ratio = p_calc / p_actual if p_actual != 0 else float("inf")
    if ratio > 100:
        p_calc /= 1000  # calc was in W, actual is in kW
    elif ratio < 0.01:
        p_calc *= 1000  # calc was in kW, actual is in W

    deviation = abs(p_actual - p_calc) / p_calc if p_calc != 0 else float("inf")

    severity = _severity_from_deviation(deviation, tolerance)
    keys = tuple(x.key for x in p_list + v_list + i_list + pf_list)

    return CheckResult(
        check_id="cross.power_calculation",
        severity=severity,
        message=(
            f"P_actual={p_actual:.2f} vs P_calc={p_calc:.2f} "
            f"(deviation {deviation*100:.1f}%)"
        ),
        expected=f"P ~ V*I*PF*sqrt(3) within {tolerance*100:.0f}%",
        actual=f"deviation={deviation*100:.1f}%",
        field_keys=keys,
    )


def cross_check_phase_balance(
    params: list[ClassifiedParam],
    tolerance: float = 0.10,
) -> CheckResult | None:
    """All phase voltages within tolerance of each other (unbalance < 10%)."""
    groups = _group_by_type(params)

    # Prefer L-N phases, fall back to L-L
    v_list = groups.get(ParameterType.VOLTAGE_LN, []) or groups.get(ParameterType.VOLTAGE_LL, [])

    # Need at least 2 different phases
    phased = [p for p in v_list if p.phase is not None]
    phases_seen = {p.phase for p in phased}
    if len(phases_seen) < 2:
        return None

    values = [p.value for p in phased]
    mean = sum(values) / len(values)
    if mean == 0:
        return None

    max_dev = max(abs(v - mean) for v in values)
    deviation = max_dev / mean

    severity = _severity_from_deviation(deviation, tolerance)
    keys = tuple(p.key for p in phased)

    return CheckResult(
        check_id="cross.phase_balance",
        severity=severity,
        message=(
            f"Phase voltages: {', '.join(f'{v:.1f}V' for v in values)}, "
            f"max deviation from mean {deviation*100:.1f}%"
        ),
        expected=f"Phase unbalance < {tolerance*100:.0f}%",
        actual=f"unbalance={deviation*100:.1f}%",
        field_keys=keys,
    )


def cross_check_reactive_vs_pf(
    params: list[ClassifiedParam],
    tolerance: float = 0.20,
) -> CheckResult | None:
    """Q ~ P * tan(acos(PF)) within tolerance (default 25%)."""
    groups = _group_by_type(params)
    q_list = groups.get(ParameterType.REACTIVE_POWER, [])
    p_list = groups.get(ParameterType.ACTIVE_POWER, [])
    pf_list = groups.get(ParameterType.POWER_FACTOR, [])

    if not q_list or not p_list or not pf_list:
        return None

    q_actual = _avg(q_list)
    p = _avg(p_list)
    pf = _avg(pf_list)

    # Clamp PF to avoid domain errors
    pf_clamped = max(-0.999, min(0.999, pf))
    if abs(pf_clamped) < 0.01:
        return None  # PF near zero → tan explodes, skip

    q_calc = abs(p) * math.tan(math.acos(abs(pf_clamped)))
    if q_calc == 0:
        return None

    deviation = abs(abs(q_actual) - q_calc) / q_calc

    severity = _severity_from_deviation(deviation, tolerance)
    keys = tuple(x.key for x in q_list + p_list + pf_list)

    return CheckResult(
        check_id="cross.reactive_vs_pf",
        severity=severity,
        message=(
            f"Q_actual={q_actual:.2f} vs Q_calc={q_calc:.2f} "
            f"(from P={p:.2f}, PF={pf:.3f}; deviation {deviation*100:.1f}%)"
        ),
        expected=f"Q ~ P*tan(acos(PF)) within {tolerance*100:.0f}%",
        actual=f"deviation={deviation*100:.1f}%",
        field_keys=keys,
    )


# ---------------------------------------------------------------------------
# Collected cross-checks — append-friendly for future phases
# ---------------------------------------------------------------------------

ALL_CROSS_CHECKS: list[Callable[[list[ClassifiedParam]], CheckResult | None]] = [
    cross_check_vln_vll,
    cross_check_power_triangle,
    cross_check_power_calculation,
    cross_check_phase_balance,
    cross_check_reactive_vs_pf,
]
