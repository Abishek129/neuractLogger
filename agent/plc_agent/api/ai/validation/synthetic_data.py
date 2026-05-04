# mypy: ignore-errors
"""
Synthetic data generator — physics-aware training data for the anomaly autoencoder.

Generates reading snapshots from MFM KB ``typical_range`` values with
physically realistic correlations:
    P = V × I × PF × √3
    S² = P² + Q²
    Q = P × tan(acos(PF))
    Phase balance with realistic variance
    Frequency: narrow band ±0.5 Hz

Each sample is a 39-dimensional normalized [0,1] vector matching
the canonical parameter ordering in ``anomaly.py``.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger("loggerfast.ai.validation.synthetic")


class SyntheticDataGenerator:
    """Generate physics-aware synthetic reading snapshots from KB data."""

    def __init__(self, kb_registers: list[dict[str, Any]], canonical_params: list[str]):
        """
        Args:
            kb_registers: List of RegisterEntry dicts from KBEntry.registers
            canonical_params: The 39-slot canonical parameter list from anomaly.py
        """
        from .anomaly import resolve_canonical

        self._registers = kb_registers
        self._canonical = canonical_params
        self._canon_idx = {p: i for i, p in enumerate(canonical_params)}
        self._dim = len(canonical_params)

        # Build range lookup: canonical_index → (min, max)
        # Resolve KB param aliases (e.g. "active_power_total" → "active_power")
        self._ranges: dict[int, tuple[float, float]] = {}
        self._available: set[int] = set()

        for reg in kb_registers:
            param = reg.get("parameter", "")
            canon = resolve_canonical(param)
            idx = self._canon_idx.get(canon) if canon else None
            if idx is None:
                continue
            tr = reg.get("typical_range", [])
            if len(tr) == 2:
                self._ranges[idx] = (float(tr[0]), float(tr[1]))
            self._available.add(idx)

    def generate(self, n_samples: int = 10000) -> tuple[np.ndarray, np.ndarray]:
        """Generate synthetic training data.

        Returns:
            data: (n_samples, 39) array, normalized [0, 1]
            mask: (39,) binary mask — 1 for populated slots
        """
        rng = np.random.default_rng(seed=42)
        data = np.zeros((n_samples, self._dim), dtype=np.float64)
        mask = np.zeros(self._dim, dtype=np.float64)

        # Mark which slots this model populates
        for idx in self._available:
            mask[idx] = 1.0

        # --- Generate raw (unnormalized) values ---
        raw = np.zeros((n_samples, self._dim), dtype=np.float64)

        # Phase noise generators
        phase_noise_small = lambda: rng.normal(0, 0.02, n_samples)  # ±2% for voltage balance
        phase_noise_med = lambda: rng.normal(0, 0.05, n_samples)    # ±5% for current balance
        gen_noise = lambda pct: rng.normal(0, pct, n_samples)       # generic

        # 1. Voltage L-N (per-phase)
        vln_base = self._sample_range(rng, 0, n_samples, default=(220, 254))
        raw[:, 0] = vln_base                                        # voltage_l1n
        raw[:, 1] = vln_base * (1 + phase_noise_small())            # voltage_l2n
        raw[:, 2] = vln_base * (1 + phase_noise_small())            # voltage_l3n
        raw[:, 3] = (raw[:, 0] + raw[:, 1] + raw[:, 2]) / 3        # voltage_ln_avg

        # 2. Voltage L-L (derived from L-N × √3)
        sqrt3 = math.sqrt(3)
        raw[:, 4] = raw[:, 0] * sqrt3 * (1 + gen_noise(0.01))      # voltage_l12
        raw[:, 5] = raw[:, 1] * sqrt3 * (1 + gen_noise(0.01))      # voltage_l23
        raw[:, 6] = raw[:, 2] * sqrt3 * (1 + gen_noise(0.01))      # voltage_l31
        raw[:, 7] = (raw[:, 4] + raw[:, 5] + raw[:, 6]) / 3        # voltage_ll_avg

        # 3. Current (per-phase with load imbalance)
        i_base = self._sample_range(rng, 8, n_samples, default=(0, 100))
        raw[:, 8] = i_base                                          # current_l1
        raw[:, 9] = i_base * (1 + phase_noise_med())                # current_l2
        raw[:, 10] = i_base * (1 + phase_noise_med())               # current_l3
        raw[:, 11] = (raw[:, 8] + raw[:, 9] + raw[:, 10]) / 3      # current_avg

        # 4. Power Factor (per-phase)
        pf_base = rng.uniform(0.7, 1.0, n_samples)
        raw[:, 12] = np.clip(pf_base * (1 + gen_noise(0.02)), 0.01, 1.0)  # pf_l1
        raw[:, 13] = np.clip(pf_base * (1 + gen_noise(0.02)), 0.01, 1.0)  # pf_l2
        raw[:, 14] = np.clip(pf_base * (1 + gen_noise(0.02)), 0.01, 1.0)  # pf_l3
        raw[:, 15] = (raw[:, 12] + raw[:, 13] + raw[:, 14]) / 3           # pf_total

        # 5. Frequency
        raw[:, 16] = np.clip(rng.normal(50.0, 0.2, n_samples), 49.0, 51.0)

        # 6. Active Power (per-phase, derived: P_Lx = V_LxN × I_Lx × PF_Lx)
        for phase in range(3):
            v_idx = phase          # voltage_l1n/l2n/l3n
            i_idx = 8 + phase      # current_l1/l2/l3
            pf_idx = 12 + phase    # pf_l1/l2/l3
            p_idx = 17 + phase     # active_power_l1/l2/l3
            raw[:, p_idx] = raw[:, v_idx] * raw[:, i_idx] * raw[:, pf_idx] * (1 + gen_noise(0.03))

        raw[:, 20] = raw[:, 17] + raw[:, 18] + raw[:, 19]  # active_power total

        # 7. Reactive Power (Q = P × tan(acos(PF)))
        for phase in range(3):
            pf_val = np.clip(raw[:, 12 + phase], 0.01, 0.999)
            q_idx = 21 + phase
            raw[:, q_idx] = raw[:, 17 + phase] * np.tan(np.arccos(pf_val)) * (1 + gen_noise(0.05))

        raw[:, 24] = raw[:, 21] + raw[:, 22] + raw[:, 23]  # reactive_power total

        # 8. Apparent Power (S = √(P² + Q²))
        for phase in range(3):
            s_idx = 25 + phase
            raw[:, s_idx] = np.sqrt(
                raw[:, 17 + phase] ** 2 + raw[:, 21 + phase] ** 2
            ) * (1 + gen_noise(0.01))

        raw[:, 28] = raw[:, 25] + raw[:, 26] + raw[:, 27]  # apparent_power total

        # 9. Energy (monotonic accumulators — snapshot values)
        e_active_range = self._ranges.get(29, (0, 999999))
        raw[:, 29] = rng.uniform(e_active_range[0], e_active_range[1], n_samples)
        e_reactive_range = self._ranges.get(30, (0, 999999))
        raw[:, 30] = rng.uniform(e_reactive_range[0], e_reactive_range[1], n_samples)

        # 10. THD & Demand slots (31-38) — generate if KB has those registers
        # THD Voltage (slots 31-33): typically 1-8% in industrial settings
        for slot_idx in range(31, 34):
            if slot_idx in self._available:
                raw[:, slot_idx] = rng.uniform(1.0, 8.0, n_samples) + gen_noise(0.01) * 2

        # THD Current (slots 34-36): typically 5-25%
        for slot_idx in range(34, 37):
            if slot_idx in self._available:
                raw[:, slot_idx] = rng.uniform(5.0, 25.0, n_samples) + gen_noise(0.02) * 5

        # Demand Active (slot 37): correlated with active power total
        if 37 in self._available:
            raw[:, 37] = raw[:, 20] * rng.uniform(0.5, 1.0, n_samples)

        # Demand Apparent (slot 38): correlated with apparent power total
        if 38 in self._available:
            raw[:, 38] = raw[:, 28] * rng.uniform(0.5, 1.0, n_samples)

        # --- Normalize to [0, 1] ---
        for i in range(self._dim):
            if mask[i] == 0:
                continue
            lo, hi = self._get_norm_range(i)
            if hi <= lo:
                hi = lo + 1.0
            data[:, i] = np.clip((raw[:, i] - lo) / (hi - lo), 0.0, 1.0)

        return data, mask

    def _sample_range(
        self, rng: np.random.Generator, idx: int, n: int,
        default: tuple[float, float] = (0, 1),
    ) -> np.ndarray:
        """Sample n values uniformly from the KB typical_range for slot idx."""
        lo, hi = self._ranges.get(idx, default)
        return rng.uniform(lo, hi, n)

    def _get_norm_range(self, idx: int) -> tuple[float, float]:
        """Get normalization bounds for a canonical slot."""
        if idx in self._ranges:
            return self._ranges[idx]
        return _DEFAULT_NORM_RANGES.get(idx, (0, 1))


# ---------------------------------------------------------------------------
# Fallback normalization ranges (Indian industrial 3-phase defaults)
# Used when KB typical_range is missing for a parameter.
# ---------------------------------------------------------------------------

_DEFAULT_NORM_RANGES: dict[int, tuple[float, float]] = {
    0: (30, 350),       # voltage_l1n
    1: (30, 350),       # voltage_l2n
    2: (30, 350),       # voltage_l3n
    3: (30, 350),       # voltage_ln_avg
    4: (50, 600),       # voltage_l12
    5: (50, 600),       # voltage_l23
    6: (50, 600),       # voltage_l31
    7: (50, 600),       # voltage_ll_avg
    8: (0, 6000),       # current_l1
    9: (0, 6000),       # current_l2
    10: (0, 6000),      # current_l3
    11: (0, 6000),      # current_avg
    12: (-1, 1),        # pf_l1
    13: (-1, 1),        # pf_l2
    14: (-1, 1),        # pf_l3
    15: (-1, 1),        # pf_total
    16: (45, 55),       # frequency
    17: (0, 1e6),       # active_power_l1
    18: (0, 1e6),       # active_power_l2
    19: (0, 1e6),       # active_power_l3
    20: (0, 3e6),       # active_power total
    21: (0, 1e6),       # reactive_power_l1
    22: (0, 1e6),       # reactive_power_l2
    23: (0, 1e6),       # reactive_power_l3
    24: (0, 3e6),       # reactive_power total
    25: (0, 1e6),       # apparent_power_l1
    26: (0, 1e6),       # apparent_power_l2
    27: (0, 1e6),       # apparent_power_l3
    28: (0, 3e6),       # apparent_power total
    29: (0, 999999),    # energy_active
    30: (0, 999999),    # energy_reactive
    31: (0, 15),        # thd_voltage_l1 (%)
    32: (0, 15),        # thd_voltage_l2 (%)
    33: (0, 15),        # thd_voltage_l3 (%)
    34: (0, 40),        # thd_current_l1 (%)
    35: (0, 40),        # thd_current_l2 (%)
    36: (0, 40),        # thd_current_l3 (%)
    37: (0, 3e6),       # demand_active
    38: (0, 3e6),       # demand_apparent
}
