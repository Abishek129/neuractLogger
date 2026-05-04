# mypy: ignore-errors
"""
Training data management — collect, store, export/import anonymized reading
snapshots for anomaly autoencoder retraining.

Data is stored per MFM model family as compressed NumPy arrays:
    agent/plc_agent/data/anomaly_training/{model}_dataset.npz

Each .npz contains:
    data  — (N, 39) float64 normalized [0,1] canonical vectors
    mask  — (39,) float64 binary mask (which slots this model populates)
    count — scalar, number of samples

An index.json tracks per-model metadata (sample count, versions, timestamps).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("loggerfast.ai.validation.training_data")

_TRAINING_DIR = Path(__file__).resolve().parents[3] / "data" / "anomaly_training"
_INDEX_PATH = _TRAINING_DIR / "index.json"
_MAX_SAMPLES = 50_000  # cap per model — FIFO if exceeded

_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def load_training_index() -> dict:
    """Load the training data index. Returns empty dict if not found."""
    if not _INDEX_PATH.exists():
        return {}
    try:
        return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_training_index(model_family: str, **fields) -> None:
    """Update a model's entry in the training index."""
    with _write_lock:
        idx = load_training_index()
        entry = idx.get(model_family, {})
        entry.update(fields)
        idx[model_family] = entry
        _TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _INDEX_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_INDEX_PATH)


# ---------------------------------------------------------------------------
# Dataset storage
# ---------------------------------------------------------------------------

def append_training_samples(
    model_family: str,
    readings_list: list[dict[str, Any]],
    kb_registers: list[dict[str, Any]],
    skip_outlier_filter: bool = False,
) -> int:
    """Normalize readings and append to the per-model training dataset.

    Args:
        model_family: Sanitized model key (e.g. "pm5110")
        readings_list: List of {"values": {field: value}, ...} dicts
        kb_registers: RegisterEntry dicts for normalization
        skip_outlier_filter: If True, skip anomaly-based outlier filtering.
            Use for initial bootstrap from historical data when the model
            was only trained on synthetic data.

    Returns:
        Number of samples successfully appended.
    """
    from .anomaly import AnomalyDetector

    detector = AnomalyDetector.instance()

    # Normalize each reading to 39-dim vector, filtering outliers
    new_vecs = []
    shared_mask = None
    skipped_outliers = 0
    for reading in readings_list:
        values = reading.get("values")
        if not values or not isinstance(values, dict):
            continue
        try:
            vec, mask = detector._normalize(values, kb_registers)
            if mask.sum() == 0:
                continue

            # Outlier filtering: skip readings with high anomaly score
            # to prevent bad data from corrupting the training set
            if not skip_outlier_filter:
                try:
                    anomaly_result = detector.compute_anomaly(vec, mask, model_family)
                    if anomaly_result is not None and anomaly_result.get("score", 0) > 0.5:
                        skipped_outliers += 1
                        logger.debug("training_sample_skipped_outlier",
                                     extra={"model": model_family,
                                            "score": anomaly_result.get("score")})
                        continue
                except Exception:
                    pass  # No trained model yet — allow all samples through

            new_vecs.append(vec)
            if shared_mask is None:
                shared_mask = mask.copy()
            else:
                # Union mask (any slot populated in any sample)
                shared_mask = np.maximum(shared_mask, mask)
        except Exception:
            logger.debug("normalize_failed", exc_info=True)
            continue

    if skipped_outliers:
        logger.info("training_outliers_filtered",
                     extra={"model": model_family, "skipped": skipped_outliers})

    if not new_vecs:
        return 0

    new_data = np.array(new_vecs, dtype=np.float64)

    with _write_lock:
        _TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        dataset_path = _TRAINING_DIR / f"{model_family}_dataset.npz"

        # Load existing dataset
        existing_data = None
        if dataset_path.exists():
            try:
                loaded = np.load(str(dataset_path))
                existing_data = loaded["data"]
                existing_mask = loaded["mask"]
                shared_mask = np.maximum(shared_mask, existing_mask)
            except Exception:
                existing_data = None

        # Combine
        if existing_data is not None and len(existing_data) > 0:
            combined = np.vstack([existing_data, new_data])
        else:
            combined = new_data

        # Cap at MAX_SAMPLES (FIFO — drop oldest)
        if len(combined) > _MAX_SAMPLES:
            combined = combined[-_MAX_SAMPLES:]

        # Save
        np.savez_compressed(
            str(dataset_path),
            data=combined,
            mask=shared_mask,
            count=np.array([len(combined)]),
        )

        # Update index
        now = datetime.now(timezone.utc).isoformat()
        update_training_index(
            model_family,
            samples=int(len(combined)),
            last_updated=now,
        )

    logger.info("training_samples_appended", extra={
        "model": model_family,
        "new": len(new_vecs),
        "total": len(combined),
    })
    return len(new_vecs)


def load_training_dataset(
    model_family: str,
) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Load a model's training dataset from disk.

    Returns (data, mask, count) or None if not found.
    """
    dataset_path = _TRAINING_DIR / f"{model_family}_dataset.npz"
    if not dataset_path.exists():
        return None
    try:
        loaded = np.load(str(dataset_path))
        data = loaded["data"]
        mask = loaded["mask"]
        raw_count = loaded["count"] if "count" in loaded else len(data)
        count = int(raw_count.item()) if hasattr(raw_count, 'item') else int(raw_count)
        return data, mask, count
    except Exception:
        logger.warning("dataset_load_failed", extra={"model": model_family}, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------

def export_dataset(model_family: str) -> bytes | None:
    """Read raw .npz bytes for download. Returns None if not found."""
    dataset_path = _TRAINING_DIR / f"{model_family}_dataset.npz"
    if not dataset_path.exists():
        return None
    return dataset_path.read_bytes()


def import_dataset(model_family: str, npz_bytes: bytes) -> int:
    """Import a dataset from .npz bytes. Merges with existing data.

    Returns total sample count after import.
    """
    import io

    # Validate the uploaded data
    try:
        loaded = np.load(io.BytesIO(npz_bytes))
        imported_data = loaded["data"]
        imported_mask = loaded["mask"]
    except Exception as e:
        raise ValueError(f"Invalid .npz file: {e}")

    if imported_data.ndim != 2 or imported_data.shape[1] != 39:
        raise ValueError(f"Expected shape (N, 39), got {imported_data.shape}")
    if imported_mask.shape != (39,):
        raise ValueError(f"Expected mask shape (39,), got {imported_mask.shape}")

    with _write_lock:
        _TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        dataset_path = _TRAINING_DIR / f"{model_family}_dataset.npz"

        # Merge with existing
        existing_data = None
        if dataset_path.exists():
            try:
                existing = np.load(str(dataset_path))
                existing_data = existing["data"]
                imported_mask = np.maximum(imported_mask, existing["mask"])
            except Exception:
                pass

        if existing_data is not None and len(existing_data) > 0:
            combined = np.vstack([existing_data, imported_data])
        else:
            combined = imported_data

        if len(combined) > _MAX_SAMPLES:
            combined = combined[-_MAX_SAMPLES:]

        np.savez_compressed(
            str(dataset_path),
            data=combined,
            mask=imported_mask,
            count=np.array([len(combined)]),
        )

        now = datetime.now(timezone.utc).isoformat()
        update_training_index(model_family, samples=int(len(combined)), last_updated=now)

    logger.info("dataset_imported", extra={
        "model": model_family,
        "imported": len(imported_data),
        "total": len(combined),
    })
    return len(combined)
