# mypy: ignore-errors
"""
Anomaly detection autoencoder — Layer 2 validation.

A lightweight pure-NumPy autoencoder (39→16→8→16→39, <1MB, CPU-only)
that catches subtle issues missed by Layer 1 rule-based checks:
    - Reversed CT wiring
    - Wrong byte order
    - Misidentified meter model

Per MFM model family, trained on synthetic physics-aware data from
KB ``typical_range``. Cold-start training happens automatically on
first inference if no pre-trained model exists.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from .anomaly_types import AnomalyResult, _severity_from_score

logger = logging.getLogger("loggerfast.ai.validation.anomaly")

# ---------------------------------------------------------------------------
# Canonical parameter vector (39 slots)
# ---------------------------------------------------------------------------

CANONICAL_PARAMS: list[str] = [
    # Voltage L-N (0-3)
    "voltage_l1n", "voltage_l2n", "voltage_l3n", "voltage_ln_avg",
    # Voltage L-L (4-7)
    "voltage_l12", "voltage_l23", "voltage_l31", "voltage_ll_avg",
    # Current (8-11)
    "current_l1", "current_l2", "current_l3", "current_avg",
    # Power Factor (12-15)
    "power_factor_l1", "power_factor_l2", "power_factor_l3", "power_factor",
    # Frequency (16)
    "frequency",
    # Active Power (17-20)
    "active_power_l1", "active_power_l2", "active_power_l3", "active_power",
    # Reactive Power (21-24)
    "reactive_power_l1", "reactive_power_l2", "reactive_power_l3", "reactive_power",
    # Apparent Power (25-28)
    "apparent_power_l1", "apparent_power_l2", "apparent_power_l3", "apparent_power",
    # Energy (29-30)
    "energy_active", "energy_reactive",
    # Reserved (31-38)
    "thd_voltage_l1", "thd_voltage_l2", "thd_voltage_l3",
    "thd_current_l1", "thd_current_l2", "thd_current_l3",
    "demand_active", "demand_apparent",
]

CANONICAL_INDEX: dict[str, int] = {p: i for i, p in enumerate(CANONICAL_PARAMS)}

# Alias map: KB parameter names that differ from canonical names.
# Maps non-canonical KB param → canonical param so both _normalize() and
# SyntheticDataGenerator resolve KB registers to the correct vector slot.
PARAM_ALIASES: dict[str, str] = {
    # "_total" suffixed totals → canonical unsuffixed totals
    "active_power_total":   "active_power",
    "reactive_power_total": "reactive_power",
    "apparent_power_total": "apparent_power",
    "power_factor_total":   "power_factor",
    "power_factor_avg":     "power_factor",
    # Energy import variants → canonical energy slots
    "energy_active_import": "energy_active",
    "energy_reactive_import": "energy_reactive",
    # THD with "_l1n/_l2n/_l3n" phase naming → canonical "_l1/_l2/_l3"
    "thd_voltage_l1n":      "thd_voltage_l1",
    "thd_voltage_l2n":      "thd_voltage_l2",
    "thd_voltage_l3n":      "thd_voltage_l3",
    # Voltage L-L alternate naming (l1l2 → l12)
    "voltage_l1l2":         "voltage_l12",
    "voltage_l2l3":         "voltage_l23",
    "voltage_l3l1":         "voltage_l31",
}

INPUT_DIM = len(CANONICAL_PARAMS)  # 39


def resolve_canonical(param: str) -> str | None:
    """Resolve a parameter name to its canonical form, or None if unmappable."""
    if param in CANONICAL_INDEX:
        return param
    return PARAM_ALIASES.get(param)

# Default normalization ranges (Indian industrial 3-phase)
DEFAULT_RANGES: dict[str, tuple[float, float]] = {
    "voltage_l1n": (30, 350), "voltage_l2n": (30, 350), "voltage_l3n": (30, 350),
    "voltage_ln_avg": (30, 350),
    "voltage_l12": (50, 600), "voltage_l23": (50, 600), "voltage_l31": (50, 600),
    "voltage_ll_avg": (50, 600),
    "current_l1": (0, 6000), "current_l2": (0, 6000), "current_l3": (0, 6000),
    "current_avg": (0, 6000),
    "power_factor_l1": (-1, 1), "power_factor_l2": (-1, 1),
    "power_factor_l3": (-1, 1), "power_factor": (-1, 1),
    "frequency": (45, 55),
    "active_power_l1": (0, 1e6), "active_power_l2": (0, 1e6),
    "active_power_l3": (0, 1e6), "active_power": (0, 3e6),
    "reactive_power_l1": (0, 1e6), "reactive_power_l2": (0, 1e6),
    "reactive_power_l3": (0, 1e6), "reactive_power": (0, 3e6),
    "apparent_power_l1": (0, 1e6), "apparent_power_l2": (0, 1e6),
    "apparent_power_l3": (0, 1e6), "apparent_power": (0, 3e6),
    "energy_active": (0, 999999), "energy_reactive": (0, 999999),
    "thd_voltage_l1": (0, 15), "thd_voltage_l2": (0, 15), "thd_voltage_l3": (0, 15),
    "thd_current_l1": (0, 40), "thd_current_l2": (0, 40), "thd_current_l3": (0, 40),
    "demand_active": (0, 3e6), "demand_apparent": (0, 3e6),
}

# Models directory
_MODELS_DIR = Path(__file__).resolve().parents[3] / "data" / "anomaly_models"


# ---------------------------------------------------------------------------
# NumpyAutoencoder — the neural network
# ---------------------------------------------------------------------------

class NumpyAutoencoder:
    """Pure NumPy 4-layer autoencoder: input → h1 → bottleneck → h1 → output.

    Architecture: 39 → 16 → 8 → 16 → 39
    Activations: ReLU (hidden layers), Sigmoid (output)
    Size: ~1,872 weights = ~15KB saved
    """

    def __init__(self, input_dim: int = 39, hidden1: int = 16, bottleneck: int = 8):
        self.input_dim = input_dim
        self.hidden1 = hidden1
        self.bottleneck = bottleneck
        self.threshold_97: float = 1.0  # calibrated after training

        # Xavier initialization
        self.W1 = np.random.randn(input_dim, hidden1) * np.sqrt(2.0 / input_dim)
        self.b1 = np.zeros(hidden1)
        self.W2 = np.random.randn(hidden1, bottleneck) * np.sqrt(2.0 / hidden1)
        self.b2 = np.zeros(bottleneck)
        self.W3 = np.random.randn(bottleneck, hidden1) * np.sqrt(2.0 / bottleneck)
        self.b3 = np.zeros(hidden1)
        self.W4 = np.random.randn(hidden1, input_dim) * np.sqrt(2.0 / hidden1)
        self.b4 = np.zeros(input_dim)

    def forward(self, x: np.ndarray) -> np.ndarray:
        """Full encode + decode pass. Input: (batch, dim) or (dim,)."""
        squeeze = x.ndim == 1
        if squeeze:
            x = x.reshape(1, -1)

        a1 = np.maximum(0, x @ self.W1 + self.b1)        # ReLU
        a2 = np.maximum(0, a1 @ self.W2 + self.b2)       # ReLU
        a3 = np.maximum(0, a2 @ self.W3 + self.b3)       # ReLU
        z4 = a3 @ self.W4 + self.b4
        out = _sigmoid(z4)                                 # Sigmoid

        return out.squeeze(0) if squeeze else out

    def encode(self, x: np.ndarray) -> np.ndarray:
        """Return bottleneck representation (8-dim)."""
        squeeze = x.ndim == 1
        if squeeze:
            x = x.reshape(1, -1)
        a1 = np.maximum(0, x @ self.W1 + self.b1)
        a2 = np.maximum(0, a1 @ self.W2 + self.b2)
        return a2.squeeze(0) if squeeze else a2

    def compute_anomaly(
        self, x: np.ndarray, mask: np.ndarray,
    ) -> tuple[float, dict[str, float]]:
        """Compute anomaly score and per-parameter contributions.

        Args:
            x: (dim,) normalized input vector
            mask: (dim,) binary mask — 1 for populated slots

        Returns:
            (score, contributions) where score ∈ [0, 1] and
            contributions maps canonical param name → fraction of total error.
        """
        reconstruction = self.forward(x)
        sq_errors = ((x - reconstruction) ** 2) * mask

        total_error = sq_errors.sum()
        mask_count = mask.sum()
        if mask_count == 0:
            return 0.0, {}

        # Mean masked error, scaled by calibrated threshold
        raw_score = total_error / mask_count
        score = min(1.0, raw_score / self.threshold_97) if self.threshold_97 > 0 else 0.0

        # Per-parameter contribution (fraction of total)
        contributions: dict[str, float] = {}
        if total_error > 0:
            for i, param in enumerate(CANONICAL_PARAMS):
                if mask[i] > 0 and sq_errors[i] > 0:
                    contributions[param] = float(sq_errors[i] / total_error)

        return float(score), contributions

    def save(self, path: str | Path) -> None:
        """Save weights + threshold to .npz file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            str(path),
            W1=self.W1, b1=self.b1,
            W2=self.W2, b2=self.b2,
            W3=self.W3, b3=self.b3,
            W4=self.W4, b4=self.b4,
            threshold_97=np.array([self.threshold_97]),
            input_dim=np.array([self.input_dim]),
            hidden1=np.array([self.hidden1]),
            bottleneck=np.array([self.bottleneck]),
        )
        logger.info("model_saved path=%s size=%d", path, path.stat().st_size)

    @classmethod
    def load(cls, path: str | Path) -> "NumpyAutoencoder":
        """Load from .npz file."""
        data = np.load(str(path))
        input_dim = int(data["input_dim"][0])
        hidden1 = int(data["hidden1"][0])
        bottleneck = int(data["bottleneck"][0])

        model = cls(input_dim=input_dim, hidden1=hidden1, bottleneck=bottleneck)
        model.W1 = data["W1"]
        model.b1 = data["b1"]
        model.W2 = data["W2"]
        model.b2 = data["b2"]
        model.W3 = data["W3"]
        model.b3 = data["b3"]
        model.W4 = data["W4"]
        model.b4 = data["b4"]
        model.threshold_97 = float(data["threshold_97"][0])
        return model


