"""Random Forest inference and risk smoothing for alerts."""
import logging
import os
from collections import deque
from datetime import datetime
from typing import Any

import joblib
import numpy as np
import pandas as pd

from config.config import Config
from config.utils import config_float
from app.csv_logger import append_telemetry
import app.rules as rules_module

logger = logging.getLogger("pump_engine")


def _is_healthy_nominal(
    vib_rms: float, pressure: float, temp: float, current: float
) -> bool:
    """True if sample is in nominal healthy zone per Operating Instruction (e.g. after pump restart)."""
    # Healthy: vib 2.8–4.5, current 44–48 A, pressure 5.5–6.0 bar, temp 42–55°C (use margins).
    temp_warning = config_float(Config, "TEMP_WARNING_C", 60.0)
    overload_amp = config_float(Config, "OVERLOAD_CURRENT_MIN_AMP", 50.0)
    low_p_bar = config_float(Config, "DEGRADATION_PRESSURE_MAX_BAR", 5.2)
    vib_warning = config_float(
        Config, "VIBRATION_WARNING_MMPS", 4.5
    )  # ISO 10816-3 Zone B/C
    choked_p = config_float(Config, "CHOKED_PRESSURE_MIN_BAR", 7.0)
    deg_current = config_float(Config, "DEGRADATION_CURRENT_MAX_AMP", 40.0)
    return (
        vib_rms < vib_warning
        and pressure >= low_p_bar
        and pressure < choked_p
        and temp < temp_warning
        and temp >= 35.0
        and current > deg_current
        and current < overload_amp
    )


