# mypy: ignore-errors
"""PredictionManager — singleton coordinating per-device statistical monitoring."""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import stats
from .types import (
    AlertCode,
    AlertInfo,
    BaselineStatus,
    DeviceBaseline,
    ParameterState,
    PredictionStatus,
    TrendInfo,
)

logger = logging.getLogger("loggerfast.ai.prediction")


class PredictionManager:
    """Thread-safe singleton that tracks per-device statistical baselines."""

    _instance: Optional["PredictionManager"] = None
    _class_lock = threading.Lock()

    # ── configurable defaults ──
    DEFAULT_WINDOW_SIZE = 120               # readings in rolling window
    DEFAULT_SIGMA_THRESHOLD = 2.0           # z-score for deviation alert
    DEFAULT_DRIFT_SIGMA = 2.5              # z-score for baseline drift
    DEFAULT_TREND_SLOPE_THRESHOLD = 0.5    # %/hr to trigger trend alert
    DEFAULT_TREND_R2_THRESHOLD = 0.6       # min R² for trend to be "real"
    DEFAULT_HW_ALPHA = 0.3
    DEFAULT_HW_BETA = 0.1
    DEFAULT_ALERT_COOLDOWN_S = 300         # 5 minutes
    DEFAULT_MIN_WINDOW_FOR_ALERTS = 10     # need >= 10 readings

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: Dict[str, DeviceBaseline] = {}
        # Mutable config
        self.window_size = self.DEFAULT_WINDOW_SIZE
        self.sigma_threshold = self.DEFAULT_SIGMA_THRESHOLD
        self.drift_sigma = self.DEFAULT_DRIFT_SIGMA
        self.trend_slope_threshold = self.DEFAULT_TREND_SLOPE_THRESHOLD
        self.trend_r2_threshold = self.DEFAULT_TREND_R2_THRESHOLD
        self.hw_alpha = self.DEFAULT_HW_ALPHA
        self.hw_beta = self.DEFAULT_HW_BETA
        self.alert_cooldown_s = self.DEFAULT_ALERT_COOLDOWN_S
        self.min_window_for_alerts = self.DEFAULT_MIN_WINDOW_FOR_ALERTS

    @classmethod
    def instance(cls) -> "PredictionManager":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = PredictionManager()
            return cls._instance

    def configure(self, **kwargs: Any) -> None:
        """Update configuration at runtime. Thread-safe."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    # ------------------------------------------------------------------
    # Feed — main ingestion entry point
    # ------------------------------------------------------------------

    # Feed rate limiting: minimum interval per device (seconds)
    _MIN_FEED_INTERVAL_S = 1.0
    _last_feed_time: Dict[str, float] = {}

    def feed(
        self,
        device_id: str,
        table_id: str,
        readings: Dict[str, Any],
    ) -> List[AlertInfo]:
        """Ingest new readings for a device. Returns newly triggered alerts.

        Called by the background thread after each successful device read.
        Only processes numeric (int/float) values; skips None and non-numeric.
        Rate-limited to one reading per second per device to prevent buffer overload.
        """
        now = time.time()

        # Rate limiting — drop excess readings
        last = self._last_feed_time.get(device_id, 0.0)
        if now - last < self._MIN_FEED_INTERVAL_S:
            return []
        self._last_feed_time[device_id] = now

        now_iso = datetime.now(timezone.utc).isoformat()
        new_alerts: List[AlertInfo] = []

        with self._lock:
            baseline = self._devices.get(device_id)
            if baseline is None:
                baseline = DeviceBaseline(
                    device_id=device_id,
                    table_ids=[table_id],
                    monitoring_since=now_iso,
                )
                self._devices[device_id] = baseline
            elif table_id not in baseline.table_ids:
                baseline.table_ids.append(table_id)

            for param_key, raw_value in readings.items():
                if not isinstance(raw_value, (int, float)) or math.isnan(raw_value):
                    continue
                value = float(raw_value)

                # Get or create parameter state
                ps = baseline.params.get(param_key)
                if ps is None:
                    ps = ParameterState()
                    baseline.params[param_key] = ps

                # Append to rolling window
                ps.values.append(value)
                ps.timestamps.append(now)

                # Trim to window_size
                if len(ps.values) > self.window_size:
                    excess = len(ps.values) - self.window_size
                    ps.values = ps.values[excess:]
                    ps.timestamps = ps.timestamps[excess:]

                # Update Holt-Winters
                ps.hw_level, ps.hw_trend = stats.holt_winters_update(
                    ps.hw_level, ps.hw_trend, value,
                    alpha=self.hw_alpha, beta=self.hw_beta,
                    initialized=ps.hw_initialized,
                )
                ps.hw_initialized = True

                # Skip alert checks until enough data
                if len(ps.values) < self.min_window_for_alerts:
                    continue

                # ── Z-score deviation check ──
                # Compare current against window *excluding* current value
                z = stats.z_score(ps.values[:-1], value)
                abs_z = abs(z)

                if abs_z >= self.drift_sigma:
                    alert = self._maybe_alert(
                        baseline, device_id, param_key,
                        AlertCode.BASELINE_DRIFT, abs_z,
                        f"{param_key} baseline drift: {abs_z:.1f}\u03c3 deviation",
                        now, now_iso,
                    )
                    if alert:
                        new_alerts.append(alert)
                elif abs_z >= self.sigma_threshold:
                    alert = self._maybe_alert(
                        baseline, device_id, param_key,
                        AlertCode.DEVIATION, abs_z,
                        f"{param_key} deviation: {abs_z:.1f}\u03c3 from mean",
                        now, now_iso,
                    )
                    if alert:
                        new_alerts.append(alert)

                # ── Trend detection ──
                slope_s, r2 = stats.linear_regression_slope(
                    ps.timestamps, ps.values,
                )
                slope_hr = stats.slope_per_hour(slope_s)
                mean_val = sum(ps.values) / len(ps.values)
                slope_pct_hr = (
                    (slope_hr / abs(mean_val) * 100)
                    if abs(mean_val) > 1e-10
                    else 0.0
                )

                if (
                    abs(slope_pct_hr) >= self.trend_slope_threshold
                    and r2 >= self.trend_r2_threshold
                ):
                    direction = stats.classify_direction(slope_pct_hr)
                    alert = self._maybe_alert(
                        baseline, device_id, param_key,
                        AlertCode.TREND_ALERT, abs_z,
                        f"{param_key} trending {direction} "
                        f"{abs(slope_pct_hr):.1f}%/hr, "
                        f"current deviation {abs_z:.1f}\u03c3",
                        now, now_iso,
                    )
                    if alert:
                        new_alerts.append(alert)

                # ── Clear resolved alerts ──
                if abs_z < self.sigma_threshold:
                    for code in AlertCode:
                        key = f"{param_key}:{code.value}"
                        baseline.active_alerts.pop(key, None)

        # ── Temporal model inference (Phase 3B) ──
        try:
            from .temporal_monitor import TemporalManager
            temporal_alerts = TemporalManager.instance().feed(
                device_id, table_id, readings,
            )
            for ta in temporal_alerts:
                new_alerts.append(AlertInfo(
                    alert_code=AlertCode.TEMPORAL_ANOMALY,
                    parameter=ta.parameter,
                    message=ta.message,
                    sigma=ta.anomaly_score,
                    timestamp=ta.timestamp,
                    device_id=device_id,
                ))
        except ImportError:
            pass
        except Exception:
            logger.debug("temporal_feed_error device=%s", device_id, exc_info=True)

        return new_alerts

    # ------------------------------------------------------------------
    # Alert helpers
    # ------------------------------------------------------------------

    def _maybe_alert(
        self,
        baseline: DeviceBaseline,
        device_id: str,
        param_key: str,
        code: AlertCode,
        sigma: float,
        message: str,
        now: float,
        now_iso: str,
    ) -> Optional[AlertInfo]:
        """Create alert if cooldown has elapsed. Returns AlertInfo or None."""
        key = f"{param_key}:{code.value}"
        last = baseline.last_alert_times.get(key, 0.0)
        if now - last < self.alert_cooldown_s:
            return None  # still in cooldown
        alert = AlertInfo(
            alert_code=code,
            parameter=param_key,
            message=message,
            sigma=sigma,
            timestamp=now_iso,
            device_id=device_id,
        )
        baseline.active_alerts[key] = alert
        baseline.last_alert_times[key] = now
        return alert

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_status(self, device_id: str) -> Optional[PredictionStatus]:
        """Get prediction status for a device. Returns None if not monitored."""
        with self._lock:
            baseline = self._devices.get(device_id)
            if baseline is None:
                return None
            return self._build_status(baseline)

    def get_all_statuses(self) -> List[PredictionStatus]:
        """Get prediction status for all monitored devices."""
        with self._lock:
            return [self._build_status(b) for b in self._devices.values()]

    def remove_device(self, device_id: str) -> None:
        """Stop monitoring a device (e.g. when a job stops)."""
        with self._lock:
            self._devices.pop(device_id, None)

    def device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_status(self, baseline: DeviceBaseline) -> PredictionStatus:
        """Build PredictionStatus from DeviceBaseline. Caller must hold lock."""
        fills: list[float] = []
        deviations: Dict[str, float] = {}
        trends: List[TrendInfo] = []

        for param_key, ps in baseline.params.items():
            fill = (
                (len(ps.values) / self.window_size) * 100
                if self.window_size > 0
                else 100.0
            )
            fills.append(fill)

            # Current z-score
            if len(ps.values) >= 2:
                z = stats.z_score(ps.values[:-1], ps.values[-1])
                deviations[param_key] = z
            else:
                deviations[param_key] = 0.0

            # Trend
            slope_s, r2 = stats.linear_regression_slope(
                ps.timestamps, ps.values,
            )
            slope_hr = stats.slope_per_hour(slope_s)
            mean_val = (
                sum(ps.values) / len(ps.values) if ps.values else 1.0
            )
            slope_pct = (
                (slope_hr / abs(mean_val) * 100)
                if abs(mean_val) > 1e-10
                else 0.0
            )
            direction = stats.classify_direction(slope_pct)
            trends.append(TrendInfo(
                parameter=param_key,
                slope_per_hour=slope_pct,
                direction=direction,
                r_squared=r2,
                window_size=len(ps.values),
                hw_level=ps.hw_level,
                hw_trend=ps.hw_trend,
            ))

        avg_fill = sum(fills) / len(fills) if fills else 0.0
        has_alerts = len(baseline.active_alerts) > 0

        if avg_fill < 100.0:
            status = BaselineStatus.LEARNING
        elif has_alerts:
            status = BaselineStatus.ALERTING
        else:
            status = BaselineStatus.ACTIVE

        return PredictionStatus(
            device_id=baseline.device_id,
            baseline_status=status,
            monitoring_since=baseline.monitoring_since,
            window_fill_pct=avg_fill,
            current_deviations=deviations,
            active_alerts=list(baseline.active_alerts.values()),
            trends=trends,
            config={
                "window_size": self.window_size,
                "sigma_threshold": self.sigma_threshold,
                "drift_sigma": self.drift_sigma,
                "trend_slope_threshold": self.trend_slope_threshold,
                "hw_alpha": self.hw_alpha,
                "hw_beta": self.hw_beta,
                "alert_cooldown_s": self.alert_cooldown_s,
            },
        )
