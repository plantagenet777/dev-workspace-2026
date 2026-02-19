"""MQTT client and telemetry analysis pipeline: universal pump predictive maintenance engine."""
import json
import logging
import os
import ssl
import threading
import time
from collections import deque
from typing import Any

import paho.mqtt.client as mqtt

from config.config import Config
from config.validation import ConfigValidationError, validate_artifacts, validate_config
from app.data_processor import DataProcessor
from app.predictor import PumpPredictor
from app.notifier import send_telegram_alert
from app.logger import setup_logging
from app.csv_logger import append_alert

logger = logging.getLogger("pump_engine")

# Status display for logs and alerts (predictor returns raw status; we add labels)
STATUS_DISPLAY = {
    "CRITICAL": "🚨 CRITICAL",
    "WARNING": "⚠️ WARNING",
    "HEALTHY": "✅ HEALTHY",
    "ERROR": "❌ ERROR",
    "UNKNOWN (No Model)": "❌ UNKNOWN (No Model)",
}


def _status_display(status: str) -> str:
    """Return human-readable status with label for logs and notifications."""
    return STATUS_DISPLAY.get(status, status)


def _predict_with_retry(
    predictor: Any,
    features: Any,
    max_attempts: int,
    base_delay_sec: float,
    is_startup: bool = False,
    latest_telemetry: dict[str, Any] | None = None,
    iso_vib_rms: float | None = None,
) -> tuple[str, float]:
    """Call predictor.predict with retry on ERROR (transient inference failure)."""
    status, prob = predictor.predict(
        features,
        is_startup=is_startup,
        latest_telemetry=latest_telemetry,
        iso_vib_rms=iso_vib_rms,
    )
    attempt = 1
    while status == "ERROR" and attempt < max_attempts:
        time.sleep(base_delay_sec * (2 ** (attempt - 1)))
        status, prob = predictor.predict(
            features,
            is_startup=is_startup,
            latest_telemetry=latest_telemetry,
            iso_vib_rms=iso_vib_rms,
        )
        attempt += 1
    return status, prob