class PumpPredictor:
    """Load model and scaler; run inference with asymmetric risk smoothing."""

    def __init__(self) -> None:
        self.model: Any = None
        self.scaler: Any = None
        self.feature_names = Config.FEATURE_NAMES
        self.risk_history: deque = deque(maxlen=Config.RISK_HISTORY_SIZE)
        self.smoothed_risk: float | None = None
        self._feature_buffer: deque = deque(maxlen=Config.SMOOTHING_WINDOW_SIZE)
        # Alert / trip metadata for downstream consumers (simulator, notifier, etc.)
        self.last_alert_reason: str | None = (
            None  # e.g. cavitation / choked / overtemp message for notifications
        )
        self.last_trip_cause: str | None = (
            None  # e.g. "CAVITATION", "CHOKED_DISCHARGE", "VIB_INTERLOCK", "OVERTEMP"
        )
        self.last_alarm_causes: list[
            str
        ] = []  # All active alarm-level cause codes for the last step
        self._last_status: str | None = (
            None  # for hysteresis (avoid WARNING/CRITICAL flicker)
        )
        self._critical_low_vib_steps: int = (
            0  # consecutive steps with low vib before allowing CRITICAL -> WARNING
        )
        self._load_artifacts()
        # Ensure rules module uses the same Config (including when mocked in tests)
        rules_module.Config = Config

    def reset_smoothing(self) -> None:
        """Clear smoothing state (risk history and feature buffer). Call after maintenance or reset."""
        self.risk_history.clear()
        self.smoothed_risk = None
        self._feature_buffer.clear()
        self._last_status = None
        self._critical_low_vib_steps = 0

    def _load_artifacts(self) -> None:
        try:
            self.model = joblib.load(Config.MODEL_PATH)
            self.scaler = joblib.load(Config.SCALER_PATH)
            logger.info("Predictor: Model and Scaler artifacts loaded successfully.")
        except Exception as e:
            logger.error(f"Predictor Load Error: {e}")

    def _log_to_csv(self, features_df: pd.DataFrame, risk: float, status: str) -> None:
        """Queue telemetry row for telemetry_history.csv (retry in background)."""
        try:
            row_data = features_df.iloc[0].to_dict()
            for k in self.feature_names:
                if k in row_data and isinstance(row_data[k], (int, float)):
                    row_data[k] = round(float(row_data[k]), 4)
            row_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row_data["risk_score"] = round(risk, 4)
            row_data["status"] = status
            fieldnames = ["timestamp", "risk_score", "status"] + self.feature_names
            append_telemetry(fieldnames, row_data)
        except Exception as e:
            logger.error("CSV Logging Error: %s", e)

    def predict(
        self,
        features: np.ndarray | pd.DataFrame,
        is_startup: bool = False,
        latest_telemetry: dict | None = None,
        iso_vib_rms: float | None = None,
    ) -> tuple[str, float]:
        """Predict status (CRITICAL/WARNING/HEALTHY) and smoothed anomaly probability.

        Uses a rolling average of the last SMOOTHING_WINDOW_SIZE feature vectors to
        reduce jitter. During startup (is_startup=True) a higher threshold is used
        for CRITICAL to avoid false positives from transient states.
        When latest_telemetry is provided, critical checks (choked, cavitation) use
        the actual last sample so we react in the same step, not after the batch mean crosses the threshold.
        When iso_vib_rms is provided (USE_ISO_BAND_FOR_ZONES), zone and shutdown decisions use
        RMS in the 10–1000 Hz band instead of overall RMS.

        Args:
            features: Feature vector (1, n_features) or DataFrame with FEATURE_NAMES columns.
            is_startup: If True, use PROB_CRITICAL_STARTUP for CRITICAL instead of PROB_CRITICAL.
            latest_telemetry: Optional last raw MQTT payload (current, pressure, temp, vib_rms, vib_crest).
            iso_vib_rms: Optional RMS in 10–1000 Hz band (mm/s) for zone/shutdown when USE_ISO_BAND_FOR_ZONES.

        Returns:
            Tuple (status, probability). On error or missing model: ("ERROR", 0.0) or ("UNKNOWN (No Model)", 0.0).
        """
        if self.model is None or self.scaler is None:
            return "UNKNOWN (No Model)", 0.0

        try:
            features_df = self._build_features_df(features)

            (
                smoothed_df,
                display_prob,
                status,
                vib_rms,
                vib_crest,
                current,
                pressure,
                temp,
                latest_vib,
                latest_crest,
                latest_current,
                latest_pressure,
                latest_temp,
                smoothed_prob,
            ) = self._update_smoothing_and_status(
                features_df,
                is_startup=is_startup,
                latest_telemetry=latest_telemetry,
                iso_vib_rms=iso_vib_rms,
            )

            prev_alert_reason = self.last_alert_reason
            # Clear per-step metadata; rules will fill them if any condition applies
            self.last_alert_reason = None
            self.last_trip_cause = None
            self.last_alarm_causes = []

            ctx = rules_module.RuleContext(
                vib_rms=vib_rms,
                vib_crest=vib_crest,
                current=current,
                pressure=pressure,
                temp=temp,
                latest_vib=latest_vib,
                latest_crest=latest_crest,
                latest_current=latest_current,
                latest_pressure=latest_pressure,
                latest_temp=latest_temp,
                smoothed_prob=smoothed_prob,
                prev_reason=prev_alert_reason,
                last_status=self._last_status,
                debris_flag=bool(
                    latest_telemetry and latest_telemetry.get("debris_impact")
                ),
                status=status,
                reason=None,
                display_prob=display_prob,
                critical_low_vib_steps=self._critical_low_vib_steps,
            )
            for rule in rules_module.RULES:
                rule.evaluate(ctx)
            status = ctx.status
            self.last_alert_reason = ctx.reason
            # Trip / alarm metadata (may be used by simulator / notifier / tests)
            raw_trip_cause = getattr(ctx, "trip_cause", None)
            alarm_causes = getattr(ctx, "alarm_causes", [])
            # Make a shallow copy so downstream mutation does not affect RuleContext
            self.last_alarm_causes = (
                list(alarm_causes) if alarm_causes is not None else []
            )
            # Use trip_cause exactly as set by rules (no extra selection layer)
            self.last_trip_cause = raw_trip_cause
            display_prob = ctx.display_prob
            self._critical_low_vib_steps = ctx.critical_low_vib_steps
            self._last_status = status
            self._log_to_csv(features_df, round(display_prob, 3), status)
            return status, round(display_prob, 3)

        except Exception as e:
            logger.error(f"Inference Error: {e}")
            return "ERROR", 0.0

    def _build_features_df(self, features: np.ndarray | pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with FEATURE_NAMES from raw features input."""
        if isinstance(features, np.ndarray):
            return pd.DataFrame(features, columns=self.feature_names)
        return features[self.feature_names].copy()

    def _update_smoothing_and_status(
        self,
        features_df: pd.DataFrame,
        *,
        is_startup: bool,
        latest_telemetry: dict | None,
        iso_vib_rms: float | None,
    ) -> tuple[
        pd.DataFrame,
        float,
        str,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
    ]:
        """Update smoothing state and derive status and display probability."""
        # Latest sample (for recovery detection before using buffer)
        latest_vib_early = float(features_df["vib_rms"].iloc[0])
        latest_current_early = float(features_df["current"].iloc[0])
        latest_pressure_early = float(features_df["pressure"].iloc[0])
        latest_temp_early = float(features_df["temp"].iloc[0])
        if latest_telemetry:
            latest_vib_early = float(latest_telemetry.get("vib_rms", latest_vib_early))
            latest_current_early = float(
                latest_telemetry.get("current", latest_current_early)
            )
            latest_pressure_early = float(
                latest_telemetry.get("pressure", latest_pressure_early)
            )
            latest_temp_early = float(latest_telemetry.get("temp", latest_temp_early))
        if iso_vib_rms is not None:
            latest_vib_early = float(iso_vib_rms)
        # After CRITICAL or WARNING (e.g. shutdown/restart or degradation ended), if telemetry is back in
        # healthy nominal zone, reset smoothing so we don't show WARNING from carried-over risk.
        if self._last_status in ("CRITICAL", "WARNING") and _is_healthy_nominal(
            latest_vib_early,
            latest_pressure_early,
            latest_temp_early,
            latest_current_early,
        ):
            self.reset_smoothing()

        row = features_df.iloc[0].values.reshape(1, -1)
        self._feature_buffer.append(row)
        smoothed_row = np.mean(self._feature_buffer, axis=0).reshape(1, -1)
        smoothed_df = pd.DataFrame(smoothed_row, columns=self.feature_names)

        scaled = self.scaler.transform(smoothed_df)
        proba = self.model.predict_proba(scaled)[0]
        n_classes = len(proba)
        if n_classes == 3:
            # 0=Healthy, 1=Warning, 2=Critical: risk = P(anomaly) = P(1)+P(2)
            instant_prob = float(proba[1] + proba[2])
            p_critical = float(proba[2])
            p_warning = float(proba[1])
        else:
            # Binary: 0=Healthy, 1=Anomaly
            instant_prob = float(proba[1])
            p_critical = instant_prob
            p_warning = instant_prob

        # Asymmetric smoothing: react faster when risk rises, decay faster when falling (exit WARNING sooner)
        if self.smoothed_risk is None:
            self.smoothed_risk = instant_prob
        else:
            high_risk_threshold = config_float(
                Config, "SMOOTH_HIGH_RISK_THRESHOLD", 0.80
            )
            alpha_very_high = config_float(Config, "SMOOTH_ALPHA_VERY_HIGH", 0.92)
            alpha_rising = config_float(Config, "SMOOTH_ALPHA_RISING", 0.7)
            alpha_falling = config_float(Config, "SMOOTH_ALPHA_FALLING", 0.65)
            if (
                instant_prob > self.smoothed_risk
                and instant_prob >= high_risk_threshold
            ):
                alpha = alpha_very_high
            elif instant_prob > self.smoothed_risk:
                alpha = alpha_rising
            else:
                alpha = alpha_falling
            self.smoothed_risk = alpha * instant_prob + (1 - alpha) * self.smoothed_risk

        self.risk_history.append(self.smoothed_risk)
        smoothed_prob = np.mean(self.risk_history)
        # Allow displayed risk to reach 95–100%: scale upper range [0.65, 1.0] -> [0.85, 1.0]
        if smoothed_prob >= 0.65:
            display_prob = min(
                1.0,
                0.85 + (smoothed_prob - 0.65) * (0.15 / 0.35),
            )
        else:
            display_prob = smoothed_prob
        threshold_critical = (
            config_float(Config, "PROB_CRITICAL_STARTUP", 0.9)
            if is_startup
            else config_float(Config, "PROB_CRITICAL", 0.85)
        )
        threshold_warning = config_float(Config, "PROB_WARNING", 0.6)

        # Status from smoothed risk (model)
        if smoothed_prob >= threshold_critical:
            status = "CRITICAL"
        elif smoothed_prob >= threshold_warning:
            status = "WARNING"
        else:
            status = "HEALTHY"

        vib_rms = (
            float(iso_vib_rms)
            if iso_vib_rms is not None
            else float(smoothed_df["vib_rms"].iloc[0])
        )
        vib_crest = float(smoothed_df["vib_crest"].iloc[0])
        current = float(smoothed_df["current"].iloc[0])
        pressure = float(smoothed_df["pressure"].iloc[0])
        temp = float(smoothed_df["temp"].iloc[0])
        # Latest: use actual last telemetry sample when provided (so choked/cavitation react same step)
        latest_vib = (
            float(iso_vib_rms)
            if iso_vib_rms is not None
            else float(features_df["vib_rms"].iloc[0])
        )
        latest_crest = float(features_df["vib_crest"].iloc[0])
        latest_current = float(features_df["current"].iloc[0])
        latest_pressure = float(features_df["pressure"].iloc[0])
        latest_temp = float(features_df["temp"].iloc[0])
        if latest_telemetry and iso_vib_rms is None:
            latest_vib = float(latest_telemetry.get("vib_rms", latest_vib))
            latest_crest = float(latest_telemetry.get("vib_crest", latest_crest))
            latest_current = float(latest_telemetry.get("current", latest_current))
            latest_pressure = float(latest_telemetry.get("pressure", latest_pressure))
            latest_temp = float(latest_telemetry.get("temp", latest_temp))

        return (
            smoothed_df,
            display_prob,
            status,
            vib_rms,
            vib_crest,
            current,
            pressure,
            temp,
            latest_vib,
            latest_crest,
            latest_current,
            latest_pressure,
            latest_temp,
            float(smoothed_prob),
        )
