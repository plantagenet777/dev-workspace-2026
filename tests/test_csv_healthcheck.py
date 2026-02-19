import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.config import Config
from app.csv_logger import append_alert, append_telemetry, get_csv_worker


def test_append_alert_and_telemetry_create_files_with_headers(tmp_path, monkeypatch):
    """append_alert/append_telemetry should create CSV files with headers and append rows."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))

    worker = get_csv_worker()

    # One alert row
    append_alert("2026-02-18 10:00:00", "PUMP_01", "CRITICAL", 0.95, "OK")
    # One telemetry row
    fieldnames = ["timestamp", "risk_score", "status"] + Config.FEATURE_NAMES
    row = {
        "timestamp": "2026-02-18 10:00:00",
        "risk_score": 0.5,
        "status": "HEALTHY",
        **{name: 0.0 for name in Config.FEATURE_NAMES},
    }
    append_telemetry(fieldnames, row)

    # Wait until queue is drained
    worker._q.join()
    worker.stop()

    alerts_path = Path(Config.ALERTS_LOG_PATH)
    telemetry_path = Path(Config.TELEMETRY_LOG_PATH)
    assert alerts_path.is_file()
    assert telemetry_path.is_file()

    alerts_lines = alerts_path.read_text(encoding="utf-8").strip().splitlines()
    telemetry_lines = telemetry_path.read_text(encoding="utf-8").strip().splitlines()
    # header + one row
    assert len(alerts_lines) == 2
    assert len(telemetry_lines) == 2
    assert alerts_lines[0].startswith(
        "timestamp,pump_id,status,anomaly_probability,sensor_status"
    )
    assert telemetry_lines[0].startswith("timestamp,risk_score,status,")


def test_healthcheck_ok_and_failure(monkeypatch, capsys):
    """healthcheck exits 0 on success and 1 on validation error."""
    import app.healthcheck as health

    # Success case
    with patch.object(health, "validate_config") as vconf, patch.object(
        health, "validate_artifacts"
    ) as vart, patch.object(health.sys, "exit") as sexit:
        health.check_health()
        vconf.assert_called_once()
        vart.assert_called_once()
        sexit.assert_called_with(0)

    # Failure case
    with patch.object(health, "validate_config") as vconf, patch.object(
        health, "validate_artifacts"
    ) as vart, patch.object(health.sys, "exit") as sexit:
        from config.validation import ConfigValidationError

        vart.side_effect = ConfigValidationError("MODEL_PATH missing")
        health.check_health()
        captured = capsys.readouterr()
        assert "Healthcheck failed" in captured.out
        sexit.assert_called_with(1)