class PumpReliabilityEngine:
    """Predictive maintenance engine: MQTT subscription, telemetry buffer, inference pipeline, alerts."""

    def __init__(self) -> None:
        setup_logging()
        try:
            validate_config()
        except ConfigValidationError as e:
            logger.critical("Config validation failed: %s", e)
            raise
        # Optional strict artifact check: when enabled via STRICT_ARTIFACT_CHECK,
        # missing model/scaler will cause a startup failure instead of soft UNKNOWN status.
        strict_artifacts = os.getenv("STRICT_ARTIFACT_CHECK", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        if strict_artifacts:
            try:
                validate_artifacts()
            except ConfigValidationError as e:
                logger.critical("Artifact validation failed: %s", e)
                raise
        logger.info(Config.get_info())

        # 1. Components (processor expects batch of FEATURE_WINDOW_SIZE records)
        self.processor = DataProcessor(window_size=Config.FEATURE_WINDOW_SIZE)
        self.predictor = PumpPredictor()

        # 2. Telemetry buffer: last FEATURE_WINDOW_SIZE records for stable metrics
        self.buffer = deque(maxlen=Config.FEATURE_WINDOW_SIZE)
        self.messages_since_run = 0  # trigger pipeline every MQTT_BATCH_SIZE messages
        self._inference_count = 0  # used for startup/transient suppression of CRITICAL

        # 3. MQTT resilience
        self._last_message_time: float = time.time()
        self._reconnect_delay: float = getattr(
            Config, "MQTT_RECONNECT_BACKOFF_BASE_SEC", 1.0
        )
        self._disconnect_alert_sent = False
        self._reconnect_lock = threading.Lock()
        self._stop_reconnect = threading.Event()
        self._reconnect_thread: threading.Thread | None = None

        # 4. MQTT client setup
        self.client = mqtt.Client(client_id=Config.PUMP_ID, clean_session=False)
        self.setup_security()

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def setup_security(self) -> None:
        """Configure TLS v1.2 for MQTT (or skip when MQTT_USE_TLS=false)."""
        if not Config.MQTT_USE_TLS:
            logger.warning("TLS disabled (MQTT_USE_TLS=false) — local dev mode")
            return
        try:
            self.client.tls_set(
                ca_certs=Config.CA_CERT,
                certfile=Config.CLIENT_CERT,
                keyfile=Config.CLIENT_KEY,
                tls_version=ssl.PROTOCOL_TLSv1_2,
            )
            # In production use False; True disables hostname verification (dev/test only).
            self.client.tls_insecure_set(Config.MQTT_TLS_INSECURE)
        except Exception as e:
            logger.critical("Security Config Error: %s", e)
            raise RuntimeError(f"Security configuration failed: {e}") from e

    def on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        """MQTT broker connection callback."""
        if rc == 0:
            self._reconnect_delay = getattr(
                Config, "MQTT_RECONNECT_BACKOFF_BASE_SEC", 1.0
            )
            self._disconnect_alert_sent = False
            mode = "Secure" if Config.MQTT_USE_TLS else "Plain"
            logger.info("Connected to %s Broker: %s", mode, Config.MQTT_BROKER)
            self.client.subscribe(Config.TOPIC_TELEMETRY, qos=1)
        else:
            logger.error("Connection failed. Code: %s", rc)

    def on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        """MQTT broker disconnection callback; start reconnection with backoff."""
        logger.warning(
            "Disconnected from broker (rc=%s). Reconnecting with backoff...", rc
        )
        with self._reconnect_lock:
            if self._reconnect_thread is None or not self._reconnect_thread.is_alive():
                self._reconnect_thread = threading.Thread(
                    target=self._reconnect_loop, daemon=True
                )
                self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Reconnect to broker with exponential backoff."""
        max_backoff = getattr(Config, "MQTT_RECONNECT_MAX_BACKOFF_SEC", 60.0)
        while not self._stop_reconnect.is_set():
            time.sleep(self._reconnect_delay)
            try:
                self.client.reconnect()
                logger.info("Reconnected to broker.")
                return
            except Exception as e:
                logger.warning(
                    "Reconnect failed: %s. Retry in %.1fs.", e, self._reconnect_delay
                )
                self._reconnect_delay = min(self._reconnect_delay * 2, max_backoff)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Incoming MQTT message handler: append to buffer and run pipeline on trigger."""
        self._last_message_time = time.time()
        try:
            raw_payload = (
                msg.payload.decode("utf-8")
                if isinstance(getattr(msg, "payload", b""), (bytes, bytearray))
                else str(getattr(msg, "payload", ""))
            )
            payload = json.loads(raw_payload)
            self.buffer.append(payload)
            self.messages_since_run += 1

            # Run pipeline when buffer full (FEATURE_WINDOW_SIZE) and MQTT_BATCH_SIZE messages received
            if (
                len(self.buffer) >= Config.FEATURE_WINDOW_SIZE
                and self.messages_since_run >= Config.MQTT_BATCH_SIZE
            ):
                self.run_analysis_pipeline()
                self.messages_since_run = 0

        except json.JSONDecodeError as e:
            logger.error(
                "JSON decode error on topic %s: %s; payload=%r",
                getattr(msg, "topic", "?"),
                e,
                getattr(msg, "payload", b""),
            )
        except Exception as e:
            logger.error(
                "Error processing message on topic %s: %s; payload=%r",
                getattr(msg, "topic", "?"),
                e,
                getattr(msg, "payload", b""),
            )

    def run_analysis_pipeline(self) -> None:
        """Pipeline: prepare batch, run inference, publish report, send alerts when needed."""

        # 1. Prepare batch and sensor health check
        features, sensor_status, iso_vib_rms = self.processor.prepare_batch(self.buffer)

        if features is None:
            self.publish_report({"status": "OFFLINE", "reason": sensor_status})
            return

        # 2. Inference with retry on transient failure; suppress CRITICAL during startup
        is_startup = self._inference_count < Config.STARTUP_ITERATIONS
        latest_telemetry = self.buffer[-1] if self.buffer else None
        status, prob = _predict_with_retry(
            self.predictor,
            features,
            max_attempts=Config.INFERENCE_RETRY_ATTEMPTS,
            base_delay_sec=Config.INFERENCE_RETRY_DELAY_SEC,
            is_startup=is_startup,
            latest_telemetry=latest_telemetry,
            iso_vib_rms=iso_vib_rms,
        )
        self._inference_count += 1

        # 3. Build report
        report = {
            "pump_id": Config.PUMP_ID,
            "status": status,
            "anomaly_probability": prob,
            "sensor_health": sensor_status,
            "timestamp": time.ctime(),
        }

        # 4. Publish to MQTT
        self.publish_report(report)

        # 5. On CRITICAL/WARNING: queue alert for CSV (retry in background) and send Telegram
        if status in ["CRITICAL", "WARNING"]:
            append_alert(
                report["timestamp"], Config.PUMP_ID, status, prob, sensor_status
            )
            alert_msg = f"Pump: {Config.PUMP_ID}\nStatus: {_status_display(status)}\nProb: {prob}\nSensors: {sensor_status}"
            reason = getattr(self.predictor, "last_alert_reason", None)
            if reason:
                alert_msg += f"\n\n{reason}"
                logger.warning("ALERT REASON: %s", reason)
            # Include structured alarm causes (if available) for richer operator context
            alarm_causes = getattr(self.predictor, "last_alarm_causes", []) or []
            if alarm_causes:
                unique_causes = sorted(set(alarm_causes))
                alert_msg += "\nCauses: " + ", ".join(unique_causes)
            send_telegram_alert(alert_msg)
            logger.warning("ALERT SENT: %s (%.3f)", _status_display(status), prob)

    def publish_report(self, report: dict[str, Any]) -> None:
        """Publish report to MQTT alerts topic."""
        self.client.publish(Config.TOPIC_ALERTS, json.dumps(report), qos=1)

    def _prolonged_disconnect_check(self) -> None:
        """Alert once if no telemetry received for MQTT_DISCONNECT_ALERT_SEC."""
        if self._disconnect_alert_sent:
            return
        alert_sec = getattr(Config, "MQTT_DISCONNECT_ALERT_SEC", 90)
        if time.time() - self._last_message_time >= alert_sec:
            self._disconnect_alert_sent = True
            msg = (
                f"Pump {Config.PUMP_ID}: No telemetry for {alert_sec}s. "
                "Check broker and publishers."
            )
            logger.warning(msg)
            send_telegram_alert(msg)

    def start(self) -> None:
        """Connect to broker and run message loop with reconnect and disconnect alert."""
        try:
            logger.info("Starting Monitor Engine for %s...", Config.PUMP_ID)
            self.client.connect(
                Config.MQTT_BROKER, Config.MQTT_PORT, Config.MQTT_KEEPALIVE
            )
            # Run loop in a thread so we can run prolonged-disconnect checker
            self.client.loop_start()
            alert_sec = getattr(Config, "MQTT_DISCONNECT_ALERT_SEC", 90)
            check_interval = max(30, alert_sec // 3)
            while True:
                time.sleep(check_interval)
                self._prolonged_disconnect_check()
        except KeyboardInterrupt:
            logger.info("Stopping engine...")
            self._stop_reconnect.set()
            self.client.disconnect()
            self.client.loop_stop()


if __name__ == "__main__":
    engine = PumpReliabilityEngine()
    engine.start()
