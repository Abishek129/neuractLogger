# mypy: ignore-errors
"""Background monitoring thread for Layer 3 prediction.

Follows the daemon-thread pattern used by ``Store._reconnect_loop`` and
``jobs._run_job_loop``: a daemon thread with a ``threading.Event`` for
graceful shutdown.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("loggerfast.ai.prediction.background")

_monitor_thread: Optional[threading.Thread] = None
_monitor_stop: Optional[threading.Event] = None
_started = False
_start_lock = threading.Lock()

DEFAULT_POLL_INTERVAL_S = 60.0  # sample every 60 seconds


def start_prediction_monitor(
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Start the prediction background monitor.  Idempotent."""
    global _monitor_thread, _monitor_stop, _started
    with _start_lock:
        if _started:
            return
        _started = True
    _monitor_stop = threading.Event()
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(poll_interval_s, _monitor_stop),
        name="prediction-monitor",
        daemon=True,
    )
    _monitor_thread.start()
    logger.info(
        "prediction_monitor_started interval_s=%.1f", poll_interval_s,
    )


def stop_prediction_monitor() -> None:
    """Gracefully stop the prediction background monitor."""
    global _started
    with _start_lock:
        if not _started:
            return
        _started = False
    if _monitor_stop:
        _monitor_stop.set()
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=5.0)
    logger.info("prediction_monitor_stopped")


# ------------------------------------------------------------------
# Internal loop
# ------------------------------------------------------------------


def _monitor_loop(
    poll_interval_s: float,
    stop_event: threading.Event,
) -> None:
    """Main background loop.  Reads from running jobs, feeds PredictionManager."""
    from .monitor import PredictionManager

    manager = PredictionManager.instance()

    while not stop_event.is_set():
        try:
            _poll_once(manager)
        except Exception:
            logger.exception("prediction_poll_error")
        stop_event.wait(timeout=poll_interval_s)


def _poll_once(manager) -> None:  # noqa: ANN001
    """Single polling iteration: read all running jobs' tables, feed manager."""
    # Lazy imports to avoid circular dependencies at module load time
    from ...store import Store
    from ...routers.jobs import _read_mapping_values, _job_threads

    store = Store.instance()

    for job in store.list_jobs():
        job_id = job.get("id")
        if not job_id:
            continue
        thr = _job_threads.get(job_id)
        if not thr or not thr.is_alive():
            continue  # job not running

        for table_id in job.get("tables") or []:
            try:
                mapping = store.get_mapping(table_id)
                if not mapping:
                    continue
                device_id = mapping.get("deviceId")
                if not device_id:
                    continue

                values = _read_mapping_values(table_id, job_id=job_id)
                if not isinstance(values, dict) or not values:
                    continue

                new_alerts = manager.feed(device_id, table_id, values)

                for alert in new_alerts:
                    _fire_notification(alert)

            except Exception:
                logger.debug(
                    "prediction_read_failed table=%s", table_id,
                    exc_info=True,
                )

    # ── Check temporal model retraining schedule (Phase 3B) ──
    try:
        from .temporal_scheduler import check_retrain_schedule
        from .temporal_monitor import TemporalManager
        retrained = check_retrain_schedule(TemporalManager.instance())
        if retrained:
            logger.info("temporal_retrain_complete devices=%s", retrained)
    except ImportError:
        pass
    except Exception:
        logger.debug("temporal_retrain_check_error", exc_info=True)


# Alert deduplication — prevent firing identical alerts within cooldown window
_recent_alert_hashes: dict[str, float] = {}
_ALERT_DEDUP_COOLDOWN_S = 300.0  # 5 minutes


def _fire_notification(alert) -> None:  # noqa: ANN001
    """Create a notification for a prediction alert via appdb.

    Deduplicates identical alerts within a 5-minute cooldown window.
    """
    import hashlib
    import time

    # Deduplicate by (device_id, alert_code, parameter)
    alert_key = hashlib.md5(
        f"{alert.device_id}:{alert.alert_code.value}:{alert.parameter}".encode()
    ).hexdigest()

    now = time.monotonic()
    last_fired = _recent_alert_hashes.get(alert_key, 0.0)
    if now - last_fired < _ALERT_DEDUP_COOLDOWN_S:
        logger.debug("prediction_alert_deduplicated device=%s code=%s",
                      alert.device_id, alert.alert_code.value)
        return

    try:
        from ...appdb import create_notification

        notif = create_notification(
            "prediction",
            alert.message,
            "system",  # system-generated, not user-specific
        )
        _recent_alert_hashes[alert_key] = now

        # Broadcast to WebSocket via Redis pub/sub
        _broadcast_to_redis(notif)

        logger.info(
            "prediction_alert_fired device=%s code=%s param=%s",
            alert.device_id, alert.alert_code.value, alert.parameter,
        )
    except Exception:
        logger.warning("prediction_notification_failed", exc_info=True)


def _broadcast_to_redis(notif: dict) -> None:
    """Publish notification to Redis for WebSocket delivery."""
    try:
        import json as _json
        import os
        import redis

        url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/3")
        r = redis.from_url(url)
        payload = {
            "type": notif.get("type", "prediction"),
            "action": "create",
            "notification_id": notif.get("id", ""),
            "message": notif.get("message", ""),
            "user": notif.get("user", "system"),
            "read": False,
            "time": notif.get("time", ""),
        }
        r.publish("logger_read", _json.dumps(payload))
        r.close()
    except Exception:
        logger.debug("redis_broadcast_failed", exc_info=True)