# ---------------------------------------------------------------------------
# AnomalyDetector — high-level interface
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """High-level anomaly detector with lazy model loading and cold-start training."""

    _instance: "AnomalyDetector | None" = None

    def __init__(self):
        self._model_cache: dict[str, NumpyAutoencoder] = {}

    @classmethod
    def instance(cls) -> "AnomalyDetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def check(
        self,
        readings: dict[str, float],
        model: str,
        kb_registers: list[dict[str, Any]],
    ) -> AnomalyResult:
        """Run anomaly detection on a set of readings.

        Args:
            readings: field_key → value (raw, unnormalized)
            model: MFM model name (e.g. "PM5110")
            kb_registers: RegisterEntry dicts from KBEntry.registers

        Returns:
            AnomalyResult with score, severity, and per-parameter contributions.
        """
        model_family = _sanitize_key(model)

        # Normalize readings to canonical vector
        vec, mask = self._normalize(readings, kb_registers)

        # Get or train model
        ae = self._get_model(model_family, kb_registers)

        # Compute anomaly
        score, contributions = ae.compute_anomaly(vec, mask)
        severity = _severity_from_score(score)

        # Top contributors (sorted by contribution, descending)
        sorted_contribs = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        top = [name for name, _ in sorted_contribs[:5]]

        # Human-readable interpretation
        interpretation = _build_interpretation(score, severity, top)

        return AnomalyResult(
            score=score,
            severity=severity,
            contributions=contributions,
            top_contributors=top,
            model_family=model_family,
            interpretation=interpretation,
        )

    def _normalize(
        self,
        readings: dict[str, float],
        kb_registers: list[dict[str, Any]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Map readings to 39-dim canonical vector, normalized [0, 1].

        Two-tier mapping:
            1. Exact match: reading key → CANONICAL_INDEX
            2. Fallback: KB register parameter → CANONICAL_INDEX
        """
        vec = np.zeros(INPUT_DIM, dtype=np.float64)
        mask = np.zeros(INPUT_DIM, dtype=np.float64)

        # Build KB param → typical_range lookup, resolving aliases
        kb_ranges: dict[str, tuple[float, float]] = {}
        for reg in kb_registers:
            param = reg.get("parameter", "")
            canon = resolve_canonical(param) or param
            tr = reg.get("typical_range", [])
            if canon and len(tr) == 2:
                kb_ranges[canon] = (float(tr[0]), float(tr[1]))

        for key, value in readings.items():
            if not isinstance(value, (int, float)):
                continue
            if not np.isfinite(value):
                continue

            # Tier 1: exact match or alias → canonical index
            resolved = resolve_canonical(key)
            idx = CANONICAL_INDEX.get(resolved) if resolved else None

            # Tier 2: regex-based classify fallback
            if idx is None:
                idx = _classify_to_canonical(key, value)

            if idx is None:
                continue

            # Get normalization range
            param_name = CANONICAL_PARAMS[idx]
            lo, hi = kb_ranges.get(param_name, DEFAULT_RANGES.get(param_name, (0, 1)))
            if hi <= lo:
                hi = lo + 1.0

            vec[idx] = np.clip((float(value) - lo) / (hi - lo), 0.0, 1.0)
            mask[idx] = 1.0

        return vec, mask

    def _get_model(
        self, model_family: str, kb_registers: list[dict[str, Any]],
    ) -> NumpyAutoencoder:
        """Get cached model, load from disk, or cold-start train."""
        if model_family in self._model_cache:
            return self._model_cache[model_family]

        model_path = _MODELS_DIR / f"{model_family}.npz"
        if model_path.exists():
            try:
                ae = NumpyAutoencoder.load(model_path)
                self._model_cache[model_family] = ae
                logger.info("model_loaded model=%s", model_family)
                return ae
            except Exception:
                logger.warning("model_load_failed model=%s", model_family, exc_info=True)

        # Cold-start training
        ae = self._train_cold_start(model_family, kb_registers)
        self._model_cache[model_family] = ae
        return ae

    def _train_cold_start(
        self, model_family: str, kb_registers: list[dict[str, Any]],
    ) -> NumpyAutoencoder:
        """Generate synthetic data and train a new model."""
        from .synthetic_data import SyntheticDataGenerator
        from .training import train_autoencoder

        logger.info("cold_start_training model=%s", model_family)

        gen = SyntheticDataGenerator(kb_registers, CANONICAL_PARAMS)
        data, mask = gen.generate(n_samples=10000)

        ae = train_autoencoder(data, mask, input_dim=INPUT_DIM)

        # Save to disk
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        ae.save(_MODELS_DIR / f"{model_family}.npz")

        logger.info("cold_start_complete model=%s threshold=%.6f", model_family, ae.threshold_97)
        return ae

    def retrain_model(
        self, model_family: str, kb_registers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Retrain a model using real + synthetic data mix.

        Real data gets 2x weight via duplication. Synthetic fills to 10k min.
        Old model is backed up. Returns training stats.
        """
        from .training_data import load_training_dataset, load_training_index, update_training_index
        from .synthetic_data import SyntheticDataGenerator
        from .training import train_autoencoder
        from datetime import datetime, timezone

        # Load real data
        real_result = load_training_dataset(model_family)
        real_data, real_mask, real_count = (None, None, 0)
        if real_result is not None:
            real_data, real_mask, real_count = real_result

        # Generate synthetic data
        gen = SyntheticDataGenerator(kb_registers, CANONICAL_PARAMS)
        min_total = 10000
        synth_count = max(min_total - (real_count * 2), 2000)
        synth_data, synth_mask = gen.generate(n_samples=synth_count)

        # Mix datasets (real data gets 2x weight)
        if real_data is not None and real_count > 0:
            weighted_real = np.tile(real_data, (2, 1))
            combined = np.vstack([weighted_real, synth_data])
            mask = np.maximum(real_mask, synth_mask)
        else:
            combined = synth_data
            mask = synth_mask

        # Train
        ae = train_autoencoder(combined, mask, input_dim=INPUT_DIM)

        # Backup old model
        model_path = _MODELS_DIR / f"{model_family}.npz"
        idx = load_training_index()
        old_version = idx.get(model_family, {}).get("model_version", 1)

        if model_path.exists():
            backup = _MODELS_DIR / f"{model_family}_v{old_version}.npz"
            try:
                import shutil
                shutil.copy2(str(model_path), str(backup))
            except Exception:
                pass

        # Save new model
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        ae.save(model_path)
        self._model_cache[model_family] = ae

        # Update index
        new_version = old_version + 1
        update_training_index(
            model_family,
            last_retrain=datetime.now(timezone.utc).isoformat(),
            model_version=new_version,
            threshold_97=ae.threshold_97,
            synthetic_samples=synth_count,
        )

        logger.info("retrain_complete model=%s real=%d synth=%d version=%d threshold=%.6f",
                     model_family, real_count, synth_count, new_version, ae.threshold_97)

        return {
            "model_family": model_family,
            "real_samples": real_count,
            "synthetic_samples": synth_count,
            "total_training_samples": len(combined),
            "model_version": new_version,
            "threshold_97": float(ae.threshold_97),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    return np.where(
        x >= 0,
        1 / (1 + np.exp(-x)),
        np.exp(x) / (1 + np.exp(x)),
    )


def _sanitize_key(model: str) -> str:
    """Sanitize model name to filesystem-safe key."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", model.strip().lower())


def _classify_to_canonical(key: str, value: float) -> int | None:
    """Fallback: try to map a reading key to canonical index using regex.

    Handles common abbreviations from LoggerFast schemas:
    V_L1, V_L2, V_L3, I_L1, I_L2, I_L3, Hz, kW, kVA, kVAR, PF,
    as well as longer forms like voltage_l1n, current_l1, etc.
    """
    k = key.strip().lower()

    # ── Short-form aliases (V_L1, I_L1, Hz, etc.) ──
    _SHORT_MAP = {
        "v_l1": "voltage_l1n", "v_l2": "voltage_l2n", "v_l3": "voltage_l3n",
        "v_l1_l2": "voltage_l12", "v_l2_l3": "voltage_l23", "v_l3_l1": "voltage_l31",
        "v_ln": "voltage_ln_avg", "v_ll": "voltage_ll_avg",
        "i_l1": "current_l1", "i_l2": "current_l2", "i_l3": "current_l3",
        "i_avg": "current_avg",
        "pf_l1": "power_factor_l1", "pf_l2": "power_factor_l2", "pf_l3": "power_factor_l3",
        "pf": "power_factor",
        "hz": "frequency", "freq": "frequency",
        "kw": "active_power", "kva": "apparent_power", "kvar": "reactive_power",
        "kwh": "energy_active", "kvarh": "energy_reactive",
        "p_l1": "active_power_l1", "p_l2": "active_power_l2", "p_l3": "active_power_l3",
        "q_l1": "reactive_power_l1", "q_l2": "reactive_power_l2", "q_l3": "reactive_power_l3",
        "s_l1": "apparent_power_l1", "s_l2": "apparent_power_l2", "s_l3": "apparent_power_l3",
        "thd_v_l1": "thd_voltage_l1", "thd_v_l2": "thd_voltage_l2", "thd_v_l3": "thd_voltage_l3",
        "thd_i_l1": "thd_current_l1", "thd_i_l2": "thd_current_l2", "thd_i_l3": "thd_current_l3",
    }
    canon = _SHORT_MAP.get(k)
    if canon:
        return CANONICAL_INDEX.get(canon)

    # ── Long-form patterns ──

    # Voltage patterns
    m = re.match(r"volt(?:age)?_l(\d)n?", k)
    if m:
        phase = int(m.group(1))
        return CANONICAL_INDEX.get(f"voltage_l{phase}n")

    m = re.match(r"volt(?:age)?_l(\d)(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"voltage_l{m.group(1)}{m.group(2)}")

    if "voltage" in k and "avg" in k:
        if "ll" in k or "line" in k:
            return CANONICAL_INDEX.get("voltage_ll_avg")
        return CANONICAL_INDEX.get("voltage_ln_avg")

    # Current
    m = re.match(r"curr(?:ent)?_l(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"current_l{m.group(1)}")
    if "current" in k and "avg" in k:
        return CANONICAL_INDEX.get("current_avg")

    # Power factor
    m = re.match(r"p(?:ower)?_?f(?:actor)?_l(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"power_factor_l{m.group(1)}")
    if re.match(r"p(?:ower)?_?f(?:actor)?$", k):
        return CANONICAL_INDEX.get("power_factor")

    # Frequency
    if "freq" in k:
        return CANONICAL_INDEX.get("frequency")

    # Active power
    m = re.match(r"(?:active_?)?power_l(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"active_power_l{m.group(1)}")
    if re.match(r"(?:active_?power|^kw)", k):
        return CANONICAL_INDEX.get("active_power")

    # Reactive power
    m = re.match(r"reactive_?(?:power)?_l(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"reactive_power_l{m.group(1)}")
    if re.match(r"reactive|^kvar", k):
        return CANONICAL_INDEX.get("reactive_power")

    # Apparent power
    m = re.match(r"apparent_?(?:power)?_l(\d)", k)
    if m:
        return CANONICAL_INDEX.get(f"apparent_power_l{m.group(1)}")
    if re.match(r"apparent|^kva", k):
        return CANONICAL_INDEX.get("apparent_power")

    # Energy
    if "energy" in k and "reactive" in k:
        return CANONICAL_INDEX.get("energy_reactive")
    if "energy" in k or "kwh" in k:
        return CANONICAL_INDEX.get("energy_active")

    return None


def _build_interpretation(score: float, severity: str, top: list[str]) -> str:
    """Build a human-readable interpretation of the anomaly result."""
    if severity == "normal":
        return "Readings are consistent with expected patterns for this meter model."

    top_str = ", ".join(top[:3]) if top else "unknown parameters"

    if severity == "moderate":
        return (
            f"Some readings show moderate deviation from expected patterns. "
            f"Key contributors: {top_str}. Consider verifying device configuration."
        )

    return (
        f"Readings show significant deviation from expected patterns. "
        f"Key contributors: {top_str}. "
        f"Possible causes: reversed CT wiring, wrong byte order, or misidentified meter model. "
        f"Manual verification recommended."
    )
