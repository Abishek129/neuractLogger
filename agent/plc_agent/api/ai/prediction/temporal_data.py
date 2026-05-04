# mypy: ignore-errors
"""
Per-device temporal data — feature extraction, sequence building, persistence.

Features (14-dim):
  10 electrical: voltage_ln_avg, current_l1/l2/l3, current_avg,
                 power_factor, active_power, reactive_power,
                 apparent_power, frequency
  4 temporal:    sin(2π·h/24), cos(2π·h/24), sin(2π·d/7), cos(2π·d/7)
"""
from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("loggerfast.ai.prediction.temporal_data")

_TEMPORAL_DIR = Path(__file__).resolve().parents[3] / "data" / "temporal_models"
_write_lock = threading.Lock()

SEQUENCE_LENGTH = 24  # 24 minutes of context at 60s polling

# Electrical features and their normalization ranges (from DEFAULT_RANGES)
FEATURE_SPECS: list[tuple[str, list[str], float, float]] = [
    # (feature_name, [possible_reading_keys], norm_min, norm_max)
    ("voltage_ln_avg", ["voltage_ln_avg", "voltage_avg", "vln_avg"], 30, 350),
    ("current_l1", ["current_l1", "i_l1", "i1"], 0, 6000),
    ("current_l2", ["current_l2", "i_l2", "i2"], 0, 6000),
    ("current_l3", ["current_l3", "i_l3", "i3"], 0, 6000),
    ("current_avg", ["current_avg", "i_avg"], 0, 6000),
    ("power_factor", ["power_factor", "pf", "pf_total", "power_factor_total"], -1, 1),
    ("active_power", ["active_power", "p_total", "active_power_total", "kw", "kw_total"], 0, 3e6),
    ("reactive_power", ["reactive_power", "q_total", "reactive_power_total", "kvar"], 0, 3e6),
    ("apparent_power", ["apparent_power", "s_total", "apparent_power_total", "kva"], 0, 3e6),
    ("frequency", ["frequency", "freq", "f"], 45, 55),
]

N_ELECTRICAL = len(FEATURE_SPECS)  # 10
N_TEMPORAL = 4  # hour_sin, hour_cos, dow_sin, dow_cos
N_FEATURES = N_ELECTRICAL + N_TEMPORAL  # 14

MIN_ELECTRICAL_PARAMS = 5  # minimum to produce a valid feature vector


def readings_to_feature_vector(
    readings: dict[str, Any], timestamp: float,
) -> np.ndarray | None:
    """Convert raw readings dict to normalized 14-dim feature vector.

    Returns None if fewer than MIN_ELECTRICAL_PARAMS electrical params are present.
    """
    vec = np.full(N_FEATURES, 0.5)  # default midpoint for missing
    found = 0

    readings_lower = {k.lower(): v for k, v in readings.items()}

    for i, (name, keys, lo, hi) in enumerate(FEATURE_SPECS):
        val = None
        for key in keys:
            val = readings_lower.get(key)
            if val is not None:
                break
        if val is None:
            # Try computing voltage_ln_avg from individual phases
            if name == "voltage_ln_avg":
                v1 = readings_lower.get("voltage_l1n")
                v2 = readings_lower.get("voltage_l2n")
                v3 = readings_lower.get("voltage_l3n")
                if v1 is not None and v2 is not None and v3 is not None:
                    val = (float(v1) + float(v2) + float(v3)) / 3.0
            # Try computing current_avg from individual phases
            elif name == "current_avg":
                i1 = readings_lower.get("current_l1")
                i2 = readings_lower.get("current_l2")
                i3 = readings_lower.get("current_l3")
                if i1 is not None and i2 is not None and i3 is not None:
                    val = (float(i1) + float(i2) + float(i3)) / 3.0

        if val is not None and isinstance(val, (int, float)) and not math.isnan(val):
            rng = hi - lo
            if rng > 0:
                vec[i] = max(0.0, min(1.0, (float(val) - lo) / rng))
            found += 1

    if found < MIN_ELECTRICAL_PARAMS:
        return None

    # Temporal features
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    hour = dt.hour + dt.minute / 60.0
    dow = dt.weekday()  # 0=Monday

    vec[N_ELECTRICAL] = math.sin(2 * math.pi * hour / 24.0)
    vec[N_ELECTRICAL + 1] = math.cos(2 * math.pi * hour / 24.0)
    vec[N_ELECTRICAL + 2] = math.sin(2 * math.pi * dow / 7.0)
    vec[N_ELECTRICAL + 3] = math.cos(2 * math.pi * dow / 7.0)

    return vec


def build_sequences(
    buffer: list[np.ndarray],
    seq_len: int = SEQUENCE_LENGTH,
    stride: int = 1,
    timestamps: list[float] | None = None,
    max_gap_s: float = 180.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert rolling buffer to (sequences, targets) for training.

    If *timestamps* is provided, sequences that span a gap larger than
    *max_gap_s* seconds are discarded to avoid training on data that
    crosses power outages or device disconnections.

    Returns:
        sequences: (N, seq_len, n_features)
        targets: (N, n_features) — next-step values
    """
    n = len(buffer)
    seqs = []
    tgts = []
    for i in range(0, n - seq_len, stride):
        # Gap detection: ensure no discontinuity within this sequence
        if timestamps is not None and len(timestamps) > i + seq_len:
            has_gap = False
            for j in range(i, i + seq_len):
                if timestamps[j + 1] - timestamps[j] > max_gap_s:
                    has_gap = True
                    break
            if has_gap:
                continue
        seqs.append(np.array(buffer[i : i + seq_len]))
        tgts.append(buffer[i + seq_len])
    if not seqs:
        return np.empty((0, seq_len, buffer[0].shape[0] if buffer else 0)), np.empty((0, buffer[0].shape[0] if buffer else 0))
    return np.array(seqs), np.array(tgts)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _device_dir(device_id: str) -> Path:
    return _TEMPORAL_DIR / device_id


def save_baseline(
    device_id: str,
    features: np.ndarray,
    timestamps: np.ndarray,
) -> None:
    """Persist baseline buffer to disk for crash recovery."""
    d = _device_dir(device_id)
    d.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        np.savez_compressed(
            str(d / "baseline.npz"),
            features=features,
            timestamps=timestamps,
        )


def load_baseline(device_id: str) -> tuple[np.ndarray, np.ndarray] | None:
    """Load persisted baseline buffer."""
    path = _device_dir(device_id) / "baseline.npz"
    if not path.exists():
        return None
    data = np.load(str(path))
    return data["features"], data["timestamps"]


def save_model_metadata(device_id: str, metadata: dict) -> None:
    """Save per-device metadata.json."""
    d = _device_dir(device_id)
    d.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        (d / "metadata.json").write_text(
            json.dumps(metadata, indent=2, default=str), encoding="utf-8",
        )


def load_model_metadata(device_id: str) -> dict | None:
    """Load per-device metadata."""
    path = _device_dir(device_id) / "metadata.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_temporal_index() -> dict:
    """Global index of all temporal models."""
    path = _TEMPORAL_DIR / "index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_temporal_index(device_id: str, **fields) -> None:
    """Update device entry in global index."""
    with _write_lock:
        _TEMPORAL_DIR.mkdir(parents=True, exist_ok=True)
        path = _TEMPORAL_DIR / "index.json"
        idx = {}
        if path.exists():
            try:
                idx = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        entry = idx.get(device_id, {})
        entry.update(fields)
        idx[device_id] = entry
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
