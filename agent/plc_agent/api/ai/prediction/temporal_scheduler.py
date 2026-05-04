# mypy: ignore-errors
"""Retraining schedule — checks which devices need TCN retraining."""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("loggerfast.ai.prediction.temporal_scheduler")


def check_retrain_schedule(manager: "TemporalManager") -> list[str]:
    """Check which devices need retraining. Called from background thread.

    Returns list of device_ids that were retrained.
    """
    retrained = []
    now = time.time()

    for status in manager.get_all_statuses():
        if status.model_status != "active":
            continue
        if status.model_version < 1:
            continue

        device_state = manager._devices.get(status.device_id)
        if device_state is None:
            continue

        age = now - device_state.last_trained_ts
        if age < manager.retrain_interval:
            continue

        # Check enough new data since last training
        if device_state.samples_needed > 0 and len(device_state.baseline_buffer) < device_state.samples_needed:
            continue

        try:
            logger.info("retrain_trigger device=%s age_days=%.1f", status.device_id, age / 86400)
            manager.trigger_retrain(status.device_id)
            retrained.append(status.device_id)
        except Exception:
            logger.exception("retrain_failed device=%s", status.device_id)

    return retrained
