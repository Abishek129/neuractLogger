# mypy: ignore-errors
"""
TemporalManager — per-device TCN temporal anomaly detection lifecycle.

State machine per device:
    ACCUMULATING → (samples >= needed) → train → ACTIVE
    ACTIVE → (retrain interval) → RETRAINING → ACTIVE
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .temporal_types import (
    DeviceTemporalState,
    LoadClass,
    TemporalAlertCode,
    TemporalAlertInfo,
    TemporalModelStatus,
)

logger = logging.getLogger("loggerfast.ai.prediction.temporal_monitor")


class TemporalManager:
    """Thread-safe singleton managing per-device TCN temporal models."""

    _instance: Optional["TemporalManager"] = None
    _class_lock = threading.Lock()

    # Configurable defaults
    baseline_samples: int = 4320        # 3 days @ 60s
    max_baseline: int = 10080           # 7 days @ 60s
    retrain_interval: float = 7 * 86400  # 7 days
    alert_cooldown: float = 600.0       # 10 minutes
    anomaly_threshold: float = 1.5      # score threshold (>1 = above 97th pct)
    score_smoothing: int = 5            # smooth over N readings

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._device_locks: Dict[str, threading.Lock] = {}
        self._devices: Dict[str, DeviceTemporalState] = {}
        self._startup_load()

    @classmethod
    def instance(cls) -> "TemporalManager":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = TemporalManager()
            return cls._instance

    def configure(self, **kwargs: Any) -> None:
        """Update configuration at runtime."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    # ------------------------------------------------------------------
    # Feed — main ingestion entry point
    # ------------------------------------------------------------------

    def feed(
        self,
        device_id: str,
        table_id: str,
        readings: Dict[str, Any],
    ) -> List[TemporalAlertInfo]:
        """Ingest new reading. Returns new temporal alerts.

        Called from PredictionManager.feed() after statistical checks.
        """
        from .temporal_data import readings_to_feature_vector, SEQUENCE_LENGTH

        vec = readings_to_feature_vector(readings, time.time())
        if vec is None:
            return []

        with self._lock:
            state = self._get_or_create(device_id)

            state.baseline_buffer.append(vec)
            state.baseline_timestamps.append(time.time())

            # Trim buffer to max
            if len(state.baseline_buffer) > self.max_baseline:
                excess = len(state.baseline_buffer) - self.max_baseline
                state.baseline_buffer = state.baseline_buffer[excess:]
                state.baseline_timestamps = state.baseline_timestamps[excess:]

        # Handle state-specific logic (outside global lock for training)
        if state.status == "accumulating":
            has_enough_samples = len(state.baseline_buffer) >= state.samples_needed
            # Also require minimum temporal coverage (72 hours) for diurnal cycle
            MIN_TIMESPAN_S = 72 * 3600  # 72 hours
            has_enough_timespan = (
                len(state.baseline_timestamps) >= 2
                and (state.baseline_timestamps[-1] - state.baseline_timestamps[0]) >= MIN_TIMESPAN_S
            )
            if has_enough_samples and has_enough_timespan:
                self._trigger_training(state)
            return []

        if state.model is None:
            return []

        # During training/retraining, keep using the old model for inference
        # so we don't miss real anomalies. The model reference is updated
        # atomically after training completes.

        # Inference
        buf_len = len(state.baseline_buffer)
        if buf_len < SEQUENCE_LENGTH + 1:
            return []

        seq = np.array(state.baseline_buffer[-(SEQUENCE_LENGTH + 1):-1])
        actual = state.baseline_buffer[-1]

        score, per_feature = state.model.compute_anomaly_score(
            seq.reshape(1, SEQUENCE_LENGTH, -1), actual,
        )

        state.recent_scores.append(score)
        smoothed = float(np.mean(list(state.recent_scores)))

        # Check for alerts
        alerts = []
        if smoothed > self.anomaly_threshold:
            now = time.time()
            now_iso = datetime.now(timezone.utc).isoformat()
            dt = datetime.fromtimestamp(now, tz=timezone.utc)

            # Find top contributing feature
            from .temporal_data import FEATURE_SPECS
            top_idx = int(np.argmax(per_feature[:len(FEATURE_SPECS)]))
            top_param = FEATURE_SPECS[top_idx][0] if top_idx < len(FEATURE_SPECS) else "unknown"

            # Denormalize for message
            predicted = state.model.forward(seq.reshape(1, SEQUENCE_LENGTH, -1))
            if predicted.ndim > 1:
                predicted = predicted[0]

            key = f"{top_param}:{TemporalAlertCode.TEMPORAL_ANOMALY.value}"
            last = state.last_alert_times.get(key, 0.0)
            if now - last >= self.alert_cooldown:
                alert = TemporalAlertInfo(
                    alert_code=TemporalAlertCode.TEMPORAL_ANOMALY,
                    parameter=top_param,
                    message=(
                        f"{top_param} is unusual for {dt.hour:02d}:{dt.minute:02d} UTC "
                        f"— temporal anomaly score {smoothed:.2f} "
                        f"(load class: {state.load_class.value})"
                    ),
                    anomaly_score=smoothed,
                    expected_value=float(predicted[top_idx]) if top_idx < len(predicted) else 0.0,
                    actual_value=float(actual[top_idx]) if top_idx < len(actual) else 0.0,
                    timestamp=now_iso,
                    device_id=device_id,
                    hour_of_day=dt.hour,
                )
                alerts.append(alert)
                state.last_alert_times[key] = now
                state.active_alerts[key] = alert

        # Clear resolved alerts
        if smoothed <= self.anomaly_threshold * 0.8:
            state.active_alerts.clear()

        return alerts

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _trigger_training(self, state: DeviceTemporalState) -> None:
        """Train TCN on accumulated baseline."""
        device_id = state.device_id
        state.status = "training"

        # Get per-device lock (allows other devices to continue)
        dev_lock = self._get_device_lock(device_id)

        try:
            with dev_lock:
                from .temporal_data import (
                    build_sequences, save_baseline, save_model_metadata,
                    update_temporal_index, SEQUENCE_LENGTH, FEATURE_SPECS,
                )
                from .temporal_training import train_tcn
                from .load_classifier import classify_load
                from .tcn import NumpyTCN

                features = np.array(state.baseline_buffer)
                timestamps = np.array(state.baseline_timestamps)

                # Persist baseline for crash recovery
                save_baseline(device_id, features, timestamps)

                # Classify load type
                pf_idx = next(
                    (i for i, (name, *_) in enumerate(FEATURE_SPECS) if name == "power_factor"),
                    5,
                )
                cur_idx = next(
                    (i for i, (name, *_) in enumerate(FEATURE_SPECS) if name == "current_l1"),
                    1,
                )
                pwr_idx = next(
                    (i for i, (name, *_) in enumerate(FEATURE_SPECS) if name == "active_power"),
                    6,
                )

                # Denormalize for classifier (approx — classifier uses relative metrics)
                pf_vals = features[:, pf_idx].tolist()
                cur_vals = features[:, cur_idx].tolist()
                pwr_vals = features[:, pwr_idx].tolist()
                ts_list = timestamps.tolist()

                load_class, evidence = classify_load(pf_vals, cur_vals, pwr_vals, ts_list)
                state.load_class = load_class

                # Build sequences
                buffer_list = [features[i] for i in range(len(features))]
                sequences, targets = build_sequences(buffer_list, SEQUENCE_LENGTH)

                if len(sequences) < 10:
                    logger.warning("insufficient_sequences device=%s count=%d", device_id, len(sequences))
                    state.status = "accumulating"
                    return

                # Train
                n_features = features.shape[1]
                model = train_tcn(sequences, targets, n_features=n_features, epochs=80)

                # Save model
                _TEMPORAL_DIR = Path(__file__).resolve().parents[3] / "data" / "temporal_models"
                model_path = _TEMPORAL_DIR / device_id / "model.npz"
                model.save(model_path)

                # Save metadata
                now_iso = datetime.now(timezone.utc).isoformat()
                save_model_metadata(device_id, {
                    "load_class": load_class.value,
                    "load_evidence": evidence,
                    "model_version": 1,
                    "trained_at": now_iso,
                    "baseline_samples": len(features),
                    "sequences_trained": len(sequences),
                    "threshold_97": model.threshold_97,
                    "n_features": n_features,
                })

                update_temporal_index(
                    device_id,
                    model_version=1,
                    load_class=load_class.value,
                    trained_at=now_iso,
                    samples=len(features),
                    threshold_97=model.threshold_97,
                )

                state.model = model
                state.model_version = 1
                state.last_trained_ts = time.time()
                state.status = "active"

                logger.info(
                    "temporal_model_trained device=%s load_class=%s samples=%d threshold=%.6f",
                    device_id, load_class.value, len(features), model.threshold_97,
                )

        except Exception:
            logger.exception("temporal_training_failed device=%s", device_id)
            state.status = "accumulating"

    def trigger_retrain(self, device_id: str) -> dict:
        """Manually trigger retraining for a device with an active model."""
        with self._lock:
            state = self._devices.get(device_id)
        if state is None:
            return {"error": "device_not_found"}
        if state.model is None and state.status != "active":
            return {"error": "no_active_model"}

        old_version = state.model_version
        state.status = "retraining"

        dev_lock = self._get_device_lock(device_id)
        try:
            with dev_lock:
                from .temporal_data import (
                    build_sequences, save_model_metadata,
                    update_temporal_index, SEQUENCE_LENGTH,
                )
                from .temporal_training import train_tcn

                features = np.array(state.baseline_buffer)
                buffer_list = [features[i] for i in range(len(features))]
                sequences, targets = build_sequences(buffer_list, SEQUENCE_LENGTH)

                if len(sequences) < 10:
                    state.status = "active"
                    return {"error": "insufficient_data"}

                n_features = features.shape[1]
                model = train_tcn(sequences, targets, n_features=n_features, epochs=80)

                # Backup old model
                _TEMPORAL_DIR = Path(__file__).resolve().parents[3] / "data" / "temporal_models"
                model_dir = _TEMPORAL_DIR / device_id
                old_path = model_dir / "model.npz"
                if old_path.exists():
                    backup = model_dir / f"model_v{old_version}.npz"
                    old_path.rename(backup)

                model.save(model_dir / "model.npz")

                new_version = old_version + 1
                now_iso = datetime.now(timezone.utc).isoformat()
                save_model_metadata(device_id, {
                    "load_class": state.load_class.value,
                    "model_version": new_version,
                    "retrained_at": now_iso,
                    "baseline_samples": len(features),
                    "sequences_trained": len(sequences),
                    "threshold_97": model.threshold_97,
                    "n_features": n_features,
                })
                update_temporal_index(
                    device_id,
                    model_version=new_version,
                    retrained_at=now_iso,
                    threshold_97=model.threshold_97,
                )

                state.model = model
                state.model_version = new_version
                state.last_trained_ts = time.time()
                state.status = "active"
                state.recent_scores.clear()

                logger.info(
                    "temporal_model_retrained device=%s v%d→v%d threshold=%.6f",
                    device_id, old_version, new_version, model.threshold_97,
                )

                return {
                    "device_id": device_id,
                    "old_version": old_version,
                    "new_version": new_version,
                    "threshold_97": model.threshold_97,
                    "sequences_trained": len(sequences),
                }

        except Exception:
            logger.exception("temporal_retrain_failed device=%s", device_id)
            state.status = "active"
            return {"error": "training_failed"}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self, device_id: str) -> TemporalModelStatus | None:
        with self._lock:
            state = self._devices.get(device_id)
        if state is None:
            return None
        return TemporalModelStatus(
            device_id=state.device_id,
            model_status=state.status,
            load_class=state.load_class,
            samples_collected=len(state.baseline_buffer),
            samples_needed=state.samples_needed,
            model_version=state.model_version,
            last_trained=datetime.fromtimestamp(
                state.last_trained_ts, tz=timezone.utc,
            ).isoformat() if state.last_trained_ts > 0 else "",
            anomaly_threshold=self.anomaly_threshold,
            recent_scores=list(state.recent_scores),
        )

    def get_all_statuses(self) -> list[TemporalModelStatus]:
        with self._lock:
            device_ids = list(self._devices.keys())
        return [s for did in device_ids if (s := self.get_status(did)) is not None]

    def remove_device(self, device_id: str) -> None:
        with self._lock:
            self._devices.pop(device_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, device_id: str) -> DeviceTemporalState:
        """Get or create device state. Must be called within self._lock."""
        state = self._devices.get(device_id)
        if state is None:
            state = DeviceTemporalState(
                device_id=device_id,
                samples_needed=self.baseline_samples,
            )
            self._devices[device_id] = state
        return state

    def _get_device_lock(self, device_id: str) -> threading.Lock:
        with self._lock:
            if device_id not in self._device_locks:
                self._device_locks[device_id] = threading.Lock()
            return self._device_locks[device_id]

    def _startup_load(self) -> None:
        """On init: scan temporal_models/ dir, load persisted models."""
        from .temporal_data import _TEMPORAL_DIR, load_model_metadata, load_baseline

        if not _TEMPORAL_DIR.exists():
            return

        for d in _TEMPORAL_DIR.iterdir():
            if not d.is_dir() or d.name == "__pycache__":
                continue
            device_id = d.name
            meta = load_model_metadata(device_id)
            model_path = d / "model.npz"

            state = DeviceTemporalState(
                device_id=device_id,
                samples_needed=self.baseline_samples,
            )

            if model_path.exists() and meta:
                try:
                    from .tcn import NumpyTCN
                    state.model = NumpyTCN.load(model_path)
                    state.status = "active"
                    state.model_version = meta.get("model_version", 1)
                    state.load_class = LoadClass(meta.get("load_class", "unknown"))
                    logger.info("loaded_temporal_model device=%s v%d", device_id, state.model_version)
                except Exception:
                    logger.exception("failed_load_temporal device=%s", device_id)

            # Try to restore baseline buffer
            baseline = load_baseline(device_id)
            if baseline is not None:
                features, timestamps = baseline
                state.baseline_buffer = [features[i] for i in range(len(features))]
                state.baseline_timestamps = timestamps.tolist()

            self._devices[device_id] = state
