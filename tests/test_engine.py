import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.main_app as main_app


@pytest.fixture
def engine(monkeypatch):
    """Create PumpReliabilityEngine with mocked MQTT client and safe config."""

    # Ensure TLS is disabled for tests unless explicitly enabled (via env)
    monkeypatch.setenv("MQTT_USE_TLS", "false")

    mock_client = MagicMock()
    with patch.object(main_app.mqtt, "Client", return_value=mock_client):
        eng = main_app.PumpReliabilityEngine()
    return eng


def _make_msg(payload: dict, topic: str = "test/topic") -> SimpleNamespace:
    return SimpleNamespace(
        payload=json.dumps(payload).encode("utf-8"),
        topic=topic,
    )


def test_on_message_triggers_pipeline_when_buffer_and_batch_full(engine, monkeypatch):
    """on_message should buffer messages and call run_analysis_pipeline at the right cadence."""
    # Use small window / batch for fast test
    monkeypatch.setattr(main_app.Config, "FEATURE_WINDOW_SIZE", 2, raising=False)
    monkeypatch.setattr(main_app.Config, "MQTT_BATCH_SIZE", 2, raising=False)

    # Recreate engine with updated config
    with patch.object(main_app.mqtt, "Client", return_value=MagicMock()):
        engine = main_app.PumpReliabilityEngine()

    engine.run_analysis_pipeline = MagicMock()

    payload = {
        "vib_rms": 2.5,
        "vib_crest": 3.0,
        "vib_kurtosis": 3.2,
        "current": 45.0,
        "pressure": 6.0,
        "temp": 38.0,
        "cavitation_index": 0.05,
    }

    # First message: buffer not yet full
    engine.on_message(engine.client, None, _make_msg(payload))
    assert len(engine.buffer) == 1
    assert engine.messages_since_run == 1
    engine.run_analysis_pipeline.assert_not_called()

    # Second message: buffer full and MQTT_BATCH_SIZE reached -> pipeline runs
    engine.on_message(engine.client, None, _make_msg(payload))
    assert len(engine.buffer) == 2
    engine.run_analysis_pipeline.assert_called_once()
    assert engine.messages_since_run == 0


def test_run_analysis_pipeline_publishes_offline_on_invalid_batch(engine, monkeypatch):
    """When prepare_batch returns no features, engine should publish OFFLINE status."""
    engine.processor.prepare_batch = MagicMock(
        return_value=(None, "MISSING_COLUMNS:vib_crest", None)
    )
    published = {}

    def capture_report(report: dict):
        published.update(report)

    engine.publish_report = capture_report

    # Buffer content is irrelevant; prepare_batch is mocked
    engine.buffer.clear()
    engine.buffer.append({"vib_rms": 1.0})

    engine.run_analysis_pipeline()

    assert published.get("status") == "OFFLINE"
    assert "MISSING_COLUMNS" in published.get("reason", "")


def test_prolonged_disconnect_sends_alert_once(engine, monkeypatch):
    """_prolonged_disconnect_check should send a Telegram alert only once after timeout."""
    alert_calls = []

    def fake_send(msg: str):
        alert_calls.append(msg)

    monkeypatch.setattr(main_app, "send_telegram_alert", fake_send)
    monkeypatch.setattr(main_app.Config, "MQTT_DISCONNECT_ALERT_SEC", 1, raising=False)

    # Simulate last message far in the past
    engine._last_message_time -= 5
    engine._disconnect_alert_sent = False

    engine._prolonged_disconnect_check()
    assert len(alert_calls) == 1
    assert "No telemetry" in alert_calls[0]

    # Second check should be a no-op
    engine._prolonged_disconnect_check()
    assert len(alert_calls) == 1
